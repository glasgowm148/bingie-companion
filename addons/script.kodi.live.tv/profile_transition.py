"""Profile changes cancel old work before Kodi takes its GUI/profile locks.

Only generation, process, profile paths and add-on IDs are stored. No media
URLs, account identifiers or credentials. File checks need no Kodi GUI lock.
"""
import json
import os
import threading
import time
import uuid

import xbmc
import xbmcvfs

ROOT = xbmcvfs.translatePath('special://masterprofile/addon_data/script.kodi.live.tv')
PROFILE = xbmcvfs.translatePath('special://profile/').rstrip('/\\')
STATE = os.path.join(ROOT, 'transition.json')
ADDONS = xbmcvfs.translatePath('special://home/addons').rstrip('/\\')



# Tag workers when they are created. Inspecting process-wide Python frame
# objects can cross Kodi sub-interpreter boundaries during service teardown.
_OWNER_KEY = '_kodi_profile_worker_owner'
threading.current_thread().__dict__[_OWNER_KEY] = uuid.uuid4().hex

def _install_thread_ownership():
    original = threading.Thread.start
    if getattr(original, '_kodi_profile_tracking', False):
        return
    current_thread = threading.current_thread
    def start(thread, *args, **kwargs):
        owner = current_thread().__dict__.get('_kodi_profile_worker_owner')
        if owner:
            thread.__dict__['_kodi_profile_worker_owner'] = owner
        return original(thread, *args, **kwargs)
    start._kodi_profile_tracking = True
    threading.Thread.start = start

_install_thread_ownership()

def read_state():
    try:
        with open(STATE, encoding='utf-8') as stream:
            value = json.load(stream)
        return value if value.get('pid') == os.getpid() else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + '.' + uuid.uuid4().hex + '.tmp'
    with open(temp, 'w', encoding='utf-8') as stream:
        json.dump(value, stream)
        stream.flush()
    os.replace(temp, path)


def begin(target):
    state = {'pid': os.getpid(), 'generation': uuid.uuid4().hex,
             'switching': True, 'outgoing': PROFILE, 'target': target}
    _write(STATE, state)
    return state['generation']


def settle():
    state = read_state()
    if state:
        state['switching'] = False
        _write(STATE, state)


class Lease:
    def __init__(self):
        self.profile = PROFILE
        self.generation = read_state().get('generation', '')

    def cancelled(self):
        state = read_state()
        return (state.get('generation', '') != self.generation or
                (state.get('switching') and state.get('outgoing') == self.profile))


class Monitor(xbmc.Monitor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lease = Lease()

    def abortRequested(self):
        return self.lease.cancelled() or super().abortRequested()

    def waitForAbort(self, timeout=-1):
        deadline = time.monotonic() + timeout if timeout > 0 else float("inf")
        while not self.abortRequested():
            left = deadline - time.monotonic()
            if left <= 0:
                return False
            if super().waitForAbort(min(.2, left)):
                return True
        return True


class Invocation(Lease):
    def __init__(self, addon):
        super().__init__()
        self.path = os.path.join(ROOT, 'jobs', str(os.getpid()), uuid.uuid4().hex + '.json')
        self.addon = addon

    def __enter__(self):
        self.thread = threading.current_thread()
        self.previous_owner = self.thread.__dict__.get(_OWNER_KEY)
        self.thread.__dict__[_OWNER_KEY] = self.path
        _write(self.path, {'profile': self.profile, 'addon': self.addon})
        return self

    def __exit__(self, *_):
        # The switch has its own bounded timeout and cancels safely. Keep this
        # invocation alive until its children finish so native interpreter
        # cleanup cannot join them under a GUI lock, or leave a stale ticket.
        while _owned_workers(self.addon):
            time.sleep(.05)
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        finally:
            if self.previous_owner:
                self.thread.__dict__[_OWNER_KEY] = self.previous_owner
            else:
                self.thread.__dict__.pop(_OWNER_KEY, None)


def pending_jobs():
    state = read_state()
    directory = os.path.join(ROOT, 'jobs', str(os.getpid()))
    jobs = []
    try:
        paths = os.listdir(directory)
    except FileNotFoundError:
        return jobs
    for name in paths:
        if not name.endswith('.json'):
            continue
        try:
            with open(os.path.join(directory, name), encoding='utf-8') as stream:
                job = json.load(stream)
            if job.get('profile') == state.get('outgoing'):
                jobs.append(job['addon'])
        except (OSError, ValueError, KeyError):
            continue
    return jobs


def _ack_path(addon):
    return os.path.join(ROOT, 'drained', read_state().get('generation', 'none'), addon + '.json')


def _owned_workers(addon):
    current = threading.current_thread()
    owner = current.__dict__.get(_OWNER_KEY)
    return [thread for thread in threading.enumerate()
            if thread is not current and thread.is_alive() and owner
            and thread.__dict__.get(_OWNER_KEY) == owner]


def drained(addon, timeout=10):
    _write(os.path.join(ROOT, 'drain-start-' + addon + '.json'), {'started': True})
    deadline = time.monotonic() + timeout
    while True:
        children = _owned_workers(addon)
        if not children:
            _write(_ack_path(addon), {'complete': True})
            return True
        if time.monotonic() >= deadline:
            _write(os.path.join(ROOT, 'drain-diagnostic.json'), {'addon': addon,
                   'workers': [t.name for t in children]})
            return False
        time.sleep(.05)


def is_drained(addon):
    return os.path.isfile(_ack_path(addon))
