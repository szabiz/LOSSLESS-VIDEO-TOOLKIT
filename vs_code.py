# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 szabiz <szabiz@yahoo.com>
# Copyright (c) 2026 szabiz <szabiz@yahoo.com>
"""
vs_code.py - beillesztett VapourSynth-kódsorokból szűrő-kártya (efekt_vs.py "Szűrőlánc" lap)

Egy működő sor, pl.
    clip = G41Fun.mClean(clip, thSAD=400, chroma=True, sharp=10, strength=10)
kártyává alakul: a függvény neve, a pozicionális argumentumok (változatlanok) és a kulcsszavas
paraméterek (név + érték, ezekből lesznek a felületi elemek). A kártyából a program visszaadja a kódot.

Ami nem egyetlen "clip = fv(...)" hívás (def, ciklus, több utasítás), az "nyers" kártya: a kód változatlanul,
szerkeszthető szövegként marad meg.

Tiszta logika, nincs benne Tk - önállóan tesztelhető. A felhasználónak szóló üzenetek (magyar, angol)
párokként térnek vissza; a megjelenítés az efekt_vs.py dolga.

Kártya-szerkezet (JSON-barát, a szakasz állapotában tárolódik):
    {"id": "code", "uid": ..., "enabled": True, "title": "mClean",
     "target": "clip", "func": "G41Fun.mClean", "pos": ["clip"], "kw": [["thSAD", "400"], ...],
     "imports": ["import G41Fun"]}
    {"id": "code", ..., "title": "def interpolate", "raw": "def interpolate(clip):\\n    ...", "imports": []}
Az értékek Python-kifejezések SZÖVEGKÉNT (pl. "400", "True", "'Slower'").
"""
import ast
import re
import textwrap

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DOTTED = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*$")
_PCT = re.compile(r"%([A-Za-z_]\w*)%")
_PH = "__SXVAR_%s__"
_PH_MARK = "__SXVAR_"
_PH_BACK = re.compile(r"__SXVAR_([A-Za-z_]\w*?)__")


# ------------------------------------------------------------------ értékek
def kind_of(text):
    """Az érték szövegéből widget-fajta: bool / int / float / str / lit (lista, None ...) / expr (név, hívás ...)."""
    try:
        v = ast.literal_eval(str(text).strip())
    except Exception:           # noqa
        return "expr"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "str"
    return "lit"


def number_of(text):
    try:
        return float(ast.literal_eval(str(text).strip()))
    except Exception:           # noqa
        return 0.0


def str_of(text):
    try:
        v = ast.literal_eval(str(text).strip())
        return v if isinstance(v, str) else str(text)
    except Exception:           # noqa
        return str(text)


def fmt_number(kind, x):
    if kind == "int":
        return str(int(round(float(x))))
    return repr(round(float(x), 4))


def fmt_str(s):
    return repr(str(s))


def valid_expr(text):
    t = str(text).strip()
    if not t:
        return False
    try:
        ast.parse(t, mode="eval")
        return True
    except (SyntaxError, ValueError):
        return False


def guess_range(kind, text):
    """Csúszka-tartomány az érték alapján (a tartományt a plugin nem adja meg, ezért becslés; a számmező bármit elfogad)."""
    v = number_of(text)
    if v < 0:
        return 2 * v, -2 * v
    hi = max(2 * v, 1.0 if kind == "float" else 10.0)
    return 0.0, hi


def step_of(kind, text):
    v = abs(number_of(text))
    if kind == "int":
        return 1 if v < 100 else 10
    if v == 0:
        return 0.1
    s = 10 ** (len(str(int(v))) - 2) if v >= 10 else (0.1 if v >= 1 else 0.01)
    return max(0.001, s)


# ------------------------------------------------------------------ elemzés
def _card(node):
    """Egy 'név = ns.fv(...)' utasításból kártya, vagy None, ha nem ilyen alakú."""
    if not (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)):
        return None
    call = node.value
    func = ast.unparse(call.func)
    if not _DOTTED.match(func):
        return None
    if any(k.arg is None for k in call.keywords) or any(isinstance(a, ast.Starred) for a in call.args):
        return None
    return dict(id="code", target=node.targets[0].id, func=func,
                pos=[ast.unparse(a) for a in call.args],
                kw=[[k.arg, ast.unparse(k.value)] for k in call.keywords],
                title=func.split(".")[-1])


def _raw_title(code):
    for line in code.splitlines():
        s = line.strip()
        if s.startswith("def "):
            return s[4:].split("(")[0].strip() or "def"
    first = next((l.strip() for l in code.splitlines() if l.strip() and not l.strip().startswith("#")), "")
    return (first[:28] + "…") if len(first) > 28 else (first or "kód")


def parse_paste(text):
    """Beillesztett kód -> ([kártya, ...], [(magyar, angol) üzenet, ...]).
    A StaxRip %változó% jelölései (pl. %source_file%) miatt az ilyen utasítások kimaradnak."""
    notes = []
    text = textwrap.dedent(str(text or "")).strip("\n")
    if not text.strip():
        return [], []
    text = _PCT.sub(lambda m: _PH % m.group(1), text)
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return [], [("Szintaxishiba a(z) %s. sorban: %s" % (e.lineno, e.msg),
                     "Syntax error on line %s: %s" % (e.lineno, e.msg))]
    lines = text.splitlines()
    items, imports, buf = [], [], []

    def flush():
        if buf:
            code = "\n".join(buf)
            items.append(dict(id="code", raw=code, title=_raw_title(code)))
            del buf[:]

    for st in tree.body:
        start = min([st.lineno] + [d.lineno for d in getattr(st, "decorator_list", [])])
        seg = "\n".join(lines[start - 1:st.end_lineno])
        if isinstance(st, (ast.Import, ast.ImportFrom)):
            imports.append(seg)
            continue
        if _PH_MARK in seg:
            flush()
            first = _PH_BACK.sub(lambda m: "%" + m.group(1) + "%", seg.splitlines()[0])[:70]
            notes.append(("Kihagyva (StaxRip-változót tartalmaz, pl. %source_file% – a forrást a program maga tölti be): "
                          + first,
                          "Skipped (contains a StaxRip variable such as %source_file% – the source is loaded by the program): "
                          + first))
            continue
        c = _card(st)
        if c:
            flush()
            items.append(c)
        else:
            buf.append(seg)
    flush()
    for it in items:
        it["imports"] = list(imports)
    if not items and not notes:
        notes.append(("Nem találtam szűrő-hívást a beillesztett kódban.", "No filter call found in the pasted code."))
    return items, notes


# ------------------------------------------------------------------ kódgenerálás
def call_text(it):
    args = list(it.get("pos") or []) + ["%s=%s" % (k, v) for k, v in (it.get("kw") or [])]
    return "%s = %s(%s)" % (it["target"], it["func"], ", ".join(args))


def _imports(it):
    imps = list(it.get("imports") or [])
    if imps or "raw" in it:
        return imps
    parts = str(it["func"]).split(".")
    return [] if len(parts) < 2 or parts[0] in ("core", "vs", "std") else ["import " + parts[0]]


def body_lines(it):
    """A kártya kódja (importokkal) sorokként."""
    out = _imports(it)
    if "raw" in it:
        out += str(it["raw"]).splitlines()
    else:
        out.append(call_text(it))
    return out


def label_of(it):
    return str(it.get("title") or it.get("func") or "kód")


def script_block(it):
    """A kártya a generált .vpy-ban: try/except, hogy egy hibás szűrő ne döntse meg az egész láncot
    (a KIHAGYVA-sor a meglévő jelző-mechanizmuson át a felületre kerül)."""
    out = ["try:"] + ["    " + l for l in body_lines(it)]
    out += ["except Exception as _e:",
            "    sys.stderr.write(%r + str(_e).replace(chr(10), ' ')[:200] + chr(10))" % ("KIHAGYVA: %s - " % label_of(it))]
    return out


def code_text(it):
    return "\n".join(body_lines(it))


def is_valid(it):
    if it.get("id") != "code":
        return False
    if "raw" in it:
        return bool(str(it["raw"]).strip())
    try:
        return bool(_IDENT.match(str(it.get("target", ""))) and _DOTTED.match(str(it.get("func", "")))
                    and all(_IDENT.match(str(k[0])) for k in (it.get("kw") or [])))
    except (TypeError, IndexError):
        return False


def ns_of(it):
    """core.<névtér>.fv hívásnál a névtér (a plugin-ellenőrzéshez), különben None."""
    if "raw" in it:
        return None
    parts = str(it.get("func", "")).split(".")
    return parts[1] if len(parts) == 3 and parts[0] == "core" else None


def needs_all_plugins(it):
    """Python-függvény (havsfunc stb.) vagy nyers kód: sok plugint használhat, ezért mindet be kell tölteni."""
    return "raw" in it or ns_of(it) is None


# ------------------------------------------------------------------ előbeállítások
def preset_of(it):
    return {k: v for k, v in it.items() if k not in ("uid", "enabled")}


# ------------------------------------------------------------------ Python-függvény kártya a szignatúrából (vs_pyscan)
def card_from_func(full_name, params):
    """'havsfunc.QTGMC' + [[név, alapérték|None], ...] -> új kártya.
    Csak a kötelező (alapérték nélküli) paraméterek kerülnek rá azonnal ('None' értékkel, hogy a felületen
    kitölthetők legyenek); a többit a kártya „Paraméter ▾” menüjéből lehet hozzáadni az alapértékükkel."""
    mod, _, fname = str(full_name).rpartition(".")
    kw = [[n, "None"] for n, d in (params or []) if d is None]
    return dict(id="code", target="clip", func=full_name, pos=["clip"], kw=kw, title=fname,
                imports=["import " + mod.split(".")[0]] if mod else [])


def with_kw(it, name, value):
    """A kártya másolata a paraméterrel (hozzáadva vagy felülírva); az eredetit nem módosítja."""
    kw = [list(p) for p in (it.get("kw") or [])]
    for p in kw:
        if p[0] == name:
            p[1] = value
            break
    else:
        kw.append([name, value])
    return dict(it, kw=kw)


def without_kw(it, name):
    return dict(it, kw=[list(p) for p in (it.get("kw") or []) if p[0] != name])


def missing_params(it, params):
    """A szignatúra azon paraméterei, amelyek még nincsenek a kártyán: [[név, alapérték|None], ...]."""
    have = {p[0] for p in (it.get("kw") or [])}
    return [[n, d] for n, d in (params or []) if n not in have]


# ------------------------------------------------------------------ kategóriák (fix sorrend, mint a StaxRip-ben)
# A szűrőlánc mindig ebben a sorrendben fut: a kategóriák között a sorrend rögzített, a kategórián belül a lista szerinti.
# (A forrás betöltését és a kezdeti vágást a program maga végzi, ezért ezek nem külön kategóriák.)
CATS = [
    ("crop",      "Vágás",       "Crop"),
    ("noise",     "Zaj",         "Noise"),
    ("field",     "Mező (deinterlace)", "Field (deinterlace)"),
    ("line",      "Vonal / élesítés", "Line / sharpen"),
    ("color",     "Szín",        "Color"),
    ("resize",    "Átméretezés", "Resize"),
    ("framerate", "Képkockaszám", "Frame rate"),
    ("other",     "Egyéb",       "Other"),
]
CAT_KEYS = [c[0] for c in CATS]

# Név-részletek (kisbetűs) -> kategória. A sorrend számít: az első találat dönt (pl. a SmoothFps a framerate,
# nem a noise; az nnedi3_rpow2 a resize, nem a field).
_CAT_HINTS = [
    ("framerate", ("smoothfps", "svp", "interpolat", "framerate", "changefps", "assumefps", "convertfps", "mflow",
                   "mvflow", "fps", "frc")),
    ("resize",    ("resize", "spline", "lanczos", "bicubic", "bilinear", "rpow2", "upscale", "fsrcnn", "superres",
                   "nnedi3_resize", "scale")),
    ("crop",      ("crop", "addborders", "borders")),
    ("field",     ("qtgmc", "nnedi3", "bwdif", "yadif", "tdeint", "deinterlac", "ivtc", "tfm", "tdecimate", "vivtc",
                   "separatefields", "selecteven", "selectodd", "weave", "eedi")),
    ("line",      ("sharp", "cas", "lsfmod", "warp", "santiag", "antialias", "daa", "maa", "taa", "edge", "dehalo",
                   "contrasharp", "canny", "unsharp")),
    ("color",     ("levels", "tweak", "curve", "gamma", "tonemap", "hdr", "colorspace", "matrix", "bright", "contrast",
                   "saturation", "hue", "rgb", "lut")),
    ("noise",     ("clean", "degrain", "bm3d", "dfttest", "knlm", "nlmeans", "fft3d", "removegrain", "denoise",
                   "tempsmooth", "tnlm", "deblock", "deband", "f3kdb", "grain", "blur", "median", "smooth")),
]


def guess_cat(*names):
    """A függvény(ek) nevéből kategória-kulcs (nem ismert -> 'other')."""
    low = " ".join(str(n or "") for n in names).lower()
    for cat, hints in _CAT_HINTS:
        if any(h in low for h in hints):
            return cat
    return "other"


def cat_rank(cat):
    try:
        return CAT_KEYS.index(cat)
    except ValueError:
        return len(CAT_KEYS) - 1


def cat_label(cat, hu=True):
    for k, h, e in CATS:
        if k == cat:
            return h if hu else e
    return cat
