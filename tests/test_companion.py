import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'addons/script.bingie.companion'))
from resources.lib import navigation, voice, continuing


class Kodi:
    def __init__(self, conditions=(), version='21.3', replies=None):
        self.conditions, self.version = set(conditions), version
        self.calls, self.actions = [], []
        self.replies = replies or {}

    def getCondVisibility(self, condition):
        return condition in self.conditions

    def getInfoLabel(self, label):
        return self.version if label == 'System.BuildVersion' else ''

    def executebuiltin(self, action):
        self.actions.append(action)

    def executeJSONRPC(self, raw):
        request = json.loads(raw)
        self.calls.append(request)
        reply = self.replies.get(request['params'].get('directory'), {'files': []})
        return json.dumps(reply if 'error' in reply else {'result': reply})


def addon(settings=None):
    values = {'voice_package': 'io.github.glasgowm148.kodivoice', 'voice_enabled': 'true'}
    values.update(settings or {})
    return types.SimpleNamespace(getSetting=lambda key: values.get(key, ''), openSettings=Mock())


class NavigationTests(unittest.TestCase):
    def test_profile_switch_refuses_playback_even_with_existing_coordinator(self):
        kodi = Kodi(['Player.HasMedia', 'System.AddonIsEnabled(script.kodi.live.tv)'])
        navigation.profiles(kodi, Mock())
        self.assertEqual(kodi.actions, [])

    def test_kodi22_and_unknown_versions_never_use_native_profile_loading(self):
        for version in ('22.0-RC1', '22.1', '', 'unknown'):
            kodi = Kodi(version=version)
            navigation.profiles(kodi, Mock())
            self.assertEqual(kodi.actions, [], version)

    def test_existing_coordinator_remains_in_charge_on_kodi22(self):
        kodi = Kodi(['System.AddonIsEnabled(script.kodi.live.tv)'], version='22.0-RC1')
        navigation.profiles(kodi, Mock())
        self.assertEqual(kodi.actions, ['RunScript(script.kodi.live.tv,switch-account)'])

    def test_kodi21_uses_its_native_login_screen(self):
        kodi = Kodi()
        navigation.profiles(kodi, Mock())
        self.assertEqual(kodi.actions, ['System.LogOff'])

    def test_day_navigation_starts_from_now_and_cancel_does_nothing(self):
        kodi = Kodi()
        dialog = Mock()
        dialog.select.return_value = 2
        navigation.choose_day(kodi, dialog)
        self.assertEqual(kodi.actions, ['PVR.EpgGridControl(currentprogramme)',
                                      'PVR.EpgGridControl(+48)', 'SetFocus(10)'])
        dialog.select.return_value = -1
        kodi.actions.clear()
        navigation.choose_day(kodi, dialog)
        self.assertEqual(kodi.actions, [])

    def test_cancelled_channel_wizard_preserves_all_existing_rows(self):
        kodi = Kodi(replies={'pvr://channels/tv/': {'files': [
            {'filetype': 'directory', 'label': 'Example group', 'file': 'pvr://channels/tv/Example@7/'}]}})
        dialog = Mock()
        dialog.select.side_effect = [2, -1]
        navigation.configure_rows(kodi, dialog)
        self.assertEqual(kodi.actions, [])

    def test_rows_use_returned_paths_and_ignore_unrestricted_wildcards(self):
        path = 'pvr://channels/tv/Example%20group@7/'
        kodi = Kodi(replies={'pvr://channels/tv/': {'files': [
            {'filetype': 'directory', 'label': 'All', 'file': 'pvr://channels/tv/*'},
            {'filetype': 'directory', 'label': 'Example group', 'file': path}]}})
        dialog = Mock()
        dialog.select.side_effect = [2, 0, 1]
        navigation.configure_rows(kodi, dialog)
        self.assertIn('Skin.SetString(KM_PVRRow1Path,"%s")' % path, kodi.actions)
        self.assertIn('Skin.SetString(KM_PVRRow2Path,"")', kodi.actions)
        self.assertFalse(any('KM_PVRRow3' in action for action in kodi.actions))


class VoiceTests(unittest.TestCase):
    def test_voice_uses_only_validated_package_and_explicit_listen_action(self):
        kodi = Kodi(['System.Platform.Android'])
        voice.run('voice', kodi, addon(), Mock(), Mock())
        self.assertEqual(kodi.actions, ['StartAndroidActivity("io.github.glasgowm148.kodivoice",'
                                      '"io.github.glasgowm148.kodivoice.LISTEN")'])

    def test_voice_never_changes_permissions_role_or_existing_search_text(self):
        for condition in ([], ['System.Platform.Android', 'Player.HasMedia']):
            kodi = Kodi(condition)
            voice.run('voice', kodi, addon(), Mock(), Mock())
            self.assertEqual(kodi.actions, [])

    def test_invalid_package_is_never_run(self):
        kodi = Kodi(['System.Platform.Android'])
        dialog = Mock()
        dialog.yesno.return_value = False
        voice.run('voice', kodi, addon({'voice_package': 'x),RunScript(evil)'}), dialog, Mock())
        self.assertEqual(kodi.actions, [])

    def test_disabled_voice_status_is_not_reported_as_ready(self):
        window = Mock()
        voice.run('voice-status', Kodi(['System.Platform.Android']),
                  addon({'voice_enabled': 'false'}), Mock(), window)
        window.setProperty.assert_called_once_with('Bingie.VoiceStatus', 'Set up voice search')


class ContinueWatchingTests(unittest.TestCase):
    def test_no_provider_or_network_source_is_enabled_by_default(self):
        kodi = Kodi()
        self.assertEqual(continuing.load_rows(kodi, addon()), ([], 0))
        self.assertEqual(kodi.calls, [])
        for source in ('https://example.invalid/history', 'http://user:secret@example.invalid/',
                       'file:///other-profile/history', 'special://masterprofile/history'):
            self.assertFalse(continuing.allowed_source(source))

    def test_resumable_duplicate_wins_and_original_playback_url_survives(self):
        a = {'showtitle': 'Example', 'season': 1, 'episode': 2, 'file': 'plugin://a/?play=original'}
        b = dict(a, file='plugin://b/?signed=a%26b', resume={'position': 30, 'total': 100}, playcount=1)
        self.assertEqual(continuing.merge([[a], [b]]), [b])
        self.assertEqual(continuing.merge([[b], [a]]), [b])

    def test_watched_without_resume_is_removed_but_different_episodes_remain(self):
        a = {'showtitle': 'Example', 'season': 1, 'episode': 2, 'file': 'plugin://a/'}
        self.assertEqual(len(continuing.merge([[a, dict(a, episode=3), dict(a, episode=4, playcount=1)]])), 2)

    def test_one_failed_source_keeps_other_results_and_reports_failure(self):
        kodi = Kodi(replies={'plugin://a/': {'error': {'code': -1}},
                             'plugin://b/': {'files': [{'file': 'plugin://b/play', 'title': 'Example'}]}})
        result, failures = continuing.load_rows(kodi, addon({'source1': 'plugin://a/', 'source2': 'plugin://b/'}))
        self.assertEqual(failures, 1)
        self.assertEqual(result[0]['file'], 'plugin://b/play')
        self.assertEqual([c['params']['directory'] for c in kodi.calls], ['plugin://a/', 'plugin://b/'])


if __name__ == '__main__':
    unittest.main()
