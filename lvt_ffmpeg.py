#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 szabiz <szabiz@yahoo.com>
# Copyright (c) 2026 szabiz <szabiz@yahoo.com>
"""
Lossless Video Toolkit - OPCIONÁLIS FFmpeg modul (lvt_ffmpeg.py)
================================================================
Szerkesztő (kép + hang, hanghullám, kocka-pontos léptetés), vizsgálat (ffprobe) és
átalakítás / pontos vágás grafikus felületen, a FELHASZNÁLÓ SAJÁT FFmpeg-jével.

Licenc és működés:
  * Saját fejlesztésű, eredeti kód MIT licenc alatt; csak a Python szabványos könyvtárát használja.
  * Az FFmpeg-et NEM tartalmazza, nem csomagolja és nem tölti le. A felhasználó adja meg, hol van az
    ffmpeg / ffprobe / ffplay (a saját gépén telepítve). Amíg ezt nem teszi és nem kapcsolja be,
    a modul teljesen inaktív, külső programot nem indít.
  * Az FFmpeg külön programként fut (parancssori hívás), a saját licence (LGPL vagy GPL, a buildtől
    függően) rá vonatkozik, nem erre a kódra. A modul kiírja a megadott build licenctípusát.
  * Ha az FFmpeg-et te terjeszted (pl. a telepítőben), annak licencfeltételeit külön teljesíteni kell.
  * Megnyitáskor licenc-figyelmeztetés jelenik meg; az OK gomb csak a szöveg végére görgetés után aktív.
    Az elfogadást a program mappájában lévő jelzőfájl (lvt_ffmpeg_licenc.txt) tartja
    meg – Pythonnál a .py, exe-nél az exe mappájába –, ezért az ablak csak az ELSŐ
    megnyitáskor jön elő, és újratelepítés (a mappa törlése) után újra kérdez. A
    Beállítás fülön a jelző törölhető, azaz a szöveg bármikor újra megnézhető.

Használat: az mts_joiner.py "FFmpeg" füle nyitja (külön ablakban), vagy önállóan:  python lvt_ffmpeg.py [fájl]

Változások az 1.8-as verzióban:
  * A Smart cut választása az export indításakor felugró, két leírt lehetőséget tartalmazó ablakba került; az Editor korábbi elrendezése visszaállt.

Változások az 1.7-es verzióban:
  * Kísérleti Smart cut az Editor exportjaihoz: H.264 MPEG-TS/MTS/M2TS esetén az IDR-ek közti közép stream copy, a szélek libx264 újrakódolás; a hangsáv egyben kódolódik újra. Nem garantált az eredeti SPS/PPS teljes egyezése.

Változások az 1.6-os verzióban:
  * "→ Kijelöltek az Átalakításra": ha nincs szakasz és nincs A–B jelölés, az EGÉSZ fájl kerül az Átalakítás listára.
  * Átalakítás / pontos vágás: a forrásfájl kiválasztásakor a Videó és Hang mezők azonnal kitöltődnek a fájl saját
    adataival (kodek, bitráta, méret, fps, pix_fmt, csatorna, Hz, konténer) - ffprobe kell hozzá; kézzel módosíthatók.
  * ÖSSZEFŰZÉS JAVÍTÁS (Átalakítás fül, Szerkesztő export): újrakódolásnál a szakaszok vágása és egybefűzése
    EGY ffmpeg-menetben történik (trim/atrim + concat szűrő, egyetlen kódoló). Korábban minden szakasz külön
    fájlba készült, majd a concat demuxer másolással fűzte össze: a darabok kép- és hanghossza eltért
    (AAC-előfutás, kockahatár), ezért az illesztéseknél a hang előbb indult, mint a kép, vagy megakadt a kép.
    Most a szakaszok azonos kocka/mp-re, méretre, képarányra, mintavételre kerülnek, a kép és a hang pontosan
    a szakasz hosszára van vágva, és az időbélyegek folytonosak. A vágás nem bemeneti keresésre épül (az
    MPEG-TS / M2TS fájloknál nem kocka-pontos), hanem a szűrőben történik. Másolásnál (copy) a régi módszer marad.

Változások az 1.5-ös verzióban:
  * KÉPEFFEKTEK: a Szerkesztőből a "→ Kijelöltek a Képeffektekre" gombbal külön ablak nyílik (efekt.py), élő
    előnézettel (átméretezés, körbevágás, forgatás, deinterlace, fény/árnyék/szín, élesség, zajszűrés,
    VapourSynth, egyéni -vf). Szakaszonként külön beállítás; a "Kimenet" gomb az Átalakítás fül listájára viszi
    a szakaszokat a szűrőlánccal együtt. Az efekt.py nélkül a modul a régi módon működik.

Változások az 1.4-es verzióban:
  * Konténer választó az Átalakítás fülön: az FFmpeg saját "-formats" listájából (amit a build ki tud írni).
  * Saját beállítás-minták mentése / törlése (★ jelöléssel, a ~/.lvt_ffmpeg.json fájlba).
  * Az "Előnézet / vágási pont" fül kikerült (a Szerkesztő kiváltja).
  * Licenc-figyelmeztető ablak (görgetés + OK) a megnyitás előtt.

Változások a 1.3-as verzióban:
  * A hang ffplay-be írása valós idejű ütemezésű (csendes előfutással), a kép a hang TÉNYLEGES indulási
    pillanatához van kötve; "Szinkron-teszt" gomb (villanás+sípolás) a gép saját hangkésésének beállításához;
    a "Hang–kép igazítás" mező értéke megmarad; az fps szűrő start_time=0, hogy a késve induló képfolyam
    eltérése is látszódjon.
  * Élő lejátszás - hang/kép szinkron JAVÍTÁS (MKV, M2TS): a hangot az ffmpeg dekódolja ugyanazzal a pontos
    kereséssel (-ss), mint a képet, és az ffplay-nek csak a kész hangot adjuk át (stdin). Az ffplay indulási
    késését az AUDIO_LAT állandó kompenzálja, finomhangolás: "Hang–kép igazítás (ms)" mező.

Változások a 1.2-es verzióban:
  * Élő lejátszás: a közös indítási pillanatot a TÉNYLEGESEN megérkezett első képkockánál rögzítjük.
  * Szerkesztő elrendezés: induláskor az időszalag a minimális magasságán jelenik meg.
"""
import base64
import bisect
import hashlib
import json
import os
import queue
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import lvt_smartcut
import lvt_iframe

MODULE_VERSION = "1.9"
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".lvt_ffmpeg.json")
LANG = "en"          # default UI language (English); "hu" = Magyar


def _(hu, en):
    return hu if LANG == "hu" else en


class FFError(Exception):
    pass


class _IkCancel(Exception):
    """Az I-kocka elemzés megszakítása (belső jelzés)."""


class CancelFlag(threading.Event):
    """Megszakítás-jelző. keep: a megszakításkor az addig kódolt rész megmarad (az ffmpeg szabályosan lezárja a fájlt);
    can_keep: a futó parancs támogatja-e ezt; has_final: a végén még összefűzés / utómunka következik (ilyenkor nincs részmentés)."""

    def __init__(self):
        threading.Event.__init__(self)
        self.keep = self.can_keep = self.has_final = False

    def clear(self):
        threading.Event.clear(self)
        self.keep = self.can_keep = self.has_final = False



def load_analyzer():
    """Az opcionális lvt_analyzer.py (Videó-elemző) betöltése ugyanabból a mappából, mint az efekt.py.
    Visszatér: (modul, hibaszöveg). Modul nélkül a fül csak egy figyelmeztetést mutat."""
    import os as _os
    import sys as _sys
    here = _os.path.dirname(_os.path.abspath(__file__))
    if here not in _sys.path:
        _sys.path.insert(0, here)
    try:
        import lvt_analyzer
    except Exception as e:      # noqa
        return None, "%s: %s" % (type(e).__name__, e)
    return lvt_analyzer, ""


HELP_CONVERT_HU = (
    "Átalakítás – súgó (rövid magyarázat)",
    "",
    "HOGYAN HASZNÁLD (lépésenként)",
    "1. A Szerkesztőben jelöld ki a részeket, majd: → Kijelöltek az Átalakításra.",
    "2. Preset: válassz mintát. A „Fast copy” gyors, nem kódol újra.",
    "3. Output file: írd be a célfájl nevét, vagy a … gombbal válaszd ki.",
    "4. Parancs megtekintése (Show command): ellenőrizd a parancsot.",
    "5. Start: indul az átalakítás. Cancel: megszakítja.",
    "",
    "SZAKASZOK LISTA",
    "▲ Fel / ▼ Le: a sorrend. Ebben a sorrendben készül el a kimenet.",
    "Törlés (Delete): a kijelölt sorokat veszi ki a listából. Több sort is egyszerre.",
    "Ctrl+A: minden sor kijelölése. A fájlok a lemezen maradnak.",
    "With several items: joined into one file = egy fájlba, egy menetben vágva és fűzve.",
    "separate files = külön fájlok (név_001, név_002 …).",
    "",
    "VÁGÁS",
    "Start / End: másodperc (pl. 83.5) vagy ó:pp:mp (pl. 0:01:23.5).",
    "frame-accurate: pontos, kockára pontos vágás. Lassabb. Akkor kell, ha a pontosság számít.",
    "",
    "KONTÉNER ÉS KITERJESZTÉS",
    "Container: a fájl „doboza” (mp4, mkv, ts, m2ts, mp3 …). Ez dönti el, mi fér bele.",
    "Csak hangos konténernél (pl. mp3) a Video rész nem aktív.",
    "Extension: a fájl vége (pl. .mp4). Általában a konténerhez illő legyen.",
    "",
    "RÖVIDÍTÉSEK – MIT ÍRJ BE",
    "codec (videó): copy = nem kódol újra, gyors, a minőség nem változik.",
    "   Más kodek (pl. libx264, libx265) újrakódol: lassabb, a minőség a beállításoktól függ.",
    "preset: gyorsaság. Lassabb = kisebb fájl azonos minőségnél. Pl.: medium, slow.",
    "CRF / CQ: minőség. Kisebb szám = jobb minőség, nagyobb fájl. Szokásos: 18–23. Pl.: 20.",
    "bitrate: adatsebesség. Pl.: 8M (8 Mbit/s) vagy 5000k. Ha van bitrate, a CRF/CQ nem számít.",
    "scale: szélesség:magasság. Pl.: 1280:720. Arányos magasság: 1280:-2. Üresen: az eredeti méret.",
    "fps: képkocka másodpercenként. Pl.: 25, vagy 25000/1001 (kb. 29,97). Üresen: az eredeti.",
    "pix_fmt: színformátum. yuv420p = a legkompatibilisebb. Üresen: az eredeti.",
    "hwaccel: videokártyás dekódolás, gyorsabb. „-” = ki. Csak ha a gép és az FFmpeg támogatja.",
    "GOP (frames): kulcskockák távolsága kockában. Pl.: 25 = másodpercenként egy kulcskocka 25 fps-nél.",
    "   Üresen M2TS / TS kimenetnél: fps/2 (kb. 0,5 mp), ez a gyors tekeréshez jó.",
    "-vf: saját videószűrő FFmpeg-szintaxissal. Pl.: hflip (tükrözés).",
    "   Több szűrő vesszővel: hflip,transpose=1",
    "Deinterlace (yadif): összefésült (interlaced) forrásnál pipáld be, pl. régi TV-felvételnél.",
    "",
    "HANG",
    "codec (hang): copy = változatlan. Más: aac (MP4-hez), ac3, libopus, libmp3lame (MP3).",
    "bitrate (hang): minőség. Pl.: 192k (jó), 128k (kisebb fájl).",
    "channels: csatornák. 2 = sztereó, 6 = 5.1.",
    "Hz: mintavételezés. 48000 a szokásos.",
    "dB: hangerő-változtatás. Pl.: 3 = hangosabb, -3 = halkabb. Üresen: nincs változtatás.",
    "-af: saját hangszűrő FFmpeg-szintaxissal. Pl.: highpass=f=200 (mély zúgás kiszűrése).",
    "",
    "KIMENET ÉS KAPCSOLÓK",
    "Extra args: nyers FFmpeg-kapcsolók. Csak haladóknak. Hibás kapcsoló miatt az átalakítás megáll.",
    "faststart (MP4): webes lejátszáshoz jobb. Ajánlott bekapcsolva.",
    "avoid negative ts (copy): másolásnál a kezdő időbélyeg-hibákat javítja. Hagyd bekapcsolva.",
    "overwrite: a meglévő kimeneti fájlt felülírja. Ha az előző fájl kell, adj új nevet.",
    "",
    "GOMBOK",
    "Save as preset: a beállításaidat mintaként elmenti. A ★ jelű a saját mintád.",
    "Delete preset: a kiválasztott saját mintát törli.",
    "H: ez a súgó.",
)

HELP_CONVERT_EN = (
    "Convert / exact cut – help (short guide)",
    "",
    "HOW TO USE (step by step)",
    "1. In the Editor, select the parts, then: → Send selected to Convert.",
    "2. Preset: choose a profile. \"Fast copy\" is quick and does not re-encode.",
    "3. Output file: type the target file name, or pick it with the … button.",
    "4. Show command: check the exact command before you run it.",
    "5. Start: runs the conversion. Cancel: stops it.",
    "",
    "SEGMENT LIST",
    "▲ Up / ▼ Down: the order. The output is made in this order.",
    "Remove (Delete key): removes the selected rows from the list. Several rows at once.",
    "Ctrl+A: selects all rows. The files stay on disk.",
    "With several items: joined into one file = one file, cut and joined in one pass.",
    "separate files = separate files (name_001, name_002 …).",
    "",
    "CUT",
    "Start / End: seconds (e.g. 83.5) or h:mm:ss (e.g. 0:01:23.5).",
    "frame-accurate: exact, frame-by-frame cut. Slower. Use it when precision matters.",
    "",
    "CONTAINER AND EXTENSION",
    "Container: the file \"box\" (mp4, mkv, ts, m2ts, mp3 …). It decides what fits inside.",
    "For audio-only containers (e.g. mp3) the Video part is inactive.",
    "Extension: the file ending (e.g. .mp4). Should normally match the container.",
    "",
    "ABBREVIATIONS – WHAT TO TYPE",
    "codec (video): copy = no re-encoding, fast, quality unchanged.",
    "   Another codec (e.g. libx264, libx265) re-encodes: slower, quality depends on the settings.",
    "preset: speed. Slower = smaller file at the same quality. E.g.: medium, slow.",
    "CRF / CQ: quality. Lower number = better quality, bigger file. Typical: 18–23. E.g.: 20.",
    "bitrate: data rate. E.g.: 8M (8 Mbit/s) or 5000k. If a bitrate is set, CRF/CQ is ignored.",
    "scale: width:height. E.g.: 1280:720. Keep aspect ratio: 1280:-2. Empty: original size.",
    "fps: frames per second. E.g.: 25, or 25000/1001 (about 29.97). Empty: original.",
    "pix_fmt: colour format. yuv420p = most compatible. Empty: original.",
    "hwaccel: decoding on the graphics card, faster. \"-\" = off. Only if your PC and FFmpeg support it.",
    "GOP (frames): distance between keyframes in frames. E.g.: 25 = one keyframe per second at 25 fps.",
    "   Empty for M2TS / TS output: fps/2 (about 0.5 s), good for fast seeking.",
    "-vf: your own video filter, FFmpeg syntax. E.g.: hflip (mirror).",
    "   Several filters separated by commas: hflip,transpose=1",
    "Deinterlace (yadif): tick it for interlaced sources, e.g. old TV recordings.",
    "",
    "AUDIO",
    "codec (audio): copy = unchanged. Others: aac (good for MP4), ac3, libopus, libmp3lame (MP3).",
    "bitrate (audio): quality. E.g.: 192k (good), 128k (smaller file).",
    "channels: number of channels. 2 = stereo, 6 = 5.1.",
    "Hz: sample rate. 48000 is the usual value.",
    "dB: volume change. E.g.: 3 = louder, -3 = quieter. Empty: no change.",
    "-af: your own audio filter, FFmpeg syntax. E.g.: highpass=f=200 (removes low rumble).",
    "",
    "OUTPUT AND SWITCHES",
    "Extra args: raw FFmpeg switches. For advanced users only. A wrong switch stops the conversion.",
    "faststart (MP4): better for web playback. Recommended: on.",
    "avoid negative ts (copy): fixes start-timestamp errors when copying. Keep it on.",
    "overwrite: replaces an existing output file. To keep the previous file, use a new name.",
    "",
    "BUTTONS",
    "Save as preset: saves your settings as a preset. Items marked ★ are your own presets.",
    "Delete preset: deletes the selected own preset.",
    "H: this help.",
)


def load_efekt():
    """Az opcionális efekt.py betöltése (ugyanabból a mappából). None + hibaüzenet, ha nincs meg / hibás."""
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        import efekt
    except ImportError as e:
        return None, str(e)
    except Exception as e:      # noqa  (szintaktikai / futási hiba az efekt.py-ban)
        return None, "%s: %s" % (type(e).__name__, e)
    if not hasattr(efekt, "open_window"):
        # a betöltött „efekt” modulból hiányzik az open_window: nem a teljes efekt.py töltődött be (más / csonka / felülírt fájl)
        path = getattr(efekt, "__file__", "?")
        try:
            size = os.path.getsize(path)
        except (OSError, TypeError):
            size = -1
        sys.modules.pop("efekt", None)
        return None, _("A betöltött efekt modulban nincs open_window: %s (%d bájt).\nEz nem a teljes efekt.py: ellenőrizd, hogy "
                       "az efekt.py-t nem írta-e felül egy másik fájl (pl. az efekt_vs.py), és nézd meg az efekt_vs_hiba.txt-t.",
                       "The loaded efekt module has no open_window: %s (%d bytes).\nThis is not the complete efekt.py: check that "
                       "efekt.py was not overwritten by another file (e.g. efekt_vs.py), and look at efekt_vs_hiba.txt.") % (path, size)
    try:
        efekt.LANG = LANG
    except Exception:       # noqa
        pass
    return efekt, ""


# ----------------------------------------------------------------- beállítások ---

# ---- "megmarkoló kéz" egérkurzor (az időszalag jobb gombos húzásához) ----
_GRAB = {"spec": None}


def _fist_pixels(N=32):
    """32x32-es zárt kéz: 0 = átlátszó, 1 = fekete, 2 = fehér."""
    sh = [[0] * N for _ in range(N)]

    def disc(cx, cy, r):
        for y in range(N):
            for x in range(N):
                if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                    sh[y][x] = 1

    def rect(x1, y1, x2, y2):
        for y in range(y1, y2 + 1):
            for x in range(x1, x2 + 1):
                sh[y][x] = 1
    for cx in (9, 13, 17, 21):          # négy ujj (bütyök)
        disc(cx, 10, 3.2)
    rect(6, 10, 24, 21)                 # tenyér
    disc(9, 21, 3.2)
    disc(21, 21, 3.2)
    rect(9, 21, 21, 24)
    disc(26, 17, 3.2)                   # hüvelykujj oldalt
    rect(24, 15, 27, 19)
    out = [[2 if sh[y][x] else 0 for x in range(N)] for y in range(N)]
    for y in range(N):                  # fekete körvonal
        for x in range(N):
            if not sh[y][x] and any(0 <= y + dy < N and 0 <= x + dx < N and sh[y + dy][x + dx]
                                    for dy in (-1, 0, 1) for dx in (-1, 0, 1)):
                out[y][x] = 1
    for x in (11, 15, 19):              # ujjak közti vonalak
        for y in range(9, 15):
            if out[y][x] == 2:
                out[y][x] = 1
    for x in range(8, 23):              # behajlított ujjak alsó vonala
        if out[15][x] == 2:
            out[15][x] = 1
    return out


def _cur_bytes(px, N=32):
    """Windows .cur fájl (1 bites, 32x32, középpont a fogási pont)."""
    xor, andm = bytearray(), bytearray()
    for y in range(N - 1, -1, -1):      # a BMP alulról felfelé tárol
        xr = an = 0
        for x in range(N):
            xr = (xr << 1) | (1 if px[y][x] == 2 else 0)
            an = (an << 1) | (1 if px[y][x] == 0 else 0)
        xor += xr.to_bytes(4, "big")
        andm += an.to_bytes(4, "big")
    img = (struct.pack("<IiiHHIIiiII", 40, N, N * 2, 1, 1, 0, 0, 0, 0, 2, 2) + bytes([0, 0, 0, 0, 255, 255, 255, 0])
           + bytes(xor) + bytes(andm))
    return struct.pack("<HHH", 0, 2, 1) + struct.pack("<BBBBHHII", N, N, 0, 0, N // 2, N // 2, len(img), 22) + img


def _write_xbm(path, px, pred, name, N=32):
    rows = []
    for y in range(N):
        bs = []
        for bx in range(0, N, 8):
            b = 0
            for i in range(8):
                if pred(px[y][bx + i]):
                    b |= 1 << i
            bs.append("0x%02x" % b)
        rows.append(", ".join(bs))
    with open(path, "w") as fh:
        fh.write("#define %s_width %d\n#define %s_height %d\n#define %s_x_hot %d\n#define %s_y_hot %d\n"
                 "static unsigned char %s_bits[] = {\n  %s };\n" % (name, N, name, N, name, N // 2, name, N // 2, name,
                                                                    ",\n  ".join(rows)))


def _short_path(p):
    if " " not in p:
        return p
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(520)
        return buf.value if ctypes.windll.kernel32.GetShortPathNameW(p, buf, 520) else p
    except Exception:       # noqa
        return p


def grab_cursor_spec():
    """A "megmarkoló kéz" kurzor Tk-leírása: macOS-en natív 'closedhand', Windowson .cur, X11-en .xbm (a Temp mappában
    készül el). Bármilyen hiba esetén 'fleur' (négyirányú nyíl)."""
    if _GRAB["spec"]:
        return _GRAB["spec"]
    spec = "fleur"
    try:
        if sys.platform == "darwin":
            spec = "closedhand"
        else:
            px = _fist_pixels()
            d = os.path.join(tempfile.gettempdir(), "lvt_cursor")
            os.makedirs(d, exist_ok=True)
            if sys.platform.startswith("win"):
                fp = os.path.join(d, "grab_v1.cur")
                if not os.path.isfile(fp):
                    with open(fp, "wb") as fh:
                        fh.write(_cur_bytes(px))
                spec = "@" + _short_path(fp).replace("\\", "/")
            elif " " not in d:
                src, msk = os.path.join(d, "grab_v1.xbm"), os.path.join(d, "grab_v1_mask.xbm")
                if not (os.path.isfile(src) and os.path.isfile(msk)):
                    _write_xbm(src, px, lambda v: v == 1, "grab")
                    _write_xbm(msk, px, lambda v: v != 0, "grabm")
                spec = "@%s %s black white" % (src, msk)
    except Exception:       # noqa
        spec = "fleur"
    _GRAB["spec"] = spec
    return spec


def load_config():
    cfg = {"enabled": False, "license_ok": False, "ffmpeg": "", "ffprobe": "", "ffplay": "", "av_off": "0",
           "presets": {}, "fx_presets": {}}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update({k: v for k, v in json.load(f).items() if k in cfg})
    except (OSError, ValueError):
        pass
    if not isinstance(cfg.get("presets"), dict):
        cfg["presets"] = {}
    if not isinstance(cfg.get("fx_presets"), dict):
        cfg["fx_presets"] = {}
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)
        return True
    except OSError:
        return False


def missing_paths(cfg):
    """A három program (ffmpeg, ffprobe, ffplay) közül azok a nevei, amelyek útvonala
    hiányzik vagy nem létező fájra mutat."""
    return [n for n in ("ffmpeg", "ffprobe", "ffplay") if not (cfg.get(n) and os.path.isfile(cfg[n]))]


def setup_incomplete(cfg):
    """Igaz, ha a modul ki van kapcsolva, vagy valamelyik program útvonala hiányzik:
    ilyenkor ugrik be megnyitáskor a Beállítás (Setup) fül."""
    return not cfg.get("enabled") or bool(missing_paths(cfg))


LICENCE_MARK_FILE = "lvt_ffmpeg_licenc.txt"
_LIC_MARK_TXT_HU = ("Lossless Video Toolkit – FFmpeg modul: a licenc-figyelmeztetés megjelent,\n"
                    "és a felhasználó elfogadta. Ha ezt a fájlt törlöd, a figyelmeztetés a\n"
                    "következő megnyitáskor újra előjön. Ez a fájl csak a felület\n"
                    "emlékeztető jelzője, jogi nyilatkozatot nem tartalmaz.\n")
_LIC_MARK_TXT_EN = ("Lossless Video Toolkit – FFmpeg module: the licence notice was shown\n"
                    "and the user accepted it. If you delete this file, the notice appears\n"
                    "again the next time the module is opened. This file is only a UI\n"
                    "reminder marker and contains no legal statement.\n")




def app_dir():
    """A program saját mappája: fagyasztott (exe) változatnál az exe mappája,
    egyébként a .py fájljáé. Ide kerül a licenc-figyelmeztetés jelzőfájlja."""
    import sys
    if getattr(sys, "frozen", False) and getattr(sys, "executable", ""):
        return os.path.dirname(os.path.abspath(sys.executable))
    here = globals().get("__file__") or (sys.argv[0] if getattr(sys, "argv", "") else "")
    return os.path.dirname(os.path.abspath(here)) if here else os.getcwd()


def licence_mark_path():
    """A jelzőfájl útvonala: a program mappája, ha oda tudunk írni; ha nem (pl.
    Program Files), akkor a beállítás-fájl mappája – így sem törik el a művelet."""
    d = app_dir()
    if not os.path.isdir(d) or not os.access(d, os.W_OK):
        d = os.path.dirname(os.path.abspath(CONFIG_PATH))
    return os.path.join(d, LICENCE_MARK_FILE)


def notice_needed():
    """Igaz, ha a licenc-figyelmeztetést ebben a telepítésben még nem fogadták el: a
    jelző a program mappájában van, ezért az mappa törlése (újratelepítés) után újra
    előjön; a ~/.lvt_ffmpeg.json régi „license_ok” kulcsa NEM elég."""
    return not os.path.isfile(licence_mark_path())


def accept_license():
    """A figyelmeztetés elfogadása: jelzőfájl a program mappájába, emellett a
    beállítás-fájl jelzője is bekapcsol, hogy a régebbi kód is lássa."""
    try:
        with open(licence_mark_path(), "w", encoding="utf-8") as f:
            f.write(_(_LIC_MARK_TXT_HU, _LIC_MARK_TXT_EN))
    except OSError:
        pass
    mark_license_ok()


def clear_license_ok():
    """A beállítás-fájl „license_ok” jelzőjének törlése: a kapu biztosan előjöjjön."""
    cfg = load_config()
    if cfg.get("license_ok"):
        cfg["license_ok"] = False
        save_config(cfg)


def revoke_license():
    """A jelzőfájl törlése: a következő megnyitáskor újra megjelenik a figyelmeztetés."""
    try:
        os.remove(licence_mark_path())
    except OSError:
        pass
    clear_license_ok()


def mark_license_ok():
    """A licenc-figyelmeztetés elfogadását a beállítás-fájl jelzője tartja meg, így az
    ablak csak az első megnyitáskor jelenik meg."""
    cfg = load_config()
    if not cfg.get("license_ok"):
        cfg["license_ok"] = True
        save_config(cfg)


def is_enabled():
    c = load_config()
    return bool(c["enabled"] and c["ffmpeg"] and os.path.isfile(c["ffmpeg"]))


def parse_time(s):
    """'12.5', '1:02.5', '0:01:02,5' -> másodperc (float); hibánál None."""
    s = (s or "").strip().replace(",", ".")
    if not s:
        return None
    try:
        parts = [float(x) for x in s.split(":")]
    except ValueError:
        return None
    if len(parts) > 3:
        return None
    v = 0.0
    for p in parts:
        v = v * 60 + p
    return v


def fmt_time(t):
    t = max(0.0, float(t))
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return "%d:%02d:%06.3f" % (h, m, s)


# ----------------------------------------------------------------- FFmpeg hívások ---

_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Az ffplay-be írt hang és a hallható hang közti átlagos késés (mp). Gépfüggő: a "Szinkron-teszt" gombbal és a
# "Hang–kép igazítás (ms)" mezővel pontosan beállítható (a mező értéke megmarad a következő indításkor is).
AUDIO_LAT = 0.10


class _AudioPump:
    """Hang lejátszása a képpel azonos, PONTOS kereséssel: ffmpeg (-ss) -> nyers PCM -> ffplay (stdin).
    Az ffplay a kezdetektől csendet kap VALÓS IDEJŰ ütemben (így a hangeszköz már nyitva van, és nincs
    felgyülemlő várakozó adat), a tényleges hang a go jelre, egy pontosan rögzített pillanatban (t_real0) kezdődik."""
    RATE, STEP, DT = 48000, 3840, 0.02          # 20 ms = 3840 bájt (sztereó, 16 bit)
    PRE = 96000                                 # ~0,5 mp előtöltés

    def __init__(self, ff, src, t0, dur, vol):
        self.ready, self.go, self.stop = threading.Event(), threading.Event(), threading.Event()
        self.go_at, self.t_real0, self.eof = 0.0, None, False
        self.pcm, self.lock = bytearray(), threading.Lock()
        ca = [ff.ffmpeg, "-v", "error", "-nostdin", "-ss", "%.3f" % max(0.0, t0), "-i", src, "-vn", "-sn",
              "-af", "aresample=async=1:first_pts=0", "-ac", "2", "-ar", str(self.RATE), "-c:a", "pcm_s16le"]
        if dur and dur > 0:
            ca += ["-t", "%.3f" % dur]
        ca += ["-f", "s16le", "-"]
        cp = [ff.ffplay, "-hide_banner", "-loglevel", "error", "-nodisp", "-autoexit",
              "-fflags", "nobuffer", "-probesize", "32768", "-analyzeduration", "100000",
              "-volume", str(int(vol)), "-i", "pipe:0"]
        self.ea = self.pl = None
        self.ea = subprocess.Popen(ca, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   bufsize=65536, creationflags=_NOWIN)
        try:
            self.pl = subprocess.Popen(cp, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, creationflags=_NOWIN)
        except OSError:
            self.close()
            raise
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._writer, daemon=True).start()

    @classmethod
    def _header(cls):
        import struct
        return (b"RIFF" + struct.pack("<I", 0x7FFFFFDB) + b"WAVEfmt " +
                struct.pack("<IHHIIHH", 16, 1, 2, cls.RATE, cls.RATE * 4, 4, 16) +
                b"data" + struct.pack("<I", 0x7FFFFFB7))

    def _reader(self):
        try:
            while not self.stop.is_set():
                c = self.ea.stdout.read(16384)
                if not c:
                    break
                with self.lock:
                    self.pcm += c
                    n = len(self.pcm)
                if n >= self.PRE:
                    self.ready.set()
                while n > 8 * self.PRE and not self.stop.is_set():
                    time.sleep(0.02)
                    with self.lock:
                        n = len(self.pcm)
        except (OSError, ValueError):
            pass
        finally:
            self.eof = True
            self.ready.set()

    def _writer(self):
        sil = bytes(self.STEP)
        real = False
        try:
            self.pl.stdin.write(self._header())
            self.pl.stdin.flush()
            nxt = time.perf_counter()
            while not self.stop.is_set():
                now = time.perf_counter()
                if now < nxt:
                    time.sleep(min(nxt - now, 0.004))
                    continue
                if not real and self.go.is_set() and now >= self.go_at:
                    real = True
                    self.t_real0 = now
                if real:
                    with self.lock:
                        chunk = bytes(self.pcm[:self.STEP])
                        del self.pcm[:self.STEP]
                    if not chunk and self.eof:
                        break
                    if len(chunk) < self.STEP:
                        chunk += bytes(self.STEP - len(chunk))
                else:
                    chunk = sil
                self.pl.stdin.write(chunk)
                self.pl.stdin.flush()
                nxt += self.DT
                t = time.perf_counter()
                if t - nxt > self.DT:           # a cső megtelt / az ffplay még nyit: nem hozzuk be, nem halmozunk
                    nxt = t
            try:
                self.pl.stdin.close()
            except (OSError, ValueError):
                pass
        except (OSError, ValueError):
            pass
        finally:
            if self.t_real0 is None:
                self.t_real0 = time.perf_counter()

    def close(self):
        self.stop.set()
        for pr in (self.ea, self.pl):
            if pr is not None and pr.poll() is None:
                try:
                    pr.kill()
                except OSError:
                    pass
            if pr is not None:
                threading.Thread(target=pr.wait, daemon=True).start()


# ---- vspipe -> ffmpeg KÖZVETLEN csővezeték (Képeffektek / VapourSynth; nincs köztes fájl, egyetlen kódolás) ----
class PipeCmd(list):
    """Az ffmpeg-parancs (list), amelynek KÉPFOLYAMÁT a vspipe adja a stdin-re (y4m).
    sources: [{"vcmd": [vspipe ...] | None, "stage": [ffmpeg ...] | None}, ...]
      * egy forrás, szakasz (stage) nélkül: a vspipe kimenete közvetlenül az ffmpeg stdin-jére megy;
      * több forrás (összefűzés): minden forrás normalizált y4m-et ad (vspipe -> stage ffmpeg), és a betöltő szál
        ezeket EGYETLEN y4m-folyammá fűzi (az első fejléce marad) -> a végén egyetlen kódolás van."""

    def __init__(self, cmd, sources=()):
        list.__init__(self, cmd)
        self.sources = list(sources)


def cmdline(cmd):
    """Megjelenítésre szánt parancssor (a PipeCmd-nél a vspipe-részekkel együtt)."""
    if isinstance(cmd, PipeCmd) and cmd.sources:
        parts = []
        for s_ in cmd.sources:
            seg = [subprocess.list2cmdline(x) for x in (s_.get("vcmd"), s_.get("stage")) if x]
            parts.append(" | ".join(seg))
        return "  ||  ".join(parts) + "  |  " + subprocess.list2cmdline(list(cmd))
    return subprocess.list2cmdline(cmd)


class _PipeRun:
    """A PipeCmd futtatása: ffmpeg-folyamat + a hozzá tartozó vspipe / szakasz-folyamatok + betöltő szál."""

    def __init__(self, cmd):
        self.cmd = cmd
        self.procs = []
        self.errs = []              # vspipe / szakasz-ffmpeg hibasorai (a végére elég)
        self.feed_err = None
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.thread = None
        self.p = None

    def _spawn(self, cmd, **kw):
        pr = subprocess.Popen(cmd, creationflags=_NOWIN, **kw)
        with self.lock:
            self.procs.append(pr)
        return pr

    def _drain(self, pr, who):
        def run():
            try:
                for raw in pr.stderr:
                    ln = raw.decode("utf-8", "replace").strip()
                    if ln:
                        self.errs.append("%s: %s" % (who, ln))
                        del self.errs[:-40]
            except (OSError, ValueError):
                pass
        threading.Thread(target=run, daemon=True).start()

    def start(self):
        cmd, src = self.cmd, self.cmd.sources
        if len(src) == 1 and src[0].get("vcmd") and not src[0].get("stage"):
            vp = self._spawn(src[0]["vcmd"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
            self._drain(vp, "vspipe")
            self.p = self._spawn(list(cmd), stdin=vp.stdout, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            vp.stdout.close()
            self.vps = [vp]
        else:
            self.vps = []
            self.p = self._spawn(list(cmd), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.thread = threading.Thread(target=self._feed, daemon=True)
            self.thread.start()
        return self.p

    def _feed(self):
        """Az összes forrás y4m-folyamát egyetlen folyammá fűzi az ffmpeg stdin-jére."""
        w = self.p.stdin
        first = True
        try:
            for n, s_ in enumerate(self.cmd.sources):
                if self.stop.is_set():
                    break
                prev, chain = None, []
                if s_.get("vcmd"):
                    vp = self._spawn(s_["vcmd"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
                    self._drain(vp, "vspipe")
                    chain.append(vp)
                    prev = vp.stdout
                if s_.get("stage"):
                    sp = self._spawn(s_["stage"], stdin=prev if prev else subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE)
                    if prev:
                        prev.close()
                    self._drain(sp, "ffmpeg")
                    chain.append(sp)
                    prev = sp.stdout
                if prev is None:
                    continue
                head = prev.readline()                      # y4m fejléc: csak az első szakaszé kerül tovább
                size = 0
                if head:
                    if first:
                        w.write(head)
                        first = False
                    while not self.stop.is_set():
                        buf = prev.read(1 << 20)
                        if not buf:
                            break
                        size += len(buf)
                        w.write(buf)
                for pr in chain:
                    try:
                        pr.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        pr.kill()
                if self.stop.is_set():
                    break
                bad = [pr for pr in chain if pr.returncode not in (0, None)]
                # a klip végén a VapourSynth „beyond clip end” jelzése normális lezárás
                tail = " | ".join(self.errs[-3:])
                if size == 0 or (bad and "beyond clip end" not in tail):
                    self.feed_err = (_("A %d. szakasz képe nem készült el: ", "Segment %d produced no picture: ") % (n + 1)) + \
                        (tail or "?")
                    break
        except (OSError, ValueError):
            pass                                            # az ffmpeg bezárt / leállítottuk
        finally:
            try:
                w.close()
            except (OSError, ValueError):
                pass

    def kill(self):
        self.stop.set()
        with self.lock:
            ps = list(self.procs)
        for pr in ps:
            try:
                if pr.poll() is None:
                    pr.kill()
            except OSError:
                pass

    def finish(self, tail):
        """A futás után: a hibák összegyűjtése. -> hibaszöveg vagy None."""
        if self.thread is not None:
            self.thread.join(timeout=30)
        rc = self.p.returncode
        err = self.feed_err
        if not err and self.vps:
            vp = self.vps[0]
            try:
                vp.wait(timeout=20)
            except subprocess.TimeoutExpired:
                vp.kill()
            vt = " | ".join(self.errs[-3:])
            if vp.returncode not in (0, None) and rc == 0 and "beyond clip end" not in vt:
                err = _("A VapourSynth hibával leállt: ", "VapourSynth stopped with an error: ") + (vt or "rc=%s" % vp.returncode)
        if rc != 0 and not err:
            extra = [e for e in self.errs[-3:]]
            err = "\n".join(extra + list(tail[-3:])) if (tail or extra) else "exit %d" % rc   # a vspipe hibája elöl
        return err



def norm_bitrate(v):
    """'3000' -> '3000k' (az FFmpeg a szám egység nélkül bit/mp-nek venné); '5M', '192k', '128000' marad."""
    v = (v or "").strip().replace(",", ".")
    if re.fullmatch(r"\d+(\.\d+)?", v) and float(v) < 10000:
        return v + "k"
    return v


class FFmpeg:
    def __init__(self, ffmpeg, ffprobe="", ffplay=""):
        self.ffmpeg, self.ffprobe, self.ffplay = ffmpeg, ffprobe, ffplay
        self._enc = None
        self._mux = None

    # --- program keresése (csak kérésre) ---
    @staticmethod
    def locate(hint=""):
        out = {}
        dirs = []
        if hint:
            dirs.append(hint if os.path.isdir(hint) else os.path.dirname(hint))
        for name in ("ffmpeg", "ffprobe", "ffplay"):
            found = None
            for d in dirs:
                for ext in ("", ".exe"):
                    p = os.path.join(d, name + ext)
                    if os.path.isfile(p):
                        found = p
                        break
                if found:
                    break
            out[name] = found or shutil.which(name) or ""
        return out

    def _run(self, args, timeout=60, binary=False, stdin=None):
        try:
            r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=stdin,
                               timeout=timeout, creationflags=_NOWIN)
        except (OSError, subprocess.SubprocessError) as e:
            raise FFError(str(e))
        if r.returncode != 0:
            err = r.stderr.decode("utf-8", "replace").strip().splitlines()
            raise FFError(err[-1] if err else "exit %d" % r.returncode)
        return r.stdout if binary else r.stdout.decode("utf-8", "replace")

    def version_info(self):
        txt = self._run([self.ffmpeg, "-hide_banner", "-version"], 15)
        first = txt.splitlines()[0] if txt else ""
        cfg = ""
        for ln in txt.splitlines():
            if ln.startswith("configuration:"):
                cfg = ln
        if "--enable-nonfree" in cfg:
            lic = _("nonfree (NEM terjeszthető)", "nonfree (NOT redistributable)")
        elif "--enable-gpl" in cfg:
            lic = "GPL" + ("v3" if "--enable-version3" in cfg else "")
        elif "--enable-version3" in cfg:
            lic = "LGPL v3"
        else:
            lic = "LGPL v2.1+"
        return {"version": first, "license": lic, "configuration": cfg}

    def encoders(self):
        """{'V': [(név, leírás)], 'A': [...], 'S': [...]} az FFmpeg saját listájából."""
        if self._enc is not None:
            return self._enc
        res = {"V": [], "A": [], "S": []}
        txt = self._run([self.ffmpeg, "-hide_banner", "-encoders"], 30)
        for ln in txt.splitlines():
            m = re.match(r"^\s([VAS])[\.A-Z]{5}\s+(\S+)\s+(.*)$", ln)
            if m and m.group(2) != "=":
                res[m.group(1)].append((m.group(2), m.group(3).strip()))
        self._enc = res
        return res

    def muxers(self):
        """[(név, leírás)] mindazokról a konténerekről, amelyeket ez az FFmpeg-build ki tud írni."""
        if self._mux is not None:
            return self._mux
        res = []
        txt = self._run([self.ffmpeg, "-hide_banner", "-formats"], 30)
        for ln in txt.splitlines():
            m = re.match(r"^\s([D ])([E ])\s+(\S+)\s+(.*)$", ln)
            if m and m.group(2) == "E":
                for nm in m.group(3).split(","):
                    res.append((nm, m.group(4).strip()))
        self._mux = sorted(set(res))
        return self._mux

    def filters(self):
        """Az ffmpeg-build szűrőinek neve (halmaz) - az effekt-ablak ebből tudja, mi érhető el."""
        if getattr(self, "_flt", None) is not None:
            return self._flt
        names = set()
        txt = self._run([self.ffmpeg, "-hide_banner", "-filters"], 30)
        for ln in txt.splitlines():
            m = re.match(r"^\s[T\.][S\.][C\.]\s+(\S+)\s+\S+->\S+", ln)
            if m:
                names.add(m.group(1))
        self._flt = names
        return names

    def hwaccels(self):
        txt = self._run([self.ffmpeg, "-hide_banner", "-hwaccels"], 15)
        return [x.strip() for x in txt.splitlines()[1:] if x.strip()]

    def quick_info(self, path):
        """Gyors adatok a szerkesztőnek: hossz, kocka/mp, méret, képarány, összefésültség, van-e hang."""
        r = {"duration": 0.0, "fps": 25.0, "w": 0, "h": 0, "sar": 1.0, "interlaced": False, "audio": False}
        info = None
        if self.ffprobe:
            try:
                info = self.probe(path)
            except FFError:
                info = None
        if info:
            try:
                r["duration"] = float(info.get("format", {}).get("duration") or 0)
            except ValueError:
                pass
            for st in info.get("streams", []):
                if st.get("codec_type") == "audio":
                    r["audio"] = True
                elif st.get("codec_type") == "video" and not r["w"]:
                    r["w"], r["h"] = int(st.get("width") or 0), int(st.get("height") or 0)
                    m = re.match(r"^(\d+):(\d+)$", st.get("sample_aspect_ratio") or "")
                    if m and int(m.group(1)) and int(m.group(2)):
                        r["sar"] = int(m.group(1)) / int(m.group(2))
                    if st.get("field_order") not in (None, "progressive", "unknown"):
                        r["interlaced"] = True
            r["fps"] = self.video_fps(info)
        if not info or r["duration"] <= 0 or not r["w"]:
            try:
                pr = subprocess.run([self.ffmpeg, "-hide_banner", "-nostdin", "-i", path], stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=60, creationflags=_NOWIN)
            except (OSError, subprocess.SubprocessError) as e:
                raise FFError(str(e))
            txt = pr.stderr.decode("utf-8", "replace")
            m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", txt)
            if m and r["duration"] <= 0:
                r["duration"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
            if not r["w"]:
                m = re.search(r"Video:.*?,\s*(\d{2,5})x(\d{2,5})", txt)
                if m:
                    r["w"], r["h"] = int(m.group(1)), int(m.group(2))
                m = re.search(r"SAR\s+(\d+):(\d+)", txt)
                if m and int(m.group(2)):
                    r["sar"] = int(m.group(1)) / int(m.group(2)) or 1.0
                m = re.search(r"([\d.]+)\s*fps", txt)
                if m and float(m.group(1)) > 0:
                    r["fps"] = float(m.group(1))
            if "Audio:" in txt:
                r["audio"] = True
        if r["w"] == 0 and r["duration"] <= 0:
            raise FFError(_("Nem olvasható a fájl.", "Cannot read the file."))
        return r

    def probe(self, path):
        if not self.ffprobe:
            raise FFError(_("Az ffprobe nincs megadva.", "ffprobe is not set."))
        txt = self._run([self.ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", path], 60)
        try:
            return json.loads(txt)
        except ValueError:
            raise FFError("ffprobe JSON")

    @staticmethod
    def stream_rows(info):
        rows = []
        for s in info.get("streams", []):
            kind = s.get("codec_type", "?")
            det = ""
            if kind == "video":
                det = "%sx%s  %s  %s" % (s.get("width"), s.get("height"), s.get("pix_fmt", ""), s.get("avg_frame_rate", ""))
                if s.get("field_order") not in (None, "progressive", "unknown"):
                    det += "  " + s["field_order"]
            elif kind == "audio":
                det = "%s Hz  %s ch  %s" % (s.get("sample_rate", ""), s.get("channels", ""), s.get("channel_layout", ""))
            br = s.get("bit_rate")
            rows.append((s.get("index"), kind, s.get("codec_name", ""), s.get("profile", ""), det,
                         ("%d kb/s" % (int(br) // 1000)) if br and br.isdigit() else "",
                         s.get("tags", {}).get("language", "")))
        return rows

    @staticmethod
    def video_fps(info):
        for s in info.get("streams", []):
            if s.get("codec_type") == "video":
                try:
                    a, b = s.get("avg_frame_rate", "0/1").split("/")
                    if float(b) and float(a):
                        return float(a) / float(b)
                except (ValueError, ZeroDivisionError):
                    pass
        return 25.0

    # --- képkocka és hanghullám PNG-ben (Tk PhotoImage közvetlenül olvassa) ---
    def frame_png(self, path, t, width=240):
        return self._run([self.ffmpeg, "-v", "error", "-ss", "%.3f" % max(0.0, t), "-i", path, "-frames:v", "1",
                          "-vf", "scale=%d:-2" % width, "-f", "image2pipe", "-vcodec", "png", "-"], 60, True)

    def wave_png(self, path, t0, dur, w=900, h=120):
        flt = "aformat=channel_layouts=mono,showwavespic=s=%dx%d:colors=0x33aaff" % (w, h)
        return self._run([self.ffmpeg, "-v", "error", "-ss", "%.3f" % max(0.0, t0), "-t", "%.3f" % dur, "-i", path,
                          "-filter_complex", flt, "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"], 120, True)

    # --- lejátszás ---
    def play_cmd(self, path, t0, dur, audio_only=False, loop=False, volume=100, width=0):
        if self.ffplay:
            c = [self.ffplay, "-hide_banner", "-loglevel", "error", "-autoexit", "-ss", "%.3f" % max(0.0, t0)]
            if dur and dur > 0:
                c += ["-t", "%.3f" % dur]
            if audio_only:
                c += ["-nodisp"]
            if loop:
                c += ["-loop", "0"]
            c += ["-volume", str(int(volume))]
            if width and not audio_only:
                c += ["-x", str(int(width))]
            return c + [path]
        return None

    def play(self, path, t0, dur, **kw):
        cmd = self.play_cmd(path, t0, dur, **kw)
        if cmd is None:
            # nincs ffplay: rövid szakasz másolása és megnyitás az alapértelmezett lejátszóval
            tmp = os.path.join(tempfile.gettempdir(), "lvt_preview_%d.mkv" % os.getpid())
            self._run([self.ffmpeg, "-v", "error", "-y", "-ss", "%.3f" % max(0.0, t0), "-t", "%.3f" % dur, "-i", path,
                       "-c", "copy", tmp], 120)
            if hasattr(os, "startfile"):
                os.startfile(tmp)       # Windows: alapértelmezett lejátszó
            else:
                subprocess.Popen(["xdg-open", tmp])
            return None
        return subprocess.Popen(cmd, creationflags=_NOWIN)

    # --- átalakítás ---
    def build_convert(self, o, probe_dur=None):
        """o: beállítások szótára -> (parancs, várt hossz másodpercben)."""
        src, out = o.get("src"), o.get("out")
        if not src or not out:
            raise FFError(_("Hiányzik a forrás vagy a cél fájl.", "Source or output file missing."))
        t0 = parse_time(o.get("start"))
        t1 = parse_time(o.get("end"))
        if t0 is not None and t1 is not None and t1 <= t0:
            raise FFError(_("A vég nem lehet korábbi, mint az eleje.", "End must be after start."))
        cmd = [self.ffmpeg, "-hide_banner", "-nostdin", "-y" if o.get("overwrite", True) else "-n",
               "-progress", "pipe:1", "-nostats"]
        if o.get("hwaccel") and o["hwaccel"] != "-" and not o.get("fx_vs"):
            cmd += ["-hwaccel", o["hwaccel"]]
        accurate = bool(o.get("accurate"))
        vs = o.get("fx_vs")                       # VapourSynth-szakasz: a kép a vspipe-ból jön (y4m a stdin-en), a hang a forrásból
        vc, ac = o.get("vcodec", "copy"), o.get("acodec", "copy")
        if vs:
            cmd += ["-f", "yuv4mpegpipe", "-i", "-"]
            if ac != "none":
                if t0 is not None:
                    cmd += ["-ss", "%.3f" % t0]
                cmd += ["-i", src]
        else:
            if t0 is not None and not accurate:
                ss0 = t0
                if vc == "copy" and self.ffprobe:
                    # Másolásnál a -ss a konténer kezdőidejéhez mér, a kulcskockák ideje a videóéhoz.
                    # Ha a hang korábban indul (pl. Opus pre-skip MKV/MP4-ben), a vágás egy GOP-pal
                    # korábbra esne, a hang pedig elcsúszna / elmaradna. Ezt ellensúlyozza az eltolás.
                    try:
                        _inf = self.probe(src)
                        ss0 = max(0.0, t0 + lvt_smartcut.av_start_delta(_inf, lvt_smartcut._video_stream(_inf))
                                  + lvt_smartcut.SEEK_EPS)
                    except Exception:
                        ss0 = t0
                cmd += ["-ss", "%.3f" % ss0]           # gyors keresés a bemeneten
            cmd += ["-i", src]
            if t0 is not None and accurate:
                cmd += ["-ss", "%.3f" % t0]           # kocka-pontos (dekódolás a kezdőpontig)
        dur = None
        if t0 is not None and t1 is not None:
            dur = t1 - t0
        elif t1 is not None:
            dur = t1
        elif t0 is not None and probe_dur:
            dur = max(0.0, probe_dur - t0)
        elif probe_dur:
            dur = probe_dur
        if t1 is not None:
            cmd += ["-t", "%.3f" % dur]
        if vc == "none":
            cmd += ["-vn"]
        else:
            cmd += ["-map", "0:v" if vs else "0:v?", "-c:v", vc]
        if ac == "none":
            cmd += ["-an"]
        else:
            cmd += ["-map", "1:a?" if vs else "0:a?", "-c:a", ac]
        if o.get("subs", True) and o.get("subs_copy", False) and not vs:
            cmd += ["-map", "0:s?", "-c:s", "copy"]
        vf = []
        fx = (o.get("fx_vf") or "").strip()         # a Képeffektek ablak szűrőlánca (efekt.py)
        fx_deint = bool(re.search(r"\b(yadif|bwdif|w3fdif|estdif|fieldmatch|vapoursynth)\b", fx))
        if o.get("deint") and not fx_deint:
            vf.append("yadif=0:-1:0")
        if fx:
            vf.append(fx)
        if (o.get("scale") or "").strip():
            vf.append("scale=%s" % o["scale"].strip())
        if (o.get("fps") or "").strip():
            vf.append("fps=%s" % o["fps"].strip())
        if (o.get("vf") or "").strip():
            vf.append(o["vf"].strip())
        af = []
        if (o.get("volume") or "").strip():
            af.append("volume=%sdB" % o["volume"].strip())
        if (o.get("af") or "").strip():
            af.append(o["af"].strip())
        gfps = self._parse_fps(o.get("fps"))
        if not gfps and vs:
            gfps = self._parse_fps(vs.get("fps"))
        if not gfps and vc not in ("copy", "none") and not (o.get("gop") or "").strip() and self.ffprobe:
            try:
                gfps = self.video_fps(self.probe(src))     # a forrás kocka/mp-je az automatikus GOP-hoz
            except FFError:
                gfps = None
        cmd += self._enc_opts(o, vc, ac, vf, af, fps=gfps, out=out)
        cmd += self._out_opts(o, out, vc)
        cmd.append(out)
        if vs:
            cmd = PipeCmd(cmd, [{"vcmd": list(vs["vcmd"])}])
        return cmd, dur

    @staticmethod
    def _parse_fps(v):
        """'50', '25000/1001', '29.97' -> float; hibánál None."""
        v = (str(v) if v is not None else "").strip().replace(",", ".")
        if not v:
            return None
        try:
            if "/" in v:
                a, b = v.split("/", 1)
                r = float(a) / float(b)
            else:
                r = float(v)
        except (ValueError, ZeroDivisionError):
            return None
        return r if r > 0 else None

    # --- a kódolási és kimeneti opciók közös részei (egy fájlos és összefűzős átalakításhoz) ---
    @staticmethod
    def _enc_opts(o, vc, ac, vf=None, af=None, fps=None, out=""):
        """Kódoló-beállítások (előbeállítás, minőség, bitráta, pix_fmt, hang paraméterek). A vf / af lista
        elemei egy -vf / -af láncba kerülnek; összefűzős (filter_complex) módban üresen hagyandók.
        GOP: a 'gop' mező (kocka) a kulcskockák távolsága. Üresen MPEG-TS / M2TS kimenetnél automatikus:
        kb. 0,5 mp (fps/2), mint a kameráknál. Enélkül az x264 5 mp-es GOP-ot ír (keyint=250), és a
        lejátszóban a tekerés 1-2 mp-et akad (a kép a kulcskockától dekódol, a hang közben megy tovább)."""
        cmd = []
        if vc not in ("copy", "none"):
            if o.get("preset") and re.search(r"x26[45]|nvenc|svtav1|qsv|amf", vc):
                cmd += ["-preset", o["preset"]]
            g = (o.get("gop") or "").strip()
            if not g:
                cont = (o.get("container") or "").strip().lower()
                ext = os.path.splitext(out or "")[1].lower()
                if fps and (cont in ("mpegts", "mpeg", "dvd", "vob") or (not cont and ext in (".m2ts", ".ts", ".mts", ".mpg", ".vob"))):
                    g = str(max(1, int(round(fps / 2.0))))
            if g:
                try:
                    gi = max(1, int(float(g.replace(",", "."))))
                except ValueError:
                    gi = 0
                if gi:
                    cmd += ["-g", str(gi)]
                    if re.search(r"x26[45]", vc):
                        cmd += ["-keyint_min", str(max(1, gi // 2)),
                                "-x264-params" if "264" in vc else "-x265-params", "open-gop=0"]
            q = (o.get("crf") or "").strip()
            vb = norm_bitrate(o.get("vbitrate"))
            if vb:
                cmd += ["-b:v", vb]
            elif q:
                if "nvenc" in vc:
                    cmd += ["-rc", "vbr", "-cq", q, "-b:v", "0"]
                elif "qsv" in vc:
                    cmd += ["-global_quality", q]
                elif "amf" in vc:
                    cmd += ["-qp_i", q, "-qp_p", q]
                elif "vpx" in vc or "aom" in vc:
                    cmd += ["-crf", q, "-b:v", "0"]
                elif re.search(r"x26[45]|svtav1|rav1e", vc):
                    cmd += ["-crf", q]
                else:
                    cmd += ["-q:v", q]
            if vf:
                cmd += ["-vf", ",".join(vf)]
            if (o.get("pix_fmt") or "").strip():
                cmd += ["-pix_fmt", o["pix_fmt"].strip()]
        if ac not in ("copy", "none"):
            if norm_bitrate(o.get("abitrate")):
                cmd += ["-b:a", norm_bitrate(o.get("abitrate"))]
            if (o.get("achannels") or "").strip():
                cmd += ["-ac", o["achannels"].strip()]
            if (o.get("arate") or "").strip():
                cmd += ["-ar", o["arate"].strip()]
            if af:
                cmd += ["-af", ",".join(af)]
        return cmd

    @staticmethod
    def _out_opts(o, out, vc):
        """Konténer-specifikus kimeneti opciók (faststart, -f, m2ts, egyéni extra paraméterek)."""
        cmd = []
        if vc == "copy" and o.get("avoid_neg", True):
            cmd += ["-avoid_negative_ts", "make_zero"]
        ext = os.path.splitext(out)[1].lower()
        cont = (o.get("container") or "").strip()
        mp4fam = (cont in ("mp4", "mov", "ipod", "psp", "3gp", "3g2", "f4v")) if cont \
            else ext in (".mp4", ".m4v", ".mov")
        if mp4fam and o.get("faststart", True):
            cmd += ["-movflags", "+faststart"]
        if cont:
            cmd += ["-f", cont]
            if cont == "mpegts" and ext == ".m2ts":
                cmd += ["-mpegts_m2ts_mode", "1"]
        elif ext == ".m2ts":
            cmd += ["-f", "mpegts", "-mpegts_m2ts_mode", "1"]
        extra = (o.get("extra") or "").strip()
        if extra:
            import shlex
            cmd += shlex.split(extra, posix=(os.name != "nt"))
        return cmd

    # --- több szakasz EGY menetben: vágás + egybefűzés egyetlen szűrőgráffal ---
    @staticmethod
    def join_ok(o):
        """Igaz, ha a szakaszok egy menetben fűzhetők össze (a videó nem 'copy', és van mit kódolni).
        Másolásnál (copy) csak a darabonkénti vágás + concat lehetséges."""
        vc, ac = o.get("vcodec", "copy"), o.get("acodec", "copy")
        return vc != "copy" and not (vc == "none" and ac == "none")

    def _join_facts(self, path):
        """A forrás adatai az egybefűzéshez: van-e kép / hang, méret, kocka/mp, SAR, mintavétel, csatornák."""
        f = {"v": False, "a": False, "w": 0, "h": 0, "fps": "", "sar": "1/1", "sarf": 1.0,
             "ar": 0, "ach": 0, "vspec": "v:0", "aspec": "a:0"}
        info = None
        if self.ffprobe:
            try:
                info = self.probe(path)
            except FFError:
                info = None
        if info:
            bestv = besta = None
            for st in info.get("streams", []):
                kind = st.get("codec_type")
                if kind == "video" and not (st.get("disposition") or {}).get("attached_pic"):
                    px = int(st.get("width") or 0) * int(st.get("height") or 0)
                    if bestv is None or px > bestv[0]:          # az FFmpeg is a legnagyobb felbontásút választja
                        bestv = (px, st)
                elif kind == "audio":
                    ch = int(st.get("channels") or 0)
                    if besta is None or ch > besta[0]:          # ...és a legtöbb csatornásat (ez szól az előnézetben is)
                        besta = (ch, st)
            if bestv:
                st = bestv[1]
                f["v"] = True
                f["vspec"] = str(st.get("index", 0))
                w, h = int(st.get("width") or 0), int(st.get("height") or 0)
                rot = 0
                try:
                    rot = int(float((st.get("tags") or {}).get("rotate") or 0))
                except ValueError:
                    pass
                for sd in st.get("side_data_list") or []:
                    if "rotation" in sd:
                        try:
                            rot = int(float(sd["rotation"]))
                        except ValueError:
                            pass
                if abs(rot) % 180 == 90:                        # az FFmpeg automatikusan elforgatja
                    w, h = h, w
                f["w"], f["h"] = w, h
                for key in ("avg_frame_rate", "r_frame_rate"):
                    m = re.match(r"^(\d+)/(\d+)$", st.get(key) or "")
                    if m and int(m.group(1)) and int(m.group(2)):
                        f["fps"] = "%s/%s" % m.groups()
                        break
                m = re.match(r"^(\d+):(\d+)$", st.get("sample_aspect_ratio") or "")
                if m and int(m.group(1)) and int(m.group(2)):
                    f["sar"] = "%s/%s" % m.groups()
                    f["sarf"] = int(m.group(1)) / int(m.group(2))
            if besta:
                st = besta[1]
                f["a"] = True
                f["aspec"] = str(st.get("index", 0))
                try:
                    f["ar"] = int(st.get("sample_rate") or 0)
                except ValueError:
                    pass
                f["ach"] = int(st.get("channels") or 0)
        else:
            try:
                qi = self.quick_info(path)
            except FFError:
                qi = {}
            f["v"] = bool(qi.get("w"))
            f["w"], f["h"] = int(qi.get("w") or 0), int(qi.get("h") or 0)
            f["fps"] = ("%.5f" % qi["fps"]) if qi.get("fps") else ""
            f["sarf"] = float(qi.get("sar") or 1.0)
            f["sar"] = "%.6f" % f["sarf"]
            f["a"] = bool(qi.get("audio"))
        return f

    def build_join(self, items, o, out, tmpdir=None, vsx=None):
        """items: [(forrás, kezdet, vég, effekt_vf), ...] -> (parancs, várt hossz, ideiglenes fájlok listája).

        EGYETLEN ffmpeg-menet: minden szakasz külön, kocka-pontos bemenet (-ss/-t), szakaszonként azonos
        kocka/mp-re, mérethez, képaránypontra, mintavételre és csatornaelrendezésre hozva, a kép és a hang pontosan
        a szakasz hosszára vágva (a hang kiegészítve / levágva), majd a concat SZŰRŐ fűzi össze, és EGY kódoló
        írja ki. Így nincs darabonkénti kódolás, nincs AAC-előfutás és -lecsengés az illesztéseknél, és a kép és
        a hang hossza szakaszonként ugyanannyi: nem csúszhatnak el egymáshoz képest.

        vsx: (nem kötelező) az items-szel párhuzamos lista; eleme None vagy {"vcmd": [vspipe...], "fps": ...} (VapourSynth).
        Ha van benne VapourSynth-es szakasz, a KÉP minden szakaszból egy-egy előkészítő ffmpeg-en (vspipe -> normalizálás)
        át, egyetlen y4m-folyamként érkezik a végső kódoló stdin-jére (PipeCmd), a hang a szűrőgráfban marad.
        Köztes fájl így sincs: egyetlen kódolás készül."""
        if not items:
            raise FFError(_("Nincs szakasz.", "No segments."))
        vc, ac = o.get("vcodec", "copy"), o.get("acodec", "copy")
        if ac == "copy":                    # a szűrőgráfon átmenő hangot újra kell kódolni
            ac = "aac"
            o = dict(o, acodec="aac")
            if not norm_bitrate(o.get("abitrate")):
                o["abitrate"] = "192k"
        facts = {}
        for src, a, b, _fx in items:
            if b <= a:
                raise FFError(_("A vég nem lehet korábbi, mint az eleje.", "End must be after start."))
            if src not in facts:
                facts[src] = self._join_facts(src)
        first_v = next((facts[i[0]] for i in items if facts[i[0]]["v"]), None)
        first_a = next((facts[i[0]] for i in items if facts[i[0]]["a"]), None)
        hv = vc != "none" and first_v is not None
        ha = ac != "none" and first_a is not None
        pipe = bool(vsx) and any(vsx) and hv
        if pipe and len(vsx) != len(items):
            raise FFError("vsx / items hossza eltér.")
        if not hv and not ha:
            raise FFError(_("A szakaszokban nincs kép és hang, amit ki lehetne írni.",
                            "The segments contain no video or audio to write."))
        W = H = 0
        F = TS = TSF = None
        if hv:
            W, H = first_v["w"] or 0, first_v["h"] or 0
            if W <= 0 or H <= 0:
                raise FFError(_("A kép mérete nem állapítható meg.", "Cannot determine the picture size."))
            W, H = W - W % 2, H - H % 2
            m_sz = re.fullmatch(r"\s*(\d{2,5})\s*[:x]\s*(\d{2,5})\s*", str(o.get("scale") or ""))
            if m_sz:            # a „méret” mező a mérvadó: a szakaszok ehhez igazodnak (nem az első forrás méretéhez)
                W, H = int(m_sz.group(1)), int(m_sz.group(2))
                W, H = W - W % 2, H - H % 2
            F = (o.get("fps") or "").strip() or first_v["fps"] or "25"
            TS, TSF = first_v["sar"], first_v["sarf"]
        R, L = 48000, "stereo"
        if ha:
            try:
                R = int((o.get("arate") or "").strip() or 0) or first_a["ar"] or 48000
            except ValueError:
                R = first_a["ar"] or 48000
            try:
                nch = int((o.get("achannels") or "").strip() or 0) or first_a["ach"]
            except ValueError:
                nch = first_a["ach"]
            L = {1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}.get(nch, "stereo")

        cmd = [self.ffmpeg, "-hide_banner", "-nostdin", "-y" if o.get("overwrite", True) else "-n",
               "-progress", "pipe:1", "-nostats"]
        # Bemenetek. FONTOS: nem használunk bemeneti -ss keresést: MPEG-TS / M2TS (MTS) forrásnál az FFmpeg keresése
        # NEM kocka-pontos (a kért ponttól másodpercekkel később indulhat, kockák vesznek el vagy ismétlődnek).
        # Ezért a fájl elejétől dekódolunk, és a szűrőgráfban vágunk (trim / atrim) - ez minden konténernél pontos.
        # Ha egy forrás szakaszai időrendben, átfedés nélkül követik egymást, EGY bemenet szolgálja ki mindet
        # (egyszeri dekódolás); egyébként szakaszonként külön bemenet kell (különben a memória megtelne).
        by_src = {}
        for n, it in enumerate(items):
            by_src.setdefault(it[0], []).append(n)
        inputs, seg_in = [], {}
        for src, ns in by_src.items():
            if all(items[ns[k]][1] >= items[ns[k - 1]][2] - 1e-6 for k in range(1, len(ns))):
                seg_in.update({n: len(inputs) for n in ns})
                inputs.append((src, max(items[n][2] for n in ns) + 1.0))
            else:
                for n in ns:
                    seg_in[n] = len(inputs)
                    inputs.append((src, items[n][2] + 1.0))
        users = {}
        for n, idx in seg_in.items():
            users.setdefault(idx, []).append(n)
        off = 0
        if pipe:                            # a 0. bemenet a képfolyam (y4m, stdin); a hang-bemenetek utána jönnek
            cmd += ["-f", "yuv4mpegpipe", "-i", "-"]
            off = 1
        for src, tmax in inputs:
            # a -t felső korlát: az olvasás ennél tovább nem megy (+1 mp tartalék a B-kockák átrendezése miatt)
            cmd += ["-t", "%.3f" % tmax, "-i", src]
        chains = []
        src_v, src_a = {}, {}
        for idx, ns in users.items():
            f = facts[inputs[idx][0]]
            for kind, spec, tag, flt, ok, store in (("v", f["vspec"], "sv", "split", hv and f["v"], src_v),
                                                    ("a", f["aspec"], "sa", "asplit", ha and f["a"], src_a)):
                if not ok or (kind == "v" and pipe):
                    continue
                if len(ns) == 1:
                    store[ns[0]] = "[%d:%s]" % (idx + off, spec)
                else:
                    labs = ["[%s%d]" % (tag, n) for n in ns]
                    chains.append("[%d:%s]%s=%d%s" % (idx + off, spec, flt, len(ns), "".join(labs)))
                    store.update(zip(ns, labs))
        total = 0.0
        fx_re = r"\b(yadif|bwdif|w3fdif|estdif|fieldmatch|vapoursynth)\b"
        for n, (src, a, b, fx) in enumerate(items):
            d = b - a
            total += d
            f = facts[src]
            if hv and pipe:
                pass                                            # a képet a csővezeték hozza (lásd alább)
            elif hv:
                if n in src_v:
                    # trim = kocka-pontos vágás; a setpts a szakaszt 0-ra tolja (a hanggal AZONOS a-val: a kép-hang
                    # eltolás a forrásban lévővel egyezik); fps = állandó kocka/mp, a szakasz PONTOSAN 0-nál indul
                    ch = ["trim=start=%.6f:end=%.6f" % (a, b), "setpts=PTS-%.6f/TB" % a]
                    fx = (fx or "").strip()
                    if o.get("deint") and not re.search(fx_re, fx):
                        ch.append("yadif=0:-1:0")
                    if fx:
                        ch.append(fx)
                    if abs(f["sarf"] - TSF) > 0.002:            # eltérő képarányú pont -> az első szakaszéra
                        ch.append("scale=w=trunc(iw*sar/%.6f/2)*2:h=ih" % TSF)
                    ch.append("scale=%d:%d:force_original_aspect_ratio=decrease" % (W, H))
                    ch.append("pad=%d:%d:(ow-iw)/2:(oh-ih)/2" % (W, H))
                    ch.append("setsar=%s" % TS)
                    ch.append("fps=%s:start_time=0" % F)
                    ch.append("trim=duration=%.3f" % d)
                    chains.append("%s%s[v%d]" % (src_v[n], ",".join(ch), n))
                else:                                           # a szakasznak nincs képe: fekete kép
                    chains.append("color=c=black:s=%dx%d:r=%s:d=%.3f,format=yuv420p,setsar=%s[v%d]"
                                  % (W, H, F, d, TS, n))
            if ha:
                fmt = "aformat=sample_fmts=fltp:sample_rates=%d:channel_layouts=%s" % (R, L)
                if n in src_a:
                    # atrim = mintapontos vágás; first_pts=0: a késve induló hang elé csend kerül, a lyukak
                    # kitöltődnek; apad+atrim: a hang pontosan a szakasz hosszú -> a kép és a hang nem csúszhat el
                    chains.append("%satrim=start=%.6f:end=%.6f,asetpts=PTS-%.6f/TB,aresample=async=1:first_pts=0,"
                                  "%s,apad,atrim=duration=%.3f[a%d]" % (src_a[n], a, b, a, fmt, d, n))
                else:                                           # a szakasznak nincs hangja: csend
                    chains.append("anullsrc=r=%d:cl=%s:d=%.3f,%s[a%d]" % (R, L, d, fmt, n))
        if pipe:
            if ha:
                cat = "".join("[a%d]" % n for n in range(len(items)))
                chains.append(cat + "concat=n=%d:v=0:a=1[ac]" % len(items))
        else:
            cat = "".join(("[v%d]" % n if hv else "") + ("[a%d]" % n if ha else "") for n in range(len(items)))
            cat += "concat=n=%d:v=%d:a=%d" % (len(items), 1 if hv else 0, 1 if ha else 0)
            cat += ("[vc]" if hv else "") + ("[ac]" if ha else "")
            chains.append(cat)
        # az összefűzés UTÁNI szűrők (átméretezés, egyéni -vf, hangerő, egyéni -af): az egész anyagra egyszer
        vpost, apost = [], []
        if hv:
            if (o.get("scale") or "").strip():
                vpost.append("scale=%s" % o["scale"].strip())
            if (o.get("vf") or "").strip():
                vpost.append(o["vf"].strip())
        if ha:
            if (o.get("volume") or "").strip():
                apost.append("volume=%sdB" % o["volume"].strip())
            if (o.get("af") or "").strip():
                apost.append(o["af"].strip())
        if hv:
            chains.append("[%s]%s[vout]" % ("0:v" if pipe else "vc", ",".join(vpost) if vpost else "null"))
        if ha:
            chains.append("[ac]%s[aout]" % (",".join(apost) if apost else "anull"))
        graph = ";".join(chains)
        tmpfiles = []
        if len(graph) > 12000:              # a Windows parancssora kb. 32 000 karakter: hosszú gráfot fájlból olvastatunk
            fd, gp = tempfile.mkstemp(prefix="lvt_graph_", suffix=".txt", dir=tmpdir)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(graph)
            tmpfiles.append(gp)
            cmd += ["-filter_complex_script", gp]
        else:
            cmd += ["-filter_complex", graph]
        if hv:
            cmd += ["-map", "[vout]", "-c:v", vc]
        else:
            cmd += ["-vn"]
        if ha:
            cmd += ["-map", "[aout]", "-c:a", ac]
        else:
            cmd += ["-an"]
        cmd += ["-max_muxing_queue_size", "4096"]
        cmd += self._enc_opts(o, vc if hv else "none", ac if ha else "none", fps=self._parse_fps(F) if hv else None, out=out)
        cmd += self._out_opts(o, out, vc)
        cmd.append(out)
        if pipe:
            pf = (o.get("pix_fmt") or "").strip() or "yuv420p"
            srcs = []
            for n, (src, a, b, fx) in enumerate(items):
                srcs.append(self._join_stage(n, src, a, b, fx, vsx[n], facts[src], W, H, F, TS, TSF, pf,
                                             (o.get("deint") and not re.search(fx_re, (fx or ""))), fx_re))
            cmd = PipeCmd(cmd, srcs)
        return cmd, total, tmpfiles

    def _join_stage(self, n, src, a, b, fx, vs, f, W, H, F, TS, TSF, pf, deint, fx_re):
        """Egy szakasz képe a közös y4m-folyamhoz: a szakasz vspipe-ból vagy a forrásfájlból jön, az effektek és a
        közös képméret / kocka/mp / képarány-pont / képformátum után y4m-ként a stdout-ra. -> {"vcmd", "stage"}"""
        d = b - a
        fx = (fx or "").strip()
        tail = []
        if abs(f["sarf"] - TSF) > 0.002 and not vs:
            tail.append("scale=w=trunc(iw*sar/%.6f/2)*2:h=ih" % TSF)
        tail += ["scale=%d:%d:force_original_aspect_ratio=decrease" % (W, H),
                 "pad=%d:%d:(ow-iw)/2:(oh-ih)/2" % (W, H), "setsar=%s" % TS, "fps=%s%s" % (F, "" if vs else ":start_time=0"),
                 "trim=duration=%.3f" % d]
        base = [self.ffmpeg, "-v", "error", "-nostdin"]
        outp = ["-pix_fmt", pf, "-f", "yuv4mpegpipe", "-"]
        if vs:                                              # a vspipe már a szakaszt adja (a kezdőkockától)
            chain = ([fx] if fx else []) + tail
            return {"vcmd": list(vs["vcmd"]), "stage": base + ["-f", "yuv4mpegpipe", "-i", "-", "-an", "-sn",
                                                               "-vf", ",".join(chain)] + outp}
        if not f["v"]:                                      # a szakasznak nincs képe: fekete kép
            return {"vcmd": None, "stage": base + ["-f", "lavfi", "-i", "color=c=black:s=%dx%d:r=%s:d=%.3f,format=yuv420p,setsar=%s"
                                                   % (W, H, F, d, TS)] + outp}
        chain = ["trim=start=%.6f:end=%.6f" % (a, b), "setpts=PTS-%.6f/TB" % a]
        if deint:
            chain.append("yadif=0:-1:0")
        if fx:
            chain.append(fx)
        chain += tail
        return {"vcmd": None, "stage": base + ["-t", "%.3f" % (b + 1.0), "-i", src, "-map", "0:" + f["vspec"], "-an", "-sn",
                                              "-vf", ",".join(chain)] + outp}

    @staticmethod
    def _drop_partial(cmd, t0):
        """Megszakítás után a félkész kimeneti fájl törlése (csak ha ez a futás írta)."""
        try:
            outp = cmd[-1]
            if isinstance(outp, str) and os.path.isfile(outp) and os.path.getmtime(outp) >= t0 - 2:
                os.remove(outp)
        except (OSError, IndexError, TypeError):
            pass

    def run_convert(self, cmd, total, progress=None, log=None, cancel=None):
        """Futtatja a parancsot; a -progress kimenetből számol százalékot. Siker: True.
        PipeCmd-nél (Képeffektek / VapourSynth) a vspipe képfolyama közvetlenül az ffmpeg-be megy (nincs köztes fájl)."""
        pipe = _PipeRun(cmd) if isinstance(cmd, PipeCmd) and cmd.sources else None
        t_start = time.time()
        if cancel is not None and hasattr(cancel, "can_keep"):
            cancel.can_keep = pipe is None          # részmentés csak a közvetlen ffmpeg-futásnál lehetséges
        stopping = False
        try:
            if pipe:
                p = pipe.start()
            else:
                # a -nostdin nélkül az ffmpeg a stdin-ről "q" billentyűt fogad: így szabályosan le tudjuk zárni a fájlt
                p = subprocess.Popen([x for x in cmd if x != "-nostdin"], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=_NOWIN)
        except OSError as e:
            if pipe:
                pipe.kill()
            raise FFError(str(e))
        tail = []
        try:
            for raw in p.stdout:
                ln = raw.decode("utf-8", "replace").strip()
                if cancel is not None and cancel.is_set():
                    if getattr(cancel, "keep", False) and pipe is None:
                        if not stopping:
                            stopping = True
                            try:
                                p.stdin.write(b"q")
                                p.stdin.flush()
                            except (OSError, ValueError):
                                p.kill()
                            wd = threading.Timer(20.0, lambda: p.kill() if p.poll() is None else None)
                            wd.daemon = True
                            wd.start()
                    else:
                        if pipe:
                            pipe.kill()
                        p.kill()
                        p.wait()
                        self._drop_partial(cmd, t_start)
                        raise FFError("cancelled")
                if "=" in ln and not ln.startswith("["):
                    k, v = ln.split("=", 1)
                    if k in ("out_time_us", "out_time_ms") and total and v.lstrip("-").isdigit():
                        sec = int(v) / 1e6
                        if progress:
                            progress(max(0.0, min(1.0, sec / total)))
                    elif k == "progress" and v == "end" and progress:
                        progress(1.0)
                    elif k in ("speed", "fps") and log:
                        pass
                elif ln:
                    tail.append(ln)
                    if log:
                        log(ln)
            p.wait()
        finally:
            if p.poll() is None:
                p.kill()
            try:
                if p.stdin:
                    p.stdin.close()
            except (OSError, ValueError):
                pass
            if pipe:
                if p.returncode != 0 or pipe.feed_err:
                    pipe.stop.set()
        if stopping:
            outp = cmd[-1] if cmd else ""
            if isinstance(outp, str) and os.path.isfile(outp) and os.path.getsize(outp) > 0:
                raise FFError("cancelled_keep")
            raise FFError("cancelled")
        if pipe:
            try:
                err = pipe.finish(tail)
            finally:
                pipe.kill()
            if err:
                raise FFError(err)
            return True
        if p.returncode != 0:
            raise FFError("\n".join(tail[-3:]) if tail else "exit %d" % p.returncode)
        return True


PRESETS = {
    "Gyors másolás – újrakódolás nélkül (remux)": dict(vcodec="copy", acodec="copy"),
    "H.264 jó minőség (CRF 20, AAC 192k)": dict(vcodec="libx264", preset="medium", crf="20", pix_fmt="yuv420p",
                                                acodec="aac", abitrate="192k"),
    "H.265 / HEVC kicsi fájl (CRF 24)": dict(vcodec="libx265", preset="medium", crf="24", pix_fmt="yuv420p",
                                              acodec="aac", abitrate="160k"),
    "Pontos vágás újrakódolással (REC / nyitott GOP javítás)": dict(vcodec="libx264", preset="fast", crf="16",
                                                                   pix_fmt="yuv420p", acodec="aac",
                                                                   abitrate="256k", accurate=True),
    "Összefésült (interlaced) -> progresszív, H.264": dict(vcodec="libx264", preset="medium", crf="19", deint=True,
                                                          pix_fmt="yuv420p", acodec="aac", abitrate="192k"),
    "Csak hang kimentése (AAC)": dict(vcodec="none", acodec="aac", abitrate="192k"),
    "Videó hang nélkül": dict(vcodec="copy", acodec="none"),
}

# The Hungarian names above are the stable preset IDs; the labels shown in the UI follow the language.
PRESET_EN = {
    "Gyors másolás – újrakódolás nélkül (remux)": "Fast copy – no re-encoding (remux)",
    "H.264 jó minőség (CRF 20, AAC 192k)": "H.264 good quality (CRF 20, AAC 192k)",
    "H.265 / HEVC kicsi fájl (CRF 24)": "H.265 / HEVC small file (CRF 24)",
    "Pontos vágás újrakódolással (REC / nyitott GOP javítás)": "Exact cut with re-encoding (REC / open-GOP fix)",
    "Összefésült (interlaced) -> progresszív, H.264": "Interlaced -> progressive, H.264",
    "Csak hang kimentése (AAC)": "Extract audio only (AAC)",
    "Videó hang nélkül": "Video without audio",
}
_PRESET_REV = {en: hu for hu, en in PRESET_EN.items()}


def preset_label(key):
    """Display label of a built-in preset in the active language."""
    return _(key, PRESET_EN.get(key, key))


def preset_key(label):
    """Preset ID (Hungarian name) from a label in either language."""
    return label if label in PRESETS else _PRESET_REV.get(label, label)


# a mintákban mentett mezők (a felhasználói minták ezeket tárolják)
PRESET_KEYS = ("vcodec", "acodec", "preset", "crf", "vbitrate", "pix_fmt", "abitrate", "achannels",
               "arate", "scale", "fps", "vf", "af", "volume", "container", "extra", "gop")
PRESET_BOOLS = (("accurate", False), ("deint", False), ("faststart", True), ("avoid_neg", True))
USER_MARK = "★ "
# konténer -> kiterjesztés (a cél fájl kiterjesztését a konténer választásakor erre cseréli)
CONTAINER_EXT = {"matroska": ".mkv", "webm": ".webm", "mp4": ".mp4", "mov": ".mov", "mpegts": ".ts",
                 "avi": ".avi", "flv": ".flv", "ogg": ".ogg", "ogv": ".ogv", "mp3": ".mp3", "wav": ".wav",
                 "flac": ".flac", "ipod": ".m4a", "adts": ".aac", "ac3": ".ac3", "eac3": ".eac3",
                 "opus": ".opus", "gif": ".gif", "mpeg": ".mpg", "vob": ".vob", "dvd": ".vob",
                 "asf": ".wmv", "3gp": ".3gp", "mxf": ".mxf", "mp2": ".mp2", "aiff": ".aiff"}

# ---- a konténer szabja meg a felületet: kiterjesztések + mi fér bele ----
# "v": a konténer bír-e videót; a "vp"/"ap" minta azokat a kodekneveket engedi, amelyek
# beleférnek. Ami nincs a táblázatban, arra nem szűrünk: egy szokatlan FFmpeg build ne
# tiltható le tévesen.
CONTAINERS = {
    "matroska": dict(ext=(".mkv", ".mka"), v=True,
                     vp=r"x264|x265|h26[1-4]|hevc|av1|vp[89]|mpe?g|theora|prores|ffv[12]|vc1|"
                        r"dvvideo|rawvideo|gif|cfhd|utvideo|xvid",
                     ap=r"aac|mp3|lame|flac|opus|vorbis|ac3|eac3|dts|truehd|alac|pcm_|mp2|tta|wmav"),
    "webm": dict(ext=(".webm",), v=True, vp=r"vp[89]|libvpx|av1", ap=r"opus|vorbis|flac"),
    "mp4": dict(ext=(".mp4", ".m4v", ".m4a"), v=True,
                vp=r"x264|x265|h26[45]|hevc|av1|mpe?g4|vp9|libvpx|ac[45]",
                ap=r"aac|alac|ac3|eac3|opus|flac"),
    "mov": dict(ext=(".mov",), v=True,
                vp=r"x264|x265|h26[45]|hevc|prores|mpeg4|xvid|mjpeg|jpeg|png|dnxhd|dvvideo|qtrle|ffv[12]",
                ap=r"aac|alac|pcm_|mp3|lame|ac3|adpcm"),
    "ipod": dict(ext=(".m4v", ".m4a"), v=True, vp=r"x264|x265|h26[45]|hevc", ap=r"aac|alac|ac3"),
    "psp": dict(ext=(".mp4",), v=True, vp=r"x264|h26[45]|mpeg4|xvid", ap=r"aac|mp3|lame|ac3"),
    "3gp": dict(ext=(".3gp",), v=True, vp=r"x264|h26[45]|hevc|mpeg4|xvid|h263", ap=r"aac|amr"),
    "3g2": dict(ext=(".3g2",), v=True, vp=r"x264|h26[45]|hevc|mpeg4|xvid|h263", ap=r"aac|amr"),
    "mpegts": dict(ext=(".ts", ".m2ts"), v=True,
                   vp=r"x264|x265|h26[45]|hevc|mpe?g(1|2|4)|vc1|dirac|av1",
                   ap=r"aac|mp2|mp3|lame|ac3|eac3|dts|opus|flac"),
    "mpeg": dict(ext=(".mpg", ".m2v"), v=True, vp=r"mpeg(1|2)_video|mpe?g(1|2)", ap=r"mp2|mp3|lame|aac"),
    "dvd": dict(ext=(".vob",), v=True, vp=r"mpeg2_video|mpe?g2", ap=r"ac3|mp2|dts"),
    "avi": dict(ext=(".avi",), v=True,
                vp=r"mpeg4|xvid|x264|x265|h26[45]|hevc|ffv[12]|rawvideo|cfhd|dnxhd|prores|dvvideo|mjpeg",
                ap=r"mp3|lame|pcm_|aac|ac3|wmav|flac|mp2"),
    "asf": dict(ext=(".wmv", ".wma"), v=True, vp=r"wmv[123]|msmpeg4", ap=r"wma|wmav"),
    "flv": dict(ext=(".flv",), v=True, vp=r"x264|h264|flv1|hevc", ap=r"mp3|lame|aac|adpcm"),
    "ogg": dict(ext=(".ogg", ".oga"), v=True, vp=r"theora|vp[89]|libvpx|dirac",
                ap=r"vorbis|opus|flac|speex"),
    "gif": dict(ext=(".gif",), v=True, vp=r"gif", ap=""),
    "mxf": dict(ext=(".mxf",), v=True, vp=r"mpeg2|h264|x264|prores|dnxhd|dvvideo|jpeg2000",
                ap=r"pcm_|aac|mp2"),
    "mp3": dict(ext=(".mp3",), v=False, ap=r"mp3|lame"),
    "mp2": dict(ext=(".mp2",), v=False, ap=r"mp2"),
    "wav": dict(ext=(".wav",), v=False, ap=r"pcm_|adpcm|float|ulaw|alaw"),
    "flac": dict(ext=(".flac",), v=False, ap=r"flac"),
    "aiff": dict(ext=(".aiff", ".aif"), v=False, ap=r"pcm_|alac|flac"),
    "adts": dict(ext=(".aac",), v=False, ap=r"aac"),
    "ac3": dict(ext=(".ac3",), v=False, ap=r"ac3"),
    "eac3": dict(ext=(".eac3",), v=False, ap=r"eac3"),
    "opus": dict(ext=(".opus",), v=False, ap=r"opus"),
}

# csak hangot bíró kiterjesztések: ezeknél inaktív a Videó rész. Az .mka a .mkv, az .m4a
# az .mp4 hang-változata, ezért a kiterjesztés is döntő lehet
AUDIO_ONLY_EXT = (".mka", ".m4a", ".mp3", ".mp2", ".wav", ".flac", ".aac", ".ac3", ".eac3",
                  ".dts", ".aiff", ".aif", ".oga", ".opus", ".spx", ".ape", ".au", ".wma")

# rövid leírás a kodeknév mellé; ha itt nincs, az FFmpeg saját leírása jelenik meg utána
CODEC_INFO = {
    "copy": _("Másolás – újrakódolás nélkül", "Copy – no re-encoding"),
    "none": _("Nincs ilyen folyam", "No such stream"),
    "libx264": _("H.264 – széles körben kompatibilis", "H.264 – widely compatible"),
    "libx265": _("H.265 – kisebb fájl, lassabb kódolás", "H.265 – smaller file, slower encode"),
    "libsvtav1": _("AV1 – kicsi fájl, lassú kódolás", "AV1 – small file, slow encoding"),
    "libaom-av1": _("AV1 – referencia kódoló, nagyon lassú", "AV1 – reference encoder, very slow"),
    "librav1e": _("AV1 – gyorsabb, kevesebb beállítással", "AV1 – faster, fewer options"),
    "vp9": _("VP9 – ingyenes, WebM-be", "VP9 – royalty free, for WebM"),
    "libvpx-vp9": _("VP9 – ingyenes, WebM-be", "VP9 – royalty free, for WebM"),
    "vp8": _("VP8 – régebbi WebM kódoló", "VP8 – older WebM encoder"),
    "libvpx": _("VP8 – régebbi WebM kódoló", "VP8 – older WebM encoder"),
    "mpeg2_video": _("MPEG-2 – DVD, régi lejátszók", "MPEG-2 – DVD, old players"),
    "mpeg4": _("MPEG-4 Part 2 – AVI-ban gyakori", "MPEG-4 part 2 – common in AVI"),
    "libxvid": _("Xvid – MPEG-4, régi eszközök", "Xvid – MPEG-4, old devices"),
    "h264_nvenc": _("H.264 – NVIDIA gyorsítással, gyors", "H.264 – NVIDIA accelerated, fast"),
    "hevc_nvenc": _("H.265 – NVIDIA gyorsítással, gyors", "H.265 – NVIDIA accelerated, fast"),
    "av1_nvenc": _("AV1 – NVIDIA gyorsítással", "AV1 – NVIDIA accelerated"),
    "h264_qsv": _("H.264 – Intel Quick Sync, gyors", "H.264 – Intel Quick Sync, fast"),
    "hevc_qsv": _("H.265 – Intel Quick Sync, gyors", "H.265 – Intel Quick Sync, fast"),
    "h264_amf": _("H.264 – AMD gyorsítással", "H.264 – AMD accelerated"),
    "hevc_amf": _("H.265 – AMD gyorsítással", "H.265 – AMD accelerated"),
    "aac": _("AAC – az MP4 hangszabványa", "AAC – the MP4 audio standard"),
    "libfdk_aac": _("AAC – jobb minőség, nem minden buildben van meg",
                    "AAC – better quality, not in every build"),
    "libmp3lame": _("MP3 – mindenhol lejátszható", "MP3 – plays everywhere"),
    "libopus": _("Opus – kicsi fájl, beszédre is jó", "Opus – small file, good for speech"),
    "libvorbis": _("Vorbis – Ogg hang", "Vorbis – Ogg audio"),
    "flac": _("FLAC – veszteségmentes hang", "FLAC – lossless audio"),
    "alac": _("ALAC – veszteségmentes, Apple", "ALAC – lossless, Apple"),
    "ac3": _("Dolby Digital – DVD, AVI", "Dolby Digital – DVD, AVI"),
    "eac3": _("Dolby Digital+ – műsorszórás", "Dolby Digital+ – broadcast TV"),
    "pcm_s16le": _("WAV – nyers, változatlan hang", "WAV – raw, untouched audio"),
    "prores_ks": _("ProRes – vágószoftverekhez", "ProRes – for editing software"),
    "ffv1": _("FFV1 – veszteségmentes archívum", "FFV1 – lossless archival"),
}

# az ajánlott kodekek: a Másolás és a „nincs folyam” után ezek jönnek a listában
RECOMMENDED_V = ("copy", "none", "libx264", "libx265", "libsvtav1", "libaom-av1", "vp9",
                 "libvpx-vp9", "vp8", "libvpx", "h264_nvenc", "hevc_nvenc", "av1_nvenc",
                 "h264_qsv", "hevc_qsv", "h264_amf", "hevc_amf", "mpeg2_video", "mpeg4",
                 "libxvid", "prores_ks", "ffv1")
RECOMMENDED_A = ("copy", "none", "aac", "libfdk_aac", "libmp3lame", "mp2", "libopus",
                 "libvorbis", "flac", "alac", "ac3", "eac3", "pcm_s16le", "wmav2")

# ha a megadott FFmpeg build kódolólistája nem olvasható ki (nem futtatható), ez a lista látszik –
# így a felület üres listával sem törik el, csak épp a „nincs meg a buildben” jelölés hiányzik
FALLBACK_V = ("copy", "none") + tuple(x for x in RECOMMENDED_V if x not in ("copy", "none"))
FALLBACK_A = ("copy", "none") + tuple(x for x in RECOMMENDED_A if x not in ("copy", "none"))

_CODEC_SEP = " — "
GROUP_MARK = "─"          # a csoportelválasztó jele a legördülő menő soraiban


# ---- a forrásfájl saját adataiból a Videó / Hang mezők kitöltése ----
# forrás kodek -> a kódolók (az FFmpeg neve szerint), elsőbbségi sorrendben; ami nincs a buildben, az kimarad
SRC_ENC_V = {
    "h264": ("libx264", "h264_nvenc", "h264_qsv", "h264_amf", "libopenh264"),
    "hevc": ("libx265", "hevc_nvenc", "hevc_qsv", "hevc_amf"),
    "mpeg2video": ("mpeg2video",), "mpeg1video": ("mpeg1video",), "mpeg4": ("mpeg4", "libxvid"),
    "vp9": ("libvpx-vp9",), "vp8": ("libvpx",), "av1": ("libsvtav1", "libaom-av1", "librav1e", "av1_nvenc"),
    "theora": ("libtheora",), "prores": ("prores_ks", "prores"), "mjpeg": ("mjpeg",),
    "wmv1": ("wmv1",), "wmv2": ("wmv2",), "msmpeg4v3": ("msmpeg4",), "msmpeg4v2": ("msmpeg4v2",),
}
SRC_ENC_A = {
    "aac": ("aac", "libfdk_aac"), "mp3": ("libmp3lame",), "mp2": ("mp2", "libtwolame"), "ac3": ("ac3",),
    "eac3": ("eac3",), "opus": ("libopus", "opus"), "vorbis": ("libvorbis", "vorbis"), "flac": ("flac",),
    "alac": ("alac",), "wmav2": ("wmav2",), "wmav1": ("wmav1",),
}
# a kódoló megengedett legnagyobb hangbitrátája (kb/s): a forrás értéke ide vágva
SRC_ABR_MAX = {"libmp3lame": 320, "mp2": 384, "libtwolame": 384, "ac3": 640, "libopus": 510, "opus": 510,
               "aac": 576, "libfdk_aac": 576, "libvorbis": 500, "vorbis": 500, "wmav2": 384, "wmav1": 384}
_SRC_LOSSLESS_A = re.compile(r"^(pcm_|flac$|alac$|truehd$)")


def container_from_probe(info, path):
    """Az ffprobe formátumnevéből (és a kiterjesztésből) a konténer mezőbe illő név; ismeretlenre ''."""
    names = ((info.get("format") or {}).get("format_name") or "").split(",")
    ext = os.path.splitext(path or "")[1].lower()
    if "mpegts" in names:
        return "mpegts"
    if "matroska" in names or "webm" in names:
        return "webm" if ext == ".webm" else "matroska"
    if "mov" in names or "mp4" in names:
        return {".mov": "mov", ".3gp": "3gp", ".3g2": "3g2"}.get(ext, "mp4")
    for n, c in (("avi", "avi"), ("flv", "flv"), ("asf", "asf"), ("ogg", "ogg"), ("mp3", "mp3"), ("wav", "wav"),
                 ("flac", "flac"), ("aiff", "aiff"), ("ac3", "ac3"), ("eac3", "eac3"), ("aac", "adts"),
                 ("mpeg", "mpeg"), ("gif", "gif"), ("mxf", "mxf"), ("mp2", "mp2")):
        if n in names:
            return c
    return ""


def _kbps(v):
    try:
        v = int(v)
    except (TypeError, ValueError):
        return 0
    return v // 1000 if v > 0 else 0


def settings_from_probe(info, enc_v=(), enc_a=(), path=""):
    """Az ffprobe-adatokból {mezőnév: érték}: a Videó és Hang mezők a forrás SAJÁT adataival (kodek, bitráta, méret,
    kocka/mp, pix_fmt, csatorna, mintavétel, konténer). enc_v / enc_a: az FFmpeg-build kódolói (üres = ismeretlen:
    az első jelölt kerül be). A forrás kodeknek megfelelő kódolót választja; ha nincs ilyen (pl. DTS), vagy nincs ilyen folyam, a kodek mező üres."""
    st = info.get("streams", [])
    fmt = info.get("format") or {}
    hv, ha = set(enc_v), set(enc_a)
    vs = [s for s in st if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")]
    as_ = [s for s in st if s.get("codec_type") == "audio"]
    v = max(vs, key=lambda s: int(s.get("width") or 0) * int(s.get("height") or 0), default=None)
    a = max(as_, key=lambda s: int(s.get("channels") or 0), default=None)      # mint az FFmpeg és az előnézet
    res = {"vf": "", "af": "", "volume": ""}
    cont = container_from_probe(info, path)
    if cont:
        res["container"] = cont

    def pick(cands, have):
        return next((c for c in cands if not have or c in have), "")

    if v:
        name = v.get("codec_name") or ""
        enc = pick(SRC_ENC_V.get(name, (name,)) if name else (), hv)
        res["vcodec"] = enc          # üres, ha ehhez a kodekhez nincs kódoló (kézzel választható)
        w, h = int(v.get("width") or 0), int(v.get("height") or 0)
        res["scale"] = "%d:%d" % (w, h) if w > 0 and h > 0 else ""
        m = re.match(r"^(\d+)/(\d+)$", v.get("avg_frame_rate") or "")
        if not (m and int(m.group(1)) and int(m.group(2))):
            m = re.match(r"^(\d+)/(\d+)$", v.get("r_frame_rate") or "")
        if m and int(m.group(1)) and int(m.group(2)):
            n_, d_ = int(m.group(1)), int(m.group(2))
            res["fps"] = str(n_ // d_) if n_ % d_ == 0 else "%d/%d" % (n_, d_)
        else:
            res["fps"] = ""
        res["pix_fmt"] = (v.get("pix_fmt") or "").replace("yuvj", "yuv")
        vb = _kbps(v.get("bit_rate"))
        if not vb:                  # TS / MKV: a folyam bitrátája gyakran hiányzik -> az összes mínusz a hang
            vb = _kbps(fmt.get("bit_rate")) - sum(_kbps(s.get("bit_rate")) for s in as_)
        res["vbitrate"] = ("%dk" % vb) if vb > 0 else ""
        res["preset"] = "medium" if res["vcodec"] in ("libx264", "libx265") else ""
        # bitráta ismeretében az számít; ha nincs, jó minőségű CRF
        res["crf"] = "" if res["vbitrate"] else ("20" if res["vcodec"] in ("libx264", "libx265") else "")
    else:
        res.update(vcodec="", scale="", fps="", pix_fmt="", vbitrate="", preset="", crf="")
    if a:
        name = a.get("codec_name") or ""
        enc = pick(SRC_ENC_A.get(name, (name,)) if name else (), ha)
        fallback = False
        res["acodec"] = enc          # üres, ha ehhez a kodekhez nincs kódoló (kézzel választható)
        ch = int(a.get("channels") or 0)
        res["achannels"] = str(ch) if ch > 0 else ""
        res["arate"] = str(int(a.get("sample_rate") or 0) or "") if a.get("sample_rate") else ""
        ab = _kbps(a.get("bit_rate"))
        if _SRC_LOSSLESS_A.match(name) or _SRC_LOSSLESS_A.match(enc):
            ab = 0
        elif fallback:
            ab = 384 if ch > 2 else 192
        elif ab:
            ab = min(ab, SRC_ABR_MAX.get(enc, ab))
        res["abitrate"] = ("%dk" % ab) if ab > 0 else ""
    else:
        res.update(acodec="", achannels="", arate="", abitrate="")
    return res


def gop_stats(ts, fps):
    """Az I-kockák idejéből (mp, növekvő) a GOP-statisztika: db, legkisebb / átlag / legnagyobb távolság (mp és kocka).
    None, ha kevesebb mint 2 I-kocka van (nincs mit mérni)."""
    if not ts or len(ts) < 2:
        return None
    gaps = [b - a for a, b in zip(ts, ts[1:]) if b - a > 1e-6]
    if not gaps:
        return None
    f = fps if fps and fps > 0 else 25.0
    mn, mx, av = min(gaps), max(gaps), sum(gaps) / len(gaps)
    return dict(n=len(ts), min=mn, avg=av, max=mx, min_f=int(round(mn * f)), avg_f=int(round(av * f)),
                max_f=int(round(mx * f)), first=ts[0])


def gop_text(st, short=False):
    """Olvasható GOP-összefoglaló (a státuszsorba rövid, az Info ablakba részletes)."""

    if not st:
        return _("Kevesebb mint 2 I-kocka: a GOP nem mérhető.",
                 "Fewer than 2 I-frames: GOP cannot be measured.")

    if short:
        return _("I-kockák: %d db, GOP átlag %.2f mp (%d kocka), legnagyobb %.2f mp (%d kocka)",
                 "I-frames: %d, GOP avg %.2f s (%d frames), max %.2f s (%d frames)") % (
                     st["n"],
                     st["avg"], st["avg_f"],
                     st["max"], st["max_f"])

    t = _("GOP (kulcskocka-távolság)\n\n"
          "  I-kockák száma : %d db\n"
          "  Legkisebb GOP  : %.2f mp (%d kocka)\n"
          "  Átlagos GOP    : %.2f mp (%d kocka)\n"
          "  Legnagyobb GOP : %.2f mp (%d kocka)\n"
          "  Első I-kocka   : %.2f mp\n",
          "GOP (keyframe distance)\n\n"
          "  Number of I-frames : %d\n"
          "  Smallest GOP       : %.2f s (%d frames)\n"
          "  Average GOP        : %.2f s (%d frames)\n"
          "  Largest GOP        : %.2f s (%d frames)\n"
          "  First I-frame      : %.2f s\n") % (
              st["n"],
              st["min"], st["min_f"],
              st["avg"], st["avg_f"],
              st["max"], st["max_f"],
              st["first"])

    if st["max"] > 2.0:
        t += _(
            "\n⚠ Hosszú GOP (>2 mp)\n"
            "  Előre- vagy visszatekeréskor a kívánt kép\n"
            "  megjelenése kissé lassabb lehet.\n",
            "\n⚠ Long GOP (>2 s)\n"
            "  Forward/backward seeking may be slightly slower.\n"
        )

    elif st["max"] <= 1.0:
        t += _(
            "\n✓ Rövid GOP (≤1 mp)\n"
            "  Gyors és pontos tekerés.\n",
            "\n✓ Short GOP (<=1 s)\n"
            "  Fast and accurate seeking.\n"
        )

    t += _(
        "\nMegjegyzés:\n"
        "  • Több I-kocka = gyorsabb tekerés, nagyobb fájl.\n"
        "  • A GOP főként tekeréskor és vágáskor számít.\n",
        "\nNotes:\n"
        "  • More I-frames = faster seeking, larger file.\n"
        "  • GOP mainly affects seeking and editing.\n"
    )

    return t

def is_group_row(label):
    """Igaz, ha a Combobox sora csak csoportelválasztó („── ajánlott ──”)."""
    t = (label or "").strip()
    return bool(t) and (t.startswith(GROUP_MARK) or t.endswith(GROUP_MARK))


MORE_MARK = "▸"           # a rövid lista utolsó sora: ez nyitja a kereshető kodekválasztót
# a hardveres (GPU) kódolók nevének végződése: ezek külön csoportba kerülnek
_HW_RE = re.compile(r"_(nvenc|qsv|amf|vaapi|videotoolbox|mf|vulkan|v4l2m2m|omx|rkmpp|mediacodec|cuvid)$", re.I)


def is_more_row(label):
    """Igaz, ha a Combobox sora a „Továbbiak…” sor (a kereshető ablakot nyitja)."""
    return (label or "").strip().startswith(MORE_MARK)


def codec_label(name, desc="", miss=False):
    """A legördülő menő sora: „libx264 — H.264 – széles körben kompatibilis”."""
    d = CODEC_INFO.get(name) or (desc or "").strip()
    if miss:
        d = (d + " " if d else "") + _("(nincs meg ebben az FFmpeg buildben)",
                                        "(not in this FFmpeg build)")
    return (name + _CODEC_SEP + d) if d else name


def codec_name(label):
    """A legördülő sorából a kodeknevet kapjuk vissza: ezt tartja a mező és a profil."""
    return ((label or "").split(_CODEC_SEP)[0] or "").strip()


# ----------------------------------------------------------------- grafikus felület ---

class _AnalyzerHost:
    """A Videó-elemző (lvt_analyzer.AnalyzerTab) hosztja: a FFmpeg panel állapotát adja át –
    az aktuális fájlt, az ffmpeg / ffprobe útvonalát, a nyelvet. Külső programot csak akkor enged,
    ha a modul be van kapcsolva (EXTERNAL_OK)."""

    def __init__(self, panel):
        self._panel = panel

    @property
    def LANG(self):
        return "hu" if _("x", "y") == "x" else "en"

    @property
    def EXTERNAL_OK(self):
        return bool(self._panel.v_enabled.get())

    @property
    def FFMPEG(self):
        return self._panel.v_ffmpeg.get().strip() if self.EXTERNAL_OK else ""

    @property
    def FFPROBE(self):
        return self._panel.v_ffprobe.get().strip() if self.EXTERNAL_OK else ""

    def current_path(self):
        return self._panel.v_src.get().strip()

    def probe_json(self, path):
        """ffprobe JSON (külön folyamat, stdlib). Hibánál None."""
        if not self.EXTERNAL_OK or not self.FFPROBE:
            return None
        import json
        import os as _os
        import subprocess
        cmd = [self.FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path]
        kw = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "timeout": 120}
        if _os.name == "nt":
            kw["creationflags"] = 0x08000000   # CREATE_NO_WINDOW
        try:
            r = subprocess.run(cmd, **kw)
            return json.loads(r.stdout.decode("utf-8", "replace")) if r.returncode == 0 else None
        except Exception:
            return None


class FfmpegPanel:
    """Önálló panel tetszőleges Tk tárolóban. tk/ttk/filedialog/messagebox kívülről érkezik (mint a vágónál)."""

    def __init__(self, parent, tk, ttk, filedialog, messagebox, path="", t=0.0, start=None, end=None):
        self.tk, self.ttk, self.fd = tk, ttk, filedialog
        self.parent = parent

        class _MB:
            """A messagebox minden hívását a panel ablakához köti (parent), hogy ne kerüljön az ablak mögé."""
            def __getattr__(_s, name):
                fn = getattr(messagebox, name)

                def call(*a, **kw):
                    try:
                        kw.setdefault("parent", parent.winfo_toplevel())
                    except Exception:       # noqa
                        pass
                    return fn(*a, **kw)
                return call
        self.mb = _MB()
        self.cfg = load_config()
        self.ff = None
        self.q = queue.Queue()
        self.cancel = CancelFlag()
        self.busy = False
        self._imgs = []
        self._probe = None
        self._filled_src = None      # annak a forrásnak az útvonala, amelynek adataival a mezőket kitöltöttük
        self._src_after = None
        self._wave_img = None
        self._proc = None
        self.fx = {}            # (forrás, kezdet, vég) -> {"vf": szűrőlánc, "state": beállítások, "orig": (forrás, kezdet, vég)}  (a Képeffektek ablakból)
        self.fx_reopen = {}     # EREDETI (forrás, kezdet, vég) kulcs -> {"state": ...}: a VapourSynth-es szakasz forrása a renderelt fájl,
                                # de az újranyitáshoz (Szerkesztő / Átalakítás) az eredeti beállítások kellenek
        self._fx_win = None

        def V(value=""):
            return tk.StringVar(master=parent, value=value)
        self.v_enabled = tk.BooleanVar(master=parent, value=self.cfg["enabled"])
        self.v_ffmpeg, self.v_ffprobe, self.v_ffplay = (V(value=self.cfg[k]) for k in ("ffmpeg", "ffprobe", "ffplay"))
        self.v_src = V(value=path or "")
        self.v_t = V(value=fmt_time(t) if t else "0:00:00.000")
        self.v_before, self.v_after, self.v_step = V(value="2"), V(value="2"), V(value="0.5")
        self.v_volume = V(value="100")
        self.v_loop = tk.BooleanVar(master=parent, value=False)
        self.v_status = V(value="")
        self.v_prog = tk.DoubleVar(master=parent, value=0.0)
        self.v_start = V(value="" if start is None else fmt_time(start))
        self.v_end = V(value="" if end is None else fmt_time(end))
        self.v_qmode = V(value="join")      # a lista több eleménél: "join" = egy fájlba fűzve, "sep" = külön fájlok (_001, _002…)
        self.q_suffix = "_cut"              # a javasolt fájlnév vége (a Szerkesztő mentés-gombjai állítják: "_cut" / "_without")
        self.o = {k: V(value="") for k in ("out", "preset", "crf", "vbitrate", "scale", "fps", "pix_fmt", "abitrate",
                                           "achannels", "arate", "volume", "vf", "af", "extra", "container", "gop")}
        self.o["vcodec"], self.o["acodec"] = V(value="copy"), V(value="copy")
        self.o["hwaccel"] = V(value="-")
        self.b = {k: tk.BooleanVar(master=parent, value=d) for k, d in (("accurate", False), ("deint", False), ("faststart", True),
                                                           ("avoid_neg", True), ("overwrite", False))}
        self.v_cmd = V(value="")
        self.v_preset = V(value=preset_label(list(PRESETS)[0]))
        self.v_ext = V(value="")        # a választott kiterjesztés a konténer mellett
        self._encV = {}                  # kódolónév -> az FFmpeg saját leírása (videó)
        self._encA = {}                  # u., csak hangra
        self._v_was = ""                 # a Videó kodek, mielőtt a konténer kikapcsolta
        self._build_enc = False          # a lista az FFmpeg saját -encoders kimenetéből jön-e
        self._codec_last = {}            # a legördülő menő utolsó valódi kódolója (/fajta)
        self._build()
        self._apply_enabled()
        self.parent.after(150, self._poll)
        self._autoload()
        # a forrásfájl kiválasztásakor (Szerkesztő, tallózás, Átalakításra küldés) a Videó / Hang mezők a fájl
        # saját adataival kitöltődnek; utána kézzel szabadon módosíthatók
        self.v_src.trace_add("write", self._src_changed)
        if path:
            self.parent.after(700, lambda: self.autofill_source(self.v_src.get()))
        # a Beállítás (ffmpeg / ffprobe / ffplay útvonalai) csak akkor ugrik be, ha a modul
        # ki van kapcsolva vagy valamelyik program útvonala hiányzik; egyébként a Szerkesztő
        # jön, ha a parancssorból / a vágóból fájlt kaptunk
        if setup_incomplete(self.cfg):
            self.nb.select(self.t_set)
        elif path:
            self.nb.select(self.t_edit)
        # induláskor a tárolt konténer-beállítás határozza meg a mezők állapotát (a konténer
        # választja ki a kiterjesztést, és tilthatja le a Videó részt)
        self._apply_container(quiet=True)

    # ---- felépítés ----
    def _row(self, parent, label, var, browse=None, width=44):
        ttk = self.ttk
        r = ttk.Frame(parent)
        r.pack(fill="x", pady=1)
        ttk.Label(r, text=label, width=14).pack(side="left")
        ttk.Entry(r, textvariable=var, width=width).pack(side="left", fill="x", expand=True)
        if browse:
            ttk.Button(r, text="…", width=3, command=browse).pack(side="left", padx=2)
        return r

    def _build(self):
        tk, ttk = self.tk, self.ttk
        self.nb = ttk.Notebook(self.parent)
        self.nb.pack(fill="both", expand=True, padx=6, pady=6)
        self.t_set, self.t_prev = (ttk.Frame(self.nb, padding=8) for _x in range(2))
        self.t_conv, self.t_conv_in = self._scroll_frame()
        self.t_edit = ttk.Frame(self.nb, padding=4)
        self.nb.add(self.t_edit, text=_("Szerkesztő", "Editor"))
        # az "Előnézet / vágási pont" fül nincs a füllistán (a Szerkesztő kiváltja); a t_prev keret csak
        # a háttérben marad, hogy a hozzá tartozó kód ne igényeljen módosítást
        self.nb.add(self.t_conv, text=_("Átalakítás / pontos vágás", "Convert / exact cut"))
        self.t_an = ttk.Frame(self.nb, padding=6)
        self.nb.add(self.t_an, text=_("Videó-elemző", "Video analyzer"))
        # a Beállítás (ffmpeg / ffprobe / ffplay helye) a lista végén marad, de innen is
        # bármikor átállítható: a fül nincs letiltva, csak éppen nem az első
        self.nb.add(self.t_set, text=_("Beállítás", "Setup"))
        self._build_setup()
        self._build_preview()
        self._build_convert()
        self._build_analyzer()
        self.editor = VideoEditor(self, self.t_edit)
        self.nb.bind("<<NotebookTabChanged>>", self._tab_changed)
        ttk.Label(self.parent, textvariable=self.v_status, padding=(8, 2)).pack(fill="x")

    def _scroll_frame(self):
        """Görgethető oldal a füllapon: függőlegesen ÉS vízszintesen. [hscroll-v5]
        A tartalom a természetes szélességén marad (nem szorul össze), így a jobb oldali gombok
        is elérhetők: ha az ablak szűkebb, alul vízszintes csúszka jelenik meg.
        Egérgörgő: függőlegesen; Shift + görgő: vízszintesen."""
        tk, ttk = self.tk, self.ttk
        outer = ttk.Frame(self.nb)
        cv = tk.Canvas(outer, highlightthickness=0, borderwidth=0)
        sby = ttk.Scrollbar(outer, orient="vertical", command=cv.yview)
        sbx = ttk.Scrollbar(outer, orient="horizontal", command=cv.xview)
        inner = ttk.Frame(cv, padding=8)
        win = cv.create_window((0, 0), window=inner, anchor="nw")
        cv.configure(yscrollcommand=sby.set, xscrollcommand=sbx.set)
        # a vízszintes csúszkát a vászon ELŐTT kell becsomagolni, különben a vászon kitölti a helyét
        sby.pack(side="right", fill="y")
        sbx.pack(side="bottom", fill="x")
        cv.pack(side="left", fill="both", expand=True)

        def sync(_e=None):
            # a belső keret legalább a saját kért méretét kapja; ha az ablak szélesebb, kitölti
            cw = max(cv.winfo_width(), inner.winfo_reqwidth())
            ch = max(cv.winfo_height(), inner.winfo_reqheight())
            cv.itemconfigure(win, width=cw)
            cv.configure(scrollregion=(0, 0, cw, ch))

        inner.bind("<Configure>", sync)
        cv.bind("<Configure>", sync)

        def in_page(w):
            while w is not None:
                if w is outer:
                    return True
                w = getattr(w, "master", None)
            return False

        def wheel(e):
            try:
                w = cv.winfo_containing(e.x_root, e.y_root)
            except (tk.TclError, KeyError):
                return
            if w is None or not in_page(w) or isinstance(w, (tk.Text, ttk.Treeview)):
                return                       # ezek saját görgetést kapnak
            num = getattr(e, "num", None)
            if num == 4:
                d = -1
            elif num == 5:
                d = 1
            else:
                d = -1 if e.delta > 0 else 1
            if e.state & 1:                  # Shift: vízszintes görgetés
                cv.xview_scroll(d, "units")
            else:
                cv.yview_scroll(d, "units")

        outer.bind_all("<MouseWheel>", wheel, add="+")
        outer.bind_all("<Button-4>", wheel, add="+")
        outer.bind_all("<Button-5>", wheel, add="+")
        return outer, inner

    def _build_analyzer(self):
        """A Videó-elemző a FFmpeg panel „Videó-elemző” füle (Átalakítás után, Beállítás előtt).
        Az elemző maga az lvt_analyzer.py fájlban van; ha az hiányzik, a fül csak figyelmeztet."""
        from tkinter import filedialog as _lva_fd, messagebox as _lva_mb
        ttk, f = self.ttk, self.t_an
        la, err = load_analyzer()
        if la is None:
            ttk.Label(f, text=_("A Videó-elemző nem tölthető be (lvt_analyzer.py hiányzik vagy hibás): ",
                                "The video analyzer could not be loaded (lvt_analyzer.py missing or broken): ") + err,
                      wraplength=760, justify="left").pack(fill="x", pady=8)
            return
        host = _AnalyzerHost(self)
        if getattr(la, "_CORE", None) is None:
            la.install(host)
        tab = la.AnalyzerTab(host, self.tk, ttk, _lva_fd, _lva_mb)
        tab.core = host                      # a panel állapotát használja (fájl, ffmpeg / ffprobe, nyelv)
        tab.build(f)
        self._analyzer = tab

    def show_help_convert(self):
        """„H” gomb: az Átalakítás oldal rövid súgója (nem modális ablak)."""
        win = self.tk.Toplevel(self.nb.winfo_toplevel())
        win.title(_("Súgó – Átalakítás / pontos vágás", "Help – Convert / exact cut"))
        win.geometry("660x470")
        t = self.tk.Text(win, wrap="word", padx=12, pady=10)
        t.pack(fill="both", expand=True)
        t.insert("1.0", "\n".join(_(HELP_CONVERT_HU, HELP_CONVERT_EN)))
        t.configure(state="disabled")
        win.bind("<Escape>", lambda _e: win.destroy())

    def _build_setup(self):
        ttk, f = self.ttk, self.t_set
        ttk.Label(f, wraplength=640, justify="left", text=_(
            "Ez a modul opcionális. Az FFmpeg-et NEM tartalmazza: add meg a saját gépeden telepített ffmpeg "
            "(és ha van: ffprobe, ffplay) elérési útját. Amíg nincs bekapcsolva, semmilyen külső programot nem indít. "
            "Az FFmpeg külön programként fut, a saját licence (LGPL vagy GPL) rá vonatkozik.",
            "This module is optional and does NOT include FFmpeg. Set the path of your own installed ffmpeg "
            "(and ffprobe/ffplay). Until enabled it starts no external program. FFmpeg runs as a separate program "
            "under its own license (LGPL or GPL).")).pack(fill="x", pady=(0, 8))
        self._row(f, "ffmpeg", self.v_ffmpeg, lambda: self._browse(self.v_ffmpeg))
        self._row(f, "ffprobe", self.v_ffprobe, lambda: self._browse(self.v_ffprobe))
        self._row(f, "ffplay", self.v_ffplay, lambda: self._browse(self.v_ffplay))
        b = ttk.Frame(f)
        b.pack(fill="x", pady=6)
        ttk.Button(b, text=_("Keresés a mappában / PATH-on", "Find in folder / PATH"), command=self.find).pack(side="left")
        ttk.Button(b, text=_("Ellenőrzés és mentés", "Test and save"), command=self.test).pack(side="left", padx=6)
        ttk.Checkbutton(f, text=_("Modul bekapcsolva", "Module enabled"), variable=self.v_enabled,
                        command=self._toggle_enabled).pack(anchor="w")
        self.txt_ver = self.tk.Text(f, height=9, wrap="word")
        self.txt_ver.pack(fill="both", expand=True, pady=6)
        ttk.Button(f, text=_("A licenc-figyelmeztetés elolvasása újra", "Read the license notice again"),
                   command=self.show_notice).pack(anchor="w", pady=(0, 4))

    def _build_preview(self):
        tk, ttk, f = self.tk, self.ttk, self.t_prev
        self._row(f, _("Fájl", "File"), self.v_src, self._browse_src)
        r = ttk.Frame(f)
        r.pack(fill="x", pady=3)
        ttk.Label(r, text=_("Vágási pont", "Cut point"), width=14).pack(side="left")
        ttk.Entry(r, textvariable=self.v_t, width=14).pack(side="left")
        for txt, d in (("-1s", -1), ("-0.1", -0.1), ("-1f", "f-"), ("+1f", "f+"), ("+0.1", 0.1), ("+1s", 1)):
            ttk.Button(r, text=txt, width=5, command=lambda d=d: self._nudge(d)).pack(side="left", padx=1)
        r2 = ttk.Frame(f)
        r2.pack(fill="x", pady=3)
        ttk.Label(r2, text=_("Előtte / utána (mp)", "Before / after (s)"), width=18).pack(side="left")
        ttk.Entry(r2, textvariable=self.v_before, width=5).pack(side="left")
        ttk.Entry(r2, textvariable=self.v_after, width=5).pack(side="left", padx=4)
        ttk.Label(r2, text=_("Hangerő %", "Volume %")).pack(side="left", padx=(10, 2))
        ttk.Entry(r2, textvariable=self.v_volume, width=5).pack(side="left")
        ttk.Checkbutton(r2, text=_("Ismétlés", "Loop"), variable=self.v_loop).pack(side="left", padx=8)
        r3 = ttk.Frame(f)
        r3.pack(fill="x", pady=3)
        ttk.Button(r3, text=_("▶ Lejátszás a pont körül", "▶ Play around point"), command=lambda: self.play(False)).pack(side="left")
        ttk.Button(r3, text=_("♪ Csak hang", "♪ Audio only"), command=lambda: self.play(True)).pack(side="left", padx=4)
        ttk.Button(r3, text=_("■ Leállít", "■ Stop"), command=self.stop_play).pack(side="left")
        r4 = ttk.Frame(f)
        r4.pack(fill="x", pady=3)
        ttk.Label(r4, text=_("Képsor lépése (mp)", "Frame step (s)"), width=18).pack(side="left")
        ttk.Entry(r4, textvariable=self.v_step, width=7).pack(side="left")
        ttk.Button(r4, text=_("1 képkocka", "1 frame"), command=self._step_frame).pack(side="left", padx=4)
        ttk.Button(r4, text=_("Képek a pont körül", "Frames around point"), command=self.show_frames).pack(side="left", padx=4)
        ttk.Button(r4, text=_("Hanghullám", "Waveform"), command=self.show_wave).pack(side="left")
        self.strip = ttk.Frame(f)
        self.strip.pack(fill="x", pady=4)
        self.wave = tk.Canvas(f, height=130, background="#111", highlightthickness=0)
        self.wave.pack(fill="x", pady=4)

    def _build_convert(self):
        tk, ttk, f = self.tk, self.ttk, self.t_conv_in
        r = ttk.Frame(f)
        r.pack(fill="x")
        ttk.Button(r, text=_("Fájl hozzáadása…", "Add file…"), command=self.q_add_files).pack(side="left", padx=(0, 4))
        ttk.Separator(r, orient="vertical").pack(side="left", fill="y", padx=(0, 8))
        ttk.Label(r, text=_("Beállítás-minta", "Preset"), width=14).pack(side="left")
        self.cb_preset = ttk.Combobox(r, textvariable=self.v_preset, values=self._preset_names(),
                                      state="readonly", width=48)
        self.cb_preset.pack(side="left")
        self.cb_preset.bind("<<ComboboxSelected>>", lambda e: self.apply_preset())
        ttk.Button(r, text=_("Mentés mintaként…", "Save as preset…"), command=self.save_preset).pack(side="left", padx=(6, 2))
        ttk.Button(r, text=_("Minta törlése", "Delete preset"), command=self.delete_preset).pack(side="left")
        ttk.Button(r, text="H", width=3, command=self.show_help_convert).pack(side="right")
        self.queue = []         # (forrás, kezdet, vég) - a szerkesztőből átvitt szakaszok, egymás után fűzve
        qf = ttk.LabelFrame(f, text=_("Átalakítandó szakaszok (a felsorolt sorrendben dolgozza fel)",
                                      "Segments to convert (processed in the listed order)"), padding=4)
        qf.pack(fill="x", pady=3)
        self.qtree = ttk.Treeview(qf, columns=("n", "f", "s", "e", "l", "x"), show="headings", height=4, selectmode="extended")
        for c, t, w in (("n", "#", 32), ("f", _("Fájl", "File"), 300), ("s", _("Kezdet", "Start"), 100),
                        ("e", _("Vég", "End"), 100), ("l", _("Hossz", "Length"), 90), ("x", _("Effekt", "FX"), 70)):
            self.qtree.heading(c, text=t)
            self.qtree.column(c, width=w, anchor="w" if c == "f" else "center", stretch=(c == "f"))
        self.qtree.pack(side="left", fill="both", expand=True)
        self.qtree.bind("<Control-a>", self._q_select_all)
        self.qtree.bind("<Control-A>", self._q_select_all)
        self.qtree.bind("<Delete>", self._q_del_key)
        self.qtree.bind("<BackSpace>", self._q_del_key)
        self.qtree.bind("<Escape>", self._q_clear_sel)
        self.qtree.bind("<Control-o>", self._q_open)
        self.qtree.bind("<Control-O>", self._q_open)
        qb = ttk.Frame(qf)
        qb.pack(side="left", padx=6, fill="y")
        for txt, fn in ((_("▲ Fel", "▲ Up"), lambda: self.q_move(-1)), (_("▼ Le", "▼ Down"), lambda: self.q_move(1)),
                        (_("Törlés", "Remove"), self.q_del), (_("Lista ürítése", "Clear list"), self.q_clear),
                        (_("Képeffektek…", "Image effects…"), self.q_effects)):
            ttk.Button(qb, text=txt, command=fn, width=14).pack(fill="x", pady=1)
        rq = ttk.Frame(f)
        rq.pack(fill="x", pady=(2, 0))
        ttk.Label(rq, text=_("Több elemnél", "With several items"), width=14).pack(side="left")
        ttk.Radiobutton(rq, text=_("egy fájlba fűzve", "joined into one file"), variable=self.v_qmode,
                        value="join").pack(side="left")
        ttk.Radiobutton(rq, text=_("külön fájlokba (cél_001, cél_002…)", "separate files (target_001, target_002…)"),
                        variable=self.v_qmode, value="sep").pack(side="left", padx=10)
        rt = ttk.Frame(f)
        rt.pack(fill="x", pady=2)
        ttk.Label(rt, text=_("Kezdet / vég", "Start / end"), width=14).pack(side="left")
        ttk.Entry(rt, textvariable=self.v_start, width=14).pack(side="left")
        ttk.Entry(rt, textvariable=self.v_end, width=14).pack(side="left", padx=4)
        ttk.Checkbutton(rt, text=_("kocka-pontos", "frame-accurate"), variable=self.b["accurate"]).pack(side="left", padx=6)
        # konténer + kiterjesztés: a konténer dönti el, mi áll rendelkezésre. A kiterjesztésből
        # annyi jelenik meg, ahányat a konténer bír (Matroska: .mkv / .mka), és a Videó állapota
        # javasol meg egyet. A sor a „Kezdet / vég” és a Videó rész között van (nem a Kimenet blokkban).
        rc = ttk.Frame(f)
        rc.pack(fill="x", pady=2)
        ttk.Label(rc, text=_("Konténer", "Container"), width=14).pack(side="left")
        self.cb_c = ttk.Combobox(rc, textvariable=self.o["container"], values=[""], width=24)
        self.cb_c.pack(side="left")
        self.cb_c.bind("<<ComboboxSelected>>", self._apply_container)
        self.cb_c.bind("<KeyRelease>", self._container_typed)
        ttk.Label(rc, text=_("Kiterjesztés", "Extension")).pack(side="left", padx=(10, 2))
        self.cb_ext = ttk.Combobox(rc, textvariable=self.v_ext, values=[""], width=8)
        self.cb_ext.bind("<KeyRelease>", lambda _e: getattr(self, "_upd_ext_in_out", lambda: None)())
        self.cb_ext.pack(side="left")
        self.cb_ext.bind("<<ComboboxSelected>>", self._ext_chosen)
        self.lbl_cont = ttk.Label(rc, text="", foreground="#00695c")
        self.lbl_cont.pack(side="left", padx=8)
        g = ttk.LabelFrame(f, text="Video", padding=4)
        g.pack(fill="x", pady=3)
        self.cb_v = self._combo(g, "codec", self.o["vcodec"], ["copy", "none"], 0, 0, 46)
        self.frm_v = g          # a Videó-keret: csak-hang konténernél ezt kapcsoljuk inaktívra
        self.cb_v.bind("<<ComboboxSelected>>", lambda _e: self._codec_picked("v"))
        self.cb_p = self._combo(g, "preset", self.o["preset"], ["", "ultrafast", "veryfast", "fast", "medium", "slow", "slower", "veryslow"], 0, 2, 11)
        self._entry(g, "CRF/CQ", self.o["crf"], 0, 4, 9)
        self._entry(g, "bitrate", self.o["vbitrate"], 0, 6, 9)
        self._entry(g, _("méret", "scale"), self.o["scale"], 1, 0, 14)
        self._entry(g, "fps", self.o["fps"], 1, 2, 7)
        self._entry(g, "pix_fmt", self.o["pix_fmt"], 1, 4, 9)
        self.cb_hw = self._combo(g, "hwaccel", self.o["hwaccel"], ["-"], 1, 6, 9)
        self._entry(g, _("GOP (kocka)", "GOP (frames)"), self.o["gop"], 1, 8, 6)
        self._entry(g, "-vf", self.o["vf"], 0, 8, 30, span=3)
        ttk.Checkbutton(g, text=_("Deinterlace (yadif)", "Deinterlace (yadif)"), variable=self.b["deint"]).grid(row=1, column=10, columnspan=2, sticky="w")
        self.lbl_vdesc = ttk.Label(g, text="", foreground="#00695c")
        self.lbl_vdesc.grid(row=2, column=0, columnspan=12, sticky="w", padx=2, pady=(2, 0))
        a = ttk.LabelFrame(f, text=_("Hang", "Audio"), padding=4)
        a.pack(fill="x", pady=3)
        self.cb_a = self._combo(a, "codec", self.o["acodec"], ["copy", "none"], 0, 0, 46)
        self.frm_a = a          # a Hang-keret neve (a konténer ezt nem kapcsolja ki)
        self.cb_a.bind("<<ComboboxSelected>>", lambda _e: self._codec_picked("a"))
        self._entry(a, "bitrate", self.o["abitrate"], 0, 2, 8)
        self._entry(a, _("csatorna", "channels"), self.o["achannels"], 0, 4, 4)
        self._entry(a, "Hz", self.o["arate"], 0, 6, 7)
        self._entry(a, "dB", self.o["volume"], 1, 0, 6)
        self._entry(a, "-af", self.o["af"], 1, 2, 30, span=3)
        self.lbl_adesc = ttk.Label(a, text="", foreground="#00695c")
        self.lbl_adesc.grid(row=2, column=0, columnspan=8, sticky="w", padx=2, pady=(2, 0))
        for _v in (self.o["vcodec"], self.o["acodec"]):
            try:
                _v.trace_add("write", self._upd_codec_desc)     # profil / előbeállítás is frissíti
                _v.trace_add("write", self._upd_codec_fields)   # copy / none: a kódolási mezők inaktívak
            except Exception:
                pass
        o = ttk.LabelFrame(f, text=_("Kimenet", "Output"), padding=4)
        o.pack(fill="x", pady=3)
        self._row(o, _("Cél fájl", "Output file"), self.o["out"], self._browse_out)
        self._row(o, _("Extra paraméter", "Extra args"), self.o["extra"])
        r5 = ttk.Frame(o)
        r5.pack(fill="x")
        ttk.Checkbutton(r5, text="faststart (MP4)", variable=self.b["faststart"]).pack(side="left")
        ttk.Checkbutton(r5, text=_("másoláskor negatív idő elkerülése", "avoid negative ts (copy)"), variable=self.b["avoid_neg"]).pack(side="left", padx=8)
        ttk.Checkbutton(r5, text=_("felülírás", "overwrite"), variable=self.b["overwrite"]).pack(side="left")
        r6 = ttk.Frame(f)
        r6.pack(fill="x", pady=4)
        ttk.Button(r6, text=_("Parancs megtekintése", "Show command"), command=self.show_cmd).pack(side="left")
        self.btn_run = ttk.Button(r6, text=_("Indítás", "Start"), command=self.run)
        self.btn_run.pack(side="left", padx=6)
        ttk.Button(r6, text=_("Megszakít", "Cancel"), command=self.request_cancel).pack(side="left")
        ttk.Progressbar(f, variable=self.v_prog, maximum=1.0).pack(fill="x", pady=(5, 5))
        self.ent_cmd = ttk.Entry(f, textvariable=self.v_cmd, state="readonly")

        def _cmd_vis(*_a):
            # a parancssor csak akkor látszik, ha van tartalma; üresen nincs felesleges sáv
            on = bool((self.v_cmd.get() or "").strip())
            if on and not self.ent_cmd.winfo_manager():
                self.ent_cmd.pack(fill="x", before=self.txt_log)
            elif not on and self.ent_cmd.winfo_manager():
                self.ent_cmd.pack_forget()
        self.v_cmd.trace_add("write", _cmd_vis)
        self.txt_log = tk.Text(f, height=6, wrap="none")
        self.txt_log.pack(fill="both", expand=True, pady=(4, 4))

    def _combo(self, parent, label, var, values, r, c, w):
        self.ttk.Label(parent, text=label).grid(row=r, column=c, sticky="e", padx=2)
        cb = self.ttk.Combobox(parent, textvariable=var, values=values, width=w)
        cb.grid(row=r, column=c + 1, sticky="w", padx=2, pady=1)
        return cb

    def _entry(self, parent, label, var, r, c, w, span=1):
        self.ttk.Label(parent, text=label).grid(row=r, column=c, sticky="e", padx=2)
        self.ttk.Entry(parent, textvariable=var, width=w).grid(row=r, column=c + 1, columnspan=span, sticky="w", padx=2, pady=1)

    def _tab_changed(self, _e=None):
        ed = getattr(self, "editor", None)
        if ed is None:
            return
        if self.nb.select() == str(self.t_edit):
            ed.on_show()
        else:
            ed.pause(quiet=True)

    def request_cancel(self):
        """„Megszakít” gomb. Futó kódolásnál megkérdezi, hogy az addig kódolt rész (hanggal együtt) megmaradjon-e."""
        c = self.cancel
        if not self.busy or c.is_set():
            c.set()
            return
        if c.can_keep and not c.has_final:
            r = self.mb.askyesnocancel("FFmpeg", _(
                "Megszakítod a kódolást.\n\nElmentsem az eddig elkészült részt (a hanggal együtt)?\n\n"
                "Igen = mentés   |   Nem = eldobás   |   Mégse = folytatás",
                "Stopping the encode.\n\nSave the part encoded so far (with the audio)?\n\n"
                "Yes = save   |   No = discard   |   Cancel = keep encoding"))
            if r is None:
                return
            if not self.busy:
                return              # közben befejeződött
            c.keep = bool(r)
        c.set()

    def close(self):
        self.cancel.set()
        self.stop_play()
        try:
            self.editor._pk_cancel()
        except Exception:       # noqa
            pass
        try:
            if self._fx_win is not None:
                self._fx_win.close()
        except Exception:       # noqa
            pass
        try:
            self.editor.shutdown()
        except Exception:       # noqa
            pass

    def _autoload(self):
        """Ha a modul be van kapcsolva, az FFmpeg saját kódoló- és konténerlistáját betölti a legördülő menükbe."""
        p = self.v_ffmpeg.get().strip()
        if not (self.v_enabled.get() and p and os.path.isfile(p)):
            return
        ff = FFmpeg(p, self.v_ffprobe.get().strip(), self.v_ffplay.get().strip())

        def work():
            ff.encoders()
            try:
                ff.muxers()
            except FFError:
                pass
            try:
                hw = ff.hwaccels()
            except FFError:
                hw = []
            return hw

        self._bg(work, lambda hw, err: None if err else self._fill_encoders(ff, hw))

    # ---- általános ----
    def _status(self, s):
        self.v_status.set(s)

    def _browse(self, var):
        p = self.fd.askopenfilename(parent=self.parent, title=_("Program kiválasztása", "Select program"),
                                    filetypes=[(_("Programok", "Programs"), "*.exe"), ("*", "*.*")])
        if p:
            p = os.path.normpath(p)
            var.set(p)
            self.parent.update_idletasks()
            if var is self.v_ffmpeg:        # a mellette lévő ffprobe / ffplay automatikus kitöltése
                r = FFmpeg.locate(p)
                if not self.v_ffprobe.get().strip():
                    self.v_ffprobe.set(r["ffprobe"])
                if not self.v_ffplay.get().strip():
                    self.v_ffplay.set(r["ffplay"])

    def _browse_src(self):
        p = self.fd.askopenfilename(parent=self.parent, filetypes=[("Video", "*.mts *.m2ts *.ts *.mkv *.webm *.mp4 *.m4v *.mov *.avi"), ("*", "*.*")])
        if p:
            self._filled_src = None         # ugyanazt a fájlt újra kiválasztva is frissüljenek a mezők
            self.v_src.set(p)
            self._probe = None
            self._src_changed()

    # ---- a forrásfájl adatainak automatikus kitöltése (Videó / Hang mezők) ----
    def _src_changed(self, *_a):
        try:
            if self._src_after is not None:
                self.parent.after_cancel(self._src_after)
            self._src_after = self.parent.after(400, lambda: self.autofill_source(self.v_src.get()))
        except Exception:       # noqa
            pass

    def autofill_source(self, path, force=False, local=False):
        """A fájl ffprobe-adataival kitölti az Átalakítás fül Videó és Hang mezőit (kodek, bitráta, méret, fps, pix_fmt,
        csatorna, mintavétel) és a konténert. Csendben nem tesz semmit, ha a modul ki van kapcsolva vagy nincs ffprobe."""
        self._src_after = None
        path = (path or "").strip()
        if not path or not os.path.isfile(path) or self.busy:
            return
        if not force and os.path.normcase(path) == self._filled_src:
            return
        p = self.v_ffmpeg.get().strip()
        if not (self.v_enabled.get() and p and os.path.isfile(p)):
            return
        ff = FFmpeg(p, self.v_ffprobe.get().strip(), self.v_ffplay.get().strip())
        if not ff.ffprobe:
            self._status(_("A mezők automatikus kitöltéséhez az ffprobe kell (Beállítás fül).",
                           "Filling the fields automatically needs ffprobe (Setup tab)."))
            return

        def work():
            info = ff.probe(path)
            try:
                enc = ff.encoders()
            except FFError:
                enc = {"V": [], "A": []}
            try:
                ff.muxers()
            except FFError:
                pass
            return info, enc

        def done(res, err):
            if err or not res:
                self._status(_("A fájl adatai nem olvashatók: ", "Cannot read the file's data: ") + str(err))
                return
            if not local and os.path.normcase(self.v_src.get().strip()) != os.path.normcase(path):
                return              # közben másik fájlt választottak
            info, enc = res
            self._probe = info
            self._apply_source_settings(settings_from_probe(info, [n for n, _d in enc["V"]],
                                                            [n for n, _d in enc["A"]], path))
            self._filled_src = os.path.normcase(path)
            self._status(_("A(z) %s adataival kitöltve a Videó / Hang rész (kézzel módosíthatod).",
                           "Video / Audio fields filled from %s (you can change them).") % os.path.basename(path))

        self._bg(work, done)

    def _apply_source_settings(self, res):
        """A settings_from_probe eredményét beírja a mezőkbe; a konténer a kiterjesztést és a kodeklistákat is igazítja."""
        cont = res.get("container", "")
        # ismeretlen konténer: üres (ne maradjon az utoljára ismert); kézzel a listáról választható
        self.o["container"].set(cont if (cont and self._cont_known(cont)) else "")
        self._apply_container(quiet=True)
        for k, val in res.items():
            if k != "container" and k in self.o:
                self.o[k].set(val)
        try:
            self.v_preset.set(_("— a forrás adatai —", "— source settings —"))
        except Exception:       # noqa
            pass
        self._apply_container(quiet=True)
        src_ext = os.path.splitext(self.v_src.get().strip())[1].lower()      # lehetőleg a forrás kiterjesztése maradjon
        try:
            if src_ext and src_ext in self._ext_list() and self.v_ext.get().strip().lower() != src_ext:
                self.v_ext.set(src_ext)
                self._upd_ext_in_out()
        except Exception:       # noqa
            pass

    def _cont_known(self, cont):
        # csak olyan konténert állítunk be, amelyet ez az FFmpeg-build ki is tud írni (ha a lista ismert)
        mux = getattr(self.ff, "_mux", None) if self.ff is not None else None
        return not mux or cont in {n for n, _d in mux}

    def _default_ext(self):
        # a cél fájl kiterjesztése a kiválasztott kiterjesztést követi; ha nincs választás, a
        # forrásfájl kiterjesztése a kapaszkodó (így a kézi beírás és a profil nem sérül)
        e = (self.v_ext.get().strip() if hasattr(self, "v_ext") else "")
        if e:
            return e if e.startswith(".") else "." + e
        return os.path.splitext(self.v_src.get().strip())[1] or ".mkv"

    def _browse_out(self):
        p = self.fd.asksaveasfilename(parent=self.parent, defaultextension=self._default_ext())
        if p:
            self.o["out"].set(p)

    def _bg(self, work, done):
        def run():
            try:
                self.q.put((done, work(), None))
            except BaseException as e:      # noqa
                self.q.put((done, None, e))
        threading.Thread(target=run, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, res, err = self.q.get_nowait()
                if callable(kind):
                    kind(res, err)
        except queue.Empty:
            pass
        try:
            self.parent.after(150, self._poll)
        except Exception:       # az ablak már bezárult
            pass

    def show_notice(self):
        """A licenc-figyelmeztetés újra megjelenítése: a „license_ok” jelző törlődik, így a
        következő megnyitáskor ismét előjön – hacsak itt újra el nem fogadják."""
        revoke_license()            # a jelzőfájl + a „license_ok” kulcs is törlődik
        self.cfg["license_ok"] = False
        if show_license_gate(self.parent.winfo_toplevel(), self.tk, self.ttk):
            accept_license()        # elfogadva: a jelzőfájl vissza a program mappájába
            self.cfg["license_ok"] = True
            self._status(_("A figyelmeztetést elolvastad: megnyitáskor többé nem jelenik meg.",
                           "Notice read: it will no longer appear when opening."))
        else:
            self._status(_("Nem fogadtad el: a figyelmeztetés a következő megnyitáskor újra előjön.",
                           "Not accepted: the notice will appear again the next time you open this."))

    def _toggle_enabled(self):
        if self.v_enabled.get() and not self.cfg.get("license_ok"):
            ok = self.mb.askyesno("FFmpeg", _(
                "Az FFmpeg külön program, a saját licence (LGPL vagy GPL, a buildtől függően) vonatkozik rá, "
                "nem erre a modulra. A modul csak a te gépeden telepített FFmpeg-et indítja el; nem tartalmazza "
                "és nem tölti le.\n\nElfogadod ezt, és bekapcsolod a modult?",
                "FFmpeg is a separate program under its own license (LGPL or GPL depending on the build), not "
                "this module's. The module only starts the FFmpeg installed on your machine; it does not include "
                "or download it.\n\nDo you accept this and enable the module?"), parent=self.parent)
            if not ok:
                self.v_enabled.set(False)
            else:
                self.cfg["license_ok"] = True
        self._apply_enabled()
        if self.v_enabled.get():
            self._autoload()

    def _apply_enabled(self):
        on = bool(self.v_enabled.get())
        self.cfg["enabled"] = on
        save_config(self.cfg)
        if not on:
            self._status(_("A modul ki van kapcsolva – külső program nem indul.", "Module is off - no external program is started."))
        else:
            self._status("")

    def _need(self):
        """FFmpeg objektum, ha a modul be van kapcsolva és az ffmpeg megvan; különben None + üzenet."""
        if not self.v_enabled.get():
            self.mb.showinfo("FFmpeg", _("Kapcsold be a modult a Beállítás fülön.", "Enable the module on the Setup tab."))
            return None
        p = self.v_ffmpeg.get().strip()
        if not p or not os.path.isfile(p):
            self.mb.showwarning("FFmpeg", _("Az ffmpeg elérési útja hiányzik vagy hibás.", "ffmpeg path is missing or wrong."))
            return None
        self.ff = FFmpeg(p, self.v_ffprobe.get().strip(), self.v_ffplay.get().strip())
        return self.ff

    # ---- beállítás ----
    def find(self):
        hint = self.v_ffmpeg.get().strip()
        r = FFmpeg.locate(hint)
        self.v_ffmpeg.set(r["ffmpeg"])
        self.v_ffprobe.set(r["ffprobe"])
        self.v_ffplay.set(r["ffplay"])
        self._status(_("Keresés kész.", "Search done."))

    def test(self):
        p = self.v_ffmpeg.get().strip()
        if not p or not os.path.isfile(p):
            self.mb.showwarning("FFmpeg", _("Az ffmpeg elérési útja hiányzik vagy hibás.", "ffmpeg path is missing or wrong."))
            return
        ff = FFmpeg(p, self.v_ffprobe.get().strip(), self.v_ffplay.get().strip())

        def work():
            info = ff.version_info()
            ff.encoders()
            try:
                ff.muxers()
            except FFError:
                pass
            info["hw"] = ff.hwaccels()
            return info

        def done(info, err):
            self.txt_ver.delete("1.0", "end")
            if err:
                self.txt_ver.insert("end", _("HIBA: %s", "ERROR: %s") % err)
                return
            enc = ff._enc
            self.txt_ver.insert("end", _("%s\nLicenc (a megadott build): %s\n\nVideó kódolók: %d, hang kódolók: %d\n"
                                         "Konténerek (kiírható): %d\nHW gyorsítás: %s\n\n"
                                         "ffprobe: %s\nffplay: %s\n\n%s",
                                         "%s\nLicense (the given build): %s\n\nVideo encoders: %d, audio encoders: %d\n"
                                         "Containers (writable): %d\nHW acceleration: %s\n\n"
                                         "ffprobe: %s\nffplay: %s\n\n%s") % (
                                    info["version"], info["license"], len(enc["V"]), len(enc["A"]),
                                    len(ff._mux or []),
                                    ", ".join(info["hw"]) or "-", ff.ffprobe or _("nincs", "none"), ff.ffplay or _("nincs", "none"),
                                    info["configuration"][:600]))
            self.cfg.update(ffmpeg=p, ffprobe=ff.ffprobe, ffplay=ff.ffplay, enabled=bool(self.v_enabled.get()))
            save_config(self.cfg)
            self._fill_encoders(ff, info["hw"])
            self._status(_("FFmpeg rendben, beállítás elmentve.", "FFmpeg OK, settings saved."))
            if self.v_enabled.get() and not self.editor.info and self.nb.select() == str(self.t_edit):
                self.editor.on_show()

        self._bg(work, done)

    def _fill_encoders(self, ff, hw):
        # a kódolólista az épp beállított FFmpeg buildből jön: régi és új build is megfelel; ha a
        # build nem futtatható, a beépített lista marad, és a felület akkor sem törik el
        enc = getattr(ff, "_enc", None) or {"V": [], "A": []}
        self._encV = dict((n, (d or "").strip()) for n, d in enc["V"])
        self._encA = dict((n, (d or "").strip()) for n, d in enc["A"])
        self._build_enc = bool(enc["V"] or enc["A"])
        if not self._encV:
            self._encV = dict((n, "") for n in FALLBACK_V)
        if not self._encA:
            self._encA = dict((n, "") for n in FALLBACK_A)
        self.cb_hw["values"] = ["-"] + list(hw)
        self.cb_c["values"] = [""] + [n for n, _d in (getattr(ff, "_mux", None) or [])]
        self._apply_container(quiet=True)
        if not self._build_enc:
            self._status(_("Az FFmpeg kódolólistája nem olvasható: a beépített lista látszik, "
                           "ellenőrizd a nevet.",
                           "The FFmpeg encoder list could not be read: the built-in list is shown, "
                           "check the name."))
        else:
            self._status(_("Kódolók ebben az FFmpeg buildben: videó %d, hang %d – a lista a konténer "
                           "szerint szűr.",
                           "Encoders in this FFmpeg build: %d video, %d audio – the list is filtered "
                           "per container.") % (len(self._encV), len(self._encA)))

    # ---- előnézet (háttér-kód, a fül nincs a füllistán) ----
    def _cur(self):
        t = parse_time(self.v_t.get())
        src = self.v_src.get().strip()
        if t is None or not src or not os.path.isfile(src):
            self.mb.showwarning("FFmpeg", _("Adj meg érvényes fájlt és időt.", "Give a valid file and time."))
            return None
        return src, t

    def _fps(self):
        if self._probe:
            return FFmpeg.video_fps(self._probe)
        return 25.0

    def _step_frame(self):
        self.v_step.set("%.5f" % (1.0 / self._fps()))

    def _nudge(self, d):
        t = parse_time(self.v_t.get()) or 0.0
        if d == "f-":
            d = -1.0 / self._fps()
        elif d == "f+":
            d = 1.0 / self._fps()
        self.v_t.set(fmt_time(max(0.0, t + d)))

    def play(self, audio_only):
        c = self._cur()
        ff = self._need() if c else None
        if not ff:
            return
        src, t = c
        b = parse_time(self.v_before.get()) or 0.0
        a = parse_time(self.v_after.get()) or 0.0
        self.stop_play()
        try:
            vol = float(self.v_volume.get())
        except ValueError:
            vol = 100
        try:
            self._proc = ff.play(src, max(0.0, t - b), a + b, audio_only=audio_only, loop=bool(self.v_loop.get()), volume=vol)
            self._status(_("Lejátszás: %s – %s", "Playing: %s - %s") % (fmt_time(max(0.0, t - b)), fmt_time(t + a)))
        except FFError as e:
            self.mb.showwarning("FFmpeg", str(e))

    def stop_play(self):
        p = self._proc
        self._proc = None
        if p is not None and p.poll() is None:
            try:
                p.kill()
            except OSError:
                pass

    def show_frames(self):
        c = self._cur()
        ff = self._need() if c else None
        if not ff:
            return
        src, t = c
        try:
            step = max(0.001, float(self.v_step.get().replace(",", ".")))
        except ValueError:
            step = 0.5
        n = 4
        times = [max(0.0, t + i * step) for i in range(-n, n + 1)]

        def work():
            return [(tt, ff.frame_png(src, tt, 200)) for tt in times]

        def done(res, err):
            for w in self.strip.winfo_children():
                w.destroy()
            self._imgs = []
            if err:
                self._status(str(err))
                return
            for i, (tt, png) in enumerate(res):
                img = self.tk.PhotoImage(data=base64.b64encode(png))
                self._imgs.append(img)
                cell = self.ttk.Frame(self.strip)
                cell.grid(row=0, column=i, padx=1)
                self.ttk.Label(cell, image=img).pack()
                self.ttk.Label(cell, text=("► " if i == n else "") + fmt_time(tt)[2:], font=("TkDefaultFont", 8)).pack()
            self._status(_("Képek kész (a ► a vágási pont).", "Frames ready (► = cut point)."))

        self._status(_("Képek készítése…", "Rendering frames…"))
        self._bg(work, done)

    def show_wave(self):
        c = self._cur()
        ff = self._need() if c else None
        if not ff:
            return
        src, t = c
        b = parse_time(self.v_before.get()) or 2.0
        a = parse_time(self.v_after.get()) or 2.0
        t0 = max(0.0, t - b)
        dur = (t - t0) + a
        W = 900

        def work():
            return ff.wave_png(src, t0, dur, W, 120)

        def done(png, err):
            self.wave.delete("all")
            if err:
                self._status(str(err))
                return
            self._wave_img = self.tk.PhotoImage(data=base64.b64encode(png))
            self.wave.create_image(0, 5, image=self._wave_img, anchor="nw")
            x = (t - t0) / dur * W
            self.wave.create_line(x, 0, x, 130, fill="#ff3333", width=2)
            self._status(_("Hanghullám kész (piros vonal = vágási pont).", "Waveform ready (red line = cut point)."))

        self._status(_("Hanghullám készítése…", "Rendering waveform…"))
        self._bg(work, done)

    # ---- átalakítás ----
    def _preset_names(self):
        return [preset_label(k) for k in PRESETS] + [USER_MARK + n for n in sorted(self.cfg.get("presets", {}))]

    def _preset_get(self, label):
        if label.startswith(USER_MARK):
            return self.cfg.get("presets", {}).get(label[len(USER_MARK):], {})
        return PRESETS.get(preset_key(label), {})

    def _refresh_presets(self):
        self.cb_preset["values"] = self._preset_names()

    def apply_preset(self):
        p = self._preset_get(self.v_preset.get())
        for k in PRESET_KEYS:
            if k in self.o:
                self.o[k].set(p.get(k, "copy" if k in ("vcodec", "acodec") else ""))
        for k, d in PRESET_BOOLS:
            self.b[k].set(bool(p.get(k, d)))
        ext = {"Csak hang kimentése (AAC)": ".m4a"}.get(preset_key(self.v_preset.get()))
        if ext and self.o["out"].get():
            self.o["out"].set(os.path.splitext(self.o["out"].get())[0] + ext)
        self._container_chosen()

    # ---- a konténer hajtja a felületet: kiterjesztés, Videó, kodeklisták ----
    def _set_children_state(self, w, on):
        # egy keret minden mezője engedélyezett vagy inaktív; a gyerekekre is, mert a
        # Frame állapot-öröklődése a ttk-ban nem működik. (A tk.Text-nek nincs .state()-je.)
        try:
            kids = list(w.winfo_children())
        except Exception:
            kids = []
        for k in kids:
            self._set_children_state(k, on)
        try:
            if hasattr(w, "state"):
                w.state(["!disabled"] if on else ["disabled"])
        except Exception:
            pass

    def _set_combo_values(self, cb, vals):
        # a Combobox sorai (a tk.Combobox és a ttk.Combobox másképp kezeli a values-t)
        try:
            cb.configure(values=list(vals))
        except Exception:
            try:
                cb["values"] = list(vals)
            except Exception:
                pass

    def _encoders_known(self):
        # a lista az FFmpeg saját -encoders kimenete-e; ha nem, a „nincs meg a buildben”
        # jelölés semmit nem mondana, ezért azt akkor hagyjuk el
        return bool(getattr(self, "_build_enc", False))

    def _cont_spec(self):
        # a kiválasztott konténer leírása; ismeretlen muxerra None – ilyenkor nem szűrünk
        # és nem tilthatunk le semmit
        try:
            return CONTAINERS.get(self.o["container"].get().strip())
        except Exception:
            return None

    def _cont_pat(self, kind):
        # a kodekek szűrésére használt minta; None = egy kodek sem tilos
        sp = self._cont_spec()
        if not sp:
            return None
        p = sp.get("vp" if kind == "v" else "ap")
        return re.compile(p, re.I) if p else None

    def _audio_only(self):
        # a konténer VAGY a választott kiterjesztés csak hangot bír-e
        sp = self._cont_spec()
        if sp is not None and not sp.get("v", True):
            return True
        try:
            return self.v_ext.get().strip().lower() in AUDIO_ONLY_EXT
        except Exception:
            return False

    def _codec_ok(self, kind, name):
        # belefér-e a kodek a konténerbe; a Másolás és a „nincs folyam” mindig belefér
        name = (name or "").strip()
        if not name or name in ("copy", "none"):
            return True
        pat = self._cont_pat(kind)
        return pat is None or bool(pat.search(name))

    def _codec_missing(self, kind, name):
        # van-e ilyen kódoló ebben az FFmpeg buildben (csak a valódi listával jelölünk)
        name = (name or "").strip()
        if not name or name in ("copy", "none") or not self._encoders_known():
            return False
        return name not in (self._encV if kind == "v" else self._encA)

    def _codec_split(self, kind):
        # a kodekek csoportjai: (have, első, szoftveres ajánlott, hardveres, egyéb, hiányzó)
        have = dict(self._encV if kind == "v" else self._encA)
        if not have:
            return None
        free = self._cont_pat(kind) is None
        pool = sorted(have) if free else sorted(n for n in have if self._codec_ok(kind, n))
        first = ["copy", "none"]     # a "nincs folyam" mindkét listában marad: -vn / -an
        rec = RECOMMENDED_V if kind == "v" else RECOMMENDED_A
        # az ajánlott kodekek, amelyek EBBEN az FFmpeg buildben nincsnek meg: a kereshető
        # ablakban jelezve látszanak; a konténerbe nem illő, de meglévő kodek kimarad
        miss = [] if free else [n for n in rec if n not in have and n not in first
                                and n not in ("vp9", "vp8") and self._codec_ok(kind, n)]
        head = [n for n in rec if n in pool and n not in first and not _HW_RE.search(n)]
        hw = [n for n in pool if n not in first and _HW_RE.search(n)]
        body = [n for n in pool if n not in first and n not in head and n not in hw]
        return have, first, head, hw, body, miss

    def _codec_rows(self, kind):
        # a legördülő menő sorai: Másolás, „nincs folyam”, szoftveres ajánlottak – röviden –,
        # a végén a „Továbbiak…” sor, amely a kereshető ablakot nyitja
        sp = self._codec_split(kind)
        if sp is None:
            return []
        have, first, head, hw, body, miss = sp
        out = [codec_label(n, have.get(n, "")) for n in first + head]
        more = len(hw) + len(body) + len(miss)
        if more:
            out.append(MORE_MARK + " " + _("Továbbiak… (%d db)", "More… (%d)") % more)
        return out

    def _codec_groups(self, kind):
        # a kereshető ablak csoportjai: [(cím, [(név, leírás, hiányzik-e)])]
        sp = self._codec_split(kind)
        if sp is None:
            return []
        have, first, head, hw, body, miss = sp

        def rows(names, missing=False):
            return [(n, CODEC_INFO.get(n) or (have.get(n) or "").strip(), missing) for n in names]

        out = []
        for title, names, ms in (
                (_("Ajánlott", "Recommended"), first + head, False),
                (_("Hardveres (videokártya)", "Hardware (graphics card)"), hw, False),
                (_("Egyéb", "Other"), body, False),
                (_("Ebben az FFmpeg buildben nincs meg", "Not in this FFmpeg build"), miss, True)):
            if names:
                out.append((title, rows(names, ms)))
        return out

    def _upd_codec_desc(self, *_a):
        # a kodekmező melletti/alatti címke: a kiválasztott kodek rövid leírása és figyelmeztetése
        for kind, lbl, var in (("v", getattr(self, "lbl_vdesc", None), self.o["vcodec"]),
                               ("a", getattr(self, "lbl_adesc", None), self.o["acodec"])):
            if lbl is None:
                continue
            try:
                n = codec_name(var.get())
                if is_more_row(n) or is_group_row(n):
                    continue
                if not n:
                    t, col = _("üres – nincs kiválasztva (másolás; kimarad, ha a forrásban nincs ilyen folyam) – lenyitva kézzel választható",
                               "empty – nothing selected (copy; skipped if the source has no such stream) – pick one from the list"), "#666666"
                else:
                    t, col = "%s – %s" % (n, self._codec_desc(kind, n)), "#00695c"
                    if self._codec_missing(kind, n):
                        t += _("   (nincs meg ebben az FFmpeg buildben)", "   (not in this FFmpeg build)")
                        col = "#b71c1c"
                    elif not self._codec_ok(kind, n):
                        t += _("   (nem szokásos ebben a konténerben)", "   (unusual in this container)")
                        col = "#e65100"
                lbl.config(text=t, foreground=col)
            except Exception:
                pass

    def _codec_dialog(self, kind):
        # kereshető kodekválasztó: csoportosított lista kereséssel, a leírás nem vágódik le
        tk, ttk = self.tk, self.ttk
        groups = self._codec_groups(kind)
        if not groups:
            return
        var = self.o["vcodec" if kind == "v" else "acodec"]
        dlg = tk.Toplevel(self.cb_v.winfo_toplevel())
        dlg.title(_("Videókodek kiválasztása", "Choose video codec") if kind == "v"
                  else _("Hangkodek kiválasztása", "Choose audio codec"))
        dlg.geometry("680x500")
        dlg.minsize(480, 320)
        try:
            dlg.transient(self.cb_v.winfo_toplevel())
        except Exception:
            pass
        top = ttk.Frame(dlg, padding=(8, 8, 8, 4))
        top.pack(fill="x")
        ttk.Label(top, text=_("Keresés:", "Search:")).pack(side="left")
        q = tk.StringVar()
        ent = ttk.Entry(top, textvariable=q)
        ent.pack(side="left", fill="x", expand=True, padx=6)
        mid = ttk.Frame(dlg, padding=(8, 0))
        mid.pack(fill="both", expand=True)
        tv = ttk.Treeview(mid, columns=("name", "desc"), show="headings", selectmode="browse")
        tv.heading("name", text=_("Kodek", "Codec"))
        tv.heading("desc", text=_("Leírás", "Description"))
        tv.column("name", width=170, stretch=False, anchor="w")
        tv.column("desc", width=470, stretch=True, anchor="w")
        sb = ttk.Scrollbar(mid, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        tv.tag_configure("grp", foreground="#00695c", font=("Segoe UI", 9, "bold"))
        tv.tag_configure("miss", foreground="#9e9e9e")
        cnt = tk.StringVar()
        ttk.Label(dlg, textvariable=cnt, foreground="#555", padding=(10, 4)).pack(fill="x")
        bt = ttk.Frame(dlg, padding=(8, 0, 8, 8))
        bt.pack(fill="x")
        names = {}

        def fill(*_a):
            tv.delete(*tv.get_children())
            names.clear()
            term = q.get().strip().lower()
            total = 0
            for title, rows in groups:
                hit = [r for r in rows if not term or term in r[0].lower() or term in r[1].lower()]
                if not hit:
                    continue
                gid = tv.insert("", "end", values=("%s (%d)" % (title, len(hit)), ""), tags=("grp",))
                names[gid] = None
                for n, d, ms in hit:
                    iid = tv.insert("", "end", values=(n, d), tags=("miss",) if ms else ())
                    names[iid] = n
                    total += 1
            cnt.set(_("%d kodek – dupla kattintás vagy Enter a kiválasztáshoz", "%d codecs - double-click or Enter to choose") % total)

        def pick(_e=None):
            sel = tv.selection()
            n = names.get(sel[0]) if sel else None
            if not n:
                return
            dlg.destroy()
            var.set(n)
            self._codec_picked(kind)

        def first_row(_e=None):
            for iid in tv.get_children():
                if names.get(iid):
                    tv.selection_set(iid)
                    tv.focus(iid)
                    tv.focus_set()
                    return

        ttk.Button(bt, text=_("Mégse", "Cancel"), command=dlg.destroy).pack(side="right")
        ttk.Button(bt, text=_("Kiválaszt", "Choose"), command=pick).pack(side="right", padx=6)
        q.trace_add("write", fill)
        tv.bind("<Double-1>", pick)
        tv.bind("<Return>", pick)
        ent.bind("<Return>", lambda e: (first_row(), pick()))
        ent.bind("<Down>", first_row)
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        fill()
        # a jelenlegi kodek kijelölése és láthatóvá tétele
        cur = codec_name(var.get())
        for iid, n in names.items():
            if n and n == cur:
                tv.selection_set(iid)
                tv.see(iid)
                break
        ent.focus_set()
        try:
            dlg.grab_set()
        except Exception:
            pass

    def _codec_desc(self, kind, name):
        # a lista szerinti rövid leírás; ha nincs, az FFmpeg saját leírása
        d = CODEC_INFO.get((name or "").strip())
        if d:
            return d
        have = getattr(self, "_encV" if kind == "v" else "_encA", {})
        return (have.get(name) or "").strip() or _("ismeretlen kodek", "unknown codec")

    def _status_shown(self, kind, name):
        # ugyanazt az üzenetet ne írjuk ki kétszer egymás után
        last = getattr(self, "_last_codec_msg", ("", ""))
        self._last_codec_msg = (kind, name)
        return last == (kind, name)

    def _codec_first(self, kind):
        # az első valódi kodek a listán (a Másolás és a „nincs folyam” után)
        for row in self._codec_rows(kind):
            n = codec_name(row)
            if n and not is_group_row(row) and n not in ("copy", "none"):
                return n
        return "copy"

    def _codec_picked(self, kind):
        # a sorból a kodeknevet tartjuk számon: a parancssor és a profilok ezt kapják
        cb = self.cb_v if kind == "v" else self.cb_a
        var = self.o["vcodec" if kind == "v" else "acodec"]
        raw = (getattr(cb, "get", lambda: "")() or "")
        if is_more_row(raw):
            # a „Továbbiak…” sor nem kodek: visszaállunk az előzőre, és megnyitjuk a kereshető ablakot
            prev = (getattr(self, "_codec_last", None) or {}).get(kind)
            var.set(prev if prev and not is_more_row(prev) else self._codec_first(kind))
            self._codec_dialog(kind)
            return
        if is_group_row(raw):
            # a csoportelválasztó sora nem választható: visszaállunk az utolsó kodekre
            prev = (getattr(self, "_codec_last", None) or {}).get(kind)
            var.set(prev if prev and not is_group_row(prev) else self._codec_first(kind))
            return
        n = codec_name(raw)
        if not n:
            return
        if raw != n:
            var.set(n)          # a beállítások és a parancssor soha ne kapja a leírást
        d = getattr(self, "_codec_last", None)
        if d is None:
            d = self._codec_last = {}
        d[kind] = n
        if self._codec_missing(kind, n):
            self._status(_("A(z) „%s” kódoló nincs meg ebben az FFmpeg buildben: válassz másikat a listáról.",
                           "The encoder %s is not in this FFmpeg build: pick another one from the list.") % n)
        elif not self._codec_ok(kind, n):
            self._status(_("A(z) „%s” kodek nem szokásos a(z) %s konténerben: az FFmpeg elutasíthatja.",
                           "The codec %s is unusual in the %s container: FFmpeg may refuse it.")
                         % (n, self.o["container"].get()))
        if not self._status_shown(kind, n):
            self._status(_("%s – %s", "%s - %s") % (n, self._codec_desc(kind, n)))
        self._apply_container(quiet=True)

    def _ext_list(self):
        # a konténer által kínált kiterjesztések; ismeretlen konténernál a célfájlé a kapaszkodó
        sp = self._cont_spec()
        c = self.o["container"].get().strip()
        exts = list(sp["ext"]) if sp and sp.get("ext") else []
        if not exts and c in CONTAINER_EXT:
            exts = [CONTAINER_EXT[c]]
        if exts:
            return exts
        try:
            tgt = os.path.splitext(self.o["out"].get().strip())[1].lower()
        except Exception:
            tgt = ""
        return [tgt] if tgt else []

    def _suggest_ext(self):
        # a Videó állapota adja meg a javasolt kiterjesztést: nincs videó -> a konténer hang-társa
        exts = self._ext_list()
        if not exts:
            return ""
        if self.o["vcodec"].get().strip() == "none":
            return next((x for x in exts if x in AUDIO_ONLY_EXT), exts[0])
        return next((x for x in exts if x not in AUDIO_ONLY_EXT), exts[0])

    def _ext_chosen(self, _e=None):
        # a kézzel választott kiterjesztés dönthet úgy, hogy a Videó rész kikapcsol (.mka / .m4a)
        self._apply_container(quiet=True)

    def _container_typed(self, _e=None):
        # a beírt konténernevet is komolyan vesszük, ha pontosan egy muxernek felel meg
        try:
            c = self.o["container"].get().strip()
        except Exception:
            return
        if not c or c in CONTAINERS:
            self._apply_container()

    def _upd_cont_hint(self):
        # egy sorban: mi fér a konténerbe, és mi inaktív most
        try:
            c = self.o["container"].get().strip()
            e = self.v_ext.get().strip()
            if not c:
                self.lbl_cont.config(text="")
                return
            t = "%s → %s" % (c, e) if e else str(c)
            if self._audio_only():
                t += _("  –  csak hang (a Videó rész inaktív)",
                       "  -  audio only (the Video frame is inactive)")
            if self._cont_spec() is None:
                t += _("  –  ismeretlen konténer: nincs kodekszűrés",
                       "  -  unknown container: no codec filtering")
            self.lbl_cont.config(text=t)
        except Exception:
            pass

    def _apply_container(self, _e=None, quiet=False):
        # a konténer változásának egyetlen köre: kiterjesztés, Videó ki/be, kodeklisták
        if not hasattr(self, "cb_c"):
            return
        # ha a Videó kodeket mi kapcsoltuk ki, előbb azt állítjuk vissza, hogy a
        # kiterjesztés-javaslat megint videót bíró konténert lásson
        sp = self._cont_spec()
        if self._v_was and (sp is None or sp.get("v", True)):
            self.o["vcodec"].set(self._v_was)
            self._v_was = ""
        exts = self._ext_list()
        self._set_combo_values(self.cb_ext, exts or [""])
        cur = self.v_ext.get().strip().lower()
        if exts and (not cur or cur not in exts or (not quiet and len(exts) > 1)):
            pick = self._suggest_ext()
            if pick and pick != cur:
                self.v_ext.set(pick)
                cur = pick
        # a csak-hang konténer (vagy a .mka / .m4a kiterjesztés) inaktívvá teszi a Videó részt
        audio_only = self._audio_only()
        if audio_only:
            if self.o["vcodec"].get() != "none":
                self._v_was = self.o["vcodec"].get()
                self.o["vcodec"].set("none")
        frm = getattr(self, "frm_v", None)      # a Videó-keret (a 6. szabály nevezte el)
        if frm is not None:
            self._set_children_state(frm, not audio_only)
        # a kodeklisták a konténerhez igazítva
        rows_v = self._codec_rows("v")
        rows_a = self._codec_rows("a")
        if rows_v:
            self._set_combo_values(self.cb_v, rows_v)
        if rows_a:
            self._set_combo_values(self.cb_a, rows_a)
        # ha a beírt kodek nem fér a konténerbe: átállunk az első illőre, és szólunk
        for kind, var in (("v", self.o["vcodec"]), ("a", self.o["acodec"])):
            n = (var.get() or "").strip()
            if kind == "v" and audio_only:
                if n != "none":
                    self._status(_("A Videó rész inaktív ebben a konténerben: videó nélkül írunk ki.",
                                   "The Video frame is inactive in this container: writing without video."))
                continue
            if not n:
                continue
            if not self._codec_ok(kind, n):
                nb = self._codec_first(kind)
                var.set(nb)
                what = _("videó", "video") if kind == "v" else _("hang", "audio")
                self._status(_("A(z) „%s” %s-kodek nem fér a(z) %s konténerbe: átállunk „%s”-ra. "
                               "A kodeklista az FFmpeg saját kódolóiból készült.",
                               "The %s codec %s does not fit in the %s container: switched to %s. "
                               "The codec list comes from this FFmpeg build's own encoders.")
                             % (n, what, self.o["container"].get(), nb))
            elif self._codec_missing(kind, n):
                self._status(_("A(z) „%s” kódoló nincs meg ebben az FFmpeg buildben: az indítás "
                               "hibát adhat. A lista többi kódolója elérhető.",
                               "The encoder %s is not in this FFmpeg build: starting may fail. "
                               "The other encoders on the list are available.") % n)
        d = getattr(self, "_codec_last", None)
        if d is None:
            d = self._codec_last = {}
        d["v"] = self.o["vcodec"].get()
        d["a"] = self.o["acodec"].get()
        self._upd_ext_in_out()
        self._upd_cont_hint()
        self._upd_codec_desc()
        self._upd_codec_fields()

    def _upd_codec_fields(self, *_a):
        """Másolásnál (copy), kihagyásnál (none) vagy üres kodeknél nincs újrakódolás, ezért a hozzá tartozó mezők
        (preset, CRF, bitráta, méret, fps, pix_fmt, hwaccel, GOP, -vf, deinterlace / csatorna, Hz, dB, -af)
        inaktívak. A kodek-választó és a leíró sor megmarad. Csak-hang konténernél a Videó-keretet az
        _apply_container kapcsolja ki teljesen."""
        try:
            audio_only = self._audio_only()
        except Exception:
            audio_only = False
        for frm, keep, var, skip in (
                (getattr(self, "frm_v", None), (getattr(self, "cb_v", None), getattr(self, "lbl_vdesc", None)),
                 self.o["vcodec"], audio_only),
                (getattr(self, "frm_a", None), (getattr(self, "cb_a", None), getattr(self, "lbl_adesc", None)),
                 self.o["acodec"], False)):
            if frm is None or skip:
                continue
            off = (var.get() or "").strip() in ("copy", "none", "")
            for w in frm.winfo_children():
                if any(w is k for k in keep):
                    continue
                self._set_children_state(w, not off)

    def _upd_ext_in_out(self):
        # a célfájl kiterjesztése a kiválasztott kiterjesztéshez igazodik
        try:
            e = self.v_ext.get().strip().lower()
            out = self.o["out"].get().strip()
            if not e.startswith(".") or not out:
                return
            base, old = os.path.splitext(out)
            if not base or old.lower() == e:
                return
            self.o["out"].set(base + e)
        except Exception:
            pass

    def _container_chosen(self, _e=None):
        # a régi hívó hely (apply_preset) is ide fut be: egyetlen kör, a konténer szerint
        self._apply_container()

    def save_preset(self):
        from tkinter import simpledialog
        name = simpledialog.askstring(_("Minta mentése", "Save preset"), _("A minta neve:", "Preset name:"),
                                      parent=self.parent.winfo_toplevel())
        name = (name or "").strip()
        if name.startswith(USER_MARK):
            name = name[len(USER_MARK):]
        if not name:
            return
        presets = self.cfg.setdefault("presets", {})
        if name in presets and not self.mb.askyesno("FFmpeg", _("Már van ilyen nevű minta. Felülírod?",
                                                                 "A preset with this name exists. Overwrite?")):
            return
        d = {k: self.o[k].get() for k in PRESET_KEYS if k in self.o}
        d.update({k: bool(self.b[k].get()) for k, _d in PRESET_BOOLS})
        presets[name] = d
        save_config(self.cfg)
        self._refresh_presets()
        self.v_preset.set(USER_MARK + name)
        self._status(_("Minta elmentve: ", "Preset saved: ") + name)

    def delete_preset(self):
        label = self.v_preset.get()
        if not label.startswith(USER_MARK):
            self.mb.showinfo("FFmpeg", _("Csak a saját (★) minták törölhetők.", "Only your own (★) presets can be deleted."))
            return
        name = label[len(USER_MARK):]
        if self.mb.askyesno("FFmpeg", _("Törlöd a mintát: %s?", "Delete preset: %s?") % name):
            self.cfg.get("presets", {}).pop(name, None)
            save_config(self.cfg)
            self._refresh_presets()
            self.v_preset.set(preset_label(list(PRESETS)[0]))
            self.apply_preset()

    def _opts(self):
        out = self.o["out"].get().strip()
        if out and not os.path.splitext(out)[1]:        # kiterjesztés nélküli cél: pótoljuk
            self.o["out"].set(out + self._default_ext())
        o = {k: v.get() for k, v in self.o.items()}
        o.update({k: bool(v.get()) for k, v in self.b.items()})
        o.update(src=self.v_src.get().strip(), start=self.v_start.get(), end=self.v_end.get())
        for k in ("vcodec", "acodec"):              # üres kodek = nincs kiválasztva: másolás (ha nincs ilyen folyam, kimarad)
            if not (o.get(k) or "").strip():
                o[k] = "copy"
        return o

    def _make_cmd(self):
        ff = self._need()
        if not ff:
            return None, None, None
        dur = None
        if self._probe:
            try:
                dur = float(self._probe.get("format", {}).get("duration"))
            except (TypeError, ValueError):
                dur = None
        if dur is None and getattr(self, "editor", None) is not None and self.editor.info:
            dur = self.editor.dur or None
        try:
            cmd, total = ff.build_convert(self._opts(), dur)
        except FFError as e:
            self.mb.showwarning("FFmpeg", str(e))
            return None, None, None
        return ff, cmd, total

    def show_cmd(self):
        if self.queue:
            ff = self._need()
            if not ff:
                return
            src, a, b = self.queue[0]
            oo = self._opts()
            sep = self.v_qmode.get() == "sep"
            if len(self.queue) > 1 and not sep and ff.join_ok(oo):
                tf = []
                try:
                    jl, jv = self._join_args(self.queue)
                    cmd, _t, tf = ff.build_join(jl, oo, oo.get("out", "").strip() or _("<cél fájl>", "<target file>"), vsx=jv)
                except FFError as e:
                    self.mb.showwarning("FFmpeg", str(e))
                    return
                self.v_cmd.set(_("(egy menetben vágva és egybefűzve) ", "(cut and joined in a single pass) ")
                               + cmdline(cmd))
                for fp in tf:
                    try:
                        os.remove(fp)
                    except OSError:
                        pass
                return
            oo.update(src=src, start=fmt_time(a), end=fmt_time(b), out=oo.get("out", "").strip() or _("<cél fájl>", "<target file>"),
                      fx_vf=self.fx_vf(src, a, b), fx_vs=self.fx_vs(src, a, b))
            try:
                cmd, _t = ff.build_convert(oo, b - a)
            except FFError as e:
                self.mb.showwarning("FFmpeg", str(e))
                return
            txt = cmdline(cmd)
            if len(self.queue) > 1:
                if sep:
                    txt = _("(1. szakasz parancsa; a többi ugyanígy, külön fájlokba) ", "(command of item 1; the rest alike, separate files) ") + txt
                else:
                    txt = _("(1. szakasz parancsa; a többi ugyanígy, majd egybefűzés) ", "(command of item 1; the rest alike, then joined) ") + txt
            self.v_cmd.set(txt)
            return
        ff, cmd, _t = self._make_cmd()
        if cmd:
            self.v_cmd.set(cmdline(cmd))

    # ---- képeffektek (efekt.py) ----
    @staticmethod
    def _fx_key(src, a, b):
        return (os.path.normcase(os.path.abspath(src)), round(float(a), 3), round(float(b), 3))

    def fx_vf(self, src, a, b):
        """Az adott szakaszhoz tartozó effekt-szűrőlánc ("" ha nincs)."""
        return (self.fx.get(self._fx_key(src, a, b)) or {}).get("vf", "")

    def fx_vs(self, src, a, b):
        """A szakasz VapourSynth-adatai ({"vcmd": [vspipe ...], "fps": ...}) vagy None. A kép közvetlenül a vspipe-ból
        megy az ffmpeg-be (nincs köztes fájl, egyetlen kódolás)."""
        v = (self.fx.get(self._fx_key(src, a, b)) or {}).get("vs")
        return v if v and v.get("vcmd") else None

    def _join_args(self, items):
        """items: [(forrás, kezdet, vég)] -> (build_join-elemek, vsx) (vsx: None, ha egyik szakasz sem VapourSynth-es)."""
        lst = [(s_, a_, b_, self.fx_vf(s_, a_, b_)) for s_, a_, b_ in items]
        vsx = [self.fx_vs(s_, a_, b_) for s_, a_, b_ in items]
        return lst, (vsx if any(vsx) else None)

    def open_effects(self, src, rngs):
        """Megnyitja (vagy frissíti) a Képeffektek ablakot a megadott szakaszokkal: rngs = [(kezdet, vég), ...]."""
        ff = self._need()
        if not ff or not src or not rngs:
            return
        ef, err = load_efekt()
        if ef is None:
            self.mb.showwarning("FFmpeg", _("A Képeffektek modul (efekt.py) nem tölthető be – tedd az lvt_ffmpeg.py mellé.\n\n",
                                            "The image effects module (efekt.py) could not be loaded - put it next to lvt_ffmpeg.py.\n\n") + err)
            return
        segs = [(src, a, b) for a, b in rngs]
        w = self._fx_win
        try:
            if w is not None and w.alive():
                w.add_segments(segs)
                w.focus()
                return
        except Exception:       # noqa
            pass
        try:
            self._fx_win = ef.open_window(self, ff, segs)
        except Exception as e:      # noqa
            self.mb.showwarning("FFmpeg", _("A Képeffektek ablak nem nyílt meg:\n", "The effects window failed to open:\n") + str(e))

    def q_effects(self):
        """Az Átalakítás lista kijelölt (ha nincs: az összes) szakaszát megnyitja újra szerkesztésre a Képeffektekben."""
        sel = sorted(int(i) for i in self.qtree.selection() if int(i) < len(self.queue)) or list(range(len(self.queue)))
        if not sel:
            self.mb.showinfo("FFmpeg", _("A lista üres. A Szerkesztőben jelölj ki szakaszt, és használd a „→ Kijelöltek a Képeffektekre” gombot.",
                                         "The list is empty. In the Editor select segments and use \"→ Selected to Image effects\"."))
            return
        ff = self._need()
        if not ff:
            return
        ef, err = load_efekt()
        if ef is None:
            self.mb.showwarning("FFmpeg", _("A Képeffektek modul (efekt.py) nem tölthető be.\n\n", "efekt.py could not be loaded.\n\n") + err)
            return
        segs = []
        for i in sel:
            e = self.fx.get(self._fx_key(*self.queue[i])) or {}
            segs.append(tuple(e["orig"]) if e.get("orig") else self.queue[i])    # renderelt fájl helyett az eredeti szakasz
        try:
            if self._fx_win is not None and self._fx_win.alive():
                self._fx_win.add_segments(segs)
                self._fx_win.focus()
                return
        except Exception:       # noqa
            pass
        try:
            self._fx_win = ef.open_window(self, ff, segs)
        except Exception as e:      # noqa
            self.mb.showwarning("FFmpeg", str(e))

    def fx_apply(self, items):
        """A Képeffektek ablak "Kimenet" gombja hívja: items = [{"src","a","b","vf","state", "orig", "conv"}, ...].
        A szakaszok az Átalakítás lista végére kerülnek (ha már ott vannak: a beállításuk frissül).
        orig: az eredeti (forrás, kezdet, vég), ha a szakasz forrása a VapourSynth által renderelt közbenső fájl; ha az eredeti
              szakasz már a listában van (korábbi kimenetből), az ott marad a helyén, de az új fájlt kapja.
        conv: {"scale": "1280:720", "fps": "25"}: az effektek utáni kimeneti méret / kocka-sebesség; a program az Átalakítás
              fül „méret” és „fps” mezőibe írja. A mezők kézzel átírhatók, és a végén azok a mérvadók (a szűrőlánc UTÁN
              érvényesülnek, az összefűzésnél pedig a közös képméretet is azok adják)."""
        for it in items:
            key = self._fx_key(it["src"], it["a"], it["b"])
            orig = it.get("orig")
            entry = {"vf": it.get("vf", ""), "state": it.get("state", {})}
            if it.get("vs"):                                # VapourSynth: közvetlen vspipe -> ffmpeg, köztes fájl nélkül
                entry["vs"] = dict(it["vs"])
            if orig:
                entry["orig"] = tuple(orig)
                okey = self._fx_key(*orig)
                self.fx_reopen[okey] = {"state": dict(it.get("orig_state") or it.get("state") or {})}
                idx = next((n for n, q in enumerate(self.queue)
                            if (self.fx.get(self._fx_key(*q)) or {}).get("orig")
                            and self._fx_key(*self.fx[self._fx_key(*q)]["orig"]) == okey), None)
                if idx is None:                             # maga az eredeti szakasz van a listában (innen nyitották az effektet)
                    idx = next((n for n, q in enumerate(self.queue) if self._fx_key(*q) == okey), None)
                if idx is not None:                         # a helyén cserélődik a renderelt változatra (nem duplázódik)
                    self.queue[idx] = (it["src"], it["a"], it["b"])
                else:
                    self.queue_add(it["src"], [(it["a"], it["b"])])
            else:
                self.queue_add(it["src"], [(it["a"], it["b"])])
            if it.get("vf") or it.get("vs") or it.get("state") or orig:
                self.fx[key] = entry
        self._refresh_queue()
        self.nb.select(self.t_conv)
        n = sum(1 for it in items if it.get("vf") or it.get("orig") or it.get("vs"))
        conv = next((it.get("conv") for it in items if it.get("conv")), None)
        set_txt = ""
        if conv:
            done = []
            for fld, label in (("scale", _("méret", "size")), ("fps", "fps")):
                val = (conv.get(fld) or "").strip()
                if val and fld in self.o:
                    self.o[fld].set(val)
                    done.append("%s=%s" % (label, val))
            if done:
                set_txt = _(" Beállítva az Átalakításon: ", " Set on the Convert tab: ") + ", ".join(done) + "."
        vs_txt = ""
        if any(it.get("vs") for it in items):
            vs_txt = _(" VapourSynth: köztes fájl nélkül, a kép közvetlenül a vspipe-ból megy az ffmpeg-be (egyetlen kódolás).",
                       " VapourSynth: no intermediate file, the picture goes straight from vspipe into ffmpeg (one encode).")
        self._status(_("Képeffektek átvéve: %d szakasz (%d effekttel).%s%s Az Átalakítás fül kodekje legyen újrakódolós (pl. libx264); "
                       "a kodek, a kbit/s és a konténer itt még átírható, a mezők kézzel módosíthatók, és azok a mérvadók.",
                       "Image effects applied: %d segments (%d with effects).%s%s Use a re-encoding codec (e.g. libx264); "
                       "codec, kbit/s and container can still be changed here, the fields can be edited and they are authoritative.")
                     % (len(items), n, set_txt, vs_txt))
        self.reveal_convert()

    def reveal_convert(self):
        """Az Átalakítás fület és a főablakot előtérbe hozza (kis késleltetésekkel is: a Képeffektek ablak bezárásakor az
        operációs rendszer máshová adhatja a fókuszt, és a főablak a többi mögött maradna / minimalizálva lenne)."""
        def go():
            try:
                w = self.f
                while w is not None:                    # minden fölötte lévő fül-tárolóban ez a panel legyen kijelölve
                    p = w.master
                    if p is None:
                        break
                    try:
                        if p.winfo_class() == "TNotebook":
                            p.select(w)
                    except Exception:       # noqa
                        pass
                    w = p
                try:
                    self.nb.select(self.t_conv)
                except Exception:       # noqa
                    pass
                top = self.parent.winfo_toplevel()
                try:
                    if str(top.state()) == "iconic":
                        top.deiconify()
                except Exception:       # noqa
                    pass
                top.lift()
                top.focus_force()
                try:
                    top.attributes("-topmost", True)
                    top.after(200, lambda: top.attributes("-topmost", False))
                except Exception:       # noqa
                    pass
            except Exception:       # noqa
                pass
        go()
        try:
            top = self.parent.winfo_toplevel()
            top.after(120, go)
            top.after(500, go)
        except Exception:       # noqa
            pass

    def _fx_active(self):
        keys = {self._fx_key(*q) for q in self.queue}
        return any((v.get("vf") or v.get("vs")) for k, v in self.fx.items() if k in keys)

    # ---- az átvitt szakaszok listája (Átalakítás fül) ----
    def queue_add(self, src, rngs):
        for a, b in rngs:
            if not any(q[0] == src and abs(q[1] - a) < 1e-3 and abs(q[2] - b) < 1e-3 for q in self.queue):
                self.queue.append((src, a, b))
        self._refresh_queue()

    def _refresh_queue(self, select=None):
        for i in self.qtree.get_children():
            self.qtree.delete(i)
        keys = {self._fx_key(*q) for q in self.queue}
        self.fx = {k: v for k, v in self.fx.items() if k in keys}       # a listából kikerült szakaszok effektjei törlődnek
        for n, (src, a, b) in enumerate(self.queue):
            f = self.fx.get(self._fx_key(src, a, b))
            self.qtree.insert("", "end", iid=str(n), values=(n + 1, os.path.basename(src), fmt_time(a), fmt_time(b),
                                                             fmt_time(b - a), ("✓ FX+VS" if f.get("vs") else "✓ FX") if f and (f.get("vf") or f.get("vs")) else "–"))
        for i in (select or []):
            if 0 <= i < len(self.queue):
                self.qtree.selection_add(str(i))

    def q_move(self, d):
        sel = sorted(int(i) for i in self.qtree.selection())
        q = self.queue
        if not sel or (d < 0 and sel[0] == 0) or (d > 0 and sel[-1] == len(q) - 1):
            return
        for i in (sel if d < 0 else reversed(sel)):
            q[i + d], q[i] = q[i], q[i + d]
        self._refresh_queue([i + d for i in sel])

    # ---- gyorsbillentyűk az Átalakítás listán ----
    def _q_select_all(self, _e=None):
        self.qtree.selection_set(self.qtree.get_children(""))
        return "break"

    def _q_clear_sel(self, _e=None):
        self.qtree.selection_remove(self.qtree.selection())
        return "break"

    def _q_del_key(self, _e=None):
        self.q_del()
        return "break"

    def q_del(self):
        for i in sorted((int(i) for i in self.qtree.selection()), reverse=True):
            if i < len(self.queue):
                del self.queue[i]
        self._refresh_queue()

    def q_clear(self):
        self.queue = []
        self._refresh_queue()

    def _ask_range(self, n):
        """Kis párbeszédablak: teljes fájl vagy A–B rész. Visszatér: (mód, kezdet, vég) vagy None (Mégse)."""
        tk, ttk = self.tk, self.ttk
        top = self.parent.winfo_toplevel()
        win = tk.Toplevel(top)
        win.title(_("Hozzáadás az Átalakítás listájához", "Add to the Convert list"))
        try:
            win.transient(top)
        except tk.TclError:
            pass
        res = {"v": None}
        mode = tk.StringVar(master=win, value="whole")
        st = tk.StringVar(master=win, value="")
        en = tk.StringVar(master=win, value="")
        fr = ttk.Frame(win, padding=12)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text=_("%d fájl kiválasztva. Mit adjak hozzá?",
                             "%d file(s) selected. What should be added?") % n).pack(anchor="w")
        ttk.Radiobutton(fr, text=_("Teljes fájl (az egész hossza)", "Whole file (full length)"),
                        variable=mode, value="whole").pack(anchor="w", pady=(6, 0))
        ttk.Radiobutton(fr, text=_("Csak A–B rész", "Only an A-B part"),
                        variable=mode, value="ab").pack(anchor="w")
        r = ttk.Frame(fr)
        r.pack(anchor="w", padx=22, pady=4)
        ttk.Label(r, text=_("Kezdet", "Start")).pack(side="left")
        ttk.Entry(r, textvariable=st, width=12).pack(side="left", padx=4)
        ttk.Label(r, text=_("Vég (üresen: a fájl vége)", "End (empty: end of file)")).pack(side="left", padx=(10, 0))
        ttk.Entry(r, textvariable=en, width=12).pack(side="left", padx=4)
        ttk.Label(fr, text=_("Az A–B rész minden kiválasztott fájlra vonatkozik. Idő: 83.5 vagy 0:01:23.5",
                             "The A-B range applies to every selected file. Time: 83.5 or 0:01:23.5"),
                  foreground="#555555").pack(anchor="w")
        bt = ttk.Frame(fr)
        bt.pack(fill="x", pady=(10, 0))

        def ok(_e=None):
            if mode.get() == "whole":
                res["v"] = ("whole", 0.0, None)
            else:
                a = parse_time(st.get()) if st.get().strip() else 0.0
                b = parse_time(en.get()) if en.get().strip() else None
                if a is None or (en.get().strip() and b is None):
                    self.mb.showwarning("FFmpeg", _("Az időpont nem értelmezhető (pl. 83.5 vagy 0:01:23.5).",
                                                    "The time is not valid (e.g. 83.5 or 0:01:23.5)."))
                    return
                res["v"] = ("ab", a, b)
            win.destroy()

        ttk.Button(bt, text=_("Mégse", "Cancel"), command=win.destroy).pack(side="right")
        ttk.Button(bt, text=_("Hozzáadás", "Add"), command=ok).pack(side="right", padx=6)
        win.bind("<Escape>", lambda _e: win.destroy())
        win.bind("<Return>", ok)
        try:
            win.grab_set()
        except tk.TclError:
            pass
        win.focus_force()
        win.wait_window()
        return res["v"]

    def q_add_files(self, _e=None):
        """„Fájl hozzáadása…”: kívülről érkező fájlok az Átalakítás listájára (teljes hossz vagy A–B)."""
        if self.busy:
            return "break"
        if self._need() is None:
            return "break"
        paths = self.fd.askopenfilenames(
            parent=self.parent, title=_("Fájl hozzáadása az átalakításhoz", "Add file to convert"),
            filetypes=[(_("Videó / hang", "Video / audio"),
                         "*.mts *.m2ts *.ts *.mkv *.webm *.mp4 *.m4v *.mov *.avi *.mpg *.vob "
                         "*.mp3 *.m4a *.wav *.flac *.aac *.ac3 *.opus"),
                       ("*", "*.*")])
        if not paths:
            return "break"
        rng = self._ask_range(len(paths))
        if rng is None:
            return "break"
        mode, ra, rb = rng
        ff = self.ff
        paths = [os.path.normpath(p) for p in paths]

        def work():
            out = []
            for p in paths:
                try:
                    qi = ff.quick_info(p)
                    out.append((p, float(qi.get("duration") or 0.0), ""))
                except FFError as e:
                    out.append((p, 0.0, str(e)))
            return out

        def done(res, err):
            if err:
                self._status(_("Hiba a fájl olvasásakor: ", "Error reading the file: ") + str(err))
                return
            added, problems = [], []
            was_empty = not self.queue
            for p, dur, why in res:
                name = os.path.basename(p)
                if dur <= 0:
                    problems.append("%s: %s" % (name, why or _("nincs hossz-adat", "no duration data")))
                    continue
                if mode == "whole":
                    a, b = 0.0, dur
                else:
                    a, b = ra, (dur if rb is None else rb)
                if b <= a or a >= dur:
                    problems.append(_("%s: az A–B tartomány nem fér bele a fájlba (hossz %s)",
                                      "%s: the A-B range does not fit the file (length %s)")
                                    % (name, fmt_time(dur)))
                    continue
                b = min(b, dur)
                self.queue_add(p, [(a, b)])
                added.append(p)
            if added and not self.v_src.get().strip():
                # nincs forrásfájl a mezőkben: az első hozzáadott lesz (a Videó / Hang mezők ebből töltődnek)
                self.v_src.set(added[0])
            elif added and was_empty:
                # üres volt a lista: a Videó / Hang mezők az első hozzáadott fájl adataival töltődnek (a Szerkesztő fájlja nem változik)
                self.autofill_source(added[0], force=True, local=True)
            if added:
                self.nb.select(self.t_conv)
            msg = _("%d fájl került az Átalakítás listájára.",
                    "%d file(s) added to the Convert list.") % len(added)
            if problems:
                msg += "  " + " | ".join(problems)
                self.mb.showwarning("FFmpeg", "\n".join(problems))
            self._status(msg)

        self._status(_("Fájlok olvasása…", "Reading files…"))
        self._bg(work, done)
        return "break"

    def _q_open(self, _e=None):
        """Ctrl+O az Átalakítás listán: ugyanaz, mint a „Fájl hozzáadása…” gomb."""
        self.q_add_files()
        return "break"

    def _smart_copy_eligible(self, items, o, out):
        """Igaz, ha az Átalakítás lista „copy + copy” módban pontos (Smart) vágással készíthető el:
        ugyanaz a forrás, azonos konténer-család, nincs effekt, nincs kocka-pontos vágás / felirat."""
        try:
            if str(o.get("vcodec", "copy")) != "copy" or str(o.get("acodec", "copy")) != "copy":
                return False
            if self._fx_active() or o.get("accurate") or o.get("subs_copy") or o.get("fx_vs"):
                return False
            srcs = {os.path.normcase(os.path.abspath(it[0])) for it in items}
            if len(srcs) != 1:
                return False

            def fam(e):
                e = e.lower()
                return ("mpegts" if e in (".ts", ".mts", ".m2ts") else
                        "matroska" if e in (".mkv", ".webm") else
                        "iso-bmff" if e in (".mp4", ".m4v", ".mov") else None)
            sf = fam(os.path.splitext(items[0][0])[1])
            return sf is not None and sf == fam(os.path.splitext(out)[1])
        except Exception:
            return False

    def _queue_jobs(self, ff):
        """Átalakítás lista -> munkák. „copy + copy” módban a vágás a Smart Cut gépezettel készül (a kezdő- és
        végpont nem kulcskockán is pontos, nincs pre-roll és illesztési rés); ha az nem lehetséges, a klasszikus út."""
        r = self._queue_jobs_classic(ff)
        if not r:
            return r
        jobs, final, cleanup, shown = r
        items = list(self.queue)
        o = self._opts()
        out = o["out"].strip()
        if not out or not self._smart_copy_eligible(items, o, out):
            return r
        src = items[0][0]
        base, ext = os.path.splitext(out)
        sep = len(items) > 1 and self.v_qmode.get() == "sep"
        ranges = [(float(a), float(b)) for (_s, a, b) in items]
        groups = [[rg] for rg in ranges] if sep else [ranges]
        targets = ["%s_%03d%s" % (base, i + 1, ext) for i in range(len(ranges))] if sep else [out]
        classic = r

        def builder():
            ffc = lvt_smartcut.CommandFFmpeg(ff.ffmpeg, getattr(ff, "ffprobe", None) or "ffprobe")
            try:
                probe = ffc.probe(src)
                opts = {"container": "", "overwrite": bool(o.get("overwrite", True)), "vcodec": "copy",
                        "acodec": "copy", "arate": None, "achannels": None, "abitrate": "", "volume": "", "af": ""}
                sj, sfinal, scleanup = lvt_smartcut.build_jobs(ffc, src, groups, None, probe, targets, opts,
                                                               cancel=self.cancel)
            except Exception as ex:
                if str(ex) == "cancelled":
                    raise
                # nem támogatott kodek / forrás: a klasszikus másolásos út
                return classic[0], classic[1], classic[2], False
            if classic[2]:
                try:
                    classic[2]()
                except Exception:
                    pass
            return sj, sfinal, scleanup, True

        return builder, None, None, shown

    def run_lazy(self, ff, builder, out=""):
        """Mint a run_jobs, de a munkák összeállítása (kulcskocka-elemzés) a háttérszálon történik."""
        if self.busy:
            return
        self.busy = True
        self.cancel.clear()
        self.v_prog.set(0.0)
        self.txt_log.delete("1.0", "end")
        self.btn_run.state(["disabled"])
        self.cancel.has_final = True        # amíg a munkák össze nem állnak, nincs részmentés

        def work():
            jobs, final, cleanup = [], None, None
            try:
                jobs, final, cleanup, smart = builder()
                self.cancel.has_final = bool(final)
                if smart:
                    self.q.put((lambda r, e: self._status(_(
                        "Pontos másolásos vágás (Smart): csak a vágásszélek kódolódnak újra, nincs pre-roll.",
                        "Exact stream-copy cut (Smart): only the cut edges are re-encoded, no pre-roll.")), None, None))
                n = len(jobs)
                kept = False
                try:
                    for i, (cmd, total) in enumerate(jobs):
                        ff.run_convert(cmd, total,
                                       lambda fr, i=i: self.q.put((lambda r, e, v=(i + fr) / n: self.v_prog.set(v), None, None)),
                                       lambda s: self.q.put((lambda r, e, s=s: self.txt_log.insert("end", s + "\n"), None, None)),
                                       self.cancel)
                except FFError as e:
                    if str(e) != "cancelled_keep":
                        raise
                    kept = True             # az addig kódolt rész megmaradt: a további munkák és az utómunka kimarad
                if final and not kept:
                    final()
                return "kept" if kept else True
            finally:
                if cleanup:
                    cleanup()

        def done(res, err):
            self.busy = False
            self.btn_run.state(["!disabled"])
            if err:
                msg = str(err)
                self._status(_("Megszakítva, a félkész fájl törölve." if msg == "cancelled" else "Hiba: %s" % msg.splitlines()[-1],
                               "Cancelled, the unfinished file was deleted." if msg == "cancelled" else "Error: %s" % msg.splitlines()[-1]))
                if msg != "cancelled":
                    self.mb.showwarning("FFmpeg", _("Az átalakítás nem sikerült:\n\n", "Conversion failed:\n\n") + msg)
            elif res == "kept":
                self._status(_("Megszakítva – az addig kódolt rész elmentve: ", "Cancelled – the part encoded so far was saved: ") + out)
                self.mb.showinfo("FFmpeg", _("Megszakítva. Az addig kódolt rész (hanggal) elmentve:\n",
                                             "Cancelled. The part encoded so far (with audio) was saved:\n") + out)
            else:
                self.v_prog.set(1.0)
                self._status(_("Kész: ", "Done: ") + out)
                self.mb.showinfo("FFmpeg", _("Kész:\n", "Done:\n") + out)

        self._status(_("Kulcskocka-elemzés és átalakítás folyamatban…", "Analysing keyframes and converting…"))
        self._bg(work, done)

    def _queue_jobs_classic(self, ff):
        """A lista szakaszaiból ffmpeg-munkák; több elemnél: részenként kódolás + egybefűzés. -> (jobs, final, cleanup, out)"""
        items = list(self.queue)
        o = self._opts()
        out = o["out"].strip()
        if not out:
            ext = self._default_ext()       # a kiválasztott kiterjesztés (nem a forrásfájlé)
            out = self.fd.asksaveasfilename(parent=self.parent, defaultextension=ext,
                                            initialfile=os.path.splitext(os.path.basename(items[0][0]))[0] + self.q_suffix + ext)
            if not out:
                return None
            out = os.path.normpath(out)
            self.o["out"].set(out)
        base, ext = os.path.splitext(out)
        tmpdir = None
        if len(items) > 1 and self.v_qmode.get() == "sep":
            # KÜLÖN FÁJLOK: minden szakasz önálló fájl (cél_001, cél_002…), nincs egybefűzés
            jobs = []
            for i, (src, a, b) in enumerate(items):
                oo = dict(o)
                oo.update(src=src, start=fmt_time(a), end=fmt_time(b), out="%s_%03d%s" % (base, i + 1, ext),
                          fx_vf=self.fx_vf(src, a, b), fx_vs=self.fx_vs(src, a, b))
                try:
                    jobs.append(ff.build_convert(oo, b - a))
                except FFError as ex:
                    self.mb.showwarning("FFmpeg", str(ex))
                    return None
            shown = "%s_001%s … %s_%03d%s  (%d %s)" % (base, ext, base, len(items), ext, len(items), _("fájl", "files"))
            return jobs, None, None, shown
        if len(items) > 1 and ff.join_ok(o):
            # ÚJRAKÓDOLÁS: a szakaszok vágása és egybefűzése EGY menetben, egyetlen szűrőgráffal -> a kép és a hang
            # nem csúszhat el az illesztéseknél (a darabonkénti kódolás + concat ezt nem tudta garantálni)
            tmpdir = tempfile.mkdtemp(prefix="lvt_")
            try:
                jl, jv = self._join_args(items)
                cmd, total, _tf = ff.build_join(jl, o, out, tmpdir, vsx=jv)
            except FFError as ex:
                self.mb.showwarning("FFmpeg", str(ex))
                shutil.rmtree(tmpdir, ignore_errors=True)
                return None
            return [(cmd, total)], None, (lambda: shutil.rmtree(tmpdir, ignore_errors=True)), out
        if len(items) == 1:
            targets = [out]
        else:
            tmpdir = tempfile.mkdtemp(prefix="lvt_")
            targets = [os.path.join(tmpdir, "part_%03d%s" % (i + 1, ext)) for i in range(len(items))]
        jobs = []
        for (src, a, b), tg in zip(items, targets):
            oo = dict(o)
            oo.update(src=src, start=fmt_time(a), end=fmt_time(b), out=tg, fx_vf=self.fx_vf(src, a, b), fx_vs=self.fx_vs(src, a, b))
            try:
                jobs.append(ff.build_convert(oo, b - a))
            except FFError as ex:
                self.mb.showwarning("FFmpeg", str(ex))
                if tmpdir:
                    shutil.rmtree(tmpdir, ignore_errors=True)
                return None
        final = cleanup = None
        if tmpdir:
            def final():
                lst = os.path.join(tmpdir, "list.txt")
                with open(lst, "w", encoding="utf-8") as fh:
                    for tg in targets:
                        fh.write("file '%s'\n" % tg.replace("\\", "/").replace("'", "'\\''"))
                cmd = [ff.ffmpeg, "-hide_banner", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                       "-map", "0:v?", "-map", "0:a?", "-c", "copy"]
                if ext.lower() in (".mp4", ".m4v", ".mov"):
                    cmd += ["-movflags", "+faststart"]
                if (o.get("container") or "").strip():
                    cmd += ["-f", o["container"].strip()]
                elif ext.lower() == ".m2ts":
                    cmd += ["-f", "mpegts", "-mpegts_m2ts_mode", "1"]
                ff.run_convert(cmd + [out], None, None, None, self.cancel)

            def cleanup():
                shutil.rmtree(tmpdir, ignore_errors=True)
        return jobs, final, cleanup, out

    def run(self):
        if self.busy:
            return
        if self.queue:
            ff = self._need()
            if not ff:
                return
            if self._fx_active() and self.o["vcodec"].get().strip() in ("copy", ""):
                if not self.mb.askyesno("FFmpeg", _(
                        "A képeffektekhez a videót újra kell kódolni, a „copy” (másolás) nem alkalmazhatja őket.\n\n"
                        "Átállítsam H.264 (libx264, CRF 18) kódolásra?",
                        "Image effects need the video to be re-encoded; \"copy\" cannot apply them.\n\n"
                        "Switch to H.264 (libx264, CRF 18)?")):
                    return
                self.o["vcodec"].set("libx264")
                self.o["preset"].set("medium")
                self.o["crf"].set("18")
                self.o["pix_fmt"].set("yuv420p")
                self.o["vbitrate"].set("")
            r = self._queue_jobs(ff)
            if not r:
                return
            jobs, final, cleanup, out = r
            if callable(jobs):
                self.v_cmd.set(_("Pontos másolásos vágás (Smart): a parancsok az elemzés után állnak össze.",
                                 "Exact stream-copy cut (Smart): commands are built after the analysis."))
                self.run_lazy(ff, jobs, out=out)
                return
            if len(jobs) > 1 and self.o["vcodec"].get().strip() in ("copy", ""):
                if self.v_qmode.get() == "sep":
                    self._status(_("Figyelem: másolásnál a vágás a legközelebbi kulcskockán történik; kocka-pontos vágáshoz "
                                   "válassz újrakódolós beállítást.", "Note: with stream copy cuts snap to keyframes; pick a "
                                   "re-encoding preset for frame-exact cuts."))
                else:
                    self._status(_("Figyelem: másolásnál a vágás a legközelebbi kulcskockán történik; hibamentes egybefűzéshez "
                                   "válassz újrakódolós beállítást.", "Note: with stream copy cuts snap to keyframes; pick a "
                                   "re-encoding preset for a clean join."))
            self.v_cmd.set(cmdline(jobs[0][0]))
            self.run_jobs(ff, jobs, final=final, out=out, cleanup=cleanup)
            return
        ff, cmd, total = self._make_cmd()
        if not cmd:
            return
        self.v_cmd.set(cmdline(cmd))
        self.run_jobs(ff, [(cmd, total)], out=self.o["out"].get())

    def run_jobs(self, ff, jobs, final=None, out="", cleanup=None):
        """Több ffmpeg-parancs egymás után (háttérszálon), közös folyamatjelzővel. A final() az utolsó lépés."""
        if self.busy:
            return
        self.busy = True
        self.cancel.clear()
        self.v_prog.set(0.0)
        self.txt_log.delete("1.0", "end")
        self.btn_run.state(["disabled"])
        self.cancel.has_final = bool(final)
        n = len(jobs)

        def work():
            try:
                kept = False
                try:
                    for i, (cmd, total) in enumerate(jobs):
                        ff.run_convert(cmd, total,
                                       lambda fr, i=i: self.q.put((lambda r, e, v=(i + fr) / n: self.v_prog.set(v), None, None)),
                                       lambda s: self.q.put((lambda r, e, s=s: self.txt_log.insert("end", s + "\n"), None, None)),
                                       self.cancel)
                except FFError as e:
                    if str(e) != "cancelled_keep":
                        raise
                    kept = True             # az addig kódolt rész megmaradt: a további munkák és az utómunka kimarad
                if final and not kept:
                    final()
                return "kept" if kept else True
            finally:
                if cleanup:
                    cleanup()

        def done(res, err):
            self.busy = False
            self.btn_run.state(["!disabled"])
            if err:
                msg = str(err)
                self._status(_("Megszakítva, a félkész fájl törölve." if msg == "cancelled" else "Hiba: %s" % msg.splitlines()[-1],
                               "Cancelled, the unfinished file was deleted." if msg == "cancelled" else "Error: %s" % msg.splitlines()[-1]))
                if msg != "cancelled":
                    self.mb.showwarning("FFmpeg", _("Az átalakítás nem sikerült:\n\n", "Conversion failed:\n\n") + msg)
            elif res == "kept":
                self._status(_("Megszakítva – az addig kódolt rész elmentve: ", "Cancelled – the part encoded so far was saved: ") + out)
                self.mb.showinfo("FFmpeg", _("Megszakítva. Az addig kódolt rész (hanggal) elmentve:\n",
                                             "Cancelled. The part encoded so far (with audio) was saved:\n") + out)
            else:
                self.v_prog.set(1.0)
                self._status(_("Kész: ", "Done: ") + out)
                self.mb.showinfo("FFmpeg", _("Kész:\n", "Done:\n") + out)

        self._status(_("Átalakítás folyamatban…", "Converting…"))
        self._bg(work, done)


# ----------------------------------------------------------------- szerkesztő: videó + időszalag ---

# ---- az ffprobe-ablak (I gomb) megjelenítése: betűtípus, szakaszok, figyelmeztetések ----
INFO_FONT = ("Consolas", 10)


def _fps_text(rate):
    """'50/1' -> '50', '25000/1001' -> '24.975'; hibánál ''."""
    m = re.match(r"^(\d+)/(\d+)$", str(rate or ""))
    if m and int(m.group(2)):
        return "%g" % round(int(m.group(1)) / int(m.group(2)), 3)
    return ""


def probe_summary_lines(info):
    """Az ffprobe-adatok megjelenítési sorai: [(szöveg, stílus)]. Stílus: title, bold, dim vagy üres.
    Streamenként két sor (fejléc: típus és kodek; alatta a részletek), így a sorok nem törnek és nem lógnak ki."""
    lines = []
    fm = info.get("format") or {}
    try:
        dur = "%.2f s" % float(fm.get("duration"))
    except (TypeError, ValueError):
        dur = "? s"
    br = str(fm.get("bit_rate") or "")
    lines.append((fm.get("format_long_name") or fm.get("format_name") or "?", "title"))
    lines.append((dur + (("   ·   %d kb/s" % (int(br) // 1000)) if br.isdigit() else ""), "dim"))
    lines.append(("", ""))
    for s in info.get("streams", []):
        kind = s.get("codec_type") or "?"
        codec = s.get("codec_name") or "?"
        if s.get("profile"):
            codec += " (%s)" % s["profile"]
        lang = (s.get("tags") or {}).get("language")
        if lang:
            codec += " [%s]" % lang
        lines.append(("#%s  %-9s%s" % (s.get("index", "?"), kind, codec), "bold"))
        det = []
        if kind == "video":
            det.append("%sx%s" % (s.get("width") or "?", s.get("height") or "?"))
            if s.get("pix_fmt"):
                det.append(s["pix_fmt"])
            fps = _fps_text(s.get("avg_frame_rate"))
            if fps:
                det.append(fps + " fps")
            if s.get("field_order") not in (None, "", "progressive", "unknown"):
                det.append(s["field_order"])
        elif kind == "audio":
            if s.get("sample_rate"):
                det.append("%s Hz" % s["sample_rate"])
            if s.get("channels"):
                det.append("%s ch" % s["channels"])
            if s.get("channel_layout"):
                det.append(s["channel_layout"])
        sbr = str(s.get("bit_rate") or "")
        if sbr.isdigit():
            det.append("%d kb/s" % (int(sbr) // 1000))
        if det:
            lines.append(("      " + "  ·  ".join(det), ""))
    return lines


def _info_insert(widget, lines):
    """[(szöveg, stílus)] sorait írja a Text widgetbe a stílus-címkékkel."""
    for text, tag in lines:
        widget.insert("end", text + "\n", (tag,) if tag else ())


def _gop_style_lines(text):
    """A gop_text() szövegét sorokra bontja és stílust ad: fejléc, figyelmeztetés (sárga háttér), ✓ sor, megjegyzés."""
    out, warn = [], False
    for ln in (text or "").rstrip("\n").split("\n"):
        s = ln.strip()
        if s.startswith("⚠"):
            warn = True
            out.append((ln, "warn"))
        elif warn and s and ln.startswith("  "):
            out.append((ln, "warn"))
        else:
            warn = False
            if s.startswith("✓"):
                out.append((ln, "ok"))
            elif s.startswith(("GOP (", "Megjegyzés:", "Notes:")):
                out.append((ln, "head"))
            elif s.startswith("•"):
                out.append((ln, "dim"))
            else:
                out.append((ln, ""))
    return out


def _info_tags(w):
    """A Text widget stílusai (az _info_insert ezekre hivatkozik)."""
    f = INFO_FONT[0]
    w.tag_configure("title", font=(f, 12, "bold"), foreground="#0d47a1", spacing3=4)
    w.tag_configure("head", font=(f, 10, "bold"), foreground="#1b5e20", spacing1=10, spacing3=2)
    w.tag_configure("bold", font=(f, 10, "bold"), spacing1=4)
    w.tag_configure("dim", foreground="#666666")
    w.tag_configure("warn", background="#fff3cd", foreground="#7a4b00")
    w.tag_configure("ok", foreground="#1b5e20")


class _LatestWorker:
    """Egy háttérszál, ami mindig csak a LEGUTÓBBI kérést dolgozza fel (a régebbit eldobja, a futó
    ffmpeg-et leállítja). Így húzás közben a kép gyorsan követi az egeret."""

    def __init__(self, work, deliver):
        self.work, self.deliver = work, deliver
        self.cv = threading.Condition()
        self.req = None
        self.proc = None
        self.alive = True
        threading.Thread(target=self._loop, daemon=True).start()

    def submit(self, req):
        with self.cv:
            self.req = req
            p = self.proc
            self.cv.notify()
        if p is not None:
            try:
                p.kill()
            except OSError:
                pass

    def stop(self):
        with self.cv:
            self.alive = False
            self.req = None
            p = self.proc
            self.cv.notify()
        if p is not None:
            try:
                p.kill()
            except OSError:
                pass

    def run(self, args, timeout=120):
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                             creationflags=_NOWIN)
        with self.cv:
            self.proc = p
            newer = self.req is not None
        if newer:
            p.kill()
        try:
            out, err = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            p.communicate()
            raise FFError("timeout")
        finally:
            with self.cv:
                self.proc = None
        if p.returncode != 0:
            lines = err.decode("utf-8", "replace").strip().splitlines()
            raise FFError(lines[-1] if lines else "exit %d" % p.returncode)
        return out

    def _loop(self):
        while True:
            with self.cv:
                while self.req is None and self.alive:
                    self.cv.wait()
                if not self.alive:
                    return
                req, self.req = self.req, None
            try:
                res, err = self.work(req, self), None
            except BaseException as e:      # noqa
                res, err = None, e
            with self.cv:
                newer = self.req is not None
            if not newer and self.alive:
                self.deliver(req, res, err)


class VideoEditor:
    """Avidemux-szerű szerkesztő: élő kép, időszalag hanghullámmal, kocka-pontos léptetés, A/B jelölők,
    szakaszlista és export. Minden kép és hang a felhasználó saját FFmpeg-jéből jön (külön folyamat)."""

    TL_H0 = 90           # kezdeti magasság (induláskor MINIMÁLIS - a kép kapja a hely nagy részét)
    MIN_TL = 70          # legkisebb időszalag-magasság

    @property
    def TL_H(self):
        """Az időszalag aktuális magassága (a kép és a hullám közti elválasztóvonal húzásával változik)."""
        try:
            h = self.tl.winfo_height()
        except Exception:       # noqa
            h = 0
        wv = getattr(self, "v_wave", None)
        if wv is not None and not wv.get():         # csak az idővonal: keskeny sáv
            return h if h >= self.RULER + 6 else self.RULER + 14
        return h if h >= self.MIN_TL else self.TL_H0

    def _wh(self):
        return max(16, self.TL_H - self.RULER - 2)
    RULER = 18
    MAX_W = 960

    def __init__(self, panel, frame):
        self.p, self.f = panel, frame
        self.tk, self.ttk = panel.tk, panel.ttk
        self.ff = None
        self.src = ""
        self.info = None
        self.dur, self.fps = 0.0, 25.0
        self.t = 0.0
        self.A = self.B = None
        self.segs = []
        self._undo = []
        self._redo = []
        self.vs, self.vl = 0.0, 1.0
        self.token = 0
        self.playing = False
        self._play_id = 0
        self._vproc = self._aproc = None
        self._fq = None
        self._pend = None
        self._stop_evt = None
        self._t0 = 0.0
        self._wall0 = None
        self._pending_audio = None
        self._apump = None
        self._first = None
        self._wait0 = 0.0
        self._stop_at = None
        self._drag = None
        self._pan = None                # jobb gombos fogás: (egér x, nézet-kezdet) a kezdéskor
        self._drag_before = None        # az A/B-marker húzás előtti állapot (a Vissza-listához)
        self._tl_saved = None           # az időszalag magassága a hullám kikapcsolása előtt
        self._was_playing = False
        self._wave_img = self._wave_all = None
        self._crops = []
        self._wave_key = None
        self._wave_cache = {}
        self._pk = None                 # hanghullám-burkoló (háttérben készül, gyorsítótárazott), lásd _pk_start
        self._ik = None                 # I-kocka (kulcskocka) elemzés: csak az „I-frame” gomb bekapcsolásakor indul
        self._ik_pending = 0            # a gombnyomás után még teljesítendő ugrás (-1 előző / +1 következő)
        self._smart_pending = None     # Smart cut folytatása az IDR-elemzés befejezése után
        self._wave_state = ""
        self._after_cfg = self._after_wave = None
        self._pW = self._pH = 0
        self._build()
        self.fw = _LatestWorker(self._frame_work, self._frame_deliver)
        self.ww = _LatestWorker(self._wave_work, self._wave_deliver)
        self.f.after_idle(self._smartcut_install_cut_list_controls)

    # ---------------------------------------------------------------- felület
    def _btn(self, parent, text, cmd, width=None, style=None):
        b = self.ttk.Button(parent, text=text, command=cmd, takefocus=False)
        if width:
            b.config(width=width)
        if style:
            b.config(style=style)
        return b

    def _build(self):
        tk, ttk, f, P = self.tk, self.ttk, self.f, self.p
        try:
            ttk.Style().configure("Big.TButton", font=("TkDefaultFont", 12, "bold"))
        except Exception:       # noqa
            pass

        def S(v=""):
            return tk.StringVar(master=f, value=v)

        self.v_time, self.v_total, self.v_frame = S("0:00:00.000"), S("/ 0:00:00.000"), S("")
        self.v_a, self.v_b = S(""), S("")
        self.v_deint = tk.BooleanVar(master=f, value=False)
        self.v_loop = tk.BooleanVar(master=f, value=False)
        self.v_mute = tk.BooleanVar(master=f, value=False)
        self.v_skip = tk.BooleanVar(master=f, value=True)
        self.v_only = tk.BooleanVar(master=f, value=False)      # csak a kivágott (piros) szakaszok lejátszása
        self.v_vol, self.v_off = S("100"), S(str(self.p.cfg.get("av_off", "0")))
        self.v_off.trace_add("write", lambda *a: self._save_off())
        self.v_gain = S("x4")
        self.v_wave = tk.BooleanVar(master=f, value=True)       # hullám mutatása (alapból be)
        self.v_ik = tk.BooleanVar(master=f, value=False)        # I-frame vonalak (alapból ki: betöltéskor nem lassít)

        top = ttk.Frame(f)
        top.pack(fill="x")
        self._btn(top, _("Megnyitás…", "Open…"), self._browse, 11).pack(side="left", padx=(0, 4))
        ttk.Label(top, text=_("Fájl", "File"), width=4).pack(side="left")
        ef = ttk.Entry(top, textvariable=P.v_src)
        ef.pack(side="left", fill="x", expand=True)
        ef.bind("<Return>", lambda e: self.load(True))      # a beírt/beillesztett útvonalat Enterre betölti

        # a kép és a hanghullám közti vonal húzható: az egyik nő, a másik csökken
        self.pw = tk.PanedWindow(f, orient="vertical", sashwidth=7, sashrelief="raised", sashpad=1,
                                 opaqueresize=True, borderwidth=0, height=200)
        self.pw.pack(fill="both", expand=True, pady=3)
        self.vc = tk.Canvas(self.pw, background="#000", highlightthickness=0, height=240, takefocus=1)
        # a panenek kicsi a kért magassága (az alsó gombok/lista így sosem szorulnak ki); a hely nagy részét utólag a kép kapja (_init_sash)
        self.pw.add(self.vc, minsize=90, stretch="always", height=200)
        self.img = tk.PhotoImage(master=self.vc)
        self.vimg = self.vc.create_image(0, 0, image=self.img, anchor="center")
        self.vtxt = self.vc.create_text(10, 10, text="", fill="#bbb", width=520, justify="center")
        self.vc.bind("<Configure>", self._on_vc_cfg)
        self.vc.bind("<Button-1>", lambda e: self.vc.focus_set())
        self.vc.bind("<MouseWheel>", self._vc_wheel)
        self.vc.bind("<Button-4>", lambda e: self._vc_wheel(e, 1))
        self.vc.bind("<Button-5>", lambda e: self._vc_wheel(e, -1))

        tlf = self._tlf = ttk.Frame(self.pw)
        # induláskor az időszalag/hullám csak a minimális magasságát kapja
        self.pw.add(tlf, minsize=self.MIN_TL + 20, stretch="never", height=self.TL_H0 + 20)
        self.tl = tk.Canvas(tlf, height=self.TL_H0, background="#111", highlightthickness=1,
                            highlightbackground="#333", takefocus=1)
        self.tl.pack(fill="both", expand=True, pady=(2, 0))
        self.sb = ttk.Scrollbar(tlf, orient="horizontal", command=self._xview)
        self.sb.pack(fill="x", pady=(0, 2))
        self.tl.bind("<Configure>", self._on_tl_cfg)
        self.tl.bind("<Button-1>", self._tl_press)
        self.tl.bind("<B1-Motion>", self._tl_move)
        self.tl.bind("<ButtonRelease-1>", self._tl_release)
        for b in (("2", "3") if sys.platform == "darwin" else ("3",)):      # jobb gomb (macOS-en a 2-es)
            self.tl.bind("<ButtonPress-%s>" % b, self._pan_press)
            self.tl.bind("<B%s-Motion>" % b, self._pan_move)
            self.tl.bind("<ButtonRelease-%s>" % b, self._pan_release)
        self.tl.bind("<MouseWheel>", self._tl_wheel)
        self.tl.bind("<Button-4>", lambda e: self._tl_wheel(e, 1))
        self.tl.bind("<Button-5>", lambda e: self._tl_wheel(e, -1))
        # biztosan a minimális magasságon induljon (néhány Tk verzió a "height" pane-opciót csak
        # kezdeti javaslatként veszi figyelembe) - ezért explicit módon is beállítjuk a választóvonalat,
        # amint a panedwindow már ki van mérve.
        self._sash_done = False
        self.pw.bind("<Configure>", lambda e: self._init_sash())
        self.f.after(80, self._init_sash)

        r = ttk.Frame(f)
        r.pack(fill="x", pady=2)
        for txt, fn, w in (("|<", lambda: self.goto(0.0), 3), ("-10s", lambda: self.step_s(-10), 5),
                           ("-1s", lambda: self.step_s(-1), 4), ("-1f", lambda: self.step_f(-1), 4)):
            self._btn(r, txt, fn, w).pack(side="left", padx=1)
        self.btn_play = self._btn(r, _("▶ Lejátszás", "▶ Play"), self.toggle, 13)
        self.btn_play.pack(side="left", padx=3)
        for txt, fn, w in (("+1f", lambda: self.step_f(1), 4), ("+1s", lambda: self.step_s(1), 4),
                           ("+10s", lambda: self.step_s(10), 5), (">|", lambda: self.goto(self.dur), 3)):
            self._btn(r, txt, fn, w).pack(side="left", padx=1)
        e = ttk.Entry(r, textvariable=self.v_time, width=13)
        e.pack(side="left", padx=(10, 2))
        e.bind("<Return>", self._time_entered)
        ttk.Label(r, textvariable=self.v_total).pack(side="left")
        ttk.Label(r, textvariable=self.v_frame).pack(side="left", padx=6)
        self._btn(r, "I", self.show_info, 2, style="Big.TButton").pack(side="left", padx=(12, 2))
        self._btn(r, "H", self.show_help, 2, style="Big.TButton").pack(side="left", padx=2)

        m = ttk.Frame(f)
        m.pack(fill="x", pady=2)
        self._btn(m, _("[ Kezdet  (I)", "[ In  (I)"), self.set_a, 13).pack(side="left")
        ea = ttk.Entry(m, textvariable=self.v_a, width=13)
        ea.pack(side="left", padx=2)
        ea.bind("<Return>", lambda e: self._marks_typed())
        ea.bind("<FocusOut>", lambda e: self._marks_typed())
        self._btn(m, _("Vég  (O) ]", "Out  (O) ]"), self.set_b, 12).pack(side="left", padx=(8, 0))
        eb = ttk.Entry(m, textvariable=self.v_b, width=13)
        eb.pack(side="left", padx=2)
        eb.bind("<Return>", lambda e: self._marks_typed())
        eb.bind("<FocusOut>", lambda e: self._marks_typed())
        self._btn(m, "→A", lambda: self.goto(self.A), 4).pack(side="left", padx=(8, 1))
        self._btn(m, "→B", lambda: self.goto(self.B), 4).pack(side="left", padx=1)
        self._btn(m, _("▶ A–B", "▶ A-B"), self.play_ab, 7).pack(side="left", padx=4)
        self._btn(m, _("✂ A–B kivágása  (P)", "✂ Cut A-B  (P)"), self.cut_remove, 20).pack(side="left", padx=(12, 1))
        self._btn(m, "⟲", self.undo, 3).pack(side="left", padx=(8, 1))
        self._btn(m, "⟳", self.redo, 3).pack(side="left", padx=1)
        cg = ttk.Combobox(m, textvariable=self.v_gain, values=["x1", "x2", "x4", "x8", "x16", "x32"], width=4,
                          state="readonly")
        cg.pack(side="right", padx=(0, 8))
        cg.bind("<<ComboboxSelected>>", lambda e: (self._view_changed(), self.vc.focus_set()))
        self.cg = cg
        ttk.Label(m, text=_("Hullám+:", "Gain:")).pack(side="right", padx=(8, 2))
        ttk.Checkbutton(m, text=_("Hullám mutatása", "Show waveform"), variable=self.v_wave, takefocus=False,
                        command=self._wave_toggled).pack(side="right", padx=(8, 4))

        o = ttk.Frame(f)
        o.pack(fill="x", pady=2)
        ttk.Checkbutton(o, text=_("Kivágások lejátszása", "Play cuts only"), variable=self.v_only, takefocus=False,
                        command=self._only_toggled).pack(side="left")
        ttk.Checkbutton(o, text=_("A–B ismétlés", "Loop A-B"), variable=self.v_loop, takefocus=False).pack(side="left", padx=8)
        ttk.Checkbutton(o, text=_("Néma", "Mute"), variable=self.v_mute, takefocus=False,
                        command=self._mute_toggled).pack(side="left")
        ttk.Checkbutton(o, text=_("Kivágások átugrása", "Skip cuts"), variable=self.v_skip, takefocus=False,
                        command=self._skip_toggled).pack(side="left", padx=8)
        ttk.Label(o, text=_("Hangerő %", "Volume %")).pack(side="left", padx=(10, 2))
        ttk.Entry(o, textvariable=self.v_vol, width=4).pack(side="left")
        ttk.Label(o, text=_("Hang–kép igazítás (ms)", "A/V offset (ms)")).pack(side="left", padx=(10, 2))
        ttk.Entry(o, textvariable=self.v_off, width=6).pack(side="left")
        ttk.Button(o, text=_("Szinkron-teszt", "Sync test"), command=self.sync_test, takefocus=False).pack(side="left", padx=4)
        # I-frame: bekapcsolva élénk sárga vonalak jelzik a kulcskockákat az idősávon / hullámon.
        # Az elemzés CSAK a bekapcsoláskor indul (betöltéskor nem lassít). A két nyíl az I-kockákra ugrik.
        # Valódi gomb (mint a többi): az állapotot a ☐ / ☑ jel mutatja a szövegben, a v_ik változót követi
        # (az Info ablak és a hibakezelés is átállíthatja).
        self.btn_ik = self._btn(o, "☐ I-frame", lambda: (self.v_ik.set(not self.v_ik.get()), self._ik_toggled()), 11)
        self.btn_ik.pack(side="left", padx=(8, 2))
        self.v_ik.trace_add("write", lambda *a: self.btn_ik.config(text=("☑ I-frame" if self.v_ik.get() else "☐ I-frame")))
        self._btn(o, "◀ I", lambda: self._ik_step(-1), 5).pack(side="left", padx=1)
        self._btn(o, "I ▶", lambda: self._ik_step(1), 5).pack(side="left", padx=1)
        self._btn(o, "+", lambda: self._zoom(1 / 1.6, self.t), 3).pack(side="right")
        self._btn(o, "-", lambda: self._zoom(1.6, self.t), 3).pack(side="right", padx=2)
        self._btn(o, _("Teljes", "Fit"), self._zoom_fit, 7).pack(side="right", padx=2)
        ttk.Label(o, text=_("Időszalag zoom:", "Timeline zoom:")).pack(side="right", padx=4)

        g = ttk.LabelFrame(f, text=_("Kivágott szakaszok (a „✂ A–B kivágása” gombbal vehetők fel)", "Cut-out segments (added with the Cut A-B button)"), padding=4)
        g.pack(fill="x", pady=3)
        self.tree = ttk.Treeview(g, columns=("n", "s", "e", "l"), show="headings", height=6)
        for c, t, w in (("n", "#", 30), ("s", _("Kezdet", "Start"), 110), ("e", _("Vég", "End"), 110), ("l", _("Hossz", "Length"), 90)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)       # a gombsor magasságához igazodik
        self.tree.bind("<Double-1>", lambda e: self.seg_load())
        self.tree.bind("<Delete>", lambda e: self.seg_del())
        self.tree.bind("<BackSpace>", lambda e: self.seg_del())
        self.tree.bind("<Delete>", self._seg_del_many)
        self.tree.bind("<BackSpace>", self._seg_del_many)
        self.tree.bind("<Control-a>", self._tree_select_all)
        self.tree.bind("<Control-A>", self._tree_select_all)
        self.tree.bind("<Escape>", self._tree_clear_sel)
        self.tree.bind("<Return>", self._seg_enter)
        bb = ttk.Frame(g)
        bb.pack(side="left", padx=6)
        self._btn(bb, _("Betöltés A–B-be", "Load into A-B"), self.seg_load, 18).pack(fill="x", pady=1)
        self._btn(bb, _("Törlés (Delete)", "Delete"), self.seg_del, 18).pack(fill="x", pady=1)
        ex = ttk.Frame(g)
        ex.pack(side="left", padx=6)
        self._btn(ex, _("→ Kijelöltek az Átalakításra", "→ Selected to Convert tab"), self.to_convert, 30).pack(fill="x", pady=1)
        self._btn(ex, _("→ Kijelöltek a Képeffektekre", "→ Selected to Image effects"), self.to_effects, 30).pack(fill="x", pady=1)
        self._btn(ex, _("Kivágottak: külön fájlok", "Cut-outs: separate files"), lambda: self.export("sep"), 30).pack(fill="x", pady=1)
        self._btn(ex, _("Kivágottak: egy fájlba", "Cut-outs: one file"), lambda: self.export("join"), 30).pack(fill="x", pady=1)
        self._btn(ex, _("Teljes fájl a kivágások NÉLKÜL", "Whole file WITHOUT the cut-outs"), lambda: self.export("rest"), 30).pack(fill="x", pady=1)
        pr = ttk.Frame(f)
        pr.pack(fill="x", pady=2)
        ttk.Progressbar(pr, variable=P.v_prog, maximum=1.0).pack(side="left", fill="x", expand=True)
        self._btn(pr, _("Megszakít", "Cancel"), P.request_cancel, 11).pack(side="left", padx=4)
        self.f.winfo_toplevel().bind("<KeyPress>", self._key, add="+")
        self.f.winfo_toplevel().bind("<Control-o>", lambda e: (self._browse(), "break")[1], add="+")
        self._msg(_("Kapcsold be a modult a Beállítás fülön, majd válassz videót.",
                    "Enable the module on the Setup tab, then choose a video."))

    def _init_sash(self):
        """Induláskor a kép kapja a hely nagy részét, az időszalag/hullám a MINIMÁLIS magasságú legyen.
        Az első olyan méretezéskor fut le, amikor a panedwindow már ténylegesen kimért (egyszer)."""
        if self._sash_done:
            return
        try:
            h = self.pw.winfo_height()
            if h > self.MIN_TL + 140:
                self.pw.sash_place(0, 0, h - (self.MIN_TL + 20))
                self._sash_done = True
        except Exception:       # noqa
            pass

    def _msg(self, s):
        self.vc.itemconfigure(self.vtxt, text=s)
        self.vc.coords(self.vtxt, max(60, self.vc.winfo_width() // 2), max(30, self.vc.winfo_height() // 2))

    def _status(self, s):
        self.p._status(s)

    def _browse(self):
        p = self.p.fd.askopenfilename(parent=self.p.parent, filetypes=[
            ("Video", "*.mts *.m2ts *.ts *.mkv *.webm *.mp4 *.m4v *.mov *.avi"), ("*", "*.*")])
        if p:
            self.p.v_src.set(os.path.normpath(p))
            self.p._probe = None
            self.load(True)

    # ---------------------------------------------------------------- betöltés
    def _setup_ok(self):
        P = self.p
        if not P.v_enabled.get():
            self._msg(_("Kapcsold be a modult a Beállítás fülön.", "Enable the module on the Setup tab."))
            return False
        pth = P.v_ffmpeg.get().strip()
        if not pth or not os.path.isfile(pth):
            self._msg(_("Az ffmpeg elérési útja hiányzik vagy hibás (Beállítás fül).",
                        "ffmpeg path is missing or wrong (Setup tab)."))
            return False
        self.ff = FFmpeg(pth, P.v_ffprobe.get().strip(), P.v_ffplay.get().strip())
        return True

    def on_show(self):
        self.vc.focus_set()
        P = self.p
        if self.info:
            a, b = parse_time(P.v_start.get()), parse_time(P.v_end.get())
            if (a, b) != (self.A, self.B) and (a is not None or b is not None):
                self.A, self.B = a, b
                self._marks_changed(push=False)
        if self.info is None or self.src != P.v_src.get().strip():
            self.load()

    def load(self, force=False):
        P = self.p
        src = P.v_src.get().strip()
        if not self._setup_ok():
            return
        if not src or not os.path.isfile(src):
            self._msg(_("Válassz videófájlt (…).", "Choose a video file (...)."))
            return
        if not force and self.info and src == self.src:
            return
        self.pause(quiet=True)
        self.token += 1
        self._pk_cancel()
        self._smart_pending = None
        self._ik_reset()         # az I-frame elemzés betöltéskor NEM indul: csak a gomb bekapcsolásakor
        token, ff = self.token, self.ff
        self._msg(_("Fájl betöltése…", "Loading file…"))

        def done(info, err):
            if token != self.token:
                return
            if err:
                self._msg(_("Hiba: %s", "Error: %s") % err)
                return
            if src != self.src:
                self._undo.clear()
                self._redo.clear()
            self.src, self.info = src, info
            self.dur = max(0.0, info["duration"])
            self.fps = info["fps"] if info["fps"] > 0 else 25.0
            self.vs, self.vl = 0.0, max(1.0, self.dur)
            self.t = self._snap(parse_time(P.v_t.get()) or 0.0)
            self.A, self.B = parse_time(P.v_start.get()), parse_time(P.v_end.get())
            if self.B is not None and self.A is not None and self.B <= self.A:
                self.B = None
            self.v_deint.set(False)      # az előnézet mindig a videó eredeti állapotát mutatja (nincs automatikus deinterlace)
            self.v_total.set("/ " + fmt_time(self.dur))
            self._msg("" if info["w"] else _("Nincs képfolyam a fájlban (csak hang).", "No video stream (audio only)."))
            self._marks_changed(push=False)
            self._update_time()
            self._pk_start()
            self._view_changed()
            self._request_frame()
            ae = "" if (ff.ffplay or not info["audio"]) else _("  (Hanghoz add meg az ffplay-t a Beállításban.)",
                                                           "  (Set ffplay in Setup for sound.)")
            self._status(_("Betöltve: %dx%d, %.3f kocka/mp, %s", "Loaded: %dx%d, %.3f fps, %s") %
                         (info["w"], info["h"], self.fps, fmt_time(self.dur)) + ae)

        P._bg(lambda: ff.quick_info(src), done)

    # ---------------------------------------------------------------- idő, nézet
    def _snap(self, t):
        last = max(0.0, (round(self.dur * self.fps) - 1) / self.fps) if self.dur else max(0.0, t)
        return min(max(0.0, round(t * self.fps) / self.fps), last)

    def _tw(self):
        return max(60, self.tl.winfo_width() - 2)

    def _tx(self, t):
        return (t - self.vs) / self.vl * self._tw()

    def _xt(self, x):
        return self.vs + x / self._tw() * self.vl

    def _update_time(self):
        self.v_time.set(fmt_time(self.t))
        self.v_frame.set(_("kocka #%d", "frame #%d") % round(self.t * self.fps))
        x = self._tx(self.t)
        self.tl.coords("ph", x, 0, x, self.TL_H)

    def _set_t(self, t, fetch=True, follow=True):
        self.t = self._snap(t)
        if follow and self.info and self._pan is None and (self.t < self.vs or self.t > self.vs + self.vl):
            self.vs = min(max(0.0, self.t - 0.1 * self.vl), max(0.0, self.dur - self.vl))
            self._view_changed()
        self._update_time()
        if fetch:
            self._request_frame()

    def goto(self, t):
        if t is None or not self.info:
            return
        self.pause(quiet=True)
        self._set_t(t)

    def step_f(self, n):
        if self.info:
            self.pause(quiet=True)
            self._set_t(self.t + n / self.fps)

    def step_s(self, s):
        if self.info:
            self.pause(quiet=True)
            self._set_t(self.t + s)

    def _time_entered(self, _e=None):
        t = parse_time(self.v_time.get())
        if t is not None:
            self.goto(t)
        self.vc.focus_set()

    # ---- az időszalag jobb gombos "megfogása": a nézet balra-jobbra húzható, közben zárt kéz kurzor ----
    def _set_tl_cursor(self, grab):
        try:
            self.tl.configure(cursor=grab_cursor_spec() if grab else "")
        except self.tk.TclError:
            _GRAB["spec"] = "fleur"
            try:
                self.tl.configure(cursor="fleur" if grab else "")
            except self.tk.TclError:
                pass

    def _pan_press(self, e):
        if not self.info:
            return "break"
        self.tl.focus_set()
        self._pan = (e.x, self.vs)
        self._set_tl_cursor(True)
        return "break"

    def _pan_move(self, e):
        if self._pan is None or not self.info:
            return
        x0, vs0 = self._pan
        self.vs = vs0 - (e.x - x0) / float(self._tw()) * self.vl      # a tartalom követi az egeret
        self._view_changed()

    def _pan_release(self, _e):
        self._pan = None
        self._set_tl_cursor(False)

    # ---- hullám mutatása / elrejtése: kikapcsolva csak az idővonal (keskeny sáv) marad, a kép megkapja a helyet ----
    def _set_tl_height(self, ch):
        """Az időszalag (vászon) magasságát ch képpontra állítja a kép és a szalag közti választóvonal mozgatásával."""
        try:
            self.pw.update_idletasks()
            if self.pw.winfo_height() < 100:
                return
            self.pw.paneconfigure(self._tlf, minsize=min(ch, self.MIN_TL))
            for _i in range(2):             # a vászon tényleges magasságából számoljuk a szükséges elmozdulást
                x, y = self.pw.sash_coord(0)
                self.pw.sash_place(0, x, y + (self.tl.winfo_height() - ch))
                self.pw.update_idletasks()
            if ch >= self.MIN_TL:
                self.pw.paneconfigure(self._tlf, minsize=self.MIN_TL + 20)
        except Exception:       # noqa
            pass

    def _wave_toggled(self):
        on = self.v_wave.get()
        try:
            self.cg.configure(state="readonly" if on else "disabled")
        except Exception:       # noqa
            pass
        if on:
            self._set_tl_height(self._tl_saved or self.TL_H0)
            if self.info and (not self._pk or self._pk["src"] != self.src):
                self._pk_start()
            self._wave_img = self._wave_all = None
        else:
            cur = self.tl.winfo_height()
            if cur >= self.MIN_TL:
                self._tl_saved = cur
            self._set_tl_height(self.RULER + 14)
            self._after_wave and self.f.after_cancel(self._after_wave)
            self._after_wave = None
        self.f.after(60, lambda: (self._view_changed(), self._request_frame() if self.info and not self.playing else None))

    def _view_changed(self):
        self.vl = min(max(self.vl, 0.5), max(1.0, self.dur))
        self.vs = min(max(0.0, self.vs), max(0.0, self.dur - self.vl))
        if not (self._wave_all is not None and self._wave_key and self._wkey()[1:] == self._wave_key[1:]):
            self._wave_img = self._wave_all = None      # más nagyítás -> új hullám kell; csak eltolás -> a régi kép elcsúsztatva látszik
        self._draw_tl()
        if self._after_wave:
            try:
                self.f.after_cancel(self._after_wave)
            except Exception:       # noqa
                pass
        self._after_wave = self.f.after(250, self._request_wave)

    def _xview(self, *a):
        """A görgetősáv parancsa: az időszalag nézetének mozgatása balra-jobbra."""
        if not self.info or not self.dur:
            return
        if a[0] == "moveto":
            self.vs = float(a[1]) * self.dur
        elif a[0] == "scroll":
            n = int(a[1])
            self.vs += n * (0.9 if a[2] == "pages" else 0.1) * self.vl
        self._view_changed()

    def _zoom(self, factor, center):
        if not self.info:
            return
        rel = (center - self.vs) / self.vl if self.vl else 0.5
        rel = min(max(rel, 0.0), 1.0)
        nvl = min(max(self.vl * factor, 0.5), max(1.0, self.dur))
        self.vs = center - rel * nvl
        self.vl = nvl
        self._view_changed()

    def _zoom_fit(self):
        self.vs, self.vl = 0.0, max(1.0, self.dur)
        self._view_changed()

    # ---------------------------------------------------------------- időszalag rajzolása
    def _wkey(self):
        return (round(self.vs, 3), round(self.vl, 3), self._tw(), self.v_gain.get(), self.TL_H)

    def _draw_tl(self):
        c, W, H = self.tl, self._tw(), self.TL_H
        c.delete("all")
        c.create_rectangle(0, 0, W + 2, H, fill="#111", outline="")
        if not self.info:
            return
        if self.dur:
            self.sb.set(self.vs / self.dur, min(1.0, (self.vs + self.vl) / self.dur))
        top = self.RULER
        regions = [(a, b, "#5a1c1c", "#e05555", 2) for a, b in self.segs]
        if self.A is not None and self.B is not None:
            regions.append((self.A, self.B, "#5a4510", "#ffcc33", 1))
        spans = []
        for a, b, bg, edge, band in regions:       # háttér: a hullám MÖGÖTT, teljes magasságban
            x1, x2 = max(0, int(self._tx(a))), min(W, int(self._tx(b)))
            if x2 > x1:
                c.create_rectangle(x1, top, x2, H - 2, fill=bg, outline="")
                spans.append((x1, x2, edge, band))
        self._crops = []
        off = None                                   # a kész hullámkép vízszintes eltolása (0 = pontosan a mostani nézet)
        if self.v_wave.get() and self._wave_img is not None and self._wave_all is not None and self._wave_key:
            if self._wave_key == self._wkey():
                off = 0
            elif self._wave_key[1:] == self._wkey()[1:]:        # csak a nézet-kezdet változott (mozgatás): elcsúsztatjuk
                off = int(round((self._wave_key[0] - self.vs) / self.vl * W))
        if off is not None:
            iw = self._wave_all.width()
            c.create_image(off, top, image=self._wave_img, anchor="nw")
            for x1, x2, edge, band in spans:         # a kijelölésen belüli hullám más, élénk színű
                ix1, ix2 = max(x1, off), min(x2, off + iw, W)
                if ix2 > ix1:
                    piece = self._crop(band, ix1 - off, ix2 - off)
                    self._crops.append(piece)
                    c.create_image(ix1, top, image=piece, anchor="nw")
        elif self.v_wave.get():
            c.create_text(W // 2, top + (H - top) // 2, fill="#555", text=self._wave_state)
        for x1, x2, edge, band in spans:
            c.create_line(x1, top, x1, H - 2, fill=edge)
            c.create_line(x2, top, x2, H - 2, fill=edge)
        pk = self._pk
        if self.v_wave.get() and pk and pk["running"]:
            c.create_text(W - 6, top + 3, anchor="ne", fill="#bbbbbb",
                          text=_("hanghullám elemzése: %d %%", "analysing audio: %d %%") % int(pk["frac"] * 100))
        px = W / self.vl
        step = next((s for s in (0.04, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600)
                     if s * px >= 90), 3600)
        tt = int(self.vs / step) * step
        while tt <= self.vs + self.vl + step:
            if tt >= self.vs:
                x = self._tx(tt)
                c.create_line(x, 0, x, top, fill="#777")
                s = fmt_time(tt)
                c.create_text(x + 3, 2, anchor="nw", fill="#aaa", font=("TkDefaultFont", 8),
                              text=s[:-4] if step >= 1 else s)
            tt += step
        if self.v_ik.get():                          # I-kockák: élénk sárga vonalak (a hullám fölött, a jelölők alatt)
            ts = self._ik_times()
            if ts:
                i0 = bisect.bisect_left(ts, self.vs - 0.5)
                i1 = bisect.bisect_right(ts, self.vs + self.vl + 0.5)
                seen = set()
                for tt in ts[i0:i1]:
                    x = self._tx(tt)
                    if x < -1 or x > W + 1:
                        continue
                    colx = int(x // 3)               # sűrű (kicsinyített) nézetben 3 képpontonként egy vonal elég
                    if colx in seen:
                        continue
                    seen.add(colx)
                    c.create_line(x, top, x, H - 2, fill="#ffee00")
            ik = self._ik
            if ik and ik["running"]:
                c.create_text(6, top + 3, anchor="nw", fill="#ffee00",
                              text=_("I-kockák keresése: %d %%", "looking for I-frames: %d %%") % int(ik["frac"] * 100))
        for name, val, col in (("A", self.A, "#33dd66"), ("B", self.B, "#ffaa33")):
            if val is not None:
                x = self._tx(val)
                c.create_line(x, 0, x, H, fill=col, width=2)
                c.create_text(x + (-8 if name == "B" else 8), top + 8, text=name, fill=col, font=("TkDefaultFont", 9, "bold"))
        x = self._tx(self.t)
        c.create_line(x, 0, x, H, fill="#ff3333", width=2, tags="ph")

    # ---------------------------------------------------------------- időszalag egér
    def _tl_press(self, e):
        self.tl.focus_set()
        if not self.info:
            return
        self._drag = "seek"
        self._drag_before = None
        for name, val in (("A", self.A), ("B", self.B)):
            if val is not None and abs(self._tx(val) - e.x) <= 6:
                self._drag = name
                self._drag_before = self._snap_state()     # az A/B-marker húzása is visszavonható
                break
        self._was_playing = self.playing
        if self.playing:
            self.pause(quiet=True)
        self._tl_move(e)

    def _tl_move(self, e):
        if not self.info or not self._drag:
            return
        t = self._snap(self._xt(min(max(e.x, 0), self._tw())))
        if self._drag == "A":
            if self.B is None or t < self.B:
                self.A = t
        elif self._drag == "B":
            if self.A is None or t > self.A:
                self.B = t
        if self._drag in ("A", "B"):
            self._marks_changed()
        self._set_t(t, follow=False)

    def _tl_release(self, _e):
        if self._drag_before is not None:
            self._record(self._drag_before)
            self._drag_before = None
        self._drag = None
        if self._was_playing:
            self._was_playing = False
            self.play()

    def _wheel_dir(self, e, d=None):
        if d is not None:
            return d
        return 1 if e.delta > 0 else -1

    def _tl_wheel(self, e, d=None):
        if not self.info:
            return
        d = self._wheel_dir(e, d)
        if e.state & 1:         # Shift: görgetés
            self.vs += -d * 0.2 * self.vl
            self._view_changed()
        else:
            self._zoom(1 / 1.4 if d > 0 else 1.4, self._xt(e.x))

    def _vc_wheel(self, e, d=None):
        d = self._wheel_dir(e, d)
        if e.state & 1:
            self.step_s(d)
        else:
            self.step_f(d)

    def _on_tl_cfg(self, _e):
        if self._after_cfg:
            try:
                self.f.after_cancel(self._after_cfg)
            except Exception:       # noqa
                pass
        self._after_cfg = self.f.after(200, self._cfg_settled)

    def _on_vc_cfg(self, _e):
        self._on_tl_cfg(_e)
        self.vc.coords(self.vimg, self.vc.winfo_width() // 2, self.vc.winfo_height() // 2)
        self.vc.coords(self.vtxt, max(60, self.vc.winfo_width() // 2), max(30, self.vc.winfo_height() // 2))

    def _cfg_settled(self):
        self._after_cfg = None
        if self.info:
            self._view_changed()
            if not self.playing:
                self._request_frame()

    # ---------------------------------------------------------------- jelölők, szakaszok
    def set_a(self):
        if not self.info:
            return
        before = self._snap_state()
        if self.B is not None and self.t >= self.B:
            self.B = None
        self.A = self.t
        self._marks_changed()
        self._record(before)

    def set_b(self):
        if not self.info:
            return
        if self.A is not None and self.t <= self.A:
            self._status(_("A vég nem lehet a kezdet előtt.", "End must be after start."))
            return
        before = self._snap_state()
        self.B = self.t
        self._marks_changed()
        self._record(before)

    def clear_marks(self):
        before = self._snap_state()
        self.A = self.B = None
        self._marks_changed()
        self._record(before)

    # ---------------------------------------------------------------- vágás, visszavonás
    def _snap_state(self):
        """A visszavonható állapot: a kivágott szakaszok listája + az A–B jelölés."""
        return (tuple(self.segs), self.A, self.B)

    def _record(self, before):
        """Ha a művelet megváltoztatta az állapotot, az ELŐTTI állapot a Vissza-listára kerül (üres művelet nem)."""
        if self._snap_state() != before:
            self._undo.append(before)
            if len(self._undo) > 200:
                del self._undo[0]
            self._redo.clear()

    def _apply_state(self, st):
        self.segs = list(st[0])
        self.A, self.B = st[1], st[2]
        self._marks_changed()
        self._refresh_segs()

    @staticmethod
    def _diff_name(a, b):
        parts = []
        if a[0] != b[0]:
            parts.append(_("szakasz-lista", "segment list"))
        if (a[1], a[2]) != (b[1], b[2]):
            parts.append(_("A–B jelölés", "A-B selection"))
        return ", ".join(parts)

    @staticmethod
    def _merge(rngs):
        out = []
        for a, b in sorted(rngs):
            if out and a <= out[-1][1] + 1e-3:
                out[-1] = (out[-1][0], max(out[-1][1], b))
            else:
                out.append((a, b))
        return out

    def cut_remove(self):
        """A kijelölt A–B darabot a KIVÁGOTT szakaszok listájára teszi (az egymást átfedők összeolvadnak).
        A fájl nem változik; az exportnál választható: a darabok külön / egy fájlban, vagy a TELJES fájl
        ezek nélkül."""
        if not self.info:
            self._status(_("Előbb tölts be egy videót.", "Load a video first."))
            return
        if self.A is None or self.B is None or self.B <= self.A:
            self._status(_("Előbb jelöld ki a kivágandó részt (A és B).", "Mark the range to cut first (A and B)."))
            return
        before = self._snap_state()
        a, b = self.A, self.B
        self.segs = self._merge(self.segs + [(a, b)])
        self.A = self.B = None
        self._marks_changed()
        self._refresh_segs()
        self._record(before)
        self._status(_("Kivágva a listára: %s – %s (összesen %d szakasz).",
                       "Added to the cut list: %s - %s (%d segments).") % (fmt_time(a), fmt_time(b), len(self.segs)))

    def undo(self):
        if not self._undo:
            self._status(_("Nincs mit visszavonni.", "Nothing to undo."))
            return
        cur = self._snap_state()
        st = self._undo.pop()
        self._redo.append(cur)
        self._apply_state(st)
        self._status(_("Visszavonva: %s.", "Undone: %s.") % self._diff_name(cur, st))

    def redo(self):
        if not self._redo:
            self._status(_("Nincs mit mégis végrehajtani.", "Nothing to redo."))
            return
        cur = self._snap_state()
        st = self._redo.pop()
        self._undo.append(cur)
        self._apply_state(st)
        self._status(_("Újra végrehajtva: %s.", "Redone: %s.") % self._diff_name(cur, st))

    # ---------------------------------------------------------------- infó / súgó gombok
    def show_info(self):
        if not self.info:
            self.p.mb.showinfo("Info", _("Nincs betöltött fájl – előbb tölts be egy videót.",
                                         "No file loaded - load a video first."), parent=self.f.winfo_toplevel())
            return
        if not self._setup_ok():
            return
        src, ff = self.src, self.ff
        win = self.tk.Toplevel(self.f)
        win.title(_("Fájl adatai (ffprobe)", "File info (ffprobe)"))
        win.geometry("740x560")
        txtw = self.tk.Text(win, wrap="word", font=INFO_FONT, padx=16, pady=12, borderwidth=0,
                            highlightthickness=0, spacing1=1, spacing3=1)
        sb = self.ttk.Scrollbar(win, orient="vertical", command=txtw.yview)
        txtw.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txtw.pack(side="left", fill="both", expand=True)
        _info_tags(txtw)
        txtw.insert("end", _("Fájl beolvasása…\n", "Reading file…\n"))

        def work():
            return ff.probe(src)

        def done(info, err):
            txtw.delete("1.0", "end")
            if err or not ff.ffprobe:
                txtw.insert("end", _("Nincs ffprobe megadva, vagy hiba történt: %s\n\nAlap adatok:\n%dx%d, %.3f kocka/mp, "
                                     "%s, hang: %s", "ffprobe not set, or an error occurred: %s\n\nBasic info:\n%dx%d, "
                                     "%.3f fps, %s, audio: %s") % (err or "-", self.info["w"], self.info["h"], self.fps,
                                     fmt_time(self.dur), _("van", "yes") if self.info["audio"] else _("nincs", "no")))
                return
            _info_insert(txtw, probe_summary_lines(info))
            if not self.info.get("w"):
                return
            txtw.insert("end", "\n")
            mark = txtw.index("end-1c")

            def fill_gop():
                try:
                    txtw.delete(mark, "end")
                    ik = self._ik
                    if ik and ik["src"] == src and ik["done"]:
                        _info_insert(txtw, _gop_style_lines(gop_text(gop_stats(ik["t"], self.fps))))
                    elif ik and ik["src"] == src and ik["running"]:
                        txtw.insert("end", _("GOP: elemzés folyamatban (%d %%)…\n", "GOP: analysing (%d %%)…\n")
                                    % int(ik["frac"] * 100))
                    else:
                        txtw.insert("end", _("GOP: az elemzés nem futott le.\n", "GOP: analysis did not run.\n"))
                except self.tk.TclError:        # az ablak közben bezárult
                    self._gop_cb = None

            ik = self._ik
            if not (ik and ik["src"] == src and (ik["done"] or ik["running"])):
                self.v_ik.set(True)             # a GOP méréséhez kellenek az I-kockák: ugyanaz az elemzés, mint az I-frame gomb
                self._ik_start()
            self._gop_cb = fill_gop
            fill_gop()
            if self._ik and self._ik["src"] == src and self._ik["done"]:
                self._gop_cb = None

        self.p._bg(work, done)

    def show_help(self):
        txt = _(
            "Billentyűk:\n"
            "  Szóköz — lejátszás / szünet\n"
            "  ←  /  → — 1 kocka\n"
            "  Shift + ←/→ — 1 mp\n"
            "  Ctrl + ←/→ — 10 mp\n"
            "  I  /  O — kezdet (A) / vég (B) jelölő\n"
            "  P — a kijelölt A–B rész kivágása („✂ A–B kivágása”)\n"
            "  Ctrl + Z / Ctrl + Y — visszavonás / újra\n"
            "  Home / End — az elejére / a végére\n"
            "  Görgő a képen — léptetés kockánként\n"
            "  Görgő az időszalagon — nagyítás/kicsinyítés (Shift = görgetés)\n"
            "  Jobb egérgomb lenyomva az időszalagon + húzás — a hullám balra-jobbra mozgatása (megfogó kéz)\n"
            "  „Hullám mutatása” — kikapcsolva a hullám eltűnik, csak az idővonal marad (a kép megkapja a helyet)\n\n"
            "Szakaszok:\n"
            "  „✂ A–B kivágása” — a kijelölt A–B részt a KIVÁGOTT szakaszok listájára teszi (pirosan látszik "
            "az időszalagon; az átfedők összeolvadnak). A fájl nem változik.\n"
            "  „Kivágások átugrása” — lejátszáskor a piros részeket átugorja, így hallod/látod a végeredményt.\n"
            "  „Kivágások lejátszása” — lejátszáskor CSAK a piros (kivágott) részeket játssza le, egymás után. "
            "A két mód kizárja egymást.\n"
            "  ⟲ / ⟳ — visszavonás / mégis (undo / redo): az A–B jelölésnél (kezdet, vég, húzás, törlés) és a szakaszok "
            "felvételénél, törlésénél is.\n"
            "  Ctrl+A — minden szakasz kijelölése (a bal és az Átalakítás listában is)\n"
            "  Delete / Backspace — a kijelölt szakaszok törlése (több is egyszerre)\n"
            "  Enter — a kijelölt szakasz betöltése A–B-be\n"
            "  Esc — a kijelölés megszüntetése\n"
            "  Ctrl+O — fájl megnyitása\n\n"
            "Mentés:\n"
            "  „Kivágottak: külön fájlok” — minden kivágott darab külön fájlba kerül.\n"
            "  „Kivágottak: egy fájlba” — a kivágott darabok egyetlen fájlba fűzve.\n"
            "  „Teljes fájl a kivágások NÉLKÜL” — az egész fájl egyetlen fájlban, a piros részek nélkül.\n\n"
            "A kódolást az „Átalakítás” fül beállításai adják (kodek, minőség, konténer, stb.).",
            "Keys:\n"
            "  Space — play / pause\n"
            "  Left / Right — 1 frame\n"
            "  Shift + Left/Right — 1 s\n"
            "  Ctrl + Left/Right — 10 s\n"
            "  I / O — set in (A) / out (B) marker\n"
            "  P — cut the selected A-B range ('Cut A-B')\n"
            "  Ctrl + Z / Ctrl + Y — undo / redo\n"
            "  Home / End — go to start / end\n"
            "  Wheel over the picture — step by frame\n"
            "  Wheel over the timeline — zoom in/out (Shift = pan)\n"
            "  Hold the right mouse button on the timeline and drag — pan the waveform left/right (grabbing hand)\n"
            "  'Show waveform' — when off the waveform disappears and only the time ruler remains (the picture gets the space)\n\n"
            "Segments:\n"
            "  'Cut A-B' — adds the selected range to the list of CUT-OUT segments (shown in red on the "
            "timeline; overlapping ones merge). The file itself is not changed.\n"
            "  'Skip cuts' — during playback the red parts are skipped, so you see/hear the final result.\n"
            "  'Play cuts only' — during playback ONLY the red (cut-out) parts are played, one after another. "
            "The two modes are mutually exclusive.\n"
            "  Undo / Redo buttons revert A-B selection changes (set, drag, clear) and segment additions/removals.\n"
            "  Ctrl+A — select all segments (also in the Convert list)\n"
            "  Delete / Backspace — remove the selected segments (several at once)\n"
            "  Enter — load the selected segment into A-B\n"
            "  Esc — clear the selection\n"
            "  Ctrl+O — open a file\n\n"
            "Saving:\n"
            "  'Cut-outs: separate files' — saves every cut-out piece to its own file.\n"
            "  'Cut-outs: one file' — joins the cut-out pieces into a single file.\n"
            "  'Whole file WITHOUT the cut-outs' — the whole file in one piece, without the red parts.\n\n"
            "Encoding uses the settings on the 'Convert' tab (codec, quality, container, etc.).")
        self.p.mb.showinfo(_("Súgó", "Help"), txt, parent=self.f.winfo_toplevel())

    def _marks_changed(self, push=True):
        self.v_a.set("" if self.A is None else fmt_time(self.A))
        self.v_b.set("" if self.B is None else fmt_time(self.B))
        if push:
            self.p.v_start.set(self.v_a.get())
            self.p.v_end.set(self.v_b.get())
        self._draw_tl()

    def _marks_typed(self):
        a, b = parse_time(self.v_a.get()), parse_time(self.v_b.get())
        if self.info:
            a = None if a is None else self._snap(a)
            b = None if b is None else self._snap(b)
        if a is not None and b is not None and b <= a:
            b = None
        if (a, b) != (self.A, self.B):
            before = self._snap_state()
            self.A, self.B = a, b
            self._marks_changed()
            self._record(before)

    def _refresh_segs(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for n, (a, b) in enumerate(self.segs, 1):
            self.tree.insert("", "end", iid=str(n - 1), values=(n, fmt_time(a), fmt_time(b), fmt_time(b - a)))
        self._draw_tl()

    def seg_add(self):
        if self.A is None or self.B is None or self.B <= self.A:
            self._status(_("Előbb jelöld ki a kezdetet és a véget (A és B).", "Set start and end first (A and B)."))
            return
        before = self._snap_state()
        self.segs = self._merge(self.segs + [(self.A, self.B)])
        self.A = self.B = None
        self._marks_changed()
        self._refresh_segs()
        self._record(before)

    def _sel(self):
        s = self.tree.selection()
        return int(s[0]) if s else None

    def seg_load(self):
        i = self._sel()
        if i is None or i >= len(self.segs):
            return
        before = self._snap_state()
        self.A, self.B = self.segs[i]
        self._marks_changed()
        self._record(before)
        self.goto(self.A)

    def seg_del(self):
        i = self._sel()
        if i is not None and i < len(self.segs):
            before = self._snap_state()
            del self.segs[i]
            self._refresh_segs()
            self._record(before)

    # ---------------------------------------------------------------- képkocka és hanghullám (háttérben)
    def _fit(self):
        w0 = (self.info or {}).get("w") or 0
        h0 = (self.info or {}).get("h") or 0
        dar = (w0 * (self.info or {}).get("sar", 1.0) / h0) if w0 and h0 else 16 / 9
        cw, ch = max(160, self.vc.winfo_width() - 4), max(90, self.vc.winfo_height() - 4)
        W, H = cw, cw / dar
        if H > ch:
            H, W = ch, ch * dar
        if W > self.MAX_W:
            W, H = self.MAX_W, self.MAX_W / dar
        return max(16, int(W) // 2 * 2), max(16, int(H) // 2 * 2)

    def _vf(self, W, H, fps=None):
        vf = []
        if self.v_deint.get():
            vf.append("yadif=0:-1:0")
        vf.append("scale=%d:%d:flags=fast_bilinear" % (W, H))
        if fps:
            vf.append("fps=%.6f:start_time=0" % fps)
        return ",".join(vf)

    def _request_frame(self):
        if not self.info or not self.ff or not self.info["w"] or self.playing:
            return
        W, H = self._fit()
        self._pW, self._pH = W, H
        self.fw.submit((self.token, self.src, self.t, W, H, self._vf(W, H)))

    def _frame_work(self, req, wk):
        _tok, src, t, W, H, vf = req
        ss = max(0.0, t - 0.4 / self.fps)
        cmd = [self.ff.ffmpeg, "-v", "error", "-nostdin", "-ss", "%.3f" % ss, "-i", src, "-an", "-sn",
               "-frames:v", "1", "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        data = wk.run(cmd, 60)
        if len(data) != W * H * 3:
            raise FFError("no frame")
        return data

    def _frame_deliver(self, req, res, err):
        self.p.q.put((lambda r, e: self._frame_done(req, r, e), res, err))

    def _frame_done(self, req, data, err):
        if req[0] != self.token or self.playing:
            return
        if err:
            return
        self._blit(data, req[3], req[4])

    def _blit(self, data, W, H):
        try:
            self.img.configure(data=b"P6 %d %d 255\n" % (W, H) + data, format="PPM")
        except self.tk.TclError:
            return
        self.vc.coords(self.vimg, self.vc.winfo_width() // 2, self.vc.winfo_height() // 2)
        self.vc.itemconfigure(self.vtxt, text="")

    # ---- hanghullám: egyszeri háttér-elemzés (burkoló-fájl), mint az Audacity / Premiere "peak" fájlja ----
    # Az egész hangot EGYSZER végigolvassuk (ffmpeg, háttérben), és másodpercenként 100 érték (a hang abszolút
    # értékének átlaga) kerül egy kis gyorsítótár-fájlba. Hosszú nézeteket (>2 perc) innen rajzoljuk (~0,1 mp),
    # így nem kell minden nagyításnál újra végigolvasni a hangot; a fájl megmarad a következő megnyitásra is.
    PK_RATE = 100           # érték / másodperc a burkoló-fájlban
    PK_FAKE = 8000          # ennyi Hz-nek DEKLARÁLJUK a fájlt rajzoláskor (az FFmpeg így percek helyett ms alatt dolgozza fel)
    PK_MIN_VIEW = 120       # ennél hosszabb nézetet rajzolunk a burkolóból; a rövidebbet közvetlenül a hangból

    # ---------------------------------------------------------------- I-kockák (kulcskockák)
    def _ik_cancel(self):
        """A futó I-kocka elemzés leállítása (a már kész lista megmarad a self._ik-ben, ha nem dobjuk el)."""
        ik = self._ik
        if not ik:
            return
        ik["cancel"] = True
        try:
            if ik.get("after"):
                self.f.after_cancel(ik["after"])
        except Exception:       # noqa
            pass
        pr = ik.get("proc")
        if pr is not None and pr.poll() is None:
            try:
                pr.kill()
            except OSError:
                pass

    def _ik_reset(self):
        """Új fájl betöltésekor: elemzés leállítva, lista eldobva, a gomb kikapcsolva (magától semmi nem indul)."""
        self._ik_cancel()
        self._ik = None
        self._ik_pending = 0
        try:
            self.v_ik.set(False)
        except Exception:       # noqa
            pass

    def _ik_times(self):
        """A betöltött fájl eddig megtalált I-kockáinak ideje (mp, a szerkesztő időzítésében), növekvő sorrendben."""
        ik = self._ik
        return ik["t"] if ik and ik["src"] == self.src else []

    def _ik_toggled(self):
        if not self.v_ik.get():
            self._ik_pending = 0
            self._smart_pending = None
            ik = self._ik
            if ik and ik["running"]:            # a félbehagyott elemzést eldobjuk, a kész listát megtartjuk
                self._ik_cancel()
                self._ik = None
            self._draw_tl()
            return
        self._ik_start()

    def _ik_start(self):
        """A kulcskockák kigyűjtése ffprobe-bal a háttérben: csak a csomagok fejlécét olvassa (nincs dekódolás)."""
        if not self.info or not self.ff:
            self.v_ik.set(False)
            return
        ik = self._ik
        if ik and ik["src"] == self.src and (ik["done"] or ik["running"]):
            self._draw_tl()
            return
        if not self.ff.ffprobe:
            self.v_ik.set(False)
            self._status(_("Az I-frame elemzéshez az ffprobe kell (Beállítás fül).",
                           "I-frame analysis needs ffprobe (Setup tab)."))
            return
        self._ik_cancel()
        src, dur, ffp = self.src, self.dur, self.ff.ffprobe
        ik = dict(src=src, t=[], done=False, running=True, failed=False, cancel=False, frac=0.0, proc=None, after=None,
                  idr=False)
        self._ik = ik
        self._status(_("I-kockák keresése…", "Looking for I-frames…"))

        def run():
            ok = False
            try:
                off = 0.0       # az első időbélyeg a fájlban (TS-nél nem 0): ennyit le kell vonni a szerkesztő idejéhez
                codec = ""
                try:
                    txt = self.ff._run([ffp, "-v", "error", "-select_streams", "v:0", "-show_entries",
                                        "stream=start_time,codec_name:format=start_time", "-of", "compact", src], 30)
                    vals = {}
                    for ln in txt.splitlines():
                        parts = ln.strip().split("|")
                        for kv in parts[1:]:
                            k, _eq, v = kv.partition("=")
                            if k == "start_time":
                                try:
                                    vals.setdefault(parts[0], float(v))
                                except ValueError:
                                    pass
                            elif k == "codec_name" and parts[0] == "stream":
                                codec = v.strip().lower()
                    off = vals.get("stream", vals.get("format", 0.0))
                except FFError:
                    off = 0.0
                out = ik["t"]

                # 1. lépés: csak az IGAZI I-kockák (IDR). Az ffprobe „K” jelzője a recovery point (nyílt GOP) képeket is
                # kulcskockának veszi, de azoknál a másolásos (copy) vágás/összefűzés megakad. Ezért a H.264 / HEVC
                # adatfolyamból a filter_units szűrővel csak az IDR NAL-egységeket tartalmazó csomagokat hagyjuk meg
                # (nincs dekódolás, csak a csomagok olvasása), és ezek időbélyegét olvassuk ki.
                idr_types = {"h264": "5", "hevc": "19|20"}.get(codec)
                ffm = getattr(self.ff, "ffmpeg", None)
                if idr_types and ffm:
                    try:
                        cmd = [ffm, "-v", "error", "-nostdin", "-i", src, "-map", "0:v:0", "-c", "copy", "-copyts",
                               "-bsf:v", "filter_units=pass_types=" + idr_types, "-f", "framecrc", "-"]
                        pr = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                              stdin=subprocess.DEVNULL, creationflags=_NOWIN)
                        ik["proc"] = pr
                        tb = 1.0 / 90000
                        for raw in pr.stdout:
                            if ik["cancel"]:
                                break
                            ln = raw.decode("utf-8", "replace").strip()
                            if ln.startswith("#tb"):
                                m = re.search(r"(\d+)\s*/\s*(\d+)\s*$", ln)
                                if m and int(m.group(2)) > 0:
                                    tb = int(m.group(1)) / float(int(m.group(2)))
                                continue
                            if not ln or ln.startswith("#"):
                                continue
                            f = [x.strip() for x in ln.split(",")]
                            if len(f) < 3:
                                continue
                            try:
                                t = int(f[2]) * tb - off        # pts; (dts nem jó: B-képkockáknál előrébb van)
                            except ValueError:
                                continue
                            if t > -0.001:
                                out.append(max(0.0, t))
                            if dur > 0:
                                ik["frac"] = min(0.99, max(0.0, t) / dur)
                        if ik["cancel"] and pr.poll() is None:
                            try:
                                pr.kill()
                            except OSError:
                                pass
                        rc = pr.wait()
                        if ik["cancel"]:
                            raise _IkCancel()
                        if rc == 0 and out:
                            out[:] = sorted(set(round(x, 3) for x in out))
                            ik["idr"] = True
                            ok = True
                    except _IkCancel:
                        raise
                    except Exception:       # noqa  (nem sikerült: visszaesünk a K-jelzős módszerre)
                        pass
                    if not ok:
                        del out[:]
                        ik["frac"] = 0.0
                if ok:
                    ik["running"] = False
                    ik["done"] = True
                    ik["frac"] = 1.0
                    self.p.q.put((lambda r, e: self._ik_finished(ik), None, None))
                    return

                # 2. lépés (tartalék: más kodek, vagy az IDR-keresés nem járt eredménnyel): minden „K” jelzésű csomag
                cmd = [ffp, "-v", "error", "-select_streams", "v:0", "-show_entries",
                       "packet=pts_time,dts_time,flags", "-of", "compact", src]
                pr = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                      creationflags=_NOWIN)
                ik["proc"] = pr
                for raw in pr.stdout:
                    if ik["cancel"]:
                        break
                    ln = raw.decode("utf-8", "replace").strip()
                    if not ln.startswith("packet|"):
                        continue
                    d = {}
                    for kv in ln.split("|")[1:]:
                        k, _eq, v = kv.partition("=")
                        d[k] = v
                    try:
                        ts = float(d.get("pts_time", ""))
                    except ValueError:
                        try:
                            ts = float(d.get("dts_time", ""))
                        except ValueError:
                            continue
                    t = ts - off
                    if "K" in d.get("flags", "") and t > -0.001:
                        out.append(max(0.0, t))
                    if dur > 0:
                        ik["frac"] = min(0.99, max(0.0, t) / dur)
                if ik["cancel"] and pr.poll() is None:
                    try:
                        pr.kill()
                    except OSError:
                        pass
                rc = pr.wait()
                ok = rc == 0 and not ik["cancel"]
                if ok:
                    # a megjelenítési idő szerinti sorrend (B-képkockák miatt a csomagok nem mindig növekvők)
                    srt = sorted(set(round(x, 3) for x in out))
                    out[:] = srt
            except _IkCancel:
                ok = False
            except Exception:       # noqa
                ok = False
            ik["running"] = False
            ik["done"] = ok
            ik["failed"] = (not ok) and not ik["cancel"]
            if ik["frac"] < 1.0 and ok:
                ik["frac"] = 1.0
            if not ik["cancel"]:
                self.p.q.put((lambda r, e: self._ik_finished(ik), None, None))

        threading.Thread(target=run, daemon=True).start()
        ik["after"] = self.f.after(1000, lambda: self._ik_tick(ik))

    def _ik_tick(self, ik):
        """Másodpercenként: a már megtalált I-kockák és a haladás megjelenítése."""
        if ik is not self._ik or not ik["running"]:
            return
        self._draw_tl()
        ik["after"] = self.f.after(1000, lambda: self._ik_tick(ik))

    def _ik_finished(self, ik):
        if ik is not self._ik:
            return
        self._draw_tl()
        if ik["failed"]:
            pending, self._smart_pending = self._smart_pending, None
            self.v_ik.set(False)
            self._ik_pending = 0
            self._status(_("Az I-frame elemzés nem sikerült.", "I-frame analysis failed."))
            if pending is not None:
                self._status(_("A Smart cut IDR-elemzése nem sikerült; normál export használható.",
                               "Smart cut IDR analysis failed; normal export is still available."))
            return
        n = len(ik["t"])
        pre = _("[csak IDR] ", "[IDR only] ") if ik.get("idr") else ""
        self._status(pre + gop_text(gop_stats(ik["t"], self.fps), short=True) if n > 1 else
                     (_("I-kockák: %d db.", "I-frames: %d.") % n if n else
                      _("Ebben a fájlban nem találtam I-kockát.", "No I-frames found in this file.")))
        cb, self._gop_cb = getattr(self, "_gop_cb", None), None
        if cb:
            try:
                cb()                    # az Info ablak GOP-része frissül
            except Exception:       # noqa
                pass
        smart_mode, self._smart_pending = self._smart_pending, None
        if smart_mode is not None:
            if ik.get("idr"):
                self.f.after_idle(lambda mode=smart_mode: self.export_smart(mode))
            else:
                self._status(_("Nem készült csak-IDR lista; a Smart cut nem indul el.",
                               "No IDR-only list was produced; Smart cut will not start."))
        d, self._ik_pending = self._ik_pending, 0
        if d and n:
            self._ik_step(d)

    def _ik_step(self, d):
        """Az előző (d<0) / következő (d>0) I-kockára ugrik. Ha az elemzés még nem futott, elindítja, és utána ugrik."""
        if not self.info:
            return
        ik = self._ik
        ts = self._ik_times()
        if not ts:
            if ik and ik["src"] == self.src and ik["done"]:
                self._status(_("Ebben a fájlban nem találtam I-kockát.", "No I-frames found in this file."))
                return
            self._ik_pending = d
            if not (ik and ik["src"] == self.src and ik["running"]):
                self.v_ik.set(True)
                self._ik_start()
            return
        tol = 0.5 / self.fps
        if d > 0:
            i = bisect.bisect_right(ts, self.t + tol)
            tgt = ts[i] if i < len(ts) else None
        else:
            i = bisect.bisect_left(ts, self.t - tol) - 1
            tgt = ts[i] if i >= 0 else None
        if tgt is None:
            self._status(_("Nincs további I-kocka ebben az irányban.", "No further I-frame in that direction.")
                         + ("" if not (ik and ik["running"]) else
                            _(" (az elemzés még tart)", " (analysis still running)")))
            return
        self.goto(tgt)

    def _pk_dir(self):
        return os.path.join(tempfile.gettempdir(), "lvt_wave")

    def _pk_file(self, src):
        try:
            st = os.stat(src)
            key = "%s|%d|%d|env1" % (os.path.abspath(src), st.st_size, int(st.st_mtime))
        except OSError:
            key = os.path.abspath(src) + "|env1"
        return os.path.join(self._pk_dir(), hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()[:24] + ".env")

    def _pk_prune(self, d):
        """A 30 napnál régebbi gyorsítótár-fájlok és a megszakadt .part fájlok törlése."""
        now = time.time()
        try:
            for n in os.listdir(d):
                fp = os.path.join(d, n)
                try:
                    if (n.endswith(".part") and now - os.path.getmtime(fp) > 3600) or now - os.path.getmtime(fp) > 30 * 86400:
                        os.remove(fp)
                except OSError:
                    pass
        except OSError:
            pass

    def _pk_cancel(self):
        pk, self._pk = self._pk, None
        if not pk:
            return
        pk["cancel"] = True
        try:
            if pk.get("after"):
                self.f.after_cancel(pk["after"])
        except Exception:       # noqa
            pass
        pr = pk.get("proc")
        if pr is not None and pr.poll() is None:
            try:
                pr.kill()
            except OSError:
                pass

    def _pk_start(self):
        """A betöltött videó hangjából burkoló-fájlt készít a háttérben (ha még nincs a gyorsítótárban)."""
        self._pk_cancel()
        info, src = self.info, self.src
        if not info or not info.get("audio") or not self.ff or self.dur <= 0 or not self.v_wave.get():
            return
        final = self._pk_file(src)
        pk = dict(src=src, final=final, part=final + ".part", done=False, running=False, failed=False, cancel=False,
                  frac=0.0, last=-1, proc=None)
        self._pk = pk
        if os.path.isfile(final):                   # már kész (korábbi megnyitásból) -> azonnal használható
            pk["done"], pk["frac"] = True, 1.0
            try:
                os.utime(final, None)
            except OSError:
                pass
            return
        pk["running"] = True
        ffm = self.ff.ffmpeg

        def run():
            ok = False
            try:
                os.makedirs(self._pk_dir(), exist_ok=True)
                self._pk_prune(self._pk_dir())
                cmd = [ffm, "-v", "error", "-nostdin", "-y", "-i", src, "-vn", "-sn", "-dn", "-af",
                       "aformat=channel_layouts=mono:sample_fmts=fltp,aresample=8000,aeval=abs(val(0)):c=same,aresample=%d" % self.PK_RATE,
                       "-f", "s16le", pk["part"]]
                pr = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                      creationflags=_NOWIN)
                pk["proc"] = pr
                rc = pr.wait()
                ok = rc == 0 and not pk["cancel"] and os.path.getsize(pk["part"]) > 0
                if ok:
                    os.replace(pk["part"], final)       # csak sikeres, TELJES elemzés kerül a végleges névre
            except Exception:       # noqa
                ok = False
            if not ok:
                try:
                    os.remove(pk["part"])
                except OSError:
                    pass
            pk["running"] = False
            pk["done"] = ok
            pk["failed"] = (not ok) and not pk["cancel"]
            if not pk["cancel"]:
                self.p.q.put((lambda r, e: self._pk_finished(pk), None, None))

        threading.Thread(target=run, daemon=True).start()
        pk["after"] = self.f.after(1000, lambda: self._pk_tick(pk))

    def _pk_tick(self, pk):
        """Másodpercenként: haladás kiolvasása, a (részben kész) hullám frissítése balról jobbra."""
        if pk is not self._pk or not pk["running"]:
            return
        try:
            sz = os.path.getsize(pk["part"])
        except OSError:
            sz = 0
        pk["frac"] = min(0.99, sz / max(1.0, self.dur * self.PK_RATE * 2.0))
        if sz != pk["last"]:
            pk["last"] = sz
            if self.vl > self.PK_MIN_VIEW:
                self._request_wave()
        self._draw_tl()
        pk["after"] = self.f.after(1200, lambda: self._pk_tick(pk))

    def _pk_finished(self, pk):
        if pk is not self._pk:
            return
        if pk["failed"]:
            self._wave_state = _("hanghullám: az elemzés nem sikerült", "waveform: analysis failed")
        self._wave_img = self._wave_all = None
        self._request_wave()

    def _pk_for_view(self):
        """A mostani nézethez használandó burkoló-fájl útvonala, vagy None (ilyenkor közvetlenül a hangból rajzolunk)."""
        pk = self._pk
        if not pk or pk["src"] != self.src or pk["failed"] or self.vl <= self.PK_MIN_VIEW:
            return None
        if pk["done"]:
            return pk["final"]
        if pk["running"]:
            try:
                avail = os.path.getsize(pk["part"]) / (self.PK_RATE * 2.0)      # a már elemzett hang másodperce
            except OSError:
                return None
            if avail >= self.vs + self.vl or self.vl > 1500:
                return pk["part"]
        return None

    def _request_wave(self):
        self._after_wave = None
        if not self.info or not self.ff or not self.v_wave.get():
            return
        if not self.info["audio"]:
            self._wave_state = _("nincs hangsáv", "no audio track")
            self._draw_tl()
            return
        pkp = self._pk_for_view()
        req = (self.token, self.src, self.vs, self.vl, self._tw(), self._wkey(), self.v_gain.get(), self._wh(), pkp)
        if not pkp:
            png = self._wave_cache.get(self._wave_ckey(req))
            if png:                      # a hosszú, közvetlen nézetek hullámát megjegyezzük
                self._wave_done(req, png, None)
                return
        if pkp and pkp.endswith(".part"):
            self._wave_state = _("hanghullám elemzése… %d %%", "analysing audio… %d %%") % int(self._pk["frac"] * 100)
        elif self.vl > 1500:
            self._wave_state = _("hanghullám készül… (hosszú videó: a hang végigolvasása eltarthat egy ideig)",
                                 "rendering waveform… (long video: reading the audio can take a while)")
        else:
            self._wave_state = _("hanghullám készül…", "rendering waveform…")
        self._draw_tl()
        self.ww.submit(req)

    @staticmethod
    def _wave_ckey(req):
        return (req[1], round(req[2], 2), round(req[3], 2), req[4], req[7], req[6])

    def _wave_work(self, req, wk):
        _tok, src, vs, vl, W, _key, gain, H, pkp = req
        try:
            g = float(gain.lstrip("x"))
        except ValueError:
            g = 1.0
        sz = "s=%dx%d" % (W, H)
        # 3 sáv: 0 = alap (kék), 1 = A–B kijelölés (sárga), 2 = kivágott szakasz (zöld). A háttérszínt BELESÜTJÜK a képbe
        # (átlátszatlan PNG): a Tk az átlátszó PNG-t hosszú, sűrű hullámnál másodpercekig tölti be, az átlátszatlant ms alatt.
        bands = ("asplit=3[a][b][c];"
                 "[a]showwavespic=%s:colors=0x33aaff:scale=sqrt,format=rgba[w1];"
                 "[b]showwavespic=%s:colors=0xffe066:scale=sqrt,format=rgba[w2];"
                 "[c]showwavespic=%s:colors=0x8dffa8:scale=sqrt,format=rgba[w3];"
                 "color=c=0x111111:%s,format=rgba[g1];color=c=0x5a4510:%s,format=rgba[g2];color=c=0x5a1c1c:%s,format=rgba[g3];"
                 "[g1][w1]overlay=shortest=1[o1];[g2][w2]overlay=shortest=1[o2];[g3][w3]overlay=shortest=1[o3];"
                 "[o1][o2][o3]vstack=inputs=3,format=rgb24") % (sz, sz, sz, sz, sz, sz)
        if pkp:      # gyors út: a kész (vagy részben kész) burkoló-fájlból; az időtengely csak arány, ezért a fájlt
            k = float(self.PK_FAKE) / self.PK_RATE          # PK_FAKE Hz-esnek deklaráljuk -> a "hossza" 80-ad része
            try:
                avail = os.path.getsize(pkp) / (self.PK_RATE * 2.0)
            except OSError:
                avail = 0.0
            if avail <= vs + 0.05:
                raise RuntimeError("pk-wait")
            flt = "apad=whole_dur=%.6f,volume=%g,%s" % (vl / k, g, bands)
            cmd = [self.ff.ffmpeg, "-v", "error", "-nostdin", "-f", "s16le", "-ar", str(self.PK_FAKE), "-ac", "1",
                   "-ss", "%.6f" % (vs / k), "-t", "%.6f" % (vl / k), "-i", pkp, "-filter_complex", flt,
                   "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"]
            return wk.run(cmd, 120)
        # közvetlen út (rövid nézet, vagy ha a burkoló nem áll rendelkezésre): hosszú nézetnél előbb kisebb mintavétel
        pre = "aresample=8000," if vl > 600 else ""
        flt = "aformat=channel_layouts=mono,%svolume=%g,%s" % (pre, g, bands)
        cmd = [self.ff.ffmpeg, "-v", "error", "-nostdin", "-ss", "%.3f" % vs, "-t", "%.3f" % vl, "-i", src,
               "-vn", "-sn", "-filter_complex", flt, "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"]
        return wk.run(cmd, 3600 if vl > 1500 else 300)

    def _wave_deliver(self, req, res, err):
        self.p.q.put((lambda r, e: self._wave_done(req, r, e), res, err))

    def _wave_done(self, req, png, err):
        if req[0] != self.token or req[5] != self._wkey():
            return
        if err or not png:
            pk = self._pk
            if pk and pk["running"] and req[8]:
                self._wave_state = _("hanghullám elemzése… %d %%", "analysing audio… %d %%") % int(pk["frac"] * 100)
            else:
                self._wave_state = _("nincs hanghullám", "no waveform")
            self._wave_img = self._wave_all = None
        else:
            if req[3] > 600 and not req[8]:
                if len(self._wave_cache) >= 8:
                    self._wave_cache.pop(next(iter(self._wave_cache)))
                self._wave_cache[self._wave_ckey(req)] = png
            self._wave_all = self.tk.PhotoImage(master=self.tl, data=base64.b64encode(png))
            self._wave_key = req[5]
            self._wave_img = self._crop(0, 0, self._wave_all.width())
        self._draw_tl()

    def _crop(self, band, x1, x2):
        """A hullámkép egy sávjából (0 kék, 1 sárga, 2 zöld) kivág egy vízszintes darabot."""
        h = max(1, self._wave_all.height() // 3)
        img = self.tk.PhotoImage(master=self.tl)
        img.tk.call(img.name, "copy", self._wave_all.name, "-from", x1, band * h, x2, (band + 1) * h)
        return img

    # ---------------------------------------------------------------- lejátszás
    def toggle(self):
        if self.playing:
            self.pause()
        else:
            self.play()

    def play_ab(self):
        if self.A is None:
            self._status(_("Előbb jelöld ki a kezdetet (A).", "Set the start (A) first."))
            return
        self.play(self.A, self.B)

    @staticmethod
    def _reader(proc, q, n, stop):
        idx = 0
        try:
            while not stop.is_set():
                buf = proc.stdout.read(n)
                if len(buf) < n:
                    break
                while not stop.is_set():
                    try:
                        q.put((idx, buf), timeout=0.2)
                        break
                    except queue.Full:
                        pass
                idx += 1
        except (OSError, ValueError):
            pass
        finally:
            try:
                q.put((-1, None), timeout=1)
            except queue.Full:
                pass

    @staticmethod
    def _kill(pr):
        if pr is not None and pr.poll() is None:
            try:
                pr.kill()
            except OSError:
                pass
        if pr is not None:
            threading.Thread(target=pr.wait, daemon=True).start()

    def _save_off(self):
        try:
            self.p.cfg["av_off"] = self.v_off.get().strip() or "0"
            save_config(self.p.cfg)
        except Exception:       # noqa
            pass

    def sync_test(self):
        """Hang–kép kalibráló teszt: másodpercenként egy fehér villanás ÉS egy sípolás, a fájlban pontosan egyszerre."""
        if not self._setup_ok():
            return
        out = os.path.join(tempfile.gettempdir(), "lvt_sync_test.mkv")
        cmd = [self.ff.ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
               "color=c=black:s=640x360:r=25:d=20,drawbox=x=0:y=0:w=iw:h=ih:color=white:t=fill:enable='lt(mod(t,1),0.04)'",
               "-f", "lavfi", "-i", "aevalsrc='0.8*sin(2*PI*1000*t)*lt(mod(t,1),0.04)':s=48000:d=20",
               "-c:v", "mpeg4", "-q:v", "2", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", out]
        try:
            subprocess.run(cmd, check=True, creationflags=_NOWIN, timeout=60, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            self._msg(_("A teszt-fájl nem hozható létre.", "Could not create the test file."))
            return
        self.p.v_src.set(out)
        self.load(force=True)
        self._status(_("Szinkron-teszt: játszd le. Ha a sípolás a villanás ELŐTT hallatszik, írj a mezőbe negatív "
                       "értéket (ms), ha UTÁNA, pozitívat. Addig állítsd, amíg egyszerre van; az érték megmarad.",
                       "Sync test: play it. If the beep comes BEFORE the flash enter a negative value (ms), if AFTER "
                       "a positive one, until they coincide; the value is remembered."))

    def _offset(self):
        try:
            return float(self.v_off.get().replace(",", ".")) / 1000.0
        except ValueError:
            return 0.0

    def _mute_toggled(self):
        """Lejátszás közbeni némítás / visszakapcsolás. Némításkor a hangfolyamat leáll; visszakapcsoláskor a lejátszás
        az aktuális helyről újraindul, hogy a hang a képpel szinkronban induljon."""
        if not self.playing:
            return
        if self.v_mute.get():
            if self._apump is not None:
                self._apump.close()
                self._apump = None
        elif self.info and self.info.get("audio"):
            self.play(self.t, self._stop_at)

    def _only_toggled(self):
        if self.v_only.get():
            self.v_skip.set(False)          # a két mód kizárja egymást
            if not self.segs:
                self._status(_("Nincs kivágott szakasz: előbb vegyél fel a „✂ A–B kivágása” gombbal.",
                               "No cut-out segments yet: add some with the Cut A-B button."))

    def _skip_toggled(self):
        if self.v_skip.get():
            self.v_only.set(False)

    def _in_cut(self, t):
        e = 0.5 / self.fps
        return any(ca - e <= t < cb - 2 * e for ca, cb in self.segs)

    def _next_cut_start(self, t):
        """A t utáni első kivágott szakasz kezdete; ha nincs több: None."""
        return next((ca for ca, cb in sorted(self.segs) if ca > t), None)

    def play(self, t0=None, stop_at=None):
        if not self.info or not self.ff:
            return
        if not self.info["w"]:
            self._status(_("Nincs képfolyam – csak a hang játszható.", "No video stream."))
        self.pause(quiet=True)
        t0 = self.t if t0 is None else t0
        if t0 >= self.dur - 2.0 / self.fps:
            t0 = 0.0
        if stop_at is None and self.v_only.get() and self.segs and not self._in_cut(t0):
            nxt = self._next_cut_start(t0)
            t0 = nxt if nxt is not None else sorted(self.segs)[0][0]     # a végén túl: az első kivágottól
        W, H = self._fit()
        self._pW, self._pH = W, H
        cmd = [self.ff.ffmpeg, "-v", "error", "-nostdin", "-ss", "%.3f" % max(0.0, t0 - 0.4 / self.fps), "-i", self.src,
               "-an", "-sn", "-vf", self._vf(W, H, self.fps), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        try:
            self._vproc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                           stdin=subprocess.DEVNULL, bufsize=W * H * 3, creationflags=_NOWIN)
        except OSError as e:
            self._status(str(e))
            return
        self._play_id += 1
        pid = self._play_id
        self._fq = queue.Queue(maxsize=6)
        self._pend = None
        self._stop_evt = threading.Event()
        threading.Thread(target=self._reader, args=(self._vproc, self._fq, W * H * 3, self._stop_evt),
                         daemon=True).start()
        self._t0, self._stop_at, self.playing = t0, stop_at, True
        self.t = t0
        self._update_time()
        # a kép és a hang közös "indítási pillanatát" NEM a folyamatindítás (Popen) idejéhez igazítjuk,
        # hanem csak a ténylegesen megérkezett ELSŐ képkockához - lásd _tick().
        self._wall0 = None
        self._first = None
        self._wait0 = time.perf_counter()
        self._pending_audio = dict(t0=t0, stop_at=stop_at, off=self._offset())
        self._apump = self._make_pump(t0, stop_at)
        self.btn_play.config(text=_("❚❚ Szünet", "❚❚ Pause"))
        self._tick(pid)

    def _make_pump(self, t0, stop_at):
        if self.v_mute.get() or not self.ff.ffplay or not self.info["audio"]:
            return None
        try:
            vol = float(self.v_vol.get())
        except ValueError:
            vol = 100.0
        try:
            return _AudioPump(self.ff, self.src, t0, (stop_at - t0) if stop_at else 0, vol)
        except OSError:
            return None

    def pause(self, quiet=False):
        self.playing = False
        self._play_id += 1
        if self._stop_evt is not None:
            self._stop_evt.set()
        self._kill(self._vproc)
        self._kill(self._aproc)
        if self._apump is not None:
            self._apump.close()
            self._apump = None
        self._vproc = self._aproc = None
        self._fq = None
        self.btn_play.config(text=_("▶ Lejátszás", "▶ Play"))

    def _tick(self, pid):
        if pid != self._play_id or not self.playing:
            return
        if self._wall0 is None:
            # Az első képkockát megjelenítjük, de az időzítést (és a hangot) csak akkor indítjuk, amikor
            # az előtöltött hang is kész: így mindkettő ugyanabból a pillanatból indul.
            eof = False
            if self._first is None and self._fq is not None:
                try:
                    idx, buf = self._fq.get_nowait()
                    if idx < 0:
                        eof = True
                    else:
                        self._first = (idx, buf)
                        self._blit(buf, self._pW, self._pH)
                        self.t = self._t0 + idx / self.fps
                        self._update_time()
                except queue.Empty:
                    pass
            if self._first is not None:
                ap, idx = self._apump, self._first[0]
                pa = self._pending_audio or {}
                off = pa.get("off", 0.0)
                now = time.perf_counter()
                if ap is None:
                    self._wall0 = now - idx / self.fps + max(0.0, off)
                elif not ap.go.is_set():
                    if ap.ready.is_set() or now - self._wait0 > 8.0:
                        ap.go_at = now + max(0.0, -off)       # negatív igazítás: a hang indul később
                        ap.go.set()
                elif ap.t_real0 is not None:
                    # a kép a hang TÉNYLEGES indulási pillanatához (t_real0) van kötve + a hallhatóság késése
                    self._wall0 = ap.t_real0 + AUDIO_LAT - idx / self.fps + max(0.0, off)
            elif eof:
                self.pause(quiet=True)
                return
            self.f.after(8, lambda: self._tick(pid))
            return
        due = int((time.perf_counter() - self._wall0) * self.fps)
        shown, eof = None, False
        while self._fq is not None:
            if self._pend is None:
                try:
                    self._pend = self._fq.get_nowait()
                except queue.Empty:
                    break
            idx, buf = self._pend
            if idx < 0:
                eof = True
                break
            if idx <= due:
                shown = self._pend
                self._pend = None
            else:
                break
        if shown is not None:
            self._blit(shown[1], self._pW, self._pH)
            self.t = self._t0 + shown[0] / self.fps
            self._update_time()
            if self.t > self.vs + self.vl or self.t < self.vs:
                self.vs = min(max(0.0, self.t - 0.1 * self.vl), max(0.0, self.dur - self.vl))
                self._view_changed()
            if self._stop_at is not None and self.t >= self._stop_at - 0.5 / self.fps:
                self._finish_segment()
                return
            if self.v_only.get() and self._stop_at is None and self.segs and not self._in_cut(self.t):
                nxt = self._next_cut_start(self.t)
                if nxt is None:             # az utolsó kivágott szakasz után: vége
                    self.pause(quiet=True)
                    return
                self.play(nxt)
                return
            if self.v_skip.get() and self._stop_at is None:
                for ca, cb in self.segs:
                    if ca - 0.5 / self.fps <= self.t < cb - 1.0 / self.fps:
                        if cb >= self.dur - 2.0 / self.fps:
                            self.pause(quiet=True)
                            self._set_t(ca)
                        else:
                            self.play(cb)
                        return
        if eof:
            if self.v_loop.get() and self.A is None:
                self.play(0.0)
            else:
                self.pause(quiet=True)
            return
        self.f.after(8, lambda: self._tick(pid))

    def _finish_segment(self):
        if self.v_loop.get() and self.A is not None:
            self.play(self.A, self._stop_at)
        else:
            end = self._stop_at
            self.pause(quiet=True)
            self._set_t(end if end is not None else self.t)

    # ---------------------------------------------------------------- billentyűk
    # ---- gyorsbillentyűk a szakaszlistán ----
    def _tree_select_all(self, _e=None):
        self.tree.selection_set(self.tree.get_children(""))
        self._status(_("Minden szakasz kijelölve (%d).", "All segments selected (%d).") % len(self.segs))
        return "break"

    def _tree_clear_sel(self, _e=None):
        self.tree.selection_remove(self.tree.selection())
        return "break"

    def _seg_enter(self, _e=None):
        self.seg_load()
        return "break"

    def _seg_del_many(self, _e=None):
        # több kijelölt sor egyszerre; a nagyobb indextől törlünk, hogy a többi index ne csússzon el
        idxs = sorted((int(i) for i in self.tree.selection() if int(i) < len(self.segs)), reverse=True)
        if not idxs:
            return "break"
        before = self._snap_state()
        for i in idxs:
            del self.segs[i]
        self._refresh_segs()
        self._record(before)
        self._status(_("%d szakasz törölve.", "%d segment(s) removed.") % len(idxs))
        return "break"

    def _key(self, e):
        if not self.info or self.p.nb.select() != str(self.f):
            return None
        try:
            w = self.f.focus_get()
        except KeyError:
            w = None
        if isinstance(w, (self.tk.Entry, self.tk.Text, self.tk.Spinbox)):
            return None
        k = e.keysym
        n = 10.0 if e.state & 4 else (1.0 if e.state & 1 else None)
        if k == "space":
            self.toggle()
        elif k in ("Left", "Right"):
            d = -1 if k == "Left" else 1
            self.step_s(d * n) if n else self.step_f(d)
        elif k == "Prior":
            self._ik_step(-1)               # PageUp = előző I-kocka
        elif k == "Next":
            self._ik_step(1)                # PageDown = következő I-kocka
        elif k == "Home":
            self.goto(0.0)
        elif k == "End":
            self.goto(self.dur)
        elif k.lower() == "i":
            self.set_a()
        elif k.lower() == "o":
            self.set_b()
        elif k.lower() == "p" and not e.state & 4:
            self.cut_remove()               # P = A–B kivágása
        elif k.lower() == "z" and e.state & 4:
            self.undo()                     # Ctrl+Z = Vissza
        elif k.lower() == "y" and e.state & 4:
            self.redo()                     # Ctrl+Y = Újra
        else:
            return None
        return "break"

    # ---------------------------------------------------------------- export
    def _sel_ranges(self):
        """Kijelölt szakaszok (ha nincs kijelölés: az összes; ha nincs lista: a megjelölt A–B rész)."""
        sel = sorted(int(i) for i in self.tree.selection() if int(i) < len(self.segs))
        if sel:
            return [self.segs[i] for i in sel]
        if self.segs:
            return list(self.segs)
        if self.A is not None and self.B is not None and self.B > self.A:
            return [(self.A, self.B)]
        return []

    def to_effects(self):
        """A kijelölt szakaszokat átviszi a Képeffektek ablakba (külön ablak élő előnézettel). Ha nincs szakasz és
        nincs A–B jelölés, a teljes fájl kerül be."""
        if not self.src or not self.info:
            self.p.mb.showinfo("FFmpeg", _("Előbb tölts be egy videót a Szerkesztőben.", "Load a video in the Editor first."))
            return
        rngs = self._sel_ranges() or ([(0.0, self.dur)] if self.dur > 0 else [])
        self.p.open_effects(self.src, rngs)

    def to_convert(self):
        """„→ Kijelöltek az Átalakításra”: a kijelölt szakaszokat (ha nincs kijelölés: az összeset; ha nincs
        lista: a megjelölt A–B részt; ha az sincs: az EGÉSZ fájlt) átadja az Átalakítás fül listájának, és oda vált.
        CSAK a szakaszlistát adja át: az Átalakítás fül kodek-, minőség- és konténerbeállításait nem írja felül,
        a Kezdet / Vég mezőket sem (a lista ezeket nem használja)."""
        P = self.p
        if not self.src or not self.info:
            P.mb.showinfo("FFmpeg", _("Előbb tölts be egy videót a Szerkesztőben.",
                                      "Load a video in the Editor first."))
            return
        rngs = self._sel_ranges()
        whole = False
        if not rngs and self.dur > 0:
            rngs, whole = [(0.0, self.dur)], True
        if not rngs:
            P.mb.showwarning("FFmpeg", _("Nincs átadható szakasz: jelölj ki vágást, vagy jelölj meg A–B részt.",
                                         "Nothing to pass on: cut a segment or mark an A-B range."))
            return
        before = len(P.queue)
        P.queue_add(self.src, rngs)
        added = len(P.queue) - before
        P.nb.select(P.t_conv)
        if whole:
            msg = _("Nincs kijelölt szakasz: a teljes fájl került az Átalakítás listájára.",
                    "No segment selected: the whole file was added to the Convert list.")
        else:
            msg = _("%d szakasz került az Átalakítás listájára (%d már ott volt).",
                    "%d segment(s) added to the Convert list (%d were already there).") % (added, len(rngs) - added)
        P._status(msg)

    def _complement(self, cuts):
        """A teljes fájl a kivágott darabok nélkül: a megmaradó részek listája."""
        keep, pos = [], 0.0
        for a, b in self._merge(cuts):
            if a - pos > 1e-3:
                keep.append((pos, a))
            pos = max(pos, b)
        if self.dur - pos > 1e-3:
            keep.append((pos, self.dur))
        return keep

    def _items(self):
        if self.segs:
            return list(self.segs)
        if self.A is not None or self.B is not None:
            return [(self.A or 0.0, self.B if self.B is not None else self.dur)]
        return []

    def _smartcut_parse_time_value(self, value):
        try:
            text = str(value).strip().replace(",", ".")
            if not text:
                return None
            if ":" not in text:
                return float(text)
            parts = [float(part) for part in text.split(":")]
            if len(parts) == 3:
                return parts[0] * 3600.0 + parts[1] * 60.0 + parts[2]
            if len(parts) == 2:
                return parts[0] * 60.0 + parts[1]
        except (TypeError, ValueError):
            pass
        return None

    def _smartcut_item_range_pair(self, item):
        try:
            if isinstance(item, dict):
                start = item.get("start", item.get("a", item.get("begin")))
                end = item.get("end", item.get("b", item.get("stop")))
            else:
                start, end = item[0], item[1]
            return self._smartcut_parse_time_value(start), self._smartcut_parse_time_value(end)
        except (TypeError, IndexError, KeyError):
            return None, None

    def _smartcut_items_in_tree_order(self, items):
        tree = getattr(self, "_smartcut_cut_tree", None)
        if tree is None:
            return items
        try:
            rows = list(tree.get_children(""))
            columns = list(tree["columns"])
            headings = []
            for column in columns:
                try:
                    headings.append(str(tree.heading(column).get("text", "")).lower())
                except Exception:
                    headings.append(str(column).lower())
            start_index = next((i for i, h in enumerate(headings)
                                if any(k in h for k in ("kezdet", "start", "from", "eleje"))), None)
            end_index = next((i for i, h in enumerate(headings)
                              if any(k in h for k in ("vég", "veg", "end", "to"))), None)
            if start_index is None or end_index is None:
                start_index, end_index = (1, 2) if len(columns) >= 4 else (0, 1)
            row_ranges = []
            for iid in rows:
                values = list(tree.item(iid, "values"))
                if len(values) <= max(start_index, end_index):
                    continue
                a = self._smartcut_parse_time_value(values[start_index])
                b = self._smartcut_parse_time_value(values[end_index])
                if a is not None and b is not None:
                    row_ranges.append((a, b))
            if not row_ranges:
                return items
            available = list(range(len(items)))
            ordered_indices = []
            for a, b in row_ranges:
                best = None
                best_delta = None
                for idx in available:
                    item_a, item_b = self._smartcut_item_range_pair(items[idx])
                    if item_a is None or item_b is None:
                        continue
                    delta = abs(item_a - a) + abs(item_b - b)
                    if best_delta is None or delta < best_delta:
                        best, best_delta = idx, delta
                if best is not None and best_delta is not None and best_delta <= 0.06:
                    ordered_indices.append(best)
                    available.remove(best)
            ordered_indices.extend(available)
            return [items[idx] for idx in ordered_indices]
        except Exception:
            return items

    def _smartcut_move_cut_rows(self, direction):
        tree = getattr(self, "_smartcut_cut_tree", None)
        if tree is None:
            return
        rows = list(tree.get_children(""))
        selected = set(tree.selection())
        if not selected:
            return
        if direction < 0:
            for index in range(1, len(rows)):
                if rows[index] in selected and rows[index - 1] not in selected:
                    rows[index - 1], rows[index] = rows[index], rows[index - 1]
        else:
            for index in range(len(rows) - 2, -1, -1):
                if rows[index] in selected and rows[index + 1] not in selected:
                    rows[index], rows[index + 1] = rows[index + 1], rows[index]
        for index, iid in enumerate(rows):
            tree.move(iid, "", index)
        tree.selection_set(tuple(selected))
        if rows:
            first = next((iid for iid in rows if iid in selected), rows[0])
            tree.focus(first)
            tree.see(first)

    def _smartcut_install_cut_list_controls(self):
        if getattr(self, "_smartcut_controls_installed", False):
            return
        try:
            widgets = []
            root_widget = getattr(self, "f", self)
            pending = list(root_widget.winfo_children())
            while pending:
                widget = pending.pop(0)
                widgets.append(widget)
                try:
                    pending.extend(widget.winfo_children())
                except Exception:
                    pass

            def norm(value):
                try:
                    import unicodedata
                    return "".join(ch for ch in unicodedata.normalize("NFD", str(value).lower())
                                   if unicodedata.category(ch) != "Mn")
                except Exception:
                    return str(value).lower()

            tree_candidates = []
            for widget in widgets:
                try:
                    if "treeview" not in str(widget.winfo_class()).lower():
                        continue
                    columns = list(widget["columns"])
                    heads = [norm(widget.heading(col).get("text", "")) for col in columns]
                    score = int(any(any(k in h for k in ("kezdet", "start", "from", "eleje")) for h in heads))
                    score += int(any(any(k in h for k in ("veg", "end", "to")) for h in heads))
                    score += int(any(any(k in h for k in ("hossz", "duration", "length")) for h in heads))
                    if score >= 2:
                        tree_candidates.append((score, widget))
                except Exception:
                    continue
            if not tree_candidates:
                self._status(_("Nem találom a kivágott szakaszok táblázatát a Select all gombhoz.",
                               "Could not find the cut-segment table for Select all."))
                return
            tree_candidates.sort(key=lambda item: item[0], reverse=True)
            tree = tree_candidates[0][1]

            load_button = delete_button = None
            for widget in widgets:
                try:
                    if "button" not in str(widget.winfo_class()).lower():
                        continue
                    label = norm(widget.cget("text"))
                    if load_button is None and ("betolt" in label or ("load" in label and ("a-b" in label or "ab" in label))):
                        load_button = widget
                    if delete_button is None and ("torles" in label or "delete" in label):
                        delete_button = widget
                except Exception:
                    continue
            if load_button is None or delete_button is None:
                self._status(_("Nem találom a Betöltés A-B-be / Törlés gombokat; a sorrendező vezérlők kimaradtak.",
                               "Could not locate Load A-B / Delete buttons; reorder controls were not added."))
                return
            if load_button.master is not delete_button.master:
                self._status(_("A Betöltés A-B-be és Törlés gomb nincs ugyanabban a vezérlőkeretben; a sorrendező vezérlők kimaradtak.",
                               "Load A-B and Delete are not in the same control frame; reorder controls were not added."))
                return

            tree.configure(selectmode="extended")
            self._smartcut_cut_tree = tree

            if not hasattr(self, "_smartcut_original_items") and callable(getattr(self, "_items", None)):
                original_items = self._items
                self._smartcut_original_items = original_items
                def ordered_items():
                    return self._smartcut_items_in_tree_order(original_items())
                self._items = ordered_items

            parent = delete_button.master
            manager = delete_button.winfo_manager()
            controls = self.ttk.Frame(parent)
            if manager == "pack":
                controls.pack(side="top", fill="x", padx=0, pady=(2, 0))
            elif manager == "grid":
                info = delete_button.grid_info()
                row = int(info.get("row", 0)) + int(info.get("rowspan", 1))
                column = int(info.get("column", 0))
                columnspan = int(info.get("columnspan", 1))
                controls.grid(row=row, column=column, columnspan=columnspan, sticky="ew", padx=0, pady=(2, 0))
            else:
                self._status(_("A vezérlőkeret nem pack/grid elrendezést használ; a sorrendező gombokat nem lehet biztonságosan elhelyezni.",
                               "The control frame does not use pack/grid; reorder buttons cannot be placed safely."))
                return

            self.ttk.Button(
                controls,
                text=_("Összes kijelölése", "Select all"),
                command=lambda: tree.selection_set(tree.get_children("")),
            ).pack(fill="x", pady=1)
            self.ttk.Button(
                controls,
                text=_("↑ Fel", "↑ Up"),
                command=lambda: self._smartcut_move_cut_rows(-1),
            ).pack(fill="x", pady=1)
            self.ttk.Button(
                controls,
                text=_("↓ Le", "↓ Down"),
                command=lambda: self._smartcut_move_cut_rows(1),
            ).pack(fill="x", pady=1)
            self._smartcut_controls_installed = True
        except Exception as exc:
            try:
                self._status(_("A Select all / sorrendező vezérlők nem telepíthetők: ",
                               "Could not install Select all / reorder controls: ") + str(exc))
            except Exception:
                pass

    def export_smart(self, mode):
        import threading
        P = self.p
        if not self._setup_ok():
            return
        if not self.src or not self.info:
            P.mb.showinfo("FFmpeg", _("Előbb tölts be egy videót a Szerkesztőben.",
                                       "Load a video in the Editor first."))
            return
        if P.busy:
            P.mb.showinfo("FFmpeg", _("Már fut egy művelet.", "An operation is already running."))
            return

        items = self._items()
        if not items:
            P.mb.showwarning("FFmpeg", _("Nincs mit exportálni: jelölj ki A–B szakaszt, vagy adj kivágást a listához.",
                                          "Nothing to export: mark an A-B range or add a cut-out."))
            return
        if mode == "rest":
            items = self._complement(items)
            if not items:
                P.mb.showwarning("FFmpeg", _("A kivágások után nem marad semmi a fájlból.",
                                              "Nothing would remain after the cuts."))
                return

        try:
            if (P._probe and P._filled_src and
                    os.path.normcase(self.src) == P._filled_src):
                probe = P._probe
            else:
                probe = self.ff.probe(self.src)
            video = lvt_smartcut._video_stream(probe)
            codec = (video.get("codec_name") or "").lower()
            if codec not in ("h264", "hevc", "vp9", "av1"):
                raise lvt_smartcut.SmartCutError(_(
                    "A Smart export H.264, HEVC/H.265, VP9 és AV1 forrásvideót támogat. "
                    "Más kodekhez használd a Kijelöltek átalakítása műveletet.",
                    "Smart export supports H.264, HEVC/H.265, VP9 and AV1 source video. "
                    "For other codecs use the Convert selected action."
                ))
        except Exception as ex:
            P.mb.showwarning("FFmpeg", _("A Smart export forrásadatai nem olvashatók:\n", "Could not read Smart export source information:\n") + str(ex))
            return

        # Cache codec-specific access points; scans run off the Tk thread. For
        # H.264 this deliberately counts true IDR NAL units, not arbitrary I-frames.
        try:
            stat = os.stat(self.src)
            signature = (os.path.normcase(os.path.abspath(self.src)), stat.st_size, stat.st_mtime_ns)
        except OSError:
            signature = (os.path.normcase(os.path.abspath(self.src)),)
        cache = getattr(self, "_smartcut_access_cache", None)
        access_times = cache[1] if cache and cache[0] == signature else None
        if access_times is None:
            running = getattr(self, "_smartcut_scan_running", None)
            if running == signature:
                self._smart_pending = mode
                self._status(_("Kulcskocka-elemzés folyamatban; a Smart export utána indul.",
                               "Keyframe scan is running; Smart export will start when it finishes."))
                return
            self._smart_pending = mode
            self._smartcut_scan_running = signature
            self._status(_("Biztonságos kulcskockák keresése a Smart exporthoz…",
                           "Finding safe access points for Smart export…"))
            try:
                P.cancel.clear()
            except Exception:
                pass
            ff = self.ff
            src = self.src

            result = {"done": False, "times": None, "error": None}

            def scan_access_points():
                # Worker thread: no Tk calls here (Tkinter is not thread-safe).
                try:
                    result["times"] = lvt_smartcut.detect_random_access_times(ff, src, probe, cancel=P.cancel)
                except Exception as ex:
                    result["error"] = str(ex)
                result["done"] = True

            def finish_scan():
                times, error = result["times"], result["error"]
                if getattr(self, "_smartcut_scan_running", None) != signature:
                    return
                self._smartcut_scan_running = None
                if os.path.normcase(os.path.abspath(self.src or "")) != signature[0]:
                    self._smart_pending = None
                    return
                pending, self._smart_pending = getattr(self, "_smart_pending", None), None
                if error:
                    self._status(_("A Smart export kulcskocka-elemzése nem sikerült.",
                                   "Smart export keyframe analysis failed."))
                    P.mb.showwarning("FFmpeg", _("A Smart export nem készíthető el:\n\n", "Smart export could not be prepared:\n\n") + error)
                    return
                self._smartcut_access_cache = (signature, times)
                if pending is not None:
                    self.export_smart(pending)

            def poll_scan():
                # Runs on the Tk main thread: waits for the worker without touching Tk from it.
                if not result["done"]:
                    try:
                        self.f.after(150, poll_scan)
                    except Exception:
                        pass
                    return
                finish_scan()

            threading.Thread(target=scan_access_points, daemon=True).start()
            try:
                self.f.after(150, poll_scan)
            except Exception:
                pass
            return

        out = self._ask_target(mode)
        if not out:
            return
        P.o["out"].set(out)

        def _container_family(path_ext):
            e = path_ext.lower()
            return ("mpegts" if e in (".ts", ".mts", ".m2ts") else
                    "matroska" if e == ".mkv" else
                    "iso-bmff" if e in (".mp4", ".m4v", ".mov") else None)

        source_ext = os.path.splitext(self.src)[1] or ".mkv"
        source_family = _container_family(source_ext)
        out_base, out_ext = os.path.splitext(out)
        output_family = _container_family(out_ext)
        # Smart export keeps the source container. An unknown source extension is left
        # to lvt_smartcut, which reports it clearly instead of guessing a family here.
        if source_family is not None and output_family != source_family:
            out = out_base + source_ext
            P.o["out"].set(out)
            self._status(_("A Smart export a forrás konténerét tartja meg, ezért a kimenet kiterjesztése: ",
                           "Smart export keeps the source container, so the output extension is: ") + source_ext)
        base, ext = os.path.splitext(out)
        separate = mode == "sep" and len(items) > 1
        if separate:
            groups = [[item] for item in items]
            targets = ["%s_%03d%s" % (base, i + 1, ext) for i in range(len(items))]
            shown = "%s_001%s … %s_%03d%s  (%d %s)" % (
                base, ext, base, len(items), ext, len(items), _("fájl", "files"))
        else:
            groups, targets, shown = [items], [out], out

        try:
            jobs, final, cleanup = lvt_smartcut.build_jobs(
                self.ff, self.src, groups, access_times, probe, targets, self._copy_opts(out), cancel=P.cancel)
        except Exception as ex:
            P.mb.showwarning("FFmpeg", _("A Smart export nem készíthető el:\n\n", "Smart export could not be prepared:\n\n") + str(ex))
            return

        P.v_cmd.set(_("Smart export: a forrás konténer-, videó- és hangkodekje megmarad; a vágásszélek újrakódolódnak.",
                      "Smart export: preserves the source container and video/audio codecs; cut edges are re-encoded."))
        self._status(_("Smart export indul: kimenet a forrás konténerében és kodekjeivel; kísérleti illesztés.",
                       "Starting Smart export: source container/codecs preserved; experimental joins."))
        P.run_jobs(self.ff, jobs, final=final, out=shown, cleanup=cleanup)


    def _ask_target(self, mode):
        """Mentési párbeszédablak MINDEN Szerkesztő-exportnál: nem írja felül csendben az előző fájlt.
        Az utoljára mentett név és mappa az alapértelmezés; a felülírást a Windows külön megerősítteti."""
        P = self.p
        ext = os.path.splitext(self.src)[1] or ".mkv"
        last = getattr(self, "_last_target", None)
        if last:
            initdir, initfile = os.path.split(last)
        else:
            initdir = os.path.dirname(self.src)
            initfile = os.path.splitext(os.path.basename(self.src))[0] + ("_without" if mode == "rest" else "_cut") + ext
        out = P.fd.asksaveasfilename(parent=P.parent, defaultextension=ext, initialdir=initdir,
                                     initialfile=initfile)
        if out:
            out = os.path.normpath(out)
            self._last_target = out
        return out

    def _copy_opts(self, out):
        """Az Editor-export beállításai: CSAK MÁSOLÁS (kulcskockás vágás, fejléc-írás), SEMMI újrakódolás.
        Az Átalakítás fül kodek-, szűrő-, minőség- és konténerbeállításai ide NEM kerülnek át: azokat
        a „→ Kijelöltek az Átalakításra” gomb viszi a konvertáló fülre."""
        return {"src": self.src, "out": out, "vcodec": "copy", "acodec": "copy", "container": "",
                "overwrite": True, "faststart": True, "avoid_neg": True, "accurate": False,
                "subs": False, "hwaccel": "-", "deint": False, "fx_vf": ""}

    def _choose_export_method(self):
        """Ask whether this export should use Smart Cut or the normal path."""
        parent = self.p.parent
        dlg = self.tk.Toplevel(parent)
        dlg.title(_("Mentési mód", "Save method"))
        dlg.transient(parent)
        dlg.resizable(False, False)
        choice = {"smart": None}

        outer = self.ttk.Frame(dlg, padding=14)
        outer.pack(fill="both", expand=True)
        self.ttk.Label(
            outer,
            text=_("Hogyan szeretnéd menteni ezt a kijelölést?",
                   "How would you like to save this selection?"),
            font=("TkDefaultFont", 11, "bold"),
            wraplength=480,
        ).pack(anchor="w", pady=(0, 10))

        def finish(value):
            choice["smart"] = value
            dlg.destroy()

        smart_box = self.ttk.LabelFrame(
            outer, text=_("Smart export – I-frame pont nélkül is", "Smart export – no I-frame cuts needed"),
            padding=10,
        )
        smart_box.pack(fill="x", pady=(0, 8))
        self.ttk.Label(
            smart_box,
            text=_("Nem kell I-frame-re vágni: MTS/TS/M2TS, MKV vagy MP4/M4V/MOV forráson H.264/AVC, HEVC/H.265, VP9 és AV1 kulcskockáit keresi. A forrás konténerét, videó- és hangkodekjét megtartja; a biztonságos kulcskockák közti részt másolja, a vágásszéleket ugyanabba a videókodekbe kódolja újra. Ha nincs másolható közép, a teljes kijelölt szakasz újrakódolódik. A hang kimenetenként egyszer, a forrás hangkodekjével készül.",
                   "No I-frame cuts are required: on MTS/TS/M2TS, MKV, or MP4/M4V/MOV sources, the program finds safe keyframes for H.264/AVC, HEVC/H.265, VP9, and AV1. It preserves the source container and video/audio codecs; copies the section between IDRs/keyframes and re-encodes cut edges in the same video codec. If no copyable middle exists, the selected section is fully re-encoded. Audio is encoded once per output in its source codec."),
            wraplength=470,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))
        self.ttk.Button(
            smart_box,
            text=_("Smart export használata", "Use Smart export"),
            command=lambda: finish(True),
        ).pack(anchor="e")

        normal_box = self.ttk.LabelFrame(
            outer, text=_("I-frame / kulcskocka export – korábbi útvonal", "I-frame / keyframe export – existing path"), padding=10
        )
        normal_box.pack(fill="x", pady=(0, 8))
        self.ttk.Label(
            normal_box,
            text=_("Csak másol: a kulcskockákra (I-frame) vág, és a fejlécet újraírja. Nincs újrakódolás, az Átalakítás fül beállításait nem használja. A vágás a legközelebbi kulcskockára ugrik. Konvertáláshoz: „→ Kijelöltek az Átalakításra”.",
                   "Stream copy only: cuts on keyframes (I-frames) and rewrites the headers. No re-encoding; the Convert tab settings are not used. Cuts snap to the nearest keyframe. To convert: '→ Selected to Convert tab'."),
            wraplength=470,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))
        self.ttk.Button(
            normal_box,
            text=_("I-frame export használata", "Use I-frame export"),
            command=lambda: finish(False),
        ).pack(anchor="e")

        self.ttk.Button(
            outer,
            text=_("Mégse", "Cancel"),
            command=dlg.destroy,
        ).pack(anchor="e", pady=(2, 0))
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        dlg.update_idletasks()
        try:
            px, py = parent.winfo_rootx(), parent.winfo_rooty()
            pw, ph = parent.winfo_width(), parent.winfo_height()
            x = px + max(0, (pw - dlg.winfo_width()) // 2)
            y = py + max(0, (ph - dlg.winfo_height()) // 2)
        except self.tk.TclError:
            x = max(0, (dlg.winfo_screenwidth() - dlg.winfo_width()) // 2)
            y = max(0, (dlg.winfo_screenheight() - dlg.winfo_height()) // 2)
        # Keep the complete dialog within the usable display area (DPI/scaling
        # can make the requested content larger than the main window).
        try:
            sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
            dw, dh = dlg.winfo_width(), dlg.winfo_height()
            x = min(max(0, x), max(0, sw - dw))
            y = min(max(0, y), max(0, sh - dh - 48))
            dlg.resizable(True, True)
        except Exception:
            pass
        dlg.geometry("+%d+%d" % (x, y))
        dlg.grab_set()
        dlg.wait_window()
        return choice["smart"]


    def _iframe_times(self, ffc, info):
        """I-frame kulcskocka-lista a forrásfájlhoz (gyorsítótárazva, a fájl módosítási ideje szerint)."""
        key = (self.src, os.path.getmtime(self.src))
        if getattr(self, "_iframe_key", None) != key:
            self._iframe_times_cache = lvt_smartcut.detect_random_access_times(ffc, self.src, info)
            self._iframe_key = key
        return self._iframe_times_cache

    def export(self, mode):
        smart = self._choose_export_method()
        if smart is None:
            return
        if smart:
            return self.export_smart(mode)
        join = mode in ("join", "rest")
        P = self.p
        ff = P._need()
        if not ff or not self.src:
            return
        if P.busy:
            P.mb.showinfo("FFmpeg", _("Már fut egy művelet.", "An operation is already running."))
            return
        items = self._items()
        if not items:
            P.mb.showwarning("FFmpeg", _("Nincs mit exportálni: jelölj ki A–B szakaszt, és add a kivágottak listájára.",
                                         "Nothing to export: mark A-B and add it to the cut list."))
            return
        if mode == "rest":
            items = self._complement(items)
            if not items:
                P.mb.showwarning("FFmpeg", _("A kivágások után nem marad semmi a fájlból.",
                                             "Nothing would remain after the cuts."))
                return
        out = self._ask_target(mode)
        if not out:
            return
        # I-frame (kulcskockás) Editor-export: csak másolás, a hang újrakódolódik.
        # Ha egy vágási pont nem kulcskockára esik, a művelet nem indul, és a hiba
        # megmutatja a legközelebbi kulcskockákat. A kiterjesztés-eltérést a felhasználó dönti el.
        ask = (lambda q: P.mb.askyesno("FFmpeg", q)) if hasattr(P.mb, "askyesno") else None
        try:
            out = lvt_iframe.resolve_target(self.src, out, ask)
            ffc = lvt_smartcut.CommandFFmpeg(ff.ffmpeg, getattr(ff, "ffprobe", None) or "ffprobe")
            info = ffc.probe(self.src)
            times = self._iframe_times(ffc, info)
            lvt_iframe.plan_ranges(items, times, duration=self.dur)
        except Exception as ex:
            P.mb.showwarning("FFmpeg", str(ex))
            return
        P.o["out"].set(out)
        base, ext = os.path.splitext(out)
        tmpdir = None
        if len(items) == 1:
            targets, join = [out], False
        elif join:
            tmpdir = tempfile.mkdtemp(prefix="lvt_")
            targets = [os.path.join(tmpdir, "part_%03d%s" % (i + 1, ext)) for i in range(len(items))]
        else:
            targets = ["%s_%03d%s" % (base, i + 1, ext) for i in range(len(items))]
        jobs = []
        workdir = tempfile.mkdtemp(prefix="lvt_if_")      # a videó- és hangdarabok köztes fájljai
        try:
            for (a, b), tg in zip(items, targets):
                for c in lvt_iframe.part_commands(ff, self.src, info, a, b, tg, workdir, times):
                    jobs.append((c, float(b) - float(a)))
        except Exception as ex:
            P.mb.showwarning("FFmpeg", str(ex))
            shutil.rmtree(workdir, ignore_errors=True)
            if tmpdir:
                shutil.rmtree(tmpdir, ignore_errors=True)
            return
        final = None

        def cleanup():
            shutil.rmtree(workdir, ignore_errors=True)
            if tmpdir:
                shutil.rmtree(tmpdir, ignore_errors=True)
        if join:
            def final():
                lst = os.path.join(tmpdir, "list.txt")
                with open(lst, "w", encoding="utf-8") as fh:
                    for tg in targets:
                        fh.write("file '%s'\n" % tg.replace("\\", "/").replace("'", "'\\''"))
                cmd = [ff.ffmpeg, "-hide_banner", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                       "-map", "0:v?", "-map", "0:a?", "-c", "copy"] + lvt_iframe._out_args(out)
                ff.run_convert(cmd + [out], None, None, None, P.cancel)
        self._status(_("I-frame mentés: kulcskockás vágás, a videó másolva, a hang újrakódolva.",
                       "I-frame export: keyframe cut, video copied, audio re-encoded."))
        P.run_jobs(ff, jobs, final=final, out=out, cleanup=cleanup)

    def shutdown(self):
        self.pause(quiet=True)
        self.fw.stop()
        self.ww.stop()


# ----------------------------------------------------------------- licenc-figyelmeztetés ---

def show_license_gate(master, tk, ttk):
    """Licenc-figyelmeztetés: az OK csak a szöveg legvégére görgetés után aktív. True, ha elfogadták."""
    text = _(
        "FIGYELEM – KÜLSŐ PROGRAM (FFmpeg)\n\n"
        "Ez a modul NEM tartalmazza az FFmpeg-et, nem csomagolja és nem tölti le. "
        "A következő ablakban a saját gépeden telepített ffmpeg, ffprobe és ffplay "
        "programok helyét kell megadnod.\n\n"
        "Az FFmpeg külön program, a saját licence vonatkozik rá, nem erre a programra. "
        "A licenc a használt buildtől függően LGPL vagy GPL (egyes buildek nonfree "
        "kapcsolóval készülnek, ezek nem terjeszthetők). A pontos feltételeket az FFmpeg "
        "hivatalos oldalán találod: https://ffmpeg.org/legal.html\n\n"
        "Ez a modul az FFmpeg-et csak különálló programként, parancssorból indítja el. "
        "A kódja nem része ennek a programnak, és ennek a programnak az MIT-licence "
        "az FFmpeg-re nem terjed ki.\n\n"
        "Ha az FFmpeg-et te magad terjeszted (például telepítőben vagy a programmal együtt), "
        "annak licencfeltételeit külön, önállóan kell teljesítened.\n\n"
        "A program a használatból eredő károkért nem vállal felelősséget. "
        "Csak olyan felvételekkel használd, amelyekhez jogod van.\n\n"
        "Kérlek, görgesd le a szöveg végéig és olvasd el. Az OK gomb csak ezután válik aktívvá.\n\n"
        "- vége -",
        "NOTICE – EXTERNAL PROGRAM (FFmpeg)\n\n"
        "This module does NOT include, bundle or download FFmpeg. In the next window you "
        "must give the location of the ffmpeg, ffprobe and ffplay programs installed on "
        "your own computer.\n\n"
        "FFmpeg is a separate program under its own license, not this program's. Depending "
        "on the build the license is LGPL or GPL (some builds use the nonfree switch and "
        "may not be redistributed). See the official page for the exact terms: "
        "https://ffmpeg.org/legal.html\n\n"
        "This module only starts FFmpeg as a separate command-line program. Its code is not "
        "part of this program, and this program's MIT License does not cover FFmpeg.\n\n"
        "If you distribute FFmpeg yourself (e.g. in an installer or together with this "
        "program), you must fulfil its license terms separately.\n\n"
        "No liability is accepted for any damage arising from use. Use only recordings you "
        "have the right to use.\n\n"
        "Please scroll to the end of the text and read it. The OK button becomes active only then.\n\n"
        "- end -")
    win = tk.Toplevel(master)
    win.title(_("FFmpeg – licenc", "FFmpeg – license"))
    win.geometry("640x470")
    win.transient(master)
    res = {"ok": False}
    fr = ttk.Frame(win, padding=10)
    fr.pack(fill="both", expand=True)
    box = ttk.Frame(fr)
    box.pack(fill="both", expand=True)
    t = tk.Text(box, wrap="word", padx=10, pady=8, height=10)
    sb = ttk.Scrollbar(box, orient="vertical", command=t.yview)
    t.insert("1.0", text)
    t.configure(state="disabled")
    row = ttk.Frame(fr)
    row.pack(fill="x", pady=(8, 0))
    btn_ok = ttk.Button(row, text="OK", state="disabled")

    def on_scroll(a, b):
        sb.set(a, b)
        if float(b) >= 0.999:
            btn_ok.state(["!disabled"])
    t.configure(yscrollcommand=on_scroll)
    t.pack(side="left", fill="both", expand=True)
    sb.pack(side="left", fill="y")

    def ok():
        res["ok"] = True
        win.destroy()
    btn_ok.configure(command=ok)
    btn_ok.pack(side="right")
    ttk.Button(row, text=_("Mégse", "Cancel"), command=win.destroy).pack(side="right", padx=6)
    try:
        import webbrowser
        ttk.Button(row, text=_("Licenc megnyitása a böngészőben", "Open license in browser"),
                   command=lambda: webbrowser.open("https://ffmpeg.org/legal.html")).pack(side="left")
    except Exception:       # noqa
        pass
    win.protocol("WM_DELETE_WINDOW", win.destroy)
    win.bind("<Escape>", lambda e: win.destroy())
    try:
        win.wait_visibility()
        win.grab_set()
    except Exception:       # noqa
        pass
    win.focus_force()
    win.wait_window()
    if res["ok"]:
        cfg = load_config()
        cfg["license_ok"] = True        # a modul bekapcsolásakor ne kérdezze újra
        save_config(cfg)
    return res["ok"]


# ----------------------------------------------------------------- belépési pontok ---

def open_window(master, tk, ttk, filedialog, messagebox, path="", t=0.0, start=None, end=None):
    """Külön ablakban nyitja a panelt. A licenc-figyelmeztetés az ELSŐ megnyitáskor
    jön elő; azt, hogy már megjelenítettük, a program mappájában lévő jelzőfájl
    (licence_mark_path()) tartja meg, ezért újratelepítés után újra kérdez. None, ha a
    felhasználó nem fogadta el – ilyenkor az ablak sem nyílik meg."""
    if notice_needed():
        clear_license_ok()   # a kapu maga is nézheti a kulcsot: most biztosan előjön
        if not show_license_gate(master, tk, ttk):
            return None
        accept_license()     # jelzőfájl az exe / a .py mappájába
    win = tk.Toplevel(master)
    win.title("FFmpeg – %s" % _("előnézet és átalakítás (opcionális)", "preview and convert (optional)"))
    win.geometry("1000x880")
    panel = FfmpegPanel(win, tk, ttk, filedialog, messagebox, path, t, start, end)
    win.protocol("WM_DELETE_WINDOW", lambda: (panel.close(), win.destroy()))
    return panel


def main(argv=None):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    argv = argv if argv is not None else sys.argv[1:]
    root = tk.Tk()
    root.title("Lossless Video Toolkit – FFmpeg")
    root.geometry("1000x880")
    if notice_needed():
        clear_license_ok()   # a kapu maga is nézheti a kulcsot: most biztosan előjön
        if not show_license_gate(root, tk, ttk):
            root.destroy()
            return 0
        accept_license()     # önálló indításnál is ugyanaz a jelzőfájl a mérvadó
    panel = FfmpegPanel(root, tk, ttk, filedialog, messagebox, argv[0] if argv else "")
    root.protocol("WM_DELETE_WINDOW", lambda: (panel.close(), root.destroy()))
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
