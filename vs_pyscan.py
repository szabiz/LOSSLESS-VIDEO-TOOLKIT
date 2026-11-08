# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 szabiz <szabiz@yahoo.com>
# Copyright (c) 2026 szabiz <szabiz@yahoo.com>
"""
vs_pyscan.py - a pluginmappában lévő Python-modulok (havsfunc, G41Fun, mvsfunc ...) szűrő-függvényeinek
paraméterei: név, alapérték, a docstring első sora.

A natív DLL-plugin csak típust ad, a Python-függvény viszont megadja a paraméter NEVÉT és ALAPÉRTÉKÉT
(inspect.signature) - ebből lehet a kártyán felkínálni a paramétereket működő alapértékkel.

Modulonként külön vspipe-folyamat fut (a vspipe-ban fut, mert a modulok importálják a vapoursynth-ot),
időkorláttal, megszakíthatóan; a hibás modul nem állítja le a többit. A modulok kódját a vizsgálat IMPORTÁLJA,
tehát csak megbízható pluginmappán használd (ugyanúgy, mint a DLL-ek vizsgálatát).

Eredmény: {"havsfunc.QTGMC": {"params": [["Preset", "'Slower'"], ["TFF", None], ...], "doc": "..."}}
    a paraméter értéke az alapérték Python-kifejezésként (szövegként), vagy None, ha nincs alapértéke.
Az első (klip) paramétert a kártya maga adja ("clip"), ezért az nincs a listában.
"""
import hashlib
import json
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor

import vs_code

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CLIP_NAMES = ("clip", "input", "src", "c", "source", "video", "clip1", "clip_a", "clipa", "inp", "i")
SKIP_FILES = ("setup.py", "conftest.py", "__init__.py", "__main__.py")

PROBE_SRC = r'''import importlib, inspect, json, os, sys
import vapoursynth as vs
core = vs.core
_dir = str(globals().get("moddir", "") or "")
_name = str(globals().get("modname", "") or "")
if _dir and _dir not in sys.path:
    sys.path.insert(0, _dir)
_CLIPS = %(clips)r
_mod = importlib.import_module(_name)
_out = []
for _fname, _fn in inspect.getmembers(_mod, inspect.isfunction):
    if _fname.startswith("_") or getattr(_fn, "__module__", "") != _mod.__name__:
        continue
    try:
        _sig = inspect.signature(_fn)
    except (TypeError, ValueError):
        continue
    _ps = list(_sig.parameters.values())
    if not _ps:
        continue
    _p0 = _ps[0]
    if not (_p0.name.lower() in _CLIPS or "VideoNode" in str(_p0.annotation)):
        continue
    _params = []
    for _p in _ps[1:]:
        if _p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if _p.default is inspect.Parameter.empty:
            _params.append([_p.name, None])
        else:
            try:
                _params.append([_p.name, repr(_p.default)[:300]])
            except Exception:
                _params.append([_p.name, None])
    try:
        _doc = (inspect.getdoc(_fn) or "").strip().splitlines()
        _doc = _doc[0][:140] if _doc else ""
    except Exception:
        _doc = ""
    _out.append([_fname, _params, _doc])
with open(str(globals().get("outp")), "w", encoding="utf-8") as _fh:
    json.dump({"module": _name, "funcs": _out}, _fh)
core.std.BlankClip(width=16, height=16, length=1, format=vs.YUV420P8).set_output()
''' % {"clips": CLIP_NAMES}


def find_modules(plugdir, limit=400):
    """[(modulnév, mappa), ...]: a pluginmappa .py fájljai és csomagjai (rekurzívan)."""
    out = []
    if not plugdir or not os.path.isdir(plugdir):
        return out
    for root, dirs, files in os.walk(plugdir):
        dirs.sort()
        dirs[:] = [d for d in dirs if not d.startswith((".", "__"))]
        if "__init__.py" in files and root != plugdir:       # csomag: a szülő mappából importáljuk, nem lépünk bele
            out.append((os.path.basename(root), os.path.dirname(root)))
            dirs[:] = []
            continue
        for f in sorted(files):
            low = f.lower()
            if low.endswith(".py") and low not in SKIP_FILES and not low.startswith(("test", "_")):
                stem = f[:-3]
                if stem.isidentifier():
                    out.append((stem, root))
        if len(out) >= limit:
            break
    seen, uniq = set(), []
    for m, d in out:
        if m not in seen:
            seen.add(m)
            uniq.append((m, d))
    return uniq[:limit]


def py_sig(plugdir):
    """A .py fájlok „ujjlenyomata”: változáskor a gyorsítótár érvénytelen."""
    h = hashlib.sha1()
    try:
        for m, d in find_modules(plugdir):
            for p in (os.path.join(d, m + ".py"), os.path.join(d, m, "__init__.py")):
                if os.path.isfile(p):
                    st = os.stat(p)
                    h.update(("%s:%d:%d\n" % (p, st.st_size, int(st.st_mtime))).encode("utf-8", "replace"))
    except OSError:
        pass
    return h.hexdigest()[:12]


def _clean_params(params):
    """Csak a használható alapértékű paraméterek: a nem Python-kifejezés (pl. '<object ...>') alapérték kimarad."""
    out = []
    for n, d in params:
        if d is not None and (str(d).startswith("<") or not vs_code.valid_expr(d)):
            continue
        out.append([n, d])
    return out


def probe_module(vsp, workdir, modname, moddir, timeout=30):
    """Egy modul vizsgálata külön vspipe-folyamatban. -> (függvények dict | None, hibaüzenet | None)"""
    tag = hashlib.sha1(modname.encode("utf-8")).hexdigest()[:8]     # modulonként saját fájlok: párhuzamosan is biztonságos
    probe = os.path.join(workdir, "_probe_py_%s.vpy" % tag)
    outp = os.path.join(workdir, "_probe_py_%s.json" % tag)
    with open(probe, "w", encoding="utf-8") as fh:
        fh.write(PROBE_SRC)
    if os.path.exists(outp):
        os.remove(outp)
    cmd = [vsp, "-a", "outp=" + outp, "-a", "moddir=" + moddir, "-a", "modname=" + modname, "-i", probe]
    try:
        r = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=timeout, creationflags=NOWIN)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except OSError as e:
        return None, str(e)
    if not os.path.isfile(outp):
        lines = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        real = [l for l in lines if "error" in l.lower() or "failed" in l.lower() or "import" in l.lower()]
        return None, (real or lines or ["rc=%s" % r.returncode])[-1][:200]
    try:
        with open(outp, encoding="utf-8") as fh:
            data = json.load(fh)
        os.remove(outp)
    except (OSError, ValueError) as e:
        return None, str(e)
    funcs = {}
    for fname, params, doc in data.get("funcs", []):
        funcs["%s.%s" % (modname, fname)] = {"params": _clean_params(params), "doc": doc}
    return funcs, None


def scan(vsp, plugdir, workdir, timeout=30, cancel=None, progress=None, workers=3):
    """Az összes modul vizsgálata. -> (funcs dict, rows, total); rows: [{module, ok, count, message}]"""
    mods = find_modules(plugdir)
    total = len(mods)
    funcs, rows = {}, []
    lock = threading.Lock()
    done = [0]

    def one(idx_mod):
        _idx, (mod, d) = idx_mod
        if cancel is not None and cancel.is_set():
            return
        res, err = probe_module(vsp, workdir, mod, d, timeout)
        with lock:
            if res is not None:
                funcs.update(res)
            rows.append(dict(module=mod, ok=res is not None, count=len(res or {}), message=err or ""))
            done[0] += 1
            n = done[0]
        if progress:
            progress(n, total, mod)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        list(ex.map(one, list(enumerate(mods))))
    return funcs, rows, total


# ------------------------------------------------------------------ gyorsítótár
def cache_file(workdir):
    return os.path.join(workdir, "pyfuncs.json")


def load_cache(workdir, key):
    try:
        with open(cache_file(workdir), encoding="utf-8") as fh:
            d = json.load(fh)
        return d["funcs"] if d.get("key") == key and isinstance(d.get("funcs"), dict) else None
    except (OSError, ValueError, KeyError):
        return None


def save_cache(workdir, key, funcs):
    try:
        with open(cache_file(workdir), "w", encoding="utf-8") as fh:
            json.dump({"key": key, "funcs": funcs}, fh)
    except OSError:
        pass
