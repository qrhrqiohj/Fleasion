import asyncio
import ctypes
import gzip
import json
import subprocess
import sys
import threading
import time
import tkinter as tk
import mimetypes
import shutil  # Added for file copying
import os
from copy import deepcopy
from functools import wraps
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk
from typing import Callable
from urllib.parse import urlparse

import pystray
from mitmproxy import certs, http
from mitmproxy.options import Options
from mitmproxy.tools.dump import DumpMaster
from PIL import Image

# Constants
ROBLOX_PROCESS = "RobloxPlayerBeta.exe"
PROXY_TARGET_HOST = "assetdelivery.roblox.com"
STRIPPABLE_ASSET_TYPES = {"Image", "TexturePack"}
APP_NAME, APP_VERSION = "Fleasion NT", "1.4.1-Universal"
APP_AUTHOR = "Script by Blockce, modified by 8ar, portable by Gemini"
APP_DISCORD = "discord.gg/hXyhKehEZF"
ICON_FILENAME = "fleasionlogo2.ico"

# --- Directory Setup (Universal Pathing) ---
# Determine where the script or exe is actually running
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent.resolve()

# Dedicated folder for assets next to the script
ASSETS_DIR = BASE_DIR / "FleasionAssets"

LOCAL_APPDATA = Path.home() / "AppData" / "Local"
MITMPROXY_DIR = Path.home() / ".mitmproxy"
STORAGE_DB = LOCAL_APPDATA / "Roblox" / "rbx-storage.db"
CONFIG_DIR = LOCAL_APPDATA / "FleasionNT"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "strip_textures": True,
    "active_config": "Default",
    "last_config": "Default",
    "configs": {"Default": {"replacement_rules": []}},
}

# State
log_buffer: list[str] = []
proxy_running = False
tray_icon = None
config_manager = None


# --- Utilities ---


def log(cat: str, msg: str):
    log_buffer.append(f"[{cat}] {msg}")


def run_cmd(args: list[str]) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True).stdout
    except Exception:
        return ""


def is_roblox_running() -> bool:
    return ROBLOX_PROCESS in run_cmd(
        ["tasklist", "/FI", f"IMAGENAME eq {ROBLOX_PROCESS}"]
    )


def terminate_roblox() -> bool:
    if not is_roblox_running():
        return False
    run_cmd(["taskkill", "/F", "/IM", ROBLOX_PROCESS])
    return True


def wait_for_roblox_exit(timeout=10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_roblox_running():
            return True
        time.sleep(0.5)
    return False


def get_icon_path() -> Path | None:
    path = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / ICON_FILENAME
    return path if path.exists() else None


def get_icon_image() -> Image.Image:
    if p := get_icon_path():
        try:
            return (
                Image.open(p).convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)
            )
        except Exception:
            pass
    return Image.new("RGBA", (64, 64), (70, 130, 180, 255))


def set_window_icon(window: tk.Tk | tk.Toplevel):
    if p := get_icon_path():
        try:
            window.iconbitmap(str(p))
        except Exception:
            pass


def threaded_gui(func: Callable) -> Callable:
    """Decorator to run a GUI function in a daemon thread."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        threading.Thread(target=func, args=args, kwargs=kwargs, daemon=True).start()

    return wrapper


def make_window(title: str, w: int, h: int, resizable=True) -> tk.Tk:
    root = tk.Tk()
    root.withdraw()
    root.title(title)
    root.geometry(
        f"{w}x{h}+{(root.winfo_screenwidth() - w) // 2}"
        f"+{(root.winfo_screenheight() - h) // 2}"
    )
    root.resizable(resizable, resizable)
    set_window_icon(root)
    root.deiconify()
    return root


# --- Config Manager ---


class ConfigManager:
    def __init__(self):
        self._lock = threading.Lock()
        self.config = self._load()
        # Ensure Assets directory exists on startup
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        
        last = self.config.get("last_config", "Default")
        if last in self.config.get("configs", {}):
            self.config["active_config"] = last

    def _load(self) -> dict:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r") as f:
                    loaded = json.load(f)
                if "configs" not in loaded:  # Migration
                    loaded = {
                        "strip_textures": loaded.get("strip_textures", True),
                        "active_config": "Default",
                        "last_config": "Default",
                        "configs": {
                            "Default": {
                                "replacement_rules": loaded.get("replacement_rules", [])
                            }
                        },
                    }
                return {**DEFAULT_CONFIG, **loaded}
            except (json.JSONDecodeError, OSError):
                pass
        return deepcopy(DEFAULT_CONFIG)

    def save(self):
        with self._lock:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.config, f, indent=2)

    @property
    def strip_textures(self) -> bool:
        return self.config.get("strip_textures", True)

    @strip_textures.setter
    def strip_textures(self, value: bool):
        self.config["strip_textures"] = value
        self.save()

    @property
    def active_config_name(self) -> str:
        return self.config.get("active_config", "Default")

    @active_config_name.setter
    def active_config_name(self, value: str):
        self.config["active_config"] = self.config["last_config"] = value
        self.save()

    @property
    def config_names(self) -> list[str]:
        return list(self.config.get("configs", {}).keys())

    @property
    def replacement_rules(self) -> list:
        return (
            self.config.get("configs", {})
            .get(self.active_config_name, {})
            .get("replacement_rules", [])
        )

    @replacement_rules.setter
    def replacement_rules(self, value: list):
        self.config.setdefault("configs", {}).setdefault(self.active_config_name, {})[
            "replacement_rules"
        ] = value
        self.save()

    def _modify_config(
        self, name: str, new_name: str | None = None, delete: bool = False
    ) -> bool:
        configs = self.config.get("configs", {})
        if name not in configs:
            return False
        if delete:
            if len(configs) <= 1:
                return False
            del configs[name]
            if self.active_config_name == name:
                self.config["active_config"] = self.config["last_config"] = list(
                    configs.keys()
                )[0]
        elif new_name:
            if new_name in configs:
                return False
            configs[new_name] = configs.pop(name)
            if self.config["active_config"] == name:
                self.config["active_config"] = new_name
            if self.config["last_config"] == name:
                self.config["last_config"] = new_name
        self.save()
        return True

    def create_config(self, name: str) -> bool:
        if name in self.config.get("configs", {}):
            return False
        self.config.setdefault("configs", {})[name] = {"replacement_rules": []}
        self.save()
        return True

    def delete_config(self, name: str) -> bool:
        return self._modify_config(name, delete=True)

    def rename_config(self, old_name: str, new_name: str) -> bool:
        return self._modify_config(old_name, new_name)

    def duplicate_config(self, name: str, new_name: str) -> bool:
        configs = self.config.get("configs", {})
        if name not in configs or new_name in configs:
            return False
        configs[new_name] = deepcopy(configs[name])
        self.save()
        return True

    def get_hash_replacements(self) -> tuple[dict[str, Path], set[str]]:
        """
        Returns:
        1. Dictionary {target_hash -> FULL_PATH_TO_ASSET}
        2. Set of hashes to remove {target_hash}
        """
        replacements, removals = {}, set()
        for rule in self.replacement_rules:
            target = rule.get("target_hash", "").strip()
            if not target:
                continue
                
            if rule.get("remove"):
                removals.add(target)
            else:
                filename = rule.get("replacement_file", "")
                if filename:
                    # Resolve the filename relative to ASSETS_DIR
                    # This makes it universal/portable
                    full_path = ASSETS_DIR / filename
                    replacements[target] = full_path
        return replacements, removals


# --- Certificate Installation ---


def get_ca_content() -> str | None:
    MITMPROXY_DIR.mkdir(exist_ok=True)
    certs.CertStore.from_store(str(MITMPROXY_DIR), "mitmproxy", 2048)
    ca_file = MITMPROXY_DIR / "mitmproxy-ca-cert.pem"
    return ca_file.read_text() if ca_file.exists() else None


def install_certs() -> bool:
    if not (ca := get_ca_content()):
        return False
    for d in LOCAL_APPDATA.glob("**/version-*"):
        if d.is_dir() and (d / ROBLOX_PROCESS).exists():
            ssl_dir = d / "ssl"
            ssl_dir.mkdir(exist_ok=True)
            ca_file = ssl_dir / "cacert.pem"
            try:
                existing = ca_file.read_text() if ca_file.exists() else ""
                if ca not in existing:
                    ca_file.write_text(f"{existing}\n{ca}")
            except (PermissionError, OSError):
                pass
    return True


async def wait_for_cert_install(timeout=10.0) -> bool:
    for _ in range(int(timeout / 0.1)):
        if install_certs():
            return True
        await asyncio.sleep(0.1)
    return False


# --- Proxy Addon ---


class TextureStripper:
    @staticmethod
    def _decode(content: bytes, enc: str):
        if enc == "gzip":
            content = gzip.decompress(content)
        return json.loads(content)

    @staticmethod
    def _encode(data, enc: str) -> bytes:
        raw = json.dumps(data, separators=(",", ":")).encode()
        return gzip.compress(raw) if enc == "gzip" else raw

    def request(self, flow: http.HTTPFlow):
        # 1. BATCH REQUEST INTERCEPTION
        if (
            urlparse(flow.request.pretty_url).hostname == PROXY_TARGET_HOST
            and flow.request.raw_content
            and config_manager.strip_textures
        ):
            enc = flow.request.headers.get("Content-Encoding", "").lower()
            try:
                data = self._decode(flow.request.raw_content, enc)
            except (json.JSONDecodeError, gzip.BadGzipFile, OSError):
                data = None

            if isinstance(data, list):
                modified = False
                for e in data:
                    if not isinstance(e, dict): continue
                    
                    if (
                        e.get("assetType") in STRIPPABLE_ASSET_TYPES
                        and e.pop("contentRepresentationPriorityList", None) is not None
                    ):
                        log("Stripper", f"Removed texture priority: {e['assetType']}")
                        modified = True
                
                if modified:
                    flow.request.raw_content = self._encode(data, enc)
                    flow.request.headers["Content-Length"] = str(len(flow.request.raw_content))

    def response(self, flow: http.HTTPFlow):
        # 2. HASH BASED REPLACEMENT
        replacements, removals = config_manager.get_hash_replacements()
        if not replacements and not removals:
            return

        url = flow.request.pretty_url
        
        # Check for Removals
        for target_hash in removals:
            if target_hash in url:
                flow.response = http.Response.make(404, b"Not Found (Blocked by Fleasion)")
                log("Remover", f"Blocked download for hash: {target_hash[:8]}...")
                return

        # Check for Replacements
        for target_hash, file_path_obj in replacements.items():
            if target_hash in url:
                # file_path_obj is a Path object resolving to ASSETS_DIR/filename
                if file_path_obj.exists():
                    try:
                        mime = mimetypes.guess_type(file_path_obj)[0] or "application/octet-stream"
                        content = file_path_obj.read_bytes()
                        
                        flow.response = http.Response.make(
                            200,
                            content,
                            {
                                "Content-Type": mime,
                                "Content-Length": str(len(content)),
                                "Access-Control-Allow-Origin": "*",
                                "Cache-Control": "no-cache"
                            }
                        )
                        log("Replacer", f"Served {file_path_obj.name} for hash: {target_hash[:8]}...")
                        return
                    except Exception as e:
                        log("Error", f"Failed to read {file_path_obj.name}: {e}")
                else:
                    log("Error", f"Missing asset file: {file_path_obj}")


# --- Cache Deletion ---


def delete_cache_with_cleanup() -> list[str]:
    messages = []

    if is_roblox_running():
        messages.append("Roblox is running, terminating...")
        terminate_roblox()
        if wait_for_roblox_exit():
            messages.append("Roblox terminated successfully")
        else:
            messages.extend(
                ["Roblox termination timed out", "Cache deletion aborted"]
            )
            return messages
    else:
        messages.append("Roblox is not running")

    if not STORAGE_DB.exists():
        messages.append("Storage database not found")
    else:
        try:
            STORAGE_DB.unlink()
            messages.append("Storage database deleted successfully")
        except PermissionError:
            messages.append("Failed: Permission denied - file is locked")
        except OSError as e:
            messages.append(f"Failed: {e}")

    return messages


# --- GUI Windows ---


@threaded_gui
def show_logs():
    root = make_window(f"{APP_NAME} - Logs", 600, 400)
    text = scrolledtext.ScrolledText(root, wrap=tk.WORD, font=("Consolas", 10))
    text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    last_count = [0]

    def update():
        if len(log_buffer) != last_count[0]:
            text.config(state=tk.NORMAL)
            text.delete("1.0", tk.END)
            text.insert(tk.END, "\n".join(log_buffer) or "No logs yet.")
            text.config(state=tk.DISABLED)
            text.see(tk.END)
            last_count[0] = len(log_buffer)
        root.after(250, update)

    update()
    root.mainloop()


@threaded_gui
def show_delete_cache_result():
    root = make_window(f"{APP_NAME} - Delete Cache", 400, 200, resizable=False)
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill=tk.BOTH, expand=True)

    ttk.Label(frame, text="Deleting Cache...", font=("Segoe UI", 11, "bold")).pack(
        anchor=tk.W
    )
    status_text = scrolledtext.ScrolledText(
        frame, wrap=tk.WORD, font=("Consolas", 9), height=6
    )
    status_text.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

    close_btn = ttk.Button(frame, text="Close", command=root.destroy, state=tk.DISABLED)
    close_btn.pack(pady=(10, 0))

    def perform():
        for msg in delete_cache_with_cleanup():
            log("Cache", msg)
            status_text.insert(tk.END, msg + "\n")
            status_text.see(tk.END)
            root.update()
            time.sleep(0.3)
        status_text.insert(tk.END, "\nDone.")
        close_btn.config(state=tk.NORMAL)

    threading.Thread(target=perform, daemon=True).start()
    root.mainloop()


@threaded_gui
def show_about():
    root = make_window(f"About {APP_NAME}", 350, 200, resizable=False)
    f = tk.Frame(root)
    f.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

    for text, font in [
        (APP_NAME, ("Segoe UI", 14, "bold")),
        (f"Version {APP_VERSION}", ("Segoe UI", 10)),
        (APP_AUTHOR, ("Segoe UI", 10)),
        (f"Distributed in {APP_DISCORD}", ("Segoe UI", 10)),
        (f"\nStatus: {'Running' if proxy_running else 'Starting...'}", ("Segoe UI", 10, "bold")),
    ]:
        tk.Label(f, text=text, font=font).pack(pady=(5, 0) if "Version" in text else 0)

    tk.Button(root, text="Close", command=root.destroy, width=10).pack(pady=(0, 15))
    root.mainloop()


@threaded_gui
def copy_discord():
    root = tk.Tk()
    root.withdraw()
    root.clipboard_clear()
    root.clipboard_append(f"https://{APP_DISCORD}")
    root.update()
    root.destroy()
    ctypes.windll.user32.MessageBoxW(
        0, f"Discord invite copied!\n\nhttps://{APP_DISCORD}", APP_NAME, 0x40
    )


# --- Replacer Config Window ---


@threaded_gui
def show_replacer_config():
    root = make_window(f"{APP_NAME} - Hash Replacer Config", 750, 700)
    root.minsize(650, 600)
    main = ttk.Frame(root, padding=10)
    main.pack(fill=tk.BOTH, expand=True)

    # --- Config selector ---
    cfg_frame = ttk.LabelFrame(main, text="Configuration", padding=10)
    cfg_frame.pack(fill=tk.X, pady=(0, 10))

    cfg_sel = ttk.Frame(cfg_frame)
    cfg_sel.pack(fill=tk.X)
    ttk.Label(cfg_sel, text="Active Config:").pack(side=tk.LEFT)

    config_var = tk.StringVar(value=config_manager.active_config_name)
    config_combo = ttk.Combobox(
        cfg_sel,
        textvariable=config_var,
        values=config_manager.config_names,
        state="readonly",
        width=25,
    )
    config_combo.pack(side=tk.LEFT, padx=(5, 10))

    def refresh_combo():
        config_combo["values"] = config_manager.config_names
        config_var.set(config_manager.active_config_name)

    def on_config_change(_=None):
        config_manager.active_config_name = config_var.get()
        refresh_tree()
        log("Config", f"Switched to: {config_var.get()}")

    config_combo.bind("<<ComboboxSelected>>", on_config_change)

    def config_action(action: str):
        current = config_manager.active_config_name
        if action == "new":
            name = simpledialog.askstring("New Config", "Name:", parent=root)
            if name and config_manager.create_config(name.strip()):
                config_manager.active_config_name = name.strip()
                refresh_combo()
                refresh_tree()
        elif action == "dup":
            name = simpledialog.askstring("Duplicate", f"Copy of '{current}':", parent=root)
            if name and config_manager.duplicate_config(current, name.strip()):
                config_manager.active_config_name = name.strip()
                refresh_combo()
                refresh_tree()
        elif action == "rename":
            name = simpledialog.askstring("Rename", "New name:", initialvalue=current, parent=root)
            if name and name.strip() != current and config_manager.rename_config(current, name.strip()):
                refresh_combo()
        elif action == "delete":
            if len(config_manager.config_names) <= 1:
                messagebox.showerror("Error", "Cannot delete last config")
            elif messagebox.askyesno("Delete", f"Delete '{current}'?"):
                config_manager.delete_config(current)
                refresh_combo()
                refresh_tree()

    for txt, act in [("New", "new"), ("Duplicate", "dup"), ("Rename", "rename"), ("Delete", "delete")]:
        ttk.Button(cfg_sel, text=txt, command=lambda a=act: config_action(a)).pack(side=tk.LEFT, padx=2)

    # --- Strip toggle ---
    strip_var = tk.BooleanVar(value=config_manager.strip_textures)

    def on_strip():
        config_manager.strip_textures = strip_var.get()

    ttk.Checkbutton(
        main, text="Enable Default No Textures (Stripper)", variable=strip_var, command=on_strip
    ).pack(anchor=tk.W, pady=(0, 10))

    # --- Rules tree ---
    ttk.Label(main, text="Hash Replacement Profiles:", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
    list_frame = ttk.Frame(main)
    list_frame.pack(fill=tk.BOTH, expand=True, pady=5)

    columns = ("name", "action", "hash", "file")
    tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=8)
    for col, txt, w in [
        ("name", "Profile Name", 150),
        ("action", "Action", 80),
        ("hash", "Target Hash", 200),
        ("file", "File (in FleasionAssets)", 200),
    ]:
        tree.heading(col, text=txt)
        tree.column(col, width=w)

    scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def refresh_tree():
        tree.delete(*tree.get_children())
        for i, rule in enumerate(config_manager.replacement_rules):
            name = rule.get("name", f"Profile {i + 1}")
            is_rm = rule.get("remove", False)
            fpath = rule.get("replacement_file", "")
            
            tree.insert(
                "", tk.END, iid=str(i),
                values=(
                    name,
                    "Remove" if is_rm else "Replace",
                    rule.get("target_hash", ""),
                    "-" if is_rm else fpath,
                ),
            )

    refresh_tree()

    # --- Edit frame ---
    edit = ttk.LabelFrame(main, text="Add/Edit Hash Rule", padding=10)
    edit.pack(fill=tk.X, pady=10)

    ttk.Label(edit, text="Profile Name:").grid(row=0, column=0, sticky=tk.W, pady=2)
    name_entry = ttk.Entry(edit, width=40)
    name_entry.grid(row=0, column=1, padx=5, pady=2, sticky=tk.W)

    action_frame = ttk.Frame(edit)
    action_frame.grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(10, 5))
    action_var = tk.StringVar(value="replace")

    def update_input_state():
        state = tk.DISABLED if action_var.get() == "remove" else tk.NORMAL
        file_entry.config(state=state)
        browse_btn.config(state=state)

    ttk.Label(action_frame, text="Action:").pack(side=tk.LEFT)
    for txt, val in [("Replace Content", "replace"), ("Block/Remove", "remove")]:
        ttk.Radiobutton(
            action_frame, text=txt, variable=action_var, value=val,
            command=update_input_state,
        ).pack(side=tk.LEFT, padx=(10, 5))

    ttk.Label(edit, text="Target Hash (32 chars):").grid(row=2, column=0, sticky=tk.W, pady=2)
    hash_entry = ttk.Entry(edit, width=60)
    hash_entry.grid(row=2, column=1, padx=5, pady=2, sticky=tk.EW)

    ttk.Label(edit, text="Replacement File:").grid(row=3, column=0, sticky=tk.W, pady=2)
    
    file_frame = ttk.Frame(edit)
    file_frame.grid(row=3, column=1, padx=5, pady=2, sticky=tk.EW)
    
    file_entry = ttk.Entry(file_frame)
    file_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def browse_file():
        # Ensure the assets dir exists
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        
        filename = filedialog.askopenfilename(
            parent=root,
            title="Import Replacement File",
            filetypes=[("Image Files", "*.png;*.jpg;*.jpeg;*.tga"), ("All Files", "*.*")]
        )
        if filename:
            try:
                # Copy file to local assets folder
                src = Path(filename)
                dest = ASSETS_DIR / src.name
                shutil.copy2(src, dest)
                
                # Update entry with JUST the filename, not the full path
                file_entry.delete(0, tk.END)
                file_entry.insert(0, src.name)
                log("Import", f"Imported {src.name} to FleasionAssets folder")
            except Exception as e:
                messagebox.showerror("Import Error", f"Failed to copy file:\n{e}")

    browse_btn = ttk.Button(file_frame, text="Import to Assets", command=browse_file)
    browse_btn.pack(side=tk.LEFT, padx=(5, 0))
    
    edit.columnconfigure(1, weight=1)

    def clear_entries():
        name_entry.delete(0, tk.END)
        hash_entry.delete(0, tk.END)
        file_entry.delete(0, tk.END)
        action_var.set("replace")
        update_input_state()

    def get_rule_from_entries() -> dict | None:
        target = hash_entry.get().strip()
        if not target:
            messagebox.showerror("Error", "Enter the Target Hash")
            return None
        
        is_rm = action_var.get() == "remove"
        rule = {
            "name": name_entry.get().strip() or f"Hash Rule {len(config_manager.replacement_rules) + 1}",
            "target_hash": target,
            "remove": is_rm,
        }
        
        if not is_rm:
            # We assume the user used the Browse button, so the file is in ASSETS_DIR
            # or they typed a filename that exists there.
            val = file_entry.get().strip()
            # If they pasted a full path, strip it to filename and warn if not imported
            if "\\" in val or "/" in val:
                 val = Path(val).name
                 
            if not val:
                 messagebox.showerror("Error", "Select a replacement file")
                 return None
                 
            if not (ASSETS_DIR / val).exists():
                 messagebox.showwarning("Warning", f"File '{val}' not found in FleasionAssets folder.\nPlease use 'Import to Assets'.")
                 
            rule["replacement_file"] = val
                
        return rule

    def add_rule():
        if rule := get_rule_from_entries():
            rules = config_manager.replacement_rules.copy()
            rules.append(rule)
            config_manager.replacement_rules = rules
            refresh_tree()
            clear_entries()
            log("Config", f"Added hash rule: {rule['target_hash'][:8]}...")

    def load_selected():
        if not (sel := tree.selection()):
            return
        rule = config_manager.replacement_rules[int(sel[0])]
        clear_entries()
        name_entry.insert(0, rule.get("name", ""))
        hash_entry.insert(0, rule.get("target_hash", ""))
        if rule.get("remove"):
            action_var.set("remove")
            update_input_state()
        else:
            file_entry.insert(0, rule.get("replacement_file", ""))

    def update_selected():
        if not (sel := tree.selection()):
            return
        if rule := get_rule_from_entries():
            rules = config_manager.replacement_rules.copy()
            rules[int(sel[0])] = rule
            config_manager.replacement_rules = rules
            refresh_tree()
            clear_entries()

    def delete_selected():
        if not (sel := tree.selection()):
            return
        rules = config_manager.replacement_rules.copy()
        rules.pop(int(sel[0]))
        config_manager.replacement_rules = rules
        refresh_tree()

    btn_frame = ttk.Frame(edit)
    btn_frame.grid(row=4, column=0, columnspan=2, pady=(10, 0))
    for txt, cmd in [
        ("Add New", add_rule),
        ("Load Selected", load_selected),
        ("Update Selected", update_selected),
        ("Delete Selected", delete_selected),
    ]:
        ttk.Button(btn_frame, text=txt, command=cmd).pack(side=tk.LEFT, padx=2)

    # --- Footer ---
    footer = ttk.Frame(main)
    footer.pack(fill=tk.X, pady=(10, 0))
    ttk.Label(footer, text=f"Config: {CONFIG_FILE}", font=("Consolas", 8), foreground="gray").pack(side=tk.LEFT)
    
    def open_assets_folder():
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(["explorer", str(ASSETS_DIR)])

    ttk.Button(
        footer, text="Open Assets Folder", command=open_assets_folder
    ).pack(side=tk.RIGHT, padx=(10, 0))

    root.mainloop()


# --- Proxy ---


async def run_proxy():
    global proxy_running

    if terminate_roblox():
        log("Cleanup", "Roblox found, terminating...")
        if not wait_for_roblox_exit():
            log("Cleanup", "Termination timed out")
        else:
            log("Cleanup", "Roblox terminated")
            try:
                STORAGE_DB.unlink()
                log("Cleanup", "Storage deleted")
            except (FileNotFoundError, PermissionError, OSError) as e:
                log("Cleanup", f"Storage deletion: {e}")
    else:
        log("Cleanup", "Roblox not running")

    master = DumpMaster(
        Options(mode=[f"local:{ROBLOX_PROCESS}"]), with_termlog=False, with_dumper=False
    )
    master.addons.add(TextureStripper())
    proxy_task = asyncio.create_task(master.run())

    if not await wait_for_cert_install():
        log("Certificate", "Installation failed")
        return

    log_buffer.extend([
        "=" * 50,
        "[Info] Hash-Based Proxy Active",
        f"[Info] Assets Dir: {ASSETS_DIR}",
        "[Info] Ready for Universal Configs",
        "=" * 50,
    ])
    proxy_running = True
    await proxy_task


def run_proxy_thread():
    try:
        asyncio.run(run_proxy())
    except Exception as e:
        log("Error", f"Proxy failed: {e}")
        ctypes.windll.user32.MessageBoxW(0, f"Proxy startup failed:\n{e}", "Error", 0x10)
        if tray_icon:
            tray_icon.stop()


def main():
    global tray_icon, config_manager
    config_manager = ConfigManager()
    threading.Thread(target=run_proxy_thread, daemon=True).start()

    tray_icon = pystray.Icon(
        APP_NAME,
        get_icon_image(),
        f"{APP_NAME} - Running",
        pystray.Menu(
            pystray.MenuItem(f"{APP_NAME} v{APP_VERSION}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("About", lambda: show_about()),
            pystray.MenuItem("View Logs", lambda: show_logs()),
            pystray.MenuItem("Replacer Config", lambda: show_replacer_config()),
            pystray.MenuItem("Delete Cache", lambda: show_delete_cache_result()),
            pystray.MenuItem("Copy Discord Invite", lambda: copy_discord()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", lambda: tray_icon.stop()),
        ),
    )
    tray_icon.run()


if __name__ == "__main__":
    main()