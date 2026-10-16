"""script.kodi.live.tv "Choose day": PVR.EpgGridControl(+N) is relative to the guide's selected time."""
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import live_tv_fakes as fakes  # noqa: E402


class ChooseDayTests(unittest.TestCase):
    def choose(self, choice):
        with tempfile.TemporaryDirectory() as temp:
            xbmc, gui, vfs = fakes.kodi(temp)
            offered = []

            class Dialog:
                def select(self, heading, labels):
                    offered.extend(labels)
                    return choice
            gui.Dialog = Dialog
            with patch.dict(sys.modules, {"xbmc": xbmc, "xbmcgui": gui, "xbmcvfs": vfs}), \
                    patch.object(sys, "argv", ["default.py", "day"]):
                with self.assertRaises(SystemExit):
                    runpy.run_path(str(fakes.ADDON / "default.py"), run_name="__main__")
        self.assertEqual(len(offered), 3)  # no guide database: today and the next two days
        return xbmc.builtins

    def test_later_day_first_returns_to_now_then_moves_whole_days(self):
        self.assertEqual(self.choose(2), ["PVR.EpgGridControl(currentprogramme)", "PVR.EpgGridControl(+48)", "SetFocus(10)"])
        self.assertEqual(self.choose(1), ["PVR.EpgGridControl(currentprogramme)", "PVR.EpgGridControl(+24)", "SetFocus(10)"])

    def test_today_goes_to_the_current_programme(self):
        self.assertEqual(self.choose(0), ["PVR.EpgGridControl(currentprogramme)", "SetFocus(10)"])

    def test_cancel_changes_nothing(self):
        self.assertEqual(self.choose(-1), [])


if __name__ == "__main__":
    unittest.main()
