# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 szabiz <szabiz@yahoo.com>
# Copyright (c) 2026 szabiz <szabiz@yahoo.com>
"""Diagnosztika: python lvt_diag.py "F:\\CODEC\\fajl_cut2.mkv" [ffmpeg_mappa]
A lvt_smartcut.py és lvt_iframe.py legyen ugyanabban a mappában. Az eredményt (a kiírt szöveget,
és a lvt_diag_report.txt fájlt) küldd el. Ideiglenes fájlokat a TEMP mappába ír, a forrást nem módosítja."""
import json, os, shutil, subprocess, sys, tempfile, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # a programmodulok a szülőmappában vannak
import lvt_smartcut as sc, lvt_iframe as lf

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
rep = []
def say(*a):
    s = " ".join(str(x) for x in a); print(s); rep.append(s)

def main():
    if len(sys.argv) < 2:
        print(__doc__); return
    src = sys.argv[1]
    if len(sys.argv) > 2:
        d = sys.argv[2]
        ffm, ffp = os.path.join(d, "ffmpeg"), os.path.join(d, "ffprobe")
        ff = sc.CommandFFmpeg(ffm, ffp)
    else:
        ff = sc.CommandFFmpeg.from_environment()
    info = ff.probe(src)
    say("== FORMAT", json.dumps({k: (info.get("format") or {}).get(k) for k in ("format_name", "start_time", "duration", "bit_rate")}))
    for s in info["streams"]:
        say("== STREAM", json.dumps({k: s.get(k) for k in ("index", "codec_type", "codec_name", "profile", "channels", "channel_layout",
                                                          "sample_rate", "start_time", "time_base", "r_frame_rate", "pix_fmt", "bit_rate")}))
    out = subprocess.run([ff.ffprobe, "-v", "error", "-read_intervals", "%+2", "-show_entries",
                          "packet=stream_index,pts_time,dts_time,flags", "-of", "csv", src],
                         capture_output=True, text=True, creationflags=NOWIN).stdout.splitlines()
    seen = {}
    for ln in out:
        p = ln.split(",")
        if len(p) > 1:
            seen.setdefault(p[1], []).append(ln)
    for k, v in seen.items():
        say("== ELSŐ CSOMAGOK (stream %s): %s" % (k, " | ".join(x.replace("packet,", "") for x in v[:5])))
    say("== av_start_delta =", sc.av_start_delta(info, sc._video_stream(info)))
    times = sc.detect_random_access_times(ff, src, info)
    say("== kulcskockák (első 6):", times[:6])
    ks = [t for t in times if t > 1.0]
    if len(ks) < 3:
        say("nincs elég kulcskocka a teszthez"); return
    a, b = ks[0], ks[2]
    tmp = tempfile.mkdtemp(prefix="lvt_diag_")
    ext = os.path.splitext(src)[1] or ".mkv"
    def vol(path):
        r = subprocess.run([ff.ffmpeg, "-hide_banner", "-nostdin", "-i", path, "-map", "0:a:0", "-af", "volumedetect", "-f", "null", "-"],
                           capture_output=True, text=True, creationflags=NOWIN)
        m = re.search(r"mean_volume: ([-\d.inf]+) dB", r.stderr)
        return m.group(1) if m else "NINCS HANG / hiba: " + r.stderr.strip()[-200:]
    def streams(path):
        i2 = ff.probe(path)
        return [(s["codec_type"], s.get("codec_name"), s.get("start_time")) for s in i2["streams"]]
    try:
        say("== forrás hangerő (mean):", vol(src))
        t1 = os.path.join(tmp, "iframe" + ext)
        cmd = lf.part_command(ff, src, info, a, b, t1)
        say("== I-FRAME parancs:", " ".join(cmd))
        r = subprocess.run(cmd, capture_output=True, text=True, creationflags=NOWIN)
        say("   rc", r.returncode, (r.stderr or "").strip()[-400:])
        if os.path.isfile(t1):
            say("   kimenet:", streams(t1), "hangerő:", vol(t1))
        rngs = [(a + 2.0, b + 3.0)]
        t2 = os.path.join(tmp, "smart" + ext)
        opts = {"container": "", "overwrite": True, "vcodec": "copy", "acodec": "copy", "arate": None, "achannels": None,
                "abitrate": "", "volume": "", "af": ""}
        jobs, final, cleanup = sc.build_jobs(ff, src, [rngs], times, info, [t2], opts)
        for c, d in jobs:
            say("== SMART parancs:", " ".join(c)[:700])
            ff.run_convert(c, d)
        final()
        say("   kimenet:", streams(t2), "hangerő:", vol(t2))
    except Exception as e:
        say("HIBA:", e)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    with open("lvt_diag_report.txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(rep))
    print("\nKész. A jelentés: lvt_diag_report.txt")
main()
