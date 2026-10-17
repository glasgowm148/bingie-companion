"""script.kodi.live.tv restart-current: dispatch guards and the shared guarded relaunch (fakes only).

Runs against the add-on source in addons/script.kodi.live.tv:

    python -m unittest discover -s tests -q
"""
import json
import os
from pathlib import Path
import runpy
import shutil
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import Mock, patch

ADDON = Path(__file__).resolve().parents[1] / "addons/script.kodi.live.tv"
RC1 = "22.0-RC1 (21.90.901) Git:20260927-28ea2eac1e"


class Window:
    properties = {}

    def __init__(self, window_id):
        assert window_id == 10000

    def getProperty(self, name):
        return self.properties.get(name, "")

    def setProperty(self, name, value):
        self.properties[name] = value

    def clearProperty(self, name):
        self.properties.pop(name, None)


def fake_kodi(profile="Adults", playing=False, build=RC1):
    xbmc = types.ModuleType("xbmc")
    xbmc.LOGINFO = 1
    xbmc.lines, xbmc.builtins = [], []
    labels = {"System.ProfileName": profile, "System.BuildVersion": build}
    conds = {"System.Platform.Android": True, "Player.HasMedia": playing}
    xbmc.getInfoLabel = lambda name: labels.get(name, "")
    xbmc.getCondVisibility = lambda expression: conds.get(expression, False)
    xbmc.log = lambda line, level=0: xbmc.lines.append(line)
    xbmc.executebuiltin = xbmc.builtins.append
    xbmc.sleep = lambda ms: time.sleep(ms / 1000.0)
    gui = types.ModuleType("xbmcgui")
    Window.properties = {}
    gui.Window = Window
    return xbmc, gui


class DispatchTests(unittest.TestCase):
    def run_mode(self, argv, required=True, **kodi):
        xbmc, gui = fake_kodi(**kodi)
        restart = types.ModuleType("profile_restart")
        restart.required = Mock(return_value=required)
        restart.restart = Mock()
        switch = types.ModuleType("profile_switch")
        switch.restart_with_drain = restart.restart
        with patch.dict(sys.modules, {"xbmc": xbmc, "xbmcgui": gui, "profile_restart": restart, "profile_switch": switch}), \
                patch.object(sys, "argv", ["default.py"] + argv):
            with self.assertRaises(SystemExit):
                runpy.run_path(str(ADDON / "default.py"), run_name="__main__")
        return restart.restart, xbmc

    def test_restarts_into_the_profile_already_loaded(self):
        restart, xbmc = self.run_mode(["restart-current", "Adults"])
        restart.assert_called_once_with("Adults")
        self.assertEqual(xbmc.lines, ["[Profile Switch] Restarting into the current profile Adults"])
        self.assertEqual(xbmc.builtins, [])
        restart, _ = self.run_mode(["restart-current"], profile="Kids")
        restart.assert_called_once_with("Kids")

    def test_guards(self):
        cases = {"expected profile differs": dict(argv=["restart-current", "Kids"]),
                 "unaffected build": dict(argv=["restart-current", "Adults"], required=False),
                 "playing": dict(argv=["restart-current", "Adults"], playing=True),
                 "no profile": dict(argv=["restart-current"], profile="")}
        for name, case in cases.items():
            with self.subTest(name):
                restart, xbmc = self.run_mode(case.pop("argv"), **case)
                restart.assert_not_called()
                self.assertEqual(xbmc.lines, ["[Profile Switch] Restart into the current profile skipped"])
                self.assertEqual(xbmc.builtins, [])  # never the default Back action

    def test_switch_in_progress(self):
        xbmc, gui = fake_kodi()
        restart = types.ModuleType("profile_restart")
        restart.required, restart.restart = Mock(return_value=True), Mock()
        switch = types.ModuleType("profile_switch")
        switch.restart_with_drain = restart.restart
        Window.properties["KodiNavigation.ProfileSwitch"] = "1"
        with patch.dict(sys.modules, {"xbmc": xbmc, "xbmcgui": gui, "profile_restart": restart, "profile_switch": switch}), \
                patch.object(sys, "argv", ["default.py", "restart-current", "Adults"]):
            with self.assertRaises(SystemExit):
                runpy.run_path(str(ADDON / "default.py"), run_name="__main__")
        restart.restart.assert_not_called()


class GuardedRelaunchTests(unittest.TestCase):
    """profile_restart.restart(current): same helper arguments as a switch, current profile's index."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        addon = self.root / "addons" / "script.kodi.live.tv"
        (addon / "profile_restart").mkdir(parents=True)
        shutil.copyfile(ADDON / "profile_restart.py", addon / "profile_restart.py")
        shutil.copyfile(ADDON / "profile_restart" / "relaunch.sh", addon / "profile_restart" / "relaunch.sh")
        (addon / "profile_restart" / "classes.dex").write_bytes(b"dex")
        master = self.root / "master"
        (master / "addon_data" / "script.kodi.live.tv").mkdir(parents=True)
        (master / "addon_data" / "script.kodi.live.tv" / "profile-handoff-token").write_text("t")
        (master / "profiles.xml").write_text("<profiles><lastloaded>0</lastloaded><profile><name>Adults</name>"
                                             "</profile><profile><name>Kids</name></profile></profiles>")
        (self.root / "kodi.log").write_text("log\n")
        self.addon = addon

    def load(self, xbmc, gui):
        vfs = types.ModuleType("xbmcvfs")
        vfs.translatePath = lambda path: (path.replace("special://masterprofile/", str(self.root / "master") + "/")
                                          .replace("special://logpath/", str(self.root) + "/"))
        sys.modules.update({"xbmc": xbmc, "xbmcgui": gui, "xbmcvfs": vfs})
        return runpy.run_path(str(self.addon / "profile_restart.py"))

    def test_current_profile_index_reaches_the_helper_and_kodi_quits(self):
        xbmc, gui = fake_kodi(profile="Kids")
        launched = []

        def popen(args, **kwargs):
            launched.append(args)
            with open(args[5], "w", encoding="utf-8") as handle:
                json.dump({"phase": "waiting_saved", "pid": int(args[2]), "index": int(args[3])}, handle)
            return Mock(poll=Mock(return_value=None))

        with patch.dict(sys.modules), patch("subprocess.Popen", side_effect=popen):
            module = self.load(xbmc, gui)
            self.assertTrue(module["required"]())
            module["restart"]("Kids")
        [args] = launched
        self.assertEqual(args[:4], ["/system/bin/sh", str(self.addon / "profile_restart" / "relaunch.sh"),
                                    str(os.getpid()), "1"])
        self.assertEqual(xbmc.builtins, ["Quit"])
        self.assertIn("[Profile Switch] Controlled restart to Kids", xbmc.lines)

    def test_no_acknowledgement_means_no_quit(self):
        xbmc, gui = fake_kodi()
        with patch.dict(sys.modules), patch("subprocess.Popen", return_value=Mock(poll=Mock(return_value=1))):
            module = self.load(xbmc, gui)
            with self.assertRaises(RuntimeError):
                module["restart"]("Adults")
        self.assertEqual(xbmc.builtins, [])
        self.assertEqual(Window.properties, {})


if __name__ == "__main__":
    unittest.main()
