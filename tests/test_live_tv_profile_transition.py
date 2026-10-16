"""script.kodi.live.tv profile_transition.py: the coordinator side of the switch protocol (fakes only).

The same file is copied into POV, TMDb Bingie Helper, a4kSubtitles and Kodi Backup.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import live_tv_fakes as fakes  # noqa: E402


class TransitionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.xbmc, gui, vfs = fakes.kodi(self.root)
        modules = patch.dict(sys.modules)
        modules.start()
        self.addCleanup(modules.stop)
        self.addCleanup(fakes.restore_threading)
        self.t = fakes.load("profile_transition", {"xbmc": self.xbmc, "xbmcgui": gui, "xbmcvfs": vfs})
        self.state = Path(self.t.STATE)

    def test_paths(self):
        self.assertEqual(self.state, self.root / "master" / "addon_data" / "script.kodi.live.tv" / "transition.json")
        self.assertEqual(self.t.PROFILE, str(self.root / "profile"))

    def test_begin_settle_and_foreign_process(self):
        self.assertEqual(self.t.read_state(), {})
        generation = self.t.begin("Kids")
        state = self.t.read_state()
        self.assertEqual(state, {"pid": os.getpid(), "generation": generation, "switching": True,
                                 "outgoing": self.t.PROFILE, "target": "Kids"})
        self.t.settle()
        self.assertFalse(self.t.read_state()["switching"])
        self.state.write_text(json.dumps(dict(state, pid=os.getpid() + 1)))
        self.assertEqual(self.t.read_state(), {})         # another Kodi process's record is ignored
        self.state.write_text("{broken")
        self.assertEqual(self.t.read_state(), {})

    def test_lease_and_monitor_cancel_on_switch(self):
        lease, monitor = self.t.Lease(), self.t.Monitor()
        self.assertFalse(lease.cancelled())
        self.assertFalse(monitor.abortRequested())
        self.assertFalse(monitor.waitForAbort(0.01))
        self.t.begin("Kids")
        self.assertTrue(lease.cancelled())                 # new generation and our profile is outgoing
        self.assertTrue(monitor.abortRequested())
        self.assertTrue(monitor.waitForAbort(5))           # returns at once instead of waiting 5 s
        later = self.t.Lease()
        self.assertTrue(later.cancelled())                 # still switching away from this profile
        self.t.settle()
        self.assertFalse(later.cancelled())

    def test_invocation_jobs_and_owned_workers(self):
        self.t.begin("Kids")
        release, seen = threading.Event(), []
        with self.t.Invocation("plugin.video.pov") as invocation:
            self.assertTrue(invocation.cancelled())             # begun before: a switch is under way
            self.assertEqual(self.t.pending_jobs(), ["plugin.video.pov"])
            worker = threading.Thread(target=release.wait, args=(5,))
            worker.start()
            seen = self.t._owned_workers("plugin.video.pov")
            release.set()
        self.assertEqual(seen, [worker])                   # the worker inherited the invocation's owner
        self.assertFalse(worker.is_alive())                # __exit__ waited for it
        self.assertEqual(self.t.pending_jobs(), [])        # ticket removed

    def test_drained_acknowledges_per_generation(self):
        self.t.begin("Kids")
        self.assertFalse(self.t.is_drained("script.xbmcbackup"))
        self.assertTrue(self.t.drained("script.xbmcbackup", timeout=1))
        self.assertTrue(self.t.is_drained("script.xbmcbackup"))
        self.t.begin("Adults")                             # a new switch needs a new acknowledgement
        self.assertFalse(self.t.is_drained("script.xbmcbackup"))


if __name__ == "__main__":
    unittest.main()
