#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 szabiz <szabiz@yahoo.com>
# Copyright (c) 2026 szabiz <szabiz@yahoo.com>
r"""Seek checker for Lossless Video Toolkit output (lvt_seek_check.py).
Keresés-vizsgáló a Lossless Video Toolkit kimenetéhez.

It checks two things that can make an external player stall when seeking:
  1) whether the container carries a seek index (MKV / MP4 / MOV: yes; MPEG-TS / M2TS: NO),
  2) how dense the keyframes are - if the player has to decode forward from the previous
     keyframe to the requested point, the picture freezes while the audio keeps playing.

Usage:
    python lvt_seek_check.py OUTPUT.m2ts
    python lvt_seek_check.py OUTPUT.mkv --ffprobe=C:\folder\ffprobe.exe
    python lvt_seek_check.py OUTPUT.mkv --lang=hu     (Hungarian; English is the default)
    python lvt_seek_check.py --demo                   (keyframe-counting self-test, no file needed)

The ffprobe path is also read from ~/.lvt_ffmpeg.json (an ffprobe next to the configured
ffmpeg is used if only ffmpeg is set). The language can also be set with the LVT_LANG
environment variable. Only the Python standard library is used; the file is not modified.
"""
import json
import os
import re
import subprocess
import sys

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LANG = (os.environ.get("LVT_LANG") or "en").strip().lower()
if LANG not in ("hu", "en"):
    LANG = "en"


def _(hu, en):
    return hu if LANG == "hu" else en


INDEXED = ("matroska", "webm", "mov", "mp4", "m4v", "isom", "3gp")
NO_INDEX = ("mpegts", "mpegts_raw", "rawvideo", "mp3", "aac", "adts", "mp2", "wav", "flac")


def find_ffprobe(override=""):
    """Az ffprobe útvonala: kézi megadás, a modul beállítás-fájlja, vagy a PATH."""
    if override and os.path.isfile(override):
        return override
    p = os.path.join(os.path.expanduser("~"), ".lvt_ffmpeg.json")
    try:
        with open(p, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
        v = (cfg.get("ffprobe") or "").strip()
        if v and os.path.isfile(v):
            return v
        ffm = (cfg.get("ffmpeg") or "").strip()
        if ffm and os.path.isfile(ffm):
            # only ffmpeg is configured: use the ffprobe that sits next to it
            d, name = os.path.split(ffm)
            cand = os.path.join(d, name.lower().replace("ffmpeg", "ffprobe", 1))
            if os.path.isfile(cand):
                return cand
    except (OSError, ValueError):
        pass
    import shutil
    return shutil.which("ffprobe") or ""


def run(ffprobe, args):
    cmd = [ffprobe, "-v", "error", "-hide_banner"] + args
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                           creationflags=NOWIN, timeout=900)
    except (OSError, subprocess.SubprocessError) as e:
        sys.exit(_("Nem futtatható az ffprobe (%s): %s", "Cannot run ffprobe (%s): %s") % (ffprobe, e))
    if r.returncode != 0:
        sys.exit(_("Az ffprobe hibája: ", "ffprobe error: ") + (r.stderr.decode("utf-8", "replace").strip()[-300:]))
    return r.stdout.decode("utf-8", "replace")


def keyframe_times(txt):
    """Az ffprobe `packet=pts_time,flags` soraiból a kulcskockák idői (mp, növekvő sorrend)."""
    out = []
    for ln in txt.splitlines():
        ln = ln.strip().lstrip("[").rstrip("]")
        if not ln.startswith("packet|"):
            continue
        d = {}
        for part in ln.split("|")[1:]:
            k, _eq, v = part.partition("=")
            d[k.strip()] = v.strip()
        if "K" not in (d.get("flags") or ""):
            continue
        for key in ("pts_time", "pkt_pts_time", "dts_time", "pkt_dts_time"):
            try:
                out.append(max(0.0, float(d[key])))
                break
            except (KeyError, ValueError):
                continue
    return sorted(set(round(x, 3) for x in out))


def gaps(ts, dur):
    """A kulcskockák közti hézagok (mp) -> (legnagyobb, átlag, darabszám, az első kulcskocka időe)."""
    if not ts:
        return 0.0, 0.0, 0, 0.0
    g = [b - a for a, b in zip(ts, ts[1:])]
    if dur:
        g.append(max(0.0, dur - ts[-1]))            # a fájl vége is kulcskockára várhat
    return (max(g) if g else 0.0), (sum(g) / len(g) if g else 0.0), len(ts), ts[0]


def report(path, ffprobe):
    f = {}
    for ln in run(ffprobe, ["-show_format", "-of", "default=nw=1:nk=0", path]).splitlines():
        k, _eq, v = ln.partition("=")
        f[k.strip()] = v.strip()
    name = (f.get("format_name") or "").split(",")[0].strip()
    try:
        dur = float(f.get("duration") or 0)
    except ValueError:
        dur = 0.0
    s = {}
    for ln in run(ffprobe, ["-select_streams", "v:0", "-show_entries",
                            "stream=codec_name,width,height,r_frame_rate,start_time",
                            "-of", "default=nw=1:nk=0", path]).splitlines():
        k, _eq, v = ln.partition("=")
        s[k.strip()] = v.strip()
    fps = 0.0
    m = re.match(r"^(\d+)/(\d+)$", s.get("r_frame_rate") or "")
    if m and int(m.group(2)):
        fps = int(m.group(1)) / int(m.group(2))
    ts = keyframe_times(run(ffprobe, ["-select_streams", "v:0", "-show_entries", "packet=pts_time,flags",
                                      "-of", "compact", path]))
    mx, av, n, first = gaps(ts, dur)
    st = (s.get("start_time") or "0").strip()

    print(_(u"Fájl           : %s", u"File           : %s") % path)
    print(_(u"Konténer       : %s   (kiterjesztés: %s)", u"Container      : %s   (extension: %s)") %
          (name or "?", os.path.splitext(path)[1] or "-"))
    print(_(u"Hossz          : %.1f mp   Videó: %s %sx%s, %.3f kocka/mp",
            u"Duration       : %.1f s   Video: %s %sx%s, %.3f fps") %
          (dur, s.get("codec_name") or "?", s.get("width") or "?", s.get("height") or "?", fps))
    if st not in ("0", "0.000000", "N/A", ""):
        print(_(u"start_time     : %s   <- nem 0: a lejátszó ehhez képest számol",
                u"start_time     : %s   <- not 0: the player counts relative to this") % st)
    print()
    print(_(u"Kulcskockák    : %d db", u"Keyframes      : %d") % n)
    print(_(u"  legnagyobb   : %.2f mp", u"  largest gap  : %.2f s") % mx)
    print(_(u"  átlag        : %.2f mp", u"  average gap  : %.2f s") % av)
    print(_(u"  az első pont : %.2f mp", u"  first point  : %.2f s") % first)
    print()

    verdict = []
    if name in NO_INDEX:
        verdict.append(_(
            u"KONTÉNER: az %s nem hordoz keresési indexet. A lejátszó ilyenkor a közelben"
            u" talált bájt-pozícióból INDÍTVA keresi a kért időpontot, és addig az utolsó"
            u" képet tartja – a hang közben megy. Ez a te tünete, és NEM a kodektől függ.",
            u"CONTAINER: %s carries no seek index. The player then starts from a nearby byte"
            u" position and scans forward to the requested time, holding the last picture"
            u" meanwhile while the audio keeps playing. This is your symptom, and it does NOT"
            u" depend on the codec.") % name)
    elif name in INDEXED:
        verdict.append(_(
            u"KONTÉNER: az %s indexelt, a seek itt azonnal ugrik. Ha mégis akadozik, a"
            u" kulcskockák ritkák.",
            u"CONTAINER: %s is indexed, so seeking jumps immediately. If it still stutters,"
            u" the keyframes are sparse.") % name)
    else:
        verdict.append(_(u"KONTÉNER: %s – nem ismert, indexeltséget nem állapítok meg.",
                         u"CONTAINER: %s – unknown, cannot tell whether it is indexed.") % (name or "?"))
    if mx > 2.0:
        verdict.append(_(
            u"GOP: a kulcskockák %.2f mp-enként jönnek. Az ugrás előtt a lejátszónak el kell"
            u" dekódolnia az előző kulcskockáig: %.2f mp a legnagyobb „befagyás”.",
            u"GOP: keyframes come every %.2f s. Before a jump the player must decode forward"
            u" from the previous keyframe: %.2f s is the longest \"freeze\".") % (mx, mx))
    elif mx:
        verdict.append(_(u"GOP: %.2f mp – sűrűn vannak kulcskockák, ez kevésbé okoz döccenést.",
                         u"GOP: %.2f s – keyframes are dense, which causes fewer stutters.") % mx)
    if st not in ("0", "0.000000", "N/A", ""):
        verdict.append(_(
            u"CSOMAGIDŐ: a videó %s mp-nél indul (a fájl nem nulláról indul). Egyes külső"
            u" lejátszók így a 0. mp-re ugorva nem találnak képet, előbb a végére mennek.",
            u"PACKET TIME: the video starts at %s s (the file does not start at zero). Some"
            u" external players then find no picture when jumping to second 0 and go to the end first.") % st)
    for i, t in enumerate(verdict, 1):
        print(u"%d. %s" % (i, t))
    print()
    print(_(u"Kétperces vizsgálat: írd újra ugyanazt a szakaszt MATROSKA (.mkv) konténerre ugyanazzal\n"
            u"a kodekkel, és keresgélj benne. Ha szűnik a fagyás, a konténer (az index hiánya) volt az\n"
            u"ok; ha marad, a kulcskockák a ritkák – az „Extra paraméter” mezőbe írd (szóköz nélkül):",
            u"Two-minute test: rewrite the same section into a MATROSKA (.mkv) container with the same\n"
            u"codec and seek around in it. If the freezing stops, the container (missing index) was the\n"
            u"cause; if it stays, the keyframes are too sparse – enter this in the \"Extra parameter\" field"
            u" (no spaces):"))
    print(u"    -g 25 -force_key_frames expr:gte(t,n_forced*1)")
    print(_(u"(az értéket az „Extra paraméter” mezőbe NEM kell idézőjelbe tenni: Windowson a\n"
            u" beírt idézőjel benne marad a paraméterben, és az FFmpeg elutasítja)",
            u"(do NOT put the value in quotes in the \"Extra parameter\" field: on Windows the\n"
            u" typed quote stays in the parameter and FFmpeg rejects it)"))


DEMO = ("packet|pts_time=0.000000|flags=K__\n"
        "packet|pts_time=0.040000|flags=___\n"
        "packet|pts_time=4.040000|flags=K__\n"
        "packet|pts_time=8.080000|flags=K__\n"
        "packet|pts_time=18.120000|flags=K__\n")


def main(argv):
    global LANG
    for a in argv:
        if a.startswith("--lang="):
            code = a.split("=", 1)[1].strip().lower()
            if code in ("hu", "en"):
                LANG = code
    if "--demo" in argv:
        ts = keyframe_times(DEMO)
        mx, av, n, first = gaps(ts, 20.0)
        assert n == 4 and ts[0] == 0.0, ts
        assert abs(mx - 10.04) < 1e-6 and abs(av - 5.0) < 1e-9, (mx, av)
        print(_("DEMO: kulcskockák: %d db, legnagyobb hézag %.2f mp, átlag %.2f mp  -> OK",
                "DEMO: keyframes: %d, largest gap %.2f s, average %.2f s  -> OK") % (n, mx, av))
        d2 = keyframe_times("packet|pkt_pts_time=4.040000|flags=K__\npacket|pts_time=N/A|flags=K__\n"
                            "packet|pts_time=8.080000|flags=K__\nframe|pts_time=9|flags=K__\n")
        assert d2 == [4.04, 8.08], d2
        print(_("DEMO: régi ffprobe-alakú + N/A + nem packet sor kezelése      -> OK",
                "DEMO: old ffprobe format + N/A + non-packet line handling     -> OK"))
        return 0
    argv = list(argv)
    for i, a in enumerate(argv):
        if a == "--ffprobe" and i + 1 < len(argv):
            argv[i:i + 2] = ["--ffprobe=" + argv[i + 1]]
            break
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1:
        print(__doc__.strip())
        return 2
    path = args[0]
    if not os.path.isfile(path):
        print(_("Nincs ilyen fájl: %s", "No such file: %s") % path)
        return 1
    ff = ""
    for a in argv:
        if a.startswith("--ffprobe"):
            ff = a.split("=", 1)[1]
    ff = ff or find_ffprobe()
    if not ff:
        print(_("Nem találom az ffprobe-ot: python lvt_seek_check.py fajl.m2ts --ffprobe=C:\\...\\ffprobe.exe",
                "Cannot find ffprobe: python lvt_seek_check.py file.m2ts --ffprobe=C:\\...\\ffprobe.exe"))
        return 1
    report(path, ff)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
