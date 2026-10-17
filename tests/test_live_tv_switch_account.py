"""script.kodi.live.tv switch-account: dispatch, target choice, opt-in participants, the guarded
relaunch path, the direct Kodi 21 path and the remote-control journal (fakes only; native service
shutdown and profile loading need a real Kodi)."""
import json
from pathlib import Path
import runpy
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import live_tv_fakes as fakes  # noqa: E402

PROFILES = ("<profiles><lastloaded>0</lastloaded><profile><name>Adults</name></profile>"
            "<profile><name>Kids</name></profile></profiles>")
KODI21 = "21.2 (21.2.0) Git:20250105-dbf7e3c4bb"
GUISETTINGS = ("<settings version='2'><setting id='services.webserver'>false</setting>"
               "<setting id='services.esenabled' default='true'>true</setting></settings>")


class DispatchTests(unittest.TestCase):
    def run_mode(self, *argv):
        with tempfile.TemporaryDirectory() as temp:
            xbmc, gui, vfs = fakes.kodi(temp)
            switch = types.ModuleType("profile_switch")
            switch.switch = Mock()
            with patch.dict(sys.modules, {"xbmc": xbmc, "xbmcgui": gui, "xbmcvfs": vfs, "profile_switch": switch}), \
                    patch.object(sys, "argv", ["default.py"] + list(argv)):
                with self.assertRaises(SystemExit):
                    runpy.run_path(str(fakes.ADDON / "default.py"), run_name="__main__")
        return switch.switch, xbmc

    def test_modes(self):
        for mode, target in (("switch-account", None), ("profiles", None)):
            with self.subTest(mode):
                switch, xbmc = self.run_mode(mode)
                switch.assert_called_once_with(target)
                self.assertEqual(xbmc.builtins, [])

    def test_household_iplayer_modes_are_not_public(self):
        # Modes 140/142 exist only in a patched iPlayer add-on; the public helper refuses them.
        for mode in ("browse-bbc-show", "mark-bbc-watched"):
            with self.subTest(mode), tempfile.TemporaryDirectory() as temp:
                xbmc, gui, vfs = fakes.kodi(temp)
                with patch.dict(sys.modules, {"xbmc": xbmc, "xbmcgui": gui, "xbmcvfs": vfs}), \
                        patch.object(sys, "argv", ["default.py", mode, "plugin://plugin.video.iplayerwww/"]), \
                        self.assertRaisesRegex(SystemExit, "Unknown navigation action"):
                    runpy.run_path(str(fakes.ADDON / "default.py"), run_name="__main__")
                self.assertEqual(xbmc.builtins, [])
        source = (fakes.ADDON / "default.py").read_text()
        self.assertNotIn("iplayerwww", source)


class SwitchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.addCleanup(fakes.restore_threading)
        modules = patch.dict(sys.modules)
        modules.start()
        self.addCleanup(modules.stop)
        (self.root / "master").mkdir()
        (self.root / "master" / "profiles.xml").write_text(PROFILES)
        (self.root / "profile").mkdir()
        (self.root / "profile" / "guisettings.xml").write_text(GUISETTINGS)

    def load(self, profile="Adults", required=True, build=fakes.RC1, real_restart=False):
        self.xbmc, self.gui, vfs = fakes.kodi(self.root, profile=profile, build=build)
        self.xbmc.executeJSONRPC = self.rpc
        self.toggles = []
        self.settings = {"services.webserver": True, "services.esenabled": True}
        modules = {"xbmc": self.xbmc, "xbmcgui": self.gui, "xbmcvfs": vfs}
        fakes.load("profile_transition", modules)
        if real_restart:
            restart = fakes.load("profile_restart", modules)
        else:
            restart = types.ModuleType("profile_restart")
            restart.required, restart.restart = Mock(return_value=required), Mock()
            restart.preflight = Mock()
        self.restart = restart
        return fakes.load("profile_switch", {"profile_restart": restart})

    def service(self, aid, library="service.py", opt_in="resources/lib/profile_transition.py"):
        """An installed service add-on; ``opt_in`` places the cooperative protocol module in it."""
        folder = self.root / "home" / "addons" / aid
        (folder / library).parent.mkdir(parents=True, exist_ok=True)
        (folder / library).write_text("")
        if opt_in:
            (folder / opt_in).parent.mkdir(parents=True, exist_ok=True)
            (folder / opt_in).write_text("")
        return str(folder / library)

    def rpc(self, request):
        request = json.loads(request)
        self.xbmc.rpc.append(request["method"])
        if request["method"] == "Settings.GetSettingValue":
            return json.dumps({"result": {"value": self.settings[request["params"]["setting"]]}})
        if request["method"] == "Addons.GetAddons":
            return json.dumps({"result": {"addons": getattr(self, "pvr_clients", [])}})
        if request["method"] == "Addons.SetAddonEnabled":
            self.toggles.append((request["params"]["addonid"], request["params"]["enabled"]))
            if request["params"]["addonid"] in getattr(self, "refuse_toggle", ()):
                return json.dumps({"error": {"code": -1}})
            return json.dumps({"result": "OK"})
        return json.dumps({"error": {"code": -1}})

    def test_target_is_the_other_of_two_profiles(self):
        switch = self.load()
        self.assertEqual(switch._target(None), "Kids")
        self.assertEqual(switch._target("Kids"), "Kids")
        self.assertIsNone(switch._target("Adults"))        # already there: nothing to do
        for bad in ("Guests", 'Ki"ds'):
            with self.subTest(bad), self.assertRaises(ValueError):
                switch._target(bad)
        (self.root / "master" / "profiles.xml").write_text(PROFILES.replace("</profiles>",
                                                                           "<profile><name>Third</name></profile></profiles>"))
        with self.assertRaises(ValueError):
            switch._target(None)                            # "the other profile" needs exactly two

    def test_affected_build_uses_the_guarded_relaunch(self):
        switch = self.load(profile="Kids")
        with patch.object(switch, "service_paths", return_value=[]):
            switch.switch()
        self.restart.restart.assert_called_once_with("Adults")
        self.assertEqual(self.xbmc.builtins, [])            # no StopScript/LoadProfile on RC1
        self.assertEqual(self.xbmc.rpc, [])

    def test_relaunch_waits_for_manager_before_native_quit(self):
        switch = self.load(profile="Kids")
        service = self.service('service.kodi.addonadmin', 'resources/lib/service.py')
        polls = []
        def finished(aid):
            polls.append(aid)
            return len(polls) > 1
        with patch.object(switch, 'service_paths', return_value=[service]), \
                patch.object(switch.transition, 'is_drained', side_effect=finished) as drained:
            switch.switch()
        self.restart.restart.assert_called_once_with('Adults')
        self.restart.preflight.assert_called_once_with('Adults')
        self.assertGreaterEqual(drained.call_count, 2)
        self.assertEqual(set(polls), {'service.kodi.addonadmin'})
        self.assertEqual(fakes.Window.properties['TMDbBingieHelper.ServiceStop'], 'True')
        self.assertTrue(switch.transition.read_state()['switching'])
        self.assertEqual(self.xbmc.builtins, [])

    def test_failed_restart_restores_cooperatively_stopped_services(self):
        switch = self.load(profile="Kids")
        service = self.service('service.kodi.addonadmin', 'resources/lib/service.py')
        self.restart.restart.side_effect = RuntimeError('synthetic launcher failure')
        with patch.object(switch, 'service_paths', return_value=[service]), \
                patch.object(switch.transition, 'is_drained', return_value=True):
            with self.assertRaisesRegex(RuntimeError, 'synthetic launcher failure'):
                switch.switch()
        self.assertFalse(switch.transition.read_state()['switching'])
        self.assertEqual(self.xbmc.builtins, [])
        self.assertEqual(self.xbmc.rpc, ['Addons.SetAddonEnabled', 'Addons.SetAddonEnabled'])
        self.assertFalse(fakes.Window.properties.get(switch.PROPERTY))

    def test_one_failed_restart_call_does_not_strand_the_other_services(self):
        switch = self.load(profile="Kids")
        manager = self.service('service.kodi.addonadmin', 'resources/lib/service.py')
        backup = self.service('script.xbmcbackup', opt_in='profile_transition.py')
        self.restart.restart.side_effect = RuntimeError('synthetic launcher failure')
        self.refuse_toggle = {'service.kodi.addonadmin'}
        with patch.object(switch, 'service_paths', return_value=[manager, backup]), \
                patch.object(switch.transition, 'is_drained', return_value=True):
            with self.assertRaisesRegex(RuntimeError, 'synthetic launcher failure'):
                switch.switch()
        self.assertEqual(self.toggles, [('script.xbmcbackup', False), ('script.xbmcbackup', True),
                                        ('service.kodi.addonadmin', False), ('service.kodi.addonadmin', True)])

    def test_only_addons_shipping_the_protocol_module_participate(self):
        switch = self.load()
        pov = self.service("plugin.video.pov", "resources/lib/service.py", "resources/lib/modules/profile_transition.py")
        stock = self.service("plugin.video.tmdb.bingie.helper", opt_in=None)
        deep = self.service("service.deep", opt_in="a/b/c/d/e/f/profile_transition.py")
        outside = str(self.root / "system" / "addons" / "service.system" / "service.py")
        (self.root / "home" / "addons" / "service.empty").mkdir()
        self.assertEqual(switch.participants([pov, stock, deep, outside]), ["plugin.video.pov"])
        self.assertEqual(switch.addon_id(pov), "plugin.video.pov")
        self.assertIsNone(switch.addon_id(outside))
        self.assertFalse(switch.opted_in("service.empty"))
        self.assertFalse(switch.opted_in("service.missing"))
        crowded = self.root / "home" / "addons" / "service.crowded"
        (crowded / "resources" / "a").mkdir(parents=True)
        for index in range(switch.OPT_IN_ENTRIES + 1):
            (crowded / ("f%04d.txt" % index)).write_text("")
        (crowded / "resources" / "a" / "profile_transition.py").write_text("")
        self.assertFalse(switch.opted_in("service.crowded"))      # bounded scan gives up
        switch.OPT_IN_ENTRIES = 1000000
        self.assertTrue(switch.opted_in("service.crowded"))

    def test_stock_addons_neither_block_the_relaunch_nor_get_restarted(self):
        switch = self.load(profile="Kids")
        stock = [self.service(aid, opt_in=None) for aid in (
            'service.kodi.addonadmin', 'service.subtitles.a4ksubtitles', 'script.xbmcbackup',
            'plugin.video.tmdb.bingie.helper', 'plugin.video.pov')]
        clock = iter(range(0, 1000))
        with patch.object(switch, 'service_paths', return_value=stock), \
                patch.object(switch.time, 'monotonic', side_effect=lambda: next(clock) / 10):
            switch.switch()
        self.restart.restart.assert_called_once_with('Adults')     # no 20 s wait for acknowledgements
        self.restart.restart.side_effect = RuntimeError('synthetic launcher failure')
        fakes.Window.properties.clear()
        with patch.object(switch, 'service_paths', return_value=stock):
            with self.assertRaisesRegex(RuntimeError, 'synthetic'):
                switch.switch()
        self.assertEqual(self.toggles, [])                          # stock add-ons are never disabled

    def test_failed_preflight_stops_and_changes_nothing(self):
        cases = {"no launcher token": ("not been configured", PROFILES),
                 "locked destination": ("Locked profiles", PROFILES.replace(
                     "<name>Adults</name>", "<name>Adults</name><lockmode>1</lockmode>"))}
        for name, (message, profiles) in cases.items():
            with self.subTest(name):
                (self.root / "master" / "profiles.xml").write_text(profiles)
                switch = self.load(profile="Kids", real_restart=True)
                self.assertTrue(self.restart.required())
                service = self.service('plugin.video.pov')
                with patch.object(switch, 'service_paths', return_value=[service]) as paths, \
                        patch.object(switch, 'prepare_home') as home:
                    with self.assertRaisesRegex((RuntimeError, ValueError), message):
                        switch.switch()
                    with self.assertRaisesRegex((RuntimeError, ValueError), message):
                        switch.restart_with_drain('Adults')      # the restart-current entry point
                paths.assert_not_called()
                home.assert_not_called()
                self.assertEqual(switch.transition.read_state(), {})      # transition never began
                self.assertEqual(fakes.Window.properties, {})             # no ServiceStop request
                self.assertEqual((self.xbmc.builtins, self.xbmc.rpc, self.toggles), ([], [], []))
                if name == "no launcher token":
                    token = self.root / "master" / "addon_data" / "script.kodi.live.tv" / "profile-handoff-token"
                    token.parent.mkdir(parents=True, exist_ok=True)

    def test_kodi21_direct_switch_loads_the_profile_natively(self):
        switch = self.load(profile="Adults", build=KODI21, real_restart=True)
        self.assertFalse(self.restart.required())
        with patch.object(switch, 'service_paths', return_value=[]):
            switch.switch()
        self.assertEqual(self.xbmc.builtins, ['AlarmClock(KodiNavigationSwitch,noop,2,silent)',
                                              'RunScript(script.kodi.live.tv,wait-profile-switch)'])
        self.assertIn('Addons.GetAddons', self.xbmc.rpc)                     # no IPTV Simple needed
        self.assertNotIn('Addons.GetAddonDetails', self.xbmc.rpc)
        self.assertEqual(self.xbmc.servers, [(self.xbmc.SERVER_WEBSERVER, False),
                                             (self.xbmc.SERVER_JSONRPCSERVER, False)])
        self.assertEqual(fakes.Window.properties['KodiNavigation.SwitchTarget'], 'Kids')
        switch.finish_switch()
        self.assertEqual(self.xbmc.builtins[-1], 'LoadProfile("Kids",prompt)')
        text = (self.root / "profile" / "guisettings.xml").read_text()
        self.assertIn('<setting id="services.webserver">true</setting>', text)  # restored for next load

    def test_direct_switch_recovery_survives_a_failed_restore(self):
        switch = self.load(profile="Adults", build=KODI21, real_restart=True)
        pov = self.service('plugin.video.pov')
        backup = self.service('script.xbmcbackup')
        stock = self.service('service.stock', opt_in=None)
        with patch.object(switch, 'service_paths', return_value=[pov, backup, stock]), \
                patch.object(switch.transition, 'is_drained', return_value=True), \
                patch.object(switch, 'quiesce_pvr', side_effect=RuntimeError('synthetic PVR failure')), \
                patch.object(switch, 'restore_remote_control', side_effect=OSError('synthetic restore failure')):
            with self.assertRaisesRegex(RuntimeError, 'synthetic PVR failure'):
                switch.switch()
        self.assertEqual(self.xbmc.builtins[-3:], ['CancelAlarm(KodiNavigationSwitch,silent)',
                                                   'RunScript("%s")' % pov, 'RunScript("%s")' % backup])
        self.assertTrue(any('Restoring remote control failed' in line for line in self.xbmc.lines))

    def test_restart_is_refused_when_pending_work_never_finishes(self):
        switch = self.load(profile="Kids")
        with patch.object(switch, 'service_paths', return_value=[]), \
                patch.object(switch.transition, 'pending_jobs', return_value=['synthetic-job']), \
                patch.object(switch.time, 'monotonic', side_effect=[0, 1, 21]):
            with self.assertRaisesRegex(RuntimeError, 'safely cancelled'):
                switch.switch()
        self.restart.restart.assert_not_called()
        self.assertFalse(switch.transition.read_state()['switching'])

    def test_switch_in_progress_or_same_profile_does_nothing(self):
        switch = self.load()
        fakes.Window.properties[switch.PROPERTY] = "1"
        switch.switch("Kids")
        fakes.Window.properties.clear()
        switch.switch("Adults")
        self.restart.restart.assert_not_called()

    def test_remote_control_preferences_saved_for_the_next_load(self):
        switch = self.load()
        switch.save_remote_preferences({"services.webserver": True, "services.esenabled": False})
        text = (self.root / "profile" / "guisettings.xml").read_text()
        self.assertIn("<setting id=\"services.webserver\">true</setting>", text)
        self.assertIn("<setting id=\"services.esenabled\">false</setting>", text)   # default attribute dropped
        with self.assertRaises(ValueError):
            switch.save_remote_preferences({"services.missing": True})

    def test_journal_restores_servers_and_clears_switch_state(self):
        switch = self.load()
        journal = Path(switch.journal_path())
        journal.parent.mkdir(parents=True)
        journal.write_text(json.dumps({"version": 1, "settings": {"services.webserver": False,
                                                                  "services.esenabled": True}}))
        fakes.Window.properties.update({switch.PROPERTY: "1", "KodiNavigation.SwitchTarget": "Kids",
                                        "KodiNavigation.ServiceIds": "a.b", "KodiNavigation.Service.a.b": "x"})
        self.assertTrue(switch.restore_remote_control())
        self.assertEqual(self.xbmc.servers, [(self.xbmc.SERVER_WEBSERVER, False)])   # only what changed
        self.assertFalse(journal.exists())
        self.assertEqual(fakes.Window.properties, {})
        journal.write_text(json.dumps({"version": 1, "settings": {"services.webserver": "yes",
                                                                  "services.esenabled": True}}))
        with self.assertRaises(ValueError):
            switch.restore_remote_control()


if __name__ == "__main__":
    unittest.main()
