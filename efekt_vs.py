# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 szabiz <szabiz@yahoo.com>
# Copyright (c) 2026 szabiz <szabiz@yahoo.com>
"""
efekt_vs.py - VapourSynth (vspipe) támogatás a Képeffektek ablakhoz (efekt.py)

Bekötés (egyszer): az efekt.py VÉGÉRE, a többi definíció után tedd be:

    try:
        import sys
        import efekt_vs
        efekt_vs.install(sys.modules[__name__])
    except Exception:
        pass

Ugyanabban a mappában kell lennie: efekt.py, efekt_vs.py, vs_bridge.py, vs_code.py, vs_meta.py, vs_pyscan.py,
vs_render.py (és a vs_filters mappa a metaadat-JSON-okkal).
Az efekt.py kódját nem írja át: csak a szükséges metódusokat cseréli le. Ha nincs telepítve,
az efekt.py a régi módon működik.

Mit ad:
  * VapourSynth fül: vspipe.exe és plugin-mappa, „Ellenőrzés” (valódi próba), sablon-szkript, csúszkák.
  * Szűrőlista: a plugin-mappa összes szűrője (rekurzív bejárás, katalógus-gyorsítótár), keresés,
    és minden telepített szűrőhöz számmezős SABLON (a kötelező paraméterek csillaggal jelölve,
    az üres mező a plugin alapértéke). A program a listából magától írja a .vpy szkriptet.
  * Előnézet és lejátszás: vspipe → FFmpeg csővezeték. Az „Eredeti” mód továbbra is közvetlenül az
    FFmpeg-gel készül.
  * Export: NINCS köztes fájl. A Kimenet gomb a VapourSynth-es szakaszt az eredeti forrással és vágásponttal, mellé a
    vspipe-paranccsal adja át az Átalakítás fülnek (lvt_ffmpeg.py: PipeCmd). A méret, az fps és az ffmpeg-effektek
    megmaradnak (a mezőket egy kocka lefuttatásával mért értékekkel tölti ki), a kódolás egyetlen menet:
    vspipe → ffmpeg. Az Átalakítás fülön a kodek, a bitráta (kbit/s) és a konténer továbbra is átírható.
"""
import copy
import hashlib
import json
import math
import os
import queue
import re
import secrets
import subprocess
import threading
import time

import vs_bridge as vb
import vs_code
import vs_env
import vs_meta
import vs_pyscan
import vs_render

E = None            # az efekt.py modulja (install() állítja be)
_ORIG = {}          # az eredeti metódusok (a felülírtak ezeket hívják)
_NAMES = ("_tab_vs", "_frame_work", "_frame_done", "_request", "_vcmd", "_play_thread", "_start_play", "_caps_done",
          "_update_chain", "_refresh_tree", "output", "_load", "_collect", "_make_vpy", "_reset")


def T(hu, en):
    return E._(hu, en)


def L(v):
    """Kétnyelvű metaadat-szöveg ([hu, en]) az aktuális felületi nyelven."""
    return vs_meta.loc(v, T("1", "0") == "1")


# ------------------------------------------------------------------ beépített (kész) szűrők – csúszkákkal
# A {u} helyére a szűrőpéldány egyedi azonosítója (uid) kerül, így a csúszka-értékek a sorrend
# változtatása után is a helyükön maradnak.
FILTERS = {
    "denoise": {
        "ns": "dfttest", "label": ("Zajszűrő (DFTTest)", "Denoise (DFTTest)"),
        "params": [("sigma", "float", 2.0, 0.1, 10.0, ("Erősség (sigma)", "Strength (sigma)"))],
        "code": 'clip = core.dfttest.DFTTest(clip, sigma=float(globals().get("{u}_sigma", 2.0)), planes=[0])',
    },
    "sharpen": {
        "ns": "warp", "label": ("Élesítés (AWarpSharp2)", "Sharpen (AWarpSharp2)"),
        "params": [],
        "code": "clip = core.warp.AWarpSharp2(clip)",
    },
    "levels": {
        "ns": "std", "label": ("Fényerő / gamma (beépített)", "Brightness / gamma (built-in)"),
        "params": [("gamma", "float", 1.0, 0.5, 2.5, ("Fényerő (gamma)", "Brightness (gamma)"))],
        "code": 'clip = core.std.Levels(clip, gamma=float(globals().get("{u}_gamma", 1.0)), planes=[0])',
    },
    # A QTGMC nem plugin, hanem a havsfunc.py Python-függvénye (a plugin-mappában lévő .py fájlokat a szkript
    # automatikusan a Python-keresési útvonalra teszi). Több pluginra támaszkodik: ezeket mind be kell tölteni.
    "qtgmc": {
        "ns": "mv", "label": ("Deinterlace (QTGMC, havsfunc)", "Deinterlace (QTGMC, havsfunc)"),
        "needs": ("mv", "mvsf", "nnedi3", "znedi3", "eedi3m", "eedi3", "rgvs", "rgsf", "zsmooth", "fmtc",
                  "dfttest", "fft3dfilter", "ctmf", "ffms2", "lsmas"),
        "params": [
            ("preset", "str", "Medium", "-", "-", ("Előbeállítás (Draft…Placebo, pl. Slower)",
                                                  "Preset (Draft…Placebo, e.g. Slower)")),
            ("tff", "bool", 1, 0, 1, ("Felső mező elöl (TFF)", "Top field first (TFF)")),
            ("div", "int", 2, 1, 2, ("FPS-osztó (2 = azonos fps, 1 = dupla)", "FPS divisor (2 = same fps, 1 = double)")),
        ],
        "code": ('import havsfunc; clip = havsfunc.QTGMC(clip, Preset=str(globals().get("{u}_preset", "Medium")), '
                 'TFF=bool(int(float(globals().get("{u}_tff", 1)))), '
                 'FPSDivisor=int(float(globals().get("{u}_div", 2))))'),
    },
}

# A plugin-mappát REKURZÍVAN járja be (rekurzív pluginmappa-kezelés).
# A DLL-eket tartalmazó almappák a DLL-keresési útvonalba kerülnek (függőségek), a .py fájlokat
# tartalmazó mappák a Python-keresési útvonalba (havsfunc, mvsfunc stb. importálható legyen).
LOAD_PLUGINS_SRC = """plugdir = str(globals().get("plugdir", "") or "")
if plugdir and os.path.isdir(plugdir):
    _seen = set()
    for _root, _dirs, _files in os.walk(plugdir):
        _dirs.sort()
        if any(f.lower().endswith(".py") for f in _files) and _root not in sys.path:
            sys.path.append(_root)
        _dlls = sorted(f for f in _files if f.lower().endswith(".dll"))
        if not _dlls:
            continue
        try:
            os.add_dll_directory(_root)
        except Exception:
            pass
        for _f in _dlls:
            if _f.lower() in _seen:
                continue
            try:
                core.std.LoadPlugin(os.path.join(_root, _f))
                _seen.add(_f.lower())
            except Exception:
                pass
"""

# Katalógus-felderítéskor: minden DLL betöltése, és megjegyezzük, melyik DLL melyik névteret hozta (névtér -> DLL).
LOAD_PLUGINS_MAP_SRC = """plugdir = str(globals().get("plugdir", "") or "")
_map = {}
if plugdir and os.path.isdir(plugdir):
    _seen = set()
    _have = set(_p.namespace for _p in core.plugins())
    for _root, _dirs, _files in os.walk(plugdir):
        _dirs.sort()
        if any(f.lower().endswith(".py") for f in _files) and _root not in sys.path:
            sys.path.append(_root)
        _dlls = sorted(f for f in _files if f.lower().endswith(".dll"))
        if not _dlls:
            continue
        try:
            os.add_dll_directory(_root)
        except Exception:
            pass
        for _f in _dlls:
            if _f.lower() in _seen:
                continue
            _full = os.path.join(_root, _f)
            try:
                core.std.LoadPlugin(_full)
                _seen.add(_f.lower())
            except Exception:
                continue
            _now = set(_p.namespace for _p in core.plugins())
            for _n in _now - _have:
                _map[_n] = _full
            _have = _now
"""

# Generált szűrőlista-szkriptben: CSAK a használt szűrők DLL-jeit töltjük be (a több száz DLL mindegyikének
# betöltése minden egyes állóképnél új vspipe-folyamatban percekig is tarthatna).
LOAD_LAZY_SRC = """plugdir = str(globals().get("plugdir", "") or "")
if plugdir and os.path.isdir(plugdir):
    for _root, _dirs, _files in os.walk(plugdir):
        _dirs.sort()
        if any(f.lower().endswith(".py") for f in _files) and _root not in sys.path:
            sys.path.append(_root)
        if any(f.lower().endswith(".dll") for f in _files):
            try:
                os.add_dll_directory(_root)
            except Exception:
                pass
for _full in __WANT__:
    try:
        core.std.LoadPlugin(_full)
    except Exception as _e:
        sys.stderr.write("PLUGIN-HIBA: %s: %s\\n" % (_full, str(_e).strip().replace("\\n", " ")))
_pd = str(globals().get("plugin_dll", "") or "")
if _pd and not (hasattr(core, "lsmas") or hasattr(core, "ffms2")):
    try:
        core.std.LoadPlugin(_pd)
    except Exception:
        pass
"""

PLUGMAP = {}        # névtér -> a DLL teljes útja (a katalógus-felderítés tölti ki; üres = mindent betöltünk)

PROBE_NS_SRC = """import glob, json, os, sys
import vapoursynth as vs
core = vs.core
""" + LOAD_PLUGINS_SRC + """nss = [n for n in str(globals().get("nss", "")).split(",") if n]
res = dict((n, bool(hasattr(core, n))) for n in nss)
with open(str(globals().get("outp")), "w", encoding="utf-8") as fh:
    json.dump(res, fh)
core.std.BlankClip(width=16, height=16, length=1, format=vs.YUV420P8).set_output()
"""

# ------------------------------------------------------------------ plugin-katalógus (automatikus felderítés)
# A plugin-mappa összes DLL-jét betöltjük egy próba-szkriptben, és kiolvassuk a core.plugins() listát.
PROBE_CAT_SRC = """import glob, json, os, sys
import vapoursynth as vs
core = vs.core
""" + LOAD_PLUGINS_MAP_SRC + """out = []
for p in core.plugins():
    ns = p.namespace
    for f in p.functions():
        if isinstance(f, (tuple, list)):
            name, sig = f[0], f[1]
        else:
            name, sig = f.name, f.signature
        out.append([ns, name, str(sig)])
with open(str(globals().get("outp")), "w", encoding="utf-8") as fh:
    json.dump({"items": out, "map": _map}, fh)
core.std.BlankClip(width=16, height=16, length=1, format=vs.YUV420P8).set_output()
"""
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SIMPLE_TYPES = {"int", "float", "data", "int[]", "float[]", "data[]"}


def parse_sig(sig):
    """'clip:vnode:all;sigma:float[]:opt;' -> [(név, típus, opcionális?), ...]"""
    res = []
    for part in str(sig).split(";"):
        bits = part.strip().split(":")
        if bits and bits[0]:
            res.append((bits[0], bits[1] if len(bits) > 1 else "", "opt" in bits[2:]))
    return res


# Névterek, amelyek szűrői csak többlépcsős láncban (Super → Analyse → Degrain/Compensate) értelmesek.
_NEEDS_PIPELINE_NS = {"mv", "mvsf"}


def is_simple_sig(sig):
    """Videó-szűrő: az első paraméter a bemeneti klip (vnode vagy vnode[]), a többi szám/szöveg/tömb,
    és nincs több klip-bemenet. Ezeket a sablon ki tudja tölteni."""
    ps = parse_sig(sig)
    if not ps or not ps[0][1].startswith("vnode"):
        return False
    if ps[0][0] not in ("clip", "clips"):       # pl. mv.Finest(super, ...): speciális bemenet kell
        return False
    if any(t.startswith("vnode") for _n, t, _o in ps[1:]):
        return False
    return all(t in _SIMPLE_TYPES for _n, t, _o in ps[1:])


# ------------------------------------------------------------------ kategóriák (kategória szerinti csoportosítás)
# (kulcs, rövid név a listasorhoz, teljes név a menühöz, regex az „ns.fn” kisbetűs nevére). Az első találat nyer.
CATS = (
    ("source", ("Forrás", "Source"), ("Forrás / beolvasás", "Source / input"),
     r"lsmas|ffms2|^bs\.|bestsource|d2v|dgdecn|dgsource|imwri|avisource|lwlibav|\.source"),
    ("text", ("Felirat", "Text"), ("Felirat / átfedés", "Subtitles / overlay"),
     r"^sub\.|subtext|assrender|^text\.|overlay|subtitle|vsfilter|clipinfo|framecounter"),
    ("fps", ("FPS", "FPS"), ("Képkocka / FPS / vágás", "Frames / FPS / trim"),
     r"fps|framerate|rife|svpflow|selectevery|^std\.(trim|reverse|loop|splice|interleave|duplicateframes|"
     r"deleteframes|freezeframes)|interframe"),
    ("ai", ("AI", "AI"), ("AI / neurális", "AI / neural"),
     r"waifu2x|esrgan|mlrt|ncnn|dpir|artcnn|fsrcnn|anime4k|^trt\.|^ort\."),
    ("resize", ("Átméret", "Resize"), ("Átméretezés", "Resize"),
     r"^resize\.|descale|resample|rpow2|ssim|fsrcnnx|krig|superres|vsscale|rescale"),
    ("deint", ("Deint", "Deint"), ("Deinterlace / IVTC", "Deinterlace / IVTC"),
     r"nnedi3|znedi3|eedi2|eedi3|bwdif|yadif|tdeint|tfm|tdecimate|vivtc|qtgmc|deinterlace|vfm|vdecimate|"
     r"fieldmatch|separatefields|doubleweave|^std\.weave|dgbob|telecine|ivtc|decomb"),
    ("aa", ("Halo/AA", "Halo/AA"), ("Halo / élsimítás", "Halo / anti-alias"),
     r"dehalo|dering|edgecleaner|halo|taa|antialias|^aa\.|sangnom|rgaa|santiag"),
    ("noise", ("Zaj", "Noise"), ("Zajszűrés", "Denoise"),
     r"dfttest|bm3d|nlm|fft3d|hqdn3d|degrain|mvtools|^mv\.|smoothst|flux\.|ttempsmooth|temporalsoften|"
     r"tmedian|bilateral|removegrain|rgvs|^rgsf|repair|clense|deblock|denoise|dgm\."),
    ("sharp", ("Élesítés", "Sharpen"), ("Élesítés", "Sharpen"),
     r"^cas\.|awarp|warpsf|sharp|lsfmod|unsharp|contrasharp|fastlinedarken|toon"),
    ("deband", ("Sávosodás", "Deband"), ("Sávosodás-eltávolítás", "Debanding"),
     r"f3kdb|deband|gradfun|banding"),
    ("color", ("Szín", "Color"), ("Szín / tónus / HDR", "Color / tone / HDR"),
     r"tonemap|hdr|levels|curve|tweak|color|colour|matrix|gamma|contrast|saturation|brightness|retinex|"
     r"autolevel|dovi|ocio|sepia|primaries"),
    ("geom", ("Geom", "Geom"), ("Vágás / geometria", "Crop / geometry"),
     r"crop|border|flip|turn180|transpose|rotate|stackhorizontal|stackvertical|mirror|shift|offset|pad|fillmargins"),
    ("mask", ("Maszk", "Mask"), ("Maszk / pixelműveletek", "Masks / pixel ops"),
     r"mask|binarize|inflate|deflate|maximum|minimum|median|convolution|sobel|prewitt|canny|kirsch|invert|"
     r"limiter|expr|lut|merge|diff|shuffleplanes|planestats|blur"),
)
CAT_OTHER = ("other", ("Egyéb", "Other"), ("Egyéb", "Other"))
_CATS_C = tuple((k, short, full, re.compile(rx)) for k, short, full, rx in CATS)
CAT_ORDER = [c[0] for c in CATS] + [CAT_OTHER[0]]
CAT_NAMES = {c[0]: (c[1], c[2]) for c in CATS}
CAT_NAMES[CAT_OTHER[0]] = (CAT_OTHER[1], CAT_OTHER[2])
CAT_SEP = " · "


def categorize(ns, fn):
    """A szűrő kategóriája a plugin- és függvénynév alapján (a Pluginok listában nincs kategória-adat)."""
    s = ("%s.%s" % (ns, fn)).lower()
    for key, _short, _full, rx in _CATS_C:
        if rx.search(s):
            return key
    return CAT_OTHER[0]


def catalog_file():
    return os.path.join(lanc_dir(), "katalogus.json")


def plug_sig(plug):
    """A plugin-mappa „ujjlenyomata”: új / módosított DLL esetén a katalógus magától újraolvasódik."""
    h = hashlib.sha1()
    try:
        for root, dirs, files in os.walk(plug or ""):
            dirs.sort()
            for n in sorted(files):
                if n.lower().endswith(".dll"):
                    p = os.path.join(root, n)
                    st = os.stat(p)
                    h.update(("%s:%d:%d\n" % (p, st.st_size, int(st.st_mtime))).encode("utf-8", "replace"))
    except OSError:
        pass
    return h.hexdigest()[:12]


def load_catalog(key):
    try:
        with open(catalog_file(), encoding="utf-8") as fh:
            d = json.load(fh)
        if d.get("key") != key or not isinstance(d.get("map"), dict):
            return None
        PLUGMAP.clear()
        PLUGMAP.update(d["map"])
        return d["items"]
    except Exception:               # noqa
        return None


def save_catalog(key, items):
    try:
        with open(catalog_file(), "w", encoding="utf-8") as fh:
            json.dump({"key": key, "items": items, "map": dict(PLUGMAP)}, fh)
    except OSError:
        pass


def discover_catalog(vsp, plug, timeout=180):
    """-> ([[ns, függvény, szignatúra], ...] | None, hiba | None)"""
    d = lanc_dir()
    probe = os.path.join(d, "_probe_cat.vpy")
    with open(probe, "w", encoding="utf-8") as fh:
        fh.write(PROBE_CAT_SRC)
    outp = os.path.join(d, "_probe_cat.json")
    if os.path.exists(outp):
        os.remove(outp)
    cmd = [vsp, "-a", "outp=" + outp, "-a", "plugdir=" + (plug or ""), "-i", probe]
    try:
        r = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=timeout, creationflags=E._NOWIN)
    except Exception as e:          # noqa
        return None, str(e)
    if not os.path.isfile(outp):
        lines = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        return None, _last_error(lines) or T("ismeretlen vspipe-hiba", "unknown vspipe error")
    try:
        with open(outp, encoding="utf-8") as fh:
            d = json.load(fh)
        PLUGMAP.clear()
        PLUGMAP.update(d.get("map") or {})
        return d["items"], None
    except Exception as e:          # noqa
        return None, str(e)


# ------------------------------------------------------------------ lista-elemek
def item_ns(it):
    """A szűrő névtere (a plugin-ellenőrzéshez). Beillesztett kódnál (vs_code) None is lehet: Python-függvény / nyers kód."""
    if it["id"] == "code":
        return vs_code.ns_of(it)
    return FILTERS[it["id"]]["ns"] if it["id"] in FILTERS else it["ns"]


def item_label(it):
    if it["id"] == "code":
        return vs_code.label_of(it)
    return T(*FILTERS[it["id"]]["label"]) if it["id"] in FILTERS else "%s.%s" % (it["ns"], it["fn"])


def vs_mode(st):
    return "list" if (st or {}).get("vs_mode") == "list" else "file"


def _valid_item(it):
    if it.get("id") in FILTERS:
        return True
    if it.get("id") == "code":
        return vs_code.is_valid(it)
    return (it.get("id") == "auto" and _IDENT.match(str(it.get("ns") or "")) is not None
            and _IDENT.match(str(it.get("fn") or "")) is not None and bool(it.get("sig")))


FILTER_CAT = {"denoise": "noise", "sharpen": "line", "levels": "color", "qtgmc": "field"}

_META = None
_META_ERR = []


def meta_all():
    """A natív szűrők metaadat-könyvtára (vs_filters/*.json a program mellett + ~/efekt_vs_filters/*.json). Egyszer töltődik be."""
    global _META, _META_ERR
    if _META is None:
        base = os.path.dirname(os.path.abspath(__file__))
        _META, _META_ERR = vs_meta.load([os.path.join(base, "vs_filters"),
                                         os.path.join(os.path.expanduser("~"), "efekt_vs_filters")])
    return _META


def meta_for(it):
    """A kártya szűrőjének metaadata, ha a 'core.ns.fn' hívás szerepel a könyvtárban; különben None."""
    if it.get("id") != "code" or "raw" in it:
        return None
    f = str(it.get("func") or "")
    return meta_all().get(f[5:]) if f.startswith("core.") else None


def item_cat(it):
    """Az elem kategóriája: a felhasználó által beállított, különben a névből / a beépített szűrő táblájából becsült."""
    try:
        c = it.get("cat")
        if c in vs_code.CAT_KEYS:
            return c
        if it.get("id") in FILTER_CAT:
            return FILTER_CAT[it["id"]]
        if it.get("id") == "code":
            m = meta_for(it)
            return m["cat"] if m else vs_code.guess_cat(it.get("func") or it.get("title"), it.get("title"))
        return vs_code.guess_cat(it.get("fn"), it.get("ns"))
    except Exception:           # noqa
        return "other"


def sort_chain(L):
    """Stabil rendezés kategória szerint: a kategóriák rögzített sorrendben futnak, belül a lista szerinti a sorrend."""
    return sorted(L, key=lambda it: vs_code.cat_rank(item_cat(it)))


def chain_items(st):
    """A lista összes (érvényes) eleme kategória-sorrendben, a kikapcsoltakkal együtt - a felület ezt rajzolja."""
    return sort_chain([it for it in ((st or {}).get("vs_chain") or []) if _valid_item(it)])


def active_items(st):
    """Csak a bekapcsolt (pipás) elemek - ezekből készül a szkript."""
    return [it for it in chain_items(st) if it.get("enabled", True)]


def vs_active(st):
    st = st or {}
    if vs_mode(st) == "list":           # lista-módban a szűrők a jelölőnégyzet nélkül is futnak
        return bool(active_items(st))
    if not st.get("vs_on"):
        return False
    return bool(str(st.get("vs_file") or "").strip())


def lanc_dir():
    d = os.path.join(os.path.expanduser("~"), "efekt_vs_lanc")
    os.makedirs(d, exist_ok=True)
    return d


def _lit(typ, text):
    """A sablon szövegéből Python-literál (csak számok, szövegek és tömbök; más nem kerülhet a kódba)."""
    t = str(text).strip()
    if typ == "int":
        return repr(int(float(t)))
    if typ == "float":
        v = float(t)
        if not math.isfinite(v):
            raise ValueError(t)
        return repr(v)
    if typ == "data":
        return repr(t)
    if typ == "int[]":
        return "[" + ", ".join(repr(int(float(x))) for x in t.replace(";", ",").split(",") if x.strip()) + "]"
    if typ == "float[]":
        out = []
        for x in t.replace(";", ",").split(","):
            if x.strip():
                v = float(x)
                if not math.isfinite(v):
                    raise ValueError(x)
                out.append(repr(v))
        return "[" + ", ".join(out) + "]"
    if typ == "data[]":
        return "[" + ", ".join(repr(x.strip()) for x in t.split(";") if x.strip()) + "]"
    raise ValueError(typ)


def item_defaults(it):
    """A felhasználó által megadott értékek; külső példaértéket a program nem feltételez."""
    return dict(it.get("vals") or {})


def auto_call(it):
    """
    Egy katalógus-szűrő hívása a sablon mezőiből.
    Visszatér: (hívás-szöveg | None, figyelmeztetés | None).
    None: hiányzik egy kötelező paraméter, vagy hibás a szám – ilyenkor a szűrő kimarad.
    """
    ps = parse_sig(it.get("sig") or "")
    if not ps:
        return None, T("nincs szignatúra", "no signature")
    if not is_simple_sig(it.get("sig") or "") or it.get("ns") in _NEEDS_PIPELINE_NS:
        return None, T("önmagában nem használható (más szűrő kimenete kell hozzá)",
                       "cannot be used on its own (needs the output of another filter)")
    vals = item_defaults(it)
    kw = []
    for name, typ, opt in ps[1:]:
        t = str(vals.get(name, "") or "").strip()
        if not t:
            if not opt:
                return None, T("hiányzik a kötelező paraméter: %s", "missing required parameter: %s") % name
            continue
        try:
            kw.append("%r: %s" % (name, _lit(typ, t)))
        except (ValueError, TypeError, OverflowError):
            return None, T("hibás érték: %s = %s", "invalid value: %s = %s") % (name, t)
    first = "[clip]" if ps[0][1].endswith("[]") else "clip"
    call = "core.%s.%s(%s" % (it["ns"], it["fn"], first)
    if kw:
        call += ", **{%s}" % ", ".join(kw)
    return call + ")", None


def _lazy_dlls(items):
    """A lánc által használt DLL-ek (névtér-térkép alapján), vagy None: nincs térkép -> az összes DLL betöltése."""
    if not PLUGMAP:
        return None
    if any(it.get("id") == "code" and vs_code.needs_all_plugins(it) for it in items):
        return None                     # Python-függvény (havsfunc, G41Fun ...) vagy nyers kód: sok plugin kellhet
    need = set(item_ns(it) for it in items)
    for it in items:
        if it.get("id") in FILTERS:
            need.update(FILTERS[it["id"]].get("needs", ()))
    need -= {"std", None}
    need.add("lsmas" if "lsmas" in PLUGMAP else "ffms2")      # a forrás-betöltő
    out = []
    for ns in sorted(need):
        dll = PLUGMAP.get(ns)
        if dll and dll not in out:
            out.append(dll)
    return out


def build_list_script(items):
    head = ["# " + T("Automatikusan generált szűrőlánc (Képeffektek ablak). A program írja újra, ne szerkeszd kézzel.",
                     "Automatically generated filter chain (Image effects window). The program rewrites it, do not edit it by hand."),
            "import glob", "import os", "import sys", "import vapoursynth as vs", "core = vs.core", ""]
    for it in items:
        if it["id"] not in FILTERS:
            continue
        for name, kind, dflt, lo, hi, lab in FILTERS[it["id"]]["params"]:
            head.append("# @param %s_%s %s %s %s %s %s" % (it["uid"], name, kind, dflt, lo, hi, T(*lab)))
    lazy = _lazy_dlls(items)
    pre = LOAD_PLUGINS_SRC if lazy is None else LOAD_LAZY_SRC.replace("__WANT__", repr(lazy))
    load = pre.splitlines() + [
        'src = globals().get("src")',
        'if hasattr(core, "lsmas"):',
        "    clip = core.lsmas.LWLibavSource(src)",
        'elif hasattr(core, "ffms2"):',
        "    clip = core.ffms2.Source(src)",
        "else:",
        '    raise vs.Error("' + T("Nincs forrás-betöltő plugin (lsmas vagy ffms2).", "No source loader plugin (lsmas or ffms2).") + '")',
    ]
    # Export: a szakaszt a forrás betöltése után levágjuk (seg_start / seg_end szkript-paraméter, kockaszámban). Az előnézet
    # és a lejátszás nem ad ilyet, ott a teljes klip marad.
    load += [
        '_ss = globals().get("seg_start")',
        'if _ss not in (None, ""):',
        "    _n = clip.num_frames",
        "    _a = max(0, min(int(float(_ss)), _n - 1))",
        '    _b = max(_a + 1, min(int(float(globals().get("seg_end") or _n)), _n))',
        "    clip = clip[_a:_b]",
    ]
    # Ha a plugin nincs betöltve, a szűrő kimarad (nem dönti meg az egész láncot).
    body = []

    def _skip(ns, why):
        return "    sys.stderr.write(%r)" % ("KIHAGYVA: %s - %s\n" % (ns, why))
    for it in items:
        if it["id"] == "code":
            body += vs_code.script_block(it)
        elif it["id"] in FILTERS:
            ns = FILTERS[it["id"]]["ns"]
            body.append('if hasattr(core, "%s"):' % ns)
            body.append("    " + FILTERS[it["id"]]["code"].format(u=it["uid"]).replace("\n", "\n    "))
            body.append("else:")
            body.append(_skip(ns, "a plugin nincs betöltve"))
        else:
            call, warn = auto_call(it)
            name = "%s.%s" % (it["ns"], it["fn"])
            if call is None:
                body.append("# kihagyva (%s): %s" % (warn, name))
                body.append("sys.stderr.write(%r)" % ("KIHAGYVA: %s - %s\n" % (name, warn)))
            else:
                body.append('if hasattr(core, "%s"):' % it["ns"])
                body.append("    clip = %s" % call)
                body.append("else:")
                body.append(_skip(name, "a plugin nincs betöltve (hiányzó DLL / függőség?)"))
    return "\n".join(head + [""] + load + body + ["clip.set_output()", ""])


def list_script_path(items):
    text = build_list_script(items)
    key = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
    path = os.path.join(lanc_dir(), "lanc_%s.vpy" % key)
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        try:        # a hetvenél régebbi generált szkriptek törlése
            for n in os.listdir(lanc_dir()):
                p = os.path.join(lanc_dir(), n)
                if n.startswith("lanc_") and n.endswith(".vpy") and time.time() - os.path.getmtime(p) > 7 * 86400:
                    os.remove(p)
        except OSError:
            pass
    return path


def effective_script(st):
    """A vspipe-nak átadott szkript: a szűrőlista generált fájlja, vagy a kézzel megadott .vpy."""
    st = st or {}
    if vs_mode(st) == "list":
        items = active_items(st)
        return list_script_path(items) if items else ""
    return str(st.get("vs_file") or "").strip()


def check_namespaces(vsp, plug, nss, timeout=120):
    """Betölti a plugin-mappa DLL-jeit, és megnézi, melyik névtér érhető el. Visszatér: (dict|None, hiba|None)."""
    d = lanc_dir()
    probe = os.path.join(d, "_probe.vpy")
    with open(probe, "w", encoding="utf-8") as fh:
        fh.write(PROBE_NS_SRC)
    outp = os.path.join(d, "_probe_result.json")
    if os.path.exists(outp):
        os.remove(outp)
    cmd = [vsp, "-a", "outp=" + outp, "-a", "plugdir=" + (plug or ""), "-a", "nss=" + ",".join(nss),
           "-i", probe]
    try:
        r = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=timeout, creationflags=E._NOWIN)
    except Exception as e:          # noqa
        return None, str(e)
    if not os.path.isfile(outp):
        lines = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        return None, _last_error(lines) or T("ismeretlen vspipe-hiba", "unknown vspipe error")
    try:
        with open(outp, encoding="utf-8") as fh:
            return json.load(fh), None
    except Exception as e:          # noqa
        return None, str(e)


def split_rgb(left, right, W, H, p):
    """Két azonos méretű rgb24 kocka összevágása: a bal oldal az eredeti (left), a jobb az effekt (right)."""
    lw = max(0, min(W, (int(W * p) // 2) * 2))
    out = bytearray(W * H * 3)
    for y in range(H):
        base = y * W * 3
        out[base:base + lw * 3] = left[base:base + lw * 3]
        out[base + lw * 3:base + W * 3] = right[base + lw * 3:base + W * 3]
    return bytes(out)


def _note_popup(self, note):
    """A kimaradt szűrőről szóló jelzés: UGYANAZT csak egyszer mutatja felugró ablakban (nem az üzenetsorban:
    az átrendezné a gombokat), amíg nem jön újra „tiszta” kocka."""
    if note == getattr(self, "_vs_note_last", ""):
        return
    self._vs_note_last = note
    if note:
        try:
            self._show_error(note)
        except Exception:           # noqa
            pass


def _busy(self, text):
    """Állapotjelzés a lejátszó-sor „élő: x / y kocka/mp” címkéjében (nem mozgatja az elrendezést)."""
    try:
        self._vs_busy = bool(text)
        self.v_perf.set(text)
    except Exception:               # noqa
        pass


_VS_FAIL = re.compile(r"(failed to retrieve|script evaluation failed|error:|exception|traceback)", re.I)


def _last_error(lines):
    real = [l for l in lines if "error" in l.lower() or "failed" in l.lower()]
    pick = real or lines
    return pick[-1] if pick else None


def _paths(self):
    """(vspipe útvonal, plugin-mappa) a beállításokból. Hiányzó vspipe esetén RuntimeError."""
    cfg = self.p.cfg
    vsp = vb.find_vspipe(str(cfg.get("vs_vspipe", "") or "").strip() or None)
    if not vsp:
        raise RuntimeError(T("Nincs vspipe.exe megadva (VapourSynth fül).", "No vspipe.exe set (VapourSynth tab)."))
    plug = str(cfg.get("vs_plugins", "") or "").strip()
    _dep_path(vsp, plug)
    return vsp, plug


_DEP_DONE = set()
_SRC_PLUGIN = {}
_orig_find_source_plugin = vb.find_source_plugin


def _find_source_plugin_cached(plugin_dir):
    """A vs_bridge.find_source_plugin eredménye mappánként megjegyezve: a bejárás nagy plugin-fán másodpercekig tart,
    és korábban minden Play-nél / paraméter-változásnál lefutott (a felület ezalatt „lefagyott”)."""
    key = plugin_dir or ""
    hit = _SRC_PLUGIN.get(key)
    if hit is not None and (hit == "" or os.path.isfile(hit)):
        return hit or None
    found = _orig_find_source_plugin(plugin_dir)
    _SRC_PLUGIN[key] = found or ""
    return found


vb.find_source_plugin = _find_source_plugin_cached


def _dep_path(vsp, plug=""):
    """A külső DLL-függőségek mappáit a vizsgálati folyamat számára elérhetővé teszi."""
    key = (vsp, plug)
    if key in _DEP_DONE:
        return
    _DEP_DONE.add(key)
    base = os.path.dirname(os.path.abspath(vsp))
    cands = [base]
    if plug and os.path.isdir(plug):
        cands.append(plug)
        root = os.path.normpath(plug)
        found = 0
        seen_dirs = 0
        for dp, dns, fns in os.walk(root):
            seen_dirs += 1
            if seen_dirs > 4000:
                break
            rel = os.path.relpath(dp, root)
            if rel != "." and rel.count(os.sep) + 1 >= 8:
                dns[:] = []
            low = [f.lower() for f in fns]
            # fftw / MinGW-féle "lib*.dll" függőségek (libfftw3f-3.dll, libgcc_s_seh-1.dll, libstdc++-6.dll ...)
            if any(f.endswith(".dll") and (f.startswith("lib") or "fftw" in f) for f in low):
                cands.append(dp)
                found += 1
                if found >= 40:
                    break
    parts = os.environ.get("PATH", "").split(os.pathsep)
    added = []
    for d in cands:
        d = os.path.normpath(d)
        if os.path.isdir(d) and d not in parts and len(os.pathsep.join(parts)) < 30000:
            parts.insert(0, d)
            added.append(d)
    os.environ["PATH"] = os.pathsep.join(parts)
    try:
        E._log("PATH bővítve %d függőség-mappával: %s" % (len(added), "; ".join(added[:20])))
    except Exception:       # noqa
        pass


# ------------------------------------------------------------------ előnézet (állókép)
class _Pair:
    """Két folyamat (vspipe + ffmpeg) egyben: a munkaszál így mindkettőt azonnal le tudja állítani, ha újabb kérés jön
    (az elavult, nehéz számítás ne tartsa fel a legutóbbit)."""

    def __init__(self, *procs):
        self.procs = [p for p in procs if p is not None]

    def poll(self):
        return None if any(p.poll() is None for p in self.procs) else 0

    def kill(self):
        for p in self.procs:
            try:
                if p.poll() is None:
                    p.kill()
            except OSError:
                pass


def _still_fx(self, req, wk):
    """Egy képkocka a VapourSynth-szűrőkkel: ugyanaz a vspipe → ffmpeg csővezeték, mint a lejátszásnál."""
    W, H, fps = req["W"], req["H"], req["fps"]
    vsp, plug = _paths(self)
    args = vb.script_args(src=req["src"], plugin_dir=plug or None, params=req.get("vsp") or {})
    args["plugdir"] = plug or ""
    idx = max(0, int(round(req["t"] * fps)))
    vcmd = vb.vspipe_cmd(vsp, req["script"], args, start=idx, end=idx)
    disp = ("scale=trunc(iw*sar/2)*2:ih,setsar=1,scale=%d:%d:force_original_aspect_ratio=decrease,"
            "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:black") % (W, H, W, H)
    chain = req["chain"]
    fxv = (chain + "," if chain else "") + disp
    fcmd = [self.ff.ffmpeg, "-v", "error", "-nostdin", "-f", "yuv4mpegpipe", "-i", "-", "-vf", fxv,
            "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    vp = fp = None
    try:
        vp = subprocess.Popen(vcmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                              creationflags=E._NOWIN)
        fp = subprocess.Popen(fcmd, stdin=vp.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              creationflags=E._NOWIN)
        vp.stdout.close()
        pair = _Pair(vp, fp)
        with wk.cv:
            wk.proc = pair
            stale = wk.req is not None or wk.dead
        if stale:                       # közben újabb kérés érkezett: ne számoljunk feleslegesen
            pair.kill()
            raise RuntimeError("stale")
        t0 = time.time()
        try:
            out, ferr = fp.communicate(timeout=600)
        except subprocess.TimeoutExpired:
            pair.kill()
            raise RuntimeError(T("Időtúllépés az előnézetnél.", "Preview timed out."))
        try:
            vp.wait(timeout=10)
        except Exception:               # noqa
            pair.kill()
        verr = b""
        try:
            verr = vp.stderr.read() or b""
        except Exception:               # noqa
            pass
        vlines = verr.decode("utf-8", "replace").strip().splitlines()
        notes = [l.strip() for l in vlines if l.startswith(("KIHAGYVA", "PLUGIN-HIBA"))]
        try:
            E._log("VS kocka: %.1f mp, vspipe rc=%s, ffmpeg rc=%s, bytes=%d, script=%s%s" % (
                time.time() - t0, vp.returncode, fp.returncode, len(out), req.get("script"),
                ("\n    " + "\n    ".join(notes)) if notes else ""))
        except Exception:               # noqa
            pass
        note = ""
        if notes:
            note = T("VapourSynth: kimaradt szűrő – ", "VapourSynth: filter skipped – ") + "; ".join(
                n.split(": ", 1)[-1][:160] for n in notes[:3])
        if len(out) == W * H * 3:
            try:
                self._post(lambda _r, _e, note=note: _note_popup(self, note), None, None)
            except Exception:           # noqa
                pass
        if len(out) != W * H * 3:
            with wk.cv:
                superseded = wk.req is not None or wk.dead
            if superseded:              # újabb kérés (pl. paraméter-módosítás) megölte ezt a számítást: nem hiba
                raise RuntimeError("stale")
            lines = verr.decode("utf-8", "replace").strip().splitlines()
            lines2 = (ferr or b"").decode("utf-8", "replace").strip().splitlines()
            raise RuntimeError(_last_error(lines) or _last_error(lines2)
                               or (T("A VapourSynth nem adott képkockát", "VapourSynth returned no frame")
                                   + " (vspipe rc=%s, ffmpeg rc=%s)." % (vp.returncode, fp.returncode)))
        return out
    finally:
        with wk.cv:
            wk.proc = None
        for pr in (fp, vp):
            if pr is not None:
                try:
                    if pr.poll() is None:
                        pr.kill()
                    pr.wait()
                except Exception:       # noqa
                    pass


def _tree_vs_summary(self):
    for i, sg in enumerate(getattr(self, "segs", [])):
        try:
            ff_names = E.summary(self._chain_of(sg)[1])
            vs_names = [item_label(it) for it in active_items(sg.get("state") or {})]
            parts = [ff_names] if ff_names else []
            if vs_names and vs_mode(sg.get("state") or {}) == "list":
                parts.append("VS: " + ", ".join(vs_names))
            self.tree.set(str(i), "x", " | ".join(parts) if parts else "–")
        except Exception:
            pass


def _update_chain(self):
    result = _ORIG["_update_chain"](self)
    _tree_vs_summary(self)
    return result


def _refresh_tree(self):
    result = _ORIG["_refresh_tree"](self)
    _tree_vs_summary(self)
    return result


def _start_play(self):
    """A VapourSynth-only osztott lejátszásnál is rajzoljon osztóvonalat és feliratokat."""
    result = _ORIG["_start_play"](self)
    sg = self._seg()
    st = getattr(self, "_pstate", None)
    if (st is not None and self.v_mode.get() == "split" and sg is not None
            and vs_active(sg.get("state") or {})):
        info = st.get("info", (False, float(self.v_split.get()) / 100.0))
        st["info"] = (True, info[1])
    return result


def _frame_done(self, req, data, err):
    """A VS-split előnézetnél is rajzoljon osztóvonalat, és törölje a befejezési jelzést."""
    try:
        draw_req = req
        if req.get("mode") == "split" and req.get("vs") and not req.get("chain"):
            # Az eredeti rajzoló a split jelzést az FFmpeg-lánc meglétéhez kötötte.
            # A VapourSynth-lánc külön fut, ezért itt csak a rajzolónak adunk jelzést.
            draw_req = dict(req, chain="<vapoursynth-chain>")
        return _ORIG["_frame_done"](self, draw_req, data, err)
    finally:
        if req.get("token") == getattr(self, "token", None):
            _busy(self, "")


def _frame_work(self, req, wk):
    if not req.get("vs"):
        return _ORIG["_frame_work"](self, req, wk)
    W, H, fps = req["W"], req["H"], req["fps"]
    fx = _still_fx(self, req, wk)
    if req["mode"] == "split":
        ss = max(0.0, req["t"] - 0.4 / fps)
        org = wk.run(self._vcmd(req["src"], ss, "", "orig", W, H, req["split"]), 180)
        if len(org) != W * H * 3:
            raise RuntimeError(T("Az eredeti kocka hiányzik.", "Original frame missing."))
        return split_rgb(org, fx, W, H, req["split"])
    return fx


def _refresh_preview(self):
    """Kényszerített újraszámolás (a duplikált kérések kiszűrése ilyenkor nem érvényes)."""
    self._vs_sig = None
    if getattr(self, "_ok", True):
        self._request()


def _request(self):
    self._after = None
    sg = self._seg()
    if sg is None or not self._ok:
        return
    if self._playing:
        self._start_play()
        return
    st = sg["state"]
    chain = self._chain_of(sg, preview=True)[0]     # a VapourSynth nélküli szűrőlánc; az időhöz kötött szűrők nélkül
    W, H = self._view_size()
    mode = self.v_mode.get()
    use_vs = vs_active(st) and mode != "orig"
    script = effective_script(st)
    req = dict(
        src=sg["src"], t=float(self.v_t.get()), mode=mode, chain=chain, W=W, H=H,
        split=float(self.v_split.get()) / 100.0, fps=self._fps(),
        vs=use_vs, script=script, vsp=dict(st.get("vs_params") or {}))
    if use_vs:
        # Ugyanaz a kérés már fut / kész: ne indítsunk újabb (nehéz) számítást, és ne dobjuk el a futót.
        try:
            mt = os.path.getmtime(script)
        except OSError:
            mt = 0
        paths = (str(self.p.cfg.get("vs_vspipe", "")), str(self.p.cfg.get("vs_plugins", "")))
        sig = repr(sorted(req.items(), key=lambda kv: kv[0])) + repr(mt) + repr(paths)
        if sig == getattr(self, "_vs_sig", None):
            return
        self._vs_sig = sig
        _busy(self, T("VapourSynth számol…", "VapourSynth is working…"))
    else:
        self._vs_sig = None
    self.token += 1
    req["token"] = self.token
    self.worker.submit(req)


# ------------------------------------------------------------------ lejátszás (vspipe | ffmpeg)
def _strip_end(cmd):
    """A vspipe parancsból elhagyja a végkocka-kapcsolót (-e N / --end N / --end=N)."""
    out, skip = [], False
    for a in cmd:
        if skip:
            skip = False
            continue
        sa = str(a)
        if sa in ("-e", "--end"):
            skip = True
            continue
        if sa.startswith("--end="):
            continue
        out.append(a)
    return out


def _vcmd(self, src, ss, chain, mode, W, H, split, play=False, dur=0.0, pfps=25.0):
    sg = self._seg()
    if not play or mode == "orig" or sg is None or not vs_active(sg["state"]):
        return _ORIG["_vcmd"](self, src, ss, chain, mode, W, H, split, play=play, dur=dur, pfps=pfps)
    st = sg["state"]
    vsp, plug = _paths(self)
    args = vb.script_args(src=sg["src"], plugin_dir=plug or None, params=dict(st.get("vs_params") or {}))
    args["plugdir"] = plug or ""
    fps = self._fps()
    idx0 = max(0, int(round(ss * fps)))
    nfr = int(math.ceil(dur * fps)) + 3
    # A szakasz a klip végéig is tarthat (itt: a teljes videó). Ilyenkor a „végkocka” (+3 tartalék) a klip mögé esne, és a
    # vspipe már indulás előtt hibával leáll („beyond clip end”) -> a lejátszás kép nélkül, csendben véget ér.
    # Megoldás: a klip vége közelében egyáltalán nem adunk meg végkockát; a leállást az ffmpeg „-t” és a csővezeték zárása adja.
    seg_last = int(float(sg["b"]) * fps)
    near_end = idx0 + nfr >= seg_last - int(2 * fps)
    vcmd = vb.vspipe_cmd(vsp, effective_script(st), args, start=idx0, end=idx0 + nfr)
    if near_end:
        vcmd = _strip_end(vcmd)
    disp = ("scale=trunc(iw*sar/2)*2:ih,setsar=1,scale=%d:%d:force_original_aspect_ratio=decrease,"
            "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:black,fps=%.6f") % (W, H, W, H, pfps)
    fxv = (chain + "," if chain else "") + disp
    ff = self.ff.ffmpeg
    base = [ff, "-v", "error", "-nostdin", "-f", "yuv4mpegpipe", "-i", "-"]
    tail = ["-t", "%.3f" % dur, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    if mode == "split":
        p = split
        fc = ("[0:v]%s[f];[1:v]%s[o];[o]crop=trunc(iw*%.4f/2)*2:ih:0:0[l];"
              "[f]crop=iw-trunc(iw*%.4f/2)*2:ih:trunc(iw*%.4f/2)*2:0[r];[l][r]hstack[out]") % (fxv, disp, p, p, p)
        fcmd = base + ["-ss", "%.3f" % ss, "-i", src, "-filter_complex", fc, "-map", "[out]"] + tail
    else:
        fcmd = base + ["-vf", fxv] + tail
    return ("pipe", vcmd, fcmd)


def _play_thread(self, gen, cmd, W, H, q):
    if not (isinstance(cmd, tuple) and len(cmd) == 3 and cmd[0] == "pipe"):
        return _ORIG["_play_thread"](self, gen, cmd, W, H, q)
    _, vcmd, fcmd = cmd
    E._log("LEJÁTSZÁS indul: %s | ffmpeg: %s" % (" ".join(vcmd)[:400], " ".join(fcmd)[:300]))
    fsz = W * H * 3
    vp = fp = None
    n = 0
    err = None
    verrs, ferrs = [], []           # a vspipe / ffmpeg hibakimenetének sorai (külön szálak olvassák: a tele cső megállítaná őket)
    t_start = time.time()

    def _say(msg, popup=False):
        def _f(_r, _e):
            if gen != self._pgen:
                return
            if popup:
                _note_popup(self, msg)
            else:
                _busy(self, msg)
        try:
            self._post(_f, None, None)
        except Exception:           # noqa
            pass

    def _drain(pipe, store, who):
        try:
            for raw in iter(pipe.readline, b""):
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                if len(store) < 200:
                    store.append(line)
                if line.startswith(("KIHAGYVA", "PLUGIN-HIBA")):
                    E._log("LEJÁTSZÁS (%s): %s" % (who, line))
                    _say(T("VapourSynth: kimaradt szűrő – ", "VapourSynth: filter skipped – ") + line.split(": ", 1)[-1][:160],
                         popup=True)
        except Exception:           # noqa
            pass
    try:
        vp = subprocess.Popen(vcmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                              creationflags=E._NOWIN)
        fp = subprocess.Popen(fcmd, stdin=vp.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              creationflags=E._NOWIN)
        vp.stdout.close()          # a csőnek csak az ffmpeg-oldala maradjon nyitva
        threading.Thread(target=_drain, args=(vp.stderr, verrs, "vspipe"), daemon=True).start()
        threading.Thread(target=_drain, args=(fp.stderr, ferrs, "ffmpeg"), daemon=True).start()
        if gen != self._pgen:
            return
        self._pproc = fp
        _say(T("VapourSynth indul…", "VapourSynth is starting…"))
        while gen == self._pgen:
            buf = fp.stdout.read(fsz)
            if len(buf) < fsz:
                break
            if n == 0:
                E._log("LEJÁTSZÁS: első kocka %.1f mp után" % (time.time() - t_start))
                _say("")
            while gen == self._pgen:
                try:
                    q.put((n, buf), timeout=0.05)
                    break
                except queue.Full:
                    continue
            n += 1
        if n == 0 and gen == self._pgen:
            try:
                vp.wait(timeout=5)
            except Exception:       # noqa
                pass
            time.sleep(0.3)         # a hibakimenetet olvasó szálak még befejezhetik
            err = _last_error(list(verrs)) or _last_error(list(ferrs))
            if not err:
                err = T("Nem érkezett képkocka a VapourSynthtől (részletek: efekt_naplo.txt).",
                        "No frame arrived from VapourSynth (see efekt_naplo.txt).")
            E._log("LEJÁTSZÁS: 0 kocka; vspipe rc=%s ffmpeg rc=%s; hiba: %s" % (vp.poll(), fp.poll(), err))
        elif n > 0 and gen == self._pgen:
            # A kép közben szakadt meg (pl. egy szűrő hibát dobott egy későbbi kockánál): ne maradjon csendben megfagyott kép.
            try:
                vp.wait(timeout=3)
            except Exception:       # noqa
                pass
            time.sleep(0.3)
            fails = [l for l in verrs if _VS_FAIL.search(l) and "fwrite" not in l.lower() and "errno" not in l.lower()]
            if fails:
                err = fails[-1]
                E._log("LEJÁTSZÁS: megszakadt %d kocka után; vspipe rc=%s; hiba: %s" % (n, vp.poll(), err))
    except Exception as e:          # noqa
        err = str(e)
        E._log("LEJÁTSZÁS kivétel: %s" % e)
    finally:
        try:
            E._log("LEJÁTSZÁS vége: kockák=%d, %.1f mp, vspipe rc=%s (None = még futott), ffmpeg rc=%s%s%s" % (
                n, time.time() - t_start, vp.poll() if vp else "-", fp.poll() if fp else "-",
                ("\n    vspipe: " + " | ".join(verrs[-3:])) if verrs else "",
                ("\n    ffmpeg: " + " | ".join(ferrs[-3:])) if ferrs else ""))
        except Exception:           # noqa
            pass
        for pr in (fp, vp):
            if pr is not None:
                try:
                    if pr.poll() is None:
                        pr.kill()
                    pr.wait()
                except Exception:   # noqa
                    pass
    while gen == self._pgen:        # a vége-jelzés (-1) a sor végére
        try:
            q.put((-1, err), timeout=0.05)
            break
        except queue.Full:
            continue


# ------------------------------------------------------------------ állapot (paraméterek szakaszonként)
def _collect(self):
    st = _ORIG["_collect"](self)
    sg = self._seg()
    s0 = (sg or {}).get("state") or {}
    st["vs_params"] = dict(s0.get("vs_params") or {})
    st["vs_chain"] = [dict(it) for it in (s0.get("vs_chain") or [])]
    st["vs_mode"] = vs_mode(s0)
    return st


def _sync(self, st):
    """A csúszkák értékét az állapotból tölti (a jelzőt visszaállítja, hogy ne fusson be a „változott” ág)."""
    vp = (st or {}).get("vs_params") or {}
    prev = self._loading
    self._loading = True
    try:
        for name, (var, kind, dflt) in getattr(self, "_vs_pvars", {}).items():
            val = vp.get(name, dflt)
            try:
                if kind == "bool":
                    var.set(bool(val))
                elif kind == "str":
                    var.set(str(val))
                else:
                    var.set(float(val))
            except Exception:       # noqa
                pass
    finally:
        self._loading = prev


def _load(self, st):
    _ORIG["_load"](self, st)
    _sync(self, st)
    _refresh_list_ui(self)
    if chain_items(st):
        _nscheck(self)


def _reset(self):
    sg = self._seg()
    if sg is not None:
        sg["state"]["vs_params"] = {}
        sg["state"]["vs_chain"] = []
        sg["state"]["vs_mode"] = "file"
    _ORIG["_reset"](self)
    _refresh_list_ui(self)


def _pchanged(self, name, kind, var):
    if self._loading or not self._ok:
        return
    try:
        v = var.get()
    except Exception:               # noqa
        return
    if kind == "int":
        v = int(round(float(v)))
    elif kind == "float":
        v = round(float(v), 4)
    elif kind == "bool":
        v = bool(v)
    else:
        v = str(v)
    sg = self._seg()
    if sg is None:
        return
    targets = self.segs if self.v_all.get() else [sg]
    for o in targets:
        vp = dict(o["state"].get("vs_params") or {})
        vp[name] = v
        o["state"]["vs_params"] = vp
    self._update_chain()
    self._schedule()


def _make_param(self, p):
    tk, ttk = self.tk, self.ttk
    row = ttk.Frame(self.vs_pframe)
    row.pack(fill="x", pady=1)
    ttk.Label(row, text=p["label"], width=18, anchor="w").pack(side="left")
    kind, name = p["kind"], p["name"]
    if kind == "bool":
        var = tk.BooleanVar(master=self.top, value=bool(p["default"]))
        ttk.Checkbutton(row, variable=var, takefocus=False).pack(side="left")
    elif kind == "str":
        var = tk.StringVar(master=self.top, value=str(p["default"]))
        ttk.Entry(row, textvariable=var, width=18).pack(side="left")
    else:
        var = tk.DoubleVar(master=self.top, value=float(p["default"]))
        lab = ttk.Label(row, width=8, anchor="e")

        def upd(*_a, lab=lab, var=var, kind=kind):
            try:
                v = var.get()
                lab.config(text=("%d" % round(v)) if kind == "int" else ("%.2f" % v))
            except Exception:       # noqa
                pass
        var.trace_add("write", upd)
        ttk.Scale(row, from_=p["lo"], to=p["hi"], orient="horizontal", variable=var, length=150).pack(
            side="left", padx=4)
        lab.pack(side="left")
        upd()
    self._vs_pvars[name] = (var, kind, p["default"])
    var.trace_add("write", lambda *a, n=name, k=kind, v=var: _pchanged(self, n, k, v))


def _rebuild(self):
    fr = getattr(self, "vs_pframe", None)
    if fr is None:
        return
    for w in fr.winfo_children():
        w.destroy()
    self._vs_pvars = {}
    sg = self._seg()
    st = sg["state"] if sg else {}
    path = effective_script(st) if vs_mode(st) == "list" else str(self.vars["vs_file"].get() or "").strip()
    params = []
    if path and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                params = vb.parse_params(fh.read())
        except OSError:
            params = []
    if not params:
        self.ttk.Label(fr, text=T("(nincs csúszka: a szűrőlista sablonjait a fenti listában töltöd ki)",
                                  "(no sliders: fill in the templates in the list above)"),
                       foreground="#555").pack(anchor="w")
        return
    for p in params:
        _make_param(self, p)
    sg = self._seg()
    _sync(self, sg["state"] if sg else {})


# ------------------------------------------------------------------ VapourSynth fül
def _profile_data(self):
    profiles = self.p.cfg.get("vs_profiles")
    if not isinstance(profiles, dict):
        profiles = {}
        self.p.cfg["vs_profiles"] = profiles
    return profiles


def _profile_refresh(self, select=None):
    names = sorted(_profile_data(self))
    self.vs_profile_cb["values"] = names
    if select in names:
        self.vs_profile.set(select)
    elif self.vs_profile.get() not in names:
        self.vs_profile.set(names[0] if names else "")


def _profile_snapshot(self):
    return {"vspipe": str(self.vs_vspipe.get() or "").strip(),
            "plugins": str(self.vs_plugins.get() or "").strip()}


def _profile_save_as(self):
    from tkinter import simpledialog
    name = (simpledialog.askstring(T("Környezet mentése", "Save environment"),
                                   T("A profil neve:", "Profile name:"), parent=self.top) or "").strip()
    if not name:
        return
    _profile_data(self)[name] = _profile_snapshot(self)
    self.vs_profile.set(name)
    self.p.cfg["vs_profile_active"] = name
    self._save_cfg()
    _profile_refresh(self, name)


def _profile_save(self):
    name = self.vs_profile.get().strip()
    if not name:
        return _profile_save_as(self)
    _profile_data(self)[name] = _profile_snapshot(self)
    self.p.cfg["vs_profile_active"] = name
    self._save_cfg()
    self.v_envstat.set(T("Profil mentve: %s", "Profile saved: %s") % name)


def _profile_load(self, _event=None):
    name = self.vs_profile.get().strip()
    data = _profile_data(self).get(name)
    if not isinstance(data, dict):
        return
    self.vs_vspipe.set(str(data.get("vspipe", "")))
    self.vs_plugins.set(str(data.get("plugins", "")))
    self.p.cfg["vs_profile_active"] = name
    self._save_cfg()
    self.v_envstat.set(T("Kiválasztott környezet: %s. Ellenőrizd vagy vizsgáld meg a plugineket.",
                         "Selected environment: %s. Check it or scan its plugins.") % name)


def _profile_delete(self):
    name = self.vs_profile.get().strip()
    if not name:
        return
    _profile_data(self).pop(name, None)
    if self.p.cfg.get("vs_profile_active") == name:
        self.p.cfg.pop("vs_profile_active", None)
    self._save_cfg()
    self.vs_profile.set("")
    _profile_refresh(self)
    self.v_envstat.set(T("Profil törölve: %s", "Profile removed: %s") % name)


def _env_render(self, rows):
    tree = getattr(self, "vs_envtree", None)
    if tree is None:
        return
    for iid in tree.get_children():
        tree.delete(iid)
    for n, row in enumerate(rows):
        result = row.get("result") or {}
        plugins = result.get("plugins") or []
        if result.get("ok") and plugins:
            for p in plugins:
                funcs = p.get("functions") or []
                tree.insert("", "end", iid="e%d_%d" % (n, len(tree.get_children())),
                            values=("✔ Betölthető", p.get("namespace", ""), p.get("name", ""),
                                    p.get("version", ""), "%d függvény" % len(funcs), row.get("path", "")),
                            tags=("ok",))
        else:
            message = str(result.get("message", "Ismeretlen hiba"))
            low = message.lower()
            not_plugin = any(mark in low for mark in ("no entry point", "entry point not", "not a plugin", "not a vapoursynth plugin"))
            status = T("– Nem VS-plugin", "– Not a VS plugin") if not_plugin else T("⚠ Betöltési hiba", "⚠ Load error")
            tree.insert("", "end", iid="e%d" % n,
                        values=(status, "", message[:110], "", "", row.get("path", "")),
                        tags=("notplugin" if not_plugin else "bad",))
    tree.tag_configure("ok", foreground="#176b36")
    tree.tag_configure("bad", foreground="#a12622")
    tree.tag_configure("notplugin", foreground="#777777")


# ------------------------------------------------------------------ VapourSynth fül

def _cfg(self, key, val):
    self.p.cfg[key] = str(val).strip()
    self._save_cfg()


def _askdir(self):
    try:
        return self.fd.askdirectory(parent=self.top)
    except AttributeError:
        import tkinter.filedialog as tf
        return tf.askdirectory(parent=self.top)


def _path_row(self, parent, label, var, dirmode, key):
    r = self.ttk.Frame(parent)
    r.pack(fill="x", pady=1)
    self.ttk.Label(r, text=label, width=12, anchor="w").pack(side="left")
    self.ttk.Entry(r, textvariable=var, width=34).pack(side="left")

    def browse():
        if dirmode:
            p = _askdir(self)
        else:
            p = self.fd.askopenfilename(parent=self.top, filetypes=[("vspipe.exe", "*.exe"), ("*", "*.*")])
        if p:
            var.set(os.path.normpath(p))
    self.ttk.Button(r, text="…", width=3, command=browse, takefocus=False).pack(side="left", padx=2)
    var.trace_add("write", lambda *a: _cfg(self, key, var.get()))


def _check(self):
    try:
        vsp, plug = _paths(self)
    except RuntimeError as e:
        self.v_envstat.set(str(e))
        return
    self.v_envstat.set(T("VapourSynth-környezet ellenőrzése…", "Checking VapourSynth environment…"))
    def run():
        r = vb.probe_setup(vsp, plugin_dll=None, src=None, timeout=120)
        self._post(lambda a, b, r=r: _check_done(self, r), None, None)
    threading.Thread(target=run, daemon=True).start()


def _check_done(self, r):
    if not self._ok:
        return
    if r.get("ok"):
        self.v_envstat.set("✔ %s, %s" % (r.get("core") or "", r.get("api") or ""))
    else:
        self.v_envstat.set(T("✘ Hiba: ", "✘ Error: ") + str(r.get("message") or ""))


def _tab_vs(self, f):
    tk, ttk = self.tk, self.ttk
    cfg = self.p.cfg
    self._vs_pvars = {}
    self._vs_lookup, self._vs_labels = {}, []
    sub = ttk.Notebook(f)
    sub.pack(fill="both", expand=True)
    env_page, filters_page = ttk.Frame(sub), ttk.Frame(sub)
    sub.add(env_page, text=T("Környezet és pluginek", "Environment & plugins"))
    sub.add(filters_page, text=T("Szűrőlánc", "Filter chain"))

    # 1. KÖRNYEZET: verzió, útvonalak, profilok és különálló pluginpróba.
    s = self._sec(env_page, "VapourSynth környezet")
    self._note(s, T("Ez a munkafül a megadott vspipe.exe és pluginmappa párosát vizsgálja. A DLL-jelöltek külön, "
                    "eldobható folyamatban töltődnek be; a program nem másolja és nem módosítja őket. Ez nem biztonsági "
                    "sandbox, ezért csak megbízható DLL-eket vizsgálj. A sikeres betöltés nem garantál minden szűrőbeállítást.",
                    "This workspace checks the selected vspipe.exe and plugin folder. DLL candidates are tested in "
                    "separate disposable processes; the app does not copy or modify them. This is not a security sandbox, "
                    "so scan only trusted DLLs. Successful loading does not guarantee every filter configuration."))
    v1 = tk.StringVar(master=self.top, value=str(cfg.get("vs_vspipe", "") or ""))
    self.vs_vspipe = v1
    _path_row(self, s, T("vspipe.exe", "vspipe.exe"), v1, False, "vs_vspipe")
    v2 = tk.StringVar(master=self.top, value=str(cfg.get("vs_plugins", "") or ""))
    self.vs_plugins = v2
    _path_row(self, s, T("Pluginmappa", "Plugin folder"), v2, True, "vs_plugins")
    pr = ttk.Frame(s)
    pr.pack(fill="x", pady=2)
    ttk.Label(pr, text=T("Környezetprofil:", "Environment profile:")).pack(side="left")
    self.vs_profile = tk.StringVar(master=self.top, value=str(cfg.get("vs_profile_active", "") or ""))
    self.vs_profile_cb = ttk.Combobox(pr, textvariable=self.vs_profile, state="readonly", width=24)
    self.vs_profile_cb.pack(side="left", padx=4)
    self.vs_profile_cb.bind("<<ComboboxSelected>>", lambda e: _profile_load(self, e))
    pr2 = ttk.Frame(s)
    pr2.pack(fill="x", pady=(0, 2))
    ttk.Button(pr2, text=T("Mentés újként…", "Save as…"), command=lambda: _profile_save_as(self), takefocus=False).pack(side="left", padx=2)
    ttk.Button(pr2, text=T("Profil frissítése", "Update profile"), command=lambda: _profile_save(self), takefocus=False).pack(side="left", padx=2)
    ttk.Button(pr2, text=T("Törlés", "Delete"), command=lambda: _profile_delete(self), takefocus=False).pack(side="left", padx=2)
    _profile_refresh(self, self.vs_profile.get())
    self.v_envstat = tk.StringVar(master=self.top, value="")
    ttk.Label(s, textvariable=self.v_envstat, wraplength=420, justify="left").pack(fill="x", pady=3)
    br = ttk.Frame(s)
    br.pack(fill="x", pady=2)
    ttk.Button(br, text=T("Környezet ellenőrzése", "Check environment"), command=lambda: _check(self), takefocus=False).pack(side="left")
    ttk.Button(br, text=T("Pluginok vizsgálata / megszakítás", "Scan plugins / cancel"), command=lambda: _cat_load(self, force=True), takefocus=False).pack(side="left", padx=4)
    treebox = ttk.LabelFrame(env_page, text=T("Pluginmappa DLL-jelöltjei — a fájl nem feltétlenül VapourSynth-plugin", "DLL candidates — a DLL is not necessarily a VapourSynth plugin"), padding=4)
    treebox.pack(fill="both", expand=True, padx=6, pady=4)
    self.vs_envtree = ttk.Treeview(treebox, columns=("status", "ns", "name", "version", "funcs", "path"), show="headings", height=8)
    for col, title, width in (("status", T("Állapot", "Status"), 80), ("ns", T("Névtér", "Namespace"), 60),
                              ("name", T("Plugin / hiba", "Plugin / error"), 110), ("version", T("Verzió", "Version"), 50),
                              ("funcs", T("Függvények", "Functions"), 60), ("path", T("Fájl", "File"), 130)):
        self.vs_envtree.heading(col, text=title)
        self.vs_envtree.column(col, width=width, minwidth=40, anchor="w", stretch=(col in ("name", "path")))
    sb = ttk.Scrollbar(treebox, orient="vertical", command=self.vs_envtree.yview)
    hsb = ttk.Scrollbar(treebox, orient="horizontal", command=self.vs_envtree.xview)
    self.vs_envtree.configure(yscrollcommand=sb.set, xscrollcommand=hsb.set)
    hsb.pack(side="bottom", fill="x")
    sb.pack(side="right", fill="y")
    self.vs_envtree.pack(side="left", fill="both", expand=True)

    # 2. SZŰRŐLÁNC: csak a kiválasztott környezetben katalógusba került szűrőket használd.
    sf = self._sec(filters_page, "VapourSynth szűrőlánc")
    self._note(sf, T("Előbb válaszd ki és ellenőrizd a VapourSynth-környezetet a „Környezet és pluginek” lapon. "
                     "Itt építheted fel a szűrőláncot, vagy saját .vpy fájlt használhatsz.",
                     "First select and check an environment on the “Environment & plugins” tab. Build a filter chain "
                     "here or use your own .vpy file."))
    self.check(sf, "vs_on", T("VapourSynth használata", "Use VapourSynth"))
    self.v_vsmode = tk.StringVar(master=self.top, value="file")
    mr = ttk.Frame(sf)
    mr.pack(fill="x", pady=2)
    ttk.Label(mr, text=T("Forrás:", "Source:")).pack(side="left")
    for val, hu, en in (("list", "Szűrőlista (automatikus)", "Filter list (auto)"),
                        ("file", "Saját .vpy szkript", "Own .vpy script")):
        ttk.Radiobutton(mr, text=T(hu, en), value=val, variable=self.v_vsmode, takefocus=False,
                        command=lambda v=val: _chain_edit(self, lambda L: L, mode=v)).pack(side="left", padx=4)
    lf = ttk.LabelFrame(sf, text=T("Szűrőlista (felülről lefelé)", "Filter list (top to bottom)"), padding=4)
    lf.pack(fill="x", pady=2)
    self.vs_lframe = ttk.Frame(lf)
    self.vs_lframe.pack(fill="x")
    ar = ttk.Frame(lf)
    ar.pack(fill="x", pady=2)
    mb = ttk.Button(ar, text=T("Kategóriák ▾", "Categories ▾"), takefocus=False)
    self._vs_catmenu = tk.Menu(mb, tearoff=0)
    def _pop_cat(mb=mb):
        try:
            self._vs_catmenu.tk_popup(mb.winfo_rootx(), mb.winfo_rooty() + mb.winfo_height())
        finally:
            self._vs_catmenu.grab_release()
    mb.configure(command=_pop_cat)
    mb.pack(side="left", padx=(0, 4))
    self.v_addf = ttk.Combobox(ar, width=26)
    self.v_addf.pack(side="left")
    ttk.Button(ar, text=T("↻ Katalógus", "↻ Catalog"), takefocus=False,
               command=lambda: _cat_load(self, force=True)).pack(side="left", padx=(4, 0))
    ar2 = ttk.Frame(lf)
    ar2.pack(fill="x", pady=(0, 2))
    ttk.Button(ar2, text=T("Kódsor beillesztése…", "Paste code…"), takefocus=False,
               command=lambda: _paste_dialog(self)).pack(side="left")
    ttk.Button(ar2, text=T("Összes kód…", "All code…"), takefocus=False,
               command=lambda: _all_code_window(self)).pack(side="left", padx=(4, 0))
    pm = ttk.Button(ar2, text=T("Saját előbeállítások ▾", "My presets ▾"), takefocus=False)
    self._vs_presetmenu = tk.Menu(pm, tearoff=0)

    def _pop_presets(pm=pm):
        try:
            self._vs_presetmenu.tk_popup(pm.winfo_rootx(), pm.winfo_rooty() + pm.winfo_height())
        finally:
            self._vs_presetmenu.grab_release()
    pm.configure(command=_pop_presets)
    pm.pack(side="left", padx=4)
    _fill_preset_menu(self)
    ar3 = ttk.Frame(lf)
    ar3.pack(fill="x", pady=(0, 2))
    pyb = ttk.Button(ar3, text=T("Python-függvények ▾", "Python functions ▾"), takefocus=False)
    self._vs_pymenu = tk.Menu(pyb, tearoff=0)

    def _pop_py(pyb=pyb):
        try:
            self._vs_pymenu.tk_popup(pyb.winfo_rootx(), pyb.winfo_rooty() + pyb.winfo_height())
        finally:
            self._vs_pymenu.grab_release()
    pyb.configure(command=_pop_py)
    pyb.pack(side="left")
    ttk.Button(ar3, text=T("↻ Python-vizsgálat", "↻ Scan Python"), takefocus=False,
               command=lambda: _pyf_load(self, force=True)).pack(side="left", padx=4)
    _fill_py_menu(self)
    ar4 = ttk.Frame(lf)
    ar4.pack(fill="x", pady=(0, 2))
    rb = ttk.Button(ar4, text=T("Ajánlott szűrők ▾", "Recommended filters ▾"), takefocus=False)
    self._vs_metamenu = tk.Menu(rb, tearoff=0)

    def _pop_meta(rb=rb):
        _fill_meta_menu(self)           # frissen, a katalógus aktuális állapotával (✔ / ✘)
        try:
            self._vs_metamenu.tk_popup(rb.winfo_rootx(), rb.winfo_rooty() + rb.winfo_height())
        finally:
            self._vs_metamenu.grab_release()
    rb.configure(command=_pop_meta)
    rb.pack(side="left")
    ttk.Label(ar4, text=T("kész paraméterekkel, címkékkel és előbeállításokkal", "with ready parameters, labels and presets"),
              foreground="#555").pack(side="left", padx=6)
    ttk.Label(lf, text=T("A katalógus csak az ellenőrzött környezetben felismert szűrőket jeleníti meg. A ★ jelűek "
                         "beépített példaszűrők.",
                         "The catalog shows filters discovered in the checked environment. ★ marks built-in example filters."),
              foreground="#555", wraplength=390, justify="left").pack(anchor="w")
    def _pick(_e=None):
        lab = self.v_addf.get().strip()
        ent = self._vs_lookup.get(lab)
        if ent is None:
            cand = _cat_values(self, lab)
            ent = self._vs_lookup.get(cand[0]) if len(cand) == 1 else None
        self.v_addf.set("")
        self.v_addf["values"] = _cat_values(self, "")
        if ent is not None:
            if ent[0] == "preset":
                _add(self, ent[1])
            else:
                _add_auto(self, ent[1], ent[2], ent[3])
    def _typed(e):
        if e.keysym in ("Return", "KP_Enter", "Up", "Down", "Left", "Right", "Tab", "Escape", "Shift_L", "Shift_R"):
            return
        self.v_addf["values"] = _cat_values(self, self.v_addf.get())
    self.v_addf.bind("<<ComboboxSelected>>", _pick)
    self.v_addf.bind("<Return>", _pick)
    self.v_addf.bind("<KeyRelease>", _typed)
    self.entry(sf, "vs_file", T("Szkript (.vpy)", "Script (.vpy)"), 24, browse=self._browse_vpy)
    try:                                    # a mező ne nyúljon az egész panel szélességére
        _ent = sf.winfo_children()[-1].winfo_children()[1]
        _ent.pack_configure(fill="none", expand=False)
    except Exception:       # noqa
        pass
    r = ttk.Frame(sf)
    r.pack(fill="x", pady=3)
    ttk.Button(r, text=T("Sablon-szkript…", "Template script…"), command=self._make_vpy, takefocus=False).pack(side="left")
    ttk.Button(r, text=T("↻ Előnézet frissítése", "↻ Refresh preview"), takefocus=False,
               command=lambda: _refresh_preview(self)).pack(side="left", padx=4)
    self.v_vsstat = tk.StringVar(master=self.top, value="")
    ttk.Label(sf, textvariable=self.v_vsstat, wraplength=390, justify="left").pack(fill="x", pady=2)
    self.vs_pframe = ttk.LabelFrame(sf, text=T("Állítható paraméterek (a ★ szűrők csúszkái)",
                                               "Adjustable parameters (★ filter sliders)"), padding=4)
    self.vs_pframe.pack(fill="x", pady=4)
    self.vars["vs_file"].trace_add("write", lambda *a: _rebuild(self))
    for v in (v1, v2):
        v.trace_add("write", lambda *a: _cat_later(self))
    _rebuild(self)
    _cat_set(self, [])
    _cat_load(self)
    _pyf_load(self)


# ------------------------------------------------------------------ plugin-katalógus (UI)
def _cat_values(self, text=""):
    t = (text or "").strip().lower()
    labs = getattr(self, "_vs_labels", [])
    return [l for l in labs if t in l.lower()][:400] if t else labs[:400]


def _add_label(self, lab):
    ent = self._vs_lookup.get(lab)
    if ent is None:
        return
    if ent[0] == "preset":
        _add(self, ent[1])
    else:
        _add_auto(self, ent[1], ent[2], ent[3])


def _fill_menu(self, presets, groups):
    """A „Kategóriák” menü (kategóriánként egy almenü, hosszú listáknál több oszlopban."""
    m = getattr(self, "_vs_catmenu", None)
    if m is None:
        return
    try:
        for w in m.winfo_children():
            w.destroy()
        m.delete(0, "end")

        def sub(title, labs, strip):
            sm = self.tk.Menu(m, tearoff=0)
            for i, lab in enumerate(labs):
                sm.add_command(label=lab.split(CAT_SEP, 1)[-1] if strip else lab,
                               command=lambda l=lab: _add_label(self, l), columnbreak=1 if (i and i % 25 == 0) else 0)
            m.add_cascade(label="%s (%d)" % (title, len(labs)), menu=sm)
        if presets:
            sub(T("★ Beépített (csúszkás)", "★ Built-in (sliders)"), presets, False)
        for key in CAT_ORDER:
            if groups.get(key):
                sub(T(*CAT_NAMES[key][1]), groups[key], True)
        if m.index("end") is None:
            m.add_command(label=T("(nincs plugin-lista – ↻ Pluginok)", "(no plugin list – ↻ Plugins)"), state="disabled")
    except Exception:               # noqa
        pass


def _cat_set(self, items):
    """A legördülő lista tartalma: először a beépített (★) szűrők, utána a plugin-mappából felderítettek,
    kategória szerint csoportosítva („Zaj · dfttest2_cuda.DFTTest”). A kategória névre is lehet keresni."""
    lookup, labels, presets = {}, [], []
    self._vs_sigs = {"%s.%s" % (it[0], it[1]): it[2] for it in (items or []) if isinstance(it, (list, tuple)) and len(it) >= 3} or None
    available_ns = {str(it[0]) for it in (items or []) if isinstance(it, (list, tuple)) and it}
    for fid in FILTERS:
        preset = FILTERS[fid]
        required_ns = {preset.get("ns", "")} | set(preset.get("needs", ()))
        if any(ns and ns not in available_ns for ns in required_ns):
            continue
        lab = "★ " + T(*preset["label"])
        lookup[lab] = ("preset", fid)
        labels.append(lab)
        presets.append(lab)
    seen, rows = set(), []
    for ns, fn, sig in items or []:
        plain = "%s.%s" % (ns, fn)
        if plain in seen or ns in _NEEDS_PIPELINE_NS or not is_simple_sig(sig) or not _IDENT.match(ns) or not _IDENT.match(fn):
            continue
        seen.add(plain)
        rows.append((CAT_ORDER.index(categorize(ns, fn)), ns.lower(), fn.lower(), ns, fn, sig))
    rows.sort()
    groups = {}
    for oi, _a, _b, ns, fn, sig in rows:
        key = CAT_ORDER[oi]
        lab = "%s%s%s.%s" % (T(*CAT_NAMES[key][0]), CAT_SEP, ns, fn)
        lookup[lab] = ("auto", ns, fn, sig)
        labels.append(lab)
        groups.setdefault(key, []).append(lab)
    self._vs_lookup, self._vs_labels = lookup, labels
    try:
        self.v_addf["values"] = labels[:400]
    except Exception:               # noqa
        pass
    _fill_menu(self, presets, groups)
    return len(rows)


def _cat_later(self):
    try:
        if getattr(self, "_vs_cat_after", None):
            self.top.after_cancel(self._vs_cat_after)
        self._vs_cat_after = self.top.after(900, lambda: _cat_load(self))
    except Exception:               # noqa
        pass


def _cat_load(self, force=False):
    """A felderítést DLL-enként, külön vspipe-folyamatban végzi; a hibás plugin nem állítja le a többit."""
    self._vs_cat_after = None
    if not getattr(self, "_ok", True):
        return
    try:
        vsp, plug = _paths(self)
    except RuntimeError as exc:
        _cat_set(self, [])
        self.v_vsstat.set(str(exc))
        return
    key = "%s|%s|%s|v3-isolated" % (vsp, plug, plug_sig(plug))
    if not force:
        items = load_catalog(key)
        if items is not None:
            _cat_set(self, items)
            self.v_vsstat.set(T("✔ Gyorsítótárazott katalógus: %d szűrő. Új vizsgálathoz használd a ↻ Katalógus gombot.",
                                "✔ Cached catalog: %d filters. Use ↻ Catalog to rescan.") % len(items))
            return
        self.v_vsstat.set(T("A pluginok első vizsgálatához nyomd meg a ↻ Katalógus gombot a Szűrőlánc lapon.",
                            "Press ↻ Catalog on the Filter chain tab to run the first plugin scan."))
        return
    active = getattr(self, "_vs_catalog_cancel", None)
    if active is not None and not active.is_set():
        active.set()
        self.v_envstat.set(T("Leállítás kérése… kattints újra a vizsgálat folytatásához.",
                             "Stopping scan… click again to start another scan."))
        return
    cancel = threading.Event()
    self._vs_catalog_cancel = cancel
    self.v_envstat.set(T("Pluginok külön vizsgálata indul… a gombbal megszakítható.",
                         "Starting isolated plugin scan… press the button to cancel."))

    def progress(done, total, path, result):
        if done % 5 == 0 or done == total:
            self._post(lambda a, b, d=done, t=total, p=path:
                       self.v_envstat.set(T("Vizsgálat: %d / %d — %s", "Scanning: %d / %d — %s") %
                                          (d, t, os.path.basename(p))), None, None)

    def run():
        core_items, core_err = vs_env.probe_core_catalog(vsp)
        rows, total = vs_env.scan_plugins(vsp, plug, timeout=10, cancel=cancel, progress=progress)
        items = list(core_items or [])
        for row in rows:
            result = row.get("result") or {}
            for plugin in result.get("plugins") or []:
                ns = plugin.get("namespace", "")
                for fn, sig in plugin.get("functions") or []:
                    items.append([ns, fn, sig])
        # Stabil, duplikációmentes katalógus: azonos namespace/fn esetén az első bejegyzés marad.
        unique, seen = [], set()
        for it in items:
            if len(it) >= 3 and (it[0], it[1]) not in seen:
                seen.add((it[0], it[1]))
                unique.append(it[:3])
        if not cancel.is_set():
            save_catalog(key, unique)
        report = {"rows": rows, "total": total, "core_error": core_err, "cancelled": cancel.is_set()}
        self._post(lambda a, b, its=unique, rep=report: _cat_done(self, its, rep), None, None)
    threading.Thread(target=run, daemon=True).start()


def _cat_done(self, items, report):
    if not self._ok:
        return
    if items is None:
        self.v_vsstat.set(T("✘ Plugin-katalógus nem készíthető.", "✘ Plugin catalog could not be created."))
        return
    if isinstance(report, dict):
        rows = report.get("rows", [])
        _env_render(self, rows)
        good = sum(1 for row in rows if (row.get("result") or {}).get("ok"))
        not_plugin = sum(1 for row in rows if not (row.get("result") or {}).get("ok") and any(
            mark in str((row.get("result") or {}).get("message", "")).lower()
            for mark in ("no entry point", "entry point not", "not a plugin", "not a vapoursynth plugin")))
        checked = len(rows)
        errors = checked - good - not_plugin
        total = report.get("total", 0)
        n = _cat_set(self, items)
        core_error = report.get("core_error")
        lead = T("Megszakítva — részleges eredmény. ", "Cancelled — partial results. ") if report.get("cancelled") else ""
        self.v_envstat.set(lead + T("Ellenőrizve %d/%d DLL-jelölt: %d működik ezzel a környezettel, %d nem VapourSynth-plugin, %d betöltési hiba. Katalógus: %d függvény.",
                                    "Checked %d/%d DLL candidates: %d load in this environment, %d are not VapourSynth plugins, %d have load errors. Catalog: %d functions.") %
                           (checked, total, good, not_plugin, errors, n))
        if core_error:
            self.v_vsstat.set(T("A beépített szűrők egy része nem olvasható ki: ",
                                "Some built-in filters could not be read: ") + str(core_error))
        else:
            self.v_vsstat.set(T("✔ Katalógus frissítve: %d használható függvény.",
                                "✔ Catalog updated: %d usable functions.") % n)
    else:
        n = _cat_set(self, items)
        self.v_vsstat.set(T("✔ Katalógus betöltve: %d szűrő.", "✔ Catalog loaded: %d filters.") % n)


# ------------------------------------------------------------------ szűrőlista (UI-műveletek)
def _chain_edit(self, fn, mode=None):
    """A szűrőlistát (és a módot) módosítja: a jelenlegi szakaszra, vagy mindre, ha az „összes szakasz” be van kapcsolva."""
    sg = self._seg()
    if sg is None:
        return
    targets = self.segs if self.v_all.get() else [sg]
    for o in targets:
        st = o["state"]
        st["vs_chain"] = sort_chain(fn(sort_chain([dict(it) for it in (st.get("vs_chain") or [])])))
        if mode:
            st["vs_mode"] = mode
    _refresh_list_ui(self)
    _nscheck(self)
    self._update_chain()
    self._schedule()


def _add(self, fid):
    uid = "f" + secrets.token_hex(3)
    _chain_edit(self, lambda L: L + [{"id": fid, "uid": uid}], mode="list")


def _add_auto(self, ns, fn, sig):
    uid = "f" + secrets.token_hex(3)
    _chain_edit(self, lambda L: L + [{"id": "auto", "uid": uid, "ns": ns, "fn": fn, "sig": sig, "vals": {}}],
                mode="list")


# ------------------------------------------------------------------ beillesztett kód: kártyák (vs_code)
_QTGMC_PRESETS = ["Placebo", "Very Slow", "Slower", "Slow", "Medium", "Fast", "Faster", "Very Fast", "Super Fast",
                  "Ultra Fast", "Draft"]


def _new_uid():
    return "f" + secrets.token_hex(3)


def _add_code_items(self, items):
    """Beillesztett / előbeállításból származó kártyák hozzáadása a lista végére (bekapcsolva)."""
    uids = [_new_uid() for _ in items]
    _chain_edit(self, lambda L: L + [dict(copy.deepcopy(x), uid=u, enabled=True) for x, u in zip(items, uids)],
                mode="list")


def _toggle(self, uid, on):
    _chain_edit(self, lambda L: [dict(it, enabled=on) if it.get("uid") == uid else it for it in L])


def _find_item(self, uid):
    sg = self._seg()
    return next((x for x in chain_items(sg["state"]) if x.get("uid") == uid), None) if sg else None


def _set_kw(self, uid, name, text, delay=900):
    def fn(it):
        it["kw"] = [[k, (text if k == name else v)] for k, v in (it.get("kw") or [])]
    _patch_item(self, uid, fn, delay=delay)


def _tip(self, w, text):
    """Egyszerű súgó-buborék: az egér ráhúzásakor jelenik meg."""
    if not text:
        return
    box = [None]

    def hide(_e=None):
        if box[0] is not None:
            try:
                box[0].destroy()
            except Exception:       # noqa
                pass
            box[0] = None

    def show(e):
        hide()
        try:
            t = self.tk.Toplevel(w)
            t.wm_overrideredirect(True)
            t.wm_geometry("+%d+%d" % (e.x_root + 12, e.y_root + 16))
            self.tk.Label(t, text=text, justify="left", background="#ffffe0", relief="solid", borderwidth=1,
                          wraplength=320).pack()
            box[0] = t
        except Exception:           # noqa
            box[0] = None
    w.bind("<Enter>", show, add="+")
    w.bind("<Leave>", hide, add="+")
    w.bind("<Destroy>", hide, add="+")


def _code_row(self, parent, it, name, text):
    """Egy kulcsszavas paraméter sora: az érték típusából (és a metaadat-könyvtárból) lesz a felületi elem:
    pipa / legördülő lista / számmező + csúszka / szöveg."""
    tk, ttk = self.tk, self.ttk
    uid = it["uid"]
    meta = meta_for(it)
    pm = vs_meta.param(meta, name)
    kind = vs_code.kind_of(text)
    row = ttk.Frame(parent)
    row.pack(fill="x", pady=1)
    lab = L(pm["label"]) if pm else name
    lbl = ttk.Label(row, text=lab, width=20, anchor="w")
    lbl.pack(side="left")
    tip = (name + (" – " + L(pm["help"]) if pm and pm["help"] else "")) if pm else ""
    _tip(self, lbl, tip if (pm and (tip != name or lab != name)) else "")
    ttk.Button(row, text="↺", width=2, takefocus=False,
               command=lambda: _del_kw(self, uid, name)).pack(side="right", padx=(2, 0))   # vissza a függvény alapértékére

    def apply(val, delay=900):
        _set_kw(self, uid, name, val, delay)

    choices = pm["choices"] if (pm and pm["choices"] and kind in ("int", "float", "str")) else None
    if choices:
        cur = vs_code.str_of(text) if kind == "str" else str(text).strip()
        var = tk.StringVar(master=self.top, value=cur)
        cb = ttk.Combobox(row, textvariable=var, values=[str(c) for c in choices], state="readonly", width=16)
        cb.pack(side="left")

        def picked(_e=None):
            v = var.get()
            apply(vs_code.fmt_str(v) if kind == "str" else vs_code.fmt_number(kind, float(v)), 250)
        cb.bind("<<ComboboxSelected>>", picked)
    elif kind == "bool":
        var = tk.BooleanVar(master=self.top, value=(str(text).strip() == "True"))
        ttk.Checkbutton(row, variable=var, takefocus=False).pack(side="left")
        var.trace_add("write", lambda *a: apply("True" if var.get() else "False", 250))
    elif kind in ("int", "float"):
        var = tk.StringVar(master=self.top, value=str(text).strip())
        cur = vs_code.number_of(text)
        if pm and pm["lo"] is not None and pm["hi"] is not None:
            lo, hi = min(pm["lo"], cur), max(pm["hi"], cur)
        else:
            lo, hi = vs_code.guess_range(kind, text)
        step = pm["step"] if pm else vs_code.step_of(kind, text)
        ttk.Spinbox(row, from_=-1e9, to=1e9, increment=step, width=9, textvariable=var).pack(side="left")
        sc = ttk.Scale(row, from_=lo, to=hi, orient="horizontal", length=150)
        sc.set(cur)
        sc.pack(side="left", padx=4)
        busy = [False]

        def from_scale(x):
            if busy[0]:
                return
            busy[0] = True
            try:
                var.set(vs_code.fmt_number(kind, _snap(float(x), step, kind)))
            finally:
                busy[0] = False

        def from_var(*_a):
            try:
                x = float(var.get().strip().replace(",", "."))
            except ValueError:
                return
            if not busy[0]:
                busy[0] = True
                try:
                    sc.set(min(max(x, lo), hi))
                finally:
                    busy[0] = False
            apply(vs_code.fmt_number(kind, x), 450)
        sc.configure(command=from_scale)
        var.trace_add("write", from_var)
    elif kind == "str":
        var = tk.StringVar(master=self.top, value=vs_code.str_of(text))
        pre = _QTGMC_PRESETS if (name.lower() == "preset" and str(it.get("func", "")).endswith("QTGMC")) else None
        if pre:
            ttk.Combobox(row, textvariable=var, values=pre, width=20).pack(side="left")
        else:
            ttk.Entry(row, textvariable=var, width=22).pack(side="left")
        var.trace_add("write", lambda *a: apply(vs_code.fmt_str(var.get()), 700))
    else:                                   # lista, None, név, hívás ...: szabad Python-kifejezés
        var = tk.StringVar(master=self.top, value=str(text))
        en = ttk.Entry(row, textvariable=var, width=22)
        en.pack(side="left")

        def from_text(*_a):
            ok = vs_code.valid_expr(var.get())
            try:
                en.configure(foreground="" if ok else "#b00020")
            except Exception:       # noqa
                pass
            if ok:
                apply(var.get().strip(), 900)
        var.trace_add("write", from_text)


def _snap(x, step, kind):
    """A csúszka értékét a lépésközhöz igazítja (egésznél egészre, törtnél a lépés többszörösére)."""
    if kind == "int":
        return round(x)
    try:
        return round(x / step) * step if step else x
    except (TypeError, ZeroDivisionError):
        return x


def _code_body(self, fr, it):
    ttk = self.ttk
    box = ttk.Frame(fr, padding=(22, 0, 0, 3))
    box.pack(fill="x")
    info = _py_info(self, it.get("func")) if "raw" not in it else None
    meta = meta_for(it)
    if meta:
        text = L(meta["help"]) or L(meta["label"])
        ttk.Label(box, text=text, foreground="#555", wraplength=330, justify="left").pack(anchor="w", pady=(0, 2))
        if meta["presets"]:
            pr = ttk.Frame(box)
            pr.pack(fill="x", pady=(0, 2))
            ttk.Label(pr, text=T("Előbeállítás:", "Preset:"), width=20, anchor="w").pack(side="left")
            names = [L(p["name"]) for p in meta["presets"]]
            cur = vs_meta.preset_match(it, meta)
            pv = self.tk.StringVar(master=self.top, value=names[cur] if cur is not None else T("(egyéni)", "(custom)"))
            cb = ttk.Combobox(pr, textvariable=pv, values=names, state="readonly", width=16)
            cb.pack(side="left")
            cb.bind("<<ComboboxSelected>>", lambda _e, u=it["uid"], c=cb: _apply_meta_preset(self, u, c.current()))
    elif info and info.get("doc"):
        ttk.Label(box, text=info["doc"], foreground="#555", wraplength=330, justify="left").pack(anchor="w", pady=(0, 2))
    if "raw" in it:
        first = (str(it["raw"]).splitlines() or [""])[0]
        ttk.Label(box, text=T("Egyéni kód, nincs állítható paraméter: ", "Custom code, no adjustable parameters: ") + first[:60],
                  foreground="#555", wraplength=330, justify="left").pack(anchor="w")
    elif it.get("kw"):
        for k, v in it["kw"]:
            _code_row(self, box, it, k, v)
    else:
        ttk.Label(box, text=T("(nincs kulcsszavas paraméter – a „Kód…” gombbal szerkeszthető)",
                              "(no keyword parameters – use “Code…” to edit)"), foreground="#555").pack(anchor="w")
    r = ttk.Frame(box)
    r.pack(fill="x", pady=2)
    if _known_params(self, it):
        pb = ttk.Button(r, text=T("Paraméter ▾", "Parameter ▾"), takefocus=False)
        pb.configure(command=lambda u=it["uid"], b=pb: _param_menu(self, u, b))
        pb.pack(side="left", padx=(0, 4))
    ttk.Button(r, text=T("Kód…", "Code…"), takefocus=False,
               command=lambda u=it["uid"]: _edit_code(self, u)).pack(side="left")
    ttk.Button(r, text=T("Mentés előbeállításként…", "Save as preset…"), takefocus=False,
               command=lambda u=it["uid"]: _save_preset(self, u)).pack(side="left", padx=4)


def _text_window(self, title, hint, initial, ok_text, on_ok):
    """Kis szerkesztő-ablak (beillesztés / kód-szerkesztés). on_ok(text) -> None (siker, bezár) vagy hibaszöveg."""
    tk, ttk = self.tk, self.ttk
    win = tk.Toplevel(self.top)
    win.title(title)
    win.geometry("760x420")
    win.transient(self.top)
    ttk.Label(win, text=hint, wraplength=720, justify="left", foreground="#555").pack(fill="x", padx=8, pady=(8, 2))
    bt = ttk.Frame(win)
    bt.pack(side="bottom", fill="x", padx=8, pady=6)
    msg = tk.StringVar(master=win, value="")
    ttk.Label(win, textvariable=msg, foreground="#b00020", wraplength=720, justify="left").pack(side="bottom", fill="x", padx=8)
    box = ttk.Frame(win)
    box.pack(fill="both", expand=True, padx=8, pady=2)
    txt = tk.Text(box, wrap="none", font="TkFixedFont", undo=True)
    sy = ttk.Scrollbar(box, orient="vertical", command=txt.yview)
    sx = ttk.Scrollbar(win, orient="horizontal", command=txt.xview)
    txt.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
    sy.pack(side="right", fill="y")
    txt.pack(side="left", fill="both", expand=True)
    sx.pack(side="top", fill="x", padx=8)
    txt.insert("1.0", initial)
    txt.focus_set()

    def ok():
        err = on_ok(txt.get("1.0", "end"))
        if err:
            msg.set(err)
        else:
            win.destroy()
    ttk.Button(bt, text=ok_text, command=ok).pack(side="right", padx=4)
    ttk.Button(bt, text=T("Mégse", "Cancel"), command=win.destroy).pack(side="right")
    return win


def _all_code_text(self, full):
    """A jelenlegi szakasz szűrőláncának kódja egymás alatt. full=True: a program által generált teljes .vpy szkript."""
    sg = self._seg()
    if sg is None:
        return ""
    st = sg["state"]
    if full:
        items = active_items(st)
        if not items:
            return T("# Nincs bekapcsolt VapourSynth-szűrő.", "# No VapourSynth filter is enabled.")
        try:
            return build_list_script(items)
        except Exception as e:          # noqa
            return "# %s" % e
    blocks = []
    for n, it in enumerate(chain_items(st), 1):
        try:
            if it.get("id") == "code":
                txt = vs_code.code_text(it)
            elif it.get("id") in FILTERS:
                txt = FILTERS[it["id"]]["code"].format(u=it["uid"])
            else:
                call, warn = auto_call(it)
                txt = ("clip = " + call) if call else "# %s" % warn
        except Exception as e:          # noqa
            txt = "# %s" % e
        txt = str(txt).rstrip("\n")
        if not it.get("enabled", True):
            txt = "# [%d] %s\n%s" % (n, T("KIKAPCSOLVA", "DISABLED"), "\n".join("# " + ln for ln in txt.splitlines()))
        blocks.append(txt)
    return "\n\n".join(blocks) if blocks else T("# A szűrőlista üres.", "# The filter list is empty.")


def _all_code_window(self):
    """Egy ablakban, egymás alatt mutatja a szűrőlista összes kódsorát (a kártyákká alakított sorokat is). Csak olvasható,
    másolható; a „Frissítés” az aktuális állapotot tölti be, a pipa a teljes generált szkriptet mutatja."""
    tk, ttk = self.tk, self.ttk
    if self._seg() is None:
        return
    old = getattr(self, "_vs_allcode", None)
    try:
        if old is not None and old.winfo_exists():
            old.deiconify()
            old.lift()
            old.focus_force()
            old._refresh()
            return
    except Exception:       # noqa
        pass
    win = tk.Toplevel(self.top)
    win.title(T("VapourSynth – az összes kód", "VapourSynth – all code"))
    win.geometry("900x560")
    self._vs_allcode = win
    full = tk.BooleanVar(master=win, value=False)
    bt = ttk.Frame(win)
    bt.pack(side="bottom", fill="x", padx=8, pady=6)
    ttk.Checkbutton(win, text=T("Teljes generált szkript (.vpy) mutatása", "Show the full generated script (.vpy)"),
                    variable=full, command=lambda: win._refresh()).pack(side="bottom", anchor="w", padx=8)
    box = ttk.Frame(win)
    box.pack(fill="both", expand=True, padx=8, pady=(8, 2))
    txt = tk.Text(box, wrap="none", font="TkFixedFont", undo=False)
    sy = ttk.Scrollbar(box, orient="vertical", command=txt.yview)
    sx = ttk.Scrollbar(win, orient="horizontal", command=txt.xview)
    txt.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
    sy.pack(side="right", fill="y")
    txt.pack(side="left", fill="both", expand=True)
    sx.pack(side="top", fill="x", padx=8, before=bt)

    def refresh():
        txt.configure(state="normal")
        txt.delete("1.0", "end")
        txt.insert("1.0", _all_code_text(self, full.get()))
        txt.configure(state="disabled")
    win._refresh = refresh

    def copy():
        try:
            win.clipboard_clear()
            win.clipboard_append(_all_code_text(self, full.get()))
        except Exception:       # noqa
            pass
    ttk.Button(bt, text=T("Bezárás", "Close"), command=win.destroy).pack(side="right")
    ttk.Button(bt, text=T("Másolás vágólapra", "Copy to clipboard"), command=copy).pack(side="right", padx=4)
    ttk.Button(bt, text=T("Frissítés", "Refresh"), command=refresh).pack(side="right")
    win.bind("<Escape>", lambda e: win.destroy())
    refresh()


def _notes_text(notes):
    return "\n".join(T(*n) for n in notes)


def _paste_dialog(self):
    if self._seg() is None:
        return

    def on_ok(text):
        items, notes = vs_code.parse_paste(text)
        if not items:
            return _notes_text(notes) or T("Üres a beillesztett kód.", "The pasted code is empty.")
        _add_code_items(self, items)
        if notes:
            try:
                self.mb.showinfo("VapourSynth", _notes_text(notes), parent=self.top)
            except Exception:       # noqa
                pass
        return None
    _text_window(self, T("Kódsor beillesztése", "Paste code"),
                 T("Illessz be egy vagy több működő VapourSynth-sort (pl. a StaxRip Code Editorából). Az egyes hívásokból "
                   "kártya lesz állítható paraméterekkel; a def-blokkok egyéni kódként maradnak meg. A forrást és a vágást "
                   "(%source_file%, %crop_left% ...) a program maga kezeli, ezek a sorok kimaradnak.",
                   "Paste one or more working VapourSynth lines (e.g. from the StaxRip Code Editor). Each call becomes a card "
                   "with adjustable parameters; def blocks stay as custom code. The source and cropping "
                   "(%source_file%, %crop_left% ...) are handled by the program, those lines are skipped."),
                 "clip = ", T("Hozzáadás", "Add"), on_ok)


def _edit_code(self, uid):
    it = _find_item(self, uid)
    if it is None:
        return

    def on_ok(text):
        items, notes = vs_code.parse_paste(text)
        if not items:
            return _notes_text(notes) or T("Üres a kód.", "The code is empty.")
        uids = [uid] + [_new_uid() for _ in items[1:]]
        enabled = it.get("enabled", True)
        _chain_edit(self, lambda L: [y for x in L for y in (
            [dict(copy.deepcopy(n), uid=u, enabled=enabled) for n, u in zip(items, uids)] if x.get("uid") == uid else [x])],
            mode="list")
        return None
    _text_window(self, T("Kód szerkesztése", "Edit code"),
                 T("A kártya kódja. Ha egyetlen „clip = fv(...)” hívás marad, a paraméterek újra csúszkákká / mezőkké válnak.",
                   "The card's code. If it stays a single “clip = fn(...)” call, its parameters become sliders / fields again."),
                 vs_code.code_text(it), T("Alkalmaz", "Apply"), on_ok)


# ------------------------------------------------------------------ Python-függvények (vs_pyscan): paraméterek alapértékkel
def _py_info(self, func):
    return getattr(self, "_vs_pyf", {}).get(func) if func else None


def _del_kw(self, uid, name):
    _chain_edit(self, lambda L: [vs_code.without_kw(it, name) if it.get("uid") == uid else it for it in L])


def _add_kw(self, uid, name, value):
    _chain_edit(self, lambda L: [vs_code.with_kw(it, name, value) if it.get("uid") == uid else it for it in L])


def _sig_names(self, key):
    """A plugin tényleges paraméternevei (a katalógusból), vagy None, ha a katalógus még nincs betöltve."""
    sigs = getattr(self, "_vs_sigs", None)
    sg = sigs.get(key) if sigs else None
    return {n for n, _t, _o in parse_sig(sg)} if sg else None


def _known_params(self, it):
    """A kártyához ismert paraméterek: [(név, alapérték-kifejezés | None, címke), ...]. Forrás: a metaadat-könyvtár
    (a telepített plugin szignatúrájával szűrve), különben a Python-függvény szignatúrája (vs_pyscan)."""
    m = meta_for(it)
    if m:
        return [(n, d, L(lab)) for n, d, lab in vs_meta.known_params(m, _sig_names(self, m["key"]))]
    info = _py_info(self, it.get("func")) if "raw" not in it else None
    return [(n, d, "") for n, d in (info.get("params") if info else None) or []]


def _apply_meta_preset(self, uid, idx):
    def fn(L_):
        out = []
        for x in L_:
            m = meta_for(x) if x.get("uid") == uid else None
            out.append(vs_meta.apply_preset(x, m, idx) if m else x)
        return out
    _chain_edit(self, fn)


def _param_menu(self, uid, btn):
    """A kártyára még fel nem vett, ismert paraméterek az alapértékükkel; a kiválasztott a kártyára kerül."""
    it = _find_item(self, uid)
    if it is None:
        return
    have = {p[0] for p in (it.get("kw") or [])}
    miss = [p for p in _known_params(self, it) if p[0] not in have]
    m = self.tk.Menu(btn, tearoff=0)
    if not miss:
        m.add_command(label=T("(nincs több ismert paraméter)", "(no more known parameters)"), state="disabled")
    for i, (n, d, lab) in enumerate(miss):
        text = "%s%s = %s" % (lab + " – " if lab and lab != n else "", n, (d if d is not None else "?")[:32])
        m.add_command(label=text, command=lambda n=n, d=d: _add_kw(self, uid, n, d if d is not None else "None"),
                      columnbreak=1 if (i and i % 25 == 0) else 0)
    try:
        m.tk_popup(btn.winfo_rootx(), btn.winfo_rooty() + btn.winfo_height())
    finally:
        m.grab_release()


def _fill_meta_menu(self):
    """„Ajánlott szűrők” menü: kategóriánként almenü; ✔ = a telepített pluginban megvan, ✘ = hiányzik, · = még nem ismert."""
    m = getattr(self, "_vs_metamenu", None)
    if m is None:
        return
    try:
        for w in m.winfo_children():
            w.destroy()
        m.delete(0, "end")
        meta = meta_all()
        sigs = getattr(self, "_vs_sigs", None)
        if not meta:
            m.add_command(label=T("(nincs vs_filters mappa a program mellett)", "(no vs_filters folder next to the program)"),
                          state="disabled")
            return
        groups = {}
        for key, f in meta.items():
            groups.setdefault(f["cat"], []).append(f)
        for cat in vs_code.CAT_KEYS:
            if cat not in groups:
                continue
            sm = self.tk.Menu(m, tearoff=0)
            for f in sorted(groups[cat], key=lambda x: L(x["label"]).lower()):
                present = None if sigs is None else (f["key"] in sigs)
                mark = "· " if present is None else ("✔ " if present else "✘ ")
                sm.add_command(label=mark + L(f["label"]), command=lambda k=f["key"]: _add_meta(self, k),
                               state="disabled" if present is False else "normal")
            m.add_cascade(label="%s (%d)" % (T(vs_code.cat_label(cat, True), vs_code.cat_label(cat, False)), len(groups[cat])), menu=sm)
        if _META_ERR:
            m.add_separator()
            m.add_command(label=T("⚠ %d hibás metaadat-bejegyzés: ", "⚠ %d faulty metadata entries: ") % len(_META_ERR)
                          + _META_ERR[0][:60], state="disabled")
    except Exception:               # noqa
        pass


def _add_meta(self, key):
    f = meta_all().get(key)
    if f is not None and self._seg() is not None:
        _add_code_items(self, [vs_meta.card_from_meta(f, _sig_names(self, key))])


def _add_pyfunc(self, full):
    info = _py_info(self, full)
    if info is not None and self._seg() is not None:
        _add_code_items(self, [vs_code.card_from_func(full, info.get("params"))])


def _fill_py_menu(self):
    """„Python-függvények” menü: modulonként egy almenü."""
    m = getattr(self, "_vs_pymenu", None)
    if m is None:
        return
    try:
        m.delete(0, "end")
        funcs = getattr(self, "_vs_pyf", {})
        if not funcs:
            m.add_command(label=T("(nincs lista – ↻ Python-vizsgálat)", "(no list – ↻ Scan Python)"), state="disabled")
            return
        mods = {}
        for full in sorted(funcs, key=str.lower):
            mods.setdefault(full.rpartition(".")[0], []).append(full)
        for mod in sorted(mods, key=str.lower):
            sm = self.tk.Menu(m, tearoff=0)
            for i, full in enumerate(mods[mod]):
                sm.add_command(label=full.rpartition(".")[2], command=lambda f=full: _add_pyfunc(self, f),
                               columnbreak=1 if (i and i % 25 == 0) else 0)
            m.add_cascade(label="%s (%d)" % (mod, len(mods[mod])), menu=sm)
    except Exception:               # noqa
        pass


def _pyf_load(self, force=False):
    """A pluginmappa Python-moduljainak függvény-listája: gyorsítótárból, vagy (force) új vizsgálattal."""
    if not getattr(self, "_ok", True):
        return
    try:
        vsp, plug = _paths(self)
    except RuntimeError as exc:
        if force:
            self.v_vsstat.set(str(exc))
        return
    wd = lanc_dir()
    key = "%s|%s|%s|py1" % (vsp, plug, vs_pyscan.py_sig(plug))
    if not force:
        funcs = vs_pyscan.load_cache(wd, key)
        if funcs is not None:
            self._vs_pyf = funcs
            _fill_py_menu(self)
        return
    active = getattr(self, "_vs_py_cancel", None)
    if active is not None and not active.is_set():
        active.set()
        self.v_vsstat.set(T("Leállítás kérése… kattints újra egy új vizsgálathoz.",
                            "Stopping scan… click again to start a new one."))
        return
    cancel = threading.Event()
    self._vs_py_cancel = cancel
    self.v_vsstat.set(T("Python-modulok vizsgálata indul… a gombbal megszakítható.",
                        "Starting Python module scan… press the button to cancel."))

    def progress(done, total, mod):
        self._post(lambda a, b: self.v_vsstat.set(T("Python-vizsgálat: %d / %d – %s", "Python scan: %d / %d – %s")
                                                  % (done, total, mod)), None, None)

    def run():
        funcs, rows, total = vs_pyscan.scan(vsp, plug, wd, timeout=30, cancel=cancel, progress=progress)
        if not cancel.is_set():
            vs_pyscan.save_cache(wd, key, funcs)
        self._post(lambda a, b: _pyf_done(self, funcs, rows, total, cancel.is_set()), None, None)
    threading.Thread(target=run, daemon=True).start()


def _pyf_done(self, funcs, rows, total, cancelled):
    if not self._ok:
        return
    self._vs_pyf = funcs
    self._vs_py_cancel = None
    _fill_py_menu(self)
    bad = [r for r in rows if not r["ok"]]
    lead = T("Megszakítva – részleges eredmény. ", "Cancelled – partial results. ") if cancelled else ""
    txt = lead + T("✔ Python-függvények: %d függvény, %d/%d modul olvasható.",
                   "✔ Python functions: %d functions, %d/%d modules readable.") % (len(funcs), len(rows) - len(bad), total)
    if bad:
        txt += T(" Nem importálható: ", " Not importable: ") + "; ".join("%s (%s)" % (r["module"], r["message"][:60])
                                                                        for r in bad[:3]) + ("…" if len(bad) > 3 else "")
    self.v_vsstat.set(txt)
    _refresh_list_ui(self)          # a kártyákon megjelenik a „Paraméter ▾” gomb és a leírás


def _presets(self):
    d = self.p.cfg.get("vs_code_presets")
    if not isinstance(d, dict):
        d = {}
        self.p.cfg["vs_code_presets"] = d
    return d


def _fill_preset_menu(self):
    m = getattr(self, "_vs_presetmenu", None)
    if m is None:
        return
    try:
        m.delete(0, "end")
        names = sorted(_presets(self))
        if not names:
            m.add_command(label=T("(nincs mentett előbeállítás – a kártyán: Mentés előbeállításként…)",
                                  "(no saved presets – on a card: Save as preset…)"), state="disabled")
            return
        for n in names:
            m.add_command(label=n, command=lambda n=n: _add_preset(self, n))
        dm = self.tk.Menu(m, tearoff=0)
        for n in names:
            dm.add_command(label=n, command=lambda n=n: _del_preset(self, n))
        m.add_separator()
        m.add_cascade(label=T("Törlés", "Delete"), menu=dm)
    except Exception:               # noqa
        pass


def _add_preset(self, name):
    data = _presets(self).get(name)
    if isinstance(data, dict) and self._seg() is not None:
        _add_code_items(self, [data])


def _del_preset(self, name):
    _presets(self).pop(name, None)
    self._save_cfg()
    _fill_preset_menu(self)


def _save_preset(self, uid):
    it = _find_item(self, uid)
    if it is None:
        return
    from tkinter import simpledialog
    name = (simpledialog.askstring(T("Előbeállítás mentése", "Save preset"), T("Az előbeállítás neve:", "Preset name:"),
                                   initialvalue=vs_code.label_of(it), parent=self.top) or "").strip()
    if not name:
        return
    _presets(self)[name] = copy.deepcopy(vs_code.preset_of(it))
    self._save_cfg()
    _fill_preset_menu(self)


def _patch_item(self, uid, fn, delay=250):
    """Egy lista-elem módosítása (minden érintett szakaszon), a lista újrarajzolása nélkül (megmarad a fókusz)."""
    if self._loading or not self._ok:
        return
    sg = self._seg()
    if sg is None:
        return
    for o in (self.segs if self.v_all.get() else [sg]):
        L = [dict(it) for it in (o["state"].get("vs_chain") or [])]
        for it in L:
            if it.get("uid") == uid:
                fn(it)
        o["state"]["vs_chain"] = L
    self._update_chain()
    self._schedule(delay)


def _set_val(self, uid, name, text):
    def fn(it):
        v = dict(it.get("vals") or {})
        v[name] = text
        it["vals"] = v
    _patch_item(self, uid, fn, delay=900)     # gépelés közben ne induljon nehéz számítás minden számjegyre


def _reset_vals(self, uid):
    def fn(it):
        it["vals"] = {}
    _chain_edit(self, lambda L: [(_dict_with(it, fn) if it.get("uid") == uid else it) for it in L])


def _dict_with(it, fn):
    fn(it)
    return it


def _move(self, uid, d):
    """Egy elem léptetése a kategóriáján BELÜL (a kategóriák sorrendje rögzített)."""
    def fn(L):
        i = next((k for k, x in enumerate(L) if x.get("uid") == uid), None)
        if i is None:
            return L
        j = i + d
        if 0 <= j < len(L) and item_cat(L[j]) == item_cat(L[i]):
            L[i], L[j] = L[j], L[i]
        return L
    _chain_edit(self, fn)


def _remove(self, uid):
    _chain_edit(self, lambda L: [x for x in L if x.get("uid") != uid])


def _set_cat(self, uid, cat):
    """Az elem áthelyezése másik kategóriába (a kategória végére kerül)."""
    _chain_edit(self, lambda L: [dict(x, cat=cat) if x.get("uid") == uid else x for x in L])


def _cat_menu(self, uid, btn):
    it = _find_item(self, uid)
    if it is None:
        return
    cur = item_cat(it)
    m = self.tk.Menu(btn, tearoff=0)
    for k, hu, en in vs_code.CATS:
        m.add_command(label=("✔ " if k == cur else "    ") + T(hu, en), command=lambda k=k: _set_cat(self, uid, k))
    try:
        m.tk_popup(btn.winfo_rootx(), btn.winfo_rooty() + btn.winfo_height())
    finally:
        m.grab_release()


def _template_rows(self, fr, it):
    """A nyers, nem dokumentált paramétereket alapból összecsukja; az üres opcionális érték plugin-defaultot jelent."""
    ttk = self.ttk
    vals = item_defaults(it)
    ps = parse_sig(it.get("sig") or "")
    params = ps[1:]
    if not params:
        return
    required = [p[0] for p in params if not p[2]]
    if required:
        hint = T("Kötelező paraméter(ek): %s. A többi mező haladó beállítás.",
                 "Required parameter(s): %s. Other fields are advanced settings.") % ", ".join(required)
    else:
        hint = T("A plugin saját alapértékei használatban maradnak. Nem kell ezeket a mezőket kitöltened.",
                 "The plugin's own defaults remain active. You do not need to fill these fields.")
    ttk.Label(fr, text=hint, foreground="#555", wraplength=350, justify="left").pack(anchor="w", pady=(0, 2))
    box = ttk.LabelFrame(fr, text=T("Haladó paraméterek — üresen hagyva: plugin-alapérték", 
                                    "Advanced parameters — blank means plugin default"), padding=3)
    visible = [False]
    button = ttk.Button(fr, text=T("Paraméterek megjelenítése (%d)", "Show parameters (%d)") % len(params),
                        takefocus=False)
    button.pack(anchor="w", pady=(0, 3))
    def toggle():
        if visible[0]:
            box.pack_forget()
            visible[0] = False
            button.configure(text=T("Paraméterek megjelenítése (%d)", "Show parameters (%d)") % len(params))
        else:
            box.pack(fill="x", pady=(0, 4))
            visible[0] = True
            button.configure(text=T("Paraméterek elrejtése", "Hide parameters"))
    button.configure(command=toggle)
    for name, typ, opt in params:
        r = ttk.Frame(box)
        r.pack(fill="x", pady=1)
        ttk.Label(r, text=name + ("" if opt else " *"), width=16, anchor="w").pack(side="left")
        ttk.Label(r, text=typ, width=9, foreground="#555").pack(side="left")
        var = self.tk.StringVar(master=self.top, value=str(vals.get(name, "") or ""))
        ttk.Entry(r, textvariable=var, width=18).pack(side="left", fill="x", expand=True)
        var.trace_add("write", lambda *a, u=it["uid"], n=name, v=var: _set_val(self, u, n, v.get()))
    ttk.Label(box, text=T("Tömb: vesszővel elválasztva (pl. 0,1); szövegtömb: pontosvesszővel. "
                          "A * kötelező paramétert jelent. A paraméterek részletes súgója metaadat felvétele után jelenik meg.",
                          "Arrays: comma-separated (e.g. 0,1); string arrays: semicolon-separated. "
                          "* means required. Detailed help appears when metadata is added."),
              foreground="#555", wraplength=350, justify="left").pack(anchor="w")
    ttk.Button(box, text=T("Sablon alaphelyzet", "Reset template"), takefocus=False,
               command=lambda u=it["uid"]: _reset_vals(self, u)).pack(anchor="e", pady=2)
    if required:
        box.pack(fill="x", pady=(0, 4))
        visible[0] = True
        button.configure(text=T("Paraméterek elrejtése", "Hide parameters"))


def _refresh_list_ui(self):
    fr = getattr(self, "vs_lframe", None)
    if fr is None:
        return
    sg = self._seg()
    st = sg["state"] if sg else {}
    self.v_vsmode.set(vs_mode(st))
    for w in fr.winfo_children():
        w.destroy()
    ttk = self.ttk
    items = chain_items(st)
    if not items:
        ttk.Label(fr, text=T("(üres – adj hozzá szűrőt a listából)",
                             "(empty – add a filter from the list)"), foreground="#555").pack(anchor="w")
    nsok = getattr(self, "_vs_nsok", {})
    prev_cat = None
    for i, it in enumerate(items):
        ns = item_ns(it)
        enabled = bool(it.get("enabled", True))
        cat = item_cat(it)
        if cat != prev_cat:                 # kategória-fejléc (fix sorrend: Vágás → Zaj → Mező → Vonal → ... → Képkockaszám)
            hdr = ttk.Frame(fr)
            hdr.pack(fill="x", pady=(6 if prev_cat else 0, 1))
            ttk.Label(hdr, text=T(vs_code.cat_label(cat, True), vs_code.cat_label(cat, False)),
                      foreground="#164d86").pack(side="left")
            ttk.Separator(hdr, orient="horizontal").pack(side="left", fill="x", expand=True, padx=(6, 0))
            prev_cat = cat
        ok = True if ns == "std" else nsok.get(ns)
        mark = "–" if not enabled else ("·" if ns is None else ("✔" if ok is True else ("✘" if ok is False else "…")))
        row = ttk.Frame(fr)
        row.pack(fill="x", pady=1)
        ev = self.tk.BooleanVar(master=self.top, value=enabled)
        ttk.Checkbutton(row, variable=ev, takefocus=False,
                        command=lambda u=it["uid"], v=ev: _toggle(self, u, bool(v.get()))).pack(side="left")
        ttk.Label(row, text="%s  %s" % (mark, item_label(it)),
                  foreground="" if enabled else "#999999").pack(side="left")
        uid_ = it["uid"]
        b_x = ttk.Button(row, text="✖", width=3, takefocus=False, command=lambda u=uid_: _remove(self, u))
        b_dn = ttk.Button(row, text="↓", width=3, takefocus=False, command=lambda u=uid_: _move(self, u, 1))
        b_up = ttk.Button(row, text="↑", width=3, takefocus=False, command=lambda u=uid_: _move(self, u, -1))
        b_cat = ttk.Button(row, text="⇅", width=3, takefocus=False)
        b_cat.configure(command=lambda u=uid_, b=b_cat: _cat_menu(self, u, b))
        for b in (b_x, b_dn, b_up, b_cat):
            b.pack(side="right", padx=1)
        if i == 0 or item_cat(items[i - 1]) != cat:          # a kategória első elemét nem lehet feljebb léptetni
            b_up.state(["disabled"])
        if i == len(items) - 1 or item_cat(items[i + 1]) != cat:
            b_dn.state(["disabled"])
        if it["id"] == "code":
            if enabled:                     # a kikapcsolt kártya összecsukva, szürkén marad (mint a StaxRip-ben)
                _code_body(self, fr, it)
        elif it["id"] == "auto":
            _template_rows(self, fr, it)
            call, warn = auto_call(it)
            if warn:
                ttk.Label(fr, text="   ⚠ " + warn + T(" – kihagyva", " – skipped"), foreground="#b00020",
                          wraplength=360, justify="left").pack(anchor="w", pady=(0, 3))
    act = [it for it in items if it.get("enabled", True)]
    if act and vs_mode(st) == "list":
        lines = []
        for it in act:
            label = item_label(it)
            if it["id"] == "code":
                lines.append(label)
                continue
            vals = item_defaults(it)
            supplied = ["%s=%s" % (k, v) for k, v in vals.items() if str(v).strip()]
            if supplied:
                label += " (" + "; ".join(supplied) + ")"
            else:
                label += T(" — plugin-alapérték", " — plugin defaults")
            lines.append(label)
        ttk.Label(fr, text=T("Aktív VapourSynth-lánc: ", "Active VapourSynth chain: ") + " → ".join(lines),
                  foreground="#164d86", wraplength=360, justify="left").pack(anchor="w", pady=(2, 0))
        ttk.Label(fr, text=T("Generált szkript: ", "Generated script: ") + effective_script(st),
                  foreground="#555", wraplength=360, justify="left").pack(anchor="w", pady=2)
    _rebuild(self)


def _nscheck(self):
    """Minden szűrő névterét ellenőrzi a plugin-mappa betöltése után (zöld pipa / piros X)."""
    sg = self._seg()
    items = active_items(sg["state"]) if sg else []
    nss = sorted(set(item_ns(i) for i in items) - {"std", None})
    self._vs_nsok = {}
    if not nss:
        return
    try:
        vsp, plug = _paths(self)
    except RuntimeError as e:
        if getattr(self, "v_vsstat", None) is not None:
            self.v_vsstat.set(str(e))
        return

    def run():
        res, err = check_namespaces(vsp, plug, nss)
        self._post(lambda a, b, r=(res, err, nss): _nsdone(self, r), None, None)
    threading.Thread(target=run, daemon=True).start()


def _nsdone(self, r):
    if not self._ok:
        return
    res, err, nss = r
    self._vs_nsok = {}
    for n in nss:
        self._vs_nsok[n] = None if res is None else bool(res.get(n, False))
    if err and getattr(self, "v_vsstat", None) is not None:
        self.v_vsstat.set(T("✘ Plugin-ellenőrzés: ", "✘ Plugin check: ") + str(err))
    _refresh_list_ui(self)


def _make_vpy(self):
    p = self.fd.asksaveasfilename(parent=self.top, defaultextension=".vpy", initialfile="szuro.vpy",
                                  filetypes=[("VapourSynth", "*.vpy")])
    if not p:
        return
    try:
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(vb.TEMPLATE)
    except OSError as e:
        self.mb.showwarning("FFmpeg", str(e), parent=self.top)
        return
    self.vars["vs_file"].set(os.path.normpath(p))


# ------------------------------------------------------------------ egyéb
def _caps_done(self, caps):
    if not self._ok:
        return
    self.caps = caps
    self._update_chain()


def _y4m_head(data):
    """Egy y4m-folyam fejlécéből: dict(w, h, fn, fd, sar) vagy None."""
    line = bytes(data[:512]).split(b"\n", 1)[0].decode("ascii", "replace")
    if not line.startswith("YUV4MPEG2"):
        return None
    d = {}
    for tok in line.split()[1:]:
        d[tok[:1]] = tok[1:]
    try:
        w, h = int(d["W"]), int(d["H"])
        fn, fd = (int(x) for x in d.get("F", "25:1").split(":"))
        an, ad = (int(x) for x in d.get("A", "1:1").split(":"))
    except (KeyError, ValueError):
        return None
    return dict(w=w, h=h, fn=fn, fd=fd or 1, sar=(an / float(ad)) if an > 0 and ad > 0 else 1.0)


def _fps_str(fn, fd):
    """Kocka/mp az Átalakítás fül „fps” mezőjébe: 25, 50, 30000/1001."""
    if not fn or not fd:
        return ""
    if fn % fd == 0:
        return str(fn // fd)
    return "%d/%d" % (fn, fd)


def _y4m_frame(ffmpeg, vf, vcmd=None, data=None, cancel=None, timeout=900):
    """EGY képkocka y4m-ben, a képet a vspipe (vcmd) vagy a megadott y4m-bájtok (data) adják, opcionális szűrőlánccal (vf).
    -> (bájtok, hibaszöveg)"""
    fcmd = [ffmpeg, "-v", "error", "-nostdin", "-f", "yuv4mpegpipe", "-i", "-"] + (["-vf", vf] if vf else []) + \
           ["-frames:v", "1", "-f", "yuv4mpegpipe", "-"]
    vp = fp = None
    verr = []
    try:
        if vcmd:
            vp = subprocess.Popen(vcmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                  creationflags=E._NOWIN)
            threading.Thread(target=lambda pr=vp: verr.extend(pr.stderr.read().decode("utf-8", "replace").splitlines()),
                             daemon=True).start()
            fp = subprocess.Popen(fcmd, stdin=vp.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=E._NOWIN)
            vp.stdout.close()
        else:
            fp = subprocess.Popen(fcmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  creationflags=E._NOWIN)
        box = {}

        def comm():
            try:
                box["r"] = fp.communicate(input=data, timeout=timeout)
            except Exception as e:      # noqa
                box["e"] = e
        t = threading.Thread(target=comm, daemon=True)
        t.start()
        while t.is_alive():
            t.join(0.3)
            if cancel is not None and cancel.is_set():
                break
        if cancel is not None and cancel.is_set():
            return b"", "cancelled"
        if "r" not in box:
            return b"", T("Időtúllépés a VapourSynth előkészítésénél.", "Timeout while preparing VapourSynth.")
        out, ferr = box["r"]
        time.sleep(0.05)
        lines = verr + (ferr or b"").decode("utf-8", "replace").strip().splitlines()
        return out or b"", _last_error(verr) or _last_error(lines[len(verr):]) or ""
    finally:
        for pr in (fp, vp):
            if pr is not None:
                try:
                    if pr.poll() is None:
                        pr.kill()
                    pr.wait()
                except Exception:       # noqa
                    pass


def _probe_job(self, j, cancel):
    """Egyetlen kocka lefuttatásával megméri a VapourSynth-szakasz KIMENETÉT (méret, SAR, fps), majd az ffmpeg-effektek
    UTÁNI végső méretet és kocka/mp-et. Ebből lesz az Átalakítás fül „méret” és „fps” mezője - köztes fájl nélkül."""
    ff = self.ff.ffmpeg
    sg = j["sg"]
    raw, err = _y4m_frame(ff, "", vcmd=j["vcmd"], cancel=cancel)
    if cancel.is_set():
        raise RuntimeError("cancelled")
    h1 = _y4m_head(raw)
    if not h1 or len(raw) < 100:
        raise RuntimeError("%s: %s" % (os.path.basename(sg["src"]), err or T("A VapourSynth nem adott képkockát.",
                                                                           "VapourSynth returned no frame.")))
    info = dict(w=h1["w"], h=h1["h"], sar=h1["sar"], fps=h1["fn"] / float(h1["fd"]))
    chain = E.build_chain(sg["state"], info, getattr(self, "caps", None))[0]     # a lánc a VS-KIMENET adataival számolódik
    w, h, fn, fd = h1["w"], h1["h"], h1["fn"], h1["fd"]
    if chain:
        raw2, err2 = _y4m_frame(ff, chain, data=raw, cancel=cancel)
        if cancel.is_set():
            raise RuntimeError("cancelled")
        h2 = _y4m_head(raw2)
        if h2:
            w, h, fn, fd = h2["w"], h2["h"], h2["fn"], h2["fd"]
        else:
            E._log("VS előkészítés: az effekt-lánc egy kockán nem adott képet (%s); a VS-kimenet adatai maradnak" % err2)
    fp = re.sub(r"[^0-9./]", "", str((sg["state"] or {}).get("fps_to") or ""))
    j["vf"] = chain
    j["conv"] = {"scale": "%d:%d" % (w - w % 2, h - h % 2), "fps": fp or _fps_str(fn, fd)}
    j["vs"] = {"vcmd": list(j["vcmd"]), "fps": _fps_str(h1["fn"], h1["fd"]), "w": h1["w"], "h": h1["h"]}
    E._log("VS előkészítés: %s -> VS-kimenet %dx%d %s fps, végső %dx%d %s fps, lánc=%r" % (
        os.path.basename(sg["src"]), h1["w"], h1["h"], _fps_str(h1["fn"], h1["fd"]), w, h, _fps_str(fn, fd), chain))


def output(self):
    """Kimenet az Átalakítás fülre. A VapourSynth-es szakaszok NEM renderelődnek köztes fájlba: a program csak a vspipe-parancsot
    adja át az Átalakítás fülnek, ahol a kódolás egyetlen menetben fut (vspipe → ffmpeg), a hang a forrásból jön.
    A beállított méret, fps és az effektek megmaradnak (az Átalakítás fül mezői ezekkel töltődnek fel; kodek, bitráta,
    konténer ott szabadon átírható)."""
    todo = [sg for sg in self.segs if vs_active(sg["state"])]
    if not todo:
        return _export_finish(self, [])
    try:
        vsp, plug = _paths(self)
    except RuntimeError as e:
        self.mb.showwarning("FFmpeg", str(e), parent=self.top)
        return None
    jobs = []
    for sg in todo:
        info = self._info_of(sg["src"]) or {}
        fps = float(info.get("fps") or 25.0)
        a, b = float(sg["a"]), float(sg["b"])
        script = effective_script(sg["state"])
        if not script:
            self.mb.showwarning("VapourSynth", T("Nincs bekapcsolt VapourSynth-szűrő / szkript.", "No VapourSynth filter / script is enabled."),
                                parent=self.top)
            return None
        params = dict(sg["state"].get("vs_params") or {})
        s0, e0 = vs_render.seg_frames(a, b, fps)
        args = vb.script_args(src=sg["src"], plugin_dir=plug or None, params=params)
        args["plugdir"] = plug or ""
        frames = None
        if vs_mode(sg["state"]) == "list":          # a generált szkript maga vágja le a szakaszt
            args["seg_start"], args["seg_end"] = s0, e0
        else:                                       # kézzel írt .vpy: a vspipe -s / -e kapcsolója vág
            frames = (s0, e0 - 1)
        # a vspipe-parancsot ugyanaz a (bevált) építő adja, mint a korábbi renderhez; az ffmpeg-részét (köztes fájl) eldobjuk
        vcmd, _unused = vs_render.build_cmds(vsp, self.ff.ffmpeg, script, args, sg["src"], a, b - a,
                                             os.path.join(lanc_dir(), "_nincs_koztes_fajl.mkv"), frames=frames)
        jobs.append(dict(sg=sg, vcmd=list(vcmd)))
    _prepare(self, jobs)
    return None


def _prepare(self, jobs):
    """Háttérszál + kis várakozó ablak: egy kocka lefuttatása szakaszonként (a VapourSynth kimenetének mérése)."""
    tk, ttk = self.tk, self.ttk
    cancel = threading.Event()
    st = dict(i=0, done=False, error=None, cancelled=False)

    def work():
        try:
            for k, j in enumerate(jobs):
                st["i"] = k
                if cancel.is_set():
                    st["cancelled"] = True
                    break
                _probe_job(self, j, cancel)
        except Exception as e:          # noqa
            if cancel.is_set() or str(e) == "cancelled":
                st["cancelled"] = True
            else:
                st["error"] = str(e)
                E._log("VS előkészítés hiba: %r" % e)
        finally:
            st["done"] = True

    win = tk.Toplevel(self.top)
    win.title(T("VapourSynth – előkészítés", "VapourSynth – preparing"))
    win.transient(self.top)
    win.resizable(False, False)
    try:
        win.geometry("+%d+%d" % (self.top.winfo_rootx() + 60, self.top.winfo_rooty() + 80))
    except Exception:                   # noqa
        pass
    lab = ttk.Label(win, text="", width=64, anchor="w")
    lab.pack(fill="x", padx=12, pady=(12, 4))
    pb = ttk.Progressbar(win, length=440, mode="indeterminate")
    pb.pack(padx=12)
    pb.start(20)
    ttk.Label(win, text=T("Nem készül köztes fájl: a kép a kódolásnál közvetlenül a vspipe-ból megy az ffmpeg-be.",
                          "No intermediate file: the picture goes straight from vspipe into ffmpeg when encoding."),
              foreground="#555", wraplength=440, justify="left").pack(fill="x", padx=12, pady=4)
    btn = ttk.Button(win, text=T("Mégse", "Cancel"))
    btn.pack(pady=(2, 10))

    def stop():
        cancel.set()
        try:
            btn.configure(text=T("Leállítás…", "Stopping…"), state="disabled")
        except Exception:               # noqa
            pass
    btn.configure(command=stop)
    win.protocol("WM_DELETE_WINDOW", stop)
    try:
        win.grab_set()
    except Exception:                   # noqa
        pass

    def tick():
        try:
            if not win.winfo_exists():
                return
            k = min(st["i"], len(jobs) - 1)
            lab.configure(text=T("VapourSynth-szakasz %d / %d: %s – kimenet mérése (1 kocka)…",
                                 "VapourSynth segment %d / %d: %s – measuring output (1 frame)…")
                          % (k + 1, len(jobs), os.path.basename(jobs[k]["sg"]["src"])))
            if st["done"]:
                try:
                    win.grab_release()
                except Exception:       # noqa
                    pass
                pb.stop()
                win.destroy()
                if st["cancelled"]:
                    self.v_vsstat.set(T("A kimenet megszakítva.", "Output cancelled."))
                elif st["error"]:
                    self.mb.showwarning("VapourSynth", T("A VapourSynth-szakasz nem indítható:\n", "The VapourSynth segment cannot start:\n")
                                        + str(st["error"]), parent=self.top)
                else:
                    _export_finish(self, jobs)
                return
            win.after(200, tick)
        except Exception as e:          # noqa
            E._log("VS előkészítő ablak hiba: %r" % e)
            try:                        # a várakozó ablak ne ragadjon be (grab) – lezárjuk és jelezzük
                cancel.set()
                win.grab_release()
                win.destroy()
                self.mb.showwarning("VapourSynth", T("Az előkészítés hibára futott: ", "Preparation failed: ") + str(e),
                                    parent=self.top)
            except Exception:           # noqa
                pass
    threading.Thread(target=work, daemon=True).start()
    win.after(200, tick)


def _conv_values(self, sg, it, path, ss, info, chain):
    """Az Átalakítás fül „méret” és „fps” mezőibe kerülő érték: a szűrőlánc UTÁNI képméret és kocka/mp.
    A méretet egy kocka tényleges lefuttatásával méri (így a vágás, forgatás, kimeneti méret mind benne van)."""
    out = {}
    size = vs_render.probe_output_size(self.ff.ffmpeg, path, ss, chain) if chain else None
    if size is None and info and info.get("w") and info.get("h") and not chain:
        size = (int(info["w"]), int(info["h"]))
    if size:
        out["scale"] = "%d:%d" % (size[0] - size[0] % 2, size[1] - size[1] % 2)
    fp = re.sub(r"[^0-9./]", "", str((sg["state"] or {}).get("fps_to") or ""))
    out["fps"] = vs_render.fps_text(fp or (info or {}).get("fps"))
    return {k: v for k, v in out.items() if v}


def _export_finish(self, jobs):
    """Az eredeti kimenet-lépés futtatása úgy, hogy
      * a VS-es szakaszok az ÁTALAKÍTÁS fülre az EREDETI forrással és vágásponttal kerülnek, mellé a vspipe-parancs (nincs köztes
        fájl: a kódoláskor a vspipe képe közvetlenül az ffmpeg-be megy),
      * az ffmpeg-effektek lánca a VapourSynth KIMENETÉNEK adataival számolódik újra,
      * az Átalakítás fül „méret” és „fps” mezői az effektek utáni értékeket kapják (kézzel átírhatók, azok a mérvadók),
      * az eredeti szakasz és beállítás megmarad az újranyitáshoz (Szerkesztő / Átalakítás „Képeffektek…”)."""
    byseg = {id(j["sg"]): j for j in jobs if j.get("vs")}
    panel = self.p
    real = panel.fx_apply

    def patched(items):
        conv_done = False
        for sg, it in zip(self.segs, items):
            j = byseg.get(id(sg))
            info = self._info_of(sg["src"]) or {}
            if j is not None:
                it["vf"] = j["vf"]
                it["vs"] = dict(j["vs"])
                it.pop("orig", None)                    # nincs köztes fájl: az eredeti szakasz marad a listában
                if not conv_done:
                    it["conv"] = dict(j["conv"])        # a mezők az egész listára közösek: az első effektes szakasz értéke kerül be
                    conv_done = True
            elif not conv_done and it.get("vf"):
                try:
                    it["conv"] = _conv_values(self, sg, it, sg["src"], float(sg["a"]), info, it.get("vf") or "")
                except Exception as e:      # noqa
                    E._log("méret / fps meghatározása: %r" % e)
                conv_done = True
        return real(items)
    panel.fx_apply = patched
    try:
        return _ORIG["output"](self)
    finally:
        try:
            del panel.fx_apply
        except AttributeError:
            pass


NEW = {
    "_tab_vs": _tab_vs, "_frame_work": _frame_work, "_frame_done": _frame_done,
    "_start_play": _start_play, "_request": _request, "_vcmd": _vcmd,
    "_play_thread": _play_thread, "_caps_done": _caps_done, "output": output, "_load": _load,
    "_collect": _collect, "_make_vpy": _make_vpy, "_reset": _reset,
}


def install(mod):
    """Az efekt.py modulját kapja (sys.modules[__name__]). Egyszer hívható; többször nem csinál semmit."""
    global E
    cls = mod.EffectWindow
    if getattr(cls, "_vs_installed", False):
        return True
    E = mod
    for n in _NAMES:
        _ORIG[n] = getattr(cls, n)
    for n, fn in NEW.items():
        setattr(cls, n, fn)
    cls._vs_installed = True
    # a szűrőlánc-építő a régi (FFmpeg „vapoursynth” szűrős) VS-ágat már nem használja
    orig_bc = mod.build_chain
    _ORIG["build_chain"] = orig_bc

    def build_chain_no_vs(state, info=None, caps=None, **kw):
        st = dict(state or {})
        st["vs_on"] = False
        return orig_bc(st, info, caps, **kw)
    mod.build_chain = build_chain_no_vs
    return True
