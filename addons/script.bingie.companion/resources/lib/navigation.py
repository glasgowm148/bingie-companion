"""Guide/day navigation extracted from the private navigation helper, without its IPTV setup."""
import re
import time
from urllib.parse import unquote

from .common import rpc, skin_string

DEFAULT_FUTURE_DAYS, MAX_FUTURE_DAYS = 3, 7


def future_days(xbmc):
    """Days after today that Kodi's guide keeps (Settings → PVR → Guide → Future days to display)."""
    try:
        value = int(rpc(xbmc, 'Settings.GetSettingValue', setting='epg.futuredaystodisplay')['value'])
    except (RuntimeError, KeyError, TypeError, ValueError, AttributeError):
        value = DEFAULT_FUTURE_DAYS
    return max(0, min(MAX_FUTURE_DAYS, value))


def _local(now, days, clock=None):
    """Epoch seconds of local wall-clock ``clock`` (default: now's) ``days`` calendar days after now.

    time.mktime normalises the day overflow and resolves the UTC offset of that date, so a DST
    change in between is accounted for. (datetime.strptime is avoided: it fails in Kodi's Python
    sub-interpreters on 3.8-3.11.)
    """
    hour, minute, second = clock or now[3:6]
    return time.mktime((now.tm_year, now.tm_mon, now.tm_mday + days, hour, minute, second, 0, 0, -1))


def day_choices(xbmc, now=None):
    """[(label, hours)] for today and each future guide day; hours moves the guide from now to the
    same local wall-clock time on that day (23 or 25 across a DST change)."""
    now = time.localtime(time.time() if now is None else now)
    start = time.mktime(now)
    choices = []
    for days in range(future_days(xbmc) + 1):
        # Label from midday: it exists on every date, unlike times inside a DST gap.
        date = time.localtime(_local(now, days, (12, 0, 0)))
        prefix = 'Today • ' if days == 0 else 'Tomorrow • ' if days == 1 else ''
        choices.append((prefix + time.strftime('%A %d %B', date),
                        int(round((_local(now, days) - start) / 3600.0))))
    return choices


def choose_day(xbmc, dialog, now=None):
    # Kodi's guide clamps to available EPG data; offer only the days it is configured to keep.
    choices = day_choices(xbmc, now)
    choice = dialog.select('Choose a day', [label for label, _ in choices])
    if choice < 0 or choice >= len(choices):
        return
    # "+N" moves N hours from the guide's selected time, not from now: go to now first.
    xbmc.executebuiltin('PVR.EpgGridControl(currentprogramme)')
    hours = choices[choice][1]
    if choice and hours > 0:
        xbmc.executebuiltin('PVR.EpgGridControl(+%d)' % hours)
    xbmc.executebuiltin('SetFocus(10)')


def configure_rows(xbmc, dialog, vfs=None):
    """Use actual Kodi directory paths; never derive a path from a group label or guess its ID."""
    # JSON-RPC's RemoteAccessAllowed rejects pvr:// even inside an add-on. Local VFS gives
    # the actual encoded directory names (including client IDs), without inventing paths.
    if vfs is None:
        import xbmcvfs as vfs
    directories, _ = vfs.listdir('pvr://channels/tv/')
    rows = [{'file': 'pvr://channels/tv/' + name + '/',
             'label': unquote(name.rsplit('@', 1)[0])}
            for name in directories if isinstance(name, str) and name
            and not any(c in name for c in '/\\')
            and not any(c in unquote(name) for c in '*\r\n')
            and unquote(name) not in ('.', '..')]
    if not rows:
        dialog.ok('Channel rows', 'No channel groups were returned by Kodi. Configure your PVR client first.')
        return
    pending = []
    for index in range(1, 4):
        selected = dialog.select('Channel row %d' % index, ['Hide this row', 'Keep existing row']
                                 + [r.get('label', 'Channel group') for r in rows])
        if selected < 0:
            return
        if selected == 1:
            continue
        row = rows[selected - 2] if selected >= 2 else {'file': '', 'label': ''}
        pending.append((index, row))
    for index, row in pending:
        skin_string(xbmc, 'KM_PVRRow%dPath' % index, row['file'])
        skin_string(xbmc, 'KM_PVRRow%dLabel' % index, row.get('label', 'Channel group'))
    xbmc.executebuiltin('Skin.SetBool(KM_CustomPVRRows)')


def profiles(xbmc, dialog):
    if xbmc.getCondVisibility('Player.HasMedia'):
        dialog.ok('Profiles', 'Stop playback before switching profiles.')
        return
    if xbmc.getCondVisibility('System.AddonIsEnabled(script.kodi.live.tv)'):
        # Preserve the existing opt-in coordinator, including its version-gated Android relaunch.
        xbmc.executebuiltin('RunScript(script.kodi.live.tv,switch-account)')
        return
    version = xbmc.getInfoLabel('System.BuildVersion')
    major = re.match(r'^(\d+)\.', version)
    if not major or int(major.group(1)) >= 22:
        dialog.ok('Profiles', 'Direct switching is unavailable on this Kodi build without a compatible '
                  'relaunch coordinator. The switch was cancelled; your profile is unchanged.')
        return
    # Keep Kodi's own login screen and password prompts on reviewed stable versions.
    xbmc.executebuiltin('System.LogOff')


def dispatch(mode):
    import xbmc
    import xbmcaddon
    import xbmcgui
    dialog = xbmcgui.Dialog()
    if mode in ('voice', 'voice-setup', 'voice-status'):
        from .voice import run
        return run(mode, xbmc, xbmcaddon.Addon(), dialog, xbmcgui.Window(10000))
    if mode == 'day':
        return choose_day(xbmc, dialog)
    if mode == 'configure-pvr':
        return configure_rows(xbmc, dialog)
    if mode in ('profiles', 'switch-account'):
        return profiles(xbmc, dialog)
    if mode == 'settings':
        return xbmcaddon.Addon().openSettings()
    if mode not in ('home', 'back', 'guide'):
        raise ValueError('Unknown companion action')
    player = xbmc.Player()
    live = xbmc.getCondVisibility('PVR.IsPlayingTV') or xbmc.getCondVisibility('PVR.IsPlayingRadio')
    if mode in ('home', 'back') and live:
        player.stop()
        monitor = xbmc.Monitor()
        for _ in range(100):
            if not player.isPlaying():
                break
            if monitor.waitForAbort(.1):
                return
        else:
            dialog.ok('Live TV', 'Playback has not stopped; navigation was cancelled.')
            return
        xbmc.executebuiltin('Dialog.Close(videoosd,true)')
        xbmc.executebuiltin('ActivateWindow(home)' if mode == 'home' else 'ActivateWindow(tvguide,return)')
    elif mode == 'home':
        xbmc.executebuiltin('ActivateWindow(home)')
    elif mode == 'guide':
        xbmc.executebuiltin('ActivateWindow(tvguide,return)')
    else:
        xbmc.executebuiltin('Action(Back)')
