#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 szabiz <szabiz@yahoo.com>
# Copyright (c) 2026 szabiz <szabiz@yahoo.com>
"""
Lossless Video Toolkit - KÉPEFFEKTEK ablak (efekt.py)
=====================================================
Az lvt_ffmpeg.py Szerkesztőjéből nyílik ("→ Kijelöltek a Képeffektekre"), külön ablakban, élő előnézettel.

Működés:
  * A Szerkesztőben kijelölt szakaszok bekerülnek a bal alsó listába; szakaszonként külön effekt-beállítás
    adható (vagy a "Módosítás az összes szakaszra" pipával mindegyikre egyszerre).
  * Az előnézet az FFmpeg-gel készül (Eredeti / Effekttel / Osztott kép), így PONTOSAN azt látod, amit a
    konvertálás is csinálni fog. A "Play" gomb a kiválasztott módban (Eredeti / Effekttel / Osztott)
    a beépített előnézeti képben játssza le a mozgóképet; dupla kattintás a képre: teljes képernyő (Esc / dupla kattintás: vissza).
  * A "Kimenet → Átalakítás fül" gomb a szakaszokat a kész szűrőlánccal (-vf) együtt az Átalakítás fül
    listájára viszi; ott a szokott módon indítható a konvertálás (újrakódolós kodekkel).
  * Csak az FFmpeg saját szűrőit használja (a felhasználó saját FFmpeg-jét), a hiányzó szűrőkről figyelmeztet.
    A VapourSynth a "vapoursynth" szűrőn át használható, ha az FFmpeg-build tartalmazza.

A modul az lvt_ffmpeg.py mellett lévő, OPCIONÁLIS fájl: nélküle az lvt_ffmpeg.py a régi módon működik.
"""
import math
import os
import re
import subprocess
import queue
import threading
import time

try:                                    # a Pillow (pip install pillow) sokkal gyorsabb kirajzolást ad -> folyamatos lejátszás
    from PIL import Image as _PILImage, ImageTk as _PILImageTk
except Exception:                       # noqa
    _PILImage = _PILImageTk = None
HAVE_PIL = _PILImage is not None

EFEKT_VERSION = "1.6"
_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "efekt_naplo.txt")


def _log(msg):
    """Napló az efekt.py mellé (efekt_naplo.txt). Hibakereséshez; ~1 MB fölött újrakezdődik."""
    try:
        if os.path.exists(_LOG_PATH) and os.path.getsize(_LOG_PATH) > 1000000:
            os.remove(_LOG_PATH)
        with open(_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))
    except OSError:
        pass
LANG = "en"
_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _(hu, en):
    return hu if LANG == "hu" else en


def fmt_time(t):
    t = max(0.0, float(t))
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return "%d:%02d:%06.3f" % (h, m, s)


# ======================================================================== beállítások (alapértékek, választék)

DEFAULTS = dict(
    # --- deinterlace / képkocka-sebesség ---
    deint="none", deint_parity="auto", deint_only=False, fps_to="", fps_method="fps",
    # --- geometria ---
    angle=0.0, angle_zoom=True, rotate="none",
    crop_l=0, crop_r=0, crop_t=0, crop_b=0, crop_aspect="none",
    square=False, scale_w="", scale_h="", scale_algo="bicubic", dar="",
    out_mode="none", out_w="", out_h="",
    # --- fény / szín ---
    tonemap=False, normalize=False, norm_smooth=0,
    black=0.0, white=1.0,
    brightness=0.0, contrast=1.0, saturation=1.0, gamma=1.0,
    shadows=0, midtones=0, highlights=0,
    temperature=0, tint=0, hue=0, vibrance=0.0,
    colorfx="none", vig=0, vig_mode="forward", lut="",
    # --- élesség / zaj ---
    sharp="none", sharp_amt=1.0, sharp_size=5,
    denoise="none", denoise_amt=3.0, blur=0.0, grain=0,
    deband=False, deband_thr=0.03, deblock="none", deshake=False, deshake_rx=16,
    # --- VapourSynth, egyéni ---
    vs_on=False, vs_file="", custom="",
)

# név -> [(kulcs, magyar, angol), ...]   (az állapot a KULCSOT tárolja, így nyelvtől független)
CHOICES = dict(
    deint=[("none", "Nincs", "None"),
           ("yadif", "yadif (kocka)", "yadif (frame)"),
           ("yadif2x", "yadif (mező → dupla fps)", "yadif (field → double fps)"),
           ("bwdif", "bwdif (kocka, jobb minőség)", "bwdif (frame, better quality)"),
           ("bwdif2x", "bwdif (mező → dupla fps)", "bwdif (field → double fps)"),
           ("w3fdif", "w3fdif", "w3fdif"),
           ("estdif", "estdif (élvezérelt)", "estdif (edge directed)"),
           ("ivtc", "Inverz telecine (film → 23.976)", "Inverse telecine (film → 23.976)")],
    deint_parity=[("auto", "Automatikus", "Auto"), ("tff", "Felső mező elöl (TFF)", "Top field first (TFF)"),
                  ("bff", "Alsó mező elöl (BFF)", "Bottom field first (BFF)")],
    fps_method=[("fps", "Eldobás / ismétlés (fps)", "Drop / duplicate (fps)"),
                ("blend", "Keverés (framerate)", "Blend (framerate)"),
                ("mci", "Mozgáskövetés (minterpolate – lassú)", "Motion interpolation (minterpolate – slow)")],
    rotate=[("none", "Nincs", "None"), ("cw", "90° jobbra", "90° clockwise"), ("ccw", "90° balra", "90° counter-clockwise"),
            ("180", "180°", "180°"), ("hflip", "Vízszintes tükrözés", "Flip horizontal"),
            ("vflip", "Függőleges tükrözés", "Flip vertical")],
    crop_aspect=[("none", "Nincs", "None"), ("16:9", "16:9", "16:9"), ("4:3", "4:3", "4:3"), ("1:1", "1:1 (négyzet)", "1:1 (square)"),
                 ("9:16", "9:16 (álló)", "9:16 (portrait)"), ("21:9", "21:9", "21:9"), ("2.35:1", "2.35:1", "2.35:1")],
    scale_algo=[(k, k, k) for k in ("bicubic", "lanczos", "bilinear", "spline", "neighbor", "area")],
    out_mode=[("none", "Nincs", "None"),
              ("pad", "Illesztés fekete kerettel", "Fit with black bars"),
              ("fill", "Kitöltés (levágással)", "Fill (crop)"),
              ("stretch", "Nyújtás", "Stretch")],
    colorfx=[("none", "Nincs", "None"), ("bw", "Fekete-fehér", "Black & white"), ("sepia", "Szépia", "Sepia"),
             ("negate", "Negatív", "Negative")],
    vig_mode=[("forward", "Hozzáadás", "Add"), ("backward", "Eltávolítás", "Remove")],
    sharp=[("none", "Nincs", "None"), ("unsharp", "unsharp (klasszikus)", "unsharp (classic)"),
           ("cas", "CAS (kontraszt-adaptív)", "CAS (contrast adaptive)")],
    denoise=[("none", "Nincs", "None"), ("hqdn3d", "hqdn3d (gyors)", "hqdn3d (fast)"),
             ("nlmeans", "nlmeans (lassú, jó)", "nlmeans (slow, good)"), ("atadenoise", "atadenoise (időbeli)", "atadenoise (temporal)")],
    deblock=[("none", "Nincs", "None"), ("weak", "Gyenge", "Weak"), ("strong", "Erős", "Strong")],
)

SIZE_PRESETS = [("—", "", ""), ("2160p", "-2", "2160"), ("1440p", "-2", "1440"), ("1080p", "-2", "1080"),
                ("720p", "-2", "720"), ("576p", "-2", "576"), ("480p", "-2", "480"), ("360p", "-2", "360"),
                ("50 %", "trunc(iw/4)*2", "trunc(ih/4)*2"), ("1920x1080", "1920", "1080"), ("1280x720", "1280", "720")]
FPS_VALUES = ["", "23.976", "24", "25", "29.97", "30", "50", "59.94", "60"]

# Hungarian names are the stable IDs; the labels shown in the UI follow the language.
LOOK_EN = {
    "Sötét jelenet kivilágosítása": "Brighten a dark scene",
    "Élénk, napos": "Vivid, sunny",
    "Meleg, filmes": "Warm, cinematic",
    "Hideg, kékes": "Cold, bluish",
    "Fekete-fehér, kontrasztos": "Black and white, high contrast",
    "Régi felvétel tisztítása": "Clean up old footage",
    "HDR → SDR": "HDR → SDR",
    "Összefésült → progresszív": "Interlaced → progressive",
}
_LOOK_REV = {en: hu for hu, en in LOOK_EN.items()}


def look_label(key):
    return _(key, LOOK_EN.get(key, key))


def look_key(label):
    return _LOOK_REV.get(label, label)


# kész "hangulatok": a teljes állapotot felülírják (az alapértékekből indulnak)
LOOKS = {
    "Sötét jelenet kivilágosítása": dict(shadows=45, brightness=0.03, contrast=1.06, denoise="hqdn3d", denoise_amt=3.0),
    "Élénk, napos": dict(saturation=1.25, contrast=1.08, vibrance=0.4, sharp="unsharp", sharp_amt=0.8),
    "Meleg, filmes": dict(temperature=30, contrast=1.1, saturation=0.95, shadows=-10, vig=25, grain=8),
    "Hideg, kékes": dict(temperature=-35, saturation=0.9, contrast=1.05),
    "Fekete-fehér, kontrasztos": dict(colorfx="bw", contrast=1.25, vig=20),
    "Régi felvétel tisztítása": dict(deint="bwdif", denoise="hqdn3d", denoise_amt=4.0, deband=True, sharp="cas", sharp_amt=1.2),
    "HDR → SDR": dict(tonemap=True),
    "Összefésült → progresszív": dict(deint="bwdif", deint_only=True),
}


def label_of(name, key):
    for k, hu, en in CHOICES[name]:
        if k == key:
            return _(hu, en)
    return _(CHOICES[name][0][1], CHOICES[name][0][2])


def key_of(name, label):
    for k, hu, en in CHOICES[name]:
        if label in (hu, en):
            return k
    return DEFAULTS[name]


# ======================================================================== szűrőlánc-építés (tiszta logika)

_SAFE = re.compile(r"[^0-9A-Za-z_+\-*/(). ]")


def _san(x):
    """Méret-kifejezés megtisztítása (csak szám, műveleti jelek, iw/ih, zárójel)."""
    return _SAFE.sub("", str(x if x is not None else "")).replace(" ", "")


def _f(x, d=0.0):
    try:
        return float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return d


def _i(x, d=0):
    return int(round(_f(x, d)))


def ffq(path):
    """Fájlnév beágyazása szűrő-opcióba (Windows-útvonalhoz is): 'C\\:/mappa/fájl.cube'."""
    p = str(path).replace("\\", "/").replace(":", "\\:").replace("'", "'\\\\\\''")
    return "'%s'" % p


def build_chain(state, info=None, caps=None):
    """-> (szűrőlánc-szöveg, [használt szűrők], [az FFmpeg-ből hiányzó szűrők]).
    info: a forrás adatai (lvt_ffmpeg quick_info: w, h, sar, fps ...) vagy None; caps: az elérhető szűrők halmaza vagy None."""
    S = dict(DEFAULTS)
    S.update({k: v for k, v in (state or {}).items() if k in DEFAULTS})
    f, used = [], []

    def add(flt, name=None):
        f.append(flt)
        used.append(name or re.split(r"[=,]", flt, 1)[0])

    sar = (info or {}).get("sar") if info else None
    src_w, src_h = ((info or {}).get("w"), (info or {}).get("h")) if info else (None, None)
    done = {"sq": False}

    def square():
        """Nem négyzetes képpont (pl. 1440x1080, SAR 4:3) átszámítása négyzetesre - csak egyszer, és csak ha kell."""
        if done["sq"]:
            return
        done["sq"] = True
        if sar is None or abs(sar - 1.0) > 0.002:
            add("scale=trunc(iw*sar/2)*2:ih", "scale")
            add("setsar=1")

    # 0) VapourSynth - a nyers képen dolgozik elsőként (pl. QTGMC, zajszűrés)
    if S["vs_on"] and str(S["vs_file"]).strip():
        add("vapoursynth=file=%s" % ffq(str(S["vs_file"]).strip()), "vapoursynth")

    # 1) deinterlace / inverz telecine
    d = S["deint"]
    par = {"auto": -1, "tff": 0, "bff": 1}.get(S["deint_parity"], -1)
    parn = S["deint_parity"] if S["deint_parity"] in ("tff", "bff") else "auto"
    only = 1 if S["deint_only"] else 0
    if d in ("yadif", "yadif2x"):
        add("yadif=%d:%d:%d" % (1 if d == "yadif2x" else 0, par, only), "yadif")
    elif d in ("bwdif", "bwdif2x"):
        add("bwdif=%d:%d:%d" % (1 if d == "bwdif2x" else 0, par, only), "bwdif")
    elif d == "w3fdif":
        add("w3fdif=filter=complex:mode=frame:parity=%s:deint=%s" % (parn, "interlaced" if only else "all"), "w3fdif")
    elif d == "estdif":
        add("estdif=mode=frame:parity=%s:deint=%s" % (parn, "interlaced" if only else "all"), "estdif")
    elif d == "ivtc":
        add("fieldmatch=order=%s:combmatch=full" % parn, "fieldmatch")
        add("yadif=0:-1:1", "yadif")
        add("decimate")

    # 2) tisztítás (a geometria előtt, az eredeti képen)
    if S["deblock"] in ("weak", "strong"):
        add("deblock=filter=%s:block=8" % S["deblock"], "deblock")
    a = _f(S["denoise_amt"])
    if S["denoise"] == "hqdn3d" and a > 0:
        add("hqdn3d=%.2f:%.2f:%.2f:%.2f" % (a, a * 0.75, a * 1.5, a * 1.1), "hqdn3d")
    elif S["denoise"] == "nlmeans" and a > 0:
        add("nlmeans=s=%.1f" % max(1.0, a), "nlmeans")
    elif S["denoise"] == "atadenoise" and a > 0:
        add("atadenoise=s=%d" % max(5, 2 * int(round(a)) + 3), "atadenoise")
    if S["deband"]:
        t = max(0.0005, min(0.5, _f(S["deband_thr"], 0.03)))
        add("deband=1thr=%.4f:2thr=%.4f:3thr=%.4f:range=16:blur=1" % (t, t, t), "deband")
    if S["deshake"]:
        rx = max(0, min(64, _i(S["deshake_rx"], 16)))
        add("deshake=rx=%d:ry=%d:edge=mirror" % (rx, rx), "deshake")

    # 3) geometria
    ang = _f(S["angle"])
    if abs(ang) >= 0.05:
        square()
        expr = "%.4f*PI/180" % ang
        if S["angle_zoom"] and src_w and src_h:
            W = int(src_w * sar / 2) * 2 if (sar and abs(sar - 1.0) > 0.002) else int(src_w)
            H = int(src_h)
            th = math.radians(abs(ang))
            k = 1.0 / (math.cos(th) + math.sin(th) * max(W / H, H / W))
            cw, ch = max(16, int(W * k) // 2 * 2), max(16, int(H * k) // 2 * 2)
            add("rotate=a=%s:ow=%d:oh=%d:fillcolor=black" % (expr, cw, ch), "rotate")
            add("scale=%d:%d:flags=lanczos" % (W, H), "scale")
        else:
            add("rotate=a=%s:fillcolor=black" % expr, "rotate")
    r = S["rotate"]
    if r == "cw":
        add("transpose=1")
    elif r == "ccw":
        add("transpose=2")
    elif r == "180":
        add("hflip")
        add("vflip")
    elif r in ("hflip", "vflip"):
        add(r)
    L, R, T, B = (max(0, _i(S[k])) for k in ("crop_l", "crop_r", "crop_t", "crop_b"))
    if L or R or T or B:
        add("crop=w=trunc((iw-%d)/2)*2:h=trunc((ih-%d)/2)*2:x=%d:y=%d" % (L + R, T + B, L, T), "crop")
    if S["crop_aspect"] != "none":
        square()
        ca, cb = S["crop_aspect"].split(":")
        add("crop=w='trunc(min(iw,ih*%s/%s)/2)*2':h='trunc(min(ih,iw*%s/%s)/2)*2'" % (ca, cb, cb, ca), "crop")
    if S["square"]:
        square()
    sw, sh = _san(S["scale_w"]), _san(S["scale_h"])
    if sw or sh:
        add("scale=%s:%s:flags=%s" % (sw or "-2", sh or "-2", S["scale_algo"] if S["scale_algo"] in
                                      [k for k, _h, _e in CHOICES["scale_algo"]] else "bicubic"), "scale")
    if re.match(r"^\d+(\.\d+)?[:/]\d+(\.\d+)?$", str(S["dar"]).strip()):
        add("setdar=%s" % str(S["dar"]).strip().replace(":", "/"))
    ow, oh = _i(S["out_w"]), _i(S["out_h"])
    if S["out_mode"] != "none" and ow > 0 and oh > 0:
        square()
        if S["out_mode"] == "pad":
            add("scale=%d:%d:force_original_aspect_ratio=decrease" % (ow, oh), "scale")
            add("pad=%d:%d:(ow-iw)/2:(oh-ih)/2:black" % (ow, oh))
        elif S["out_mode"] == "fill":
            add("scale=%d:%d:force_original_aspect_ratio=increase" % (ow, oh), "scale")
            add("crop=%d:%d" % (ow, oh))
        else:
            add("scale=%d:%d" % (ow, oh), "scale")
        add("setsar=1")

    # 4) fény / szín
    if S["tonemap"]:
        for x in ("zscale=t=linear:npl=100", "format=gbrpf32le", "zscale=p=bt709", "tonemap=tonemap=hable:desat=0",
                  "zscale=t=bt709:m=bt709:r=tv", "format=yuv420p"):
            add(x)
    if S["normalize"]:
        add("normalize=smoothing=%d" % max(0, _i(S["norm_smooth"])), "normalize")
    b, w = _f(S["black"]), _f(S["white"], 1.0)
    if b > 0.001 or w < 0.999:
        add("colorlevels=rimin=%.3f:gimin=%.3f:bimin=%.3f:rimax=%.3f:gimax=%.3f:bimax=%.3f" % (b, b, b, w, w, w), "colorlevels")
    eq = []
    for key, dflt, nm in (("brightness", 0.0, "brightness"), ("contrast", 1.0, "contrast"),
                          ("saturation", 1.0, "saturation"), ("gamma", 1.0, "gamma")):
        v = _f(S[key], dflt)
        if abs(v - dflt) > 0.0005:
            eq.append("%s=%.3f" % (nm, v))
    if eq:
        add("eq=" + ":".join(eq), "eq")
    sh_, mi_, hi_ = _f(S["shadows"]) / 100.0, _f(S["midtones"]) / 100.0, _f(S["highlights"]) / 100.0
    if abs(sh_) > 0.001 or abs(mi_) > 0.001 or abs(hi_) > 0.001:
        pts = "0/0 0.25/%.4f 0.5/%.4f 0.75/%.4f 1/1" % (0.25 + 0.15 * sh_, 0.5 + 0.12 * mi_, 0.75 + 0.15 * hi_)
        add("curves=master='%s'" % pts, "curves")
    tm, tn = _f(S["temperature"]) / 100.0 * 0.25, _f(S["tint"]) / 100.0 * 0.2
    if abs(tm) > 0.001 or abs(tn) > 0.001:
        add("colorbalance=rs=%.3f:gs=%.3f:bs=%.3f:rm=%.3f:gm=%.3f:bm=%.3f:rh=%.3f:gh=%.3f:bh=%.3f" % (
            tm, -tn, -tm, tm, -tn, -tm, tm, -tn, -tm), "colorbalance")
    if abs(_f(S["hue"])) > 0.05:
        add("hue=h=%.1f" % _f(S["hue"]), "hue")
    if abs(_f(S["vibrance"])) > 0.005:
        add("vibrance=intensity=%.3f" % _f(S["vibrance"]), "vibrance")
    cf = S["colorfx"]
    if cf == "bw":
        add("hue=s=0", "hue")
    elif cf == "sepia":
        add("colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131:0", "colorchannelmixer")
    elif cf == "negate":
        add("negate")
    if str(S["lut"]).strip():
        add("lut3d=file=%s" % ffq(str(S["lut"]).strip()), "lut3d")
    vg = _f(S["vig"])
    if vg > 0.5:
        add("vignette=angle=%.4f:mode=%s" % ((1.0 - min(vg, 100.0) / 100.0) * (math.pi / 2) + 0.05,
                                             "backward" if S["vig_mode"] == "backward" else "forward"), "vignette")

    # 5) élesség / lágyítás / szemcse
    sa = _f(S["sharp_amt"])
    if S["sharp"] == "unsharp" and sa > 0:
        sz = max(3, min(23, _i(S["sharp_size"], 5) | 1))
        add("unsharp=luma_msize_x=%d:luma_msize_y=%d:luma_amount=%.2f:chroma_amount=0" % (sz, sz, sa), "unsharp")
    elif S["sharp"] == "cas" and sa > 0:
        add("cas=strength=%.2f" % min(1.0, sa / 3.0), "cas")
    if _f(S["blur"]) > 0.05:
        add("gblur=sigma=%.2f" % _f(S["blur"]), "gblur")
    if _i(S["grain"]) > 0:
        add("noise=alls=%d:allf=t+u" % _i(S["grain"]), "noise")

    # 6) képkocka-sebesség
    fp = re.sub(r"[^0-9./]", "", str(S["fps_to"]))
    if fp:
        m = S["fps_method"]
        if m == "blend":
            add("framerate=fps=%s" % fp, "framerate")
        elif m == "mci":
            add("minterpolate=fps=%s:mi_mode=mci:mc_mode=aobmc:vsbmc=1" % fp, "minterpolate")
        else:
            add("fps=%s" % fp, "fps")

    # 7) egyéni szűrők (szabad szöveg, a lánc végére)
    cu = str(S["custom"]).strip().strip(",")
    if cu:
        add(cu, "custom")

    missing = []
    if caps:
        for n in used:
            if n not in caps and n not in missing and n != "custom":
                missing.append(n)
    return ",".join(f), used, missing


def geometry_sig(state):
    """A kimeneti képméretet befolyásoló beállítások - ha a szakaszoké eltér, az egyberakás (concat) hibás lehet."""
    S = dict(DEFAULTS)
    S.update(state or {})
    return tuple(str(S[k]) for k in ("rotate", "angle", "angle_zoom", "crop_l", "crop_r", "crop_t", "crop_b", "crop_aspect",
                                     "square", "scale_w", "scale_h", "dar", "out_mode", "out_w", "out_h", "tonemap"))


def summary(used):
    seen = []
    for n in used:
        if n not in seen and n not in ("setsar", "format"):
            seen.append(n)
    return ", ".join(seen)


# ======================================================================== az ablak

VS_TEMPLATE_HU = '''# VapourSynth szkript az FFmpeg "vapoursynth" szűrőjéhez (lvt_ffmpeg / efekt.py)
import vapoursynth as vs
core = vs.core

clip = video_in          # az FFmpeg ezt a képfolyamot adja át a szkriptnek

# --- példák (vedd ki a # jelet, ha a bővítmény telepítve van) ---
# clip = core.knlm.KNLMeansCL(clip, d=1, s=3, h=1.0)      # zajszűrés
# clip = core.f3kdb.Deband(clip)                          # sávosodás-eltávolítás
# clip = core.resize.Spline36(clip, 1920, 1080)           # átméretezés

clip.set_output()
'''

VS_TEMPLATE_EN = '''# VapourSynth script for the FFmpeg "vapoursynth" filter (lvt_ffmpeg / efekt.py)
import vapoursynth as vs
core = vs.core

clip = video_in          # FFmpeg passes this video stream to the script

# --- examples (remove the # if the plugin is installed) ---
# clip = core.knlm.KNLMeansCL(clip, d=1, s=3, h=1.0)      # denoising
# clip = core.f3kdb.Deband(clip)                          # debanding
# clip = core.resize.Spline36(clip, 1920, 1080)           # resizing

clip.set_output()
'''

VS_TEMPLATE = VS_TEMPLATE_EN      # default (English)


USER_MARK = "★ "


class _Stale(Exception):
    """Szándékosan leállított (elavult) előnézet-számítás: nem hiba, nem jelenítjük meg."""


class _Latest:
    """Háttérszál, amely mindig csak a LEGUTÓBBI kérést dolgozza fel; az elavult ffmpeg-futást megöli."""

    def __init__(self, work, deliver):
        self.work, self.deliver = work, deliver
        self.cv = threading.Condition()
        self.req = None
        self.proc = None
        self.dead = False
        threading.Thread(target=self._loop, daemon=True).start()

    def submit(self, req):
        with self.cv:
            self.req = req
            p = self.proc
            self.cv.notify()
        if p is not None and p.poll() is None:
            try:
                p.kill()
            except OSError:
                pass

    def _loop(self):
        while True:
            with self.cv:
                while self.req is None and not self.dead:
                    self.cv.wait()
                if self.dead:
                    return
                req, self.req = self.req, None
            try:
                res, err = self.work(req, self), None
            except Exception as e:      # noqa
                res, err = None, e
                _log("HIBA előnézet-háttér: %s" % e)
            with self.cv:
                stale = self.req is not None or self.dead
            if not stale:
                self.deliver(req, res, err)

    def run(self, cmd, timeout=120):
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                 creationflags=_NOWIN)
        except OSError as e:
            raise RuntimeError(str(e))
        with self.cv:
            self.proc = p
        try:
            out, err = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            p.communicate()
            raise RuntimeError(_("Időtúllépés az előnézetnél.", "Preview timed out."))
        finally:
            with self.cv:
                self.proc = None
        if p.returncode != 0:
            with self.cv:
                superseded = self.dead or self.req is not None
            if superseded:
                raise _Stale()
            lines = err.decode("utf-8", "replace").strip().splitlines()
            raise RuntimeError(lines[-1] if lines else "ffmpeg exit %d" % p.returncode)
        return out

    def stop(self):
        with self.cv:
            self.dead = True
            p = self.proc
            self.cv.notify()
        if p is not None and p.poll() is None:
            try:
                p.kill()
            except OSError:
                pass


class EffectWindow:
    """Külön ablak: élő előnézet + effekt-beállítások szakaszonként; a Kimenet az Átalakítás fülre visz."""

    def __init__(self, panel, ff, segs):
        _log("NYITÁS v%s PIL=%s ffmpeg=%s segs=%d" % (EFEKT_VERSION, HAVE_PIL, getattr(ff, "ffmpeg", "?"), len(segs)))
        self.p, self.ff = panel, ff
        for _n in _GUARDED:                 # az efekt_vs.py által felülírtakat is (példányszinten) naplózzuk
            _bind_guard(self, _n)
        self.tk, self.ttk, self.fd, self.mb = panel.tk, panel.ttk, panel.fd, panel.mb
        self.segs = []              # {"src","a","b","state"}
        self.infos = {}             # forrás -> quick_info dict | None (töltődik) | False (hiba)
        self.caps = None            # az ffmpeg szűrői (halmaz) vagy None
        self.cur = -1
        self.token = 0
        self._loading = False
        self._after = None
        self._playing = False      # a beépített lejátszás fut-e
        self._pgen = 0             # lejátszás-azonosító (az elavult szálak leállításához)
        self._pproc = None
        self._pbusy = False
        self._fit_after = None
        self._pq = None           # a lejátszó szál képkocka-sora
        self._pending = None       # a sorból kivett, még nem esedékes képkocka
        self._ptick = None         # a Tk-oldali lejátszó-időzítő azonosítója
        self._apump = None         # a hang (_AudioPump az lvt_ffmpeg.py-ból)
        self._pstate = None        # a lejátszás adatai (idő, fps, méret ...)
        self.fs = None             # teljes képernyős nézet (dict) vagy None
        self._ok = True
        self.vars, self.kinds = {}, {}
        self._inbox = queue.Queue()   # háttérszál -> Tk-szál üzenetek (a panel q-jától függetlenül)
        self._msg_keep = ""           # tartós üzenet (pl. automatikus váltás), amíg nincs újabb esemény
        self._wait_n = 0              # hányszor vártunk a vászon megjelenésére
        # Megjegyzés: NINCS transient(), így az ablak címsorában ott van a minimalizálás / maximalizálás gomb is.
        top = self.top = self.tk.Toplevel(panel.parent.winfo_toplevel())
        top.title(_("Képeffektek – előnézet és beállítás", "Image effects - preview and settings"))
        top.geometry("1260x820")
        top.minsize(1000, 660)
        try:
            top.resizable(True, True)
            top.attributes("-toolwindow", False)
        except Exception:       # noqa
            pass
        top.protocol("WM_DELETE_WINDOW", self.close)
        self.worker = _Latest(self._frame_work, self._frame_deliver)
        self._build()
        self._space_buttons(self.top)
        top.bind("<Configure>", lambda e: self._schedule_fit(400) if e.widget is top else None)
        top.bind("<space>", self._space_key)
        self._schedule_fit(300)
        self._inbox_poll()
        self.add_segments(segs)
        self._load_caps()

    # ------------------------------------------------------------ általános
    def alive(self):
        try:
            return bool(self._ok and self.top.winfo_exists())
        except Exception:       # noqa
            return False

    def focus(self):
        try:
            self.top.deiconify()
            self.top.lift()
            self.top.focus_force()
        except Exception:       # noqa
            pass

    def close(self):
        self._ok = False
        self._stop_play()
        self._close_fs()
        try:
            if self._after:
                self.top.after_cancel(self._after)
        except Exception:       # noqa
            pass
        self.worker.stop()
        try:
            self.top.destroy()
        except Exception:       # noqa
            pass

    def _post(self, fn, res, err):
        """Háttérszálból a Tk-szálra. SAJÁT sorba megy, amit az ablak maga üríti (_inbox_poll).
        Korábban a panel q-ján ment át: ha a panel nem ürítette, az előnézet fekete maradt (betöltéskor)."""
        self._inbox.put((fn, res, err))

    def _inbox_poll(self):
        if not self._ok:
            return
        try:
            while True:
                fn, res, err = self._inbox.get_nowait()
                try:
                    fn(res, err)
                except Exception as e:      # noqa
                    self._show_error(_("Belső hiba: ", "Internal error: ") + str(e))
        except queue.Empty:
            pass
        try:
            self.top.after(30, self._inbox_poll)
        except Exception:       # noqa
            pass

    def _save_cfg(self):
        import sys
        mod = sys.modules.get(type(self.p).__module__)
        try:
            mod.save_config(self.p.cfg)
        except Exception:       # noqa
            pass

    # ------------------------------------------------------------ felépítés
    def _build(self):
        ttk, top = self.ttk, self.top
        bottom = ttk.Frame(top, padding=(6, 2))
        bottom.pack(side="bottom", fill="x")
        pw = ttk.PanedWindow(top, orient="horizontal")
        pw.pack(side="top", fill="both", expand=True)
        left, right = ttk.Frame(pw), ttk.Frame(pw)
        self.pw, self.left = pw, left
        left.bind("<Configure>", lambda e: self._layout(self.main))
        pw.add(left, weight=3)
        pw.add(right, weight=2)
        self._build_preview(left)
        self._build_tabs(right)
        self._build_bottom(bottom)

    def _build_preview(self, f):
        tk, ttk, top = self.tk, self.ttk, self.top
        asp = str(self.p.cfg.get("fx_aspect", "16:9"))
        self.v_aspect = tk.StringVar(master=top, value=asp if asp in ("16:9", "4:3") else "16:9")
        self.v_audio = tk.BooleanVar(master=top, value=True)
        self.v_show = tk.StringVar(master=top, value="video")     # alapból VIDEÓ mód (élő, effektekkel)
        self.v_perf = tk.StringVar(master=top, value="")
        try:
            bgc = self.ttk.Style(master=top).lookup("TFrame", "background") or top.cget("bg")
        except Exception:       # noqa
            bgc = "#f0f0f0"
        box = tk.Frame(f, bg=bgc, width=640, height=360)
        box.pack(fill="x", padx=10, pady=4)
        box.pack_propagate(False)
        self.cv = tk.Canvas(box, bg="#000000", highlightthickness=0)
        self.cv.configure(takefocus=1)
        self.cv.bind("<Button-1>", lambda e: self.cv.focus_set(), add="+")
        self.img = tk.PhotoImage(master=top)
        self.cimg = self.cv.create_image(0, 0, anchor="center", image=self.img)
        self.main = dict(cv=self.cv, img=self.img, cimg=self.cimg, box=box, photo=None)
        box.bind("<Configure>", lambda e: self._layout(self.main))
        # átméretezésnél lejátszás közben nem indítjuk újra a lejátszást (csak állóképnél frissítünk)
        self.cv.bind("<Configure>", self._cv_configure)
        self.cv.bind("<Double-Button-1>", self._toggle_fs)
        self._layout(self.main)

        t = ttk.Frame(f)
        t.pack(fill="x", padx=10, pady=2)
        for txt, d in ((_("⏮ Eleje", "⏮ Start"), "start"), ("−1 s", -1.0), (_("−1 kocka", "−1 frame"), "f-"),
                       (_("+1 kocka", "+1 frame"), "f+"), ("+1 s", 1.0), (_("Vége ⏭", "End ⏭"), "end")):
            ttk.Button(t, text=txt, width=9, command=lambda d=d: self._step(d), takefocus=False).pack(side="left", padx=1)
        self.v_t = tk.DoubleVar(master=top, value=0.0)
        self.sc_t = ttk.Scale(t, from_=0.0, to=1.0, variable=self.v_t, orient="horizontal")
        self.sc_t.pack(side="left", fill="x", expand=True, padx=8)
        # húzás: lejátszás közben a húzás alatt megáll, a kép a csúszkát követi (állóképben);
        # elengedéskor, ha előtte ment a lejátszás, az új helyről folytatódik
        self.sc_t.bind("<ButtonPress-1>", self._drag_begin, add="+")
        self.sc_t.bind("<ButtonRelease-1>", self._drag_end, add="+")
        self.v_tl = tk.StringVar(master=top, value="")
        ttk.Label(t, textvariable=self.v_tl, width=26).pack(side="left")
        self.v_t.trace_add("write", self._time_changed)

        r0 = ttk.Frame(f)
        r0.pack(fill="x", padx=10, pady=(0, 2))
        self._r0_frame = r0
        ttk.Label(r0, text=_("Képernyő:", "Screen:")).pack(side="left", padx=(0, 2))
        for k in ("16:9", "4:3"):
            ttk.Radiobutton(r0, text=k, value=k, variable=self.v_aspect, command=self._aspect_changed,
                            takefocus=False).pack(side="left", padx=4)
        ttk.Checkbutton(r0, text=_("Hang", "Sound"), variable=self.v_audio, takefocus=False).pack(side="left", padx=(14, 4))
        ttk.Label(r0, text=_("Hang–kép igazítás (ms):", "Audio/video offset (ms):")).pack(side="left", padx=(6, 2))
        self.v_off = tk.StringVar(master=top, value=str(self.p.cfg.get("av_off", "0")))
        ttk.Entry(r0, textvariable=self.v_off, width=6).pack(side="left")
        self.v_off.trace_add("write", lambda *a: self._save_off())

        self.v_msg = tk.StringVar(master=top, value="")
        rs = self._rs_frame = ttk.Frame(f)
        rs.pack(fill="x", padx=10, pady=(0, 2))
        ttk.Label(rs, text=_("Előnézet:", "Preview:")).pack(side="left", padx=(0, 2))
        ttk.Radiobutton(rs, text=_("Videó (élő, effektekkel)", "Video (live, with effects)"), value="video",
                        variable=self.v_show, command=self._show_changed, takefocus=False).pack(side="left", padx=4)
        ttk.Radiobutton(rs, text=_("Állókép (változtatásnál egy kép)", "Still (one picture per change)"), value="still",
                        variable=self.v_show, command=self._show_changed, takefocus=False).pack(side="left", padx=4)
        ttk.Label(rs, textvariable=self.v_perf, foreground="#555").pack(side="left", padx=10)

        r = ttk.Frame(f)
        r.pack(fill="x", padx=10, pady=2)
        self.v_mode = tk.StringVar(master=top, value="fx")
        for k, hu, en in (("orig", "Eredeti", "Original"), ("fx", "Effekttel", "With effects"),
                          ("split", "Osztott (bal: eredeti | jobb: effekt)", "Split (left: original | right: effect)")):
            ttk.Radiobutton(r, text=_(hu, en), value=k, variable=self.v_mode, command=lambda: self._schedule(0)).pack(side="left", padx=(0, 8))
        self.v_split = tk.DoubleVar(master=top, value=50.0)
        ttk.Scale(r, from_=10, to=90, variable=self.v_split, orient="horizontal", length=110,
                  command=lambda v: self._schedule(150)).pack(side="left", padx=6)


        p = ttk.Frame(f)
        p.pack(fill="x", padx=10, pady=2)
        ttk.Button(p, text="▶ Play", command=self._play_fx, takefocus=False).pack(side="left")
        ttk.Button(p, text=_("■ Leállít", "■ Stop"), command=self._stop_play, takefocus=False).pack(side="left", padx=4)
        ttk.Label(p, text=_("(dupla kattintás a képre: teljes képernyő)", "(double-click the picture: full screen)"),
                  foreground="#555").pack(side="left", padx=4)
        self.v_info = tk.StringVar(master=top, value="")
        ttk.Label(p, textvariable=self.v_info, foreground="#555").pack(side="left", padx=10)

        c = ttk.Frame(f)
        c.pack(fill="x", padx=10, pady=2)
        ttk.Label(c, text=_("Szűrőlánc (-vf):", "Filter chain (-vf):")).pack(side="left", anchor="n", pady=(2, 0))
        self.v_chain = tk.StringVar(master=top, value="")
        cw = ttk.Frame(c)
        cw.pack(side="left", fill="x", expand=True, padx=4)
        txt = self._chain_txt = tk.Text(cw, height=3, wrap="word", relief="solid", bd=1, bg="#f4f4f4", font="TkDefaultFont",
                                        state="disabled", takefocus=0, cursor="arrow", padx=4, pady=2)
        csb = ttk.Scrollbar(cw, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=csb.set)
        txt.pack(side="left", fill="x", expand=True)
        csb.pack(side="left", fill="y")

        def _sync_chain(*_a, txt=txt):
            try:
                txt.configure(state="normal")
                txt.delete("1.0", "end")
                txt.insert("1.0", self.v_chain.get())
                txt.configure(state="disabled")
            except Exception:       # noqa
                pass
        self.v_chain.trace_add("write", _sync_chain)
        ttk.Button(c, text=_("Másolás", "Copy"), command=self._copy_chain, takefocus=False).pack(side="left", anchor="n")

        # (A sorok fentről lefelé, a kép alatt közvetlenül követik egymást: a felesleges magasság az ALJÁN marad, nem a sorok között.)

    def _scroll(self, parent):
        """Görgethető tartalom: függőleges és (ha a tartalom szélesebb a panelnél) vízszintes görgetősávval, így a sorok jobb szélén
        lévő gombok sem tűnnek el, ha a jobb oldali panel keskeny."""
        tk, ttk = self.tk, self.ttk
        cv = tk.Canvas(parent, highlightthickness=0, borderwidth=0)
        sb = ttk.Scrollbar(parent, orient="vertical", command=cv.yview)
        hb = ttk.Scrollbar(parent, orient="horizontal", command=cv.xview)
        inner = ttk.Frame(cv, padding=6)
        win = cv.create_window(0, 0, window=inner, anchor="nw")
        cv.configure(yscrollcommand=sb.set, xscrollcommand=hb.set)
        st = {"h": False}

        def fit(_e=None):
            try:
                need = inner.winfo_reqwidth()
                have = cv.winfo_width()
                cv.itemconfigure(win, width=max(have, need))
                cv.configure(scrollregion=cv.bbox("all"))
                want = need > have + 1 and have > 1
                if want != st["h"]:
                    st["h"] = want
                    if want:
                        hb.pack(side="bottom", fill="x", before=cv)
                    else:
                        hb.pack_forget()
                        cv.xview_moveto(0)
            except Exception:       # noqa
                pass
        inner.bind("<Configure>", fit)
        cv.bind("<Configure>", fit)
        sb.pack(side="right", fill="y")
        cv.pack(side="left", fill="both", expand=True)
        self._scrollers.append((cv, inner))
        return inner

    def _wheel_bind(self):
        def bind_tree(w, cv):
            def wheel(e):
                d = -1 if (getattr(e, "delta", 0) > 0 or getattr(e, "num", 0) == 4) else 1
                if getattr(e, "state", 0) & 1:          # Shift + görgő: vízszintes
                    cv.xview_scroll(d * 3, "units")
                else:
                    cv.yview_scroll(d, "units")
                return "break"
            for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                w.bind(ev, wheel, add="+")
            for ch in w.winfo_children():
                bind_tree(ch, cv)
        for cv, inner in self._scrollers:
            bind_tree(cv, cv)
            bind_tree(inner, cv)

    # --- elem-készítők (mindegyik egy állapot-mezőhöz köt)
    def _var(self, name, kind):
        tk, d = self.tk, DEFAULTS[name]
        if kind == "check":
            v = tk.BooleanVar(master=self.top, value=bool(d))
        elif kind == "slider":
            v = tk.DoubleVar(master=self.top, value=float(d))
        elif kind == "choice":
            v = tk.StringVar(master=self.top, value=label_of(name, d))
        else:
            v = tk.StringVar(master=self.top, value=str(d))
        v.trace_add("write", self._changed)
        self.vars[name], self.kinds[name] = v, kind
        return v

    def _sec(self, parent, title):
        lf = self.ttk.LabelFrame(parent, text=title, padding=5)
        lf.pack(fill="x", pady=4)
        return lf

    def _note(self, parent, text):
        self.ttk.Label(parent, text=text, foreground="#555", wraplength=370, justify="left").pack(fill="x", pady=(0, 3))

    def choice(self, parent, name, label, width=30):
        ttk = self.ttk
        r = ttk.Frame(parent)
        r.pack(fill="x", pady=1)
        ttk.Label(r, text=label, width=20, anchor="w").pack(side="left")
        v = self._var(name, "choice")
        ttk.Combobox(r, textvariable=v, state="readonly", width=width,
                     values=[_(hu, en) for _k, hu, en in CHOICES[name]]).pack(side="left", fill="x", expand=True)

    def check(self, parent, name, text):
        v = self._var(name, "check")
        self.ttk.Checkbutton(parent, text=text, variable=v, takefocus=False).pack(anchor="w", pady=1)

    def slider(self, parent, name, label, lo, hi, fmt="%.2f"):
        ttk = self.ttk
        r = ttk.Frame(parent)
        r.pack(fill="x", pady=1)
        ttk.Label(r, text=label, width=20, anchor="w").pack(side="left")
        v = self._var(name, "slider")
        lab = ttk.Label(r, width=7, anchor="e")

        def upd(*_a):
            try:
                lab.config(text=fmt % v.get())
            except Exception:       # noqa
                pass
        v.trace_add("write", upd)
        ttk.Scale(r, from_=lo, to=hi, orient="horizontal", variable=v).pack(side="left", fill="x", expand=True, padx=4)
        lab.pack(side="left")
        ttk.Button(r, text="↺", width=2, takefocus=False, command=lambda: v.set(DEFAULTS[name])).pack(side="left", padx=(2, 0))
        upd()

    def entry(self, parent, name, label, width=12, values=None, browse=None):
        ttk = self.ttk
        r = ttk.Frame(parent)
        r.pack(fill="x", pady=1)
        ttk.Label(r, text=label, width=20, anchor="w").pack(side="left")
        v = self._var(name, "text")
        if values is not None:
            ttk.Combobox(r, textvariable=v, values=values, width=width).pack(side="left")
        else:
            ttk.Entry(r, textvariable=v, width=width).pack(side="left", fill="x", expand=(width > 20))
        if browse:
            ttk.Button(r, text="…", width=3, command=browse).pack(side="left", padx=2)

    def numrow(self, parent, label, fields):
        ttk = self.ttk
        r = ttk.Frame(parent)
        r.pack(fill="x", pady=1)
        ttk.Label(r, text=label, width=20, anchor="w").pack(side="left")
        for name, cap in fields:
            ttk.Label(r, text=cap).pack(side="left", padx=(6, 1))
            ttk.Spinbox(r, from_=0, to=8000, increment=2, width=6, textvariable=self._var(name, "num")).pack(side="left")

    # --- fülek
    def _build_tabs(self, f):
        tk, ttk, top = self.tk, self.ttk, self.top
        pr = ttk.Frame(f)
        pr.pack(fill="x", pady=2)
        ttk.Label(pr, text=_("Minta:", "Look:")).pack(side="left")
        self.v_look = tk.StringVar(master=top, value="")
        self.cb_look = ttk.Combobox(pr, textvariable=self.v_look, state="readonly", width=30)
        self.cb_look.pack(side="left", padx=4)
        self.cb_look.bind("<<ComboboxSelected>>", lambda e: self._apply_look())
        ttk.Button(pr, text=_("Mentés…", "Save…"), command=self._save_look, takefocus=False).pack(side="left")
        ttk.Button(pr, text=_("Törlés", "Delete"), command=self._del_look, takefocus=False).pack(side="left", padx=2)
        self._refresh_looks()
        self._scrollers = []
        nb = self.nb = ttk.Notebook(f)
        nb.pack(fill="both", expand=True)
        tabs = []
        for key, hu, en in (("geo", "Geometria", "Geometry"), ("deint", "Deinterlace / fps", "Deinterlace / fps"),
                            ("light", "Fény – szín", "Light – colour"), ("sharp", "Élesség – zaj", "Sharpness – noise"),
                            ("vs", "VapourSynth", "VapourSynth"), ("custom", "Egyéni", "Custom")):
            fr = ttk.Frame(nb)
            nb.add(fr, text=_(hu, en))
            tabs.append(self._scroll(fr))
        self._tab_geo(tabs[0])
        self._tab_deint(tabs[1])
        self._tab_light(tabs[2])
        self._tab_sharp(tabs[3])
        self._tab_vs(tabs[4])
        self._tab_custom(tabs[5])
        self._wheel_bind()

    def _tab_geo(self, f):
        ttk = self.ttk
        s = self._sec(f, _("Forgatás / tükrözés", "Rotate / flip"))
        self.choice(s, "rotate", _("Forgatás / tükör", "Rotate / flip"))
        self.slider(s, "angle", _("Finom szög (vízszint)", "Fine angle (horizon)"), -45, 45, "%+.1f°")
        self.check(s, "angle_zoom", _("Fekete sarkok eltüntetése (nagyítással)", "Hide black corners (zoom in)"))
        s = self._sec(f, _("Körbevágás", "Crop"))
        self.numrow(s, _("Levágás (képpont)", "Trim (pixels)"), (("crop_l", _("bal", "left")), ("crop_r", _("jobb", "right"))))
        self.numrow(s, "", (("crop_t", _("felül", "top")), ("crop_b", _("alul", "bottom"))))
        r = ttk.Frame(s)
        r.pack(fill="x", pady=2)
        ttk.Button(r, text=_("Fekete sávok felismerése (cropdetect)", "Detect black bars (cropdetect)"), command=self._cropdetect,
                   takefocus=False).pack(side="left")
        self.choice(s, "crop_aspect", _("Középre vágás képarányra", "Centre crop to aspect"))
        s = self._sec(f, _("Átméretezés", "Resize"))
        r = ttk.Frame(s)
        r.pack(fill="x", pady=1)
        ttk.Label(r, text=_("Gyors méret", "Quick size"), width=20, anchor="w").pack(side="left")
        self.v_sizepre = self.tk.StringVar(master=self.top, value="—")
        cb = ttk.Combobox(r, textvariable=self.v_sizepre, state="readonly", width=12, values=[n for n, _w, _h in SIZE_PRESETS])
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self._size_preset())
        self.entry(s, "scale_w", _("Szélesség", "Width"), 14)
        self.entry(s, "scale_h", _("Magasság", "Height"), 14)
        self._note(s, _("-2 = a másik méretből arányosan. Üresen hagyva nincs átméretezés.",
                        "-2 = proportional to the other side. Leave empty for no resize."))
        self.choice(s, "scale_algo", _("Algoritmus", "Algorithm"), 14)
        self.check(s, "square", _("Négyzet-képpont (anamorf → pl. 1440x1080 helyett 1920x1080)", "Square pixels (anamorphic → e.g. 1920x1080)"))
        self.entry(s, "dar", _("Képarány-jelölő (DAR)", "Aspect flag (DAR)"), 8, values=["", "16:9", "4:3", "1:1", "21:9"])
        s = self._sec(f, _("Egységes kimeneti méret", "Uniform output size"))
        self._note(s, _("Több szakasz egyetlen fájlba fűzésekor ugyanazt a méretet állítsd be mindegyiknél.",
                        "When joining several segments into one file give them all the same size."))
        self.choice(s, "out_mode", _("Mód", "Mode"))
        self.numrow(s, _("Méret (kép­pont)", "Size (pixels)"), (("out_w", _("szél.", "w")), ("out_h", _("mag.", "h"))))

    def _tab_deint(self, f):
        s = self._sec(f, _("Deinterlace (összefésültség megszüntetése)", "Deinterlace"))
        self.choice(s, "deint", _("Módszer", "Method"))
        self.choice(s, "deint_parity", _("Mezősorrend", "Field order"))
        self.check(s, "deint_only", _("Csak az összefésült kockákat érintse", "Only touch interlaced frames"))
        self._note(s, _("Ha a kép „fésűs” mozgásnál: bwdif a legjobb általános választás. Az „(mező → dupla fps)” módok "
                        "50/60 képkocka/mp-et adnak. A mezősorrendet automatikusra hagyhatod.",
                        "If the picture is combed in motion bwdif is the best general choice. The field→double fps "
                        "modes give 50/60 fps. Field order can stay on auto."))
        s = self._sec(f, _("Képkocka-sebesség átalakítása", "Frame-rate conversion"))
        self.entry(s, "fps_to", _("Cél fps", "Target fps"), 10, values=FPS_VALUES)
        self.choice(s, "fps_method", _("Módszer", "Method"))
        self._note(s, _("Az Átalakítás fül saját „fps” mezője ezután is él; ha itt már megadtad, ott hagyd üresen.",
                        "The Convert tab's own fps field still applies; leave it empty if you set it here."))

    def _tab_light(self, f):
        s = self._sec(f, _("Alap", "Basics"))
        self.slider(s, "brightness", _("Fényerő", "Brightness"), -0.5, 0.5, "%+.2f")
        self.slider(s, "contrast", _("Kontraszt", "Contrast"), 0.2, 2.5, "%.2f")
        self.slider(s, "gamma", "Gamma", 0.3, 3.0, "%.2f")
        self.slider(s, "saturation", _("Telítettség", "Saturation"), 0.0, 3.0, "%.2f")
        s = self._sec(f, _("Fény – árnyék", "Light – shadow"))
        self.slider(s, "shadows", _("Árnyékok", "Shadows"), -100, 100, "%+.0f")
        self.slider(s, "midtones", _("Középtónusok", "Midtones"), -100, 100, "%+.0f")
        self.slider(s, "highlights", _("Fények", "Highlights"), -100, 100, "%+.0f")
        self.slider(s, "black", _("Fekete pont", "Black point"), 0.0, 0.4, "%.3f")
        self.slider(s, "white", _("Fehér pont", "White point"), 0.6, 1.0, "%.3f")
        self.check(s, "normalize", _("Automatikus kontraszt (normalize)", "Auto contrast (normalize)"))
        self.slider(s, "norm_smooth", _("  időbeli simítás (kocka)", "  temporal smoothing (frames)"), 0, 50, "%.0f")
        s = self._sec(f, _("Szín", "Colour"))
        self.slider(s, "temperature", _("Hőmérséklet (hideg ↔ meleg)", "Temperature (cool ↔ warm)"), -100, 100, "%+.0f")
        self.slider(s, "tint", _("Árnyalat (zöld ↔ bíbor)", "Tint (green ↔ magenta)"), -100, 100, "%+.0f")
        self.slider(s, "hue", _("Színezet-eltolás", "Hue shift"), -180, 180, "%+.0f°")
        self.slider(s, "vibrance", _("Élénkség (vibrance)", "Vibrance"), -1.0, 2.0, "%+.2f")
        self.choice(s, "colorfx", _("Színhatás", "Colour effect"))
        s = self._sec(f, _("Egyéb", "Other"))
        self.slider(s, "vig", _("Vignetta erőssége", "Vignette strength"), 0, 100, "%.0f")
        self.choice(s, "vig_mode", _("Vignetta módja", "Vignette mode"), 14)
        self.entry(s, "lut", _("3D LUT (.cube / .3dl)", "3D LUT (.cube / .3dl)"), 24, browse=self._browse_lut)
        self.check(s, "tonemap", _("HDR → SDR (tonemap; csak HDR-jelölésű forrásnál)", "HDR → SDR (tonemap; HDR-tagged sources only)"))

    def _tab_sharp(self, f):
        ttk = self.ttk
        s = self._sec(f, _("Élesítés", "Sharpen"))
        self.choice(s, "sharp", _("Módszer", "Method"))
        self.slider(s, "sharp_amt", _("Erősség", "Amount"), 0.0, 3.0, "%.2f")
        r = ttk.Frame(s)
        r.pack(fill="x", pady=1)
        ttk.Label(r, text=_("Mag mérete (unsharp)", "Kernel size (unsharp)"), width=20, anchor="w").pack(side="left")
        ttk.Spinbox(r, from_=3, to=23, increment=2, width=5, textvariable=self._var("sharp_size", "num")).pack(side="left")
        s = self._sec(f, _("Zajszűrés", "Denoise"))
        self.choice(s, "denoise", _("Módszer", "Method"))
        self.slider(s, "denoise_amt", _("Erősség", "Strength"), 0.0, 10.0, "%.1f")
        self.choice(s, "deblock", _("Blokkosodás-szűrés", "Deblock"), 14)
        self.check(s, "deband", _("Sávosodás-szűrés (deband)", "Remove banding (deband)"))
        self.slider(s, "deband_thr", _("  küszöb", "  threshold"), 0.005, 0.2, "%.3f")
        s = self._sec(f, _("Lágyítás / szemcse / stabilizálás", "Blur / grain / stabilise"))
        self.slider(s, "blur", _("Elmosás (gblur)", "Blur (gblur)"), 0.0, 10.0, "%.1f")
        self.slider(s, "grain", _("Filmszemcse", "Film grain"), 0, 60, "%.0f")
        self.check(s, "deshake", _("Egyszerű stabilizálás (deshake)", "Simple stabilisation (deshake)"))
        self.slider(s, "deshake_rx", _("  max. elmozdulás (képpont)", "  max shift (pixels)"), 1, 64, "%.0f")

    def _tab_vs(self, f):
        ttk = self.ttk
        s = self._sec(f, "VapourSynth")
        self._note(s, _("A VapourSynth az FFmpeg „vapoursynth” szűrőjén át érhető el, ezért csak olyan FFmpeg-buildnél működik, "
                        "amely tartalmazza (a legtöbb kész build NEM). A szkript a lánc ELSŐ eleme, vagyis az eredeti képen "
                        "dolgozik (pl. QTGMC, zajszűrés). A szkriptben a bemenet: video_in, a végén: clip.set_output().",
                        "VapourSynth is reached through FFmpeg's \"vapoursynth\" filter, so it works only with an FFmpeg build "
                        "that includes it (most prebuilt ones do NOT). The script is the FIRST element of the chain, i.e. it "
                        "works on the original picture (e.g. QTGMC, denoising). In the script the input is video_in, the "
                        "script ends with clip.set_output()."))
        self.v_vsnote = self.tk.StringVar(master=self.top, value="")
        ttk.Label(s, textvariable=self.v_vsnote, wraplength=370, justify="left").pack(fill="x", pady=2)
        self.check(s, "vs_on", _("VapourSynth-szkript használata", "Use a VapourSynth script"))
        self.entry(s, "vs_file", _("Szkript (.vpy)", "Script (.vpy)"), 24, browse=self._browse_vpy)
        ttk.Button(s, text=_("Sablon-szkript létrehozása…", "Create a template script…"), command=self._make_vpy,
                   takefocus=False).pack(anchor="w", pady=3)

    def _tab_custom(self, f):
        s = self._sec(f, _("Egyéni FFmpeg-szűrők", "Custom FFmpeg filters"))
        self._note(s, _("Szabadon beírható szűrőlánc (vesszővel elválasztva), amely a fenti beállítások UTÁN fut. "
                        "Pl.:  hue=s=0.5,chromashift=crh=3  –  minden FFmpeg-szűrő használható, a hibát az előnézet kiírja.",
                        "Free filter chain (comma separated) applied AFTER the settings above. E.g.  hue=s=0.5,chromashift=crh=3  "
                        "- any FFmpeg filter works, errors are shown by the preview."))
        self.entry(s, "custom", "-vf", 40)

    def _build_bottom(self, f):
        tk, ttk, top = self.tk, self.ttk, self.top
        g = ttk.LabelFrame(f, text=_("Szakaszok (a Szerkesztőből átvéve) – szakaszonként külön effekt",
                                     "Segments (from the Editor) - separate effects per segment"), padding=4)
        g.pack(fill="x")
        # Állandó állapotsor a szakaszok alatt: mindig látszik, fix magasságú (2 sor)
        try:
            sbg = ttk.Style(master=top).lookup("TFrame", "background") or top.cget("bg")
        except Exception:       # noqa
            sbg = "#f0f0f0"
        self.v_status = tk.StringVar(master=top, value="")
        self._status_lbl = tk.Label(f, textvariable=self.v_status, anchor="nw", justify="left", height=2,
                                    padx=4, pady=1, bg=sbg, wraplength=900)
        self._status_lbl.pack(fill="x", pady=(2, 0))
        f.bind("<Configure>", lambda e: self._status_lbl.configure(wraplength=max(200, e.width - 24)), add="+")
        self._status("")
        self.tree = ttk.Treeview(g, columns=("n", "f", "s", "e", "x"), show="headings", height=4, selectmode="browse")
        for c, t, w in (("n", "#", 32), ("f", _("Fájl", "File"), 220), ("s", _("Kezdet", "Start"), 90), ("e", _("Vég", "End"), 90),
                        ("x", _("Effektek", "Effects"), 330)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w", stretch=(c in ("f", "x")))
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._tree_select())
        bb = ttk.Frame(g)
        bb.pack(side="left", padx=6)
        self.v_all = tk.BooleanVar(master=top, value=False)
        ttk.Checkbutton(bb, text=_("Módosítás az összes szakaszra", "Edit all segments at once"), variable=self.v_all,
                        command=self._all_toggled, takefocus=False).pack(anchor="w")
        for txt, fn in ((_("Beállítások másolása mindre", "Copy settings to all"), self._copy_all),
                        (_("Alapértékek (nincs effekt)", "Reset (no effects)"), self._reset),
                        (_("Szakasz eltávolítása", "Remove segment"), self._remove)):
            ttk.Button(bb, text=txt, command=fn, takefocus=False).pack(fill="x", pady=1)
        ob = ttk.Frame(g)
        ob.pack(side="right", padx=6)
        try:
            big = ttk.Button(ob, text=_("✔ Kimenet → Átalakítás fül", "✔ Output → Convert tab"), command=self.output, style="Big.TButton")
        except Exception:       # noqa
            big = ttk.Button(ob, text=_("✔ Kimenet → Átalakítás fül", "✔ Output → Convert tab"), command=self.output)
        big.pack(fill="x", pady=2, ipady=6)
        ttk.Button(ob, text=_("Bezár", "Close"), command=self.close, takefocus=False).pack(fill="x")

    # ------------------------------------------------------------ állapot <-> felület
    def _collect(self):
        st = {}
        for name, v in self.vars.items():
            kind = self.kinds[name]
            try:
                val = v.get()
            except Exception:       # noqa
                val = DEFAULTS[name]
            if kind == "choice":
                val = key_of(name, val)
            elif kind == "slider":
                val = round(float(val), 4)
            elif kind == "num":
                val = _i(val, DEFAULTS[name] if isinstance(DEFAULTS[name], int) else 0)
                if isinstance(DEFAULTS[name], str):
                    val = str(val)
            st[name] = val
        return st

    def _load(self, st):
        self._loading = True
        try:
            for name, v in self.vars.items():
                val = st.get(name, DEFAULTS[name])
                kind = self.kinds[name]
                try:
                    if kind == "choice":
                        v.set(label_of(name, val))
                    elif kind == "slider":
                        v.set(float(val))
                    elif kind == "check":
                        v.set(bool(val))
                    else:
                        v.set(str(val))
                except Exception:       # noqa
                    pass
        finally:
            self._loading = False

    def _seg(self):
        return self.segs[self.cur] if 0 <= self.cur < len(self.segs) else None

    def _info_of(self, src):
        i = self.infos.get(src)
        return i if isinstance(i, dict) else None

    def _chain_of(self, sg, preview=False):
        """A szűrőlánc a szakaszhoz. preview=True: az előnézet hívása (az efekt_vs.py ezt használja); az
        előnézetben és a kimenetben is ugyanaz a lánc (a VapourSynth-et az efekt_vs.py kezeli)."""
        return build_chain(sg["state"], self._info_of(sg["src"]), self.caps)

    def _changed(self, *_a):
        if self._loading or not self._ok:
            return
        sg = self._seg()
        if sg is None:
            return
        st = self._collect()
        sg["state"] = st
        if self.v_all.get():
            for o in self.segs:
                if o is not sg:
                    o["state"] = dict(st)
        self._update_chain()
        self._schedule()

    def _update_chain(self):
        sg = self._seg()
        if sg is None:
            return
        chain, used, missing = self._chain_of(sg)
        self.v_chain.set(chain)
        self._set_msg(_("Az FFmpeg-build nem tartalmazza ezt a szűrőt: ", "This FFmpeg build lacks the filter: ") + ", ".join(missing)
                      if missing else "")
        for i, o in enumerate(self.segs):
            try:
                self.tree.set(str(i), "x", summary(self._chain_of(o)[1]) or "–")
            except Exception:       # noqa
                pass

    def _status(self, s, kind="info"):
        """Az ablak alján lévő ÁLLANDÓ állapotsor (a szakaszok alatt, rögzített helyen és magassággal):
        nincs hiba -> „Hibák: nincs” (zöld); hiba / figyelmeztetés -> a szöveg (piros / narancs)."""
        lbl = getattr(self, "_status_lbl", None)
        if lbl is None:
            return
        s = " ".join(str(s or "").split())
        if len(s) > 400:
            s = s[:397] + "…"
        if not s:
            txt, color = _("Hibák: nincs", "Errors: none"), "#1b7f3b"
        elif kind == "err":
            txt, color = _("Hiba: ", "Error: ") + s, "#b00020"
        else:
            txt, color = s, "#b36b00"
        try:
            self.v_status.set(txt)
            lbl.configure(fg=color)
        except Exception:       # noqa
            pass

    def _show_error(self, s):
        """Hibaüzenet felugró ablakban + az állandó állapotsorban. Ugyanazt a hibát nem ismétli, amíg nincs sikeres kocka."""
        s = str(s or "")
        if s:
            self._status(s, "err")
        if not s or s == getattr(self, "_last_popup", None):
            return
        self._last_popup = s
        try:
            from tkinter import messagebox as _mb
            _mb.showerror(_("Képeffektek – hiba", "Image effects – error"), s, parent=self.top)
        except Exception:       # noqa
            self._set_msg(s)

    def _set_msg(self, s):
        """Üzenet az állandó állapotsorba (nem foglal helyet a vezérlősorok között, nem mozgatja az elrendezést).
        Üres szöveg = nincs hiba."""
        self.v_msg.set(s)
        self._status(s, "info")

    def _copy_chain(self):
        try:
            self.top.clipboard_clear()
            self.top.clipboard_append(self.v_chain.get())
        except Exception:       # noqa
            pass

    # ------------------------------------------------------------ szakaszok
    def add_segments(self, segs):
        first = None
        for src, a, b in segs:
            key = self.p._fx_key(src, a, b)
            if any(self.p._fx_key(s["src"], s["a"], s["b"]) == key for s in self.segs):
                continue
            st = dict(DEFAULTS)
            old = ((self.p.fx.get(key) or getattr(self.p, "fx_reopen", {}).get(key) or {}).get("state")) or {}
            # a vs_* kulcsok (VapourSynth-lista, paraméterek, mód) nincsenek a DEFAULTS-ban, de újranyitáskor meg kell maradniuk
            st.update({k: v for k, v in old.items() if k in DEFAULTS or str(k).startswith("vs_")})
            self.segs.append(dict(src=src, a=float(a), b=float(b), state=st))
            if first is None:
                first = len(self.segs) - 1
            self._load_info(src)
        self._refresh_tree()
        if first is not None:
            self._select(first)
        elif self.cur < 0 and self.segs:
            self._select(0)

    def _refresh_tree(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for n, s in enumerate(self.segs):
            self.tree.insert("", "end", iid=str(n), values=(n + 1, os.path.basename(s["src"]), fmt_time(s["a"]), fmt_time(s["b"]),
                                                            summary(self._chain_of(s)[1]) or "–"))
        if 0 <= self.cur < len(self.segs):
            self.tree.selection_set(str(self.cur))

    def _tree_select(self):
        sel = self.tree.selection()
        if sel and int(sel[0]) != self.cur:
            self._select(int(sel[0]))

    def _select(self, idx):
        if not (0 <= idx < len(self.segs)):
            return
        self._stop_play()
        self._msg_keep = ""
        self._wait_n = 0
        self.cur = idx
        sg = self.segs[idx]
        try:
            self._load(sg["state"])
        except Exception:           # noqa
            _log("HIBA _load: " + __import__("traceback").format_exc())
        a, b = sg["a"], max(sg["b"], sg["a"] + 0.04)
        self._loading = True
        try:
            self.sc_t.configure(from_=a, to=b)
            self.v_t.set(a)           # a betöltési pont a szakasz ELEJE: ezen az első képkocka látszik
        finally:
            self._loading = False
        try:
            self.tree.selection_set(str(idx))
        except Exception:       # noqa
            pass
        self._time_changed()
        self._info_text()
        self._update_chain()
        self._schedule(0)

    def _remove(self):
        if not self.segs or self.cur < 0:
            return
        self._stop_play()
        del self.segs[self.cur]
        self.cur = min(self.cur, len(self.segs) - 1)
        self._refresh_tree()
        if self.segs:
            self._select(self.cur)
        else:
            self.cur = -1
            self.v_chain.set("")

    def _reset(self):
        if self.cur < 0:
            return
        self._load(DEFAULTS)
        self._changed()

    def _copy_all(self):
        sg = self._seg()
        if not sg:
            return
        for o in self.segs:
            o["state"] = dict(sg["state"])
        self._update_chain()

    def _all_toggled(self):
        if self.v_all.get():
            self._copy_all()

    # ------------------------------------------------------------ háttér-adatok
    def _load_info(self, src):
        if src in self.infos:
            return
        self.infos[src] = None
        ff = self.ff

        def work():
            try:
                return ff.quick_info(src), None
            except Exception as e:      # noqa
                return None, e

        def run():
            res, err = work()
            self._post(lambda r, e: self._info_done(src, res, err), None, None)
        threading.Thread(target=run, daemon=True).start()

    def _info_done(self, src, info, err):
        if not self._ok:
            return
        self.infos[src] = info if info else False
        sg = self._seg()
        if sg and sg["src"] == src:
            self._info_text()
            self._update_chain()
            self._schedule(0)

    def _info_text(self):
        sg = self._seg()
        i = self._info_of(sg["src"]) if sg else None
        if not i:
            self.v_info.set("")
            return
        self.v_info.set("%dx%d  %.3f fps  SAR %.3f%s" % (i.get("w", 0), i.get("h", 0), i.get("fps", 0), i.get("sar", 1.0),
                                                        _("  összefésült", "  interlaced") if i.get("interlaced") else ""))

    def _load_caps(self):
        ff = self.ff

        def run():
            try:
                caps = ff.filters()
            except Exception:       # noqa
                caps = None
            self._post(lambda r, e: self._caps_done(caps), None, None)
        threading.Thread(target=run, daemon=True).start()

    def _caps_done(self, caps):
        if not self._ok:
            return
        self.caps = caps
        if caps is not None:
            if "vapoursynth" in caps:
                self.v_vsnote.set(_("✔ Ez az FFmpeg-build tartalmazza a vapoursynth szűrőt.", "✔ This FFmpeg build includes the vapoursynth filter."))
            else:
                self.v_vsnote.set(_("✘ Ez az FFmpeg-build NEM tartalmazza a vapoursynth szűrőt – a szkript nem fog működni.",
                                    "✘ This FFmpeg build does NOT include the vapoursynth filter - the script will not work."))
        self._update_chain()

    # ------------------------------------------------------------ idő, léptetés
    def _fps(self):
        sg = self._seg()
        i = self._info_of(sg["src"]) if sg else None
        return (i or {}).get("fps") or 25.0

    def _time_changed(self, *_a):
        sg = self._seg()
        if sg is None:
            return
        try:
            t = float(self.v_t.get())
        except Exception:       # noqa
            return
        self.v_tl.set("%s  (+%.2f s)" % (fmt_time(t), t - sg["a"]))
        if not self._loading:
            self._schedule(150)

    def _step(self, d):
        sg = self._seg()
        if sg is None:
            return
        t = float(self.v_t.get())
        if d == "start":
            t = sg["a"]
        elif d == "end":
            t = max(sg["a"], sg["b"] - 1.0 / self._fps())
        elif d == "f-":
            t -= 1.0 / self._fps()
        elif d == "f+":
            t += 1.0 / self._fps()
        else:
            t += d
        self.v_t.set(min(max(t, sg["a"]), max(sg["b"] - 0.001, sg["a"])))

    # ------------------------------------------------------------ előnézet
    def _schedule(self, delay=250):
        if not self._ok:
            return
        try:
            if self._after:
                self.top.after_cancel(self._after)
            self._after = self.top.after(delay, self._request)
        except Exception:       # noqa
            pass

    def _request(self):
        """Előnézet a csúszka / beállítás szerint. VIDEÓ módban lejátszás közben az élő lejátszás indul újra az
        új beállítással az aktuális helyről; minden más esetben EGY állókép készül az aktuális időpontból."""
        self._after = None
        sg = self._seg()
        if sg is None or not self._ok:
            return
        if not self._canvas_ready() and self._wait_n < 40:
            self._wait_n += 1
            self._schedule(100)           # a vászon még nincs kirajzolva: később rajzolunk, nem üres képre
            return
        self._wait_n = 0
        if self._playing:
            if self.v_show.get() == "video":
                self._start_play()
                return
            self._stop_play()             # állókép módban a változtatás leállítja a lejátszást
        self._still(sg)

    def _still(self, sg):
        chain = self._chain_of(sg)[0]
        W, H = self._view_size()
        self.token += 1
        req = dict(token=self.token, src=sg["src"], t=float(self.v_t.get()), mode=self.v_mode.get(), chain=chain,
                   W=W, H=H, split=float(self.v_split.get()) / 100.0, fps=self._fps())
        req = self._req_extra(sg, req)
        _log("KERES token=%d t=%.3f mode=%s show=%s W=%d H=%d chain=%r" % (
            self.token, req["t"], req["mode"], self.v_show.get(), W, H, chain))
        self.worker.submit(req)

    def _req_extra(self, sg, req):
        """Bővítési pont: az efekt_vs ide írja a VapourSynth-adatokat (vs, script, vsp)."""
        return req

    def _drag_begin(self, _e=None):
        self._dragging = True
        self._was_playing = self._playing
        self._cancel_after()
        if self._playing:
            self._stop_play()

    def _drag_end(self, _e=None):
        if not getattr(self, "_dragging", False):
            return
        self._dragging = False
        self._cancel_after()
        if self._was_playing:
            self._was_playing = False
            self._play_fx()
        else:
            self._schedule(0)

    def _cancel_after(self):
        try:
            if self._after:
                self.top.after_cancel(self._after)
        except Exception:       # noqa
            pass
        self._after = None

    def _cv_configure(self, e):
        key = (e.width, e.height)
        if key == getattr(self, "_cv_size", None):
            return
        self._cv_size = key
        if not self._playing:
            self._schedule(300)

    def _canvas_ready(self):
        """A kép-vászon látszik-e és van-e mérete (különben a rajzolás elcsúszik / 0x0 képet adna)."""
        try:
            cv = self.main["cv"]
            return bool(cv.winfo_ismapped()) and cv.winfo_width() >= 60 and cv.winfo_height() >= 40
        except Exception:       # noqa
            return False

    def _show_changed(self):
        if self.v_show.get() == "still":
            self._stop_play()
        self._msg_keep = ""
        self._set_msg("")
        self._schedule(0)

    def _fallback_still(self):
        """Automatikus visszaesés: a gép nem tartja a valós időt -> ÁLLÓKÉP mód, a figyelmeztetés megmarad."""
        self.v_show.set("still")
        self._stop_play()
        self._msg_keep = _("A gép ezzel az effekttel nem bírja élőben, ezért Állókép módra váltottam. "
                           "Élő lejátszáshoz válts újra Videó módra, vagy csökkentsd az effektet.",
                           "This machine cannot keep up live with these effects, so the preview switched to Still. "
                           "For live playback switch back to Video, or reduce the effects.")
        self._set_msg(self._msg_keep)
        self._schedule(0)

    def _view(self):
        """Az éppen látható nézet: teljes képernyő, ha nyitva van, különben a beépített kis ablak."""
        return self.fs or self.main

    def _aspect_value(self):
        return 4.0 / 3.0 if self.v_aspect.get() == "4:3" else 16.0 / 9.0

    def _layout(self, v):
        """A kép-vásznat a kiválasztott képarányú (16:9 / 4:3) legnagyobb téglalapba igazítja a tartóján belül."""
        try:
            box, cv = v["box"], v["cv"]
            a = self._aspect_value()
            pw = box.winfo_width()
            if pw < 40:
                return
            if v is self.main:
                # a beépített keret maga lesz 16:9 / 4:3 arányú: a magassága a szélességéből adódik, a kép teljesen kitölti
                h = max(30, int(pw / a))
                lh = self.left.winfo_height()
                if lh > 300:
                    other = sum(c.winfo_reqheight() for c in self.left.winfo_children() if c is not box)
                    h = min(h, max(120, lh - other - 16))
                # a keret magassága a képé; a kép MINDIG pontos 16:9 / 4:3 arányú (ha kevés a hely, keskenyebb lesz, középen)
                if abs(int(box.cget("height")) - h) > 1:
                    box.configure(height=h)
                w2, h2 = pw, int(pw / a)
                if h2 > h:
                    w2, h2 = int(h * a), h
                cv.place(relx=0.5, rely=0.5, anchor="center", width=max(40, w2), height=max(30, h2))
                return
            ph = box.winfo_height()
            if ph < 40:
                return
            w, h = pw, int(pw / a)
            if h > ph:
                w, h = int(ph * a), ph
            cv.place(relx=0.5, rely=0.5, anchor="center", width=max(40, w), height=max(30, h))
        except Exception:       # noqa
            pass

    def _schedule_fit(self, delay=300):
        if not self._ok:
            return
        try:
            if self._fit_after:
                self.top.after_cancel(self._fit_after)
            self._fit_after = self.top.after(delay, self._fit_pane)
        except Exception:       # noqa
            pass

    def _fit_pane(self, tries=0):
        """A bal oldalt (kép) olyan szélesre húzza, hogy a 16:9 / 4:3 keret kitöltse a rendelkezésre álló magasságot;
        a jobb oldali beállítás-panel ennyivel keskenyebb lesz (de legalább ~400 képpont marad neki)."""
        self._fit_after = None
        if not self._ok:
            return
        try:
            self.top.update_idletasks()
            lh, total = self.left.winfo_height(), self.pw.winfo_width()
            if (lh < 200 or total < 600) and tries < 10:
                self._fit_after = self.top.after(200, lambda: self._fit_pane(tries + 1))
                return
            box = self.main["box"]
            ctrl = sum(c.winfo_reqheight() for c in self.left.winfo_children() if c is not box)
            avail = lh - ctrl - 20
            w = int(avail * self._aspect_value()) + 12
            if w > total - 400 and avail > 150:
                # Szűk ablak: a jobb panel (min. 400 px) miatt a kép nem érné el a teljes magasságot (üres sáv maradna).
                # Ilyenkor az ablakot szélesítjük (a képernyő széléig), így a kép pontos arányban kitölti a helyet.
                try:
                    top = self.top
                    if top.state() == "normal":
                        need = w - (total - 400)
                        scr = top.winfo_screenwidth()
                        x0, wd = top.winfo_x(), top.winfo_width()
                        room_r = max(0, scr - (x0 + wd))
                        grow = min(need, room_r + max(0, x0))
                        if grow > 8 and getattr(self, "_autowiden_n", 0) < 3:
                            self._autowiden_n = getattr(self, "_autowiden_n", 0) + 1
                            nx = x0 - max(0, grow - room_r)
                            top.geometry("%dx%d+%d+%d" % (wd + grow, top.winfo_height(), max(0, nx), top.winfo_y()))
                            self._fit_after = top.after(250, lambda: self._fit_pane(tries))
                            return
                except Exception:       # noqa
                    pass
            self._autowiden_n = 0
            w = max(520, min(w, total - 400))
            self.pw.sashpos(0, w)
            self._balance()
        except Exception:       # noqa
            pass

    def _balance(self):
        """A bal oldal alján maradó üres magasságot a szakaszok listája kapja (több sor), így nincs üres sáv a szűrőlánc és a
        szakaszok között. Ha a kép emiatt szűkülne (kisebb ablak), a lista sorai visszacsökkennek (legalább 4)."""
        if not self._ok or getattr(self, "_bal_n", 0) > 6:
            return
        rh = 20
        try:
            self.top.update_idletasks()
            rows = [c for c in self.left.winfo_children() if c.winfo_ismapped()]
            if not rows:
                return
            last = max(c.winfo_y() + c.winfo_height() for c in rows)
            gap = self.left.winfo_height() - last
            box = self.main["box"]
            ideal = int(box.winfo_width() / self._aspect_value())
            deficit = ideal - box.winfo_height()
            cur = int(self.tree.cget("height"))
            new = cur
            if deficit > 4 and cur > 4:
                new = max(4, cur - int((deficit + rh - 1) // rh))
            elif gap > rh + 12:
                new = cur + int((gap - 12) // rh)
            if new != cur:
                self._bal_n = getattr(self, "_bal_n", 0) + 1
                self.tree.configure(height=new)
                self._schedule_fit(120)
            else:
                self._bal_n = 0
        except Exception:       # noqa
            pass

    def _aspect_changed(self):
        self.p.cfg["fx_aspect"] = self.v_aspect.get()
        self._save_cfg()
        self._layout(self.main)
        if self.fs:
            self._layout(self.fs)
        self._schedule_fit(50)
        self._schedule(300)

    def _view_size(self, play=False):
        cv = self._view()["cv"]
        cw, ch = cv.winfo_width(), cv.winfo_height()
        if cw < 60 or ch < 60:
            cw, ch = 640, 360
        W, H = max(160, cw) // 2 * 2, max(90, ch) // 2 * 2
        if play:
            # mozgóképnél a képkockák mérete korlátozott, hogy a lejátszás folyamatos maradjon; Pillow-val a kisebb képet
            # a kirajzoláskor felnagyítjuk a vászonra
            lim = 900000.0 if HAVE_PIL else 300000.0
            s = min(1.0, math.sqrt(lim / float(W * H)))
            if s < 1.0:
                W, H = max(160, int(W * s)) // 2 * 2, max(90, int(H * s)) // 2 * 2
        return W, H

    def _vcmd(self, src, ss, chain, mode, W, H, split, play=False, dur=0.0, pfps=25.0):
        """Egyetlen ffmpeg-parancs az előnézethez (állókép) vagy a lejátszáshoz (képkocka-folyam) - mindkét esetben UGYANAZ a kép."""
        disp = ("scale=trunc(iw*sar/2)*2:ih,setsar=1,scale=%d:%d:force_original_aspect_ratio=decrease,"
                "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:black" % (W, H, W, H))
        if play:
            disp = disp.replace("force_original_aspect_ratio=decrease", "force_original_aspect_ratio=decrease:flags=fast_bilinear")
            disp += ",fps=%.6f:start_time=0" % pfps
            base = [self.ff.ffmpeg, "-v", "error", "-nostdin", "-ss", "%.3f" % ss, "-t", "%.3f" % dur, "-i", src, "-an", "-sn"]
        else:
            base = [self.ff.ffmpeg, "-v", "error", "-nostdin", "-ss", "%.3f" % ss, "-i", src, "-an", "-sn", "-frames:v", "1"]
        out = ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        if mode == "orig" or not chain:
            return base + ["-vf", disp] + out
        if mode == "fx":
            return base + ["-vf", chain + "," + disp] + out
        p = split
        fc = ("[0:v]split=2[o][p];[p]%s,%s[f];[o]%s[o2];"
              "[o2]crop=trunc(iw*%.4f/2)*2:ih:0:0[l];"
              "[f]crop=iw-trunc(iw*%.4f/2)*2:ih:trunc(iw*%.4f/2)*2:0[r];[l][r]hstack[out]") % (chain, disp, disp, p, p, p)
        return base + ["-filter_complex", fc, "-map", "[out]"] + out

    def _frame_work(self, req, wk):
        W, H, fps = req["W"], req["H"], req["fps"]
        ss = max(0.0, req["t"] - 0.4 / fps)
        cmd = self._vcmd(req["src"], ss, req["chain"], req["mode"], W, H, req["split"])
        data = wk.run(cmd, 180)
        if len(data) != W * H * 3:
            raise RuntimeError(_("Az FFmpeg nem adott képkockát (a szűrőlánc üres képet eredményezett).",
                                 "FFmpeg returned no frame (the chain produced nothing)."))
        return data

    def _frame_deliver(self, req, res, err):
        self._post(lambda r, e: self._frame_done(req, r, e), res, err)

    def _frame_done(self, req, data, err):
        if not self._ok or req["token"] != self.token or self._playing:
            return
        if data is None and not err:        # megszakított / elavult számítás: nincs mit rajzolni
            return
        if err:
            _log("HIBA előnézet (token=%d): %s" % (req["token"], err))
            self._show_error(_("Előnézet-hiba: ", "Preview error: ") + str(err) + _("\n(részletek: efekt_naplo.txt)", "\n(details: efekt_naplo.txt)"))
            return
        _log("KÉSZ token=%d bytes=%d" % (req["token"], len(data) if data else 0))
        self._last_popup = None
        self._set_msg(self._msg_keep)
        self._draw(data, req["W"], req["H"], req["mode"] == "split" and bool(req["chain"]), req["split"])

    def _draw(self, data, W, H, split_line, split):
        """Egy kész RGB-képkockát kirajzol az aktuális nézetbe (kis ablak vagy teljes képernyő)."""
        v = self._view()
        cv = v["cv"]
        cw, ch = cv.winfo_width(), cv.winfo_height()
        dw, dh = W, H
        done = False
        if HAVE_PIL:
            try:
                im = _PILImage.frombuffer("RGB", (W, H), data, "raw", "RGB", 0, 1)
                s = min(cw / float(W), ch / float(H))
                if s > 1.02:            # a kisebb képkockát a vászon méretére nagyítjuk (teljes képernyő)
                    dw, dh = int(W * s), int(H * s)
                    im = im.resize((dw, dh), _PILImage.BILINEAR)
                ph = v.get("photo")
                if ph is not None and ph.width() == dw and ph.height() == dh:
                    ph.paste(im)
                else:
                    ph = v["photo"] = _PILImageTk.PhotoImage(im, master=cv)
                cv.itemconfigure(v["cimg"], image=ph)
                done = True
            except Exception:       # noqa
                done = False
                dw, dh = W, H
        if not done:
            try:
                v["img"].configure(data=b"P6 %d %d 255\n" % (W, H) + data, format="PPM")
                cv.itemconfigure(v["cimg"], image=v["img"])
            except self.tk.TclError:
                return
        cv.coords(v["cimg"], cw // 2, ch // 2)
        cv.delete("ov")
        if split_line:
            x = (cw - dw) // 2 + int(dw * split)
            y0 = (ch - dh) // 2
            H = dh
            cv.create_line(x, y0, x, y0 + H, fill="#ffcc00", width=2, tags="ov")
            cv.create_text(x - 8, y0 + 8, anchor="ne", fill="#ffcc00", text=_("eredeti", "original"), tags="ov")
            cv.create_text(x + 8, y0 + 8, anchor="nw", fill="#ffcc00", text=_("effekttel", "with effects"), tags="ov")

    # ------------------------------------------------------------ teljes képernyő (dupla kattintás)
    def _toggle_fs(self, _e=None):
        if self.fs:
            self._close_fs()
            return
        tk = self.tk
        top = tk.Toplevel(self.top)
        top.configure(bg="#000000")
        try:
            top.attributes("-fullscreen", True)
        except Exception:       # noqa
            try:
                top.state("zoomed")
            except Exception:       # noqa
                pass
        box = tk.Frame(top, bg="#000000")
        box.pack(fill="both", expand=True)
        cv = tk.Canvas(box, bg="#000000", highlightthickness=0)
        img = tk.PhotoImage(master=top)
        cimg = cv.create_image(0, 0, anchor="center", image=img)
        for w in (top, box, cv):
            w.bind("<Double-Button-1>", self._toggle_fs)
            w.bind("<Escape>", self._toggle_fs)
        top.bind("<space>", lambda e: self._stop_play() if self._playing else self._play_fx())
        v = dict(top=top, cv=cv, img=img, cimg=cimg, box=box, photo=None)
        box.bind("<Configure>", lambda e: self._layout(v))
        cv.bind("<Configure>", lambda e: self._schedule(250))
        top.protocol("WM_DELETE_WINDOW", self._close_fs)
        self.fs = v
        try:
            top.focus_force()
        except Exception:       # noqa
            pass
        self._schedule(200)

    def _close_fs(self):
        f, self.fs = self.fs, None
        if f is None:
            return
        try:
            f["top"].destroy()
        except Exception:       # noqa
            pass
        if self._ok:
            self._schedule(100)

    def _space_key(self, e=None):
        """Space: lejátszás / leállítás. Szöveges mezőben nem avatkozik be (ott a szóköz karakter kell)."""
        w = getattr(e, "widget", None)
        if not hasattr(w, "winfo_class"):
            try:
                w = self.top.focus_get()
            except Exception:       # noqa
                w = None
        cls = w.winfo_class() if w is not None else ""
        if cls in ("Entry", "TEntry", "Text", "Spinbox", "TSpinbox", "TCombobox", "Combobox"):
            return None
        if self._playing:
            self._stop_play()
        else:
            self._play_fx()
        return "break"

    def _space_buttons(self, w):
        """A gombokon a Space ne fusson le kétszer: a gomb saját Space-kötését (aktiválás/parancs) elnyomjuk."""
        for c in w.winfo_children():
            if c.winfo_class() in _BTN_CLASSES:
                c.bind("<KeyPress-space>", self._space_key)
                c.bind("<KeyRelease-space>", lambda e: "break")
            self._space_buttons(c)

    # ------------------------------------------------------------ beépített lejátszás (ffmpeg → képkockák a vászonra)
    def _play_fx(self):
        sg = self._seg()
        if sg is None:
            return
        t0 = float(self.v_t.get())
        if t0 >= sg["b"] - 0.1:             # a végén állunk: újra az elejéről
            t0 = sg["a"]
            self._loading = True
            try:
                self.v_t.set(t0)
            finally:
                self._loading = False
        self._playing = True
        self._start_play()

    def _host(self):
        """Az lvt_ffmpeg.py modulja (onnan vesszük a bevált hang-szinkron megoldást: _AudioPump, AUDIO_LAT)."""
        import sys
        return sys.modules.get(type(self.p).__module__)

    def _offset(self):
        try:
            return float(str(self.v_off.get()).replace(",", ".")) / 1000.0
        except ValueError:
            return 0.0

    def _save_off(self):
        try:
            self.p.cfg["av_off"] = str(self.v_off.get()).strip() or "0"
            self._save_cfg()
        except Exception:       # noqa
            pass

    def _make_pump(self, t0, dur):
        """Ugyanaz a hang-megoldás, mint a Szerkesztő lejátszójában: ffmpeg (pontos -ss) -> PCM -> ffplay (stdin)."""
        if not self.v_audio.get() or not getattr(self.ff, "ffplay", None):
            if self.v_audio.get():
                self._set_msg(_("Hang nélkül: az ffplay nincs megadva a Beállítás fülön.", "No sound: ffplay is not set on the Setup tab."))
            return None
        sg = self._seg()
        i = self._info_of(sg["src"]) if sg else None
        if i is not None and "audio" in i and not i["audio"]:
            return None
        cls = getattr(self._host(), "_AudioPump", None)
        if cls is None:
            return None
        try:
            return cls(self.ff, sg["src"], t0, dur, 100)
        except OSError:
            return None

    def _start_play(self):
        """(Újra)indítja a lejátszást az aktuális idő-csúszkától, az aktuális nézet méretével és a kiválasztott móddal."""
        self._kill_play()
        sg = self._seg()
        if sg is None or not self._ok:
            self._playing = False
            return
        t0 = float(self.v_t.get())
        dur = max(0.2, sg["b"] - t0)
        if dur <= 0.25:
            t0, dur = sg["a"], max(0.2, sg["b"] - sg["a"])
        chain = self._chain_of(sg)[0]
        W, H = self._view_size(play=True)
        pfps = max(5.0, min(30.0, self._fps()))
        mode = self.v_mode.get()
        split = float(self.v_split.get()) / 100.0
        ss = max(0.0, t0 - 0.4 / pfps)
        cmd = self._vcmd(sg["src"], ss, chain, mode, W, H, split, play=True, dur=dur + (t0 - ss), pfps=pfps)
        self._pgen += 1
        gen = self._pgen
        self._msg_keep = ""
        self._set_msg("")
        q = self._pq = queue.Queue(maxsize=6)
        self._pending = None
        self._pstate = dict(gen=gen, t0=t0, dur=dur, pfps=pfps, W=W, H=H, wall0=None, first=None, last_sl=0.0,
                            wait0=time.perf_counter(), off=self._offset(), info=(mode == "split" and bool(chain), split), shown=0, perf_t=0.0, perf_n=0)
        threading.Thread(target=self._play_thread, args=(gen, cmd, W, H, q), daemon=True).start()
        self._apump = self._make_pump(t0, dur)
        self._ptick = self.top.after(5, self._play_tick)

    def _play_thread(self, gen, cmd, W, H, q):
        """Háttérszál: az ffmpeg képkockáit olvassa és sorba teszi (a kirajzolást a Tk-oldali _play_tick végzi)."""
        err = None
        proc = None
        n = 0
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                    creationflags=_NOWIN, bufsize=W * H * 3)
            if gen != self._pgen:
                proc.kill()
                return
            self._pproc = proc
            fsz = W * H * 3
            while gen == self._pgen:
                buf = proc.stdout.read(fsz)
                if len(buf) < fsz:
                    break
                while gen == self._pgen:
                    try:
                        q.put((n, buf), timeout=0.05)
                        break
                    except queue.Full:
                        continue
                n += 1
            if n == 0 and gen == self._pgen:
                try:
                    lines = proc.stderr.read().decode("utf-8", "replace").strip().splitlines()
                    err = lines[-1] if lines else None
                except Exception:       # noqa
                    err = None
        except Exception as e:      # noqa
            err = str(e)
        finally:
            if proc is not None:
                try:
                    if proc.poll() is None:
                        proc.kill()
                    proc.wait()
                except Exception:       # noqa
                    pass
        while gen == self._pgen:            # a vége-jelzés (-1) a sor végére
            try:
                q.put((-1, err), timeout=0.05)
                break
            except queue.Full:
                continue

    def _slider_to(self, st, idx, force=False):
        now = time.time()
        if force or now - st["last_sl"] > 0.12:      # az idő-csúszka követi a lejátszást (nem indít új kérést)
            st["last_sl"] = now
            self._loading = True
            try:
                self.v_t.set(st["t0"] + idx / st["pfps"])
            finally:
                self._loading = False

    def _play_end(self, err):
        self._playing = False
        self._kill_play()
        self.v_perf.set("")
        # a klip végén a VapourSynth „beyond clip end” jelzése normális lezárás, nem hiba
        if err and "beyond clip end" not in str(err):
            self._show_error(_("Lejátszási hiba: ", "Playback error: ") + str(err))

    def _play_tick(self):
        """Tk-oldali lejátszó-óra. A kép és a hang közös indítása pontosan úgy működik, mint a Szerkesztő lejátszójában:
        az első képkocka megjelenik, a hang (_AudioPump) előtölt, majd a kép időzítése a hang TÉNYLEGES indulásához kötődik."""
        self._ptick = None
        st = self._pstate
        if not self._ok or not self._playing or st is None or st["gen"] != self._pgen:
            return
        q = self._pq
        pfps = st["pfps"]
        if st["wall0"] is None:
            eof = None
            if st["first"] is None:
                try:
                    idx, payload = q.get_nowait()
                except queue.Empty:
                    idx = None
                if idx is not None:
                    if idx < 0:
                        eof = payload or ""
                    else:
                        st["first"] = idx
                        self._draw(payload, st["W"], st["H"], st["info"][0], st["info"][1])
                        st["shown"] += 1
                        self._slider_to(st, idx, True)
            if st["first"] is not None:
                ap, idx, off, now = self._apump, st["first"], st["off"], time.perf_counter()
                if ap is None:
                    st["wall0"] = now - idx / pfps + max(0.0, off)
                elif not ap.go.is_set():
                    if ap.ready.is_set() or now - st["wait0"] > 8.0:
                        ap.go_at = now + max(0.0, -off)       # negatív igazítás: a hang indul később
                        ap.go.set()
                elif ap.t_real0 is not None:
                    lat = getattr(self._host(), "AUDIO_LAT", 0.10)
                    st["wall0"] = ap.t_real0 + lat - idx / pfps + max(0.0, off)
            elif eof is not None:
                self._play_end(eof)
                return
            self._ptick = self.top.after(8, self._play_tick)
            return
        due = int((time.perf_counter() - st["wall0"]) * pfps)
        shown, eof = None, None
        while True:
            if self._pending is None:
                try:
                    self._pending = q.get_nowait()
                except queue.Empty:
                    break
            idx, payload = self._pending
            if idx < 0:
                eof = payload or ""
                break
            if idx <= due:
                shown = self._pending
                self._pending = None
            else:
                break
        if shown is not None:
            self._draw(shown[1], st["W"], st["H"], st["info"][0], st["info"][1])
            st["shown"] += 1
            self._slider_to(st, shown[0])
        if self._perf_update(st):         # automatikus váltás állóképre -> a lejátszó-óra leáll
            return
        if eof is not None:
            self._play_end(eof)
            return
        self._ptick = self.top.after(8, self._play_tick)

    def _perf_update(self, st):
        """Másodpercenként: a kirajzolt kockák száma. Az első 3 másodperc után, ha a kockák száma kisebb
        mint 0,6 x fps x eltelt idő, automatikusan Állókép módra vált. Igaz-értékkel tér vissza, ha váltott."""
        if st["wall0"] is None:
            return False
        now = time.perf_counter()
        if "t_w" not in st:
            st["t_w"], st["n_w"] = now, st["shown"]
            st["perf_t"], st["perf_n"] = now, st["shown"]
            return False
        dt = now - st["perf_t"]
        if dt < 1.0:
            return False
        rate = (st["shown"] - st["perf_n"]) / dt
        st["perf_t"], st["perf_n"] = now, st["shown"]
        self.v_perf.set(_("élő: %.0f / %.0f kocka/mp", "live: %.0f / %.0f fps") % (rate, st["pfps"]))
        el = now - st["t_w"]
        if el >= 3.0 and (st["shown"] - st["n_w"]) < 0.6 * st["pfps"] * el:
            self._fallback_still()
            return True
        return False

    def _kill_play(self):
        self._pgen += 1             # az éppen futó szál ettől kilép
        if self._ptick is not None:
            try:
                self.top.after_cancel(self._ptick)
            except Exception:       # noqa
                pass
            self._ptick = None
        self._pending = None
        ap, self._apump = self._apump, None
        if ap is not None:
            try:
                ap.close()
            except Exception:       # noqa
                pass
        p, self._pproc = self._pproc, None
        if p is not None and p.poll() is None:
            try:
                p.kill()
            except OSError:
                pass

    def _stop_play(self):
        self._playing = False
        self._kill_play()
        self.v_perf.set("")

    # ------------------------------------------------------------ részfunkciók
    def _size_preset(self):
        for n, w, h in SIZE_PRESETS:
            if n == self.v_sizepre.get() and (w or h or n == "—"):
                self.vars["scale_w"].set(w)
                self.vars["scale_h"].set(h)
                break

    def _browse_lut(self):
        p = self.fd.askopenfilename(parent=self.top, filetypes=[("LUT", "*.cube *.3dl *.dat"), ("*", "*.*")])
        if p:
            self.vars["lut"].set(os.path.normpath(p))

    def _browse_vpy(self):
        p = self.fd.askopenfilename(parent=self.top, filetypes=[("VapourSynth", "*.vpy *.py"), ("*", "*.*")])
        if p:
            self.vars["vs_file"].set(os.path.normpath(p))

    def _make_vpy(self):
        p = self.fd.asksaveasfilename(parent=self.top, defaultextension=".vpy", initialfile="szuro.vpy", filetypes=[("VapourSynth", "*.vpy")])
        if not p:
            return
        try:
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(_(VS_TEMPLATE_HU, VS_TEMPLATE_EN))
        except OSError as e:
            self.mb.showwarning("FFmpeg", str(e), parent=self.top)
            return
        self.vars["vs_file"].set(os.path.normpath(p))

    def _cropdetect(self):
        sg = self._seg()
        if sg is None:
            return
        info = self._info_of(sg["src"])
        if not info or not info.get("w"):
            self._set_msg(_("A forrás adatai még töltődnek, próbáld újra.", "Source info still loading, try again."))
            return
        cmd = [self.ff.ffmpeg, "-hide_banner", "-nostdin", "-ss", "%.3f" % sg["a"], "-t", "%.3f" % max(1.0, min(15.0, sg["b"] - sg["a"])),
               "-i", sg["src"], "-an", "-sn", "-vf", "cropdetect=limit=24:round=2:reset=0", "-f", "null", "-"]
        self._set_msg(_("Fekete sávok keresése…", "Detecting black bars…"))

        def run():
            try:
                r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=180,
                                   creationflags=_NOWIN)
                ms = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", r.stderr.decode("utf-8", "replace"))
                res, err = ([int(x) for x in ms[-1]], None) if ms else (None, RuntimeError(_("Nem található sáv.", "No bars found.")))
            except Exception as e:      # noqa
                res, err = None, e
            self._post(lambda r_, e_: self._crop_done(info, res, err), None, None)
        threading.Thread(target=run, daemon=True).start()

    def _crop_done(self, info, res, err):
        if not self._ok:
            return
        if err or not res:
            self._set_msg(str(err))
            return
        w, h, x, y = res
        self._set_msg("")
        self.vars["crop_l"].set(str(x))
        self.vars["crop_t"].set(str(y))
        self.vars["crop_r"].set(str(max(0, info["w"] - w - x)))
        self.vars["crop_b"].set(str(max(0, info["h"] - h - y)))

    # ------------------------------------------------------------ minták
    def _user_looks(self):
        return self.p.cfg.setdefault("fx_presets", {})

    def _refresh_looks(self):
        self.cb_look["values"] = ["—"] + [look_label(k) for k in LOOKS] + [USER_MARK + n for n in sorted(self._user_looks())]

    def _apply_look(self):
        name = self.v_look.get()
        if name == "—":
            return
        d = self._user_looks().get(name[len(USER_MARK):]) if name.startswith(USER_MARK) else LOOKS.get(look_key(name))
        if not isinstance(d, dict):
            return
        st = dict(DEFAULTS)
        st.update({k: v for k, v in d.items() if k in DEFAULTS})
        self._load(st)
        self._changed()

    def _save_look(self):
        from tkinter import simpledialog
        name = (simpledialog.askstring(_("Minta mentése", "Save look"), _("A minta neve:", "Look name:"), parent=self.top) or "").strip()
        if name.startswith(USER_MARK):
            name = name[len(USER_MARK):]
        if not name:
            return
        self._user_looks()[name] = self._collect()
        self._save_cfg()
        self._refresh_looks()
        self.v_look.set(USER_MARK + name)

    def _del_look(self):
        name = self.v_look.get()
        if not name.startswith(USER_MARK):
            self.mb.showinfo("FFmpeg", _("Csak a saját (★) minták törölhetők.", "Only your own (★) looks can be deleted."), parent=self.top)
            return
        self._user_looks().pop(name[len(USER_MARK):], None)
        self._save_cfg()
        self._refresh_looks()
        self.v_look.set("—")

    # ------------------------------------------------------------ kimenet
    def output(self):
        if not self.segs:
            return
        items, sigs, any_fx = [], set(), False
        for sg in self.segs:
            chain, used, missing = self._chain_of(sg)
            if missing:
                self.mb.showwarning("FFmpeg", _("Az FFmpeg-build nem tartalmazza ezeket a szűrőket: %s\n(%s)\n\nKapcsold ki az érintett effektet.",
                                                "This FFmpeg build lacks these filters: %s\n(%s)\n\nTurn the affected effect off.")
                                    % (", ".join(missing), os.path.basename(sg["src"])), parent=self.top)
                return
            any_fx = any_fx or bool(chain)
            info = self._info_of(sg["src"]) or {}
            sigs.add((geometry_sig(sg["state"]) if chain else None, info.get("w"), info.get("h")))
            items.append(dict(src=sg["src"], a=sg["a"], b=sg["b"], vf=chain, state=dict(sg["state"])))
        if any_fx and len(items) > 1 and len(sigs) > 1:
            if not self.mb.askyesno("FFmpeg", _(
                    "A szakaszok kimeneti képmérete eltérhet (más vágás / méret / forrás). Ha egyetlen fájlba fűzöd őket, "
                    "ez hibás eredményt adhat.\n\nTipp: a Geometria fülön az „Egységes kimeneti méret” mindegyiknél azonos legyen.\n\n"
                    "Folytatod így is?",
                    "The output picture size of the segments may differ (different crop / size / source). Joining them "
                    "into one file may then fail.\n\nTip: set the same \"Uniform output size\" on all of them.\n\n"
                    "Continue anyway?"), parent=self.top):
                return
        try:
            self.p.fx_apply(items)
        except Exception as e:      # noqa
            import traceback
            _log("HIBA fx_apply: %s" % traceback.format_exc())
            self._show_error(_("A kimenet átadása nem sikerült: ", "Passing the output failed: ") + str(e)
                             + _("  – részletek: efekt_naplo.txt", "  – details: efekt_naplo.txt"))
            return                  # az ablak nyitva marad: a beállítások nem vesznek el
        panel = self.p
        self.close()
        try:
            panel.reveal_convert()          # a főablak (Átalakítás fül) kerüljön előtérbe, az ablak bezárása után is
        except Exception:       # noqa
            pass


def _guarded(name, fn):
    def run(self, *a, **k):
        try:
            return fn(self, *a, **k)
        except Exception as e:      # noqa
            if isinstance(e, _Stale) or str(e) == "stale":
                return None
            import traceback
            _log("HIBA %s: %s" % (name, traceback.format_exc()))
            try:
                self._show_error(_("Belső hiba (%s): " % name, "Internal error (%s): " % name) + str(e)
                              + _("  – részletek: efekt_naplo.txt", "  – details: efekt_naplo.txt"))
            except Exception:       # noqa
                pass
            return None
    run.__name__ = fn.__name__
    return run


_BTN_CLASSES = ("TButton", "Button", "TCheckbutton", "TRadiobutton", "Checkbutton", "Radiobutton", "TMenubutton")

_GUARDED = ("_request", "_select", "_still", "_frame_done", "_draw", "_play_tick", "_start_play", "_play_fx",
            "_drag_end", "_drag_begin", "_info_done", "_caps_done", "_perf_update", "_fallback_still", "_play_end",
            "_show_changed", "_frame_work", "_changed", "_update_chain", "_frame_deliver", "_space_key")


def _bind_guard(obj, name):
    """A metódus példány-szintű, naplózó csomagolása (a felülírt, pl. efekt_vs-es változatot is figyeli)."""
    fn = getattr(type(obj), name, None)
    if fn is None:
        return
    def run(*a, **k):
        try:
            return fn(obj, *a, **k)
        except Exception as e:      # noqa
            if isinstance(e, _Stale) or str(e) == "stale":
                return None
            import traceback
            _log("HIBA %s: %s" % (name, traceback.format_exc()))
            try:
                obj._show_error(_("Belső hiba (%s): " % name, "Internal error (%s): " % name) + str(e)
                             + _("  – részletek: efekt_naplo.txt", "  – details: efekt_naplo.txt"))
            except Exception:       # noqa
                pass
            return None
    setattr(obj, name, run)


def open_window(panel, ff, segs):
    """Az lvt_ffmpeg.py hívja: panel = FfmpegPanel, ff = FFmpeg objektum, segs = [(forrás, kezdet, vég), ...]."""
    return EffectWindow(panel, ff, segs)

try:
    import sys, traceback
    import efekt_vs
    efekt_vs.install(sys.modules[__name__])
except Exception:
    with open("efekt_vs_hiba.txt", "w", encoding="utf-8") as _hiba:
        _hiba.write(traceback.format_exc())