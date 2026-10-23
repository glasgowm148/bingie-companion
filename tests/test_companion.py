import json
import os
from pathlib import Path
import sys
import time
import types
import unittest
from unittest.mock import Mock, patch

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
        key = request['params'].get('directory') or request['params'].get('setting') or request['method']
        reply = self.replies.get(key, {'files': []})
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
        navigation.choose_day(kodi, dialog, now=time.mktime((2027, 6, 1, 20, 0, 0, 0, 0, -1)))
        self.assertEqual(kodi.actions, ['PVR.EpgGridControl(currentprogramme)',
                                      'PVR.EpgGridControl(+48)', 'SetFocus(10)'])
        dialog.select.return_value = -1
        kodi.actions.clear()
        navigation.choose_day(kodi, dialog)
        self.assertEqual(kodi.actions, [])

    def test_cancelled_channel_wizard_preserves_all_existing_rows(self):
        kodi = Kodi()
        vfs = types.SimpleNamespace(listdir=Mock(return_value=(['Example@7'], [])))
        dialog = Mock()
        dialog.select.side_effect = [2, -1]
        navigation.configure_rows(kodi, dialog, vfs)
        self.assertEqual(kodi.actions, [])
        vfs.listdir.assert_called_once_with('pvr://channels/tv/')
        self.assertEqual(kodi.calls, [])  # PVR directories are unavailable through JSON-RPC.

    def test_rows_use_returned_paths_and_ignore_unrestricted_wildcards(self):
        path = 'pvr://channels/tv/Example%20group@7/'
        kodi = Kodi()
        vfs = types.SimpleNamespace(listdir=lambda _: (['*', 'Example%20group@7', '../bad', '%2A'], []))
        dialog = Mock()
        dialog.select.side_effect = [2, 0, 1]
        navigation.configure_rows(kodi, dialog, vfs)
        self.assertIn('Skin.SetString(KM_PVRRow1Path,"%s")' % path, kodi.actions)
        self.assertIn('Skin.SetString(KM_PVRRow2Path,"")', kodi.actions)
        self.assertFalse(any('KM_PVRRow3' in action for action in kodi.actions))


class DayPickerTests(unittest.TestCase):
    NOON = (2027, 6, 1, 12, 0, 0, 0, 0, -1)

    def setUp(self):
        saved = os.environ.get('TZ')

        def restore():
            if saved is None:
                os.environ.pop('TZ', None)
            else:
                os.environ['TZ'] = saved
            time.tzset()
        self.addCleanup(restore)

    def zone(self, name):
        if not hasattr(time, 'tzset'):
            self.skipTest('time.tzset is unavailable on this platform')
        os.environ['TZ'] = name
        time.tzset()

    def offered(self, setting, now):
        kodi = Kodi(replies=setting)
        dialog = Mock()
        dialog.select.return_value = -1
        navigation.choose_day(kodi, dialog, now=now)
        self.assertEqual(kodi.calls[0]['method'], 'Settings.GetSettingValue')
        self.assertEqual(kodi.calls[0]['params'], {'setting': 'epg.futuredaystodisplay'})
        return dialog.select.call_args[0][1]

    def test_days_follow_kodis_guide_setting_with_today_and_tomorrow_labels(self):
        self.zone('UTC')
        now = time.mktime(self.NOON)
        labels = self.offered({'epg.futuredaystodisplay': {'value': 2}}, now)
        self.assertEqual(labels, ['Today • Tuesday 01 June', 'Tomorrow • Wednesday 02 June', 'Thursday 03 June'])
        self.assertEqual(len(self.offered({'epg.futuredaystodisplay': {'value': 14}}, now)), 8)   # capped at 7
        self.assertEqual(len(self.offered({'epg.futuredaystodisplay': {'value': 0}}, now)), 1)

    def test_unreadable_setting_offers_kodis_default_three_future_days(self):
        self.zone('UTC')
        now = time.mktime(self.NOON)
        for reply in ({'error': {'code': -32602}}, {'value': 'x'}, {}):
            with self.subTest(reply):
                self.assertEqual(len(self.offered({'epg.futuredaystodisplay': reply}, now)), 4)

    def test_jump_keeps_the_same_wall_clock_time_across_a_dst_change(self):
        self.zone('Europe/London')
        kodi = Kodi(replies={'epg.futuredaystodisplay': {'value': 3}})
        spring = time.mktime((2027, 3, 27, 20, 30, 0, 0, 0, -1))   # BST starts 01:00 GMT on 28 March
        self.assertEqual([h for _, h in navigation.day_choices(kodi, spring)], [0, 23, 47, 71])
        self.assertEqual(navigation.day_choices(kodi, spring)[1][0], 'Tomorrow • Sunday 28 March')
        autumn = time.mktime((2027, 10, 30, 20, 30, 0, 0, 0, -1))  # BST ends 02:00 BST on 31 October
        self.assertEqual([h for _, h in navigation.day_choices(kodi, autumn)], [0, 25, 49, 73])
        dialog = Mock()
        dialog.select.return_value = 1
        navigation.choose_day(kodi, dialog, now=spring)
        self.assertEqual(kodi.actions, ['PVR.EpgGridControl(currentprogramme)',
                                        'PVR.EpgGridControl(+23)', 'SetFocus(10)'])
        # Target 2027-03-28 20:30 BST is 19:30 UTC; 23 h after 2027-03-27 20:30 GMT.
        self.assertEqual(time.gmtime(spring + 23 * 3600)[:5], (2027, 3, 28, 19, 30))


class VoiceTests(unittest.TestCase):
    def test_setup_uses_the_explicit_launcher_resolved_by_kodi(self):
        kodi = Kodi(['System.Platform.Android'])
        dialog = Mock()
        dialog.yesno.return_value = True
        voice.run('voice-setup', kodi, addon(), dialog, Mock())
        self.assertEqual(kodi.actions, ['StartAndroidActivity("io.github.glasgowm148.kodivoice")'])

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
                       'file:///other-profile/history', 'special://masterprofile/history',
                       'plugin://', 'videodb://'):
            self.assertFalse(continuing.allowed_source(source))

    def test_malformed_rows_are_ignored_without_breaking_other_items(self):
        valid = {'title': 'Example', 'season': 1, 'episode': 2, 'file': 'plugin://a/'}
        malformed = {'title': 'Broken', 'season': [], 'episode': {}, 'file': 'plugin://b/'}
        self.assertEqual(continuing.merge([[None, malformed, valid]]), [malformed, valid])

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



class FakePlugin:
    """xbmc, xbmcaddon, xbmcgui and xbmcplugin modules recording every directory call."""

    def __init__(self, kodi, settings, fail_on=None):
        self.ends, self.items = [], []
        self.modules = {'xbmc': types.ModuleType('xbmc'), 'xbmcaddon': types.ModuleType('xbmcaddon'),
                        'xbmcgui': types.ModuleType('xbmcgui'), 'xbmcplugin': types.ModuleType('xbmcplugin')}
        xbmc = self.modules['xbmc']
        xbmc.executeJSONRPC, xbmc.LOGERROR, xbmc.log = kodi.executeJSONRPC, 4, Mock()
        self.log = xbmc.log
        self.modules['xbmcaddon'].Addon = lambda: addon(settings)
        plugin = self.modules['xbmcplugin']
        plugin.setContent = Mock()
        plugin.endOfDirectory = lambda handle, succeeded=True, **kw: self.ends.append((handle, succeeded))

        def add(handle, url, li, isFolder=False):
            if url == fail_on:
                raise RuntimeError('synthetic listing failure')
            self.items.append(url)
        plugin.addDirectoryItem = add
        self.modules['xbmcgui'].ListItem = lambda **kw: Mock()

    def serve(self, mode='continue'):
        with patch.dict(sys.modules, self.modules):
            continuing.serve(7, mode)
        return self.ends


def listing(*files):
    return {'files': [{'file': f, 'title': f.rsplit('/', 1)[-1], 'season': 1, 'episode': i}
                      for i, f in enumerate(files)]}


class ServeTests(unittest.TestCase):
    def test_no_sources_is_a_successful_empty_folder(self):
        plugin = FakePlugin(Kodi(), {})
        self.assertEqual(plugin.serve(), [(7, True)])
        self.assertEqual(plugin.items, [])

    def test_all_sources_failing_reports_failure_once(self):
        kodi = Kodi(replies={'plugin://a/': {'error': {'code': -1}}})
        plugin = FakePlugin(kodi, {'source1': 'plugin://a/', 'source2': 'https://example.invalid/'})
        self.assertEqual(plugin.serve(), [(7, False)])

    def test_partial_failure_keeps_the_other_sources_results(self):
        kodi = Kodi(replies={'plugin://a/': {'error': {'code': -1}}, 'plugin://b/': listing('plugin://b/1')})
        plugin = FakePlugin(kodi, {'source1': 'plugin://a/', 'source2': 'plugin://b/'})
        self.assertEqual(plugin.serve(), [(7, True)])
        self.assertEqual(plugin.items, ['plugin://b/1'])

    def test_malformed_source_does_not_erase_a_healthy_source(self):
        malformed = ('not json', 'null', '[]', '{"result": null}',
                     '{"result": {"files": null}}', '{"result": {"files": {}}}',
                     '{"result": {"files": [null]}}')
        for reply in malformed:
            with self.subTest(reply=reply):
                kodi = Kodi(replies={'plugin://b/': listing('plugin://b/1')})
                execute = kodi.executeJSONRPC
                kodi.executeJSONRPC = lambda raw: (
                    reply if json.loads(raw)['params']['directory'] == 'plugin://a/' else execute(raw))
                plugin = FakePlugin(kodi, {'source1': 'plugin://a/', 'source2': 'plugin://b/'})
                self.assertEqual(plugin.serve(), [(7, True)])
                self.assertEqual(plugin.items, ['plugin://b/1'])
                self.assertFalse(plugin.log.called)

    def test_malformed_only_source_reports_failure_once(self):
        kodi = Kodi()
        kodi.executeJSONRPC = lambda raw: '{"result": {"files": null}}'
        plugin = FakePlugin(kodi, {'source1': 'plugin://a/'})
        self.assertEqual(plugin.serve(), [(7, False)])
        self.assertEqual(plugin.items, [])

    def test_exception_mid_listing_still_ends_the_directory_exactly_once(self):
        kodi = Kodi(replies={'plugin://b/': listing('plugin://b/1', 'plugin://b/2', 'plugin://b/3')})
        plugin = FakePlugin(kodi, {'source1': 'plugin://b/'}, fail_on='plugin://b/2')
        self.assertEqual(plugin.serve(), [(7, False)])
        self.assertEqual(plugin.items, ['plugin://b/1'])
        self.assertIn('synthetic listing failure', plugin.log.call_args[0][0])

    def test_settings_and_unknown_modes_end_once(self):
        self.assertEqual(FakePlugin(Kodi(), {}).serve('settings'), [(7, True)])
        self.assertEqual(FakePlugin(Kodi(), {}).serve('unknown'), [(7, False)])

    def test_addon_requires_kodi20_for_info_tag_setters(self):
        text = (ROOT / 'addons/script.bingie.companion/addon.xml').read_text()
        self.assertIn('<import addon="xbmc.python" version="3.0.1" />', text)


if __name__ == '__main__':
    unittest.main()
