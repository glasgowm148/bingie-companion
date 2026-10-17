"""Shield/Kodi 22 beta2/RC1: switch accounts via normal full shutdown, not PVR unload."""
import json
import re
import os
import subprocess
import time
import xml.etree.ElementTree as ET
import xbmc
import xbmcgui
import xbmcvfs


def required():
    return (xbmc.getCondVisibility('System.Platform.Android')
            and re.match(r'^22\.0-(?:BETA2|RC1)(?:\b|$)', xbmc.getInfoLabel('System.BuildVersion')) is not None)


def target_index(path, target):
    tree = ET.parse(path)
    names = [node.findtext('name') for node in tree.getroot().findall('profile')]
    if len(names) != 2 or target not in names:
        raise ValueError('Switch Account requires a known destination in two profiles')
    destination = tree.getroot().findall('profile')[names.index(target)]
    if destination.findtext('lockmode', '0') != '0' or destination.findtext('lockcode', '-') not in ('', '-'):
        raise ValueError('Locked profiles require Kodi authentication; direct relaunch refused')
    if tree.getroot().find('lastloaded') is None:
        raise ValueError('Missing startup profile setting')
    return names.index(target)


def preflight(target):
    """Cheap, read-only checks that refuse a relaunch before any service is asked to stop."""
    profiles = xbmcvfs.translatePath('special://masterprofile/profiles.xml')
    index = target_index(profiles, target)
    folder = xbmcvfs.translatePath('special://masterprofile/addon_data/script.kodi.live.tv')
    token = os.path.join(folder, 'profile-handoff-token')
    if not os.path.isfile(token):
        raise RuntimeError('Account switch launcher has not been configured')
    resources = os.path.join(os.path.dirname(__file__), 'profile_restart')
    script, dex = os.path.join(resources, 'relaunch.sh'), os.path.join(resources, 'classes.dex')
    if not os.path.isfile(script) or not os.path.isfile(dex):
        raise RuntimeError('Profile relaunch helper is missing')
    return {'profiles': profiles, 'index': index, 'folder': folder, 'token': token,
            'script': script, 'dex': dex}


def restart(target):
    checked = preflight(target)
    profiles, index, folder = checked['profiles'], checked['index'], checked['folder']
    token, script, dex = checked['token'], checked['script'], checked['dex']
    os.makedirs(folder, exist_ok=True)
    result = os.path.join(folder, 'profile-restart-result.json')
    if os.path.isfile(result): os.unlink(result)
    window = xbmcgui.Window(10000)
    window.setProperty('KodiNavigation.ProfileSwitch', str(time.time()))
    window.setProperty('KodiNavigation.SwitchTarget', target)
    window.setProperty('KodiNavigation.SwitchStage', 'Saving and switching to ' + target + '…')
    log = xbmcvfs.translatePath('special://logpath/kodi.log')
    offset = os.path.getsize(log)
    child = None
    try:
        with open(result + '.stderr', 'wb') as error:
            child = subprocess.Popen(['/system/bin/sh', script, str(os.getpid()), str(index),
                                      profiles, result, dex, log, str(offset), token], stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=error,
                                     start_new_session=True, close_fds=True)
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            if child.poll() is not None:
                try:
                    with open(result + '.launch.log', encoding='utf-8') as stream:
                        denied = 'relaunch_helper_unavailable' in stream.read(4096)
                except OSError: denied = False
                if denied:
                    raise RuntimeError("Account switch launcher is unavailable, outdated, or its relaunch permission is disabled")
                raise RuntimeError('Profile relaunch helper stopped before shutdown')
            try:
                with open(result, encoding='utf-8') as stream: state = json.load(stream)
                if (state.get('phase') == 'waiting_saved' and state.get('pid') == os.getpid()
                        and state.get('index') == index):
                    xbmc.log('[Profile Switch] Controlled restart to ' + target, xbmc.LOGINFO)
                    # Full Stop saves current settings and waits for the native
                    # job manager before destroying queues. Do not disable PVR,
                    # stop interpreters, or pause network listeners individually.
                    xbmc.executebuiltin('Quit')
                    return
            except (OSError, ValueError): pass
            xbmc.sleep(50)
        raise RuntimeError('Profile relaunch helper did not acknowledge startup')
    except Exception:
        if child and child.poll() is None:
            child.terminate()
        for name in ('KodiNavigation.ProfileSwitch', 'KodiNavigation.SwitchTarget',
                     'KodiNavigation.SwitchStage'):
            window.clearProperty(name)
        raise
