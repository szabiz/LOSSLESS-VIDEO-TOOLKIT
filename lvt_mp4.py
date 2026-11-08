#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 szabiz <szabiz@yahoo.com>
# Copyright (c) 2026 szabiz <szabiz@yahoo.com>
"""
Lossless Video Toolkit - MP4 / MOV / M4V modul (lvt_mp4.py)
===========================================================
Veszteségmentes (újrakódolás nélküli) vágás és egyesítés kulcskockánál MP4 / M4V / MOV fájlokon.

Saját fejlesztésű, eredeti kód MIT licenc alatt. Kizárólag a Python szabványos könyvtárát használja,
külső programot nem hív meg. A formátum az ISO alapú médiafájl-formátum (ISO/IEC 14496-12) nyilvános
szerkezetét követi; a kód ebből készült, nem másolt kódból.

Támogatott: nem töredezett (nem fragmentált) fájlok, több sáv (videó, hang, felirat), B-kockák,
nyitott GOP (a kulcskockát követő, korábbi megjelenítési idejű kockákat kihagyja).
"""
import bisect
import os
import struct
import sys


def _lang():
    """Active UI language, English by default; the host program owns the setting."""
    for name in ("mts_joiner", "__main__", "lvt_ffmpeg"):
        value = getattr(sys.modules.get(name), "LANG", None)
        if value in ("hu", "en"):
            return value
    value = (os.environ.get("LVT_LANG") or "").strip().lower()
    return value if value in ("hu", "en") else "en"


def _(hu, en):
    return hu if _lang() == "hu" else en


MODULE_VERSION = "1.0"
MP4_EXTS = (".mp4", ".m4v", ".mov")

_CONT = (b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts")


class Mp4Error(Exception):
    pass


# ------------------------------------------------------------ dobozok ---

def _boxes(data, start, end):
    p = start
    while p + 8 <= end:
        size, typ = struct.unpack_from(">I4s", data, p)
        hl = 8
        if size == 1:
            if p + 16 > end:
                raise Mp4Error(_("Hibás doboz-fejléc a(z) %d. bájtnál.", "Invalid box header at byte %d.") % p)
            size = struct.unpack_from(">Q", data, p + 8)[0]
            hl = 16
        elif size == 0:
            size = end - p
        if size < hl or p + size > end:
            raise Mp4Error(_("Hibás doboz a(z) %d. bájtnál.", "Invalid box at byte %d.") % p)
        yield typ, p, p + hl, p + size
        p += size


def _top(f, fsize):
    out = []
    pos = 0
    while pos + 8 <= fsize:
        f.seek(pos)
        h = f.read(16)
        size, typ = struct.unpack(">I4s", h[:8])
        hl = 8
        if size == 1:
            if len(h) < 16:
                raise Mp4Error(_("Csonka doboz-fejléc a(z) %d. bájtnál.", "Truncated box header at byte %d.") % pos)
            size = struct.unpack(">Q", h[8:16])[0]
            hl = 16
        elif size == 0:
            size = fsize - pos
        if size < hl or pos + size > fsize:
            raise Mp4Error(_("A fájl csonka vagy sérült (hibás doboz a(z) %d. bájtnál).", "The file is truncated or damaged (invalid box at byte %d).") % pos)
        out.append((typ, pos, pos + hl, pos + size))
        pos += size
    if pos != fsize and fsize - pos > 0:
        raise Mp4Error(_("A fájl végén felesleges vagy csonka adat van (%d bájt).", "There is extra or truncated data at the end of the file (%d bytes).") % (fsize - pos))
    return out


class _Node:
    __slots__ = ("typ", "data", "kids")

    def __init__(self, typ, data=b"", kids=None):
        self.typ, self.data, self.kids = typ, data, kids

    def dump(self):
        payload = b"".join(k.dump() for k in self.kids) if self.kids is not None else self.data
        return struct.pack(">I4s", len(payload) + 8, self.typ) + payload

    def find(self, typ):
        for k in (self.kids or []):
            if k.typ == typ:
                return k
        return None


def _parse_tree(d, start, end):
    nodes = []
    for typ, p, ds, e in _boxes(d, start, end):
        if typ in _CONT:
            nodes.append(_Node(typ, kids=_parse_tree(d, ds, e)))
        else:
            nodes.append(_Node(typ, bytes(d[ds:e])))
    return nodes


# ------------------------------------------------------------ táblák ---

def _read_stts(b):
    n = struct.unpack_from(">I", b, 4)[0]
    out = []
    for i in range(n):
        c, dl = struct.unpack_from(">II", b, 8 + i * 8)
        out.extend([dl] * c)
    return out


def _read_ctts(b):
    n = struct.unpack_from(">I", b, 4)[0]
    out = []
    for i in range(n):
        c, o = struct.unpack_from(">Ii", b, 8 + i * 8)
        out.extend([o] * c)
    return out


def _read_stsz(b):
    size, n = struct.unpack_from(">II", b, 4)
    if size:
        return [size] * n
    return list(struct.unpack_from(">%dI" % n, b, 12))


def _sample_offsets(chunks, stsc, sizes):
    offs = []
    si = 0
    nch = len(chunks)
    ns = len(sizes)
    for k, (first, spc, _d) in enumerate(stsc):
        last = stsc[k + 1][0] - 1 if k + 1 < len(stsc) else nch
        for c in range(first, last + 1):
            if c < 1 or c > nch:
                break
            o = chunks[c - 1]
            for _ in range(spc):
                if si >= ns:
                    return offs
                offs.append(o)
                o += sizes[si]
                si += 1
    return offs


class _Track:
    pass


def _codec(stsd):
    d = stsd.data
    if len(d) < 16:
        return None, 0
    typ = bytes(d[12:16])
    i = d.find(b"avcC")
    if i >= 0 and typ in (b"avc1", b"avc3", b"avc2", b"avc4"):
        return "avc", (d[i + 8] & 3) + 1
    i = d.find(b"hvcC")
    if i >= 0:
        return "hevc", (d[i + 4 + 21] & 3) + 1
    return None, 0


def _make_track(node):
    t = _Track()
    t.node = node
    tkhd, mdia = node.find(b"tkhd"), node.find(b"mdia")
    if tkhd is None or mdia is None:
        raise Mp4Error(_("Hibás sáv (hiányzik a tkhd vagy az mdia).", "Invalid track (the tkhd or mdia box is missing)."))
    t.id = struct.unpack_from(">I", tkhd.data, 12 if tkhd.data[0] == 0 else 20)[0]
    mdhd, hdlr, minf = mdia.find(b"mdhd"), mdia.find(b"hdlr"), mdia.find(b"minf")
    if mdhd is None or hdlr is None or minf is None:
        raise Mp4Error(_("Hibás sáv (hiányzik az mdhd, hdlr vagy minf).", "Invalid track (the mdhd, hdlr or minf box is missing)."))
    if mdhd.data[0] == 0:
        t.ts, t.mdur = struct.unpack_from(">II", mdhd.data, 12)
    else:
        t.ts = struct.unpack_from(">I", mdhd.data, 20)[0]
        t.mdur = struct.unpack_from(">Q", mdhd.data, 24)[0]
    t.ts = t.ts or 1
    t.handler = bytes(hdlr.data[8:12])
    stbl = minf.find(b"stbl")
    if stbl is None:
        raise Mp4Error(_("Hibás sáv (hiányzik az stbl).", "Invalid track (the stbl box is missing)."))
    g = stbl.find
    if g(b"stz2") is not None:
        raise Mp4Error(_("Tömörített mintaméret-tábla (stz2) – nem támogatott.", "Compressed sample size table (stz2) – not supported."))
    stsd, stts, stsc, stsz = g(b"stsd"), g(b"stts"), g(b"stsc"), g(b"stsz")
    stco, co64 = g(b"stco"), g(b"co64")
    if None in (stsd, stts, stsc, stsz) or (stco is None and co64 is None):
        raise Mp4Error(_("Hiányos mintatáblák (stsd/stts/stsc/stsz/stco).", "Incomplete sample tables (stsd/stts/stsc/stsz/stco)."))
    t.stsd = stsd
    t.codec, t.nal_len = _codec(stsd)
    t.deltas = _read_stts(stts.data)
    t.sizes = _read_stsz(stsz.data)
    n = struct.unpack_from(">I", stsc.data, 4)[0]
    t.stsc = [struct.unpack_from(">III", stsc.data, 8 + i * 12) for i in range(n)]
    if any(e[2] != 1 for e in t.stsc):
        raise Mp4Error(_("Több mintaleíró (stsd) egy sávban – nem támogatott.", "Multiple sample descriptions (stsd) in one track – not supported."))
    if co64 is not None:
        cn = struct.unpack_from(">I", co64.data, 4)[0]
        chunks = list(struct.unpack_from(">%dQ" % cn, co64.data, 8))
    else:
        cn = struct.unpack_from(">I", stco.data, 4)[0]
        chunks = list(struct.unpack_from(">%dI" % cn, stco.data, 8))
    t.offs = _sample_offsets(chunks, t.stsc, t.sizes)
    ctts = g(b"ctts")
    t.cto = _read_ctts(ctts.data) if ctts is not None else None
    t.ctts_ver = ctts.data[0] if ctts is not None else 0
    stss = g(b"stss")
    if stss is not None:
        sn = struct.unpack_from(">I", stss.data, 4)[0]
        t.sync = list(struct.unpack_from(">%dI" % sn, stss.data, 8))
        t.syncset = set(i - 1 for i in t.sync)
    else:
        t.sync, t.syncset = None, None
    t.dts = []
    acc = 0
    for dl in t.deltas:
        t.dts.append(acc)
        acc += dl
    return t


def _load_top(path, fsize):
    with open(path, "rb") as f:
        top = _top(f, fsize)
        types = [b[0] for b in top]
        if b"moov" not in types:
            raise Mp4Error(_("Nincs moov doboz – nem támogatott vagy sérült MP4.", "No moov box – unsupported or damaged MP4."))
        if b"moof" in types:
            raise Mp4Error(_("Töredezett (fragmentált) MP4 – ezt a modul még nem támogatja.", "Fragmented MP4 – this module does not support it yet."))
        ftyp = b""
        for typ, p, ds, e in top:
            if typ == b"ftyp":
                f.seek(p)
                ftyp = f.read(e - p)
                break
        mo = next(b for b in top if b[0] == b"moov")
        f.seek(mo[2])
        mdata = f.read(mo[3] - mo[2])
    return top, mdata, ftyp


class Mp4Info:
    kind = "mp4"

    def __init__(self, path):
        self.path = path
        self.name = os.path.basename(path)
        self.size = os.path.getsize(path)
        self.error = None
        top, mdata, self.ftyp_raw = _load_top(path, self.size)
        self.mdats = [(b[2], b[3]) for b in top if b[0] == b"mdat"]
        tree = _parse_tree(mdata, 0, len(mdata))
        if any(n.typ in (b"mvex", b"cmov") for n in tree):
            raise Mp4Error(_("Töredezett vagy tömörített moov – nem támogatott.", "Fragmented or compressed moov – not supported."))
        self.moov_kids = tree
        mvhd = next((n for n in tree if n.typ == b"mvhd"), None)
        if mvhd is None:
            raise Mp4Error(_("Hiányzik az mvhd doboz.", "The mvhd box is missing."))
        self.movie_ts = struct.unpack_from(">I", mvhd.data, 12 if mvhd.data[0] == 0 else 20)[0] or 1000
        self.tracks = [_make_track(n) for n in tree if n.typ == b"trak"]
        self.vtrack = next((t for t in self.tracks if t.handler == b"vide" and t.sizes), None)
        if self.vtrack is None:
            raise Mp4Error(_("Nincs videósáv a fájlban.", "The file contains no video track."))
        self.duration = self.vtrack.mdur / float(self.vtrack.ts)


def open_info(path):
    return Mp4Info(path)


# ------------------------------------------------------------ kulcskockák ---

def _nal_kind(codec, L, head):
    p, types = 0, []
    while L and p + L < len(head):
        n = int.from_bytes(head[p:p + L], "big")
        b = head[p + L]
        types.append((b & 0x1F) if codec == "avc" else ((b >> 1) & 0x3F))
        p += L + n
    if codec == "avc":
        if 5 in types:
            return "idr"
        return "rec" if 1 in types else "idr"
    if codec == "hevc":
        if any(x in (19, 20) for x in types):
            return "idr"
        return "rec" if any(x in (16, 17, 18, 21) for x in types) else "idr"
    return "idr"


def scan_keyframes(inf, progress=None, cancel=None):
    # (idő_mp, mintaindex, fájlbeli_pozíció, típus) - a vágó (lvt_cutter) kfs formátuma
    progress = progress or (lambda f: None)
    v = inf.vtrack
    n = len(v.sizes)
    idxs = [i - 1 for i in v.sync if 1 <= i <= n] if v.sync is not None else list(range(n))
    kfs = []
    with open(inf.path, "rb") as f:
        for k, i in enumerate(idxs):
            if cancel is not None and cancel.is_set():
                raise Mp4Error("cancelled")
            kind = "idr"
            if v.codec and i < len(v.offs):
                f.seek(v.offs[i])
                kind = _nal_kind(v.codec, v.nal_len, f.read(min(v.sizes[i], 2048)))
            off = v.offs[i] if i < len(v.offs) else 0
            kfs.append((v.dts[i] / float(v.ts), i, off, kind))
            if k % 256 == 0:
                progress((k + 1) / float(len(idxs) or 1))
    return kfs


# ------------------------------------------------------------ vágás ---

def _nearest(t, sec):
    x = sec * t.ts
    k = bisect.bisect_left(t.dts, x)
    n = len(t.dts)
    if k >= n:
        return n
    if k > 0 and abs(t.dts[k - 1] - x) <= abs(t.dts[k] - x):
        return k - 1
    return k


def _select(inf, rng, first):
    # Egy tartomány mintái sávonként: {sáv_index: (megtartott_indexek, deltak, trim)}
    s, e = rng
    v = inf.vtrack
    n = len(v.sizes)
    i0, i1 = int(s[1]), min(int(e[1]), n)
    if i1 <= i0:
        raise Mp4Error(_("Üres vagy fordított tartomány.", "Empty or reversed range."))
    cto = v.cto

    def pts(j):
        return v.dts[j] + (cto[j] if cto and j < len(cto) else 0)

    p0 = pts(i0)
    dropped = set()
    j = i0 + 1
    while j < i1 and pts(j) < p0:      # vezető (nyitott GOP) kockák: az előző GOP-ra hivatkoznak
        dropped.add(j)
        j += 1
    kept = [i for i in range(i0, i1) if i not in dropped]
    deltas = []
    for i in kept:
        d = v.deltas[i]
        j = i + 1
        while j in dropped:
            d += v.deltas[j]
            j += 1
        deltas.append(d)
    t0 = p0 / float(v.ts)
    t1 = pts(i1) / float(v.ts) if i1 < n else float("inf")
    sel = {}
    vi = inf.tracks.index(v)
    sel[vi] = (kept, deltas, max(0, cto[i0]) if cto and i0 < len(cto) else 0)
    for ti, t in enumerate(inf.tracks):
        if t is v or not t.sizes:
            continue
        a, b = _nearest(t, t0), _nearest(t, t1)
        if b <= a:
            continue
        a0 = a - 1 if (first and a > 0 and t.handler == b"soun") else a   # hang: 1 előkészítő keret
        trim = max(0, int(round(t0 * t.ts)) - t.dts[a0]) if first else 0
        sel[ti] = (list(range(a0, b)), t.deltas[a0:b], trim)
    return sel


def _rle(vals):
    out = []
    for v in vals:
        if out and out[-1][0] == v:
            out[-1][1] += 1
        else:
            out.append([v, 1])
    return out


def _patch(data, off0, off1, value):
    b = bytearray(data)
    if b[0] == 1:
        struct.pack_into(">Q", b, off1, value)
    else:
        struct.pack_into(">I", b, off0, min(value, 0xFFFFFFFF))
    return bytes(b)


def _rebuild_trak(t, a, chunks, base, wide, mts):
    media_dur = sum(a["deltas"])
    trim = a["trim"] or 0
    seg = max(0, int(round((media_dur - trim) * mts / float(t.ts))))
    if seg < 0x7FFFFFFF and trim < 0x7FFFFFFF:
        elst = b"\x00\x00\x00\x00" + struct.pack(">I", 1) + struct.pack(">Iihh", seg, trim, 1, 0)
    else:
        elst = b"\x01\x00\x00\x00" + struct.pack(">I", 1) + struct.pack(">Qqhh", seg, trim, 1, 0)
    edts = _Node(b"edts", kids=[_Node(b"elst", elst)])

    r = _rle(a["deltas"])
    stts = _Node(b"stts", struct.pack(">II", 0, len(r)) + b"".join(struct.pack(">II", c, v) for v, c in r))
    stbl_kids = [t.stsd, stts]
    if t.cto is not None:
        r = _rle(a["cto"])
        stbl_kids.append(_Node(b"ctts", bytes([t.ctts_ver, 0, 0, 0]) + struct.pack(">I", len(r)) +
                               b"".join(struct.pack(">Ii", c, v) for v, c in r)))
    if t.sync is not None:
        sy = a["sync"]
        stbl_kids.append(_Node(b"stss", struct.pack(">II", 0, len(sy)) + struct.pack(">%dI" % len(sy), *sy)))
    ent = []
    for ci, ch in enumerate(chunks, 1):
        if not ent or ent[-1][1] != ch[1]:
            ent.append((ci, ch[1]))
    stbl_kids.append(_Node(b"stsc", struct.pack(">II", 0, len(ent)) +
                           b"".join(struct.pack(">III", fc, spc, 1) for fc, spc in ent)))
    sz = a["sizes"]
    if sz and all(x == sz[0] for x in sz):
        stbl_kids.append(_Node(b"stsz", struct.pack(">III", 0, sz[0], len(sz))))
    else:
        stbl_kids.append(_Node(b"stsz", struct.pack(">III", 0, 0, len(sz)) + struct.pack(">%dI" % len(sz), *sz)))
    offs = [base + ch[2] for ch in chunks]
    if wide:
        stbl_kids.append(_Node(b"co64", struct.pack(">II", 0, len(offs)) + struct.pack(">%dQ" % len(offs), *offs)))
    else:
        stbl_kids.append(_Node(b"stco", struct.pack(">II", 0, len(offs)) + struct.pack(">%dI" % len(offs), *offs)))
    new_stbl = _Node(b"stbl", kids=stbl_kids)

    kids = []
    for k in t.node.kids:
        if k.typ == b"tkhd":
            kids.append(_Node(b"tkhd", _patch(k.data, 20, 28, seg)))
            kids.append(edts)
        elif k.typ == b"edts":
            continue
        elif k.typ == b"mdia":
            mk = []
            for m in k.kids:
                if m.typ == b"mdhd":
                    mk.append(_Node(b"mdhd", _patch(m.data, 16, 24, media_dur)))
                elif m.typ == b"minf":
                    mk.append(_Node(b"minf", kids=[new_stbl if x.typ == b"stbl" else x for x in m.kids]))
                else:
                    mk.append(m)
            kids.append(_Node(b"mdia", kids=mk))
        else:
            kids.append(k)
    return _Node(b"trak", kids=kids), seg


def _build_moov(inf, acc, chunks, base, wide):
    mts = inf.movie_ts
    new = {}
    maxdur = 0
    for ti, t in enumerate(inf.tracks):
        a = acc[ti]
        if not a["sizes"]:
            continue
        node, seg = _rebuild_trak(t, a, chunks[ti], base, wide, mts)
        new[id(t.node)] = node
        maxdur = max(maxdur, seg)
    kids = []
    for k in inf.moov_kids:
        if k.typ == b"trak":
            if id(k) in new:
                kids.append(new[id(k)])
        elif k.typ == b"mvhd":
            kids.append(_Node(b"mvhd", _patch(k.data, 16, 24, maxdur)))
        else:
            kids.append(k)
    return _Node(b"moov", kids=kids).dump()


def _write_output(inf, path, grp, progress, cancel):
    ntr = len(inf.tracks)
    acc = [{"sizes": [], "deltas": [], "cto": [], "sync": [], "src": [], "trim": 0} for _ in range(ntr)]
    order = []
    for ri, rng in enumerate(grp):
        sel = _select(inf, rng, ri == 0)
        marks = {}
        for ti, (kept, deltas, trim) in sel.items():
            t, a = inf.tracks[ti], acc[ti]
            base = len(a["sizes"])
            marks[ti] = base
            a["sizes"] += [t.sizes[i] for i in kept]
            a["deltas"] += deltas
            if t.cto is not None:
                a["cto"] += [t.cto[i] if i < len(t.cto) else 0 for i in kept]
            if t.sync is not None:
                ss = t.syncset
                a["sync"] += [base + k + 1 for k, i in enumerate(kept) if i in ss]
            a["src"] += [t.offs[i] for i in kept]
            if ri == 0:
                a["trim"] = trim
        ents = []
        for ti, base in marks.items():
            a = acc[ti]
            for pos in range(base, len(a["sizes"])):
                ents.append((a["src"][pos], a["sizes"][pos], ti, pos))
        ents.sort()
        order.extend(ents)

    chunks = [[] for _ in range(ntr)]
    cur, prev = 0, None
    for src, size, ti, pos in order:
        if ti != prev:
            chunks[ti].append([pos, 0, cur])
            prev = ti
        chunks[ti][-1][1] += 1
        cur += size
    total = cur

    ftyp = inf.ftyp_raw
    hdr_len = 16 if total + 8 > 0xFFFFFFFF else 8
    wide = False
    moov = _build_moov(inf, acc, chunks, 0, wide)
    if len(ftyp) + len(moov) + hdr_len + total > 0xFFFFFFFF:
        wide = True
        moov = _build_moov(inf, acc, chunks, 0, wide)
    base = len(ftyp) + len(moov) + hdr_len
    moov2 = _build_moov(inf, acc, chunks, base, wide)
    if len(moov2) != len(moov):
        raise Mp4Error(_("Belső hiba: a moov mérete változott.", "Internal error: the moov size changed."))

    with open(inf.path, "rb") as fi, open(path, "wb") as fo:
        fo.write(ftyp)
        fo.write(moov2)
        if hdr_len == 8:
            fo.write(struct.pack(">I4s", total + 8, b"mdat"))
        else:
            fo.write(struct.pack(">I4sQ", 1, b"mdat", total + 16))
        done = 0
        k = 0
        n = len(order)
        while k < n:
            if cancel is not None and cancel.is_set():
                raise Mp4Error("cancelled")
            start = order[k][0]
            end = start + order[k][1]
            k += 1
            while k < n and order[k][0] == end:
                end += order[k][1]
                k += 1
            fi.seek(start)
            left = end - start
            while left > 0:
                b = fi.read(min(left, 1 << 22))
                if not b:
                    raise Mp4Error(_("A forrásfájl váratlanul véget ért.", "The source file ended unexpectedly."))
                fo.write(b)
                left -= len(b)
                done += len(b)
            if progress:
                progress(min(1.0, done / float(total or 1)))


def cut_ranges(inf, ranges, out_paths, merge=False, progress=None, log=None, cancel=None):
    dest = [out_paths] if merge else list(out_paths)
    groups = [list(ranges)] if merge else [[r] for r in ranges]
    tmps = [p + ".part" for p in dest]
    try:
        for tmp, grp in zip(tmps, groups):
            _write_output(inf, tmp, grp, progress, cancel)
        for t_, p in zip(tmps, dest):
            os.replace(t_, p)
        return True
    except BaseException:
        for t_ in tmps:
            try:
                os.remove(t_)
            except OSError:
                pass
        raise


# ------------------------------------------------------------ ellenőrzés ---

def verify(path, expected=None, progress=None, cancel=None):
    # Visszaadja: [(szint, kulcs, argumentumok)] - a lvt_cutter ellenőrzője jeleníti meg
    out = []

    def add(level, key, *args):
        out.append((level, key, args))

    size = os.path.getsize(path)
    try:
        top, mdata, _ftyp = _load_top(path, size)
        tree = _parse_tree(mdata, 0, len(mdata))
    except Mp4Error as e:
        add("err", "vf_mp4_box", str(e))
        return out
    mdats = [(b[2], b[3]) for b in top if b[0] == b"mdat"]
    if not mdats:
        add("err", "vf_mp4_nomdat")
        return out
    if any(n.typ in (b"mvex", b"cmov") for n in tree):
        add("warn", "vf_mp4_frag")
        return out
    starts = [m[0] for m in mdats]
    traks = [n for n in tree if n.typ == b"trak"]
    if not traks:
        add("err", "vf_mp4_nomoov")
        return out
    vdur = adur = None
    for ti, node in enumerate(traks, 1):
        if cancel is not None and cancel.is_set():
            add("warn", "vf_cancel")
            return out
        try:
            t = _make_track(node)
        except (Mp4Error, struct.error, IndexError) as e:
            add("err", "vf_mp4_tbl", ti, str(e))
            continue
        n = len(t.sizes)
        if len(t.deltas) != n:
            add("err", "vf_mp4_tbl", ti, "stts/stsz")
        if t.cto is not None and len(t.cto) != n:
            add("err", "vf_mp4_tbl", ti, "ctts/stsz")
        if len(t.offs) != n:
            add("err", "vf_mp4_tbl", ti, "stsc/stco")
        if t.sync is not None:
            if not t.sync or t.sync != sorted(t.sync) or t.sync[-1] > n or t.sync[0] < 1:
                add("err", "vf_mp4_tbl", ti, "stss")
        bad = 0
        for off, sz in zip(t.offs, t.sizes):
            k = bisect.bisect_right(starts, off) - 1
            if k < 0 or off + sz > mdats[k][1]:
                bad += 1
        if bad:
            add("err", "vf_mp4_range", ti, bad)
        tsum = sum(t.deltas)
        if abs(tsum - t.mdur) > max(1, t.ts // 50):
            add("warn", "vf_mp4_dur", ti, tsum / float(t.ts), t.mdur / float(t.ts))
        if t.handler == b"vide":
            if t.sync is not None and t.sync and t.sync[0] != 1:
                add("err", "vf_mp4_nosync")
            if vdur is None:
                vdur = tsum / float(t.ts)
                add("info", "vf_dur", vdur, n)
        elif t.handler == b"soun" and adur is None:
            adur = tsum / float(t.ts)
    if vdur is not None and adur is not None and abs(vdur - adur) > 0.5:
        add("warn", "vf_mp4_avdiff", vdur, adur)
    if vdur is not None and expected is not None and abs(vdur - expected) > max(1.5, 0.1 * expected):
        add("warn", "vf_durdiff", vdur, expected)
    return out
