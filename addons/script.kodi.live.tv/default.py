import sys, xbmc
mode = sys.argv[1] if len(sys.argv) > 1 else "back"
if mode not in ("switch-account", "profiles", "wait-profile-switch", "finish-profile-switch",
                "restart-current", "rebuild-navigation",
                "bbc", "refresh", "setup", "day", "guide", "home", "back"):
    raise SystemExit("Unknown navigation action")
if mode in ("switch-account", "profiles"):
    from profile_switch import switch
    switch(None)
    raise SystemExit
if mode == "wait-profile-switch":
    from profile_switch import prepare_home
    prepare_home()
    import xbmcgui
    # Window.setFocusId uses the GUI thread-message queue, which is dispatched
    # on the next frame after the native application-message stack unwinds.
    window = xbmcgui.Window(10000)
    if window.getProperty("KodiNavigation.SwitchTarget"):
        window.setFocusId(94871)
    raise SystemExit
if mode == "finish-profile-switch":
    from profile_switch import finish_switch
    finish_switch()
    raise SystemExit
if mode == "restart-current":
    # Fresh start into the profile already loaded (Kodi Manager's idle memory refresh). Only the
    # account switch's guarded relaunch (settings saved first, helper acknowledged) is used, so this
    # does nothing on builds that do not need it, during playback or while a switch is under way.
    import xbmcgui
    from profile_restart import required
    from profile_switch import restart_with_drain as restart
    current = xbmc.getInfoLabel("System.ProfileName")
    expected = sys.argv[2] if len(sys.argv) > 2 else current
    if (current and expected == current and required() and not xbmc.getCondVisibility("Player.HasMedia")
            and not xbmcgui.Window(10000).getProperty("KodiNavigation.ProfileSwitch")):
        xbmc.log("[Profile Switch] Restarting into the current profile " + current, xbmc.LOGINFO)
        restart(current)
    else:
        xbmc.log("[Profile Switch] Restart into the current profile skipped", xbmc.LOGINFO)
    raise SystemExit
if mode == "rebuild-navigation":
    import xbmcgui
    xbmcgui.Window(10000).setProperty('skinshortcuts-reloadmainmenu','True')
    xbmc.executebuiltin('RunScript(script.skinshortcuts,type=buildxml&mainmenuID=900&levels=1&group=mainmenu|powermenu|searchmenu|tmdbsearchmenu|moviehub|tvshowhub|newhub|musichub|customhub|somethinghub|mylisthub)')
    raise SystemExit
if mode == "bbc":
    xbmc.executebuiltin("ActivateWindow(1120,return)")
    raise SystemExit
if mode == "refresh":
    xbmc.executebuiltin("ReloadSkin()")
    raise SystemExit
if mode == "setup":
    for action in ["Skin.SetString(GuideRows,8)", "Skin.SetString(PVRGuideItemColorFocus,FF0066FF)", "Skin.SetString(PVRGuideItemTextColorFocus,FFFFFFFF)", "Skin.SetString(PVRGuideItemTextColorUnfocus,FFE8ECF4)", "Skin.SetString(PVRGuideItemColorUnfocus,FF242830)", "Skin.SetBool(View10_DisableFanArt)", "Skin.SetBool(TVGuideChannelLogo)", "Skin.SetBool(GuideShowInfo)"]:
        xbmc.executebuiltin(action)
    raise SystemExit
if mode == "day":
    import datetime, glob, os, sqlite3, xbmcgui, xbmcvfs
    now = datetime.datetime.now()
    last_day = now.date() + datetime.timedelta(days=2)
    try:
        databases = glob.glob(os.path.join(xbmcvfs.translatePath("special://database/"), "Epg*.db"))
        database = max(databases, key=lambda p: int(os.path.basename(p)[3:-3]))
        with sqlite3.connect("file:" + database + "?mode=ro", uri=True, timeout=0.2) as db:
            end_time = db.execute("SELECT MAX(iEndTime) FROM epgtags").fetchone()[0]
        db.close()
        if end_time:
            last_day = datetime.datetime.fromtimestamp(end_time - 1).date()
    except (OSError, ValueError, sqlite3.Error, TypeError):
        pass
    future = max(0, min(7, (last_day - now.date()).days))
    offsets = list(range(0, future + 1))
    labels = []
    for offset in offsets:
        date = now + datetime.timedelta(days=offset)
        prefix = "Today • " if offset == 0 else "Tomorrow • " if offset == 1 else ""
        labels.append(prefix + date.strftime("%A %d %B"))
    choice = xbmcgui.Dialog().select("Choose a day", labels)
    if choice >= 0:
        # "+N" moves N hours from the guide's selected time, not from now: go to now first.
        xbmc.executebuiltin("PVR.EpgGridControl(currentprogramme)")
        if offsets[choice]:
            xbmc.executebuiltin("PVR.EpgGridControl(+" + str(offsets[choice] * 24) + ")")
        xbmc.executebuiltin("SetFocus(10)")
    raise SystemExit
def wait_live_transport():
    # Public installations use Kodi/PVR directly. Household relay readiness stays in its private
    # helper; this package never reads playlists, provider URLs or transport credentials.
    return True


if mode == "guide":
    if not wait_live_transport():
        import xbmcgui
        xbmcgui.Dialog().ok('Live TV is still starting', 'Please try again in a moment.')
        raise SystemExit
    xbmc.executebuiltin("ActivateWindow(tvguide,return)")
    raise SystemExit
player = xbmc.Player()
live = xbmc.getCondVisibility("PVR.IsPlayingTV") or xbmc.getCondVisibility("PVR.IsPlayingRadio")
if not live and player.isPlaying():
    try:
        live = player.getPlayingFile().startswith("pvr://")
    except RuntimeError:
        pass
if live:
    player.stop()
    monitor = xbmc.Monitor()
    for _ in range(100):
        if not player.isPlaying() or monitor.waitForAbort(0.1):
            break
    xbmc.executebuiltin("Dialog.Close(videoosd,true)")
    xbmc.executebuiltin("ActivateWindow(home)" if mode == "home" else "ActivateWindow(tvguide,return)")
elif mode == "home":
    xbmc.executebuiltin("ActivateWindow(home)")
else:
    # Preserve the usual Back action for movies and episodes.
    xbmc.executebuiltin("Action(Back)")
