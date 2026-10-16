"""script.kodi.live.tv switch-account: dispatch, target choice, the guarded relaunch path and the
remote-control journal (fakes only; the native drain path needs a real Kodi)."""
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

    def load(self, profile="Adults", required=True):
        self.xbmc, self.gui, vfs = fakes.kodi(self.root, profile=profile)
        self.xbmc.executeJSONRPC = self.rpc
        self.toggles = []
        self.settings = {"services.webserver": True, "services.esenabled": True}
        restart = types.ModuleType("profile_restart")
        restart.required, restart.restart = Mock(return_value=required), Mock()
        self.restart = restart
        fakes.load("profile_transition", {"xbmc": self.xbmc, "xbmcgui": self.gui, "xbmcvfs": vfs})
        return fakes.load("profile_switch", {"profile_restart": restart})

    def rpc(self, request):
        request = json.loads(request)
        self.xbmc.rpc.append(request["method"])
        if request["method"] == "Settings.GetSettingValue":
            return json.dumps({"result": {"value": self.settings[request["params"]["setting"]]}})
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
        service = '/addons/service.kodi.addonadmin/resources/lib/service.py'
        polls = []
        def finished(aid):
            polls.append(aid)
            return len(polls) > 1
        with patch.object(switch, 'service_paths', return_value=[service]), \
                patch.object(switch.transition, 'is_drained', side_effect=finished) as drained:
            switch.switch()
        self.restart.restart.assert_called_once_with('Adults')
        self.assertGreaterEqual(drained.call_count, 2)
        self.assertEqual(fakes.Window.properties['TMDbBingieHelper.ServiceStop'], 'True')
        self.assertTrue(switch.transition.read_state()['switching'])
        self.assertEqual(self.xbmc.builtins, [])

    def test_failed_restart_restores_cooperatively_stopped_services(self):
        switch = self.load(profile="Kids")
        service = '/addons/service.kodi.addonadmin/resources/lib/service.py'
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
        manager = '/addons/service.kodi.addonadmin/resources/lib/service.py'
        backup = '/addons/script.xbmcbackup/service.py'
        self.restart.restart.side_effect = RuntimeError('synthetic launcher failure')
        self.refuse_toggle = {'service.kodi.addonadmin'}
        with patch.object(switch, 'service_paths', return_value=[manager, backup]), \
                patch.object(switch.transition, 'is_drained', return_value=True):
            with self.assertRaisesRegex(RuntimeError, 'synthetic launcher failure'):
                switch.switch()
        self.assertEqual(self.toggles, [('service.kodi.addonadmin', False), ('service.kodi.addonadmin', True),
                                        ('script.xbmcbackup', False), ('script.xbmcbackup', True)])

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
