"""Drain services and settle native Live TV before changing Kodi profiles.

The journal restores each profile's remote-control preferences after login,
including recovery if power is lost during a switch. No credentials are stored.
"""
import json
import os
import re
import time
import xml.etree.ElementTree as ET

import xbmc
import profile_transition as transition
import xbmcgui
import xbmcvfs
from profile_restart import required as restart_required, restart as restart_profile

PROPERTY = 'KodiNavigation.ProfileSwitch'
SETTINGS = {'services.webserver': xbmc.SERVER_WEBSERVER,
            'services.esenabled': xbmc.SERVER_JSONRPCSERVER}


def rpc(method, params):
    reply = json.loads(xbmc.executeJSONRPC(json.dumps({
        'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})))
    if 'error' in reply:
        raise RuntimeError('Kodi request failed: ' + method)
    return reply['result']


def journal_path(profile=None):
    if profile:
        return os.path.join(profile, 'addon_data/script.kodi.live.tv/profile-switch.json')
    return xbmcvfs.translatePath('special://profile/addon_data/script.kodi.live.tv/profile-switch.json')


def pvr_journal_path():
    return xbmcvfs.translatePath('special://masterprofile/addon_data/script.kodi.live.tv/pvr-switch.json')


def restore_pvr(cancelled=False):
    path = pvr_journal_path()
    if not os.path.isfile(path): return True
    with open(path, encoding='utf-8') as stream: saved = json.load(stream)
    if saved.get('enabled') is not True: raise ValueError('Invalid PVR switch journal')
    if not cancelled and saved.get('pid') == os.getpid() and saved.get('target') != xbmc.getInfoLabel('System.ProfileName') and time.time() - saved.get('created', 0) < 120:
        return False
    rpc('Addons.SetAddonEnabled', {'addonid': 'pvr.iptvsimple', 'enabled': True})
    os.unlink(path)
    xbmc.log('[Profile Switch] Destination Live TV restored', xbmc.LOGINFO)
    return True


PVR_STARTED = b'PVR Manager: Started'
PVR_CHANGING = (b'PVR Manager: Starting\n', b'PVR Manager: Stopping', b'PVR Manager: Stopped', b'PVR Manager: Start aborted')
LOG_CHUNK, LOG_SCAN_LIMIT = 262144, 16 * 1024 * 1024


def pvr_manager_started(data):
    """True/False when the last PVR Manager state line in ``data`` is Started/another; None if none."""
    started = data.rfind(PVR_STARTED)
    changing = max(data.rfind(marker) for marker in PVR_CHANGING)
    if started < 0 and changing < 0: return None
    return started > changing


def last_pvr_manager_state(stream, size):
    """Latest PVR Manager state in kodi.log, read backwards in chunks (bounded): after a day of
    Live TV the Started line is far behind the log's end."""
    end = size
    while end > 0 and size - end < LOG_SCAN_LIMIT:
        start = max(0, end - LOG_CHUNK)
        stream.seek(start)
        found = pvr_manager_started(stream.read(end - start + 64))  # overlap: markers across chunk edges
        if found is not None: return found
        end = start
    return None


def quiesce_pvr(target):
    details = rpc('Addons.GetAddonDetails', {'addonid': 'pvr.iptvsimple', 'properties': ['enabled']})['addon']
    if not details['enabled']: return
    log = xbmcvfs.translatePath('special://logpath/kodi.log')
    # An enabled addon may still be creating its native client on a worker.
    # Disabling during Starting aborts creation while GUIInfo still owns groups.
    deadline = time.monotonic() + 30
    started, scanned = None, 0
    while time.monotonic() < deadline:
        with open(log, 'rb') as stream:
            size = os.fstat(stream.fileno()).st_size
            if size < scanned: started, scanned = None, 0  # log restarted
            if scanned:
                # Only what Kodi logged since the last look (plus a marker's width of overlap).
                stream.seek(max(0, scanned - 64))
                latest = pvr_manager_started(stream.read(size - stream.tell()))
                if latest is not None: started = latest
            else:
                started = last_pvr_manager_state(stream, size)
            scanned = size
        if started:
            break
        xbmc.sleep(100)
    else:
        raise RuntimeError('Live TV is still starting; account switch safely cancelled')
    offset = os.path.getsize(log)
    path = pvr_journal_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + '.tmp', 'w', encoding='utf-8') as stream:
        json.dump({'enabled': True, 'pid': os.getpid(), 'target': target, 'created': time.time()}, stream)
        stream.flush(); os.fsync(stream.fileno())
    os.replace(path + '.tmp', path)
    rpc('Addons.SetAddonEnabled', {'addonid': 'pvr.iptvsimple', 'enabled': False})
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        with open(log, 'rb') as stream:
            size = os.fstat(stream.fileno()).st_size
            stream.seek(max(offset if size >= offset else 0, size - 65536))
            stopped = b'PVR Manager: Stopped' in stream.read(65536)
        if stopped:
            # Leave the GUI and native workers running for a further frame/settle period.
            xbmc.sleep(500)
            xbmc.log('[Profile Switch] Live TV shutdown barrier complete', xbmc.LOGINFO)
            return
        xbmc.sleep(100)
    raise RuntimeError('Live TV shutdown not confirmed; account switch cancelled')


def restore_remote_control(cancelled=False):
    if not restore_pvr(cancelled): return False
    state = transition.read_state()
    outgoing = state.get('outgoing')
    current = xbmcvfs.translatePath('special://profile/').rstrip('/\\')
    if outgoing and outgoing != current:
        previous = journal_path(outgoing)
        if os.path.isfile(previous):
            with open(previous, encoding='utf-8') as stream:
                saved = json.load(stream)['settings']
            if any(type(saved.get(key)) is not bool for key in SETTINGS):
                raise ValueError('Invalid saved remote-control preference')
            # Profile loading saves the outgoing settings again. Restore that file only
            # after the destination has loaded, so returning needs no popup.
            save_remote_preferences(saved, outgoing)
            os.unlink(previous)
    path = journal_path()
    if os.path.isfile(path):
        with open(path, encoding='utf-8') as stream:
            settings = json.load(stream)['settings']
        for setting, server in SETTINGS.items():
            value = settings.get(setting)
            if type(value) is not bool:
                raise ValueError('Invalid saved remote-control preference')
            current = rpc('Settings.GetSettingValue', {'setting': setting})['value']
            if current != value and not xbmc.startServer(server, value):
                raise RuntimeError('Could not restore ' + setting)
        os.unlink(path)
        xbmc.log('[Profile Switch] Remote-control preferences restored', xbmc.LOGINFO)
    window = xbmcgui.Window(10000)
    for aid in window.getProperty('KodiNavigation.ServiceIds').split(','):
        if aid:
            window.clearProperty('KodiNavigation.Service.' + aid)
    window.clearProperty('TMDbBingieHelper.ServiceStop')
    window.clearProperty('KodiNavigation.ServiceIds')
    window.clearProperty('KodiNavigation.SwitchTarget')
    window.clearProperty('KodiNavigation.SwitchStage')
    window.clearProperty(PROPERTY)
    transition.settle()
    return True


def service_paths():
    addons = rpc('Addons.GetAddons', {
        'type': 'xbmc.service', 'enabled': True, 'properties': ['path']})['addons']
    paths = []
    for addon in addons:
        if addon['addonid'] == 'script.kodi.live.tv':
            continue
        directory = xbmcvfs.translatePath(addon['path'])
        root = ET.parse(os.path.join(directory, 'addon.xml')).getroot()
        for extension in root.findall('extension'):
            library = extension.get('library', '')
            if extension.get('point') == 'xbmc.service' and library.endswith('.py'):
                paths.append(os.path.join(directory, library))
    # Give the metadata helper time to honour ServiceStop while other services exit.
    return sorted(paths, key=lambda path: 'plugin.video.tmdb.bingie.helper' in path)


def save_remote_preferences(settings, profile=None):
    # Restore the saved preferences for the NEXT profile load, without
    # restarting listeners while the outgoing profile is being dismantled.
    path = os.path.join(profile, 'guisettings.xml') if profile else xbmcvfs.translatePath('special://profile/guisettings.xml')
    tree = ET.parse(path)
    for setting, value in settings.items():
        node = tree.find("./setting[@id='%s']" % setting)
        if node is None:
            raise ValueError('Missing remote-control preference')
        node.text = 'true' if value else 'false'
        node.attrib.pop('default', None)
    temp = path + '.profile-switch.tmp'
    with open(temp, 'wb') as stream:
        tree.write(stream, encoding='utf-8', xml_declaration=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def _target(target):
    profiles = ET.parse(xbmcvfs.translatePath('special://masterprofile/profiles.xml')).getroot()
    names = [p.findtext('name') for p in profiles.findall('profile')]
    current = xbmc.getInfoLabel('System.ProfileName')
    if target is None:
        if len(names) != 2 or current not in names:
            raise ValueError('Switch Account requires exactly two profiles')
        target = next(name for name in names if name != current)
    if target not in names or any(c in target for c in '\"(),\r\n'):
        raise ValueError('Unknown profile')
    return None if target == current else target


def prepare_home():
    # The GUI focus handoff lives in Home.xml. Sending it while another hub is
    # active silently drops the event after network listeners have been stopped.
    xbmc.executebuiltin('Dialog.Close(all,true)')
    xbmc.executebuiltin('ActivateWindow(home)')
    for _ in range(100):
        if xbmcgui.getCurrentWindowId() == 10000:
            return
        xbmc.sleep(50)
    raise RuntimeError('Could not return Home; account switch cancelled')


def finish_switch():
    build = re.match(r'^(\d+)\.', xbmc.getInfoLabel('System.BuildVersion'))
    if not build or int(build.group(1)) >= 22:
        raise RuntimeError('Native profile loading is not reviewed on this Kodi build')
    # A GUI focus message acknowledges the next frame after StopScript returns.
    # Kodi pumps application messages recursively inside StopScript, so queuing
    # Profile loading directly after it would still run inside service shutdown.
    window = xbmcgui.Window(10000)
    target = _target(window.getProperty('KodiNavigation.SwitchTarget'))
    if not target:
        raise ValueError('Missing switch target')
    with open(journal_path(), encoding='utf-8') as stream:
        settings = json.load(stream)['settings']
    save_remote_preferences(settings)
    xbmc.log('[Profile Switch] Service cleanup complete; loading ' + target, xbmc.LOGINFO)
    # PVR has already stopped while the GUI was responsive. Avoid LogOff's
    # temporary master-profile load and its duplicate service/PVR startup.
    xbmc.executebuiltin('LoadProfile("%s",prompt)' % target)


def restart_with_drain(target):
    """Cancel cooperative Python work while the GUI still runs, then perform full Stop."""
    paths = service_paths()
    participants = ('service.kodi.addonadmin', 'service.subtitles.a4ksubtitles',
                    'script.xbmcbackup', 'plugin.video.tmdb.bingie.helper', 'plugin.video.pov')
    required = [aid for aid in participants if any('/' + aid + '/' in path for path in paths)]
    window = xbmcgui.Window(10000)
    if xbmcgui.getCurrentWindowId() != 10000:
        prepare_home()
    window.setProperty(PROPERTY, str(time.time()))
    window.setProperty('KodiNavigation.SwitchTarget', target)
    window.setProperty('KodiNavigation.SwitchStage', 'Finishing background tasks...')
    transition.begin(target)
    window.clearProperty('TMDbBingieHelper.ServiceDrained')
    window.setProperty('TMDbBingieHelper.ServiceStop', 'True')
    try:
        deadline, quiet_since = time.monotonic() + 20, None
        while time.monotonic() < deadline:
            ready = not transition.pending_jobs() and all(transition.is_drained(aid) for aid in required)
            if ready:
                quiet_since = quiet_since or time.monotonic()
                if time.monotonic() - quiet_since >= .3:
                    break
            else:
                quiet_since = None
            xbmc.sleep(50)
        else:
            raise RuntimeError('Pending tasks have not finished; account switch safely cancelled')
        xbmc.log('[Profile Switch] Cooperative background drain complete before restart', xbmc.LOGINFO)
        restart_profile(target)
    except Exception:
        completed = [path for path in paths if any(transition.is_drained(aid) and '/' + aid + '/' in path
                                                    for aid in participants)]
        # Recovery must reach every drained add-on: one failed call must not leave the
        # rest stopped (or an add-on disabled, which Kodi keeps across restarts).
        try:
            restore_remote_control(cancelled=True)
        except Exception as error:
            xbmc.log('[Profile Switch] Restoring remote control failed: %s' % error, xbmc.LOGERROR)
        # Enabling through Kodi's add-on manager supplies the original add-on
        # context; RunScript(library_path) loses it for multi-extension add-ons.
        for aid in participants:
            if aid in required or any('/' + aid + '/' in path for path in completed):
                for enabled in (False, True):
                    try:
                        rpc('Addons.SetAddonEnabled', {'addonid': aid, 'enabled': enabled})
                    except Exception as error:
                        xbmc.log('[Profile Switch] Restarting %s failed: %s' % (aid, error), xbmc.LOGERROR)
        raise


def switch(target=None):
    build = xbmc.getInfoLabel('System.BuildVersion')
    major = re.match(r'^(\d+)\.', build)
    if not major or int(major.group(1)) >= 22 and not restart_required():
        raise RuntimeError('Profile switching is not reviewed on this Kodi build')
    if xbmc.getCondVisibility('Player.HasMedia'):
        raise RuntimeError('Stop playback before switching profiles')
    window = xbmcgui.Window(10000)
    if window.getProperty(PROPERTY):
        return
    target = _target(target)
    if not target:
        return
    if restart_required():
        restart_with_drain(target)
        return
    paths = service_paths()
    path = journal_path()
    if os.path.isfile(path):
        restore_remote_control()
    settings = {key: rpc('Settings.GetSettingValue', {'setting': key})['value']
                for key in SETTINGS}
    window.setProperty(PROPERTY, str(time.time()))
    window.setProperty('KodiNavigation.SwitchTarget', target)
    transition.begin(target)
    window.setProperty('KodiNavigation.SwitchStage', 'Finishing playback…')
    try:
        xbmc.PlayList(xbmc.PLAYLIST_VIDEO).clear()
        player = xbmc.Player()
        if player.isPlaying():
            player.stop()
            for _ in range(50):
                if not player.isPlaying():
                    break
                xbmc.sleep(100)
            else:
                raise RuntimeError('Playback has not stopped')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + '.tmp', 'w', encoding='utf-8') as stream:
            json.dump({'version': 1, 'settings': settings}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(path + '.tmp', path)
        # Alarm state survives Kodi resetting Home during profile loading.
        xbmc.executebuiltin('AlarmClock(KodiNavigationSwitch,noop,2,silent)')
        window.setProperty('KodiNavigation.SwitchStage', 'Saving and finishing background tasks…')
        window.clearProperty('TMDbBingieHelper.ServiceDrained')
        window.setProperty('TMDbBingieHelper.ServiceStop', 'True')
        # Native StopScript holds GUI locks. Let the helper release its Player
        # callbacks while the GUI can still process them, then stop interpreters.
        if any('plugin.video.tmdb.bingie.helper' in service for service in paths):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if window.getProperty('TMDbBingieHelper.ServiceDrained') == 'True':
                    break
                xbmc.sleep(50)

        xbmc.log('[Profile Switch] Direct switch to %s; draining %s services and pending playback' % (target, len(paths)), xbmc.LOGINFO)
        required = [aid for aid in ('service.kodi.addonadmin', 'service.subtitles.a4ksubtitles',
                    'script.xbmcbackup', 'plugin.video.tmdb.bingie.helper', 'plugin.video.pov')
                    if any('/' + aid + '/' in service for service in paths)]
        deadline = time.monotonic() + 20
        quiet_since = None
        while time.monotonic() < deadline:
            ready = not transition.pending_jobs() and all(transition.is_drained(aid) for aid in required)
            if ready:
                quiet_since = quiet_since or time.monotonic()
                if time.monotonic() - quiet_since >= .3:
                    break
            else:
                quiet_since = None
            xbmc.sleep(50)
        else:
            raise RuntimeError('Pending tasks have not finished; account switch safely cancelled')
        if player.isPlaying():
            player.stop()
            for _ in range(50):
                if not player.isPlaying(): break
                xbmc.sleep(100)
            else: raise RuntimeError('Late playback has not stopped')
        window.setProperty('KodiNavigation.SwitchStage', 'Preparing Live TV…')
        quiesce_pvr(target)
        window.setProperty('KodiNavigation.SwitchStage', 'Loading your account…')
        for setting, server in SETTINGS.items():
            if settings[setting] and not xbmc.startServer(server, False):
                raise RuntimeError('Could not pause ' + setting)
        for service in paths:
            # Keep stops outside GUI window initialization and release Python's
            # GIL. Synchronous Python builtins or window onload stops can deadlock.
            aid = next((part for part in service.replace('\\', '/').split('/')
                        if part.startswith(('plugin.', 'service.', 'script.'))), 'unknown')
            xbmc.log('[Profile Switch] Stop request entering: ' + aid, xbmc.LOGINFO)
            xbmc.executebuiltin('StopScript("%s")' % service)
            # Returning acknowledges the request, not native callback completion.
            xbmc.log('[Profile Switch] Stop request returned: ' + aid, xbmc.LOGINFO)
        xbmc.executebuiltin('RunScript(script.kodi.live.tv,wait-profile-switch)')
    except Exception:
        xbmc.executebuiltin('CancelAlarm(KodiNavigationSwitch,silent)')
        completed = [service for service in paths if any(transition.is_drained(aid) and '/' + aid + '/' in service for aid in ('service.kodi.addonadmin', 'service.subtitles.a4ksubtitles', 'script.xbmcbackup', 'plugin.video.tmdb.bingie.helper', 'plugin.video.pov'))]
        restore_remote_control(cancelled=True)
        for service in completed:
            xbmc.executebuiltin('RunScript("%s")' % service)
        raise
