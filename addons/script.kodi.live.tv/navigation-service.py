"""Restore the destination profile and check its menus once after switching."""
import xbmc
from profile_switch import restore_remote_control
try:
    switching = xbmc.getCondVisibility('System.HasAlarm(KodiNavigationSwitch)')
    restore_remote_control()
    if switching:
        xbmc.executebuiltin('CancelAlarm(KodiNavigationSwitch,silent)')
    # Both accounts are already present in the generated menu XML. Home skips
    # rebuilding while Kodi passes through its temporary master/login profile.
    # Check for genuine edits once the destination profile is fully initialized.
    if switching and xbmc.getCondVisibility('Window.IsActive(home)'):
        xbmc.executebuiltin('RunScript(script.skinshortcuts,type=buildxml&mainmenuID=900&levels=1&group=mainmenu|powermenu|searchmenu|tmdbsearchmenu|moviehub|tvshowhub|newhub|musichub|customhub|somethinghub|mylisthub)')
except Exception as error:
    xbmc.log('[Profile Switch] Remote-control restore deferred: ' + type(error).__name__, xbmc.LOGERROR)
