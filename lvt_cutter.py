#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 szabiz <szabiz@yahoo.com>
# Copyright (c) 2026 szabiz <szabiz@yahoo.com>
"""
Lossless Video Toolkit - VÁGÓ modul & Smart EKG Timeline (lvt_cutter.py)
=======================================================================
Veszteségmentes (újrakódolás nélküli) szétvágás és egyesítés kulcskockánál: TS / M2TS (AVCHD), MKV / WebM és (az opcionális lvt_mp4.py modullal) MP4 / M4V / MOV.
Az opcionális Smart Cut H.264/AVC videónál, MTS/TS, MKV és MP4 konténerben csak a nem IDR-határok széleit kódolja újra.

A veszteségmentes útvonal saját fejlesztésű, eredeti kód MIT licenc alatt, és csak a Python szabványos könyvtárát használja.
A Smart Cut külön választásra külső FFmpeg/ffprobe programot indít; a programokat nem csomagolja.
"""
import argparse
import bisect
import io
import json
import os
import re
import struct
import sys
import shutil
import threading
import zlib
from collections import Counter

CUTTER_VERSION = "1.44"
try:
    import lvt_mp4 as _mp4          # opcionális, saját MP4 modul (a főprogramot nem érinti)
except Exception:                   # hiányzik vagy hibás: az MP4 támogatás egyszerűen kikapcsol
    _mp4 = None
# Az FFmpeg-modulok (lvt_ffmpeg, lvt_smartcut) induláskor NEM töltődnek be, és a vágó nem is hivatkozik rájuk, amíg a
# felhasználó az FFmpeg fülön el nem fogadta az FFmpeg-feltételeket és be nem kapcsolta a modult (lásd _smartcut_gate).
_ffm = None
_smartcut = None
_ffm_tried = False


def _load_ffm():
    """Az opcionális FFmpeg-modulok betöltése (egyszer). Külső programot NEM indít."""
    global _ffm, _smartcut, _ffm_tried
    if _ffm_tried:
        return
    _ffm_tried = True
    try:
        import lvt_ffmpeg as m
        _ffm = m
    except Exception:
        _ffm = None
    try:
        import lvt_smartcut as m2
        _smartcut = m2
    except Exception:
        _smartcut = None


def _smartcut_gate():
    """(ffmpeg, ffprobe) útvonalak, ha a Smart Cut használható; különben None.
    Feltételek (mind): az FFmpeg-feltételek elfogadva, a modul bekapcsolva, az ffmpeg és az ffprobe helye megadva az
    FFmpeg fülön. Ha bármelyik hiányzik, a vágó a saját, FFmpeg nélküli veszteségmentes útján megy, és semmi nem utal
    az FFmpeg-re. A PATH-ban és a környezeti változókban nem keres, Megnyitás ablakot sem nyit."""
    _load_ffm()
    if _ffm is None or _smartcut is None:
        return None
    try:
        if _ffm.notice_needed() or not _ffm.is_enabled():
            return None
        c = _ffm.load_config()
    except Exception:
        return None
    ffmpeg = str(c.get("ffmpeg") or "")
    ffprobe = str(c.get("ffprobe") or "")
    if not ffprobe or not os.path.isfile(ffprobe):          # az ffprobe az ffmpeg mellett is lehet
        d = os.path.dirname(ffmpeg)
        ffprobe = next((os.path.join(d, n) for n in ("ffprobe.exe", "ffprobe") if os.path.isfile(os.path.join(d, n))), "")
    if not ffmpeg or not os.path.isfile(ffmpeg) or not ffprobe:
        return None
    return ffmpeg, ffprobe


TITLE = "Lossless Video Toolkit"
_INSTALLED = False


# ------------------------------------------------------------ szövegek, súgó ---
_USTR = {
    "hu": {
        "cu2_log_nosps": "Figyelem: a kezdőpontnál nincs SPS – a kimenet eleje hibás lehet. Válassz IDR pontot!",
        "cu2_time": "Idő: %s",
        "cu2_err_title": "Hiba",
        "cu2_info_fail": "Nem sikerült megnyitni az infót:\n%s",
        "cu2_same_kf": "A kezdet és a vég ugyanarra a kulcskockára esik – adj meg szélesebb tartományt.",
        "cu2_manual_snap": "Kézi tartomány (snap): %s -> %s",
        "cu2_busy": "Feldolgozás, kulcskockák elemzése...",
        "cu2_empty": "Nyiss meg egy videót a vágáshoz (üres idővonal)",
        "cu2_start_set": "Kezdőpont rögzítve: %s. Most kattints a másik pontra!",
        "cu2_same_pt": "A kezdő- és végpont ugyanaz – válassz másik pontot!",
        "cu2_added": "Tartomány hozzáadva: %s -> %s",
        "tab_cut": "Vágó",
        "cu_open": "Videó megnyitása…", "cu_nofile": "Nincs fájl megnyitva",
        "cu_scanning": "Kulcskockák és jelenetek keresése…",
        "cu_box": "Tartományok és Vezérlők",
        "cu_outdir": "Kimeneti mappa:", 
        "cu_start_sep": "Vágás külön fájlokba (Soronként)",
        "cu_start_merge": "Kivágott részek egyesítése 1 fájlba",
        "cu_method_title": "Vágási mód",
        "cu_method_question": "Hogyan szeretnéd feldolgozni a kijelölt tartományokat?",
        "cu_method_smart_title": "Smart Cut – H.264/AVC, kísérleti",
        "cu_method_smart_desc": "MTS/TS, MKV vagy MP4 H.264/AVC bemenethez. Az IDR-ek közötti videót másolja, csak a nem IDR-határok széleit kódolja újra. A hang egyben készül. A Smart Cut csak erre az opcióra kattintva indít FFmpeg-et. Ez az ablak csak akkor jelenik meg, ha az FFmpeg fülön elfogadtad az FFmpeg-feltételeket, bekapcsoltad a modult, és megadtad az ffmpeg / ffprobe helyét.",
        "cu_smart_choose_ffmpeg": "Válaszd ki az ffmpeg programot",
        "cu_smart_choose_ffprobe": "Válaszd ki az ffprobe programot",
        "cu_smart_need_bins": "A Smart Cut-hoz az ffmpeg és az ffprobe is szükséges.",
        "cu_method_smart_btn": "Smart Cut használata",
        "cu_method_lossless_title": "Veszteségmentes kulcskocka-vágás",
        "cu_method_lossless_desc": "A jelenlegi vágási útvonal: változatlanul megőrzi a kódolt adatokat, és a kiválasztott kulcskockákhoz igazít. Nem kódol újra, és nem indít külső programot.",
        "cu_method_lossless_btn": "Veszteségmentes vágás használata",
        "cu_method_cancel": "Mégse",
        "cu_smart_running": "Smart Cut fut…",
        "cu_smart_missing": "A lvt_smartcut.py helper nem tölthető be. Tedd a Cutter mellé, majd indítsd újra a programot.",
        "cu_smart_need_setup": "A Smart Cut-hoz az FFmpeg fülön el kell fogadnod az FFmpeg-feltételeket, be kell kapcsolnod a modult, és meg kell adnod az ffmpeg és az ffprobe helyét. A veszteségmentes vágás ettől függetlenül működik.",
        "cu_export": "Export (JSON / TXT)",
        "cu_help_btn": "Súgó / Magyarázat",
        "cu_help_title": "Lossless Cutter Súgó és Útmutató",
        "cu_help_text": (
            "LOSSLESS CUTTER RENDSZER ÚTMUTATÓ:\n\n"
            "• IDR (Tiszta kulcskocka):\n"
            "  Teljes értékű, független I-képkocka. Ez a legbiztonságosabb és legideálisabb vágási pont, "
            "amely garantálja a hibahelymentes illesztést és a tökéletes lejátszást.\n\n"
            "• REC (Visszaállási pont):\n"
            "  Olyan helyreállítási jelzéssel ellátott pont, amely segít a dekódernek magához térni "
            "és helyreállítani a videófolyamot.\n\n"
            "• Offset (Bájteltolódás):\n"
            "  A fájlon belüli pontos fizikai pozíció bájtokban. A veszteségmentes vágáshoz ez kötelező, "
            "mivel a videót nem képkocka sorszámok, hanem bájthatárok szerint vágjuk szét.\n\n"
            "• Kézi tartomány megadás (Snap funkció):\n"
            "  Írd be a kívánt időintervallumot a mezőbe (pl. 25:41.1-29:00.0), majd kattints a "
            "Hozzáadás gombra. A program automatikusan a legközelebbi érvényes kulcskockára igazítja a tartományt."
        ),
        "cu_manual_lbl": "Kézi tartomány (Kezdet - Vég):",
        "cu_manual_add": "Hozzáadás",
        "cu_manual_err": "Hibás formátum! Használd a Kezdet-Vég formátumot (pl. 0:00:01.0-0:00:08.1)",
        "cu_all_head": "Összes lehetséges kulcskocka (2 kattintás = Tartomány kijelölése)",
        "cu_sel_head": "Végrehajtási terv (Kiválasztott tartományok)",
        "cu_col_time": "Időpont", "cu_col_byte": "Offset", "cu_col_type": "Típus",
        "cu_col_part": "Rész", "cu_col_start": "Kezdet", "cu_col_end": "Vég", "cu_col_len": "Hossz", "cu_col_size": "MB",
        "cu_col_cut": "Típus",
        "cu_k_idr": "IDR (tiszta)", "cu_k_rec": "visszaállási pont", "cu_k_start": "a fájl eleje",
        "cu_nokey": "Nem található vágásra alkalmas kulcskocka a fájlban",
        "cu_nocut": "Nincs kiválasztva vágási tartomány",
        "cu_cv_hint": " (Kattints a sávra | 2 kattintás a bal oldalon: Kezdet/Vég | Nagyítás: egérgörgő vagy + / - | Mozgatás: jobb gomb húzása)",
        "cu_done": "A művelet sikeresen elkészült.",
        "cu_l_head": "Fájl vágása: %s (%d tartomány)...",
        "cu_l_done": "Kész! Mentve ide: %s",
        "cu_unsup": "Nem támogatott fájltípus a vágáshoz",
        'vf_empty': 'A fájl nem létezik vagy üres.',
        'vf_nofmt': 'Ismeretlen fájlformátum (nem TS/M2TS/MKV).',
        'vf_nosync': 'Nem található érvényes TS csomagszerkezet.',
        'vf_size': 'A fájlméret nem a csomagméret (%d) többszöröse – a fájl csonka vagy elcsúszott.',
        'vf_sync': 'Szinkronvesztés: %d hibás csomag.',
        'vf_nopsi': 'A fájl elején nincs PAT/PMT a videó előtt – a lejátszók nem ismerik fel a sávokat.',
        'vf_novideo': 'Nincs videó elemi folyam a fájlban.',
        'vf_nokey': 'A videó nem kulcskockával kezdődik.',
        'vf_nosps': 'A kezdő képnél nincs SPS – egyes lejátszóknál az eleje hibás lehet.',
        'vf_start': 'Kezdőpont típusa: %s',
        'vf_pes': 'Hibás PES kezdet: %d db.',
        'vf_cc': 'Folytonossági számláló eltérés: %d db.',
        'vf_back': 'Visszalépő videó-időbélyeg: %d helyen (az első %.1f s-nál).',
        'vf_gap': 'Időugrás a videóban: %.1f s a %.1f s környékén (%d db).',
        'vf_pcr': 'PCR visszalépés vagy ugrás: %d db.',
        'vf_lead': 'Maradt %d vezető (a kezdőképnél korábbi) kocka – az eleje hibás lehet.',
        'vf_dur': 'Hossz: %.1f s (%d egység).',
        'vf_durdiff': 'A tényleges hossz (%.1f s) eltér a vártól (%.1f s).',
        'vf_noaudio': 'Nincs hang a fájlban (PID %d).',
        'vf_cancel': 'Az ellenőrzés megszakítva.',
        'vf_exc': 'Az ellenőrzés váratlan hibával leállt: %s',
        'vf_ok': 'Ellenőrzés: nincs hiba, a fájl szerkezete rendben van.',
        'vf_mkv_ebml': 'Hibás EBML fejléc.',
        'vf_mkv_noseg': 'Hiányzik a Segment elem.',
        'vf_mkv_segsize': 'A Segment mérete (%d) nem egyezik a fájlmérettel (%d).',
        'vf_mkv_segunk': 'A Segment mérete ismeretlen (egyes lejátszók nem tudnak tekerni).',
        'vf_mkv_bad': 'Hibás elem a(z) %d. bájtnál.',
        'vf_mkv_trunc': 'Csonka elem a(z) %d. bájtnál – a fájl vége hiányzik.',
        'vf_mkv_nohdr': 'Hiányzik az Info vagy a Tracks elem.',
        'vf_mkv_noclu': 'Nincs klaszter a fájlban.',
        'vf_mkv_seek': 'A SeekHead hibás mutatót tartalmaz (%s).',
        'vf_mkv_cues': 'A Cues %d db hibás klaszter-pozíciót tartalmaz.',
        'vf_mkv_nocues': 'Nincs Cues (a tekerés lassú lehet).',
        'vf_mkv_tcback': 'Visszalépő klaszter-időkód: %d helyen.',
        'vf_mkv_gap': 'Nagy időugrás a klaszterek között: %.1f s (%d db).',
        'vf_mkv_nokey': 'Az első videóblokk nem kulcskocka.',
        'vf_mkv_dur': 'Az Info Duration (%.1f s) eltér a tényleges hossztól (%.1f s).',
        'vf_mkv_clbad': 'A klaszter (%d. bájt) belső elemei hibásak.',
        'vf_mkv_neg': 'Negatív blokk-időbélyeg: %d db.',
        'vf_ajump': 'A hang időbélyege ugrik (PID %d, %d helyen) – a hang és a videó elcsúszik egymástól.',
        'vf_avstart': 'A hang (PID %d) kezdete %.1f s-sal eltér a videó kezdetétől.',
        'vf_mp4_box': '%s',
        'vf_mp4_nomdat': 'Hiányzik az mdat (a médiaadat).',
        'vf_mp4_nomoov': 'Hiányzik a moov (a fájl szerkezete).',
        'vf_mp4_frag': 'Töredezett (fragmentált) MP4 – a részletes ellenőrzés nem végezhető el.',
        'vf_mp4_tbl': '%d. sáv: hibás táblázat (%s).',
        'vf_mp4_range': '%d. sáv: %d minta a fájlon kívülre mutat.',
        'vf_mp4_nosync': 'A videó első mintája nem kulcskocka.',
        'vf_mp4_dur': '%d. sáv: a mintaidők összege (%.2f s) eltér a sáv hosszától (%.2f s).',
        'vf_mp4_avdiff': 'A videó (%.2f s) és a hang (%.2f s) hossza eltér.',
    },
    "en": {
        "cu2_log_nosps": "Warning: no SPS at the start point – the beginning of the output may be broken. Choose an IDR point!",
        "cu2_time": "Time: %s",
        "cu2_err_title": "Error",
        "cu2_info_fail": "Could not open the info:\n%s",
        "cu2_same_kf": "The start and the end fall on the same keyframe – enter a wider range.",
        "cu2_manual_snap": "Manual range (snap): %s -> %s",
        "cu2_busy": "Processing, analyzing keyframes...",
        "cu2_empty": "Open a video to cut (empty timeline)",
        "cu2_start_set": "Start point set: %s. Now click the other point!",
        "cu2_same_pt": "The start and end points are the same – choose another point!",
        "cu2_added": "Range added: %s -> %s",
        "tab_cut": "Cutter",
        "cu_open": "Open video…", "cu_nofile": "No file opened",
        "cu_scanning": "Scanning key frames & scenes…",
        "cu_box": "Ranges & Controls",
        "cu_outdir": "Output folder:", 
        "cu_start_sep": "Cut into separate files",
        "cu_start_merge": "Merge ranges into 1 file",
        "cu_method_title": "Cut method",
        "cu_method_question": "How should the selected ranges be processed?",
        "cu_method_smart_title": "Smart Cut – H.264/AVC, experimental",
        "cu_method_smart_desc": "For H.264/AVC in MTS/TS, MKV, or MP4. Copies video between IDRs and re-encodes only non-IDR cut edges; audio is encoded once. FFmpeg is launched only if chosen. This window appears only after you accepted the FFmpeg terms on the FFmpeg tab, enabled the module and set the ffmpeg / ffprobe locations.",
        "cu_smart_choose_ffmpeg": "Select the ffmpeg executable",
        "cu_smart_choose_ffprobe": "Select the ffprobe executable",
        "cu_smart_need_bins": "Smart Cut requires both ffmpeg and ffprobe.",
        "cu_method_smart_btn": "Use Smart Cut",
        "cu_method_lossless_title": "Lossless keyframe cut",
        "cu_method_lossless_desc": "Keeps the current cutting path: preserves the encoded data and aligns cuts to the selected keyframes. No re-encoding and no external program is launched.",
        "cu_method_lossless_btn": "Use lossless cut",
        "cu_method_cancel": "Cancel",
        "cu_smart_running": "Smart Cut running…",
        "cu_smart_missing": "The lvt_smartcut.py helper could not be loaded. Put it beside the Cutter module and restart the application.",
        "cu_smart_need_setup": "Smart Cut requires that on the FFmpeg tab you accept the FFmpeg terms, enable the module and set the ffmpeg and ffprobe locations. Lossless cutting works regardless.",
        "cu_export": "Export (JSON / TXT)",
        "cu_help_btn": "Help & Explanation",
        "cu_help_title": "Lossless Cutter Help & Guide",
        "cu_help_text": (
            "LOSSLESS CUTTER GUIDE:\n\n"
            "• IDR (Clean Keyframe): Independent I-frame, ideal and safest cut point ensuring glitch-free joining.\n\n"
            "• REC (Recovery Point): Helps the decoder recover the stream.\n\n"
            "• Offset (Byte Offset): Precise physical position in bytes within the file, required for lossless cutting.\n\n"
            "• Manual Range Input: Enter the desired time range (e.g. 25:41.1-29:00.0), and the program automatically snaps it to the nearest valid keyframe."
        ),
        "cu_manual_lbl": "Manual Range (Start - End):",
        "cu_manual_add": "Add Range",
        "cu_manual_err": "Invalid format! Use Start-End format (e.g. 0:00:01.0-0:00:08.1)",
        "cu_all_head": "All Keyframes (2 clicks = Range Selection)",
        "cu_sel_head": "Execution Plan (Selected Ranges)",
        "cu_col_time": "Time", "cu_col_byte": "Offset", "cu_col_type": "Type",
        "cu_col_part": "Part", "cu_col_start": "Start", "cu_col_end": "End", "cu_col_len": "Length", "cu_col_size": "MB",
        "cu_col_cut": "Type",
        "cu_k_idr": "IDR (clean)", "cu_k_rec": "recovery point", "cu_k_start": "start of file",
        "cu_nokey": "No suitable key frame found",
        "cu_nocut": "No ranges selected",
        "cu_cv_hint": " (Click timeline | Double click left list: Start/End | Zoom: mouse wheel or + / - | Pan: drag right button)",
        "cu_done": "Operation finished.",
        "cu_l_head": "Cutting file: %s (%d ranges)...",
        "cu_l_done": "Done! Saved to: %s",
        "cu_unsup": "Unsupported file type for cutting",
        'vf_empty': 'File missing or empty.',
        'vf_nofmt': 'Unknown file format (not TS/M2TS/MKV).',
        'vf_nosync': 'No valid TS packet structure found.',
        'vf_size': 'File size is not a multiple of the packet size (%d) - truncated or misaligned.',
        'vf_sync': 'Lost sync: %d bad packets.',
        'vf_nopsi': 'No PAT/PMT before the first video packet - players cannot identify the streams.',
        'vf_novideo': 'No video elementary stream in the file.',
        'vf_nokey': 'The video does not start with a key frame.',
        'vf_nosps': 'No SPS at the start picture - the beginning may be broken in some players.',
        'vf_start': 'Start point type: %s',
        'vf_pes': 'Invalid PES start: %d.',
        'vf_cc': 'Continuity counter mismatches: %d.',
        'vf_back': 'Video timestamp goes backwards at %d places (first at %.1f s).',
        'vf_gap': 'Time jump in video: %.1f s around %.1f s (%d).',
        'vf_pcr': 'PCR backward step or jump: %d.',
        'vf_lead': '%d leading pictures (earlier than the start picture) remain - the start may be broken.',
        'vf_dur': 'Length: %.1f s (%d units).',
        'vf_durdiff': 'Actual length (%.1f s) differs from the expected (%.1f s).',
        'vf_noaudio': 'No audio in the file (PID %d).',
        'vf_cancel': 'Verification cancelled.',
        'vf_exc': 'Verification stopped with an unexpected error: %s',
        'vf_ok': 'Verification: no problems found, the file structure is fine.',
        'vf_mkv_ebml': 'Invalid EBML header.',
        'vf_mkv_noseg': 'Segment element missing.',
        'vf_mkv_segsize': 'Segment size (%d) does not match the file size (%d).',
        'vf_mkv_segunk': 'Segment size is unknown (some players cannot seek).',
        'vf_mkv_bad': 'Invalid element at byte %d.',
        'vf_mkv_trunc': 'Truncated element at byte %d - the end of the file is missing.',
        'vf_mkv_nohdr': 'Info or Tracks element missing.',
        'vf_mkv_noclu': 'No clusters in the file.',
        'vf_mkv_seek': 'SeekHead contains a wrong pointer (%s).',
        'vf_mkv_cues': 'Cues contain %d invalid cluster positions.',
        'vf_mkv_nocues': 'No Cues (seeking may be slow).',
        'vf_mkv_tcback': 'Cluster timecode goes backwards at %d places.',
        'vf_mkv_gap': 'Large time jump between clusters: %.1f s (%d).',
        'vf_mkv_nokey': 'The first video block is not a key frame.',
        'vf_mkv_dur': 'Info Duration (%.1f s) differs from the actual length (%.1f s).',
        'vf_mkv_clbad': 'Cluster (byte %d) has invalid inner elements.',
        'vf_mkv_neg': 'Negative block timestamps: %d.',
        'vf_ajump': 'Audio timestamp jumps (PID %d, %d places) - audio and video drift apart.',
        'vf_avstart': 'Audio (PID %d) starts %.1f s away from the video start.',
        'vf_mp4_box': '%s',
        'vf_mp4_nomdat': 'mdat (media data) is missing.',
        'vf_mp4_nomoov': 'moov (file structure) is missing.',
        'vf_mp4_frag': 'Fragmented MP4 - detailed verification is not possible.',
        'vf_mp4_tbl': 'Track %d: invalid table (%s).',
        'vf_mp4_range': 'Track %d: %d samples point outside the file.',
        'vf_mp4_nosync': 'The first video sample is not a key frame.',
        'vf_mp4_dur': 'Track %d: sample times add up to %.2f s, the track length is %.2f s.',
        'vf_mp4_avdiff': 'Video (%.2f s) and audio (%.2f s) lengths differ.',
    },
}

_CUT_NOTES = {
    "hu": "\n\nA vágó és a Smart Cut modul (lvt_cutter.py, lvt_mp4.py) saját fejlesztésű, eredeti kód, MIT licenc alatt. "
          "Kizárólag a Python szabványos könyvtárát használja (PSF licenc, az MIT-tel kompatibilis); külső programot "
          "csak Smart Cut választásakor indít külső FFmpeg-et; idegen kódot nem tartalmaz.",
    "en": "\n\nThe cutter and Smart Cut modules (lvt_cutter.py, lvt_mp4.py) are original, self-developed code under the "
          "MIT License. They use only the Python standard library (PSF license, MIT-compatible); they call no external "
          "programs for lossless cutting; Smart Cut launches FFmpeg only when selected. No third-party code.",
}

_CUT_HELP = {
    "hu": ("Vágó & Smart Cut", """## Tartomány Vágó és Egyesítő
Kattints két pontra a bal oldali listában a vágási tartomány meghatározásához.""", "\nSmart Cut: opcionális FFmpeg/ffprobe; csak külön választásra indul."),
    "en": ("Cutter & Smart Cut", """## Range Cutter & Merger""", "\nSmart Cut: optional FFmpeg/ffprobe, launched only when selected."),
}


# ======================================================================
# EBML / MKV Segédkonstansok és kódolók
# ======================================================================

ID_SEGMENT = 0x18538067
ID_INFO = 0x1549A966
ID_TRACKS = 0x1654AE6B
ID_CUES = 0x1C53BB6B
ID_CLUSTER = 0x1F43B675
ID_TIMECODE = 0xE7
ID_POSITION = 0xA7
ID_PREVSIZE = 0xAB
ID_CRC32 = 0xBF
ID_VOID = 0xEC
MKV_UNKNOWN = b'\x01\xff\xff\xff\xff\xff\xff\xff'

def _encode_vint(val):
    if val < 0x7F:
        return bytes([0x80 | val])
    elif val < 0x3FFF:
        return bytes([0x40 | (val >> 8), val & 0xFF])
    elif val < 0x1FFFFF:
        return bytes([0x20 | (val >> 16), (val >> 8) & 0xFF, val & 0xFF])
    elif val < 0x0FFFFFFF:
        return bytes([0x10 | (val >> 24), (val >> 16) & 0xFF, (val >> 8) & 0xFF, val & 0xFF])
    return bytes([0x01, (val >> 56) & 0xFF, (val >> 48) & 0xFF, (val >> 40) & 0xFF, (val >> 32) & 0xFF, (val >> 24) & 0xFF, (val >> 16) & 0xFF, (val >> 8) & 0xFF, val & 0xFF])

def _eb_id(eid):
    if eid <= 0xFF: return bytes([eid])
    elif eid <= 0xFFFF: return bytes([eid >> 8, eid & 0xFF])
    elif eid <= 0xFFFFFF: return bytes([eid >> 16, (eid >> 8) & 0xFF, eid & 0xFF])
    elif eid <= 0xFFFFFFFF: return bytes([eid >> 24, (eid >> 16) & 0xFF, (eid >> 8) & 0xFF, eid & 0xFF])
    return bytes([eid >> 32, (eid >> 24) & 0xFF, (eid >> 16) & 0xFF, (eid >> 8) & 0xFF, eid & 0xFF])

def _eb_uint(eid, val, size=None):
    if size is None:
        if val < 0x100: size = 1
        elif val < 0x10000: size = 2
        elif val < 0x1000000: size = 3
        elif val < 0x100000000: size = 4
        else: size = 8
    b = val.to_bytes(size, 'big')
    return _eb_id(eid) + _encode_vint(len(b)) + b

def _eb(eid, data):
    return _eb_id(eid) + _encode_vint(len(data)) + data

def _mkv_seekhead(entries):
    # Seek (0x4DBB) { SeekID (0x53AB) = nyers elem-ID, SeekPosition (0x53AC) }.
    # A pozíciók mindig 8 bájtosak, így a SeekHead hossza a végső (visszaírt) változatban is ugyanaz.
    seeks = []
    for eid, pos in entries:
        seeks.append(_eb(0x4DBB, _eb(0x53AB, _eb_id(eid)) + _eb_uint(0x53AC, pos, 8)))
    return _eb(0x114D9B74, b"".join(seeks))

def _mkv_cues(cues_data, track=1):
    # CuePoint { CueTime, CueTrackPositions { CueTrack, CueClusterPosition } }
    pts = []
    for tc, pos in cues_data:
        cp = _eb_uint(0xB3, tc) + _eb(0xB7, _eb_uint(0xF7, track) + _eb_uint(0xF1, pos))
        pts.append(_eb(0xBB, cp))
    return _eb(ID_CUES, b"".join(pts))

def _mkv_whole(eid, raw):
    # biztosítja, hogy a másolt elem az ID + méret fejléccel együtt kerüljön a kimenetbe
    idb = _eb_id(eid)
    return raw if raw.startswith(idb) else idb + _encode_vint(len(raw)) + raw


# ======================================================================
# Smart & Scene# ======================================================================
# Smart & Scene Detection Logika
# ======================================================================

def detect_scenes(scan, threshold_ratio=1.5):
    kfs = scan.get("kfs", [])
    if len(kfs) < 3:
        return []
    sizes = [kfs[i][2] - kfs[i-1][2] for i in range(1, len(kfs))]
    if not sizes:
        return []
    avg_size = sum(sizes) / len(sizes)
    scenes = []
    for i, size in enumerate(sizes):
        if size > avg_size * threshold_ratio:
            scenes.append(kfs[i+1][0])
    return scenes

def smart_cut_recommendation(scan):
    cands = scan["cands"]
    if len(cands) < 2:
        return []
    scenes = detect_scenes(scan)
    pick_indices = []
    for st in scenes:
        best_idx = min(range(len(cands)), key=lambda i: abs(cands[i][0] - st))
        if best_idx not in pick_indices:
            pick_indices.append(best_idx)
    if not pick_indices and len(cands) >= 4:
        step = len(cands) // 3
        for i in range(0, len(cands), step):
            pick_indices.append(i)
    if len(pick_indices) < 2:
        pick_indices = [0, len(cands) - 1]
    
    pick_indices.sort()
    ranges = []
    for i in range(0, len(pick_indices) - 1, 2):
        ranges.append((cands[pick_indices[i]], cands[pick_indices[i+1]]))
    if not ranges and len(cands) >= 2:
        ranges.append((cands[0], cands[-1]))
    return ranges

def export_cuts_json(ranges, scan, filepath):
    data = {
        "version": CUTTER_VERSION,
        "duration": scan["dur"],
        "ranges": [{"start": r[0][0], "end": r[1][0], "start_byte": r[0][2], "end_byte": r[1][2]} for r in ranges]
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def export_cuts_txt(ranges, scan, filepath):
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("# Lossless Video Toolkit - Ranges List\n")
        for i, r in enumerate(ranges):
            f.write(f"Range {i+1}: {r[0][0]:.3f}s -> {r[1][0]:.3f}s\n")


# ------------------------------------------------------------ kulcskockák & vágó ---

def _ts_sync_origin(data, ps, H):
    # a csomagrács kezdőeltolása: 5 egymás utáni csomag szinkronbájtja (0x47) H eltolással
    for o in range(ps):
        ok = True
        for n in range(5):
            p = o + n * ps + H
            if p >= len(data) or data[p] != 0x47:
                ok = False
                break
        if ok:
            return o
    return 0

def _ts_payload_off(pkt, H):
    t = H
    afc = (pkt[t + 3] >> 4) & 3
    if not (afc & 1):
        return -1
    off = t + 4
    if afc & 2:
        off += 1 + pkt[t + 4]
    return off if off < t + 188 else -1

def _ts_psi_packets(inf):
    # A fájl elejéről kigyűjti a PAT és PMT csomagot. Ezek nélkül a kivágott
    # fájl elején nincs program-tábla, és a lejátszók nem tudják, mit játsszanak.
    ps, H = inf.ps, inf.H
    pmt_pid = getattr(inf, "pmt_pid", 0) or 0
    psi = {}
    try:
        with open(inf.path, "rb") as f:
            data = f.read(ps * 30000)
    except OSError:
        return psi, pmt_pid
    org = _ts_sync_origin(data, ps, H)
    for o in range(org, len(data) - ps + 1, ps):
        pkt = data[o:o + ps]
        t = H
        if pkt[t] != 0x47 or not (pkt[t + 1] & 0x40):
            continue
        pid = ((pkt[t + 1] & 0x1F) << 8) | pkt[t + 2]
        if pid == 0 and 0 not in psi:
            po = _ts_payload_off(pkt, H)
            if po < 0:
                continue
            s = po + 1 + pkt[po]
            if s + 8 > t + 188 or pkt[s] != 0:
                continue
            sec_len = ((pkt[s + 1] & 0x0F) << 8) | pkt[s + 2]
            end = min(s + 3 + sec_len - 4, t + 188)
            q = s + 8
            while q + 4 <= end:
                prog = (pkt[q] << 8) | pkt[q + 1]
                ppid = ((pkt[q + 2] & 0x1F) << 8) | pkt[q + 3]
                if prog != 0:
                    if not pmt_pid:
                        pmt_pid = ppid
                    break
                q += 4
            psi[0] = bytes(pkt)
        elif pmt_pid and pid == pmt_pid and pmt_pid not in psi:
            psi[pmt_pid] = bytes(pkt)
        if 0 in psi and pmt_pid in psi:
            break
    return psi, pmt_pid

def _ts_is_key(vtype, es, rai):
    es = bytes(es)
    if vtype == 0x1B:
        lead = _h264_lead(es)
        if lead is not None:
            nals, key = lead
            return (("idr" if nals[-1][0] == 5 else "rec") if key else None)
        return "rec" if rai else None
    if vtype == 0x24:
        j = es.find(b"\x00\x00\x01")
        while 0 <= j < len(es) - 3:
            nt = (es[j + 3] >> 1) & 0x3F
            if 16 <= nt <= 21:
                return "idr" if nt <= 20 else "rec"
            if nt < 32:
                return None
            j = es.find(b"\x00\x00\x01", j + 3)
        return "rec" if rai else None
    if vtype in (0x01, 0x02):
        return "idr" if b"\x00\x00\x01\xb3" in es else ("rec" if rai else None)
    return "rec" if rai else None

def _cut_scan_ts(inf, progress, cancel):
    ps, H, vpid, v0 = inf.ps, inf.H, inf.vpid, inf.v_first
    kfs, cur, k0 = [], [None], 0
    def fin():
        c = cur[0]
        cur[0] = None
        if c is not None and c["ts"] is not None:
            kt = _ts_is_key(inf.vtype, c["es"], c["rai"])
            if kt:
                kfs.append((sdiff(c["ts"], v0) / 90000.0, c["k"], c["k"] * ps, kt))
    for buf in _ts_iter(inf, cancel, progress):
        for i, (t, pid, pusi, afc, cc, pay, pcr) in enumerate(iter_packets(buf, ps, H)):
            if pid != vpid or pay < 0:
                continue
            c = cur[0]
            if pusi:
                fin()
                es = _pes_es_start(buf, pay, t + 188)
                if es < 0:
                    continue
                tm = pes_times(buf, pay, t + 188)
                cur[0] = {"k": k0 + i, "es": bytearray(buf[es:t + 188]), "rai": bool(
                    (afc & 2) and buf[t + 4] > 0 and (buf[t + 5] & 0x40)),
                    "ts": None if tm is None else (tm[1] if tm[1] is not None else tm[0])}
            elif c is not None and len(c["es"]) < 4096:
                c["es"] += buf[pay:t + 188]
        k0 += len(buf) // ps
    fin()
    return kfs

def _cut_scan_mkv(inf, progress, cancel):
    pt, scale, n = inf.ptrack, inf.scale, float(max(1, len(inf.clusters)))
    kfs = []
    with open(inf.path, "rb") as f:
        for ci, (cp, ds, end) in enumerate(inf.clusters):
            if cancel is not None and cancel.is_set():
                raise MsgError("cancelled")
            tc = _mkv_cluster_tc(f, ds, end)
            for eid, ep, ee, info in _mkv_cluster_items(f, ds, end):
                if info is not None and info[0] == pt.number:
                    if info[4] or pt.type != 1:
                        kfs.append(((tc + info[1] - inf.t_start) * scale / 1e9, ci, cp, "idr"))
                    break
            progress((ci + 1) / n)
    return kfs

def _mp4_call(fn, *a, **k):
    # az MP4 modul hibáit a vágó saját hibatípusaira fordítja
    try:
        return fn(*a, **k)
    except _mp4.Mp4Error as e:
        if str(e) == "cancelled":
            raise MsgError("cancelled")
        raise RuntimeError(str(e))


def cut_scan(inf, progress=None, cancel=None):
    progress = progress or (lambda f: None)
    if inf.kind == "ts":
        kfs, gap = _cut_scan_ts(inf, progress, cancel), max(0.05, inf.fd / 90000.0)
    elif inf.kind == "mkv":
        kfs, gap = _cut_scan_mkv(inf, progress, cancel), 0.05
    elif inf.kind == "mp4" and _mp4 is not None:
        kfs, gap = _mp4_call(_mp4.scan_keyframes, inf, progress, cancel), 0.05
    else:
        raise MsgError("cu_unsup")
    cands = [x for x in kfs if x[0] >= 0]
    if not cands:
        raise MsgError("cu_nokey")
    return {"kind": inf.kind, "kfs": kfs, "cands": cands, "dur": inf.duration, "size": inf.size}

def cut_ranges_info(scan, ranges):
    rows = []
    for r in ranges:
        t0, t1 = r[0][0], r[1][0]
        b0, b1 = r[0][2], r[1][2]
        rows.append((t0, t1, max(0.0, t1 - t0), max(0, b1 - b0), r[0][3]))
    return rows

def _cut_paths(outdir, stem, ext, n):
    k = 0
    while True:
        base = stem if k == 0 else "%s_%d" % (stem, k)
        paths = [os.path.join(outdir, "%s_%02d%s" % (base, i + 1, ext)) for i in range(n)]
        if not any(os.path.exists(p) or os.path.exists(os.path.splitext(p)[0] + "_HIBAS" + ext) for p in paths):
            return paths
        k += 1

def _ts_origin(inf):
    try:
        with open(inf.path, "rb") as f:
            return _ts_sync_origin(f.read(inf.ps * 8), inf.ps, inf.H)
    except OSError:
        return 0

def _ts_fix_cc(buf, t, cc):
    # folytonossági számláló (continuity counter) újraszámolása PID-enként
    pid = ((buf[t + 1] & 0x1F) << 8) | buf[t + 2]
    if pid == 0x1FFF:
        return
    b3 = buf[t + 3]
    last = cc.get(pid)
    if (b3 >> 4) & 1:
        c = 0 if last is None else (last + 1) & 15
        cc[pid] = c
    else:
        c = 0 if last is None else last
    buf[t + 3] = (b3 & 0xF0) | c

_M33 = (1 << 33) - 1

def _ts_rd33(b, o):
    return (((b[o] >> 1) & 7) << 30) | (b[o + 1] << 22) | ((b[o + 2] >> 1) << 15) | (b[o + 3] << 7) | (b[o + 4] >> 1)

def _ts_wr33(b, o, v):
    b[o] = (b[o] & 0xF1) | (((v >> 30) & 7) << 1)
    b[o + 1] = (v >> 22) & 0xFF
    b[o + 2] = (((v >> 15) & 0x7F) << 1) | 1
    b[o + 3] = (v >> 7) & 0xFF
    b[o + 4] = ((v & 0x7F) << 1) | 1

def _ts_first_times(inf, start_byte):
    # a szakasz első videó-PES csomagjának (PTS, DTS) értéke, 90 kHz-ben
    ps, H = inf.ps, inf.H
    vpid = getattr(inf, "vpid", None)
    try:
        with open(inf.path, "rb") as f:
            f.seek(start_byte)
            for _ in range(2000):
                pkt = f.read(ps)
                if len(pkt) < ps or pkt[H] != 0x47:
                    return None
                pid = ((pkt[H + 1] & 0x1F) << 8) | pkt[H + 2]
                if not (pkt[H + 1] & 0x40) or pid < 0x20 or pid == 0x1FFF or (vpid is not None and pid != vpid):
                    continue
                po = _ts_payload_off(pkt, H)
                if po < 0 or po + 19 > len(pkt) or pkt[po:po + 3] != b"\x00\x00\x01" or (pkt[po + 6] & 0xC0) != 0x80:
                    continue
                if vpid is None and not (0xE0 <= pkt[po + 3] <= 0xEF):
                    continue
                fl = pkt[po + 7] >> 6
                pts = _ts_rd33(pkt, po + 9) if ((fl & 2) and pkt[po + 8] >= 5) else None
                dts = _ts_rd33(pkt, po + 14) if (fl == 3 and pkt[po + 8] >= 10) else None
                if pts is None:
                    continue
                return pts, dts
    except OSError:
        return None
    return None

def _ts_last_vtimes(inf, start_byte, end_byte):
    # a szakasz utolsó két videó-PES időbélyege (DTS, ennek hiányában PTS): (utolsó, képidő)
    ps, H = inf.ps, inf.H
    vpid = getattr(inf, "vpid", None)
    a = max(start_byte, end_byte - ps * 20000)
    a = start_byte + (a - start_byte) // ps * ps
    seq = []
    try:
        with open(inf.path, "rb") as f:
            f.seek(a)
            buf = f.read(end_byte - a)
    except OSError:
        return None
    for o in range(0, len(buf) - ps + 1, ps):
        t = o + H
        if buf[t] != 0x47 or not (buf[t + 1] & 0x40):
            continue
        pid = ((buf[t + 1] & 0x1F) << 8) | buf[t + 2]
        if pid < 0x20 or pid == 0x1FFF or (vpid is not None and pid != vpid):
            continue
        afc = (buf[t + 3] >> 4) & 3
        if not afc & 1:
            continue
        po = t + 4 + ((1 + buf[t + 4]) if (afc & 2) else 0)
        if po + 19 > o + ps or buf[po:po + 3] != b"\x00\x00\x01" or (buf[po + 6] & 0xC0) != 0x80:
            continue
        if vpid is None and not (0xE0 <= buf[po + 3] <= 0xEF):
            continue
        fl = buf[po + 7] >> 6
        if fl == 3 and buf[po + 8] >= 10:
            seq.append(_ts_rd33(buf, po + 14))
        elif (fl & 2) and buf[po + 8] >= 5:
            seq.append(_ts_rd33(buf, po + 9))
    if not seq:
        return None
    fd = None
    cnt = {}
    for x, y in zip(seq, seq[1:]):
        d = (y - x) & _M33
        if 0 < d < 9000:
            cnt[d] = cnt.get(d, 0) + 1
    if cnt:
        fd = max(cnt, key=cnt.get)      # a leggyakoribb DTS-lépés = képidő
    return seq[-1], fd


def _ts_first_vtime(inf, start_byte):
    r = _ts_first_times(inf, start_byte)
    if r is None:
        return None
    return r[1] if r[1] is not None else r[0]

def _ts_start_has_params(inf, start_byte):
    # Van-e SPS (H.264) / SPS (HEVC) a kezdő hozzáférési egységben? Nélküle a lejátszás eleje hibás lehet.
    vpid, vtype = getattr(inf, "vpid", None), getattr(inf, "vtype", None)
    if vpid is None or vtype not in (0x1B, 0x24):
        return True
    ps, H = inf.ps, inf.H
    es = bytearray()
    try:
        with open(inf.path, "rb") as f:
            f.seek(start_byte)
            first = True
            for _ in range(400):
                pkt = f.read(ps)
                if len(pkt) < ps or pkt[H] != 0x47:
                    break
                if (((pkt[H + 1] & 0x1F) << 8) | pkt[H + 2]) != vpid:
                    continue
                po = _ts_payload_off(pkt, H)
                if po < 0:
                    continue
                if pkt[H + 1] & 0x40:
                    if not first:
                        break
                    first = False
                es += pkt[po:H + 188]
                if len(es) > 4096:
                    break
    except OSError:
        return True
    j = es.find(b"\x00\x00\x01")
    while 0 <= j < len(es) - 3:
        b = es[j + 3]
        if vtype == 0x1B and (b & 0x1F) == 7:
            return True
        if vtype == 0x24 and ((b >> 1) & 0x3F) == 33:
            return True
        j = es.find(b"\x00\x00\x01", j + 3)
    return False

def _ts_shift_times(buf, o, t, ps, shift):
    # PCR és PES PTS/DTS eltolása, hogy egyesítésnél az idővonal folytonos legyen
    afc = (buf[t + 3] >> 4) & 3
    pid = ((buf[t + 1] & 0x1F) << 8) | buf[t + 2]
    if (afc & 2) and buf[t + 4] >= 7 and (buf[t + 5] & 0x10):
        base = (buf[t + 6] << 25) | (buf[t + 7] << 17) | (buf[t + 8] << 9) | (buf[t + 9] << 1) | (buf[t + 10] >> 7)
        base = (base + shift) & _M33
        buf[t + 6] = (base >> 25) & 0xFF
        buf[t + 7] = (base >> 17) & 0xFF
        buf[t + 8] = (base >> 9) & 0xFF
        buf[t + 9] = (base >> 1) & 0xFF
        buf[t + 10] = ((base & 1) << 7) | (buf[t + 10] & 0x7F)
    if (buf[t + 1] & 0x40) and (afc & 1) and pid >= 0x20 and pid != 0x1FFF:
        po = t + 4 + ((1 + buf[t + 4]) if (afc & 2) else 0)
        if po + 19 <= o + ps and buf[po:po + 3] == b"\x00\x00\x01" and (buf[po + 6] & 0xC0) == 0x80:
            fl = buf[po + 7] >> 6
            if (fl & 2) and buf[po + 8] >= 5:
                _ts_wr33(buf, po + 9, (_ts_rd33(buf, po + 9) + shift) & _M33)
            if fl == 3 and buf[po + 8] >= 10:
                _ts_wr33(buf, po + 14, (_ts_rd33(buf, po + 14) + shift) & _M33)

def _ts_copy_range(inf, fo, start_byte, end_byte, psi_list, cc, mark_disc, cancel, shift=0, drop_pts=None):
    ps, H = inf.ps, inf.H
    vpid = getattr(inf, "vpid", None)
    dropping = False
    for pkt in psi_list:
        b = bytearray(pkt)
        _ts_fix_cc(b, H, cc)
        fo.write(bytes(b))
    disc = set()
    # Hang- és egyéb csatornák: a szakasz eleje általában egy PES közepére esik. Az árva (kezdet nélküli) darabot
    # eldobjuk, a szakasz végén pedig a félbevágott utolsó PES hátralévő részét még átmásoljuk, így a hang
    # csomagjai épek maradnak (egyesítésnél különben a szomszédos szakasz adataival keverednének).
    psi_pids = set((((p_[H + 1] & 0x1F) << 8) | p_[H + 2]) for p_ in psi_list)
    started = set()
    with open(inf.path, "rb") as fi:
        fi.seek(start_byte)
        remaining = end_byte - start_byte
        while remaining > 0:
            if cancel is not None and cancel.is_set():
                raise MsgError("cancelled")
            # A blokkméret a csomagméret (188/192) többszöröse, különben a csomagok elcsúsznak
            buf = bytearray(fi.read(min(remaining, ps * 8192)))
            if not buf:
                break
            remaining -= len(buf)
            n_ = len(buf) // ps * ps
            if drop_pts is None:
                # Gyors út: a blokkot helyben javítjuk (csak a folytonossági számláló, ill. ritkán az idők
                # változnak), és egyetlen írással mentjük; nincs csomagonkénti másolás.
                bad = []
                cc_get = cc.get
                for o in range(0, n_, ps):
                    t = o + H
                    if buf[t] != 0x47:
                        bad.append(o)
                        continue
                    pid = ((buf[t + 1] & 0x1F) << 8) | buf[t + 2]
                    if vpid is not None and pid != vpid and pid >= 0x20 and pid != 0x1FFF and pid not in psi_pids:
                        if buf[t + 1] & 0x40:
                            started.add(pid)
                        elif pid not in started and (buf[t + 3] & 0x10):
                            bad.append(o)
                            continue
                    if mark_disc and ((buf[t + 3] >> 4) & 2) and buf[t + 4] > 0 and (buf[t + 5] & 0x10) and pid not in disc:
                        buf[t + 5] |= 0x80   # discontinuity_indicator: az illesztésnél új PCR-idő jön
                        disc.add(pid)
                    if shift:
                        _ts_shift_times(buf, o, t, ps, shift)
                    if pid == 0x1FFF:
                        continue
                    b3 = buf[t + 3]
                    last = cc_get(pid)
                    if b3 & 0x10:
                        c = 0 if last is None else (last + 1) & 15
                        cc[pid] = c
                    else:
                        c = 0 if last is None else last
                    if (b3 & 15) != c:
                        buf[t + 3] = (b3 & 0xF0) | c
                if bad:
                    out = bytearray()
                    for o in range(0, n_, ps):
                        if o not in bad:
                            out += buf[o:o + ps]
                    fo.write(out)
                else:
                    fo.write(buf[:n_] if n_ != len(buf) else buf)
                continue
            out = bytearray()
            for o in range(0, len(buf) - ps + 1, ps):
                t = o + H
                if buf[t] != 0x47:
                    continue
                pid_ = ((buf[t + 1] & 0x1F) << 8) | buf[t + 2]
                if vpid is not None and pid_ != vpid and pid_ >= 0x20 and pid_ != 0x1FFF and pid_ not in psi_pids:
                    if buf[t + 1] & 0x40:
                        started.add(pid_)
                    elif pid_ not in started and (buf[t + 3] & 0x10):
                        continue
                if vpid is not None and pid_ == vpid:
                    # Visszaállási (REC / nyitott GOP) kezdőpont: a kezdő képnél korábbi megjelenítési
                    # idejű (vezető) képek az előző GOP-ra hivatkoznak, ezeket kihagyjuk.
                    if buf[t + 1] & 0x40:
                        dropping = False
                        afc_ = (buf[t + 3] >> 4) & 3
                        if afc_ & 1:
                            po_ = t + 4 + ((1 + buf[t + 4]) if (afc_ & 2) else 0)
                            if po_ + 14 <= o + ps and buf[po_:po_ + 3] == b"\x00\x00\x01" and ((buf[po_ + 7] >> 6) & 2):
                                dropping = ((_ts_rd33(buf, po_ + 9) - drop_pts) & _M33) > (_M33 >> 1)
                    if dropping:
                        continue
                if mark_disc and ((buf[t + 3] >> 4) & 2) and buf[t + 4] > 0 and (buf[t + 5] & 0x10):
                    pid = ((buf[t + 1] & 0x1F) << 8) | buf[t + 2]
                    if pid not in disc:
                        buf[t + 5] |= 0x80
                        disc.add(pid)
                if shift:
                    _ts_shift_times(buf, o, t, ps, shift)
                _ts_fix_cc(buf, t, cc)
                out += buf[o:o + ps]
            fo.write(out)
        # a félbevágott utolsó hang-PES (stb.) hátralévő csomagjai
        open_ = set(started)
        fi.seek(end_byte)
        for _ in range(6000):
            if not open_:
                break
            pkt = bytearray(fi.read(ps))
            if len(pkt) < ps or pkt[H] != 0x47:
                break
            pid = ((pkt[H + 1] & 0x1F) << 8) | pkt[H + 2]
            if pid not in open_:
                continue
            if pkt[H + 1] & 0x40:
                open_.discard(pid)
                continue
            if pkt[H + 3] & 0x10:
                _ts_fix_cc(pkt, H, cc)
                fo.write(bytes(pkt))


def ts_cut_ranges(inf, ranges, out_paths, merge=False, progress=None, log=None, cancel=None):
    log = log or (lambda s: None)
    progress = progress or (lambda f: None)
    ps = inf.ps
    psi, _pmt = _ts_psi_packets(inf)
    psi_list = [psi[k] for k in sorted(psi)]
    org = _ts_origin(inf)

    def snap(b):
        return org + max(0, (b - org) // ps) * ps

    dest_paths = [out_paths] if merge else list(out_paths)
    groups = [list(ranges)] if merge else [[r] for r in ranges]
    tmps = [p + ".part" for p in dest_paths]
    total = float(sum(max(0, snap(e[2]) - snap(s[2])) for s, e in ranges)) or 1.0
    done = 0
    try:
        for tmp, grp in zip(tmps, groups):
            cc = {}
            anchor_out, prev_dur, last_out, prev_fd = None, 0, None, None
            with open(tmp, "wb") as fo:
                for ri, (s, e) in enumerate(grp):
                    sb, eb = snap(s[2]), snap(e[2])
                    if eb <= sb:
                        continue
                    shift = 0
                    if merge:
                        a = _ts_first_vtime(inf, sb)
                        if a is not None:
                            if anchor_out is None:
                                anchor_out = a
                            elif last_out is not None:
                                # a következő szakasz az előző utolsó képe után egy képidővel indul
                                anchor_out = (last_out + (prev_fd or int(getattr(inf, "fd", 0) or 0) or 1800)) & _M33
                            else:
                                anchor_out = (anchor_out + prev_dur) & _M33
                            shift = (anchor_out - a) & _M33
                        prev_dur = int(max(0.0, e[0] - s[0]) * 90000)
                        lv = _ts_last_vtimes(inf, sb, eb)
                        if lv is not None:
                            last_out = (lv[0] + shift) & _M33
                            prev_fd = lv[1]
                        else:
                            last_out = None
                    drop = None
                    if len(s) > 3 and s[3] == "rec":
                        r_ = _ts_first_times(inf, sb)
                        drop = r_[0] if r_ else None
                        if not _ts_start_has_params(inf, sb):
                            log(tr("cu2_log_nosps"))
                    _ts_copy_range(inf, fo, sb, eb, psi_list, cc, merge and ri > 0, cancel, shift, drop)
                    done += eb - sb
                    progress(min(1.0, done / total))
        for t_, p in zip(tmps, dest_paths):
            os.replace(t_, p)
        return True
    except BaseException:
        for t_ in tmps:
            try:
                os.remove(t_)
            except OSError:
                pass
        raise


class PurePythonMKVCutter:
    def __init__(self, inf, ranges, out_paths, merge=False):
        self.inf = inf
        self.ranges = ranges
        self.out_paths = out_paths if isinstance(out_paths, list) else [out_paths]
        self.merge = merge
        self._cl = {c[0]: (c[1], c[2]) for c in inf.clusters}

    def _clusters_of(self, rng):
        # [kezdő klaszter, záró klaszter) - a záró kulcskockához tartozó klaszter már nem kerül bele
        s, e = rng
        return [c for c in self.inf.clusters if s[2] <= c[0] < e[2]]

    def _range_ticks(self, fi, rng):
        s, e = rng
        cl = self._clusters_of(rng)
        if not cl:
            return 0
        t0 = _mkv_cluster_tc(fi, cl[0][1], cl[0][2])
        if e[2] in self._cl:
            ds, end = self._cl[e[2]]
            t1 = _mkv_cluster_tc(fi, ds, end)
        else:
            t1 = t0 + int(max(0.0, e[0] - s[0]) * 1e9 / self.inf.scale)
        return max(0, t1 - t0)

    def _write(self, path, ranges):
        inf = self.inf
        scale = inf.scale
        app = ("Lossless Video Toolkit %s" % CUTTER_VERSION).encode("utf-8")
        track = getattr(getattr(inf, "ptrack", None), "number", 1) or 1
        skip = (ID_TIMECODE, ID_POSITION, ID_PREVSIZE, ID_CRC32, ID_VOID)
        with open(inf.path, "rb") as fi, open(inf.path, "rb") as fd, open(path, "wb") as fo:
            durs = [self._range_ticks(fi, r) for r in ranges]
            # A Duration a TimecodeScale egységében (tick) van, nem másodpercben
            info_el = _eb(ID_INFO, b"".join((
                _eb(0x73A4, os.urandom(16)),
                _eb_uint(0x2AD7B1, scale),
                _eb(0x4489, struct.pack(">d", float(sum(durs)))),
                _eb(0x4D80, app), _eb(0x5741, app))))
            fi.seek(inf.tracks_span[0])
            tracks_raw = _mkv_whole(ID_TRACKS, fi.read(inf.tracks_span[1] - inf.tracks_span[0]))
            sh_len = len(_mkv_seekhead([(ID_INFO, 0), (ID_TRACKS, 0), (ID_CUES, 0)]))

            fo.write(inf.ebml)
            fo.write(_eb_id(ID_SEGMENT))
            size_pos = fo.tell()
            fo.write(MKV_UNKNOWN)
            seg0 = fo.tell()
            fo.write(b"\x00" * sh_len)          # helyfoglaló, a végén felülírjuk
            info_pos = fo.tell() - seg0
            fo.write(info_el)
            tracks_pos = fo.tell() - seg0
            fo.write(tracks_raw)

            cues = []
            offset = 0
            for rng, dur in zip(ranges, durs):
                cl = self._clusters_of(rng)
                if not cl:
                    continue
                base = _mkv_cluster_tc(fi, cl[0][1], cl[0][2])
                for cp, ds, end in cl:
                    tc = _mkv_cluster_tc(fi, ds, end)
                    # Az időkód ugyanabban az egységben marad (tick), egyesítésnél folytatólagos
                    ntc = max(0, offset + tc - base)
                    cbuf = io.BytesIO()
                    cbuf.write(_eb_uint(ID_TIMECODE, ntc, 8 if ntc >= (1 << 32) else 4))
                    for eid, ep, ee, info in _mkv_cluster_items(fi, ds, end):
                        if eid in skip:
                            continue
                        fd.seek(ep)
                        cbuf.write(_mkv_whole(eid, fd.read(ee - ep)))
                    cdata = cbuf.getvalue()
                    cues.append((ntc, fo.tell() - seg0))
                    fo.write(_eb_id(ID_CLUSTER) + _encode_vint(len(cdata)) + cdata)
                offset += dur
            if not cues:
                raise MsgError("cu_nocut")

            cues_pos = fo.tell() - seg0
            fo.write(_mkv_cues(cues, track))
            end_pos = fo.tell()
            fo.seek(seg0)
            fo.write(_mkv_seekhead([(ID_INFO, info_pos), (ID_TRACKS, tracks_pos), (ID_CUES, cues_pos)]))
            fo.seek(size_pos)
            fo.write(b"\x01" + (end_pos - seg0).to_bytes(7, "big"))   # valós Segment méret

    def cut(self):
        groups = [list(self.ranges)] if self.merge else [[r] for r in self.ranges]
        tmps = [p + ".part" for p in self.out_paths]
        try:
            for tmp, grp in zip(tmps, groups):
                self._write(tmp, grp)
            for t_, p in zip(tmps, self.out_paths):
                os.replace(t_, p)
            return True
        except BaseException:
            for t_ in tmps:
                try:
                    os.remove(t_)
                except OSError:
                    pass
            raise


def mkv_cut_ranges(inf, ranges, out_paths, merge=False, progress=None, log=None, cancel=None):
    cutter = PurePythonMKVCutter(inf, ranges, out_paths, merge)
    return cutter.cut()

def cut_run_ranges(inf, scan, ranges, outdir, stem=None, merge=False, progress=None, log=None, cancel=None):
    log = log or (lambda s: None)
    if inf.kind not in ("ts", "mkv") and not (inf.kind == "mp4" and _mp4 is not None): raise MsgError("cu_unsup")
    ranges = [r for r in ranges if r[1][2] > r[0][2]]
    if not ranges: raise MsgError("cu_nocut")
    stem = stem or os.path.splitext(os.path.basename(inf.path))[0]
    os.makedirs(outdir, exist_ok=True)
    ext = os.path.splitext(inf.path)[1]
    
    if merge:
        out_path = os.path.join(outdir, f"{stem}_egyesitett{ext}")
        k = 0
        while os.path.exists(out_path):
            k += 1
            out_path = os.path.join(outdir, f"{stem}_egyesitett_{k}{ext}")
        paths = out_path
    else:
        paths = _cut_paths(outdir, stem, ext, len(ranges))
        
    log(tr("cu_l_head", inf.name, len(ranges)))
    if inf.kind == "mp4":
        ok = _mp4_call(_mp4.cut_ranges, inf, ranges, paths, merge, progress, log, cancel)
    else:
        ok = (ts_cut_ranges if inf.kind == "ts" else mkv_cut_ranges)(inf, ranges, paths, merge, progress, log, cancel)
    if ok:
        log(tr("cu_l_done", outdir))
        return paths
    return False


# ======================================================================
# Idő konvertáló segédfüggvény a kézi megadáshoz
# ======================================================================

def parse_time_to_seconds(t_str):
    t_str = t_str.strip().replace(',', '.')
    try:
        return float(t_str)
    except ValueError:
        pass
    
    parts = t_str.split(':')
    try:
        if len(parts) == 3:
            m = float(parts[0])
            s = float(parts[1])
            f_str = parts[2]
            f = float(f_str) / (10 ** len(f_str))
            return m * 60 + s + f
        elif len(parts) == 2:
            m = float(parts[0])
            s = float(parts[1])
            return m * 60 + s
    except ValueError:
        pass
    raise ValueError("Invalid time format")


# ======================================================================
# Ellenőrző: a mentett fájl önálló vizsgálata (a vágótól független kód)
# ======================================================================

_VF_M33 = (1 << 33) - 1
_VF_VIDEO = (0x01, 0x02, 0x1B, 0x24, 0xEA)
_VF_AUDIO = (0x03, 0x04, 0x0F, 0x11, 0x81, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87)


class VReport:
    def __init__(self, path):
        self.path = path
        self.items = []     # (szint, kulcs, argumentumok); szint: "err" / "warn" / "info"
        self.stats = {}

    def add(self, level, key, *args):
        self.items.append((level, key, args))

    @property
    def errors(self):
        return [i for i in self.items if i[0] == "err"]

    @property
    def warnings(self):
        return [i for i in self.items if i[0] == "warn"]

    @property
    def ok(self):
        return not self.errors


def _vf_text(key, args):
    tmpl = None
    try:
        tmpl = tr(key)          # a főprogram fordítója, ha telepítve van
    except Exception:
        tmpl = None
    if not tmpl or tmpl == key:
        tmpl = _USTR["hu"].get(key, key)
    try:
        return tmpl % args if args else tmpl
    except Exception:
        return tmpl


def vf_format(rep):
    mark = {"err": "[HIBA] ", "warn": "[!] ", "info": "• "}
    lines = [mark[lv] + _vf_text(k, a) for lv, k, a in rep.items]
    if rep.ok and not rep.warnings:
        lines.append(_vf_text("vf_ok", ()))
    return "\n".join(lines)


def _vf_sei_has_recovery(data):
    i = 0
    while i + 2 < len(data):
        pt = 0
        while i < len(data) and data[i] == 0xFF:
            pt += 255
            i += 1
        if i >= len(data):
            break
        pt += data[i]
        i += 1
        sz = 0
        while i < len(data) and data[i] == 0xFF:
            sz += 255
            i += 1
        if i >= len(data):
            break
        sz += data[i]
        i += 1
        if pt == 6:
            return True
        i += sz
    return False


def _vf_first_au(vtype, es):
    # A kezdő hozzáférési egység: van-e kulcskocka (IDR / visszaállási pont) és SPS
    es = bytes(es)
    res = {"key": None, "sps": False}
    nals = []
    j = es.find(b"\x00\x00\x01")
    while 0 <= j < len(es) - 3:
        nals.append(j + 3)
        j = es.find(b"\x00\x00\x01", j + 3)
    if vtype == 0x1B:
        rec = False
        for k, p in enumerate(nals):
            nt = es[p] & 0x1F
            end = nals[k + 1] - 3 if k + 1 < len(nals) else len(es)
            if nt == 7:
                res["sps"] = True
            elif nt == 5:
                res["key"] = "idr"
            elif nt == 6 and _vf_sei_has_recovery(es[p + 1:end]):
                rec = True
        if res["key"] is None and rec:
            res["key"] = "rec"
    elif vtype == 0x24:
        for p in nals:
            nt = (es[p] >> 1) & 0x3F
            if nt == 33:
                res["sps"] = True
            elif 16 <= nt <= 21 and res["key"] is None:
                res["key"] = "idr" if nt <= 20 else "rec"
    elif vtype in (0x01, 0x02):
        if b"\x00\x00\x01\xb3" in es:
            res["sps"] = True
            res["key"] = "idr"
    else:
        res["key"] = "?"
        res["sps"] = True
    return res


def _vf_ts_psi(data, ps, H):
    # PAT/PMT megkeresése a fájl elején: (pat_idx, pmt_idx, {pid: típus}, pcr_pid)
    pat_i = pmt_i = pmt_pid = pcr = None
    streams = {}
    for i in range(min(len(data) // ps, 6000)):
        pkt = data[i * ps:(i + 1) * ps]
        t = H
        if pkt[t] != 0x47 or not (pkt[t + 1] & 0x40):
            continue
        pid = ((pkt[t + 1] & 0x1F) << 8) | pkt[t + 2]
        po = _ts_payload_off(pkt, H)
        if po < 0:
            continue
        s = po + 1 + pkt[po]
        if pid == 0 and pat_i is None and s + 8 <= t + 188 and pkt[s] == 0:
            sl = ((pkt[s + 1] & 0x0F) << 8) | pkt[s + 2]
            q, end = s + 8, min(s + 3 + sl - 4, t + 188)
            while q + 4 <= end:
                if ((pkt[q] << 8) | pkt[q + 1]) != 0:
                    pmt_pid = ((pkt[q + 2] & 0x1F) << 8) | pkt[q + 3]
                    break
                q += 4
            pat_i = i
        elif pmt_pid is not None and pid == pmt_pid and pmt_i is None and s + 12 <= t + 188 and pkt[s] == 2:
            sl = ((pkt[s + 1] & 0x0F) << 8) | pkt[s + 2]
            pcr = ((pkt[s + 8] & 0x1F) << 8) | pkt[s + 9]
            pil = ((pkt[s + 10] & 0x0F) << 8) | pkt[s + 11]
            q, end = s + 12 + pil, min(s + 3 + sl - 4, t + 188)
            while q + 5 <= end:
                streams[((pkt[q + 1] & 0x1F) << 8) | pkt[q + 2]] = pkt[q]
                q += 5 + (((pkt[q + 3] & 0x0F) << 8) | pkt[q + 4])
            pmt_i = i
        if pat_i is not None and pmt_i is not None:
            break
    return pat_i, pmt_i, streams, pcr


def _vf_ts(path, rep, expected, progress, cancel):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        head = f.read(192 * 8)
    ps = H = None
    for cps, cH in ((188, 0), (192, 4)):
        if len(head) >= cps * 5 and all(head[cH + n * cps] == 0x47 for n in range(5)):
            ps, H = cps, cH
            break
    if ps is None:
        rep.add("err", "vf_nosync")
        return
    if size % ps:
        rep.add("err", "vf_size", ps)
    with open(path, "rb") as f:
        pre = f.read(ps * 6000)
    pat_i, pmt_i, streams, _pcr_pid = _vf_ts_psi(pre, ps, H)
    if pat_i is None or pmt_i is None:
        rep.add("err", "vf_nopsi")
        return
    vpid = next((p for p, st in streams.items() if st in _VF_VIDEO), None)
    if vpid is None:
        rep.add("err", "vf_novideo")
        return
    vtype = streams[vpid]

    last_cc, last_pcr = {}, {}
    cc_err = pcr_bad = bad_sync = pes_bad = 0
    pes_cnt = dict((p, 0) for p in streams)
    first_vidx = None
    a_prev, a_jump, a_first = {}, [], {}
    v_first_pts = None
    first_es = bytearray()
    es_started = collecting = False
    n = back = lead = 0
    prev_ts = first_ts = last_ts = None
    back_first = None
    gaps = []
    p0 = None
    min_rel = max_rel = 0
    idx = 0
    with open(path, "rb") as f:
        while True:
            if cancel is not None and cancel.is_set():
                rep.add("warn", "vf_cancel")
                return
            buf = f.read(ps * 4096)
            if not buf:
                break
            for o in range(0, len(buf) - ps + 1, ps):
                t = o + H
                idx += 1
                if buf[t] != 0x47:
                    bad_sync += 1
                    continue
                b1, b3 = buf[t + 1], buf[t + 3]
                pid = ((b1 & 0x1F) << 8) | buf[t + 2]
                if pid == 0x1FFF:
                    continue
                afc = (b3 >> 4) & 3
                cc = b3 & 15
                disc = bool((afc & 2) and buf[t + 4] > 0 and (buf[t + 5] & 0x80))
                last = last_cc.get(pid)
                if afc & 1:
                    if last is not None and not disc and cc != last and cc != ((last + 1) & 15):
                        cc_err += 1
                    last_cc[pid] = cc
                elif afc == 2:
                    if last is not None and not disc and cc != last:
                        cc_err += 1
                if (afc & 2) and buf[t + 4] >= 7 and (buf[t + 5] & 0x10):
                    pb = (buf[t + 6] << 25) | (buf[t + 7] << 17) | (buf[t + 8] << 9) | (buf[t + 9] << 1) | (buf[t + 10] >> 7)
                    pp = last_pcr.get(pid)
                    if pp is not None and not disc:
                        d = (pb - pp) & _VF_M33
                        if d > (_VF_M33 >> 1) or d > 180000:
                            pcr_bad += 1
                    last_pcr[pid] = pb
                if (b1 & 0x40) and (afc & 1) and pid in streams:
                    po = t + 4 + ((1 + buf[t + 4]) if (afc & 2) else 0)
                    if po + 9 > o + ps or buf[po:po + 3] != b"\x00\x00\x01":
                        pes_bad += 1
                        continue
                    pes_cnt[pid] += 1
                    if pid != vpid:
                        if (buf[po + 7] & 0x80) and po + 14 <= o + ps:
                            ap = _ts_rd33(buf, po + 9)
                            q = a_prev.get(pid)
                            if q is None:
                                a_first[pid] = ap
                            elif abs(((ap - q + (1 << 32)) & _VF_M33) - (1 << 32)) > 90000 and not disc:
                                a_jump.append((pid, ((ap - a_first[pid] + (1 << 32)) & _VF_M33) / 90000.0 - (1 << 32) / 90000.0 * 0))
                            a_prev[pid] = ap
                        continue
                    if first_vidx is None:
                        first_vidx = idx - 1
                    if not es_started:
                        es_started = collecting = True
                        hs = po + 9 + buf[po + 8]
                        if hs < o + ps:
                            first_es += buf[hs:o + ps]
                    else:
                        collecting = False
                    fl = buf[po + 7] >> 6
                    pts = _ts_rd33(buf, po + 9) if ((fl & 2) and po + 14 <= o + ps) else None
                    dts = _ts_rd33(buf, po + 14) if (fl == 3 and po + 19 <= o + ps) else None
                    ts = dts if dts is not None else pts
                    if v_first_pts is None and pts is not None:
                        v_first_pts = pts
                    if ts is not None:
                        n += 1
                        if prev_ts is None:
                            first_ts = ts
                        else:
                            d = (ts - prev_ts) & _VF_M33
                            at = ((ts - first_ts) & _VF_M33) / 90000.0
                            if d > (_VF_M33 >> 1):
                                back += 1
                                if back_first is None:
                                    back_first = at
                            elif d > 135000:
                                gaps.append((d / 90000.0, at))
                        prev_ts = last_ts = ts
                    if pts is not None:
                        if p0 is None:
                            p0 = pts
                        rel = ((pts - p0 + (1 << 32)) & _VF_M33) - (1 << 32)
                        min_rel, max_rel = min(min_rel, rel), max(max_rel, rel)
                        if rel < 0:
                            lead += 1
                elif collecting and pid == vpid and (afc & 1) and len(first_es) < 8192:
                    po = t + 4 + ((1 + buf[t + 4]) if (afc & 2) else 0)
                    first_es += buf[po:o + ps]
            if progress:
                progress(min(1.0, (idx * ps) / float(size or 1)))

    if first_vidx is None:
        rep.add("err", "vf_novideo")
        return
    if pat_i >= first_vidx or pmt_i >= first_vidx:
        rep.add("err", "vf_nopsi")
    if bad_sync:
        rep.add("err", "vf_sync", bad_sync)
    if pes_bad:
        rep.add("err", "vf_pes", pes_bad)
    if cc_err:
        rep.add("warn", "vf_cc", cc_err)
    if back:
        rep.add("err", "vf_back", back, back_first or 0.0)
    if gaps:
        g = gaps[0]
        rep.add("warn", "vf_gap", g[0], g[1], len(gaps))
    if pcr_bad:
        rep.add("warn", "vf_pcr", pcr_bad)
    if lead:
        rep.add("err", "vf_lead", lead)
    au = _vf_first_au(vtype, first_es)
    if au["key"] is None:
        rep.add("err", "vf_nokey")
    else:
        rep.add("info", "vf_start", {"idr": "IDR", "rec": "REC"}.get(au["key"], "?"))
        if not au["sps"]:
            rep.add("warn", "vf_nosps")
    for pid, st in streams.items():
        if st in _VF_AUDIO and pes_cnt.get(pid, 0) == 0:
            rep.add("warn", "vf_noaudio", pid)
    if a_jump:
        rep.add("err", "vf_ajump", a_jump[0][0], len(a_jump))
    if v_first_pts is not None:
        for pid, ap in a_first.items():
            dd = ((ap - v_first_pts + (1 << 32)) & _VF_M33) - (1 << 32)
            if abs(dd) > 135000:
                rep.add("err", "vf_avstart", pid, dd / 90000.0)
    if n >= 2 and first_ts is not None:
        fd = (((last_ts - first_ts) & _VF_M33) / float(n - 1)) / 90000.0
        dur = (max_rel - min_rel) / 90000.0 + fd
        rep.stats["dur"] = dur
        rep.add("info", "vf_dur", dur, n)
        if expected is not None and abs(dur - expected) > max(1.5, 0.1 * expected):
            rep.add("warn", "vf_durdiff", dur, expected)


# ------------------------------------------------------------------ MKV ---

def _vf_vlen(b0):
    if b0 == 0:
        return 0
    n, m = 1, 0x80
    while not (b0 & m):
        m >>= 1
        n += 1
    return n


def _vf_el(data, pos, end=None):
    # EBML elemfejléc memóriából: (id, adat_kezdet, méret | None) vagy None
    if end is None:
        end = len(data)
    if pos >= end:
        return None
    n = _vf_vlen(data[pos])
    if n == 0 or n > 4 or pos + n >= end:
        return None
    eid = int.from_bytes(data[pos:pos + n], "big")
    m = _vf_vlen(data[pos + n])
    if m == 0 or pos + n + m > end:
        return None
    sz = data[pos + n] & (0xFF >> m)
    for x in data[pos + n + 1:pos + n + m]:
        sz = (sz << 8) | x
    if sz == (1 << (7 * m)) - 1:
        sz = None
    return eid, pos + n + m, sz


def _vf_children(data, start, end):
    p = start
    while p < end:
        h = _vf_el(data, p, end)
        if h is None or h[2] is None or h[1] + h[2] > end:
            yield None, p, p, p
            return
        eid, ds, sz = h
        yield eid, ds, ds + sz, p
        p = ds + sz


def _vf_mkv(path, rep, expected, progress, cancel):
    fsize = os.path.getsize(path)
    f = open(path, "rb")
    try:
        def hdr(pos):
            f.seek(pos)
            return _vf_el(f.read(16), 0)

        h = hdr(0)
        if h is None or h[0] != 0x1A45DFA3 or h[2] is None:
            rep.add("err", "vf_mkv_ebml")
            return
        p = h[1] + h[2]
        s = hdr(p)
        if s is None or s[0] != 0x18538067:
            rep.add("err", "vf_mkv_noseg")
            return
        seg0 = p + s[1]
        if s[2] is None:
            seg_end = fsize
            rep.add("warn", "vf_mkv_segunk")
        else:
            seg_end = seg0 + s[2]
            if seg_end != fsize:
                rep.add("err" if seg_end > fsize else "warn", "vf_mkv_segsize", seg_end, fsize)
                seg_end = min(seg_end, fsize)

        scale, dur_ticks = 1000000, None
        seeks, cue_pos = [], []
        have_cues = have_info = have_tracks = False
        vtrack = None
        clusters = set()
        prev_tc = None
        tcback = neg = nclu = 0
        gaps = []
        first_key = None
        min_abs = max_abs = None
        pos = seg0
        while pos < seg_end:
            if cancel is not None and cancel.is_set():
                rep.add("warn", "vf_cancel")
                return
            h = hdr(pos)
            if h is None or h[2] is None:
                rep.add("err", "vf_mkv_bad", pos)
                break
            eid, hl, sz = h
            ds = pos + hl
            de = ds + sz
            if de > fsize:
                rep.add("err", "vf_mkv_trunc", pos)
                break
            if eid == 0x1F43B675:
                f.seek(ds)
                data = f.read(sz)
                nclu += 1
                clusters.add(pos - seg0)
                tc = None
                for ceid, cds, cde, cep in _vf_children(data, 0, len(data)):
                    if ceid is None:
                        rep.add("err", "vf_mkv_clbad", pos)
                        break
                    if ceid == 0xE7:
                        tc = int.from_bytes(data[cds:cde], "big")
                        if prev_tc is not None:
                            if tc < prev_tc:
                                tcback += 1
                            elif (tc - prev_tc) * scale / 1e9 > 30:
                                gaps.append(((tc - prev_tc) * scale / 1e9, tc * scale / 1e9))
                        prev_tc = tc
                    elif ceid in (0xA3, 0xA0):
                        b0, key = None, None
                        if ceid == 0xA3:
                            b0 = cds
                        else:
                            ref = False
                            for geid, gds, gde, gep in _vf_children(data, cds, cde):
                                if geid == 0xA1:
                                    b0 = gds
                                elif geid == 0xFB:
                                    ref = True
                            key = not ref
                        if b0 is None or b0 + 4 > len(data):
                            continue
                        bn = _vf_vlen(data[b0])
                        if bn == 0:
                            continue
                        track = data[b0] & (0xFF >> bn)
                        for x in data[b0 + 1:b0 + bn]:
                            track = (track << 8) | x
                        if ceid == 0xA3:
                            key = bool(data[b0 + bn + 2] & 0x80)
                        if vtrack is None:
                            vtrack = track
                        if track == vtrack and tc is not None:
                            rel = int.from_bytes(data[b0 + bn:b0 + bn + 2], "big", signed=True)
                            ab = tc + rel
                            if ab < 0:
                                neg += 1
                            min_abs = ab if min_abs is None else min(min_abs, ab)
                            max_abs = ab if max_abs is None else max(max_abs, ab)
                            if first_key is None:
                                first_key = key
                if tc is None:
                    rep.add("err", "vf_mkv_clbad", pos)
            elif eid in (0x114D9B74, 0x1549A966, 0x1654AE6B, 0x1C53BB6B):
                f.seek(ds)
                data = f.read(sz)
                if eid == 0x114D9B74:
                    for e1, d1, de1, _ in _vf_children(data, 0, len(data)):
                        if e1 == 0x4DBB:
                            sid = spos = None
                            for e2, d2, de2, _ in _vf_children(data, d1, de1):
                                if e2 == 0x53AB:
                                    sid = int.from_bytes(data[d2:de2], "big")
                                elif e2 == 0x53AC:
                                    spos = int.from_bytes(data[d2:de2], "big")
                            if sid is not None and spos is not None:
                                seeks.append((sid, spos))
                elif eid == 0x1549A966:
                    have_info = True
                    for e1, d1, de1, _ in _vf_children(data, 0, len(data)):
                        if e1 == 0x2AD7B1:
                            scale = int.from_bytes(data[d1:de1], "big") or scale
                        elif e1 == 0x4489 and de1 - d1 in (4, 8):
                            dur_ticks = struct.unpack(">f" if de1 - d1 == 4 else ">d", data[d1:de1])[0]
                elif eid == 0x1654AE6B:
                    have_tracks = True
                    for e1, d1, de1, _ in _vf_children(data, 0, len(data)):
                        if e1 == 0xAE:
                            num = typ = None
                            for e2, d2, de2, _ in _vf_children(data, d1, de1):
                                if e2 == 0xD7:
                                    num = int.from_bytes(data[d2:de2], "big")
                                elif e2 == 0x83:
                                    typ = int.from_bytes(data[d2:de2], "big")
                            if typ == 1 and vtrack is None and num is not None:
                                vtrack = num
                else:
                    have_cues = True
                    for e1, d1, de1, _ in _vf_children(data, 0, len(data)):
                        if e1 == 0xBB:
                            for e2, d2, de2, _ in _vf_children(data, d1, de1):
                                if e2 == 0xB7:
                                    for e3, d3, de3, _ in _vf_children(data, d2, de2):
                                        if e3 == 0xF1:
                                            cue_pos.append(int.from_bytes(data[d3:de3], "big"))
            if progress:
                progress(min(1.0, pos / float(seg_end or 1)))
            pos = de

        if not have_info or not have_tracks:
            rep.add("err", "vf_mkv_nohdr")
        if nclu == 0:
            rep.add("err", "vf_mkv_noclu")
        for sid, spos in seeks:
            h2 = hdr(seg0 + spos)
            if h2 is None or h2[0] != sid:
                rep.add("err", "vf_mkv_seek", "0x%X" % sid)
        badc = [c for c in cue_pos if c not in clusters]
        if badc:
            rep.add("err", "vf_mkv_cues", len(badc))
        if not have_cues:
            rep.add("warn", "vf_mkv_nocues")
        if tcback:
            rep.add("err", "vf_mkv_tcback", tcback)
        if gaps:
            rep.add("warn", "vf_mkv_gap", gaps[0][0], len(gaps))
        if neg:
            rep.add("err", "vf_mkv_neg", neg)
        if first_key is False:
            rep.add("err", "vf_mkv_nokey")
        if max_abs is not None:
            actual = (max_abs - min_abs) * scale / 1e9
            rep.stats["dur"] = actual
            rep.add("info", "vf_dur", actual, nclu)
            if dur_ticks is not None:
                info_s = dur_ticks * scale / 1e9
                if abs(info_s - actual) > max(1.5, 0.08 * actual):
                    rep.add("warn", "vf_mkv_dur", info_s, actual)
            if expected is not None and abs(actual - expected) > max(1.5, 0.1 * expected):
                rep.add("warn", "vf_durdiff", actual, expected)
    finally:
        f.close()


def verify_output(path, expected=None, progress=None, cancel=None):
    # Önálló ellenőrzés: a mentett TS/M2TS vagy MKV fájl szerkezetét újraolvassa és vizsgálja
    rep = VReport(path)
    try:
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            rep.add("err", "vf_empty")
            return rep
        with open(path, "rb") as f:
            head = f.read(8)
        if head[:4] == b"\x1a\x45\xdf\xa3":
            _vf_mkv(path, rep, expected, progress, cancel)
        elif head[:1] == b"\x47" or head[4:5] == b"\x47":
            _vf_ts(path, rep, expected, progress, cancel)
        elif _mp4 is not None and head[4:8] in (b"ftyp", b"moov", b"mdat", b"free", b"wide"):
            for lvl, key, args in _mp4.verify(path, expected, progress, cancel):
                rep.add(lvl, key, *args)
        else:
            rep.add("err", "vf_nofmt")
    except Exception as e:
        rep.add("err", "vf_exc", str(e))
    return rep


def verify_paths(paths, ranges, merge, progress=None, cancel=None):
    paths = paths if isinstance(paths, list) else [paths]
    reps = []
    for i, p in enumerate(paths):
        try:
            if merge:
                exp = sum(max(0.0, r[1][0] - r[0][0]) for r in ranges)
            else:
                exp = max(0.0, ranges[i][1][0] - ranges[i][0][0])
        except Exception:
            exp = None
        reps.append(verify_output(p, exp, progress, cancel))
    return reps


def _cli(argv=None):
    ap = argparse.ArgumentParser(description="Lossless Video Toolkit - saved file check / mentett fájl ellenőrzése")
    ap.add_argument("files", nargs="+")
    args = ap.parse_args(argv)
    rc = 0
    for p in args.files:
        rep = verify_output(p)
        print(p)
        print(vf_format(rep))
        print()
        if not rep.ok:
            rc = 1
    return rc


# ======================================================================
# CutterTab UI & EKG Timeline Canvas
# ======================================================================

class CutterTab:
    def __init__(self, app, tk, ttk, filedialog, messagebox):
        self.app, self.tk, self.ttk = app, tk, ttk
        self.filedialog, self.messagebox = filedialog, messagebox
        self.q = app.q
        self.inf = self.scan = None
        self.cuts = []
        self._pending_start = None
        self.info = tk.StringVar()
        self.time_clock_var = tk.StringVar(value=tr("cu2_time", "00:00.0"))
        self.manual_range_var = tk.StringVar()
        self._current_play_time = 0.0
        self.outdir = tk.StringVar()
        self.busy, self.cancel = False, threading.Event()
        self.zoom = 1.0
        self.pan_offset = 0.0
        self._pan_x0 = 0
        self._pan_o0 = 0.0

    def build(self, f):
        tk, ttk = self.tk, self.ttk
        top = ttk.Frame(f, padding=8)
        top.pack(fill="x")
        self.btn_open = ttk.Button(top, text=tr("cu_open"), command=self.open_file)
        self.btn_open.pack(side="left")
        
        self.btn_help = ttk.Button(top, text=tr("cu_help_btn"), command=self.open_help_dialog)
        self.btn_help.pack(side="left", padx=6)
        ttk.Label(top, textvariable=self.info, padding=(10, 0)).pack(side="left")

        box = ttk.LabelFrame(f, text=tr("cu_box"), padding=8)
        box.pack(fill="x", padx=8, pady=4)
        
        srow = ttk.Frame(box)
        srow.pack(fill="x", pady=(2, 4))
        ttk.Label(srow, text=tr("cu_manual_lbl")).pack(side="left")
        self.entry_manual = ttk.Entry(srow, textvariable=self.manual_range_var, width=22)
        self.entry_manual.pack(side="left", padx=6)
        self.entry_manual.bind("<Return>", lambda e: self.add_manual_range())
        self.btn_add_manual = ttk.Button(srow, text=tr("cu_manual_add"), command=self.add_manual_range)
        self.btn_add_manual.pack(side="left")
        
        self.btn_export = ttk.Button(srow, text=tr("cu_export"), command=self.do_export)
        self.btn_export.pack(side="right", padx=6)

        orow = ttk.Frame(box)
        orow.pack(fill="x", pady=(4, 0))
        ttk.Label(orow, text=tr("cu_outdir")).pack(side="left")
        ttk.Entry(orow, textvariable=self.outdir).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(orow, text=tr("b_browse"), command=self.browse).pack(side="left")

        row = ttk.Frame(f, padding=(8, 4))
        row.pack(fill="x")
        self.btn_start_sep = ttk.Button(row, text=tr("cu_start_sep"), command=lambda: self.start(merge=False))
        self.btn_start_sep.pack(side="left")
        self.btn_start_merge = ttk.Button(row, text=tr("cu_start_merge"), command=lambda: self.start(merge=True))
        self.btn_start_merge.pack(side="left", padx=6)
        self.btn_cancel = ttk.Button(row, text=tr("b_cancel"), command=self.cancel.set)
        self.btn_cancel.pack(side="right")
        
        split_frame = ttk.Frame(f, padding=8)
        split_frame.pack(fill="both", expand=True)

        left_pane = ttk.LabelFrame(split_frame, text=tr("cu_all_head"), padding=4)
        left_pane.pack(side="left", fill="both", expand=True, padx=(0, 4))
        
        tree_container = ttk.Frame(left_pane)
        tree_container.pack(side="left", fill="both", expand=True)
        
        self.tree_all = ttk.Treeview(tree_container, columns=("time", "byte", "type"), show="headings", height=6)
        scrollbar_all = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree_all.yview)
        self.tree_all.configure(yscrollcommand=scrollbar_all.set)
        
        for c, key, w, a in (("time", "cu_col_time", 90, "center"), ("byte", "cu_col_byte", 110, "e"), ("type", "cu_col_type", 110, "center")):
            self.tree_all.heading(c, text=tr(key))
            self.tree_all.column(c, width=w, anchor=a)
        
        self.tree_all.pack(side="left", fill="both", expand=True)
        scrollbar_all.pack(side="right", fill="y")
        self.tree_all.bind("<Double-1>", self.on_double_click_all)

        right_pane = ttk.LabelFrame(split_frame, text=tr("cu_sel_head"), padding=4)
        right_pane.pack(side="right", fill="both", expand=True, padx=(4, 0))
        self.tree_sel = ttk.Treeview(right_pane, columns=("part", "start", "end", "len", "size", "cut"), show="headings", height=6)
        for c, key, w, a in (("part", "cu_col_part", 45, "center"), ("start", "cu_col_start", 75, "e"),
                             ("end", "cu_col_end", 75, "e"), ("len", "cu_col_len", 70, "e"), 
                             ("size", "cu_col_size", 60, "e"), ("cut", "cu_col_cut", 80, "center")):
            self.tree_sel.heading(c, text=tr(key))
            self.tree_sel.column(c, width=w, anchor=a)
        self.tree_sel.pack(side="left", fill="both", expand=True)
        self.tree_sel.bind("<Double-1>", self.on_double_click_sel)
        self.tree_sel.bind("<Delete>", self.on_delete_sel)
        self.tree_sel.bind("<BackSpace>", self.on_delete_sel)

        cv_container = ttk.Frame(f, padding=(8, 4))
        cv_container.pack(fill="x", padx=8, pady=4)
        
        info_bar = ttk.Frame(cv_container)
        info_bar.pack(fill="x", pady=(0, 2))
        ttk.Label(info_bar, textvariable=self.time_clock_var, font=("Consolas", 10, "bold")).pack(side="left")
        ttk.Label(info_bar, text=tr("cu_cv_hint")).pack(side="left", padx=6)
        
        zoom_frame = ttk.Frame(info_bar)
        zoom_frame.pack(side="right")
        ttk.Button(zoom_frame, text="-", width=3, command=self.zoom_out).pack(side="left", padx=1)
        ttk.Button(zoom_frame, text="+", width=3, command=self.zoom_in).pack(side="left", padx=1)

        self.canvas = tk.Canvas(cv_container, height=80, bg="#0d0d0d", highlightthickness=1, highlightbackground="#555")
        self.canvas.pack(fill="x", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.redraw_timeline())
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<MouseWheel>", self.on_canvas_wheel)
        self.canvas.bind("<ButtonPress-3>", self.on_pan_start)
        self.canvas.bind("<B3-Motion>", self.on_pan_move)

        self._btns()

    def _fill(self):
        self.tree_all.delete(*self.tree_all.get_children())
        if self.scan:
            for k in self.scan["cands"]:
                self.tree_all.insert("", "end", values=(fmt_dur(k[0]), k[2], k[3]))

        self.tree_sel.delete(*self.tree_sel.get_children())
        kn = {"idr": "cu_k_idr", "rec": "cu_k_rec"}
        part_idx = 1
        if self.scan and self.cuts:
            for (t0, t1, ln, sz, ty) in cut_ranges_info(self.scan, self.cuts):
                type_key = kn.get(ty, "cu_k_start")
                translated_type = tr(type_key)
                self.tree_sel.insert("", "end", values=(part_idx, fmt_dur(t0), fmt_dur(t1), fmt_dur(ln), "%.1f" % (sz / 1048576.0), translated_type))
                part_idx += 1
        if self._pending_start is not None:
            ps = self._pending_start
            ty = ps[3]
            translated_type = tr(kn.get(ty, "cu_k_start"))
            self.tree_sel.insert("", "end", values=(part_idx, fmt_dur(ps[0]), "...", "...", "...", translated_type))

    def _btns(self):
        st = "disabled" if self.busy else "normal"
        for b in (self.btn_open, self.btn_start_sep, self.btn_start_merge, self.btn_add_manual, self.btn_export, self.btn_help):
            try:
                b.configure(state=st)
            except:
                pass
        try:
            self.btn_cancel.configure(state="normal" if self.busy else "disabled")
        except:
            pass

    def open_help_dialog(self):
        try:
            # a Toplevel szülője csak widget lehet: az „app” objektum nem az, ezért az
            # idővonal keretét, illetve a főablakot adjuk meg (ha egyik sincs, a tkinter
            # a már meglévő root-ot használja)
            master = getattr(self, "canvas", None) or getattr(self.app, "root", None)
            dlg = self.tk.Toplevel(master if hasattr(master, "tk") else None)
            dlg.title(tr("cu_help_title"))
            dlg.geometry("580x440")
            dlg.grab_set()
            
            txt = self.tk.Text(dlg, wrap="word", padx=12, pady=12, font=("Segoe UI", 10), bg="#1e2229", fg="#ffffff")
            txt.pack(fill="both", expand=True, padx=8, pady=8)
            txt.insert("1.0", tr("cu_help_text"))
            txt.configure(state="disabled")
            
            btn = self.ttk.Button(dlg, text="OK", command=dlg.destroy)
            btn.pack(pady=8)
        except Exception as e:
            self.messagebox.showerror(tr("cu2_err_title"), tr("cu2_info_fail", str(e)))

    def add_manual_range(self):
        if not self.scan:
            self.messagebox.showinfo(TITLE, tr("cu_nofile"))
            return
        text = self.manual_range_var.get().strip()
        if "-" not in text:
            self.messagebox.showwarning(TITLE, tr("cu_manual_err"))
            return
        parts = text.split("-", 1)
        try:
            t_start_sec = parse_time_to_seconds(parts[0])
            t_end_sec = parse_time_to_seconds(parts[1])
        except Exception:
            self.messagebox.showwarning(TITLE, tr("cu_manual_err"))
            return
        
        if t_start_sec > t_end_sec:
            t_start_sec, t_end_sec = t_end_sec, t_start_sec
        
        cands = self.scan.get("cands", [])
        if not cands:
            self.messagebox.showwarning(TITLE, tr("cu_nokey"))
            return
        
        best_start = min(cands, key=lambda c: abs(c[0] - t_start_sec))
        best_end = min(cands, key=lambda c: abs(c[0] - t_end_sec))
        if best_start[2] == best_end[2]:
            self.messagebox.showwarning(TITLE, tr("cu2_same_kf"))
            return
        
        self.cuts.append((best_start, best_end))
        self.manual_range_var.set("")
        self.info.set(tr("cu2_manual_snap", fmt_dur(best_start[0]), fmt_dur(best_end[0])))
        self._fill()
        self.redraw_timeline()

    def set_busy_state(self, busy):
        self.busy = busy
        cur = "watch" if busy else ""
        for w in (self.app, self.canvas, self.tree_all, self.tree_sel):
            try:
                w.config(cursor=cur)
            except:
                pass
        try:
            self.app.update_idletasks()
        except:
            pass
        self._btns()
        self.redraw_timeline()

    def _clamp_pan(self, w=None):
        if w is None:
            w = self.canvas.winfo_width()
        if w < 10:
            w = 600
        max_pan = max(0.0, (w - 20) * (self.zoom - 1.0))
        self.pan_offset = min(max(0.0, self.pan_offset), max_pan)

    def _set_zoom(self, nz):
        w = self.canvas.winfo_width()
        if w < 10:
            w = 600
        nz = max(1.0, min(15.0, nz))
        if self.scan:
            dur = max(0.1, self.scan["dur"])
            fx = 10 - self.pan_offset + (self._current_play_time / dur) * (w - 20) * self.zoom
            if not (10 <= fx <= w - 10):
                fx = w / 2.0
            self.zoom = nz
            self.pan_offset = 10 + (self._current_play_time / dur) * (w - 20) * nz - fx
        else:
            self.zoom = nz
            self.pan_offset = 0.0
        self._clamp_pan(w)
        self.redraw_timeline()

    def zoom_in(self):
        self._set_zoom(self.zoom * 1.25)

    def zoom_out(self):
        self._set_zoom(self.zoom / 1.25)

    def on_pan_start(self, event):
        self._pan_x0 = event.x
        self._pan_o0 = self.pan_offset

    def on_pan_move(self, event):
        if not self.scan:
            return
        self.pan_offset = self._pan_o0 - (event.x - self._pan_x0)
        self._clamp_pan()
        self.redraw_timeline()

    def redraw_timeline(self):
        cv = self.canvas
        cv.delete("all")
        w = cv.winfo_width()
        h = cv.winfo_height()
        if w < 10: w = 600
        
        self._clamp_pan(w)
        cv.create_rectangle(0, 0, w, h, fill="#121212", outline="")
        
        bar_top = 10
        bar_bottom = h - 26
        
        if self.busy:
            cv.create_rectangle(10, bar_top, w - 10, bar_bottom, fill="#1a1a1a", outline="#00E5FF", width=1)
            cv.create_text(w / 2, h / 2 - 5, text=tr("cu2_busy"), fill="#00E5FF", font=("Segoe UI", 9, "bold"))
            return

        if not self.scan:
            cv.create_rectangle(10, bar_top, w - 10, bar_bottom, fill="#1a1a1a", outline="#444444", width=1)
            cv.create_text(w / 2, h / 2 - 5, text=tr("cu2_empty"), fill="#888888", font=("Segoe UI", 9))
            return

        effective_w = (w - 20) * self.zoom
        base_x0 = 10 - self.pan_offset

        cv.create_rectangle(base_x0, bar_top, base_x0 + effective_w, bar_bottom, fill="#1e2229", outline="#444", width=1)

        dur = max(0.1, self.scan["dur"])

        nice_steps = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600]
        step = nice_steps[0]
        for ns in nice_steps:
            if (dur / ns) <= 15:
                step = ns
                break
        else:
            step = nice_steps[-1]
        step = max(0.05, step / max(1.0, self.zoom * 0.4))

        t_tick = 0.0
        while t_tick <= dur + step:
            tx = base_x0 + (t_tick / dur) * effective_w
            if 10 <= tx <= w - 10:
                cv.create_line(tx, bar_bottom, tx, bar_bottom + 4, fill="#888888", width=1)
                cv.create_text(tx, bar_bottom + 6, text=fmt_dur(t_tick), fill="#aaaaaa", font=("Consolas", 7), anchor="n")
            t_tick += step

        for r in self.cuts:
            x1 = base_x0 + (r[0][0] / dur) * effective_w
            x2 = base_x0 + (r[1][0] / dur) * effective_w
            if x2 >= 10 and x1 <= w - 10:
                cv.create_rectangle(max(10, x1), bar_top, min(w - 10, x2), bar_bottom, fill="#8b0000", outline="#ff5252", width=1)
        
        for c in self.scan.get("cands", []):
            cx_pos = base_x0 + (c[0] / dur) * effective_w
            if 10 <= cx_pos <= w - 10:
                col = "#00E5FF" if c[3] == "idr" else "#888888"
                cv.create_line(cx_pos, bar_top + 2, cx_pos, bar_bottom - 2, fill=col, width=1)

        cur_x = base_x0 + (self._current_play_time / dur) * effective_w
        if 10 <= cur_x <= w - 10:
            cv.create_line(cur_x, 2, cur_x, bar_bottom, fill="#FFD700", width=2)

    def on_canvas_click(self, event):
        if not self.scan: return
        w = self.canvas.winfo_width()
        if w < 10: return
        dur = max(0.1, self.scan["dur"])
        effective_w = (w - 20) * self.zoom
        base_x0 = 10 - self.pan_offset
        clicked_time = ((event.x - base_x0) / effective_w) * dur
        clicked_time = max(0.0, min(dur, clicked_time))
        
        cands = self.scan.get("cands", [])
        if cands:
            closest_idx = min(range(len(cands)), key=lambda i: abs(cands[i][0] - clicked_time))
            closest_cand = cands[closest_idx]
            
            self._current_play_time = closest_cand[0]
            self.time_clock_var.set(tr("cu2_time", fmt_dur(self._current_play_time)))
            
            children = self.tree_all.get_children()
            if 0 <= closest_idx < len(children):
                item_id = children[closest_idx]
                self.tree_all.selection_set(item_id)
                self.tree_all.see(item_id)
        else:
            self._current_play_time = clicked_time
            self.time_clock_var.set(tr("cu2_time", fmt_dur(clicked_time)))
            
        self.redraw_timeline()

    def on_canvas_wheel(self, event):
        if not self.scan: return
        if (hasattr(event, 'delta') and event.delta > 0) or getattr(event, 'num', 0) == 4:
            self.zoom_in()
        else:
            self.zoom_out()

    def on_double_click_all(self, event):
        sel = self.tree_all.selection()
        if not sel or not self.scan:
            return
        idx = self.tree_all.index(sel[0])
        cand = self.scan["cands"][idx]
        
        if self._pending_start is None:
            self._pending_start = cand
            self.info.set(tr("cu2_start_set", fmt_dur(cand[0])))
            self._fill()
            self.redraw_timeline()
        else:
            r_start, r_end = self._pending_start, cand
            if r_start[0] > r_end[0]:
                r_start, r_end = r_end, r_start
            if r_start[2] == r_end[2]:
                self.info.set(tr("cu2_same_pt"))
                return
            self.cuts.append((r_start, r_end))
            self.info.set(tr("cu2_added", fmt_dur(r_start[0]), fmt_dur(r_end[0])))
            self._pending_start = None
            self._fill()
            self.redraw_timeline()

    def on_double_click_sel(self, event):
        if self.tree_sel.selection():
            self.on_delete_sel()

    def on_delete_sel(self, event=None):
        sel = self.tree_sel.selection()
        if not sel:
            self.cuts = []
            self._pending_start = None
        else:
            indices = sorted([self.tree_sel.index(s) for s in sel], reverse=True)
            for idx in indices:
                if self._pending_start is not None and idx == len(self.cuts):
                    self._pending_start = None
                elif 0 <= idx < len(self.cuts):
                    self.cuts.pop(idx)
        self._fill()
        self.redraw_timeline()

    def do_export(self):
        if not self.cuts or not self.scan:
            self.messagebox.showinfo(TITLE, tr("cu_nocut"))
            return
        path = self.filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json"), ("TXT", "*.txt")])
        if path:
            if path.endswith(".txt"):
                export_cuts_txt(self.cuts, self.scan, path)
            else:
                export_cuts_json(self.cuts, self.scan, path)
            self.messagebox.showinfo(TITLE, tr("cu_done"))

    def browse(self):
        d = self.filedialog.askdirectory(title=tr("cu_outdir"))
        if d: self.outdir.set(d)

    def open_ffmpeg(self):
        # Opcionális modul: a megnyitott fájllal és az aktuális idővonal-ponttal nyitja az előnézetet
        _load_ffm()
        if _ffm is None: return
        path = self.inf.path if self.inf is not None else ""
        st = en = None
        if self.cuts:
            st, en = self.cuts[-1][0][0], self.cuts[-1][1][0]
        _ffm.open_window(self.app.root if hasattr(self.app, "root") else self.app, self.tk, self.ttk,
                         self.filedialog, self.messagebox, path, self._current_play_time, st, en)

    def open_file(self):
        if self.busy: return
        p = self.filedialog.askopenfilename(filetypes=[("Video", "*.mts *.m2ts *.ts *.mkv *.webm" + (" *.mp4 *.m4v *.mov" if _mp4 else "")), ("*", "*.*")])
        if not p: return
        self.set_busy_state(True)
        self.cancel.clear()
        self.info.set(tr("cu_scanning"))

        def work():
            try:
                if _mp4 is not None and p.lower().endswith(_mp4.MP4_EXTS):
                    inf = _mp4.open_info(p)
                else:
                    inf = analyze_into(FileInfo(p))
                if inf.error: raise inf.error
                sc = cut_scan(inf, lambda f: None, self.cancel)
                self.q.put(("cready", (inf, sc, None)))
            except BaseException as e:
                self.q.put(("cready", (None, None, str(e))))
        threading.Thread(target=work, daemon=True).start()

    def _choose_cut_method(self):
        """Csak akkor hívódik, ha a Smart Cut használható (_smartcut_gate): választás a veszteségmentes út és a Smart Cut között."""
        parent = getattr(self, "canvas", None) or getattr(self.app, "root", None)
        dlg = self.tk.Toplevel(parent if hasattr(parent, "tk") else None)
        dlg.title(tr("cu_method_title"))
        try:
            dlg.transient(parent)
        except Exception:
            pass
        dlg.resizable(False, False)
        choice = {"value": None}
        outer = self.ttk.Frame(dlg, padding=14)
        outer.pack(fill="both", expand=True)
        self.ttk.Label(
            outer, text=tr("cu_method_question"),
            font=("TkDefaultFont", 11, "bold"), wraplength=520,
        ).pack(anchor="w", pady=(0, 10))

        def finish(value):
            choice["value"] = value
            dlg.destroy()

        smart = self.ttk.LabelFrame(outer, text=tr("cu_method_smart_title"), padding=10)
        smart.pack(fill="x", pady=(0, 8))
        self.ttk.Label(smart, text=tr("cu_method_smart_desc"), wraplength=510,
                       justify="left").pack(anchor="w", pady=(0, 8))
        self.ttk.Button(smart, text=tr("cu_method_smart_btn"),
                        command=lambda: finish("smart")).pack(anchor="e")

        lossless = self.ttk.LabelFrame(outer, text=tr("cu_method_lossless_title"), padding=10)
        lossless.pack(fill="x", pady=(0, 8))
        self.ttk.Label(lossless, text=tr("cu_method_lossless_desc"), wraplength=510,
                       justify="left").pack(anchor="w", pady=(0, 8))
        self.ttk.Button(lossless, text=tr("cu_method_lossless_btn"),
                        command=lambda: finish("lossless")).pack(anchor="e")

        self.ttk.Button(outer, text=tr("cu_method_cancel"), command=dlg.destroy).pack(anchor="e")
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        dlg.update_idletasks()
        try:
            px, py = parent.winfo_rootx(), parent.winfo_rooty()
            pw, ph = parent.winfo_width(), parent.winfo_height()
            x = px + max(0, (pw - dlg.winfo_width()) // 2)
            y = py + max(0, (ph - dlg.winfo_height()) // 2)
        except Exception:
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
        return choice["value"]

    def _smartcut_output_path(self, inf, outdir, stem, ext, merge, count):
        if merge:
            k = 0
            while True:
                suffix = "_egyesitett" if k == 0 else "_egyesitett_%d" % k
                path = os.path.join(outdir, stem + suffix + ext)
                if not os.path.exists(path) and not os.path.exists(path + ".part"):
                    return path
                k += 1
        return _cut_paths(outdir, stem, ext, count)

    def _start_smart_cut(self, merge=False):
        if self.busy:
            return
        if not self.inf or not self.scan:
            self.messagebox.showinfo(TITLE, tr("cu_nofile"))
            return
        valid = [r for r in list(self.cuts) if r[1][2] > r[0][2]]
        if not valid:
            self.messagebox.showinfo(TITLE, tr("cu_nocut"))
            return
        gate = _smartcut_gate()
        if gate is None:
            self.messagebox.showwarning(TITLE, tr("cu_smart_need_setup"))
            return
        inf = self.inf
        containers = {"ts": "mpegts", "mkv": "matroska", "mp4": "mp4"}
        container = containers.get(inf.kind)
        if container is None:
            self.messagebox.showwarning(TITLE, tr("cu_unsup"))
            return
        ffmpeg, ffprobe = gate
        try:
            ff = _smartcut.CommandFFmpeg(ffmpeg, ffprobe)
        except Exception as exc:
            self.messagebox.showwarning(TITLE, str(exc))
            return

        outdir = self.outdir.get().strip() or os.path.dirname(os.path.abspath(inf.path))
        stem = os.path.splitext(os.path.basename(inf.path))[0]
        ext = os.path.splitext(inf.path)[1] or {"ts": ".ts", "mkv": ".mkv", "mp4": ".mp4"}.get(inf.kind, ".ts")
        try:
            os.makedirs(outdir, exist_ok=True)
        except OSError as exc:
            self.messagebox.showwarning(TITLE, str(exc))
            return
        paths = self._smartcut_output_path(inf, outdir, stem, ext, merge, len(valid))
        targets = [paths] if merge else list(paths)
        ranges = [(float(r[0][0]), float(r[1][0])) for r in valid]
        groups = [ranges] if merge else [[r] for r in ranges]
        result_paths = paths if merge else list(paths)
        opts = {
            "container": container, "overwrite": False, "vcodec": "copy", "acodec": "copy",
            "arate": None, "achannels": None, "abitrate": "", "volume": "", "af": "",
        }
        self.set_busy_state(True)
        self.cancel.clear()
        self.info.set(tr("cu_smart_running"))

        def work():
            cleanup = None
            try:
                probe = ff.probe(inf.path)
                jobs, final, cleanup = _smartcut.build_jobs(
                    ff, inf.path, groups, None, probe, targets, opts, cancel=self.cancel)
                for cmd, duration in jobs:
                    ff.run_convert(cmd, duration, cancel=self.cancel)
                if self.cancel.is_set():
                    raise _smartcut.SmartCutError("cancelled")
                final()
                if cleanup:
                    cleanup()
                    cleanup = None
                if self.cancel.is_set():
                    raise _smartcut.SmartCutError("cancelled")
                reps = verify_paths(result_paths, valid, merge, None, self.cancel)
                allok = all(r.ok and not r.warnings for r in reps)
                txt = "\n\n".join("%s\n%s" % (os.path.basename(r.path), vf_format(r)) for r in reps)
                self.q.put(("cend", "rep:" + ("1" if allok else "0") + txt))
            except Exception as exc:
                self.q.put(("cend", "err:Smart Cut: " + str(exc)))
            finally:
                if cleanup:
                    cleanup()

        threading.Thread(target=work, daemon=True).start()

    def start(self, merge=False):
        if self.busy: return
        method = "lossless"                 # alapértelmezett: a saját, FFmpeg nélküli veszteségmentes vágás, kérdés nélkül
        if _smartcut_gate() is not None:    # a választó csak az FFmpeg-feltételek elfogadása és a modul bekapcsolása után jön
            method = self._choose_cut_method()
            if method is None: return
        if method == "smart":
            return self._start_smart_cut(merge)
        if self.busy: return
        if not self.cuts:
            self.messagebox.showinfo(TITLE, tr("cu_nocut"))
            return
        inf, sc = self.inf, self.scan
        outdir = self.outdir.get().strip() or os.path.dirname(os.path.abspath(inf.path))
        self.set_busy_state(True)
        self.cancel.clear()

        def work():
            try:
                res = cut_run_ranges(inf, sc, self.cuts, outdir, None, merge, lambda f: None, lambda s: None, self.cancel)
                if res:
                    valid = [r for r in self.cuts if r[1][2] > r[0][2]]
                    reps = verify_paths(res, valid, merge, None, self.cancel)
                    allok = all(r.ok and not r.warnings for r in reps)
                    txt = "\n\n".join("%s\n%s" % (os.path.basename(r.path), vf_format(r)) for r in reps)
                    self.q.put(("cend", "rep:" + ("1" if allok else "0") + txt))
                else:
                    self.q.put(("cend", None))
            except Exception as e:
                self.q.put(("cend", "err:" + str(e)))
        threading.Thread(target=work, daemon=True).start()

    def handle(self, m, dialogs):
        self.set_busy_state(False)
        kind = m[0]
        if kind == "cready":
            inf, sc, err = m[1]
            if err:
                self.info.set(tr("cu_nofile"))
                dialogs.append(("showwarning", TITLE, err))
            else:
                self.inf, self.scan, self.cuts, self._pending_start = inf, sc, [], None
                self.info.set("%s  (%s, %d)" % (inf.name, fmt_dur(sc["dur"]), len(sc["cands"])))
                self._current_play_time = 0.0
                self.outdir.set(os.path.dirname(os.path.abspath(inf.path)))
                self._fill()
                self.zoom = 1.0
                self.pan_offset = 0.0
                self.redraw_timeline()
        elif kind == "cend":
            msg = m[1]
            if msg and msg.startswith("rep:"):
                ok = msg[4:5] == "1"
                dialogs.append(("showinfo" if ok else "showwarning", TITLE, tr("cu_done") + "\n\n" + msg[5:]))
            elif msg and msg.startswith("err:"):
                dialogs.append(("showwarning", TITLE, msg[4:]))
            else:
                dialogs.append(("showinfo", TITLE, tr("cu_done")))


# ======================================================================
# Telepítés a főprogramba
# ======================================================================

def install(core):
    global _INSTALLED
    if _INSTALLED: return
    _INSTALLED = True
    g = globals()
    for k, v in vars(core).items():
        if k not in g and (k == "__version__" or not k.startswith("__")):
                    g[k] = v
    S = core._STR
    for lang in S: S[lang].update(_USTR[lang])
    for lang, add in _CUT_NOTES.items():
        if add not in S[lang]["comp_text"]:
            S[lang]["comp_text"] += add


if __name__ == "__main__":
    sys.exit(_cli())
