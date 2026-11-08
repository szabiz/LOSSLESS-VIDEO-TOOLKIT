# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 szabiz <szabiz@yahoo.com>
# Copyright (c) 2026 szabiz <szabiz@yahoo.com>
"""
vs_render.py - egy VapourSynth-es szakasz renderelése veszteségmentes közbenső fájlba (export az Átalakítás fülre).

Folyamat:  vspipe (a szűrőlánc-szkript, a szakaszra levágva) --y4m--> ffmpeg --> FFV1 (veszteségmentes) + FLAC (hang) .mkv
Az Átalakítás fül ezt a fájlt kapja forrásként, és a szokásos módon konvertálja (kódolás, egyéb FFmpeg-effektek).

A szakaszt a SZKRIPT vágja le (seg_start / seg_end szkript-paraméter, kockaszámban), nem a vspipe -s/-e kapcsolója:
így a képkockaszámot módosító szűrők (pl. interpoláció) mellett is a szakasz pontosan egyszer, hibátlanul dolgozódik fel.
A hangot az ffmpeg ugyanabból az időpontból (-ss) veszi a forrásfájlból.

Nincs benne Tk; a szálkezelést (haladásjelző ablak, megszakítás) az efekt_vs.py végzi. Megszakítás: threading.Event.
"""
import hashlib
import os
import re
import subprocess
import threading
import time

import vs_bridge as vb

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_PROGRESS = re.compile(r"Frame:\s*(\d+)\s*/\s*(\d+)(?:\s*\(\s*([\d.]+)\s*fps\s*\))?")
_DUR = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_FAIL = re.compile(r"(failed|error|exception|traceback)", re.I)
KEEP_DAYS = 3


# ------------------------------------------------------------------ előkészítés
def seg_frames(a, b, fps):
    """A szakasz kockatartománya [kezdet, vég) a forrás képkockaszáma szerint."""
    fps = float(fps or 25.0)
    s = max(0, int(round(float(a) * fps)))
    e = max(s + 1, int(round(float(b) * fps)))
    return s, e


def estimate_bytes(w, h, fps, seconds):
    """Durva felső becslés a veszteségmentes közbenső fájl méretére (az FFV1 jellemzően a nyers méret fele alatt marad)."""
    try:
        return int(float(seconds) * float(fps) * float(w) * float(h) * 1.5 * 0.5)
    except (TypeError, ValueError):
        return 0


def render_dir(base):
    d = os.path.join(base, "render")
    os.makedirs(d, exist_ok=True)
    return d


def render_key(src, a, b, fps, script_path, params, paths):
    """Gyorsítótár-kulcs: ugyanaz a forrás, szakasz, szkript-tartalom, paraméterek és útvonalak -> ugyanaz a fájl."""
    h = hashlib.sha1()
    try:
        st = os.stat(src)
        h.update(("%s|%d|%d" % (os.path.abspath(src), st.st_size, int(st.st_mtime))).encode("utf-8", "replace"))
    except OSError:
        h.update(str(src).encode("utf-8", "replace"))
    try:
        with open(script_path, "rb") as fh:
            h.update(fh.read())
    except OSError:
        h.update(str(script_path).encode("utf-8", "replace"))
    h.update(("|%.4f|%.4f|%.5f|%r|%r" % (a, b, fps, sorted((params or {}).items()), tuple(paths))).encode("utf-8", "replace"))
    return h.hexdigest()[:16]


def cleanup(directory, days=KEEP_DAYS):
    """A régi közbenső fájlok (és a félbemaradt .part fájlok) törlése."""
    n = 0
    try:
        for name in os.listdir(directory):
            if not name.startswith("vs_") or not (name.endswith(".mkv") or name.endswith(".part")):
                continue
            p = os.path.join(directory, name)
            if time.time() - os.path.getmtime(p) > days * 86400:
                os.remove(p)
                n += 1
    except OSError:
        pass
    return n


def build_cmds(vsp, ffmpeg, script, args, src, a, dur, part_path, frames=None):
    """(vspipe-parancs, ffmpeg-parancs). A szkript-paraméterek (seg_start, seg_end, plugdir ...) az args szótárban.
    frames: (első, utolsó) kocka (beleértve) a vspipe -s/-e kapcsolóihoz - a kézzel írt .vpy fájloknál, amelyek nem
    ismerik a seg_start / seg_end paramétert; a program által generált szkriptnél None."""
    vcmd = vb.vspipe_cmd(vsp, script, args, start=frames[0] if frames else None, end=frames[1] if frames else None)
    vcmd = vcmd[:3] + ["-p"] + vcmd[3:]                 # [vspipe, -c, y4m, -p, -a ..., szkript, -]: haladásjelzés a stderr-re
    fcmd = [ffmpeg, "-hide_banner", "-v", "error", "-nostdin", "-y",
            "-f", "yuv4mpegpipe", "-i", "-",
            "-ss", "%.3f" % max(0.0, a), "-t", "%.3f" % max(0.1, dur), "-i", src,
            "-map", "0:v:0", "-map", "1:a?", "-sn",
            "-c:v", "ffv1", "-level", "3", "-g", "1",
            "-c:a", "flac", "-compression_level", "0",
            "-f", "matroska", part_path]
    return vcmd, fcmd


def probe_duration(ffmpeg, path):
    """A fájl hossza másodpercben az ffmpeg kimenetéből (nincs szükség ffprobe-ra), vagy None."""
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-i", path], stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, creationflags=NOWIN)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = _DUR.search((r.stderr or b"").decode("utf-8", "replace"))
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None


# ------------------------------------------------------------------ futtatás
def _reader(pipe, on_line, store):
    """A cső tartalmát \\r és \\n mentén sorokra bontja (a vspipe a haladást \\r-rel írja)."""
    buf = b""
    try:
        while True:
            chunk = pipe.read1(4096) if hasattr(pipe, "read1") else pipe.read(1)
            if not chunk:
                break
            buf += chunk
            parts = re.split(rb"[\r\n]+", buf)
            buf = parts.pop()
            for raw in parts:
                line = raw.decode("utf-8", "replace").strip()
                if line:
                    if len(store) < 300:
                        store.append(line)
                    if on_line:
                        on_line(line)
        tail = buf.decode("utf-8", "replace").strip()
        if tail:
            store.append(tail)
            if on_line:
                on_line(tail)
    except (OSError, ValueError):
        pass


def _kill(*procs):
    for p in procs:
        if p is not None:
            try:
                if p.poll() is None:
                    p.kill()
                p.wait(timeout=10)
            except Exception:       # noqa
                pass


def run_render(vcmd, fcmd, part_path, final_path, progress=None, cancel=None, log=None):
    """A csővezeték futtatása. Visszatér: dict(ok, cancelled, error, skipped, frames, seconds).
    progress(kocka, összes, fps) a haladáshoz; cancel: threading.Event; log(szöveg): naplózás."""
    res = dict(ok=False, cancelled=False, error="", skipped=[], frames=0, seconds=0.0)
    verrs, ferrs = [], []
    t0 = time.time()
    state = {"frame": 0}
    vp = fp = None

    def on_vline(line):
        m = _PROGRESS.search(line)
        if m:
            state["frame"] = int(m.group(1))
            if progress:
                progress(int(m.group(1)), int(m.group(2)), float(m.group(3)) if m.group(3) else 0.0)
        elif line.startswith(("KIHAGYVA", "PLUGIN-HIBA")):
            res["skipped"].append(line.split(": ", 1)[-1][:200])

    try:
        if os.path.exists(part_path):
            os.remove(part_path)
        vp = subprocess.Popen(vcmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, creationflags=NOWIN)
        fp = subprocess.Popen(fcmd, stdin=vp.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=NOWIN)
        vp.stdout.close()                       # a csőnek csak az ffmpeg-oldala maradjon nyitva
        ths = [threading.Thread(target=_reader, args=(vp.stderr, on_vline, verrs), daemon=True),
               threading.Thread(target=_reader, args=(fp.stderr, None, ferrs), daemon=True)]
        for t in ths:
            t.start()
        while fp.poll() is None:
            if cancel is not None and cancel.is_set():
                res["cancelled"] = True
                break
            time.sleep(0.15)
        if res["cancelled"]:
            _kill(fp, vp)
        else:
            try:
                vp.wait(timeout=30)
            except subprocess.TimeoutExpired:
                _kill(vp)
        for t in ths:
            t.join(timeout=3)
    except OSError as e:
        res["error"] = str(e)
    finally:
        _kill(fp, vp)
    res["frames"] = state["frame"]
    res["seconds"] = time.time() - t0
    if log:
        log("RENDER vége: rc vspipe=%s ffmpeg=%s kockák=%d %.1f mp%s%s" % (
            vp.returncode if vp else "-", fp.returncode if fp else "-", state["frame"], res["seconds"],
            ("\n    vspipe: " + " | ".join(verrs[-4:])) if verrs else "",
            ("\n    ffmpeg: " + " | ".join(ferrs[-4:])) if ferrs else ""))
    if res["cancelled"]:
        _discard(part_path)
        return res
    good = (not res["error"] and fp is not None and fp.returncode == 0 and os.path.isfile(part_path)
            and os.path.getsize(part_path) > 1000)
    if good and vp is not None and vp.returncode not in (0, None):
        good = False
    if not good:
        errs = [l for l in verrs if _FAIL.search(l) and not _PROGRESS.search(l)] or \
               [l for l in ferrs if _FAIL.search(l)] or verrs[-1:] or ferrs[-1:]
        res["error"] = res["error"] or (errs[-1] if errs else "ismeretlen hiba (vspipe rc=%s, ffmpeg rc=%s)" % (
            vp.returncode if vp else "-", fp.returncode if fp else "-"))
        _discard(part_path)
        return res
    os.replace(part_path, final_path)
    res["ok"] = True
    return res


def _discard(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


# ------------------------------------------------------------------ a kész kép adatai (méret, kocka/mp) az Átalakítás fülhöz
_VSTREAM = re.compile(r"Stream #\d+:\d+[^\n]*?: Video:[^\n]*")
_SIZE = re.compile(r"[\s,](\d{2,5})x(\d{2,5})(?=[\s,\[]|$)")
_SAR = re.compile(r"SAR\s+(\d+):(\d+)")
_FPS = re.compile(r"([\d.]+)\s+fps")
_SHOWINFO = re.compile(r"showinfo[^\n]*?\bs:(\d+)x(\d+)")


def probe_video(ffmpeg, path):
    """A fájl első videó-folyamának adatai az ffmpeg kimenetéből: dict(w, h, sar (float), fps (float)) vagy None."""
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-i", path], stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, creationflags=NOWIN)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = _VSTREAM.search((r.stderr or b"").decode("utf-8", "replace"))
    if not m:
        return None
    line = m.group(0)
    sz = _SIZE.search(line)
    if not sz:
        return None
    sar = _SAR.search(line)
    fps = _FPS.search(line)
    sarf = (int(sar.group(1)) / float(sar.group(2))) if sar and int(sar.group(2)) else 1.0
    return dict(w=int(sz.group(1)), h=int(sz.group(2)), sar=sarf or 1.0, fps=float(fps.group(1)) if fps else None)


def probe_output_size(ffmpeg, path, ss, chain):
    """A szűrőlánc UTÁNI képméret (w, h): egyetlen kockát futtat át a láncon (showinfo). None, ha nem sikerül."""
    vf = (chain + "," if chain else "") + "showinfo"
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-ss", "%.3f" % max(0.0, ss), "-i", path, "-vf", vf,
           "-frames:v", "1", "-an", "-sn", "-f", "null", "-"]
    try:
        r = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
                           creationflags=NOWIN)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = _SHOWINFO.search((r.stderr or b"").decode("utf-8", "replace"))
    return (int(m.group(1)), int(m.group(2))) if m else None


_NTSC = ((24000, 1001), (30000, 1001), (60000, 1001), (120000, 1001))


def fps_text(value):
    """Kocka/mp szöveg az Átalakítás fül „fps” mezőjébe: egész szám, vagy tört az NTSC-értékeknél (23.976 -> 24000/1001).
    value: szám vagy szöveg ('25', '30000/1001', '29.97'); None / hibás -> ''."""
    try:
        v = str(value).strip().replace(",", ".")
        if "/" in v:
            a, b = v.split("/", 1)
            x = float(a) / float(b)
            if x <= 0:
                return ""
            return v if v.replace("/", "").isdigit() else ""
        x = float(v)
    except (ValueError, ZeroDivisionError):
        return ""
    if x <= 0:
        return ""
    for n, d in _NTSC:
        if abs(x - n / float(d)) < 0.02:
            return "%d/%d" % (n, d)
    return str(int(round(x))) if abs(x - round(x)) < 0.01 else ("%.3f" % x).rstrip("0").rstrip(".")
