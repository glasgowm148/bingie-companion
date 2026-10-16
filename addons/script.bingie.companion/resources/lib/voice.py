"""Explicit Android voice action; never changes microphone permissions or the assistant role."""
import json
import re

PACKAGE = re.compile(r'^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$')


def run(mode, xbmc, addon, dialog, window):
    android = xbmc.getCondVisibility('System.Platform.Android')
    package = addon.getSetting('voice_package')
    enabled = addon.getSetting('voice_enabled') == 'true'
    valid = bool(PACKAGE.fullmatch(package or ''))
    status = 'Voice helper enabled' if android and enabled and valid else 'Set up voice search'
    window.setProperty('Bingie.VoiceStatus', status)
    if mode == 'voice-status':
        return
    if mode == 'voice-setup' or not enabled or not valid:
        dialog.ok('Voice search setup', 'Install the separate Android voice helper, configure its '
                  'Kodi Manager token on the TV, and allow its microphone. Enable it in Companion '
                  'settings. The remote mic also needs the TV assistant-role setting. '
                  'Speech uses your Android recognition provider; it may send audio to its service.')
        if android and valid and package == 'io.github.glasgowm148.kodivoice' and dialog.yesno(
                'Voice search setup', 'Open the Android helper setup? Choose No to edit Companion settings.'):
            xbmc.executebuiltin('StartAndroidActivity(%s,%s)' %
                                (json.dumps(package), json.dumps('android.intent.action.MAIN')))
        else:
            addon.openSettings()
        return
    if not android:
        dialog.ok('Voice search', 'This voice helper requires Android. Typed search remains available.')
        return
    if xbmc.getCondVisibility('Player.HasMedia'):
        dialog.ok('Voice search', 'Stop playback before starting a voice search.')
        return
    # A separate explicit action works without replacing the system assistant. The remote mic's
    # assistant role is optional and always configured by the owner, outside the skin.
    xbmc.executebuiltin('StartAndroidActivity(%s,%s)' %
                        (json.dumps(package), json.dumps(package + '.LISTEN')))
