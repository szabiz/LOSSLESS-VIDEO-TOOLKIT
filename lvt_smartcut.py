#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 szabiz <szabiz@yahoo.com>
# Copyright (c) 2026 szabiz <szabiz@yahoo.com>
"""Experimental keyframe-aware Smart Cut job builder for the Editor and Cutter.

The Smart path preserves the source container family, video codec, and audio
codec. It copies safe random-access-to-random-access video middles, re-encodes
unaligned edges with the same codec, joins Matroska intermediates, and encodes
one continuous audio track per output in the source audio codec. Initial codec
support: 8/10-bit 4:2:0 H.264/AVC, HEVC/H.265, VP9, and AV1 in MPEG-TS/MTS/M2TS,
Matroska/MKV, or MP4/M4V/MOV. It is experimental and does not promise
bit-identical codec headers at joins; test outputs before deleting source media.
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from fractions import Fraction


class SmartCutError(Exception):
    """A smart-cut request cannot be safely built for this input/settings."""


def _lang():
    """Active UI language ("en" default). The host program owns the setting:
    mts_joiner / the running main script / lvt_ffmpeg expose a LANG variable;
    otherwise the LVT_LANG environment variable is used."""
    for name in ("mts_joiner", "__main__", "lvt_ffmpeg"):
        value = getattr(sys.modules.get(name), "LANG", None)
        if value in ("hu", "en"):
            return value
    value = (os.environ.get("LVT_LANG") or "").strip().lower()
    return value if value in ("hu", "en") else "en"


def _(hu, en):
    """Return the Hungarian or English text; English is the default."""
    return hu if _lang() == "hu" else en


class CommandFFmpeg:
    """Small FFmpeg/ffprobe adapter for the Cutter's opt-in Smart Cut path.

    Resolve binaries from PATH, or from LVT_FFMPEG / LVT_FFPROBE environment
    variables. The Editor can continue using its own configured FFmpeg object.
    """
    def __init__(self, ffmpeg, ffprobe):
        self.ffmpeg = shutil.which(ffmpeg) or os.path.abspath(ffmpeg)
        self.ffprobe = shutil.which(ffprobe) or os.path.abspath(ffprobe)

    @classmethod
    def from_environment(cls):
        ffmpeg = os.environ.get("LVT_FFMPEG") or shutil.which("ffmpeg")
        ffprobe = os.environ.get("LVT_FFPROBE") or shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            raise SmartCutError(_(
                "Smart Cut-hoz az ffmpeg és ffprobe programnak elérhetőnek kell lennie a PATH-ban, "
                "vagy be kell állítani a LVT_FFMPEG és LVT_FFPROBE környezeti változót. "
                "A veszteségmentes vágás ettől függetlenül használható.",
                "Smart Cut needs ffmpeg and ffprobe to be available on the PATH, "
                "or the LVT_FFMPEG and LVT_FFPROBE environment variables to be set. "
                "Lossless cutting can be used regardless."
            ))
        return cls(ffmpeg, ffprobe)

    @staticmethod
    def _capture(cmd, timeout=60):
        try:
            p = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, timeout=timeout,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SmartCutError(_("Nem sikerült futtatni az FFmpeg eszközt: %s",
          "Could not run the FFmpeg tool: %s") % exc)
        if p.returncode:
            detail = (p.stderr or b"").decode("utf-8", "replace").strip()
            raise SmartCutError(detail or _("Az FFmpeg eszköz hibakóddal állt le (%d).",
          "The FFmpeg tool exited with an error code (%d).") % p.returncode)
        return p.stdout

    def probe(self, src):
        raw = self._capture([self.ffprobe, "-v", "error", "-show_streams", "-show_format",
                             "-of", "json", src], timeout=120)
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except (ValueError, TypeError) as exc:
            raise SmartCutError(_("Az ffprobe hibás JSON-adatot adott: %s",
          "ffprobe returned invalid JSON data: %s") % exc)

    def encoders(self):
        raw = self._capture([self.ffmpeg, "-hide_banner", "-encoders"], timeout=60)
        result = {"V": [], "A": [], "S": []}
        for line in raw.decode("utf-8", "replace").splitlines():
            fields = line.split()
            if len(fields) >= 2 and re.fullmatch(r"[A-Z.]{6}", fields[0]):
                flags, name = fields[0], fields[1]
                kind = flags[0]
                if kind in result:
                    result[kind].append((name, ""))
        return result

    def _out_opts(self, opts, target, vcodec):
        container = (opts.get("container") or "").strip().lower()
        muxer = {"mpegts": "mpegts", "matroska": "matroska", "mp4": "mp4",
                 "mov": "mov", "ipod": "ipod"}.get(container)
        out = ["-f", muxer] if muxer else []
        if container in ("mp4", "mov", "ipod"):
            out += ["-movflags", "+faststart"]
        return out

    def run_convert(self, cmd, duration=0.0, cancel=None):
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            raise SmartCutError(_("Nem indítható az FFmpeg: %s",
          "FFmpeg could not be started: %s") % exc)
        tail = bytearray()

        def drain_stderr():
            if proc.stderr is None:
                return
            for line in iter(proc.stderr.readline, b""):
                tail.extend(line)
                if len(tail) > 24000:
                    del tail[:len(tail) - 24000]

        reader = threading.Thread(target=drain_stderr, daemon=True)
        reader.start()
        cancelled = False
        while proc.poll() is None:
            if cancel is not None and cancel.is_set():
                cancelled = True
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                break
            time.sleep(0.1)
        rc = proc.wait()
        reader.join(timeout=3)
        if cancelled:
            raise SmartCutError("cancelled")
        if rc:
            detail = bytes(tail).decode("utf-8", "replace").strip()
            raise SmartCutError(detail or _("Az FFmpeg hibakóddal állt le (%d).",
          "FFmpeg exited with an error code (%d).") % rc)


def _fraction(value):
    value = str(value or "").strip()
    if not value or value in ("0/0", "N/A"):
        return None
    try:
        f = Fraction(value)
        return f if f > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def _fmt(value):
    return "%.6f" % max(0.0, float(value))


def _rate_for(stream):
    avg = _fraction(stream.get("avg_frame_rate"))
    nominal = _fraction(stream.get("r_frame_rate"))
    rate = avg or nominal
    if not rate:
        raise SmartCutError(_("A képkockasebesség nem állapítható meg ffprobe-bal.",
          "The frame rate could not be determined with ffprobe."))
    fps = float(rate)
    if not math.isfinite(fps) or fps <= 0 or fps > 240:
        raise SmartCutError(_("A képkockasebesség nem alkalmas a Smart cut módhoz.",
          "The frame rate is not suitable for Smart cut."))
    if avg and nominal:
        ratio = float(nominal / avg)
        interlaced = (stream.get("field_order") or "").lower() in ("tt", "tb", "bb", "bt")
        # FFprobe can report field rate as r_frame_rate for interlaced AVCHD.
        is_field_rate = interlaced and abs(ratio - 2.0) < 0.02
        if abs(ratio - 1.0) > 0.01 and not is_field_rate:
            raise SmartCutError(_("Változó vagy nem egyértelmű képkockasebesség: Smart cut csak állandó fps-sel biztonságos.",
          "Variable or ambiguous frame rate: Smart cut is only safe with a constant fps."))
    return str(rate), fps


def _edge_opts_with_select(opts, skip_frames):
    """Edge re-encode options: frame-count select, no forced output rate.

    A forced output "-r" makes FFmpeg's fps filter duplicate frames around the
    start point (measured dup=72); frames are passed through instead, and the
    frame count is fixed by -frames:v.
    """
    out = []
    existing = None
    i = 0
    while i < len(opts):
        tok = opts[i]
        if tok == "-vf" and i + 1 < len(opts):
            existing = opts[i + 1]
            i += 2
            continue
        if tok == "-r" and i + 1 < len(opts):
            i += 2
            continue
        out.append(tok)
        i += 1
    chain = "select=gte(n\\,%d),setpts=N/(FRAME_RATE*TB)" % int(skip_frames)
    if existing:
        chain += "," + existing
    return out + ["-fps_mode", "passthrough", "-vf", chain]


def _keyframe_at_or_before(times, t, tol=0.0006):
    """Largest known random-access time <= t (small tolerance); 0.0 if none."""
    best = 0.0
    for value in times or ():
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(v) and v <= t + tol and v > best:
            best = v
    return best


def split_range(start, end, idr_times, fps):
    """Return (begin, end, mode) fragments, where mode is 'encode' or 'copy'.

    The copied interval is bounded by codec-safe random-access points and is
    half-open [begin, end). If there is no useful keyframe-bounded middle, the
    entire requested range is re-encoded.
    """
    start, end, fps = float(start), float(end), float(fps)
    if not math.isfinite(start) or not math.isfinite(end) or end <= start:
        raise SmartCutError(_("Érvénytelen vágási szakasz.",
          "Invalid cut segment."))
    if not math.isfinite(fps) or fps <= 0:
        raise SmartCutError(_("Érvénytelen képkockasebesség.",
          "Invalid frame rate."))

    frame = 1.0 / fps
    # The IDR analyser reports millisecond timestamps. Allow half a millisecond
    # of display rounding only; never turn a merely-nearby frame into an IDR cut.
    tol = 0.0006
    ids = []
    for value in idr_times or ():
        try:
            t = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(t) and start - tol <= t <= end + tol:
            ids.append(t)
    ids = sorted(set(ids))

    # If the requested edge is already on an IDR, it can be copied from there.
    near_start = [t for t in ids if abs(t - start) <= tol]
    if near_start:
        copy_start = start
    else:
        copy_start = next((t for t in ids if t > start + tol and t < end - tol), None)

    if copy_start is None:
        return [(start, end, "encode")]

    near_end = [t for t in ids if abs(t - end) <= tol and t > copy_start + frame * 0.5]
    if near_end:
        copy_end = end
    else:
        candidates = [t for t in ids if t > copy_start + frame * 0.5 and t < end - tol]
        copy_end = candidates[-1] if candidates else None

    if copy_end is None or copy_end - copy_start < frame * 0.9:
        return [(start, end, "encode")]

    result = []
    if copy_start - start > tol:
        result.append((start, copy_start, "encode"))
    result.append((copy_start, copy_end, "copy"))
    if end - copy_end > tol:
        result.append((copy_end, end, "encode"))
    return result or [(start, end, "encode")]


def _video_stream(info):
    streams = [s for s in info.get("streams", [])
               if s.get("codec_type") == "video"
               and not (s.get("disposition") or {}).get("attached_pic")]
    if not streams:
        raise SmartCutError(_("A fájlban nincs videófolyam.",
          "The file contains no video stream."))
    # The existing IDR analyser uses v:0. Match it rather than silently using
    # a different (e.g. larger secondary) video stream.
    return streams[0]


def _audio_stream(info):
    streams = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    if not streams:
        return None
    return max(streams, key=lambda s: int(s.get("channels") or 0))


def _validate_source_container(info, src):
    """Fail closed to the source container families supported by this path."""
    names = set(((info.get("format") or {}).get("format_name") or "").split(","))
    ext = os.path.splitext(src)[1].lower()
    if ext in (".ts", ".mts", ".m2ts") and "mpegts" in names:
        return
    if ext == ".mkv" and "matroska" in names:
        return
    if ext in (".mp4", ".m4v", ".mov") and ("mov" in names or "mp4" in names):
        return
    raise SmartCutError(_("A Smart Cut bemeneti konténere MPEG-TS/MTS/M2TS, MKV vagy MP4/M4V/MOV legyen.",
          "The Smart Cut input container must be MPEG-TS/MTS/M2TS, MKV or MP4/M4V/MOV."))


def _source_container_setting(info, src):
    """Return the muxer corresponding to the loaded source, not a conversion choice."""
    _validate_source_container(info, src)
    ext = os.path.splitext(src)[1].lower()
    if ext in (".ts", ".mts", ".m2ts"):
        return "mpegts"
    if ext == ".mkv":
        return "matroska"
    if ext == ".mov":
        return "mov"
    return "mp4"


def _validate_target_container(opts, target):
    cont = (opts.get("container") or "").strip().lower()
    ext = os.path.splitext(target)[1].lower()
    ext_family = None
    if ext in (".ts", ".mts", ".m2ts"):
        ext_family = "mpegts"
    elif ext == ".mkv":
        ext_family = "matroska"
    elif ext in (".mp4", ".m4v", ".mov"):
        ext_family = "iso-bmff"
    if ext_family is None:
        raise SmartCutError(_("Smart cut kimenethez .ts/.m2ts, .mkv, .mp4/.m4v vagy .mov kiterjesztés kell.",
          "Smart cut output needs a .ts/.m2ts, .mkv, .mp4/.m4v or .mov extension."))
    if not cont:
        return
    cont_family = {
        "mpegts": "mpegts", "matroska": "matroska",
        "mp4": "iso-bmff", "mov": "iso-bmff", "ipod": "iso-bmff",
    }.get(cont)
    if cont_family is None:
        raise SmartCutError(_("Smart cut kimenethez MPEG-TS, Matroska/MKV vagy MP4/MOV konténer kell.",
          "Smart cut output needs an MPEG-TS, Matroska/MKV or MP4/MOV container."))
    if cont_family != ext_family:
        raise SmartCutError(_("A Smart cut kimeneti konténerbeállítás nem egyezik a fájlkiterjesztéssel.",
          "The Smart cut output container setting does not match the file extension."))


def detect_idr_times(ff, src, info, cancel=None):
    """Return true H.264 IDR PTS in the editor's zero-based time axis using FFmpeg's filter_units bsf."""
    video = _video_stream(info)
    if (video.get("codec_name") or "").lower() != "h264":
        raise SmartCutError(_("Az automatikus IDR-keresés ebben a változatban H.264/AVC-re készült.",
          "Automatic IDR detection in this version is built for H.264/AVC."))
    offset = 0.0
    for value in (video.get("start_time"), (info.get("format") or {}).get("start_time")):
        try:
            offset = float(value)
            break
        except (TypeError, ValueError):
            continue
    cmd = [ff.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-copyts", "-i", src,
           "-map", "0:%d" % int(video.get("index", 0)), "-c", "copy", "-bsf:v",
           "filter_units=pass_types=5", "-f", "framecrc", "-"]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as exc:
        raise SmartCutError(_("Az FFmpeg nem indítható az IDR-k kereséséhez: %s",
          "FFmpeg could not be started to find IDR frames: %s") % exc)
    times = []
    tb = 1.0 / 90000.0
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            if cancel is not None and cancel.is_set():
                proc.terminate()
                raise SmartCutError("cancelled")
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("#tb"):
                m = re.search(r"(\d+)\s*/\s*(\d+)\s*$", line)
                if m and int(m.group(2)):
                    tb = int(m.group(1)) / float(int(m.group(2)))
                continue
            if not line or line.startswith("#"):
                continue
            fields = [x.strip() for x in line.split(",")]
            if len(fields) < 3:
                continue
            try:
                t = int(fields[2]) * tb - offset
            except ValueError:
                continue
            if t > -0.001:
                times.append(max(0.0, t))
        rc = proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    if rc != 0:
        raise SmartCutError(_("Az FFmpeg nem tudta felolvasni a H.264 IDR-listát ehhez a fájlhoz.",
          "FFmpeg could not read the H.264 IDR list for this file."))
    return sorted(set(round(t, 3) for t in times))


def detect_random_access_times(ff, src, info, cancel=None):
    """Find safe-ish copy boundaries for H.264, HEVC, VP9, and AV1 sources.

    H.264 uses true IDR NAL units. HEVC uses BLA/IDR NAL units and deliberately
    excludes CRA frames (which may have leading pictures). VP9/AV1 use the
    decoder's key_frame flag. For non-H.264 inputs, timestamps are gathered by
    streaming ffprobe output instead of loading every frame into memory.
    """
    video = _video_stream(info)
    codec = (video.get("codec_name") or "").lower()
    if codec == "h264":
        return detect_idr_times(ff, src, info, cancel=cancel)
    if codec not in ("hevc", "vp9", "av1"):
        raise SmartCutError(_("A Smart Cut jelenleg H.264, HEVC/H.265, VP9 és AV1 videót támogat.",
          "Smart Cut currently supports H.264, HEVC/H.265, VP9 and AV1 video."))

    offset = 0.0
    for value in (video.get("start_time"), (info.get("format") or {}).get("start_time")):
        try:
            offset = float(value)
            break
        except (TypeError, ValueError):
            continue

    if codec == "hevc":
        # BLA/IDR access units are safe restart points; do not cut on CRA because
        # its leading pictures can precede the random-access timestamp.
        cmd = [ff.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-copyts", "-i", src,
               "-map", "0:%d" % int(video.get("index", 0)), "-c", "copy", "-bsf:v",
               "filter_units=pass_types=16-20", "-f", "framecrc", "-"]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    stdin=subprocess.DEVNULL,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            raise SmartCutError(_("Az FFmpeg nem indítható a HEVC IDR-ek kereséséhez: %s",
          "FFmpeg could not be started to find HEVC IDR frames: %s") % exc)
        times = []
        tb = 1.0 / 90000.0
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                if cancel is not None and cancel.is_set():
                    proc.terminate()
                    raise SmartCutError("cancelled")
                line = raw.decode("utf-8", "replace").strip()
                if line.startswith("#tb"):
                    match = re.search(r"(\d+)\s*/\s*(\d+)\s*$", line)
                    if match and int(match.group(2)):
                        tb = int(match.group(1)) / float(int(match.group(2)))
                    continue
                if not line or line.startswith("#"):
                    continue
                fields = [field.strip() for field in line.split(",")]
                if len(fields) < 3:
                    continue
                try:
                    stamp = int(fields[2]) * tb - offset
                except ValueError:
                    continue
                if stamp > -0.001:
                    times.append(max(0.0, stamp))
            rc = proc.wait()
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        if rc != 0:
            raise SmartCutError(_("Az FFmpeg nem tudta felolvasni a HEVC BLA/IDR-listát ehhez a fájlhoz.",
          "FFmpeg could not read the HEVC BLA/IDR list for this file."))
        return sorted(set(round(t, 3) for t in times))

    ffprobe = getattr(ff, "ffprobe", None)
    if not ffprobe:
        raise SmartCutError(_("A VP9/AV1 kulcsképkockák kereséséhez ffprobe szükséges.",
          "ffprobe is required to find VP9/AV1 keyframes."))
    cmd = [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_frames",
           "-show_entries", "frame=key_frame,best_effort_timestamp_time", "-of", "csv=p=0", src]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as exc:
        raise SmartCutError(_("Az ffprobe nem indítható a kulcsképkockák kereséséhez: %s",
          "ffprobe could not be started to find keyframes: %s") % exc)
    times = []
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            if cancel is not None and cancel.is_set():
                proc.terminate()
                raise SmartCutError("cancelled")
            fields = [field.strip() for field in raw.decode("utf-8", "replace").strip().split(",")]
            if len(fields) < 2 or fields[0] != "1":
                continue
            try:
                stamp = float(fields[1]) - offset
            except (TypeError, ValueError):
                continue
            if math.isfinite(stamp) and stamp > -0.001:
                times.append(max(0.0, stamp))
        rc = proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    if rc != 0:
        raise SmartCutError(_("Az ffprobe nem tudta felolvasni a %s kulcsképkocka-listát ehhez a fájlhoz.",
          "ffprobe could not read the %s keyframe list for this file.") % codec.upper())
    return sorted(set(round(t, 3) for t in times))


def _profile_name(stream):
    p = (stream.get("profile") or "").strip().lower()
    mapping = {
        "constrained baseline": "baseline", "baseline": "baseline",
        "main": "main", "high": "high", "high 10": "high10",
        "high 4:2:2": "high422", "high 4:4:4 predictive": "high444",
    }
    return mapping.get(p, "")


def _level_name(stream):
    try:
        n = int(stream.get("level"))
    except (TypeError, ValueError):
        return ""
    if n == 9:
        return "1b"
    if 10 <= n <= 62:
        return "%d.%d" % (n // 10, n % 10)
    return ""


def _int_or_none(value):
    try:
        n = int(value)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _video_encoder_options(stream, rate, available_encoders=None):
    """Choose an encoder matching the source codec; never silently change codec."""
    codec = (stream.get("codec_name") or "").lower()
    pix = (stream.get("pix_fmt") or "").lower()
    if pix in ("yuv420p", "yuvj420p"):
        output_pix_fmt, bit_depth = "yuv420p", 8
    elif pix == "yuv420p10le":
        output_pix_fmt, bit_depth = "yuv420p10le", 10
    else:
        raise SmartCutError(
            _("A Smart Cut jelenleg 8/10 bites 4:2:0 képpontformátumot támogat (forrás pix_fmt: %s).",
          "Smart Cut currently supports 8/10-bit 4:2:0 pixel formats (source pix_fmt: %s).") % (pix or "?")
        )
    candidates = {
        "h264": ("libx264",),
        "hevc": ("libx265",),
        "vp9": ("libvpx-vp9",),
        "av1": ("libsvtav1", "libaom-av1"),
    }.get(codec)
    if not candidates:
        raise SmartCutError(_("A Smart Cut jelenleg H.264, HEVC/H.265, VP9 és AV1 videót támogat.",
          "Smart Cut currently supports H.264, HEVC/H.265, VP9 and AV1 video."))
    available = set(available_encoders or ())
    encoder = next((name for name in candidates if not available or name in available), None)
    if encoder is None:
        raise SmartCutError(_("A megadott FFmpeg buildben nincs a %s szélek újrakódolásához szükséges encoder (%s).",
          "The given FFmpeg build has no encoder needed to re-encode %s edges (%s).") %
                            (codec.upper(), ", ".join(candidates)))

    # yuvj420p is deprecated; encode as yuv420p while retaining range metadata.
    out = ["-c:v", encoder, "-pix_fmt", output_pix_fmt, "-r", rate]
    # Match the ~0.5 s random-access cadence common in camera H.264. Long GOPs
    # made MTS Smart exports painfully slow to seek in players such as MPC-HC.
    keyint = max(1, min(600, int(round(float(Fraction(rate)) * 0.5))))
    br = _int_or_none(stream.get("bit_rate"))

    if codec == "h264":
        out += ["-preset", "medium"]
        profile = _profile_name(stream)
        if profile:
            out += ["-profile:v", profile]
        level = _level_name(stream)
        if level:
            out += ["-level:v", level]
        try:
            bframes = max(0, min(16, int(stream.get("has_b_frames") or 0)))
        except (TypeError, ValueError):
            bframes = 0
        if profile == "baseline":
            bframes = 0
        out += ["-bf", str(bframes)]
        out += ["-b:v", str(br)] if br else ["-crf", "18"]
        out += ["-g", str(keyint), "-keyint_min", "1"]
    elif codec == "hevc":
        field_order = (stream.get("field_order") or "").lower()
        if field_order in ("tt", "tb", "bb", "bt"):
            raise SmartCutError(_("A Smart Cut HEVC-élszakaszok kódolása ebben a változatban csak progresszív videón támogatott.",
          "Smart Cut HEVC edge encoding is only supported on progressive video in this version."))
        out += ["-preset", "medium"]
        out += ["-profile:v", "main10" if bit_depth == 10 else "main"]
        out += ["-b:v", str(br)] if br else ["-crf", "22"]
        out += ["-g", str(keyint), "-keyint_min", "1", "-x265-params", "open-gop=0:scenecut=0"]
    elif codec == "vp9":
        field_order = (stream.get("field_order") or "").lower()
        if field_order in ("tt", "tb", "bb", "bt"):
            raise SmartCutError(_("A Smart Cut VP9-élszakaszok kódolása ebben a változatban csak progresszív videón támogatott.",
          "Smart Cut VP9 edge encoding is only supported on progressive video in this version."))
        out += ["-deadline", "good", "-cpu-used", "2", "-row-mt", "1", "-profile:v", "2" if bit_depth == 10 else "0",
                "-crf", "31", "-b:v", "0", "-g", str(keyint)]
    else:  # AV1
        field_order = (stream.get("field_order") or "").lower()
        if field_order in ("tt", "tb", "bb", "bt"):
            raise SmartCutError(_("A Smart Cut AV1-élszakaszok kódolása ebben a változatban csak progresszív videón támogatott.",
          "Smart Cut AV1 edge encoding is only supported on progressive video in this version."))
        if encoder == "libsvtav1":
            out += ["-preset", "8", "-crf", "30", "-b:v", "0", "-g", str(keyint)]
        else:
            out += ["-cpu-used", "6", "-crf", "30", "-b:v", "0", "-g", str(keyint)]

    sar = (stream.get("sample_aspect_ratio") or "1:1").replace(":", "/")
    if re.fullmatch(r"\d+/\d+", sar) and not sar.startswith("0/"):
        out += ["-vf", "setsar=%s" % sar]
    for key, opt in (("color_range", "-color_range"), ("color_primaries", "-color_primaries"),
                     ("color_transfer", "-color_trc"), ("color_space", "-colorspace")):
        val = (stream.get(key) or "").strip()
        if val and val.lower() not in ("unknown", "unspecified", "n/a"):
            out += [opt, val]
    if codec == "h264":
        field_order = (stream.get("field_order") or "").lower()
        params = "open-gop=0:scenecut=0"
        if field_order in ("tt", "tb", "bb", "bt"):
            top_first = field_order in ("tt", "tb")
            out += ["-flags:v", "+ilme+ildct", "-top", "1" if top_first else "0"]
            params += ":%s=1" % ("tff" if top_first else "bff")
        out += ["-x264-params", params]
    return out


SEEK_EPS = 0.003    # a bemeneti -ss ennyivel a kulcskocka UTÁNRA célzik (az ms-ra kerekített időlista miatt)


def av_start_delta(info, video):
    """A videó és a konténer kezdőidejének különbsége (mp).

    A kulcskocka-listák a VIDEÓ start_time-jához mérnek, az ffmpeg bemeneti -ss és a
    hangszűrők (atrim) viszont a KONTÉNER start_time-jához. Ha a hang korábban indul, mint a
    kép (pl. Opus pre-skip MKV/MP4-ben), a kettő eltér, és enélkül a vágás egy GOP-pal
    korábbra esik, a hang pedig elcsúszik. MPEG-TS-nél ez többnyire 0, ezért ott nem látszott.
    """
    def _f(v):
        try:
            x = float(v)
        except (TypeError, ValueError):
            return None
        return x if math.isfinite(x) else None
    vs = _f((video or {}).get("start_time"))
    fs = _f(((info or {}).get("format") or {}).get("start_time"))
    if vs is None or fs is None:
        return 0.0
    d = vs - fs
    return d if abs(d) <= 5.0 else 0.0


def copy_seek(x, delta, times):
    """Másolt (copy) darab kezdőpontja: (bemeneti -ss, kimeneti -ss, margó).

    A bemeneti -ss az MKV Cues-táblájára ugrik, ami csak a klaszterek elejét indexeli, ezért gyakran EGY
    KORÁBBI kulcskockára esik; a másolás ott elkezdődne, és a kép egy GOP-pal korábbról indulna, a hang
    viszont pontosan vágott lenne (ez a "elcsúszott hang"). A durva bemeneti ugrás után ezért a kimeneti
    -ss pontosan a kívánt kulcskocka elé áll (a B-képkockák dts-e miatt kb. 0,1 s margóval), és az ffmpeg
    az első kulcskockáig minden csomagot eldob."""
    prev = None
    for t in times or ():
        try:
            t = float(t)
        except (TypeError, ValueError):
            continue
        if t < x - 0.001 and (prev is None or t > prev):
            prev = t
    margin = 0.1
    if prev is not None:
        margin = min(0.1, max(0.02, (x - prev) * 0.4))
    target = x + delta - margin
    if target <= 0.001:
        # A fájl elején nincs mit trimmelni; a kimeneti -ss 0 a negatív dts-ű első kulcskockát
        # (B-képkockáknál) is eldobná, és a másolás a következő kulcskockánál indulna.
        return 0.0, None, 0.0
    coarse = max(0.0, target - 40.0)
    return coarse, target - coarse, margin


def _audio_layout(channels):
    return {1: "mono", 2: "stereo", 3: "2.1", 4: "4.0", 5: "5.0", 6: "5.1", 7: "6.1", 8: "7.1"}.get(channels, "stereo")


def _choose_audio_codec(requested, source_codec):
    requested = (requested or "copy").strip().lower()
    if requested == "none":
        return None
    # Editor/Cutter Smart exports preserve the source audio codec. The selected
    # encoder is only an implementation detail (e.g. Opus -> libopus).
    codec = (source_codec or "").strip().lower() if requested == "copy" else requested
    mapping = {
        "aac": "aac", "ac3": "ac3", "eac3": "eac3", "mp2": "mp2",
        "mp3": "libmp3lame", "flac": "flac", "opus": "libopus",
        "vorbis": "libvorbis", "alac": "alac", "wavpack": "wavpack",
        "speex": "libspeex", "dts": "dca", "wmav2": "wmav2",
    }
    if codec.startswith("pcm_"):
        return codec
    encoder = mapping.get(codec)
    if encoder is None:
        raise SmartCutError(_("A hangsáv kodekje (%s) ebben a Smart Cut-változatban nem kódolható vissza ugyanabba a kodekbe.",
          "The audio codec (%s) cannot be re-encoded to the same codec in this Smart Cut version.") %
                            (codec or "ismeretlen"))
    return encoder


def _normal_bitrate(value):
    v = (str(value or "").strip()).replace(",", ".")
    if re.fullmatch(r"\d+(?:\.\d+)?", v) and float(v) < 10000:
        return v + "k"
    return v


def _audio_command(ff, src, audio, ranges, outfile, opts, tmpdir):
    index = int(audio.get("index", 0))
    channels = _int_or_none(opts.get("achannels")) or _int_or_none(audio.get("channels")) or 2
    rate = _int_or_none(opts.get("arate")) or _int_or_none(audio.get("sample_rate")) or 48000
    layout = opts.get("_channel_layout") or _audio_layout(channels)
    codec = _choose_audio_codec("copy", audio.get("codec_name"))
    if not codec:
        return None
    if codec == "libopus":      # a libopus nem fogadja el pl. az 5.1(side) kiosztást
        layout = _audio_layout(channels)

    chains = []
    if len(ranges) > 1:
        labels = ["[asrc%d]" % i for i in range(len(ranges))]
        chains.append("[0:%d]asplit=%d%s" % (index, len(ranges), "".join(labels)))
    else:
        labels = ["[0:%d]" % index]

    outputs = []
    total = 0.0
    shift = float(opts.get("_av_delta") or 0.0)
    for i, (a, b) in enumerate(ranges):
        dur = b - a
        total += dur
        a2, b2 = a + shift, b + shift
        flt = ("atrim=start=%.6f:end=%.6f,asetpts=PTS-%.6f/TB," % (a2, b2, a2) +
               "aresample=async=1:first_pts=0,aformat=sample_rates=%d:channel_layouts=%s," % (rate, layout) +
               "apad,atrim=duration=%.6f[a%d]" % (dur, i))
        chains.append("%s%s" % (labels[i], flt))
        outputs.append("[a%d]" % i)

    if len(outputs) == 1:
        chains.append("%sanull[acat]" % outputs[0])
    else:
        chains.append("%sconcat=n=%d:v=0:a=1[acat]" % ("".join(outputs), len(outputs)))
    post = []
    if (opts.get("volume") or "").strip():
        post.append("volume=%sdB" % opts["volume"].strip())
    if (opts.get("af") or "").strip():
        post.append(opts["af"].strip())
    chains.append("[acat]%s[aout]" % (",".join(post) if post else "anull"))
    graph = ";".join(chains)

    cmd = [ff.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
           "-progress", "pipe:1", "-nostats", "-i", src]
    if len(graph) > 12000:
        fd, gp = tempfile.mkstemp(prefix="lvt_sc_audio_", suffix=".txt", dir=tmpdir)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(graph)
        cmd += ["-filter_complex_script", gp]
    else:
        cmd += ["-filter_complex", graph]
    cmd += ["-map", "[aout]", "-vn", "-sn", "-dn", "-c:a", codec,
            "-ar", str(rate), "-ac", str(channels)]
    bitrate = _normal_bitrate(opts.get("abitrate"))
    if codec not in ("flac", "alac") and not codec.startswith("pcm_"):
        if not bitrate:
            bitrate = "384k" if channels > 2 else "192k"
        cmd += ["-b:a", bitrate]
    cmd += ["-f", "matroska", outfile]
    return (cmd, total)


def build_jobs(ff, src, groups, idr_times, info, targets, opts, cancel=None):
    """Build source-profile-preserving Smart Cut jobs for one or more outputs.

    `groups` is a list of lists of (start,end) ranges; each group is one output
    file and `targets` has one target path per group. The source container,
    video codec, and audio codec are authoritative: this path does not perform
    codec/container conversion. Conversion remains a separate Editor action.
    """
    if len(groups) != len(targets) or not groups:
        raise SmartCutError(_("Hibás Smart cut kimeneti lista.",
          "Invalid Smart cut output list."))
    source_container = _source_container_setting(info, src)
    video = _video_stream(info)
    codec = (video.get("codec_name") or "").lower()
    if codec not in ("h264", "hevc", "vp9", "av1"):
        raise SmartCutError(_("A Smart Cut jelenleg H.264, HEVC/H.265, VP9 és AV1 videót támogat.",
          "Smart Cut currently supports H.264, HEVC/H.265, VP9 and AV1 video."))
    if (video.get("pix_fmt") or "").lower() not in ("yuv420p", "yuvj420p", "yuv420p10le"):
        raise SmartCutError(_("A Smart Cut jelenleg 8/10 bites 4:2:0 videót támogat (forrás pix_fmt: %s).",
          "Smart Cut currently supports 8/10-bit 4:2:0 video (source pix_fmt: %s).") %
                            (video.get("pix_fmt") or "?"))
    if codec in ("vp9", "av1") and source_container == "mpegts":
        raise SmartCutError(_("A VP9/AV1 Smart Cut MKV vagy MP4 konténerben támogatott, MPEG-TS-ben nem.",
          "VP9/AV1 Smart Cut is supported in MKV or MP4 containers, not in MPEG-TS."))
    rate, fps = _rate_for(video)
    av_delta = av_start_delta(info, video)
    # The Editor supplies codec-specific safe access points after its async scan;
    # Cutter passes None and lets this worker-side planner scan the source.
    if idr_times is not None:
        access_times = idr_times
    else:
        access_times = detect_random_access_times(ff, src, info, cancel=cancel)
    # An empty list is valid: split_range will re-encode the full selected span.
    video_index = int(video.get("index", 0))
    audio = _audio_stream(info)

    known_v = set()
    known_a = set()
    try:
        enc = ff.encoders()
        known_v = {n for n, _desc in enc.get("V", [])}
        known_a = {n for n, _desc in enc.get("A", [])}
    except Exception:
        # Let the FFmpeg job return the concrete error if listing is unavailable.
        pass
    edge_video_opts = _video_encoder_options(video, rate, known_v)

    # Copy the profile from the loaded source. User settings on the separate
    # conversion page must never turn these Editor exports into conversions.
    run_opts = dict(opts or {})
    run_opts["container"] = source_container
    run_opts["vcodec"] = "copy"
    run_opts["acodec"] = "copy"
    run_opts["_av_delta"] = av_delta
    if audio:
        source_acodec = (audio.get("codec_name") or "").lower()
        audio_encoder = _choose_audio_codec("copy", source_acodec)
        if known_a and audio_encoder not in known_a:
            raise SmartCutError(_("A megadott FFmpeg buildben nincs %s encoder; a hang eredeti kodekjének megtartásához szükséges.",
          "The given FFmpeg build has no %s encoder; it is needed to keep the original audio codec.") %
                                audio_encoder)
        channels = _int_or_none(audio.get("channels"))
        sample_rate = _int_or_none(audio.get("sample_rate"))
        if channels:
            run_opts["achannels"] = channels
        if sample_rate:
            run_opts["arate"] = sample_rate
        layout = (audio.get("channel_layout") or "").strip()
        if layout and layout.lower() not in ("unknown", "n/a"):
            run_opts["_channel_layout"] = layout
        if _int_or_none(audio.get("bit_rate")):
            run_opts["abitrate"] = str(_int_or_none(audio.get("bit_rate")))

    tmpdir = tempfile.mkdtemp(prefix="lvt_smartcut_")
    lifecycle = {"final_started": False, "final_done": False}
    jobs = []
    built_groups = []
    serial = 0

    def write_concat_list(path, parts):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("ffconcat version 1.0\n")
            for part, duration in parts:
                # Relative single-quoted names avoid Windows drive/space parsing issues.
                name = os.path.basename(part).replace("'", "\\'")
                fh.write("file '%s'\n" % name)
                fh.write("duration %.9f\n" % duration)
    try:
        for gi, (ranges, target) in enumerate(zip(groups, targets)):
            if not ranges:
                raise SmartCutError(_("Üres Smart Cut kimeneti szakasz.",
          "Empty Smart Cut output segment."))
            if os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(target)):
                raise SmartCutError(_("A kimeneti fájl nem lehet azonos a forrásfájllal.",
          "The output file cannot be the same as the source file."))
            _validate_target_container(run_opts, target)
            parts = []
            total = 0.0
            clean_ranges = []
            for a, b in ranges:
                a, b = float(a), float(b)
                if b <= a:
                    raise SmartCutError(_("A vég nem lehet korábbi, mint az eleje.",
          "The end cannot be earlier than the start."))
                fragments = split_range(a, b, access_times, fps)
                range_frames = 0
                for x, y, mode in fragments:
                    nframes = int(round((y - x) * fps))
                    if nframes <= 0:
                        continue
                    range_frames += nframes
                    mpegts_intermediate = codec in ("h264", "hevc")
                    part_ext = ".ts" if mpegts_intermediate else ".mkv"
                    part = os.path.join(tmpdir, "video_%04d%s" % (serial, part_ext))
                    serial += 1
                    if mode == "copy":
                        c_in, c_out, _mg = copy_seek(x, av_delta, access_times)
                        cmd = [ff.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                               "-progress", "pipe:1", "-nostats", "-ss", _fmt(c_in), "-i", src,
                               ] + (["-ss", _fmt(c_out)] if c_out is not None else []) + [
                               "-map", "0:%d" % video_index, "-an", "-sn", "-dn",
                               "-frames:v", str(nframes), "-c:v", "copy"]
                        if mpegts_intermediate:
                            bsf = "h264_mp4toannexb" if codec == "h264" else "hevc_mp4toannexb"
                            cmd += ["-bsf:v", bsf, "-mpegts_flags", "+resend_headers", "-f", "mpegts", part]
                        else:
                            cmd += ["-f", "matroska", part]
                    else:
                        # Select by frame count from that keyframe, not by timestamp: the
                        # source timestamps sit at x.01/x.03 offsets, so a time-based
                        # output -ss can start one or more frames early (measured 0.09 s).
                        k_seek = _keyframe_at_or_before(access_times, x, tol=0.0006)
                        skip_frames = max(0, int(round((x - k_seek) * fps)))
                        cmd = [ff.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                               "-progress", "pipe:1", "-nostats", "-ss", _fmt(max(0.0, k_seek + av_delta - 0.002)), "-i", src,
                               "-map", "0:%d" % video_index, "-an", "-sn", "-dn",
                               "-frames:v", str(nframes)]
                        cmd += _edge_opts_with_select(edge_video_opts, skip_frames)
                        if mpegts_intermediate:
                            cmd += ["-mpegts_flags", "+resend_headers", "-f", "mpegts", part]
                        else:
                            cmd += ["-f", "matroska", part]
                    jobs.append((cmd, nframes / fps))
                    parts.append((part, nframes / fps))
                if range_frames:
                    duration = range_frames / fps
                    total += duration
                    clean_ranges.append((a, a + duration))

            if not parts:
                raise SmartCutError(_("A kijelölt szakaszok nem tartalmaznak teljes képkockát.",
          "The selected segments contain no complete frame."))
            audio_path = None
            if audio:
                audio_path = os.path.join(tmpdir, "audio_%03d.mka" % gi)
                audio_job = _audio_command(ff, src, audio, clean_ranges, audio_path, run_opts, tmpdir)
                if audio_job:
                    jobs.append(audio_job)
                else:
                    audio_path = None

            concat_list = os.path.join(tmpdir, "video_%03d.ffconcat" % gi)
            write_concat_list(concat_list, parts)
            built_groups.append(dict(parts=parts, concat=concat_list, audio=audio_path,
                                     target=target, total=total))

        if not jobs:
            raise SmartCutError(_("Nem készült végrehajtható Smart Cut feladat.",
          "No executable Smart Cut job was produced."))

        def final():
            lifecycle["final_started"] = True
            try:
                for group in built_groups:
                    if cancel is not None and cancel.is_set():
                        raise SmartCutError("cancelled")
                    for part, _duration in group["parts"]:
                        if not os.path.isfile(part):
                            raise SmartCutError(_("A Smart Cut köztes videódarab hiányzik a végső összefűzés előtt: %s",
          "A Smart Cut intermediate video part is missing before the final join: %s") % part)
                    # Some hosts call cleanup before invoking their final callback.
                    # Re-create the small playlist if needed; keep intermediates alive
                    # until this final mux has completed.
                    if not os.path.isfile(group["concat"]):
                        write_concat_list(group["concat"], group["parts"])
                    overwrite = bool(run_opts.get("overwrite", True))
                    concat_input = group["concat"].replace("\\", "/")
                    cmd = [ff.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
                           "-y" if overwrite else "-n", "-progress", "pipe:1", "-nostats",
                           "-fflags", "+genpts", "-f", "concat", "-safe", "0", "-i", concat_input]
                    if group["audio"]:
                        # Az ffmpeg a bemenet start_time-ját kivonja; az Opus pre-skip miatt az .mka
                        # kb. -7 ms-ról indul, ezt ki kell egyenlíteni, különben a hang késik a képhez képest.
                        a_off = 0.0
                        try:
                            a_info = ff.probe(group["audio"])
                            a_off = float((a_info.get("format") or {}).get("start_time") or 0.0)
                            if not math.isfinite(a_off) or abs(a_off) > 1.0:
                                a_off = 0.0
                        except Exception:
                            a_off = 0.0
                        if a_off:
                            cmd += ["-itsoffset", "%.6f" % a_off]
                        cmd += ["-i", group["audio"].replace("\\", "/")]
                    cmd += ["-map", "0:v:0"]
                    if group["audio"]:
                        cmd += ["-map", "1:a:0", "-c:a", "copy", "-strict", "-2"]
                    else:
                        cmd += ["-an"]
                    cmd += ["-c:v", "copy"]
                    cmd += ff._out_opts(run_opts, group["target"], "copy")
                    cmd += ["-avoid_negative_ts", "make_zero"]
                    ext = os.path.splitext(group["target"])[1].lower()
                    if run_opts["container"] == "mpegts" or ext in (".ts", ".mts", ".m2ts"):
                        cmd += ["-mpegts_flags", "+resend_headers"]
                    cmd.append(group["target"])
                    ff.run_convert(cmd, group["total"], cancel=cancel)
            finally:
                lifecycle["final_done"] = True
                shutil.rmtree(tmpdir, ignore_errors=True)

        def cleanup_if_final_never_started():
            if not lifecycle["final_started"] and not lifecycle["final_done"]:
                shutil.rmtree(tmpdir, ignore_errors=True)

        def cleanup():
            if lifecycle["final_done"]:
                shutil.rmtree(tmpdir, ignore_errors=True)
            elif not lifecycle["final_started"]:
                # Avoid leaking temps if an earlier encoding job failed and the
                # host never invokes final(); the callback normally follows at once.
                timer = threading.Timer(60.0, cleanup_if_final_never_started)
                timer.daemon = True
                timer.start()

        return jobs, final, cleanup
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
