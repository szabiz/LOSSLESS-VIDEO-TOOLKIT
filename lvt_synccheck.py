# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 szabiz <szabiz@yahoo.com>
# Copyright (c) 2026 szabiz <szabiz@yahoo.com>
"""Szinkron-mérés: python lvt_synccheck.py FORRÁS KIMENET FORRÁS_KEZDET_MP [ffmpeg_mappa]

FORRÁS_KEZDET_MP: az a másodperc a FORRÁSFÁJLBAN, ahonnan a kimenet első szakasza indul
(pl. 708.2, ha a 11:48.2-nél kezdődő szakaszt vágtad). Csak a kimenet első szakaszát méri.
Kell hozzá: numpy (pip install numpy). Kimenet: mennyivel tér el a hang a képtől a forráshoz képest."""
import os, re, subprocess, sys
import numpy as np

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)

def tools(d):
    if d:
        return os.path.join(d, "ffmpeg"), os.path.join(d, "ffprobe")
    return "ffmpeg", "ffprobe"

def video(ffm, path, ss, length):
    cmd = [ffm, "-hide_banner", "-nostdin", "-copyts", "-ss", "%.3f" % max(0, ss), "-t", "%.3f" % length, "-i", path,
           "-map", "0:v:0", "-vf", "scale=48:27,format=gray,showinfo", "-f", "rawvideo", "-"]
    r = subprocess.run(cmd, capture_output=True, creationflags=NOWIN)
    ts = [float(x) for x in re.findall(rb"pts_time:\s*([-\d.]+)", r.stderr)]
    raw = np.frombuffer(r.stdout, dtype=np.uint8)
    n = min(len(ts), len(raw) // (48 * 27))
    fr = raw[: n * 48 * 27].reshape(n, 48 * 27).astype(np.float32)
    order = np.argsort(ts[:n])
    return np.array(ts[:n])[order], fr[order]

def audio(ffm, path, ss, length):
    cmd = [ffm, "-hide_banner", "-nostdin", "-copyts", "-ss", "%.3f" % max(0, ss), "-t", "%.3f" % length, "-i", path,
           "-map", "0:a:0", "-ac", "1", "-ar", "8000", "-af", "ashowinfo", "-f", "f32le", "-"]
    r = subprocess.run(cmd, capture_output=True, creationflags=NOWIN)
    ts = re.findall(rb"pts_time:\s*([-\d.]+)", r.stderr)
    t0 = float(ts[0]) if ts else 0.0
    return t0, np.frombuffer(r.stdout, dtype=np.float32)

def main():
    if len(sys.argv) < 4:
        print(__doc__); return
    src, out, start = sys.argv[1], sys.argv[2], float(sys.argv[3])
    ffm, _ = tools(sys.argv[4] if len(sys.argv) > 4 else "")
    L = 3.0
    # kép: a kimenet első kockája melyik forráskockával egyezik
    ot, of = video(ffm, out, 0.0, 1.0)
    st, sf = video(ffm, src, start - 0.5, 1.5)
    d = np.abs(sf - of[0]).mean(axis=1)
    j = int(np.argmin(d))
    v_src = st[j]
    dv = v_src - ot[0]
    print("kép: a kimenet első kockája (%.3f s) = forrás %.3f s  (illeszkedés hiba %.2f)" % (ot[0], v_src, d[j]))
    # hang: a kimenet első másodpercei hol vannak a forrásban
    oa0, oa = audio(ffm, out, 0.0, L)
    sa0, sa = audio(ffm, src, start - 2.0, L + 4.0)
    n = min(len(oa), 8000 * 2)
    q = oa[:n] - oa[:n].mean()
    best, lag = -1e9, 0
    # keresés 8 kHz-en +-2 mp tartományban
    nfft = 1 << int(np.ceil(np.log2(len(sa) + n)))
    cc = np.fft.irfft(np.fft.rfft(sa - sa.mean(), nfft) * np.conj(np.fft.rfft(q, nfft)), nfft)[: len(sa) - n + 1]
    lag = int(np.argmax(cc))
    a_src = sa0 + lag / 8000.0
    da = a_src - oa0
    print("hang: a kimenet első mintája (%.3f s) = forrás %.3f s" % (oa0, a_src))
    err = da - dv
    print()
    print("ELTÉRÉS (hang - kép): %+.0f ms" % (err * 1000))
    print("  (0 körül jó; pozitív: a hang a forrásban KÉSŐBBI részt játssza, mint a kép = a hang siet; negatív: késik)")
main()
