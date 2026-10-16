"""script.kodi.live.tv: the Live TV barrier before a direct (Kodi 22 final) account switch reads kodi.log."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import live_tv_fakes as fakes  # noqa: E402

PROFILES = ("<profiles><lastloaded>0</lastloaded><profile><name>Adults</name></profile>"
            "<profile><name>Kids</name></profile></profiles>")
GUISETTINGS = ("<settings version='2'><setting id='services.webserver'>false</setting>"
               "<setting id='services.esenabled'>true</setting></settings>")
FILLER = b"2026-10-15 20:00:00.000 T:1 info <general>: VideoPlayer: an ordinary playback line ..........\n"
STARTED = b"... info <general>: PVR Manager: Starting\n... info <general>: PVR Manager: Started\n"


class QuiesceTests(unittest.TestCase):
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
        self.xbmc, self.gui, self.vfs = fakes.kodi(self.root, profile="Adults", build=fakes.FINAL)
        self.log = self.root / "log" / "kodi.log"
        self.toggles, self.clock, self.on_sleep = [], [0.0], None
        self.xbmc.executeJSONRPC = self.rpc

        def sleep(ms):
            self.clock[0] += ms / 1000
            if self.on_sleep:
                self.on_sleep()
        self.xbmc.sleep = sleep
        modules = {"xbmc": self.xbmc, "xbmcgui": self.gui, "xbmcvfs": self.vfs}
        fakes.load("profile_transition", modules)
        fakes.load("profile_restart", modules)
        self.switch = fakes.load("profile_switch", modules)
        patcher = patch.object(self.switch.time, "monotonic", lambda: self.clock[0])
        patcher.start()
        self.addCleanup(patcher.stop)

    def rpc(self, request):
        request = json.loads(request)
        self.xbmc.rpc.append(request["method"])
        if request["method"] == "Addons.GetAddonDetails":
            return json.dumps({"result": {"addon": {"enabled": True}}})
        if request["method"] == "Settings.GetSettingValue":
            return json.dumps({"result": {"value": False}})
        if request["method"] == "Addons.SetAddonEnabled":
            self.toggles.append((request["params"]["addonid"], request["params"]["enabled"]))
            if request["params"]["addonid"] == "pvr.iptvsimple" and not request["params"]["enabled"]:
                with open(self.log, "ab") as stream:   # Kodi stops the PVR manager
                    stream.write(b"... PVR Manager: Stopping\n... PVR Manager: Stopped\n")
            return json.dumps({"result": "OK"})
        return json.dumps({"error": {"code": -1}})

    def test_started_line_far_behind_the_end_of_a_long_log_still_counts(self):
        self.log.write_bytes(STARTED + FILLER * 12000)               # ~1.1 MiB of ordinary logging since
        self.switch.quiesce_pvr("Kids")
        self.assertEqual(self.toggles, [("pvr.iptvsimple", False)])
        self.assertLess(self.clock[0], 2)                             # no 30 s wait
        self.assertTrue(Path(self.switch.pvr_journal_path()).exists())

    def test_started_marker_split_across_chunk_edges_is_found(self):
        for cut in (5, 12, 19):
            with self.subTest(cut=cut):
                self.toggles.clear()
                # The marker (20 bytes) starts ``cut`` bytes before the edge two chunks back from the end.
                chunk = self.switch.LOG_CHUNK
                self.log.write_bytes(b"x" * chunk + b"PVR Manager: Started\n" + b"y" * (2 * chunk + cut - 21))
                size = self.log.stat().st_size
                self.assertEqual(size - 2 * chunk, chunk + cut)
                self.switch.quiesce_pvr("Kids")
                self.assertEqual(self.toggles, [("pvr.iptvsimple", False)])

    def test_pvr_still_starting_waits_for_the_started_line(self):
        self.log.write_bytes(FILLER * 4000 + b"... PVR Manager: Starting\n" + FILLER * 4000)
        def start_later():
            if self.clock[0] >= 3 and b"Started" not in self.log.read_bytes()[-200:]:
                with open(self.log, "ab") as stream:
                    stream.write(b"... PVR Manager: Started\n" + FILLER)
        self.on_sleep = start_later
        self.switch.quiesce_pvr("Kids")
        self.assertGreaterEqual(self.clock[0], 3)
        self.assertEqual(self.toggles, [("pvr.iptvsimple", False)])

    def test_switch_is_refused_while_the_pvr_never_reports_started(self):
        self.log.write_bytes(STARTED + b"... PVR Manager: Stopping\n" + FILLER * 3000)
        with self.assertRaisesRegex(RuntimeError, "still starting"):
            self.switch.quiesce_pvr("Kids")
        self.assertEqual(self.toggles, [])

    def test_scan_is_bounded(self):
        self.log.write_bytes(STARTED + b"z" * (self.switch.LOG_SCAN_LIMIT + self.switch.LOG_CHUNK))
        reads = []
        real_open = open

        def counting_open(path, mode="r", *args, **kwargs):
            stream = real_open(path, mode, *args, **kwargs)
            if "b" in mode:
                read = stream.read
                stream.read = lambda size=-1: reads.append(size) or read(size)
            return stream
        with patch("builtins.open", counting_open), self.assertRaisesRegex(RuntimeError, "still starting"):
            self.switch.quiesce_pvr("Kids")
        first = sum(size for size in reads[:self.switch.LOG_SCAN_LIMIT // self.switch.LOG_CHUNK + 1])
        self.assertLessEqual(first, self.switch.LOG_SCAN_LIMIT + 2 * self.switch.LOG_CHUNK)
        self.assertLessEqual(sum(reads), first + 64 * len(reads))    # later polls read only new lines

    def test_direct_switch_on_unreviewed_kodi22_is_refused_before_mutations(self):
        with self.assertRaisesRegex(RuntimeError, 'not reviewed'):
            self.switch.switch("Kids")
        self.assertEqual(self.toggles, [])
        self.assertEqual(self.xbmc.builtins, [])


if __name__ == "__main__":
    unittest.main()
