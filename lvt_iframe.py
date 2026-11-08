#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 szabiz <szabiz@yahoo.com>
# Copyright (c) 2026 szabiz <szabiz@yahoo.com>
"""lvt_iframe.py - I-frame (kulcskockás) Editor-export segédek.

Szabályok:
  * Csak kulcskockás vágás. Minden vágási pont (szakasz eleje és vége, a fájl
    végét kivéve) kulcskockára kell essen. Ha nem, a vágás nem indul, és a
    hibaüzenet megmutatja a legközelebbi kulcskockák idejét.
  * A videó másolódik (-c:v copy), nincs újrakódolás.
  * A hang újrakódolódik a forrás kodekjével (felhasználói döntés, 2026-10-15).
    Az időbélyeg a szakasz elejéhez igazodik, így nincs csúszás.
  * Kiterjesztés-eltérésnél nincs csendes átírás: a felhasználó dönt.

Kulcskocka-lista: lvt_smartcut.detect_random_access_times() (H.264 esetén csak
IDR; a nyitott GOP-os I-képek kimaradnak, mert onnan a másolt darab hibás lenne).
A bemeneti -ss kulcskockára pontos, ezért a szakasz eleje K, nem a kért idő.
"""
import math
import os
import shutil
import subprocess
import tempfile

from lvt_smartcut import (SEEK_EPS, SmartCutError, copy_seek, _, _audio_layout, _audio_stream, _choose_audio_codec,
                          _rate_for, _video_stream, av_start_delta)

KEY_TOL = 0.0006


class IFrameCutError(SmartCutError):
    """Az I-frame vágás nem végezhető el a kért pontokon."""


def _fmt(value):
    return "%.6f" % max(0.0, float(value))


def _fmt_time(value):
    if value is None:
        return _("nincs", "none")
    return "%.3f s" % float(value)


def _finite_times(times):
    out = []
    for value in times or ():
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(v):
            out.append(v)
    return sorted(set(out))


def nearest_keyframes(times, t):
    """Return (legkisebb kulcskocka <= t, legkisebb kulcskocka >= t); None ha nincs."""
    prev_t = None
    next_t = None
    for v in _finite_times(times):
        if v <= t + KEY_TOL:
            prev_t = v
        if next_t is None and v >= t - KEY_TOL:
            next_t = v
    return prev_t, next_t


def is_keyframe(times, t):
    prev_t, next_t = nearest_keyframes(times, t)
    return any(x is not None and abs(x - t) <= KEY_TOL for x in (prev_t, next_t))


def snap_to_keyframe(times, t, duration=None):
    """A KEY_TOL-on belül talált kulcskocka pontos idejét adja vissza.

    A -ss kulcskockára pontos, de ha a kért idő hajszállal a kulcskocka ELŐTT van
    (pl. 0.033 a 0.0333667 helyett), az FFmpeg stream copy módban az előző
    kulcskockára ugrana (egy teljes GOP-pal korábbi kezdet). Ezért a vágási
    pontot a tényleges kulcskocka-időre igazítjuk. A fájl vége (duration) nem
    kulcskocka, azt változatlanul hagyjuk.
    """
    t = float(t)
    if duration is not None and abs(t - float(duration)) <= KEY_TOL:
        return t
    kf = _finite_times(times)
    best = None
    for v in kf:
        if abs(v - t) <= KEY_TOL and (best is None or abs(v - t) < abs(best - t)):
            best = v
    return t if best is None else best


def check_cut_points(times, points, duration=None):
    """Ellenőrzi a vágási pontokat. points: [(címke, másodperc), ...].

    A fájl végét (duration) nem kell kulcskockának lennie. Hiba esetén
    IFrameCutError, amely minden hibás pontot felsorol.
    """
    kf = _finite_times(times)
    if not kf:
        raise IFrameCutError(_("Nincs kulcskocka-lista, I-frame vágás nem indítható.",
                               "No keyframe list, I-frame cut cannot start."))
    bad = []
    for label, t in points:
        if duration is not None and abs(float(t) - float(duration)) <= KEY_TOL:
            continue
        if is_keyframe(kf, t):
            continue
        prev_t, next_t = nearest_keyframes(kf, t)
        bad.append(_("  • %s: %s – kulcskockák: előtte %s, utána %s",
                     "  • %s: %s – keyframes: before %s, after %s")
                   % (label, _fmt_time(t), _fmt_time(prev_t), _fmt_time(next_t)))
    if bad:
        raise IFrameCutError(
            _("I-frame módban a vágási pontnak kulcskockára kell esnie.\n",
              "In I-frame mode the cut point must be on a keyframe.\n")
            + "\n".join(bad)
            + _("\nÁllítsd a pontot a fenti kulcskockák egyikére, vagy válts Smart exportra.",
                "\nMove the point to one of the keyframes above, or switch to Smart export.")
        )


def plan_ranges(ranges, times, duration=None):
    """Validált (a, b) listát ad vissza. Ellenőrzi a kezdő és záró pontokat."""
    points = []
    cleaned = []
    for i, (a, b) in enumerate(ranges, 1):
        a, b = float(a), float(b)
        if not (math.isfinite(a) and math.isfinite(b)) or b <= a:
            raise IFrameCutError(_("Érvénytelen szakasz: %d. (%s–%s).",
                                   "Invalid segment: %d. (%s–%s).") % (i, a, b))
        points.append((_("%d. szakasz eleje", "segment %d start") % i, a))
        points.append((_("%d. szakasz vége", "segment %d end") % i, b))
        cleaned.append((a, b))
    if not cleaned:
        raise IFrameCutError(_("Nincs kijelölt szakasz.", "No segment selected."))
    check_cut_points(times, points, duration=duration)
    snapped = []
    for i, (a, b) in enumerate(cleaned, 1):
        a2 = snap_to_keyframe(times, a, duration)
        b2 = snap_to_keyframe(times, b, duration)
        if b2 <= a2:
            raise IFrameCutError(_("Érvénytelen szakasz a kulcskockára igazítás után: %d. (%s–%s).",
                                   "Invalid segment after keyframe snapping: %d. (%s–%s).") % (i, a2, b2))
        snapped.append((a2, b2))
    return snapped


def _family(path):
    ext = os.path.splitext(path)[1].lower()
    return {".ts": "mpegts", ".mts": "mpegts", ".m2ts": "mpegts", ".mkv": "matroska",
            ".mp4": "mp4", ".m4v": "mp4", ".mov": "mp4"}.get(ext)


def resolve_target(src, target, ask_yes_no):
    """Kiterjesztés-kérdés: ha a célfájl konténere eltér a forrásétól, a felhasználó dönt.

    ask_yes_no(szöveg) -> bool. Igen: a kért kiterjesztés marad.
    Nem: ugyanaz a név a forrás kiterjesztésével.
    Csendes átírás nincs. Ha nincs kérdező, hibát dob.
    """
    tfam = _family(target)
    if tfam is None:
        raise IFrameCutError(_("Ismeretlen kimeneti kiterjesztés: %s", "Unknown output extension: %s")
                             % os.path.splitext(target)[1])
    sfam = _family(src)
    if sfam is None or sfam == tfam:
        return target
    src_ext = os.path.splitext(src)[1].lower()
    tgt_ext = os.path.splitext(target)[1].lower()
    if ask_yes_no is None:
        raise IFrameCutError(_("A célkiterjesztés (%s) eltér a forrástól (%s), döntés nélkül nem mentünk.",
                               "Target extension (%s) differs from source (%s), not saving without a decision.")
                             % (tgt_ext, src_ext))
    question = _("A forrás konténere %s (%s), a célfájl kiterjesztése %s.\n\n"
                 "Igen: mentés %s kiterjesztéssel.\n"
                 "Nem: mentés ugyanazzal a névvel, %s kiterjesztéssel.",
                 "The source container is %s (%s), the target extension is %s.\n\n"
                 "Yes: save with the %s extension.\n"
                 "No: save with the same name and the %s extension.") % (sfam, src_ext, tgt_ext, tgt_ext, src_ext)
    if ask_yes_no(question):
        return target
    return os.path.splitext(target)[0] + src_ext


def _out_args(target):
    ext = os.path.splitext(target)[1].lower()
    if ext in (".ts", ".mts", ".m2ts"):
        return ["-f", "mpegts", "-mpegts_flags", "+resend_headers"]
    if ext == ".mkv":
        return ["-f", "matroska"]
    if ext in (".mp4", ".m4v"):
        return ["-f", "mp4", "-movflags", "+faststart"]
    if ext == ".mov":
        return ["-f", "mov", "-movflags", "+faststart"]
    raise IFrameCutError(_("Ismeretlen kimeneti kiterjesztés: %s", "Unknown output extension: %s") % ext)


def _audio_reencode_args(audio):
    """Hang újrakódolása a forrás kodekjével. Csatornaszám és mintavétel megmarad."""
    src_codec = (audio.get("codec_name") or "").lower()
    enc = _choose_audio_codec("copy", src_codec)
    channels = int(audio.get("channels") or 2)
    args = ["-c:a", enc, "-ac", str(channels)]
    if enc not in ("flac", "alac") and not enc.startswith("pcm_"):
        try:
            kbps = int(int(audio.get("bit_rate")) / 1000)
        except (TypeError, ValueError):
            kbps = 384 if channels > 2 else 192
        args += ["-b:a", "%dk" % max(32, kbps)]
    return args


def part_command(ff, src, info, start, end, target, times=None):
    """Egy kulcskockás darab parancsa: -ss a kulcskockán, videó másolva, hang újrakódolva."""
    video = _video_stream(info)
    audio = _audio_stream(info)
    vidx = int(video.get("index", 0))
    # A -t limit on a stream-copy output cuts on packet timing and can keep a few
    # frames past the end keyframe (measured +4 frames). The video is therefore
    # limited by an exact frame count; the audio is trimmed with atrim.
    _rate, fps = _rate_for(video)
    dur = float(end) - float(start)
    nframes = max(1, int(round(dur * fps)))
    c_in, c_out, _mg = copy_seek(float(start), av_start_delta(info, video), times)
    cmd = [ff.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
           "-ss", _fmt(c_in), "-i", src] + (["-ss", _fmt(c_out)] if c_out is not None else []) + [
           "-frames:v", str(nframes),
           "-map", "0:%d" % vidx, "-c:v", "copy"]
    if audio:
        cmd += ["-map", "0:%d" % int(audio.get("index", 1))]
        cmd += _audio_reencode_args(audio)
        pre = ""
        if _choose_audio_codec("copy", (audio.get("codec_name") or "").lower()) == "libopus":
            pre = "aformat=channel_layouts=%s," % _audio_layout(int(audio.get("channels") or 2))
        cmd += ["-af", pre + "aresample=async=1:first_pts=0,atrim=duration=%s" % _fmt(dur)]
    else:
        cmd += ["-an"]
    cmd += ["-sn", "-dn"] + _out_args(target) + [target]
    return cmd


def part_commands(ff, src, info, start, end, target, workdir, times=None):
    """Egy kulcskockás darab parancsai (lista): videó másolása, hang újrakódolása, majd összeállítás.

    Egyetlen parancsban a -frames:v az ffmpeg ÖSSZES kimenetét leállítja, amint a videó kockaszáma meglett.
    B-képkockás videónál a hang ilyenkor még le sem kódolódott, és a kimenet hangsávja üres maradt
    (nulla hangcsomag). Ezért a videó és a hang külön parancs, a végén -c copy összeállítással.
    A -copyts megtartja a két köztes fájl időbélyegét, így a kép-hang viszony nem módosul.
    """
    audio = _audio_stream(info)
    if not audio:
        return [part_command(ff, src, info, start, end, target, times)]
    video = _video_stream(info)
    vidx = int(video.get("index", 0))
    _rate, fps = _rate_for(video)
    dur = float(end) - float(start)
    nframes = max(1, int(round(dur * fps)))
    delta = av_start_delta(info, video)
    seek = _fmt(max(0.0, float(start) + delta))
    c_in, c_out, margin = copy_seek(float(start), delta, times)
    key = "%s_%d" % (os.path.basename(target), abs(hash((target, float(start), float(end)))) % 10 ** 8)
    tv = os.path.join(workdir, key + "_v.mkv")
    ta = os.path.join(workdir, key + "_a.mka")
    head = [ff.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    vcmd = head + ["-ss", _fmt(c_in), "-i", src] + (["-ss", _fmt(c_out)] if c_out is not None else []) + ["-frames:v", str(nframes), "-map", "0:%d" % vidx,
                   "-c:v", "copy", "-an", "-sn", "-dn", "-f", "matroska", tv]
    pre = ""
    if _choose_audio_codec("copy", (audio.get("codec_name") or "").lower()) == "libopus":
        pre = "aformat=channel_layouts=%s," % _audio_layout(int(audio.get("channels") or 2))
    acmd = head + ["-ss", seek, "-i", src, "-map", "0:%d" % int(audio.get("index", 1))]
    acmd += _audio_reencode_args(audio)
    acmd += ["-af", pre + "aresample=async=1:first_pts=0,atrim=duration=%s" % _fmt(dur),
             "-vn", "-sn", "-dn", "-f", "matroska", ta]
    # MPEG-TS kimenetnél a -copyts elrontja az időbélyegeket (a muxer saját 1,4 s-os eltolása miatt),
    # ott a két köztes fájl a saját kezdőidejéhez normalizálódik (a kép-hang eltérés ms-nyi marad).
    ts_out = os.path.splitext(target)[1].lower() in (".ts", ".mts", ".m2ts")
    mcmd = head + ([] if ts_out else (["-copyts", "-itsoffset", "%.4f" % -margin] if margin else ["-copyts"])) + ["-i", tv, "-i", ta, "-map", "0:v:0", "-map", "1:a:0", "-c", "copy",
                   "-strict", "-2"] + _out_args(target) + ["-avoid_negative_ts", "make_zero", target]
    return [vcmd, acmd, mcmd]


def export_iframe(ff, src, info, ranges, times, target, duration=None, ask_yes_no=None, cancel=None):
    """Kulcskockás exportálás. Hibát dob, ha bármelyik pont nem kulcskockára esik.

    Több szakasz esetén minden szakasz külön darab, majd -c copy összefűzés.
    Visszatérés: a végleges célfájl útja (a kiterjesztés-döntés után).
    """
    cleaned = plan_ranges(ranges, times, duration=duration)
    target = resolve_target(src, target, ask_yes_no)
    if os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(target)):
        raise IFrameCutError(_("A kimeneti fájl nem lehet azonos a forrásfájllal.",
                               "The output file cannot be the source file."))
    _out_args(target)  # kiterjesztés-ellenőrzés

    # A kimenet előbb egy ideiglenes néven készül ugyanabban a mappában, és csak
    # siker esetén kerül a végleges helyére. Hiba vagy megszakítás után nem marad
    # félkész fájl, és a már meglévő célfájl sem sérül.
    base, ext = os.path.splitext(target)
    # Absolute path: the concat step runs with cwd=tmpdir, a relative output would land there.
    staging = os.path.abspath("%s.lvt_tmp%s" % (base, ext))
    tmpdir = None
    try:
        if len(cleaned) == 1:
            a, b = cleaned[0]
            tmpdir = tempfile.mkdtemp(prefix="lvt_iframe_")
            for c in part_commands(ff, src, info, a, b, staging, tmpdir, times):
                _run(ff, c, cancel)
        else:
            tmpdir = tempfile.mkdtemp(prefix="lvt_iframe_")
            parts = []
            for i, (a, b) in enumerate(cleaned):
                part = os.path.join(tmpdir, "part_%03d%s" % (i, ext))
                for c in part_commands(ff, src, info, a, b, part, tmpdir, times):
                    _run(ff, c, cancel)
                parts.append((part, b - a))
            listfile = os.path.join(tmpdir, "list.ffconcat")
            with open(listfile, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("ffconcat version 1.0\n")
                for p, dur in parts:
                    # Explicit durations: the audio packets of a part run ~10 ms past
                    # its frame range (encoder padding); without this the next part
                    # would start late by that amount.
                    fh.write("file '%s'\n" % os.path.basename(p))
                    fh.write("duration %.6f\n" % dur)
            cmd = [ff.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                   "-f", "concat", "-safe", "0", "-i", listfile, "-map", "0", "-c", "copy",
                   "-avoid_negative_ts", "make_zero"] + _out_args(staging) + [staging]
            _run(ff, cmd, cancel, cwd=tmpdir)
        os.replace(staging, target)
    except BaseException:
        try:
            if os.path.exists(staging):
                os.remove(staging)
        except OSError:
            pass
        raise
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
    return target


def _kill(proc):
    """A folyamat leállítása; a csővezetékek kiürítése legfeljebb 3 mp-ig tart."""
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.communicate(timeout=3)
    except Exception:
        pass


def _run(ff, cmd, cancel=None, cwd=None):
    """FFmpeg futtatása. A cancel esemény beállításakor a futó folyamatot leállítja."""
    if cancel is not None and cancel.is_set():
        raise SmartCutError("cancelled")
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, cwd=cwd,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as exc:
        raise SmartCutError(_("Nem indítható az FFmpeg: %s", "FFmpeg could not be started: %s") % exc)
    try:
        while True:
            try:
                _out, err = proc.communicate(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                if cancel is not None and cancel.is_set():
                    _kill(proc)
                    raise SmartCutError("cancelled")
    except BaseException:
        if proc.poll() is None:
            _kill(proc)
        raise
    if proc.returncode:
        detail = (err or b"").decode("utf-8", "replace").strip()
        raise SmartCutError(detail or _("Az FFmpeg hibakóddal állt le (%d).",
                                        "FFmpeg exited with an error code (%d).") % proc.returncode)
