# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 szabiz <szabiz@yahoo.com>
# Copyright (c) 2026 szabiz <szabiz@yahoo.com>
"""VapourSynth environment and plugin probes.

Original project code. Plugins are only inspected and tested in disposable vspipe
processes; this module does not distribute or modify plugin binaries.
"""
import json
import os
import subprocess
import tempfile

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


_PROBE = r'''import json, os, sys
import vapoursynth as vs
core = vs.core
path = os.path.normcase(os.path.realpath(str(globals().get("target", ""))))
outp = str(globals().get("outp", ""))
_dll_handles = []
for d in (os.path.dirname(path), str(globals().get("plugin_root", "") or "")):
    if d and os.path.isdir(d):
        try:
            _dll_handles.append(os.add_dll_directory(d))
        except Exception:
            pass
err = ""
loaded = False
try:
    # If this DLL was loaded by VapourSynth's normal autoloading, don't load it twice.
    for p in core.plugins():
        try:
            if os.path.normcase(os.path.realpath(p.plugin_path)) == path:
                loaded = True
                break
        except Exception:
            pass
    if not loaded:
        core.std.LoadPlugin(path)
        loaded = True
except Exception as e:
    err = str(e)
plugins = []
for p in core.plugins():
    try:
        ppath = os.path.normcase(os.path.realpath(p.plugin_path))
    except Exception:
        ppath = ""
    if ppath != path:
        continue
    funcs = []
    try:
        for f in p.functions():
            if isinstance(f, (tuple, list)):
                name, sig = f[0], f[1]
            else:
                name, sig = f.name, f.signature
            funcs.append([str(name), str(sig)])
    except Exception as e:
        err = err or str(e)
    plugins.append({"namespace": str(getattr(p, "namespace", "")),
                    "name": str(getattr(p, "name", "")),
                    "identifier": str(getattr(p, "identifier", "")),
                    "version": str(getattr(p, "version", "")),
                    "path": str(getattr(p, "plugin_path", "")),
                    "functions": funcs})
try:
    with open(outp, "w", encoding="utf-8") as f:
        json.dump({"loaded": bool(plugins), "error": err, "plugins": plugins}, f)
except Exception:
    pass
core.std.BlankClip(width=16, height=16, length=1, format=vs.YUV420P8).set_output()
'''


def dll_files(root, max_files=3000):
    """Find DLL candidates; finding a DLL does not imply it is a VapourSynth plugin."""
    if not root or not os.path.isdir(root):
        return []
    found = []
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d.lower() not in (".git", "__pycache__"))
        for name in sorted(files):
            if name.lower().endswith(".dll"):
                found.append(os.path.join(base, name))
                if len(found) >= max_files:
                    return found
    return found


def probe_plugin(vspipe, path, plugin_root="", timeout=30):
    """Load one candidate in a disposable vspipe process and return a result dict."""
    if not vspipe or not os.path.isfile(vspipe):
        return {"ok": False, "message": "vspipe.exe nem található", "plugins": []}
    if not path or not os.path.isfile(path):
        return {"ok": False, "message": "A DLL-fájl nem található", "plugins": []}
    with tempfile.TemporaryDirectory(prefix="vs_plugin_probe_") as td:
        script = os.path.join(td, "probe.vpy")
        result = os.path.join(td, "result.json")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(_PROBE)
        env = os.environ.copy()
        dirs = [os.path.dirname(os.path.abspath(path))]
        if plugin_root and os.path.isdir(plugin_root):
            dirs.append(os.path.abspath(plugin_root))
        old = env.get("PATH", "")
        env["PATH"] = os.pathsep.join(dirs + ([old] if old else []))
        cmd = [vspipe, "-a", "target=" + os.path.abspath(path), "-a", "outp=" + result,
               "-a", "plugin_root=" + os.path.abspath(plugin_root or ""), "-i", script]
        try:
            proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, timeout=timeout, creationflags=CREATE_NO_WINDOW,
                                  env=env)
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "Időtúllépés (%d mp)" % timeout, "plugins": []}
        except OSError as exc:
            return {"ok": False, "message": str(exc), "plugins": []}
        detail = ""
        if os.path.isfile(result):
            try:
                with open(result, encoding="utf-8") as fh:
                    data = json.load(fh)
                if data.get("loaded"):
                    return {"ok": True, "message": "Betölthető", "plugins": data.get("plugins", []),
                            "stderr": (proc.stderr or b"").decode("utf-8", "replace")[-2000:]}
                detail = str(data.get("error") or "A VapourSynth nem regisztrálta pluginként")
            except (OSError, ValueError) as exc:
                detail = str(exc)
        lines = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        if not detail and lines:
            detail = lines[-1]
        if not detail:
            detail = "Nem VapourSynth-plugin vagy nem kompatibilis DLL (kilépési kód %s)" % proc.returncode
        return {"ok": False, "message": detail, "plugins": [],
                "stderr": (proc.stderr or b"").decode("utf-8", "replace")[-2000:]}


def probe_core_catalog(vspipe, timeout=20):
    """Read already available core/built-in plugin signatures without loading extra DLLs."""
    script_text = r'''import json, os, vapoursynth as vs
core = vs.core
outp = str(globals().get("outp", ""))
items = []
for p in core.plugins():
    try:
        for f in p.functions():
            if isinstance(f, (tuple, list)):
                name, sig = f[0], f[1]
            else:
                name, sig = f.name, f.signature
            items.append([str(p.namespace), str(name), str(sig)])
    except Exception:
        pass
with open(outp, "w", encoding="utf-8") as fh:
    json.dump(items, fh)
core.std.BlankClip(width=16, height=16, length=1, format=vs.YUV420P8).set_output()
'''
    with tempfile.TemporaryDirectory(prefix="vs_core_probe_") as td:
        script, result = os.path.join(td, "core.vpy"), os.path.join(td, "core.json")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(script_text)
        try:
            proc = subprocess.run([vspipe, "-a", "outp=" + result, "-i", script],
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  timeout=timeout, creationflags=CREATE_NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return [], str(exc)
        try:
            with open(result, encoding="utf-8") as fh:
                return json.load(fh), None
        except (OSError, ValueError):
            lines = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
            return [], lines[-1] if lines else "A beépített szűrők nem olvashatók ki"


def scan_plugins(vspipe, plugin_root, timeout=30, cancel=None, progress=None):
    """Sequential isolated scan. progress(done, total, path, result) is called per candidate."""
    files = dll_files(plugin_root)
    results = []
    for i, path in enumerate(files, 1):
        if cancel is not None and cancel.is_set():
            break
        result = probe_plugin(vspipe, path, plugin_root, timeout)
        row = {"path": path, "result": result}
        results.append(row)
        if progress:
            progress(i, len(files), path, result)
    return results, len(files)
