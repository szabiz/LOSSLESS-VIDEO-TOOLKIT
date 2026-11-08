#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 szabiz <szabiz@yahoo.com>
# Copyright (c) 2026 szabiz <szabiz@yahoo.com>
"""
Lossless Video Toolkit - Videó-elemző (lvt_analyzer.py)
=======================================================
Egy betöltött videófájl teljes technikai adatlapja, majd szerkezeti és időzítési
ellenőrzés. Kizárólag saját fejlesztésű kód; a Python szabványos könyvtárát használja.

Harmadik féltől származó kódot, könyvtárat, adatfájlt NEM tartalmaz és NEM igényel (az ffmpeg/ffprobe csak opcionális külső program):
nincs FFmpeg-kód, ffprobe-kód, MediaInfo, pymediainfo, dekóder, külső táblázat; az FFmpeg/ffprobe csak külső programként hívódik, ha telepítve van. A feldolgozás
a nyilvános szabványok leírása alapján készült (ITU-T H.264, ISO/IEC 13818-1 és -2,
ATSC A/52 és E-AC-3, ISO/IEC 11172-3, ADTS); másolt kód nincs benne.

Mélyelemzés: MPEG-TS / M2TS (AVCHD). Szerkezeti ellenőrzés: MP4 / MOV, MKV / WebM,
MPEG-PS / VOB a joiner egyfájlos elemzőjével (ha elérhető), AVI saját RIFF-ellenőrzővel.
A képkockák dekódolása csak az opcionális külső ffmpeg-ellenőrzésben történik, ha telepítve van.

Használat:
    python lvt_analyzer.py fájl.mts            -> adatlap a konzolra
    python lvt_analyzer.py fájl.mts -o r.txt   -> adatlap fájlba (UTF-8)
A grafikus fül a joiner programba épül be (lásd apply_analyzer_patch.py).
"""
import os
import re
import sys
import struct
import queue
import threading
import argparse
from collections import Counter

__version__ = "1.0"

MOD33 = 1 << 33
HALF33 = 1 << 32
CHUNK_PKTS = 4096        # ennyi TS-csomag olvasása egyszerre
AU_SCAN = 4096           # videó-hozzáférési egységből ennyi bájt vizsgálata (SPS/PPS, képtípus)
AUDIO_CAP = 65536        # hang-PES-enként ennyi bájt a keretezéshez
CRC_STEP = 8             # AC-3 CRC: minden N. hang-PES ellenőrzése (mintavétel, a sebesség miatt)
PCR_JUMP = 2700000       # 100 ms 27 MHz-en
GOP_WARN_S = 2.0         # ennél hosszabb GOP lassú keresést okoz
GOP_ERR_S = 5.0
NOHDR_SIDS = {0xBC, 0xBE, 0xBF, 0xF0, 0xF1, 0xFF, 0xF2, 0xF8}
_HIGH_PROFILES = (100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135)
_PROFILE_NAMES = {66: "Baseline", 77: "Main", 88: "Extended", 100: "High", 110: "High 10",
                  122: "High 4:2:2", 244: "High 4:4:4 Predictive", 118: "Multiview High",
                  128: "Stereo High"}
_STREAM_TYPES = {0x01: ("MPEG-1 video", "video"), 0x02: ("MPEG-2 video", "video"),
                 0x1B: ("H.264/AVC", "video"), 0x24: ("H.265/HEVC", "video"),
                 0xEA: ("VC-1", "video"), 0x03: ("MPEG-1 audio", "audio"),
                 0x04: ("MPEG-2 audio", "audio"), 0x0F: ("AAC (ADTS)", "audio"),
                 0x81: ("AC-3", "audio"), 0x87: ("E-AC-3", "audio"), 0x82: ("DTS", "audio"),
                 0x83: ("TrueHD", "audio"), 0x80: ("LPCM", "audio"), 0x90: ("PGS felirat", "sub"),
                 0x06: ("private (AC-3?)", "other")}
_AUDIO_CODEC = {0x81: "ac3", 0x87: "eac3", 0x03: "mpa", 0x04: "mpa", 0x0F: "aac"}
_AC3_KBPS = (32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384, 448, 512, 576, 640)
_NCH = (2, 1, 2, 3, 3, 4, 4, 5)
_ADTS_SF = (96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000, 7350)
_MPA_SR = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}
_MPA_BR = {
    (1, 2): (32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384),
    (1, 3): (32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
    (2, 2): (8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
    (2, 3): (8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
}
_MPEG2_FPS = {1: 23.976, 2: 24.0, 3: 25.0, 4: 29.97, 5: 30.0, 6: 50.0, 7: 59.94, 8: 60.0}


# ----------------------------------------------------------------- nyelv ----

def L(hu, en):
    """Bilingual text following the joiner's active language (default: English)."""
    return hu if _lang() == "hu" else en


_CORE = None


def _lang():
    return getattr(_CORE, "LANG", "en") if _CORE is not None else "en"


def install(core):
    """A joiner modul (sys.modules[__name__]) átadása: nyelv és alapelemző eléréséhez."""
    global _CORE
    _CORE = core


def tab_title():
    """A fül felirata a joiner nyelve szerint."""
    return L("Videó-elemző", "Video analyzer")


class AnalyzeCancelled(Exception):
    pass


# ------------------------------------------------------------ alapfüggvények --

def sdiff(a, b):
    """(a - b) előjeles értéke 33 bites órában."""
    return ((a - b + HALF33) % MOD33) - HALF33


def _unwrap(vals):
    if not vals:
        return []
    out = [vals[0]]
    for a, b in zip(vals, vals[1:]):
        out.append(out[-1] + sdiff(b, a))
    return out


def _fmt_t(sec):
    if sec is None:
        return "?"
    sec = max(0.0, sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return "%d:%02d:%06.3f" % (int(h), int(m), s)


def _median(vals):
    if not vals:
        return 0
    v = sorted(vals)
    return v[len(v) // 2]


def _ts5(b, i):
    return (((b[i] >> 1) & 7) << 30) | (b[i + 1] << 22) | ((b[i + 2] >> 1) << 15) | \
           (b[i + 3] << 7) | (b[i + 4] >> 1)


def _pcr27(b, p):
    """PCR (27 MHz) a 6 bajtos mezőből, p = a PCR első bájtja."""
    base = (b[p] << 25) | (b[p + 1] << 17) | (b[p + 2] << 9) | (b[p + 3] << 1) | (b[p + 4] >> 7)
    ext = ((b[p + 4] & 1) << 8) | b[p + 5]
    return base * 300 + ext


def _pes_hdr(b, p, end):
    """PES fejléc: (stream_id, pts|None, dts|None, elemi adat kezdete) vagy None."""
    if end - p < 6 or b[p] != 0 or b[p + 1] != 0 or b[p + 2] != 1:
        return None
    sid = b[p + 3]
    if sid in NOHDR_SIDS:
        return sid, None, None, p + 6
    if end - p < 9 or (b[p + 6] & 0xC0) != 0x80:
        return None
    fl = (b[p + 7] >> 6) & 3
    hl = b[p + 8]
    pts = dts = None
    if (fl & 2) and end - p >= 14:
        pts = _ts5(b, p + 9)
    if fl == 3 and end - p >= 19:
        dts = _ts5(b, p + 14)
    return sid, pts, dts, p + 9 + hl


def _unesc(b):
    """H.264 emulációs bájtok (00 00 03) eltávolítása."""
    out = bytearray()
    z = 0
    for x in b:
        if z >= 2 and x == 3:
            z = 0
            continue
        out.append(x)
        z = z + 1 if x == 0 else 0
    return bytes(out)


def _nals(b):
    """Annex B NAL-egységek: (fejlécbájt indexe, a következő start kód indexe)."""
    out = []
    i = b.find(b"\x00\x00\x01")
    while i >= 0:
        h = i + 3
        j = b.find(b"\x00\x00\x01", h)
        if h < len(b):
            out.append((h, j if j >= 0 else len(b)))
        i = j
    return out


def _fold(entry, row):
    """Egy bejegyzés (időbélyeg, méretek...) összevonása további PES-adatokkal."""
    return (entry[0],) + tuple(a + b for a, b in zip(entry[1:], row))


class _Bits:
    """Bitolvasó (u = fix szélesség, ue / se = Exp-Golomb)."""
    __slots__ = ("d", "p", "n")

    def __init__(self, d):
        self.d = d
        self.p = 0
        self.n = len(d) * 8

    def u(self, k):
        v = 0
        for _ in range(k):
            if self.p >= self.n:
                raise IndexError("bit")
            v = (v << 1) | ((self.d[self.p >> 3] >> (7 - (self.p & 7))) & 1)
            self.p += 1
        return v

    def ue(self):
        z = 0
        while self.u(1) == 0:
            z += 1
            if z > 31:
                raise ValueError("ue")
        return (1 << z) - 1 + self.u(z)

    def se(self):
        k = self.ue()
        return (k + 1) // 2 if k & 1 else -(k // 2)


def _crc16_table():
    tab = []
    for i in range(256):
        c = i << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x8005) if (c & 0x8000) else (c << 1)
            c &= 0xFFFF
        tab.append(c)
    return tab


_AC3_CRC_TAB = _crc16_table()


def _ac3_crc_ok(fr):
    """AC-3 keret CRC-ellenőrzése (a 2. bájttól a keret végéig a maradék 0)."""
    crc = 0
    tab = _AC3_CRC_TAB
    for x in fr[2:]:
        crc = ((crc << 8) & 0xFFFF) ^ tab[(crc >> 8) ^ x]
    return crc == 0


# -------------------------------------------------------- H.264 / MPEG-2 ----

def _parse_sps(raw):
    """H.264 SPS (a NAL-fejléc utáni RBSP). Hibás/csonka részre részleges eredményt ad."""
    res = {}
    try:
        r = _Bits(_unesc(raw))
        prof = r.u(8)
        r.u(8)
        lvl = r.u(8)
        r.ue()
        cf, sep, bdl, bdc = 1, 0, 8, 8
        res.update(profile=prof, level=lvl)
        if prof in _HIGH_PROFILES:
            cf = r.ue()
            if cf == 3:
                sep = r.u(1)
            bdl = r.ue() + 8
            bdc = r.ue() + 8
            r.u(1)
            if r.u(1):
                for i in range(8 if cf != 3 else 12):
                    if r.u(1):
                        size = 16 if i < 6 else 64
                        last = nxt = 8
                        for _ in range(size):
                            if nxt != 0:
                                nxt = (last + r.se() + 256) % 256
                            last = nxt if nxt else last
        res.update(chroma=cf, sep=sep, bit_luma=bdl, bit_chroma=bdc)
        r.ue()
        poc = r.ue()
        res["poc_type"] = poc
        if poc == 0:
            r.ue()
        elif poc == 1:
            r.u(1)
            r.se()
            r.se()
            for _ in range(r.ue()):
                r.se()
        res["refs"] = r.ue()
        r.u(1)
        wmb = r.ue() + 1
        hmu = r.ue() + 1
        fmo = r.u(1)
        if not fmo:
            r.u(1)
        r.u(1)
        crop = (0, 0, 0, 0)
        if r.u(1):
            crop = (r.ue(), r.ue(), r.ue(), r.ue())
        cat = 0 if sep else cf
        sub_w = 1 if cat in (0, 3) else 2
        sub_h = 2 if cat == 1 else 1
        cux = 1 if cat == 0 else sub_w
        cuy = (2 - fmo) if cat == 0 else sub_h * (2 - fmo)
        w = wmb * 16 - (crop[0] + crop[1]) * cux
        h = (2 - fmo) * hmu * 16 - (crop[2] + crop[3]) * cuy
        res.update(width=w, height=h, interlaced=not fmo)
        res["crop"] = crop
        if r.u(1):
            if r.u(1):
                ar = r.u(8)
                if ar == 255:
                    res["sar"] = (r.u(16), r.u(16))
                else:
                    res["sar_idc"] = ar
            if r.u(1):
                r.u(1)
            if r.u(1):
                res["video_format"] = r.u(3)
                res["full_range"] = r.u(1)
                if r.u(1):
                    res["primaries"] = r.u(8)
                    res["transfer"] = r.u(8)
                    res["matrix"] = r.u(8)
            if r.u(1):
                r.ue()
                r.ue()
            if r.u(1):
                nut = r.u(32)
                ts = r.u(32)
                res["fixed_rate"] = bool(r.u(1))
                res["num_units"] = nut
                res["time_scale"] = ts
                if nut:
                    res["vui_fps"] = ts / (2.0 * nut)
    except (IndexError, ValueError):
        pass
    return res


def _mpeg2_seq(b, i):
    w = (b[i + 4] << 4) | (b[i + 5] >> 4)
    h = ((b[i + 5] & 15) << 8) | b[i + 6]
    fr = b[i + 7] & 15
    return {"width": w, "height": h, "fps": _MPEG2_FPS.get(fr)}


# ------------------------------------------------------------ audio fejlécek --

def _ac3_hdr(b, j):
    if j + 8 > len(b):
        return None
    fscod = b[j + 4] >> 6
    frm = b[j + 4] & 63
    bsid = b[j + 5] >> 3
    if fscod > 2 or frm > 37 or bsid > 10:
        return None
    kbps = _AC3_KBPS[frm >> 1]
    if fscod == 0:
        words = kbps * 2
    elif fscod == 1:
        words = (kbps * 960) // 441 + (frm & 1)
    else:
        words = kbps * 3
    r = _Bits(bytes(b[j + 6:j + 9]))
    acmod = r.u(3)
    if (acmod & 1) and acmod != 1:
        r.u(2)
    if acmod & 4:
        r.u(2)
    if acmod == 2:
        r.u(2)
    lfe = r.u(1)
    return {"size": words * 2, "samples": 1536, "fs": (48000, 44100, 32000)[fscod],
            "ch": "%d.%d" % (_NCH[acmod], lfe), "kbps": kbps, "codec": "ac3"}


def _eac3_hdr(b, j):
    if j + 6 > len(b):
        return None
    bsid = b[j + 5] >> 3
    if bsid < 11 or bsid > 16:
        return None
    frmsiz = ((b[j + 2] & 7) << 8) | b[j + 3]
    fscod = b[j + 4] >> 6
    if fscod == 3:
        fs = (24000, 22050, 16000)[(b[j + 4] >> 4) & 3]
        nblk = 6
    else:
        fs = (48000, 44100, 32000)[fscod]
        nblk = (1, 2, 3, 6)[(b[j + 4] >> 4) & 3]
    acmod = (b[j + 4] >> 1) & 7
    lfe = b[j + 4] & 1
    return {"size": (frmsiz + 1) * 2, "samples": nblk * 256, "fs": fs,
            "ch": "%d.%d" % (_NCH[acmod], lfe), "kbps": None, "codec": "eac3"}


def _mpa_hdr(b, j):
    if j + 4 > len(b):
        return None
    ver = (b[j + 1] >> 3) & 3
    lay = (b[j + 1] >> 1) & 3
    bri = b[j + 2] >> 4
    sri = (b[j + 2] >> 2) & 3
    pad = (b[j + 2] >> 1) & 1
    if ver == 1 or lay in (0, 3) or bri in (0, 15) or sri == 3:
        return None
    layer = 4 - lay
    if layer == 1:          # Layer I nincs a táblázatban: nem támogatott, nem keret
        return None
    grp = 1 if ver == 3 else 2
    kbps = _MPA_BR[(grp, layer)][bri - 1]
    fs = _MPA_SR[ver][sri]
    spf = 1152 if (layer == 2 or ver == 3) else 576
    size = spf * kbps * 125 // fs + pad
    ch = 1 if (b[j + 3] >> 6) == 3 else 2
    return {"size": size, "samples": spf, "fs": fs, "ch": str(ch), "kbps": kbps,
            "codec": "mp2" if layer == 2 else "mp3"}


def _adts_hdr(b, j):
    if j + 7 > len(b) or (b[j + 1] & 0xF6) != 0xF0:
        return None
    sf = (b[j + 2] >> 2) & 15
    if sf > 12:
        return None
    size = ((b[j + 3] & 3) << 11) | (b[j + 4] << 3) | (b[j + 5] >> 5)
    if size < 7:
        return None
    ch = ((b[j + 2] & 1) << 2) | (b[j + 3] >> 6)
    return {"size": size, "samples": 1024 * ((b[j + 6] & 3) + 1), "fs": _ADTS_SF[sf],
            "ch": str(ch), "kbps": None, "codec": "aac"}


_HDR_FN = {"ac3": _ac3_hdr, "eac3": _eac3_hdr, "mpa": _mpa_hdr, "aac": _adts_hdr}


def _audio_frames(codec, b, start=0):
    """Keretek a hang-PES adatából a 'start' eltolástól: [(állapot 'ok'|'cut', eltolás, fejléc)].
    'cut' = a keret a PES végén kezdődik és a következő PES-ben folytatódik."""
    out = []
    fn = _HDR_FN[codec]
    n = len(b)
    i = start
    while i < n - 6:
        if codec in ("ac3", "eac3"):
            j = b.find(b"\x0b\x77", i)
            if j < 0:
                break
        else:
            j = b.find(b"\xff", i)
            if j < 0 or j >= n - 1:
                break
            if codec == "aac" and (b[j + 1] & 0xF6) != 0xF0:
                i = j + 1
                continue
            if codec == "mpa" and (b[j + 1] & 0xE0) != 0xE0:
                i = j + 1
                continue
        h = fn(b, j)
        if h is None:
            i = j + 1
            continue
        if j + h["size"] > n:
            out.append(("cut", j, h))
            break
        out.append(("ok", j, h))
        i = j + h["size"]
    return out


# --------------------------------------------------------------- jelentés ----

class Section:
    def __init__(self, title):
        self.title = title
        self.rows = []

    def add(self, key, value, lvl=None):
        self.rows.append((key, value, lvl))


class Report:
    """Az elemzés eredménye: szakaszok (adatlap) és a talált problémák."""

    def __init__(self, path):
        self.path = path
        self.sections = []
        self.problems = []           # (szint 'E' / 'W', szöveg)
        self.notes = []              # ami NEM vizsgálható (korlátok)
        self.basic_only = False      # csak alapadatok készültek (nincs szerkezeti ellenőrzés)

    def sec(self, title):
        s = Section(title)
        self.sections.append(s)
        return s

    def problem(self, lvl, text):
        self.problems.append((lvl, text))

    @property
    def verdict(self):
        if any(l == "E" for l, _ in self.problems):
            return "E"
        if any(l == "W" for l, _ in self.problems):
            return "W"
        return "OK"

    def verdict_text(self):
        v = self.verdict
        if v == "OK" and self.basic_only:
            return L("Nem talált hibát, de csak alapadatok készültek – szerkezeti ellenőrzés nem történt",
                     "No errors found, but only basic data was read – no structural check was done")
        if v == "E":
            return L("HIBÁS – ne használd véglegesként; a hibák az Ellenőrzési eredményben vannak",
                     "FAULTY – do not use as final; see the verification result")
        if v == "W":
            return L("Használható, de van figyelmeztetés", "Usable, with warnings")
        return L("Hibátlan – nem találtam szerkezeti vagy időzítési hibát",
                 "No structural or timing errors found")

    def to_text(self):
        mark = {"E": "[HIBA]", "W": "[FIG] ", "OK": "[OK]  "}
        lines = ["Lossless Video Toolkit – %s %s" % (L("Videó-elemző", "Video analyzer"), __version__),
                 "%s: %s" % (L("Fájl", "File"), self.path), ""]
        for s in self.sections:
            lines.append("== %s ==" % s.title)
            w = max([len(k) for k, _, _ in s.rows] or [0])
            for k, v, lvl in s.rows:
                lines.append("  %s %-*s  %s" % (mark.get(lvl, "      "), w, k, v))
            lines.append("")
        lines.append("== %s ==" % L("Ellenőrzési eredmény", "Verification result"))
        lines.append("  " + self.verdict_text())
        for lvl, text in self.problems:
            lines.append("  %s %s" % (mark[lvl], text))
        if self.notes:
            lines.append("")
            lines.append("== %s ==" % L("Korlátok (mit nem vizsgál ez az elemző)",
                                        "Limits (what this analyzer does not check)"))
            for n in self.notes:
                lines.append("  - " + n)
        return "\n".join(lines) + "\n"


# ----------------------------------------------------------- TS mélyelemzés ----

def _detect_ts(head):
    for ps, h in ((192, 4), (188, 0)):
        n = (len(head) - h) // ps
        if n >= 3 and all(head[h + k * ps] == 0x47 for k in range(min(n, 16))):
            return ps, h
    return None


class TsDeep:
    """MPEG-TS / M2TS teljes elemzése: PSI, csomagszint, PES, képek, GOP, hang, PCR, folytonosság."""

    def __init__(self, path, size, ps, H):
        self.path = path
        self.size = size
        self.ps = ps
        self.H = H
        self.pmt = None
        self.pcr_pid = None
        self.prog = None
        self.streams = []            # (pid, stype, leírás, típus)
        self.vpid = None
        self.vcodec = None
        self.apids = []
        self.apid_set = set()
        self.acodec = {}
        self.vau = []                # (dts, pts, méret, kulcs, idr, képtípus, sps, pps, rec)
        self.aau = {}                # pid -> [(pts, méret, képkeretek, minták, crc_vizsgált, crc_hibás, határhiba)]
        self.ainfo = {}              # pid -> első fejléc
        self.aseq = {}
        self.a_nots = Counter()
        self.apend = {}              # pid -> átnyúló keret hátralévő bájtjai
        self._apre = {}              # pid -> PTS nélküli PES-ek összegyűjtött adatai
        self.pcrs = []               # (27 MHz, megszakítás-jelző)
        self.pst = {}                # pid -> statisztika
        self.total = 0
        self.nulls = 0
        self.scrambled = 0
        self.sync_err = 0
        self.sync_at = []
        self.pes_bad = Counter()
        self.base = None             # az első videó-időbélyeg (90 kHz)
        self.now = None              # az aktuális videó-időbélyeg (90 kHz)
        self.sps = None
        self.sps_raw = None
        self.pps_seen = False
        self.seq = None              # MPEG-2 sorozatfejléc
        self.first_pcr = None

    # ---- PSI: PAT / PMT ----
    def psi(self, f):
        ps, H = self.ps, self.H
        f.seek(0)
        data = f.read(2 * 1024 * 1024)
        sec = {}
        pmt_pid = None
        for k in range(len(data) // ps):
            t = k * ps + H
            if data[t] != 0x47:
                continue
            pid = ((data[t + 1] & 0x1F) << 8) | data[t + 2]
            if pid != 0 and pid != pmt_pid:
                continue
            afc = (data[t + 3] >> 4) & 3
            if not afc & 1:
                continue
            pay = t + 4 if afc == 1 else t + 5 + data[t + 4]
            if pay >= t + 188:
                continue
            d = data[pay:t + 188]
            if data[t + 1] & 0x40:
                sec[pid] = bytearray(d[1 + d[0]:])
            elif pid in sec:
                sec[pid] += d
            else:
                continue
            s = sec[pid]
            if len(s) < 3:
                continue
            ln = ((s[1] & 0x0F) << 8) | s[2]
            if len(s) < 3 + ln:
                continue
            body = bytes(s[:3 + ln])
            sec.pop(pid, None)
            if pid == 0:
                i = 8
                while i + 4 <= 3 + ln - 4:
                    prog_no = (body[i] << 8) | body[i + 1]
                    if prog_no:
                        pmt_pid = ((body[i + 2] & 0x1F) << 8) | body[i + 3]
                        if self.prog is None:
                            self.prog = prog_no
                        break
                    i += 4
                self.pmt = pmt_pid
            else:
                self.pcr_pid = ((body[8] & 0x1F) << 8) | body[9]
                pil = ((body[10] & 0x0F) << 8) | body[11]
                i = 12 + pil
                while i + 5 <= 3 + ln - 4:
                    st = body[i]
                    spid = ((body[i + 1] & 0x1F) << 8) | body[i + 2]
                    eil = ((body[i + 3] & 0x0F) << 8) | body[i + 4]
                    name, kind = _STREAM_TYPES.get(st, ("0x%02X" % st, "other"))
                    self.streams.append((spid, st, name, kind))
                    if kind == "video" and self.vpid is None and st in (0x1B, 0x24, 0x02, 0x01, 0xEA):
                        self.vpid = spid
                        self.vcodec = {0x1B: "h264", 0x24: "hevc", 0x02: "mpeg2", 0x01: "mpeg2"}.get(st, "other")
                    elif kind == "audio":
                        if spid not in self.apid_set:
                            self.apids.append(spid)
                            self.apid_set.add(spid)
                            self.acodec[spid] = _AUDIO_CODEC.get(st, "other")
                    i += 5 + eil
                break
        return self.pmt is not None and self.pcr_pid is not None

    # ---- teljes, csomagonkénti szkennelés ----
    def _st(self, pid):
        s = self.pst.get(pid)
        if s is None:
            s = self.pst[pid] = {"pkts": 0, "cc": None, "err": [], "dup": 0, "pes": 0, "bad": 0}
        return s

    def _when(self):
        if self.now is None or self.base is None:
            return "?"
        return _fmt_t(sdiff(self.now, self.base) / 90000.0)

    def scan(self, f, progress, cancel):
        ps, H = self.ps, self.H
        vpid, pcr_pid = self.vpid, self.pcr_pid
        cur = {}
        f.seek(0)
        pos = 0
        pktno = 0
        cap_v = AU_SCAN
        while True:
            if cancel is not None and cancel.is_set():
                raise AnalyzeCancelled()
            data = f.read(ps * CHUNK_PKTS)
            if not data:
                break
            pos += len(data)
            n = len(data) // ps
            for k in range(n):
                t = k * ps + H
                if data[t] != 0x47:
                    self.sync_err += 1
                    if len(self.sync_at) < 20:
                        self.sync_at.append(pktno + k)
                    continue
                b1 = data[t + 1]
                pusi = b1 & 0x40
                pid = ((b1 & 0x1F) << 8) | data[t + 2]
                b3 = data[t + 3]
                tsc = b3 >> 6
                afc = (b3 >> 4) & 3
                cc = b3 & 15
                self.total += 1
                if pid == 0x1FFF:
                    self.nulls += 1
                    continue
                s = self._st(pid)
                s["pkts"] += 1
                if tsc:
                    self.scrambled += 1
                    continue
                discont = False
                pay = -1
                if afc & 2:
                    afl = data[t + 4]
                    if afl:
                        fl = data[t + 5]
                        discont = bool(fl & 0x80)
                        if (fl & 0x10) and afl >= 7 and pid == pcr_pid:
                            self.pcrs.append((_pcr27(data, t + 6), discont))
                            if self.first_pcr is None:
                                self.first_pcr = self.pcrs[-1][0]
                    if (afc & 1) and t + 5 + afl < t + 188:
                        pay = t + 5 + afl
                elif afc & 1:
                    pay = t + 4
                if afc & 1:
                    if s["cc"] is not None and not discont:
                        if cc == s["cc"]:
                            s["dup"] += 1
                        elif cc != ((s["cc"] + 1) & 15):
                            if len(s["err"]) < 1000:
                                s["err"].append(self._when())
                    s["cc"] = cc
                if pay < 0:
                    continue
                if pid == vpid or pid in self.apid_set:
                    end = t + 188
                    if pusi:
                        prev = cur.pop(pid, None)
                        if prev is not None:
                            self._flush(pid, prev)
                        s["pes"] += 1
                        h = _pes_hdr(data, pay, end)
                        if h is None:
                            s["bad"] += 1
                            self.pes_bad[pid] += 1
                            au = {"buf": bytearray(), "pts": None, "dts": None, "size": 0,
                                  "cap": cap_v if pid == vpid else AUDIO_CAP}
                        else:
                            sid, pts, dts, es0 = h
                            au = {"buf": bytearray(), "pts": pts, "dts": dts, "size": 0,
                                  "cap": cap_v if pid == vpid else AUDIO_CAP}
                            if pid == vpid and (pts is not None or dts is not None):
                                ts = dts if dts is not None else pts
                                if self.base is None:
                                    self.base = ts
                                self.now = ts
                            chunk = data[es0:end] if es0 < end else b""
                            au["size"] += len(chunk)
                            au["buf"] += chunk[:au["cap"]]
                        if h is None:
                            chunk = data[pay:end]
                            au["size"] += len(chunk)
                            au["buf"] += chunk[:au["cap"]]
                        cur[pid] = au
                    else:
                        au = cur.get(pid)
                        if au is not None:
                            chunk = data[pay:t + 188]
                            au["size"] += len(chunk)
                            room = au["cap"] - len(au["buf"])
                            if room > 0:
                                au["buf"] += chunk[:room]
                elif pid == pcr_pid or pid == 0 or pid == self.pmt:
                    pass
            pktno += n
            progress(min(0.99, pos / float(max(1, self.size))))
        for pid, au in cur.items():
            self._flush(pid, au)
        progress(1.0)

    def _flush(self, pid, au):
        if pid == self.vpid:
            self._video_au(au)
        else:
            self._audio_au(pid, au)

    # ---- videó hozzáférési egység ----
    def _video_au(self, au):
        b = bytes(au["buf"])
        t = au["dts"] if au["dts"] is not None else au["pts"]
        if t is None:
            return
        p = au["pts"] if au["pts"] is not None else t
        key, idr, st, sps, pps, rec = self._vinfo(b)
        self.vau.append((t, p, au["size"], key, idr, st, sps, pps, rec))

    def _vinfo(self, b):
        c = self.vcodec
        if c == "h264":
            key = idr = sps = pps = rec = False
            st = "?"
            first = True
            for h, e in _nals(b):
                typ = b[h] & 0x1F
                if typ == 7:
                    sps = True
                    if self.sps_raw is None:
                        self.sps_raw = bytes(b[h + 1:e])
                elif typ == 8:
                    pps = True
                elif typ == 6:
                    if h + 1 < len(b) and b[h + 1] == 6:
                        rec = True
                elif typ in (1, 5):
                    if typ == 5:
                        idr = True
                    if first:
                        first = False
                        try:
                            r = _Bits(_unesc(bytes(b[h + 1:h + 24])))
                            r.ue()
                            stype = r.ue() % 5
                        except (IndexError, ValueError):
                            stype = -1
                        st = {0: "P", 1: "B", 2: "I", 3: "P", 4: "I"}.get(stype, "?")
            key = idr or st == "I"
            return key, idr, st, sps, pps, rec
        if c == "mpeg2":
            key = False
            st = "?"
            i = b.find(b"\x00\x00\x01\x00")
            if i >= 0 and i + 6 <= len(b):
                pt = (b[i + 5] >> 3) & 7
                st = {1: "I", 2: "P", 3: "B"}.get(pt, "?")
                key = pt == 1
            if self.seq is None:
                j = b.find(b"\x00\x00\x01\xb3")
                if j >= 0 and j + 8 <= len(b):
                    self.seq = _mpeg2_seq(b, j)
            return key, key, st, False, False, False
        if c == "hevc":
            key = idr = sps = pps = False
            for h, e in _nals(b):
                typ = (b[h] >> 1) & 0x3F
                if 16 <= typ <= 21:
                    key = True
                    idr = idr or typ in (19, 20)
                elif typ == 33:
                    sps = True
                elif typ == 34:
                    pps = True
            return key, idr, "?", sps, pps, False
        return False, False, "?", False, False, False

    # ---- hang hozzáférési egység ----
    def _audio_au(self, pid, au):
        """Egy hang-PES feldolgozása. A PTS nélküli PES (a PTS-t csak ritkán kell adni) keretei
        az előző bejegyzéshez adódnak, így a hosszúság és a rés-vizsgálat helyes marad."""
        codec = self.acodec.get(pid, "other")
        b = bytes(au["buf"])
        seq = self.aseq.get(pid, 0)
        self.aseq[pid] = seq + 1
        nfr = samples = chk = bad = hdrbad = 0
        first = None
        trunc = au["size"] > len(b)          # a puffer levágta: a határ nem ellenőrizhető
        pend = self.apend.get(pid, 0)        # az előző PES-ből átnyúló keret hátralévő bájtjai
        newpend = 0
        if codec in _HDR_FN:
            if pend >= len(b):
                newpend = pend - len(b) if not trunc else 0
            else:
                frames = _audio_frames(codec, b, pend)
                if not trunc and frames and frames[0][1] != pend:
                    hdrbad += 1              # a PES nem a várt kerethatáron kezdődik
                if not trunc and not frames:
                    hdrbad += 1
                for kind, j, h in frames:
                    if first is None:
                        first = h
                    nfr += 1
                    samples += h["samples"]  # a határon átnyúló keret ahhoz a PES-hez számít, ahol kezdődik
                    if kind == "cut":
                        if not trunc:
                            newpend = h["size"] - (len(b) - j)
                        break
                    if codec == "ac3" and seq % CRC_STEP == 0:
                        chk += 1
                        if not _ac3_crc_ok(b[j:j + h["size"]]):
                            bad += 1
            if first is not None and pid not in self.ainfo:
                self.ainfo[pid] = dict(first)
        self.apend[pid] = newpend
        row = [au["size"], nfr, samples, chk, bad, hdrbad]
        t = au["pts"] if au["pts"] is not None else au["dts"]
        lst = self.aau.setdefault(pid, [])
        pre = self._apre.pop(pid, None)
        if t is None:
            self.a_nots[pid] += 1
            if lst:
                lst[-1] = _fold(lst[-1], row)
            else:
                self._apre[pid] = row if pre is None else [x + y for x, y in zip(pre, row)]
            return
        if pre is not None:
            row = [x + y for x, y in zip(pre, row)]
        lst.append((t,) + tuple(row))

    # ---- levezetések és jelentés ----
    def _vid_stats(self):
        V = self.vau
        n = len(V)
        out = {"n": n}
        if n == 0:
            return out
        D = _unwrap([v[0] for v in V])
        P = _unwrap([v[1] for v in V])
        deltas = [D[i] - D[i - 1] for i in range(1, n)]
        pos = [d for d in deltas if d > 0]
        fd = _median(pos)
        out["fd"] = fd
        out["D"], out["P"] = D, P
        out["dup"] = sum(1 for d in deltas if d == 0)
        out["gap"] = sum(1 for d in deltas if fd and d > 1.5 * fd)
        tol = max(3, fd // 50) if fd else 3
        out["irr"] = sum(1 for d in deltas if fd and 0 < abs(d - fd) > tol and d <= 1.5 * fd)
        out["reorder"] = sum(1 for i in range(1, n) if P[i] < P[i - 1])
        offs = [sdiff(v[1], v[0]) for v in V]
        out["pts_lt_dts"] = sum(1 for o in offs if o < 0)
        out["b_present"] = len(set(offs)) > 1 or out["reorder"] > 0
        out["off_min"] = min(offs)
        out["off_max"] = max(offs)
        dur_ticks = (max(P) - min(P)) + (fd or 0)
        out["dur"] = dur_ticks / 90000.0
        out["fps"] = (90000.0 / fd) if fd else None
        out["bytes"] = sum(v[2] for v in V)
        out["sizes"] = {"all": [v[2] for v in V]}
        cnt = Counter(v[5] for v in V)
        out["types"] = cnt
        out["idr"] = sum(1 for v in V if v[4])
        out["key_idx"] = [i for i, v in enumerate(V) if v[3]]
        out["open_i"] = sum(1 for v in V if v[3] and not v[4] and v[5] == "I")
        out["first_key"] = V[0][3]
        # IDR-képnél kötelező a SPS/PPS a belépési ponthoz (vágás, keresés); nem IDR I-kép (nyitott GOP) nem.
        out["sps_missing"] = sum(1 for v in V if v[4] and not v[6]) if self.vcodec == "h264" else 0
        out["pps_missing"] = sum(1 for v in V if v[4] and not v[7]) if self.vcodec == "h264" else 0
        out["rec_sei"] = sum(1 for v in V if v[8])
        return out

    def _audio_stats(self, pid, vst):
        R = self.aau.get(pid, [])
        codec = self.acodec.get(pid, "other")
        info = self.ainfo.get(pid, {})
        fs = info.get("fs")
        res = {"n_au": len(R), "codec": codec, "info": info}
        if not R:
            return res
        T = _unwrap([r[0] for r in R])
        res["bytes"] = sum(r[1] for r in R)
        res["frames"] = sum(r[2] for r in R)
        res["samples"] = sum(r[3] for r in R)
        res["chk"] = sum(r[4] for r in R)
        res["crc_bad"] = sum(r[5] for r in R)
        res["hdrbad"] = sum(r[6] for r in R)
        res["first_pts"] = R[0][0]
        if fs and res["samples"]:
            res["dur"] = res["samples"] / float(fs)
            res["kbps"] = res["bytes"] * 8 / res["dur"] / 1000.0
            gaps_w = gaps_e = 0
            worst = 0.0
            internal = 0
            for i in range(1, len(R)):
                prev_s = R[i - 1][3]
                if not prev_s:
                    continue
                exp = T[i - 1] + prev_s * 90000.0 / fs
                g = T[i] - exp
                fr = (info.get("samples", 1536)) * 90000.0 / fs
                if abs(g) > fr / 2.0 + 2:
                    if abs(g) > 90000:
                        gaps_e += 1
                    else:
                        gaps_w += 1
                    worst = max(worst, abs(g))
            res.update(gap_w=gaps_w, gap_e=gaps_e, gap_worst=worst)
            # a hang belső órájának eltérése: tényleges és elvárt különbség (az utolsó PES előtt)
            if len(R) > 1:
                actual = T[-1] - T[0]
                expect = sum(r[3] for r in R[:-1]) * 90000.0 / fs
                res["internal_ms"] = (actual - expect) / 90.0
        else:
            res["dur"] = None
            res["kbps"] = None
        return res

    def report(self, rep):
        ps = self.ps
        dur_fallback = None
        V = self._vid_stats()
        dur = V.get("dur") or 0.0
        if not dur:
            ts_all = [r[0] for r in self.aau.get(next(iter(self.aau), -1), [])] if self.aau else []
            if len(ts_all) > 1:
                dur = (ts_all[-1] - ts_all[0]) / 90000.0
        if not dur and self.base is not None and self.now is not None:
            dur = max(0.0, sdiff(self.now, self.base) / 90000.0)
        self._section_general(rep, dur)
        self._section_video(rep, V)
        self._section_gop(rep, V)
        self._section_timing(rep, V)
        self._section_audio(rep, V)
        self._section_av(rep, V)
        self._section_integrity(rep)
        rep.notes.extend([
            L("A hang tartalma (hangerő, kattanás, szinkron a tartalommal) dekódolás nélkül nem vizsgálható.",
              "The audio content (loudness, clicks, lip sync) cannot be checked without decoding."),
            L("HEVC esetén a sorozat-paraméterkészlet részletei (SPS/VUI) nincs ebben a verzióban.",
              "For HEVC the sequence parameter set details (SPS/VUI) are not parsed in this version."),
            L("Az ellenőrzés a teljes fájlt végigolvassa; nagy fájlnál (több GB) percekig tarthat.",
              "The check reads the whole file; large files (several GB) may take minutes."),
        ])

    def _section_general(self, rep, dur):
        s = rep.sec(L("Általános", "General"))
        s.add(L("Fájlméret", "File size"), L("%.2f MB (%d bájt)", "%.2f MB (%d bytes)") % (self.size / 1048576.0, self.size))
        s.add(L("Konténer", "Container"), "MPEG-TS, %s%s" % (
            L("M2TS (192 bájtos csomag, időbélyeggel)", "M2TS (192-byte packets, with timestamp)") if self.ps == 192 else L("TS (188 bájtos csomag)", "TS (188-byte packets)"), ""))
        s.add(L("Hossz (megjelenítési idő)", "Duration (presentation)"), "%s (%.3f s)" % (_fmt_t(dur), dur))
        if dur:
            s.add(L("Teljes bitráta", "Total bitrate"), "%.0f kbps" % (self.size * 8 / dur / 1000.0))
        s.add(L("Csomagok száma", "Packets"), "%d" % self.total)
        if self.total:
            s.add(L("Üres (null) csomagok aránya", "Null packets"),
                  "%.1f %%" % (100.0 * self.nulls / self.total))
        s.add(L("Program / PMT / PCR PID", "Program / PMT / PCR PID"),
              "%s / 0x%X / 0x%X" % (self.prog, self.pmt or 0, self.pcr_pid or 0))
        for pid, st, name, kind in self.streams:
            s2 = self.pst.get(pid, {})
            rate = ""
            if dur and s2.get("pkts"):
                rate = " – %.0f kbps" % (s2["pkts"] * self.ps * 8 / dur / 1000.0)
            s.add(L("Folyam 0x%X" % pid, "Stream 0x%X" % pid), "%s (%s)%s" % (name, kind, rate))
        if self.vpid is None:
            rep.problem("E", L("Nincs videó-folyam a fájlban.", "No video stream in the file."))

    def _section_video(self, rep, V):
        s = rep.sec(L("Videó", "Video"))
        if self.vpid is None:
            return
        sp = _parse_sps(self.sps_raw) if self.sps_raw else {}
        codec_name = {"h264": "H.264/AVC", "hevc": "H.265/HEVC", "mpeg2": "MPEG-2"}.get(self.vcodec, "?")
        if self.vcodec == "h264" and sp.get("profile") is not None:
            prof = _PROFILE_NAMES.get(sp["profile"], str(sp["profile"]))
            lvl = sp.get("level", 0)
            s.add(L("Kodek", "Codec"), "%s, %s, level %d.%d" % (codec_name, prof, lvl // 10, lvl % 10))
        elif self.vcodec == "mpeg2" and self.seq:
            s.add(L("Kodek", "Codec"), "MPEG-2 video")
        else:
            s.add(L("Kodek", "Codec"), codec_name)
        if sp.get("width"):
            s.add(L("Felbontás (vágás után)", "Resolution (after cropping)"),
                  "%dx%d" % (sp["width"], sp["height"]))
        elif self.seq:
            s.add(L("Felbontás", "Resolution"), "%dx%d" % (self.seq["width"], self.seq["height"]))
        if sp:
            cat = {0: "4:0:0", 1: "4:2:0", 2: "4:2:2", 3: "4:4:4"}.get(sp.get("chroma"), "?")
            bits = sp.get("bit_luma", 8)
            s.add(L("Mintavétel / bitmélység", "Chroma / bit depth"), "%s, %d bit" % (cat, bits))
            s.add(L("Letapogatás", "Scan"), L("soros (interlaced)", "interlaced") if sp.get("interlaced")
                  else L("progresszív", "progressive"))
            if sp.get("refs") is not None:
                s.add(L("Referenciaképek (max.)", "Max reference frames"), str(sp["refs"]))
            s.add(L("Képsorrend (POC típus)", "Picture order (POC type)"), str(sp.get("poc_type")))
            if "vui_fps" in sp:
                s.add(L("Képfrekvencia (VUI)", "Frame rate (VUI)"), "%.3f fps" % sp["vui_fps"])
            if "sar" in sp or "sar_idc" in sp:
                s.add(L("Képarány-pixel (SAR)", "Pixel aspect (SAR)"),
                      "%s" % (sp.get("sar") or "idc %s" % sp.get("sar_idc")))
            tr_ = sp.get("transfer")
            if "primaries" in sp:
                hdr = ""
                if tr_ in (16, 18):
                    hdr = L(" (HDR: PQ/HLG)", " (HDR: PQ/HLG)")
                s.add(L("Színinformáció (primer/átvitel/mátrix)", "Colour (primaries/transfer/matrix)"),
                      "%s / %s / %s%s" % (sp["primaries"], tr_, sp["matrix"], hdr))
                s.add(L("Tartomány", "Range"), L("teljes (0–255)", "full (0–255)") if sp.get("full_range")
                      else L("korlátozott (16–235)", "limited (16–235)"))
        if V.get("fps"):
            s.add(L("Mért képfrekvencia (időbélyegből)", "Measured frame rate (from timestamps)"),
                  L("%.3f fps (%d ticks/kép)", "%.3f fps (%d ticks/frame)") % (V["fps"], V["fd"]))
            if sp.get("vui_fps") and abs(sp["vui_fps"] - V["fps"]) > 0.05 * V["fps"]:
                rep.problem("W", L("A VUI képfrekvencia (%.3f) eltér a mért időbélyegektől (%.3f).",
                                   "VUI frame rate (%.3f) differs from the measured timestamps (%.3f).")
                                % (sp["vui_fps"], V["fps"]))
                s.add(L("Képfrekvencia-eltérés", "Frame rate mismatch"), L("igen", "yes"), "W")
        if V.get("n"):
            s.add(L("Képek (hozzáférési egységek) száma", "Pictures (access units)"), "%d" % V["n"])
            s.add(L("Videó-bitráta", "Video bitrate"),
                  "%.0f kbps" % (V["bytes"] * 8 / V["dur"] / 1000.0) if V["dur"] else "?")
            sz = V["sizes"]["all"]
            s.add(L("Képméret min / átlag / max", "Picture size min / avg / max"),
                  L("%d / %d / %d bájt", "%d / %d / %d bytes") % (min(sz), sum(sz) // len(sz), max(sz)))
            t = V["types"]
            s.add(L("Képtípusok (I / P / B / egyéb)", "Picture types (I / P / B / other)"),
                  "%d / %d / %d / %d" % (t.get("I", 0), t.get("P", 0), t.get("B", 0),
                                         sum(v for k, v in t.items() if k not in "IPB"))
                  )
            s.add(L("B-képek (visszacsatolt sorrend)", "B-pictures (reordering)"),
                  L("igen", "yes") if V["b_present"] else L("nincs", "none"))
            s.add(L("IDR (teljes) kulcskockák", "IDR (full) key frames"), "%d" % V["idr"])
            if self.vcodec == "h264":
                if V["sps_missing"] or V["pps_missing"]:
                    rep.problem("W", L(
                        "%d IDR-képnél hiányzik az SPS és/vagy PPS – vágásnál / más pontról indított "
                        "lejátszásnál hibás lehet." % max(V["sps_missing"], V["pps_missing"]),
                        "%d IDR pictures lack the SPS and/or PPS – cutting or starting playback there "
                        "may fail." % max(V["sps_missing"], V["pps_missing"])))
                    s.add(L("SPS/PPS az IDR-képeknél", "SPS/PPS at IDR pictures"),
                          L("HIÁNYZIK (%d)", "MISSING (%d)") % max(V["sps_missing"], V["pps_missing"]), "W")
                else:
                    s.add(L("SPS/PPS az IDR-képeknél", "SPS/PPS at IDR pictures"),
                          L("rendben, minden IDR-nél megvan", "OK, present at every IDR"), "OK")
            if sp.get("primaries") is None and self.vcodec == "h264":
                s.add(L("Színinformáció", "Colour info"), L("nincs megadva (VUI)", "not signalled (VUI)"))

    def _section_gop(self, rep, V):
        if not V.get("n"):
            return
        s = rep.sec(L("GOP és keresés", "GOP and seeking"))
        keys = V["key_idx"]
        fd = V.get("fd") or 0
        s.add(L("Kulcskockák (I-képek) száma", "Key frames (I pictures)"), "%d" % len(keys))
        if not keys:
            rep.problem("E", L("Nincs kulcskocka – a fájl nem indítható közepéről.",
                               "No key frame – the file cannot be started from the middle."))
            return
        lens = [b - a for a, b in zip(keys, keys[1:])]
        if lens:
            gmin, gmax = min(lens), max(lens)
            gavg = sum(lens) / float(len(lens))
            sec = (lambda n: n * fd / 90000.0) if fd else (lambda n: 0.0)
            s.add(L("GOP-hossz képben min / átlag / max", "GOP length in pictures min / avg / max"),
                  "%d / %.1f / %d" % (gmin, gavg, gmax))
            s.add(L("GOP-hossz másodpercben min / átlag / max", "GOP length in seconds min / avg / max"),
                  "%.2f s / %.2f s / %.2f s" % (sec(gmin), sec(gavg), sec(gmax)), None)
            top = Counter(lens).most_common(3)
            s.add(L("Leggyakoribb GOP-hosszok", "Most common GOP lengths"),
                  ", ".join(L("%d kép ×%d", "%d frames ×%d") % (k, c) for k, c in top))
            gmax_s = sec(gmax)
            if gmax_s >= GOP_ERR_S:
                s.add(L("Keresési késleltetés (becslés)", "Seek latency (estimate)"),
                      L("kb. %.1f s – nagyon lassú keresés" % (gmax_s / 2.0),
                        "approx. %.1f s – very slow seeking" % (gmax_s / 2.0)), "E")
                rep.problem("E", L(
                    "A leghosszabb GOP %.2f s: a kereséskor ennyit kell várni (a lejátszó a legközelebbi "
                    "kulcskockára ugrik). Javítás: rövidebb GOP-pal (kb. 0,5 s) kódolj újra." % gmax_s,
                    "The longest GOP is %.2f s: seeking waits for the nearest key frame. "
                    "Fix: re-encode with a shorter GOP (about 0.5 s)." % gmax_s))
            elif gmax_s > GOP_WARN_S:
                s.add(L("Keresési késleltetés (becslés)", "Seek latency (estimate)"),
                      L("kb. %.1f s" % (gmax_s / 2.0), "approx. %.1f s" % (gmax_s / 2.0)), "W")
                rep.problem("W", L("A leghosszabb GOP %.2f s – a keresés észrevehetően lassú lehet." % gmax_s,
                                   "The longest GOP is %.2f s – seeking may be noticeably slow." % gmax_s))
            else:
                s.add(L("Keresési késleltetés (becslés)", "Seek latency (estimate)"),
                      L("kb. %.2f s – rendben" % (gmax_s / 2.0), "approx. %.2f s – OK" % (gmax_s / 2.0)), "OK")
        else:
            s.add(L("GOP", "GOP"), L("csak egy kulcskocka van", "only one key frame"))
        s.add(L("Első kép kulcskocka?", "First picture is a key frame?"),
              L("igen", "yes") if V["first_key"] else L("nem", "no"), None if V["first_key"] else "W")
        if not V["first_key"]:
            rep.problem("W", L("A fájl nem kulcskockával kezdődik.", "The file does not start with a key frame."))
        if V["open_i"]:
            s.add(L("Nyitott GOP (nem IDR I-kép)", "Open GOP (non-IDR I picture)"), "%d" % V["open_i"], "W")
        if V["rec_sei"]:
            s.add(L("Visszaállási pont (SEI)", "Recovery point (SEI)"), "%d" % V["rec_sei"])

    def _section_timing(self, rep, V):
        s = rep.sec(L("Időzítés", "Timing"))
        if not V.get("n"):
            return
        s.add(L("Első DTS / PTS (fájl-időbélyeg)", "First DTS / PTS (file timestamp)"),
              "%s / %s" % (_fmt_t(V["D"][0] / 90000.0), _fmt_t(V["P"][0] / 90000.0)))
        s.add(L("Megjelenítési sorrend (PTS-tartomány)", "Presentation range (PTS)"),
              "%.3f s" % (V["dur"]))
        s.add(L("PTS−DTS eltolás (min / max)", "PTS−DTS offset (min / max)"),
              "%.1f ms / %.1f ms" % (V["off_min"] / 90.0, V["off_max"] / 90.0))
        if V["pts_lt_dts"]:
            rep.problem("E", L("%d képnél a PTS kisebb a DTS-nél (lejátszási hiba).",
                               "%d pictures have PTS < DTS (playback error).") % V["pts_lt_dts"])
            s.add(L("PTS < DTS", "PTS < DTS"), "%d" % V["pts_lt_dts"], "E")
        if V.get("fd"):
            s.add(L("DTS-lépések", "DTS steps"),
                  L("ismétlődő: %d, kihagyott: %d, szabálytalan: %d",
                    "duplicate: %d, gap: %d, irregular: %d") % (V["dup"], V["gap"], V["irr"]),
                  "E" if (V["dup"] or V["gap"]) else ("W" if V["irr"] else "OK"))
            if V["gap"] or V["dup"]:
                rep.problem("E", L("%d ismétlődő és %d kihagyott képkocka a DTS-ben (rángatás).",
                                   "%d duplicate and %d skipped frames in the DTS (judder).")
                            % (V["dup"], V["gap"]))
            elif V["irr"]:
                rep.problem("W", L("%d szabálytalan képidő-lépés.", "%d irregular frame-time steps.") % V["irr"])
        if V["reorder"]:
            s.add(L("Visszacsatolt képsorrend (PTS ugrás)", "Reordered pictures (PTS jumps back)"),
                  "%d" % V["reorder"])
        # PCR
        pc = self.pcrs
        if pc:
            vals = [v for v, _ in pc]
            d = [b - a for a, b in zip(vals, vals[1:])]
            jumps_nf = sum(1 for (v, dc), dd in zip(pc[1:], d) if (dd < 0 or dd > PCR_JUMP) and not dc)
            flagged = sum(1 for _, dc in pc if dc)
            pos_d = [x for x in d if x > 0]
            if pos_d:
                s.add(L("PCR-minták / átlagos köz / max köz",
                        "PCR samples / avg interval / max interval"),
                      "%d / %.1f ms / %.1f ms" % (len(pc), sum(pos_d) / len(pos_d) / 27000.0,
                                                  max(pos_d) / 27000.0))
            s.add(L("PCR-ugrás jelzés nélkül", "PCR jump without flag"),
                  "%d" % jumps_nf, "E" if jumps_nf else "OK")
            if jumps_nf:
                rep.problem("E", L("%d PCR-ugrás jelzés nélkül (egyes lejátszók megakadhatnak)."
                                   , "%d PCR jumps without discontinuity flag (some players may stall).")
                            % jumps_nf)
            if flagged:
                s.add(L("PCR megszakítás-jelzővel", "PCR with discontinuity flag"), "%d" % flagged)
            if self.first_pcr is not None and V["P"]:
                s.add(L("PCR − első PTS", "PCR − first PTS"),
                      "%.1f ms" % (sdiff(self.first_pcr // 300, V["P"][0]) / 90.0))

    def _section_audio(self, rep, V):
        if not self.apids:
            s = rep.sec(L("Hang", "Audio"))
            s.add(L("Hangsáv", "Audio track"), L("nincs", "none"), "W")
            rep.problem("W", L("Nincs hangsáv a fájlban.", "No audio track in the file."))
            return
        for pid in self.apids:
            st = self._audio_stats(pid, V)
            info = st.get("info", {})
            name = {"ac3": "AC-3", "eac3": "E-AC-3", "mpa": "MPEG audio", "aac": "AAC (ADTS)"}.get(
                st["codec"], st["codec"])
            s = rep.sec(L("Hang 0x%X – %s", "Audio 0x%X – %s") % (pid, name))
            if not st["n_au"]:
                s.add(L("Tartalom", "Content"), L("nincs hang-PES", "no audio PES"), "E")
                rep.problem("E", L("A 0x%X hangsávban nincs adat." % pid, "Audio 0x%X has no data." % pid))
                continue
            if info:
                ch = info.get("ch", "?")
                s.add(L("Csatornák", "Channels"), ch)
                s.add(L("Mintavételezés", "Sample rate"), "%d Hz" % info.get("fs", 0))
            if st.get("kbps"):
                s.add(L("Átlagos bitráta", "Average bitrate"), "%.0f kbps" % st["kbps"])
            if st.get("dur"):
                s.add(L("Hossz (hang)", "Length (audio)"), "%s (%.3f s)" % (_fmt_t(st["dur"]), st["dur"]))
            s.add(L("Hang-PES / keretek", "Audio PES / frames"), "%d / %d" % (st["n_au"], st.get("frames", 0)))
            if st["codec"] == "ac3" and st.get("chk"):
                ok = st["chk"] - st["crc_bad"]
                s.add(L("AC-3 CRC (mintavétel)", "AC-3 CRC (sampled)"),
                      L("%d ellenőrizve, %d hibás", "%d checked, %d bad") % (st["chk"], st["crc_bad"]),
                      "E" if st["crc_bad"] else "OK")
                if st["crc_bad"]:
                    rep.problem("E", L("0x%X: %d sérült AC-3 keret (kattogás)." % (pid, st["crc_bad"]),
                                       "0x%X: %d damaged AC-3 frames (clicks)." % (pid, st["crc_bad"])))
            if st.get("hdrbad"):
                s.add(L("Keretdetektálási hiba", "Frame detection error"), "%d" % st["hdrbad"], "W")
                rep.problem("W", L("0x%X: %d hang-PES nem keretdetektálható határon kezdődik."
                                   % (pid, st["hdrbad"]),
                                   "0x%X: %d audio PES do not start on a frame boundary."
                                   % (pid, st["hdrbad"])))
            if st.get("gap_w") is not None:
                s.add(L("Hangrés/átfedés a PES-határokon (kis)", "Audio gap/overlap at PES boundaries (small)"),
                      "%d (max %.1f ms)" % (st["gap_w"], st["gap_worst"] / 90.0) if st["gap_w"] else "0",
                      "W" if st["gap_w"] else "OK")
                s.add(L("Hangrés (> 1 s)", "Audio gap (> 1 s)"), "%d" % st["gap_e"],
                      "E" if st["gap_e"] else "OK")
                if st["gap_e"]:
                    rep.problem("E", L("0x%X: %d nagy hangrés (> 1 s)." % (pid, st["gap_e"]),
                                       "0x%X: %d large audio gaps (> 1 s)." % (pid, st["gap_e"])))
                if st["gap_w"]:
                    rep.problem("W", L("0x%X: %d kis hangrés/átfedés a PES-határoknál."
                                       % (pid, st["gap_w"]),
                                       "0x%X: %d small audio gaps/overlaps at PES boundaries."
                                       % (pid, st["gap_w"])))
            if st.get("internal_ms") is not None:
                lv = "W" if abs(st["internal_ms"]) > 40 else "OK"
                s.add(L("Hang belső órájának eltérése", "Internal audio clock deviation"),
                      "%+.1f ms" % st["internal_ms"], lv)
            if self.pes_bad.get(pid):
                rep.problem("W", L("0x%X: %d hibás PES-fejléc." % (pid, self.pes_bad[pid]),
                                   "0x%X: %d bad PES headers." % (pid, self.pes_bad[pid])))
            if self.a_nots.get(pid):
                s.add(L("Időbélyeg nélküli PES", "PES without timestamp"), "%d" % self.a_nots[pid], "W")
            self._audio_cache = getattr(self, "_audio_cache", {})
            self._audio_cache[pid] = st

    def _section_av(self, rep, V):
        s = rep.sec(L("A/V szinkron", "A/V sync"))
        if not V.get("n") or not self.apids:
            s.add(L("Szinkron", "Sync"), L("nem értékelhető", "not assessable"))
            return
        first_v = V["P"][0]
        pid = self.apids[0]
        R = self.aau.get(pid, [])
        if not R:
            return
        # A küszöbök: W > 80 ms (kb. 2 kép 25 fps-nél), E > 200 ms.
        a0 = R[0][0]
        start_ms = sdiff(a0, first_v) / 90.0
        rep.av_start_ms = start_ms          # a „A/V igazítás” gomb ezt használja
        lv = "E" if abs(start_ms) > 200 else ("W" if abs(start_ms) > 80 else "OK")
        s.add(L("Hang kezdete a kép kezdetéhez képest", "Audio start relative to first picture"),
              L("%+.1f ms (+ = a hang később szól)", "%+.1f ms (+ = audio plays later)") % start_ms, lv)
        if lv == "E":
            rep.problem("E", L("Kezdeti A/V eltolás: %+.1f ms." % start_ms,
                               "Initial A/V offset: %+.1f ms." % start_ms))
        elif lv == "W":
            rep.problem("W", L("Kezdeti A/V eltolás: %+.1f ms." % start_ms,
                               "Initial A/V offset: %+.1f ms." % start_ms))
        a_u = _unwrap([r[0] for r in R])
        v_span = (max(V["P"]) - min(V["P"]))
        a_span = a_u[-1] - a_u[0]
        drift = (a_span - v_span) / 90.0
        lv = "E" if abs(drift) > 200 else ("W" if abs(drift) > 80 else "OK")
        s.add(L("A/V relatív csúszás a fájl során", "A/V relative drift over the file"),
              "%+.1f ms" % drift, lv)
        if lv == "E":
            rep.problem("E", L("A/V csúszás a fájl során: %+.1f ms." % drift,
                               "A/V drift over the file: %+.1f ms." % drift))
        elif lv == "W":
            rep.problem("W", L("Kismértékű A/V csúszás: %+.1f ms." % drift,
                               "Slight A/V drift: %+.1f ms." % drift))

    def _section_integrity(self, rep):
        s = rep.sec(L("Folytonosság és integritás", "Continuity and integrity"))
        s.add(L("Szinkronvesztések (0x47)", "Sync losses (0x47)"), "%d" % self.sync_err,
              "E" if self.sync_err else "OK")
        if self.sync_err:
            rep.problem("E", L("%d szinkronvesztés (pl. 0x%s csomagnál: %s)." % (
                self.sync_err, "47", ", ".join(str(x) for x in self.sync_at[:5])),
                "%d sync losses (e.g. at packets: %s)." % (self.sync_err, ", ".join(str(x) for x in self.sync_at[:5]))))
        s.add(L("Titkosított csomagok", "Scrambled packets"), "%d" % self.scrambled,
              "E" if self.scrambled else "OK")
        if self.scrambled:
            rep.problem("E", L("%d titkosított csomag – a fájl nem játszható le szabadon.",
                               "%d scrambled packets – the file is not freely playable.") % self.scrambled)
        total_err = 0
        for pid in sorted(self.pst):
            p = self.pst[pid]
            name = {0: "PAT", self.pmt: "PMT"}.get(pid) or next(
                (n for q, _, n, _ in self.streams if q == pid), "PID")
            errs = p["err"]
            total_err += len(errs)
            lvl = "E" if errs else ("W" if p["dup"] else "OK")
            txt = L("%d csomag, %d CC-hiba, %d ismétlődő", "%d packets, %d CC errors, %d duplicates") % (
                p["pkts"], len(errs), p["dup"])
            if errs:
                txt += L(" – első: %s", " – first: %s") % ", ".join(errs[:3])
            s.add("PID 0x%X (%s)" % (pid, name), txt, lvl)
            if errs:
                rep.problem("E", L("PID 0x%X: %d folytonossági (CC) hiba – csomag esett ki vagy ismétlődött."
                                   % (pid, len(errs)),
                                   "PID 0x%X: %d continuity (CC) errors – packet lost or repeated."
                                   % (pid, len(errs))))
            elif p["dup"]:
                rep.problem("W", L("PID 0x%X: %d ismétlődő csomag." % (pid, p["dup"]),
                                   "PID 0x%X: %d duplicate packets." % (pid, p["dup"])))
        if not self.pst:
            s.add(L("Csomagok", "Packets"), L("nincs adat", "no data"))


# ------------------------------------------------------------- belépési pont --

def _basic_from_probe(path, core, rep, size, progress):
    """Nem TS fájl: az ffprobe-adatok (a panel probe_json hívásával) alapján az alapadatok."""
    try:
        info = core.probe_json(path)
    except Exception as e:
        rep.problem("E", L("Az ffprobe nem adott adatot: %s" % e, "ffprobe gave no data: %s" % e))
        return rep
    progress(0.5)
    rep.basic_only = True
    fm = info.get("format") or {}
    s = rep.sec(L("Általános (ffprobe)", "General (ffprobe)"))
    s.add(L("Fájlméret", "File size"), "%.2f MB" % (size / 1048576.0))
    try:
        dur = float(fm.get("duration") or 0)
    except (TypeError, ValueError):
        dur = 0.0
    if dur:
        s.add(L("Hossz", "Duration"), "%s (%.3f s)" % (_fmt_t(dur), dur))
    s.add(L("Konténer", "Container"), str(fm.get("format_long_name") or fm.get("format_name") or "?"))
    streams = info.get("streams", [])
    vs = [x for x in streams if x.get("codec_type") == "video"]
    au = [x for x in streams if x.get("codec_type") == "audio"]
    if not vs:
        rep.problem("E", L("Nincs videófolyam a fájlban.", "No video stream in the file."))
    for v in vs[:1]:
        s.add(L("Videó", "Video"), "%s %sx%s, %s, %s" % (v.get("codec_name"), v.get("width"), v.get("height"),
                                                       v.get("pix_fmt", ""), v.get("avg_frame_rate", "")))
    for a in au:
        s.add(L("Hang", "Audio"), "%s, %s ch, %s Hz" % (a.get("codec_name"), a.get("channels"),
                                                       a.get("sample_rate")))
    if not au:
        s.add(L("Hang", "Audio"), L("nincs", "none"), "W")
    rep.notes.append(L("Ehhez a formátumhoz nincs saját szerkezeti ellenőrzés; az adatok az ffprobe-ból származnak.",
                       "This format has no own structural check; the data comes from ffprobe."))
    progress(1.0)
    return rep


# ----------------------------------------------- szerkezeti ellenőrzés: MP4 / MKV / MPG / VOB ----

_JM = None      # a joiner modul (lazy betöltés)


def _joiner(core=None):
    """A joiner egyfájlos elemzői: az átadott modul, különben a mellette lévő mts_joiner.py."""
    global _JM
    need = ("Mp4Info", "MkvInfo", "MpgInfo", "VobInfo", "MsgError")
    for m in (core, sys.modules.get("mts_joiner"), _JM):
        if m is not None and all(hasattr(m, a) for a in need):
            return m
    try:
        d = os.path.dirname(os.path.abspath(__file__))
        if d not in sys.path:
            sys.path.insert(0, d)
        import mts_joiner as jm
    except Exception:       # noqa
        return None
    _JM = jm
    return jm


def _sniff(path):
    """A fájltípus a tartalom alapján: avi / mp4 / mkv / mpg / vob / None."""
    try:
        with open(path, "rb") as f:
            h = f.read(12)
    except OSError:
        return None
    if h[:4] == b"RIFF" and h[8:12] == b"AVI ":
        return "avi"
    if h[4:8] in (b"ftyp", b"moov", b"mdat", b"free", b"wide", b"skip"):
        return "mp4"
    if h[:4] == b"\x1a\x45\xdf\xa3":
        return "mkv"
    if h[:4] == b"\x00\x00\x01\xba":
        return "vob" if os.path.splitext(path)[1].lower() == ".vob" else "mpg"
    return None


def _joiner_report(path, jm, kind, rep, size, progress, cancel):
    cls = {"mp4": jm.Mp4Info, "mkv": jm.MkvInfo, "mpg": jm.MpgInfo, "vob": jm.VobInfo}[kind]
    label = {"mp4": "MP4 / MOV", "mkv": "MKV / WebM", "mpg": "MPEG-PS (MPG)", "vob": "DVD VOB"}[kind]
    inf = cls(path)
    progress(0.05)
    try:
        inf.analyze()
    except jm.MsgError as e:
        rep.problem("E", str(e))
        rep.sec(L("Általános", "General")).add(L("Fájlméret", "File size"), "%.2f MB" % (size / 1048576.0))
        return rep
    except Exception as e:      # noqa
        rep.problem("E", L("Belső hiba a szerkezeti ellenőrzésben: %s" % e, "Internal error in the structural check: %s" % e))
        return rep
    progress(0.9)
    rep.basic_only = False
    s = rep.sec(L("Általános", "General"))
    s.add(L("Fájlméret", "File size"), "%.2f MB" % (size / 1048576.0))
    s.add(L("Konténer", "Container"), label)
    if inf.duration:
        s.add(L("Hossz", "Duration"), "%s (%.3f s)" % (_fmt_t(inf.duration), inf.duration))
    for lab_hu, lab_en, meth in (("Videó", "Video", "vdesc"), ("Hang", "Audio", "adesc")):
        try:
            s.add(L(lab_hu, lab_en), str(getattr(inf, meth)()))
        except Exception:       # noqa
            pass
    c = rep.sec(L("Szerkezeti ellenőrzés (saját kód)", "Structural check (own code)"))
    c.add(L("Állapot", "Status"), L("nincs szerkezeti hiba", "no structural error"), "OK")
    rep.notes.append(_CONT_NOTES[kind])
    progress(1.0)
    return rep


_CONT_NOTES = {
    "mp4": L("MP4 / MOV: a doboz-szerkezet, a méretek és a mintatáblák összhangja (darabszám, időzítés, kulcskockák), "
              "a mintaadatok az mdat-on belül ellenőrzöttek; a titkosított és a darabolt (fragmentált) MP4 elutasítva. "
              "A képminőséget nem értékeli; a dekódolást a külső ffmpeg-ellenőrzés adja, ha elérhető.",
              "MP4 / MOV: box structure, sizes and sample-table consistency (counts, timing, key frames) and sample data "
              "inside the mdat are checked; encrypted and fragmented MP4 are rejected. Picture quality is not assessed; "
              "decoding is done by the external ffmpeg check, if available."),
    "mkv": L("MKV / WebM: az EBML- és Segment/Cluster-szerkezet, a méretek, a sávleírás és az első blokkok időbélyege "
              "ellenőrzött; a titkosítás jelzése is. A keresőindex (Cues) tartalmát nem vizsgáljuk. A blokkok bájtjait "
              "a saját kód nem dekódolja; a dekódolást a külső ffmpeg-ellenőrzés végzi, ha elérhető.",
              "MKV / WebM: EBML and Segment/Cluster structure, sizes, track description and the timestamps of the first "
              "blocks are checked, as well as encryption flags. The seek index (Cues) content is not checked. The block "
              "bytes are not decoded by the built-in code; decoding is done by the external ffmpeg check, if available."),
    "mpg": L("MPEG-PS: a csomagszerkezet, a rendszerréteg, a videófolyam-fejléc, az SCR/PTS-időzítés és a DVD NAV-csomagok "
              "ellenőrzöttek. A képminőséget nem értékeli; a dekódolást a külső ffmpeg-ellenőrzés adja, ha elérhető.",
              "MPEG-PS: packet structure, system layer, video sequence header, SCR/PTS timing and DVD NAV packets are "
              "checked. Picture quality is not assessed; decoding is done by the external ffmpeg check, if available."),
}
_CONT_NOTES["vob"] = _CONT_NOTES["mpg"]


# ----------------------------------------------- szerkezeti ellenőrzés: AVI (RIFF) ----

_AVI_DATA_SUFFIX = (b"dc", b"db", b"wb", b"tx", b"pc")
_AVI_FORMATS = {0x0001: "PCM", 0x0055: "MP3", 0x2000: "AC-3", 0x00FF: "AAC", 0x0161: "WMA", 0x0162: "WMA Pro"}


class _AviErr(Exception):
    pass


def _avi_iter(f, p, end):
    """(azonosító, adat-kezdet, adat-méret, fejléc-pozíció) a [p, end) tartomány chunkjain."""
    while p + 8 <= end:
        f.seek(p)
        h = f.read(8)
        if len(h) < 8:
            break
        cc = h[:4]
        sz = struct.unpack("<I", h[4:8])[0]
        ds = p + 8
        if ds + sz > end:
            raise _AviErr(L("A(z) „%s” chunk (@%d, %d bájt) túlnyúlik a szülő blokkon: csonkolt vagy sérült fájl."
                            % (cc.decode("latin-1", "replace"), p, sz),
                            "Chunk „%s” (@%d, %d bytes) runs past its parent block: truncated or damaged file."
                            % (cc.decode("latin-1", "replace"), p, sz)))
        yield cc, ds, sz, p
        p = ds + sz + (sz & 1)


def _avi_rd(f, pos, n):
    f.seek(pos)
    return f.read(n)


class AviInfo:
    def __init__(self, path):
        self.path = path
        self.size = 0
        self.streams = []         # {type, handler, comp, scale, rate, length, w, h, fmt, ch, sr, n, bytes}
        self.avih = None          # (dwTotalFrames, dwStreams, dwWidth, dwHeight, dwMicroSecPerFrame)
        self.dmlh = None          # OpenDML összes képkocka
        self.has_indx = False
        self.movi_base = None     # a „movi” azonosító pozíciója
        self.movi_chunks = 0
        self.unknown_stream = 0
        self.idx = None           # (adat-kezdet, méret)
        self.idx_entries = 0
        self.idx_base_name = ""
        self.issues = []          # (szint, szöveg)

    def issue(self, lvl, text):
        self.issues.append((lvl, text))

    def analyze(self, progress=None, cancel=None):
        progress = progress or (lambda x: None)
        self.size = os.path.getsize(self.path)
        with open(self.path, "rb") as f:
            h = _avi_rd(f, 0, 12)
            if len(h) < 12 or h[:4] != b"RIFF" or h[8:12] != b"AVI ":
                self.issue("E", L("Nem AVI fájl (hiányzik a RIFF / AVI fejléc).", "Not an AVI file (RIFF / AVI header missing)."))
                return False
            first_end = 8 + struct.unpack("<I", h[4:8])[0]
            if first_end > self.size:
                self.issue("E", L("A RIFF-méret (%d bájt) nagyobb a fájlnál (%d bájt): a fájl csonkolt."
                                  % (first_end, self.size),
                                  "The RIFF size (%d bytes) is larger than the file (%d bytes): the file is truncated."
                                  % (first_end, self.size)))
                return False
            last_end = 0
            try:
                for cc, ds, sz, hp in _avi_iter(f, 0, self.size):
                    if cc != b"RIFF":
                        continue
                    lt = _avi_rd(f, ds, 4)
                    last_end = ds + sz
                    if lt in (b"AVI ", b"AVIX"):
                        self._walk(f, ds + 4, ds + sz, progress, cancel)
                    progress(min(0.9, ds / float(max(1, self.size))))
            except _AviErr as e:
                self.issue("E", str(e))
                return False
            if last_end < self.size:
                self.issue("W", L("A RIFF-blokkok után %d bájt van, amit az AVI-szerkezet nem fed le."
                                  % (self.size - last_end),
                                  "%d bytes follow the RIFF blocks and are not covered by the AVI structure."
                                  % (self.size - last_end)))
            return self._check(f, progress, cancel)

    def _walk(self, f, p, end, progress, cancel):
        for cc, ds, sz, hp in _avi_iter(f, p, end):
            if cc == b"LIST":
                lt = _avi_rd(f, ds, 4)
                if lt == b"hdrl":
                    self._hdrl(f, ds + 4, ds + sz)
                elif lt == b"movi":
                    if self.movi_base is None:
                        self.movi_base = ds
                    self._movi(f, ds + 4, ds + sz, cancel)
                elif lt == b"odml":
                    for c2, d2, s2, h2 in _avi_iter(f, ds + 4, ds + sz):
                        if c2 == b"dmlh" and s2 >= 4:
                            self.dmlh = struct.unpack("<I", _avi_rd(f, d2, 4))[0]
            elif cc == b"idx1" and self.idx is None:
                self.idx = (ds, sz)

    def _hdrl(self, f, p, end):
        for cc, ds, sz, hp in _avi_iter(f, p, end):
            if cc == b"avih" and sz >= 40 and self.avih is None:
                d = _avi_rd(f, ds, 40)
                us, _mbps, _pad, _fl, total, _init, nstr, _sugg, w, hgt = struct.unpack("<10I", d)
                self.avih = (total, nstr, w, hgt, us)
            elif cc == b"LIST" and _avi_rd(f, ds, 4) == b"strl":
                self._strl(f, ds + 4, ds + sz)

    def _strl(self, f, p, end):
        st = {"type": b"", "handler": b"", "comp": b"", "scale": 1, "rate": 0, "length": 0,
              "w": 0, "h": 0, "fmt": 0, "ch": 0, "sr": 0, "n": 0, "bytes": 0}
        for cc, ds, sz, hp in _avi_iter(f, p, end):
            if cc == b"strh" and sz >= 36:
                d = _avi_rd(f, ds, 36)
                st["type"], st["handler"] = d[0:4], d[4:8]
                st["scale"], st["rate"], _start, st["length"] = struct.unpack("<IIII", d[20:36])
                st["scale"] = st["scale"] or 1
            elif cc == b"strf" and sz >= 16:
                d = _avi_rd(f, ds, min(sz, 40))
                if st["type"] == b"vids":
                    st["w"], st["h"] = struct.unpack("<ii", d[4:12])
                    st["comp"] = d[16:20]
                elif st["type"] == b"auds":
                    st["fmt"], st["ch"], st["sr"] = struct.unpack("<HHI", d[0:8])
            elif cc == b"indx":
                self.has_indx = True
        self.streams.append(st)

    def _movi(self, f, p, end, cancel):
        for cc, ds, sz, hp in _avi_iter(f, p, end):
            if cancel is not None and self.movi_chunks % 2000 == 0 and cancel.is_set():
                raise AnalyzeCancelled()
            if cc == b"LIST":
                if _avi_rd(f, ds, 4) == b"rec ":
                    self._movi(f, ds + 4, ds + sz, cancel)
                continue
            if len(cc) == 4 and cc[:2].isdigit() and cc[2:] in _AVI_DATA_SUFFIX:
                self.movi_chunks += 1
                n = int(cc[:2])
                if n < len(self.streams):
                    st = self.streams[n]
                    st["n"] += 1
                    st["bytes"] += sz
                else:
                    self.unknown_stream += 1

    def _check(self, f, progress, cancel):
        if self.avih is None:
            self.issue("E", L("Hiányzik az avih fejléc (LIST hdrl / avih).", "The avih header is missing (LIST hdrl / avih)."))
            return False
        if self.movi_base is None:
            self.issue("E", L("Hiányzik az adatlista (LIST movi).", "The data list is missing (LIST movi)."))
            return False
        total, nstr, _w, _h, _us = self.avih
        if nstr != len(self.streams):
            self.issue("W", L("A fejléc %d streamet ír le, a fájlban %d van." % (nstr, len(self.streams)),
                              "The header describes %d streams, the file has %d." % (nstr, len(self.streams))))
        if self.unknown_stream:
            self.issue("E", L("%d adat-chunk olyan streamhez tartozik, amely nincs leírva a fejlécben." % self.unknown_stream,
                              "%d data chunks belong to a stream that is not described in the header." % self.unknown_stream))
        for i, st in enumerate(self.streams):
            if st["type"] != b"vids":
                continue
            frames = st["n"]
            if self.dmlh is None and total and total != frames:
                self.issue("W", L("Az avih %d képkockát ír, a fájlban %d van." % (total, frames),
                                  "avih says %d frames, the file has %d." % (total, frames)))
            if st["length"] and st["length"] != frames:
                self.issue("W", L("A(z) %d. videó fejléce (strh) %d képkockát ír, a fájlban %d van."
                                  % (i + 1, st["length"], frames),
                                  "Video %d header (strh) says %d frames, the file has %d."
                                  % (i + 1, st["length"], frames)))
        if self.dmlh is not None and self.streams:
            v = [st for st in self.streams if st["type"] == b"vids"]
            if v and self.dmlh != v[0]["n"]:
                self.issue("W", L("Az OpenDML dmlh %d képkockát ír, a fájlban %d van." % (self.dmlh, v[0]["n"]),
                                  "OpenDML dmlh says %d frames, the file has %d." % (self.dmlh, v[0]["n"])))
        if self.idx is None:
            if not self.has_indx:
                self.issue("W", L("Nincs idx1 index (és OpenDML indx sem): a lejátszó lassabban keres.",
                                  "No idx1 index (and no OpenDML indx): players seek more slowly."))
        else:
            self._check_idx(f, progress, cancel)
        return True

    def _check_idx(self, f, progress, cancel):
        ds, sz = self.idx
        if sz % 16:
            self.issue("E", L("Az idx1 mérete (%d) nem 16 bájt többszöröse." % sz,
                              "The idx1 size (%d) is not a multiple of 16 bytes." % sz))
            return
        n = sz // 16
        self.idx_entries = n
        data = _avi_rd(f, ds, sz)
        ents = [struct.unpack_from("<4sIII", data, 16 * k) for k in range(n)]
        if n != self.movi_chunks:
            self.issue("W", L("Az idx1 %d bejegyzést tartalmaz, a movi-ban %d adat-chunk van." % (n, self.movi_chunks),
                              "idx1 has %d entries, the movi list has %d data chunks." % (n, self.movi_chunks)))

        def ok(base, e):
            cc, _fl, off, size = e
            pos = base + off
            if pos < 0 or pos + 8 > self.size:
                return False
            h = _avi_rd(f, pos, 8)
            return len(h) == 8 and h[:4] == cc and struct.unpack("<I", h[4:8])[0] == size

        cands = [(self.movi_base, "movi"), (self.movi_base + 4, "movi+4"), (0, "file")]
        base = None
        for b, name in cands:
            if n and all(ok(b, e) for e in ents[:min(n, 50)]):
                base, self.idx_base_name = b, name
                break
        if base is None:
            self.issue("E", L("Az idx1 index nem mutat érvényes chunkokra: a fájl sérült vagy átírták.",
                              "The idx1 index does not point to valid chunks: the file is damaged or was rewritten."))
            return
        bad = [k for k, e in enumerate(ents) if not ok(base, e)]
        if bad:
            k = bad[0]
            self.issue("E", L("Az idx1 %d. bejegyzése nem egyezik a fájl chunkjával (összesen %d hibás bejegyzés)."
                              % (k + 1, len(bad)),
                              "idx1 entry %d does not match the file chunk (%d bad entries in total)."
                              % (k + 1, len(bad))))
        progress(0.98)

    def vdesc(self):
        v = [st for st in self.streams if st["type"] == b"vids"]
        if not v:
            return "?"
        st = v[0]
        comp = st["comp"] if st["comp"] not in (b"", b"\x00\x00\x00\x00") else st["handler"]
        fps = (st["rate"] / float(st["scale"])) if st["rate"] else 0.0
        return "%s %dx%d, %.3f fps" % (comp.decode("latin-1", "replace").strip() or "?", st["w"], st["h"], fps)

    def adesc(self):
        a = [st for st in self.streams if st["type"] == b"auds"]
        if not a:
            return L("nincs", "none")
        st = a[0]
        return "%s, %d ch, %d Hz" % (_AVI_FORMATS.get(st["fmt"], "0x%04X" % st["fmt"]), st["ch"], st["sr"])

    def duration(self):
        v = [st for st in self.streams if st["type"] == b"vids"]
        if v and v[0]["rate"] and v[0]["n"]:
            return v[0]["n"] * v[0]["scale"] / float(v[0]["rate"])
        return 0.0


def _avi_report(path, rep, size, progress, cancel):
    ai = AviInfo(path)
    ai.analyze(progress, cancel)
    progress(0.95)
    if ai.avih is not None:
        rep.basic_only = False
    s = rep.sec(L("Általános", "General"))
    s.add(L("Fájlméret", "File size"), "%.2f MB" % (size / 1048576.0))
    s.add(L("Konténer", "Container"), "AVI (RIFF)")
    d = ai.duration()
    if d:
        s.add(L("Hossz", "Duration"), "%s (%.3f s)" % (_fmt_t(d), d))
    if ai.avih is not None:
        s.add(L("Videó", "Video"), ai.vdesc())
        s.add(L("Hang", "Audio"), ai.adesc())
    c = rep.sec(L("Szerkezeti ellenőrzés (saját kód)", "Structural check (own code)"))
    c.add(L("Streamek", "Streams"), str(len(ai.streams)))
    c.add(L("Adat-chunkok (movi)", "Data chunks (movi)"), str(ai.movi_chunks))
    c.add(L("Index (idx1)", "Index (idx1)"),
          ("%d" % ai.idx_entries) if ai.idx is not None else L("nincs", "none"))
    errs = any(l == "E" for l, _ in ai.issues)
    c.add(L("Állapot", "Status"), L("hiba van", "errors found") if errs else
          L("nincs szerkezeti hiba", "no structural error"), "E" if errs else "OK")
    for lvl, text in ai.issues:
        rep.problem(lvl, text)
    rep.notes.append(L("AVI: a RIFF-szerkezet, a fejlécek, a streamek és az idx1 index összhangját ellenőrzi. "
                       "A képkockák tartalmát (kodek-szintű hibát) a saját kód nem dekódolja; a külső ffmpeg-ellenőrzés adja, ha elérhető.",
                       "AVI: checks the RIFF structure, the headers, the streams and the consistency of the idx1 index. "
                       "Frame content (codec-level errors) is not decoded by the built-in check; the external ffmpeg check covers it, if available."))
    progress(1.0)
    return rep


def _basic_report(path, core, rep, size, progress, cancel):
    """Nem TS fájl: szerkezeti ellenőrzés (MP4 / MKV / MPG / VOB: joiner, AVI: saját), különben az ffprobe-adatok."""
    kind = _sniff(path)
    if kind == "avi":
        return _avi_report(path, rep, size, progress, cancel)
    jm = _joiner(core) if kind in ("mp4", "mkv", "mpg", "vob") else None
    if jm is not None:
        return _joiner_report(path, jm, kind, rep, size, progress, cancel)
    if core is not None and not hasattr(core, "analyze_into") and hasattr(core, "probe_json"):
        return _basic_from_probe(path, core, rep, size, progress)
    if core is None:
        rep.problem("E", L("Nem MPEG-TS/M2TS fájl, és a joiner alapelemzője nem érhető el.",
                           "Not an MPEG-TS/M2TS file, and the joiner's base analyzer is not available."))
        return rep
    # A joiner alapelemzőjének hívása: a mezőneveket a getattr védi, hogy eltérés esetén
    # ne omoljon össze, csak a rész marad ki.
    try:
        inf = core.analyze_into(core.FileInfo(path))
    except Exception as e:
        rep.problem("E", L("A joiner alapelemzője hibát adott: %s" % e,
                           "The joiner's base analyzer failed: %s" % e))
        return rep
    progress(0.5)
    rep.basic_only = True
    s = rep.sec(L("Általános (alapadatok)", "General (basic data)"))
    s.add(L("Fájlméret", "File size"), "%.2f MB" % (size / 1048576.0))
    err = getattr(inf, "error", None)
    if err:
        rep.problem("E", str(err))
        s.add(L("Elemzés", "Analysis"), str(err), "E")
        return rep
    kind = getattr(inf, "kind", None)
    if kind:
        s.add(L("Típus", "Kind"), str(kind).upper())
    dur = getattr(inf, "duration", None)
    if dur:
        s.add(L("Hossz", "Duration"), "%s (%.3f s)" % (_fmt_t(dur), dur))
    for label_hu, label_en, meth in (("Videó", "Video", "vdesc"), ("Hang", "Audio", "adesc")):
        fn = getattr(inf, meth, None)
        if callable(fn):
            try:
                s.add(L(label_hu, label_en), str(fn()))
            except Exception:
                pass
    rep.notes.append(L("MP4 / MKV / MPG / VOB fájlnál a részletes GOP- és időzítés-elemzés ebben a verzióban "
                       "még nincs bekötve; az alapadatok a joiner elemzőjéből származnak.",
                       "Detailed GOP and timing analysis is not yet wired up for MP4 / MKV / MPG / VOB in this "
                       "version; basic data comes from the joiner's analyzer."))
    progress(1.0)
    return rep


# ------------------------------------------- külső ellenőrzés (ffmpeg/ffprobe) ----
# Az ffmpeg és az ffprobe KÜLSŐ PROGRAMKÉNT fut, a kódunk nem tartalmaz belőlük semmit.
# Ha nincs megtalálva, vagy a hoszt tiltja a külső programokat (EXTERNAL_OK = False),
# ez a rész nem fut, és a szerkezeti eredmény önmagában áll.

_TIMING_WORDS = ("timestamp", "dts", "pts", "monoton")
_EXT_GROUP_ERR = 5          # ennyi azonos típusú dekódolási hibától E, alatta W


def _ext_norm(msg):
    """Hibasor normalizálása a csoportosításhoz: címek, számok és a komponens-prefix egységesítése."""
    import re
    m = re.sub(r"0x[0-9a-fA-F]+", "0x#", msg)
    m = re.sub(r"\[(\w+) @ [^\]]*\]\s*", r"\1: ", m)
    m = re.sub(r"\d+", "#", m)
    m = re.sub(r"\s+", " ", m).strip()
    return m[:200]


def _ext_f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _ext_run(cmd, cancel=None, timeout=3600):
    """Külső parancs futtatása kimenettel; megszakítható. Visszatér: (kilépési kód, stdout)."""
    import subprocess
    import time
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                         errors="replace", **_hidden_kwargs())
    t0 = time.time()
    while True:
        try:
            out, _ = p.communicate(timeout=0.5)
            return p.returncode, out or ""
        except subprocess.TimeoutExpired:
            if cancel is not None and cancel.is_set():
                p.kill()
                p.communicate()
                raise AnalyzeCancelled()
            if time.time() - t0 > timeout:
                p.kill()
                p.communicate()
                return -1, ""


def _ext_duration(fp, src, cancel=None):
    try:
        rc, out = _ext_run([fp, "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", src], cancel, timeout=120)
        return float(out.strip().splitlines()[0]) if rc == 0 else 0.0
    except (AnalyzeCancelled, Exception):
        if cancel is not None and cancel.is_set():
            raise
        return 0.0


def _ext_decode(path, ff, dur, progress, cancel):
    """Teljes dekódolás ffmpeg-gel, kimenet nélkül (-f null). Visszatér: (képkockák, kód, hibasorok) vagy None."""
    import subprocess
    import tempfile
    cmd = [ff, "-hide_banner", "-nostdin", "-v", "warning", "-nostats",
           "-progress", "pipe:1", "-i", path,
           "-map", "0:v:0?", "-map", "0:a:0?", "-f", "null", "-"]
    errf = tempfile.TemporaryFile()
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errf,
                             stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                             errors="replace", **_hidden_kwargs())
    except OSError:
        errf.close()
        return None
    frames = 0
    try:
        for line in p.stdout:
            if cancel is not None and cancel.is_set():
                p.kill()
                p.wait()
                raise AnalyzeCancelled()
            k, _, v = line.strip().partition("=")
            if k == "frame" and v.isdigit():
                frames = int(v)
            elif k == "out_time_us" and dur > 0 and v.isdigit():
                progress(min(1.0, int(v) / 1e6 / dur))
        rc = p.wait()
        errf.seek(0)
        text = errf.read().decode("utf-8", "replace")
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
        p.stdout.close()
        errf.close()
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    return frames, rc, lines


def _ext_decode_section(path, ff, dur, s, rep, progress, cancel):
    res = _ext_decode(path, ff, dur, progress, cancel)
    if res is None:
        s.add(L("Dekódolás", "Decoding"), L("az ffmpeg nem indult el", "ffmpeg did not start"), "W")
        rep.problem("W", L("Az ffmpeg nem indult el, a dekódolás nem futott le.",
                           "ffmpeg did not start; decoding was not run."))
        return
    frames, rc, lines = res
    lines = [x for x in lines if not x.startswith("Last message repeated")]   # ismétlés, nem új hiba
    norm = Counter(_ext_norm(x) for x in lines)
    is_timing = lambda k: any(w in k.lower() for w in _TIMING_WORDS)
    dec_groups = [(k, n) for k, n in norm.most_common() if not is_timing(k)]
    tim_groups = [(k, n) for k, n in norm.most_common() if is_timing(k)]
    dec_n = sum(n for _, n in dec_groups)
    tim_n = sum(n for _, n in tim_groups)
    s.add(L("Dekódolt képkockák", "Decoded frames"), str(frames), None)
    if rc != 0:
        s.add(L("ffmpeg kilépési kódja", "ffmpeg exit code"), str(rc), "E")
    if dec_n == 0:
        s.add(L("Dekódolási hibák", "Decoding errors"), "0", "OK")
    else:
        worst = "E" if any(n >= _EXT_GROUP_ERR for _, n in dec_groups) else "W"
        s.add(L("Dekódolási hibák", "Decoding errors"), str(dec_n), worst)
    if tim_n:
        s.add(L("Időzítési üzenetek (ffmpeg)", "Timing messages (ffmpeg)"), str(tim_n), "W")
    if rc != 0 and not lines:
        rep.problem("E", L("Az ffmpeg %d kilépési kóddal, hibaüzenet nélkül állt le." % rc,
                           "ffmpeg exited with code %d and printed no message." % rc))
    shown = 0
    rest_lvl = None
    for k, n in dec_groups + tim_groups:
        if is_timing(k):
            lvl = "W"
            label = L("Időzítés", "Timing")
        else:
            lvl = "E" if n >= _EXT_GROUP_ERR else "W"
            label = L("Dekódolás", "Decoding")
        if shown < 8:
            rep.problem(lvl, "%s: %s (×%d)" % (label, k, n))
            shown += 1
        else:
            rest_lvl = "E" if (rest_lvl == "E" or lvl == "E") else "W"
    if rest_lvl is not None:
        rep.problem(rest_lvl, L("További hibatípusok is vannak (az összesítő sorban).",
                                "More error types exist (see the summary row)."))
    if rc == 0 and dec_n == 0 and tim_n == 0:
        s.add(L("Dekódolás eredménye", "Decoding result"), L("hibátlan", "clean"), "OK")


def _ext_timing_section(path, fp, s, rep, cancel):
    import statistics
    rc, out = _ext_run([fp, "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "packet=dts_time,duration_time", "-of", "csv=p=0", path], cancel)
    rows = []
    for line in out.splitlines():
        parts = line.strip().split(",")
        if not parts or not parts[0]:
            continue
        rows.append(_ext_f(parts[0]))
    if rc != 0 or not rows:
        s.add(L("Videó csomagok (ffprobe)", "Video packets (ffprobe)"), "0", "W")
        rep.problem("W", L("Az ffprobe nem olvasott videócsomagot.", "ffprobe read no video packets."))
        return
    dts = [d for d in rows if d is not None]
    missing = len(rows) - len(dts)
    diffs = [dts[i] - dts[i - 1] for i in range(1, len(dts))]
    pos = [d for d in diffs if d > 0]
    med = statistics.median(pos) if pos else 0.0
    nonmono = [i for i in range(1, len(dts)) if dts[i] <= dts[i - 1]]
    gaps = [(i, dts[i] - dts[i - 1]) for i in range(1, len(dts))
            if med > 0 and dts[i] - dts[i - 1] > 2.5 * med]
    s.add(L("Videó csomagok (ffprobe)", "Video packets (ffprobe)"), str(len(rows)), None)
    s.add(L("Átlagos képkockaköz (DTS)", "Average frame interval (DTS)"),
          ("%.4f s" % med) if med > 0 else "–", None)
    # Hiányzó DTS önmagában nem hiba (a Matroska nem tárol DTS-t); W csak akkor, ha nagy rés is van.
    if missing:
        s.add(L("Hiányzó DTS (információ)", "Missing DTS (info)"), str(missing), None)
    if missing and gaps:
        rep.problem("W", L("Hiányzó DTS mellett nagy időbeli rés is van (%d csomag, %d rés)."
                           % (missing, len(gaps)),
                           "Large timing gaps together with missing DTS (%d packets, %d gaps)."
                           % (missing, len(gaps))))
    if nonmono:
        i = nonmono[0]
        s.add(L("DTS nem növekvő", "Non-increasing DTS"), str(len(nonmono)), "E")
        rep.problem("E", L("A videó DTS-je nem növekvő %d helyen (első: #%d, %.3f s)." % (len(nonmono), i, dts[i]),
                           "Video DTS is not increasing at %d places (first: #%d, %.3f s)." % (len(nonmono), i, dts[i])))
    if gaps:
        i, d = gaps[0]
        s.add(L("Nagy időbeli rés", "Large timing gap"), str(len(gaps)), "W")
        rep.problem("W", L("%d helyen nagy időbeli rés van (első: #%d, %.3f s-os ugrás, a medián %.4f s)."
                           % (len(gaps), i, d, med),
                           "%d large timing gaps (first: #%d, a %.3f s jump; median %.4f s)."
                           % (len(gaps), i, d, med)))
    if not nonmono and not gaps:
        s.add(L("Időzítés", "Timing"), L("rendben", "OK"), "OK")


def _external_stage(path, rep, core, ff, progress, cancel):
    """Külső ellenőrzés: ffmpeg-dekódolás (hibák, képkockák) és ffprobe DTS-időzítés. progress: 0..1."""
    fp = ffprobe_path_guess(core)
    s = rep.sec(L("Külső ellenőrzés (ffmpeg / ffprobe)", "External check (ffmpeg / ffprobe)"))
    s.add(L("Program", "Program"), ff, None)
    rep.notes.append(L("A képkockák dekódolását és a DTS-időzítést az ffmpeg / ffprobe külső program végzi; "
                       "a saját kód nem dekódol. A képminőséget nem értékeli.",
                       "Decoding and DTS timing are done by the external ffmpeg / ffprobe programs; "
                       "the built-in code does not decode."))
    dur = _ext_duration(fp, path, cancel) if fp else 0.0
    progress(0.0)
    _ext_decode_section(path, ff, dur, s, rep, progress, cancel)
    progress(1.0)
    if fp:
        _ext_timing_section(path, fp, s, rep, cancel)
    else:
        s.add(L("Időzítés", "Timing"), L("az ffprobe nem található", "ffprobe not found"), None)


# ------------------------------------------- ellenőrzött javítás (ffmpeg) ---------
# A javítás célja: a kimenet dekódolása ffmpeg-gel hibátlan, és az ellenőrzés is hibátlant
# ad. A kimenet csak akkor kap "tiszta" jelölést, ha az ellenőrzés tényleg az. Az elveszett
# képtartalom nem állítható vissza; a hibás képkockák újrakódolásnál a dekóder által
# rekonstruált (elfedett) képpel kerülnek a kimenetbe.

_REENC_ARGS = ["-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "192k"]       # régi alapérték (már nem használt, kompatibilitás)

# ---- célkonténerek: a javítás / mentés tetszőleges formátumba ----
# fmt = az ffmpeg muxere, vc / ac = a konténerhez illő alap videó- / hangkodek újrakódoláskor.
_REPAIR_ORDER = ("mkv", "mp4", "mov", "ts", "m2ts", "webm")
_REPAIR_CONT = {
    "mkv": dict(ext=".mkv", fmt="matroska", vc="libx264", ac="aac", pat="*.mkv", label="Matroska"),
    "mp4": dict(ext=".mp4", fmt="mp4", vc="libx264", ac="aac", pat="*.mp4 *.m4v", label="MP4"),
    "mov": dict(ext=".mov", fmt="mov", vc="libx264", ac="aac", pat="*.mov", label="QuickTime MOV"),
    "ts": dict(ext=".ts", fmt="mpegts", vc="libx264", ac="ac3", pat="*.ts", label="MPEG-TS"),
    "m2ts": dict(ext=".m2ts", fmt="mpegts", vc="libx264", ac="ac3", pat="*.m2ts *.mts", label="M2TS / AVCHD"),
    "webm": dict(ext=".webm", fmt="webm", vc="libvpx-vp9", ac="libopus", pat="*.webm", label="WebM"),
}
_EXT_TO_CONT = {".mkv": "mkv", ".mka": "mkv", ".mp4": "mp4", ".m4v": "mp4", ".mov": "mov", ".ts": "ts",
                ".m2ts": "m2ts", ".mts": "m2ts", ".webm": "webm"}
# mi másolható változtatás nélkül az adott konténerbe (None = bármi)
_COPY_OK = {
    "mkv": (None, None),
    "webm": (("vp8", "vp9", "av1"), ("opus", "vorbis")),
    "mp4": (("h264", "hevc", "av1", "mpeg4", "vp9"), ("aac", "ac3", "eac3", "mp3", "opus", "flac", "alac", "mp2")),
    "mov": (("h264", "hevc", "mpeg4", "prores", "mjpeg"), ("aac", "ac3", "eac3", "mp3", "alac", "pcm_s16le", "pcm_s24le")),
    "ts": (("h264", "hevc", "mpeg2video", "mpeg1video", "vc1"), ("ac3", "eac3", "aac", "mp2", "mp3", "dts", "truehd")),
}
_COPY_OK["m2ts"] = _COPY_OK["ts"]
# melyik kódoló fér a konténerbe újrakódoláskor
_VC_OK = {"mkv": ("libx264", "libx265", "libvpx-vp9"), "mp4": ("libx264", "libx265", "libvpx-vp9"),
          "mov": ("libx264", "libx265"), "ts": ("libx264", "libx265"), "m2ts": ("libx264", "libx265"),
          "webm": ("libvpx-vp9",)}
_AC_OK = {"mkv": ("aac", "ac3", "libopus", "flac", "libvorbis"), "mp4": ("aac", "ac3", "libopus", "flac"),
          "mov": ("aac", "ac3", "flac"), "ts": ("ac3", "aac", "mp2"), "m2ts": ("ac3", "aac", "mp2"),
          "webm": ("libopus", "libvorbis")}
_CRF_DEFAULT = {"libx264": "16", "libx265": "20", "libvpx-vp9": "28"}
_PRESETS = ("ultrafast", "veryfast", "fast", "medium", "slow", "slower")
_TECH_KEYS = ("bytefix", "errtolerant", "genpts", "igndts", "bigprobe", "paramsets", "async", "avalign",
              "cfr", "shortgop")

DEFAULT_REPAIR = dict(
    container="mkv", mode="auto", vcodec="libx264", crf="16", preset="medium", acodec="auto", abitrate="",
    bytefix=True, errtolerant=True, genpts=True, igndts=False, bigprobe=True, paramsets=True,
    **{"async": False}, avalign=False, cfr=False, shortgop=False)


def _repair_ext(src):
    import os
    return ".mp4" if os.path.splitext(src)[1].lower() in (".mp4", ".mov", ".m4v") else ".mkv"


def _cont_from_ext(path, default=None):
    """A fájlkiterjesztésből a célkonténer kulcsa (mkv / mp4 / mov / ts / m2ts / webm)."""
    return _EXT_TO_CONT.get(os.path.splitext(path or "")[1].lower(), default)


def _fmt_args(cont):
    """Az ffmpeg muxer és a konténerhez illő kimeneti kapcsolók."""
    spec = _REPAIR_CONT[cont]
    a = ["-f", spec["fmt"]]
    if cont == "m2ts":
        a += ["-mpegts_m2ts_mode", "1"]
    if cont in ("ts", "m2ts"):
        a += ["-mpegts_flags", "+resend_headers+pat_pmt_at_frames"]
    if cont in ("mp4", "mov"):
        a += ["-movflags", "+faststart"]
    return a


def _can_copy(kind, cont, name):
    """Belefér-e a forrás kodekje (name) változtatás nélkül a konténerbe. Ismeretlen kodek: igen (kipróbáljuk)."""
    ok = _COPY_OK.get(cont, (None, None))[0 if kind == "v" else 1]
    return ok is None or not name or name in ok


def _ff_run(cmd, cancel=None, timeout=7200, dur=None, prog=None):
    """Külső ffmpeg-hívás hibakimenettel; megszakítható. Visszatér: (kilépési kód, stderr).
    Ha a dur (a kimenet várható hossza, mp) és a prog megvan, a folyamatjelzőt is továbbítja (0..1)."""
    import subprocess
    import tempfile
    import time
    if prog is not None and dur and dur > 0:
        c = [cmd[0], "-progress", "pipe:1", "-nostats"] + list(cmd[1:])
        errf = tempfile.TemporaryFile()
        p = subprocess.Popen(c, stdout=subprocess.PIPE, stderr=errf, stdin=subprocess.DEVNULL,
                             text=True, encoding="utf-8", errors="replace", **_hidden_kwargs())
        t0 = time.time()
        try:
            for line in p.stdout:
                if cancel is not None and cancel.is_set():
                    p.kill()
                    p.wait()
                    raise AnalyzeCancelled()
                k, _, v = line.strip().partition("=")
                if k == "out_time_us" and v.isdigit():
                    prog(min(1.0, int(v) / 1e6 / dur))
                if time.time() - t0 > timeout:
                    p.kill()
                    p.wait()
                    return -1, "timeout"
            rc = p.wait()
            errf.seek(0)
            err = errf.read().decode("utf-8", "replace")
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()
            p.stdout.close()
            errf.close()
        return rc, err
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                         stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                         errors="replace", **_hidden_kwargs())
    t0 = time.time()
    while True:
        try:
            _, err = p.communicate(timeout=0.5)
            return p.returncode, (err or "")
        except subprocess.TimeoutExpired:
            if cancel is not None and cancel.is_set():
                p.kill()
                p.communicate()
                raise AnalyzeCancelled()
            if time.time() - t0 > timeout:
                p.kill()
                p.communicate()
                return -1, "timeout"


def _probe_src(fp, src, cancel=None):
    """A forrás kodekjei, pix_fmt-je, kocka/mp-je, csatornaszáma (ffprobe). Ffprobe nélkül / hibánál üres dict."""
    import json
    info = {}
    if not fp:
        return info
    try:
        rc, out = _ext_run([fp, "-v", "error", "-show_entries",
                            "stream=codec_type,codec_name,pix_fmt,avg_frame_rate,r_frame_rate,channels",
                            "-of", "json", src], cancel, timeout=120)
        streams = json.loads(out or "{}").get("streams", [])
    except AnalyzeCancelled:
        raise
    except Exception:
        return info
    for s in streams:
        if s.get("codec_type") == "video" and "vcodec" not in info:
            info["vcodec"] = (s.get("codec_name") or "").lower()
            info["pix_fmt"] = s.get("pix_fmt") or ""
            for key in ("avg_frame_rate", "r_frame_rate"):
                fr = s.get(key) or ""
                if "/" in fr and fr not in ("0/0", "0/1"):
                    info["fps"] = fr
                    break
        elif s.get("codec_type") == "audio" and "acodec" not in info:
            info["acodec"] = (s.get("codec_name") or "").lower()
            try:
                info["channels"] = int(s.get("channels") or 2)
            except (TypeError, ValueError):
                info["channels"] = 2
    return info


def suggest_repair(rep, path=""):
    """Javasolt javítási beállítások az elemzés eredményéből. Visszatér: (opciók, indoklások listája).
    A felismerés az elemzés nyelvfüggetlen jelöléseire épül (GOP, SPS, CC, DTS, PTS, PCR, AC-3, A/V)."""
    o = dict(DEFAULT_REPAIR)
    why = []
    o["container"] = _cont_from_ext(path, "mkv")
    seen = set()

    def flag(key, hu, en, **kw):
        if key in seen:
            return
        seen.add(key)
        o.update(kw)
        why.append(L(hu, en))

    for lvl, t in (rep.problems if rep is not None else []):
        if "SPS" in t:
            flag("sps", "SPS/PPS hiányzik az IDR-képeknél → paraméterkészletek ismétlése minden kulcskockánál.",
                 "SPS/PPS missing at IDR pictures → repeat the parameter sets at every key frame.", paramsets=True)
        if "CC" in t or "0x47" in t or "sync" in t.lower() or "szinkronvesztés" in t:
            flag("cc", "Folytonossági / szinkronhiba → bájtszintű TS-javítás.",
                 "Continuity / sync errors → byte-level TS repair.", bytefix=True)
        if "DTS" in t or "PTS" in t:
            flag("ts", "Időbélyeg-hiba → PTS újragenerálása.", "Timestamp errors → regenerate the PTS.", genpts=True)
            if lvl == "E" and "DTS" in t:
                flag("dts", "A DTS nem növekvő → a hibás DTS figyelmen kívül hagyása.",
                     "DTS is not increasing → ignore the faulty DTS.", igndts=True)
        if "PCR" in t:
            flag("pcr", "PCR-hiba → az új konténer az órajel-hivatkozást újraírja (külön beállítás nem kell).",
                 "PCR problem → the new container rewrites the clock reference (no extra setting needed).")
        if "AC-3" in t or "hangrés" in t or "audio gap" in t.lower() or "drift" in t.lower() or "csúszás" in t:
            flag("audio", "Hangrés / csúszás / sérült hangkeret → hangkiegyenlítés (a hang újrakódolódik).",
                 "Audio gaps / drift / damaged frames → audio resync (the audio is re-encoded).", **{"async": True})
        if lvl == "E" and "GOP" in t:
            flag("gop", "Nagyon hosszú GOP → rövid GOP (a videó újrakódolódik).",
                 "Very long GOP → short GOP (the video is re-encoded).", shortgop=True)
        if t.startswith((L("Dekódolás", "Decoding"), "Dekódolás", "Decoding")):
            flag("dec", "Dekódolási hibák → ha a másolás nem tisztít, az automatikus mód újrakódol.",
                 "Decoding errors → if copying does not clean it, the automatic mode re-encodes.")
    av = getattr(rep, "av_start_ms", None) if rep is not None else None
    if av is not None and av < -80.0:
        flag("av", "A hang %.0f ms-mal a kép előtt indul → igazítás." % -av,
             "The audio starts %.0f ms before the picture → align it." % -av, avalign=True)
    return o, why


def _build_repair_cmd(ff, src, out, kind, o, cont, info, av_ms):
    """Az ffmpeg-parancs egy javítási kísérlethez. kind: 'copy' (a videó változatlan) vagy 'encode'.
    Visszatér: (parancs | None, megjegyzések). None = ez a kísérlet ebbe a konténerbe nem lehetséges."""
    spec = _REPAIR_CONT[cont]
    notes = []
    vname, aname = info.get("vcodec", ""), info.get("acodec", "")
    enc = kind == "encode"
    if not enc and not _can_copy("v", cont, vname):
        return None, [L("A(z) %s videó nem másolható a(z) %s konténerbe: újrakódolás kell." % (vname, cont),
                        "%s video cannot be copied into %s: re-encoding is needed." % (vname, cont))]

    cmd = [ff, "-hide_banner", "-nostdin", "-v", "error", "-y"]
    if o.get("bigprobe"):
        cmd += ["-analyzeduration", "200M", "-probesize", "200M"]
    if o.get("errtolerant"):
        cmd += ["-err_detect", "ignore_err"]
    fl = []
    if o.get("errtolerant"):
        fl.append("discardcorrupt")
    if o.get("genpts"):
        fl.append("genpts")
    if o.get("igndts"):
        fl.append("igndts")
    if fl:
        cmd += ["-fflags", "+" + "+".join(fl)]
    cmd += ["-i", src, "-map", "0:v:0?", "-map", "0:a?"]

    # ---- videó ----
    if enc:
        vc = o.get("vcodec") or spec["vc"]
        if vc not in _VC_OK.get(cont, ()):
            notes.append(L("A(z) %s kódoló nem fér a(z) %s konténerbe: %s lesz." % (vc, cont, spec["vc"]),
                           "Encoder %s does not fit %s: using %s." % (vc, cont, spec["vc"])))
            vc = spec["vc"]
        crf = str(o.get("crf") or "").strip()
        if not crf.isdigit():
            crf = _CRF_DEFAULT.get(vc, "18")
        preset = o.get("preset") if o.get("preset") in _PRESETS else "medium"
        cmd += ["-c:v", vc]
        if vc in ("libx264", "libx265"):
            cmd += ["-preset", preset, "-crf", crf]
            if vc == "libx265" and cont in ("mp4", "mov"):
                cmd += ["-tag:v", "hvc1"]
        else:
            cmd += ["-crf", crf, "-b:v", "0", "-deadline", "good", "-cpu-used", "2", "-row-mt", "1"]
        if "10" not in (info.get("pix_fmt") or ""):         # a 10 bites forrást nem rontjuk 8 bitesre
            cmd += ["-pix_fmt", "yuv420p"]
        if o.get("cfr"):
            if info.get("fps"):
                cmd += ["-vf", "fps=%s" % info["fps"]]
            else:
                notes.append(L("Az állandó képfrekvenciához nem ismert a forrás fps-e (ffprobe kell).",
                               "Constant frame rate skipped: the source fps is unknown (needs ffprobe)."))
        if o.get("shortgop") or cont in ("ts", "m2ts"):
            cmd += ["-force_key_frames", "expr:gte(t,n_forced*0.5)"]
        cmd += ["-max_muxing_queue_size", "4096"]
    else:
        cmd += ["-c:v", "copy"]
        if o.get("paramsets") and cont in ("ts", "m2ts") and vname in ("h264", "hevc", ""):
            cmd += ["-bsf:v", "dump_extra=freq=keyframe"]
        cmd += ["-avoid_negative_ts", "make_zero"]
        if o.get("cfr") or o.get("shortgop"):
            notes.append(L("Az állandó fps / rövid GOP videó-újrakódolást kér: másolásnál kimarad.",
                           "Constant fps / short GOP need video re-encoding: skipped while copying."))

    # ---- hang ----
    af = []
    if o.get("avalign") and av_ms is not None and av_ms < -80.0:
        af.append("atrim=start=%.6f" % (-av_ms / 1000.0))
    if o.get("async"):
        af.append("aresample=async=1000")
    choice = o.get("acodec") or "auto"
    a_copy = False
    if choice == "copy" or (choice == "auto" and not enc):
        if af:
            notes.append(L("A hangszűrők miatt a hang újrakódolódik.", "Audio filters force audio re-encoding."))
        elif not _can_copy("a", cont, aname):
            notes.append(L("A(z) %s hang nem másolható a(z) %s konténerbe: újrakódolódik." % (aname, cont),
                           "%s audio cannot be copied into %s: it is re-encoded." % (aname, cont)))
        else:
            a_copy = True
    if a_copy:
        cmd += ["-c:a", "copy"]
    else:
        ac = choice if choice not in ("auto", "copy") else spec["ac"]
        if ac not in _AC_OK.get(cont, ()):
            if choice not in ("auto", "copy"):
                notes.append(L("A(z) %s hangkodek nem fér a(z) %s konténerbe: %s lesz." % (ac, cont, spec["ac"]),
                               "Audio codec %s does not fit %s: using %s." % (ac, cont, spec["ac"])))
            ac = spec["ac"]
        cmd += ["-c:a", ac]
        if ac != "flac":
            ch = info.get("channels") or 2
            br = (o.get("abitrate") or "").strip().replace(",", ".")
            if re.fullmatch(r"\d+(\.\d+)?", br) and float(br) < 10000:
                br += "k"
            if not re.fullmatch(r"\d+(\.\d+)?[kKmM]?", br):
                br = {"libopus": "320k" if ch > 2 else "160k", "libvorbis": "256k" if ch > 2 else "128k"}.get(
                    ac, "384k" if ch > 2 else "192k")
            cmd += ["-b:a", br]
        if af:
            cmd += ["-af", ",".join(af)]

    cmd += _fmt_args(cont)
    cmd.append(out)
    return cmd, notes


def _ext_verify(path, ff, fp, cancel=None):
    """Ellenőrzés ugyanazzal a logikával, mint az elemzés külső szakasza.
    clean = a dekódolás kilépési kódja 0, nincs dekódolási és időzítési üzenet, és a DTS nem csökken."""
    dur = _ext_duration(fp, path, cancel) if fp else 0.0
    res = _ext_decode(path, ff, dur, lambda f: None, cancel)
    if res is None:
        return {"clean": False, "frames": 0, "rc": -1, "dec": -1, "timing": 0, "nonmono": 0,
                "why": "ffmpeg did not start"}
    frames, rc, lines = res
    lines = [x for x in lines if not x.startswith("Last message repeated")]
    flags = [any(w in _ext_norm(x).lower() for w in _TIMING_WORDS) for x in lines]
    tim_n = sum(1 for f in flags if f)
    dec_n = len(lines) - tim_n
    nonmono = 0
    if fp:
        rc2, out = _ext_run([fp, "-v", "error", "-select_streams", "v:0", "-show_entries",
                             "packet=dts_time", "-of", "csv=p=0", path], cancel)
        d = [_ext_f(l.strip().split(",")[0]) for l in out.splitlines() if l.strip()]
        d = [v for v in d if v is not None]
        nonmono = sum(1 for i in range(1, len(d)) if d[i] <= d[i - 1])
    clean = (rc == 0 and dec_n == 0 and tim_n == 0 and nonmono == 0)
    return {"clean": clean, "frames": frames, "rc": rc, "dec": dec_n, "timing": tim_n, "nonmono": nonmono}


def repair_verified(src, dst, ff, fp, progress=None, cancel=None, opts=None, av_ms=None):
    """Ellenőrzött javítás / mentés tetszőleges formátumba. A célkonténert a dst kiterjesztése adja.
    Lépések:
    1) TS-forrásnál bájtszintű javítás (repair_ts) ideiglenes fájlba (ha be van kapcsolva);
    2) 'copy' kísérlet: a videó változatlan (stream-másolás), hibatűrő beolvasás, időbélyegek újragenerálása;
    3) 'encode' kísérlet: újrakódolás (x264 / x265 / VP9) a kért javításokkal;
    minden kísérlet után ellenőrzés; az első tiszta eredmény kerül a dst-re. Ha egyik sem tiszta, a legjobb
    próbálkozás marad, a 'clean' mező jelzi, hogy tiszta-e. Az eredeti fájl sosem módosul.
    opts: lásd DEFAULT_REPAIR; mode = auto | copy | reencode. av_ms: a hang kezdete a képhez képest (elemzésből).
    Visszatér: napló-dict. Megszakításkor AnalyzeCancelled."""
    import shutil
    import subprocess
    import tempfile
    progress = progress or (lambda f: None)
    if os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(dst)):
        raise ValueError(L("A cél nem lehet maga az eredeti fájl.", "The target cannot be the original file."))
    o = dict(DEFAULT_REPAIR)
    if opts:
        o.update(opts)
    cont = _cont_from_ext(dst) or o.get("container") or "mkv"
    if cont not in _REPAIR_CONT:
        cont = "mkv"
    ext = _REPAIR_CONT[cont]["ext"]
    mode = o.get("mode") if o.get("mode") in ("auto", "copy", "reencode") else "auto"
    log = {"src": src, "dst": dst, "steps": [], "clean": False, "method": None, "verify": None, "container": cont}
    log["steps"].append(("beallitasok", dict(container=cont, mode=mode,
                                             **{k: o.get(k) for k in _TECH_KEYS + ("vcodec", "crf", "preset",
                                                                                   "acodec", "abitrate")})))
    info = _probe_src(fp, src, cancel)
    tmpdir = tempfile.mkdtemp(prefix="lvt_fix_", dir=os.path.dirname(os.path.abspath(dst)))
    try:
        work_src = src
        if o.get("bytefix") and os.path.splitext(src)[1].lower() in (".ts", ".mts", ".m2ts"):
            t0 = os.path.join(tmpdir, "bytes.ts")
            r = repair_ts(src, t0, lambda f: progress(0.1 * f), cancel)
            log["steps"].append(("bajtszintu TS-javitas", {k: v for k, v in r.items() if k != "first_events"}))
            work_src = t0
        progress(0.1)
        dur = _ext_duration(fp, work_src, cancel) if fp else 0.0

        force_enc = bool(o.get("cfr") or o.get("shortgop"))
        if mode == "copy":
            attempts = ["copy"]
        elif mode == "reencode":
            attempts = ["encode"]
        else:
            attempts = ["encode"] if force_enc else ["copy", "encode"]
        best = None
        n = len(attempts)
        for idx, kind in enumerate(attempts):
            lo, hi = 0.1 + 0.85 * idx / n, 0.1 + 0.85 * (idx + 1) / n
            out = os.path.join(tmpdir, kind + ext)
            cmd, notes = _build_repair_cmd(ff, work_src, out, kind, o, cont, info, av_ms)
            title = "ffmpeg ujracsomagolas (video masolas)" if kind == "copy" else "ffmpeg ujrakodolas"
            if cmd is None:
                log["steps"].append((title + " - kihagyva", {"ok": "; ".join(notes)}))
                continue
            rc, err = _ff_run(cmd, cancel, dur=dur, prog=lambda f, lo=lo, hi=hi: progress(lo + (hi - lo) * 0.8 * f))
            log["steps"].append((title, {"parancs": subprocess.list2cmdline(cmd), "megjegyzes": "; ".join(notes),
                                         "rc": rc, "stderr": err[-400:]}))
            if rc != 0 or not os.path.isfile(out):
                continue
            v = _ext_verify(out, ff, fp, cancel)
            log["steps"].append(("ellenorzes (%s)" % kind, v))
            progress(hi)
            method = "remux" if kind == "copy" else "reencode"
            if v.get("clean"):
                os.replace(out, dst)
                log.update(clean=True, method=method, verify=v)
                progress(1.0)
                return log
            best = (out, v, method)
        if best is not None:
            os.replace(best[0], dst)
            log.update(method=best[2], verify=best[1], clean=False)
        progress(1.0)
        return log
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def analyze_file(path, core=None, progress=None, cancel=None):
    """Fájl elemzése. Visszatér: Report. Megszakításkor AnalyzeCancelled.
    1) szerkezeti ellenőrzés (saját kód): 0–60 %;
    2) ha van ffmpeg (és nincs tiltva): külső dekódolás és időzítés-ellenőrzés: 60–100 %."""
    progress = progress or (lambda f: None)
    ff = ffmpeg_path_guess(core)
    if ff is None:
        rep = _analyze_structural(path, core, progress, cancel)
        rep.notes.append(L("A képkockák dekódolása és a külső időzítés-ellenőrzés nem futott: nincs ffmpeg "
                           "(vagy a külső programok tiltva vannak).",
                           "Frame decoding and the external timing check did not run: no ffmpeg found "
                           "(or external programs are disabled)."))
        return rep
    rep = _analyze_structural(path, core, lambda f: progress(0.6 * f), cancel)
    _external_stage(path, rep, core, ff, lambda f: progress(0.6 + 0.4 * f), cancel)
    progress(1.0)
    return rep


def _analyze_structural(path, core=None, progress=None, cancel=None):
    """Szerkezeti ellenőrzés (saját kód, változatlan)."""
    progress = progress or (lambda f: None)
    rep = Report(path)
    size = os.path.getsize(path)
    if size < 188 * 10:
        rep.problem("E", L("A fájl túl kicsi.", "The file is too small."))
        return rep
    with open(path, "rb") as f:
        head = f.read(65536)
    det = _detect_ts(head)
    if det is None:
        return _basic_report(path, core, rep, size, progress, cancel)
    ps, H = det
    ts = TsDeep(path, size, ps, H)
    with open(path, "rb") as f:
        ok = ts.psi(f)
        if not ok:
            rep.problem("E", L("Nem található PAT/PMT (PSI) – sérült vagy nem TS fájl.",
                               "PAT/PMT not found – damaged or not a TS file."))
            return rep
        ts.scan(f, progress, cancel)
    ts.report(rep)
    return rep


# ------------------------------------------------------------ Tk felület -----

# ----------------------------------------------------------- javítás (recovery) --

def repair_ts(src, dst, progress=None, cancel=None):
    """Bájtszintű TS-javítás új fájlba (az eredeti nem változik).

    * szinkronvesztés után visszatalál a csomagrácsra (3 egymás utáni 0x47-tel),
      zárolt állapotban a csomagonkénti szinkronbájtot ellenőrzi,
    * az egymás utáni, bájtra azonos csomagokat (PES-tartalommal) eldobja,
    * a folytonossági számlálót (CC) eltolással igazítja: egy kihagyás után
      a további csomagok nem tolódnak el láncreakcióban,
    * a csomagok tartalmát (PES, kép, hang) nem módosítja.
    Visszatér: naplóval (dict). Megszakításkor AnalyzeCancelled."""
    progress = progress or (lambda f: None)
    size = os.path.getsize(src)
    with open(src, "rb") as f:
        head = f.read(65536)
    det = _detect_ts(head)
    if det is None:
        raise ValueError(L("Nem TS fájl – nem javítható ezzel a módszerrel.",
                           "Not a TS file – cannot be repaired this way."))
    ps, H = det
    res = {"in_bytes": size, "out_packets": 0, "resync_bytes": 0, "resync_events": 0,
           "dup_dropped": 0, "cc_fixed": 0, "tail_bytes": 0, "first_events": []}
    st = {}               # pid -> {"raw": utolsó nyers CC, "out": utolsó kimeneti CC, "off": eltolás}
    last_pkt = {}         # pid -> utolsó (eredeti) csomag bájtjai a duplikátum-szűréshez
    CH = ps * 8192

    def three_sync(buf, eof, i):
        for k in range(3):
            pos = i + k * ps + H
            if pos >= len(buf):
                return eof
            if buf[pos] != 0x47:
                return False
        return True

    def accept(buf, i, fo):
        hdr = bytes(buf[i:i + H])
        orig = bytes(buf[i + H:i + ps])
        pid = ((orig[1] & 0x1F) << 8) | orig[2]
        pkt = bytearray(orig)
        if pid != 0x1FFF:                     # a töltőcsomag (0x1FFF) mindig megmarad
            if last_pkt.get(pid) == orig:
                res["dup_dropped"] += 1       # bájtra azonos ismétlés (PCR-, töltő- vagy adatcsomag)
                return
            afc = (orig[3] >> 4) & 3
            if afc & 1:                       # van adatrész (payload): folytonossági számláló
                s = st.setdefault(pid, {"raw": None, "out": None, "off": 0})
                raw = orig[3] & 15
                if s["raw"] is not None and raw != ((s["raw"] + 1) & 15) and raw != s["raw"]:
                    # kihagyás: a további csomagok számlálóját az utolsó kimenethez igazítjuk
                    s["off"] = (s["out"] + 1 - raw) & 15
                    res["cc_fixed"] += 1
                out = (raw + s["off"]) & 15
                if out != raw:
                    pkt[3] = (orig[3] & 0xF0) | out
                s["raw"], s["out"] = raw, out
            last_pkt[pid] = orig
        fo.write(hdr + bytes(pkt))
        res["out_packets"] += 1

    with open(src, "rb") as fi, open(dst, "wb") as fo:
        buf = bytearray()
        eof = False
        i = 0
        absbase = 0
        locked = False
        lost_at = 0                           # abszolút pozíció, ahol a szinkron elveszett

        def grow(need):
            nonlocal eof
            while len(buf) < need and not eof:
                d = fi.read(CH)
                if not d:
                    eof = True
                    break
                buf.extend(d)

        while True:
            if cancel is not None and cancel.is_set():
                raise AnalyzeCancelled()
            if i > CH:
                del buf[:i]
                absbase += i
                i = 0
            grow(i + 3 * ps + 1)
            if not locked:
                base = i + H
                k = buf.find(b"\x47", base) if base < len(buf) else -1
                if k < 0:
                    if eof:
                        res["resync_bytes"] += (absbase + len(buf)) - lost_at
                        res["tail_bytes"] += len(buf) - i
                        break
                    i = len(buf) - H          # nincs jelölt a pufferben: tovább olvasunk
                    continue
                i = k - H
                if three_sync(buf, eof, i):
                    locked = True
                    if absbase + i > lost_at:
                        res["resync_bytes"] += (absbase + i) - lost_at
                        res["resync_events"] += 1
                        if len(res["first_events"]) < 20:
                            res["first_events"].append(lost_at)
                else:
                    i += 1
                continue
            if i + H >= len(buf):
                break
            if buf[i + H] != 0x47:
                locked = False                # szinkronvesztés: újrakeresés
                lost_at = absbase + i
                continue
            if i + ps > len(buf):
                res["tail_bytes"] = len(buf) - i   # csonka utolsó csomag
                break
            accept(buf, i, fo)
            i += ps
            if res["out_packets"] % 4096 == 0:
                progress(min(0.99, (absbase + i) / float(max(1, size))))
    progress(1.0)
    return res


def ffmpeg_path_guess(core=None):
    """Az ffmpeg program helye: a joiner beállítása, különben a PATH.
    Ha a hoszt letiltja a külső programokat (EXTERNAL_OK = False), nem keres és nem indít semmit."""
    import shutil
    if core is not None and getattr(core, "EXTERNAL_OK", True) is False:
        return None
    for attr in ("FFMPEG", "FFMPEG_PATH", "ffmpeg_path"):
        p = getattr(core, attr, None) if core is not None else None
        if isinstance(p, str) and p and os.path.isfile(p):
            return p
    return shutil.which("ffmpeg")


def _hidden_kwargs():
    if os.name == "nt":
        return {"creationflags": 0x08000000}   # CREATE_NO_WINDOW
    return {}


def ffmpeg_remux(src, dst, ffmpeg, cancel=None, timeout=3600):
    """Külső ffmpeg-folyamat: hibatűrő újracsomagolás stream-másolással (új fájlba).
    A célformátumot a dst kiterjesztése adja (mkv, mp4, mov, ts, m2ts, webm); kodek nem változik.
    Ez nem a saját kód része: az ffmpeg a programon kívül fut."""
    import subprocess
    cont = _cont_from_ext(dst, "ts")
    maps = ["-map", "0:v?", "-map", "0:a?"]
    if cont in ("ts", "m2ts", "mkv"):
        maps += ["-map", "0:s?"]
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
           "-err_detect", "ignore_err", "-fflags", "+discardcorrupt+genpts",
           "-i", src] + maps + ["-c", "copy"] + _fmt_args(cont) + [dst]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **_hidden_kwargs())
    return p.returncode, (p.stderr or "").strip()


def ffmpeg_trim_audio_head(src, dst, seconds, ffmpeg, cancel=None, timeout=3600):
    """Külső ffmpeg-folyamat: a hang eleje (seconds másodperc) levágva; a kép változatlan (stream-másolás).
    A hangot AC-3-ra kódoljuk újra (384 kb/s), mert a szűrő csak dekódolt hangon működik.
    A levágás után a hang PTS-kezdete a kép kezdetéhez igazodik (atrim megtartja az időbélyeget)."""
    import subprocess
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
           "-i", src, "-map", "0:v?", "-c:v", "copy",
           "-map", "0:a?", "-c:a", "ac3", "-b:a", "384k",
           "-af", "atrim=start=%.6f" % float(seconds)] + _fmt_args(_cont_from_ext(dst, "ts")) + [dst]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **_hidden_kwargs())
    return p.returncode, (p.stderr or "").strip()


def ffprobe_check(src, ffprobe, timeout=600):
    """Külső ellenőrzés: ffprobe adatai és a kulcskockák száma (csomagjelzőkből, dekódolás nélkül)."""
    import subprocess
    import json
    out = {"ok": False}
    try:
        p = subprocess.run([ffprobe, "-v", "error", "-of", "json", "-show_format",
                            "-show_streams", src], capture_output=True, text=True,
                           timeout=timeout, **_hidden_kwargs())
        j = json.loads(p.stdout or "{}")
        streams = j.get("streams", [])
        v = next((s for s in streams if s.get("codec_type") == "video"), None)
        a = [s for s in streams if s.get("codec_type") == "audio"]
        out["format_duration"] = float((j.get("format") or {}).get("duration", 0) or 0)
        if v:
            out["vcodec"] = v.get("codec_name")
            out["vprofile"] = v.get("profile")
            out["vsize"] = "%sx%s" % (v.get("width"), v.get("height"))
            out["vfps"] = v.get("avg_frame_rate")
        out["audio"] = ["%s %s ch %s %s Hz" % (s.get("codec_name"), s.get("channel_layout", ""),
                                               s.get("channels"), s.get("sample_rate")) for s in a]
        p2 = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                             "packet=flags", "-of", "csv=p=0", src], capture_output=True, text=True,
                            timeout=timeout, **_hidden_kwargs())
        flags = [ln for ln in (p2.stdout or "").splitlines() if ln.strip()]
        out["keyframes"] = sum(1 for ln in flags if "K" in ln)
        out["packets"] = len(flags)
        out["ok"] = True
    except FileNotFoundError:
        out["error"] = L("Az ffprobe nem található.", "ffprobe was not found.")
    except Exception as e:
        out["error"] = str(e)
    return out


def compare_with_ffprobe(rep, ext):
    """A saját eredmény és az ffprobe összevetése: külön szakasz a jelentésben."""
    s = rep.sec(L("Külső ellenőrzés (ffprobe)", "External check (ffprobe)"))
    if not ext.get("ok"):
        s.add(L("Állapot", "Status"), ext.get("error", "?"), "W")
        return s
    s.add(L("Kodek / profil / felbontás", "Codec / profile / size"),
          "%s / %s / %s" % (ext.get("vcodec"), ext.get("vprofile"), ext.get("vsize")))
    s.add(L("Hang", "Audio"), "; ".join(ext.get("audio") or ["-"]))
    s.add(L("Kulcskockák (ffprobe)", "Key frames (ffprobe)"), "%d" % ext.get("keyframes", 0))
    own = None
    for sec_ in rep.sections:
        if sec_.title.startswith(L("GOP", "GOP")):
            v, _ = find_row_value(sec_, L("Kulcskockák", "Key frames"))
            own = v
    if own is not None:
        try:
            same = int(own) == int(ext.get("keyframes", -1))
        except ValueError:
            same = False
        s.add(L("Kulcskockák: saját / ffprobe", "Key frames: own / ffprobe"),
              "%s / %s" % (own, ext.get("keyframes")), "OK" if same else "W")
        if not same:
            rep.problem("W", L("A kulcskockák száma eltér a külső ellenőrzéstől (%s / %s)." % (own, ext.get("keyframes")),
                               "The key frame count differs from the external check (%s / %s)." % (own, ext.get("keyframes"))))
    if ext.get("format_duration"):
        s.add(L("Hossz (ffprobe)", "Duration (ffprobe)"), "%.3f s" % ext["format_duration"])
    return s


def find_row_value(sec, key_part):
    for k, v, lvl in sec.rows:
        if key_part in k:
            return v, lvl
    return None, None


HELP_ANALYZER_HU = """VIDEÓ-ELEMZŐ – SÚGÓ

Mire jó?
Betöltött videó technikai adatlapja, majd szerkezeti és időzítési ellenőrzés.

Gombok
• Fájl megnyitása… – a vizsgálandó videó kiválasztása.
• Kijelölt az Összefűzés listából – a listában kijelölt fájl átvétele.
• Automatikus elemzés – fájl betöltésekor a teljes fájl végigolvasása indul (nagy fájlnál percekig tarthat).
• Megszakítás – a folyamatban lévő elemzés leállítása.
• Jelentés mentése… – az adatlap és a hibák szövegfájlba írása (UTF-8).
• Hibák mentése… – csak a talált problémák listája, külön fájlba.
• Javítás (új fájl)… – ablak: célformátum (MKV, MP4, MOV, TS, M2TS, WebM), videó mód
  (veszteségmentes / újrakódolás / automatikus) és ffmpeg-technikák (bájtszintű TS-javítás,
  sérült adat átugrása, PTS/DTS újragenerálás, SPS/PPS ismétlés, hang-kiegyenlítés, CFR,
  rövid GOP). Az elemzés alapján ajánlott beállítást ad; a kimenetet ellenőrzi. Az eredeti
  fájl nem változik.
• FFmpeg-újracsomagolás… – hibatűrő másolás az ffmpeg programmal, tetszőleges formátumba.
• Külső ellenőrzés (ffprobe) – az ffprobe adatai és a kulcskockák száma összevetve.
• H – ez a súgó.

Színek
Zöld: rendben. Sárga: figyelmeztetés (használható). Piros: hiba (javítás szükséges).

Fontos számok
• GOP (kulcskockák közti táv): 0,5–2 s a jó; 2 s felett a keresés lassú; 5 s felett hiba.
• PTS/DTS: a megjelenítési és a dekódolási idő; a különbség B-képeknél normális.
• PCR: az órajel-hivatkozás; 100 ms-nél ritkább PCR vagy jelzés nélküli ugrás hiba.
• CC (folytonossági számláló): csomagvesztést vagy ismétlést jelez.
• AC-3 CRC: sérült hangkeret (kattanás). Csak mintavétellel ellenőrzött.

Korlátok
• A hang tartalma (hangerő, kattanás) dekódolás nélkül nem vizsgálható.
• HEVC részletes SPS/VUI adatai ebben a verzióban nincsenek.
• A javítás nem állítja vissza az elveszett képtartalmat; csak a szerkezetet tisztítja.
"""

HELP_ANALYZER_EN = """VIDEO ANALYZER – HELP

What is it for?
A technical data sheet of the loaded video, followed by a structural and timing check.

Buttons
• Open file… – choose the video to inspect.
• Selected from the Join list – take over the file selected in the list.
• Automatic analysis – when a file is loaded, the whole file is read through (can take minutes for large files).
• Cancel – stop the analysis in progress.
• Save report… – write the data sheet and the problems to a text file (UTF-8).
• Save errors… – only the list of problems found, to a separate file.
• Repair (new file)… – dialog: target format (MKV, MP4, MOV, TS, M2TS, WebM), video mode
  (lossless / re-encode / automatic) and ffmpeg techniques (byte-level TS repair, skipping
  damaged data, PTS/DTS regeneration, SPS/PPS repeat, audio gap fix, CFR, short GOP).
  Suggests settings from the analysis and verifies the output. The original is not changed.
• FFmpeg remux… – error-tolerant copy with ffmpeg, into any supported format.
• External check (ffprobe) – ffprobe data compared with the keyframe count.
• H – this help.

Colors
Green: OK. Yellow: warning (usable). Red: error (repair needed).

Key figures
• GOP (distance between keyframes): 0.5–2 s is good; above 2 s seeking is slow; above 5 s it is an error.
• PTS/DTS: presentation and decoding time; the difference is normal with B-frames.
• PCR: the clock reference; a PCR less frequent than 100 ms, or an unsignalled jump, is an error.
• CC (continuity counter): indicates packet loss or repetition.
• AC-3 CRC: damaged audio frame (click). Checked by sampling only.

Limitations
• The audio content (volume, clicks) cannot be inspected without decoding.
• Detailed HEVC SPS/VUI data is not available in this version.
• The repair does not restore lost picture content; it only cleans up the structure.
"""


def style_tabs(ttk, root):
    """Csak a fülek vízszintes kitöltését szűkíti. A téma és a színek változatlanok maradnak."""
    try:
        st = ttk.Style(root)
        st.configure("TNotebook.Tab", padding=(10, 4))
    except Exception:
        pass


class _Dialogs:
    """Fájl- és üzenetablakok a panel saját ablakához kötve.

    Parent nélkül a dialógus a fő ablakhoz tartozik; bezáráskor a fő ablak kerül előtérbe
    (a panel a háttérbe marad, és úgy tűnik, mintha visszaugrott volna). Ez a burkoló minden
    hívásnál a panel felső ablakát adja parent-ként, és bezáráskor visszahozza a panelt."""

    _FILE = ("askopenfilename", "asksaveasfilename", "askdirectory")
    _MSG = ("showinfo", "showerror", "showwarning", "askyesno", "askokcancel",
            "askyesnocancel", "askquestion", "askretrycancel")

    def __init__(self, mod, owner):
        self._mod = mod
        self._owner = owner

    def __getattr__(self, name):
        fn = getattr(self._mod, name)
        if name not in self._FILE + self._MSG:
            return fn

        def call(*a, **kw):
            top = self._owner()
            if top is not None and "parent" not in kw:
                kw["parent"] = top
            try:
                return fn(*a, **kw)
            finally:
                if top is not None:
                    try:
                        top.lift()
                        top.focus_force()
                    except Exception:
                        pass
        return call


class AnalyzerTab:
    """A „Videó-elemző” panel: betöltés, elemzés, hibák mentése, javítás (új fájl),
    FFmpeg-újracsomagolás, külső ellenőrzés és súgó. Háttérszálon fut."""

    def __init__(self, app, tk, ttk, filedialog, messagebox):
        self.app = app
        self.tk = tk
        self.ttk = ttk
        self.fdlg = _Dialogs(filedialog, lambda: getattr(self, "root", None))
        self.mb = _Dialogs(messagebox, lambda: getattr(self, "root", None))
        self.q = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.path = None
        self.rep = None
        self.core = _CORE
        self.var_path = tk.StringVar(value=L("Nincs fájl betöltve", "No file loaded"))
        self.var_pct = tk.StringVar(value="")
        self.var_verdict = tk.StringVar(value="")
        self._polling = False
        self._help_win = None
        self._want_run = False

    # ---- felépítés ----
    def build(self, parent):
        tk, ttk = self.tk, self.ttk
        self.root = parent.winfo_toplevel()
        bold = tkfont_bold(tk)
        self.btns = {}

        def btn(row, key, text, cmd):
            b = ttk.Button(row, text=text, command=cmd)
            b.pack(side="left", padx=(0, 4), pady=1)
            self.btns[key] = b
            return b

        r1 = ttk.Frame(parent, padding=(6, 6, 6, 0))
        r1.pack(fill="x")
        btn(r1, "open", L("Fájl megnyitása…", "Open file…"), self.open_file)
        btn(r1, "list", L("Szerkesztő fájlja", "Editor file"), self.from_list)
        btn(r1, "cancel", L("Megszakítás", "Cancel"), self.cancel.set)
        btn(r1, "save", L("Jelentés mentése…", "Save report…"), self.save)
        btn(r1, "errs", L("Hibák mentése…", "Save errors…"), self.save_errors)
        ttk.Button(r1, text="H", width=3, command=self.show_help).pack(side="right")
        self.btns["help"] = r1.winfo_children()[-1]

        r2 = ttk.Frame(parent, padding=(6, 2, 6, 4))
        r2.pack(fill="x")
        btn(r2, "repair", L("Javítás (új fájl)…", "Repair (new file)…"), self.repair)
        btn(r2, "remux", L("FFmpeg-újracsomagolás (formátumválasztással)…", "FFmpeg remux (choose format)…"), self.remux)
        btn(r2, "probe", L("Külső ellenőrzés (ffprobe)", "External check (ffprobe)"), self.probe)
        btn(r2, "avfix", L("A/V igazítás (hang eleje)…", "A/V align (audio head)…"), self.avfix)

        ttk.Label(parent, textvariable=self.var_path, padding=(10, 0)).pack(fill="x")
        bar = ttk.Frame(parent, padding=(8, 4))
        bar.pack(fill="x")
        self.pb = ttk.Progressbar(bar, maximum=1000, value=0)
        self.pb.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Label(bar, textvariable=self.var_pct, width=7).pack(side="left")
        self.lbl_verdict = tk.Label(parent, textvariable=self.var_verdict, anchor="w", padx=10, pady=4,
                                    font=bold, fg=self._verdict_color())
        self.lbl_verdict.pack(fill="x")
        paned = ttk.PanedWindow(parent, orient="vertical")
        paned.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        upper = ttk.Frame(paned)
        lower = ttk.Frame(paned)
        paned.add(upper, weight=3)
        paned.add(lower, weight=2)
        self.tree = ttk.Treeview(upper, columns=("v",), show="tree headings", selectmode="browse")
        self.tree.heading("#0", text=L("Adat", "Item"))
        self.tree.heading("v", text=L("Érték", "Value"))
        self.tree.column("#0", width=330, stretch=False)
        self.tree.column("v", width=700, stretch=True)
        tsb = ttk.Scrollbar(upper, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tsb.pack(side="left", fill="y")
        self.tree.tag_configure("E", background="#ffd6d6")
        self.tree.tag_configure("W", background="#fff4c2")
        self.tree.tag_configure("OK", background="#e3f6dc")
        self.tree.tag_configure("sec", font=bold)
        self.txt = tk.Text(lower, wrap="none", height=10, font=tkfont_mono(tk))
        xsb = ttk.Scrollbar(lower, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=xsb.set)
        self.txt.pack(side="left", fill="both", expand=True)
        xsb.pack(side="left", fill="y")
        if self.rep is not None:
            self._show(self.rep)
        self._refresh()
        if not self._polling:
            self._polling = True
            self.root.after(100, self._poll)

    def _verdict_color(self):
        if self.rep is not None and self.rep.basic_only and self.rep.verdict == "OK":
            return "#555555"          # nem vizsgált: semleges szín, nem zöld „hibátlan”
        v = self.rep.verdict if self.rep else "OK"
        return {"E": "#b00020", "W": "#8a5a00", "OK": "#1b6e20"}[v]

    def _refresh(self):
        has_path = self.path is not None
        has_rep = self.rep is not None
        idle = not self.busy
        st = lambda ok: "normal" if ok else "disabled"
        b = self.btns
        b["open"].configure(state=st(idle))
        b["list"].configure(state=st(idle))
        b["cancel"].configure(state=st(self.busy))
        b["save"].configure(state=st(idle and has_rep))
        b["errs"].configure(state=st(idle and has_rep))
        b["repair"].configure(state=st(idle and has_rep))      # a javítás a hibák mentése után
        b["remux"].configure(state=st(idle and has_path))
        b["probe"].configure(state=st(idle and has_path))
        # csak akkor, ha a hang a kép előtt indul (>= 80 ms); a késői hangot nem kezeljük
        early = has_rep and getattr(self.rep, "av_start_ms", 0.0) < -80.0
        b["avfix"].configure(state=st(idle and early))

    # ---- fájl kiválasztása ----
    def open_file(self):
        p = self.fdlg.askopenfilename(
            title=L("Videó megnyitása", "Open video"),
            filetypes=[("Video", "*.mts *.m2ts *.ts *.mp4 *.m4v *.mov *.mkv *.webm *.mpg *.mpeg *.vob"),
                       ("*", "*.*")])
        if p:
            self._set_path(p)

    def from_list(self):
        app = self.app
        getter = getattr(app, "current_path", None)
        if callable(getter):                     # az FFmpeg panelen belül: a Szerkesztőben betöltött fájl
            p = (getter() or "").strip()
            if p and os.path.isfile(p):
                self._set_path(p)
            else:
                self.mb.showinfo("Lossless Video Toolkit",
                                 L("Előbb tölts be egy fájlt a Szerkesztőben.",
                                   "Load a file in the Editor first."))
            return
        try:
            sel = app.tree.selection()
            infos = app.infos
        except Exception:
            sel, infos = (), []
        if not sel:
            self.mb.showinfo("Lossless Video Toolkit",
                             L("Jelölj ki egy fájlt az Összefűzés listában.",
                               "Select a file in the join list."))
            return
        try:
            self._set_path(infos[int(sel[0])].path)
        except Exception:
            self.mb.showinfo("Lossless Video Toolkit",
                             L("A kijelölt fájl útvonala nem olvasható ki. Használd a „Fájl megnyitása…” gombot.",
                               "The selected file path could not be read. Use “Open file…” instead."))

    def _set_path(self, p):
        self.path = p
        self.rep = None
        self.var_path.set(p)
        self.var_pct.set("")
        self.pb["value"] = 0
        self._clear()
        self._refresh()
        if self.busy:                   # az előző fájl elemzése leáll, utána indul az új
            self._want_run = True
            self.cancel.set()
        else:
            self.run()                  # betöltéskor automatikusan indul az elemzés

    def _clear(self):
        self.tree.delete(*self.tree.get_children())
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.configure(state="disabled")

    # ---- háttérfeladat ----
    def _start(self, label, fn, on_done):
        if self.busy:
            return
        self.busy = True
        self.cancel.clear()
        self.var_verdict.set(label + "…")
        self.lbl_verdict.configure(fg="#333333")
        self.pb["value"] = 0
        self.var_pct.set("0%")
        self._refresh()

        def work():
            try:
                res = fn(lambda f: self.q.put(("p", f)), self.cancel)
                self.q.put(("done", (on_done, res)))
            except AnalyzeCancelled:
                self.q.put(("cancel", None))
            except Exception as e:
                self.q.put(("err", "%s: %s" % (e.__class__.__name__, e)))
        threading.Thread(target=work, daemon=True).start()

    def run(self):
        if self.busy or not self.path:
            return
        self.rep = None
        self._clear()
        path, core = self.path, self.core
        self._start(L("Elemzés folyamatban", "Analysis in progress"),
                    lambda prog, canc: analyze_file(path, core, prog, canc),
                    self._set_report)

    def _set_report(self, rep):
        self.rep = rep
        self._errors_file = None      # az új elemzéshez új hibalista kell
        self._show(rep)

    def _poll(self):
        try:
            while True:
                try:
                    m = self.q.get_nowait()
                except queue.Empty:
                    break
                self._handle(m)
        except Exception as ex:
            try:
                self.var_verdict.set("! %s" % ex)
            except Exception:
                pass
        try:
            self.root.after(100, self._poll)
        except Exception:
            pass

    def _handle(self, m):
        kind, val = m
        if kind == "p":
            self.pb["value"] = int(val * 1000)
            self.var_pct.set("%d%%" % int(val * 100))
        elif kind == "done":
            cb, res = val
            self.busy = False
            if self._want_run:          # a régi fájl eredménye már nem kell
                self._want_run = False
                self.run()
                return
            self.pb["value"] = 1000
            self.var_pct.set("100%")
            self._refresh()
            cb(res)
        elif kind == "cancel":
            self.busy = False
            if self._want_run:
                self._want_run = False
                self.run()
                return
            self.var_verdict.set(L("Megszakítva.", "Cancelled."))
            self.lbl_verdict.configure(fg="#333333")
            self._refresh()
        elif kind == "err":
            self.busy = False
            self.var_verdict.set(L("Hiba: ", "Error: ") + val)
            self.lbl_verdict.configure(fg="#b00020")
            self._refresh()
            self.mb.showerror("Lossless Video Toolkit", val)

    def _show(self, rep):
        self.lbl_verdict.configure(fg=self._verdict_color())
        self.var_verdict.set(rep.verdict_text())
        self.tree.delete(*self.tree.get_children())
        for si, s in enumerate(rep.sections):
            sid = "s%d" % si
            self.tree.insert("", "end", iid=sid, text=s.title, values=("",), open=True, tags=("sec",))
            for ri, (k, v, lvl) in enumerate(s.rows):
                self.tree.insert(sid, "end", iid="%s_%d" % (sid, ri), text=k, values=(v,),
                                 tags=(lvl,) if lvl else ())
        if rep.problems:
            pid = "problems"
            self.tree.insert("", "end", iid=pid, text=L("Talált problémák", "Problems found"),
                             values=("%d" % len(rep.problems),), open=True, tags=("sec",))
            for i, (lvl, text) in enumerate(rep.problems):
                self.tree.insert(pid, "end", iid="p_%d" % i, text=("✗ " if lvl == "E" else "! ") + text,
                                 values=("",), tags=(lvl,))
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", rep.to_text())
        self.txt.configure(state="disabled")
        self._refresh()

    # ---- mentések ----
    def _stem(self):
        return os.path.splitext(os.path.basename(self.rep.path))[0] if self.rep else "video"

    def save(self):
        if not self.rep:
            return
        p = self.fdlg.asksaveasfilename(defaultextension=".txt", initialfile=self._stem() + "_elemzes.txt",
                                        filetypes=[("Text", "*.txt"), ("*", "*.*")])
        if not p:
            return
        try:
            with open(p, "w", encoding="utf-8-sig") as f:
                f.write(self.rep.to_text())
        except OSError as e:
            self.mb.showerror("Lossless Video Toolkit", str(e))

    def save_errors(self):
        """Csak a talált problémák, külön fájlba – a javítás előtt."""
        if not self.rep:
            return
        p = self.fdlg.asksaveasfilename(defaultextension=".txt", initialfile=self._stem() + "_hibak.txt",
                                        filetypes=[("Text", "*.txt"), ("*", "*.*")])
        if not p:
            return
        lines = [L("Hibák – %s" % self.rep.path, "Errors – %s" % self.rep.path), ""]
        if not self.rep.problems:
            lines.append(L("Nincs talált hiba.", "No errors found."))
        for lvl, text in self.rep.problems:
            lines.append("[%s] %s" % ("HIBA" if lvl == "E" else "FIG", text))
        try:
            with open(p, "w", encoding="utf-8-sig") as f:
                f.write("\n".join(lines) + "\n")
            self.var_pct.set(L("mentve", "saved"))
            self._errors_file = p
        except OSError as e:
            self.mb.showerror("Lossless Video Toolkit", str(e))

    # ---- javítás / újracsomagolás / külső ellenőrzés ----
    def _save_types(self, keys):
        types = [("%s (%s)" % (_REPAIR_CONT[k]["label"], _REPAIR_CONT[k]["pat"]), _REPAIR_CONT[k]["pat"])
                 for k in keys]
        return types + [("*", "*.*")]

    def _out_path(self, suffix, ext, types=None):
        return self.fdlg.asksaveasfilename(defaultextension=ext,
                                           initialfile=self._stem() + suffix + ext,
                                           filetypes=types or [("Transport stream", "*.ts *.mts *.m2ts"),
                                                               ("*", "*.*")])

    def _ask_repair_options(self, av_ms):
        """Javítási beállítások ablaka: célformátum, videó / hang mód és a javítási technikák.
        Visszatér: opciók (dict) vagy None (Mégse)."""
        tk, ttk = self.tk, self.ttk
        sug, why = suggest_repair(self.rep, self.path)
        win = tk.Toplevel(self.root)
        win.title(L("Javítás / mentés más formátumba", "Repair / save in another format"))
        try:
            win.transient(self.root)
        except Exception:
            pass
        win.resizable(False, False)
        res = {"v": None}
        S = lambda v: tk.StringVar(master=win, value=str(v))
        B = lambda v: tk.BooleanVar(master=win, value=bool(v))
        v_cont, v_mode = S(sug["container"]), S(sug["mode"])
        v_vc, v_crf, v_pre = S(sug["vcodec"]), S(sug["crf"]), S(sug["preset"])
        v_ac, v_abr = S(sug["acodec"]), S(sug["abitrate"])
        tech = {k: B(sug[k]) for k in _TECH_KEYS}
        fr = ttk.Frame(win, padding=10)
        fr.pack(fill="both", expand=True)

        if why:
            wf = ttk.LabelFrame(fr, text=L("Ajánlás az elemzés alapján", "Recommendation from the analysis"),
                                padding=6)
            wf.pack(fill="x", pady=(0, 6))
            ttk.Label(wf, text="\n".join("• " + w for w in why), justify="left", wraplength=560).pack(anchor="w")

        # ---- kimenet ----
        of = ttk.LabelFrame(fr, text=L("Kimenet (célformátum)", "Output (target format)"), padding=6)
        of.pack(fill="x", pady=3)
        ttk.Label(of, text=L("Konténer", "Container")).grid(row=0, column=0, sticky="w")
        cb_c = ttk.Combobox(of, textvariable=v_cont, values=list(_REPAIR_ORDER), state="readonly", width=8)
        cb_c.grid(row=0, column=1, sticky="w", padx=6)
        lbl_c = ttk.Label(of, text="", foreground="#00695c")
        lbl_c.grid(row=0, column=2, sticky="w")

        def cont_desc(*_a):
            sp = _REPAIR_CONT.get(v_cont.get())
            if sp:
                lbl_c.configure(text="%s  %s" % (sp["label"], sp["pat"]))
        v_cont.trace_add("write", cont_desc)
        cont_desc()

        # ---- videó ----
        vf_ = ttk.LabelFrame(fr, text=L("Videó", "Video"), padding=6)
        vf_.pack(fill="x", pady=3)
        for i, (val, hu, en) in enumerate((
                ("auto", "Automatikus: előbb veszteségmentes (a videó változatlan), ha az nem tiszta, újrakódolás",
                 "Automatic: lossless first (video unchanged), re-encode if it is still not clean"),
                ("copy", "Csak veszteségmentes (a videó változatlan, nincs újrakódolás)",
                 "Lossless only (video unchanged, no re-encoding)"),
                ("reencode", "Mindig újrakódolás", "Always re-encode"))):
            ttk.Radiobutton(vf_, text=L(hu, en), variable=v_mode, value=val).grid(
                row=i, column=0, columnspan=6, sticky="w")
        ttk.Label(vf_, text=L("Kódoló", "Encoder")).grid(row=3, column=0, sticky="w", pady=(4, 0))
        cb_v = ttk.Combobox(vf_, textvariable=v_vc, values=["libx264", "libx265", "libvpx-vp9"],
                            state="readonly", width=12)
        cb_v.grid(row=3, column=1, sticky="w", padx=6, pady=(4, 0))
        ttk.Label(vf_, text="CRF").grid(row=3, column=2, sticky="e", pady=(4, 0))
        ttk.Entry(vf_, textvariable=v_crf, width=5).grid(row=3, column=3, sticky="w", padx=6, pady=(4, 0))
        ttk.Label(vf_, text="preset").grid(row=3, column=4, sticky="e", pady=(4, 0))
        ttk.Combobox(vf_, textvariable=v_pre, values=list(_PRESETS), state="readonly", width=10).grid(
            row=3, column=5, sticky="w", padx=6, pady=(4, 0))
        cb_v.bind("<<ComboboxSelected>>", lambda _e: v_crf.set(_CRF_DEFAULT.get(v_vc.get(), "18")))
        v_crf.set(_CRF_DEFAULT.get(v_vc.get(), v_crf.get()) if v_crf.get() == sug["crf"] else v_crf.get())

        # ---- hang ----
        af_ = ttk.LabelFrame(fr, text=L("Hang", "Audio"), padding=6)
        af_.pack(fill="x", pady=3)
        ttk.Label(af_, text=L("Kodek", "Codec")).grid(row=0, column=0, sticky="w")
        ttk.Combobox(af_, textvariable=v_ac, values=["auto", "copy", "aac", "ac3", "libopus", "flac"],
                     state="readonly", width=10).grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(af_, text=L("bitráta (üresen: automatikus)", "bitrate (empty: automatic)")).grid(
            row=0, column=2, sticky="e", padx=(12, 0))
        ttk.Entry(af_, textvariable=v_abr, width=7).grid(row=0, column=3, sticky="w", padx=6)
        ttk.Label(af_, foreground="#555555", wraplength=560, justify="left", text=L(
            "auto: másolás, ha belefér a konténerbe; újrakódolásnál (és hangjavításnál) a konténerhez illő kodek.",
            "auto: copy if it fits the container; when re-encoding (or fixing audio) a codec that suits the "
            "container.")).grid(row=1, column=0, columnspan=4, sticky="w", pady=(3, 0))

        # ---- technikák ----
        tf = ttk.LabelFrame(fr, text=L("Javítási technikák (ffmpeg)", "Repair techniques (ffmpeg)"), padding=6)
        tf.pack(fill="x", pady=3)
        items = (
            ("bytefix", "Bájtszintű TS-javítás: szinkron-visszatalálás, ismétlődő csomagok, CC-számláló (csak TS/M2TS forrásnál)",
             "Byte-level TS repair: resync, duplicate packets, CC counter (TS/M2TS sources only)"),
            ("errtolerant", "Sérült adat átugrása (-err_detect ignore_err, +discardcorrupt)",
             "Skip damaged data (-err_detect ignore_err, +discardcorrupt)"),
            ("genpts", "Hiányzó / hibás PTS újragenerálása (+genpts)", "Regenerate missing / bad PTS (+genpts)"),
            ("igndts", "Hibás DTS figyelmen kívül hagyása (+igndts) – ha a DTS nem növekvő",
             "Ignore the faulty DTS (+igndts) – when the DTS is not increasing"),
            ("bigprobe", "Hosszabb fájlvizsgálat (-analyzeduration / -probesize 200M) – hiányzó fejléc / kodekadat esetén",
             "Longer file probing (-analyzeduration / -probesize 200M) – for missing headers / codec data"),
            ("paramsets", "SPS/PPS ismétlése minden kulcskockánál (dump_extra) – TS/M2TS kimenet, másolt H.264/HEVC",
             "Repeat SPS/PPS at every key frame (dump_extra) – TS/M2TS output, copied H.264/HEVC"),
            ("async", "Hang-rések és csúszás kiegyenlítése (aresample=async=1000) – a hang újrakódolódik",
             "Fix audio gaps and drift (aresample=async=1000) – the audio is re-encoded"),
            ("avalign", "Korán induló hang igazítása a képhez (atrim) – a hang újrakódolódik",
             "Align audio that starts before the picture (atrim) – the audio is re-encoded"),
            ("cfr", "Állandó képfrekvencia (fps szűrő) – a videót újrakódolja",
             "Constant frame rate (fps filter) – re-encodes the video"),
            ("shortgop", "Rövid GOP: kulcskocka kb. 0,5 s-onként (gyors keresés) – a videót újrakódolja",
             "Short GOP: a key frame about every 0.5 s (fast seeking) – re-encodes the video"))
        for i, (k, hu, en) in enumerate(items):
            cb = ttk.Checkbutton(tf, text=L(hu, en), variable=tech[k])
            cb.grid(row=i, column=0, sticky="w")
            if k == "avalign" and not (av_ms is not None and av_ms < -80.0):
                tech[k].set(False)
                cb.state(["disabled"])

        bt = ttk.Frame(fr)
        bt.pack(fill="x", pady=(8, 0))

        def collect():
            o = dict(DEFAULT_REPAIR)
            o.update(container=v_cont.get(), mode=v_mode.get(), vcodec=v_vc.get(), crf=v_crf.get().strip(),
                     preset=v_pre.get(), acodec=v_ac.get(), abitrate=v_abr.get().strip())
            o.update({k: bool(v.get()) for k, v in tech.items()})
            return o

        def ok(_e=None):
            res["v"] = collect()
            win.destroy()

        def recommended():
            for k in _TECH_KEYS:
                if not (k == "avalign" and not (av_ms is not None and av_ms < -80.0)):
                    tech[k].set(bool(sug[k]))
            v_mode.set(sug["mode"])

        ttk.Button(bt, text=L("Mégse", "Cancel"), command=win.destroy).pack(side="right")
        ttk.Button(bt, text=L("Indítás…", "Start…"), command=ok).pack(side="right", padx=6)
        ttk.Button(bt, text=L("Ajánlott beállítás", "Recommended"), command=recommended).pack(side="left")
        win.bind("<Escape>", lambda _e: win.destroy())
        try:
            win.grab_set()
        except Exception:
            pass
        win.focus_force()
        win.wait_window()
        return res["v"]

    def repair(self):
        if not self.rep or self.busy:
            return
        ff = ffmpeg_path_guess(self.core)
        if not ff:
            self.mb.showerror("Lossless Video Toolkit",
                              L("A javításhoz az ffmpeg szükséges (a PATH-on és a joiner beállításai között sem található).",
                                "Repair needs ffmpeg (not found on PATH or in the joiner settings)."))
            return
        if not self._confirm_errors_saved():
            return
        av_ms = getattr(self.rep, "av_start_ms", None)
        opts = self._ask_repair_options(av_ms)
        if not opts:
            return
        cont = opts["container"] if opts["container"] in _REPAIR_CONT else "mkv"
        dst = self._out_path("_javitott", _REPAIR_CONT[cont]["ext"],
                             self._save_types([cont] + [k for k in _REPAIR_ORDER if k != cont]))
        if not dst:
            return
        if os.path.normcase(os.path.abspath(dst)) == os.path.normcase(os.path.abspath(self.path)):
            self.mb.showerror("Lossless Video Toolkit",
                              L("A cél nem lehet maga az eredeti fájl: válassz másik nevet.",
                                "The target cannot be the original file: choose another name."))
            return
        src, fp = self.path, ffprobe_path_guess(self.core)
        log_path = dst + ".javitas-naplo.txt"

        def work(prog, canc):
            res = repair_verified(src, dst, ff, fp, prog, canc, opts, av_ms)
            res["log"] = log_path
            return res

        self._start(L("Javítás", "Repair"), work, lambda res: self._after_repair(res, dst))

    def _confirm_errors_saved(self):
        if getattr(self, "_errors_file", None) and os.path.isfile(self._errors_file):
            return True
        ans = self.mb.askyesno("Lossless Video Toolkit",
                               L("A javítás előtt a hibákat lemezre kell írni. Most mentsük a hibákat?",
                                 "Errors must be written to disk before repair. Save them now?"))
        if ans:
            self.save_errors()
        return bool(getattr(self, "_errors_file", None))

    def _after_repair(self, res, dst):
        with open(res["log"], "w", encoding="utf-8-sig") as f:
            f.write(L("Javítási napló\n", "Repair log\n"))
            f.write("src: %s\ndst: %s\n" % (res["src"], res["dst"]))
            for name, data in res["steps"]:
                f.write("\n[%s]\n" % name)
                if isinstance(data, dict):
                    for k, val in data.items():
                        f.write("  %s: %s\n" % (k, val))
                else:
                    f.write("  %s\n" % (data,))
            f.write("\nmethod: %s\nclean: %s\n" % (res.get("method"), res.get("clean")))
        if res.get("method") is None:
            self.mb.showerror("Lossless Video Toolkit",
                              L("A javítás nem készített kimenetet. Napló: %s", "Repair produced no output. Log: %s")
                              % res["log"])
            return
        v = res.get("verify") or {}
        mode = {"remux": L("újracsomagolás (veszteségmentes, a videó változatlan)", "remux (lossless, video unchanged)"),
                "reencode": L("újrakódolás", "re-encode")}.get(res["method"], "?")
        mode += " – %s" % _REPAIR_CONT.get(res.get("container"), {}).get("label", "")
        if res["clean"]:
            head = L("Javítás kész. Az új fájl dekódolása és DTS-ellenőrzése HIBÁTLAN.\n"
                     "Az esetleg elveszett tartalmat (pl. kivágott csomagok miatti rést) nem lehet visszahozni.",
                     "Repair done. The new file decodes and the DTS check is CLEAN.\n"
                     "Content lost from the source (e.g. a gap from removed packets) cannot be restored.")
        else:
            head = L("A javítás NEM tudta tisztára csinálni a fájlt.\n"
                     "Maradt: dekódolási hiba %s, időzítési üzenet %s, DTS-visszaugrás %s.",
                     "The repair could NOT make the file clean.\n"
                     "Remaining: decoding errors %s, timing messages %s, DTS reversals %s.") % (
                v.get("dec", "?"), v.get("timing", "?"), v.get("nonmono", "?"))
        msg = head + "\n\n" + L("Mód: %s\nKimenet: %s\nNapló: %s\n\nElemezzük az új fájlt?",
                                "Method: %s\nOutput: %s\nLog: %s\n\nAnalyze the new file?") % (
            mode, res["dst"], res["log"])
        if self.mb.askyesno("Lossless Video Toolkit", msg):
            self.path = dst
            self.var_path.set(dst)
            self.run()

    def remux(self):
        if not self.path or self.busy:
            return
        ff = ffmpeg_path_guess(self.core)
        if not ff:
            self.mb.showerror("Lossless Video Toolkit",
                              L("Az ffmpeg nem található (a PATH-on és a joiner beállításai között sem).",
                                "ffmpeg was not found (neither on PATH nor in the joiner settings)."))
            return
        dst = self._out_path("_ujracsomagolt", _REPAIR_CONT[_cont_from_ext(self.path, "mkv")]["ext"],
                             self._save_types(_REPAIR_ORDER))
        if not dst:
            return
        src = self.path

        def work(prog, canc):
            prog(0.1)
            rc, err = ffmpeg_remux(src, dst, ff, canc)
            prog(1.0)
            return {"rc": rc, "err": err, "dst": dst}

        self._start(L("FFmpeg-újracsomagolás", "FFmpeg remux"), work, self._after_remux)

    def avfix(self):
        if not self.path or self.busy or self.rep is None:
            return
        ms = getattr(self.rep, "av_start_ms", None)
        if ms is None or ms >= -80.0:
            return
        ff = ffmpeg_path_guess(self.core)
        if not ff:
            self.mb.showerror("Lossless Video Toolkit",
                              L("Az ffmpeg nem található (a PATH-on és a joiner beállításai között sem).",
                                "ffmpeg was not found (neither on PATH nor in the joiner settings)."))
            return
        dst = self._out_path("_avigazitott", _REPAIR_CONT[_cont_from_ext(self.path, "mkv")]["ext"],
                             self._save_types(_REPAIR_ORDER))
        if not dst:
            return
        src, secs = self.path, -ms / 1000.0

        def work(prog, canc):
            prog(0.1)
            rc, err = ffmpeg_trim_audio_head(src, dst, secs, ff, canc)
            prog(1.0)
            return {"rc": rc, "err": err, "dst": dst}

        self._start(L("A/V igazítás", "A/V align"), work, self._after_remux)

    def _after_remux(self, res):
        if res["rc"] == 0:
            if self.mb.askyesno("Lossless Video Toolkit",
                                L("Az újracsomagolás kész:\n%s\n\nElemezzük?" % res["dst"],
                                  "Remux done:\n%s\n\nAnalyze it?" % res["dst"])):
                self.path = res["dst"]
                self.var_path.set(res["dst"])
                self.run()
        else:
            self.mb.showerror("Lossless Video Toolkit",
                              L("Az ffmpeg hibát adott (%d):\n%s" % (res["rc"], res["err"][-800:]),
                                "ffmpeg failed (%d):\n%s" % (res["rc"], res["err"][-800:])))

    def probe(self):
        if not self.path or self.busy:
            return
        fp = ffprobe_path_guess(self.core)
        if not fp:
            self.mb.showerror("Lossless Video Toolkit",
                              L("Az ffprobe nem található.", "ffprobe was not found."))
            return
        src = self.path

        def work(prog, canc):
            prog(0.1)
            r = ffprobe_check(src, fp)
            prog(1.0)
            return r

        self._start(L("Külső ellenőrzés", "External check"), work, self._after_probe)

    def _after_probe(self, ext):
        if not self.rep or self.rep.path != self.path:
            self.mb.showinfo("Lossless Video Toolkit",
                             L("Az eredmény a saját elemzéshez kerül. Előbb várd meg az elemzés végét.",
                               "The result is added to the own analysis. Wait for the analysis to finish first."))
            return
        # ne duplázzuk az ffprobe-szakaszt (a többi külső szakasz, pl. az ffmpeg-dekódolás, marad)
        ffp_title = L("Külső ellenőrzés (ffprobe)", "External check (ffprobe)")
        self.rep.sections = [s for s in self.rep.sections if s.title != ffp_title]
        compare_with_ffprobe(self.rep, ext)
        self._show(self.rep)

    # ---- súgó ----
    def show_help(self):
        tk = self.tk
        if self._help_win is not None:
            try:
                self._help_win.lift()
                return
            except Exception:
                self._help_win = None
        w = tk.Toplevel(self.root)
        w.title(L("Súgó – Videó-elemző", "Help – Video analyzer"))
        w.geometry("640x560")
        t = tk.Text(w, wrap="word", padx=12, pady=10)
        sb = self.ttk.Scrollbar(w, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        t.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        t.insert("1.0", L(HELP_ANALYZER_HU, HELP_ANALYZER_EN))
        t.configure(state="disabled")
        self._help_win = w


def ffprobe_path_guess(core=None):
    import shutil
    if core is not None and getattr(core, "EXTERNAL_OK", True) is False:
        return None
    for attr in ("FFPROBE", "FFPROBE_PATH", "ffprobe_path"):
        p = getattr(core, attr, None) if core is not None else None
        if isinstance(p, str) and p and os.path.isfile(p):
            return p
    fp = ffmpeg_path_guess(core)
    if fp:
        cand = os.path.join(os.path.dirname(fp), "ffprobe" + (".exe" if os.name == "nt" else ""))
        if os.path.isfile(cand):
            return cand
    return shutil.which("ffprobe")


def tkfont_bold(tk):
    try:
        import tkinter.font as tkfont
        f = tkfont.nametofont("TkDefaultFont").copy()
        f.configure(weight="bold")
        return f
    except Exception:
        return None


def tkfont_mono(tk):
    try:
        import tkinter.font as tkfont
        return tkfont.nametofont("TkFixedFont")
    except Exception:
        return None


# ------------------------------------------------------------------ CLI ------

def main(argv):
    ap = argparse.ArgumentParser(description="Lossless Video Toolkit – Video analyzer / Videó-elemző")
    ap.add_argument("file")
    ap.add_argument("-o", "--output", help="write the report to a file (UTF-8) / jelentés fájlba (UTF-8)")
    args = ap.parse_args(argv)
    rep = analyze_file(args.file, None, lambda f: None, None)
    text = rep.to_text()
    if args.output:
        with open(args.output, "w", encoding="utf-8-sig") as f:
            f.write(text)
        print(L("Jelentés: %s", "Report: %s") % args.output)
    else:
        sys.stdout.write(text)
    return 2 if rep.verdict == "E" else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
