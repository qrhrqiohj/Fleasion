import zipfile
import tempfile
import sys
import os
import importlib.util
import json
import threading
import asyncio
import ctypes
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, QEvent

from mitmproxy import certs
from mitmproxy.options import Options
from mitmproxy.tools.dump import DumpMaster
from mitmproxy import ctx
import mitmproxy.proxy.mode_servers as mode_servers


PROXY = None


class Interceptor:
    def __init__(self):
        self.modules = []

    def register_module(self, module):
        if module not in self.modules:
            self.modules.append(module)

    def unregister_module(self, module):
        if module in self.modules:
            self.modules.remove(module)

    def _dispatch(self, name, *args):
        for module in list(self.modules):
            fn = getattr(module, name, None)
            if callable(fn):
                try:
                    fn(*args)
                except Exception as e:
                    print(
                        f"[Interceptor] {module.__class__.__name__}.{name} failed: {e}")

    # mitmproxy hooks
    def request(self, flow):
        self._dispatch("request", flow)

    def response(self, flow):
        self._dispatch("response", flow)

    def websocket_message(self, flow):
        self._dispatch("websocket", flow)


INTERCEPTOR = Interceptor()

# UI / ZIP loader


def load_ui(path, parent=None):
    loader = QUiLoader()
    file = QFile(path)
    file.open(QFile.ReadOnly)
    widget = loader.load(file, parent)
    file.close()
    return widget


def load_module(path, parent_tabwidget):
    if os.path.isdir(path):
        tmpdir = path
        keep_tmpdir = False
    else:
        tmpdir_obj = tempfile.TemporaryDirectory()
        tmpdir = tmpdir_obj.name
        keep_tmpdir = True
        with zipfile.ZipFile(path, "r") as z:
            z.extractall(tmpdir)

    manifest_path = os.path.join(tmpdir, "manifest.json")
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        tab_name = manifest.get("name", "Unnamed Tab")
        tab_description = manifest.get("description", "")
    else:
        tab_name = "Unnamed Tab"
        tab_description = ""

    ui_path = os.path.join(tmpdir, "tab.ui")
    if not os.path.exists(ui_path):
        raise FileNotFoundError(ui_path)

    tab_widget = QWidget()
    layout = QVBoxLayout(tab_widget)
    layout.setContentsMargins(0, 9, 0, 9)
    layout.setSpacing(6)
    layout.addWidget(load_ui(ui_path, tab_widget))

    sys.path.insert(0, tmpdir)

    py_file = os.path.join(tmpdir, "main.py")
    if not os.path.exists(py_file):
        raise FileNotFoundError(py_file)

    module_name = f"tab_module_{os.path.basename(path).replace('.', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, py_file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    tab_logic = module.Main(tab_widget)
    parent_tabwidget.addTab(tab_widget, tab_name)

    # register module with interceptor
    INTERCEPTOR.register_module(tab_logic)

    if keep_tmpdir:
        tab_logic._tmpdir = tmpdir_obj

    tab_logic._tab_name = tab_name
    tab_logic._tab_description = tab_description

    return tab_logic


def load_all_modules(parent_tabwidget, modules_dir="modules"):
    """
    Loads all modules (zip or directory) in a given directory.
    Returns a list of loaded tab_logic objects.
    """
    loaded = []

    if not os.path.exists(modules_dir):
        os.makedirs(modules_dir)

    for entry in os.listdir(modules_dir):
        path = os.path.join(modules_dir, entry)
        if entry.endswith(".zip") or os.path.isdir(path):
            try:
                tab_logic = load_module(path, parent_tabwidget)
                loaded.append(tab_logic)
            except Exception as e:
                print(f"Failed to load module '{entry}': {e}")

    return loaded


def ensure_mitm_cert():
    confdir = Path.home() / ".mitmproxy"
    confdir.mkdir(exist_ok=True)

    # Positional arguments ONLY (works across mitmproxy versions)
    certs.CertStore.from_store(
        str(confdir),   # store path
        "mitmproxy",    # basename
        2048            # key size
    )

    return (confdir / "mitmproxy-ca-cert.pem").exists()


def install_cert():
    if not ensure_mitm_cert():
        return False
    ca_path = Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.pem"
    mitm_ca_content = ca_path.read_text(encoding="utf-8")
    local_appdata = Path.home() / "AppData" / "Local"

    for e1 in os.scandir(local_appdata):
        if not e1.is_dir(follow_symlinks=False):
            continue

        try:
            for e2 in os.scandir(e1.path):
                if not e2.is_dir(follow_symlinks=False):
                    continue

                try:
                    for e3 in os.scandir(e2.path):
                        if not e3.is_dir(follow_symlinks=False):
                            continue

                        # FAST check: name only
                        if not e3.name.lower().startswith("version-"):
                            continue

                        exe_path = Path(e3.path) / "RobloxPlayerBeta.exe"
                        if not exe_path.exists():
                            continue

                        ssl = Path(e3.path) / "ssl"
                        ssl.mkdir(exist_ok=True)

                        ca_file = ssl / "cacert.pem"

                        try:
                            if ca_file.exists():
                                if mitm_ca_content not in ca_file.read_text(encoding="utf-8"):
                                    with ca_file.open("a", encoding="utf-8") as f:
                                        f.write("\n" + mitm_ca_content)
                            else:
                                ca_file.write_text(
                                    mitm_ca_content, encoding="utf-8")
                        except Exception:
                            pass

                except PermissionError:
                    continue

        except PermissionError:
            continue

    return True


async def wait_for_cert(timeout=10.0, interval=0.1):
    elapsed = 0.0
    while elapsed < timeout:
        if install_cert():
            return True
        await asyncio.sleep(interval)
        elapsed += interval
    return False


def start_proxy_t():

    def runner():
        try:
            result = asyncio.run(start_proxy())
            if result is None:
                raise RuntimeError("Proxy startup failed")
        except Exception:
            ctypes.windll.user32.MessageBoxW(
                0,
                "Failed to start proxy. The program will now close.",
                "Proxy error",
                0x10
            )
            os._exit(1)

    threading.Thread(
        target=runner,
        daemon=True
    ).start()


async def stop_proxy():
    global PROXY
    if PROXY is None:
        return

    try:
        # Shutdown the DumpMaster
        mode_servers.LocalRedirectorInstance._server = None
        mode_servers.LocalRedirectorInstance._instance = None
        if ctx.master:
            await asyncio.to_thread(ctx.master.shutdown)
        PROXY.cancel()
        PROXY = None
    except Exception as e:
        print(f"Failed to stop proxy: {e}")



async def start_proxy():
    global PROXY

    options = Options(mode=["local:RobloxPlayerBeta.exe"])
    master = DumpMaster(
        options,
        with_termlog=True,
        with_dumper=False
    )

    master.addons.add(INTERCEPTOR)

    PROXY = asyncio.create_task(master.run())

    if not await wait_for_cert():
        stop_proxy()
        return None

    await PROXY
    return master


# Main Window
class MainWindow(QMainWindow):
    def __init__(self):
        self.loaded_modules = []
        super().__init__()
        self.ui = load_ui("HoprU2.ui", self)
        self.setCentralWidget(self.ui.centralwidget)
        self.setMinimumSize(800, 350)

        self.tabs = self.ui.tabWidget

        self.tabs.currentChanged.connect(self.on_tab_changed)

        # Load all modules from 'modules/' directory
        start_proxy_t()
        self.loaded_modules = load_all_modules(self.tabs, "modules")

    def event(self, event):
        super().event(event)
        for module in self.loaded_modules:
            if hasattr(module, "event"):
                module.event(event)
        return True

    def on_tab_changed(self, index):
        """Send on_focus to the module of the newly selected tab"""
        current_widget = self.tabs.widget(index)
        for module in self.loaded_modules:
            if hasattr(module, "_tab_name") and module.tab_widget is current_widget:
                if hasattr(module, "on_focus"):
                    try:
                        module.on_focus()
                    except Exception as e:
                        print(f"[on_focus] {module._tab_name} failed: {e}")
    
    def cleanup(self):
        print("Stopping proxy...")

        # Stop proxy safely (sync wrapper)
        try:
            if PROXY:
                if ctx.master:
                    ctx.master.shutdown()
        except Exception as e:
            print(f"Proxy shutdown error: {e}")

        # Cleanup modules BEFORE Qt deletes widgets
        for module in self.loaded_modules:
            if hasattr(module, "cleanup_before_exit"):
                try:
                    module.cleanup_before_exit()
                except Exception as e:
                    print(f"Module cleanup failed: {e}")

        self.loaded_modules.clear()

        import gc
        gc.collect()

        print("Cleanup done.")
        
    def closeEvent(self, event):
        try:
            self.cleanup()  # directly call synchronous cleanup
        except Exception as e:
            print(f"Error during cleanup: {e}")

        super().closeEvent(event)  # then allow Qt to delete widgets




if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


