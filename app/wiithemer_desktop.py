#!/usr/bin/env python3
"""WiiThemer Desktop - a cross-platform GUI port of WiiThemer
(https://github.com/scooby7402976/wiithemer, GPL-2.0).

Builds Wii System Menu theme files (.csm) from .mym theme mods, the same way
the wiithemer.org site does, and lets you customize every part of it: the
theme source, version/region, spin mod, file naming, the build pipeline
itself, the catalog, the tools, and the look of the app.
"""

import copy
import io
import json
import os
import platform
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback
import urllib.request
import zipfile
import tkinter as tk
from tkinter import colorchooser, filedialog, font as tkfont, messagebox, ttk

APP_NAME = "WiiThemer Desktop"
APP_VERSION = "1.0.0"

try:
    from PIL import Image, ImageTk
except Exception:  # Pillow is optional; previews are skipped without it
    Image = ImageTk = None


def resource_dir():
    """Folder holding bundled data (works from source and from PyInstaller)."""
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def config_dir():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    path = os.path.join(base, "WiiThemerDesktop")
    os.makedirs(path, exist_ok=True)
    return path


SETTINGS_FILE = os.path.join(config_dir(), "settings.json")
CACHE_DIR = os.path.join(config_dir(), "cache")

# System Menu versions, straight from wiithemer's getappndisplayname().
# Key: "<version><region>", value: content id of the System Menu .app.
VERSIONS = {
    "4.3U": "97", "4.2U": "87", "4.1U": "7b", "4.0U": "72",
    "4.3E": "9a", "4.2E": "8a", "4.1E": "7e", "4.0E": "75",
    "4.3J": "94", "4.2J": "84", "4.1J": "78", "4.0J": "70",
    "4.3K": "9d", "4.2K": "8d", "4.1K": "81",
}

# Themes wiithemer applies with the spin mod first.
RUN_FIRST = ["black_pirate.mym", "matrix.mym", "matrix_reloaded.mym", "muse.mym"]

DEFAULT_PIPELINE = {
    "normal": [
        "{themewii} {appid} {key}",
        "{themewii} {theme} {appid} 000000{appid}.app {key}",
        "{themewii} {spin} {appid}.app {output} {key}",
    ],
    "run_first": [
        "{themewii} {appid} {key}",
        "{themewii} {spin} {appid} 000000{appid}.app {key}",
        "{themewii} {theme} {appid}.app {output} {key}",
    ],
}

DEFAULT_SETTINGS = {
    "appearance": {
        "ttk_theme": "clam",
        "font_family": "Helvetica",
        "font_size": 11,
        "bg": "#1e1f26",
        "fg": "#e8e8ee",
        "accent": "#34b6e8",
        "accent_fg": "#0b1016",
        "field_bg": "#2a2c36",
        "select_bg": "#34b6e8",
        "preview_size": 360,
        "window_geometry": "1100x720",
        "window_title": APP_NAME,
    },
    "build": {
        "version": "4.3",
        "region": "U",
        "spin": "nospin",
        "output_dir": os.path.join(os.path.expanduser("~"), "WiiThemer"),
        "filename_template": "{theme_name}{display}{spin_suffix}.csm",
        "keep_work_dir": False,
        "save_base_app": False,
        "base_app_path": "",
        "run_first_override": "auto",
        "pipeline": copy.deepcopy(DEFAULT_PIPELINE),
        "extra_versions": {},
    },
    "tools": {
        "themewii_path": "",
        "wine_command": "wine",
        "key": "wiithemer_______Scooby74029",
        "use_wine_on_windows": False,
        "timeout_seconds": 600,
    },
    "catalog": {
        "base_url": "https://raw.githubusercontent.com/scooby7402976/wiithemer/1.0/",
        "mym_path": "mym/",
        "preview_path": "previewpics/",
        "custom_themes": [],
        "hidden_themes": [],
    },
}


def deep_merge(base, override):
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return deep_merge(DEFAULT_SETTINGS, json.load(f))
    except Exception:
        return copy.deepcopy(DEFAULT_SETTINGS)


def save_settings(settings):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


def load_catalog():
    with open(os.path.join(resource_dir(), "catalog.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def download(url, dest, log=None):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest
    if log:
        log(f"Downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
    tmp = dest + ".part"
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    os.replace(tmp, dest)
    return dest


class Builder:
    """Runs the themewii pipeline. Mirrors wiithemer's index.php build steps."""

    def __init__(self, settings, log):
        self.s = settings
        self.log = log

    def themewii_dir(self):
        custom = self.s["tools"]["themewii_path"]
        if custom:
            return os.path.dirname(custom), os.path.basename(custom)
        return os.path.join(resource_dir(), "tools"), "themewii.exe"

    def command_prefix(self, exe):
        tools = self.s["tools"]
        if sys.platform == "win32" and not tools["use_wine_on_windows"]:
            return [exe]
        wine = tools["wine_command"].split()
        if not wine or not shutil.which(wine[0]):
            raise RuntimeError(
                "themewii.exe is a Windows program. Install Wine (with wine-mono) "
                "or set the Wine command in Settings > Tools.\n"
                "macOS: brew install --cask wine-stable\n"
                "Linux: sudo apt install wine")
        return wine + [exe]

    def build(self, theme_file, theme_label, version, region, spin):
        b, tools = self.s["build"], self.s["tools"]
        display = version + region
        versions = dict(VERSIONS, **b.get("extra_versions", {}))
        if display not in versions:
            raise RuntimeError(f"System Menu {display} is not a known version.")
        appid = versions[display]

        work = tempfile.mkdtemp(prefix="wiithemer_")
        self.log(f"Work folder: {work}")
        tdir, exe = self.themewii_dir()
        for name in os.listdir(tdir):
            src = os.path.join(tdir, name)
            if os.path.isfile(src):
                shutil.copy2(src, work)

        theme_name = os.path.basename(theme_file)
        shutil.copy2(theme_file, os.path.join(work, theme_name))
        spin_name = spin + ".mym"
        spin_src = spin if os.path.isfile(spin) else os.path.join(resource_dir(), "spins", spin_name)
        spin_name = os.path.basename(spin_src)
        shutil.copy2(spin_src, os.path.join(work, spin_name))

        noext = os.path.splitext(theme_name)[0]
        output = b["filename_template"].format(
            theme_name=noext, theme_label=theme_label, display=display,
            version=version, region=region, appid=appid, spin=spin,
            spin_suffix="_" + os.path.splitext(os.path.basename(spin))[0])

        if b["base_app_path"]:
            self.log(f"Using your own System Menu file: {b['base_app_path']}")
            shutil.copy2(b["base_app_path"], os.path.join(work, "000000" + appid))

        mode = b["run_first_override"]
        run_first = theme_name.lower() in RUN_FIRST if mode == "auto" else mode == "yes"
        steps = b["pipeline"]["run_first" if run_first else "normal"]
        prefix = self.command_prefix(exe)
        values = dict(theme=theme_name, spin=spin_name, appid=appid, output=output,
                      key=tools["key"], display=display, version=version, region=region)

        for i, step in enumerate(steps, 1):
            parts = step.split()
            if not parts:
                continue
            if parts[0] == "{themewii}" and parts[1:2] == ["{appid}"] and \
                    os.path.exists(os.path.join(work, "000000" + appid)):
                self.log(f"Step {i}: System Menu file already present, skipping download")
                continue
            args = [p.format(**values) for p in parts[1:]] if parts[0] == "{themewii}" \
                else [p.format(**values) for p in parts]
            cmd = prefix + args if parts[0] == "{themewii}" else args
            self.log(f"Step {i}: {' '.join(cmd)}")
            proc = subprocess.run(cmd, cwd=work, capture_output=True, text=True,
                                  timeout=tools["timeout_seconds"])
            for line in (proc.stdout + proc.stderr).splitlines():
                self.log("    " + line)
            if proc.returncode != 0:
                raise RuntimeError(f"Step {i} failed with exit code {proc.returncode}")

        result = os.path.join(work, output)
        if not os.path.exists(result) or os.path.getsize(result) == 0:
            raise RuntimeError(f"Build finished but {output} was not created.")
        os.makedirs(b["output_dir"], exist_ok=True)
        final = os.path.join(b["output_dir"], output)
        shutil.copy2(result, final)
        if b["save_base_app"]:
            base = os.path.join(work, "000000" + appid)
            if os.path.exists(base):
                shutil.copy2(base, os.path.join(b["output_dir"], f"000000{appid}.app"))
        if not b["keep_work_dir"]:
            shutil.rmtree(work, ignore_errors=True)
        return final


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.catalog = load_catalog()
        self.msgs = queue.Queue()
        self.preview_img = None
        self.mym = None  # MYM editor state: {"path", "entries": {name: bytes}}
        self.apply_appearance()
        self.build_ui()
        self.refresh_theme_list()
        self.after(100, self.drain)

    # ---------- appearance ----------
    def apply_appearance(self):
        a = self.settings["appearance"]
        self.title(a["window_title"])
        self.geometry(a["window_geometry"])
        self.configure(bg=a["bg"])
        st = ttk.Style(self)
        if a["ttk_theme"] in st.theme_names():
            st.theme_use(a["ttk_theme"])
        f = (a["font_family"], int(a["font_size"]))
        for name in ("TkDefaultFont", "TkTextFont", "TkHeadingFont", "TkMenuFont"):
            try:
                tkfont.nametofont(name).configure(family=a["font_family"], size=int(a["font_size"]))
            except tk.TclError:
                pass
        st.configure(".", background=a["bg"], foreground=a["fg"], font=f,
                     fieldbackground=a["field_bg"], insertcolor=a["fg"])
        st.configure("TButton", background=a["field_bg"], foreground=a["fg"], padding=6)
        st.map("TButton", background=[("active", a["accent"])],
               foreground=[("active", a["accent_fg"])])
        st.configure("Accent.TButton", background=a["accent"], foreground=a["accent_fg"])
        st.configure("TNotebook", background=a["bg"])
        st.configure("TNotebook.Tab", background=a["field_bg"], foreground=a["fg"], padding=(12, 6))
        st.map("TNotebook.Tab", background=[("selected", a["accent"])],
               foreground=[("selected", a["accent_fg"])])
        st.configure("Treeview", background=a["field_bg"], fieldbackground=a["field_bg"],
                     foreground=a["fg"])
        st.map("Treeview", background=[("selected", a["select_bg"])],
               foreground=[("selected", a["accent_fg"])])
        st.configure("TEntry", fieldbackground=a["field_bg"], foreground=a["fg"])
        st.configure("TCombobox", fieldbackground=a["field_bg"], foreground=a["fg"])
        st.configure("Header.TLabel", font=(a["font_family"], int(a["font_size"]) + 6, "bold"),
                     foreground=a["accent"])
        self.text_opts = dict(bg=a["field_bg"], fg=a["fg"], insertbackground=a["fg"],
                              selectbackground=a["select_bg"], relief="flat",
                              font=("Courier", int(a["font_size"])))

    # ---------- layout ----------
    def build_ui(self):
        for w in self.winfo_children():
            w.destroy()
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        self.nb = nb
        nb.add(self.build_tab(nb), text="Build Theme")
        nb.add(self.mym_tab(nb), text="MYM Editor")
        nb.add(self.catalog_tab(nb), text="Catalog")
        nb.add(self.settings_tab(nb), text="Settings")
        nb.add(self.raw_tab(nb), text="Advanced (JSON)")

        logf = ttk.Frame(self)
        logf.pack(fill="x", padx=8, pady=(0, 8))
        self.log_box = tk.Text(logf, height=8, **self.text_opts)
        self.log_box.pack(fill="x")
        self.log(f"{APP_NAME} {APP_VERSION} on {platform.system()} - settings: {SETTINGS_FILE}")

    def build_tab(self, parent):
        b = self.settings["build"]
        f = ttk.Frame(parent, padding=10)
        left = ttk.Frame(f)
        left.pack(side="left", fill="y")
        ttk.Label(left, text="Themes", style="Header.TLabel").pack(anchor="w")
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self.refresh_theme_list())
        ttk.Entry(left, textvariable=self.search).pack(fill="x", pady=4)
        self.theme_tree = ttk.Treeview(left, columns=("src",), show="tree headings", height=18)
        self.theme_tree.heading("#0", text="Name")
        self.theme_tree.heading("src", text="Source")
        self.theme_tree.column("#0", width=220)
        self.theme_tree.column("src", width=80)
        self.theme_tree.pack(fill="y", expand=True)
        self.theme_tree.bind("<<TreeviewSelect>>", lambda e: self.on_theme_select())
        row = ttk.Frame(left)
        row.pack(fill="x", pady=4)
        ttk.Button(row, text="Open .mym…", command=self.add_local_theme).pack(side="left")
        ttk.Button(row, text="Add URL…", command=self.add_url_theme).pack(side="left", padx=4)

        right = ttk.Frame(f, padding=(16, 0))
        right.pack(side="left", fill="both", expand=True)
        self.theme_title = ttk.Label(right, text="Pick a theme", style="Header.TLabel")
        self.theme_title.pack(anchor="w")
        self.preview = ttk.Label(right)
        self.preview.pack(anchor="w", pady=8)

        opts = ttk.Frame(right)
        opts.pack(anchor="w", fill="x")
        self.v_version = tk.StringVar(value=b["version"])
        self.v_region = tk.StringVar(value=b["region"])
        self.v_spin = tk.StringVar(value=b["spin"])
        self.v_runfirst = tk.StringVar(value=b["run_first_override"])
        grid = [
            ("System Menu version", self.v_version, ["4.3", "4.2", "4.1", "4.0"]),
            ("Region", self.v_region, ["U", "E", "J", "K"]),
            ("Channel spin", self.v_spin, ["nospin", "spin", "fastspin", "transchan"]),
            ("Apply spin first", self.v_runfirst, ["auto", "yes", "no"]),
        ]
        for r, (label, var, values) in enumerate(grid):
            ttk.Label(opts, text=label).grid(row=r, column=0, sticky="w", pady=3)
            ttk.Combobox(opts, textvariable=var, values=values, width=14).grid(
                row=r, column=1, sticky="w", padx=8)
        self.v_outdir = tk.StringVar(value=b["output_dir"])
        ttk.Label(opts, text="Save to").grid(row=4, column=0, sticky="w", pady=3)
        ttk.Entry(opts, textvariable=self.v_outdir, width=40).grid(row=4, column=1, sticky="w", padx=8)
        ttk.Button(opts, text="…", width=3, command=lambda: self.pick_dir(self.v_outdir)).grid(row=4, column=2)
        self.v_base = tk.StringVar(value=b["base_app_path"])
        ttk.Label(opts, text="Own System Menu .app\n(optional)").grid(row=5, column=0, sticky="w", pady=3)
        ttk.Entry(opts, textvariable=self.v_base, width=40).grid(row=5, column=1, sticky="w", padx=8)
        ttk.Button(opts, text="…", width=3, command=lambda: self.pick_file(self.v_base)).grid(row=5, column=2)

        ttk.Button(right, text="Build theme", style="Accent.TButton",
                   command=self.start_build).pack(anchor="w", pady=12)
        ttk.Label(right, wraplength=520, text=(
            "Install the resulting .csm with a theme installer on a softmodded Wii "
            "(always keep a NAND backup and Priiloader). On macOS/Linux the build "
            "runs themewii.exe through Wine.")).pack(anchor="w")
        return f

    def mym_tab(self, parent):
        f = ttk.Frame(parent, padding=10)
        bar = ttk.Frame(f)
        bar.pack(fill="x")
        for label, cmd in [("Open .mym", self.mym_open), ("New", self.mym_new),
                           ("Add/replace file", self.mym_add), ("Extract", self.mym_extract),
                           ("Delete", self.mym_delete), ("Save text", self.mym_save_text),
                           ("Save .mym as…", self.mym_save)]:
            ttk.Button(bar, text=label, command=cmd).pack(side="left", padx=2)
        self.mym_label = ttk.Label(f, text="No file open")
        self.mym_label.pack(anchor="w", pady=4)
        body = ttk.Frame(f)
        body.pack(fill="both", expand=True)
        self.mym_tree = ttk.Treeview(body, columns=("size",), show="tree headings")
        self.mym_tree.heading("#0", text="File")
        self.mym_tree.heading("size", text="Bytes")
        self.mym_tree.column("size", width=90)
        self.mym_tree.pack(side="left", fill="y")
        self.mym_tree.bind("<<TreeviewSelect>>", lambda e: self.mym_show())
        self.mym_text = tk.Text(body, **self.text_opts)
        self.mym_text.pack(side="left", fill="both", expand=True, padx=(8, 0))
        return f

    def catalog_tab(self, parent):
        c = self.settings["catalog"]
        f = ttk.Frame(parent, padding=10)
        ttk.Label(f, text="Theme catalog", style="Header.TLabel").pack(anchor="w")
        ttk.Label(f, wraplength=800, text=(
            "Built-in themes are downloaded on demand from the original WiiThemer "
            "repository. Point the base URL at a fork or your own server to use a "
            "different theme library. Uncheck themes to hide them.")).pack(anchor="w", pady=4)
        self.v_base_url = tk.StringVar(value=c["base_url"])
        ttk.Entry(f, textvariable=self.v_base_url, width=80).pack(anchor="w")
        self.cat_tree = ttk.Treeview(f, columns=("file", "shown"), show="tree headings")
        self.cat_tree.heading("#0", text="Name")
        self.cat_tree.heading("file", text="File")
        self.cat_tree.heading("shown", text="Shown")
        self.cat_tree.pack(fill="both", expand=True, pady=6)
        for t in self.all_themes():
            shown = "no" if t["name"] in c["hidden_themes"] else "yes"
            self.cat_tree.insert("", "end", iid=t["name"], text=t["name"], values=(t["file"], shown))
        row = ttk.Frame(f)
        row.pack(fill="x")
        ttk.Button(row, text="Show/hide selected", command=self.toggle_hidden).pack(side="left")
        ttk.Button(row, text="Remove custom theme", command=self.remove_custom).pack(side="left", padx=4)
        ttk.Button(row, text="Clear download cache", command=self.clear_cache).pack(side="left")
        ttk.Button(row, text="Apply", style="Accent.TButton", command=self.apply_catalog).pack(side="right")
        return f

    def settings_tab(self, parent):
        a, b, t = self.settings["appearance"], self.settings["build"], self.settings["tools"]
        f = ttk.Frame(parent, padding=10)
        self.setting_vars = {}

        def section(title, row):
            ttk.Label(f, text=title, style="Header.TLabel").grid(row=row, column=0, sticky="w", pady=(10, 2))

        def field(group, key, label, row, kind="entry", values=None):
            src = self.settings[group][key]
            var = tk.BooleanVar(value=src) if kind == "check" else tk.StringVar(value=str(src))
            self.setting_vars[(group, key)] = var
            ttk.Label(f, text=label).grid(row=row, column=0, sticky="w")
            if kind == "check":
                ttk.Checkbutton(f, variable=var).grid(row=row, column=1, sticky="w")
            elif kind == "combo":
                ttk.Combobox(f, textvariable=var, values=values, width=30).grid(row=row, column=1, sticky="w")
            else:
                ttk.Entry(f, textvariable=var, width=46).grid(row=row, column=1, sticky="w")
            if kind == "color":
                ttk.Button(f, text="Pick", command=lambda: self.pick_color(var)).grid(row=row, column=2)

        r = 0
        section("Appearance", r); r += 1
        field("appearance", "ttk_theme", "Widget style", r, "combo", ttk.Style(self).theme_names()); r += 1
        field("appearance", "font_family", "Font", r, "combo", sorted(set(tkfont.families()))); r += 1
        field("appearance", "font_size", "Font size", r); r += 1
        for key, label in [("bg", "Background"), ("fg", "Text"), ("accent", "Accent"),
                           ("accent_fg", "Text on accent"), ("field_bg", "Fields"),
                           ("select_bg", "Selection")]:
            field("appearance", key, label, r, "color"); r += 1
        field("appearance", "preview_size", "Preview width (px)", r); r += 1
        field("appearance", "window_title", "Window title", r); r += 1
        section("Build", r); r += 1
        field("build", "filename_template", "Output file name", r); r += 1
        ttk.Label(f, text="  variables: {theme_name} {theme_label} {display} {version} {region} {appid} {spin} {spin_suffix}"
                  ).grid(row=r, column=0, columnspan=3, sticky="w"); r += 1
        field("build", "keep_work_dir", "Keep work folder", r, "check"); r += 1
        field("build", "save_base_app", "Also save System Menu .app", r, "check"); r += 1
        section("Tools", r); r += 1
        field("tools", "themewii_path", "Custom themewii.exe", r); r += 1
        field("tools", "wine_command", "Wine command", r); r += 1
        field("tools", "use_wine_on_windows", "Use Wine on Windows", r, "check"); r += 1
        field("tools", "key", "themewii key argument", r); r += 1
        field("tools", "timeout_seconds", "Step timeout (s)", r); r += 1

        row = ttk.Frame(f)
        row.grid(row=r, column=0, columnspan=3, sticky="w", pady=12)
        ttk.Button(row, text="Apply", style="Accent.TButton", command=self.apply_settings).pack(side="left")
        ttk.Button(row, text="Import…", command=self.import_settings).pack(side="left", padx=4)
        ttk.Button(row, text="Export…", command=self.export_settings).pack(side="left")
        ttk.Button(row, text="Reset to defaults", command=self.reset_settings).pack(side="left", padx=4)
        return f

    def raw_tab(self, parent):
        f = ttk.Frame(parent, padding=10)
        ttk.Label(f, wraplength=900, text=(
            "Every setting, including the build pipeline (the exact themewii commands run "
            "for each build), extra System Menu versions (\"extra_versions\": {\"4.3X\": \"ab\"}), "
            "custom themes and the catalog paths. Edit and press Save.")).pack(anchor="w")
        self.raw_text = tk.Text(f, **self.text_opts)
        self.raw_text.pack(fill="both", expand=True, pady=6)
        self.raw_text.insert("1.0", json.dumps(self.settings, indent=2))
        row = ttk.Frame(f)
        row.pack(fill="x")
        ttk.Button(row, text="Save", style="Accent.TButton", command=self.save_raw).pack(side="left")
        ttk.Button(row, text="Restore default pipeline", command=self.default_pipeline).pack(side="left", padx=4)
        return f

    # ---------- helpers ----------
    def log(self, text):
        self.msgs.put(("log", text))

    def drain(self):
        try:
            while True:
                kind, payload = self.msgs.get_nowait()
                if kind == "log":
                    self.log_box.insert("end", payload + "\n")
                    self.log_box.see("end")
                elif kind == "preview":
                    self.show_preview(payload)
                elif kind == "done":
                    messagebox.showinfo(APP_NAME, f"Theme built:\n{payload}")
                elif kind == "error":
                    messagebox.showerror(APP_NAME, payload)
        except queue.Empty:
            pass
        self.after(100, self.drain)

    def persist(self):
        save_settings(self.settings)

    def rebuild(self):
        self.persist()
        self.apply_appearance()
        self.build_ui()
        self.refresh_theme_list()

    def pick_dir(self, var):
        d = filedialog.askdirectory(initialdir=var.get() or None)
        if d:
            var.set(d)

    def pick_file(self, var):
        p = filedialog.askopenfilename()
        if p:
            var.set(p)

    def pick_color(self, var):
        c = colorchooser.askcolor(color=var.get())[1]
        if c:
            var.set(c)

    # ---------- themes ----------
    def all_themes(self):
        themes = [dict(t, source="catalog") for t in self.catalog]
        return themes + [dict(t, source=t.get("source", "custom"))
                         for t in self.settings["catalog"]["custom_themes"]]

    def refresh_theme_list(self):
        if not hasattr(self, "theme_tree"):
            return
        q = self.search.get().lower()
        hidden = set(self.settings["catalog"]["hidden_themes"])
        self.theme_tree.delete(*self.theme_tree.get_children())
        for t in self.all_themes():
            if t["name"] in hidden or (q and q not in t["name"].lower()):
                continue
            self.theme_tree.insert("", "end", iid=t["name"], text=t["name"], values=(t["source"],))

    def selected_theme(self):
        sel = self.theme_tree.selection()
        if not sel:
            return None
        return next((t for t in self.all_themes() if t["name"] == sel[0]), None)

    def on_theme_select(self):
        t = self.selected_theme()
        if not t:
            return
        self.theme_title.configure(text=t["name"])
        self.preview.configure(image="", text="")
        if t.get("regions") and len(t["regions"]) < 4:
            self.log(f"{t['name']} is only available for regions: {', '.join(t['regions'])}")
        if t.get("preview"):
            threading.Thread(target=self.fetch_preview, args=(t,), daemon=True).start()

    def fetch_preview(self, t):
        try:
            p = t["preview"]
            if t["source"] == "catalog":
                c = self.settings["catalog"]
                url = c["base_url"] + c["preview_path"] + p
                p = download(url, os.path.join(CACHE_DIR, "previews", t["preview"]))
            self.msgs.put(("preview", p))
        except Exception as e:
            self.log(f"Preview unavailable: {e}")

    def show_preview(self, path):
        if Image is None:
            self.preview.configure(text="(install Pillow for previews)")
            return
        try:
            img = Image.open(path)
            w = int(self.settings["appearance"]["preview_size"])
            img.thumbnail((w, w))
            self.preview_img = ImageTk.PhotoImage(img)
            self.preview.configure(image=self.preview_img)
        except Exception as e:
            self.preview.configure(text=f"(cannot show preview: {e})")

    def add_local_theme(self):
        p = filedialog.askopenfilename(filetypes=[("Theme mod", "*.mym"), ("All files", "*")])
        if not p:
            return
        name = os.path.splitext(os.path.basename(p))[0]
        img = filedialog.askopenfilename(title="Optional preview image (Cancel to skip)",
                                         filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.avif *.webp")])
        self.add_custom({"name": name, "file": p, "preview": img or None, "source": "local"})

    def add_url_theme(self):
        win = tk.Toplevel(self)
        win.title("Add theme from URL")
        win.configure(bg=self.settings["appearance"]["bg"])
        name, url, prev = tk.StringVar(), tk.StringVar(), tk.StringVar()
        for i, (label, var) in enumerate([("Name", name), (".mym URL", url), ("Preview URL", prev)]):
            ttk.Label(win, text=label).grid(row=i, column=0, sticky="w", padx=8, pady=4)
            ttk.Entry(win, textvariable=var, width=60).grid(row=i, column=1, padx=8)

        def ok():
            if name.get() and url.get():
                self.add_custom({"name": name.get(), "file": url.get(),
                                 "preview": prev.get() or None, "source": "url"})
                win.destroy()
        ttk.Button(win, text="Add", style="Accent.TButton", command=ok).grid(row=3, column=1, sticky="e", pady=8)

    def add_custom(self, theme):
        customs = self.settings["catalog"]["custom_themes"]
        customs[:] = [t for t in customs if t["name"] != theme["name"]] + [theme]
        self.persist()
        self.refresh_theme_list()
        self.log(f"Added theme {theme['name']}")

    def resolve_theme_file(self, t, region):
        src, f = t["source"], t["file"]
        if src == "local":
            return f
        if src == "url" or "://" in f:
            return download(f, os.path.join(CACHE_DIR, "url", os.path.basename(f.split("?")[0])), self.log)
        if "{r}" in f:
            if region not in t.get("regions", []):
                raise RuntimeError(f"{t['name']} is not available for region {region}.")
            f = f.replace("{r}", region.lower())
        c = self.settings["catalog"]
        return download(c["base_url"] + c["mym_path"] + urllib.request.quote(f),
                        os.path.join(CACHE_DIR, "mym", f), self.log)

    def start_build(self):
        t = self.selected_theme()
        if not t:
            messagebox.showwarning(APP_NAME, "Select a theme first.")
            return
        b = self.settings["build"]
        b.update(version=self.v_version.get(), region=self.v_region.get(), spin=self.v_spin.get(),
                 run_first_override=self.v_runfirst.get(), output_dir=self.v_outdir.get(),
                 base_app_path=self.v_base.get())
        self.persist()
        settings = copy.deepcopy(self.settings)

        def work():
            try:
                path = self.resolve_theme_file(t, b["region"])
                out = Builder(settings, self.log).build(path, t["name"], b["version"], b["region"], b["spin"])
                self.log(f"Done: {out}")
                self.msgs.put(("done", out))
            except Exception as e:
                self.log(traceback.format_exc())
                self.msgs.put(("error", str(e)))
        self.log(f"Building {t['name']} for {b['version']}{b['region']} ({b['spin']})…")
        threading.Thread(target=work, daemon=True).start()

    # ---------- catalog tab ----------
    def toggle_hidden(self):
        hidden = self.settings["catalog"]["hidden_themes"]
        for name in self.cat_tree.selection():
            if name in hidden:
                hidden.remove(name)
            else:
                hidden.append(name)
            self.cat_tree.set(name, "shown", "no" if name in hidden else "yes")
        self.persist()
        self.refresh_theme_list()

    def remove_custom(self):
        names = set(self.cat_tree.selection())
        customs = self.settings["catalog"]["custom_themes"]
        customs[:] = [t for t in customs if t["name"] not in names]
        self.rebuild()

    def clear_cache(self):
        shutil.rmtree(CACHE_DIR, ignore_errors=True)
        self.log("Download cache cleared")

    def apply_catalog(self):
        url = self.v_base_url.get().strip()
        self.settings["catalog"]["base_url"] = url if url.endswith("/") else url + "/"
        self.persist()
        self.log("Catalog settings saved")

    # ---------- settings ----------
    def apply_settings(self):
        for (group, key), var in self.setting_vars.items():
            old = DEFAULT_SETTINGS[group][key]
            val = var.get()
            if isinstance(old, int) and not isinstance(old, bool):
                try:
                    val = int(val)
                except ValueError:
                    messagebox.showerror(APP_NAME, f"{key} must be a number")
                    return
            self.settings[group][key] = val
        self.settings["appearance"]["window_geometry"] = self.geometry()
        self.rebuild()

    def import_settings(self):
        p = filedialog.askopenfilename(filetypes=[("Settings", "*.json")])
        if p:
            with open(p, "r", encoding="utf-8") as f:
                self.settings = deep_merge(DEFAULT_SETTINGS, json.load(f))
            self.rebuild()

    def export_settings(self):
        p = filedialog.asksaveasfilename(defaultextension=".json", initialfile="wiithemer-settings.json")
        if p:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2)

    def reset_settings(self):
        if messagebox.askyesno(APP_NAME, "Reset every setting to its default?"):
            self.settings = copy.deepcopy(DEFAULT_SETTINGS)
            self.rebuild()

    def save_raw(self):
        try:
            data = json.loads(self.raw_text.get("1.0", "end"))
        except json.JSONDecodeError as e:
            messagebox.showerror(APP_NAME, f"Invalid JSON: {e}")
            return
        self.settings = deep_merge(DEFAULT_SETTINGS, data)
        self.rebuild()

    def default_pipeline(self):
        self.settings["build"]["pipeline"] = copy.deepcopy(DEFAULT_PIPELINE)
        self.rebuild()

    # ---------- MYM editor ----------
    def mym_open(self):
        p = filedialog.askopenfilename(filetypes=[("Theme mod", "*.mym"), ("All files", "*")])
        if not p:
            return
        try:
            with zipfile.ZipFile(p) as z:
                entries = {n: z.read(n) for n in z.namelist() if not n.endswith("/")}
        except zipfile.BadZipFile:
            messagebox.showerror(APP_NAME, "That file is not a valid .mym (zip) archive.")
            return
        self.mym = {"path": p, "entries": entries}
        self.mym_refresh()

    def mym_new(self):
        ini = ("[sdta]\n\n[cdta]\n\n; Add [cont1], [cont2]... sections here.\n"
               "; See the MyMenuify docs for the mym.ini format.\n")
        self.mym = {"path": None, "entries": {"mym.ini": ini.encode()}}
        self.mym_refresh()

    def mym_refresh(self):
        self.mym_label.configure(text=self.mym["path"] or "(unsaved .mym)")
        self.mym_tree.delete(*self.mym_tree.get_children())
        for name in sorted(self.mym["entries"]):
            self.mym_tree.insert("", "end", iid=name, text=name, values=(len(self.mym["entries"][name]),))
        self.mym_text.delete("1.0", "end")

    def mym_selected(self):
        sel = self.mym_tree.selection()
        return sel[0] if self.mym and sel else None

    def mym_show(self):
        name = self.mym_selected()
        if not name:
            return
        data = self.mym["entries"][name]
        self.mym_text.delete("1.0", "end")
        if name.lower().endswith((".png", ".jpg", ".jpeg", ".gif")) and Image is not None:
            try:
                img = Image.open(io.BytesIO(data))
                img.thumbnail((480, 480))
                self.mym_img = ImageTk.PhotoImage(img)
                self.mym_text.image_create("1.0", image=self.mym_img)
                return
            except Exception:
                pass
        try:
            self.mym_text.insert("1.0", data.decode("utf-8"))
        except UnicodeDecodeError:
            self.mym_text.insert("1.0", f"(binary file, {len(data)} bytes - use Extract / Add to edit)")

    def mym_add(self):
        if not self.mym:
            self.mym_new()
        paths = filedialog.askopenfilenames()
        sel = self.mym_selected()
        for p in paths:
            # Replacing the selected entry keeps its name; otherwise add by file name.
            name = sel if (sel and len(paths) == 1) else os.path.basename(p)
            with open(p, "rb") as f:
                self.mym["entries"][name] = f.read()
        self.mym_refresh()

    def mym_extract(self):
        name = self.mym_selected()
        if not name:
            return
        p = filedialog.asksaveasfilename(initialfile=os.path.basename(name))
        if p:
            with open(p, "wb") as f:
                f.write(self.mym["entries"][name])

    def mym_delete(self):
        name = self.mym_selected()
        if name:
            del self.mym["entries"][name]
            self.mym_refresh()

    def mym_save_text(self):
        name = self.mym_selected()
        if name:
            self.mym["entries"][name] = self.mym_text.get("1.0", "end-1c").encode("utf-8")
            self.mym_refresh()
            self.mym_tree.selection_set(name)

    def mym_save(self):
        if not self.mym:
            return
        p = filedialog.asksaveasfilename(defaultextension=".mym", filetypes=[("Theme mod", "*.mym")])
        if not p:
            return
        with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in self.mym["entries"].items():
                z.writestr(name, data)
        self.mym["path"] = p
        self.mym_refresh()
        if messagebox.askyesno(APP_NAME, "Add this .mym to your theme list?"):
            self.add_custom({"name": os.path.splitext(os.path.basename(p))[0], "file": p,
                             "preview": None, "source": "local"})


def main():
    if "--selftest" in sys.argv:
        app = App()
        app.update()
        assert len(app.catalog) > 0 and os.path.exists(os.path.join(resource_dir(), "tools", "themewii.exe"))
        print(f"selftest ok: {len(app.catalog)} themes")
        app.destroy()
        return
    App().mainloop()


if __name__ == "__main__":
    main()
