"""Fake Kodi modules for script.kodi.live.tv tests: labels, conditions and builtins are dictionaries."""
import importlib.util
import sys
import threading
import types
from pathlib import Path

ADDON = Path(__file__).resolve().parents[1] / "addons/script.kodi.live.tv"
RC1 = "22.0-RC1 (21.90.901) Git:20260927-28ea2eac1e"
FINAL = "22.0 (22.0.0) Git:20261101-0a1b2c3d4e"
ORIGINAL_THREAD_START = threading.Thread.start


class Window:
    properties = {}

    def __init__(self, window_id=10000):
        assert window_id == 10000

    def getProperty(self, name):
        return self.properties.get(name, "")

    def setProperty(self, name, value):
        self.properties[name] = value

    def clearProperty(self, name):
        self.properties.pop(name, None)

    def setFocusId(self, control):
        self.properties["_focus"] = control


def kodi(root, profile="Adults", build=RC1, playing=False):
    """xbmc, xbmcgui and xbmcvfs modules; special:// paths live under ``root``."""
    root = Path(root)
    xbmc = types.ModuleType("xbmc")
    xbmc.LOGINFO, xbmc.LOGWARNING, xbmc.LOGERROR = 1, 2, 3
    xbmc.SERVER_WEBSERVER, xbmc.SERVER_JSONRPCSERVER = 1, 3
    xbmc.lines, xbmc.builtins, xbmc.rpc, xbmc.servers = [], [], [], []
    xbmc.labels = {"System.ProfileName": profile, "System.BuildVersion": build, "Network.LinkState": "up"}
    xbmc.conds = {"System.Platform.Android": True, "Player.HasMedia": playing}
    xbmc.getInfoLabel = lambda name: xbmc.labels.get(name, "")
    xbmc.getCondVisibility = lambda expression: xbmc.conds.get(expression, False)
    xbmc.log = lambda line, level=0: xbmc.lines.append(line)
    xbmc.executebuiltin = xbmc.builtins.append
    xbmc.sleep = lambda ms: None
    xbmc.abort = False

    class Monitor:
        def abortRequested(self):
            return xbmc.abort

        def waitForAbort(self, timeout=-1):
            return xbmc.abort

    xbmc.Monitor = Monitor

    def startServer(server, enabled):
        xbmc.servers.append((server, enabled))
        return True
    xbmc.startServer = startServer

    gui = types.ModuleType("xbmcgui")
    Window.properties = {}
    gui.Window = Window
    gui.getCurrentWindowId = lambda: 10000

    vfs = types.ModuleType("xbmcvfs")
    places = {"special://masterprofile/": root / "master", "special://profile/": root / "profile",
              "special://home/": root / "home", "special://logpath/": root / "log",
              "special://temp/": root / "temp", "special://database/": root / "database"}

    def translatePath(path):
        for prefix, folder in places.items():
            if path.startswith(prefix):
                return str(folder) + "/" + path[len(prefix):]
        return path
    vfs.translatePath = translatePath
    for folder in places.values():
        folder.mkdir(parents=True, exist_ok=True)
    return xbmc, gui, vfs


def load(name, modules):
    """Import ADDON/<name>.py as module ``name`` with ``modules`` in sys.modules (fresh each call)."""
    sys.modules.update(modules)
    spec = importlib.util.spec_from_file_location(name, ADDON / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def restore_threading():
    threading.Thread.start = ORIGINAL_THREAD_START
