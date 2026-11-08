# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 szabiz <szabiz@yahoo.com>
# Copyright (c) 2026 szabiz <szabiz@yahoo.com>
"""
vs_bridge.py - VapourSynth-szkript futtatása a VapourSynth SAJÁT parancssori eszközével (vspipe),
nem az FFmpeg "vapoursynth" szűrőjén át.

Miért: az FFmpeg vapoursynth szűrője csak egyes buildekben van benne, és a szkript hibája vagy a
-ss (időugrás) gyakran leállítja az egész folyamatot. A vspipe a szkriptet önállóan futtatja, és a
kimenetét (y4m) csőn keresztül adja az FFmpeg-nek - ezt használja a StaxRip is.

Szkript-paraméterek: a vspipe "-a kulcs=érték" kapcsolói a szkript globális változóiba kerülnek
(a szkriptben: globals().get("src")). Ezért a forrásfájl és az állítható értékek kívülről adhatók meg,
a szkriptet nem kell szerkeszteni.

Állítható paraméterek: a szkript "# @param" sorai alapján a felület csúszkákat készít, pl.:
    # @param strength float 1.0 0 3 Erősség
    # @param denoise int 0 0 1 Zajszűrés (0/1)
    # @param label str - - - Szöveges mező (pl. egy fájlnév)

Ez a modul csak parancsokat épít és egy-két folyamatot futtat; nem tartalmaz harmadik féltől származó kódot.
"""
import os
import re
import shutil
import subprocess
import sys

PARAM_RE = re.compile(r"^\s*#\s*@param\s+(\w+)\s+(int|float|bool|str)\s+(\S+)\s+(\S+)\s+(\S+)\s*(.*)$")
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _lang():
    """Active UI language, English by default. The host owns the setting: the
    efekt / lvt_ffmpeg / mts_joiner modules expose LANG; otherwise LVT_LANG is used."""
    for name in ("mts_joiner", "__main__", "lvt_ffmpeg", "efekt"):
        value = getattr(sys.modules.get(name), "LANG", None)
        if value in ("hu", "en"):
            return value
    value = (os.environ.get("LVT_LANG") or "").strip().lower()
    return value if value in ("hu", "en") else "en"


def _(hu, en):
    return hu if _lang() == "hu" else en

TEMPLATE_HU = '''# VapourSynth-szkript (a vspipe futtatja; az FFmpeg a kimenetét kapja)
# @param strength float 1.0 0 3 Erősség (gamma)
# @param sharp bool 0 0 1 Élesítés be/ki
import vapoursynth as vs

core = vs.core
src = globals().get("src", "")          # a forrásfájl: vspipe -a src=ÚTVONAL
strength = float(globals().get("strength", 1.0))
sharp = int(float(globals().get("sharp", 0)))

if not src:
    raise vs.Error("Hiányzik a forrásfájl (src).")

plug = globals().get("plugin_dll", "")     # kézzel kiválasztott forrás-plugin (DLL) teljes útja
if plug and not (hasattr(core, "lsmas") or hasattr(core, "ffms2")):
    core.std.LoadPlugin(plug)

if hasattr(core, "lsmas"):
    clip = core.lsmas.LWLibavSource(src)
elif hasattr(core, "ffms2"):
    clip = core.ffms2.Source(src)
else:
    raise vs.Error("Nincs forrás-betöltő plugin (lsmas vagy ffms2).")

clip = core.std.Levels(clip, gamma=strength, planes=[0])   # Y-csatorna gamma
if sharp and hasattr(core, "cas"):
    clip = core.cas.CAS(clip)

clip.set_output()
'''

TEMPLATE_EN = '''# VapourSynth script (run by vspipe; FFmpeg receives its output)
# @param strength float 1.0 0 3 Strength (gamma)
# @param sharp bool 0 0 1 Sharpen on/off
import vapoursynth as vs

core = vs.core
src = globals().get("src", "")          # the source file: vspipe -a src=PATH
strength = float(globals().get("strength", 1.0))
sharp = int(float(globals().get("sharp", 0)))

if not src:
    raise vs.Error("Missing source file (src).")

plug = globals().get("plugin_dll", "")     # full path of the manually selected source plugin (DLL)
if plug and not (hasattr(core, "lsmas") or hasattr(core, "ffms2")):
    core.std.LoadPlugin(plug)

if hasattr(core, "lsmas"):
    clip = core.lsmas.LWLibavSource(src)
elif hasattr(core, "ffms2"):
    clip = core.ffms2.Source(src)
else:
    raise vs.Error("No source loader plugin (lsmas or ffms2).")

clip = core.std.Levels(clip, gamma=strength, planes=[0])   # Y-channel gamma
if sharp and hasattr(core, "cas"):
    clip = core.cas.CAS(clip)

clip.set_output()
'''

TEMPLATE = TEMPLATE_EN          # default (English)


def template():
    """The starter script in the active UI language."""
    return TEMPLATE_HU if _lang() == "hu" else TEMPLATE_EN



def find_vspipe(configured=None):
    """A vspipe helye: a beállított útvonal, PATH, vagy a Python-telepítés mappái (Scripts / bin).
    None, ha nincs meg. Nem indít folyamatot."""
    cands = []
    if configured:
        cands.append(configured)
    w = shutil.which("vspipe") or shutil.which("vspipe.exe")
    if w:
        cands.append(w)
    bases = [os.path.dirname(sys.executable), os.path.join(sys.prefix, "bin"),
             os.path.join(os.path.dirname(sys.executable), "Scripts")]
    if os.name == "nt":
        # a wheel telepítése után a vspipe.exe a csomag mappájában van (ugyanúgy, ahogy a vspipe.bat is hívja)
        bases.append(os.path.join(sys.prefix, "Lib", "site-packages", "vapoursynth"))
        bases.append(r"C:\Vapoursynth\lib\site-packages\vapoursynth")
    for base in bases:
        # vspipe.bat szándékosan kimarad: csak a valódi programot használjuk (a .bat a telepítés hiányában hibázik)
        for name in ("vspipe.exe", "vspipe"):
            cands.append(os.path.join(base, name))
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


SOURCE_DLL_HINTS = ("lsmas", "lsmashsource", "ffms2")


def find_source_plugin(plugin_dir):
    """A kézzel megadott plugin-mappában keres forrás-plugint (lsmas / L-SMASH vagy ffms2 DLL).
    Visszaadja a DLL teljes útját, vagy None-t. Az lsmas-t részesíti előnyben. Nem tölti be a DLL-t."""
    if not plugin_dir or not os.path.isdir(plugin_dir):
        return None
    found = []
    for root, _dirs, files in os.walk(plugin_dir):
        for f in files:
            low = f.lower()
            if low.endswith(".dll") and any(h in low for h in SOURCE_DLL_HINTS):
                found.append(os.path.join(root, f))
    if not found:
        return None
    found.sort(key=lambda p: (0 if "lsmash" in os.path.basename(p).lower() or "lsmas" in os.path.basename(p).lower() else 1,
                              len(p)))
    return found[0]


def script_args(src=None, plugin_dir=None, params=None):
    """A vspipe -a értékek: forrásfájl, a kézzel megadott plugin-mappából talált forrás-DLL, és a csúszka-értékek."""
    args = dict(params or {})
    if src:
        args["src"] = src
    dll = find_source_plugin(plugin_dir)
    if dll:
        args["plugin_dll"] = dll
    return args


PROBE_TEMPLATE = '''# Check script: loads the source plugin (if any) and opens the source (if any).
# Runs without errors only if vspipe and the plugin are compatible with each other.
import vapoursynth as vs
core = vs.core
dll = globals().get("plugin_dll", "")
src = globals().get("src", "")
if dll and not (hasattr(core, "lsmas") or hasattr(core, "ffms2")):
    core.std.LoadPlugin(dll)
if src:
    if hasattr(core, "lsmas"):
        clip = core.lsmas.LWLibavSource(src)
    elif hasattr(core, "ffms2"):
        clip = core.ffms2.Source(src)
    else:
        raise vs.Error("No source loader plugin (lsmas or ffms2).")
else:
    clip = core.std.BlankClip(width=16, height=16, length=1, format=vs.YUV420P8)
clip.set_output()
'''


def vspipe_version(vspipe):
    """A vspipe verziósora és API-sora (pl. 'Core R81', 'API R4.3'), vagy (None, None). Bármely VapourSynth-verzióval működik."""
    if not vspipe or not os.path.isfile(vspipe):
        return None, None
    try:
        r = subprocess.run([vspipe, "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           stdin=subprocess.DEVNULL, timeout=30, creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return None, None
    lines = [l.strip() for l in (r.stdout or b"").decode("utf-8", "replace").splitlines()]
    core = next((l for l in lines if l.startswith("Core")), None)
    api = next((l for l in lines if l.startswith("API")), None)
    return core, api


def probe_setup(vspipe, plugin_dll=None, src=None, workdir=None, timeout=120):
    """Valódi próba a megadott vspipe-pal: a plugin betöltése és a forrás megnyitása.
    Visszaad: dict {ok, core, api, message}. A message az első hibaüzenet (vagy 'OK')."""
    import tempfile
    core, api = vspipe_version(vspipe)
    res = dict(ok=False, core=core, api=api, message="")
    if not core:
        res["message"] = _("A vspipe nem indítható: %s", "vspipe cannot be started: %s") % (
            vspipe or _("(nincs megadva)", "(not set)"))
        return res
    own_dir = workdir is None
    d = workdir or tempfile.mkdtemp(prefix="vsprobe_")
    try:
        return _probe_in(vspipe, plugin_dll, src, d, timeout, res)
    finally:
        if own_dir:
            shutil.rmtree(d, ignore_errors=True)


def _probe_in(vspipe, plugin_dll, src, d, timeout, res):
    script = os.path.join(d, "probe.vpy")
    with open(script, "w", encoding="utf-8") as f:
        f.write(PROBE_TEMPLATE)
    args = {}
    if plugin_dll:
        args["plugin_dll"] = plugin_dll
    if src:
        args["src"] = src
    cmd = vspipe_cmd(vspipe, script, args, start=0, end=0)
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                           timeout=timeout, creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        res["message"] = _("Időtúllépés a próbánál.", "Timed out during the check.")
        return res
    err = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()
    if r.returncode == 0:
        res["ok"] = True
        res["message"] = "OK"
    else:
        real = [l for l in err if l.lower().startswith(("error", "failed", "plugin"))
                or "error" in l.lower() or "failed" in l.lower()]
        res["message"] = (real or err or [_("A próba sikertelen (kód %d).", "The check failed (code %d).") % r.returncode])[0]
        res["detail"] = err[-6:]
    return res


def parse_params(script_text):
    """A '# @param' sorokból paraméter-lista: [{name, kind, default, lo, hi, label}]."""
    out, seen = [], set()
    for line in (script_text or "").splitlines():
        m = PARAM_RE.match(line)
        if not m:
            continue
        name, kind, dflt, lo, hi, label = m.groups()
        if name in seen:
            continue
        seen.add(name)
        p = dict(name=name, kind=kind, default=dflt, label=label.strip() or name, lo=None, hi=None)
        if kind in ("int", "float"):
            try:
                p["lo"], p["hi"] = float(lo), float(hi)
                p["default"] = float(dflt) if kind == "float" else int(float(dflt))
            except ValueError:
                continue
        elif kind == "bool":
            p["default"] = dflt in ("1", "true", "True", "yes")
        out.append(p)
    return out


def arg_strings(args):
    """{kulcs: érték} -> ['-a', 'kulcs=érték', ...]. A bool 1/0-ként megy át."""
    out = []
    for k, v in (args or {}).items():
        if isinstance(v, bool):
            v = 1 if v else 0
        out += ["-a", "%s=%s" % (k, v)]
    return out


def vspipe_cmd(vspipe, script, args=None, start=None, end=None):
    """A vspipe parancs: y4m-kimenet a stdout-ra. start / end: kocka-index (0-tól, beleértve)."""
    cmd = [vspipe, "-c", "y4m"]
    if start is not None:
        cmd += ["-s", str(int(start))]
    if end is not None:
        cmd += ["-e", str(int(end))]
    cmd += arg_strings(args)
    cmd += [script, "-"]
    return cmd


def ffmpeg_from_pipe_cmd(ffmpeg, vf_chain, W, H, frames=None):
    """Az FFmpeg a vspipe y4m-kimenetét olvassa (stdin), a szűrőlánccal kicsinyíti és rgb24 nyers képkockát ad."""
    vf = (vf_chain + "," if vf_chain else "") + (
        "scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2:black,setsar=1" % (W, H, W, H))
    cmd = [ffmpeg, "-v", "error", "-nostdin", "-f", "yuv4mpegpipe", "-i", "-", "-vf", vf]
    if frames:
        cmd += ["-frames:v", str(int(frames))]
    cmd += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    return cmd


def run_preview_frame(vspipe, ffmpeg, script, args, index, vf_chain, W, H, timeout=120):
    """Egyetlen előnézeti kocka (rgb24 bájtok). Hibánál RuntimeError a hiba utolsó sorával."""
    vcmd = vspipe_cmd(vspipe, script, args, start=index, end=index)
    fcmd = ffmpeg_from_pipe_cmd(ffmpeg, vf_chain, W, H, frames=1)
    p1 = subprocess.Popen(vcmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                          creationflags=CREATE_NO_WINDOW)
    try:
        p2 = subprocess.Popen(fcmd, stdin=p1.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              creationflags=CREATE_NO_WINDOW)
        p1.stdout.close()           # a csőnek csak az egyik vége maradjon nyitva (SIGPIPE-hez)
        data, err2 = p2.communicate(timeout=timeout)
        p1.wait(timeout=timeout)
        err1 = p1.stderr.read()
        p1.stderr.close()
    except subprocess.TimeoutExpired:
        for proc in (p1, locals().get("p2")):
            if proc is not None:
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:
                    pass
        raise RuntimeError(_("Időtúllépés az előnézetnél.", "Timed out during the preview."))
    if p1.returncode != 0:
        lines = (err1 or b"").decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(lines[-1] if lines else _("vspipe hiba (%d)", "vspipe error (%d)") % p1.returncode)
    if p2.returncode != 0 or len(data) != W * H * 3:
        lines = (err2 or b"").decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(lines[-1] if lines else _("az FFmpeg nem adott képkockát", "FFmpeg returned no frame"))
    return data
