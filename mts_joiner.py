#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 szabiz <szabiz@yahoo.com>
# Copyright (c) 2026 szabiz <szabiz@yahoo.com>
"""
Lossless Video Toolkit 1.0 - veszteségmentes videó összefűző, kinyerő
===========================================================
Az összefűző és kinyerő rész csak a Python standard könyvtárát használja (tkinter, struct, threading).
A további modulok (vágó, FFmpeg-ablak, képeffektek, elemző) a külső FFmpeg-et és az opcionális VapourSynth-et
csak különálló programként indítják; ezeket a program nem tartalmazza.
Nincs újrakódolás: a Transport Stream csomagokat másolja, és közben

  * eltolja a PTS / DTS / PCR / ATS időbélyegeket, hogy a fájlok egymás után
    folytonosan következzenek (a videó DTS-éhez igazítva),
  * újraszámolja a continuity counter értékeket,
  * a varratnál az átfedő hang-PES csomagokat eldobja (a hang nem csúszik el,
    mert a hang és a videó ugyanazzal az eltolással kerül át),
  * MP4 / MOV fájlokat is összefűz (a konténer táblái épülnek újra, a minták bájtra
    azonosan másolódnak), ugyanazzal az ellenőrzéssel a kimeneten,
  * MKV / WebM / MKA fájlokat is összefűz (csak a Cluster időbélyegek tolódnak el, a
    blokkok bájtra azonosak; a SeekHead és a Cues újra készül), ugyanazzal az ellenőrzéssel,
  * MPEG Program Stream (.mpg / .mpeg) és DVD VOB fájlokat is összefűz (SCR + PTS/DTS
    eltolás, a hasznos adat bájtra azonos, a VOB NAV-csomagjai igazítva), ugyanazzal az
    ellenőrzéssel a kimeneten,
  * hangsáv / képfolyam kinyerése és a hang cseréje TS / M2TS, MP4 / MOV és MKV fájlokban
    (második fül; parancssorban: streams, extract, replace-audio),
  * összefűzés előtt ellenőrzi a fájlok kompatibilitását (zöld/sárga/piros),
  * jelzi, ha egy fájl az előzőnek a méretkorlát miatti FOLYTATÁSA (az előző fájl mérete és az
    időbélyegek – PTS/DTS, PCR, ATS, SCR – alapján), és a listában varratminőséget is mutat
    (kép-, hang- és óra-illesztés a varratnál, 0–100 pont),
  * beépített súgó (F1 / Súgó gomb) magyarul és angolul: használat, a jelzések és az ellenőrzési
    üzenetek jelentése; Jogi és Komponensek fül (licenc, harmadik féltől származó részek),
  * összefűzés után visszaolvassa és ellenőrzi a kész fájlt (szerkezet, számlálók,
    PCR/ATS, videó időzítés, hang keretek + CRC, A/V szinkron); hibás kimenetet
    nem fogad el (<név>_HIBAS.m2ts néven megőrzi vizsgálatra).

Használat:
    python mts_joiner.py                       -> grafikus felület
    python mts_joiner.py -o ki.m2ts a.mts b.mts  -> parancssor
"""
import os
import re
import bisect
import zlib
import sys
import struct
import queue
import argparse
import threading
from collections import Counter, deque
import math
import base64
import tempfile

MOD33 = 1 << 33
HALF33 = 1 << 32
HEAD_BYTES = 6 * 1024 * 1024
TAIL_BYTES = 8 * 1024 * 1024
CHUNK_PACKETS = 8192

VIDEO_TYPES = {0x01, 0x02, 0x10, 0x1B, 0x24, 0xEA}
AUDIO_TYPES = {0x03, 0x04, 0x0F, 0x11, 0x80, 0x81, 0x82, 0x83, 0x84, 0x85,
               0x86, 0x87, 0xA1, 0xA2}
AUDIO_NAMES = {0x81: "AC3", 0x87: "E-AC3", 0x80: "LPCM", 0x82: "DTS",
               0x83: "TrueHD", 0x03: "MP1", 0x04: "MP2", 0x0F: "AAC"}
NO_HDR_IDS = {0xBC, 0xBE, 0xBF, 0xF0, 0xF1, 0xF2, 0xF8, 0xFF}
AC3_RATES = [32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320,
             384, 448, 512, 576, 640]

_U32 = struct.Struct(">I")


# ------------------------------------------------- verzió / licenc / nyelv --

__version__ = "1.0"
# LVT-PATCH: icon+cutter v1
AUTHOR = "szabiz"      # a szerzői jogi tulajdonos (Névjegy, Jogi és Licenc fül, MIT-szöveg)
AUTHOR_EMAIL = "szabiz@yahoo.com"
YEAR = "2026"
# A szerzői ablak (a Névjegy ablak első fülére 5-ször egymás után kattintva nyílik meg).
# Idézet, forrás megjelölésével: 1Kor 9,18. A magyar szöveg Károli Gáspár fordítása (közkincs),
# az angol a King James Version (köztulajdon).
CREDITS_VERSE = {
    "hu": ("Micsoda tehát az én jutalmam? Hogy prédikálásommal ingyenvalóvá tegyem a Krisztus "
           "evangyéliomát, hogy ne használjam ki ama szabadságomat az evangyéliom hirdetésénél.",
           "1Kor 9,18",
           "Károli Gáspár fordítása"),
    "en": ("What is my reward then? Verily that, when I preach the gospel, I may make the gospel of "
           "Christ without charge, that I abuse not my power in the gospel.",
           "1Cor 9,18",
           "King James Version"),
}
LANG = "en"
LANG_NAMES = {"hu": "Magyar", "en": "English"}
_CFG = os.path.join(os.path.expanduser("~"), ".mts_joiner.cfg")

MIT_TEXT = """MIT License

Copyright (c) %s %s

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
""" % (YEAR, AUTHOR)

_STR = {
    "hu": {
        "title": "Lossless Video Toolkit 1.0 – veszteségmentes videó összefűző",
        "err_sync_k": "Szinkronvesztés a(z) %d. csomagnál (sérült fájl?)",
        "err_sync_file": "Szinkronvesztés a(z) %s fájlban",
        "err_small": "Túl kicsi fájl",
        "err_notts": "Nem MPEG-TS / M2TS fájl",
        "err_nopsi": "Nem található PAT/PMT",
        "err_novideo": "Nincs videó adatfolyam",
        "err_nots": "Nem található videó időbélyeg",
        "err_nots_end": "Nem található videó időbélyeg a fájl végén",
        "c_pend": "Elemzés…",
        "c_noref": "Az első fájl nem használható referenciának",
        "c_ref": "Referencia (első fájl)",
        "c_pktsize": "csomagméret eltér",
        "c_pid": "PID-kiosztás eltér (ez a verzió nem térképezi át)",
        "c_vcodec": "videó kodek eltér",
        "c_fps": "képfrekvencia eltér",
        "c_res": "felbontás eltér",
        "c_scan": "soros/progresszív eltér",
        "c_prof": "profil/szint eltér",
        "c_vunk": "videó paraméterei nem ellenőrizhetők",
        "c_acodec": "hang kodek eltér",
        "c_afmt": "hang formátuma eltér",
        "c_abr": "hang bitrátája eltér",
        "c_sps": "SPS eltér (más kamerabeállítás?)",
        "c_ok": "Kompatibilis",
        "j_nofiles": "Nincs fájl",
        "j_badfile": "Hibás vagy még elemzés alatt álló fájl: %s",
        "j_sameout": "A kimeneti fájl nem egyezhet meg egy bemeneti fájllal",
        "j_space": "Nincs elég szabad hely a kimeneti meghajtón",
        "l_copy": "1. %s – másolás (referencia)",
        "l_off": "%d. %s – időeltolás: %.3f s",
        "l_audio": "   hang (PID 0x%X) a varratnál: %+.1f ms, eldobott PES: %d",
        "l_pcr": "   PCR-ugrás a varratnál (%+.1f ms) – discontinuity jelzés beállítva",
        "l_done": "Kész: %s",
        "cli_desc": "Veszteségmentes AVCHD MTS összefűző",
        "b_add": "Fájlok hozzáadása…", "b_folder": "Mappa hozzáadása…",
        "b_remove": "Eltávolítás", "b_up": "▲ Fel", "b_down": "▼ Le",
        "b_sort": "Névsorba", "b_clear": "Lista törlése",
        "b_about": "Névjegy", "b_lang": "Nyelv: %s",
        "col_file": "Fájl", "col_len": "Hossz", "col_mb": "MB",
        "col_video": "Videó", "col_audio": "Hang", "col_state": "Állapot",
        "dlg_files": "AVCHD fájlok", "ft_avchd": "AVCHD videó", "ft_all": "Minden fájl",
        "dlg_folder": "Mappa",
        "row_err": "Hiba: ", "row_warn": "Figyelem: ", "row_bad": "Nem illeszthető: ",
        "summary": "%d fájl, összesen %s",
        "lbl_out": "Kimeneti fájl:", "b_browse": "Tallózás…",
        "b_start": "Összefűzés indítása", "b_cancel": "Megszakítás",
        "m_noout_t": "Kimenet", "m_noout": "Adj meg kimeneti fájlt.",
        "m_over_t": "Felülírás", "m_over": "A fájl már létezik. Felülírod?",
        "l_start": "— Összefűzés indul —",
        "e_prefix": "Hiba: %s", "cancelled": "Megszakítva.",
        "m_done": "Az összefűzés elkészült.",
        "about_title": "Névjegy", "tab_about": "Névjegy", "tab_license": "Licenc",
        "tab_comp": "Komponensek", "b_close": "Bezár",
    },
    "en": {
        "title": "Lossless Video Toolkit 1.0 – lossless video joiner, muxer, demuxer",
        "err_sync_k": "Sync lost at packet %d (damaged file?)",
        "err_sync_file": "Sync lost in file %s",
        "err_small": "File is too small",
        "err_notts": "Not an MPEG-TS / M2TS file",
        "err_nopsi": "PAT/PMT not found",
        "err_novideo": "No video stream",
        "err_nots": "No video timestamps found",
        "err_nots_end": "No video timestamps found at the end of the file",
        "c_pend": "Analyzing…",
        "c_noref": "The first file cannot be used as the reference",
        "c_ref": "Reference (first file)",
        "c_pktsize": "packet size differs",
        "c_pid": "PID layout differs (not remapped in this version)",
        "c_vcodec": "video codec differs",
        "c_fps": "frame rate differs",
        "c_res": "resolution differs",
        "c_scan": "interlaced/progressive differs",
        "c_prof": "profile/level differs",
        "c_vunk": "video parameters could not be verified",
        "c_acodec": "audio codec differs",
        "c_afmt": "audio format differs",
        "c_abr": "audio bitrate differs",
        "c_sps": "SPS differs (different camera settings?)",
        "c_ok": "Compatible",
        "j_nofiles": "No files",
        "j_badfile": "Faulty file or analysis still running: %s",
        "j_sameout": "The output file must not be one of the input files",
        "j_space": "Not enough free space on the output drive",
        "l_copy": "1. %s – copying (reference)",
        "l_off": "%d. %s – time offset: %.3f s",
        "l_audio": "   audio (PID 0x%X) at the seam: %+.1f ms, dropped PES: %d",
        "l_pcr": "   PCR jump at the seam (%+.1f ms) – discontinuity flag set",
        "l_done": "Done: %s",
        "cli_desc": "Lossless Video Toolkit 1.0",
        "b_add": "Add files…", "b_folder": "Add folder…",
        "b_remove": "Remove", "b_up": "▲ Up", "b_down": "▼ Down",
        "b_sort": "Sort by name", "b_clear": "Clear list",
        "b_about": "About", "b_lang": "Language: %s",
        "col_file": "File", "col_len": "Length", "col_mb": "MB",
        "col_video": "Video", "col_audio": "Audio", "col_state": "Status",
        "dlg_files": "AVCHD files", "ft_avchd": "AVCHD video", "ft_all": "All files",
        "dlg_folder": "Folder",
        "row_err": "Error: ", "row_warn": "Warning: ", "row_bad": "Cannot be joined: ",
        "summary": "%d files, total %s",
        "lbl_out": "Output file:", "b_browse": "Browse…",
        "b_start": "Start joining", "b_cancel": "Cancel",
        "m_noout_t": "Output", "m_noout": "Please specify an output file.",
        "m_over_t": "Overwrite", "m_over": "The file already exists. Overwrite?",
        "l_start": "— Joining started —",
        "e_prefix": "Error: %s", "cancelled": "Cancelled.",
        "m_done": "Joining finished.",
        "about_title": "About", "tab_about": "About", "tab_license": "License",
        "tab_comp": "Components", "b_close": "Close",
    },
}


_VSTR = {
    "hu": {
        "v_head": "— Ellenőrzés indul: az összefűzött fájl vizsgálata (%d varrat) —",
        "v_what": "Amit ellenőrzök:",
        "vc_struct": "Csomagszerkezet", "vd_struct": "szinkronbájtok, fájlméret, PES-fejlécek",
        "vc_cc": "Continuity counter", "vd_cc": "nincs kiesett vagy ismétlődő csomag (különösen a varratoknál)",
        "vc_pcr": "PCR óra", "vd_pcr": "nincs visszaugrás vagy túl nagy rés a varratoknál",
        "vc_ats": "ATS időbélyeg", "vd_ats": "az érkezési idő folytonos a varratoknál",
        "vc_vts": "Videó időzítés",
        "vd_vts": "minden kép pontosan egy képkockányi lépésben követi az előzőt (nincs kihagyott "
                  "vagy ismétlődő kép = nincs rángatás), a teljes hossz egyezik a forrásokéval",
        "vc_vseam": "Videó varratok", "vd_vseam": "a következő rész tiszta (IDR) képkockával indul",
        "vc_audio": "Hang",
        "vd_audio": "időbélyegek, teljes AC-3 keretek, CRC a varratoknál (nincs kattogás vagy kihagyás)",
        "vc_sync": "A/V szinkron",
        "vd_sync": "a hang ugyanazon az időrácson marad a képhez képest, mint az eredeti fájlban",
        "v_pass1": "1/3 Az összefűzött fájl beolvasása (szerkezet, számlálók, órák, időbélyegek gyűjtése)…",
        "v_pass2": "2/3 Videó időzítés és varratok elemzése…",
        "v_pass3": "3/3 Hang és A/V szinkron elemzése…",
        "v_size": "A fájlméret nem a csomagméret többszöröse (%d felesleges bájt)",
        "v_sync": "Szinkronvesztés a(z) %d. csomagnál – az ellenőrzés megszakadt",
        "v_pes": "Hibás PES-fejléc a(z) 0x%X folyamban (%s)",
        "v_cc_seam": "%d. fájl: continuity counter hiba a 0x%X PID-nél (%s)",
        "v_cc": "Continuity counter hiba a 0x%X PID-nél (%s) – a forrásfájlban is megvolt",
        "v_pcr_seam": "%d. varrat: PCR-ugrás %+.1f ms, jelzés nélkül",
        "v_pcr_seam_w": "%d. varrat: nagy PCR-rés (%+.1f ms)",
        "v_pcr": "PCR-szabálytalanság (%+.1f ms) itt: %s – a forrásban is megvolt",
        "v_ats_seam": "%d. varrat: ATS-ugrás %+.1f ms",
        "v_ats": "ATS-szabálytalanság itt: %s – a forrásban is megvolt",
        "v_v_seam": "%d. varrat (%s): videó időzítés-ugrás %+.2f képkocka (%+.1f ms) – rángatás",
        "v_v_gap": "Videó időzítés-ugrás %+.2f képkocka itt: %s – a forrásfájlban is megvolt",
        "v_pts_lt": "Videó PTS < DTS itt: %s",
        "v_p_gap": "Hibás megjelenítési sorrend (PTS): %+.2f képkocka eltérés itt: %s",
        "v_off": "%d. fájl: a videó időeltolása nem a tervezett (%+.1f ms)",
        "v_dur": "A teljes hossz eltér: várt %s, kapott %s",
        "v_novid": "Nincs értékelhető videó az összefűzött fájlban",
        "v_idr_none": "%d. varrat: az új rész nem IDR képkockával indul – az első képek hibásak lehetnek",
        "v_idr_na": "A videóvarrat IDR-ellenőrzése csak H.264-nél lehetséges, kihagyva",
        "v_a_pes": "Csonka hang PES itt: %s (%d bájt, a helyes %d lenne)",
        "v_a_sync": "A hangkeret határa elcsúszott itt: %s",
        "v_a_hdr": "Hibás AC-3 fejléc itt: %s",
        "v_a_cut": "Csonka AC-3 keret itt: %s",
        "v_a_crc": "AC-3 CRC-hiba itt: %s – sérült hangkeret (kattogás)",
        "v_a_none": "Nincs hang az összefűzött fájlban (PID 0x%X)",
        "v_a_seam_w": "%d. varrat: hangrés/átfedés %+.1f ms (fél hangkeretnél nagyobb, de egy keretnél kisebb)",
        "v_a_seam_g": "%d. varrat: %+.1f ms hangrés/átfedés – a forrásfájlok hangja nem illeszkedik pontosan "
                      "a képhez; a szinkron megmarad, de itt rövid csend vagy pattanás hallható lehet",
        "v_a_seam_e": "%d. varrat: %+.1f ms hanghiány/átfedés (több mint 1 s) – a hang jelentős része hiányzik",
        "v_a_step": "Hang időbélyeg-szabálytalanság %+.1f ms itt: %s – a forrásban is megvolt",
        "v_crc_info": "AC-3 CRC-ellenőrzés: %s",
        "v_crc_on": "bekapcsolva (a fájl elején igazolt módszer)",
        "v_crc_off": "kihagyva (a kontrollminta nem igazolta a módszert)",
        "v_s_grid": "%d. fájl: a hang elcsúszott a képhez képest (%+.1f ms az eredeti időrácstól)",
        "v_s_many": "%d. varrat: a hang elején %d keret esett ki",
        "v_s_noaudio": "%d. fájl: nincs hang az összefűzött fájl ezen szakaszában",
        "v_seam_hdr": "Varratok (kép = videó időugrás, hang = hangrés a varratnál, PCR = óraugrás):",
        "v_seam_line": "   %d. varrat @ %s: kép %+.1f ms | hang %s | PCR %s | %s",
        "v_idr_ok": "tiszta IDR-kezdés",
        "v_idr_cont": "folytatólagos (megosztott fájl)",
        "v_idr_unk": "IDR nem ellenőrizhető",
        "v_flag": "jelölt",
        "v_more": "   … a(z) %s további problémái nem kerülnek kiírásra",
        "v_res_head": "Ellenőrzés eredménye:",
        "v_ok": "rendben",
        "v_cnt": "%d hiba, %d figyelmeztetés",
        "v_final_perfect": "ELLENŐRZÉS: TÖKÉLETES – nincs hiba, nincs figyelmeztetés",
        "v_final_warn": "ELLENŐRZÉS: használható – %d figyelmeztetés, hiba nincs",
        "v_final_bad": "ELLENŐRZÉS: HIBÁS – %d hiba, %d figyelmeztetés",
        "v_failed": "Az ellenőrzés %d hibát talált, a kimenet nem lett elfogadva. "
                    "A fájl vizsgálatra megőrizve: %s",
        "l_ats": "   ATS-igazítás: %+.2f ms (az ATS/PCR kapcsolat megőrzéséhez)",
        "l_verify_off": "Ellenőrzés kihagyva (--no-verify).",
        "vc_pset": "SPS/PPS a kulcskockák előtt",
        "vd_pset": "minden kulcskocka (IDR vagy visszaállási pont) előtt ott van a szekvencia- (SPS) és "
                   "képparaméter-készlet (PPS); ami hiányzott, azt a program pótolta",
        "v_pset_miss": "Hiányzó %s a kulcskocka előtt itt: %s",
        "v_pset_na": "Az SPS/PPS-ellenőrzés csak H.264 videónál lehetséges, kihagyva",
        "v_pset_fixed": "%d kulcskockánál az SPS/PPS pótolva lett",
        "l_pset_scan": "Kulcskockák ellenőrzése a kimeneten: megvan-e az SPS/PPS…",
        "l_pset_ok": "   %d kulcskocka, mindegyik előtt ott van az SPS/PPS – rendben",
        "l_pset_miss": "   %d kulcskocka előtt (az összesen %d-ből) hiányzik az SPS és/vagy PPS",
        "l_pset_nosrc": "   %d kulcskockához nincs forrás-SPS/PPS, nem pótolható",
        "l_pset_done": "   Pótolva: %d kulcskocka, %d új csomag, %d bájt beszúrva; az ellenőrzés újra lefutott",
    },
    "en": {
        "v_head": "— Verification started: checking the joined file (%d seams) —",
        "v_what": "What is checked:",
        "vc_struct": "Packet structure", "vd_struct": "sync bytes, file size, PES headers",
        "vc_cc": "Continuity counter", "vd_cc": "no lost or repeated packets (especially at seams)",
        "vc_pcr": "PCR clock", "vd_pcr": "no backward jump or large gap at the seams",
        "vc_ats": "ATS timestamp", "vd_ats": "arrival time is continuous at the seams",
        "vc_vts": "Video timing",
        "vd_vts": "every picture follows the previous one by exactly one frame (no dropped or "
                  "repeated frame = no judder), total length matches the sources",
        "vc_vseam": "Video seams", "vd_vseam": "the next part starts with a clean (IDR) frame",
        "vc_audio": "Audio",
        "vd_audio": "timestamps, whole AC-3 frames, CRC at the seams (no clicks or dropouts)",
        "vc_sync": "A/V sync",
        "vd_sync": "audio stays on the same time grid relative to the picture as in the original file",
        "v_pass1": "1/3 Reading the joined file (structure, counters, clocks, collecting timestamps)…",
        "v_pass2": "2/3 Analyzing video timing and seams…",
        "v_pass3": "3/3 Analyzing audio and A/V sync…",
        "v_size": "File size is not a multiple of the packet size (%d extra bytes)",
        "v_sync": "Sync lost at packet %d – verification aborted",
        "v_pes": "Bad PES header in stream 0x%X (%s)",
        "v_cc_seam": "File %d: continuity counter error on PID 0x%X (%s)",
        "v_cc": "Continuity counter error on PID 0x%X (%s) – already present in the source file",
        "v_pcr_seam": "Seam %d: PCR jump %+.1f ms without a flag",
        "v_pcr_seam_w": "Seam %d: large PCR gap (%+.1f ms)",
        "v_pcr": "PCR irregularity (%+.1f ms) at %s – already present in the source",
        "v_ats_seam": "Seam %d: ATS jump %+.1f ms",
        "v_ats": "ATS irregularity at %s – already present in the source",
        "v_v_seam": "Seam %d (%s): video timing jump %+.2f frames (%+.1f ms) – judder",
        "v_v_gap": "Video timing jump %+.2f frames at %s – already present in the source file",
        "v_pts_lt": "Video PTS < DTS at %s",
        "v_p_gap": "Bad presentation order (PTS): %+.2f frame deviation at %s",
        "v_off": "File %d: video time offset differs from the planned one (%+.1f ms)",
        "v_dur": "Total length differs: expected %s, got %s",
        "v_novid": "No usable video in the joined file",
        "v_idr_none": "Seam %d: new part does not start with an IDR frame – first pictures may be corrupt",
        "v_idr_na": "The IDR check at video seams is only possible for H.264, skipped",
        "v_a_pes": "Truncated audio PES at %s (%d bytes, should be %d)",
        "v_a_sync": "Audio frame boundary misaligned at %s",
        "v_a_hdr": "Bad AC-3 header at %s",
        "v_a_cut": "Truncated AC-3 frame at %s",
        "v_a_crc": "AC-3 CRC error at %s – damaged audio frame (click)",
        "v_a_none": "No audio in the joined file (PID 0x%X)",
        "v_a_seam_w": "Seam %d: audio gap/overlap %+.1f ms (more than half a frame, less than a whole frame)",
        "v_a_seam_g": "Seam %d: %+.1f ms audio gap/overlap – the audio of the source files does not "
                      "line up exactly with the picture; sync is kept, but a short silence or pop may be audible here",
        "v_a_seam_e": "Seam %d: %+.1f ms audio loss/overlap (more than 1 s) – a large part of the audio is missing",
        "v_a_step": "Audio timestamp irregularity %+.1f ms at %s – already present in the source",
        "v_crc_info": "AC-3 CRC check: %s",
        "v_crc_on": "enabled (method verified on the start of the file)",
        "v_crc_off": "skipped (the control sample did not verify the method)",
        "v_s_grid": "File %d: audio is out of sync with the picture (%+.1f ms off the original time grid)",
        "v_s_many": "Seam %d: %d audio frames were lost at the start",
        "v_s_noaudio": "File %d: no audio in this part of the joined file",
        "v_seam_hdr": "Seams (picture = video time jump, audio = audio gap at the seam, PCR = clock jump):",
        "v_seam_line": "   seam %d @ %s: picture %+.1f ms | audio %s | PCR %s | %s",
        "v_idr_ok": "clean IDR start",
        "v_idr_cont": "continuation (split file)",
        "v_idr_unk": "IDR not checkable",
        "v_flag": "flagged",
        "v_more": "   … further %s problems are not printed",
        "v_res_head": "Verification result:",
        "v_ok": "OK",
        "v_cnt": "%d errors, %d warnings",
        "v_final_perfect": "VERIFICATION: PERFECT – no errors, no warnings",
        "v_final_warn": "VERIFICATION: usable – %d warnings, no errors",
        "v_final_bad": "VERIFICATION: FAILED – %d errors, %d warnings",
        "v_failed": "Verification found %d errors, the output was not accepted. "
                    "The file was kept for inspection: %s",
        "l_ats": "   ATS alignment: %+.2f ms (keeps the ATS/PCR relation)",
        "l_verify_off": "Verification skipped (--no-verify).",
        "vc_pset": "SPS/PPS before key frames",
        "vd_pset": "every key frame (IDR or recovery point) is preceded by the sequence (SPS) and "
                   "picture (PPS) parameter sets; anything missing was added by the program",
        "v_pset_miss": "Missing %s before the key frame at %s",
        "v_pset_na": "The SPS/PPS check is only possible for H.264 video, skipped",
        "v_pset_fixed": "SPS/PPS was added before %d key frames",
        "l_pset_scan": "Checking key frames on the output: is SPS/PPS present…",
        "l_pset_ok": "   %d key frames, each one is preceded by SPS/PPS – OK",
        "l_pset_miss": "   %d key frames (of %d) lack the SPS and/or PPS",
        "l_pset_nosrc": "   %d key frames have no source SPS/PPS and cannot be repaired",
        "l_pset_done": "   Repaired: %d key frames, %d new packets, %d bytes inserted; verification re-run",
    },
}
for _l in _STR:
    _STR[_l].update(_VSTR[_l])

_MSTR = {
    "hu": {
        "m_box": "Sérült MP4 doboz-szerkezet",
        "m_trunc": "A fájl csonka (egy doboz túlnyúlik a fájl végén)",
        "m_nomoov": "Nincs moov doboz (a felvétel nincs lezárva?)",
        "m_frag": "Töredezett (fragmentált) MP4 – ez a verzió nem támogatja",
        "m_enc": "Titkosított (DRM) sáv – nem támogatott",
        "m_ext": "Külső adathivatkozás a fájlban – nem támogatott",
        "m_rate": "A szerkesztőlista nem 1× sebességű – nem támogatott",
        "m_tables": "Inkonzisztens mintatáblák a(z) %d. sávban",
        "m_range": "A(z) %d. sáv adatblokkjai kilógnak az mdat-ból",
        "m_notrack": "Nincs sáv a fájlban",
        "m_big": "Túl nagy érték egy 32 bites mezőben",
        "c_kind": "a konténer típusa eltér (%s ≠ %s)",
        "c_mp4_tracks": "a sávok száma eltér",
        "c_mp4_kind": "a(z) %d. sáv típusa eltér",
        "c_mp4_ts": "a(z) %d. sáv időskálája eltér",
        "c_mp4_codec": "a(z) %d. sáv kodekje eltér (%s ≠ %s)",
        "c_mp4_matrix": "az elforgatás/transzformáció eltér",
        "c_mp4_cfg": "a(z) %d. sáv kodek-beállításai eltérnek – külön mintaleírás készül",
        "ft_video": "Videófájlok",
        "l_mp4_head": "MP4 összefűzés: %d fájl, %d sáv",
        "l_mp4_desc": "   a(z) %d. sávban %d különböző mintaleírás lesz",
        "l_mp4_drop": "   elhagyott opcionális táblák: %s",
        "l_mp4_pad": "   %d. rész vége, %d. sáv: %.1f ms csend (a sáv rövidebb a fájl hosszánál)",
        "l_mp4_layout": "Kimenet: moov elöl (gyors indítás), %s bites mdat, %s eltolások",
        "l_mp4_file": "%d. %s – másolás, kezdete a kimenetben: %.3f s",
        "m_pass1": "1/3 Dobozszerkezet és mintatáblák vizsgálata…",
        "m_pass2": "2/3 Adatintegritás (CRC32, minták egyenkénti összevetése)…",
        "m_pass3": "3/3 Időzítés, kulcskockák és A/V szinkron…",
        "mc_struct": "Dobozszerkezet",
        "md_struct": "hibátlan dobozok, egy moov és egy mdat, nincs levágott vég, a sávok száma stimmel",
        "mc_tables": "Mintatáblák",
        "md_tables": "a minták, darabok és méretek egymással és az adatterülettel egyeznek, nincs átfedés",
        "mc_data": "Adatintegritás",
        "md_data": "az összes kép- és hangadat bájtra azonos a forrásokéval (CRC32), a varratoknál mintánként is",
        "mc_timing": "Időzítés",
        "md_timing": "minden minta ideje és időtartama azonos a forrásokéval, a teljes hossz egyezik",
        "mc_vseam": "Videó varratok",
        "md_vseam": "minden rész kulcskockával indul",
        "mc_sync": "A/V szinkron",
        "md_sync": "a kép és a hang egymáshoz viszonyított időzítése minden részben ugyanaz, mint az eredetiben",
        "mv_boxes": "Hibás szerkezet: %s",
        "mv_moovn": "%d moov doboz van, pontosan egy kell",
        "mv_mdatn": "%d mdat doboz van, pontosan egy kell",
        "mv_tracks": "A sávok száma %d, a várt %d",
        "mv_plen": "Az mdat mérete %d, a várt %d bájt",
        "mv_kind": "A(z) %d. sáv típusa eltér az első fájlétól",
        "mv_count": "%d. sáv: a minták száma %d, a várt %d",
        "mv_mdur": "%d. sáv: a média hossza %d, a várt %d",
        "mv_stss": "%d. sáv: hibás kulcskocka-lista",
        "mv_overlap": "Átfedő adatdarabok a kimenetben (%d bájt)",
        "mv_crc": "%d. fájl: az adat megsérült a másolás során (CRC-eltérés)",
        "mv_spot": "%d. fájl, %d. sáv: a(z) %d. minta nem egyezik a forrással",
        "mv_tim": "%d. fájl, %d. sáv: az időzítés (stts/ctts) eltér a forrástól",
        "mv_dt": "%d. sáv: szokatlan minta-időköz (%.1f ms)",
        "mv_tkhd": "%d. sáv: a tkhd hossza nem egyezik a szerkesztőlistáéval",
        "mv_dur": "A teljes hossz %s, a várt %s",
        "mv_key": "%d. varrat: a(z) %d. rész nem kulcskockával indul – az első képek hibásak lehetnek",
        "mv_sync": "%d. fájl, %d. sáv: az időzítés %+.1f ms-mal eltér a várttól (A/V csúszás)",
        "mv_sync_out": "%d. fájl, %d. sáv: a hasznos szakasz kilóg a szerkesztőlistából (A/V csúszás)",
        "mv_pad": "%d. varrat: a(z) %d. sáv %.1f ms-mal rövidebb a rész hosszánál – itt csend/hiány lesz, a szinkron megmarad",
        "mv_pad_e": "%d. varrat: a(z) %d. sáv %.1f ms-mal (több mint 1 s) rövidebb a rész hosszánál – a sáv jelentős része hiányzik",
        "v_seam_hdr2": "Varratok (csend = hiányzó hang/kép a rész végén):",
        "v_seam_line2": "   %d. varrat @ %s: %s | %s",
        "v_key_ok": "kulcskockás kezdés",
        "v_key_no": "NEM kulcskockás kezdés",
    },
    "en": {
        "m_box": "Damaged MP4 box structure",
        "m_trunc": "The file is truncated (a box extends past the end of the file)",
        "m_nomoov": "No moov box (recording not finalized?)",
        "m_frag": "Fragmented MP4 – not supported in this version",
        "m_enc": "Encrypted (DRM) track – not supported",
        "m_ext": "External data reference in the file – not supported",
        "m_rate": "Edit list is not 1× speed – not supported",
        "m_tables": "Inconsistent sample tables in track %d",
        "m_range": "Data chunks of track %d lie outside the mdat",
        "m_notrack": "No tracks in the file",
        "m_big": "Value too large for a 32-bit field",
        "c_kind": "container type differs (%s ≠ %s)",
        "c_mp4_tracks": "number of tracks differs",
        "c_mp4_kind": "type of track %d differs",
        "c_mp4_ts": "time scale of track %d differs",
        "c_mp4_codec": "codec of track %d differs (%s ≠ %s)",
        "c_mp4_matrix": "rotation/transform differs",
        "c_mp4_cfg": "codec settings of track %d differ – a separate sample description is created",
        "ft_video": "Video files",
        "l_mp4_head": "MP4 join: %d files, %d tracks",
        "l_mp4_desc": "   track %d will have %d different sample descriptions",
        "l_mp4_drop": "   optional tables dropped: %s",
        "l_mp4_pad": "   end of part %d, track %d: %.1f ms of silence (track is shorter than the file)",
        "l_mp4_layout": "Output: moov first (fast start), %s-bit mdat, %s offsets",
        "l_mp4_file": "%d. %s – copying, starts in the output at %.3f s",
        "m_pass1": "1/3 Checking box structure and sample tables…",
        "m_pass2": "2/3 Data integrity (CRC32, samples compared one by one)…",
        "m_pass3": "3/3 Timing, key frames and A/V sync…",
        "mc_struct": "Box structure",
        "md_struct": "intact boxes, one moov and one mdat, nothing cut off, track count matches",
        "mc_tables": "Sample tables",
        "md_tables": "samples, chunks and sizes agree with each other and with the data area, no overlap",
        "mc_data": "Data integrity",
        "md_data": "all picture and audio data is byte-identical to the sources (CRC32), also sample by sample at the seams",
        "mc_timing": "Timing",
        "md_timing": "time and duration of every sample equal the sources, total length matches",
        "mc_vseam": "Video seams",
        "md_vseam": "every part starts with a key frame",
        "mc_sync": "A/V sync",
        "md_sync": "picture and audio keep the same relative timing in every part as in the original",
        "mv_boxes": "Bad structure: %s",
        "mv_moovn": "%d moov boxes, exactly one is required",
        "mv_mdatn": "%d mdat boxes, exactly one is required",
        "mv_tracks": "Track count is %d, expected %d",
        "mv_plen": "mdat size is %d, expected %d bytes",
        "mv_kind": "Type of track %d differs from the first file",
        "mv_count": "Track %d: sample count is %d, expected %d",
        "mv_mdur": "Track %d: media duration is %d, expected %d",
        "mv_stss": "Track %d: bad sync-sample list",
        "mv_overlap": "Overlapping data chunks in the output (%d bytes)",
        "mv_crc": "File %d: data was damaged during copying (CRC mismatch)",
        "mv_spot": "File %d, track %d: sample %d differs from the source",
        "mv_tim": "File %d, track %d: timing (stts/ctts) differs from the source",
        "mv_dt": "Track %d: unusual sample interval (%.1f ms)",
        "mv_tkhd": "Track %d: tkhd duration does not match the edit list",
        "mv_dur": "Total length is %s, expected %s",
        "mv_key": "Seam %d: part %d does not start with a key frame – first pictures may be corrupt",
        "mv_sync": "File %d, track %d: timing is off by %+.1f ms (A/V drift)",
        "mv_sync_out": "File %d, track %d: the useful range falls outside the edit list (A/V drift)",
        "mv_pad": "Seam %d: track %d is %.1f ms shorter than the part – silence/gap here, sync is kept",
        "mv_pad_e": "Seam %d: track %d is %.1f ms (more than 1 s) shorter than the part – a large piece of the track is missing",
        "v_seam_hdr2": "Seams (silence = missing audio/video at the end of the part):",
        "v_seam_line2": "   seam %d @ %s: %s | %s",
        "v_key_ok": "key-frame start",
        "v_key_no": "NOT a key-frame start",
    },
}
for _l in _STR:
    _STR[_l].update(_MSTR[_l])

_KSTR = {
    "hu": {
        "no_audio": "nincs",
        "k_ebml": "Sérült EBML szerkezet (nem Matroska fájl, vagy megsérült)",
        "k_trunc": "A fájl csonka (egy elem túlnyúlik a fájl végén)",
        "k_notmkv": "Nem Matroska / WebM fájl",
        "k_noseg": "Nincs Segment elem a fájlban",
        "k_notracks": "Nincs sávtáblázat (Tracks) a fájlban",
        "k_nocluster": "Nincs adat (Cluster) a fájlban",
        "k_unk": "Ismeretlen méretű elem a cluster belsejében – nem támogatott",
        "k_block": "Hibás blokkfejléc",
        "k_neg": "Az összefűzött időbélyeg negatív lenne",
        "c_mkv_doctype": "a konténer típusa eltér (Matroska / WebM)",
        "c_mkv_scale": "az időskála (TimecodeScale) eltér",
        "c_mkv_track": "a(z) %d. sáv száma vagy típusa eltér",
        "c_mkv_priv": "a(z) %d. sáv kodek-beállításai eltérnek – az összefűzött fájl nem lenne lejátszható",
        "c_mkv_cfg": "a(z) %d. sáv egyéb paraméterei eltérnek (pl. színinformáció)",
        "c_mkv_drop": "a fejezetek / csatolmányok ebből a fájlból nem kerülnek át",
        "l_mkv_head": "MKV összefűzés: %d fájl, %d sáv, időskála: %d ns",
        "l_mkv_drop": "   nem átvett elemek: %s",
        "l_mkv_file": "%d. %s – időeltolás: %+.3f s",
        "l_mkv_layout": "Kimenet: kereshető (SeekHead + Cues, %d keresőpont)",
        "l_mkv_audio": "   hang (%d. sáv) a varratnál: %+.1f ms, eldobott blokk: %d",
        "k_pass1": "1/3 Szerkezet, SeekHead és Cues vizsgálata…",
        "k_pass2": "2/3 Minden blokk beolvasása (CRC32, időbélyegek)…",
        "k_pass3": "3/3 Összevetés a forrásokkal, varratok, hang és A/V szinkron…",
        "kc_struct": "Szerkezet",
        "kd_struct": "EBML fejléc, egy Segment, egy Info és Tracks, a sávtáblázat azonos az elsőével, a cluster-ek száma stimmel",
        "kc_index": "Keresőindex",
        "kd_index": "a SeekHead és a Cues bejegyzések valódi elemekre mutatnak",
        "kc_data": "Adatintegritás",
        "kd_data": "minden kép-, hang- és feliratblokk bájtra azonos a forrásokéval (CRC32), sávonként és fájlonként",
        "kc_timing": "Időzítés",
        "kd_timing": "minden blokk ideje pontosan a forrás ideje + a fájl eltolása, a varratoknál nincs időugrás (nincs rángatás), a teljes hossz egyezik",
        "kc_vseam": "Videó varratok",
        "kd_vseam": "minden rész kulcskockával indul",
        "kc_audio": "Hang",
        "kd_audio": "nincs jelentős hangrés vagy átfedés a varratoknál, minden részben van hang",
        "kc_sync": "A/V szinkron",
        "kd_sync": "minden sáv ugyanazzal az eltolással került át, mint a kép",
        "kv_ebml": "Az EBML fejléc eltér az első fájlétól",
        "kv_segsize": "A Segment mérete nem egyezik a fájl méretével",
        "kv_cnt1": "%d db %s elem van, pontosan egy kell",
        "kv_clusters": "A cluster-ek száma %d, a várt %d",
        "kv_tracks": "A sávtáblázat eltér az első fájlétól",
        "kv_ctc": "A cluster-időbélyegek visszaugranak itt: %s",
        "kv_seek": "A SeekHead egyik bejegyzése rossz helyre mutat (ID 0x%X)",
        "kv_noseek": "Nincs SeekHead – egyes lejátszók lassabban nyitják meg",
        "kv_cue": "A Cues egyik bejegyzése nem Cluster-re mutat (%d)",
        "kv_nocues": "A Cues index üres – a keresés lassú lehet",
        "kv_count": "%d. fájl, %d. sáv: a blokkok száma %d, a várt %d",
        "kv_crc": "%d. fájl, %d. sáv: a blokkok adata eltér a forrástól (CRC-eltérés)",
        "kv_time": "%d. fájl, %d. sáv: az időzítés eltér a forrás idejétől + az eltolástól",
        "kv_track": "Ismeretlen sáv (%d) a kimenetben",
        "kv_neg": "Negatív időbélyeg itt: %s",
        "kv_sync": "%d. fájl, %d. sáv: az időzítés %+.1f ms-mal eltér a tervezettől (A/V csúszás)",
        "kv_key": "%d. varrat: az új rész nem kulcskockával indul – az első képek hibásak lehetnek",
    },
    "en": {
        "no_audio": "none",
        "k_ebml": "Damaged EBML structure (not a Matroska file, or corrupt)",
        "k_trunc": "The file is truncated (an element extends past the end of the file)",
        "k_notmkv": "Not a Matroska / WebM file",
        "k_noseg": "No Segment element in the file",
        "k_notracks": "No track table (Tracks) in the file",
        "k_nocluster": "No data (Cluster) in the file",
        "k_unk": "Unknown-size element inside a cluster – not supported",
        "k_block": "Bad block header",
        "k_neg": "The joined timestamp would be negative",
        "c_mkv_doctype": "container type differs (Matroska / WebM)",
        "c_mkv_scale": "time scale (TimecodeScale) differs",
        "c_mkv_track": "number or type of track %d differs",
        "c_mkv_priv": "codec settings of track %d differ – the joined file would not play correctly",
        "c_mkv_cfg": "other parameters of track %d differ (e.g. colour information)",
        "c_mkv_drop": "chapters / attachments of this file are not carried over",
        "l_mkv_head": "MKV join: %d files, %d tracks, time scale: %d ns",
        "l_mkv_drop": "   elements not carried over: %s",
        "l_mkv_file": "%d. %s – time offset: %+.3f s",
        "l_mkv_layout": "Output: seekable (SeekHead + Cues, %d cue points)",
        "l_mkv_audio": "   audio (track %d) at the seam: %+.1f ms, dropped blocks: %d",
        "k_pass1": "1/3 Checking structure, SeekHead and Cues…",
        "k_pass2": "2/3 Reading every block (CRC32, timestamps)…",
        "k_pass3": "3/3 Comparing with the sources, seams, audio and A/V sync…",
        "kc_struct": "Structure",
        "kd_struct": "EBML header, one Segment, one Info and Tracks, track table identical to the first file, cluster count matches",
        "kc_index": "Seek index",
        "kd_index": "SeekHead and Cues entries point to real elements",
        "kc_data": "Data integrity",
        "kd_data": "every picture, audio and subtitle block is byte-identical to the sources (CRC32), per track and file",
        "kc_timing": "Timing",
        "kd_timing": "every block time equals the source time + the file offset, no time jump at the seams (no judder), total length matches",
        "kc_vseam": "Video seams",
        "kd_vseam": "every part starts with a key frame",
        "kc_audio": "Audio",
        "kd_audio": "no significant audio gap or overlap at the seams, every part has audio",
        "kc_sync": "A/V sync",
        "kd_sync": "every track was moved by the same offset as the picture",
        "kv_ebml": "The EBML header differs from the first file's",
        "kv_segsize": "Segment size does not match the file size",
        "kv_cnt1": "%d %s elements, exactly one is required",
        "kv_clusters": "Cluster count is %d, expected %d",
        "kv_tracks": "The track table differs from the first file's",
        "kv_ctc": "Cluster timestamps jump backwards at %s",
        "kv_seek": "A SeekHead entry points to the wrong place (ID 0x%X)",
        "kv_noseek": "No SeekHead – some players open the file more slowly",
        "kv_cue": "A Cues entry does not point to a Cluster (%d)",
        "kv_nocues": "The Cues index is empty – seeking may be slow",
        "kv_count": "File %d, track %d: block count is %d, expected %d",
        "kv_crc": "File %d, track %d: block data differs from the source (CRC mismatch)",
        "kv_time": "File %d, track %d: timing differs from the source time + offset",
        "kv_track": "Unknown track (%d) in the output",
        "kv_neg": "Negative timestamp at %s",
        "kv_sync": "File %d, track %d: timing is off by %+.1f ms from the plan (A/V drift)",
        "kv_key": "Seam %d: the new part does not start with a key frame – first pictures may be corrupt",
    },
}
for _l in _STR:
    _STR[_l].update(_KSTR[_l])

_PSTR = {
    "hu": {
        "err_notps": "Nem MPEG Program Stream (PS) fájl",
        "err_ps_novideo": "Nem található MPEG-1/2 videó (más kodek PS-ben nem támogatott)",
        "err_ps_scrambled": "A fájl titkosított (másolásvédett) – nem támogatott",
        "err_ps_nots_end": "Nem található videó-időzítés a fájl végén",
        "c_ps_sys": "az MPEG rendszerréteg eltér (MPEG-1 / MPEG-2)",
        "c_ps_vid": "a videófolyam azonosítója eltér",
        "c_ps_ar": "a képarány eltér",
        "c_ps_streams": "a hangfolyamok eltérnek",
        "c_ps_nav": "a DVD NAV-csomagok megléte eltér",
        "c_ps_open": "nyitott GOP-pal kezdődik – a varrat utáni első 1–2 kép hibás lehet",
        "l_ps_head": "%s összefűzés: %d fájl, %s",
        "l_ps_junk": "   figyelmen kívül hagyott, felismerhetetlen bájtok: %d",
        "l_ps_lbn": "   figyelem: a NAV-csomagok LBN mezői nem igazíthatók (nem szektorhatáron vannak)",
        "l_ps_scr": "   SCR-ugrás a varratnál (%+.1f ms) – a lejátszók az időbélyegekből szinkronizálnak",
        "p_pass1": "1/2 Az összefűzött fájl beolvasása (csomagok, órák, időbélyegek, CRC32)…",
        "p_pass2": "2/2 Összevetés a forrásokkal, varratok, hang és A/V szinkron…",
        "pc_struct": "Szerkezet",
        "pd_struct": "csomagok (pack) és PES-fejlécek sértetlenek, a fájlméret és a csomagszám stimmel, a részek csomaghatáron kezdődnek",
        "pc_scr": "SCR óra",
        "pd_scr": "az első csomag órája a forrás + eltolás, nincs visszaugrás vagy nagy rés",
        "pc_data": "Adatintegritás",
        "pd_data": "minden kép-, hang- és feliratfolyam adata bájtra azonos a forrásokéval (CRC32), folyamonként és fájlonként",
        "pc_timing": "Időzítés",
        "pd_timing": "a kép megjelenítési ideje a forrás + eltolás, a varratoknál nincs időugrás (nincs rángatás), a teljes hossz egyezik",
        "pc_vseam": "Videó varratok",
        "pd_vseam": "minden rész I-képpel indul, lehetőleg zárt GOP-pal",
        "pc_audio": "Hang",
        "pd_audio": "nincs jelentős hangrés vagy átfedés a varratoknál, minden részben van hang",
        "pc_sync": "A/V szinkron",
        "pd_sync": "minden folyam ugyanazzal az eltolással került át, mint a kép",
        "pc_nav": "DVD NAV-csomagok",
        "pd_nav": "a NAV-csomagok óra- és szektorcím-mezői a csomag helyéhez és órájához képest pontosan úgy maradtak, mint a forrásban",
        "pv_size": "A fájlméret %d, a tervezett %d bájt",
        "pv_start": "A(z) %d. rész nem a tervezett helyen kezdődik",
        "pv_sys": "Az MPEG rendszerréteg a kimenet %d. bájtjánál eltér",
        "pv_scr_seam": "%d. varrat: SCR-ugrás %+.1f ms (a lejátszók az időbélyegekből szinkronizálnak)",
        "pv_scr": "SCR-szabálytalanság (%+.1f ms) itt: %s – a forrásban is megvolt",
        "pv_junk": "%d felismerhetetlen bájt a kimenetben",
        "pv_endcode": "A program_end_code megléte nem a tervezett",
        "pv_packs": "%d. rész: %d csomag van, a tervezett %d",
        "pv_data": "%d. fájl, %s: a folyam adata eltér a forrásétól (CRC vagy méret)",
        "pv_scr_off": "%d. fájl: az első csomag órája nem a forrás + eltolás",
        "pv_novid": "Nincs értékelhető videó a kimenet egy részében",
        "pv_off": "%d. fájl: a videó kezdete %+.1f ms-mal eltér a tervezettől",
        "pv_dur": "%d. fájl: a videó vége eltér a tervezettől",
        "pv_gap": "Videó időzítés-ugrás %+.2f képkocka itt: %s – a forrásfájlban is megvolt",
        "pv_seam": "%d. varrat: videó időzítés-ugrás %+.2f képkocka (%+.1f ms) – rángatás",
        "pv_idr": "%d. varrat: az új rész nem I-képpel indul – az első képek hibásak lehetnek",
        "pv_open": "%d. varrat: az új rész nyitott GOP-pal indul – az első 1–2 kép hibás lehet",
        "pv_total": "A teljes hossz eltér: várt %s, kapott %s",
        "pv_sync": "%d. fájl, %s: az időzítés %+.1f ms-mal eltér a tervezettől (A/V csúszás)",
        "pv_a_seam": "%d. varrat: hangrés/átfedés %+.1f ms",
        "pv_nav": "%d. fájl: a NAV-csomagok óra- vagy szektorcím-mezői nem a tervezett módon változtak",
    },
    "en": {
        "err_notps": "Not an MPEG Program Stream (PS) file",
        "err_ps_novideo": "No MPEG-1/2 video found (other codecs in PS are not supported)",
        "err_ps_scrambled": "The file is encrypted (copy-protected) – not supported",
        "err_ps_nots_end": "No video timing found at the end of the file",
        "c_ps_sys": "the MPEG system layer differs (MPEG-1 / MPEG-2)",
        "c_ps_vid": "the video stream id differs",
        "c_ps_ar": "the aspect ratio differs",
        "c_ps_streams": "the audio streams differ",
        "c_ps_nav": "the presence of DVD NAV packs differs",
        "c_ps_open": "starts with an open GOP – the first 1–2 pictures after the seam may be corrupt",
        "l_ps_head": "%s join: %d files, %s",
        "l_ps_junk": "   ignored unrecognised bytes: %d",
        "l_ps_lbn": "   warning: the LBN fields of the NAV packs could not be adjusted (not on a sector boundary)",
        "l_ps_scr": "   SCR jump at the seam (%+.1f ms) – players synchronise from the timestamps",
        "p_pass1": "1/2 Reading the joined file (packs, clocks, timestamps, CRC32)…",
        "p_pass2": "2/2 Comparing with the sources, seams, audio and A/V sync…",
        "pc_struct": "Structure",
        "pd_struct": "packs and PES headers intact, file size and pack count match, every part starts on a pack boundary",
        "pc_scr": "SCR clock",
        "pd_scr": "the first pack clock is the source + offset, no backward jump or large gap",
        "pc_data": "Data integrity",
        "pd_data": "every picture, audio and subtitle stream is byte-identical to the sources (CRC32), per stream and file",
        "pc_timing": "Timing",
        "pd_timing": "picture presentation time equals the source + offset, no time jump at the seams (no judder), total length matches",
        "pc_vseam": "Video seams",
        "pd_vseam": "every part starts with an I picture, preferably a closed GOP",
        "pc_audio": "Audio",
        "pd_audio": "no significant audio gap or overlap at the seams, every part has audio",
        "pc_sync": "A/V sync",
        "pd_sync": "every stream was moved by the same offset as the picture",
        "pc_nav": "DVD NAV packs",
        "pd_nav": "the clock and sector-address fields of the NAV packs relate to the pack position and clock exactly as in the source",
        "pv_size": "File size is %d, planned %d bytes",
        "pv_start": "Part %d does not start at the planned position",
        "pv_sys": "The MPEG system layer differs at output byte %d",
        "pv_scr_seam": "Seam %d: SCR jump %+.1f ms (players synchronise from the timestamps)",
        "pv_scr": "SCR irregularity (%+.1f ms) at %s – also present in the source",
        "pv_junk": "%d unrecognised bytes in the output",
        "pv_endcode": "The presence of program_end_code is not as planned",
        "pv_packs": "Part %d: %d packs, planned %d",
        "pv_data": "File %d, %s: stream data differs from the source (CRC or size)",
        "pv_scr_off": "File %d: the first pack clock is not the source + offset",
        "pv_novid": "No usable video in a part of the output",
        "pv_off": "File %d: the video start is off by %+.1f ms from the plan",
        "pv_dur": "File %d: the video end differs from the plan",
        "pv_gap": "Video timing jump %+.2f frames at %s – also present in the source file",
        "pv_seam": "Seam %d: video timing jump %+.2f frames (%+.1f ms) – judder",
        "pv_idr": "Seam %d: the new part does not start with an I picture – first pictures may be corrupt",
        "pv_open": "Seam %d: the new part starts with an open GOP – the first 1–2 pictures may be corrupt",
        "pv_total": "Total length differs: expected %s, got %s",
        "pv_sync": "File %d, %s: timing is off by %+.1f ms from the plan (A/V drift)",
        "pv_a_seam": "Seam %d: audio gap/overlap %+.1f ms",
        "pv_nav": "File %d: the clock or sector-address fields of the NAV packs did not change as planned",
    },
}
for _l in _STR:
    _STR[_l].update(_PSTR[_l])

_ASTR = {
    "hu": {
        "tab_join": "Összefűzés", "tab_tools": "Hang / stream eszközök",
        "t_open": "Fájl megnyitása…", "t_nofile": "Nincs fájl megnyitva",
        "t_col_type": "Típus", "t_col_desc": "Folyam", "t_col_codec": "Kodek", "t_col_state": "Állapot",
        "t_video": "kép", "t_audio": "hang", "t_ok": "kezelhető", "t_unsup": "nem támogatott",
        "t_extract": "Kijelölt folyam kinyerése…", "t_replace_box": "Hangsáv cseréje",
        "t_newaudio": "Új hang (nyers .ac3 / .eac3 / .aac / .mp2 / .mp3 / .opus):", "t_delay": "Hang eltolása (ms):", "t_shift": "Hang eltolása (új hang nélkül)",
        "t_delay_help": "Pozitív érték = a hang később szól, negatív = korábban. 1 ms-os lépésekkel állítható (gombok: ±1, ±10, ±100). Az eltolás a kijelölt hangsávra vonatkozik.",
        "t_out": "Kimeneti fájl:", "t_replace": "A kijelölt hangsáv cseréje", "t_verify": "Ellenőrzés a kimeneten",
        "t_help": "Jelölj ki egy hangsávot, mentsd ki, javítsd külső programmal, majd itt cseréld vissza. "
                  "A kép és a többi sáv bájtra azonos marad. Késleltetés: pozitív érték = a hang később szól, negatív = korábban. TS-ben csak AC-3, MKV-ban bármilyen hang cserélhető.",
        "t_pick": "Jelölj ki egy hangsávot a listában.", "t_pick_new": "Válaszd ki az új hangfájlt.",
        "t_bad_delay": "A késleltetés egész szám (ms) legyen.", "t_unsup_kind": "Ez a fájltípus itt nem támogatott (csak TS / M2TS / MP4 / MOV / MKV).",
        "t_done": "Kész.", "t_sync_title": "Szinkron-figyelmeztetés", "t_open_title": "Fájl megnyitása", "t_save_title": "Mentés",
        "au_unk": "A hangfájl formátuma nem ismerhető fel (AC-3, E-AC-3, AAC-ADTS, MP2, MP3, Opus/Ogg)",
        "au_opus_var": "Az új Opus-fájl csomagjainak hossza nem egyenletes – a cseréhez egyenletes (pl. 20 ms-os) kódolás kell",
        "au_opus_dur": "Az Opus csomaghossz eltér: régi %.1f ms, új %.1f ms – kódold újra azonos keretmérettel",
        "au_l_pre": "   figyelem: az Opus pre-skip eltér (régi %d, új %d minta) – a hang néhány ms-ot elcsúszhat",
        "au_pes": "Hibás PES-szerkezet a hangfolyamban",
        "au_lace": "A hangsáv laced blokkokat használ – nem támogatott",
        "au_cfg": "A sáv kodek-beállítása hiányzik vagy érthetetlen",
        "au_unsup": "Ez a folyam nem támogatott: %s",
        "au_mismatch": "Az új hang formátuma eltér a régiétől: régi %s, új %s",
        "au_pcr": "A hangsáv egyben az órajel (PCR) sávja is – nem cserélhető",
        "au_toolong": "A(z) %d. hangblokk az új hanggal %d csomag lenne, de csak %d hely van – az új hang bitrátája nagyobb a réginél",
        "au_range": "A hangblokk időbélyege kívül esik a cluster ±32 s-os tartományán – a késleltetés túl nagy",
        "au_l_ext": "Kinyerés: %s → %s",
        "au_l_info": "   %s, %d keret, %.1f s, %d Hz, %s csat., %.0f kbps, kihagyott bájt: %d",
        "au_l_done": "Kész: %d bájt kiírva.",
        "au_l_count": "   figyelem: a keretek száma eltér (régi %d, új %d, különbség %+.0f ms)",
        "au_l_rate": "   figyelem: a bitráta eltér (régi %.0f, új %.0f kbps)",
        "au_l_old": "Régi hang: %s, %d keret, %.1f s, %d PES",
        "au_l_new": "Új hang: %s, %d keret, %.1f s",
        "au_l_ts": "TS átírva: %d hangblokk, %d üres csomag, késleltetés %+.1f ms",
        "au_l_mp4": "MP4 átírva: %d hangminta, %d adatdarab",
        "au_l_mkv": "MKV átírva: %d hangblokk, %d cluster, %d keresési pont",
        "au_l_rep": "Hangcsere: %s ← %s",
        "au_v_head": "— Ellenőrzés indul: a kész fájl és a forrás összevetése —",
        "ac_struct": "Szerkezet", "ad_struct": "fájlméret, csomag- és sávszerkezet, kodek-beállítások egyeznek a forrással",
        "ac_data": "Új hang", "ad_data": "a kimenetből visszaolvasott hang bájtra azonos az új hangfájllal (CRC32)",
        "ac_cc": "Folytonosság", "ad_cc": "a hangsáv csomagszámlálója megszakítás nélkül folytatódik",
        "ac_pts": "Időzítés", "ad_pts": "a hangblokkok időbélyegei az eredeti + késleltetés értékek",
        "ac_other": "Kép és többi sáv", "ad_other": "minden más sáv adata és időzítése bájtra azonos a forrással",
        "au_v_size": "A fájlméret %d, az elvárt %d bájt",
        "au_v_other": "A(z) %d. csomag (nem hang) eltér a forrástól",
        "au_v_pid": "A(z) %d. csomag azonosítója hibás",
        "au_v_cc": "A hangsáv számlálója a(z) %d. csomagnál megszakad",
        "au_v_data": "A kimenetben lévő hang eltér az új hangfájltól (%d bájt / %d vagy CRC)",
        "au_v_pts": "%d hangblokk időbélyege nem a tervezett",
        "au_v_parse": "A kimeneti fájl nem olvasható vissza: %s",
        "au_v_tracks": "A sávok száma %d, az elvárt %d",
        "au_v_track": "A(z) %d. sáv azonosítója vagy kodek-beállítása megváltozott",
        "au_v_tab": "A(z) %d. sáv idő- vagy méretadatai eltérnek a tervezettől",
        "au_v_track_data": "A(z) %d. sáv mintáinak adata eltér a forrástól",
        "au_v_other_mkv": "Egy nem cserélt sáv blokkjai vagy időzítése eltér a forrástól",
        "au_v_mkvtracks": "A sávleírás (Tracks) eltér a forrástól",
        "au_v_ebml": "Az EBML fejléc eltér a forrástól",
        "au_v_clusters": "A clusterek száma %d, az elvárt %d",
        "au_v_ctc": "A cluster időbélyege visszaugrik itt: %s",
        "au_ts_only": "TS / M2TS fájlban csak az AC-3 hang cserélhető (a kamerák és lejátszók ezt várják) – más kodek nem támogatott",
        "au_l_fmt": "Hangformátum-változás: %g Hz / %d csat. → %d Hz / %d csat. (a sáv fejléce átíródik)",
        "au_shift_zero": "Az eltolás 0 ms – adj meg nem nulla értéket",
        "au_l_shiftrun": "Hang eltolása: %s, %+.1f ms (a hangadat bájtra azonos marad)",
        "sy_shift": "   Hang eltolása: %+.1f ms (pozitív = később szól). Csak az időzítés változik, a hangadat nem.",
        "sy_shift_big": "SZINKRON: nagy eltolás (%+.0f ms) – a hang több mint 1 másodpercet mozdul a képhez képest.\n"
                        "    Javítás: ellenőrizd az eredményt több ponton; ha nem a várt, próbálj kisebb értéket.",
        "au_l_switch": "Kodekváltás: %s → %s (a sáv fejléce átíródik, az időzítés időalapon készül)",
        "sy_dur_small": "SZINKRON: az új hang %+.1f ms-mal tér el a régi hosszától (legfeljebb 1 keret).\n"
                        "    Ok: jellemzően kódolói előfutás (AAC, MP3, Opus) vagy kerekítés a hang végén.\n"
                        "    Javítás: ha a hang a képhez képest késik vagy siet, add meg a Késleltetést %+.0f ms-ra "
                        "(pozitív érték = később szól, negatív = korábban), és ellenőrizd a kész fájlt egy jól hallható "
                        "eseménynél (taps, ütés).",
        "sy_dur_small2": "SZINKRON: az új hang %+.1f ms-mal tér el a régi hosszától (legfeljebb 1 keret) – ez jellemzően "
                         "kódolói előfutás; a javítást lásd a következő figyelmeztetésben.",
        "sy_dur_mid": "SZINKRON: az új hang %+.1f ms-mal hosszabb/rövidebb a réginél (több mint 1 keret = %.0f ms).\n"
                      "    Ok: a szerkesztőben vágtál, töröltél, beszúrtál, vagy a hang elején/végén szünet lett.\n"
                      "    Javítás: exportáld a hangot pontosan az eredeti hosszal (ne vágj, ne illessz be), "
                      "vagy ha a különbség a hang elején van, használd a Késleltetés mezőt. Ha a hang közepén "
                      "vágtál, az utána következő rész elcsúszik – ezt csak újraexportálással lehet javítani.",
        "sy_dur_big": "SÚLYOS SZINKRON-KOCKÁZAT: az új hang hossza %+.1f ms-mal tér el (régi %.1f s, új %.1f s).\n"
                      "    Ok: nem ugyanaz a hang, vagy jelentősen megvágták / meghosszabbították.\n"
                      "    Javítás: ellenőrizd, hogy a helyes fájlt választottad-e; exportáld újra az eredeti hosszal. "
                      "Ilyen eltérésnél a hang biztosan nem fog a képhez illeszkedni a teljes hosszon.",
        "sy_enc": "SZINKRON: %s → %s hangcsere. Ha az új hangot a kinyert hangból újrakódolták (ffmpeg, szerkesztőprogram), "
                  "az előfutások miatt a hang a saját méréseim szerint tipikusan %+.1f ms-ot ELTOLÓDIK "
                  "(pozitív = késik a képhez képest), hacsak a program ezt nem kompenzálta. A pontos érték a kódolótól, "
                  "a csatornaszámtól és a szerkesztőprogramtól függően akár ±20 ms-mal is eltérhet.\n"
                  "    Javítás: játszd le a kész fájl elejét egy hangos eseménynél (taps, ütés). Ha a hang késik/siet, "
                  "futtasd újra a Késleltetés mezővel; kiindulásnak %+.1f ms ajánlott (a negatív érték korábbra teszi a hangot). "
                  "Más szerkesztőprogram más előfutással dolgozhat – ezért a végső értéket mindig hallás alapján ellenőrizd.",
        "sy_enc_small": "   Kódolói előfutás (%s → %s): kb. %+.1f ms – észrevehetetlenül kicsi, nem igényel javítást.",
        "sy_pre": "SZINKRON: az Opus pre-skip eltér (%+.1f ms; régi %d, új %d minta).\n"
                  "    Javítás: kódold újra az Opus-hangot az eredeti pre-skip értékkel, vagy állítsd a "
                  "Késleltetést %+.1f ms-ra." ,
        "sy_noold": "SZINKRON: a régi hangsáv kodekje ismeretlen, ezért a korábbi varratok időugrásait nem lehet megőrizni; "
                    "az új hang folyamatosan, az eredeti hang kezdetétől kerül be.\n"
                    "    Javítás: ha a régi felvételben összefűzési varratok voltak, a hang a varrat után elcsúszhat; "
                    "ellenőrizd a kész fájl több pontján.",
        "sy_sbr": "SZINKRON: kis mintavételű AAC – HE-AAC (SBR) esetén a sáv fejléce téves lehet.\n"
                  "    Javítás: használj AAC-LC kódolást 44,1 vagy 48 kHz-en.",
        "sy_gaps": "   Az eredeti hangsávban %d időugrás (korábbi összefűzések varratai) van; ezek az új hangban is megmaradnak.",
        "sy_delay": "   Késleltetés alkalmazva: %+.1f ms (pozitív = később szól).",
        "sy_ok": "✓ Szinkron-előellenőrzés: nem találtam kockázatot (hossz, kerethossz, kódolás egyezik). "
                 "A program hangot nem dekódol, ezért a hullámformát nem hasonlítja össze – a kész fájlt "
                 "ettől még érdemes egy hangos eseménynél (taps, ütés) ellenőrizni.",
        "sy_sum": "ÖSSZEFOGLALÓ: %d szinkron-figyelmeztetés. Játszd le a kész fájlt az elején, a közepén és a végén "
                  "(taps, ütés, szájmozgás); eltérés esetén futtasd újra a Késleltetés mezővel vagy javított hanggal.",
        "au_v_nonmono": "A hangblokkok időbélyege nem növekvő – a lejátszó hibát jelezhet",
        "cli_au_desc": "Hang / stream eszközök: streams, extract, replace-audio",
    },
    "en": {
        "tab_join": "Join", "tab_tools": "Audio / stream tools",
        "t_open": "Open file…", "t_nofile": "No file opened",
        "t_col_type": "Type", "t_col_desc": "Stream", "t_col_codec": "Codec", "t_col_state": "State",
        "t_video": "video", "t_audio": "audio", "t_ok": "supported", "t_unsup": "not supported",
        "t_extract": "Extract selected stream…", "t_replace_box": "Replace audio track",
        "t_newaudio": "New audio (raw .ac3 / .eac3 / .aac / .mp2 / .mp3 / .opus):", "t_delay": "Audio offset (ms):", "t_shift": "Shift audio (no new audio)",
        "t_delay_help": "Positive = the audio plays later, negative = earlier. Adjustable in 1 ms steps (buttons: ±1, ±10, ±100). The offset applies to the selected audio track.",
        "t_out": "Output file:", "t_replace": "Replace the selected audio track", "t_verify": "Verify the output",
        "t_help": "Select an audio track, save it, improve it in an external program, then swap it back here. "
                  "The picture and all other tracks stay byte-identical. Delay: positive = audio plays later, negative = earlier. In TS only AC-3, in MKV any audio can be replaced.",
        "t_pick": "Select an audio track in the list.", "t_pick_new": "Choose the new audio file.",
        "t_bad_delay": "The delay must be a whole number (ms).", "t_unsup_kind": "This file type is not supported here (TS / M2TS / MP4 / MOV / MKV only).",
        "t_done": "Done.", "t_sync_title": "Sync warning", "t_open_title": "Open file", "t_save_title": "Save",
        "au_unk": "The audio file format is not recognised (AC-3, E-AC-3, AAC-ADTS, MP2, MP3, Opus/Ogg)",
        "au_opus_var": "The packets of the new Opus file are not of uniform length – re-encode with a fixed frame size (e.g. 20 ms)",
        "au_opus_dur": "The Opus packet length differs: old %.1f ms, new %.1f ms – re-encode with the same frame size",
        "au_l_pre": "   warning: the Opus pre-skip differs (old %d, new %d samples) – audio may shift by a few ms",
        "au_pes": "Invalid PES structure in the audio stream",
        "au_lace": "The audio track uses laced blocks – not supported",
        "au_cfg": "The track codec configuration is missing or unreadable",
        "au_unsup": "This stream is not supported: %s",
        "au_mismatch": "The new audio format differs from the old one: old %s, new %s",
        "au_pcr": "The audio track is also the clock (PCR) track – it cannot be replaced",
        "au_toolong": "Audio block %d would need %d packets with the new audio but only %d slots exist – the new bitrate is higher than the old one",
        "au_range": "The audio block timestamp is outside the ±32 s range of the cluster – the delay is too large",
        "au_l_ext": "Extracting: %s → %s",
        "au_l_info": "   %s, %d frames, %.1f s, %d Hz, %s ch, %.0f kbps, skipped bytes: %d",
        "au_l_done": "Done: %d bytes written.",
        "au_l_count": "   warning: frame count differs (old %d, new %d, difference %+.0f ms)",
        "au_l_rate": "   warning: bitrate differs (old %.0f, new %.0f kbps)",
        "au_l_old": "Old audio: %s, %d frames, %.1f s, %d PES",
        "au_l_new": "New audio: %s, %d frames, %.1f s",
        "au_l_ts": "TS rewritten: %d audio blocks, %d empty packets, delay %+.1f ms",
        "au_l_mp4": "MP4 rewritten: %d audio samples, %d data chunks",
        "au_l_mkv": "MKV rewritten: %d audio blocks, %d clusters, %d cue points",
        "au_l_rep": "Audio replace: %s ← %s",
        "au_v_head": "— Verification starts: comparing the result with the source —",
        "ac_struct": "Structure", "ad_struct": "file size, packet and track structure and codec settings match the source",
        "ac_data": "New audio", "ad_data": "the audio read back from the output is byte-identical to the new audio file (CRC32)",
        "ac_cc": "Continuity", "ad_cc": "the audio packet counter continues without a break",
        "ac_pts": "Timing", "ad_pts": "audio block timestamps equal the original + delay",
        "ac_other": "Picture and other tracks", "ad_other": "all other tracks are byte-identical to the source, including timing",
        "au_v_size": "File size is %d, expected %d bytes",
        "au_v_other": "Packet %d (not audio) differs from the source",
        "au_v_pid": "Packet %d has a wrong identifier",
        "au_v_cc": "The audio counter breaks at packet %d",
        "au_v_data": "The audio in the output differs from the new audio file (%d bytes / %d or CRC)",
        "au_v_pts": "%d audio block timestamps are not as planned",
        "au_v_parse": "The output file cannot be read back: %s",
        "au_v_tracks": "Track count is %d, expected %d",
        "au_v_track": "The id or codec settings of track %d changed",
        "au_v_tab": "The timing or size data of track %d differ from the plan",
        "au_v_track_data": "The sample data of track %d differs from the source",
        "au_v_other_mkv": "The blocks or timing of an untouched track differ from the source",
        "au_v_mkvtracks": "The track description (Tracks) differs from the source",
        "au_v_ebml": "The EBML header differs from the source",
        "au_v_clusters": "Cluster count is %d, expected %d",
        "au_v_ctc": "The cluster timestamp jumps back at %s",
        "au_ts_only": "Only AC-3 audio can be replaced in a TS / M2TS file (cameras and players expect it) – other codecs are not supported",
        "au_l_fmt": "Audio format change: %g Hz / %d ch → %d Hz / %d ch (the track header is rewritten)",
        "au_shift_zero": "The offset is 0 ms – enter a non-zero value",
        "au_l_shiftrun": "Shifting audio: %s, %+.1f ms (the audio data stays byte-identical)",
        "sy_shift": "   Audio shift: %+.1f ms (positive = plays later). Only the timing changes, not the audio data.",
        "sy_shift_big": "SYNC: large shift (%+.0f ms) – the audio moves by more than one second against the picture.\n"
                        "    Fix: check the result at several points; if it is not as expected, try a smaller value.",
        "au_l_switch": "Codec change: %s → %s (the track header is rewritten, timing is built from time)",
        "sy_dur_small": "SYNC: the new audio differs by %+.1f ms from the old length (at most one frame).\n"
                        "    Cause: usually encoder delay (AAC, MP3, Opus) or rounding at the end of the audio.\n"
                        "    Fix: if the audio is late or early against the picture, set the Delay to %+.0f ms "
                        "(positive = plays later, negative = earlier) and check the result at a clear sound event (clap, hit).",
        "sy_dur_small2": "SYNC: the new audio differs by %+.1f ms from the old length (at most one frame) – usually "
                         "encoder delay; see the fix in the next warning.",
        "sy_dur_mid": "SYNC: the new audio is %+.1f ms longer/shorter than the old one (more than one frame = %.0f ms).\n"
                      "    Cause: you cut, deleted or inserted something in the editor, or silence was added at the start/end.\n"
                      "    Fix: export the audio with exactly the original length (do not trim or insert), "
                      "or if the difference is at the start, use the Delay field. If you cut in the middle, "
                      "everything after the cut will drift – that can only be fixed by exporting again.",
        "sy_dur_big": "SEVERE SYNC RISK: the new audio length differs by %+.1f ms (old %.1f s, new %.1f s).\n"
                      "    Cause: not the same audio, or it was cut / extended significantly.\n"
                      "    Fix: check that you chose the right file; export again with the original length. "
                      "With such a difference the audio will certainly not match the picture over the full length.",
        "sy_enc": "SYNC: %s → %s audio replace. If the new audio was re-encoded from the extracted audio (ffmpeg, an editor), "
                  "because of encoder delays the audio typically SHIFTS by %+.1f ms in my measurements "
                  "(positive = late against the picture), unless the program compensated for it. The exact value can differ by up to "
                  "±20 ms depending on the encoder, the channel count and the editing program.\n"
                  "    Fix: play the beginning of the result at a sound event (clap, hit). If the audio is late/early, "
                  "run again with the Delay field; %+.1f ms is a recommended starting value (a negative value moves the audio earlier). "
                  "Other editors may work with other delays – so always confirm the final value by ear.",
        "sy_enc_small": "   Encoder delay (%s → %s): about %+.1f ms – imperceptibly small, no fix needed.",
        "sy_pre": "SYNC: the Opus pre-skip differs (%+.1f ms; old %d, new %d samples).\n"
                  "    Fix: re-encode the Opus audio with the original pre-skip, or set the Delay to %+.1f ms.",
        "sy_noold": "SYNC: the old audio codec is unknown, so the time jumps of earlier joins cannot be preserved; "
                    "the new audio is placed continuously from the start of the old audio.\n"
                    "    Fix: if the old recording had join seams, the audio may drift after a seam; "
                    "check the result at several points.",
        "sy_sbr": "SYNC: low-sample-rate AAC – for HE-AAC (SBR) the track header may be wrong.\n"
                  "    Fix: use AAC-LC at 44.1 or 48 kHz.",
        "sy_gaps": "   The original audio track has %d time jumps (seams of earlier joins); they are kept in the new audio too.",
        "sy_delay": "   Delay applied: %+.1f ms (positive = plays later).",
        "sy_ok": "✓ Sync pre-check: no risk found (length, frame length, encoding match). "
                 "The program does not decode audio, so it cannot compare the waveform – still check the result "
                 "at a sound event (clap, hit).",
        "sy_sum": "SUMMARY: %d sync warnings. Play the result at the start, middle and end "
                  "(clap, hit, lip movement); if it is off, run again with the Delay field or a corrected audio file.",
        "au_v_nonmono": "The audio block timestamps are not increasing – the player may report an error",
        "cli_au_desc": "Audio / stream tools: streams, extract, replace-audio",
    },
}
for _l in _STR:
    _STR[_l].update(_ASTR[_l])

_CSTR = {
    "hu": {
        "t_add": "Fájlok hozzáadása…", "t_remove": "Eltávolítás", "t_clear": "Lista törlése",
        "t_compose": "Összeállítás a kijelölés szerint",
        "t_extract": "Kijelölt folyamok kinyerése…",
        "t_replace_box": "Összeállítás (kép + hang a kijelölt folyamokból)",
        "t_help": "Tölts be több fájlt (videót, hangot vagy nyers hangfájlt). A bal oldali jelölőnégyzettel jelölöd ki, "
                  "mi marad: pontosan EGY képfolyam (ez az alapfájl) és EGY hangfolyam (ez kerül a kimenetbe). Ha a hang "
                  "másik fájlból van, a program belül kinyeri és kicseréli az alapfájl hangsávját – nyers hangfájl nem kell. "
                  "A kép és a többi sáv bájtra azonos marad. Ha az alapfájl saját hangját jelölöd ki, csak a késleltetés "
                  "érvényesül (pozitív = később szól, negatív = korábban). Több hangsávos alapfájlnál kattints arra a "
                  "hangsávra, amelyiket cserélni kell.",
        "t_nofile": "Nincs fájl betöltve", "t_nothing": "Nincs kijelölt, kinyerhető folyam.",
        "t_dir": "Mappa a kinyert folyamoknak", "t_raw": "nyers hang",
        "col_stream": "Fájl / folyam",
        "col_delay": "Késleltetés (kép / hang)", "t_col_delay": "Késleltetés",
        "l_ats_seam": "   ATS-igazítás a varratnál: %+.2f ms (hogy az érkezési idő ne ugorjon vissza)",
        "au_l_grow": "Az új hang bitrátája nagyobb: %d extra csomag beszúrva (%d hangblokkhoz) – a többi sáv változatlan",
        "row_skip": "Kihagyva (nincs bejelölve)",
        "cp_novideo": "Jelölj ki egy képfolyamot – ez adja az alapfájlt.",
        "cp_manyvideo": "Csak egy képfolyam jelölhető ki (az alapfájl).",
        "cp_noaudio": "Jelölj ki egy hangfolyamot, ami a kimenetben marad.",
        "cp_manyaudio": "Csak egy hangfolyam jelölhető ki – az kerül a kimenetbe.",
        "cp_nobaseaudio": "Az alapfájlban nincs hangsáv, amit cserélni lehetne (új sávot a program nem tud hozzáadni).",
        "cp_whichaudio": "Az alapfájlban több hangsáv van – kattints (jelöld ki a listában) arra, amelyiket le kell cserélni.",
        "cp_l_plan": "Összeállítás: kép = %s | hang = %s",
        "cp_l_same": "A kijelölt hang az alapfájlé: csak a késleltetés érvényesül.",
        "cp_l_skip": "   kihagyva (nem támogatott vagy nyers): %s",
        "cp_l_ext": "Kinyerés %d/%d",
    },
    "en": {
        "t_add": "Add files…", "t_remove": "Remove", "t_clear": "Clear list",
        "t_compose": "Build from the selection",
        "t_extract": "Extract checked streams…",
        "t_replace_box": "Build (picture + audio from the checked streams)",
        "t_help": "Load several files (video, audio or raw audio files). Use the checkbox on the left to choose what stays: "
                  "exactly ONE video stream (this is the base file) and ONE audio stream (this goes into the output). If the "
                  "audio comes from another file, the program extracts it internally and swaps the audio track of the base "
                  "file – no raw audio file needed. The picture and all other tracks stay byte-identical. If you check the "
                  "base file's own audio, only the delay applies (positive = plays later, negative = earlier). If the base "
                  "file has several audio tracks, click the one that has to be replaced.",
        "t_nofile": "No file loaded", "t_nothing": "No checked stream that can be extracted.",
        "t_dir": "Folder for the extracted streams", "t_raw": "raw audio",
        "col_stream": "File / stream",
        "col_delay": "Start delay (video / audio)", "t_col_delay": "Start delay",
        "l_ats_seam": "   ATS alignment at the seam: %+.2f ms (so the arrival time does not jump back)",
        "au_l_grow": "The new audio has a higher bitrate: %d extra packets inserted (for %d audio blocks) – other streams unchanged",
        "row_skip": "Skipped (not checked)",
        "cp_novideo": "Check one video stream – it provides the base file.",
        "cp_manyvideo": "Only one video stream can be checked (the base file).",
        "cp_noaudio": "Check one audio stream that stays in the output.",
        "cp_manyaudio": "Only one audio stream can be checked – it goes into the output.",
        "cp_nobaseaudio": "The base file has no audio track that could be replaced (the program cannot add a new track).",
        "cp_whichaudio": "The base file has several audio tracks – click (select in the list) the one to be replaced.",
        "cp_l_plan": "Build: picture = %s | audio = %s",
        "cp_l_same": "The checked audio belongs to the base file: only the delay applies.",
        "cp_l_skip": "   skipped (unsupported or raw): %s",
        "cp_l_ext": "Extracting %d/%d",
    },
}
for _l in _STR:
    _STR[_l].update(_CSTR[_l])

_SSTR = {
    "hu": {
        "col_cont": "Folytatólagos", "col_seam": "Varratminőség",
        "sc_first": "–", "sc_dash": "–",
        "sc_yes": "✓ igen", "sc_probable": "~ valószínű", "sc_no": "nem",
        "sc_size_only": "? csak méret",
        "sc_p_size": "méret: %s", "sc_p_ts": "időbélyegek", "sc_p_mid": "kép közepén indul",
        "sc_p_nokey": "nem I-képpel indul", "sc_p_clock": "óra folytonos",
        "g_perfect": "Tökéletes", "g_good": "Jó", "g_fair": "Elfogadható", "g_poor": "Gyenge",
        "sc_detail": "Varrat az előző fájllal – kép: %s | hang: %s | óra (PCR/SCR): %s | kezdés: %s | előző fájl: %s",
        "sc_d_size": "Előző fájl: %s",
        "sc_v": "%+.2f képkocka", "sc_ms": "%+.1f ms",
        "sc_k_idr": "IDR", "sc_k_rec": "visszaállási pont", "sc_k_none": "nem kulcskocka",
        "sc_k_unk": "ismeretlen",
        "sc_sz": "%.1f MB", "sc_sz_lim": "%.1f MB, korlát: %s",
        "sc_n_vgap": "A kép időzítése %+.2f képkockával tér el a folytatástól (pozitív = hiányzik, "
                     "negatív = átfed): a megosztott fájl nem csatlakozik pontosan, a varratnál képhiba várható.",
        "sc_n_nokey": "Az új rész nem kulcskockával indul, és az időbélyegek sem csatlakoznak az előzőhöz "
                      "– az első képek hibásak lesznek.",
        "sc_n_rec": "Az új rész visszaállási ponttal indul (nem IDR) – az első képkockák hibásak lehetnek.",
        "sc_n_keyunk": "A kulcskocka-kezdés nem ellenőrizhető.",
        "sc_n_mid": "A fájl egy képkocka közepén indul, de nem az előző folytatása – csonka képkocka kerül a varratba.",
        "sc_n_open": "Az új rész nyitott GOP-pal indul – az első 1–2 kép hibás lehet.",
        "sc_n_agap": "Hangrés/átfedés a varratnál: %+.1f ms.",
        "sc_n_pcr": "Az órajel (PCR/SCR) a varratnál %+.1f ms-ot ugrik.",
        "sc_n_sizeonly": "MP4 / MKV fájlnál az időbélyegek fájlonként nulláról indulnak, ezért a folytatás "
                         "csak a méretből sejthető, a varratminőség nem becsülhető.",
        "sc_note_ok": "A varrat hibátlanul illeszkedik.",
        "l_seam": "%d. %s – folytatólagos: %s | varratminőség: %s",
    },
    "en": {
        "col_cont": "Continuation", "col_seam": "Seam quality",
        "sc_first": "–", "sc_dash": "–",
        "sc_yes": "✓ yes", "sc_probable": "~ probable", "sc_no": "no",
        "sc_size_only": "? size only",
        "sc_p_size": "size: %s", "sc_p_ts": "timestamps", "sc_p_mid": "starts mid-frame",
        "sc_p_nokey": "does not start with an I picture", "sc_p_clock": "clock continues",
        "g_perfect": "Perfect", "g_good": "Good", "g_fair": "Fair", "g_poor": "Poor",
        "sc_detail": "Seam with the previous file – picture: %s | audio: %s | clock (PCR/SCR): %s | start: %s | previous file: %s",
        "sc_d_size": "Previous file: %s",
        "sc_v": "%+.2f frames", "sc_ms": "%+.1f ms",
        "sc_k_idr": "IDR", "sc_k_rec": "recovery point", "sc_k_none": "not a key frame",
        "sc_k_unk": "unknown",
        "sc_sz": "%.1f MB", "sc_sz_lim": "%.1f MB, limit: %s",
        "sc_n_vgap": "The picture timing is %+.2f frames off from a seamless continuation (positive = missing, "
                     "negative = overlapping): the split file does not connect exactly, expect a visible glitch at the seam.",
        "sc_n_nokey": "The new part does not start with a key frame and its timestamps do not connect to the "
                      "previous file – the first pictures will be corrupt.",
        "sc_n_rec": "The new part starts at a recovery point (not IDR) – the first frames may be corrupt.",
        "sc_n_keyunk": "The key-frame start cannot be verified.",
        "sc_n_mid": "The file starts in the middle of a frame but is not a continuation of the previous one "
                    "– a truncated frame ends up in the seam.",
        "sc_n_open": "The new part starts with an open GOP – the first 1–2 pictures may be corrupt.",
        "sc_n_agap": "Audio gap/overlap at the seam: %+.1f ms.",
        "sc_n_pcr": "The clock (PCR/SCR) jumps by %+.1f ms at the seam.",
        "sc_n_sizeonly": "In MP4 / MKV files the timestamps restart from zero in every file, so a continuation "
                         "can only be guessed from the size; the seam quality cannot be estimated.",
        "sc_note_ok": "The seam matches perfectly.",
        "l_seam": "%d. %s – continuation: %s | seam quality: %s",
    },
}
for _l in _STR:
    _STR[_l].update(_SSTR[_l])

# ---------------------------------------------- súgó, jogi és licenc szövegek --
# A súgó külön ablakban nyílik (F1 vagy a Súgó gomb). Jelölések a szövegekben:
#   "## cím" fejezetcím, "### cím" alcím, "- " felsorolás,
#   "[E]" / "[W]" ellenőrzési hiba / figyelmeztetés, "[R]" / "[Y]" piros / sárga kompatibilitási jelzés.
# Az "Ellenőrzés" és "Lista és jelzések" fül üzenetlistáit a program a saját üzenet-szövegeiből
# állítja elő (@@VERIFY:..@@ / @@COMPARE@@), így a súgó nem térhet el a tényleges kimenettől.

_LSTR = {
    "hu": {
        "b_help": "Súgó", "help_title": "Súgó –Lossless Video Toolkit", "tab_legal": "Jogi",
        "hl_E": "HIBA", "hl_W": "FIGYELMEZTETÉS", "hl_R": "PIROS", "hl_Y": "SÁRGA",
        "about_text": (
            "Lossless Video Toolkit  v%s\n\n"
            "Veszteségmentes AVCHD (.MTS / .M2TS), MP4 / MOV, MKV / WebM, MPEG-PS (.MPG) és DVD VOB összefűző.\n"
            "Nem kódol újra: a videó- és hangadatot változatlanul másolja, csak az "
            "időbélyegeket és a számlálókat számolja újra, így a hang nem csúszik el.\n\n"
            "Copyright (c) %s %s\n"
            "MIT licenc alatt, lásd a Licenc fület. Jogi tudnivalók: Jogi fül. "
            "Használati útmutató: Súgó gomb vagy F1.\n\n"
            "Soli Deo Gloria"),
        "comp_text": (
            "A program saját, eredeti kód (MIT licenc), és nem tartalmaz harmadik féltől származó kódot, könyvtárat vagy adatfájlt. Több fájlból áll: az összefűző és kinyerő (mts_joiner.py), a vágó és a Smart Cut (lvt_cutter.py, lvt_mp4.py, lvt_smartcut.py, lvt_iframe.py), az FFmpeg-ablak (lvt_ffmpeg.py), a képeffektek és a VapourSynth-támogatás (efekt.py, efekt_vs.py, vs_*.py), valamint az elemző (lvt_analyzer.py).\n\n"
            "Futtatókörnyezet (nem része a programnak, a Python telepítéssel érkezik):\n  • Python és szabványos könyvtára – Python Software Foundation License\n  • Tkinter / Tcl/Tk (grafikus felület) – Tcl/Tk License (BSD-típusú)\n\n"
            "Külső programok és könyvtárak. A program NEM tartalmazza, nem csomagolja és nem tölti le őket; a felhasználó telepíti őket, és rájuk a saját licencük vonatkozik, nem a program MIT-licence:\n  • FFmpeg, ffprobe, ffplay – a Smart Cut, az FFmpeg-ablak, a képeffektek és az elemző külső ellenőrzése használja. Csak különálló programként, parancssorból indul. A licenc a buildtől függően LGPL vagy GPL: https://ffmpeg.org/legal.html\n  • VapourSynth (vspipe), pluginjai és Python-szkriptjei (pl. havsfunc, QTGMC és függőségei) – csak akkor, ha a felhasználó bekapcsolja a VapourSynth-támogatást. A program a felhasználó által megadott mappából tölti be őket, nem másolja és nem módosítja. A pluginok licencei eltérők. A pluginok és Python-modulok vizsgálata idegen kódot futtat, ezért csak megbízható mappát vizsgálj.\n  • Pillow (PIL) – nem kötelező; ha telepítve van, a képeffektek előnézete használja (HPND licenc).\n\n"
            "Ha a programot Python nélkül, becsomagolt (pl. PyInstaller-es) formában terjeszted, a csomagba kerülő futtatókörnyezet licencszövegeit is mellékelned kell (a Python licence és a benne lévő komponensek – pl. zlib, Tcl/Tk – saját licencei; ezek a Python telepítésének LICENSE.txt fájljában találhatók). Forráskódként (.py) terjesztve erre nincs szükség. Az FFmpeg-et és a VapourSynth-et ne csomagold a programhoz, hacsak azok licencfeltételeit külön, önállóan nem teljesíted.\n\n"
            "Nyilvános specifikációk, amelyek alapján az összefűző és kinyerő kódja készült (kód nem lett átvéve):\n  • ISO/IEC 13818-1 | ITU-T H.222.0 – MPEG-2 Transport Stream és Program Stream\n  • ISO/IEC 11172-1/-2/-3 és 13818-2 – MPEG-1/2 rendszer-, videó- és hangfejlécek\n  • DVD-Video fájlok (VOB, NAV-csomag) nyilvánosan dokumentált szerkezete\n  • ISO/IEC 14496-12 – ISO Base Media File Format (MP4/MOV)\n  • RFC 8794 (EBML), RFC 9559 (Matroska / WebM)\n  • ITU-T H.264 – az SPS (profil, felbontás) beolvasása\n  • ATSC A/52 – az AC-3 fejléc beolvasása\n\n"
            "Nem használt és nem mellékelt programok: eac3to, tsMuxeR. A korábbi batch-megoldás az eac3to-ra és a tsMuxeR-re épült; ez a program önálló, ezek licencei rá nem vonatkoznak.\n\n"
            "Az összefűző és a kinyerő nem dekódol és nem kódol: az adatfolyam csomagjait változatlanul másolja. A külső FFmpeg-et használó modulok (pl. Smart Cut, FFmpeg-ablak) kódolhatnak és dekódolhatnak, de ezt maga az FFmpeg végzi, különálló programként.\n\n"
            "Idézett szöveg (nem kód): a programban egy rövid bibliai idézet szerepel a forrás megjelölésével – magyarul Károli Gáspár fordításából (közkincs), angolul a King James Version-ből (köztulajdon). Ezekre a szövegekre nem a program MIT-licence vonatkozik."
        ),
        "legal_text": (
            "JOGI TUDNIVALÓK\n\n"
            "Szerzői jog és licenc\nAz Lossless Video Toolkit 1.0 v%s szerzői jogi tulajdonosa: %s (Copyright (c) %s %s). A program az MIT licenc alatt szabadon használható, másolható, módosítható és terjeszthető. A licenc teljes szövegét – a szerzői jogi megjegyzéssel együtt – minden másolathoz vagy lényeges részéhez mellékelni kell (lásd a Licenc fület).\n\n"
            "Garancia és felelősség\nA program „ahogy van” (AS IS) készült, kifejezett vagy hallgatólagos garancia nélkül. A szerző nem felel a program használatából eredő kárért vagy adatvesztésért. A program úgy készült, hogy a forrásfájlokat ne módosítsa, a kimenetet pedig új fájlba írja – fontos felvételekről ettől függetlenül mindig tarts másolatot.\n\n"
            "Tartalom és jogosultság\nA programot csak olyan felvételekkel használd, amelyekhez jogod van (saját felvétel, vagy a jogtulajdonos engedélye). A program nem kerüli meg a másolásvédelmet és nem fejt vissza titkosítást: a titkosított / másolásvédett tartalmat elutasítja (pl. DRM-es MP4-sáv, titkosított MPEG-PS). A felhasználó felel azért, hogy a használata megfeleljen a hatályos jogszabályoknak és a jogtulajdonosok feltételeinek.\n\n"
            "Szabványok és szabadalmak\nAz összefűző és a kinyerő saját kód, nyilvános műszaki specifikációk alapján készült (lásd a Komponensek fület); nem kódol és nem dekódol videót vagy hangot, csak az adatfolyam csomagjait másolja, és az időbélyegeket, számlálókat írja át. A Smart Cut, az FFmpeg-ablak, a képeffektek és az elemző külső FFmpeg-et indíthat, amely kódol és dekódol. A videó- és hangkodekekhez (pl. H.264/AVC, MPEG-2, AC-3) kapcsolódó szabadalmi és licenckérdések jellemzően a kodeket megvalósító termékek gyártóit és használóit érintik. Ha a programot kereskedelmi termék részeként terjeszted, kérj jogi tanácsot.\n\n"
            "Idézett szöveg\nA programban egy rövid bibliai idézet is szerepel a forrás megjelölésével. A magyar szöveg Károli Gáspár fordítása (közkincs), az angol a King James Version (köztulajdon). Az idézett szövegekre nem a program MIT-licence vonatkozik: jogaik a megfelelő jogtulajdonosokat illetik.\n\n"
            "Védjegyek\nAz AVCHD a Panasonic Corporation és a Sony Corporation védjegye. A programban említett egyéb terméknevek, formátumnevek és védjegyek (pl. Dolby, DVD, MPEG, Matroska, Python, FFmpeg, VapourSynth, StaxRip) a jogos tulajdonosaiké. Említésük kizárólag a kompatibilitás megjelölésére szolgál; a programnak nincs kapcsolata e tulajdonosokkal, és ők nem támogatják vagy hagyják jóvá.\n\n"
            "Adatkezelés\nA program maga nem kezdeményez hálózati kapcsolatot, és nem gyűjt, nem küld adatot. Egyetlen helyen nyit külső hivatkozást: az FFmpeg-licencablak „Licenc megnyitása a böngészőben” gombja az alapértelmezett böngészőben megnyitja az ffmpeg.org/legal.html oldalt.\nHelyben, a gépeden ezeket írja: ~/.mts_joiner.cfg (a kiválasztott nyelv kódja); ~/.lvt_ffmpeg.json (az FFmpeg-modul beállításai: az ffmpeg / ffprobe / ffplay útvonala, mentett minták); ~/.lossless_video_toolkit (ikon-gyorsítótár); ~/efekt_vs_lanc (a VapourSynth-szűrőlánc generált szkriptjei és gyorsítótára); a program mappájában az efekt_naplo.txt diagnosztikai napló (fájl- és mappaneveket, útvonalakat tartalmazhat; sehova nem küldi el), és a lvt_ffmpeg_licenc.txt jelzőfájl (az FFmpeg-figyelmeztetés elfogadását jelzi); az operációs rendszer ideiglenes mappájában lvt_ előtagú ideiglenes fájlokat, amelyeket használat után igyekszik törölni.\n\n"
            "Ez a tájékoztató nem minősül jogi tanácsnak."
        ),
    },
    "en": {
        "b_help": "Help", "help_title": "Help – Lossless Video Toolkit 1.0", "tab_legal": "Legal",
        "hl_E": "ERROR", "hl_W": "WARNING", "hl_R": "RED", "hl_Y": "YELLOW",
        "about_text": (
            "Lossless Video Toolkit v%s\n\n"
            "Lossless joiner for AVCHD (.MTS / .M2TS), MP4 / MOV, MKV / WebM, MPEG-PS (.MPG) and DVD VOB files.\n"
            "It does not re-encode: video and audio data are copied unchanged, only the timestamps "
            "and counters are recalculated, so the audio does not drift.\n\n"
            "Copyright (c) %s %s\n"
            "Released under the MIT License, see the License tab. Legal notes: Legal tab. "
            "User guide: Help button or F1.\n\n"
            "Soli Deo Gloria"),
        "comp_text": (
            "The program is original code (MIT License) and contains no third-party code, libraries or data files. It consists of several files: the joiner / extractor (mts_joiner.py), the cutter and Smart Cut (lvt_cutter.py, lvt_mp4.py, lvt_smartcut.py, lvt_iframe.py), the FFmpeg window (lvt_ffmpeg.py), the image effects and VapourSynth support (efekt.py, efekt_vs.py, vs_*.py) and the analyzer (lvt_analyzer.py).\n\n"
            "Runtime (not part of the program, supplied by the Python installation):\n  • Python and its standard library – Python Software Foundation License\n  • Tkinter / Tcl/Tk (graphical interface) – Tcl/Tk License (BSD-style)\n\n"
            "External programs and libraries. The program does NOT include, bundle or download them; the user installs them, and they are covered by their own licenses, not by this program's MIT License:\n  • FFmpeg, ffprobe, ffplay – used by Smart Cut, the FFmpeg window, the image effects and the analyzer's external check. They are only started as separate command-line programs. The license is LGPL or GPL depending on the build: https://ffmpeg.org/legal.html\n  • VapourSynth (vspipe), its plugins and Python scripts (e.g. havsfunc, QTGMC and its dependencies) – only if the user turns on VapourSynth support. The program loads them from the folder the user specifies and does not copy or modify them. Plugin licenses differ. Scanning plugins and Python modules runs third-party code, so scan only trusted folders.\n  • Pillow (PIL) – optional; if installed, the image-effects preview uses it (HPND license).\n\n"
            "If you distribute the program bundled without a separate Python (e.g. built with PyInstaller), you must also include the license texts of the bundled runtime (the Python license and the licenses of its components, e.g. zlib and Tcl/Tk – they are in the LICENSE.txt of your Python installation). Distributing the plain source (.py) does not require this. Do not bundle FFmpeg or VapourSynth with the program unless you separately fulfil their license terms.\n\n"
            "Public specifications the joiner / extractor code was written from (no code was copied):\n  • ISO/IEC 13818-1 | ITU-T H.222.0 – MPEG-2 Transport Stream and Program Stream\n  • ISO/IEC 11172-1/-2/-3 and 13818-2 – MPEG-1/2 system, video and audio headers\n  • Publicly documented structure of DVD-Video files (VOB, NAV packs)\n  • ISO/IEC 14496-12 – ISO Base Media File Format (MP4/MOV)\n  • RFC 8794 (EBML), RFC 9559 (Matroska / WebM)\n  • ITU-T H.264 – reading the SPS (profile, resolution)\n  • ATSC A/52 – reading the AC-3 header\n\n"
            "Not used and not included: eac3to, tsMuxeR. The earlier batch solution was built on eac3to and tsMuxeR; this program is self-contained and their licenses do not apply to it.\n\n"
            "The joiner and the extractor neither decode nor encode: they copy the packets of the stream unchanged. The modules that use the external FFmpeg (e.g. Smart Cut, the FFmpeg window) may encode and decode, but that is done by FFmpeg itself, as a separate program.\n\n"
            "Quoted text (not code): the program contains one short Bible quotation with its source indicated – in Hungarian a short quotation from the Károli Gáspár translation (public domain), in English the King James Version (public domain). These texts are not covered by the program's MIT License."
        ),
        "legal_text": (
            "LEGAL NOTES\n\n"
            "Copyright and license\nLossless Video Toolkit v%s is copyright of %s (Copyright (c) %s %s). It is released under the MIT License: you may use, copy, modify and distribute it freely. The full license text – together with the copyright notice – must be included with every copy or substantial portion of the software (see the License tab).\n\n"
            "Warranty and liability\nThe software is provided \"AS IS\", without warranty of any kind, express or implied. The author is not liable for any damage or data loss arising from its use. The program is designed not to modify your source files and to write the result to a new file – still, always keep a copy of important recordings.\n\n"
            "Content and rights\nUse the program only with recordings you have the right to use (your own recordings, or with the permission of the rights holder). The program does not circumvent copy protection and does not decrypt anything: encrypted / copy-protected content is rejected (e.g. a DRM-protected MP4 track, encrypted MPEG-PS). You are responsible for ensuring that your use complies with applicable law and with the terms of the rights holders.\n\n"
            "Standards and patents\nThe joiner and the extractor are original code written from public technical specifications (see the Components tab); they neither encode nor decode video or audio, they only copy the packets of the stream and rewrite timestamps and counters. Smart Cut, the FFmpeg window, the image effects and the analyzer may start an external FFmpeg, which does encode and decode. Patent and licensing questions about video and audio codecs (e.g. H.264/AVC, MPEG-2, AC-3) typically concern the makers and users of products that implement those codecs. If you distribute the program as part of a commercial product, seek legal advice.\n\n"
            "Quoted text\nThe program also contains one short Bible quotation, with its source indicated. The Hungarian text is a short quotation from the Károli Gáspár translation (public domain), the English one is from the King James Version (public domain). The quoted texts are not covered by the program's MIT License: their rights belong to the respective rights holders.\n\n"
            "Trademarks\nAVCHD is a trademark of Panasonic Corporation and Sony Corporation. Other product names, format names and trademarks mentioned in the program (e.g. Dolby, DVD, MPEG, Matroska, Python, FFmpeg, VapourSynth, StaxRip) belong to their respective owners. They are mentioned only to indicate compatibility; the program is not affiliated with, endorsed or approved by these owners.\n\n"
            "Privacy\nThe program itself initiates no network connections and collects or sends no data. It opens an external link in one place only: the \"Open license in browser\" button of the FFmpeg license window opens ffmpeg.org/legal.html in your default browser.\nIt writes these files locally, on your computer: ~/.mts_joiner.cfg (the selected language code); ~/.lvt_ffmpeg.json (settings of the FFmpeg module: the paths of ffmpeg / ffprobe / ffplay, saved presets); ~/.lossless_video_toolkit (icon cache); ~/efekt_vs_lanc (generated scripts and cache of the VapourSynth filter chain); in the program folder the efekt_naplo.txt diagnostic log (it may contain file names, folder names and paths; it is never sent anywhere) and the lvt_ffmpeg_licenc.txt marker file (it records that the FFmpeg notice was accepted); and temporary files with the lvt_ prefix in the operating system's temp folder, which it tries to delete after use.\n\n"
            "This notice is not legal advice."
        ),
    },
}
for _l in _STR:
    _STR[_l].update(_LSTR[_l])

_SHORTSTR = {
    "hu": {"s_pend": "Elemzés…", "s_err": "Hiba", "s_ref": "Referencia", "s_ok": "Kompatibilis",
           "s_warn": "Figyelmeztetés", "s_bad": "Nem fűzhető"},
    "en": {"s_pend": "Analyzing…", "s_err": "Error", "s_ref": "Reference", "s_ok": "Compatible",
           "s_warn": "Warning", "s_bad": "Cannot be joined"},
}
for _l in _STR:
    _STR[_l].update(_SHORTSTR[_l])

_FMT_NAMES = {"ts": "AVCHD / MPEG-TS (.mts .m2ts .ts)", "mp4": "MP4 / MOV (.mp4 .m4v .mov)",
              "mkv": "Matroska / WebM (.mkv .webm .mka)", "ps": "MPEG-PS / DVD VOB (.mpg .mpeg .mod .vob)"}

# A kategóriák: (cím, magyarázat) – a [E] / [W] a lenti üzenetek súlyára utal.
_VCAT = {
    "hu": {
        "struct": ("Szerkezet", "Az összefűzött fájl alapfelépítése: szinkronbájtok, fájl- és dobozméretek, fejlécek, elemszámok. Hiba itt sérült vagy megszakadt írásra (pl. elfogyott a hely), vagy sérült forrásra utal. Teendő: ismételd meg az összefűzést, ellenőrizd a szabad helyet és a forrásfájlok épségét (pl. másold újra őket a kártyáról)."),
        "cc": ("Continuity counter (folytonosság)", "A TS-csomagok számlálója. A varratnál mért hiba [E] kiesett vagy ismétlődő csomagot jelent, ami látható vagy hallható hibát okozhat. A „forrásban is megvolt” [W] azt jelenti, hogy a forrásfájl már eleve sérült volt ezen a ponton, nem az összefűzés okozta."),
        "pcr": ("PCR óra", "A lejátszó órajele. A varratnál jelzés nélküli ugrás [E] megakaszthat egyes lejátszókat; a jelzett, nagy vagy forrásbeli ugrások [W] általában ártalmatlanok."),
        "ats": ("ATS (érkezési idő)", "Az M2TS-csomagok 4 bájtos érkezési időbélyege. Az eltérés csak figyelmeztetés, a lejátszók ritkán érzékenyek rá."),
        "scr": ("SCR óra (MPEG-PS)", "A Program Stream órajele. A varratnál mért ugrás csak figyelmeztetés (a lejátszók az időbélyegekből szinkronizálnak). Hiba [E], ha az első csomag órája nem a forrás + tervezett eltolás."),
        "vts": ("Videó időzítés", "A képkockák időbélyegei. Jó eredmény: minden kép pontosan egy képkockányi lépéssel követi az előzőt, és a teljes hossz egyezik a források hosszával. A varratnál mért ugrás [E] kihagyott vagy ismétlődő képet, vagyis rángatást jelent. Teendő: ellenőrizd a fájlok sorrendjét, és hogy nem hiányzik-e egy fájl a sorozatból."),
        "vseam": ("Videó varratok (kulcskocka)", "A következő rész kezdése. Önálló klipnél tiszta kulcskockával (H.264: IDR, MPEG-PS: I-kép) kell indulnia, különben az első képek hibásak lehetnek. Folytatólagos (megosztott) fájlnál ez nem hiba: a GOP az előző fájlból folytatódik, ezért ott a program nem jelez."),
        "pset": ("SPS/PPS a kulcskockák előtt", "H.264-nél a dekódolónak minden kulcskocka előtt szüksége van a paraméterkészletekre (SPS/PPS). A program a hiányzókat pótolja; hibát [E] csak akkor ad, ha a pótlás nem sikerült."),
        "audio": ("Hang", "A hangkeretek épsége és a varratnál mért hangrés/átfedés. Fél hangkeretnyi eltérés még rendben van; nagyobb [W] rövid csendet vagy pattanást okozhat, a szinkron ettől még megmarad. Több mint 1 s hiány [E]: a hang jelentős része hiányzik. A CRC-hiba [E] sérült AC-3 keretet jelent (kattogás)."),
        "sync": ("A/V szinkron", "A hang a képhez képest ugyanazon az időrácson marad-e, mint az eredeti fájlban. Eltérés [E] = a hang elcsúszott. Teendő: nézd meg, megvolt-e a hiba a forrásban is."),
        "data": ("Adatintegritás", "A kép- és hangadat bájtra azonos-e a forrásokéval (CRC32, darabonkénti összevetés). Bármely eltérés [E] másolási/írási hibára vagy a háttértár hibájára utal."),
        "index": ("Index (MKV)", "A gyors keresést szolgáló SeekHead és Cues. Hiányuk [W] csak lassabb megnyitást/keresést jelent; rossz mutató [E] hibás fájlt."),
        "tables": ("Mintatáblák (MP4)", "Az MP4-konténer táblái (mintaszám, kulcskocka-lista, adatdarabok). Hiba [E] esetén a fájl nem lenne helyesen lejátszható."),
        "nav": ("NAV-csomagok (DVD VOB)", "A DVD navigációs csomagjainak óra- és szektorcím-mezői. Ha nem a tervezett módon változtak [E], a DVD-lejátszó eltévedhet a keresésnél."),
        "other": ("Kép és többi sáv", "Minden, aminek változatlannak kell maradnia: a nem cserélt sávok adata és időzítése bájtra azonos a forrással."),
        "pts": ("Időzítés", "A hangblokkok időbélyegeinek az eredeti + megadott késleltetés értékeknek kell lenniük, és növekvő sorrendben kell követniük egymást."),
    },
    "en": {
        "struct": ("Structure", "The basic layout of the joined file: sync bytes, file and box sizes, headers, element counts. An error here points to an interrupted write (e.g. the disk ran out of space) or to a damaged source. What to do: repeat the join, check the free space and the integrity of the source files (e.g. copy them again from the card)."),
        "cc": ("Continuity counter", "The counter of the TS packets. An error at a seam [E] means a packet was lost or repeated, which can cause visible or audible glitches. \"Also present in the source\" [W] means the source file was already damaged at that point; the join did not cause it."),
        "pcr": ("PCR clock", "The player's clock reference. An unflagged jump at a seam [E] can stall some players; flagged, large or source-side jumps [W] are usually harmless."),
        "ats": ("ATS (arrival time)", "The 4-byte arrival timestamp of M2TS packets. A deviation is only a warning; players are rarely sensitive to it."),
        "scr": ("SCR clock (MPEG-PS)", "The clock of the Program Stream. A jump at a seam is only a warning (players synchronize from the timestamps). It is an error [E] if the clock of the first pack is not the source + the planned offset."),
        "vts": ("Video timing", "The timestamps of the frames. A good result: every picture follows the previous one by exactly one frame step, and the total length matches the sources. A jump at a seam [E] means a skipped or repeated picture, i.e. judder. What to do: check the order of the files and that no file is missing from the series."),
        "vseam": ("Video seams (key frame)", "How the next part starts. A separate clip must start with a clean key frame (H.264: IDR, MPEG-PS: I picture), otherwise the first pictures may be corrupt. For a continuation (split) file this is not an error: the GOP continues from the previous file, so no warning is given there."),
        "pset": ("SPS/PPS before key frames", "In H.264 the decoder needs the parameter sets (SPS/PPS) before every key frame. The program inserts missing ones; it reports an error [E] only if that was not possible."),
        "audio": ("Audio", "Integrity of the audio frames and the audio gap/overlap at the seams. Up to half an audio frame is fine; more [W] can cause a short silence or a click, but sync is kept. A gap of more than 1 s [E] means a large part of the audio is missing. A CRC error [E] means a damaged AC-3 frame (crackling)."),
        "sync": ("A/V sync", "Whether the audio stays on the same time grid relative to the picture as in the original file. A deviation [E] = the audio has drifted. What to do: check whether the problem was already present in the source."),
        "data": ("Data integrity", "Whether picture and audio data are byte-identical to the sources (CRC32, piece-by-piece comparison). Any deviation [E] points to a copy/write error or a storage fault."),
        "index": ("Index (MKV)", "SeekHead and Cues, used for fast seeking. Their absence [W] only means slower opening/seeking; a wrong pointer [E] means a defective file."),
        "tables": ("Sample tables (MP4)", "The tables of the MP4 container (sample counts, key-frame list, data chunks). An error [E] means the file would not play back correctly."),
        "nav": ("NAV packs (DVD VOB)", "The clock and sector-address fields of the DVD navigation packs. If they did not change as planned [E], a DVD player may get lost when seeking."),
        "other": ("Picture and other tracks", "Everything that must stay unchanged: data and timing of the tracks that were not replaced are byte-identical to the source."),
        "pts": ("Timing", "The timestamps of the audio blocks must equal the original + the given delay, and must be in increasing order."),
    },
}

_HELP = {
    "hu": [
        ("Első lépések", """## Mire való a program?
Az Lossless Video Toolkit 1.0 több videófájlt fűz össze egyetlen folyamatos fájllá újrakódolás nélkül. Tipikus eset: a kamera a hosszú felvételt a fájlrendszer méretkorlátja miatt (pl. 4 GB) több fájlra darabolta, és ezeket szeretnéd visszaegyesíteni. A kép- és hangadat bájtra azonosan másolódik, ezért nincs minőségromlás; a program csak az időbélyegeket és a számlálókat számolja újra, hogy a lejátszó egyetlen folyamatos felvételnek lássa.

## Támogatott formátumok
- AVCHD / MPEG-TS: .mts, .m2ts, .ts – a legteljesebb támogatás (H.264 videó, AC-3 hang)
- MP4 / MOV: .mp4, .m4v, .mov
- Matroska / WebM: .mkv, .webm, .mka
- MPEG Program Stream és DVD VOB: .mpg, .mpeg, .mod, .vob
Egy összefűzésben csak azonos típusú és azonos beállítású fájlok szerepelhetnek: .mts nem fűzhető .mp4-hez, és a más felbontású vagy más hangformátumú fájlt a program elutasítja (nem alakít át semmit).

## Összefűzés lépésről lépésre
- 1. Add hozzá a fájlokat: „Fájlok hozzáadása…” vagy „Mappa hozzáadása…”. Több fájl egyszerre is kijelölhető.
- 2. Ellenőrizd a sorrendet. A program a lista sorrendjében fűz. A ▲ Fel / ▼ Le gombokkal mozgathatod a kijelölt sorokat; a „Névsorba” fájlnév szerint rendez (a kamerák számozott fájlneveinél ez általában a helyes időrend).
- 3. Szükség esetén kapcsold ki az egyes fájlokat: az első oszlopban (☑ / ☐) kattintva a sor kimarad az összefűzésből. Az első bejelölt fájl a referencia, a többit ehhez hasonlítja a program.
- 4. Nézd meg az Állapot oszlopot: zöld = rendben, sárga = figyelmeztetés, piros = nem illeszthető (ekkor az indítás le van tiltva). Részletek: „Lista és jelzések” fül.
- 5. Add meg a kimeneti fájlt (alapértelmezés: osszefuzott.<kiterjesztés> az első fájl mappájában), majd kattints az „Összefűzés indítása” gombra.
- 6. Várd meg a végét. Az összefűzés után a program automatikusan ellenőrzi a kész fájlt; az eredmény a naplóban jelenik meg (lásd „Ellenőrzés” fül). A „Megszakítás” gomb bármikor leállítja a műveletet.

## Biztonság, hely, fájlnevek
- A forrásfájlokat a program csak olvassa, soha nem módosítja.
- A kimenet először <név>.part néven készül, és csak az ellenőrzés után kapja meg a végleges nevét. Ha az ellenőrzés hibát talál, a fájl <név>_HIBAS.<kiterjesztés> néven megmarad vizsgálatra, de ne használd végleges fájlként.
- Ha a kimeneti fájl már létezik, a program rákérdez a felülírásra. A kimenet nem lehet azonos egyik bemeneti fájllal sem.
- A kimeneti meghajtón a források összméreténél legalább 50 MB-tal több szabad helynek kell lennie. A kimenet mérete lényegében a források méretének összege.
- Fontos felvételekről ettől függetlenül mindig tarts másolatot."""),

        ("Lista és jelzések", """## Az oszlopok
- ✓ # – bejelölés (☑ / ☐) és sorszám. Kattintással ki-be kapcsolható.
- Fájl, Hossz, MB – a fájl neve, a felvétel hossza és a fájl mérete.
- Videó, Hang – a felismert kodek és főbb paraméterek.
- Késleltetés (kép / hang) – az első képkocka és az első hangminta kezdési ideje a legkorábban induló folyamhoz képest, ms-ban. Pl. „0 / +40” = a hang 40 ms-mal később indul, mint a kép. Ez a fájl saját időzítése, nem hiba.
- Folytatólagos, Varratminőség – lásd a „Folytatólagos fájlok” fület.
- Állapot – a kompatibilitás eredménye (lásd lent). Egy sor kijelölésekor a lista alatt részletes leírás jelenik meg a varratról is.

## Állapot: zöld, sárga, piros
Az összehasonlítás a referenciához (az első bejelölt fájlhoz) történik.
- Zöld – „Kompatibilis”: a fájl illeszthető.
- Sárga – „Figyelem: …”: illeszthető, de van különbség, amit érdemes tudni. Az indítás engedélyezett.
- Piros – „Nem illeszthető: …”: a fájl nem fűzhető a referenciához. Amíg van ilyen sor, az indítás le van tiltva: kapcsold ki vagy távolítsd el a sort, vagy tedd első helyre azt a fájlt, amelyhez a többit igazítani akarod.
- Szürke – „Kihagyva”: nincs bejelölve; „Elemzés…”: a fájl elemzése még folyik; „Referencia (első fájl)”: ez a viszonyítási alap.
- „Hiba: …”: a fájl nem olvasható (pl. sérült, vagy nem támogatott típus).

## Mi okoz piros vagy sárga jelzést?
Ha a konténer típusa eltér (pl. .mts és .mp4 együtt), az mindig piros.
@@COMPARE@@"""),

        ("Folytatólagos fájlok", """## Mi az a folytatólagos fájl?
A kamerák a fájlrendszer méretkorlátjánál (FAT32: 4 GiB, régebbi gépeknél 2 GiB; DVD VOB: 1 GiB) egy hosszú felvételt több fájlra vágnak. A következő fájl ilyenkor az előző FOLYTATÁSA: az órák (PTS/DTS, PCR, ATS, SCR) nem indulnak újra, hanem pontosan ott folytatódnak, ahol az előző fájl véget ért, és a fájl gyakran egy képkocka közepén kezdődik. Az ilyen fájlpár összefűzése a legbiztosabb eset, ezért a program külön jelzi.

## A „Folytatólagos” oszlop
Minden sort az előző bejelölt fájlhoz hasonlít (a sorrend és a bejelölés számít: átrendezéskor vagy kikapcsoláskor újraszámolódik). A döntés a fájlméret és az időbélyegek alapján készül:
- ✓ igen – az előző fájl mérete közvetlenül egy ismert korlát alatt van (vagy a fájl kép közepén indul, vagy az óra folytonos), ÉS az első kép ideje pontosan az előző fájl vége. A zárójel mutatja, mi igazolta: méret, időbélyegek, kép közepén indul.
- ~ valószínű – csak az időbélyegek csatlakoznak (de a méret nem korlát közeli), vagy a méret korlát közeli, de az idő nem csatlakozik pontosan (pl. kimaradt képkockák).
- nem – önálló klip (nem az előző folytatása). Ez nem hiba: külön felvételek is összefűzhetők.
- ? csak méret – MP4 / MKV fájlnál az időbélyegek fájlonként nulláról indulnak, ezért csak a méretből sejthető a folytatás; a varratminőség ilyenkor nem becsülhető („–”).
- – az első fájl, nincs előzője.

### Mit tekint a program méretkorlátnak és „pontos” időnek?
- Méretkorlátok: 1 GiB, 2 GB, 2 GiB, 4 GB, 4 GiB – a fájl mérete a korlát alatt legfeljebb 16 MiB-tal vagy 1,5%-kal lehet (amelyik nagyobb). A lista a forráskód elején a SPLIT_LIMITS konstansban bővíthető.
- Pontos időcsatlakozás: TS-nél az első kép ideje legfeljebb 2 óraütemnyire (kb. 22 µs) van az előző fájl végétől; MPEG-PS-nél negyed képkockányira. „Közel”: legfeljebb 4 képkockányira.
- Folytonos óra: a PCR / ATS / SCR értéke 200 ms-on belül folytatódik az előző fájl végétől.

## A „Varratminőség” oszlop
0–100 pont: mennyire illeszkedik a kép, a hang és az óra az előző fájllal való határon (a varraton). Az érték az elemzett adatokból készül még az összefűzés előtt; az összefűzés utáni ellenőrzés ugyanezt méri a kész fájlon.
- ✓ Tökéletes (95–100): nincs észrevehető hiba.
- ✓ Jó (80–94): kisebb, általában nem hallható/látható eltérés.
- ! Elfogadható (55–79): észrevehető lehet; nézd meg a részleteket (kijelölt sor alatt).
- ✗ Gyenge (0–54): várható képhiba, rángatás vagy hanghiba a varratnál.

### Pontlevonások (100-ból)
- Folytatás, de a kép időzítése nem pontos (kimaradt vagy ismétlődő képkockák): −60.
- Önálló klip, de nem kulcskockával indul: −60 (nem tisztán, visszaállási ponttal: −5; nem ellenőrizhető: −10).
- Önálló klip, amely kép közepén indul: −30 (csonka képkocka kerülne a varratba).
- Hangrés vagy átfedés: kb. fél hangkeretig 0; egy hangkeretig −8; 250 ms-ig −20; 1 s-ig −35; fölötte −60.
- Folytatásnál az óra (PCR / SCR) 0–120 ms tartományon kívül ugrik: −5.
- Önálló MPEG-PS klip nyitott GOP-pal indul: −10.

Fontos: az érték előzetes becslés. A végső szó az összefűzés utáni ellenőrzésé (lásd „Ellenőrzés” fül), de a két érték a gyakorlatban egyezik. Önálló klipek között a „nem” és a „Tökéletes” együtt is előfordulhat: az azt jelenti, hogy nem folytatás, de tisztán illeszkedik."""),

        ("Ellenőrzés", """## Mit csinál az ellenőrzés?
Az összefűzés után a program visszaolvassa a kész fájlt, és három menetben összeveti a forrásokkal (a naplóban „1/3, 2/3, 3/3” jelzi). A naplóban megjelenő „Amit ellenőrzök” lista megmutatja, melyik vizsgálat mire vonatkozik (lent formátumonként olvasható). Az eltérések két súlyúak:
[E] A kimenet nem használható megbízhatóan. A fájl nem kapja meg a végleges nevét: <név>_HIBAS.<kiterjesztés> néven megmarad vizsgálatra, és a program hibát jelez.
[W] A fájl használható, de van észrevehető vagy jelzésértékű eltérés. Sok figyelmeztetés a forrásból ered („a forrásban is megvolt”): ilyenkor nem az összefűzés okozta, hanem a kamera felvétele vagy a forrás sérülése.

## A végeredmény
- ELLENŐRZÉS: TÖKÉLETES – nincs hiba, nincs figyelmeztetés.
- ELLENŐRZÉS: használható – csak figyelmeztetések vannak, hiba nincs. Olvasd el őket, és játszd le a varratok környékét.
- ELLENŐRZÉS: HIBÁS – legalább egy hiba van; a kimenet nincs elfogadva (_HIBAS fájl).
Az ellenőrzést a parancssori --no-verify kapcsolóval ki lehet hagyni, de ez nem ajánlott.

## A varratok sora a naplóban
Példa: „3. varrat @ …: kép +0,0 ms | hang +3,2 ms | PCR +40,0 ms | tiszta IDR-kezdés”
- kép – a videó időzítési ugrása a varratnál. Helyes érték: 0 (a következő kép pontosan egy képkockányi lépéssel követi az előzőt). Eltérés = rángatás vagy kihagyott / ismétlődő kép.
- hang – hangrés (+) vagy átfedés (−) a varratnál. Fél hangkeretnyi (AC-3: kb. 16 ms) még rendben van; nagyobb eltérésnél rövid csend vagy pattanás lehet, de a szinkron megmarad.
- PCR – a lejátszó órajelének ugrása a varratnál. Normális a pár tíz ms.
- Az utolsó mező: „tiszta IDR-kezdés” (az új rész teljes képpel indul), „folytatólagos (megosztott fájl)” (az új rész ugyanannak a felvételnek a folytatása, ezért nem kell teljes képpel indulnia), „IDR nem ellenőrizhető” (nem H.264).

## Az üzenetek jelentése formátumonként
Az alábbi listák a program tényleges üzeneteiből készülnek. A „N” szám, az „x” érték, a „…” pedig a helyet vagy a nevet jelöli, amit a program a konkrét esetben beír.
@@VERIFY:ts@@
@@VERIFY:ps@@
@@VERIFY:mp4@@
@@VERIFY:mkv@@"""),

        ("Hang / stream eszközök", """## Mire jó a második fül?
A „Hang / stream eszközök” fülön folyamokat (képet, hangot) nyerhetsz ki egy fájlból, a hangot kicserélheted, vagy csak a hang időzítését tolhatod el. A kép és a többi sáv bájtra azonos marad. Támogatott: TS / M2TS, MP4 / MOV és MKV.

## Használat
- Töltsd be a fájlokat (videót, hangot vagy nyers hangfájlt). A listában a folyamok kodekje és állapota látszik („kezelhető” / „nem támogatott”).
- Kinyerés: jelöld ki a folyamokat, és kattints a „Kijelölt folyamok kinyerése…” gombra.
- Hangcsere: a bal oldali jelölőnégyzettel jelöld ki, mi marad: pontosan EGY képfolyam (az alapfájl) és EGY hangfolyam (ez kerül a kimenetbe). Ha a hang másik fájlból van, a program belül kinyeri és kicseréli az alapfájl hangsávját – nyers hangfájl nem kell. Több hangsávos alapfájlnál kattints arra a hangsávra, amelyiket cserélni kell.
- Ha az alapfájl saját hangját jelölöd ki, csak a késleltetés érvényesül.
- Késleltetés (ms): pozitív = a hang később szól, negatív = korábban; 1 ms-os lépésekkel állítható (gombok: ±1, ±10, ±100), a kijelölt hangsávra vonatkozik.

## Szinkron-figyelmeztetések
Hangcserénél a program összeveti az új és a régi hang hosszát, kerethosszát és kódolását, és figyelmeztet a szinkron kockázataira (a szövegek „SZINKRON:” kezdetűek, mindegyik megmondja az okot és a javítást):
- Kódolói előfutás (AAC, MP3, Opus): újrakódolt hang jellemzően néhány ms-ot eltolódik; a program a javasolt késleltetést is megadja.
- Hosszkülönbség legfeljebb 1 keret: jellemzően kerekítés vagy előfutás a hang végén.
- Hosszkülönbség több mint 1 keret: a szerkesztőben vágtál, töröltél vagy beszúrtál; a hang közepén vágás után a hang elcsúszik, ezt csak újraexportálással lehet javítani.
- Súlyos szinkron-kockázat: az új hang hossza jelentősen eltér, valószínűleg nem ugyanaz a hang.
- „A régi hangsáv kodekje ismeretlen”: a korábbi összefűzések varratainak időugrásait nem lehet megőrizni.
A program hangot nem dekódol, ezért a hullámformát nem hasonlítja össze: a kész fájlt mindig érdemes egy hangos eseménynél (taps, ütés) az elején, a közepén és a végén ellenőrizni.

## A kimenet ellenőrzése
Ellenőrzött területek (a program ezt olvassa vissza a kész fájlból):
@@CHECKS:tools@@

Üzenetek (súlyossággal):
@@VERIFY:tools@@"""),

        ("Parancssor", """## Összefűzés
python mts_joiner.py                          – grafikus felület
python mts_joiner.py -o ki.m2ts a.mts b.mts   – összefűzés parancssorból
- --lang hu|en – a kiírások nyelve
- --no-verify – az összefűzött fájl ellenőrzésének kihagyása (nem ajánlott)
- --no-fix-ps – a hiányzó SPS/PPS pótlásának kihagyása (TS/M2TS, H.264)
A program kiírja a kompatibilitást, a Folytatólagos és Varratminőség jelzést, majd összefűz. Kilépési kód: 0 = siker; 2 = a fájlok nem illeszthetők (piros sor); 3 = hiba az összefűzés vagy az ellenőrzés közben.

## Hang / stream eszközök
python mts_joiner.py streams fájl                               – a folyamok listája
python mts_joiner.py extract fájl -s ID -o ki                   – egy folyam kinyerése
python mts_joiner.py replace-audio fájl -s ID -a uj.ac3 -o ki   – hang cseréje
python mts_joiner.py shift-audio fájl -s ID -o ki --delay MS    – hang eltolása
- -s ID – a folyam azonosítója (a streams parancs listájából)
- --delay MS – késleltetés ezredmásodpercben (pozitív = később szól); replace-audio-nál TS és MKV esetén
- --no-verify – a kimenet ellenőrzésének kihagyása"""),

        ("Hibaelhárítás", """### A sor piros: „Nem illeszthető: …”
A fájl beállításai (felbontás, képfrekvencia, kodek, hangformátum stb.) eltérnek a referenciáétól, és a program nem alakít át semmit. Csak azonos kamerabeállítással készült fájlok fűzhetők össze. Kapcsold ki a sort, vagy tedd első helyre azt a fájlt, amelyhez igazodni szeretnél.

### Az ellenőrzés hibát talált, és van egy _HIBAS fájl
Olvasd el a naplóban a hibákat (lásd „Ellenőrzés” fül). Ellenőrizd a forrásfájlokat (játszd le őket), a kimeneti lemez épségét és a szabad helyet, majd ismételd meg. A _HIBAS fájlt ne használd véglegesként; a vizsgálat után töröld.

### „Szinkronvesztés a(z) N. csomagnál (sérült fájl?)”
A forrásfájl sérült (pl. megszakadt másolás vagy kártyahiba). Másold újra az eredeti kártyáról.

### „Nincs elég szabad hely a kimeneti meghajtón”
Szabadíts fel helyet, vagy válassz másik kimeneti meghajtót (a források összméreténél legalább 50 MB-tal több kell).

### „… nem támogatott” (töredezett MP4, DRM, külső adathivatkozás, nem 1× sebességű szerkesztőlista, ismeretlen méretű MKV-elem)
Ez a verzió ezeket nem kezeli. A titkosított / másolásvédett tartalmat (DRM-es MP4-sáv, titkosított MPEG-PS) a program szándékosan elutasítja, és nem is fog visszafejteni.

### A lejátszás a varratnál megakad vagy rángat
Nézd meg a sor Varratminőség értékét és az ellenőrzés eredményét. Ha a folytatásnál kimaradt képkocka van, valószínűleg hiányzik egy fájl a sorozatból, vagy rossz a sorrend.

### Nem jelzi folytatólagosnak a fájlt, pedig az
Ellenőrizd, hogy a fájl az előző bejelölt sor mögött áll-e, és hogy nincs-e kikapcsolva a közbeeső fájl. MP4 / MKV esetén csak a méret alapján („? csak méret”) lehet sejteni a folytatást. Ha a kamera ismeretlen méretnél vág, add hozzá a korlátot a SPLIT_LIMITS konstanthoz.

### Mennyi ideig tart?
Elsősorban a háttértár sebességétől függ: a program a forrást egyszer végigolvassa és a kimenetet kiírja, majd (ellenőrzéssel) visszaolvassa. Az ellenőrzés kihagyható, de nem ajánlott.

### Hol tárol beállítást a program?
Az összefűző a kiválasztott nyelv kódját a ~/.mts_joiner.cfg fájlba menti. A további modulok (FFmpeg-ablak, képeffektek) is írnak helyi beállításokat és naplót; a pontos lista a Jogi fül Adatkezelés részében van. A program nem kezdeményez hálózati kapcsolatot, és adatot nem gyűjt."""),
    ],
    "en": [
        ("Getting started", """## What is this program for?
Lossless Video Toolkit 1.0 joins several video files into one continuous file without re-encoding. Typical case: your camera split a long recording into several files because of the file-system size limit (e.g. 4 GB), and you want to put them back together. Picture and audio data are copied byte for byte, so there is no quality loss; the program only recalculates timestamps and counters so that a player sees one continuous recording.

## Supported formats
- AVCHD / MPEG-TS: .mts, .m2ts, .ts – the most complete support (H.264 video, AC-3 audio)
- MP4 / MOV: .mp4, .m4v, .mov
- Matroska / WebM: .mkv, .webm, .mka
- MPEG Program Stream and DVD VOB: .mpg, .mpeg, .mod, .vob
A single join may only contain files of the same type and the same settings: .mts cannot be joined to .mp4, and files with a different resolution or audio format are rejected (nothing is converted).

## Joining step by step
- 1. Add the files: "Add files…" or "Add folder…". You can select several files at once.
- 2. Check the order. The program joins in list order. Use ▲ Up / ▼ Down to move the selected rows; "Sort by name" sorts by file name (for the numbered file names of cameras this is usually the correct time order).
- 3. Switch individual files off if needed: click in the first column (☑ / ☐) and the row is left out of the join. The first checked file is the reference; the program compares the others to it.
- 4. Look at the Status column: green = fine, yellow = warning, red = cannot be joined (the start button is then disabled). Details: "List & indicators" tab.
- 5. Set the output file (default: osszefuzott.<extension> in the folder of the first file) and click "Start joining".
- 6. Wait for it to finish. After joining, the program automatically verifies the finished file; the result appears in the log (see the "Verification" tab). The "Cancel" button stops the operation at any time.

## Safety, space, file names
- Your source files are only read, never modified.
- The output is first written as <name>.part and gets its final name only after verification. If verification finds an error, the file is kept as <name>_HIBAS.<extension> for inspection, but do not use it as a final file.
- If the output file already exists, the program asks before overwriting it. The output may not be the same as any input file.
- The output drive needs at least 50 MB more free space than the total size of the sources. The output size is essentially the sum of the source sizes.
- Always keep a copy of important recordings anyway."""),

        ("List & indicators", """## The columns
- ✓ # – check mark (☑ / ☐) and row number. Click to switch on/off.
- File, Length, MB – file name, length of the recording and file size.
- Video, Audio – the detected codec and main parameters.
- Delay (picture / audio) – start time of the first frame and the first audio sample relative to the earliest-starting stream, in ms. E.g. "0 / +40" = the audio starts 40 ms later than the picture. This is the file's own timing, not an error.
- Continuation, Seam quality – see the "Continuation files" tab.
- Status – the compatibility result (see below). When you select a row, a detailed description of the seam appears below the list as well.

## Status: green, yellow, red
The comparison is made to the reference (the first checked file).
- Green – "Compatible": the file can be joined.
- Yellow – "Notice: …": it can be joined, but there is a difference worth knowing. Starting is allowed.
- Red – "Cannot be joined: …": the file cannot be joined to the reference. While such a row exists, starting is disabled: switch the row off or remove it, or move the file you want the others to match to the first position.
- Grey – "Skipped": not checked; "Analyzing…": analysis still running; "Reference (first file)": this is the basis of comparison.
- "Error: …": the file cannot be read (e.g. damaged or unsupported type).

## What causes a red or yellow indicator?
If the container type differs (e.g. .mts and .mp4 together), it is always red.
@@COMPARE@@"""),

        ("Continuation files", """## What is a continuation file?
Cameras split a long recording into several files at the file-system size limit (FAT32: 4 GiB, 2 GiB on older cameras; DVD VOB: 1 GiB). The next file is then the CONTINUATION of the previous one: the clocks (PTS/DTS, PCR, ATS, SCR) do not restart but continue exactly where the previous file ended, and the file often starts in the middle of a frame. Joining such a pair is the safest case, so the program flags it separately.

## The "Continuation" column
Every row is compared with the previous checked file (order and check marks matter: it is recalculated when you reorder or switch a file off). The decision is based on file size and timestamps:
- ✓ yes – the size of the previous file is just below a known limit (or the file starts mid-frame, or the clock is continuous) AND the time of the first picture is exactly the end of the previous file. The parentheses show what confirmed it: size, timestamps, starts mid-frame.
- ~ probable – only the timestamps connect (but the size is not near a limit), or the size is near a limit but the time does not connect exactly (e.g. missing frames).
- no – a separate clip (not a continuation of the previous one). This is not an error: separate recordings can be joined as well.
- ? size only – in MP4 / MKV files the timestamps restart from zero in every file, so a continuation can only be guessed from the size; the seam quality cannot be estimated ("–").
- – the first file, it has no predecessor.

### What counts as a size limit and as "exact" time?
- Size limits: 1 GiB, 2 GB, 2 GiB, 4 GB, 4 GiB – the file size may be at most 16 MiB or 1.5% (whichever is larger) below the limit. The list can be extended in the SPLIT_LIMITS constant at the top of the source code.
- Exact time connection: for TS the first picture is at most 2 clock ticks (about 22 µs) after the end of the previous file; for MPEG-PS a quarter of a frame. "Near": at most 4 frames.
- Continuous clock: the PCR / ATS / SCR value continues within 200 ms from the end of the previous file.

## The "Seam quality" column
0–100 points: how well picture, audio and clock fit at the boundary (the seam) with the previous file. The value is computed from the analyzed data before joining; the post-join verification measures the same on the finished file.
- ✓ Perfect (95–100): no noticeable defect.
- ✓ Good (80–94): minor deviation, usually neither visible nor audible.
- ! Fair (55–79): may be noticeable; look at the details (below the selected row).
- ✗ Poor (0–54): expect a picture glitch, judder or audio defect at the seam.

### Deductions (from 100)
- Continuation, but the picture timing is not exact (missing or repeated frames): −60.
- Separate clip that does not start with a key frame: −60 (starts at a recovery point, not a clean IDR: −5; cannot be verified: −10).
- Separate clip that starts mid-frame: −30 (a truncated frame would end up in the seam).
- Audio gap or overlap: up to about half an audio frame 0; up to one audio frame −8; up to 250 ms −20; up to 1 s −35; above that −60.
- In a continuation the clock (PCR / SCR) jumps outside the 0–120 ms range: −5.
- A separate MPEG-PS clip starts with an open GOP: −10.

Important: the value is an advance estimate. The final word belongs to the post-join verification (see the "Verification" tab), but in practice the two agree. Between separate clips, "no" and "Perfect" can appear together: it means the file is not a continuation, but it fits cleanly."""),

        ("Verification", """## What does verification do?
After joining, the program reads the finished file back and compares it with the sources in three passes (shown as "1/3, 2/3, 3/3" in the log). The "What is checked" list in the log shows what each check covers (listed per format below). Deviations have two severities:
[E] The output cannot be trusted. The file does not get its final name: it is kept as <name>_HIBAS.<extension> for inspection and the program reports an error.
[W] The file is usable, but there is a noticeable or noteworthy deviation. Many warnings come from the source ("also present in the source"): then the join did not cause them, the camera recording or a damaged source did.

## The final result
- VERIFICATION: PERFECT – no errors, no warnings.
- VERIFICATION: usable – only warnings, no errors. Read them and play the area around the seams.
- VERIFICATION: FAILED – at least one error; the output is not accepted (_HIBAS file).
Verification can be skipped with the command-line switch --no-verify, but this is not recommended.

## The seam lines in the log
Example: "Seam 3 @ …: picture +0.0 ms | audio +3.2 ms | PCR +40.0 ms | clean IDR start"
- picture – the video timing jump at the seam. The correct value is 0 (the next picture follows the previous one by exactly one frame step). A deviation = judder or a skipped / repeated picture.
- audio – audio gap (+) or overlap (−) at the seam. Half an audio frame (AC-3: about 16 ms) is fine; more can cause a short silence or click, but sync is kept.
- PCR – the jump of the player clock at the seam. A few tens of ms is normal.
- The last field: "clean IDR start" (the new part starts with a complete picture), "continuation (split file)" (the new part continues the same recording, so it need not start with a complete picture), "IDR cannot be verified" (not H.264).

## What the messages mean, per format
The lists below are generated from the program's actual messages. "N" stands for a number, "x" for a value and "…" for the place or name the program fills in for the actual case.
@@VERIFY:ts@@
@@VERIFY:ps@@
@@VERIFY:mp4@@
@@VERIFY:mkv@@"""),

        ("Audio / stream tools", """## What is the second tab for?
On the "Audio / stream tools" tab you can extract streams (picture, audio) from a file, replace the audio, or only shift the audio timing. The picture and all other tracks stay byte-identical. Supported: TS / M2TS, MP4 / MOV and MKV.

## Usage
- Load the files (video, audio or raw audio files). The list shows the codec and state of the streams ("supported" / "not supported").
- Extraction: select the streams and click "Extract selected streams…".
- Replacing audio: use the checkbox on the left to choose what stays: exactly ONE picture stream (the base file) and ONE audio stream (this goes into the output). If the audio comes from another file, the program extracts it internally and replaces the audio track of the base file – no raw audio file is needed. For a base file with several audio tracks, click the audio track that has to be replaced.
- If you select the base file's own audio, only the delay is applied.
- Delay (ms): positive = the audio plays later, negative = earlier; adjustable in 1 ms steps (buttons: ±1, ±10, ±100), applied to the selected audio track.

## Sync warnings
When replacing audio, the program compares the length, frame length and encoding of the new and the old audio and warns about sync risks (the messages start with "SYNC:", and each states the cause and the fix):
- Encoder delay (AAC, MP3, Opus): re-encoded audio typically shifts by a few ms; the program also gives the suggested delay.
- Length difference of at most 1 frame: usually rounding or encoder delay at the end of the audio.
- Length difference of more than 1 frame: you cut, deleted or inserted something in the editor; after a cut in the middle of the audio the rest drifts, which can only be fixed by re-exporting.
- Severe sync risk: the length of the new audio differs a lot, probably not the same audio.
- "The old audio track's codec is unknown": the time jumps of the seams of earlier joins cannot be preserved.
The program does not decode audio, so it does not compare the waveform: always check the finished file at a loud event (clap, knock) at the beginning, the middle and the end.

## Output verification
Checked areas (what the program reads back from the finished file):
@@CHECKS:tools@@

Messages (with severity):
@@VERIFY:tools@@"""),

        ("Command line", """## Joining
python mts_joiner.py                          – graphical interface
python mts_joiner.py -o out.m2ts a.mts b.mts  – join from the command line
- --lang hu|en – language of the output
- --no-verify – skip verification of the joined file (not recommended)
- --no-fix-ps – skip inserting missing SPS/PPS (TS/M2TS, H.264)
The program prints the compatibility, the Continuation and Seam quality indicators, and then joins. Exit code: 0 = success; 2 = the files cannot be joined (red row); 3 = error during joining or verification.

## Audio / stream tools
python mts_joiner.py streams file                               – list the streams
python mts_joiner.py extract file -s ID -o out                  – extract a stream
python mts_joiner.py replace-audio file -s ID -a new.ac3 -o out – replace audio
python mts_joiner.py shift-audio file -s ID -o out --delay MS   – shift audio
- -s ID – the stream ID (from the list printed by the streams command)
- --delay MS – delay in milliseconds (positive = plays later); for replace-audio with TS and MKV
- --no-verify – skip verification of the output"""),

        ("Troubleshooting", """### The row is red: "Cannot be joined: …"
The settings of the file (resolution, frame rate, codec, audio format, etc.) differ from the reference, and the program converts nothing. Only files recorded with the same camera settings can be joined. Switch the row off, or move the file you want to match to the first position.

### Verification found an error and there is a _HIBAS file
Read the errors in the log (see the "Verification" tab). Check the source files (play them), the health of the output drive and the free space, then repeat. Do not use the _HIBAS file as a final file; delete it after inspection.

### "Sync lost at packet N (damaged file?)"
The source file is damaged (e.g. an interrupted copy or a card error). Copy it again from the original card.

### "Not enough free space on the output drive"
Free up space or choose another output drive (it needs at least 50 MB more than the total size of the sources).

### "… not supported" (fragmented MP4, DRM, external data reference, edit list not at 1× speed, unknown-size MKV element)
This version does not handle these. Encrypted / copy-protected content (a DRM-protected MP4 track, encrypted MPEG-PS) is deliberately rejected, and the program will never decrypt it.

### Playback stalls or judders at a seam
Look at the Seam quality value of the row and at the verification result. If a continuation has a missing frame, a file is probably missing from the series or the order is wrong.

### It does not flag the file as a continuation, but it is one
Check that the file follows the previous checked row and that the file in between is not switched off. For MP4 / MKV a continuation can only be guessed from the size ("? size only"). If your camera splits at an unknown size, add the limit to the SPLIT_LIMITS constant.

### How long does it take?
It mainly depends on the speed of the storage: the program reads the sources once and writes the output, then (with verification) reads it back. Verification can be skipped, but this is not recommended.

### Where does the program store settings?
The joiner saves the selected language code in ~/.mts_joiner.cfg. The other modules (FFmpeg window, image effects) also write local settings and a log; the exact list is in the Privacy section of the Legal tab. The program initiates no network connections and collects no data."""),
    ],
}

# A két tábla az ellenőrző / összehasonlító függvényekből származik (súlyozás: E = hiba, W = figyelmeztetés;
# R = piros, Y = sárga). A tesztelés során a program forrásából újra kinyerve egyeznie kell velük.

_VERIFY_MSGS = {'mkv': (('struct',
          (('E', 'mv_boxes'), ('E', 'kv_ebml'), ('E', 'kv_segsize'), ('E', 'kv_cnt1'), ('E', 'kv_clusters'),
           ('E', 'kv_tracks'), ('E', 'kv_ctc'))),
         ('index', (('W', 'kv_noseek'), ('E', 'kv_seek'), ('E', 'kv_cue'), ('W', 'kv_nocues'))),
         ('vts', (('E', 'v_dur'), ('E', 'kv_neg'), ('E', 'kv_time'), ('E', 'v_v_seam'))),
         ('data', (('E', 'kv_track'), ('E', 'kv_count'), ('E', 'kv_crc'))), ('vseam', (('W', 'kv_key'),)),
         ('audio', (('E', 'v_s_noaudio'), ('W', 'v_a_seam_w'), ('W', 'v_a_seam_g'), ('E', 'v_a_seam_e'))),
         ('sync', (('E', 'kv_sync'),))),
 'mp4': (('struct',
          (('E', 'mv_boxes'), ('E', 'mv_moovn'), ('E', 'mv_mdatn'), ('E', 'mv_tracks'), ('E', 'mv_plen'),
           ('E', 'mv_kind'))),
         ('tables', (('E', 'mv_count'), ('E', 'mv_mdur'), ('E', 'mv_stss'), ('E', 'mv_overlap'))),
         ('data', (('E', 'mv_crc'), ('E', 'mv_spot'))),
         ('vts', (('E', 'mv_tim'), ('W', 'mv_dt'), ('E', 'mv_tkhd'), ('E', 'mv_dur'))),
         ('vseam', (('W', 'mv_key'),)),
         ('sync', (('E', 'mv_sync_out'), ('E', 'mv_sync'), ('E', 'mv_pad_e'), ('W', 'mv_pad')))),
 'ps': (('struct',
         (('E', 'pv_size'), ('E', 'pv_start'), ('E', 'pv_sys'), ('E', 'pv_junk'), ('W', 'pv_endcode'),
          ('E', 'pv_packs'))),
        ('scr', (('W', 'pv_scr_seam'), ('W', 'pv_scr'), ('E', 'pv_scr_off'))), ('data', (('E', 'pv_data'),)),
        ('nav', (('E', 'pv_nav'),)),
        ('vts',
         (('E', 'pv_novid'), ('E', 'pv_off'), ('E', 'pv_dur'), ('W', 'pv_gap'), ('E', 'pv_seam'),
          ('E', 'pv_total'))),
        ('vseam', (('E', 'pv_idr'), ('W', 'pv_open'))), ('audio', (('E', 'v_s_noaudio'),)),
        ('sync', (('E', 'pv_sync'),))),
 'tools': (('struct',
            (('E', 'au_v_size'), ('E', 'au_v_pid'), ('E', 'err_sync_k'), ('E', 'au_v_parse'),
             ('E', 'au_v_tracks'), ('E', 'au_v_track'), ('E', 'au_v_tab'), ('E', 'au_v_mkvtracks'),
             ('E', 'au_v_ebml'), ('E', 'au_v_clusters'))),
           ('cc', (('E', 'au_v_cc'),)),
           ('other', (('E', 'au_v_other'), ('E', 'au_v_track_data'), ('E', 'au_v_other_mkv'))),
           ('data', (('E', 'au_v_data'),)),
           ('pts', (('E', 'au_v_pts'), ('E', 'au_v_ctc'), ('W', 'au_v_nonmono')))),
 'ts': (('audio',
         (('E', 'v_a_crc'), ('E', 'v_a_none'), ('W', 'v_a_seam_w'), ('W', 'v_a_seam_g'), ('E', 'v_a_seam_e'),
          ('W', 'v_a_step'))),
        ('struct', (('E', 'v_size'), ('E', 'v_sync'), ('W', 'v_pes'))),
        ('ats', (('W', 'v_ats_seam'), ('W', 'v_ats'))), ('cc', (('E', 'v_cc_seam'), ('W', 'v_cc'))),
        ('pcr', (('E', 'v_pcr_seam'), ('W', 'v_pcr_seam_w'), ('W', 'v_pcr'))),
        ('vts',
         (('E', 'v_novid'), ('E', 'v_v_seam'), ('W', 'v_v_gap'), ('E', 'v_pts_lt'), ('E', 'v_off'),
          ('E', 'v_dur'))),
        ('vseam', (('W', 'v_idr_none'),)), ('pset', (('E', 'v_pset_miss'),)),
        ('sync', (('E', 'v_s_noaudio'), ('E', 'v_s_grid'), ('W', 'v_s_many'))))}

_COMPARE_MSGS = {'mkv': (('R', 'c_mp4_tracks'), ('R', 'c_mkv_doctype'), ('R', 'c_mkv_scale'), ('R', 'c_mkv_track'),
         ('R', 'c_mp4_codec'), ('R', 'c_mkv_priv'), ('R', 'c_res'), ('R', 'c_fps'), ('R', 'c_afmt'),
         ('Y', 'c_mkv_cfg'), ('Y', 'c_mkv_drop')),
 'mp4': (('R', 'c_mp4_tracks'), ('R', 'c_mp4_kind'), ('R', 'c_mp4_ts'), ('R', 'c_mp4_codec'), ('R', 'c_res'),
         ('R', 'c_mp4_matrix'), ('Y', 'c_fps'), ('R', 'c_afmt'), ('Y', 'c_mp4_cfg')),
 'ps': (('R', 'c_ps_sys'), ('R', 'c_ps_vid'), ('R', 'c_vcodec'), ('R', 'c_fps'), ('R', 'c_res'),
        ('R', 'c_scan'), ('Y', 'c_ps_ar'), ('Y', 'c_prof'), ('R', 'c_ps_streams'), ('R', 'c_afmt'),
        ('Y', 'c_abr'), ('Y', 'c_vunk'), ('Y', 'c_ps_nav'), ('Y', 'c_ps_open')),
 'ts': (('R', 'c_pktsize'), ('R', 'c_pid'), ('R', 'c_vcodec'), ('R', 'c_fps'), ('R', 'c_res'), ('R', 'c_scan'),
        ('Y', 'c_prof'), ('Y', 'c_vunk'), ('R', 'c_acodec'), ('R', 'c_afmt'), ('Y', 'c_abr'), ('Y', 'c_sps'))}

_CHECK_PFX = {"ts": ("vc", "vd"), "ps": ("pc", "pd"), "mp4": ("mc", "md"), "mkv": ("kc", "kd"), "tools": ("ac", "ad")}


def _msg_sample(s):
    """Egy üzenetsablon olvasható mintája: %d -> N, %+.1f -> ±x, %s -> …"""
    s = s.replace("%%", "\0").replace("0x%X", "0x…")
    s = re.sub(r"%[-+ #0]*\d*(?:\.\d+)?[df]",
               lambda m: "±x" if "+" in m.group(0) else ("N" if m.group(0)[-1] == "d" else "x"), s)
    s = re.sub(r"%[-+ #0]*\d*s", "…", s)
    return s.replace("\0", "%")


def _checks_lines(fmt):
    cp, dp = _CHECK_PFX[fmt]
    lang = _STR[LANG]
    return ["- %s: %s" % (lang[k], lang.get(dp + k[len(cp):], ""))
            for k in lang if k.startswith(cp + "_")]


def _verify_block(fmt):
    lang, cats, out = _STR[LANG], _VCAT[LANG], []
    if fmt != "tools":
        out += ["### " + _FMT_NAMES[fmt], lang["v_what"]] + _checks_lines(fmt)
    for cat, items in _VERIFY_MSGS[fmt]:
        title, expl = cats[cat]
        expl = expl.replace("[E]", "(%s)" % tr("hl_E")).replace("[W]", "(%s)" % tr("hl_W"))
        out += ["#### " + title, expl]
        out += ["[%s] %s" % (sev, _msg_sample(lang[key])) for sev, key in items]
    return out


def _compare_block():
    lang, out = _STR[LANG], []
    for fmt in ("ts", "mp4", "mkv", "ps"):
        out.append("### " + _FMT_NAMES[fmt])
        out += ["[%s] %s" % (lvl, _msg_sample(lang[key])) for lvl, key in _COMPARE_MSGS[fmt]]
    return out


def _help_expand(body):
    out = []
    for line in body.split("\n"):
        m = re.fullmatch(r"@@(\w+)(?::(\w+))?@@", line.strip())
        if not m:
            out.append(line)
        elif m.group(1) == "VERIFY":
            out += _verify_block(m.group(2))
        elif m.group(1) == "COMPARE":
            out += _compare_block()
        elif m.group(1) == "CHECKS":
            out += _checks_lines(m.group(2))
    return "\n".join(out)


def help_pages():
    """A súgó fülei az aktuális nyelven: [(cím, jelölt szöveg)]."""
    return [(title, _help_expand(body)) for title, body in _HELP[LANG]]


def render_help(t, text, tkfont):
    """Jelölt súgószöveg megjelenítése egy Text vezérlőben (írásvédetté is teszi)."""
    base = tkfont.nametofont("TkDefaultFont")
    t._fonts = []                                  # a betűtípus-objektumok ne szemetelődjenek ki

    def font(**kw):
        f = base.copy()
        f.configure(**kw)
        t._fonts.append(f)
        return f
    bold = font(weight="bold")
    mono = tkfont.nametofont("TkFixedFont").copy()
    t._fonts.append(mono)
    t.tag_configure("h", font=font(weight="bold", size=base.cget("size") + 3), spacing1=12, spacing3=4)
    t.tag_configure("h3", font=bold, spacing1=10, spacing3=2)
    t.tag_configure("h4", font=bold, foreground="#1f4e79", spacing1=8, spacing3=1)
    t.tag_configure("bul", lmargin1=14, lmargin2=28)
    t.tag_configure("code", font=mono, lmargin1=10, lmargin2=10)
    t.tag_configure("lab", font=bold)
    for tag, col in (("E", "#b00020"), ("W", "#8a5a00"), ("R", "#b00020"), ("Y", "#8a5a00")):
        t.tag_configure(tag, font=bold, foreground=col)
    t.tag_configure("msg", lmargin1=14, lmargin2=14)
    t.configure(state="normal")
    for line in text.split("\n"):
        if line.startswith("#### "):
            t.insert("end", line[5:] + "\n", "h4")
        elif line.startswith("### "):
            t.insert("end", line[4:] + "\n", "h3")
        elif line.startswith("## "):
            t.insert("end", line[3:] + "\n", "h")
        elif len(line) > 3 and line[0] == "[" and line[2] == "]" and line[1] in "EWRY":
            t.insert("end", tr("hl_" + line[1]), line[1])
            t.insert("end", "  " + line[4:] + "\n", "msg")
        elif line.startswith("- "):
            t.insert("end", "•  " + line[2:] + "\n", "bul")
        elif line.startswith("python mts_joiner.py"):
            t.insert("end", line + "\n", "code")
        else:
            t.insert("end", line + "\n")
    t.configure(state="disabled")


def tr(key, *a):
    s = _STR.get(LANG, {}).get(key) or _STR["en"].get(key) or key
    return s % a if a else s


class MsgError(Exception):
    """Fordítható hibaüzenet (a szöveg a kiíráskor készül el)."""

    def __init__(self, key, *fmt_args):
        Exception.__init__(self, key)
        self.key, self.fmt_args = key, fmt_args

    def __str__(self):
        return tr(self.key, *self.fmt_args)


def load_language():
    global LANG
    try:
        with open(_CFG, encoding="utf-8") as f:
            v = f.read().strip()
        if v in _STR:
            LANG = v
    except OSError:
        pass


def set_language(code, save=True):
    global LANG
    if code not in _STR:
        return
    LANG = code
    if save:
        try:
            with open(_CFG, "w", encoding="utf-8") as f:
                f.write(code)
        except OSError:
            pass


# ---------------------------------------------------------------- alapok --

def sdiff(a, b):
    """(a - b) előjeles értéke 33 bites modulóban."""
    return ((a - b + HALF33) % MOD33) - HALF33


def rd_ts(b, i):
    return ((((b[i] >> 1) & 7) << 30) | (b[i + 1] << 22) |
            ((b[i + 2] >> 1) << 15) | (b[i + 3] << 7) | (b[i + 4] >> 1))


def wr_ts(b, i, v):
    b[i] = (b[i] & 0xF0) | (((v >> 30) & 7) << 1) | 1
    b[i + 1] = (v >> 22) & 0xFF
    b[i + 2] = (((v >> 15) & 0x7F) << 1) | 1
    b[i + 3] = (v >> 7) & 0xFF
    b[i + 4] = ((v & 0x7F) << 1) | 1


def pes_times(buf, p, endt):
    """PES fejléc időbélyegei: (pts, dts|None, es_kezdet) vagy None."""
    if endt - p < 14 or buf[p] != 0 or buf[p + 1] != 0 or buf[p + 2] != 1:
        return None
    if buf[p + 3] in NO_HDR_IDS or (buf[p + 6] & 0xC0) != 0x80:
        return None
    fl = buf[p + 7] >> 6
    if not (fl & 2):
        return None
    pts = rd_ts(buf, p + 9)
    dts = None
    if fl == 3 and endt - p >= 19:
        dts = rd_ts(buf, p + 14)
    return pts, dts, p + 9 + buf[p + 8]


def detect_packet_size(head):
    for ps, h in ((192, 4), (188, 0)):
        n = (len(head) - h) // ps
        if n >= 3 and all(head[h + k * ps] == 0x47 for k in range(min(n, 8))):
            return ps
    return None


def iter_packets(buf, ps, H):
    """(t, pid, pusi, afc, cc, pay, pcr_base) minden csomagra."""
    n = len(buf) // ps
    for k in range(n):
        t = k * ps + H
        if buf[t] != 0x47:
            raise MsgError("err_sync_k", k)
        b1 = buf[t + 1]
        pid = ((b1 & 0x1F) << 8) | buf[t + 2]
        b3 = buf[t + 3]
        afc = (b3 >> 4) & 3
        pay = -1
        pcr = None
        if afc & 2:
            afl = buf[t + 4]
            if afl >= 7 and (buf[t + 5] & 0x10):
                q = t + 6
                pcr = ((buf[q] << 25) | (buf[q + 1] << 17) | (buf[q + 2] << 9) |
                       (buf[q + 3] << 1) | (buf[q + 4] >> 7))
            if afc & 1 and t + 5 + afl <= t + 188:
                pay = t + 5 + afl
        elif afc & 1:
            pay = t + 4
        yield t, pid, bool(b1 & 0x40), afc, b3 & 15, pay, pcr


# ------------------------------------------------------------ PSI / kodek --

def parse_pat(s):
    end = 3 + (((s[1] & 0x0F) << 8) | s[2]) - 4
    progs, i = {}, 8
    while i + 4 <= end:
        pn = (s[i] << 8) | s[i + 1]
        if pn != 0:
            progs[pn] = ((s[i + 2] & 0x1F) << 8) | s[i + 3]
        i += 4
    return progs


def parse_pmt(s):
    end = 3 + (((s[1] & 0x0F) << 8) | s[2]) - 4
    pcr_pid = ((s[8] & 0x1F) << 8) | s[9]
    i = 12 + (((s[10] & 0x0F) << 8) | s[11])
    streams = []
    while i + 5 <= end:
        streams.append((((s[i + 1] & 0x1F) << 8) | s[i + 2], s[i]))
        i += 5 + (((s[i + 3] & 0x0F) << 8) | s[i + 4])
    return pcr_pid, streams


def read_psi(head, ps, H):
    pmt_pid = None
    secs = {}
    for t, pid, pusi, afc, cc, pay, pcr in iter_packets(head, ps, H):
        if pay < 0 or not (pid == 0 or (pmt_pid is not None and pid == pmt_pid)):
            continue
        data = head[pay:t + 188]
        if pusi:
            secs[pid] = bytearray(data[1 + data[0]:])
        elif pid in secs:
            secs[pid] += data
        else:
            continue
        s = secs[pid]
        if len(s) >= 3 and len(s) >= 3 + (((s[1] & 0x0F) << 8) | s[2]):
            if pid == 0:
                progs = parse_pat(s)
                if progs and pmt_pid is None:
                    pmt_pid = progs[min(progs)]
            else:
                pcr_pid, streams = parse_pmt(s)
                return pcr_pid, streams, pmt_pid
            secs.pop(pid, None)
    return None


class BitReader:
    def __init__(self, data):
        self.d, self.p = data, 0

    def u(self, n):
        v = 0
        for _ in range(n):
            v = (v << 1) | ((self.d[self.p >> 3] >> (7 - (self.p & 7))) & 1)
            self.p += 1
        return v

    def ue(self):
        z = 0
        while self.u(1) == 0:
            z += 1
            if z > 32:
                raise ValueError("ue")
        return (1 << z) - 1 + self.u(z) if z else 0

    def se(self):
        k = self.ue()
        return (k + 1) // 2 if k & 1 else -(k // 2)


def unescape(b):
    out, z = bytearray(), 0
    for x in b:
        if z >= 2 and x == 3:
            z = 0
            continue
        out.append(x)
        z = z + 1 if x == 0 else 0
    return bytes(out)


def find_sps(b):
    return find_nal(b, 7)


def find_nal(b, nt):
    i = 0
    while True:
        i = b.find(b"\x00\x00\x01", i)
        if i < 0 or i + 4 > len(b):
            return None
        if (b[i + 3] & 0x9F) == nt:
            j = i + 4
            ends = [x for x in (b.find(b"\x00\x00\x01", j), b.find(b"\x00\x00\x00", j)) if x >= 0]
            return bytes(b[i + 3:(min(ends) if ends else len(b))])
        i += 3


def parse_sps(sps):
    r = BitReader(unescape(sps[1:]))
    profile = r.u(8)
    r.u(8)
    level = r.u(8)
    r.ue()
    chroma = 1
    if profile in (100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135):
        chroma = r.ue()
        if chroma == 3:
            r.u(1)
        r.ue()
        r.ue()
        r.u(1)
        if r.u(1):
            for i in range(8 if chroma != 3 else 12):
                if r.u(1):
                    last = nxt = 8
                    for _ in range(16 if i < 6 else 64):
                        if nxt != 0:
                            nxt = (last + r.se() + 256) % 256
                        last = last if nxt == 0 else nxt
    r.ue()
    poc = r.ue()
    if poc == 0:
        r.ue()
    elif poc == 1:
        r.u(1)
        r.se()
        r.se()
        for _ in range(r.ue()):
            r.se()
    r.ue()
    r.u(1)
    wmb = r.ue() + 1
    hmu = r.ue() + 1
    fmo = r.u(1)
    if not fmo:
        r.u(1)
    r.u(1)
    crop = (0, 0, 0, 0)
    if r.u(1):
        crop = tuple(r.ue() for _ in range(4))
    cux = 2 if chroma in (1, 2) else 1
    cuy = (2 - fmo) * (2 if chroma == 1 else 1)
    return {"profile": profile, "level": level,
            "w": wmb * 16 - cux * (crop[0] + crop[1]),
            "h": (2 - fmo) * hmu * 16 - cuy * (crop[2] + crop[3]),
            "interlaced": not fmo}


def parse_ac3(b):
    i = b.find(b"\x0b\x77")
    if i < 0 or len(b) < i + 10:
        return None
    fscod, frm = b[i + 4] >> 6, b[i + 4] & 0x3F
    if (b[i + 5] >> 3) > 10 or fscod > 2 or (frm >> 1) >= 19:
        return None
    r = BitReader(b[i + 6:i + 10])
    acmod = r.u(3)
    if (acmod & 1) and acmod != 1:
        r.u(2)
    if acmod & 4:
        r.u(2)
    if acmod == 2:
        r.u(2)
    lfe = r.u(1)
    nf = (2, 1, 2, 3, 3, 4, 4, 5)[acmod]
    return {"fs": (48000, 44100, 32000)[fscod], "ch": "%d.%d" % (nf, lfe),
            "kbps": AC3_RATES[frm >> 1]}


# ------------------------------------------------------------ elemzés ------

class TsInfo:
    kind = "ts"

    def analyze(self):
        _analyze(self)

    def __init__(self, path):
        self.path = path
        self.name = os.path.basename(path)
        self.pending = True
        self.error = None
        self.size = 0
        self.ps, self.H = 192, 4
        self.pcr_pid = None
        self.vpid = self.vtype = None
        self.apids, self.atypes = [], {}
        self.es_pids = set()
        self.v_first = self.v_last = None
        self.fd = 3600
        self.a_dur, self.a_last = {}, {}
        self.last_pcr = None
        self.last_cc = {}
        self.vinfo = self.sps = self.ainfo = None
        self.pps = None
        self.duration = 0.0
        self.a_first = {}          # első hang-PTS PID-enként (az ellenőrzéshez)
        self.c0 = None             # (PCR - ATS) mod 2^30 az első PCR-csomagnál
        self.v_pts0 = None         # az első kép PTS-e (a késleltetés kijelzéséhez)
        self.first_pcr = None      # az első PCR (90 kHz) – a folytatás felismeréséhez
        self.ats_first = self.ats_last = None   # az első / utolsó csomag ATS-e (30 bit)
        self.v_orphan = 0          # az első képkocka előtti videócsomagok: >0 = a fájl kép közepén indul
        self.first_key = None      # az első teljes kép: 'idr' / 'rec' (visszaállási pont) / 'none' / None

    def vdesc(self):
        if not self.vinfo:
            return "?"
        v = self.vinfo
        return "%dx%d%s %g fps" % (v["w"], v["h"], "i" if v["interlaced"] else "p",
                                   round(90000.0 / self.fd, 2))

    def adesc(self):
        if not self.apids:
            return tr("no_audio")
        t = AUDIO_NAMES.get(self.atypes[self.apids[0]], "0x%02X" % self.atypes[self.apids[0]])
        a = self.ainfo
        return "%s %s %dk" % (t, a["ch"], a["kbps"]) if a else t


def _mode_delta(vals, fallback, lo=1, hi=200000):
    d = [(b - a) % MOD33 for a, b in zip(vals, vals[1:])]
    d = [x for x in d if lo <= x <= hi]
    return Counter(d).most_common(1)[0][0] if d else fallback


def _analyze(inf):
    inf.size = os.path.getsize(inf.path)
    if inf.size < 188 * 10:
        raise MsgError("err_small")
    with open(inf.path, "rb") as f:
        head = f.read(HEAD_BYTES)
        ps = detect_packet_size(head)
        if not ps:
            raise MsgError("err_notts")
        inf.ps, inf.H = ps, (4 if ps == 192 else 0)
        H = inf.H
        head = bytearray(head[:len(head) // ps * ps])
        psi = read_psi(head, ps, H)
        if not psi:
            raise MsgError("err_nopsi")
        inf.pcr_pid, streams, _ = psi
        for pid, st in streams:
            inf.es_pids.add(pid)
            if inf.vpid is None and st in VIDEO_TYPES:
                inf.vpid, inf.vtype = pid, st
            elif st in AUDIO_TYPES:
                inf.apids.append(pid)
                inf.atypes[pid] = st
        if inf.vpid is None:
            raise MsgError("err_novideo")
        vpid, apids = inf.vpid, set(inf.apids)

        vdts, apts = [], {p: [] for p in apids}
        vbytes, abytes = bytearray(), {p: bytearray() for p in apids}
        fa_state, first_au = 0, bytearray()    # az első teljes videó PES elemi adata (kulcskocka-vizsgálathoz)
        for t, pid, pusi, afc, cc, pay, pcr in iter_packets(head, ps, H):
            if pcr is not None and H and inf.c0 is None and pid == inf.pcr_pid:
                ext = ((head[t + 10] & 1) << 8) | head[t + 11]
                inf.c0 = (pcr * 300 + ext - _U32.unpack_from(head, t - H)[0]) & 0x3FFFFFFF
            if pcr is not None and inf.first_pcr is None and pid == inf.pcr_pid:
                inf.first_pcr = pcr
            if pay < 0:
                continue
            if pid == vpid:
                start = pay
                if pusi:
                    tm = pes_times(head, pay, t + 188)
                    if tm:
                        vdts.append(tm[1] if tm[1] is not None else tm[0])
                        if inf.v_pts0 is None:
                            inf.v_pts0 = tm[0]
                        start = tm[2]
                        if fa_state < 2:
                            fa_state += 1
                elif fa_state == 0:
                    inf.v_orphan += 1       # még az előző fájlban kezdődött képkocka maradéka
                if fa_state == 1 and len(first_au) < 4096:
                    first_au += head[start:t + 188]
                if len(vbytes) < 262144:
                    vbytes += head[start:t + 188]
            elif pid in apids:
                start = pay
                if pusi:
                    tm = pes_times(head, pay, t + 188)
                    if tm:
                        apts[pid].append(tm[0])
                        start = tm[2]
                if len(abytes[pid]) < 64:
                    abytes[pid] += head[start:t + 188]
        if not vdts:
            raise MsgError("err_nots")
        inf.v_first = vdts[0]
        inf.fd = _mode_delta(vdts, 3600, 1, 180000)
        for p in apids:
            inf.a_dur[p] = _mode_delta(apts[p], 2880, 1, 180000)
            if apts[p]:
                inf.a_first[p] = apts[p][0]
        sps = find_sps(bytes(vbytes))
        if sps:
            inf.sps = sps
            try:
                inf.vinfo = parse_sps(sps)
            except Exception:
                inf.vinfo = None
        inf.pps = find_nal(bytes(vbytes), 8)
        if H:
            inf.ats_first = _U32.unpack_from(head, 0)[0] & 0x3FFFFFFF
        if inf.vtype == 0x1B and first_au:
            lead = _h264_lead(bytes(first_au))
            if lead is not None:
                nals, key = lead
                inf.first_key = ("idr" if nals[-1][0] == 5 else "rec") if key else "none"
        if inf.apids and inf.atypes[inf.apids[0]] == 0x81:
            inf.ainfo = parse_ac3(bytes(abytes[inf.apids[0]]))

        tstart = max(0, (inf.size - TAIL_BYTES) // ps * ps)
        f.seek(tstart)
        tail = f.read(inf.size - tstart)
        tail = bytearray(tail[:len(tail) // ps * ps])
        if H and len(tail) >= ps:
            inf.ats_last = _U32.unpack_from(tail, len(tail) - ps)[0] & 0x3FFFFFFF
    last_v = None
    for t, pid, pusi, afc, cc, pay, pcr in iter_packets(tail, ps, H):
        if pid != 0x1FFF:
            inf.last_cc[pid] = cc
        if pcr is not None:
            inf.last_pcr = pcr
        if pusi and pay >= 0 and pid in inf.es_pids:
            tm = pes_times(tail, pay, t + 188)
            if tm:
                if pid == vpid:
                    last_v = tm[1] if tm[1] is not None else tm[0]
                elif pid in apids:
                    inf.a_last[pid] = tm[0]
    if last_v is None:
        raise MsgError("err_nots_end")
    inf.v_last = last_v
    inf.duration = ((last_v + inf.fd - inf.v_first) % MOD33) / 90000.0


def FileInfo(path):
    """A fájl kiterjesztése alapján a megfelelő elemző objektumot adja."""
    ext = os.path.splitext(path)[1].lower()
    if ext in MP4_EXTS:
        return Mp4Info(path)
    if ext in MKV_EXTS:
        return MkvInfo(path)
    if ext in MPG_EXTS or ext in VOB_EXTS:
        try:
            with open(path, "rb") as f:
                if detect_packet_size(f.read(4096)):
                    return TsInfo(path)      # .mpg kiterjesztésű Transport Stream
        except OSError:
            pass
        return VobInfo(path) if ext in VOB_EXTS else MpgInfo(path)
    return TsInfo(path)


def analyze_into(inf):
    try:
        inf.analyze()
    except Exception as e:
        inf.error = e
    inf.pending = False
    return inf


def compare(ref, inf, prev=None):
    """('ok'|'warn'|'bad'|'pend', text)"""
    if inf.pending:
        return "pend", tr("c_pend")
    if inf.error:
        return "bad", str(inf.error) or inf.error.__class__.__name__
    if ref is None:
        return "bad", tr("c_noref")
    if inf is ref:
        return "ok", tr("c_ref")
    if inf.kind != ref.kind:
        return "bad", tr("c_kind", ref.kind.upper(), inf.kind.upper())
    if inf.kind == "mp4":
        return mp4_compare(ref, inf)
    if inf.kind == "mkv":
        return mkv_compare(ref, inf)
    if inf.kind in ("mpg", "vob"):
        return ps_compare(ref, inf, prev)
    bad, warn = [], []
    if inf.ps != ref.ps:
        bad.append(tr("c_pktsize"))
    if (inf.vpid, inf.apids, inf.pcr_pid) != (ref.vpid, ref.apids, ref.pcr_pid):
        bad.append(tr("c_pid"))
    if inf.vtype != ref.vtype:
        bad.append(tr("c_vcodec"))
    if abs(inf.fd - ref.fd) > 1:
        bad.append(tr("c_fps"))
    rv, v = ref.vinfo, inf.vinfo
    if rv and v:
        if (rv["w"], rv["h"]) != (v["w"], v["h"]):
            bad.append(tr("c_res"))
        if rv["interlaced"] != v["interlaced"]:
            bad.append(tr("c_scan"))
        if rv["profile"] != v["profile"] or rv["level"] != v["level"]:
            warn.append(tr("c_prof"))
    elif bool(rv) != bool(v):
        warn.append(tr("c_vunk"))
    if inf.atypes != ref.atypes:
        bad.append(tr("c_acodec"))
    ra, a = ref.ainfo, inf.ainfo
    if ra and a:
        if ra["fs"] != a["fs"] or ra["ch"] != a["ch"]:
            bad.append(tr("c_afmt"))
        elif ra["kbps"] != a["kbps"]:
            warn.append(tr("c_abr"))
    if not bad and not warn and ref.sps and inf.sps and ref.sps != inf.sps:
        warn.append(tr("c_sps"))
    if bad:
        return "bad", "; ".join(bad)
    if warn:
        return "warn", "; ".join(warn)
    return "ok", tr("c_ok")


# ------------------------------------- folytatólagos fájl / varratminőség ------
# Egy felvételt a kamera a fájlrendszer méretkorlátjánál (FAT32: 4 GiB, régebbi gépeknél
# 2 GiB, DVD VOB: 1 GiB) több fájlra darabol. A következő fájl ilyenkor az előző
# FOLYTATÁSA: az órák (PTS/DTS, PCR, ATS) nem indulnak újra, hanem pontosan ott folytatódnak,
# ahol az előző fájl véget ért, és a fájl gyakran egy képkocka közepén kezdődik.
# A felismerés a méretből és az időbélyegekből történik, kizárólag az elemzéskor már
# összegyűjtött adatokból (nem olvas újra a lemezről). Ugyanezekből készül a varratminőség:
# 0–100 pont, amely azt mutatja, mennyire illeszkedik a kép, a hang és az óra a varratnál.

# (név, bájt) – az a méret, amelynél a kamera / író a következő fájlt kezdi. Szükség esetén bővíthető.
SPLIT_LIMITS = (("1 GiB", 1 << 30), ("2 GB", 2000000000), ("2 GiB", 2 << 30),
                ("4 GB", 4000000000), ("4 GiB", 4 << 30))
SEAM_PCR_MAX = 10800        # 120 ms: ennél nagyobb óra-rés folytatásnál szabálytalan


def split_limit_hit(size):
    """A méretkorlát neve, ha a fájl mérete közvetlenül egy ismert korlát alatt van, különben None."""
    for name, lim in SPLIT_LIMITS:
        if lim - max(16 << 20, int(lim * 0.015)) <= size <= lim + 4096:
            return name
    return None


def _grade(score):
    if score >= 95:
        return "perfect"
    if score >= 80:
        return "good"
    if score >= 55:
        return "fair"
    return "poor"


def _aud_pen(g, fr):
    """Hangrés/átfedés (90 kHz-es tick) büntetőpontja; fr = egy hangegység ideje tickben."""
    a = abs(g)
    if a <= fr / 2.0 + 2 + fr / 100.0:
        return 0
    if a <= fr:
        return 8
    if a <= 22500:             # 250 ms
        return 20
    if a <= 90000:             # 1 s
        return 35
    return 60


def _cont_level(exact, near, hit, strong):
    """'yes' / 'probable' / 'no'.

    exact  - az első kép ideje pontosan az előző fájl vége
    near   - legfeljebb pár képkockányira van
    hit    - az előző fájl mérete méretkorlát alatt van
    strong - más erős jel (kép közepén kezdődés, folytonos PCR/ATS/SCR óra)"""
    if exact and (hit or strong):
        return "yes"
    if exact or (hit and (near or strong)):
        return "probable"
    return "no"


def _seam_new(cont, hit, parts, timed):
    return {"cont": cont, "limit": hit, "parts": parts if cont != "no" else [], "timed": timed,
            "vf": None, "ag": None, "pg": None, "key": None, "mid": False,
            "score": None, "grade": None, "notes": []}


def _seam_done(r, score):
    r["score"] = max(0, score)
    r["grade"] = _grade(r["score"])
    return r


def _seam_ts(a, b):
    fd = a.fd
    prev_end = (a.v_last + fd) % MOD33
    gv = sdiff(b.v_first, prev_end)
    exact, near = abs(gv) <= 2, abs(gv) <= 4 * fd
    hit = split_limit_hit(a.size)
    mid = b.v_orphan > 0
    pr = ar = None
    if a.last_pcr is not None and b.first_pcr is not None:
        pr = sdiff(b.first_pcr, a.last_pcr)
    if a.ats_last is not None and b.ats_first is not None:
        ar = (b.ats_first - a.ats_last) & 0x3FFFFFFF
        if ar >= 1 << 29:
            ar -= 1 << 30
    clock = (pr is not None and 0 <= pr <= 18000) or (ar is not None and 0 <= ar <= 5400000)
    cont = _cont_level(exact, near, hit, mid or clock)
    parts = []
    if hit:
        parts.append(("size", hit))
    if exact:
        parts.append(("ts", None))
    if mid:
        parts.append(("mid", None))
    elif clock and not exact:
        parts.append(("clock", None))
    r = _seam_new(cont, hit, parts, True)
    r.update(vf=gv / float(fd), key=b.first_key, mid=mid)
    notes, score = r["notes"], 100
    if cont != "no":
        if not exact:                       # a megosztott fájl nem csatlakozik pontosan
            score -= 60
            notes.append(("sc_n_vgap", gv / float(fd)))
    else:                                   # önálló klip: tiszta kezdés kell
        if b.vtype == 0x1B and b.first_key == "idr":
            pass
        elif b.vtype == 0x1B and b.first_key == "none":
            score -= 60
            notes.append(("sc_n_nokey",))
        elif b.vtype == 0x1B and b.first_key == "rec":
            score -= 5
            notes.append(("sc_n_rec",))
        else:
            score -= 10
            notes.append(("sc_n_keyunk",))
        if mid:
            score -= 30
            notes.append(("sc_n_mid",))
    worst = None                            # hang: a videóhoz igazított eltolással számolt rés/átfedés
    for p in a.apids:
        if p in a.a_last and p in b.a_first and p in a.a_dur:
            adur = a.a_dur[p]
            g = sdiff((b.a_first[p] + prev_end - b.v_first) % MOD33, (a.a_last[p] + adur) % MOD33)
            if worst is None or abs(g) > abs(worst[0]):
                worst = (g, _aud_pen(g, adur))
    if worst is not None:
        r["ag"] = worst[0] / 90.0
        if worst[1]:
            score -= worst[1]
            notes.append(("sc_n_agap", worst[0] / 90.0))
    if a.last_pcr is not None and b.first_pcr is not None:
        pg = sdiff((b.first_pcr + prev_end - b.v_first) % MOD33, a.last_pcr)
        r["pg"] = pg / 90.0
        if cont != "no" and (pg < 0 or pg > SEAM_PCR_MAX):
            score -= 5
            notes.append(("sc_n_pcr", pg / 90.0))
    return _seam_done(r, score)


def _seam_ps(a, b):
    fd = a.fd
    gv = sdiff(b.t_start, a.t_end)
    exact, near = abs(gv) <= max(2.0, 0.25 * fd), abs(gv) <= 4 * fd
    hit = split_limit_hit(a.size)
    sr = None
    if a.last_scr is not None and b.first_scr is not None:
        sr = (b.first_scr - a.last_scr + SCR_MOD // 2) % SCR_MOD - SCR_MOD // 2
    clock = sr is not None and 0 <= sr <= 5400000
    pt = b.first_ptype
    nokey = pt is not None and pt != 1
    cont = _cont_level(exact, near, hit, nokey or clock)
    parts = []
    if hit:
        parts.append(("size", hit))
    if exact:
        parts.append(("ts", None))
    if nokey:
        parts.append(("nokey", None))
    elif clock and not exact:
        parts.append(("clock", None))
    r = _seam_new(cont, hit, parts, True)
    r.update(vf=gv / float(fd), key=("idr" if pt == 1 else "none" if pt else None))
    notes, score = r["notes"], 100
    if cont != "no":
        if not exact:
            score -= 60
            notes.append(("sc_n_vgap", gv / float(fd)))
    else:
        if pt is None:
            score -= 10
            notes.append(("sc_n_keyunk",))
        elif nokey:
            score -= 60
            notes.append(("sc_n_nokey",))
        elif b.open_start:
            score -= 10
            notes.append(("sc_n_open",))
    off = (a.t_end - b.t_start) % MOD33
    worst = None
    for k in a.akeys:
        an = a.ainfo.get(k) or {}
        if k not in a.a_last or k not in b.a_first:
            continue
        if "kbps" in an:
            bps = an["kbps"] * 125.0
        elif "bits" in an:
            bps = an["fs"] * an["ch"] * an["bits"] / 8.0
        else:
            continue
        exp = int(round(a.a_last[k] + a.a_tail.get(k, 0) / bps * 90000.0)) % MOD33
        g = sdiff((b.a_first[k] + off) % MOD33, exp)
        fr = 90000.0 * an.get("spf", 1536) / an.get("fs", 48000)
        if worst is None or abs(g) > abs(worst[0]):
            worst = (g, _aud_pen(g, fr))
    if worst is not None:
        r["ag"] = worst[0] / 90.0
        if worst[1]:
            score -= worst[1]
            notes.append(("sc_n_agap", worst[0] / 90.0))
    if sr is not None:
        r["pg"] = sr / 27000.0
        if cont != "no" and (sr < 0 or sr > 5400000):
            score -= 5
            notes.append(("sc_n_pcr", sr / 27000.0))
    return _seam_done(r, score)


def _seam_size(a, b):
    """MP4 / MKV: az időbélyegek fájlonként nulláról indulnak, csak a méret használható."""
    hit = split_limit_hit(a.size)
    r = _seam_new("size" if hit else "no", hit, [("size", hit)] if hit else [], False)
    if hit:
        r["notes"].append(("sc_n_sizeonly",))
    return r


def ts_is_cont(a, b):
    """TS: b első képe pontosan az a vége után következik (az órák folytatódnak)."""
    return abs(sdiff(b.v_first, (a.v_last + a.fd) % MOD33)) <= 2


def ps_is_cont(a, b):
    """PS: b első képe az a vége után következik (az órák folytatódnak)."""
    return abs(sdiff(b.t_start, a.t_end)) <= max(2.0, 0.25 * a.fd)


def seam_assess(prev, cur):
    """Két egymás utáni, elemzett fájl varratának értékelése (dict) vagy None.

    cont : 'yes' (méret + időbélyegek igazolják), 'probable', 'no', 'size' (csak méret alapján)
    score: 0–100 varratminőség (None, ha nem becsülhető), grade: perfect / good / fair / poor"""
    if prev is None or cur is None or prev.pending or cur.pending or prev.error or cur.error:
        return None
    if prev.kind != cur.kind:
        return None
    if cur.kind == "ts":
        return _seam_ts(prev, cur)
    if cur.kind in ("mpg", "vob"):
        return _seam_ps(prev, cur)
    return _seam_size(prev, cur)


def seam_texts(prev, cur):
    """A varrat megjelenítésre kész szövegei: {cont, qual, detail, notes} vagy None.

    prev None -> ez az első fájl (nincs varrat): mindkét oszlop '–'."""
    if cur is None or cur.pending or cur.error:
        return None
    if prev is None:
        d = tr("sc_first")
        return {"cont": d, "qual": d, "detail": "", "notes": [], "sa": None}
    try:
        sa = seam_assess(prev, cur)
    except (KeyError, TypeError, AttributeError, ZeroDivisionError):
        return None                       # a díszoszlop hibája ne akassza meg a listát
    if sa is None:
        return None
    parts = [tr("sc_p_size", p[1]) if p[0] == "size" else tr("sc_p_" + p[0]) for p in sa["parts"]]
    cont = {"yes": tr("sc_yes"), "probable": tr("sc_probable"), "no": tr("sc_no"),
            "size": tr("sc_size_only")}[sa["cont"]]
    if parts:
        cont += " (%s)" % ", ".join(parts)
    if sa["score"] is None:
        qual = tr("sc_dash")
    else:
        mark = {"perfect": "✓", "good": "✓", "fair": "!", "poor": "✗"}[sa["grade"]]
        qual = "%s %s (%d)" % (mark, tr("g_" + sa["grade"]), sa["score"])
    mb = prev.size / 1048576.0
    ztxt = tr("sc_sz_lim", mb, sa["limit"]) if sa["limit"] else tr("sc_sz", mb)
    notes = [tr(n[0], *n[1:]) for n in sa["notes"]]
    if sa["timed"]:
        dash = tr("sc_dash")
        ktxt = {"idr": tr("sc_k_idr"), "rec": tr("sc_k_rec"), "none": tr("sc_k_none")}.get(
            sa["key"], tr("sc_k_unk"))
        if sa["mid"]:
            ktxt += ", " + tr("sc_p_mid")
        detail = tr("sc_detail",
                    tr("sc_v", sa["vf"]) if sa["vf"] is not None else dash,
                    tr("sc_ms", sa["ag"]) if sa["ag"] is not None else dash,
                    tr("sc_ms", sa["pg"]) if sa["pg"] is not None else dash, ktxt, ztxt)
        if not notes:
            notes = [tr("sc_note_ok")]
    else:
        detail = tr("sc_d_size", ztxt)
    return {"cont": cont, "qual": qual, "detail": detail + ("\n" + " ".join(notes) if notes else ""),
            "notes": notes, "line": "%s | %s" % (cont, qual), "sa": sa}


def seam_log(infos, log):
    """Az összefűzés elején kiírja az egyes varratok becsült jellemzőit."""
    for k in range(1, len(infos)):
        st = seam_texts(infos[k - 1], infos[k])
        if not st:
            continue
        log(tr("l_seam", k + 1, infos[k].name, st["cont"], st["qual"]))
        for n in st["notes"]:
            log("   " + n)


# ------------------------------------------------------------ összefűzés ---

class _State:
    pass


def _process_file(inf, off, fo, st, log, step, cancel):
    ps, H = inf.ps, inf.H
    off_ats = (off * 300) & 0x3FFFFFFF
    if H and inf.c0 is not None and st.c_ref is not None:
        # az ATS és a PCR kapcsolatát (c = PCR - ATS) az első fájlééval azonosra hozzuk,
        # így az érkezési idő a varratnál is folytonos marad
        adj = (inf.c0 - st.c_ref) & 0x3FFFFFFF
        if adj:
            off_ats = (off_ats + adj) & 0x3FFFFFFF
            log(tr("l_ats", (adj - (1 << 30) if adj >= (1 << 29) else adj) / 27000.0))
    if H:
        # varrat: az érkezési idő (ATS) ne ugorjon vissza az előző rész utolsó csomagjához képest
        try:
            with open(inf.path, "rb") as f0:
                a_first = _U32.unpack(f0.read(4))[0] & 0x3FFFFFFF
                f0.seek((inf.size // ps - 1) * ps)
                a_last = _U32.unpack(f0.read(4))[0] & 0x3FFFFFFF
            prev = getattr(st, "last_ats", None)
            if prev is not None:
                d = (a_first + off_ats - prev) & 0x3FFFFFFF
                if d >= (1 << 29):
                    short = (1 << 30) - d
                    off_ats = (off_ats + short) & 0x3FFFFFFF
                    log(tr("l_ats_seam", short / 27000.0))
            st.last_ats = (a_last + off_ats) & 0x3FFFFFFF
        except (OSError, struct.error):
            st.last_ats = None
    es = inf.es_pids
    apids = [p for p in inf.apids if p in st.a_end]
    adur = inf.a_dur
    seam = {p: True for p in apids}
    dropping = {p: False for p in apids}
    dropped = {p: 0 for p in apids}
    cc = st.cc
    st.pcr_pending = True
    S = _U32
    left = inf.size // ps * ps
    with open(inf.path, "rb") as fi:
        while left > 0:
            if cancel is not None and cancel.is_set():
                return False
            data = fi.read(min(ps * CHUNK_PACKETS, left))
            if not data:
                break
            left -= len(data)
            buf = bytearray(data)
            run = 0
            for k in range(len(buf) // ps):
                o = k * ps
                t = o + H
                if buf[t] != 0x47:
                    raise MsgError("err_sync_file", inf.name)
                b1 = buf[t + 1]
                pid = ((b1 & 0x1F) << 8) | buf[t + 2]
                b3 = buf[t + 3]
                afc = (b3 >> 4) & 3
                pay = -1
                if afc & 2:
                    if afc & 1:
                        pay = t + 5 + buf[t + 4]
                elif afc & 1:
                    pay = t + 4
                tm = None
                if pay >= 0 and (b1 & 0x40) and pid in es and pay + 14 <= t + 188:
                    tm = pes_times(buf, pay, t + 188)
                # hang: a varratnál átfedő PES csomagok eldobása
                if pid in dropping:
                    if tm is not None:
                        newp = (tm[0] + off) % MOD33
                        if seam[pid]:
                            d = sdiff(newp, st.a_end[pid])
                            if d < -(adur[pid] // 2):
                                dropping[pid] = True
                                dropped[pid] += 1
                            else:
                                dropping[pid] = False
                                seam[pid] = False
                                log(tr("l_audio", pid, d / 90.0, dropped[pid]))
                        if not dropping[pid]:
                            st.a_end[pid] = (newp + adur[pid]) % MOD33
                    if dropping[pid]:
                        if run < o:
                            fo.write(buf[run:o])
                        run = o + ps
                        continue
                if H:
                    a = S.unpack_from(buf, o)[0]
                    S.pack_into(buf, o, (a & 0xC0000000) | ((a + off_ats) & 0x3FFFFFFF))
                if pid != 0x1FFF:
                    last = cc.get(pid)
                    if afc & 1:
                        new = ((last + 1) & 15) if last is not None else (b3 & 15)
                    else:
                        new = last if last is not None else (b3 & 15)
                    cc[pid] = new
                    buf[t + 3] = (b3 & 0xF0) | new
                if (afc & 2) and buf[t + 4] >= 7 and (buf[t + 5] & 0x10):
                    q = t + 6
                    base = ((buf[q] << 25) | (buf[q + 1] << 17) | (buf[q + 2] << 9) |
                            (buf[q + 3] << 1) | (buf[q + 4] >> 7))
                    nb = (base + off) % MOD33
                    buf[q] = (nb >> 25) & 0xFF
                    buf[q + 1] = (nb >> 17) & 0xFF
                    buf[q + 2] = (nb >> 9) & 0xFF
                    buf[q + 3] = (nb >> 1) & 0xFF
                    buf[q + 4] = ((nb & 1) << 7) | (buf[q + 4] & 0x7F)
                    if st.pcr_pending:
                        st.pcr_pending = False
                        if st.last_pcr is not None:
                            d = sdiff(nb, st.last_pcr)
                            if d < 0 or d > 45000:
                                buf[t + 5] |= 0x80  # discontinuity_indicator
                                log(tr("l_pcr", d / 90.0))
                    st.last_pcr = nb
                if tm is not None:
                    wr_ts(buf, pay + 9, (tm[0] + off) % MOD33)
                    if tm[1] is not None:
                        wr_ts(buf, pay + 14, (tm[1] + off) % MOD33)
            if run == 0:
                fo.write(buf)
            elif run < len(buf):
                fo.write(buf[run:])
            step(len(data))
    return True


def join_files(infos, out_path, progress=None, log=None, cancel=None, verify=True, fix_ps=True):
    """Összefűzi a (már elemzett és kompatibilis) fájlokat. True, ha elkészült.

    verify=True esetén a kész fájlt ellenőrzi; hiba esetén nem fogadja el (MsgError)."""
    log = log or (lambda s: None)
    progress = progress or (lambda f: None)
    if not infos:
        raise MsgError("j_nofiles")
    for i in infos:
        if i.error or i.pending:
            raise MsgError("j_badfile", i.name)
    ref = infos[0]
    if os.path.normcase(os.path.abspath(out_path)) in [
            os.path.normcase(os.path.abspath(i.path)) for i in infos]:
        raise MsgError("j_sameout")
    for i in infos[1:]:
        if i.kind != ref.kind:
            raise MsgError("c_kind", ref.kind.upper(), i.kind.upper())
    seam_log(infos, log)
    if ref.kind == "mp4":
        return mp4_join(infos, out_path, progress, log, cancel, verify)
    if ref.kind == "mkv":
        return mkv_join(infos, out_path, progress, log, cancel, verify)
    if ref.kind in ("mpg", "vob"):
        return ps_join(infos, out_path, progress, log, cancel, verify)

    total = sum(i.size // i.ps * i.ps for i in infos)
    try:
        import shutil
        free = shutil.disk_usage(os.path.dirname(os.path.abspath(out_path)) or ".").free
        if free < total + 50 * 1024 * 1024:
            raise MsgError("j_space")
    except OSError:
        pass

    offsets = [0]
    end = (ref.v_last + ref.fd) % MOD33
    for inf in infos[1:]:
        off = (end - inf.v_first) % MOD33
        offsets.append(off)
        end = (inf.v_last + inf.fd + off) % MOD33

    st = _State()
    st.cc = dict(ref.last_cc)
    st.a_end = {p: (ref.a_last[p] + ref.a_dur[p]) % MOD33 for p in ref.apids if p in ref.a_last}
    st.last_pcr = ref.last_pcr
    st.pcr_pending = False
    st.c_ref = ref.c0
    seam_pos = []

    done = [0]

    share = 0.4 if verify else 0.7     # a folyamatjelző első része az összefűzés
    fsp = 0.1 if verify else 0.3       # utána az SPS/PPS ellenőrzés/pótlás

    def step(n):
        done[0] += n
        progress(share * done[0] / float(total))

    tmp = out_path + ".part"
    try:
        with open(tmp, "wb") as fo:
            for idx, inf in enumerate(infos):
                if cancel is not None and cancel.is_set():
                    break
                if idx == 0:
                    log(tr("l_copy", inf.name))
                    left = inf.size // inf.ps * inf.ps
                    with open(inf.path, "rb") as fi:
                        while left > 0:
                            data = fi.read(min(left, 4 * 1024 * 1024))
                            if not data:
                                break
                            left -= len(data)
                            fo.write(data)
                            step(len(data))
                    if inf.H:
                        try:
                            with open(inf.path, "rb") as f0:
                                f0.seek((inf.size // inf.ps - 1) * inf.ps)
                                st.last_ats = _U32.unpack(f0.read(4))[0] & 0x3FFFFFFF
                        except (OSError, struct.error):
                            st.last_ats = None
                    continue
                off = offsets[idx]
                seam_pos.append(fo.tell())
                log(tr("l_off", idx + 1, inf.name, sdiff(off, 0) / 90000.0))
                if not _process_file(inf, off, fo, st, log, step, cancel):
                    break
        if cancel is not None and cancel.is_set():
            os.remove(tmp)
            return False
        psrep = None
        if fix_ps and ref.vtype == 0x1B:
            psrep = ts_fix_paramsets(tmp, infos, seam_pos, lambda f: progress(share + fsp * f),
                                     log, cancel)
            if psrep is None:
                os.remove(tmp)
                return False
            seam_pos = psrep["seam_pos"]
        if verify:
            vres = verify_joined(tmp, infos, offsets, seam_pos,
                                 lambda f: progress(share + fsp + (1.0 - share - fsp) * f),
                                 log, cancel, psrep)
            if vres is None:
                os.remove(tmp)
                return False
            if vres[0]:
                root, ext = os.path.splitext(out_path)
                bad = root + "_HIBAS" + ext
                os.replace(tmp, bad)
                raise MsgError("v_failed", vres[0], bad)
        else:
            log(tr("l_verify_off"))
        os.replace(tmp, out_path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    log(tr("l_done", out_path))
    return True



# ------------------------------------------- SPS/PPS a kulcskockák előtt -----
# H.264 TS / M2TS: a kész kimeneten minden kulcskocka (IDR, vagy I-szeletű visszaállási
# pont) előtt ott kell lennie az SPS-nek és a PPS-nek, hogy a fájl bárhol indítható legyen.
# Ha hiányzik, a program a megfelelő forrásfájl (ill. a folyam korábbi) SPS/PPS-ét
# beszúrja a hozzáférési egység elejére (AUD után), a PES-t újracsomagolja, és a
# videó continuity counter értékeket a beszúrt csomagok után újraszámolja.

PSET_WIN = 4096
_PSET_NULL = bytes([0x47, 0x1F, 0xFF, 0x10]) + b"\xff" * 184


def _sei_recovery(es, a, b):
    """Van-e recovery point (6-os típusú) üzenet a SEI NAL [a, b) tartományában?"""
    p = a
    while p < b - 1:
        t = 0
        while p < b and es[p] == 0xFF:
            t += 255
            p += 1
        if p >= b:
            return False
        t += es[p]
        p += 1
        sz = 0
        while p < b and es[p] == 0xFF:
            sz += 255
            p += 1
        if p >= b:
            return False
        sz += es[p]
        p += 1
        if t == 6:
            return True
        p += sz
        if p < b and es[p] == 0x80:
            return False
    return False


def _h264_lead(es):
    """Egy H.264 hozzáférési egység eleje: (NAL-lista, kulcskocka?) vagy None, ha nincs szelet.
    NAL-lista elem: (típus, a start kód kezdete, a 00 00 01 helye)."""
    n = len(es)
    nals = []
    rec = False
    vcl = None
    j = es.find(b"\x00\x00\x01")
    while 0 <= j and j + 3 < n:
        st = j - 1 if j > 0 and es[j - 1] == 0 else j
        nt = es[j + 3] & 0x1F
        nals.append((nt, st, j))
        if nt in (1, 5):
            vcl = (nt, j)
            break
        nxt = es.find(b"\x00\x00\x01", j + 3)
        if nt == 6 and not rec:
            rec = _sei_recovery(es, j + 4, nxt if nxt >= 0 else n)
        j = nxt
    if vcl is None:
        return None
    key = vcl[0] == 5
    if not key and rec:
        try:
            r = BitReader(unescape(bytes(es[vcl[1] + 4:vcl[1] + 24])))
            r.ue()
            key = (r.ue() % 5) in (2, 4)       # I vagy SI szelet
        except (ValueError, IndexError):
            key = False
    return nals, key


def _pset_plan(nals):
    """(hiányzik az SPS, hiányzik a PPS, beszúrási pozíció az elemi folyamban)."""
    types = [t for t, _, _ in nals]
    ms, mp = 7 not in types, 8 not in types
    if not ms and not mp:
        return False, False, 0
    if ms and mp:
        pos = next((s_ for t, s_, _ in nals if t != 9), nals[-1][1])
    elif mp:
        i = max(k for k, t in enumerate(types) if t == 7)
        pos = nals[i + 1][1]
    else:
        pos = nals[types.index(8)][1]
    return ms, mp, pos


def _pset_nals(es, nals):
    out = {}
    for i, (t, st, j) in enumerate(nals[:-1]):
        if t in (7, 8) and t not in out:
            out[t] = bytes(es[j + 3:nals[i + 1][1]]).rstrip(b"\x00")
    return out


def _pset_scan(path, infos, seam_idx, progress=None, cancel=None):
    """A kimenet kulcskockáinak vizsgálata. None, ha megszakították."""
    progress = progress or (lambda f: None)
    ref = infos[0]
    ps, H, vpid = ref.ps, ref.H, ref.vpid
    v0 = ref.v_first
    total = float(max(1, os.path.getsize(path) // ps))
    rep = {"keys": 0, "find": []}
    seen, anyseen = {}, {}

    def analyze(c):
        lead = _h264_lead(bytes(c["es"]))
        if lead is None:
            return
        nals, key = lead
        if not key:
            return
        rep["keys"] += 1
        part = min(bisect.bisect_right(seam_idx, c["k"]), len(infos) - 1)
        es = bytes(c["es"])
        got = _pset_nals(es, nals)
        sn = seen.setdefault(part, {})
        sn.update(got)
        anyseen.update(got)
        ms, mp, pos = _pset_plan(nals)
        if not (ms or mp):
            return
        ins = b""
        for want, miss in ((7, ms), (8, mp)):
            if not miss:
                continue
            nb = sn.get(want)
            if nb is None:
                nb = infos[part].sps if want == 7 else infos[part].pps
            if nb is None:
                nb = anyseen.get(want)
            if nb is None:
                ins = None
                break
            ins += b"\x00\x00\x00\x01" + nb
        what = "+".join(x for x, m in (("SPS", ms), ("PPS", mp)) if m)
        tstr = "?" if c["ts"] is None else _fmt_t(sdiff(c["ts"], v0) / 90000.0)
        rep["find"].append({"k": c["k"], "pos": pos, "ins": ins, "what": what, "t": tstr})

    k = 0
    cur = None
    with open(path, "rb") as f:
        while True:
            if cancel is not None and cancel.is_set():
                return None
            data = f.read(ps * CHUNK_PACKETS)
            if not data:
                break
            for o in range(0, len(data) - ps + 1, ps):
                t = o + H
                if data[t] != 0x47:
                    raise MsgError("err_sync_k", k)
                if (((data[t + 1] & 0x1F) << 8) | data[t + 2]) == vpid:
                    afc = (data[t + 3] >> 4) & 3
                    if afc & 1:
                        pay = t + 5 + data[t + 4] if afc & 2 else t + 4
                        if pay < t + 188:
                            if data[t + 1] & 0x40:
                                if cur is not None:
                                    analyze(cur)
                                cur = None
                                es0 = _pes_es_start(data, pay, t + 188)
                                if es0 >= 0:
                                    tm = pes_times(data, pay, t + 188)
                                    ts = None if tm is None else (tm[1] if tm[1] is not None else tm[0])
                                    cur = {"k": k, "es": bytearray(data[es0:t + 188]), "ts": ts}
                            elif cur is not None:
                                cur["es"] += data[pay:t + 188]
                            if cur is not None and len(cur["es"]) >= PSET_WIN:
                                analyze(cur)
                                cur = None
                k += 1
            progress(min(1.0, k / total))
    if cur is not None:
        analyze(cur)
    return rep


def _af_core(full_af):
    """Az adaptációs mező lényegi része (jelzők, PCR, OPCR) a hosszbájt és a töltelék nélkül."""
    if len(full_af) <= 1:
        return b""
    afl, fl = full_af[0], full_af[1]
    if fl & 0x07:
        return bytes(full_af[1:])
    ml = 1 + (6 if fl & 0x10 else 0) + (6 if fl & 0x08 else 0)
    return bytes(full_af[1:1 + min(ml, afl)])


def _pset_pkt(tpl, H, core, chunk, cc):
    """Egy TS csomag a sablon fejlécével, a megadott AF-maggal és hasznos adattal."""
    T = 184 - len(chunk)
    afc = 1
    body = b""
    if T:
        afc = 3
        inner = T - 1
        if inner == 0:
            body = b"\x00"
        else:
            c = core if core else b"\x00"
            body = bytes([inner]) + c + b"\xff" * (inner - len(c))
    out = bytearray(tpl[:H])
    out += bytes([tpl[H], tpl[H + 1], tpl[H + 2], (tpl[H + 3] & 0xC0) | (afc << 4) | (cc & 15)])
    out += body
    out += chunk
    return out


def _pset_pes(hold, pos, ins, ps, H, vpid, delta, stat):
    """Egy videó PES (a hold csomaglistában) kiegészítése; (kimeneti csomagok, új csomagok száma)."""
    def is_v(p):
        return (((p[H + 1] & 0x1F) << 8) | p[H + 2]) == vpid

    def bail():
        stat["bad"] += 1
        out = []
        for p in hold:
            if delta and is_v(p):
                p[H + 3] = (p[H + 3] & 0xF0) | (((p[H + 3] & 15) + delta) & 15)
            out.append(p)
        return out, 0

    slots, parts, afs = [], [], []
    for i, p in enumerate(hold):
        if not is_v(p) or not (p[H + 3] >> 4) & 1:
            continue
        if (p[H + 3] >> 4) & 2:
            afl = p[H + 4]
            if H + 5 + afl > H + 188:
                return bail()
            afs.append(bytes(p[H + 4:H + 5 + afl]))
            pay = H + 5 + afl
        else:
            afs.append(b"")
            pay = H + 4
        slots.append(i)
        parts.append(bytes(p[pay:H + 188]))
    if not slots:
        return bail()
    P = b"".join(parts)
    if P[:3] != b"\x00\x00\x01" or not 0xE0 <= P[3] <= 0xEF or len(P) < 9 or (P[6] & 0xC0) != 0x80:
        return bail()
    ip = 9 + P[8] + pos
    if ip > len(P):
        return bail()
    P2 = bytearray(P[:ip] + ins + P[ip:])
    L = (P2[4] << 8) | P2[5]
    if L:
        L += len(ins)
        if L > 0xFFFF:
            L = 0
        P2[4], P2[5] = L >> 8, L & 0xFF
    P2 = bytes(P2)
    m = len(slots)
    cc0 = ((hold[slots[0]][H + 3] & 15) + delta) & 15
    rem, off, seq = len(P2), 0, 0
    built = []
    for si, i in enumerate(slots):
        if rem <= 0:
            return bail()                       # elvileg nem fordulhat elő (csak nőtt az adat)
        if si < m - 1:
            core = afs[si][1:] if len(afs[si]) > 1 else b""
            A = len(afs[si])
        else:
            core = _af_core(afs[si])
            A = (1 + len(core)) if core else 0
        take = min(184 - A, rem)
        chunk = P2[off:off + take]
        off += take
        rem -= take
        if take == 184 - A and si < m - 1:
            # nem utolsó csomag: az eredeti AF-et (töltelékkel együtt) változatlanul hagyjuk
            built.append(_pset_pkt_keep(hold[i], H, afs[si], chunk, (cc0 + seq) & 15))
        else:
            built.append(_pset_pkt(hold[i], H, core, chunk, (cc0 + seq) & 15))
        seq += 1
    extras = []
    tpl = bytearray(hold[slots[-1]])
    tpl[H + 1] &= 0xBF                           # nincs payload_unit_start
    while rem > 0:
        take = min(184, rem)
        extras.append(_pset_pkt(tpl, H, b"", P2[off:off + take], (cc0 + seq) & 15))
        off += take
        rem -= take
        seq += 1
    spos = {i: n for n, i in enumerate(slots)}
    d = delta
    outp = []
    for i, p in enumerate(hold):
        if i in spos:
            outp.append(built[spos[i]])
            if i == slots[-1]:
                outp.extend(extras)
                d += len(extras)
        else:
            if is_v(p):
                p[H + 3] = (p[H + 3] & 0xF0) | (((p[H + 3] & 15) + d) & 15)
            outp.append(p)
    stat["packets"] += len(extras)
    stat["bytes"] += len(ins)
    return outp, len(extras)


def _pset_pkt_keep(tpl, H, full_af, chunk, cc):
    out = bytearray(tpl[:H])
    afc = 3 if full_af else 1
    out += bytes([tpl[H], tpl[H + 1], tpl[H + 2], (tpl[H + 3] & 0xC0) | (afc << 4) | (cc & 15)])
    out += full_af
    out += chunk
    return out


def _pset_rewrite(path, ref, fixes, dst, progress=None, cancel=None):
    """A kimenet átírása: a fixes {csomagindex: (pozíció, beszúrandó bájtok)} szerinti PES-ek
    kiegészítésével. {"events": [(csomagindex, új csomagok)], ...} vagy None (megszakítva)."""
    progress = progress or (lambda f: None)
    ps, H, vpid = ref.ps, ref.H, ref.vpid
    total = float(max(1, os.path.getsize(path) // ps))
    fk = sorted(fixes)
    events = []
    stat = {"packets": 0, "bytes": 0, "bad": 0}
    delta = 0
    k = 0
    hold = None
    hold_fix = None
    with open(path, "rb") as fi, open(dst, "wb") as fo:
        def flush():
            nonlocal hold, hold_fix, delta
            outp, added = _pset_pes(hold, hold_fix[1], hold_fix[2], ps, H, vpid, delta, stat)
            for q in outp:
                fo.write(q)
            if added:
                events.append((hold_fix[0], added))
                delta = (delta + added) & 15
            hold = hold_fix = None

        while True:
            if cancel is not None and cancel.is_set():
                return None
            data = fi.read(ps * CHUNK_PACKETS)
            if not data:
                break
            n = len(data) // ps
            i0 = bisect.bisect_left(fk, k)
            nxt = fk[i0] if i0 < len(fk) else None
            if hold is None and delta == 0 and (nxt is None or nxt >= k + n):
                fo.write(data)
                k += n
                progress(min(1.0, k / total))
                continue
            for i in range(n):
                o = i * ps
                pkt = bytearray(data[o:o + ps])
                if pkt[H] != 0x47:
                    raise MsgError("err_sync_k", k)
                b1 = pkt[H + 1]
                is_v = (((b1 & 0x1F) << 8) | pkt[H + 2]) == vpid
                if hold is not None:
                    if is_v and (b1 & 0x40):
                        flush()
                    else:
                        hold.append(pkt)
                        k += 1
                        continue
                if is_v and (b1 & 0x40) and k in fixes:
                    hold = [pkt]
                    hold_fix = (k,) + tuple(fixes[k])
                    k += 1
                    continue
                if delta and is_v:
                    pkt[H + 3] = (pkt[H + 3] & 0xF0) | (((pkt[H + 3] & 15) + delta) & 15)
                fo.write(pkt)
                k += 1
            if len(data) % ps:
                fo.write(data[n * ps:])
            progress(min(1.0, k / total))
        if hold is not None:
            flush()
    return {"events": events, "added": stat["packets"], "bytes": stat["bytes"], "bad": stat["bad"]}


def ts_fix_paramsets(path, infos, seam_pos, progress=None, log=None, cancel=None, fix=True):
    """A kimeneten minden kulcskocka előtt ellenőrzi az SPS/PPS meglétét, és (fix=True esetén)
    pótolja, ha hiányzik. Jelentés (dict) vagy None, ha megszakították."""
    log = log or (lambda s: None)
    progress = progress or (lambda f: None)
    ref = infos[0]
    ps = ref.ps
    seam_idx = [p // ps for p in seam_pos]
    log(tr("l_pset_scan"))
    sc = _pset_scan(path, infos, seam_idx, lambda f: progress(0.45 * f), cancel)
    if sc is None:
        return None
    miss = sc["find"]
    rep = {"keys": sc["keys"], "missing": len(miss), "fixed": 0, "added": 0, "bytes": 0,
           "left": [(m["what"], m["t"]) for m in miss], "seam_pos": list(seam_pos)}
    if not miss:
        log(tr("l_pset_ok", sc["keys"]))
        progress(1.0)
        return rep
    log(tr("l_pset_miss", len(miss), sc["keys"]))
    if not fix:
        progress(1.0)
        return rep
    fixes = {m["k"]: (m["pos"], m["ins"]) for m in miss if m["ins"] is not None}
    if len(fixes) < len(miss):
        log(tr("l_pset_nosrc", len(miss) - len(fixes)))
    if not fixes:
        progress(1.0)
        return rep
    tmp = path + ".psfix"
    try:
        r = _pset_rewrite(path, ref, fixes, tmp, lambda f: progress(0.45 + 0.35 * f), cancel)
        if r is None:
            os.remove(tmp)
            return None
        new_idx = [q + sum(a for kk, a in r["events"] if kk < q) for q in seam_idx]
        sc2 = _pset_scan(tmp, infos, new_idx, lambda f: progress(0.8 + 0.2 * f), cancel)
        if sc2 is None:
            os.remove(tmp)
            return None
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    left = sc2["find"]
    rep.update(keys=sc2["keys"], fixed=len(miss) - len(left), added=r["added"], bytes=r["bytes"],
               left=[(m["what"], m["t"]) for m in left], seam_pos=[q * ps for q in new_idx])
    log(tr("l_pset_done", rep["fixed"], r["added"], r["bytes"]))
    progress(1.0)
    return rep


# ------------------------------------------------------------ ellenőrzés ---
# Az összefűzött fájlt a kész kimenetről olvassa vissza (nem a forrásokból),
# és csak a Python standard könyvtárát használja.

V_CHECKS = ("struct", "cc", "pcr", "ats", "vts", "vseam", "pset", "audio", "sync")
MAX_SHOWN = 10             # ellenőrzésenként ennyi problémát ír ki részletesen
PCR_MAX = 10800            # 120 ms (a szabvány 100 ms-ot enged)
M30 = 0x3FFFFFFF
HALF30 = 1 << 29


def _fmt_t(sec):
    sec = max(0.0, sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return "%d:%02d:%06.3f" % (h, m, s)


def _crc16_table():
    tab = []
    for i in range(256):
        c = i << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x8005) if c & 0x8000 else (c << 1)
            c &= 0xFFFF
        tab.append(c)
    return tab


_AC3_TAB = _crc16_table()


def ac3_crc_ok(fr):
    """AC-3 keret CRC-je: a szinkronszó utáni teljes keret CRC-je 0 kell legyen."""
    crc = 0
    tab = _AC3_TAB
    for b in fr[2:]:
        crc = ((crc << 8) & 0xFFFF) ^ tab[(crc >> 8) ^ b]
    return crc == 0


def ac3_frame_bytes(b4):
    """Az AC-3 keret mérete bájtban (fscod + frmsizecod bájtból)."""
    fscod, frm = b4 >> 6, b4 & 0x3F
    if fscod > 2 or (frm >> 1) >= 19:
        return None
    kbps = AC3_RATES[frm >> 1]
    if fscod == 0:
        words = kbps * 2
    elif fscod == 2:
        words = kbps * 3
    else:
        words = (kbps * 960) // 441 + (frm & 1)
    return words * 2


def _nal_kinds(es):
    """H.264: 'idr' / 'rec' (recovery point SEI) / 'none' a kép elején."""
    kinds = set()
    j = es.find(b"\x00\x00\x01")
    while 0 <= j < len(es) - 3:
        nt = es[j + 3] & 0x1F
        kinds.add(nt)
        if nt == 6 and j + 4 < len(es) and es[j + 4] == 6:
            kinds.add("rec")
        j = es.find(b"\x00\x00\x01", j + 3)
    if 5 in kinds:
        return "idr"
    if "rec" in kinds:
        return "rec"
    return "none"


def _unwrap(vals):
    out = [vals[0]]
    for a, b in zip(vals, vals[1:]):
        out.append(out[-1] + sdiff(b, a))
    return out


def verify_joined(path, infos, offsets, seam_pos, progress=None, log=None, cancel=None, psrep=None):
    """Az összefűzött fájl ellenőrzése. (hibák, figyelmeztetések) vagy None, ha megszakították.

    infos     - a forrásfájlok elemzett adatai (FileInfo)
    offsets   - a join által használt időeltolások
    seam_pos  - az egyes (2., 3., ...) fájlok kezdőbájtja a kimenetben
    """
    log = log or (lambda s: None)
    progress = progress or (lambda f: None)
    ref = infos[0]
    ps, H = ref.ps, ref.H
    nseg = len(infos)
    vpid, apids = ref.vpid, list(ref.apids)
    apset = set(apids)
    pcr_pid = ref.pcr_pid
    size = os.path.getsize(path)
    seam_idx = [p // ps for p in seam_pos]
    v0 = ref.v_first
    res = {k: [0, 0] for k in V_CHECKS}
    shown = Counter()

    def tpos(ts):
        return _fmt_t(sdiff(ts, v0) / 90000.0)

    def issue(chk, sev, key, *a):
        res[chk][0 if sev == "E" else 1] += 1
        shown[chk] += 1
        if shown[chk] <= MAX_SHOWN:
            log("   %s %s" % ("✗" if sev == "E" else "!", tr(key, *a)))
        elif shown[chk] == MAX_SHOWN + 1:
            log(tr("v_more", tr("vc_" + chk)))

    log(tr("v_head", len(seam_idx)))
    log(tr("v_what"))
    for key in V_CHECKS:
        log("   • %s: %s" % (tr("vc_" + key), tr("vd_" + key)))
    log(tr("v_pass1"))

    # ---------------- 1. menet: a fájl végigolvasása ----------------
    cur = [v0]                      # a legutóbbi videó DTS (a helyjelzéshez)
    cc_last = {}
    seen_seg = set()
    seg = 0
    seam_ptr = 0
    next_seam = seam_idx[0] if seam_idx else -1
    last_pcr = last_ats = None
    pcr_wait = ats_wait = False
    seaminfo = {s: {} for s in range(1, nseg)}
    vts = []                        # (dts, pts, csomag, szakasz)
    alist = {p: [] for p in apids}  # (pts, csomag, szakasz)
    acur = {}
    seg_vfirst = {}
    vs = {"cap": None}
    vidr = {}
    vcap_seen = set()
    cs = {"ok": 0, "tot": 0, "trusted": None}
    ring = {p: deque(maxlen=6) for p in apids}
    a_cnt = Counter()
    last_sg = {}
    S = _U32

    def crc_frames(tp, es, frames):
        for fi, fs in frames:
            if not ac3_crc_ok(es[fi:fi + fs]):
                issue("audio", "E", "v_a_crc", tp)
                return

    def fin_audio(pid, rec, last=False):
        buf, pts, pkt, sg = rec
        sev = "W" if last else "E"
        tp = tpos(pts)
        if len(buf) < 9 or len(buf) < 9 + buf[8]:
            issue("audio", sev, "v_a_pes", tp, len(buf), 0)
            return
        plen = (buf[4] << 8) | buf[5]
        if plen and len(buf) != plen + 6:
            issue("audio", sev, "v_a_pes", tp, len(buf), plen + 6)
        if ref.atypes.get(pid) != 0x81:
            return
        es = bytes(buf[9 + buf[8]:])
        frames, i = [], 0
        while i < len(es):
            if es[i:i + 2] != b"\x0b\x77":
                issue("audio", sev, "v_a_sync", tp)
                break
            fs = ac3_frame_bytes(es[i + 4]) if i + 5 <= len(es) else None
            if not fs:
                issue("audio", sev, "v_a_hdr", tp)
                break
            if i + fs > len(es):
                issue("audio", sev, "v_a_cut", tp)
                break
            frames.append((i, fs))
            i += fs
        if cs["trusted"] is None:
            # kalibráció: a fájl elején lévő (biztosan ép) kereteken igazoljuk a CRC-módszert
            for fi, fs in frames:
                cs["tot"] += 1
                cs["ok"] += ac3_crc_ok(es[fi:fi + fs])
            if cs["tot"] >= 30:
                cs["trusted"] = cs["ok"] == cs["tot"]
                log(tr("v_crc_info", tr("v_crc_on" if cs["trusted"] else "v_crc_off")))
        elif cs["trusted"]:
            if pid in last_sg and sg != last_sg[pid]:
                for item in ring[pid]:          # az előző rész utolsó keretei
                    crc_frames(*item)
            if a_cnt[(pid, sg)] < 6:            # az új rész első keretei
                crc_frames(tp, es, frames)
        a_cnt[(pid, sg)] += 1
        last_sg[pid] = sg
        ring[pid].append((tp, es, frames))

    def finish_vcap():
        cap = vs["cap"]
        vs["cap"] = None
        b, sg = cap
        if len(b) < 9 or len(b) < 9 + b[8]:
            vidr[sg] = "none"
        else:
            vidr[sg] = _nal_kinds(bytes(b[9 + b[8]:]))

    if size % ps:
        issue("struct", "E", "v_size", size % ps)
    total_pk = max(1, size // ps)
    k = 0
    aborted = False
    with open(path, "rb") as f:
        while not aborted:
            data = f.read(ps * CHUNK_PACKETS)
            if not data:
                break
            if cancel is not None and cancel.is_set():
                return None
            for o in range(0, len(data) - ps + 1, ps):
                t = o + H
                if k == next_seam:
                    seg += 1
                    seam_ptr += 1
                    next_seam = seam_idx[seam_ptr] if seam_ptr < len(seam_idx) else -1
                    seen_seg.clear()
                    pcr_wait = ats_wait = True
                if data[t] != 0x47:
                    issue("struct", "E", "v_sync", k)
                    aborted = True
                    break
                # ATS (minden csomagra, a null csomagokra is)
                if H:
                    a = S.unpack_from(data, o)[0] & M30
                    if last_ats is not None:
                        d = (a - last_ats) & M30
                        if ats_wait:
                            ats_wait = False
                            g = d - (M30 + 1) if d >= HALF30 else d
                            seaminfo[seg]["ats"] = g / 27000.0
                            if g < 0 or g > 27000000:
                                issue("ats", "W", "v_ats_seam", seg, g / 27000.0)
                        elif d >= HALF30 or d > 27000000:
                            issue("ats", "W", "v_ats", tpos(cur[0]))
                    last_ats = a
                b1 = data[t + 1]
                pid = ((b1 & 0x1F) << 8) | data[t + 2]
                if pid == 0x1FFF:
                    k += 1
                    continue
                b3 = data[t + 3]
                afc = (b3 >> 4) & 3
                afl = data[t + 4] if afc & 2 else 0
                pay = -1
                if afc & 2:
                    if afc & 1:
                        pay = t + 5 + afl
                elif afc & 1:
                    pay = t + 4
                if pay > t + 188:
                    pay = -1
                # continuity counter
                if afc & 1:
                    c = b3 & 15
                    last = cc_last.get(pid)
                    disc = (afc & 2) and afl > 0 and (data[t + 5] & 0x80)
                    if last is not None and not disc and c != ((last + 1) & 15):
                        if seg > 0:
                            # a 2., 3., ... fájl számlálóit az összefűző számolja újra,
                            # tehát itt a hiba nem a forrásból ered
                            issue("cc", "E", "v_cc_seam", seg + 1, pid, tpos(cur[0]))
                        else:
                            issue("cc", "W", "v_cc", pid, tpos(cur[0]))
                    cc_last[pid] = c
                    seen_seg.add(pid)
                # PCR
                if pid == pcr_pid and (afc & 2) and afl >= 7 and (data[t + 5] & 0x10):
                    q = t + 6
                    base = ((data[q] << 25) | (data[q + 1] << 17) | (data[q + 2] << 9) |
                            (data[q + 3] << 1) | (data[q + 4] >> 7))
                    flagged = bool(data[t + 5] & 0x80)
                    if last_pcr is not None:
                        d = sdiff(base, last_pcr)
                        if pcr_wait:
                            pcr_wait = False
                            seaminfo[seg]["pcr"] = (d / 90.0, flagged)
                            if flagged:
                                pass
                            elif d < 0 or d > 45000:
                                issue("pcr", "E", "v_pcr_seam", seg, d / 90.0)
                            elif d > PCR_MAX:
                                issue("pcr", "W", "v_pcr_seam_w", seg, d / 90.0)
                        elif not flagged and (d < 0 or d > PCR_MAX):
                            issue("pcr", "W", "v_pcr", d / 90.0, tpos(cur[0]))
                    last_pcr = base
                # PES: videó és hang
                if pid == vpid or pid in apset:
                    pusi = bool(b1 & 0x40)
                    if pay >= 0 and pid == vpid and seg not in seg_vfirst:
                        seg_vfirst[seg] = pusi
                    if pusi and pay >= 0 and pay + 14 <= t + 188:
                        tm = pes_times(data, pay, t + 188)
                        if tm is None:
                            issue("struct", "W", "v_pes", pid, tpos(cur[0]))
                        elif pid == vpid:
                            if vs["cap"] is not None:
                                finish_vcap()
                            dts = tm[1] if tm[1] is not None else tm[0]
                            vts.append((dts, tm[0], k, seg))
                            cur[0] = dts
                            if seg not in vcap_seen and seg_vfirst.get(seg):
                                vcap_seen.add(seg)
                                vs["cap"] = [bytearray(), seg]
                        else:
                            rec = acur.get(pid)
                            if rec is not None:
                                fin_audio(pid, rec)
                            acur[pid] = [bytearray(data[pay:t + 188]), tm[0], k, seg]
                            alist[pid].append((tm[0], k, seg))
                    if pay >= 0:
                        if pid == vpid:
                            if vs["cap"] is not None:
                                vs["cap"][0] += data[pay:t + 188]
                                if len(vs["cap"][0]) >= 4096:
                                    finish_vcap()
                        else:
                            rec = acur.get(pid)
                            if rec is not None and not (b1 & 0x40):
                                rec[0] += data[pay:t + 188]
                k += 1
            progress(min(1.0, k / float(total_pk)))
    if vs["cap"] is not None:
        finish_vcap()
    for pid, rec in acur.items():
        fin_audio(pid, rec, last=True)
    if cs["trusted"] is None and apids and ref.atypes.get(apids[0]) == 0x81:
        log(tr("v_crc_info", tr("v_crc_off")))
    if aborted:
        return _verify_summary(res, log)

    # ---------------- 2. menet: videó időzítés ----------------
    log(tr("v_pass2"))
    fd = ref.fd

    def is_cont(sg):
        return ((not seg_vfirst.get(sg, True)) or
                (sg > 0 and (abs(sdiff(offsets[sg], 0)) <= 2 * fd or ts_is_cont(infos[sg - 1], infos[sg]))))

    tol = 2
    vgap = {}
    if len(vts) < 2:
        issue("vts", "E", "v_novid")
    else:
        u = _unwrap([x[0] for x in vts])
        up = [u[i] + sdiff(vts[i][1], vts[i][0]) for i in range(len(vts))]
        first_in_seg = {}
        for i, x in enumerate(vts):
            first_in_seg.setdefault(x[3], i)
        seam_t = {sg: (u[i] - u[0]) / 90000.0 for sg, i in first_in_seg.items() if sg > 0}
        for i in range(1, len(vts)):
            dl = u[i] - u[i - 1]
            if abs(dl - fd) > tol:
                tp = _fmt_t((u[i] - u[0]) / 90000.0)
                if vts[i][3] != vts[i - 1][3]:
                    issue("vts", "E", "v_v_seam", vts[i][3], tp, (dl - fd) / float(fd), (dl - fd) / 90.0)
                else:
                    issue("vts", "W", "v_v_gap", (dl - fd) / float(fd), tp)
            if vts[i][3] != vts[i - 1][3]:
                vgap[vts[i][3]] = (dl - fd) / 90.0
        for i in range(len(vts)):
            if up[i] < u[i]:
                issue("vts", "E", "v_pts_lt", _fmt_t((u[i] - u[0]) / 90000.0))
        sp = sorted(up)
        for i in range(1, len(sp)):
            dl = sp[i] - sp[i - 1]
            if abs(dl - fd) > tol:
                ts = (sp[i] - sp[0]) / 90000.0
                near = any(abs(ts - st_) < 1.0 for st_ in seam_t.values())
                issue("vts", "E" if near else "W", "v_p_gap", (dl - fd) / float(fd), _fmt_t(ts))
        for sg in range(nseg):
            if sg in first_in_seg:
                want = (infos[sg].v_first + (offsets[sg] if sg else 0)) % MOD33
                got = vts[first_in_seg[sg]][0]
                if got != want:
                    issue("vts", "E", "v_off", sg + 1, sdiff(got, want) / 90.0)
        exp = sum(i.duration for i in infos)
        got = (u[-1] + fd - u[0]) / 90000.0
        if abs(got - exp) > 1.5 * fd / 90000.0:
            issue("vts", "E", "v_dur", _fmt_t(exp), _fmt_t(got))
        # varratok: tiszta kezdés?
        # Folytatólagos (megosztott) fájlnál az időeltolás ~0, vagy a fájl egy félbevágott
        # képkocka közepén kezdődik: ott nem kell IDR, mert a GOP az előző fájlból folytatódik.
        if ref.vtype != 0x1B:
            log("   " + tr("v_idr_na"))
        else:
            for sg in range(nseg):
                if is_cont(sg):
                    continue
                kind = vidr.get(sg)
                if kind == "none":
                    issue("vseam", "W", "v_idr_none", sg)

    # ---------------- SPS/PPS a kulcskockák előtt ----------------
    if ref.vtype != 0x1B:
        log("   " + tr("v_pset_na"))
    else:
        if psrep is None:
            psrep = ts_fix_paramsets(path, infos, seam_pos, None, log, cancel, fix=False)
            if psrep is None:
                return None
        for what, tp in psrep["left"]:
            issue("pset", "E", "v_pset_miss", what, tp)
        if psrep["fixed"]:
            log("   " + tr("v_pset_fixed", psrep["fixed"]))

    # ---------------- 3. menet: hang és A/V szinkron ----------------
    log(tr("v_pass3"))
    agap = {}
    for pid in apids:
        lst = alist[pid]
        if not lst:
            issue("audio", "E", "v_a_none", pid)
            continue
        adur = ref.a_dur[pid]
        atol = 2 + adur // 100
        u = _unwrap([x[0] for x in lst])
        for i in range(1, len(lst)):
            g = u[i] - u[i - 1] - adur
            if lst[i][2] != lst[i - 1][2]:
                sg = lst[i][2]
                agap.setdefault(sg, g / 90.0)
                if abs(g) <= adur // 2 + atol:
                    pass
                elif abs(g) <= adur:
                    issue("audio", "W", "v_a_seam_w", sg, g / 90.0)
                elif abs(g) <= 90000:
                    issue("audio", "W", "v_a_seam_g", sg, g / 90.0)
                else:
                    issue("audio", "E", "v_a_seam_e", sg, g / 90.0)
            elif abs(g) > atol:
                issue("audio", "W", "v_a_step", g / 90.0, tpos(lst[i][0]))
        first_a = {}
        for x in lst:
            first_a.setdefault(x[2], x)
        for sg in range(nseg):
            x = first_a.get(sg)
            if x is None:
                issue("sync", "E", "v_s_noaudio", sg + 1)
                continue
            src = infos[sg].a_first.get(pid)
            if src is None:
                continue
            off = offsets[sg] if sg else 0
            g = sdiff((x[0] - off) % MOD33, src)
            n = int(round(g / float(adur)))
            resid = g - n * adur
            if g < -atol or abs(resid) > atol + abs(n) // 2 + 1:
                issue("sync", "E", "v_s_grid", sg + 1, resid / 90.0)
            elif n > 5:
                issue("sync", "W", "v_s_many", sg, n)

    # varratonkénti összegzés
    if 0 < nseg - 1 <= 40:
        log(tr("v_seam_hdr"))
        for sg in range(1, nseg):
            info = seaminfo.get(sg, {})
            pc = info.get("pcr")
            ptxt = "-" if pc is None else ("%+.1f ms%s" % (pc[0], " (%s)" % tr("v_flag") if pc[1] else ""))
            atxt = "-" if sg not in agap else "%+.1f ms" % agap[sg]
            if ref.vtype != 0x1B:
                itxt = tr("v_idr_unk")
            elif is_cont(sg):
                itxt = tr("v_idr_cont")
            else:
                itxt = tr("v_idr_ok") if vidr.get(sg) in ("idr", "rec") else tr("v_idr_unk")
            tp = _fmt_t(sum(infos[j].duration for j in range(sg)))
            log(tr("v_seam_line", sg, tp, vgap.get(sg, 0.0), atxt, ptxt, itxt))
    return _verify_summary(res, log)


def _verify_summary(res, log, checks=V_CHECKS, pfx="vc_"):
    log(tr("v_res_head"))
    te = tw = 0
    for key in checks:
        e, w = res[key]
        te += e
        tw += w
        mark = "✗" if e else ("!" if w else "✓")
        log("   %s %s: %s" % (mark, tr(pfx + key), tr("v_cnt", e, w) if (e or w) else tr("v_ok")))
    if te:
        log(tr("v_final_bad", te, tw))
    elif tw:
        log(tr("v_final_warn", tw))
    else:
        log(tr("v_final_perfect"))
    return te, tw


# ============================================================ MPEG-PS / VOB ==
# Veszteségmentes MPEG Program Stream (.mpg / .mpeg / .mod) és DVD VOB összefűzés.
# A kép-, hang- és felirat-adat bájtra azonosan másolódik; csak az órák (SCR) és az
# időbélyegek (PTS / DTS) tolódnak el, a VOB NAV-csomagjaiban a hozzájuk tartozó mezők
# is. Csak a Python standard könyvtárát használja. A kód a nyilvános szabványok alapján
# készült (ISO/IEC 11172-1/-2/-3, ISO/IEC 13818-1/-2, ATSC A/52, a DVD-Video fájlok
# nyilvánosan dokumentált szerkezete); más projektből kód nem került át.

MPG_EXTS = (".mpg", ".mpeg", ".mpe", ".m2p", ".mod")
VOB_EXTS = (".vob",)
PS_BLOCK = 4 * 1024 * 1024
PS_SECTOR = 2048
PS_CHECKS = ("struct", "scr", "data", "timing", "vseam", "audio", "sync")
VOB_CHECKS = PS_CHECKS + ("nav",)
PS_END = b"\x00\x00\x01\xb9"
PS_PACK = b"\x00\x00\x01\xba"
M32 = 0xFFFFFFFF
SCR_MOD = MOD33 * 300

# frame_rate_code -> (számláló, nevező)   (ISO/IEC 13818-2, 6.3.3)
MPV_FPS = {1: (24000, 1001), 2: (24, 1), 3: (25, 1), 4: (30000, 1001), 5: (30, 1),
           6: (50, 1), 7: (60000, 1001), 8: (60, 1)}
# MPEG audio: bitráta-táblák kbps-ben [verzió-csoport][réteg][index]  (ISO/IEC 11172-3)
_MPA_BR = {
    (1, 1): (32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448),
    (1, 2): (32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384),
    (1, 3): (32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
    (2, 1): (32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256),
    (2, 2): (8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
    (2, 3): (8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
}
_MPA_FS = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}


# ------------------------------------------------------------ alapfüggvények --

def ps_is_audio(k):
    return 0xC0 <= k <= 0xDF or 0xBD80 <= k <= 0xBDBF


def ps_is_spu(k):
    return 0xBD20 <= k <= 0xBD3F


def ps_sub_hdr(k):
    """A private_stream_1 alfolyam-fejlécének mérete bájtban (a PES fejléc után)."""
    if 0xBD80 <= k <= 0xBD9F:
        return 4          # AC-3 / DTS / SDDS: azonosító, keretszám, 2 bájt mutató
    if 0xBDA0 <= k <= 0xBDA7:
        return 7          # LPCM
    if 0xBD00 <= k <= 0xBDFF:
        return 1
    return 0


def ps_key_name(k):
    if 0xE0 <= k <= 0xEF:
        return "MPEG video"
    if 0xC0 <= k <= 0xDF:
        return "MPEG audio"
    if 0xBD80 <= k <= 0xBD87:
        return "AC3"
    if 0xBD88 <= k <= 0xBD8F:
        return "DTS"
    if 0xBD90 <= k <= 0xBD9F:
        return "SDDS"
    if 0xBDA0 <= k <= 0xBDA7:
        return "LPCM"
    if ps_is_spu(k):
        return "SPU"
    return "0x%X" % k


def ps_rd_scr2(b, p):
    """MPEG-2 pack fejléc SCR-je: (alap 33 bit, kiterjesztés 9 bit). p a 00 00 01 BA helye."""
    b4, b5, b6, b7, b8, b9 = b[p + 4], b[p + 5], b[p + 6], b[p + 7], b[p + 8], b[p + 9]
    base = (((b4 >> 3) & 7) << 30) | ((b4 & 3) << 28) | (b5 << 20) | \
           ((b6 >> 3) << 15) | ((b6 & 3) << 13) | (b7 << 5) | (b8 >> 3)
    return base, ((b8 & 3) << 7) | (b9 >> 1)


def ps_wr_scr2(b, p, v):
    b[p + 4] = (b[p + 4] & 0xC4) | (((v >> 30) & 7) << 3) | ((v >> 28) & 3)
    b[p + 5] = (v >> 20) & 0xFF
    b[p + 6] = (((v >> 15) & 0x1F) << 3) | 4 | ((v >> 13) & 3)
    b[p + 7] = (v >> 5) & 0xFF
    b[p + 8] = ((v & 0x1F) << 3) | 4 | (b[p + 8] & 3)


def ps_pack(buf, p, end, final):
    """Egy PS csomag (pack) szerkezete a buf[p:end] ablakban.

    None -> több adat kell (csak ha nem a fájl vége);
    (0, q, mp2, pes) -> pack buf[p:q]; pes = [(pos, sid, hossz), ...]
    (1, q, 0, None)  -> program_end_code
    (2, q, 0, None)  -> felismerhetetlen rész buf[p:q] (eldobandó)"""
    if end - p < 4:
        return (2, end, 0, None) if final else None
    if buf[p] != 0 or buf[p + 1] != 0 or buf[p + 2] != 1 or buf[p + 3] not in (0xBA, 0xB9):
        i = buf.find(PS_PACK, p + 1, end)
        j = buf.find(PS_END, p + 1, end)
        if i < 0 or (0 <= j < i):
            i = j
        if i < 0:
            if final:
                return (2, end, 0, None)
            return (2, max(p + 1, end - 3), 0, None)
        return (2, i, 0, None)
    if buf[p + 3] == 0xB9:
        return (1, p + 4, 0, None)
    if end - p < 14:
        return (2, end, 0, None) if final else None
    b4 = buf[p + 4]
    if (b4 >> 6) == 1:
        mp2 = True
        r = p + 14 + (buf[p + 13] & 7)
    elif (b4 >> 4) == 2:
        mp2 = False
        r = p + 12
    else:
        return (2, p + 1, 0, None)
    pes = []
    while True:
        if end - r < 4:
            if final:
                return (0, end, mp2, pes)
            return None
        if buf[r] == 0 and buf[r + 1] == 0 and buf[r + 2] == 1:
            sid = buf[r + 3]
            if sid == 0xBA or sid == 0xB9:
                return (0, r, mp2, pes)
            if sid < 0xBB:
                i = buf.find(PS_PACK, r + 1, end)
                if i < 0:
                    if final:
                        return (0, end, mp2, pes)
                    return None
                return (0, i, mp2, pes)
            if end - r < 6:
                if final:
                    return (0, r, mp2, pes)
                return None
            ln = (buf[r + 4] << 8) | buf[r + 5]
            if sid == 0xBB:
                r += 6 + ln
                continue
            if ln == 0 and 0xE0 <= sid <= 0xEF:
                nxt = buf.find(PS_PACK, r + 6, end)
                if nxt < 0:
                    if not final:
                        return None
                    nxt = end
                tot = nxt - r
            else:
                tot = 6 + ln
            if r + tot > end:
                if final:
                    return (0, r, mp2, pes)
                return None
            pes.append((r, sid, tot))
            r += tot
        else:
            nxt = buf.find(b"\x00\x00\x01", r, end)
            if nxt < 0:
                if final:
                    return (0, end, mp2, pes)
                return None
            r = nxt


def ps_pes(buf, r, tot):
    """PES fejléc: (adat_kezdet, pts, dts, pts_hely, dts_hely, titkosított)."""
    e = r + tot
    sid = buf[r + 3]
    if sid in NO_HDR_IDS:
        return r + 6, None, None, -1, -1, False
    if tot < 9:
        return e, None, None, -1, -1, False
    b6 = buf[r + 6]
    if (b6 & 0xC0) == 0x80:                       # MPEG-2 PES fejléc
        fl = buf[r + 7] >> 6
        hl = buf[r + 8]
        he = min(e, r + 9 + hl)
        pts = dts = None
        pp = dp = -1
        if (fl & 2) and hl >= 5 and r + 14 <= e:
            pts, pp = rd_ts(buf, r + 9), r + 9
            if fl == 3 and hl >= 10 and r + 19 <= e:
                dts, dp = rd_ts(buf, r + 14), r + 14
        return he, pts, dts, pp, dp, bool(b6 & 0x30)
    q = r + 6                                     # MPEG-1 PES fejléc
    while q < e and buf[q] == 0xFF and q < r + 22:
        q += 1
    if q < e and (buf[q] & 0xC0) == 0x40:
        q += 2
    if q >= e:
        return e, None, None, -1, -1, False
    c = buf[q] >> 4
    if c == 2 and q + 5 <= e:
        return q + 5, rd_ts(buf, q), None, q, -1, False
    if c == 3 and q + 10 <= e:
        return q + 10, rd_ts(buf, q), rd_ts(buf, q + 5), q, q + 5, False
    if buf[q] == 0x0F:
        return q + 1, None, None, -1, -1, False
    return q, None, None, -1, -1, False


def ps_key(buf, sid, hdr_end, e):
    if sid == 0xBD and hdr_end < e:
        return 0xBD00 | buf[hdr_end]
    return sid


def parse_mpa(b):
    """MPEG audio fejléc keresése: {fs, ch, kbps, layer, spf} vagy None."""
    n = len(b)
    for i in range(min(n - 4, 2048)):
        if b[i] != 0xFF or (b[i + 1] & 0xE0) != 0xE0:
            continue
        ver, lay = (b[i + 1] >> 3) & 3, (b[i + 1] >> 1) & 3
        bri, fsi = b[i + 2] >> 4, (b[i + 2] >> 2) & 3
        if ver == 1 or lay == 0 or bri in (0, 15) or fsi == 3:
            continue
        grp = 1 if ver == 3 else 2
        layer = 4 - lay
        spf = 384 if layer == 1 else (1152 if (layer == 2 or ver == 3) else 576)
        return {"fs": _MPA_FS[ver][fsi], "ch": "1.0" if (b[i + 3] >> 6) == 3 else "2.0",
                "kbps": _MPA_BR[(grp, layer)][bri - 1], "layer": layer, "spf": spf}
    return None


def parse_lpcm(b):
    """DVD LPCM alfolyam-fejléc (7 bájt): {fs, bits, ch} vagy None."""
    if len(b) < 7:
        return None
    q, f = (b[5] >> 6) & 3, (b[5] >> 4) & 3
    if q > 2 or f > 1:
        return None
    return {"fs": (48000, 96000)[f], "bits": (16, 20, 24)[q], "ch": (b[5] & 7) + 1}


# ------------------------------------------------------- MPEG-1/2 videó elemző --

class VScan:
    """Az MPEG-1/2 videó elemi folyam kép- és GOP-szintű időzítése.

    Minden GOP-ra kiszámolja a megjelenítési kezdő- és végidőt (90 kHz, tört is lehet):
    a PTS-szel ellátott első kép és az időrendi sorszámok (temporal_reference) alapján."""

    def __init__(self, tail=False):
        self.buf = bytearray()
        self.abs0 = 0
        self.anch = deque()
        self.last_pic = -1
        self.seq = None            # dict a sorozatfejlécből
        self.fd = None             # képidő 90 kHz-en (float)
        self.mp2 = False
        self.prog = False
        self.groups = []           # (kezdet, vég, horgonyos, zárt, képszám, első_típus, vezető_képek)
        self.cur = None
        self.cur_pic = None
        self.prev_end = None
        self.wait = tail           # farok: az első GOP-fejlécig eldobjuk az adatot
        self.pics = 0
        self.first_type = None

    def feed(self, data, pts):
        start = self.abs0 + len(self.buf)
        if pts is not None:
            self.anch.append((start, pts))
        self.buf += data
        self._scan()

    def _dur(self, pic):
        """Egy kép megjelenítési ideje félképben (field)."""
        if not self.mp2:
            return 2
        if pic["st"] != 3:
            return 1
        if self.prog:
            return 2 * (1 + pic["rff"] + (pic["rff"] & pic["tff"]))
        return 2 + pic["rff"]

    def _close(self):
        g = self.cur
        self.cur = None
        if not g or not g["pics"] or self.fd is None:
            return
        hf = self.fd / 2.0
        durs = [(p["tr"], self._dur(p)) for p in g["pics"]]
        total = sum(d for _, d in durs)
        lead = 0
        if g["anchor"] is not None:
            pts, trr = g["anchor"]
            start = pts - sum(d for t, d in durs if t < trr) * hf
            lead = sum(1 for t, _ in durs if t < trr)
            anch = True
        elif self.prev_end is not None:
            start, anch = self.prev_end, False
        else:
            return
        end = start + total * hf
        self.prev_end = end
        self.groups.append((start, end, anch, g["closed"], len(g["pics"]),
                            g["pics"][0]["ty"], lead))

    def _new_group(self, closed):
        self._close()
        self.cur = {"pics": [], "anchor": None, "closed": closed}

    def finish(self):
        self._scan()
        self._close()

    def _scan(self):
        b = self.buf
        n = len(b)
        i = b.find(b"\x00\x00\x01")
        keep = n
        while i >= 0:
            if i + 4 > n:
                keep = i
                break
            c = b[i + 3]
            if c == 0x00:
                if i + 6 > n:
                    keep = i
                    break
                self._picture(b, i)
            elif c == 0xB3:
                if i + 12 > n:
                    keep = i
                    break
                self._seqhdr(b, i)
            elif c == 0xB8:
                if i + 8 > n:
                    keep = i
                    break
                self.wait = False
                self._new_group(bool((b[i + 7] >> 6) & 1))
            elif c == 0xB5:
                if i + 10 > n:
                    keep = i
                    break
                self._ext(b, i)
            i = b.find(b"\x00\x00\x01", i + 3)
        else:
            keep = max(0, n - 3)
        if keep:
            del b[:keep]
            self.abs0 += keep

    def _seqhdr(self, b, i):
        code = b[i + 7] & 15
        if code in MPV_FPS:
            nu, de = MPV_FPS[code]
            if self.seq is None:
                self.seq = {"w": (b[i + 4] << 4) | (b[i + 5] >> 4),
                            "h": ((b[i + 5] & 15) << 8) | b[i + 6],
                            "ar": b[i + 7] >> 4, "code": code, "interlaced": False,
                            "profile": None, "level": None, "mpeg": 1,
                            "br": (b[i + 8] << 10) | (b[i + 9] << 2) | (b[i + 10] >> 6)}
                self.fd = 90000.0 * de / nu
                self.seq["nu"], self.seq["de"] = nu, de
        if self.cur is not None and self.cur["pics"]:
            self._new_group(False)       # GOP-fejléc nélküli folyam: a sorozatfejléc is határ
        elif self.cur is None and not self.wait:
            self.cur = {"pics": [], "anchor": None, "closed": False}

    def _ext(self, b, i):
        e = b[i + 4] >> 4
        if e == 1 and self.seq is not None and self.seq["mpeg"] == 1:
            self.mp2 = True
            self.prog = bool((b[i + 5] >> 3) & 1)
            self.seq["mpeg"] = 2
            self.seq["interlaced"] = not self.prog
            pl = ((b[i + 4] & 15) << 4) | (b[i + 5] >> 4)
            self.seq["profile"], self.seq["level"] = (pl >> 4) & 7, pl & 15
            n, d = (b[i + 9] >> 5) & 3, b[i + 9] & 31
            if n or d:
                nu, de = self.seq["nu"] * (n + 1), self.seq["de"] * (d + 1)
                self.fd = 90000.0 * de / nu
        elif e == 8 and self.cur_pic is not None:
            pc = self.cur_pic
            pc["st"] = b[i + 6] & 3
            pc["tff"] = b[i + 7] >> 7
            pc["rff"] = (b[i + 7] >> 1) & 1

    def _picture(self, b, i):
        if self.wait:
            return
        if self.cur is None:
            self.cur = {"pics": [], "anchor": None, "closed": False}
        aa = self.abs0 + i
        cand = None
        while self.anch and self.anch[0][0] <= aa:
            cand = self.anch.popleft()
        tr = (b[i + 4] << 2) | (b[i + 5] >> 6)
        pic = {"tr": tr, "ty": (b[i + 5] >> 3) & 7, "st": 3, "tff": 0, "rff": 0}
        if cand is not None and cand[0] > self.last_pic and self.cur["anchor"] is None:
            self.cur["anchor"] = (cand[1], tr)
        self.last_pic = aa
        self.cur["pics"].append(pic)
        self.cur_pic = pic
        self.pics += 1


# ------------------------------------------------------------------ elemzés --

class _PsState:
    pass


def _ps_collect(buf, p, final, st, tail):
    """A buf-ban lévő csomagok bejárása; az eredmény az st-be gyűlik."""
    end = len(buf)
    while p < end:
        res = ps_pack(buf, p, end, final)
        if res is None:
            break
        kind, q, mp2, pes = res
        if kind == 2:
            p = q
            continue
        if kind == 1:
            st.end_code = True
            p = q
            continue
        st.end_code = False
        if st.mp2 is None:
            st.mp2 = mp2
        if mp2:
            base, ext = ps_rd_scr2(buf, p)
            scr = base * 300 + ext
        else:
            scr = rd_ts(buf, p + 4) * 300
        if st.first_scr is None:
            st.first_scr = scr
        st.last_scr = scr
        st.npack += 1
        for r, sid, tot in pes:
            e = r + tot
            if 0xE0 <= sid <= 0xEF:
                he, pts, dts, pp, dp, scrm = ps_pes(buf, r, tot)
                if scrm:
                    st.scrambled = True
                if st.vsid is None:
                    st.vsid = sid
                if sid == st.vsid:
                    if pts is not None and st.v_first_pts is None and not tail:
                        st.v_first_pts = pts
                    st.vs.feed(buf[he:e], pts)
            elif sid == 0xBD or 0xC0 <= sid <= 0xDF:
                he, pts, dts, pp, dp, scrm = ps_pes(buf, r, tot)
                if scrm:
                    st.scrambled = True
                k = ps_key(buf, sid, he, e)
                if ps_is_spu(k) and not tail:
                    st.spu.add(k)
                if not ps_is_audio(k):
                    continue
                if k not in st.akeys:
                    st.akeys.append(k)
                sh = ps_sub_hdr(k)
                if pts is not None:
                    if not tail and k not in st.a_first:
                        st.a_first[k] = pts
                    if tail:
                        st.a_last[k] = pts
                        st.a_tail[k] = 0
                    if k not in st.a_sample:
                        smp = None
                        if 0xBD80 <= k <= 0xBD87 and he + 4 <= e:
                            au = he + 3 + ((buf[he + 2] << 8) | buf[he + 3])
                            if au + 2 <= e and buf[au] == 0x0B and buf[au + 1] == 0x77:
                                smp = bytes(buf[au:min(e, au + 64)])
                        elif k >= 0xBDA0 and k <= 0xBDA7:
                            smp = bytes(buf[he:min(e, he + 8)])
                        elif k < 0x100:
                            smp = bytes(buf[he:min(e, he + 4096)])
                        elif 0xBD88 <= k <= 0xBD8F:
                            smp = b""
                        if smp is not None:
                            st.a_sample[k] = smp
                if tail and k in st.a_tail:
                    st.a_tail[k] += max(0, e - he - sh)
            elif sid == 0xBF:
                st.nav += 1
                if st.nav_first is None and tot == 986 and buf[r + 6] == 0:
                    st.nav_first = p
        p = q
    return p


def _ps_state(vsid=None, tail=False):
    st = _PsState()
    st.mp2 = st.first_scr = st.last_scr = st.v_first_pts = st.nav_first = None
    st.vsid = vsid
    st.npack = st.nav = 0
    st.end_code = False
    st.scrambled = False
    st.akeys, st.a_first, st.a_last, st.a_tail, st.a_sample = [], {}, {}, {}, {}
    st.spu = set()
    st.vs = VScan(tail=tail)
    return st


def _ps_analyze(inf):
    inf.size = os.path.getsize(inf.path)
    if inf.size < 2 * PS_SECTOR:
        raise MsgError("err_small")
    with open(inf.path, "rb") as f:
        head = bytearray(f.read(HEAD_BYTES))
        s0 = head.find(PS_PACK)
        if s0 < 0:
            raise MsgError("err_notps")
        whole = inf.size <= len(head)
        st = _ps_state()
        _ps_collect(head, s0, whole, st, False)
        if st.npack == 0:
            raise MsgError("err_notps")
        st.vs.finish()
        if st.vsid is None or st.vs.seq is None or not st.vs.groups:
            raise MsgError("err_ps_novideo")
        if st.scrambled:
            raise MsgError("err_ps_scrambled")
        if whole:
            tail, t0 = head, s0
        else:
            tstart = max(0, inf.size - TAIL_BYTES)
            tstart -= tstart % PS_SECTOR
            f.seek(tstart)
            tail = bytearray(f.read(inf.size - tstart))
            t0 = tail.find(PS_PACK)
            if t0 < 0:
                raise MsgError("err_notps")
    ts = _ps_state(st.vsid, tail=not whole)
    _ps_collect(tail, t0, True, ts, True)
    ts.vs.finish()
    if not ts.vs.groups:
        raise MsgError("err_ps_nots_end")
    inf.mp2 = bool(st.mp2)
    inf.vsid = st.vsid
    inf.seq = st.vs.seq
    inf.fd = st.vs.fd
    inf.first_scr = st.first_scr
    inf.last_scr = ts.last_scr
    inf.end_code = ts.end_code
    inf.has_nav = st.nav > 0
    inf.akeys = list(st.akeys)
    inf.spu = sorted(st.spu)
    inf.a_first = dict(st.a_first)
    inf.a_last = dict(ts.a_last)
    inf.a_tail = dict(ts.a_tail)
    inf.v_first_pts = st.v_first_pts
    inf.ainfo = {}
    for k, smp in st.a_sample.items():
        a = None
        if 0xBD80 <= k <= 0xBD87:
            a = parse_ac3(smp)
        elif 0xBDA0 <= k <= 0xBDA7:
            a = parse_lpcm(smp)
        elif k < 0x100:
            a = parse_mpa(smp)
        if a:
            inf.ainfo[k] = a
    g0, g1 = st.vs.groups[0], ts.vs.groups[-1]
    inf.first_ptype = g0[5]
    inf.open_start = (not g0[3]) and g0[6] > 0
    inf.t_start = int(round(g0[0])) % MOD33
    inf.t_end = int(round(g1[1])) % MOD33
    inf.duration = ((inf.t_end - inf.t_start) % MOD33) / 90000.0
    inf.vinfo = {"w": inf.seq["w"], "h": inf.seq["h"], "interlaced": inf.seq["interlaced"],
                 "profile": inf.seq["profile"], "level": inf.seq["level"]}


class MpgInfo:
    kind = "mpg"

    def __init__(self, path):
        self.path = path
        self.name = os.path.basename(path)
        self.pending = True
        self.error = None
        self.size = 0
        self.duration = 0.0
        self.akeys = []
        self.ainfo = {}
        self.has_nav = False
        self.a_first, self.a_last, self.a_tail = {}, {}, {}
        self.first_scr = self.last_scr = None
        self.first_ptype = None      # az első kép típusa (1 = I, 2 = P, 3 = B)
        self.open_start = False

    def analyze(self):
        _ps_analyze(self)

    def vdesc(self):
        if not getattr(self, "seq", None):
            return "?"
        s = self.seq
        return "MPEG-%d %dx%d%s %g fps" % (s["mpeg"], s["w"], s["h"],
                                           "i" if s["interlaced"] else "p",
                                           round(90000.0 / self.fd, 2))

    def adesc(self):
        if not self.akeys:
            return tr("no_audio")
        k = self.akeys[0]
        a = self.ainfo.get(k)
        n = ps_key_name(k)
        if a and "kbps" in a:
            return "%s %s %dk" % (n, a["ch"], a["kbps"])
        if a:
            return "%s %dch %dbit" % (n, a["ch"], a["bits"])
        return n


class VobInfo(MpgInfo):
    kind = "vob"


def ps_compare(ref, inf, prev=None):
    bad, warn = [], []
    if inf.mp2 != ref.mp2:
        bad.append(tr("c_ps_sys"))
    if inf.vsid != ref.vsid:
        bad.append(tr("c_ps_vid"))
    rs, s = ref.seq, inf.seq
    if rs["mpeg"] != s["mpeg"]:
        bad.append(tr("c_vcodec"))
    if abs(inf.fd - ref.fd) > 0.5:
        bad.append(tr("c_fps"))
    if (rs["w"], rs["h"]) != (s["w"], s["h"]):
        bad.append(tr("c_res"))
    if rs["interlaced"] != s["interlaced"]:
        bad.append(tr("c_scan"))
    if rs["ar"] != s["ar"]:
        warn.append(tr("c_ps_ar"))
    if (rs["profile"], rs["level"]) != (s["profile"], s["level"]):
        warn.append(tr("c_prof"))
    if inf.akeys != ref.akeys:
        bad.append(tr("c_ps_streams"))
    else:
        for k in ref.akeys:
            ra, a = ref.ainfo.get(k), inf.ainfo.get(k)
            if ra and a:
                if ra["fs"] != a["fs"] or ra["ch"] != a["ch"] or ra.get("bits") != a.get("bits"):
                    bad.append(tr("c_afmt"))
                    break
                if ra.get("kbps") != a.get("kbps"):
                    warn.append(tr("c_abr"))
            elif bool(ra) != bool(a):
                warn.append(tr("c_vunk"))
    if inf.has_nav != ref.has_nav:
        warn.append(tr("c_ps_nav"))
    if inf.open_start and not (prev is not None and not prev.pending and not prev.error
                               and prev.kind == inf.kind and ps_is_cont(prev, inf)):
        warn.append(tr("c_ps_open"))
    if bad:
        return "bad", "; ".join(bad)
    if warn:
        return "warn", "; ".join(warn)
    return "ok", tr("c_ok")


# ---------------------------------------------------------------- összefűzés --

class _Blocks:
    """Blokkonkénti olvasás; a feldolgozatlan maradék átkerül a következő blokkba."""

    def __init__(self, f, block=PS_BLOCK):
        self.f, self.block, self.carry, self.base, self.eof = f, block, b"", 0, False

    def read(self):
        if self.eof:
            return None
        data = self.f.read(self.block)
        self.eof = len(data) < self.block
        buf = bytearray(self.carry)
        buf += data
        return buf, self.eof

    def done(self, buf, p):
        self.base += p
        self.carry = bytes(buf[p:])


def _ps_process(inf, off, fo, out_base, last, crc, log, step, cancel, stats):
    """Egy fájl átmásolása eltolt időbélyegekkel. False, ha megszakították."""
    nav = inf.kind == "vob"
    blk = _Blocks(open(inf.path, "rb"))
    first_pack = True
    try:
        while True:
            if cancel is not None and cancel.is_set():
                return False
            got = blk.read()
            if got is None:
                break
            buf, final = got
            end = len(buf)
            p = run = 0
            while p < end:
                res = ps_pack(buf, p, end, final)
                if res is None:
                    break
                kind, q, mp2, pes = res
                if kind == 2:
                    if run < p:
                        fo.write(buf[run:p])
                        stats["out"] += p - run
                    stats["junk"] += q - p
                    run = p = q
                    continue
                if kind == 1:
                    if not last:
                        if run < p:
                            fo.write(buf[run:p])
                            stats["out"] += p - run
                        run = q
                        stats["endcode"] = True
                    p = q
                    continue
                if mp2:
                    b_, e_ = ps_rd_scr2(buf, p)
                else:
                    b_, e_ = rd_ts(buf, p + 4), 0
                if first_pack:
                    first_pack = False
                    stats["scr_first"] = b_ * 300 + e_
                if off:
                    if mp2:
                        ps_wr_scr2(buf, p, (b_ + off) % MOD33)
                    else:
                        wr_ts(buf, p + 4, (b_ + off) % MOD33)
                pos_out = out_base + stats["out"] + (p - run)
                for r, sid, tot in pes:
                    e = r + tot
                    if sid == 0xBE:
                        continue
                    he, pts, dts, pp, dp, _s = ps_pes(buf, r, tot)
                    if off:
                        if pp >= 0:
                            wr_ts(buf, pp, (pts + off) % MOD33)
                        if dp >= 0:
                            wr_ts(buf, dp, (dts + off) % MOD33)
                    if sid == 0xBF:
                        if nav:
                            _ps_nav(buf, r, tot, off, b_ & M32, blk.base + p, pos_out, stats)
                        continue
                    k = ps_key(buf, sid, he, e)
                    c = crc.get(k)
                    if c is None:
                        c = crc[k] = [0, 0]
                    c[0] += e - he
                    c[1] = zlib.crc32(buf[he:e], c[1])
                stats["packs"] += 1
                p = q
            if run < p:
                fo.write(buf[run:p])
                stats["out"] += p - run
            blk.done(buf, p)
            step(p)
    finally:
        blk.f.close()
    return True


def _ps_nav_sig(buf, r, tot, b32, sector):
    """A NAV-csomag mezőinek a csomag helyéhez és órájához viszonyított értéke.

    (0, bájtok) a PCI-ről, (1, bájtok) a DSI-ről, None, ha nem NAV-adat. Az összefűzés
    ezeket a viszonyokat nem változtatja, ezért a forrásból és a kimenetből számolt
    aláírásnak egyeznie kell."""
    sub, d = buf[r + 6], r + 7
    u = _U32.unpack_from
    if sub == 0 and tot == 986:
        se = u(buf, d + 20)[0]
        return 0, struct.pack(">4I", (u(buf, d)[0] - sector) & M32, (u(buf, d + 12)[0] - b32) & M32,
                              (u(buf, d + 16)[0] - b32) & M32, ((se - b32) & M32) if se else M32)
    if sub == 1 and tot == 1024:
        return 1, struct.pack(">2I", (u(buf, d)[0] - b32) & M32, (u(buf, d + 4)[0] - sector) & M32)
    return None


def _ps_nav(buf, r, tot, off, b32, src_pos, out_pos, stats):
    """NAV-csomag: aláírás a forrásból, majd az időbélyegek és az LBN igazítása."""
    sig = _ps_nav_sig(buf, r, tot, b32, src_pos // PS_SECTOR)
    if sig is None:
        return
    i, raw = sig
    stats["nav_crc"][i] = zlib.crc32(raw, stats["nav_crc"][i])
    stats["nav_n"][i] += 1
    delta = out_pos - src_pos
    if src_pos % PS_SECTOR or delta % PS_SECTOR:
        stats["nav_skip"] = True
        delta = 0
    d = r + 7
    u, w = _U32.unpack_from, _U32.pack_into
    sec = (delta // PS_SECTOR) & M32
    if i == 0:
        if sec:
            w(buf, d, (u(buf, d)[0] + sec) & M32)
        if off:
            w(buf, d + 12, (u(buf, d + 12)[0] + off) & M32)
            w(buf, d + 16, (u(buf, d + 16)[0] + off) & M32)
            se = u(buf, d + 20)[0]
            if se:
                w(buf, d + 20, (se + off) & M32)
    else:
        if off:
            w(buf, d, (u(buf, d)[0] + off) & M32)
        if sec:
            w(buf, d + 4, (u(buf, d + 4)[0] + sec) & M32)


def ps_join(infos, out_path, progress=None, log=None, cancel=None, verify=True):
    log = log or (lambda s: None)
    progress = progress or (lambda f: None)
    ref = infos[0]
    nf = len(infos)
    total = sum(i.size for i in infos)
    try:
        import shutil
        free = shutil.disk_usage(os.path.dirname(os.path.abspath(out_path)) or ".").free
        if free < total + 50 * 1024 * 1024:
            raise MsgError("j_space")
    except OSError:
        pass
    log(tr("l_ps_head", ref.kind.upper(), nf, "MPEG-2 PS" if ref.mp2 else "MPEG-1 SS"))
    offsets = [0]
    end = ref.t_end
    for inf in infos[1:]:
        off = (end - inf.t_start) % MOD33
        offsets.append(off)
        end = (inf.t_end + off) % MOD33
    share = 0.5 if verify else 1.0
    done = [0]

    def step(n):
        done[0] += n
        progress(share * done[0] / float(total))

    tmp = out_path + ".part"
    plan = {"nf": nf, "offsets": offsets, "starts": [], "crc": [], "stats": [],
            "end_code": infos[-1].end_code}
    try:
        with open(tmp, "wb") as fo:
            prev_last = None
            for idx, inf in enumerate(infos):
                if cancel is not None and cancel.is_set():
                    break
                off = offsets[idx]
                stats = {"out": 0, "junk": 0, "packs": 0, "endcode": False, "scr_first": None,
                         "nav_crc": [0, 0], "nav_n": [0, 0], "nav_skip": False}
                crc = {}
                out_base = fo.tell()
                plan["starts"].append(out_base)
                if idx == 0:
                    log(tr("l_copy", inf.name))
                else:
                    log(tr("l_off", idx + 1, inf.name, sdiff(off, 0) / 90000.0))
                if not _ps_process(inf, off, fo, out_base, idx == nf - 1, crc, log, step,
                                   cancel, stats):
                    break
                if stats["junk"]:
                    log(tr("l_ps_junk", stats["junk"]))
                if stats["nav_skip"]:
                    log(tr("l_ps_lbn"))
                if idx > 0 and prev_last is not None and stats["scr_first"] is not None:
                    gap = ((stats["scr_first"] + off * 300 - prev_last + SCR_MOD // 2)
                           % SCR_MOD) - SCR_MOD // 2
                    if gap < 0 or gap > 27000000 // 2:
                        log(tr("l_ps_scr", gap / 27000.0))
                prev_last = (inf.last_scr + off * 300) % SCR_MOD
                plan["crc"].append(crc)
                plan["stats"].append(stats)
            else:
                pass
        if cancel is not None and cancel.is_set():
            os.remove(tmp)
            return False
        plan["size"] = os.path.getsize(tmp)
        if verify:
            vres = ps_verify(tmp, infos, plan,
                             lambda f: progress(share + (1.0 - share) * f), log, cancel)
            if vres is None:
                os.remove(tmp)
                return False
            if vres[0]:
                root, ext = os.path.splitext(out_path)
                bad = root + "_HIBAS" + ext
                os.replace(tmp, bad)
                raise MsgError("v_failed", vres[0], bad)
        else:
            log(tr("l_verify_off"))
        os.replace(tmp, out_path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    log(tr("l_done", out_path))
    return True


# ------------------------------------------------------------------ ellenőrzés --

def ps_verify(path, infos, plan, progress=None, log=None, cancel=None):
    """A kész PS/VOB fájl ellenőrzése a kimenetről visszaolvasva. (hibák, figyelm.) / None."""
    log = log or (lambda s: None)
    progress = progress or (lambda f: None)
    nf = plan["nf"]
    offs = plan["offsets"]
    starts = plan["starts"]
    ref = infos[0]
    vob = ref.kind == "vob"
    checks = VOB_CHECKS if vob else PS_CHECKS
    res = {k: [0, 0] for k in checks}
    shown = Counter()

    def issue(chk, sev, key, *a):
        res[chk][0 if sev == "E" else 1] += 1
        shown[chk] += 1
        if shown[chk] <= MAX_SHOWN:
            log("   %s %s" % ("✗" if sev == "E" else "!", tr(key, *a)))
        elif shown[chk] == MAX_SHOWN + 1:
            log(tr("v_more", tr("pc_" + chk)))

    log(tr("v_head", nf - 1))
    log(tr("v_what"))
    for key in checks:
        log("   • %s: %s" % (tr("pc_" + key), tr("pd_" + key)))
    log(tr("p_pass1"))
    size = os.path.getsize(path)
    if size != plan["size"]:
        issue("struct", "E", "pv_size", size, plan["size"])

    def part_of(pos):
        return bisect.bisect_right(starts, pos) - 1

    vsids = ref.vsid
    parts = []
    for k in range(nf):
        pt = _PsState()
        pt.vs = VScan()
        pt.crc, pt.packs = {}, 0
        pt.scr0 = pt.scr1 = None
        pt.a_first, pt.a_last, pt.a_tail = {}, {}, {}
        pt.v_first = None
        pt.nav_crc, pt.nav_n = [0, 0], [0, 0]
        pt.first_pos = None
        parts.append(pt)
    prev_scr = None
    junk = 0
    last_end = False
    with open(path, "rb") as f:
        blk = _Blocks(f)
        while True:
            if cancel is not None and cancel.is_set():
                return None
            got = blk.read()
            if got is None:
                break
            buf, final = got
            end = len(buf)
            p = 0
            while p < end:
                res_ = ps_pack(buf, p, end, final)
                if res_ is None:
                    break
                kind, q, mp2, pes = res_
                apos = blk.base + p
                if kind == 2:
                    junk += q - p
                    p = q
                    continue
                if kind == 1:
                    last_end = True
                    p = q
                    continue
                last_end = False
                k = part_of(apos)
                pt = parts[k]
                if pt.first_pos is None:
                    pt.first_pos = apos
                    if apos != starts[k]:
                        issue("struct", "E", "pv_start", k + 1)
                if mp2 != ref.mp2:
                    issue("struct", "E", "pv_sys", apos)
                if mp2:
                    b_, e_ = ps_rd_scr2(buf, p)
                else:
                    b_, e_ = rd_ts(buf, p + 4), 0
                scr = b_ * 300 + e_
                if pt.scr0 is None:
                    pt.scr0 = scr
                pt.scr1 = scr
                if prev_scr is not None:
                    d = ((scr - prev_scr + SCR_MOD // 2) % SCR_MOD) - SCR_MOD // 2
                    if d < 0 or d > 27000000:
                        if pt.packs == 0 and k > 0:
                            issue("scr", "W", "pv_scr_seam", k, d / 27000.0)
                        else:
                            issue("scr", "W", "pv_scr", d / 27000.0, _fmt_t(
                                sdiff(scr // 300 % MOD33, ref.first_scr // 300) / 90000.0))
                prev_scr = scr
                pt.packs += 1
                for r, sid, tot in pes:
                    e = r + tot
                    if sid == 0xBE:
                        continue
                    he, pts, dts, pp, dp, _s = ps_pes(buf, r, tot)
                    if sid == 0xBF:
                        if vob:
                            sg = _ps_nav_sig(buf, r, tot, (b_ if mp2 else rd_ts(buf, p + 4)) & M32,
                                             apos // PS_SECTOR)
                            if sg is not None:
                                pt.nav_crc[sg[0]] = zlib.crc32(sg[1], pt.nav_crc[sg[0]])
                                pt.nav_n[sg[0]] += 1
                        continue
                    key = ps_key(buf, sid, he, e)
                    c = pt.crc.get(key)
                    if c is None:
                        c = pt.crc[key] = [0, 0]
                    c[0] += e - he
                    c[1] = zlib.crc32(buf[he:e], c[1])
                    if 0xE0 <= sid <= 0xEF:
                        if sid == vsids:
                            if pts is not None and pt.v_first is None:
                                pt.v_first = pts
                            pt.vs.feed(buf[he:e], pts)
                    elif ps_is_audio(key):
                        sh = ps_sub_hdr(key)
                        if pts is not None:
                            pt.a_first.setdefault(key, pts)
                            pt.a_last[key] = pts
                            pt.a_tail[key] = 0
                        if key in pt.a_tail:
                            pt.a_tail[key] += max(0, e - he - sh)
                p = q
            blk.done(buf, p)
            progress(min(1.0, blk.base / float(max(1, size))) * 0.9)
    for pt in parts:
        pt.vs.finish()
    if junk:
        issue("struct", "E", "pv_junk", junk)
    if last_end != bool(plan["end_code"]):
        issue("struct", "W", "pv_endcode")
    for k, pt in enumerate(parts):
        if pt.packs != plan["stats"][k]["packs"]:
            issue("struct", "E", "pv_packs", k + 1, pt.packs, plan["stats"][k]["packs"])
    log(tr("p_pass2"))

    # ---- adatintegritás: a hasznos adat bájtra azonos a forrásokkal
    for k in range(nf):
        src, got = plan["crc"][k], parts[k].crc
        for key in sorted(set(src) | set(got)):
            a, b = src.get(key), got.get(key)
            if a != b:
                issue("data", "E", "pv_data", k + 1, ps_key_name(key))

    # ---- DVD NAV-csomagok: a mezők viszonya a csomag helyéhez/órájához nem változhat
    if vob:
        for k in range(nf):
            stt = plan["stats"][k]
            if stt["nav_skip"]:
                continue
            if stt["nav_n"] != parts[k].nav_n or stt["nav_crc"] != parts[k].nav_crc:
                issue("nav", "E", "pv_nav", k + 1)

    # ---- SCR: az első csomag órája = forrás + eltolás
    for k in range(nf):
        pt = parts[k]
        want = (plan["stats"][k]["scr_first"] + offs[k] * 300) % SCR_MOD \
            if plan["stats"][k]["scr_first"] is not None else None
        if want is not None and pt.scr0 is not None and (
                (pt.scr0 - want + SCR_MOD // 2) % SCR_MOD) - SCR_MOD // 2:
            issue("scr", "E", "pv_scr_off", k + 1)

    # ---- videó időzítés és varratok
    for k, pt in enumerate(parts):
        g = pt.vs.groups
        inf = infos[k]
        if not g:
            issue("timing", "E", "pv_novid")
            continue
        tol = ref.fd * 0.25
        s0 = int(round(g[0][0])) % MOD33
        e0 = int(round(g[-1][1])) % MOD33
        if sdiff(s0, (inf.t_start + offs[k]) % MOD33) not in (-1, 0, 1):
            issue("timing", "E", "pv_off", k + 1, sdiff(s0, (inf.t_start + offs[k]) % MOD33) / 90.0)
        if sdiff(e0, (inf.t_end + offs[k]) % MOD33) not in (-1, 0, 1, -2, 2):
            issue("timing", "E", "pv_dur", k + 1)
        for a, b in zip(g, g[1:]):
            d = sdiff(int(round(b[0])), int(round(a[1])))
            if abs(d) > tol and b[2]:
                issue("timing", "W", "pv_gap", d / ref.fd, _fmt_t(
                    sdiff(int(round(b[0])) % MOD33, parts[0].vs.groups[0][0] // 1 % MOD33) / 90000.0))
        if k > 0:
            pg = parts[k - 1].vs.groups
            if pg:
                d = sdiff(s0, int(round(pg[-1][1])) % MOD33)
                if abs(d) > tol:
                    issue("timing", "E", "pv_seam", k, d / ref.fd, d / 90.0)
            first = g[0]
            if ps_is_cont(infos[k - 1], infos[k]):
                pass            # megosztott fájl: a GOP az előző fájlból folytatódik
            elif first[5] != 1:
                issue("vseam", "E", "pv_idr", k)
            elif not first[3]:
                issue("vseam", "W", "pv_open", k)
    exp_total = sum(i.duration for i in infos)
    out_dur = ((int(round(parts[-1].vs.groups[-1][1])) - int(round(parts[0].vs.groups[0][0])))
               % MOD33) / 90000.0 if parts[-1].vs.groups and parts[0].vs.groups else 0.0
    if abs(out_dur - exp_total) > ref.fd * 2 / 90000.0 * nf:
        issue("timing", "E", "pv_total", _fmt_t(exp_total), _fmt_t(out_dur))

    # ---- hang: varratok és A/V szinkron
    for k in range(nf):
        pt, inf = parts[k], infos[k]
        for key in ref.akeys:
            if key not in pt.a_first:
                issue("audio", "E", "v_s_noaudio", k + 1)
                continue
            src = inf.a_first.get(key)
            if src is not None and sdiff(pt.a_first[key], (src + offs[k]) % MOD33) != 0:
                issue("sync", "E", "pv_sync", k + 1, ps_key_name(key),
                      sdiff(pt.a_first[key], (src + offs[k]) % MOD33) / 90.0)
        if pt.v_first is not None and inf.v_first_pts is not None and \
                sdiff(pt.v_first, (inf.v_first_pts + offs[k]) % MOD33) != 0:
            issue("sync", "E", "pv_sync", k + 1, "video",
                  sdiff(pt.v_first, (inf.v_first_pts + offs[k]) % MOD33) / 90.0)
    for k in range(1, nf):
        for key in ref.akeys:
            a, b = parts[k - 1], parts[k]
            if key not in a.a_last or key not in b.a_first:
                continue
            an = ref.ainfo.get(key) or {}
            if "kbps" in an:
                bps = an["kbps"] * 125.0
            elif "bits" in an:
                bps = an["fs"] * an["ch"] * an["bits"] / 8.0
            else:
                continue
            exp = a.a_last[key] + a.a_tail[key] / bps * 90000.0
            g = sdiff(b.a_first[key], int(round(exp)) % MOD33)
            fr = 90000.0 * an.get("spf", 1536) / an.get("fs", 48000)
            if abs(g) > fr * 1.5:
                issue("audio", "E" if abs(g) > 90000 else "W", "pv_a_seam", k, g / 90.0)

    progress(1.0)
    return _verify_summary(res, log, checks, "pc_")


# ============================================================ MP4 / MOV =====
# Veszteségmentes MP4/MOV összefűzés: a minták (kép- és hangadat) bájtra azonosan
# kerülnek át, csak a konténer táblái (stts, ctts, stss, stsc, stsz, stco) és a
# szerkesztőlista (elst) épül újra. Csak a Python standard könyvtárát használja
# (ISO/IEC 14496-12 – ISO Base Media File Format – nyilvános specifikáció alapján).

MP4_EXTS = (".mp4", ".m4v", ".mov")
MP4_CO64_AT = 0xFFFFFFFF      # ennél nagyobb eltolásokhoz co64 kell
MP4_MDAT64_AT = 0xFFFFFFFF    # ennél nagyobb mdat-hoz 64 bites fejléc kell
MP4_CORE = {b"stsd", b"stts", b"ctts", b"stss", b"stsc", b"stsz", b"stz2", b"stco", b"co64"}
MP4_CFG = (b"avcC", b"hvcC", b"av1C", b"vpcC", b"dvcC", b"dvvC", b"esds", b"dOps",
           b"dac3", b"dec3", b"dfLa", b"alac", b"wave", b"glbl")
MP4_VNAMES = {b"avc1": "H.264", b"avc3": "H.264", b"hvc1": "HEVC", b"hev1": "HEVC",
              b"av01": "AV1", b"vp09": "VP9", b"vp08": "VP8", b"mp4v": "MPEG-4",
              b"apch": "ProRes", b"apcn": "ProRes", b"apcs": "ProRes", b"apco": "ProRes",
              b"ap4h": "ProRes", b"jpeg": "MJPEG", b"mjpa": "MJPEG", b"s263": "H.263"}
MP4_ANAMES = {b"mp4a": "AAC", b"ac-3": "AC-3", b"ec-3": "E-AC-3", b"Opus": "Opus",
              b"fLaC": "FLAC", b"alac": "ALAC", b".mp3": "MP3", b"sowt": "PCM",
              b"twos": "PCM", b"lpcm": "PCM", b"ipcm": "PCM", b"fpcm": "PCM",
              b"in24": "PCM", b"in32": "PCM", b"samr": "AMR", b"sawb": "AMR-WB"}
MP4_ENC = (b"encv", b"enca", b"encs", b"enct", b"encm")


def _mp4_iter(buf, s, e):
    """(típus, tartalom_kezdet, doboz_vég, doboz_kezdet) a [s, e) tartomány dobozaira."""
    p = s
    while p < e:
        if e - p < 8:
            raise MsgError("m_box")
        size, typ = struct.unpack_from(">I4s", buf, p)
        hdr = 8
        if size == 1:
            if e - p < 16:
                raise MsgError("m_box")
            size = struct.unpack_from(">Q", buf, p + 8)[0]
            hdr = 16
        elif size == 0:
            size = e - p
        if size < hdr or p + size > e:
            raise MsgError("m_box")
        yield typ, p + hdr, p + size, p
        p += size


def _mp4_scan_top(f, size):
    """A fájl legfelső szintű dobozai: [(típus, kezdet, tartalom_kezdet, vég)]."""
    out, p = [], 0
    while p < size:
        f.seek(p)
        h = f.read(16)
        if len(h) < 8:
            if not h.strip(b"\x00"):
                break
            raise MsgError("m_box")
        sz, typ = struct.unpack(">I4s", h[:8])
        hdr = 8
        if sz == 1:
            if len(h) < 16:
                raise MsgError("m_box")
            sz = struct.unpack(">Q", h[8:16])[0]
            hdr = 16
        elif sz == 0:
            sz = size - p
        if sz < hdr:
            raise MsgError("m_box")
        if p + sz > size:
            raise MsgError("m_trunc")
        out.append((typ, p, p + hdr, p + sz))
        p += sz
    return out


class Mp4Track:
    def __init__(self):
        self.id = 0
        self.handler = b""
        self.mdts = 1
        self.tk_dur = 0
        self.width = self.height = 0
        self.matrix = b""
        self.stsd = []                 # mintaleírás-bejegyzések (teljes doboz bájtjai)
        self.stts = []                 # [(db, időköz)]
        self.ctts = None               # [(db, eltolás)]
        self.ctts_ver = 0
        self.stss = None               # 1-alapú kulcskocka-indexek
        self.stsc = []                 # [(első_darab, minta/darab, leírás-index)]
        self.sizes = []
        self.uniform = 0
        self.offsets = []
        self.elst = None               # [(időtartam, média_idő)]
        self.dropped = set()
        self._lay = None
        self.ranges = []

    @property
    def n(self):
        return len(self.sizes)

    def fps(self):
        """Képfrekvencia a leggyakoribb képkockahosszból (az első/utolsó minta hossza kilóghat)."""
        agg = {}
        for c, d in self.stts:
            agg[d] = agg.get(d, 0) + c
        if not agg:
            return 0.0
        d = max(agg, key=agg.get)
        return self.mdts / float(d) if d else 0.0

    def media_dur(self):
        return sum(c * d for c, d in self.stts)

    def layout(self):
        """(minta/darab lista, leírás-index/darab lista, darabok első mintájának indexe)"""
        if self._lay is None:
            nch = len(self.offsets)
            spc, sdi = [], []
            ents = self.stsc
            if nch and (not ents or ents[0][0] != 1):
                raise MsgError("m_tables", 0)
            for i, (fc, sp, sd) in enumerate(ents):
                nxt = ents[i + 1][0] if i + 1 < len(ents) else nch + 1
                if nxt < fc or fc < 1:
                    raise MsgError("m_tables", 0)
                for _ in range(fc, min(nxt, nch + 1)):
                    spc.append(sp)
                    sdi.append(sd)
            if len(spc) != nch:
                raise MsgError("m_tables", 0)
            cfs, run = [], 0
            for sp in spc:
                cfs.append(run)
                run += sp
            self._lay = (spc, sdi, cfs, run)
        return self._lay

    def sample_loc(self, i):
        """(fájlbeli eltolás, méret) az i-edik (0-alapú) mintára."""
        spc, sdi, cfs, total = self.layout()
        c = bisect.bisect_right(cfs, i) - 1
        off = self.offsets[c] + sum(self.sizes[cfs[c]:i])
        return off, self.sizes[i]

    def entry_info(self):
        """(fourcc, szélesség, magasság, csatorna, mintavétel, {konfig-dobozok}) az 1. bejegyzésből."""
        if not self.stsd:
            return (b"", 0, 0, 0, 0, {})
        e = self.stsd[0]
        fourcc = e[4:8]
        w = h = ch = sr = 0
        kids = 0
        if self.handler == b"vide" and len(e) >= 8 + 78:
            w, h = struct.unpack_from(">HH", e, 8 + 24)
            kids = 8 + 78
        elif self.handler == b"soun" and len(e) >= 8 + 28:
            ver = struct.unpack_from(">H", e, 8 + 8)[0]
            ch = struct.unpack_from(">H", e, 8 + 16)[0]
            sr = struct.unpack_from(">I", e, 8 + 24)[0] >> 16
            kids = 8 + 28 + (16 if ver == 1 else 36 if ver == 2 else 0)
        cfg = {}
        if kids:
            try:
                for typ, ps_, pe, bs in _mp4_iter(e, kids, len(e)):
                    if typ in MP4_CFG:
                        cfg[typ] = bytes(e[bs:pe])
            except MsgError:
                pass
        return (fourcc, w, h, ch, sr, cfg)


def _desc_len(b, p):
    n = 0
    for _ in range(4):
        c = b[p]
        p += 1
        n = (n << 7) | (c & 0x7F)
        if not c & 0x80:
            break
    return n, p


def _esds_core(box):
    """Az esds dobozból a dekódolót meghatározó rész: (objectTypeIndication, AudioSpecificConfig).
    A bitráta-mezők fájlonként eltérhetnek, ezeket nem vesszük figyelembe."""
    try:
        b = box[12:]                       # fejléc (8) + verzió/flag (4)
        p = 0
        if b[p] == 3:
            n, p = _desc_len(b, p + 1)
            p += 3 + (1 if b[p + 2] & 0x80 else 0) * 2
            if b[p - 3 + 2] & 0x40:
                p += 1 + b[p]
            if b[p - 3 + 2] & 0x20:
                p += 2
        if b[p] != 4:
            return None
        n, p = _desc_len(b, p + 1)
        oti = b[p]
        p += 13
        if p < len(b) and b[p] == 5:
            n, q = _desc_len(b, p + 1)
            return (oti, bytes(b[q:q + n]))
        return (oti, b"")
    except (IndexError, struct.error):
        return None


def mp4_entry_key(e, handler):
    """A mintaleírás lényegi tartalma: a tájékoztató jellegű mezők (btrt, esds-bitráta) nélkül."""
    kids = 0
    if handler == b"vide" and len(e) >= 8 + 78:
        kids = 8 + 78
    elif handler == b"soun" and len(e) >= 8 + 28:
        ver = struct.unpack_from(">H", e, 8 + 8)[0]
        kids = 8 + 28 + (16 if ver == 1 else 36 if ver == 2 else 0)
    if not kids:
        return bytes(e)
    def norm(s, end):
        res = []
        for typ, ps_, pe, bs in _mp4_iter(e, s, end):
            if typ == b"btrt":
                continue
            if typ == b"esds":
                core = _esds_core(bytes(e[bs:pe]))
                res.append(b"esds" + (repr(core).encode() if core is not None else bytes(e[bs:pe])))
            elif typ == b"wave":                 # QuickTime: az esds ebbe van beágyazva
                res.append(b"wave" + b"".join(norm(ps_, pe)))
            else:
                res.append(bytes(e[bs:pe]))
        return res
    try:
        return bytes(e[:kids]) + b"".join(norm(kids, len(e)))
    except MsgError:
        return bytes(e)


def _mp4_parse_stbl(buf, s, e, t):
    for typ, ps_, pe, bs in _mp4_iter(buf, s, e):
        if typ == b"stsd":
            ents = []
            for et, eps, epe, ebs in _mp4_iter(buf, ps_ + 8, pe):
                ents.append(bytes(buf[ebs:epe]))
            t.stsd = ents
        elif typ == b"stts":
            n = struct.unpack_from(">I", buf, ps_ + 4)[0]
            v = struct.unpack_from(">%dI" % (2 * n), buf, ps_ + 8)
            t.stts = list(zip(v[0::2], v[1::2]))
        elif typ == b"ctts":
            n = struct.unpack_from(">I", buf, ps_ + 4)[0]
            t.ctts_ver = buf[ps_]
            v = struct.unpack_from(">%d%s" % (2 * n, "I"), buf, ps_ + 8)
            if t.ctts_ver == 1:
                v = [(x - (1 << 32)) if (i & 1) and x >= (1 << 31) else x for i, x in enumerate(v)]
            t.ctts = list(zip(v[0::2], v[1::2]))
        elif typ == b"stss":
            n = struct.unpack_from(">I", buf, ps_ + 4)[0]
            t.stss = list(struct.unpack_from(">%dI" % n, buf, ps_ + 8))
        elif typ == b"stsc":
            n = struct.unpack_from(">I", buf, ps_ + 4)[0]
            v = struct.unpack_from(">%dI" % (3 * n), buf, ps_ + 8)
            t.stsc = list(zip(v[0::3], v[1::3], v[2::3]))
        elif typ == b"stsz":
            sz, n = struct.unpack_from(">II", buf, ps_ + 4)
            if sz:
                t.uniform = sz
                t.sizes = [sz] * n
            else:
                t.sizes = list(struct.unpack_from(">%dI" % n, buf, ps_ + 12))
        elif typ == b"stz2":
            fs = buf[ps_ + 7]
            n = struct.unpack_from(">I", buf, ps_ + 8)[0]
            d = ps_ + 12
            if fs == 8:
                t.sizes = list(buf[d:d + n])
            elif fs == 16:
                t.sizes = list(struct.unpack_from(">%dH" % n, buf, d))
            elif fs == 4:
                t.sizes = [((buf[d + i // 2] >> (4 if i % 2 == 0 else 0)) & 15) for i in range(n)]
            else:
                raise MsgError("m_tables", 0)
        elif typ == b"stco":
            n = struct.unpack_from(">I", buf, ps_ + 4)[0]
            t.offsets = list(struct.unpack_from(">%dI" % n, buf, ps_ + 8))
        elif typ == b"co64":
            n = struct.unpack_from(">I", buf, ps_ + 4)[0]
            t.offsets = list(struct.unpack_from(">%dQ" % n, buf, ps_ + 8))
        else:
            t.dropped.add(typ.decode("latin-1"))


def _mp4_parse_trak(buf, s, e):
    t = Mp4Track()
    for typ, ps_, pe, bs in _mp4_iter(buf, s, e):
        if typ == b"tkhd":
            v1 = buf[ps_] == 1
            t.id = struct.unpack_from(">I", buf, ps_ + (20 if v1 else 12))[0]
            t.tk_dur = struct.unpack_from(">Q" if v1 else ">I", buf, ps_ + (28 if v1 else 20))[0]
            mo = ps_ + (52 if v1 else 40)
            t.matrix = bytes(buf[mo:mo + 36])
            t.width = struct.unpack_from(">I", buf, mo + 36)[0] >> 16
            t.height = struct.unpack_from(">I", buf, mo + 40)[0] >> 16
        elif typ == b"edts":
            for et, eps, epe, ebs in _mp4_iter(buf, ps_, pe):
                if et == b"elst":
                    ver = buf[eps]
                    n = struct.unpack_from(">I", buf, eps + 4)[0]
                    ent, p = [], eps + 8
                    for _ in range(n):
                        if ver == 1:
                            sd, mt, ri, rf = struct.unpack_from(">QqHH", buf, p)
                            p += 20
                        else:
                            sd, mt, ri, rf = struct.unpack_from(">IiHH", buf, p)
                            p += 12
                        if ri != 1 or rf != 0:
                            raise MsgError("m_rate")
                        ent.append((sd, mt))
                    t.elst = ent
        elif typ == b"mdia":
            for mt_, mps, mpe, mbs in _mp4_iter(buf, ps_, pe):
                if mt_ == b"mdhd":
                    v1 = buf[mps] == 1
                    t.mdts = struct.unpack_from(">I", buf, mps + (20 if v1 else 12))[0] or 1
                elif mt_ == b"hdlr":
                    t.handler = bytes(buf[mps + 8:mps + 12])
                elif mt_ == b"minf":
                    for it, ips, ipe, ibs in _mp4_iter(buf, mps, mpe):
                        if it == b"stbl":
                            _mp4_parse_stbl(buf, ips, ipe, t)
                        elif it == b"dinf":
                            for dt, dps, dpe, dbs in _mp4_iter(buf, ips, ipe):
                                if dt == b"dref":
                                    for ut, ups, upe, ubs in _mp4_iter(buf, dps + 8, dpe):
                                        if not (buf[ups + 3] & 1):
                                            raise MsgError("m_ext")
    return t


def _mp4_edit_entries(t, mvts):
    """Szerkesztőlista [(időtartam a film időskáláján, média_idő|-1)]; ha nincs, az azonosság."""
    if t.elst:
        return list(t.elst)
    d = t.media_dur()
    return [((d * mvts + t.mdts // 2) // t.mdts, 0)]


def _mp4_pres(entries, mvts, mdts, media_t):
    """A média-idő megjelenítési ideje a film időskáláján (vagy None, ha kivágott)."""
    t0 = 0
    for sd, mt in entries:
        if mt >= 0 and mt <= media_t and (media_t - mt) * mvts < sd * mdts:
            return t0 + ((media_t - mt) * mvts) // mdts
        t0 += sd
    return None


def _mp4_validate(t, idx, mdats):
    n = t.n
    if sum(c for c, d in t.stts) != n or (t.ctts is not None and sum(c for c, d in t.ctts) != n):
        raise MsgError("m_tables", idx)
    try:
        spc, sdi, cfs, total = t.layout()
    except MsgError:
        raise MsgError("m_tables", idx)
    if total != n:
        raise MsgError("m_tables", idx)
    if t.stss is not None and any(x < 1 or x > n for x in t.stss):
        raise MsgError("m_tables", idx)
    if sdi and (min(sdi) < 1 or max(sdi) > len(t.stsd)):
        raise MsgError("m_tables", idx)
    for e in t.stsd:
        if e[4:8] in MP4_ENC:
            raise MsgError("m_enc")
    starts = [m[0] for m in mdats]
    t.ranges = []
    pos = 0
    sizes = t.sizes
    for c, sp in enumerate(spc):
        nb = sum(sizes[pos:pos + sp])
        pos += sp
        off = t.offsets[c]
        j = bisect.bisect_right(starts, off) - 1
        if j < 0 or off + nb > mdats[j][1]:
            raise MsgError("m_range", idx)
        t.ranges.append((off, nb))


class Mp4Info:
    kind = "mp4"

    def __init__(self, path):
        self.path = path
        self.name = os.path.basename(path)
        self.pending = True
        self.error = None
        self.size = 0
        self.duration = 0.0
        self.tracks = []
        self.mvts = 1000
        self.ftyp = b""
        self.moov = b""
        self.moov_ps = 0
        self.mdats = []          # [(tartalom_kezdet, vég)] a fájlban
        self.top = []

    def analyze(self):
        self.size = os.path.getsize(self.path)
        if self.size < 16:
            raise MsgError("err_small")
        with open(self.path, "rb") as f:
            top = _mp4_scan_top(f, self.size)
            self.top = top
            types = [x[0] for x in top]
            if b"moof" in types:
                raise MsgError("m_frag")
            mo = [x for x in top if x[0] == b"moov"]
            if not mo:
                raise MsgError("m_nomoov")
            ft = [x for x in top if x[0] == b"ftyp"]
            if ft:
                f.seek(ft[0][1])
                self.ftyp = f.read(ft[0][3] - ft[0][1])
            f.seek(mo[0][1])
            self.moov = f.read(mo[0][3] - mo[0][1])
        self.moov_ps = mo[0][2] - mo[0][1]
        self.mdats = [(x[2], x[3]) for x in top if x[0] == b"mdat"]
        m = self.moov
        trs = 0
        for typ, ps_, pe, bs in _mp4_iter(m, self.moov_ps, len(m)):
            if typ == b"mvhd":
                v1 = m[ps_] == 1
                self.mvts = struct.unpack_from(">I", m, ps_ + (20 if v1 else 12))[0] or 1000
            elif typ == b"mvex":
                raise MsgError("m_frag")
            elif typ == b"trak":
                self.tracks.append(_mp4_parse_trak(m, ps_, pe))
                trs += 1
        if not self.tracks:
            raise MsgError("m_notrack")
        for i, t in enumerate(self.tracks):
            _mp4_validate(t, i + 1, self.mdats)
        self.duration = max(sum(sd for sd, mt in _mp4_edit_entries(t, self.mvts))
                            for t in self.tracks) / float(self.mvts)

    def _track(self, handler):
        for t in self.tracks:
            if t.handler == handler:
                return t
        return None

    def vdesc(self):
        t = self._track(b"vide")
        if not t or not t.stsd:
            return "?"
        fc, w, h, ch, sr, cfg = t.entry_info()
        return "%s %dx%d %g fps" % (MP4_VNAMES.get(fc, fc.decode("latin-1").strip()), w, h, round(t.fps(), 2))

    def adesc(self):
        t = self._track(b"soun")
        if not t or not t.stsd:
            return tr("no_audio")
        fc, w, h, ch, sr, cfg = t.entry_info()
        return "%s %dch %d Hz" % (MP4_ANAMES.get(fc, fc.decode("latin-1").strip()), ch, sr)


def mp4_compare(ref, inf):
    bad, warn = [], []
    if len(inf.tracks) != len(ref.tracks):
        return "bad", tr("c_mp4_tracks")
    for i, (a, b) in enumerate(zip(ref.tracks, inf.tracks)):
        if a.handler != b.handler:
            bad.append(tr("c_mp4_kind", i + 1))
            continue
        if a.mdts != b.mdts:
            bad.append(tr("c_mp4_ts", i + 1))
        fa, wa, ha, cha, sra, cfa = a.entry_info()
        fb, wb, hb, chb, srb, cfb = b.entry_info()
        if fa != fb:
            bad.append(tr("c_mp4_codec", i + 1, fa.decode("latin-1"), fb.decode("latin-1")))
            continue
        if a.handler == b"vide":
            if (wa, ha) != (wb, hb):
                bad.append(tr("c_res"))
            if a.matrix != b.matrix:
                bad.append(tr("c_mp4_matrix"))
            fpa, fpb = a.fps(), b.fps()
            if fpa and fpb and abs(fpa - fpb) > 0.01 * fpa:
                warn.append(tr("c_fps"))
        elif a.handler == b"soun":
            if (cha, sra) != (chb, srb):
                bad.append(tr("c_afmt"))
        if a.stsd and b.stsd and mp4_entry_key(a.stsd[0], a.handler) != mp4_entry_key(b.stsd[0], b.handler):
            warn.append(tr("c_mp4_cfg", i + 1))
    if bad:
        return "bad", "; ".join(bad)
    if warn:
        return "warn", "; ".join(warn)
    return "ok", tr("c_ok")


def _box(typ, payload):
    return struct.pack(">I4s", len(payload) + 8, typ) + payload


def _fbox(typ, vf, payload):
    return _box(typ, struct.pack(">I", vf) + payload)


def _pk(ch, vals):
    out = bytearray()
    for i in range(0, len(vals), 50000):
        part = vals[i:i + 50000]
        out += struct.pack(">%d%s" % (len(part), ch), *part)
    return bytes(out)


def _rle_add(lst, count, val):
    if count <= 0:
        return
    if lst and lst[-1][1] == val:
        lst[-1][0] += count
    else:
        lst.append([count, val])


def _mp4_rebuild(buf, s, e, fn):
    out = []
    for typ, ps_, pe, bs in _mp4_iter(buf, s, e):
        r = fn(typ, ps_, pe, bs)
        out.append(bytes(buf[bs:pe]) if r is None else r)
    return b"".join(out)


def _mp4_patch(buf, ps_, pe, bs, off0, off1, value):
    raw = bytearray(buf[bs:pe])
    h = ps_ - bs
    if raw[h] == 1:
        struct.pack_into(">Q", raw, h + off1, value)
    else:
        if value > 0xFFFFFFFF:
            raise MsgError("m_big")
        struct.pack_into(">I", raw, h + off0, value)
    return bytes(raw)


def _mp4_merge_edits(lst, mvts, mdts):
    out = []
    for sd, mt in lst:
        if sd <= 0:
            continue
        if out:
            psd, pmt = out[-1]
            if pmt < 0 and mt < 0:
                out[-1] = (psd + sd, -1)
                continue
            if pmt >= 0 and mt >= 0 and pmt * mvts + psd * mdts == mt * mvts:
                out[-1] = (psd + sd, pmt)
                continue
        out.append((sd, mt))
    return out


def _mp4_elst_box(ents):
    big = any(sd > 0xFFFFFFFF or mt > 0x7FFFFFFF for sd, mt in ents)
    if big:
        body = b"".join(struct.pack(">QqHH", sd, mt, 1, 0) for sd, mt in ents)
    else:
        body = b"".join(struct.pack(">IiHH", sd, mt, 1, 0) for sd, mt in ents)
    return _box(b"edts", _fbox(b"elst", 1 if big else 0, struct.pack(">I", len(ents)) + body))


def mp4_join(infos, out_path, progress=None, log=None, cancel=None, verify=True):
    log = log or (lambda s: None)
    progress = progress or (lambda f: None)
    ref = infos[0]
    nf, nt, mvts = len(infos), len(ref.tracks), ref.mvts
    log(tr("l_mp4_head", nf, nt))

    # --- a forrásfájlok mdat-területeinek leképezése a kimenet adatterületére
    base, regs, pos = [], [], 0
    for inf in infos:
        base.append(pos)
        r = []
        for s, e in inf.mdats:
            r.append((s, e, pos))
            pos += e - s
        regs.append(r)
    total_payload = pos
    starts = [[x[0] for x in r] for r in regs]

    def rel(k, off):
        j = bisect.bisect_right(starts[k], off) - 1
        s, e, p = regs[k][j]
        return p + off - s

    # --- szerkesztőlisták tervezése: minden fájl a saját időzítését megtartja
    ent_rel = [[None] * nt for _ in range(nf)]
    for k, inf in enumerate(infos):
        for ti, t in enumerate(inf.tracks):
            ent_rel[k][ti] = [((sd if inf.mvts == mvts else (sd * mvts + inf.mvts // 2) // inf.mvts), mt)
                              for sd, mt in _mp4_edit_entries(t, inf.mvts)]
    file_dur = [max(sum(sd for sd, _ in ent_rel[k][ti]) for ti in range(nt)) for k in range(nf)]
    cum, run = [], 0
    for d in file_dur:
        cum.append(run)
        run += d
    # Ha egy sáv rövidebb a fájl hosszánál, a hiányt az utolsó minta időtartamának
    # megnyújtásával pótoljuk (az időbélyegek így minden lejátszóban helyesek maradnak;
    # a mid-fájl üres szerkesztést pl. az ffmpeg figyelmen kívül hagyja).
    pads = [[0] * nt for _ in range(nf)]
    padm = [[0] * nt for _ in range(nf)]
    for k in range(nf - 1):
        for ti in range(nt):
            t = infos[k].tracks[ti]
            lst = ent_rel[k][ti]
            pad = file_dur[k] - sum(sd for sd, _ in lst)
            if pad <= 0:
                continue
            pads[k][ti] = pad
            sd_l, mt_l = lst[-1]
            if mt_l >= 0 and abs(mt_l * mvts + sd_l * t.mdts - t.media_dur() * mvts) <= 1.5 * t.mdts and t.stts:
                padm[k][ti] = (pad * t.mdts + mvts // 2) // mvts
                lst[-1] = (sd_l + pad, mt_l)
            else:
                lst.append((pad, -1))          # tartalék: üres szerkesztés
    for k in range(nf - 1):
        for ti in range(nt):
            if pads[k][ti]:
                log(tr("l_mp4_pad", k + 1, ti + 1, pads[k][ti] * 1000.0 / mvts))

    # --- sávonkénti táblák összefűzése
    ns = [[0] * nt for _ in range(nf)]
    mdur = [[0] * nt for _ in range(nf)]
    sbase = [[0] * nt for _ in range(nf)]
    mbase = [[0] * nt for _ in range(nf)]
    T = []
    dropped = set()
    for ti in range(nt):
        ts = [inf.tracks[ti] for inf in infos]
        ent, keys, maps = [], [], []
        for t in ts:
            mp = {}
            for i, e in enumerate(t.stsd):
                kk = mp4_entry_key(e, t.handler)
                if kk in keys:
                    mp[i + 1] = keys.index(kk) + 1
                else:
                    ent.append(e)
                    keys.append(kk)
                    mp[i + 1] = len(ent)
            maps.append(mp)
            dropped |= t.dropped - MP4_CORE_NAMES
        if len(ent) > 1:
            log(tr("l_mp4_desc", ti + 1, len(ent)))
        any_ctts = any(t.ctts is not None for t in ts)
        ctts_ver = max([t.ctts_ver for t in ts if t.ctts is not None] or [0])
        any_stss = any(t.stss is not None for t in ts)
        stts, ctts, stss, stsc, sizes, relo = [], [], [], [], [], []
        uniform = ts[0].uniform if all(t.uniform == ts[0].uniform for t in ts) else 0
        sb = cb = mb = 0
        for k, t in enumerate(ts):
            sl = list(t.stts)
            if padm[k][ti]:
                c, d = sl[-1]
                sl = sl[:-1] + ([(c - 1, d)] if c > 1 else []) + [(1, d + padm[k][ti])]
            for c, d in sl:
                _rle_add(stts, c, d)
            if any_ctts:
                for c, o in (t.ctts if t.ctts is not None else [(t.n, 0)]):
                    if ctts_ver == 0 and o < 0:
                        raise MsgError("m_big")
                    _rle_add(ctts, c, o)
            if any_stss:
                if t.stss is None:
                    stss.extend(range(sb + 1, sb + t.n + 1))
                else:
                    stss.extend(x + sb for x in t.stss)
            for fc, sp, sd in t.stsc:
                ne = (fc + cb, sp, maps[k][sd])
                if not stsc or stsc[-1][1:] != ne[1:]:
                    stsc.append(ne)
            sizes.extend(t.sizes)
            relo.extend(rel(k, o) for o in t.offsets)
            ns[k][ti] = t.n
            mdur[k][ti] = t.media_dur() + padm[k][ti]
            sbase[k][ti] = sb
            mbase[k][ti] = mb
            sb += t.n
            cb += len(t.offsets)
            mb += mdur[k][ti]
        T.append({"ent": ent, "stts": stts, "ctts": ctts if any_ctts else None, "ctts_ver": ctts_ver,
                  "stss": stss if any_stss else None, "stsc": stsc, "sizes": sizes,
                  "uniform": uniform, "relo": relo, "mdts": ts[0].mdts, "media": mb, "n": sb})
    if dropped:
        log(tr("l_mp4_drop", ", ".join(sorted(dropped))))

    # --- végső szerkesztőlisták (a média-idők már a kimenet idővonalán)
    final = [[] for _ in range(nt)]
    for k in range(nf):
        for ti in range(nt):
            final[ti].extend((sd, mt if mt < 0 else mt + mbase[k][ti]) for sd, mt in ent_rel[k][ti])
    movie_dur = 0
    for ti in range(nt):
        t = T[ti]
        e = _mp4_merge_edits(final[ti], mvts, t["mdts"])
        omit = (len(e) == 1 and e[0][1] == 0 and abs(e[0][0] * t["mdts"] - t["media"] * mvts) <= t["mdts"])
        t["edits"] = None if omit else e
        t["pres"] = ((t["media"] * mvts + t["mdts"] // 2) // t["mdts"]) if omit else sum(sd for sd, _ in e)
        movie_dur = max(movie_dur, t["pres"])

    # --- elrendezés: ftyp + moov (elöl, gyors indítás) + mdat
    ftyp = ref.ftyp or _box(b"ftyp", b"isom\x00\x00\x02\x00isomiso2mp41")
    use64 = len(ftyp) + total_payload + (64 << 20) > MP4_CO64_AT
    big_mdat = total_payload + 8 > MP4_MDAT64_AT
    mdat_hdr = struct.pack(">I4sQ", 1, b"mdat", total_payload + 16) if big_mdat \
        else struct.pack(">I4s", total_payload + 8, b"mdat")

    def build_moov(ps0):
        m = ref.moov
        cnt = [0]

        def fn_stbl(ti):
            t = T[ti]
            parts = [_fbox(b"stsd", 0, struct.pack(">I", len(t["ent"])) + b"".join(t["ent"])),
                     _fbox(b"stts", 0, struct.pack(">I", len(t["stts"])) +
                           _pk("I", [x for c, d in t["stts"] for x in (c, d)]))]
            if t["stss"] is not None:
                parts.append(_fbox(b"stss", 0, struct.pack(">I", len(t["stss"])) + _pk("I", t["stss"])))
            if t["ctts"] is not None:
                f = ">Ii" if t["ctts_ver"] == 1 else ">II"
                parts.append(_fbox(b"ctts", t["ctts_ver"] << 24, struct.pack(">I", len(t["ctts"])) +
                                   b"".join(struct.pack(f, c, o) for c, o in t["ctts"])))
            parts.append(_fbox(b"stsc", 0, struct.pack(">I", len(t["stsc"])) +
                               _pk("I", [x for e in t["stsc"] for x in e])))
            if t["uniform"]:
                parts.append(_fbox(b"stsz", 0, struct.pack(">II", t["uniform"], t["n"])))
            else:
                parts.append(_fbox(b"stsz", 0, struct.pack(">II", 0, t["n"]) + _pk("I", t["sizes"])))
            offs = [o + ps0 for o in t["relo"]]
            if use64:
                parts.append(_fbox(b"co64", 0, struct.pack(">I", len(offs)) + _pk("Q", offs)))
            else:
                parts.append(_fbox(b"stco", 0, struct.pack(">I", len(offs)) + _pk("I", offs)))
            return _box(b"stbl", b"".join(parts))

        def fn_trak(ti):
            t = T[ti]

            def f_minf(typ, ps_, pe, bs):
                return fn_stbl(ti) if typ == b"stbl" else None

            def f_mdia(typ, ps_, pe, bs):
                if typ == b"mdhd":
                    return _mp4_patch(m, ps_, pe, bs, 16, 24, t["media"])
                if typ == b"minf":
                    return _box(b"minf", _mp4_rebuild(m, ps_, pe, f_minf))
                return None

            def f_trak(typ, ps_, pe, bs):
                if typ == b"tkhd":
                    r = _mp4_patch(m, ps_, pe, bs, 20, 28, t["pres"])
                    return r + (_mp4_elst_box(t["edits"]) if t["edits"] else b"")
                if typ == b"edts":
                    return b""
                if typ == b"mdia":
                    return _box(b"mdia", _mp4_rebuild(m, ps_, pe, f_mdia))
                return None
            return f_trak

        def f_moov(typ, ps_, pe, bs):
            if typ == b"mvhd":
                return _mp4_patch(m, ps_, pe, bs, 16, 24, movie_dur)
            if typ == b"trak":
                ti = cnt[0]
                cnt[0] += 1
                return _box(b"trak", _mp4_rebuild(m, ps_, pe, fn_trak(ti)))
            return None
        return _box(b"moov", _mp4_rebuild(m, ref.moov_ps, len(m), f_moov))

    moov = build_moov(0)
    ps0 = len(ftyp) + len(moov) + len(mdat_hdr)
    moov2 = build_moov(ps0)
    if len(moov2) != len(moov):
        raise MsgError("m_big")
    moov = moov2
    log(tr("l_mp4_layout", "64" if big_mdat else "32", "co64" if use64 else "stco"))

    try:
        import shutil
        free = shutil.disk_usage(os.path.dirname(os.path.abspath(out_path)) or ".").free
        if free < total_payload + len(moov) + 50 * 1024 * 1024:
            raise MsgError("j_space")
    except OSError:
        pass

    share = 0.5 if verify else 1.0
    done = [0]
    crcs = []
    tmp = out_path + ".part"
    try:
        with open(tmp, "wb") as fo:
            fo.write(ftyp)
            fo.write(moov)
            fo.write(mdat_hdr)
            for k, inf in enumerate(infos):
                log(tr("l_mp4_file", k + 1, inf.name, cum[k] / float(mvts)))
                crc = 0
                with open(inf.path, "rb") as fi:
                    for s, e in inf.mdats:
                        fi.seek(s)
                        left = e - s
                        while left > 0:
                            if cancel is not None and cancel.is_set():
                                raise _Cancelled()
                            data = fi.read(min(left, 4 * 1024 * 1024))
                            if not data:
                                raise MsgError("m_trunc")
                            fo.write(data)
                            crc = zlib.crc32(data, crc)
                            left -= len(data)
                            done[0] += len(data)
                            progress(share * done[0] / float(max(1, total_payload)))
                crcs.append(crc)
        plan = {"nt": nt, "nf": nf, "ns": ns, "mdur": mdur, "sbase": sbase, "mbase": mbase,
                "base": base, "plen": [sum(e - s for s, e in inf.mdats) for inf in infos],
                "crc": crcs, "total_payload": total_payload, "file_dur": file_dur, "cum": cum,
                "pads": pads, "padm": padm, "mvts": mvts, "movie_dur": movie_dur}
        if verify:
            vres = mp4_verify(tmp, infos, plan, lambda f: progress(share + (1.0 - share) * f), log, cancel)
            if vres is None:
                raise _Cancelled()
            if vres[0]:
                root, ext = os.path.splitext(out_path)
                bad = root + "_HIBAS" + ext
                os.replace(tmp, bad)
                raise MsgError("v_failed", vres[0], bad)
        else:
            log(tr("l_verify_off"))
        os.replace(tmp, out_path)
    except _Cancelled:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    log(tr("l_done", out_path))
    return True


class _Cancelled(Exception):
    pass


MP4_CORE_NAMES = {x.decode("latin-1") for x in MP4_CORE}
MP4_CHECKS = ("struct", "tables", "data", "timing", "vseam", "sync")


def _rle_ext_last(rle, add):
    """Az utolsó minta időtartamát `add`-dal megnöveli (RLE-listán)."""
    if not add or not rle:
        return rle
    c, v = rle[-1]
    return list(rle[:-1]) + ([(c - 1, v)] if c > 1 else []) + [(1, v + add)]


def _rle_slice(rle, start, n):
    out, pos, end = [], 0, start + n
    for c, v in rle:
        a, b = max(pos, start), min(pos + c, end)
        if b > a:
            _rle_add(out, b - a, v)
        pos += c
        if pos >= end:
            break
    return [tuple(x) for x in out]


def mp4_verify(path, infos, plan, progress=None, log=None, cancel=None):
    """A kész MP4 ellenőrzése. (hibák, figyelmeztetések) vagy None, ha megszakították."""
    log = log or (lambda s: None)
    progress = progress or (lambda f: None)
    nf, nt, mvts = plan["nf"], plan["nt"], plan["mvts"]
    res = {k: [0, 0] for k in MP4_CHECKS}
    shown = Counter()

    def issue(chk, sev, key, *a):
        res[chk][0 if sev == "E" else 1] += 1
        shown[chk] += 1
        if shown[chk] <= MAX_SHOWN:
            log("   %s %s" % ("✗" if sev == "E" else "!", tr(key, *a)))
        elif shown[chk] == MAX_SHOWN + 1:
            log(tr("v_more", tr("mc_" + chk)))

    def finish():
        return _verify_summary(res, log, MP4_CHECKS, "mc_")

    log(tr("v_head", nf - 1))
    log(tr("v_what"))
    for key in MP4_CHECKS:
        log("   • %s: %s" % (tr("mc_" + key), tr("md_" + key)))

    # ---------------- 1. szerkezet és táblák ----------------
    log(tr("m_pass1"))
    out = Mp4Info(path)
    try:
        out.analyze()
    except MsgError as e:
        chk = "tables" if e.key in ("m_tables", "m_range") else "struct"
        issue(chk, "E", "mv_boxes", str(e))
        return finish()
    except Exception as e:                      # váratlan szerkezeti hiba
        issue("struct", "E", "mv_boxes", str(e) or e.__class__.__name__)
        return finish()
    types = [x[0] for x in out.top]
    if types.count(b"moov") != 1:
        issue("struct", "E", "mv_moovn", types.count(b"moov"))
    if types.count(b"mdat") != 1:
        issue("struct", "E", "mv_mdatn", types.count(b"mdat"))
        return finish()
    if len(out.tracks) != nt:
        issue("struct", "E", "mv_tracks", len(out.tracks), nt)
        return finish()
    ps0, pe0 = out.mdats[0]
    if pe0 - ps0 != plan["total_payload"]:
        issue("struct", "E", "mv_plen", pe0 - ps0, plan["total_payload"])
    for ti in range(nt):
        a, b = infos[0].tracks[ti], out.tracks[ti]
        if a.handler != b.handler:
            issue("struct", "E", "mv_kind", ti + 1)
    ivals = []
    for ti, t in enumerate(out.tracks):
        want = sum(plan["ns"][k][ti] for k in range(nf))
        if t.n != want:
            issue("tables", "E", "mv_count", ti + 1, t.n, want)
        wd = sum(plan["mdur"][k][ti] for k in range(nf))
        if t.media_dur() != wd:
            issue("tables", "E", "mv_mdur", ti + 1, t.media_dur(), wd)
        if t.stss is not None and any(b <= a for a, b in zip(t.stss, t.stss[1:])):
            issue("tables", "E", "mv_stss", ti + 1)
        for off, nb in t.ranges:
            if nb:
                ivals.append((off, off + nb))
    ivals.sort()
    for (a0, a1), (b0, b1) in zip(ivals, ivals[1:]):
        if b0 < a1:
            issue("tables", "E", "mv_overlap", a1 - b0)
            break

    # ---------------- 2. adatintegritás ----------------
    log(tr("m_pass2"))
    total = max(1, plan["total_payload"])
    donebytes = 0
    with open(path, "rb") as f:
        for k in range(nf):
            f.seek(ps0 + plan["base"][k])
            left, crc = plan["plen"][k], 0
            while left > 0:
                if cancel is not None and cancel.is_set():
                    return None
                data = f.read(min(left, 4 * 1024 * 1024))
                if not data:
                    break
                crc = zlib.crc32(data, crc)
                left -= len(data)
                donebytes += len(data)
                progress(donebytes / float(total))
            if left or crc != plan["crc"][k]:
                issue("data", "E", "mv_crc", k + 1)
        # a varratoknál mintánként is összevetjük az új és az eredeti helyet
        for k in range(nf):
            with open(infos[k].path, "rb") as fs:
                for ti in range(nt):
                    n = plan["ns"][k][ti]
                    for i in sorted({0, 1, n - 2, n - 1}):
                        if i < 0 or i >= n:
                            continue
                        so, sz = infos[k].tracks[ti].sample_loc(i)
                        oo, oz = out.tracks[ti].sample_loc(plan["sbase"][k][ti] + i)
                        ok = (sz == oz)
                        if ok and sz:
                            fs.seek(so)
                            a = fs.read(min(sz, 1 << 22))
                            f.seek(oo)
                            ok = (a == f.read(len(a)))
                        if not ok:
                            issue("data", "E", "mv_spot", k + 1, ti + 1, i + 1)

    # ---------------- 3. időzítés, kulcskockák, A/V szinkron ----------------
    log(tr("m_pass3"))
    for ti, t in enumerate(out.tracks):
        o_ctts = t.ctts if t.ctts is not None else [(t.n, 0)]
        for k in range(nf):
            n, sb = plan["ns"][k][ti], plan["sbase"][k][ti]
            st = infos[k].tracks[ti]
            if _rle_slice(t.stts, sb, n) != _rle_ext_last(_rle_slice(st.stts, 0, n), plan["padm"][k][ti]):
                issue("timing", "E", "mv_tim", k + 1, ti + 1)
            elif _rle_slice(o_ctts, sb, n) != _rle_slice(st.ctts if st.ctts is not None else [(n, 0)], 0, n):
                issue("timing", "E", "mv_tim", k + 1, ti + 1)
        if t.handler in (b"vide", b"soun"):
            for c, d in t.stts:
                if (d == 0 and c > 1) or d > 2 * t.mdts:
                    issue("timing", "W", "mv_dt", ti + 1, d * 1000.0 / t.mdts)
                    break
        want_pres = sum(sd for sd, _ in _mp4_edit_entries(t, out.mvts))
        if t.tk_dur != want_pres:
            issue("timing", "E", "mv_tkhd", ti + 1)
    if abs(out.duration * mvts - plan["movie_dur"]) > 1 or abs(plan["movie_dur"] - sum(plan["file_dur"])) > 2:
        issue("timing", "E", "mv_dur", _fmt_t(out.duration), _fmt_t(sum(plan["file_dur"]) / float(mvts)))

    vi = next((i for i, t in enumerate(out.tracks) if t.handler == b"vide"), None)
    key_ok = {}
    if vi is not None:
        vt = out.tracks[vi]
        kset = set(vt.stss) if vt.stss is not None else None
        for k in range(nf):
            if plan["ns"][k][vi] == 0:
                continue
            first = plan["sbase"][k][vi] + 1
            src = infos[k].tracks[vi]
            key_ok[k] = kset is None or first in kset
            if not key_ok[k]:
                issue("vseam", "W", "mv_key", k, k + 1)

    # A/V szinkron: a forrás szerkesztőlistájának hasznos szakaszában (kezdet és vég) minden
    # média-pont megjelenítési ideje a kimeneten pontosan a fájl kezdete + az eredeti idő kell legyen.
    # (Az első minta nem jó mérőpont: pl. az AAC előtöltést a szerkesztőlista levágja.)
    for ti, t in enumerate(out.tracks):
        ent_o = _mp4_edit_entries(t, out.mvts)
        for k in range(nf):
            if plan["ns"][k][ti] == 0:
                continue
            inf, st = infos[k], infos[k].tracks[ti]
            ent_s = _mp4_edit_entries(st, inf.mvts)
            ne = [(sd, mt) for sd, mt in ent_s if mt >= 0]
            if not ne:
                continue
            probes = [ne[0][1], ne[-1][1] + (ne[-1][0] * st.mdts) // inf.mvts - 2]
            for mt_src in probes:
                sp = _mp4_pres(ent_s, inf.mvts, st.mdts, mt_src)
                if sp is None:
                    continue
                sp = (sp * mvts + inf.mvts // 2) // inf.mvts
                want = plan["cum"][k] + sp
                op = _mp4_pres(ent_o, out.mvts, t.mdts, mt_src + plan["mbase"][k][ti])
                if op is None:
                    issue("sync", "E", "mv_sync_out", k + 1, ti + 1)
                    break
                if abs(op - want) > 2:
                    issue("sync", "E", "mv_sync", k + 1, ti + 1, (op - want) * 1000.0 / mvts)
                    break

    for k in range(nf - 1):
        for ti, t in enumerate(out.tracks):
            p = plan["pads"][k][ti]
            if not p or not t.stts:
                continue
            thr = t.stts[0][1] * mvts / float(t.mdts)
            if p > mvts:
                issue("sync", "E", "mv_pad_e", k + 1, ti + 1, p * 1000.0 / mvts)
            elif p > thr:
                issue("sync", "W", "mv_pad", k + 1, ti + 1, p * 1000.0 / mvts)

    # varratonkénti összegzés
    if 0 < nf - 1 <= 40:
        log(tr("v_seam_hdr2"))
        for k in range(1, nf):
            pv = []
            for ti, t in enumerate(out.tracks):
                p = plan["pads"][k - 1][ti]
                pv.append("%d. %s %.1f ms" % (ti + 1, t.handler.decode("latin-1"), p * 1000.0 / mvts))
            kt = tr("v_key_ok") if key_ok.get(k, True) else tr("v_key_no")
            log(tr("v_seam_line2", k, _fmt_t(plan["cum"][k] / float(mvts)), " | ".join(pv), kt))
    return finish()


# ============================================================ MKV / WEBM ====
# Veszteségmentes Matroska (MKV / MKA / WebM) összefűzés. A blokkok (kép-, hang-,
# feliratadat) bájtra azonosan másolódnak; csak a Cluster időbélyegek tolódnak el
# (a blokkok Cluster-hez viszonyított ideje változatlan marad), a Cues (keresőindex)
# és a SeekHead újra készül. Csak a Python standard könyvtárát használja
# (RFC 8794 – EBML, RFC 9559 – Matroska – nyilvános specifikáció alapján).

MKV_EXTS = (".mkv", ".mka", ".mk3d", ".webm")
ID_EBML = 0x1A45DFA3
ID_SEGMENT = 0x18538067
ID_SEEKHEAD = 0x114D9B74
ID_INFO = 0x1549A966
ID_TRACKS = 0x1654AE6B
ID_CLUSTER = 0x1F43B675
ID_CUES = 0x1C53BB6B
ID_CHAPTERS = 0x1043A770
ID_TAGS = 0x1254C367
ID_ATTACHMENTS = 0x1941A469
ID_VOID = 0xEC
ID_CRC32 = 0xBF
ID_TIMECODE = 0xE7
ID_POSITION = 0xA7
ID_PREVSIZE = 0xAB
ID_SIMPLEBLOCK = 0xA3
ID_BLOCKGROUP = 0xA0
ID_BLOCK = 0xA1
ID_BLOCKDURATION = 0x9B
ID_REFBLOCK = 0xFB
MKV_L1 = {ID_CLUSTER, ID_CUES, ID_TAGS, ID_SEEKHEAD, ID_INFO, ID_TRACKS, ID_CHAPTERS,
          ID_ATTACHMENTS}
MKV_TRK_KEYS = {0xD7, 0x83, 0x86, 0x63A2, 0x23E383, 0xE0, 0xE1, 0x6D80, 0x56AA, 0x56BB}
MKV_CHECKS = ("struct", "index", "data", "timing", "vseam", "audio", "sync")
MKV_UNKNOWN = b"\x01\xff\xff\xff\xff\xff\xff\xff"
MKV_VNAMES = {"V_MPEG4/ISO/AVC": "H.264", "V_MPEGH/ISO/HEVC": "HEVC", "V_VP8": "VP8",
              "V_VP9": "VP9", "V_AV1": "AV1", "V_MPEG2": "MPEG-2", "V_MPEG1": "MPEG-1",
              "V_MS/VFW/FOURCC": "VfW", "V_THEORA": "Theora", "V_PRORES": "ProRes"}
MKV_ANAMES = {"A_AAC": "AAC", "A_AC3": "AC-3", "A_EAC3": "E-AC-3", "A_DTS": "DTS",
              "A_OPUS": "Opus", "A_VORBIS": "Vorbis", "A_FLAC": "FLAC", "A_MPEG/L3": "MP3",
              "A_MPEG/L2": "MP2", "A_TRUEHD": "TrueHD", "A_PCM/INT/LIT": "PCM",
              "A_PCM/INT/BIG": "PCM", "A_PCM/FLOAT/IEEE": "PCM", "A_ALAC": "ALAC"}
_Q = struct.Struct(">q")


def _mkv_hdr(buf, p):
    """Elemfejléc a buf p. bájtjától: (azonosító, méret | None ha ismeretlen, fejléchossz)."""
    n = len(buf)
    if p >= n:
        raise MsgError("k_trunc")
    first = buf[p]
    il, mask = 1, 0x80
    while il <= 4 and not first & mask:
        mask >>= 1
        il += 1
    if il > 4:
        raise MsgError("k_ebml")
    q = p + il
    if q >= n:
        raise MsgError("k_trunc")
    eid = int.from_bytes(buf[p:q], "big")
    first = buf[q]
    sl, mask = 1, 0x80
    while sl <= 8 and not first & mask:
        mask >>= 1
        sl += 1
    if sl > 8:
        raise MsgError("k_ebml")
    if q + sl > n:
        raise MsgError("k_trunc")
    v = first & (mask - 1)
    ones = v == mask - 1
    for c in buf[q + 1:q + sl]:
        v = (v << 8) | c
        if c != 0xFF:
            ones = False
    return eid, (None if ones else v), il + sl


def _mkv_children(buf, s, e):
    """(azonosító, tartalom_kezdet, vég, elem_kezdet) a memóriában lévő buf [s, e) elemeire."""
    p = s
    while p < e:
        eid, size, hl = _mkv_hdr(buf, p)
        if size is None:
            size = e - p - hl
        end = p + hl + size
        if end > e:
            raise MsgError("k_trunc")
        yield eid, p + hl, end, p
        p = end


def _mkv_f_hdr(f, pos):
    f.seek(pos)
    h = f.read(12)
    if not h or not h.strip(b"\x00"):
        return None
    return _mkv_hdr(h, 0)


def _mkv_walk(f, s, e):
    """Fájlban lévő [s, e) tartomány elemei (csak fejlécet olvas): mint _mkv_children."""
    p = s
    while p < e:
        f.seek(p)
        eid, size, hl = _mkv_hdr(f.read(12), 0)
        if size is None:
            raise MsgError("k_unk")
        end = p + hl + size
        if end > e:
            raise MsgError("k_trunc")
        yield eid, p + hl, end, p
        p = end


def _mkv_cluster_end(f, ds, limit):
    """Ismeretlen méretű Cluster vége: az első olyan elem, ami már nem a cluster gyermeke."""
    p = ds
    while p < limit:
        h = _mkv_f_hdr(f, p)
        if h is None:
            return p
        eid, sz, hl = h
        if eid in MKV_L1:
            return p
        if sz is None:
            raise MsgError("k_unk")
        p += hl + sz
    if p > limit:
        raise MsgError("k_trunc")
    return p


def _mkv_block_hdr(b):
    """Blokk elejéből: (sáv, relatív idő, jelzők, keretek száma)."""
    if len(b) < 4:
        raise MsgError("k_block")
    first = b[0]
    n, mask = 1, 0x80
    while n <= 8 and not first & mask:
        mask >>= 1
        n += 1
    if n > 4 or len(b) < n + 4:
        raise MsgError("k_block")
    track = first & (mask - 1)
    for c in b[1:n]:
        track = (track << 8) | c
    rel = int.from_bytes(b[n:n + 2], "big", signed=True)
    flags = b[n + 2]
    nfr = (b[n + 3] + 1) if (flags >> 1) & 3 else 1
    return track, rel, flags, nfr


def _mkv_cluster_tc(f, ds, end):
    for eid, cs, ce, cp in _mkv_walk(f, ds, end):
        if eid == ID_TIMECODE:
            f.seek(cs)
            return int.from_bytes(f.read(ce - cs), "big")
    raise MsgError("k_ebml")


def _mkv_cluster_items(f, ds, end):
    """A cluster gyermekei: (azonosító, elem_kezdet, elem_vég, blokkinfó | None).
    blokkinfó = (sáv, relatív idő, jelzők, keretek, kulcskocka, BlockDuration | None)."""
    for eid, cs, ce, cp in _mkv_walk(f, ds, end):
        if eid == ID_SIMPLEBLOCK:
            f.seek(cs)
            tk, rel, fl, nfr = _mkv_block_hdr(f.read(min(16, ce - cs)))
            yield eid, cp, ce, (tk, rel, fl, nfr, bool(fl & 0x80), None)
        elif eid == ID_BLOCKGROUP:
            blk = dur = None
            ref = False
            for e2, s2, en2, p2 in _mkv_walk(f, cs, ce):
                if e2 == ID_BLOCK:
                    f.seek(s2)
                    blk = _mkv_block_hdr(f.read(min(16, en2 - s2)))
                elif e2 == ID_BLOCKDURATION:
                    f.seek(s2)
                    dur = int.from_bytes(f.read(en2 - s2), "big")
                elif e2 == ID_REFBLOCK:
                    ref = True
            if blk is None:
                yield eid, cp, ce, None
            else:
                yield eid, cp, ce, (blk[0], blk[1], blk[2], blk[3], not ref, dur)
        else:
            yield eid, cp, ce, None


def _mkv_scan_cluster(f, c, tnums):
    """A cluster adott sávjainak blokkjai: [(sáv, idő, BlockDuration | None, keretek)]."""
    cp, ds, end = c
    tc = _mkv_cluster_tc(f, ds, end)
    out = []
    for eid, ep, ee, info in _mkv_cluster_items(f, ds, end):
        if info is not None and info[0] in tnums:
            out.append((info[0], tc + info[1], info[5], info[3]))
    return out


def _mkv_float(raw):
    if len(raw) == 4:
        return struct.unpack(">f", raw)[0]
    if len(raw) == 8:
        return struct.unpack(">d", raw)[0]
    return 0.0


class MkvTrack:
    def __init__(self):
        self.number = self.type = self.dd = 0
        self.codec = ""
        self.priv = b""
        self.w = self.h = self.ch = 0
        self.fs = 0.0
        self.fdur = 0.0                # egy keret időtartama időskála-egységben (hangsáv)
        self.cmp = {}


def _mkv_parse_track(buf, s, e):
    t = MkvTrack()
    for eid, cs, ce, cp in _mkv_children(buf, s, e):
        raw = bytes(buf[cs:ce])
        if eid in MKV_TRK_KEYS:
            t.cmp[eid] = raw
        if eid == 0xD7:
            t.number = int.from_bytes(raw, "big")
        elif eid == 0x83:
            t.type = int.from_bytes(raw, "big")
        elif eid == 0x86:
            t.codec = raw.decode("latin-1").rstrip("\x00")
        elif eid == 0x63A2:
            t.priv = raw
        elif eid == 0x23E383:
            t.dd = int.from_bytes(raw, "big")
        elif eid == 0xE0:
            for e2, s2, en2, p2 in _mkv_children(buf, cs, ce):
                v = int.from_bytes(buf[s2:en2], "big")
                if e2 == 0xB0:
                    t.w = v
                elif e2 == 0xBA:
                    t.h = v
        elif eid == 0xE1:
            for e2, s2, en2, p2 in _mkv_children(buf, cs, ce):
                if e2 == 0xB5:
                    t.fs = _mkv_float(bytes(buf[s2:en2]))
                elif e2 == 0x9F:
                    t.ch = int.from_bytes(buf[s2:en2], "big")
        elif eid == 0x6D80:                       # ContentEncodings
            for e2, s2, en2, p2 in _mkv_children(buf, cs, ce):
                if e2 == 0x6240:                  # ContentEncoding
                    for e3, s3, en3, p3 in _mkv_children(buf, s2, en2):
                        if e3 == 0x5033 and int.from_bytes(buf[s3:en3], "big") == 1:
                            raise MsgError("m_enc")      # titkosítás
    return t


class MkvInfo:
    kind = "mkv"

    def __init__(self, path):
        self.path = path
        self.name = os.path.basename(path)
        self.pending = True
        self.error = None
        self.size = 0
        self.duration = 0.0
        self.ebml = b""
        self.doctype = ""
        self.seg_hdr = self.seg_ds = self.seg_end = 0
        self.seg_unknown = False
        self.scale = 1000000
        self.title = None
        self.info_duration = None
        self.l1 = []                   # nem-cluster L1 elemek: (azonosító, kezdet, tart_kezdet, vég)
        self.clusters = []             # (kezdet, tart_kezdet, vég)
        self.tracks = []
        self.tracks_span = (0, 0)
        self.attach_span = None
        self.dropped = []
        self.ptrack = None
        self.fd = 0.0                  # a fő sáv képkockája (blokkja) időskála-egységben
        self.t_start = self.t_end = 0.0
        self.a0 = {}                   # sáv-szám -> első időbélyeg (időskála-egység)

    def analyze(self):
        self.size = os.path.getsize(self.path)
        if self.size < 64:
            raise MsgError("err_small")
        with open(self.path, "rb") as f:
            try:
                eid, sz, hl = _mkv_hdr(f.read(12), 0)
            except MsgError:
                raise MsgError("k_notmkv")
            if eid != ID_EBML or sz is None:
                raise MsgError("k_notmkv")
            eend = hl + sz
            if eend > self.size:
                raise MsgError("k_trunc")
            f.seek(0)
            self.ebml = f.read(eend)
            for e2, s2, en2, p2 in _mkv_children(self.ebml, hl, eend):
                if e2 == 0x4282:
                    self.doctype = self.ebml[s2:en2].decode("latin-1").rstrip("\x00")
            h = _mkv_f_hdr(f, eend)
            if h is None or h[0] != ID_SEGMENT:
                raise MsgError("k_noseg")
            self.seg_hdr = eend
            self.seg_ds = eend + h[2]
            self.seg_unknown = h[1] is None
            self.seg_end = self.size if h[1] is None else self.seg_ds + h[1]
            if self.seg_end > self.size:
                raise MsgError("k_trunc")
            p = self.seg_ds
            while p < self.seg_end:
                h = _mkv_f_hdr(f, p)
                if h is None:
                    break
                eid, sz, hl = h
                ds = p + hl
                if sz is None:
                    end = _mkv_cluster_end(f, ds, self.seg_end) if eid == ID_CLUSTER \
                        else self.seg_end
                else:
                    end = ds + sz
                    if end > self.seg_end:
                        raise MsgError("k_trunc")
                if eid == ID_CLUSTER:
                    self.clusters.append((p, ds, end))
                else:
                    self.l1.append((eid, p, ds, end))
                p = end

            def grab(i):
                for x in self.l1:
                    if x[0] == i:
                        return x
                return None
            x = grab(ID_INFO)
            if x:
                f.seek(x[2])
                b = f.read(x[3] - x[2])
                for e2, s2, en2, p2 in _mkv_children(b, 0, len(b)):
                    if e2 == 0x2AD7B1:
                        self.scale = int.from_bytes(b[s2:en2], "big") or 1000000
                    elif e2 == 0x4489:
                        self.info_duration = _mkv_float(bytes(b[s2:en2]))
                    elif e2 == 0x7BA9:
                        self.title = bytes(b[s2:en2])
            x = grab(ID_TRACKS)
            if not x:
                raise MsgError("k_notracks")
            self.tracks_span = (x[1], x[3])
            f.seek(x[2])
            b = f.read(x[3] - x[2])
            for e2, s2, en2, p2 in _mkv_children(b, 0, len(b)):
                if e2 == 0xAE:
                    self.tracks.append(_mkv_parse_track(b, s2, en2))
            if not self.tracks:
                raise MsgError("k_notracks")
            if not self.clusters:
                raise MsgError("k_nocluster")
            x = grab(ID_ATTACHMENTS)
            if x:
                self.attach_span = (x[1], x[3])
            self.dropped = [n for i, n in ((ID_CHAPTERS, "Chapters"), (ID_TAGS, "Tags"))
                            if grab(i)]
            vids = [t for t in self.tracks if t.type == 1]
            pt = self.ptrack = vids[0] if vids else self.tracks[0]
            scale = float(self.scale)
            # --- az elejéről: kezdőidő és a blokkok közötti átlagos köz
            tnums = {pt.number} | {t.number for t in self.tracks if t.type == 2}
            scan1 = []
            for c in self.clusters:
                scan1 += _mkv_scan_cluster(f, c, tnums)
                if sum(1 for x in scan1 if x[0] == pt.number) >= 12:
                    break
            first = [x[1:] for x in scan1 if x[0] == pt.number]
            if not first:
                raise MsgError("err_nots")
            for t in self.tracks:                 # hangsávok keretideje (a varrati átfedés kezeléséhez)
                if t.type != 2:
                    continue
                if t.dd:
                    t.fdur = t.dd / scale
                else:
                    lst = sorted((x[1], x[3]) for x in scan1 if x[0] == t.number)
                    if len(lst) >= 2 and lst[-1][0] > lst[0][0]:
                        t.fdur = (lst[-1][0] - lst[0][0]) / float(len(lst) - 1) / lst[0][1]
            pts = sorted(x[0] for x in first)
            self.t_start = float(pts[0])
            for t in self.tracks:
                if t.type == 2:
                    v = [x[1] for x in scan1 if x[0] == t.number]
                    if v:
                        self.a0[t.number] = float(min(v))
            if pt.dd:
                self.fd = pt.dd / scale
            elif len(pts) >= 2 and pts[-1] > pts[0]:
                self.fd = (pts[-1] - pts[0]) / float(len(pts) - 1)
            else:
                d = [x[1] for x in first if x[1]]
                self.fd = float(d[0]) if d else 0.0
            # --- a végéről: a legkésőbbi kép/blokk vége
            last, scanned = [], 0
            for c in reversed(self.clusters):
                last += [x[1:] for x in _mkv_scan_cluster(f, c, {pt.number})]
                scanned += 1
                if scanned >= 3 and len(last) >= 24:
                    break
            if not last:
                raise MsgError("err_nots_end")
            self.t_end = max(x[0] + (self.fd * x[2] if pt.dd else (x[1] or self.fd))
                             for x in last)
        self.duration = max(0.0, (self.t_end - self.t_start) * scale / 1e9)

    def _first(self, typ):
        for t in self.tracks:
            if t.type == typ:
                return t
        return None

    def vdesc(self):
        t = self._first(1)
        if not t:
            return "?"
        fps = round(1e9 / (self.fd * self.scale), 2) if (t is self.ptrack and self.fd) else 0
        return "%s %dx%d%s" % (MKV_VNAMES.get(t.codec, t.codec), t.w, t.h,
                               (" %g fps" % fps) if fps else "")

    def adesc(self):
        t = self._first(2)
        if not t:
            return tr("no_audio")
        return "%s %dch %d Hz" % (MKV_ANAMES.get(t.codec, t.codec), t.ch, int(t.fs))


def mkv_compare(ref, inf):
    bad, warn = [], []
    if ref.doctype != inf.doctype:
        bad.append(tr("c_mkv_doctype"))
    if ref.scale != inf.scale:
        bad.append(tr("c_mkv_scale"))
    if len(ref.tracks) != len(inf.tracks):
        return "bad", "; ".join(bad + [tr("c_mp4_tracks")])
    for i, (a, b) in enumerate(zip(ref.tracks, inf.tracks)):
        if (a.number, a.type) != (b.number, b.type):
            bad.append(tr("c_mkv_track", i + 1))
            continue
        if a.codec != b.codec:
            bad.append(tr("c_mp4_codec", i + 1, a.codec, b.codec))
            continue
        if a.priv != b.priv or a.cmp.get(0x56AA) != b.cmp.get(0x56AA) \
                or a.cmp.get(0x56BB) != b.cmp.get(0x56BB) \
                or a.cmp.get(0x6D80) != b.cmp.get(0x6D80):
            bad.append(tr("c_mkv_priv", i + 1))
        if a.type == 1:
            if (a.w, a.h) != (b.w, b.h):
                bad.append(tr("c_res"))
            if a is ref.ptrack and b is inf.ptrack and ref.fd and inf.fd:
                if abs(ref.fd - inf.fd) > 0.01 * ref.fd:
                    bad.append(tr("c_fps"))
        elif a.type == 2:
            if (a.ch, a.fs) != (b.ch, b.fs):
                bad.append(tr("c_afmt"))
        if a.cmp.get(0xE0) != b.cmp.get(0xE0) or a.cmp.get(0xE1) != b.cmp.get(0xE1):
            if not any(x in bad for x in (tr("c_res"), tr("c_afmt"))):
                warn.append(tr("c_mkv_cfg", i + 1))
    if inf is not ref and (inf.attach_span or "Chapters" in inf.dropped):
        warn.append(tr("c_mkv_drop"))
    if bad:
        return "bad", "; ".join(bad)
    if warn:
        return "warn", "; ".join(warn)
    return "ok", tr("c_ok")


# --- EBML elemek építése ---

def _eb_id(i):
    return i.to_bytes((i.bit_length() + 7) // 8, "big")


def _eb_size(n):
    l = 1
    while n >= (1 << (7 * l)) - 1:
        l += 1
    return ((1 << (7 * l)) | n).to_bytes(l, "big")


def _eb(i, payload):
    return _eb_id(i) + _eb_size(len(payload)) + payload


def _eb_uint(i, v, n=None):
    if n is None:
        n = max(1, (v.bit_length() + 7) // 8)
    return _eb(i, v.to_bytes(n, "big"))


def _mkv_seekhead(entries):
    body = b""
    for eid, pos in entries:
        body += _eb(0x4DBB, _eb(0x53AB, _eb_id(eid)) + _eb_uint(0x53AC, pos, 8))
    return _eb(ID_SEEKHEAD, body)


def mkv_join(infos, out_path, progress=None, log=None, cancel=None, verify=True):
    log = log or (lambda s: None)
    progress = progress or (lambda f: None)
    ref = infos[0]
    nf = len(infos)
    scale = ref.scale
    pt = ref.ptrack
    log(tr("l_mkv_head", nf, len(ref.tracks), scale))

    # --- időeltolások: minden fájl a fő sáv (videó) végéhez illeszkedik
    offsets = [0]
    out_end = ref.t_end
    for inf in infos[1:]:
        off = int(round(out_end - inf.t_start))
        offsets.append(off)
        out_end = off + inf.t_end

    with open(ref.path, "rb") as fr:
        fr.seek(ref.tracks_span[0])
        tracks_raw = fr.read(ref.tracks_span[1] - ref.tracks_span[0])
        att_raw = b""
        if ref.attach_span:
            fr.seek(ref.attach_span[0])
            att_raw = fr.read(ref.attach_span[1] - ref.attach_span[0])
    app = ("Lossless Video Toolkit %s" % __version__).encode("utf-8")
    info_el = _eb(ID_INFO, b"".join((
        _eb(0x73A4, os.urandom(16)),
        _eb_uint(0x2AD7B1, scale),
        _eb(0x4489, struct.pack(">d", float(out_end))),
        _eb(0x4D80, app), _eb(0x5741, app),
        _eb(0x7BA9, ref.title) if ref.title else b"")))

    def build_seek(cues_pos):
        ent = [(ID_INFO, pos_info), (ID_TRACKS, pos_tracks)]
        if att_raw:
            ent.append((ID_ATTACHMENTS, pos_att))
        ent.append((ID_CUES, cues_pos))
        return _mkv_seekhead(ent)

    pos_info = pos_tracks = pos_att = 0
    sh_len = len(build_seek(0))
    pos_info = sh_len
    pos_tracks = pos_info + len(info_el)
    pos_att = pos_tracks + len(tracks_raw)

    dropped = set()
    for inf in infos:
        dropped.update(inf.dropped)
        if inf is not ref and inf.attach_span:
            dropped.add("Attachments")
    if dropped:
        log(tr("l_mkv_drop", ", ".join(sorted(dropped))))

    total = sum(c[2] - c[1] for inf in infos for c in inf.clusters)
    try:
        import shutil
        free = shutil.disk_usage(os.path.dirname(os.path.abspath(out_path)) or ".").free
        if free < total + len(tracks_raw) + len(att_raw) + 50 * 1024 * 1024:
            raise MsgError("j_space")
    except OSError:
        pass

    share = 0.5 if verify else 1.0
    done = [0]
    stats = [dict() for _ in range(nf)]
    cstart = []
    cues = []
    ncl = 0
    seg_id = _eb_id(ID_SEGMENT)
    audio_tr = {t.number: t for t in ref.tracks if t.type == 2 and t is not pt}
    a_end = {}                                  # hangsáv -> az utolsó átvett blokk vége (kimeneti idő)
    tmp = out_path + ".part"
    try:
        with open(tmp, "wb") as fo:
            fo.write(ref.ebml)
            seg_hdr_pos = fo.tell()
            fo.write(seg_id + MKV_UNKNOWN)
            S0 = fo.tell()
            fo.write(build_seek(0))
            fo.write(info_el)
            fo.write(tracks_raw)
            fo.write(att_raw)
            for k, inf in enumerate(infos):
                off = offsets[k]
                log(tr("l_mkv_file", k + 1, inf.name, off * scale / 1e9))
                st = stats[k]
                seam = {tn: k > 0 for tn in audio_tr}
                dropped_a = {tn: 0 for tn in audio_tr}
                with open(inf.path, "rb") as fi:
                    for ci, (cp, cds, cend) in enumerate(inf.clusters):
                        if cancel is not None and cancel.is_set():
                            raise _Cancelled()
                        tc = _mkv_cluster_tc(fi, cds, cend)
                        ntc = tc + off
                        if ntc < 0:
                            raise MsgError("k_neg")
                        cpos = fo.tell()
                        if ci == 0:
                            cstart.append(cpos)
                        fo.write(_eb_id(ID_CLUSTER) + MKV_UNKNOWN)
                        dstart = fo.tell()
                        fo.write(_eb_uint(ID_TIMECODE, ntc, 4 if ntc < (1 << 32) else 8))
                        first_cue = True
                        for eid, ep, ee, info in _mkv_cluster_items(fi, cds, cend):
                            if eid in (ID_TIMECODE, ID_POSITION, ID_PREVSIZE, ID_CRC32, ID_VOID):
                                continue
                            fi.seek(ep)
                            raw = fi.read(ee - ep)
                            if len(raw) != ee - ep:
                                raise MsgError("k_trunc")
                            if info is not None:
                                track, rel, flags, nfr, key, dur = info
                                ts = tc + rel
                                if track in audio_tr:
                                    fdur = audio_tr[track].fdur * nfr
                                    if seam[track]:
                                        # a varratnál az átfedő hangblokkok eldobása (mint a TS ágon):
                                        # a hang nem csúszik el, mert a többi blokk ugyanazt az eltolást kapja
                                        g = (ts + off) - a_end.get(track, ts + off)
                                        if fdur and g < -(fdur / 2.0 + 2.0):
                                            dropped_a[track] += 1
                                            continue
                                        seam[track] = False
                                        log(tr("l_mkv_audio", track, g * scale / 1e6, dropped_a[track]))
                                    a_end[track] = ts + off + fdur
                                s = st.get(track)
                                if s is None:
                                    s = st[track] = [0, 0, 0, ts]
                                s[0] += 1
                                s[1] = zlib.crc32(raw, s[1])
                                s[2] = zlib.crc32(_Q.pack(ts), s[2])
                                if track == pt.number:
                                    if pt.type == 1:
                                        if key:
                                            cues.append((ts + off, cpos - S0))
                                    elif first_cue:
                                        cues.append((ts + off, cpos - S0))
                                    first_cue = False
                            fo.write(raw)
                        end = fo.tell()
                        fo.seek(dstart - 8)
                        fo.write(b"\x01" + (end - dstart).to_bytes(7, "big"))
                        fo.seek(end)
                        ncl += 1
                        done[0] += cend - cds
                        progress(share * done[0] / float(max(1, total)))
            cues.sort()
            body = b"".join(
                _eb(0xBB, _eb_uint(0xB3, max(0, t)) +
                    _eb(0xB7, _eb_uint(0xF7, pt.number) + _eb_uint(0xF1, p)))
                for t, p in cues)
            cues_pos = fo.tell() - S0
            fo.write(_eb(ID_CUES, body))
            end_pos = fo.tell()
            fo.seek(seg_hdr_pos + len(seg_id))
            fo.write(b"\x01" + (end_pos - S0).to_bytes(7, "big"))
            fo.seek(S0)
            fo.write(build_seek(cues_pos))
        log(tr("l_mkv_layout", len(cues)))
        plan = {"nf": nf, "offsets": offsets, "cstart": cstart, "ncl": ncl, "stats": stats,
                "scale": scale, "ptrack": pt.number, "ptype": pt.type, "fd": ref.fd,
                "out_end": out_end, "ebml": ref.ebml, "tracks_raw": tracks_raw,
                "types": {t.number: t.type for t in ref.tracks},
                "tidx": {t.number: i + 1 for i, t in enumerate(ref.tracks)}}
        if verify:
            vres = mkv_verify(tmp, infos, plan, lambda f: progress(share + (1.0 - share) * f),
                              log, cancel)
            if vres is None:
                raise _Cancelled()
            if vres[0]:
                root, ext = os.path.splitext(out_path)
                bad = root + "_HIBAS" + ext
                os.replace(tmp, bad)
                raise MsgError("v_failed", vres[0], bad)
        else:
            log(tr("l_verify_off"))
        os.replace(tmp, out_path)
    except _Cancelled:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    log(tr("l_done", out_path))
    return True


def mkv_verify(path, infos, plan, progress=None, log=None, cancel=None):
    """A kész MKV ellenőrzése a kimenetről visszaolvasva. (hibák, figyelmeztetések) vagy None."""
    log = log or (lambda s: None)
    progress = progress or (lambda f: None)
    nf, scale = plan["nf"], plan["scale"]
    ref = infos[0]
    res = {k: [0, 0] for k in MKV_CHECKS}
    shown = Counter()

    def issue(chk, sev, key, *a):
        res[chk][0 if sev == "E" else 1] += 1
        shown[chk] += 1
        if shown[chk] <= MAX_SHOWN:
            log("   %s %s" % ("✗" if sev == "E" else "!", tr(key, *a)))
        elif shown[chk] == MAX_SHOWN + 1:
            log(tr("v_more", tr("kc_" + chk)))

    def finish():
        return _verify_summary(res, log, MKV_CHECKS, "kc_")

    def ms(t):
        return t * scale / 1e6

    def tpos(t):
        return _fmt_t(t * scale / 1e9)

    log(tr("v_head", nf - 1))
    log(tr("v_what"))
    for key in MKV_CHECKS:
        log("   • %s: %s" % (tr("kc_" + key), tr("kd_" + key)))

    # ---------------- 1. szerkezet, SeekHead, Cues ----------------
    log(tr("k_pass1"))
    out = MkvInfo(path)
    try:
        out.analyze()
    except MsgError as e:
        issue("struct", "E", "mv_boxes", str(e))
        return finish()
    except Exception as e:
        issue("struct", "E", "mv_boxes", str(e) or e.__class__.__name__)
        return finish()
    if out.ebml != plan["ebml"]:
        issue("struct", "E", "kv_ebml")
    if out.seg_unknown or out.seg_end != out.size:
        issue("struct", "E", "kv_segsize")
    for eid, nm in ((ID_INFO, "Info"), (ID_TRACKS, "Tracks")):
        c = sum(1 for x in out.l1 if x[0] == eid)
        if c != 1:
            issue("struct", "E", "kv_cnt1", c, nm)
    if len(out.clusters) != plan["ncl"]:
        issue("struct", "E", "kv_clusters", len(out.clusters), plan["ncl"])
    with open(path, "rb") as f:
        f.seek(out.tracks_span[0])
        if f.read(out.tracks_span[1] - out.tracks_span[0]) != plan["tracks_raw"]:
            issue("struct", "E", "kv_tracks")
        sh = [x for x in out.l1 if x[0] == ID_SEEKHEAD]
        if not sh:
            issue("index", "W", "kv_noseek")
        for eid, p, ds, end in sh:
            f.seek(ds)
            b = f.read(end - ds)
            try:
                for e1, s1, en1, p1 in _mkv_children(b, 0, len(b)):
                    if e1 != 0x4DBB:
                        continue
                    sid = spos = None
                    for e2, s2, en2, p2 in _mkv_children(b, s1, en1):
                        if e2 == 0x53AB:
                            sid = int.from_bytes(b[s2:en2], "big")
                        elif e2 == 0x53AC:
                            spos = int.from_bytes(b[s2:en2], "big")
                    if sid is None or spos is None:
                        issue("index", "E", "kv_seek", 0)
                        continue
                    f.seek(out.seg_ds + spos)
                    if int.from_bytes(f.read(len(_eb_id(sid))), "big") != sid:
                        issue("index", "E", "kv_seek", sid)
            except MsgError:
                issue("index", "E", "kv_seek", 0)
        cu = [x for x in out.l1 if x[0] == ID_CUES]
        ncue = 0
        if len(cu) != 1:
            issue("index", "E", "kv_cnt1", len(cu), "Cues")
        else:
            f.seek(cu[0][2])
            b = f.read(cu[0][3] - cu[0][2])
            try:
                for e1, s1, en1, p1 in _mkv_children(b, 0, len(b)):
                    if e1 != 0xBB:
                        continue
                    ncue += 1
                    for e2, s2, en2, p2 in _mkv_children(b, s1, en1):
                        if e2 != 0xB7:
                            continue
                        for e3, s3, en3, p3 in _mkv_children(b, s2, en2):
                            if e3 == 0xF1:
                                cpos = int.from_bytes(b[s3:en3], "big")
                                f.seek(out.seg_ds + cpos)
                                if int.from_bytes(f.read(4), "big") != ID_CLUSTER:
                                    issue("index", "E", "kv_cue", cpos)
            except MsgError:
                issue("index", "E", "kv_cue", 0)
            if ncue == 0:
                issue("index", "W", "kv_nocues")
    fd = plan["fd"]
    tol = 2.0
    if abs(out.t_end - plan["out_end"]) > max(tol, 1.5 * fd):
        issue("timing", "E", "v_dur", tpos(plan["out_end"]), tpos(out.t_end))
    if out.info_duration is not None and abs(out.info_duration - plan["out_end"]) > max(tol, 1.5 * fd):
        issue("timing", "E", "v_dur", tpos(plan["out_end"]), tpos(out.info_duration))

    # ---------------- 2. minden blokk beolvasása ----------------
    log(tr("k_pass2"))
    cst = plan["cstart"]
    types = plan["types"]
    pt = plan["ptrack"]
    O = [dict() for _ in range(nf)]
    pmin = [None] * nf
    pmax = [None] * nf
    pkey = [None] * nf
    last_ctc = None
    size = float(max(1, out.size))
    with open(path, "rb") as f:
        for cp, cds, cend in out.clusters:
            if cancel is not None and cancel.is_set():
                return None
            k = max(0, bisect.bisect_right(cst, cp) - 1)
            off = plan["offsets"][k]
            try:
                tc = _mkv_cluster_tc(f, cds, cend)
                if last_ctc is not None and tc < last_ctc:
                    issue("struct", "E", "kv_ctc", tpos(tc))
                last_ctc = tc
                for eid, ep, ee, info in _mkv_cluster_items(f, cds, cend):
                    if info is None:
                        continue
                    track, rel, flags, nfr, key, dur = info
                    ts = tc + rel
                    if ts < 0:
                        issue("timing", "E", "kv_neg", tpos(ts))
                    if track not in types:
                        issue("data", "E", "kv_track", track)
                        continue
                    f.seek(ep)
                    raw = f.read(ee - ep)
                    s = O[k].get(track)
                    if s is None:
                        s = O[k][track] = [0, 0, 0, ts, ts, nfr]
                    s[0] += 1
                    s[1] = zlib.crc32(raw, s[1])
                    s[2] = zlib.crc32(_Q.pack(ts - off), s[2])
                    s[4] = ts
                    s[5] = nfr
                    if track == pt:
                        if pmin[k] is None or ts < pmin[k]:
                            pmin[k] = ts
                        if pmax[k] is None or ts > pmax[k]:
                            pmax[k] = ts
                        if pkey[k] is None:
                            pkey[k] = key
            except MsgError as e:
                issue("struct", "E", "mv_boxes", str(e))
                break
            progress(min(1.0, cend / size))

    # ---------------- 3. összevetés a forrásokkal, varratok ----------------
    log(tr("k_pass3"))
    tidx = plan["tidx"]
    for k in range(nf):
        want = plan["stats"][k]
        for tn in types:
            w, o = want.get(tn), O[k].get(tn)
            wc, oc = (w[0] if w else 0), (o[0] if o else 0)
            if wc != oc:
                issue("data", "E", "kv_count", k + 1, tidx[tn], oc, wc)
                continue
            if not w:
                continue
            if o[1] != w[1]:
                issue("data", "E", "kv_crc", k + 1, tidx[tn])
            if o[2] != w[2]:
                issue("timing", "E", "kv_time", k + 1, tidx[tn])
    for k in range(1, nf):
        if pmax[k - 1] is None or pmin[k] is None:
            continue
        e = (pmin[k] - pmax[k - 1]) - fd
        if abs(e) > tol:
            issue("timing", "E", "v_v_seam", k, tpos(pmin[k]), (e / fd) if fd else 0.0, ms(e))
    if plan["ptype"] == 1:
        for k in range(1, nf):
            if pkey[k] is False:
                issue("vseam", "W", "kv_key", k)
    for t in ref.tracks:
        if t.type != 2 or t.number == pt:
            continue
        tn = t.number
        dd = (t.dd / float(scale)) if t.dd else 0.0
        for k in range(nf):
            o = O[k].get(tn)
            if o is None or o[0] == 0:
                issue("audio", "E", "v_s_noaudio", k + 1)
        for k in range(1, nf):
            a, b = O[k - 1].get(tn), O[k].get(tn)
            if not a or not b:
                continue
            if dd:
                bd = dd * a[5]
                adur = dd * max(1, a[5])
            else:
                bd = adur = (a[4] - a[3]) / float(a[0] - 1) if a[0] > 1 else 0.0
            g = b[3] - (a[4] + bd)
            atol = 2.0
            if abs(g) <= adur / 2.0 + atol:
                continue
            if abs(g) <= adur + atol:
                issue("audio", "W", "v_a_seam_w", k, ms(g))
            elif abs(g) <= 1e9 / scale:
                issue("audio", "W", "v_a_seam_g", k, ms(g))
            else:
                issue("audio", "E", "v_a_seam_e", k, ms(g))
    for k in range(nf):
        for tn, o in O[k].items():
            w = plan["stats"][k].get(tn)
            if o[0] and w:
                dl = o[3] - plan["offsets"][k] - w[3]
                if dl:
                    issue("sync", "E", "kv_sync", k + 1, tidx[tn], ms(dl))
    return finish()


# ------------------------------------------------------------ GUI ----------

def default_out_ext(first_path):
    ext = os.path.splitext(first_path)[1].lower()
    if ext in MKV_EXTS:
        return ".webm" if ext == ".webm" else ".mkv"
    if ext in VOB_EXTS:
        return ".vob"
    if ext in MPG_EXTS:
        return ".mpg" if ext in (".mpg", ".mpeg") else ext
    return ext if ext in (".mov",) else (".mp4" if ext in MP4_EXTS else ".m2ts")


def natural_key(s):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", s.lower())]


def fmt_dur(sec):
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return "%d:%02d:%04.1f" % (h, m, s) if h else "%d:%04.1f" % (m, s)


# ============================================================ HANG / STREAM ====
# Folyamok kinyerése (demux) és a hang cseréje (mux) TS / M2TS, MP4 / MOV és MKV fájlokban.
# A kinyert hang nyers keretfolyam (.ac3 / .eac3 / .aac (ADTS) / .mp2 / .mp3), a kép
# nyers elemi folyam (.h264 / .h265 / .m2v). A hangcsere az eredeti fájlt használja
# időzítési alapnak: a kép- és egyéb adat bájtra azonos marad, csak a kiválasztott
# hangsáv adata cserélődik. Csak a Python standard könyvtárát használja (ISO/IEC 13818-1,
# 14496-12/-3, 11172-3, ATSC A/52, RFC 8794/9559 nyilvános specifikációk alapján).

from array import array

AU_TMP = ".oldes"
ADTS_SF = (96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000,
           11025, 8000, 7350)
AU_EXT = {"ac3": ".ac3", "eac3": ".eac3", "aac": ".aac", "mp2": ".mp2", "mp3": ".mp3", "opus": ".opus"}
AU_CHECKS = ("struct", "data", "cc", "pts", "other")
_ACMOD_CH = (2, 1, 2, 3, 3, 4, 4, 5)


def _ch_str(acmod, lfe):
    return "%d.%d" % (_ACMOD_CH[acmod], lfe)



# ----------------------------------------------------------- Ogg / Opus -------

def _ogg_table():
    t = []
    for i in range(256):
        r = i << 24
        for _ in range(8):
            r = ((r << 1) ^ 0x04C11DB7) if r & 0x80000000 else (r << 1)
            r &= 0xFFFFFFFF
        t.append(r)
    return t


_OGG_T = _ogg_table()


def ogg_crc(data):
    c, T = 0, _OGG_T
    for b in data:
        c = ((c << 8) & 0xFFFFFFFF) ^ T[(c >> 24) ^ b]
    return c


def opus_dur(p):
    """Egy Opus csomag hossza 48 kHz-es mintában (RFC 6716, 3.1)."""
    toc = p[0]
    cfg = toc >> 3
    if cfg < 12:
        sz = (480, 960, 1920, 2880)[cfg & 3]
    elif cfg < 16:
        sz = (480, 960)[cfg & 1]
    else:
        sz = (120, 240, 480, 960)[cfg & 3]
    c = toc & 3
    n = 1 if c == 0 else 2 if c < 3 else ((p[1] & 0x3F) if len(p) > 1 else 1)
    return sz * n


def opus_head_from_dops(box):
    """MP4 dOps doboz (fejléccel) -> OpusHead (little-endian)."""
    b = box[8:]
    ch, pre, rate, gain, fam = b[1], struct.unpack_from(">H", b, 2)[0], struct.unpack_from(">I", b, 4)[0], \
        struct.unpack_from(">h", b, 8)[0], b[10]
    return b"OpusHead" + bytes([1, ch]) + struct.pack("<HIhB", pre, rate, gain, fam) + bytes(b[11:])


def opus_head_info(head):
    """OpusHead -> (csatornák, pre_skip, bemeneti mintavétel)."""
    if head[:8] != b"OpusHead" or len(head) < 19:
        raise MsgError("au_cfg")
    return head[9], struct.unpack_from("<H", head, 10)[0], struct.unpack_from("<I", head, 12)[0]


class OggOpusWriter:
    """Ogg Opus fájl (.opus) írása csomagokból."""

    def __init__(self, fo, head, serial=0x4D545331):
        self.fo, self.serial, self.seq, self.size = fo, serial, 0, 0
        self.pre = opus_head_info(head)[1]
        self.gran, self.buf, self.segs, self.pend = self.pre, [], 0, None
        self._page(0x02, 0, [head])
        v = b"mts_joiner"
        self._page(0x00, 0, [b"OpusTags" + struct.pack("<I", len(v)) + v + struct.pack("<I", 0)])

    def _page(self, flags, gran, pkts):
        segs = []
        for p in pkts:
            segs += [255] * (len(p) // 255) + [len(p) % 255]
        if len(segs) > 255:
            raise MsgError("au_pes")
        hdr = bytearray(b"OggS\x00" + bytes([flags]) + struct.pack("<qIII", gran, self.serial, self.seq, 0) +
                        bytes([len(segs)]) + bytes(segs))
        page = bytes(hdr) + b"".join(pkts)
        crc = ogg_crc(page)
        self.fo.write(page[:22] + struct.pack("<I", crc) + page[26:])
        self.seq += 1

    def add(self, pkt, dur):
        need = len(pkt) // 255 + 1
        if self.segs + need > 255 or self.size > 6000:
            self._flush()
        self.buf.append(pkt)
        self.segs += need
        self.size += len(pkt)
        self.gran += dur

    def _flush(self):
        if self.buf:
            if self.pend:
                self._page(0x00, self.pend[1], self.pend[0])
            self.pend = (self.buf, self.gran)
            self.buf, self.segs, self.size = [], 0, 0

    def close(self):
        self._flush()
        if self.pend:
            self._page(0x04, self.pend[1], self.pend[0])


def ogg_read(data):
    """Ogg fájl -> (OpusHead, [csomagok]). Csak egyetlen logikai folyamot kezel."""
    i, n, cur, pk, serial = 0, len(data), bytearray(), [], None
    while i + 27 <= n:
        if data[i:i + 4] != b"OggS":
            j = data.find(b"OggS", i + 1)
            if j < 0:
                break
            i = j
            continue
        ns = data[i + 26]
        if i + 27 + ns > n:
            break
        ser = struct.unpack_from("<I", data, i + 14)[0]
        body = i + 27 + ns
        take = ser == serial or serial is None
        if serial is None:
            serial = ser
        for sg in data[i + 27:i + 27 + ns]:
            if take:
                cur += data[body:body + sg]
            body += sg
            if sg < 255 and take:
                pk.append(bytes(cur))
                cur = bytearray()
        i = body
    if len(pk) < 2 or pk[0][:8] != b"OpusHead" or pk[1][:8] != b"OpusTags":
        raise MsgError("au_unk")
    return pk[0], pk[2:]


def _opus_scan(path):
    out = AudFrames()
    head, pk = ogg_read(open(path, "rb").read())
    if not pk:
        raise MsgError("au_unk")
    ch, pre, rate = opus_head_info(head)
    durs = [opus_dur(p) for p in pk]
    out.codec, out.fs, out.ch, out.spf = "opus", 48000, str(ch), durs[0]
    out.pk, out.head, out.pre = pk, head, pre
    out.sizes = array("I", [len(p) for p in pk])
    out.tot = sum(durs)
    out.var = len(set(durs)) > 1
    return out


# --------------------------------------------------------- keretfejlécek ------

def _hdr_ac3(b, i):
    """AC-3 / E-AC-3 keret az i. bájton: (kodek, méret, minta/keret, fs, csatorna, függő) | None"""
    if i + 8 > len(b) or b[i] != 0x0B or b[i + 1] != 0x77:
        return None
    bsid = b[i + 5] >> 3
    if bsid <= 10:
        fscod, frm = b[i + 4] >> 6, b[i + 4] & 0x3F
        sz = ac3_frame_bytes(b[i + 4])
        if sz is None or fscod > 2:
            return None
        r = parse_ac3(bytes(b[i:i + 12])) if i + 12 <= len(b) else None
        return ("ac3", sz, 1536, (48000, 44100, 32000)[fscod], r["ch"] if r else "?", False)
    if 11 <= bsid <= 16:
        strm = b[i + 2] >> 6
        sz = (((b[i + 2] & 7) << 8) | b[i + 3]) * 2 + 2
        fscod = b[i + 4] >> 6
        if fscod == 3:
            fs, nb = (24000, 22050, 16000)[(b[i + 4] >> 4) & 3], 6
            if (b[i + 4] >> 4) & 3 == 3:
                return None
        else:
            fs, nb = (48000, 44100, 32000)[fscod], (1, 2, 3, 6)[(b[i + 4] >> 4) & 3]
        acmod, lfe = (b[i + 4] >> 1) & 7, b[i + 4] & 1
        return ("eac3", sz, nb * 256, fs, _ch_str(acmod, lfe), strm == 1)
    return None


def _hdr_adts(b, i):
    if i + 7 > len(b) or b[i] != 0xFF or (b[i + 1] & 0xF6) != 0xF0:
        return None
    sf = (b[i + 2] >> 2) & 15
    if sf > 12:
        return None
    ln = ((b[i + 3] & 3) << 11) | (b[i + 4] << 3) | (b[i + 5] >> 5)
    if ln < 7:
        return None
    ch = ((b[i + 2] & 1) << 2) | (b[i + 3] >> 6)
    return ("aac", ln, 1024 * ((b[i + 6] & 3) + 1), ADTS_SF[sf], str(ch), False)


def _hdr_mpa(b, i):
    if i + 4 > len(b) or b[i] != 0xFF or (b[i + 1] & 0xE0) != 0xE0:
        return None
    ver, lay = (b[i + 1] >> 3) & 3, (b[i + 1] >> 1) & 3
    bri, fsi, pad = b[i + 2] >> 4, (b[i + 2] >> 2) & 3, (b[i + 2] >> 1) & 1
    if ver == 1 or lay == 0 or bri in (0, 15) or fsi == 3 or lay == 3:
        return None                      # az 1. réteg (lay == 3) nem támogatott
    layer = 4 - lay
    grp = 1 if ver == 3 else 2
    br = _MPA_BR[(grp, layer)][bri - 1] * 1000
    fs = _MPA_FS[ver][fsi]
    spf = 1152 if (layer == 2 or ver == 3) else 576
    sz = spf // 8 * br // fs + pad
    return ("mp2" if layer == 2 else "mp3", sz, spf, fs,
            "1" if (b[i + 3] >> 6) == 3 else "2", False)


def aud_sniff(b):
    """A nyers hangfolyam kodekje az első érvényes keretből (kezdő ID3-címke átugrása)."""
    i = 0
    if b[:3] == b"ID3" and len(b) >= 10:
        i = 10 + ((b[6] << 21) | (b[7] << 14) | (b[8] << 7) | b[9])
    if b[:4] == b"OggS" and b"OpusHead" in b[:80]:
        return "opus", 0
    n = min(len(b), i + 65536)
    for j in range(i, n - 8):
        for h in (_hdr_ac3, _hdr_adts, _hdr_mpa):
            r = h(b, j)
            if r is None:
                continue
            # megerősítés: a következő keret is érvényes legyen
            k = j + r[1]
            if k + 8 <= len(b) and any(x(b, k) for x in (_hdr_ac3, _hdr_adts, _hdr_mpa)):
                return r[0], j
    return None, 0


class AudFrames:
    """Egy nyers hangfájl keretei: offs/sizes tömbök, kodek és paraméterek."""

    def __init__(self):
        self.codec = None
        self.offs = array("Q")
        self.sizes = array("I")
        self.spf = self.fs = 0
        self.ch = "?"
        self.junk = 0
        self.skip = 0
        self.pk = None                 # Opus: a csomagok a memóriában
        self.tot = None                # Opus: összes minta 48 kHz-en
        self.var = False
        self.head = b""
        self.pre = 0

    @property
    def n(self):
        return len(self.sizes)

    def ms(self, n=None):
        if self.tot is not None and n is None:
            return self.tot * 1000.0 / 48000
        return (self.n if n is None else n) * self.spf * 1000.0 / self.fs if self.fs else 0.0

    def kbps(self):
        tot = sum(self.sizes)
        return tot * 8.0 / (self.ms() or 1.0)


def aud_scan(path, progress=None, cancel=None, codec=None):
    """Nyers hangfájl keretezése (blokkonként, memóriakímélően). AudFrames-t ad."""
    out = AudFrames()
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        head = f.read(262144)
        if codec is None:
            codec, start = aud_sniff(head)
            if codec is None:
                raise MsgError("au_unk")
        else:
            start = 0
        if codec == "opus":
            return _opus_scan(path)
        hdr = {"ac3": _hdr_ac3, "eac3": _hdr_ac3, "aac": _hdr_adts, "mp2": _hdr_mpa,
               "mp3": _hdr_mpa}[codec]
        out.codec, out.skip = codec, start
        f.seek(start)
        base, carry, eof = start, b"", False
        while not eof:
            if cancel is not None and cancel.is_set():
                raise MsgError("cancelled")
            data = f.read(8 * 1024 * 1024)
            eof = len(data) < 8 * 1024 * 1024
            buf = carry + data
            i, n = 0, len(buf)
            while i + 16 <= n or (eof and i + 8 <= n):
                h = hdr(buf, i)
                if h is None or (codec == "ac3" and h[0] != "ac3") or \
                        (codec == "eac3" and h[0] != "eac3") or \
                        (codec in ("mp2", "mp3") and h[0] != codec):
                    j = i + 1
                    while j + 8 <= n and hdr(buf, j) is None:
                        j += 1
                    if j + 8 > n and not eof:
                        out.junk += j - i - 7 if j - i > 7 else 0
                        i = max(i, n - 7)
                        break
                    out.junk += j - i
                    i = j
                    continue
                if i + h[1] > n:
                    if eof:
                        out.junk += n - i
                        i = n
                    break
                if h[5] and out.n:                       # E-AC-3 függő alfolyam: az előző egység része
                    out.sizes[-1] += h[1]
                else:
                    out.offs.append(base + i)
                    out.sizes.append(h[1])
                    if not out.fs:
                        out.spf, out.fs, out.ch = h[2], h[3], h[4]
                i += h[1]
            base += i
            carry = buf[i:]
            if progress:
                progress(min(1.0, base / float(max(1, size))))
    if not out.n:
        raise MsgError("au_unk")
    return out


def aud_read(f, fr, i):
    if fr.pk is not None:
        return fr.pk[i]
    f.seek(fr.offs[i])
    return f.read(fr.sizes[i])


def adts_strip(frame):
    return frame[9:] if not (frame[1] & 1) else frame[7:]


def asc_parse(asc):
    """AudioSpecificConfig -> (objektumtípus, mintavételi index, csatornakonfiguráció)."""
    if len(asc) < 2:
        return None
    v = int.from_bytes(asc[:4].ljust(4, b"\x00"), "big")
    aot = v >> 27
    p = 5
    if aot == 31:
        aot = 32 + ((v >> 21) & 63)
        p = 11
    sf = (v >> (32 - p - 4)) & 15
    p += 4
    if sf == 15:
        return None
    ch = (v >> (32 - p - 4)) & 15
    return aot, sf, ch


def adts_header(asc, n):
    aot, sf, ch = asc_parse(asc)
    ln = n + 7
    return bytes([0xFF, 0xF1, ((aot - 1) & 3) << 6 | (sf << 2) | (ch >> 2),
                  ((ch & 3) << 6) | (ln >> 11), (ln >> 3) & 0xFF, ((ln & 7) << 5) | 0x1F, 0xFC])


def adts_asc(frame):
    """Egy ADTS fejlécből AudioSpecificConfig (2 bájt)."""
    prof, sf = (frame[2] >> 6) & 3, (frame[2] >> 2) & 15
    ch = ((frame[2] & 1) << 2) | (frame[3] >> 6)
    v = ((prof + 1) << 11) | (sf << 7) | (ch << 3)
    return bytes([v >> 8, v & 0xFF])


# ------------------------------------------------------------- listázás -------

_TS_ACODEC = {0x81: "ac3", 0x87: "eac3", 0x03: "mpa", 0x04: "mpa", 0x0F: "aac"}
_TS_VCODEC = {0x1B: ("h264", ".h264"), 0x24: ("hevc", ".h265"), 0x02: ("mpeg2", ".m2v"),
              0x01: ("mpeg1", ".m1v"), 0xEA: ("vc1", ".vc1"), 0x10: ("mpeg4", ".m4v")}


def _st(kind, sid, codec, desc, ext, ok=True):
    return {"type": kind, "id": sid, "codec": codec, "desc": desc, "ext": ext, "ok": ok}


def _mp4_start_ms(t, mvts):
    """A sáv első mintájának megjelenítési ideje ms-ban (üres szerkesztés + kompozíciós eltolás)."""
    lead, mt0 = 0.0, 0.0
    for sd, mt in (t.elst or []):
        if mt < 0:
            lead += sd / float(mvts)
        else:
            mt0 = mt / float(t.mdts)
            break
    cts0 = 0.0
    if t.ctts:
        cts0 = min(o for c, o in t.ctts[:8]) / float(t.mdts)
    return (lead + cts0 - mt0) * 1000.0


def _start_ms(inf):
    """{(típus, azonosító): első idő ms} – csak a viszonyuk számít."""
    res = {}
    if inf.kind == "ts":
        v0 = inf.v_pts0 if inf.v_pts0 is not None else inf.v_first
        if inf.vpid is not None and v0 is not None:
            res[("video", inf.vpid)] = 0.0
            for pid, a in inf.a_first.items():
                res[("audio", pid)] = sdiff(a, v0) / 90.0
    elif inf.kind == "mp4":
        for t in inf.tracks:
            if t.handler in (b"vide", b"soun"):
                res[("video" if t.handler == b"vide" else "audio", t.id)] = _mp4_start_ms(t, inf.mvts)
    elif inf.kind == "mkv":
        k = inf.scale / 1e6
        if inf.ptrack is not None:
            res[("video", inf.ptrack.number)] = inf.t_start * k
        for n, v in inf.a0.items():
            res[("audio", n)] = v * k
    return res


def au_list(inf):
    """Folyamok + a késleltetésük (a legkorábban induló folyamhoz képest, ms; None = ismeretlen)."""
    out = _au_list0(inf)
    try:
        raw = _start_ms(inf)
    except Exception:
        raw = {}
    base = min(raw.values()) if raw else 0.0
    for s in out:
        v = raw.get((s["type"], s["id"]))
        s["delay"] = None if v is None else v - base
    return out


def fmt_delay(x):
    return "–" if x is None else ("0" if abs(x) < 0.5 else "%+.0f" % x)


def delay_text(inf):
    """Kép / hang kezdési késleltetés egy sorban, pl. '0 / +40 ms'."""
    cached = getattr(inf, "_dl", None)
    if cached is not None:
        return cached
    try:
        sts = au_list(inf)
    except Exception:
        return ""
    v = [s["delay"] for s in sts if s["type"] == "video" and s["delay"] is not None]
    a = [s["delay"] for s in sts if s["type"] == "audio" and s["delay"] is not None]
    parts = []
    if v:
        parts.append(fmt_delay(v[0]))
    if a:
        parts.append(fmt_delay(a[0]))
    txt = (" / ".join(parts) + " ms") if parts else ""
    inf._dl = txt
    return txt


def _au_list0(inf):
    """Egy elemzett fájl (TsInfo / Mp4Info / MkvInfo) folyamai."""
    out = []
    if inf.kind == "ts":
        if inf.vpid is not None:
            c, ext = _TS_VCODEC.get(inf.vtype, ("?", ".bin"))
            out.append(_st("video", inf.vpid, c, "%s %s" % (c.upper(), inf.vdesc()), ext, c != "?"))
        for pid in inf.apids:
            t = inf.atypes[pid]
            c = _TS_ACODEC.get(t)
            nm = AUDIO_NAMES.get(t, "0x%02X" % t)
            ext = AU_EXT.get(c, ".mp2") if c != "mpa" else ".mp2"
            out.append(_st("audio", pid, c or "?", "%s (PID 0x%X)" % (nm, pid), ext, c is not None))
    elif inf.kind == "mp4":
        for t in inf.tracks:
            fc, w, h, ch, sr, cfg = t.entry_info()
            if t.handler == b"soun":
                c = _mp4_acodec(fc, cfg)
                out.append(_st("audio", t.id, c or "?", "%s %dch %d Hz (#%d)" % (
                    MP4_ANAMES.get(fc, fc.decode("latin-1").strip()), ch, sr, t.id),
                    AU_EXT.get(c, ".bin"), c is not None))
            elif t.handler == b"vide":
                c = {b"avc1": "h264", b"avc3": "h264", b"hvc1": "hevc", b"hev1": "hevc"}.get(fc)
                out.append(_st("video", t.id, c or "?", "%s %dx%d (#%d)" % (
                    MP4_VNAMES.get(fc, fc.decode("latin-1").strip()), w, h, t.id),
                    ".h264" if c == "h264" else ".h265", c is not None))
    elif inf.kind == "mkv":
        for t in inf.tracks:
            if t.type == 2:
                c = {"A_AC3": "ac3", "A_EAC3": "eac3", "A_MPEG/L3": "mp3", "A_MPEG/L2": "mp2",
                     "A_OPUS": "opus"}.get(t.codec)
                if t.codec.startswith("A_AAC"):
                    c = "aac"
                out.append(_st("audio", t.number, c or "?", "%s %dch %g Hz (#%d)" % (
                    t.codec, t.ch, t.fs, t.number), AU_EXT.get(c, ".bin"), c is not None))
            elif t.type == 1:
                c = {"V_MPEG4/ISO/AVC": "h264", "V_MPEGH/ISO/HEVC": "hevc"}.get(t.codec)
                out.append(_st("video", t.number, c or "?", "%s %dx%d (#%d)" % (
                    t.codec, t.w, t.h, t.number), ".h264" if c == "h264" else ".h265", c is not None))
    return out


def _mp4_acodec(fc, cfg):
    if fc == b"ac-3":
        return "ac3"
    if fc == b"ec-3":
        return "eac3"
    if fc == b".mp3":
        return "mp3"
    if fc == b"Opus" and b"dOps" in cfg:
        return "opus"
    if fc == b"mp4a":
        core = _esds_core(cfg.get(b"esds", b"")) if b"esds" in cfg else None
        if core is None:
            return None
        if core[0] == 0x40 and len(core[1]) >= 2:
            return "aac"
        if core[0] in (0x6B, 0x69):
            return "mp3"
    return None


# ------------------------------------------------------------ TS kinyerés -----

def _ts_iter(inf, cancel=None, progress=None):
    """A TS fájl csomagjai blokkonként: (buf, ps, H) darabok; buf bytearray."""
    ps, H = inf.ps, inf.H
    left = inf.size // ps * ps
    tot = float(max(1, left))
    done = 0
    with open(inf.path, "rb") as f:
        while left > 0:
            if cancel is not None and cancel.is_set():
                raise MsgError("cancelled")
            data = f.read(min(ps * CHUNK_PACKETS, left))
            if not data:
                break
            left -= len(data)
            done += len(data)
            yield bytearray(data)
            if progress:
                progress(done / tot)


def _pes_es_start(buf, pay, endt):
    """PES fejléc után az elemi adat kezdete (PTS nélküli fejlécre is) vagy -1."""
    if endt - pay < 9 or buf[pay] != 0 or buf[pay + 1] != 0 or buf[pay + 2] != 1:
        return -1
    if (buf[pay + 6] & 0xC0) != 0x80:
        return -1
    es = pay + 9 + buf[pay + 8]
    return es if es <= endt else -1


def ts_extract(inf, pid, out_path, progress=None, cancel=None, es_marks=None):
    """Egy TS folyam hasznos adata fájlba. es_marks: [ES-eltolás, PTS, csomagszám, stream_id, flags] / PES."""
    n = 0
    started = False
    with open(out_path, "wb") as fo:
        for buf in _ts_iter(inf, cancel, progress):
            for t, p, pusi, afc, cc, pay, pcr in iter_packets(buf, inf.ps, inf.H):
                if p != pid or pay < 0:
                    continue
                if pusi:
                    es = _pes_es_start(buf, pay, t + 188)
                    if es < 0:
                        raise MsgError("au_pes")
                    started = True
                    if es_marks is not None:
                        tm = pes_times(buf, pay, t + 188)
                        es_marks.append([n, tm[0] if tm else None, 1, buf[pay + 3], buf[pay + 6]])
                    d = buf[es:t + 188]
                elif started:
                    if es_marks is not None:
                        es_marks[-1][2] += 1
                    d = buf[pay:t + 188]
                else:
                    continue
                fo.write(d)
                n += len(d)
    return n


# ------------------------------------------------------------ MP4 kinyerés ----

def _mp4_samples(f, t):
    """Az összes minta bájtjai sorban (generátor)."""
    spc, sdi, cfs, total = t.layout()
    i = 0
    for c, off in enumerate(t.offsets):
        f.seek(off)
        n = spc[c]
        blk = f.read(sum(t.sizes[i:i + n]))
        p = 0
        for k in range(i, i + n):
            yield blk[p:p + t.sizes[k]]
            p += t.sizes[k]
        i += n


def _nal_cfg(box, hevc):
    """avcC / hvcC tartalom (fejléc nélkül) -> (NAL hossz-bájtok, paraméterkészlet NAL-ok)."""
    ps = []
    if not hevc:
        ln = (box[4] & 3) + 1
        p = 5
        for grp in (box[p] & 31, None):
            if grp is None:
                grp = box[p]
            p += 1
            for _ in range(grp):
                n = (box[p] << 8) | box[p + 1]
                ps.append(bytes(box[p + 2:p + 2 + n]))
                p += 2 + n
        return ln, ps
    ln = (box[21] & 3) + 1
    p = 23
    for _ in range(box[22]):
        cnt = (box[p + 1] << 8) | box[p + 2]
        p += 3
        for _ in range(cnt):
            n = (box[p] << 8) | box[p + 1]
            ps.append(bytes(box[p + 2:p + 2 + n]))
            p += 2 + n
    return ln, ps


def _annexb(sample, ln):
    out, p, n = bytearray(), 0, len(sample)
    while p + ln <= n:
        sz = int.from_bytes(sample[p:p + ln], "big")
        p += ln
        out += b"\x00\x00\x00\x01" + sample[p:p + sz]
        p += sz
    return bytes(out)


def _aud_wrap(codec, asc):
    if codec == "aac":
        return lambda s: adts_header(asc, len(s)) + s
    return lambda s: s


def _opus_dump(fo, head, packets, progress=None, cancel=None, total=1):
    w = OggOpusWriter(fo, head)
    for i, p in enumerate(packets):
        if cancel is not None and cancel.is_set():
            raise MsgError("cancelled")
        w.add(p, opus_dur(p))
        if progress and i % 512 == 0:
            progress(i / float(max(1, total)))
    w.close()


def mp4_extract(inf, t, st, out_path, progress=None, cancel=None):
    fc, w, h, ch, sr, cfg = t.entry_info()
    n = max(1, t.n)
    with open(inf.path, "rb") as f, open(out_path, "wb") as fo:
        if st["codec"] == "opus":
            _opus_dump(fo, opus_head_from_dops(cfg[b"dOps"]), _mp4_samples(f, t), progress, cancel, n)
            return
        if st["type"] == "audio":
            asc = b""
            if st["codec"] == "aac":
                asc = _esds_core(cfg[b"esds"])[1]
                if asc_parse(asc) is None:
                    raise MsgError("au_cfg")
            wrap = _aud_wrap(st["codec"], asc)
        else:
            hevc = st["codec"] == "hevc"
            box = cfg.get(b"hvcC" if hevc else b"avcC")
            if not box:
                raise MsgError("au_cfg")
            ln, ps = _nal_cfg(box[8:], hevc)
            for x in ps:
                fo.write(b"\x00\x00\x00\x01" + x)
            wrap = lambda s: _annexb(s, ln)
        for i, s in enumerate(_mp4_samples(f, t)):
            if cancel is not None and cancel.is_set():
                raise MsgError("cancelled")
            fo.write(wrap(s))
            if progress and i % 512 == 0:
                progress(i / float(n))


# ------------------------------------------------------------ MKV kinyerés ----

def _mkv_payload(raw):
    """Egy SimpleBlock / BlockGroup elem nyers bájtjaiból (fejléccel) a blokk adatrésze."""
    eid, size, hl = _mkv_hdr(raw, 0)
    body = raw[hl:]
    if eid == ID_BLOCKGROUP:
        for e2, s2, en2, p2 in _mkv_children(body, 0, len(body)):
            if e2 == ID_BLOCK:
                body = body[s2:en2]
                break
        else:
            return None
    n, mask = 1, 0x80
    while n <= 8 and not body[0] & mask:
        mask >>= 1
        n += 1
    flags = body[n + 2]
    if flags & 0x06:
        raise MsgError("au_lace")
    return body[n + 3:]


def mkv_blocks(inf, f, tnum):
    """A sáv blokkjai sorban: (idő, nyers elem, payload)."""
    for cp, ds, cend in inf.clusters:
        tc = _mkv_cluster_tc(f, ds, cend)
        for eid, ep, ee, info in _mkv_cluster_items(f, ds, cend):
            if info is None or info[0] != tnum:
                continue
            f.seek(ep)
            raw = f.read(ee - ep)
            yield tc + info[1], raw, _mkv_payload(raw)


def mkv_extract(inf, tr_, st, out_path, progress=None, cancel=None):
    with open(inf.path, "rb") as f, open(out_path, "wb") as fo:
        if st["codec"] == "opus":
            head = tr_.priv if tr_.priv[:8] == b"OpusHead" else \
                b"OpusHead" + bytes([1, tr_.ch or 2]) + struct.pack("<HIhB", 312, 48000, 0, 0)
            _opus_dump(fo, head, (pl for ts, raw, pl in mkv_blocks(inf, f, tr_.number)), progress,
                       cancel, len(inf.clusters) * 50)
            return
        if st["type"] == "audio":
            wrap = _aud_wrap(st["codec"], tr_.priv)
            if st["codec"] == "aac" and asc_parse(tr_.priv) is None:
                raise MsgError("au_cfg")
        else:
            hevc = st["codec"] == "hevc"
            ln, ps = _nal_cfg(tr_.priv, hevc)
            for x in ps:
                fo.write(b"\x00\x00\x00\x01" + x)
            wrap = lambda s: _annexb(s, ln)
        tot = float(max(1, len(inf.clusters)))
        for k, (cp, ds, cend) in enumerate(inf.clusters):
            if cancel is not None and cancel.is_set():
                raise MsgError("cancelled")
            tc = _mkv_cluster_tc(f, ds, cend)
            for eid, ep, ee, info in _mkv_cluster_items(f, ds, cend):
                if info is None or info[0] != tr_.number:
                    continue
                f.seek(ep)
                fo.write(wrap(_mkv_payload(f.read(ee - ep))))
            if progress:
                progress((k + 1) / tot)


def au_extract(inf, st, out_path, progress=None, log=None, cancel=None):
    """Egy folyam kinyerése. st: au_list elem."""
    log = log or (lambda s: None)
    if not st["ok"]:
        raise MsgError("au_unsup", st["desc"])
    log(tr("au_l_ext", st["desc"], out_path))
    if inf.kind == "ts":
        n = ts_extract(inf, st["id"], out_path, progress, cancel)
    elif inf.kind == "mp4":
        t = [x for x in inf.tracks if x.id == st["id"]][0]
        mp4_extract(inf, t, st, out_path, progress, cancel)
        n = os.path.getsize(out_path)
    else:
        t = [x for x in inf.tracks if x.number == st["id"]][0]
        mkv_extract(inf, t, st, out_path, progress, cancel)
        n = os.path.getsize(out_path)
    if st["type"] == "audio":
        fr = aud_scan(out_path, codec=st["codec"] if st["codec"] not in ("mpa", "opus") else None)
        log(tr("au_l_info", fr.codec.upper(), fr.n, fr.ms() / 1000.0, fr.fs, fr.ch, fr.kbps(), fr.junk))
    log(tr("au_l_done", n))
    return n


# ------------------------------------------------------------ közös segédek ---

SYNC_MARK = "\u26a0"
# Saját mérés: 3,000 s-nál induló impulzus, a kinyert hang ffmpeg-gel újrakódolva MKV-ba visszatéve.
# Kulcs: (régi kodek, új kodek) -> ennyi ms-mal KÉSIK a hang a képhez képest késleltetés nélkül.
_SHIFT = {
    "ac3": {"ac3": 5.3, "eac3": 10.3, "aac": 26.3, "mp3": 28.0, "mp2": 15.0, "opus": -2.0},
    "eac3": {"ac3": 10.3, "eac3": 5.3, "aac": 26.3, "mp3": 28.0, "mp2": 15.0, "opus": -2.0},
    "aac": {"ac3": 26.3, "eac3": 26.3, "aac": 21.3, "mp3": 44.0, "mp2": 31.0, "opus": 14.0},
    "mp3": {"ac3": 28.3, "eac3": 28.3, "aac": 44.3, "mp3": 23.0, "mp2": 33.0, "opus": 16.0},
    "mp2": {"ac3": 15.3, "eac3": 15.3, "aac": 31.3, "mp3": 33.0, "mp2": 10.0, "opus": 3.0},
    "opus": {"ac3": 12.3, "eac3": 12.3, "aac": 28.3, "mp3": 30.0, "mp2": 17.0, "opus": 0.0},
}
_ENC_NAME = {"ac3": "AC-3", "eac3": "E-AC-3", "mp2": "MP2", "aac": "AAC", "mp3": "MP3", "opus": "Opus"}


def sync_report(old_ms, old_fr, new, delay_ms, log, switch=False, old_pre=None, gaps=0, nodata=False,
                old_codec=None, same_audio=False):
    """Szinkron-kockázatok jelzése. Minden figyelmeztetés: mi a gond + mit tegyen a felhasználó.
    Visszatér: a figyelmeztetések száma. (A program hangot nem dekódol, ezért a hullámforma
    egyezését nem tudja mérni; a hossz-, keret- és kódolási jellemzőket ellenőrzi.)"""
    if same_audio:                      # ugyanaz a hang, csak az időzítés változik: nincs kódolói előfutás
        log(tr("sy_shift", delay_ms))
        if abs(delay_ms) > 1000:
            log("%s %s" % (SYNC_MARK, tr("sy_shift_big", delay_ms)))
            return 1
        return 0
    n = 0
    new_ms = new.ms()
    new_fr = new.spf * 1000.0 / new.fs
    diff = new_ms - old_ms
    tol = max(old_fr, new_fr)
    est = _SHIFT.get(old_codec or new.codec, {}).get(new.codec)
    if est is None:
        est = _SHIFT.get(new.codec, {}).get(new.codec)
    est_warn = est is not None and abs(est) >= 8
    if abs(diff) >= 0.5:
        n += 1
        if abs(diff) > 1000:
            log("%s%s %s" % (SYNC_MARK, SYNC_MARK, tr("sy_dur_big", diff, old_ms / 1000.0, new_ms / 1000.0)))
        elif abs(diff) > tol:
            log("%s %s" % (SYNC_MARK, tr("sy_dur_mid", diff, tol)))
        elif est_warn:
            log("%s %s" % (SYNC_MARK, tr("sy_dur_small2", diff)))
        else:
            log("%s %s" % (SYNC_MARK, tr("sy_dur_small", diff, -diff)))
    if est is not None:
        if est_warn:
            n += 1
            log("%s %s" % (SYNC_MARK, tr("sy_enc", _ENC_NAME.get(old_codec, "?"), _ENC_NAME[new.codec],
                                          est, -est)))
        else:
            log(tr("sy_enc_small", _ENC_NAME.get(old_codec, "?"), _ENC_NAME[new.codec], est))
    if old_pre is not None and new.codec == "opus" and new.pre != old_pre:
        n += 1
        log("%s %s" % (SYNC_MARK, tr("sy_pre", (new.pre - old_pre) / 48.0, old_pre, new.pre)))
    if nodata:
        n += 1
        log("%s %s" % (SYNC_MARK, tr("sy_noold")))
    if gaps:
        log(tr("sy_gaps", gaps))
    if delay_ms:
        log(tr("sy_delay", delay_ms))
    if n:
        log("%s %s" % (SYNC_MARK, tr("sy_sum", n)))
    else:
        log(tr("sy_ok"))
    return n



class _Issues:
    def __init__(self, log):
        self.log = log
        self.res = {k: [0, 0] for k in AU_CHECKS}
        self.shown = Counter()

    def __call__(self, chk, sev, key, *a):
        self.res[chk][0 if sev == "E" else 1] += 1
        self.shown[chk] += 1
        if self.shown[chk] <= MAX_SHOWN:
            self.log("   %s %s" % ("✗" if sev == "E" else "!", tr(key, *a)))
        elif self.shown[chk] == MAX_SHOWN + 1:
            self.log(tr("v_more", tr("ac_" + chk)))

    def head(self):
        self.log(tr("v_what"))
        for k in AU_CHECKS:
            self.log("   • %s: %s" % (tr("ac_" + k), tr("ad_" + k)))

    def finish(self):
        return _verify_summary(self.res, self.log, AU_CHECKS, "ac_")


def _chan_n(s):
    try:
        a = s.split(".")
        return int(a[0]) + (int(a[1]) if len(a) > 1 else 0)
    except ValueError:
        return -1


def _au_compat(old, new, log):
    """Az új hang formátuma egyezzen a régivel (kodek, mintavétel, csatornák)."""
    if old.codec != new.codec or old.fs != new.fs or \
            (old.codec != "mp2" and old.codec != "mp3" and _chan_n(old.ch) != _chan_n(new.ch)):
        raise MsgError("au_mismatch", "%s %d Hz %s" % (old.codec.upper(), old.fs, old.ch),
                       "%s %d Hz %s" % (new.codec.upper(), new.fs, new.ch))
    if old.n != new.n:
        log(tr("au_l_count", old.n, new.n, (new.n - old.n) * new.spf * 1000.0 / new.fs))
    if abs(old.kbps() - new.kbps()) > old.kbps() * 0.02:
        log(tr("au_l_rate", old.kbps(), new.kbps()))


def _opus_check(new, pre_old, dur_old, log):
    """Az új Opus-fájl illeszkedése: egyenletes csomaghossz, azonos hossz és pre-skip."""
    if new.var:
        raise MsgError("au_opus_var")
    if new.spf != dur_old:
        raise MsgError("au_opus_dur", dur_old / 48.0, new.spf / 48.0)
    if new.pre != pre_old:
        log(tr("au_l_pre", pre_old, new.pre))


def _free_check(path, need):
    try:
        import shutil
        free = shutil.disk_usage(os.path.dirname(os.path.abspath(path)) or ".").free
        if free < need + 50 * 1024 * 1024:
            raise MsgError("j_space")
    except OSError:
        pass


def _crc_frames(path, fr, upto=None):
    crc, n = 0, 0
    with open(path, "rb") as f:
        for i in range(fr.n if upto is None else min(upto, fr.n)):
            d = aud_read(f, fr, i)
            crc = zlib.crc32(d, crc)
            n += len(d)
    return crc, n


def _finish_out(tmp, out_path, bad_ext_root, vres):
    if vres is None:
        os.remove(tmp)
        return False
    if vres[0]:
        root, ext = os.path.splitext(out_path)
        bad = root + "_HIBAS" + ext
        os.replace(tmp, bad)
        raise MsgError("v_failed", vres[0], bad)
    os.replace(tmp, out_path)
    return True


# --------------------------------------------------------------- TS csere -----

def _ts_pts_bytes(v):
    return bytes([0x21 | (((v >> 30) & 7) << 1), (v >> 22) & 0xFF,
                  (((v >> 15) & 0x7F) << 1) | 1, (v >> 7) & 0xFF, ((v & 0x7F) << 1) | 1])


def _ts_pkt(pid, pusi, chunk):
    n = len(chunk)
    h = bytes([0x47, (0x40 if pusi else 0) | (pid >> 8), pid & 0xFF])
    if n == 184:
        return bytearray(h + b"\x10" + chunk)
    af = 183 - n
    return bytearray(h + b"\x30" + (b"\x00" if af == 0 else bytes([af, 0]) + b"\xff" * (af - 1)) + chunk)


def _ts_pes_packets(pid, sid, b6, pts, payload):
    if pts is None:
        hdr = b"\x00\x00\x01" + bytes([sid, 0, 0, b6, 0, 0])
    else:
        hdr = b"\x00\x00\x01" + bytes([sid, 0, 0, b6, 0x80, 5]) + _ts_pts_bytes(pts)
    pes = bytearray(hdr) + payload
    ln = len(pes) - 6
    if ln <= 0xFFFF:
        pes[4], pes[5] = ln >> 8, ln & 0xFF
    return [_ts_pkt(pid, k == 0, bytes(pes[k * 184:(k + 1) * 184])) for k in range((len(pes) + 183) // 184)]


_NULL_PKT = bytes([0x47, 0x1F, 0xFF, 0x10]) + b"\xff" * 184


def _ts_has_pay(buf, t):
    afc = (buf[t + 3] >> 4) & 3
    if afc & 2:
        return bool(afc & 1) and t + 5 + buf[t + 4] <= t + 188
    return bool(afc & 1)


def ts_replace_audio(inf, pid, new_path, out_path, delay_ms=0.0, progress=None, log=None,
                     cancel=None, verify=True, same_audio=False):
    log = log or (lambda s: None)
    progress = progress or (lambda f: None)
    if pid == inf.pcr_pid:
        raise MsgError("au_pcr")
    if os.path.normcase(os.path.abspath(out_path)) in (
            os.path.normcase(os.path.abspath(inf.path)), os.path.normcase(os.path.abspath(new_path))):
        raise MsgError("j_sameout")
    codec_old = _TS_ACODEC.get(inf.atypes.get(pid))
    if codec_old != "ac3":
        raise MsgError("au_ts_only")
    new = aud_scan(new_path, cancel=cancel)
    tmp_old = out_path + AU_TMP
    marks = []
    try:
        ts_extract(inf, pid, tmp_old, lambda f: progress(0.1 * f), cancel, marks)
        old = aud_scan(tmp_old, codec=None if codec_old == "mpa" else codec_old, cancel=cancel)
    finally:
        try:
            os.remove(tmp_old)
        except OSError:
            pass
    if not marks:
        raise MsgError("au_pes")
    log(tr("au_l_old", old.codec.upper(), old.n, old.ms() / 1000.0, len(marks)))
    log(tr("au_l_new", new.codec.upper(), new.n, new.ms() / 1000.0))
    _au_compat(old, new, log)
    sync_report(old.ms(), old.spf * 1000.0 / old.fs, new, delay_ms, log, old_codec=old.codec,
                same_audio=same_audio)
    starts = old.offs
    idx = [bisect.bisect_left(starts, m[0]) for m in marks] + [old.n]
    cnts = [idx[i + 1] - idx[i] for i in range(len(marks))]
    cnts[-1] = max(cnts[-1], new.n - sum(cnts[:-1]))
    dly = int(round(delay_ms * 90))
    ps, H = inf.ps, inf.H
    _free_check(out_path, inf.size)
    tmp = out_path + ".part"
    exp_pts = []
    cc_next = None
    pes_i = -1
    queue = deque()
    cum = 0
    crc_new = 0
    n_new = 0
    nulls = 0
    slots_left = 0
    ins_map, grown, n_extra, gbase = {}, 0, 0, 0
    try:
        with open(new_path, "rb") as fn, open(tmp, "wb") as fo:
            for buf in _ts_iter(inf, cancel, lambda f: progress(0.1 + 0.45 * f)):
                ins = []
                for k in range(len(buf) // ps):
                    t = k * ps + H
                    if buf[t] != 0x47:
                        raise MsgError("err_sync_file", inf.name)
                    if (((buf[t + 1] & 0x1F) << 8) | buf[t + 2]) != pid:
                        continue
                    if not _ts_has_pay(buf, t):
                        buf[t:t + 188] = _NULL_PKT
                        nulls += 1
                        continue
                    if cc_next is None:
                        cc_next = buf[t + 3] & 15
                    if buf[t + 1] & 0x40:
                        pes_i += 1
                        queue.clear()
                        if pes_i < len(marks):
                            m = marks[pes_i]
                            a, b = cum, min(new.n, cum + cnts[pes_i])
                            cum += cnts[pes_i]
                            if b > a:
                                data = b"".join(aud_read(fn, new, i) for i in range(a, b))
                                crc_new = zlib.crc32(data, crc_new)
                                n_new += len(data)
                                pts = None if m[1] is None else (m[1] + dly) % MOD33
                                pk = _ts_pes_packets(pid, m[3], m[4], pts, data)
                                if len(pk) > m[2]:
                                    grown += 1      # nagyobb bitráta: a felesleg extra csomagként követi a helyeket
                                queue.extend(pk)
                                exp_pts.append(pts)
                            queue.extend(bytearray(_NULL_PKT) for _ in range(m[2] - len(queue)))
                            slots_left = m[2]
                        else:
                            slots_left = 0
                    if pes_i < 0 or not queue:
                        buf[t:t + 188] = _NULL_PKT
                        nulls += 1
                        continue
                    pkt = queue.popleft()
                    if pkt[1] == 0x1F and pkt[2] == 0xFF:
                        nulls += 1
                    else:
                        pkt[3] = (pkt[3] & 0xF0) | cc_next
                        cc_next = (cc_next + 1) & 15
                    buf[t:t + 188] = pkt
                    slots_left -= 1
                    if slots_left == 0 and queue:
                        ex = []
                        while queue:
                            x = queue.popleft()
                            x[3] = (x[3] & 0xF0) | cc_next
                            cc_next = (cc_next + 1) & 15
                            ex.append(x)
                        ins.append((k, ex))
                        ins_map[gbase + k] = len(ex)
                        n_extra += len(ex)
                gbase += len(buf) // ps
                if ins:
                    out = bytearray()
                    prev = 0
                    for k, ex in ins:
                        e = (k + 1) * ps
                        out += buf[prev:e]
                        for x in ex:
                            out += buf[k * ps:k * ps + H] + x
                        prev = e
                    out += buf[prev:]
                    fo.write(out)
                else:
                    fo.write(buf)
        log(tr("au_l_ts", len(exp_pts), nulls, dly / 90.0))
        if n_extra:
            log(tr("au_l_grow", n_extra, grown))
        plan = {"crc": crc_new, "n": n_new, "pts": exp_pts, "new": new, "ins": ins_map}
        vres = ts_replace_verify(inf, pid, tmp, plan, lambda f: progress(0.55 + 0.45 * f), log,
                                 cancel) if verify else None
        if not verify:
            log(tr("l_verify_off"))
            vres = (0, 0)
        if not _finish_out(tmp, out_path, None, vres):
            return False
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    log(tr("l_done", out_path))
    return True


def ts_replace_verify(inf, pid, path, plan, progress, log, cancel):
    issue = _Issues(log)
    log(tr("au_v_head"))
    issue.head()
    ps, H = inf.ps, inf.H
    size = os.path.getsize(path)
    ins = plan.get("ins", {})
    want = (inf.size // ps + sum(ins.values())) * ps
    if size != want:
        issue("struct", "E", "au_v_size", size, want)
    st = {"cc": None, "i": 0}

    def cc_check(out, t):
        if (out[t + 3] >> 4) & 1:
            c = out[t + 3] & 15
            if st["cc"] is not None and c != ((st["cc"] + 1) & 15):
                issue("cc", "E", "au_v_cc", st["i"])
            st["cc"] = c

    def extras(fo, g):
        for _ in range(ins.get(g, 0)):
            x = fo.read(ps)
            st["i"] += 1
            if len(x) != ps or x[H] != 0x47 or (((x[H + 1] & 0x1F) << 8) | x[H + 2]) != pid:
                issue("struct", "E", "au_v_pid", st["i"])
            else:
                cc_check(x, H)

    g = 0
    with open(path, "rb", buffering=1 << 20) as fo:
        for buf in _ts_iter(inf, cancel):
            for k in range(len(buf) // ps):
                o = k * ps
                t = o + H
                out = fo.read(ps)
                st["i"] += 1
                if len(out) != ps:
                    issue("struct", "E", "au_v_size", size, want)
                    break
                if buf[t] != 0x47 or out[H] != 0x47:
                    issue("struct", "E", "err_sync_k", st["i"])
                else:
                    sp = ((buf[t + 1] & 0x1F) << 8) | buf[t + 2]
                    if sp != pid:
                        if buf[o:o + ps] != out:
                            issue("other", "E", "au_v_other", st["i"])
                    else:
                        if H and buf[o:o + 4] != out[:4]:
                            issue("other", "E", "au_v_other", st["i"])
                        op = ((out[H + 1] & 0x1F) << 8) | out[H + 2]
                        if op == 0x1FFF:
                            pass
                        elif op != pid:
                            issue("struct", "E", "au_v_pid", st["i"])
                        else:
                            cc_check(out, H)
                extras(fo, g)
                g += 1
    tmp_es = path + ".es"
    marks = []
    try:
        cp = TsInfo(path)
        cp.size, cp.ps, cp.H = size, ps, H
        ts_extract(cp, pid, tmp_es, None, cancel, marks)
        with open(tmp_es, "rb") as f:
            blob_crc, n = 0, 0
            while True:
                d = f.read(8 * 1024 * 1024)
                if not d:
                    break
                blob_crc = zlib.crc32(d, blob_crc)
                n += len(d)
    finally:
        try:
            os.remove(tmp_es)
        except OSError:
            pass
    if n != plan["n"] or blob_crc != plan["crc"]:
        issue("data", "E", "au_v_data", n, plan["n"])
    got = [m[1] for m in marks]
    if got != plan["pts"]:
        bad = sum(1 for a, b in zip(got, plan["pts"]) if a != b) + abs(len(got) - len(plan["pts"]))
        issue("pts", "E", "au_v_pts", bad)
    progress(1.0)
    return issue.finish()


# ---------------------------------------------------------------- MP4 csere ---

def mp4_replace_audio(inf, tid, new_path, out_path, delay_ms=0.0, progress=None, log=None,
                      cancel=None, verify=True, same_audio=False):
    log = log or (lambda s: None)
    progress = progress or (lambda f: None)
    if os.path.normcase(os.path.abspath(out_path)) in (
            os.path.normcase(os.path.abspath(inf.path)), os.path.normcase(os.path.abspath(new_path))):
        raise MsgError("j_sameout")
    T = inf.tracks
    ti = [i for i, x in enumerate(T) if x.id == tid and x.handler == b"soun"]
    if not ti:
        raise MsgError("au_unsup", "#%d" % tid)
    ti = ti[0]
    t = T[ti]
    fc, w, h, ch, sr, cfg = t.entry_info()
    codec = _mp4_acodec(fc, cfg)
    if codec not in ("aac", "ac3", "opus", "mp3", "eac3"):
        raise MsgError("au_unsup", fc.decode("latin-1"))
    new = aud_scan(new_path, cancel=cancel)
    if new.codec != codec or new.fs != sr and new.fs != t.mdts or (codec == "opus" and _chan_n(new.ch) != ch):
        raise MsgError("au_mismatch", "%s %d Hz" % (codec.upper(), sr), "%s %d Hz" % (new.codec.upper(), new.fs))
    if codec == "opus":
        _opus_check(new, opus_head_info(opus_head_from_dops(cfg[b"dOps"]))[1], t.stts[0][1] * 48000 // t.mdts, log)
    with open(new_path, "rb") as fn:
        if codec == "aac":
            asc_old = _esds_core(cfg[b"esds"])[1]
            asc_new = adts_asc(aud_read(fn, new, 0))
            if asc_parse(asc_old) != asc_parse(asc_new):
                raise MsgError("au_mismatch", "AAC %s" % (asc_parse(asc_old),), "AAC %s" % (asc_parse(asc_new),))
    log(tr("au_l_new", new.codec.upper(), new.n, new.ms() / 1000.0))
    if new.n != t.n:
        log(tr("au_l_count", t.n, new.n, (new.n - t.n) * new.spf * 1000.0 / new.fs))
    sync_report(t.media_dur() * 1000.0 / t.mdts, t.stts[0][1] * 1000.0 / t.mdts, new, delay_ms, log, old_codec=codec, same_audio=same_audio,
                old_pre=(opus_head_info(opus_head_from_dops(cfg[b"dOps"]))[1] if codec == "opus" else None))
    dur = int(round(new.spf * t.mdts / float(new.fs)))
    spc, sdi, cfs, total_old = t.layout()

    # --- új hangminták darabokra osztva (a régi darabszerkezet szerint)
    cnt, sd, left = [], [], new.n
    for c in range(len(spc)):
        n = left if c == len(spc) - 1 else min(spc[c], left)
        cnt.append(n)
        sd.append(sdi[c])
        left -= n
    newsz = []
    with open(new_path, "rb") as fn:
        for i in range(new.n):
            newsz.append(len(adts_strip(aud_read(fn, new, i))) if codec == "aac" else new.sizes[i])
    # --- fájlbeli sorrend: minden sáv minden darabja
    order = []
    for k, x in enumerate(T):
        if k == ti:
            for c, off in enumerate(x.offsets):
                if cnt[c]:
                    order.append((off, k, c))
        else:
            for c, off in enumerate(x.offsets):
                order.append((off, k, c))
    order.sort()
    relo = [[0] * len(x.offsets) for x in T]
    pos = 0
    cfs_o = [x.layout()[2] for x in T]
    spc_o = [x.layout()[0] for x in T]
    first_new = []
    run = 0
    for c in range(len(spc)):
        first_new.append(run)
        run += cnt[c]
    for off, k, c in order:
        relo[k][c] = pos
        if k == ti:
            pos += sum(newsz[first_new[c]:first_new[c] + cnt[c]])
        else:
            a = cfs_o[k][c]
            pos += sum(T[k].sizes[a:a + spc_o[k][c]])
    payload = pos
    big_mdat = payload + 8 > 0xFFFFFFFF
    mdat_hdr = struct.pack(">I4sQ", 1, b"mdat", payload + 16) if big_mdat else \
        struct.pack(">I4s", payload + 8, b"mdat")

    # --- új stsc / stts / stsz a cél sávhoz
    nz = [c for c in range(len(spc)) if cnt[c]]
    new_stsc, prev = [], None
    for j, c in enumerate(nz):
        key = (cnt[c], sd[c])
        if key != prev:
            new_stsc.append((j + 1, key[0], key[1]))
            prev = key
    media_new = new.n * dur
    media_old = t.media_dur()
    stts_list = [(new.n, dur)]
    if same_audio and new.n == t.n:               # csak eltolás: a minták időtartama változatlan marad
        media_new, stts_list = media_old, [tuple(e) for e in t.stts]
    same_time = (new.n == t.n and (dur * t.n == media_old or same_audio))
    m = inf.moov
    mvts = inf.mvts

    def tgt_edits():
        """A cél hangsáv szerkesztési listája: a hossz- és késleltetés-változás átvezetése."""
        d_ts = int(round(delay_ms * t.mdts / 1000.0))
        if same_time and not d_ts:
            return None
        base = list(t.elst) if t.elst else [(int(round(media_old * mvts / float(t.mdts))), 0)]
        if not same_time and len(base) == 1:
            sdur, mt = base[0]
            base = [(max(0, int(round((media_new - max(mt, 0)) * mvts / float(t.mdts)))), mt)]
        if d_ts > 0:                                  # később szóljon: üres szakasz az elejére
            base.insert(0, (int(round(d_ts * mvts / float(t.mdts))), -1))
        elif d_ts < 0:                                # korábban szóljon: az első mintákat átugorjuk
            skip = -d_ts
            for k, (sd, mt) in enumerate(base):
                if mt >= 0:
                    base[k] = (max(0, sd - int(round(skip * mvts / float(t.mdts)))), mt + skip)
                    break
        return base
    ed_new = tgt_edits()
    pres = []
    for k, x in enumerate(T):
        if k == ti and ed_new is not None:
            e = ed_new
            pres.append(sum(a for a, b in e) if e else int(round(media_new * mvts / float(t.mdts))))
        else:
            pres.append(sum(a for a, b in _mp4_edit_entries(x, mvts)))
    movie_dur = max(pres)

    def build_moov(ps0, use64):
        cnt_t = [0]

        def co(offs):
            o = [x + ps0 for x in offs]
            return _fbox(b"co64", 0, struct.pack(">I", len(o)) + _pk("Q", o)) if use64 else \
                _fbox(b"stco", 0, struct.pack(">I", len(o)) + _pk("I", o))

        def fn_trak(k):
            x = T[k]

            def f_stbl(typ, ps_, pe, bs):
                if k != ti:
                    return co(relo[k]) if typ in (b"stco", b"co64") else None
                if typ == b"stts":
                    return _fbox(b"stts", 0, struct.pack(">I", len(stts_list)) +
                                 _pk("I", [v for e in stts_list for v in e]))
                if typ == b"stsc":
                    return _fbox(b"stsc", 0, struct.pack(">I", len(new_stsc)) +
                                 _pk("I", [v for e in new_stsc for v in e]))
                if typ in (b"stsz", b"stz2"):
                    if typ == b"stz2":
                        return b""
                    return _fbox(b"stsz", 0, struct.pack(">II", 0, new.n) + _pk("I", newsz))
                if typ in (b"stco", b"co64"):
                    return co([relo[k][c] for c in nz])
                if typ in (b"ctts", b"stss", b"sdtp", b"sbgp", b"sgpd"):
                    return b""
                return None

            def f_minf(typ, ps_, pe, bs):
                return _box(b"stbl", _mp4_rebuild(m, ps_, pe, f_stbl)) if typ == b"stbl" else None

            def f_mdia(typ, ps_, pe, bs):
                if typ == b"mdhd" and k == ti and not same_time:
                    return _mp4_patch(m, ps_, pe, bs, 16, 24, media_new)
                if typ == b"minf":
                    return _box(b"minf", _mp4_rebuild(m, ps_, pe, f_minf))
                return None

            def f_trak(typ, ps_, pe, bs):
                if typ == b"tkhd" and k == ti and ed_new is not None:
                    r = _mp4_patch(m, ps_, pe, bs, 20, 28, pres[k])
                    return r
                if typ == b"edts" and k == ti and ed_new is not None:
                    return _mp4_elst_box(ed_new)
                if typ == b"mdia":
                    return _box(b"mdia", _mp4_rebuild(m, ps_, pe, f_mdia))
                return None
            return f_trak

        def f_moov(typ, ps_, pe, bs):
            if typ == b"mvhd" and ed_new is not None:
                return _mp4_patch(m, ps_, pe, bs, 16, 24, movie_dur)
            if typ == b"trak":
                k = cnt_t[0]
                cnt_t[0] += 1
                return _box(b"trak", _mp4_rebuild(m, ps_, pe, fn_trak(k)))
            return None
        return _box(b"moov", _mp4_rebuild(m, inf.moov_ps, len(m), f_moov))

    use64 = False
    moov = build_moov(0, False)
    ps0 = len(inf.ftyp) + len(moov) + len(mdat_hdr)
    if ps0 + payload > 0xFFFFFFFF:
        use64 = True
        moov = build_moov(0, True)
        ps0 = len(inf.ftyp) + len(moov) + len(mdat_hdr)
    moov2 = build_moov(ps0, use64)
    if len(moov2) != len(moov):
        raise MsgError("m_big")
    moov = moov2
    _free_check(out_path, payload + len(moov))

    tmp = out_path + ".part"
    crc_new = 0
    try:
        with open(inf.path, "rb") as fi, open(new_path, "rb") as fn, open(tmp, "wb") as fo:
            fo.write(inf.ftyp)
            fo.write(moov)
            fo.write(mdat_hdr)
            done = 0
            for off, k, c in order:
                if cancel is not None and cancel.is_set():
                    raise MsgError("cancelled")
                if k == ti:
                    parts = []
                    for i in range(first_new[c], first_new[c] + cnt[c]):
                        d = aud_read(fn, new, i)
                        parts.append(adts_strip(d) if codec == "aac" else d)
                    data = b"".join(parts)
                    crc_new = zlib.crc32(data, crc_new)
                else:
                    a = cfs_o[k][c]
                    ln = sum(T[k].sizes[a:a + spc_o[k][c]])
                    fi.seek(off)
                    data = fi.read(ln)
                    if len(data) != ln:
                        raise MsgError("m_trunc")
                fo.write(data)
                done += len(data)
                if done % 64 == 0:
                    progress(0.5 * done / float(max(1, payload)))
        log(tr("au_l_mp4", new.n, len(order)))
        plan = {"ti": ti, "crc": crc_new, "n": new.n, "dur": dur, "sizes": newsz, "stts": stts_list,
                "payload": payload}
        vres = mp4_replace_verify(inf, tmp, plan, lambda f: progress(0.5 + 0.5 * f), log, cancel) \
            if verify else (0, 0)
        if not verify:
            log(tr("l_verify_off"))
        if not _finish_out(tmp, out_path, None, vres):
            return False
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    log(tr("l_done", out_path))
    return True


def _mp4_track_crc(path, t):
    crc = 0
    with open(path, "rb") as f:
        for s in _mp4_samples(f, t):
            crc = zlib.crc32(s, crc)
    return crc


def mp4_replace_verify(inf, path, plan, progress, log, cancel):
    issue = _Issues(log)
    log(tr("au_v_head"))
    issue.head()
    out = Mp4Info(path)
    try:
        out.analyze()
    except MsgError as e:
        issue("struct", "E", "au_v_parse", str(e))
        return issue.finish()
    ti = plan["ti"]
    if len(out.tracks) != len(inf.tracks):
        issue("struct", "E", "au_v_tracks", len(out.tracks), len(inf.tracks))
        return issue.finish()
    for k, (a, b) in enumerate(zip(inf.tracks, out.tracks)):
        if cancel is not None and cancel.is_set():
            return None
        progress(k / float(len(inf.tracks)))
        if (a.id, a.handler, a.mdts) != (b.id, b.handler, b.mdts) or a.stsd != b.stsd:
            issue("struct", "E", "au_v_track", k + 1)
        if k == ti:
            if b.n != plan["n"] or list(b.sizes) != plan["sizes"] or [tuple(e) for e in b.stts] != plan["stts"]:
                issue("struct", "E", "au_v_tab", k + 1)
            crc = _mp4_track_crc(path, b)
            if crc != plan["crc"]:
                issue("data", "E", "au_v_data", b.n, plan["n"])
        else:
            if (a.stts, a.ctts, a.stss, a.sizes, a.elst) != (b.stts, b.ctts, b.stss, b.sizes, b.elst):
                issue("other", "E", "au_v_tab", k + 1)
            if _mp4_track_crc(inf.path, a) != _mp4_track_crc(path, b):
                issue("other", "E", "au_v_track_data", k + 1)
    progress(1.0)
    return issue.finish()


# ---------------------------------------------------------------- MKV csere ---

def _mkv_simple_block(tnum, rel, payload):
    if tnum > 126:
        raise MsgError("au_unsup", "#%d" % tnum)
    if not -32768 <= rel <= 32767:
        raise MsgError("au_range")
    body = bytes([0x80 | tnum]) + struct.pack(">h", rel) + b"\x80" + payload
    return _eb(ID_SIMPLEBLOCK, body)


_MKV_CID = {"ac3": "A_AC3", "eac3": "A_EAC3", "mp3": "A_MPEG/L3", "mp2": "A_MPEG/L2",
            "aac": "A_AAC", "opus": "A_OPUS"}


def _mkv_old_codec(cid):
    c = {"A_AC3": "ac3", "A_EAC3": "eac3", "A_MPEG/L3": "mp3", "A_MPEG/L2": "mp2",
         "A_OPUS": "opus"}.get(cid)
    return "aac" if cid.startswith("A_AAC") else c


def _mkv_frame_spf(codec, payload):
    """Egy régi blokk keretének mintaszáma (a kodek szerint) vagy None."""
    if codec in ("ac3", "eac3"):
        h = _hdr_ac3(payload, 0)
        return h[2] if h else None
    if codec == "aac":
        return 1024
    if codec in ("mp2", "mp3"):
        h = _hdr_mpa(payload, 0)
        return h[2] if h else None
    if codec == "opus":
        return opus_dur(payload)
    return None


def _mkv_retrack(tracks_raw, tnum, new, asc):
    """Tracks elem újraépítése: a cserélt hangsáv kodek-fejléce az új hangra áll át."""
    eid, size, hl = _mkv_hdr(tracks_raw, 0)
    body = tracks_raw[hl:]
    out = []
    for e, cs, ce, cp in _mkv_children(body, 0, len(body)):
        raw = bytes(body[cp:ce])
        if e == 0xAE:
            kids = list(_mkv_children(body, cs, ce))
            num = [int.from_bytes(body[s:en], "big") for (k, s, en, p) in kids if k == 0xD7]
            if num and num[0] == tnum:
                keep = b"".join(bytes(body[p:en]) for (k, s, en, p) in kids
                                if k not in (0x86, 0x63A2, 0x56AA, 0x56BB, 0x23E383, 0xE1))
                priv = b""
                if new.codec == "aac":
                    priv = _eb(0x63A2, asc)
                elif new.codec == "opus":
                    priv = _eb(0x63A2, new.head) + _eb_uint(0x56AA, new.pre * 1000000000 // 48000, 4) + \
                        _eb_uint(0x56BB, 80000000, 4)
                aud = _eb(0xE1, _eb(0xB5, struct.pack(">d", float(new.fs))) +
                          _eb_uint(0x9F, max(1, _chan_n(new.ch))))
                raw = _eb(0xAE, keep + _eb(0x86, _MKV_CID[new.codec].encode("ascii")) + priv + aud)
        out.append(raw)
    return _eb(ID_TRACKS, b"".join(out))


def mkv_replace_audio(inf, tnum, new_path, out_path, delay_ms=0.0, progress=None, log=None,
                      cancel=None, verify=True, same_audio=False):
    log = log or (lambda s: None)
    progress = progress or (lambda f: None)
    if os.path.normcase(os.path.abspath(out_path)) in (
            os.path.normcase(os.path.abspath(inf.path)), os.path.normcase(os.path.abspath(new_path))):
        raise MsgError("j_sameout")
    tk = [x for x in inf.tracks if x.number == tnum and x.type == 2]
    if not tk:
        raise MsgError("au_unsup", "#%d" % tnum)
    tk = tk[0]
    codec = _mkv_old_codec(tk.codec)
    new = aud_scan(new_path, cancel=cancel)
    switch = new.codec != codec
    fmt_change = (not switch) and (abs(new.fs - (tk.fs or new.fs)) > 1 or
                                   bool(tk.ch and _chan_n(new.ch) != tk.ch))
    rewrite = (switch or fmt_change) and not same_audio     # a sáv fejlécét át kell írni
    scale = inf.scale
    pt = inf.ptrack
    if pt is None:
        raise MsgError("k_notracks")
    # --- a régi hangsáv blokkjainak ideje (a varratok megőrzéséhez) és kerethossza
    old_ts, first_pl = [], None
    with open(inf.path, "rb") as fi:
        ctc = []
        for cp, cds, cend in inf.clusters:
            tc = _mkv_cluster_tc(fi, cds, cend)
            ctc.append(tc)
            for eid, ep, ee, info in _mkv_cluster_items(fi, cds, cend):
                if info is not None and info[0] == tnum:
                    if info[3] != 1:
                        raise MsgError("au_lace")
                    old_ts.append(tc + info[1])
                    if first_pl is None:
                        fi.seek(ep)
                        first_pl = _mkv_payload(fi.read(ee - ep))
    if not old_ts:
        raise MsgError("au_unsup", "#%d" % tnum)
    spf_old = _mkv_frame_spf(codec, first_pl) if codec else None
    fs_old = int(round(tk.fs or new.fs))
    if codec == "opus":
        fs_old = 48000
    with open(new_path, "rb") as fn:
        asc = b""
        if new.codec == "aac":
            asc = adts_asc(aud_read(fn, new, 0))
            if new.fs < 24000:
                log("%s %s" % (SYNC_MARK, tr("sy_sbr")))
    if new.var:
        raise MsgError("au_opus_var")
    if codec == "opus" and tk.priv[:8] == b"OpusHead" and new.codec == "opus":
        _opus_check(new, opus_head_info(tk.priv)[1], spf_old or new.spf, log)
    if not switch and codec == "aac" and asc_parse(tk.priv) != asc_parse(asc) and not same_audio:
        rewrite = True
    log(tr("au_l_new", new.codec.upper(), new.n, new.ms() / 1000.0))
    if switch:
        log(tr("au_l_switch", (codec or tk.codec).upper(), new.codec.upper()))
    elif rewrite:
        log(tr("au_l_fmt", tk.fs or 0, tk.ch or 0, new.fs, _chan_n(new.ch)))
    dly = int(round(delay_ms * 1e6 / scale))

    # --- az új keretek időbélyegei: a régi hang időtengelyére leképezve
    nsc = 1e9 / scale
    new_ts = []
    gaps = 0
    if spf_old and fs_old:
        d_old = spf_old * nsc / fs_old
        for a, b in zip(old_ts, old_ts[1:]):
            if abs((b - a) - d_old) > d_old * 0.5:
                gaps += 1
        for i in range(new.n):
            num = i * new.spf * fs_old
            den = spf_old * new.fs
            j = min(num // den, len(old_ts) - 1)
            rem = num - j * den
            new_ts.append(int(round(old_ts[j] + rem * nsc / (new.fs * fs_old))) + dly)
        old_ms = len(old_ts) * spf_old * 1000.0 / fs_old
        old_fr = spf_old * 1000.0 / fs_old
        nodata = False
    else:
        for i in range(new.n):
            new_ts.append(int(round(old_ts[0] + i * new.spf * nsc / new.fs)) + dly)
        old_ms = (old_ts[-1] - old_ts[0]) * scale / 1e6
        old_fr = new.spf * 1000.0 / new.fs
        nodata = True
    sync_report(old_ms, old_fr, new, delay_ms, log, switch=switch, old_codec=codec, same_audio=same_audio,
                old_pre=(opus_head_info(tk.priv)[1] if codec == "opus" and tk.priv[:8] == b"OpusHead" else None),
                gaps=gaps, nodata=nodata)

    with open(inf.path, "rb") as fr:
        fr.seek(inf.tracks_span[0])
        tracks_raw = fr.read(inf.tracks_span[1] - inf.tracks_span[0])
        pre = []
        for l1 in inf.l1:
            eid, s0, cs, ce = l1
            if eid in (ID_INFO, ID_CHAPTERS, ID_TAGS, ID_ATTACHMENTS):
                fr.seek(s0)
                pre.append((eid, fr.read(ce - s0)))
    if rewrite:
        tracks_raw = _mkv_retrack(tracks_raw, tnum, new, asc)
    pre.append((ID_TRACKS, tracks_raw))
    pre.sort(key=lambda x: 0 if x[0] == ID_INFO else 1 if x[0] == ID_TRACKS else 2)

    def build_seek(cues_pos, pos):
        return _mkv_seekhead([(e, p) for (e, _), p in zip(pre, pos)] + [(ID_CUES, cues_pos)])
    sh_len = len(build_seek(0, [0] * len(pre)))
    pos, p = [], sh_len
    for e, raw in pre:
        pos.append(p)
        p += len(raw)
    total = sum(c[2] - c[1] for c in inf.clusters)
    _free_check(out_path, total + p + new.n * 12 + os.path.getsize(new_path))
    tmp = out_path + ".part"
    cues, ncl = [], 0
    idx = 0
    crc_new = 0
    stats = {}
    seg_id = _eb_id(ID_SEGMENT)
    nclust = len(inf.clusters)

    def pl_of(fn, i):
        d = aud_read(fn, new, i)
        return adts_strip(d) if new.codec == "aac" else d
    try:
        with open(inf.path, "rb") as fi, open(new_path, "rb") as fn, open(tmp, "wb") as fo:
            fo.write(inf.ebml)
            seg_hdr_pos = fo.tell()
            fo.write(seg_id + MKV_UNKNOWN)
            S0 = fo.tell()
            fo.write(build_seek(0, pos))
            for e, raw in pre:
                fo.write(raw)
            done = 0
            for ci, (cp, cds, cend) in enumerate(inf.clusters):
                if cancel is not None and cancel.is_set():
                    raise MsgError("cancelled")
                tc = ctc[ci]
                bound = ctc[ci + 1] if ci + 1 < nclust else None
                cpos = fo.tell()
                fo.write(_eb_id(ID_CLUSTER) + MKV_UNKNOWN)
                dstart = fo.tell()
                fo.write(_eb_uint(ID_TIMECODE, tc, 4 if tc < (1 << 32) else 8))
                first_cue = True

                def emit(upto):
                    nonlocal idx, crc_new, first_cue
                    while idx < new.n and (upto is None or new_ts[idx] <= upto) and \
                            (bound is None or new_ts[idx] < bound):
                        pl = pl_of(fn, idx)
                        fo.write(_mkv_simple_block(tnum, new_ts[idx] - tc, pl))
                        crc_new = zlib.crc32(pl, crc_new)
                        if pt.number == tnum and first_cue:
                            cues.append((new_ts[idx], cpos - S0))
                            first_cue = False
                        idx += 1
                for eid, ep, ee, info in _mkv_cluster_items(fi, cds, cend):
                    if eid in (ID_TIMECODE, ID_POSITION, ID_PREVSIZE, ID_CRC32, ID_VOID):
                        continue
                    if info is not None and info[0] == tnum:
                        continue                       # a régi hangblokkok helyére az újak kerülnek
                    fi.seek(ep)
                    raw = fi.read(ee - ep)
                    if info is not None:
                        ts = tc + info[1]
                        emit(ts)
                        s = stats.setdefault(info[0], [0, 0, 0])
                        s[0] += 1
                        s[1] = zlib.crc32(raw, s[1])
                        s[2] = zlib.crc32(_Q.pack(ts), s[2])
                        if info[0] == pt.number:
                            if pt.type == 1:
                                if info[4]:
                                    cues.append((ts, cpos - S0))
                            elif first_cue:
                                cues.append((ts, cpos - S0))
                            first_cue = False
                    fo.write(raw)
                emit(None)
                end = fo.tell()
                fo.seek(dstart - 8)
                fo.write(b"\x01" + (end - dstart).to_bytes(7, "big"))
                fo.seek(end)
                ncl += 1
                done += cend - cds
                progress(0.5 * done / float(max(1, total)))
            if idx < new.n:
                raise MsgError("au_range")
            cues.sort()
            body = b"".join(_eb(0xBB, _eb_uint(0xB3, max(0, t_)) +
                                _eb(0xB7, _eb_uint(0xF7, pt.number) + _eb_uint(0xF1, p_)))
                            for t_, p_ in cues)
            cues_pos = fo.tell() - S0
            fo.write(_eb(ID_CUES, body))
            end_pos = fo.tell()
            fo.seek(seg_hdr_pos + len(seg_id))
            fo.write(b"\x01" + (end_pos - S0).to_bytes(7, "big"))
            fo.seek(S0)
            fo.write(build_seek(cues_pos, pos))
        log(tr("au_l_mkv", new.n, ncl, len(cues)))
        plan = {"crc": crc_new, "n": new.n, "stats": stats, "ncl": ncl, "tnum": tnum, "pt": pt.number,
                "tracks_raw": tracks_raw, "ebml": inf.ebml, "ts": new_ts}
        vres = mkv_replace_verify(inf, tmp, plan, lambda f: progress(0.5 + 0.5 * f), log, cancel) \
            if verify else (0, 0)
        if not verify:
            log(tr("l_verify_off"))
        if not _finish_out(tmp, out_path, None, vres):
            return False
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    log(tr("l_done", out_path))
    return True


def mkv_replace_verify(inf, path, plan, progress, log, cancel):
    issue = _Issues(log)
    log(tr("au_v_head"))
    issue.head()
    out = MkvInfo(path)
    try:
        out.analyze()
    except MsgError as e:
        issue("struct", "E", "au_v_parse", str(e))
        return issue.finish()
    with open(path, "rb") as f:
        f.seek(out.tracks_span[0])
        if f.read(out.tracks_span[1] - out.tracks_span[0]) != plan["tracks_raw"]:
            issue("struct", "E", "au_v_mkvtracks")
    if out.ebml != plan["ebml"]:
        issue("struct", "E", "au_v_ebml")
    if len(out.clusters) != plan["ncl"] or plan["ncl"] != len(inf.clusters):
        issue("struct", "E", "au_v_clusters", len(out.clusters), plan["ncl"])
    st, crc_a, n_a = {}, 0, 0
    tn = plan["tnum"]
    prev_tc = -1
    got_ts = []
    with open(path, "rb") as f:
        for ci, (cp, ds, cend) in enumerate(out.clusters):
            if cancel is not None and cancel.is_set():
                return None
            tc = _mkv_cluster_tc(f, ds, cend)
            if tc < prev_tc:
                issue("pts", "E", "au_v_ctc", _fmt_t(tc * inf.scale / 1e9))
            prev_tc = tc
            for eid, ep, ee, info in _mkv_cluster_items(f, ds, cend):
                if info is None:
                    continue
                f.seek(ep)
                raw = f.read(ee - ep)
                if info[0] == tn:
                    crc_a = zlib.crc32(_mkv_payload(raw), crc_a)
                    n_a += 1
                    got_ts.append(tc + info[1])
                else:
                    s = st.setdefault(info[0], [0, 0, 0])
                    s[0] += 1
                    s[1] = zlib.crc32(raw, s[1])
                    s[2] = zlib.crc32(_Q.pack(tc + info[1]), s[2])
            progress(0.9 * (ci + 1) / float(max(1, len(out.clusters))))
    if n_a != plan["n"] or crc_a != plan["crc"]:
        issue("data", "E", "au_v_data", n_a, plan["n"])
    if got_ts != plan["ts"]:
        issue("pts", "E", "au_v_pts", sum(1 for a, b in zip(got_ts, plan["ts"]) if a != b) +
              abs(len(got_ts) - len(plan["ts"])))
    if any(b < a for a, b in zip(got_ts, got_ts[1:])):
        issue("pts", "W", "au_v_nonmono")
    if st != {k: v for k, v in plan["stats"].items() if k != tn}:
        issue("other", "E", "au_v_other_mkv")
    progress(1.0)
    return issue.finish()


# ------------------------------------------------------------ belépési pont ---

def au_replace(inf, st, new_path, out_path, delay_ms=0.0, progress=None, log=None, cancel=None,
               verify=True, same_audio=False):
    """A kiválasztott hangsáv cseréje. st: au_list elem."""
    log = log or (lambda s: None)
    if st["type"] != "audio" or not (st["ok"] or inf.kind == "mkv"):
        raise MsgError("au_unsup", st["desc"])
    log(tr("au_l_rep", st["desc"], os.path.basename(new_path)))
    fn = {"ts": ts_replace_audio, "mp4": mp4_replace_audio, "mkv": mkv_replace_audio}[inf.kind]
    return fn(inf, st["id"], new_path, out_path, delay_ms, progress, log, cancel, verify, same_audio)


def au_shift(inf, st, out_path, delay_ms, progress=None, log=None, cancel=None, verify=True):
    """A kiválasztott hangsáv eltolása új hang nélkül: csak az időzítés változik, a hangadat
    bájtra azonos marad. (A hangot ideiglenesen kinyeri, majd azonos tartalommal visszacseréli.)"""
    log = log or (lambda s: None)
    progress = progress or (lambda f: None)
    if not delay_ms:
        raise MsgError("au_shift_zero")
    if st["type"] != "audio" or not (st["ok"] or inf.kind == "mkv"):
        raise MsgError("au_unsup", st["desc"])
    tmp = out_path + ".shift" + (st["ext"] if st["ext"] != ".bin" else ".es")
    try:
        au_extract(inf, st, tmp, lambda f: progress(0.2 * f), lambda s: None, cancel)
        log(tr("au_l_shiftrun", st["desc"], delay_ms))
        return au_replace(inf, st, tmp, out_path, delay_ms, lambda f: progress(0.2 + 0.8 * f), log,
                          cancel, verify, True)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


# ---------------------------------------------------------------- CLI ---------

def au_open(path):
    """Fájl megnyitása az eszközökhöz: (info, streams) vagy MsgError."""
    inf = analyze_into(FileInfo(path))
    if inf.error:
        raise inf.error if isinstance(inf.error, MsgError) else MsgError("e_prefix", str(inf.error))
    if inf.kind not in ("ts", "mp4", "mkv"):
        raise MsgError("t_unsup_kind")
    return inf, au_list(inf)



# ----------------------------------------- többfájlos folyamválasztás / összeállítás --

RAW_AUDIO_EXTS = (".ac3", ".eac3", ".ec3", ".aac", ".mp2", ".mp3", ".mpa", ".opus", ".ogg")


def au_open_any(path):
    """Fájl megnyitása a folyamválasztóhoz: (info | None, folyamok). Nyers hangfájl is lehet."""
    if os.path.splitext(path)[1].lower() in RAW_AUDIO_EXTS:
        with open(path, "rb") as f:
            head = f.read(262144)
        codec, start = aud_sniff(head)
        if codec is None:
            raise MsgError("au_unk")
        st = _st("audio", 0, codec, "%s (%s)" % (_ENC_NAME.get(codec, codec.upper()), tr("t_raw")),
                 AU_EXT.get(codec, ".bin"))
        st["raw"] = path
        return None, [st]
    return au_open(path)


def compose_plan(entries, checked, hint=None):
    """Kijelölés -> terv. entries: [{"path", "inf", "streams"}], checked: {(fájlindex, folyamindex)},
    hint: a listában kijelölt (fájlindex, folyamindex) vagy None."""
    def kind(x):
        return entries[x[0]]["streams"][x[1]]["type"]
    vids = sorted(x for x in checked if kind(x) == "video")
    auds = sorted(x for x in checked if kind(x) == "audio")
    if not vids:
        raise MsgError("cp_novideo")
    if len(vids) > 1:
        raise MsgError("cp_manyvideo")
    if not auds:
        raise MsgError("cp_noaudio")
    if len(auds) > 1:
        raise MsgError("cp_manyaudio")
    be = vids[0][0]
    base = entries[be]
    if base["inf"] is None or base["inf"].kind not in ("ts", "mp4", "mkv"):
        raise MsgError("t_unsup_kind")
    se, ss = auds[0]
    src = entries[se]["streams"][ss]
    if not src["ok"]:
        raise MsgError("au_unsup", src["desc"])
    plan = {"base": base, "base_inf": base["inf"], "video": base["streams"][vids[0][1]],
            "src_inf": entries[se]["inf"], "src_st": src, "same": se == be}
    if se == be:
        plan["target"] = src
        return plan
    baud = [st for st in base["streams"] if st["type"] == "audio"]
    if not baud:
        raise MsgError("cp_nobaseaudio")
    if len(baud) == 1:
        plan["target"] = baud[0]
    else:
        tgt = None
        if hint is not None and hint[0] == be and base["streams"][hint[1]]["type"] == "audio":
            tgt = base["streams"][hint[1]]
        if tgt is None:
            raise MsgError("cp_whichaudio")
        plan["target"] = tgt
    return plan


def au_compose(plan, out_path, delay_ms=0.0, progress=None, log=None, cancel=None, verify=True):
    """A terv végrehajtása: a kijelölt hang beillesztése az alapfájlba (nyers hangfájl nélkül)."""
    log = log or (lambda s: None)
    progress = progress or (lambda f: None)
    base, tgt, src = plan["base_inf"], plan["target"], plan["src_st"]
    log(tr("cp_l_plan", plan["video"]["desc"], src["desc"]))
    if plan["same"]:
        log(tr("cp_l_same"))
        return au_shift(base, tgt, out_path, delay_ms, progress, log, cancel, verify)
    if src.get("raw"):
        return au_replace(base, tgt, src["raw"], out_path, delay_ms, progress, log, cancel, verify)
    tmp = out_path + ".src" + (src["ext"] if src["ext"] != ".bin" else ".es")
    try:
        au_extract(plan["src_inf"], src, tmp, lambda f: progress(0.15 * f), log, cancel)
        return au_replace(base, tgt, tmp, out_path, delay_ms, lambda f: progress(0.15 + 0.85 * f),
                          log, cancel, verify)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def uniq_path(p):
    """Soha nem írunk felül meglévő fájlt: ha létezik, név_1.kit, név_2.kit, ..."""
    if not os.path.exists(p):
        return p
    b, e = os.path.splitext(p)
    k = 1
    while os.path.exists("%s_%d%s" % (b, k, e)):
        k += 1
    return "%s_%d%s" % (b, k, e)


def au_extract_many(items, outdir, progress=None, log=None, cancel=None, out_stem=None):
    """Több folyam kinyerése egy mappába. items: [(info, folyam)]. A kinyert fájlok listáját adja.
    Egyetlen folyamnál, ha out_stem adott, a fájl neve out_stem + a folyam kiterjesztése."""
    log = log or (lambda s: None)
    progress = progress or (lambda f: None)
    todo = []
    for inf, st in items:
        if inf is None or st.get("raw") or not st["ok"]:
            log(tr("cp_l_skip", st["desc"]))
        else:
            todo.append((inf, st))
    if not todo:
        raise MsgError("t_nothing")
    outs = []
    for n, (inf, st) in enumerate(todo):
        if cancel is not None and cancel.is_set():
            raise MsgError("cancelled")
        base = os.path.splitext(os.path.basename(inf.path))[0]
        ext = st["ext"] if st["ext"] != ".bin" else ".es"
        if out_stem and len(todo) == 1:
            p = uniq_path(out_stem + ext)
        else:
            p = uniq_path(os.path.join(outdir, "%s_%s%s" % (base, st["id"], ext)))
        log(tr("cp_l_ext", n + 1, len(todo)))
        au_extract(inf, st, p, lambda f, n=n: progress((n + f) / float(len(todo))), log, cancel)
        outs.append(p)
    progress(1.0)
    return outs


def au_cli(argv):
    ap = argparse.ArgumentParser(prog="mts_joiner", description=tr("cli_au_desc"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("streams")
    a.add_argument("file")
    b = sub.add_parser("extract")
    b.add_argument("file")
    b.add_argument("-s", "--stream", required=True, help=('a folyam azonosítója (streams parancs)' if LANG == "hu" else 'the stream ID (see the streams command)'))
    b.add_argument("-o", "--output", required=True)
    c = sub.add_parser("replace-audio")
    c.add_argument("file")
    c.add_argument("-s", "--stream", required=True)
    c.add_argument("-a", "--audio", required=True, help=('az új nyers hangfájl' if LANG == "hu" else 'the new raw audio file'))
    c.add_argument("-o", "--output", required=True)
    c.add_argument("--delay", type=float, default=0.0, help=('késleltetés ms-ban (TS, MKV)' if LANG == "hu" else 'delay in ms (TS, MKV)'))
    c.add_argument("--no-verify", action="store_true")
    d = sub.add_parser("shift-audio")
    d.add_argument("file")
    d.add_argument("-s", "--stream", required=True)
    d.add_argument("-o", "--output", required=True)
    d.add_argument("--delay", type=float, required=True, help=('eltolás ms-ban (pozitív = később szól)' if LANG == "hu" else 'offset in ms (positive = plays later)'))
    d.add_argument("--no-verify", action="store_true")
    for p in (a, b, c, d):
        p.add_argument("--lang", choices=sorted(_STR))
    args = ap.parse_args(argv)
    if args.lang:
        set_language(args.lang, save=False)
    try:
        inf, sts = au_open(args.file)
        if args.cmd == "streams":
            for s in sts:
                print("%-6s id=%-6s %-8s %s%s" % (s["type"], s["id"], s["codec"], s["desc"],
                                                  "" if s["ok"] else "  [" + tr("t_unsup") + "]"))
            return 0
        sel = [s for s in sts if str(s["id"]) == str(int(args.stream, 0))]
        if not sel:
            print(tr("t_pick"))
            return 2
        if args.cmd == "extract":
            au_extract(inf, sel[0], args.output, log=print)
        elif args.cmd == "shift-audio":
            au_shift(inf, sel[0], args.output, args.delay, log=print, verify=not args.no_verify)
        else:
            au_replace(inf, sel[0], args.audio, args.output, args.delay, log=print,
                       verify=not args.no_verify)
    except MsgError as e:
        print(str(e))
        return 3
    return 0


# ------------------------------------------------------------ alkalmazás-ikon --
# Az ikont a program maga rajzolja, kizárólag matematikai alakzatokból (nincs külső
# képfájl, nincs másolt grafika). Motívum: egy ferdén álló filmszalag, amelyet egy
# borostyánszínű vágás két részre választ. A filmkockák a bal oldalon sötétek, a jobb
# oldalon (a vágás után) kékeszöldre kivilágítva.
_ICON_ANGLE = math.radians(-24.0)
_CA, _SA = math.cos(_ICON_ANGLE), math.sin(_ICON_ANGLE)
ICON_REV = 2                       # a rajz módosításakor növeld: frissíti a gyorsítótárat
APP_USER_MODEL_ID = "szabiz.LosslessVideoToolkit.1"


def _mix(a, b, t):
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def _icon_sample(x, y):
    """Egy pont színe az egységnégyzetben: (r, g, b, a), a = 0 vagy 1."""
    qx = abs(x - 0.5) - 0.26
    qy = abs(y - 0.5) - 0.26
    if math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - 0.20 > 0.0:
        return (0.0, 0.0, 0.0, 0.0)                     # lekerekített négyzeten kívül
    bg = _mix((30, 27, 75), (13, 122, 117), 0.65 * y + 0.35 * x)
    cx, cy = x - 0.5, y - 0.5
    u = cx * _CA + cy * _SA
    v = -cx * _SA + cy * _CA
    if abs(u) >= 0.40 or abs(v) >= 0.19:
        return bg + (1.0,)
    w = u + 0.32 * v                                    # a vágás iránya (ferde)
    if abs(w) < 0.034:
        glow = max(0.0, 1.0 - abs(w) / 0.034)
        if abs(w) < 0.010:
            return (255.0, 190.0, 50.0, 1.0)
        return _mix(bg, (255, 190, 50), 0.45 * glow) + (1.0,)
    if 0.133 < abs(v) < 0.173 and abs((u + 0.07) % 0.14 - 0.07) < 0.030:
        return _mix(bg, (10, 12, 35), 0.8) + (1.0,)     # a film perforációja
    if abs(v) < 0.098 and abs((u + 0.08) % 0.16 - 0.08) < 0.058:
        return ((94.0, 234.0, 212.0) if w > 0 else (24.0, 28.0, 70.0)) + (1.0,)
    return (245.0, 242.0, 234.0, 1.0)                   # a filmszalag teste


def _icon_sample_small(x, y):
    """Egyszerűsített, vastagabb rajz a kis (legfeljebb 32 px-es) méretekhez: a címsor 16-24 px-es ikonján
    a perforáció és a vékony vonalak eltűnnének, ezért itt nagyobb filmszalag, kevesebb kocka, vastag vágás van."""
    qx = abs(x - 0.5) - 0.30
    qy = abs(y - 0.5) - 0.30
    if math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - 0.18 > 0.0:
        return (0.0, 0.0, 0.0, 0.0)                     # lekerekített négyzeten kívül
    bg = _mix((30, 27, 75), (13, 122, 117), 0.65 * y + 0.35 * x)
    cx, cy = x - 0.5, y - 0.5
    u = cx * _CA + cy * _SA
    v = -cx * _SA + cy * _CA
    if abs(u) >= 0.47 or abs(v) >= 0.285:
        return bg + (1.0,)
    w = u + 0.32 * v
    if abs(w) < 0.042:
        return (255.0, 190.0, 50.0, 1.0)                # a vágás
    if abs(v) < 0.175 and abs((u % 0.25) - 0.125) < 0.078:
        return ((94.0, 234.0, 212.0) if w > 0 else (24.0, 28.0, 70.0)) + (1.0,)
    return (245.0, 242.0, 234.0, 1.0)                   # a filmszalag teste


def make_icon_rgba(size):
    sample = _icon_sample_small if size <= 32 else _icon_sample
    ss = 4 if size <= 48 else 3 if size <= 128 else 2   # szuperminták a sima széleknél
    out = bytearray()
    inv = 1.0 / (size * ss)
    isz = 1.0 / size
    for py in range(size):
        for px in range(size):
            # gyors út: ha a pixel 5 pontja gyakorlatilag azonos színű, nincs szükség szupermintára
            x0, y0 = px * isz, py * isz
            c0 = sample(x0 + 0.5 * isz, y0 + 0.5 * isz)
            flat = True
            for dx, dy in ((0.02, 0.02), (0.98, 0.02), (0.02, 0.98), (0.98, 0.98)):
                c = sample(x0 + dx * isz, y0 + dy * isz)
                if c[3] != c0[3] or abs(c[0] - c0[0]) > 2.5 or abs(c[1] - c0[1]) > 2.5 \
                        or abs(c[2] - c0[2]) > 2.5:
                    flat = False
                    break
            if flat:
                out += bytes((int(c0[0] + 0.5), int(c0[1] + 0.5), int(c0[2] + 0.5), int(c0[3] * 255)))
                continue
            r = g = b = a = 0.0
            for sy in range(ss):
                y = (py * ss + sy + 0.5) * inv
                for sx in range(ss):
                    c = sample((px * ss + sx + 0.5) * inv, y)
                    if c[3]:
                        r += c[0]; g += c[1]; b += c[2]; a += 1.0
            if a:
                out += bytes((int(r / a + 0.5), int(g / a + 0.5), int(b / a + 0.5),
                              int(255.0 * a / (ss * ss) + 0.5)))
            else:
                out += b"\x00\x00\x00\x00"
    return bytes(out)


def make_icon_png(size):
    rgba = make_icon_rgba(size)
    raw = b"".join(b"\x00" + rgba[y * size * 4:(y + 1) * size * 4] for y in range(size))

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def make_icon_ico(pngs):
    """ICO fájl PNG-képekkel (Windows Vista+). pngs: {méret: png-bájtok}."""
    sizes = sorted(pngs)
    head = struct.pack("<HHH", 0, 1, len(sizes))
    off = 6 + 16 * len(sizes)
    ent = b""
    for s in sizes:
        ent += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(pngs[s]), off)
        off += len(pngs[s])
    return head + ent + b"".join(pngs[s] for s in sizes)


def _icon_files():
    """Az ikon PNG-k és az .ico előállítása (első indításkor ~2 mp, utána a gyorsítótárból).
    Visszatér: ({méret: png-bájtok}, ico-útvonal vagy None)."""
    sizes = (16, 20, 24, 32, 48, 64, 128, 256)
    d = os.path.join(os.path.expanduser("~"), ".lossless_video_toolkit")
    pngs, ico = {}, os.path.join(d, "app_r%d.ico" % ICON_REV)
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        d = None
    for s in sizes:
        fn = os.path.join(d, "icon%d_r%d.png" % (s, ICON_REV)) if d else None
        data = None
        if fn and os.path.isfile(fn):
            try:
                with open(fn, "rb") as f:
                    data = f.read()
            except OSError:
                data = None
        if not data or data[:8] != b"\x89PNG\r\n\x1a\n":
            data = make_icon_png(s)
            if fn:
                try:
                    with open(fn, "wb") as f:
                        f.write(data)
                except OSError:
                    pass
        pngs[s] = data
    if d is None or not os.path.isfile(ico):
        try:
            if d is None:
                ico = os.path.join(tempfile.gettempdir(), "lvt_app_r%d.ico" % ICON_REV)
            with open(ico, "wb") as f:
                f.write(make_icon_ico(pngs))
        except OSError:
            ico = None
    return pngs, ico


def set_app_identity():
    """Windows: saját alkalmazás-azonosító, hogy a tálcán ne a pythonw.exe ikonja jelenjen meg.
    A Tk ablak létrehozása ELŐTT kell meghívni."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except Exception:
            pass


def _win_set_window_icons(win, ico):
    """Windows: a címsor (kis) és a tálca / Alt+Tab (nagy) ikonját közvetlenül a Windowsnak adja át, a rendszer
    által kért méretben (a Tk saját ikonkezelése egyes gépeken a címsorban nem jeleníti meg az ikont)."""
    if sys.platform != "win32" or not ico:
        return
    try:
        import ctypes
        u = ctypes.windll.user32
        u.LoadImageW.restype = ctypes.c_void_p
        u.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_uint]
        u.SendMessageW.restype = ctypes.c_void_p
        u.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        u.GetParent.restype = ctypes.c_void_p
        u.GetParent.argtypes = [ctypes.c_void_p]
        win.update_idletasks()
        hwnd = u.GetParent(win.winfo_id()) or win.winfo_id()
        IMAGE_ICON, LR_LOADFROMFILE, WM_SETICON = 1, 0x10, 0x80
        small = u.LoadImageW(None, ico, IMAGE_ICON, u.GetSystemMetrics(49), u.GetSystemMetrics(50), LR_LOADFROMFILE)
        big = u.LoadImageW(None, ico, IMAGE_ICON, u.GetSystemMetrics(11), u.GetSystemMetrics(12), LR_LOADFROMFILE)
        if small:
            u.SendMessageW(hwnd, WM_SETICON, 0, small)      # ICON_SMALL: a címsor ikonja
        if big:
            u.SendMessageW(hwnd, WM_SETICON, 1, big)        # ICON_BIG: tálca, Alt+Tab
        win._app_hicons = (small, big)                      # a kezelők éljenek az ablakkal
    except Exception:       # noqa - az ikon sosem akadályozhatja az indulást
        pass


def install_app_icon(root):
    """Minden ablak (főablak, Súgó, Névjegy, párbeszédablakok) ezt az ikont kapja a tollas helyett."""
    import tkinter as tk
    ico = None
    try:
        pngs, ico = _icon_files()
        photos = [tk.PhotoImage(master=root, data=base64.b64encode(pngs[s])) for s in (128, 64, 32, 16)]
        root.iconphoto(True, *photos)                  # True: az utána létrejövő Toplevel-ek is öröklik
        root._app_icons = photos                       # hivatkozás, hogy a szemétgyűjtő ne törölje
    except Exception:
        pass
    if sys.platform == "win32" and ico:
        try:
            root.iconbitmap(default=ico)               # Windows: a tálca / Alt+Tab / címsor ikonja
        except Exception:
            pass
        _win_set_window_icons(root, ico)               # a címsor és a tálca ikonja közvetlenül a Windowsnak


def status_short(lvl, inf, is_ref):
    """Az Állapot oszlop rövid felirata (a részletes szöveg a lista alatt jelenik meg)."""
    if lvl == "pend":
        return tr("s_pend")
    if inf.error:
        return tr("s_err")
    if is_ref:
        return tr("s_ref")
    return tr({"ok": "s_ok", "warn": "s_warn", "bad": "s_bad"}[lvl])


def run_gui():
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import ttk, filedialog, messagebox as _real_mb

    class _MsgBox:
        """A párbeszédablakok mindig a főablakhoz tartoznak és előtérbe kerülnek: szülő nélkül a
        modális ablak a főablak mögé kerülhet, és az egész programot láthatatlanul blokkolja."""
        parent = None

        def _call(self, name, *a, **k):
            p = self.parent
            if p is not None:
                try:
                    p.deiconify()
                    p.lift()
                    p.focus_force()
                except tk.TclError:
                    pass
                k.setdefault("parent", p)
            return getattr(_real_mb, name)(*a, **k)

        def showwarning(self, *a, **k):
            return self._call("showwarning", *a, **k)

        def showinfo(self, *a, **k):
            return self._call("showinfo", *a, **k)

        def showerror(self, *a, **k):
            return self._call("showerror", *a, **k)

    messagebox = _MsgBox()

    class App:
        def __init__(self, root):
            self.root = root
            root.geometry("1280x720")
            root.minsize(900, 560)
            self.infos = []
            self.q = queue.Queue()
            self.joining = False
            self.cancel = threading.Event()
            self.reasons = {}
            self.seams = {}
            self.log_lines = []
            self.pb_value = 0
            self.out_var = tk.StringVar()
            self.pct = tk.StringVar()
            self.detail = tk.StringVar()
            self.summary = tk.StringVar()
            self.t_entries, self.t_chk, self.t_map = [], set(), {}
            self.t_out, self.t_out_auto = tk.StringVar(), ""
            self.t_delay, self.t_verify, self.t_pct = tk.StringVar(value="0"), tk.IntVar(value=1), tk.StringVar()
            self.t_busy, self.t_cancel, self.t_log_lines, self.t_pb_value = False, threading.Event(), [], 0
            self.cutter = (lvt_cutter.CutterTab(self, tk, ttk, filedialog, messagebox)
                           if lvt_cutter is not None else None)
            self._build()
            root.after(100, self._poll)

        # -- felület (nyelvváltáskor újraépül) --
        def _build(self):
            r = self.root
            r.title(tr("title"))
            # >>> lvt-analyzer stílus
            try:
                import lvt_analyzer as _lva_style
                _lva_style.style_tabs(ttk, r)
            except Exception:
                pass
            # <<< lvt-analyzer stílus
            nb = ttk.Notebook(r)
            nb.pack(fill="both", expand=True)
            r = ttk.Frame(nb)
            nb.add(r, text=tr("tab_join"))
            tf = ttk.Frame(nb)
            nb.add(tf, text=tr("tab_tools"))
            self._build_tools(tf)
            if self.cutter is not None:
                cf = ttk.Frame(nb)
                nb.add(cf, text=tr("tab_cut"))
                self.cutter.build(cf)
            ff = ttk.Frame(nb)
            nb.add(ff, text="FFmpeg")
            self._nb, self._ff_tab, self._last_tab = nb, ff, None
            nb.bind("<<NotebookTabChanged>>", self._tab_changed)
            bar = ttk.Frame(r, padding=(8, 8, 8, 0))
            bar.pack(fill="x")
            for key, cmd in (("b_add", self.add_files), ("b_folder", self.add_folder),
                             ("b_remove", self.remove_sel),
                             ("b_up", lambda: self.move(-1)), ("b_down", lambda: self.move(1)),
                             ("b_sort", self.sort_names), ("b_clear", self.clear)):
                ttk.Button(bar, text=tr(key), command=cmd).pack(side="left", padx=(0, 4))
            # a többi gomb után: névjegy és nyelvválasztó
            ttk.Button(bar, text=tr("b_about"), command=self.about).pack(side="right")
            ttk.Button(bar, text=tr("b_help"), command=self.help_win).pack(side="right", padx=(0, 4))
            self.root.bind("<F1>", lambda e: self.help_win())
            codes = list(_STR)
            nxt = codes[(codes.index(LANG) + 1) % len(codes)]
            ttk.Button(bar, text=tr("b_lang", LANG_NAMES[nxt]),
                       command=self.switch_lang).pack(side="right", padx=(0, 4))

            mid = ttk.Frame(r, padding=8)
            mid.pack(fill="both", expand=True)
            cols = ("n", "fajl", "hossz", "meret", "video", "hang", "kes", "folyt", "varrat", "allapot")
            self.tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="extended")
            # (oszlop, fejléc, kívánt szélesség = arány, legkisebb szélesség, igazítás)
            self._j_cols = (("n", "\u2713 #", 60, 44, "center"), ("fajl", tr("col_file"), 200, 90, "w"),
                            ("hossz", tr("col_len"), 70, 56, "e"), ("meret", tr("col_mb"), 60, 48, "e"),
                            ("video", tr("col_video"), 150, 80, "w"), ("hang", tr("col_audio"), 110, 70, "w"),
                            ("kes", tr("col_delay"), 120, 70, "center"), ("folyt", tr("col_cont"), 110, 70, "w"),
                            ("varrat", tr("col_seam"), 100, 70, "w"), ("allapot", tr("col_state"), 220, 100, "w"))
            for c, t, w, mw, a in self._j_cols:
                self.tree.heading(c, text=t)
                self.tree.column(c, width=w, anchor=a, stretch=False, minwidth=mw)
            self._j_lastw = 0
            self.tree.bind("<Configure>", self._fit_cols, add="+")
            mid.columnconfigure(0, weight=1)
            mid.rowconfigure(0, weight=1)
            sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
            hsb = ttk.Scrollbar(mid, orient="horizontal", command=self.tree.xview)   # csak szűk ablaknál kell
            self.tree.configure(yscrollcommand=sb.set, xscrollcommand=hsb.set)
            self.tree.grid(row=0, column=0, sticky="nsew")
            sb.grid(row=0, column=1, sticky="ns")
            hsb.grid(row=1, column=0, sticky="ew")
            self.tree.tag_configure("ok", background="#e3f6dc")
            self.tree.tag_configure("warn", background="#fff4c2")
            self.tree.tag_configure("bad", background="#ffd6d6")
            self.tree.tag_configure("pend", background="#eeeeee")
            self.tree.tag_configure("skip", background="#f3f3f3", foreground="#888888")
            self.tree.bind("<Button-1>", self._j_click)
            self.tree.bind("<<TreeviewSelect>>", lambda e: self._show_detail())
            # gyorsbillentyűk a fájllistán (Ctrl+A, Delete, Esc, Ctrl+O)
            self.tree.bind("<Control-a>", self._j_select_all)
            self.tree.bind("<Control-A>", self._j_select_all)
            self.tree.bind("<Delete>", self._j_remove_key)
            self.tree.bind("<BackSpace>", self._j_remove_key)
            self.tree.bind("<Escape>", self._j_clear_sel)
            self.tree.bind("<Control-o>", self._j_open)
            self.tree.bind("<Control-O>", self._j_open)

            ttk.Label(r, textvariable=self.detail, wraplength=1080, padding=(10, 0)).pack(fill="x")
            ttk.Label(r, textvariable=self.summary, padding=(10, 2)).pack(fill="x")

            out = ttk.Frame(r, padding=(8, 4))
            out.pack(fill="x")
            ttk.Label(out, text=tr("lbl_out")).pack(side="left")
            ttk.Entry(out, textvariable=self.out_var).pack(side="left", fill="x", expand=True, padx=6)
            ttk.Button(out, text=tr("b_browse"), command=self.browse_out).pack(side="left")

            act = ttk.Frame(r, padding=(8, 4))
            act.pack(fill="x")
            self.btn_start = ttk.Button(act, text=tr("b_start"), command=self.start, state="disabled")
            self.btn_start.pack(side="left")
            self.btn_cancel = ttk.Button(act, text=tr("b_cancel"), command=self.cancel.set,
                                         state="normal" if self.joining else "disabled")
            self.btn_cancel.pack(side="left", padx=6)
            self.pb = ttk.Progressbar(act, maximum=1000, value=self.pb_value)
            self.pb.pack(side="left", fill="x", expand=True, padx=6)
            ttk.Label(act, textvariable=self.pct, width=7).pack(side="left")

            lf = ttk.Frame(r, padding=(8, 0, 8, 8))
            lf.pack(fill="both")
            self.log_w = tk.Text(lf, height=9, state="normal", wrap="word")
            self.log_w.insert("end", "".join(l + "\n" for l in self.log_lines))
            self.log_w.configure(state="disabled")
            self.log_w.see("end")
            lsb = ttk.Scrollbar(lf, orient="vertical", command=self.log_w.yview)
            self.log_w.configure(yscrollcommand=lsb.set)
            self.log_w.pack(side="left", fill="both", expand=True)
            lsb.pack(side="left", fill="y")

        # -- második fül: hang / stream eszközök --
        def _build_tools(self, f):
            top = ttk.Frame(f, padding=8)
            top.pack(fill="x")
            for key, cmd in (("t_add", self.t_add), ("t_remove", self.t_remove), ("t_clear", self.t_clear)):
                ttk.Button(top, text=tr(key), command=cmd).pack(side="left", padx=(0, 4))
            # a bevezető szöveg a Súgó „Hang / stream eszközök” fülén maradt meg
            ttk.Button(top, text=tr("b_help"), command=self.help_tools).pack(side="left", padx=(12, 4))
            mid = ttk.Frame(f, padding=8)
            mid.pack(fill="both", expand=True)
            cols = ("tipus", "kodek", "kes", "allapot")
            self.t_tree = ttk.Treeview(mid, columns=cols, show="tree headings", selectmode="browse", height=14)
            self.t_tree.heading("#0", text=tr("col_stream"))
            self.t_tree.column("#0", width=560, stretch=True)
            for c, t, w in (("tipus", tr("t_col_type"), 70), ("kodek", tr("t_col_codec"), 90),
                            ("kes", tr("t_col_delay"), 100), ("allapot", tr("t_col_state"), 160)):
                self.t_tree.heading(c, text=t)
                self.t_tree.column(c, width=w, stretch=False)
            tsb = ttk.Scrollbar(mid, orient="vertical", command=self.t_tree.yview)
            self.t_tree.configure(yscrollcommand=tsb.set)
            self.t_tree.pack(side="left", fill="both", expand=True)
            tsb.pack(side="left", fill="y")
            self.t_tree.tag_configure("ok", background="#e3f6dc")
            self.t_tree.tag_configure("bad", background="#eeeeee")
            self.t_tree.tag_configure("file", background="#dfe9f7")
            self.t_tree.bind("<Button-1>", self._t_click)
            self._t_fill()
            row = ttk.Frame(f, padding=(8, 0))
            row.pack(fill="x")
            ttk.Button(row, text=tr("t_extract"), command=self.t_extract).pack(side="left")
            self.t_btn = ttk.Button(row, text=tr("t_compose"), command=self.t_compose,
                                    state="disabled" if self.t_busy else "normal")
            self.t_btn.pack(side="left", padx=(6, 0))
            ttk.Checkbutton(row, text=tr("t_verify"), variable=self.t_verify).pack(side="left", padx=(10, 0))
            box = ttk.LabelFrame(f, text=tr("t_replace_box"), padding=8)
            box.pack(fill="x", padx=8, pady=6)
            r2 = ttk.Frame(box)
            r2.pack(fill="x")
            ttk.Label(r2, text=tr("t_out")).pack(side="left")
            ttk.Entry(r2, textvariable=self.t_out).pack(side="left", fill="x", expand=True, padx=6)
            ttk.Button(r2, text=tr("b_browse"), command=self.t_browse_out).pack(side="left")
            r3 = ttk.Frame(box)
            r3.pack(fill="x", pady=(8, 0))
            ttk.Label(r3, text=tr("t_delay")).pack(side="left")
            ttk.Spinbox(r3, from_=-30000, to=30000, increment=1, textvariable=self.t_delay, width=8,
                        justify="right").pack(side="left", padx=6)
            for d in (-100, -10, -1, 1, 10, 100):
                ttk.Button(r3, text="%+d" % d, width=5,
                           command=lambda d=d: self.t_nudge(d)).pack(side="left", padx=1)
            ttk.Button(r3, text="0", width=3, command=lambda: self.t_delay.set("0")).pack(side="left", padx=(6, 0))
            ttk.Label(box, text=tr("t_delay_help"), foreground="#555555").pack(anchor="w", pady=(2, 0))
            act = ttk.Frame(f, padding=(8, 2))
            act.pack(fill="x")
            self.t_cancel_btn = ttk.Button(act, text=tr("b_cancel"), command=self.t_cancel.set,
                                           state="normal" if self.t_busy else "disabled")
            self.t_cancel_btn.pack(side="left")
            self.t_pb = ttk.Progressbar(act, maximum=1000, value=self.t_pb_value)
            self.t_pb.pack(side="left", fill="x", expand=True, padx=6)
            ttk.Label(act, textvariable=self.t_pct, width=7).pack(side="left")
            lf = ttk.Frame(f, padding=(8, 0, 8, 8))
            lf.pack(fill="both", expand=True)
            self.t_log_w = tk.Text(lf, height=9, state="normal", wrap="word")
            self.t_log_w.insert("end", "".join(l + "\n" for l in self.t_log_lines))
            self.t_log_w.configure(state="disabled")
            self.t_log_w.see("end")
            sb = ttk.Scrollbar(lf, orient="vertical", command=self.t_log_w.yview)
            self.t_log_w.configure(yscrollcommand=sb.set)
            self.t_log_w.pack(side="left", fill="both", expand=True)
            sb.pack(side="left", fill="y")

        # -- folyamválasztó: fa, jelölőnégyzetek --
        def _t_fill(self):
            self.t_tree.delete(*self.t_tree.get_children())
            self.t_map = {}
            for ei, e in enumerate(self.t_entries):
                fid = "f%d" % ei
                self.t_tree.insert("", "end", iid=fid, open=True, tags=("file",), values=("", "", "", ""))
                self.t_map[fid] = (ei, None)
                for si, s in enumerate(e["streams"]):
                    iid = "f%d_%d" % (ei, si)
                    self.t_tree.insert(fid, "end", iid=iid, tags=("ok" if s["ok"] else "bad",), values=(
                        tr("t_video") if s["type"] == "video" else tr("t_audio"), s["codec"],
                        (fmt_delay(s.get("delay")) + " ms") if s.get("delay") is not None else "–",
                        tr("t_ok") if s["ok"] else tr("t_unsup")))
                    self.t_map[iid] = (ei, si)
            self._t_paint()

        def _t_paint(self):
            for iid, (ei, si) in self.t_map.items():
                e = self.t_entries[ei]
                if si is None:
                    keys = [(e["path"], s["id"]) for s in e["streams"]]
                    on = bool(keys) and all(k in self.t_chk for k in keys)
                    txt = os.path.basename(e["path"])
                else:
                    on = (e["path"], e["streams"][si]["id"]) in self.t_chk
                    txt = e["streams"][si]["desc"]
                self.t_tree.item(iid, text=("☑ " if on else "☐ ") + txt)

        def _t_click(self, ev):
            t = self.t_tree
            if t.identify_column(ev.x) != "#0":
                return None
            iid = t.identify_row(ev.y)
            if not iid or "indicator" in t.identify_element(ev.x, ev.y):
                return None
            ei, si = self.t_map[iid]
            e = self.t_entries[ei]
            if si is None:
                keys = [(e["path"], s["id"]) for s in e["streams"]]
                if all(k in self.t_chk for k in keys):
                    self.t_chk.difference_update(keys)
                else:
                    self.t_chk.update(keys)
            else:
                k = (e["path"], e["streams"][si]["id"])
                if k in self.t_chk:
                    self.t_chk.discard(k)
                else:
                    self.t_chk.add(k)
            self._t_paint()
            self._t_suggest()
            return None

        def _t_checked(self):
            return {(ei, si) for ei, e in enumerate(self.t_entries) for si, s in enumerate(e["streams"])
                    if (e["path"], s["id"]) in self.t_chk}

        def _t_hint(self):
            sel = self.t_tree.selection()
            if sel and sel[0] in self.t_map and self.t_map[sel[0]][1] is not None:
                return self.t_map[sel[0]]
            return None

        def _t_suggest(self):
            cur = self.t_out.get().strip()
            if cur and cur != self.t_out_auto:
                return
            chk = [(e, s) for e in self.t_entries for s in e["streams"] if (e["path"], s["id"]) in self.t_chk]
            cand = None
            for e, s in chk:
                if s["type"] == "video":
                    b = os.path.splitext(e["path"])
                    cand = b[0] + "_ujhang" + b[1]
                    break
            if cand is None and chk:
                e, s = chk[0]       # csak hang: a kimenet a hangfolyam kiterjesztését kapja
                ext = s["ext"] if s["ext"] != ".bin" else ".es"
                cand = os.path.splitext(e["path"])[0] + ext
            if cand:
                self.t_out_auto = uniq_path(cand)
                self.t_out.set(self.t_out_auto)

        def t_add(self):
            paths = filedialog.askopenfilenames(title=tr("t_open_title"), filetypes=[
                ("TS / MP4 / MKV / audio", "*.mts *.m2ts *.ts *.mp4 *.m4v *.mov *.mkv *.mka *.webm "
                                           "*.ac3 *.eac3 *.aac *.mp2 *.mp3 *.mpa *.opus *.ogg"), ("*", "*.*")])
            have = {os.path.normcase(os.path.abspath(e["path"])) for e in self.t_entries}
            errs = []
            for p in paths:
                k = os.path.normcase(os.path.abspath(p))
                if k in have:
                    continue
                try:
                    inf, sts = au_open_any(p)
                except Exception as ex:
                    errs.append("%s: %s" % (os.path.basename(p), ex))
                    continue
                have.add(k)
                self.t_entries.append({"path": p, "inf": inf, "streams": sts})
            self._t_fill()
            if errs:
                messagebox.showwarning("Lossless Video Toolkit", "\n".join(errs))

        def t_remove(self):
            sel = self.t_tree.selection()
            if not sel or sel[0] not in self.t_map:
                return
            ei = self.t_map[sel[0]][0]
            e = self.t_entries.pop(ei)
            self.t_chk.difference_update({(e["path"], s["id"]) for s in e["streams"]})
            self._t_fill()

        def t_clear(self):
            self.t_entries, self.t_chk = [], set()
            self._t_fill()

        def t_log(self, s):
            self.t_log_lines.append(s)
            self.t_log_w.configure(state="normal")
            self.t_log_w.insert("end", s + "\n")
            self.t_log_w.see("end")
            self.t_log_w.configure(state="disabled")

        def t_browse_out(self):
            cur = self.t_out.get() or "out.mkv"
            b = os.path.splitext(cur)
            p = filedialog.asksaveasfilename(title=tr("t_save_title"), defaultextension=b[1],
                                             initialfile=os.path.basename(cur))
            if p:
                self.t_out.set(p)

        def _t_run(self, fn):
            self.t_busy = True
            self.t_cancel.clear()
            self.t_btn.configure(state="disabled")
            self.t_cancel_btn.configure(state="normal")

            self.t_warn = []

            def wlog(s):
                if s.startswith("⚠"):
                    self.t_warn.append(s)
                self.q.put(("tlog", s))

            def work():
                try:
                    ok = fn(lambda f: self.q.put(("tprog", f)), wlog)
                    self.q.put(("tend", None if ok is not False else "cancelled"))
                except MsgError as e:
                    self.q.put(("tend", "cancelled" if e.key == "cancelled" else "err:" + str(e)))
                except BaseException as e:
                    self.q.put(("tend", "err:" + (str(e) or e.__class__.__name__)))
            threading.Thread(target=work, daemon=True).start()

        def t_extract(self):
            if self.t_busy:
                return
            items = [(e["inf"], s) for e in self.t_entries for s in e["streams"]
                     if (e["path"], s["id"]) in self.t_chk]
            if not items:
                messagebox.showinfo("Lossless Video Toolkit", tr("t_nothing"))
                return
            out = self.t_out.get().strip()
            if out:
                d = os.path.dirname(os.path.abspath(out))
                stem = os.path.splitext(out)[0]
            else:
                d = os.path.dirname(os.path.abspath(items[0][0].path)) if items[0][0] is not None else ""
                stem = None
            if not d:
                d = filedialog.askdirectory(title=tr("t_dir"))
                if not d:
                    return
            self._t_run(lambda prog, log: au_extract_many(items, d, prog, log, self.t_cancel, stem) and True)

        def _t_delay_val(self):
            try:
                return float(self.t_delay.get().replace(",", ".") or 0)
            except ValueError:
                messagebox.showinfo("Lossless Video Toolkit", tr("t_bad_delay"))
                return None

        def t_nudge(self, d):
            v = self._t_delay_val()
            if v is not None:
                v += d
                self.t_delay.set(("%d" % v) if v == int(v) else ("%.1f" % v))

        def t_compose(self):
            if self.t_busy:
                return
            try:
                plan = compose_plan(self.t_entries, self._t_checked(), self._t_hint())
            except MsgError as e:
                messagebox.showinfo("Lossless Video Toolkit", str(e))
                return
            dly = self._t_delay_val()
            if dly is None:
                return
            out = self.t_out.get().strip()
            if not out:
                self._t_suggest()
                out = self.t_out.get().strip()
            if not out:
                messagebox.showwarning(tr("m_noout_t"), tr("m_noout"))
                return
            if os.path.normcase(os.path.abspath(out)) in {os.path.normcase(os.path.abspath(e["path"]))
                                                           for e in self.t_entries}:
                messagebox.showwarning("Lossless Video Toolkit", tr("j_sameout"))
                return
            new = uniq_path(out)
            if new != out:
                out = new
                self.t_out.set(out)
                self.t_out_auto = ""
            ver = bool(self.t_verify.get())
            self._t_run(lambda prog, log: au_compose(plan, out, dly, prog, log, self.t_cancel, ver))

        def _tab_changed(self, event=None):
            nb = self._nb
            try:
                cur = nb.select()
            except tk.TclError:
                return
            if cur == str(self._ff_tab):
                if self._last_tab:
                    nb.select(self._last_tab)
                else:
                    nb.select(0)
                self.open_ffmpeg()
            else:
                self._last_tab = cur

        def open_ffmpeg(self):
            w = getattr(self, "_ffwin", None)
            try:
                if w is not None and w.winfo_exists():
                    w.deiconify()
                    w.lift()
                    w.focus_force()
                    return
            except tk.TclError:
                pass
            try:
                import lvt_ffmpeg
            except ImportError:
                messagebox.showwarning("FFmpeg", "lvt_ffmpeg.py hiányzik / not found")
                return
            lvt_ffmpeg.LANG = LANG
            p = lvt_ffmpeg.open_window(self.root, tk, ttk, filedialog, _real_mb)
            self._ffwin = p.parent.winfo_toplevel() if p else None

        def switch_lang(self):
            sel = [int(i) for i in self.tree.selection()]
            hw = getattr(self, "_help", None)          # a súgó nyelve is változik: zárjuk be
            if hw is not None:
                try:
                    hw.destroy()
                except tk.TclError:
                    pass
                self._help = None
            codes = list(_STR)
            set_language(codes[(codes.index(LANG) + 1) % len(codes)])
            for w in self.root.winfo_children():
                w.destroy()
            self._build()
            self.refresh(select=sel)

        def help_win(self, event=None, page=None):
            """Súgó: nem modális ablak, hogy olvasás közben dolgozni lehessen.

            page: a megnyitandó fül címe (None = az első fül)."""
            w = getattr(self, "_help", None)
            if w is not None:
                try:
                    if w.winfo_exists():
                        w.deiconify()
                        w.lift()
                        w.focus_force()
                        self._help_goto(w, page)
                        return
                except tk.TclError:
                    pass
            win = tk.Toplevel(self.root)
            self._help = win
            win.title(tr("help_title"))
            win.geometry("920x680")
            nb = ttk.Notebook(win)
            nb.pack(fill="both", expand=True, padx=8, pady=8)
            tabs = {}
            for title, text in help_pages():
                fr = ttk.Frame(nb)
                t = tk.Text(fr, wrap="word", padx=14, pady=8, relief="flat", height=10)
                s = ttk.Scrollbar(fr, orient="vertical", command=t.yview)
                t.configure(yscrollcommand=s.set)
                render_help(t, text, tkfont)
                t.pack(side="left", fill="both", expand=True)
                s.pack(side="left", fill="y")
                nb.add(fr, text=title)
                tabs[title] = fr
            win._help_nb, win._help_tabs = nb, tabs
            self._help_goto(win, page)
            ttk.Button(win, text=tr("b_close"), command=win.destroy).pack(pady=(0, 8))
            win.bind("<Escape>", lambda e: win.destroy())

        def _help_goto(self, win, page):
            """A súgóablakban a megadott című fülre vált, ha van ilyen."""
            if not page:
                return
            try:
                fr = getattr(win, "_help_tabs", {}).get(page)
                if fr is not None:
                    win._help_nb.select(fr)
            except tk.TclError:
                pass

        def help_tools(self):
            """Súgó megnyitása a „Hang / stream eszközök” füllel."""
            self.help_win(page=tr("tab_tools"))

        def about(self):
            win = tk.Toplevel(self.root)
            win.title("Lossless Video Toolkit")
            win.geometry("720x540")
            win.transient(self.root)
            nb = ttk.Notebook(win)
            nb.pack(fill="both", expand=True, padx=8, pady=8)
            for key, text in (("tab_about", tr("about_text", __version__, YEAR, AUTHOR)),
                              ("tab_license", MIT_TEXT),
                              ("tab_legal", tr("legal_text", __version__, AUTHOR, YEAR, AUTHOR)),
                              ("tab_comp", tr("comp_text"))):
                fr = ttk.Frame(nb)
                t = tk.Text(fr, wrap="word", padx=10, pady=8, relief="flat", height=10)
                s = ttk.Scrollbar(fr, orient="vertical", command=t.yview)
                t.configure(yscrollcommand=s.set)
                t.insert("1.0", text)
                t.configure(state="disabled")
                t.pack(side="left", fill="both", expand=True)
                s.pack(side="left", fill="y")
                nb.add(fr, text=tr(key))
            close_btn = ttk.Button(win, text=tr("b_close"), command=win.destroy)
            close_btn.pack(pady=(0, 8))
            win.grab_set()
            # Szerzői ablak: ennyi egymás utáni kattintás BÁRHOL az ablakban (a Bezár gomb kivételével).
            seq = {"n": 0, "t": 0}
            NEED, SPAN = 5, 2000

            def on_click(ev):
                px, py = win.winfo_pointerxy()
                if not (win.winfo_rootx() <= px < win.winfo_rootx() + win.winfo_width() and
                        win.winfo_rooty() <= py < win.winfo_rooty() + win.winfo_height()):
                    return
                now = int(win.tk.call("clock", "milliseconds"))
                gap = now - seq["t"]
                seq["n"] = seq["n"] + 1 if (seq["n"] and gap <= SPAN) else 1
                seq["t"] = now
                if seq["n"] >= NEED:
                    seq["n"] = 0
                    try:
                        self.credits_win(win)
                    except Exception as ex:
                        messagebox.showerror("Lossless Video Toolkit",
                                             "%s: %s" % (ex.__class__.__name__, ex))

            win.bind("<Button-1>", on_click, add="+")
            
        def credits_win(self, parent):
            """A szerző neve, e-mail-címe és az igevers (magyarul és angolul)."""
            top = tk.Toplevel(parent)
            top.title("Lossless Video Toolkit")
            top.transient(parent)
            top.resizable(False, False)
            base = tkfont.nametofont("TkDefaultFont")
            top._fonts = []
            for kw in ({"size": base.cget("size") + 6, "weight": "bold"}, {"slant": "italic"}, {"weight": "bold"}):
                f = base.copy()
                f.configure(**kw)
                top._fonts.append(f)
            f_name, f_verse, f_ref = top._fonts
            fr = ttk.Frame(top, padding=22)
            fr.pack()
            ttk.Label(fr, text=AUTHOR, font=f_name).pack()
            ttk.Label(fr, text=AUTHOR_EMAIL, foreground="#1f4e79").pack(pady=(2, 8))
            for lang in ("hu", "en"):
                text, ref, source = CREDITS_VERSE[lang]
                ttk.Separator(fr).pack(fill="x", pady=(10, 4))
                quoted = ("\u201e%s\u201d" if lang == "hu" else "\u201c%s\u201d") % text
                ttk.Label(fr, text=quoted, font=f_verse, wraplength=540, justify="center").pack(pady=(6, 2))
                ttk.Label(fr, text="\u2013 " + ref, font=f_ref).pack()
                ttk.Label(fr, text=source, foreground="#666666", wraplength=540, justify="center").pack()

            def close(event=None):
                try:
                    top.grab_release()
                except tk.TclError:
                    pass
                top.destroy()
                try:
                    parent.grab_set()          # a Névjegy ablak modális marad
                except tk.TclError:
                    pass
            ttk.Button(fr, text=tr("b_close"), command=close).pack(pady=(16, 0))
            top.bind("<Escape>", close)
            top.protocol("WM_DELETE_WINDOW", close)
            top.update_idletasks()
            try:                               # középre a Névjegy ablakon
                x = parent.winfo_rootx() + (parent.winfo_width() - top.winfo_reqwidth()) // 2
                y = parent.winfo_rooty() + (parent.winfo_height() - top.winfo_reqheight()) // 2
                top.geometry("+%d+%d" % (max(0, x), max(0, y)))
                top.wait_visibility()
                top.grab_set()
            except tk.TclError:
                pass
            top.focus_force()

        def log(self, s):
            self.log_lines.append(s)
            self.log_w.configure(state="normal")
            self.log_w.insert("end", s + "\n")
            self.log_w.see("end")
            self.log_w.configure(state="disabled")

        # -- lista kezelése --
        def add_files(self):
            paths = filedialog.askopenfilenames(
                title=tr("dlg_files"),
                filetypes=[(tr("ft_video"), "*.mts *.m2ts *.ts *.mp4 *.m4v *.mov *.mkv *.mka *.webm *.mpg *.mpeg *.mod *.vob"),
                           (tr("ft_avchd"), "*.mts *.m2ts *.ts"), (tr("ft_all"), "*.*")])
            self._add(sorted(paths, key=lambda p: natural_key(os.path.basename(p))))

        def add_folder(self):
            d = filedialog.askdirectory(title=tr("dlg_folder"))
            if d:
                names = [n for n in os.listdir(d) if n.lower().endswith((".mts", ".m2ts", ".mp4", ".m4v", ".mov") + MKV_EXTS + MPG_EXTS + VOB_EXTS)]
                self._add([os.path.join(d, n) for n in sorted(names, key=natural_key)])

        def _add(self, paths):
            have = {os.path.normcase(os.path.abspath(i.path)) for i in self.infos}
            new = []
            for p in paths:
                k = os.path.normcase(os.path.abspath(p))
                if k not in have:
                    have.add(k)
                    new.append(FileInfo(p))
            if not new:
                return
            self.infos.extend(new)
            cur = os.path.basename(self.out_var.get())
            if not cur or cur in ("osszefuzott.m2ts", "osszefuzott.mp4", "osszefuzott.mov",
                           "osszefuzott.mkv", "osszefuzott.webm", "osszefuzott.mpg",
                           "osszefuzott.vob", "osszefuzott.mpeg"):
                first = self.infos[0].path
                self.out_var.set(os.path.join(os.path.dirname(first), "osszefuzott" + default_out_ext(first)))
            self.refresh()

            def work():
                for inf in new:
                    analyze_into(inf)
                    self.q.put(("refresh",))
            threading.Thread(target=work, daemon=True).start()

        def _j_select_all(self, _e=None):
            # Ctrl+A: minden sor kijelölése és minden pipa bekapcsolása
            if self.joining:
                return "break"
            for inf in self.infos:
                inf.use = True
            self.refresh(select=list(range(len(self.infos))))
            return "break"

        def _j_clear_sel(self, _e=None):
            self.tree.selection_remove(self.tree.selection())
            return "break"

        def _j_remove_key(self, _e=None):
            # Delete / Backspace: a kijelölt sorok kivétele a listából (a lemezről nem törlünk)
            if self.joining:
                return "break"
            if self.tree.selection():
                self.remove_sel()
            return "break"

        def _j_open(self, _e=None):
            if not self.joining:
                self.add_files()
            return "break"

        def remove_sel(self):
            sel = {int(i) for i in self.tree.selection()}
            self.infos = [x for n, x in enumerate(self.infos) if n not in sel]
            self.refresh()

        def clear(self):
            self.infos = []
            self.refresh()

        def move(self, d):
            sel = sorted(int(i) for i in self.tree.selection())
            if not sel:
                return
            L = self.infos
            for n in (sel if d < 0 else sel[::-1]):
                m = n + d
                if 0 <= m < len(L) and m not in sel:
                    L[n], L[m] = L[m], L[n]
                    sel[sel.index(n)] = m
            self.refresh(select=sel)

        def sort_names(self):
            self.infos.sort(key=lambda i: natural_key(i.name))
            self.refresh()

        def browse_out(self):
            kind = self.infos[0].kind if self.infos else "ts"
            if kind == "mp4":
                fts = [("MP4", "*.mp4"), ("MOV", "*.mov")]
            elif kind == "mkv":
                fts = [("MKV", "*.mkv"), ("WebM", "*.webm"), ("MKA", "*.mka")]
            elif kind == "vob":
                fts = [("VOB", "*.vob")]
            elif kind == "mpg":
                fts = [("MPEG", "*.mpg *.mpeg"), ("MOD", "*.mod")]
            else:
                fts = [("M2TS", "*.m2ts"), ("TS", "*.ts")]
            p = filedialog.asksaveasfilename(
                defaultextension=fts[0][1][1:], filetypes=fts,
                initialfile=os.path.basename(self.out_var.get() or "osszefuzott" + fts[0][1][1:]))
            if p:
                self.out_var.set(p)

        def _fit_cols(self, event=None):
            """Az oszlopok szélességét a lista aktuális szélességéhez igazítja (arányosan), hogy semmi ne csússzon ki
            a képernyőről. Ha az ablak még ennél is keskenyebb, a legkisebb szélességek maradnak és a vízszintes
            görgetősáv használható."""
            try:
                total = self.tree.winfo_width() - 4
                if total < 100 or abs(total - self._j_lastw) < 3:
                    return
                self._j_lastw = total
                widths = {c: mw for c, _t, _w, mw, _a in self._j_cols}
                free = total - sum(widths.values())
                if free > 0:
                    # a maradék helyet a kívánt szélességek feletti rész arányában osztjuk szét
                    extra = {c: max(0, w - mw) for c, _t, w, mw, _a in self._j_cols}
                    need = sum(extra.values())
                    if need <= free:
                        for c in widths:
                            widths[c] += extra[c]
                        widths["allapot"] += free - need       # ami még marad, az Állapot oszlopé
                    else:
                        for c in widths:
                            widths[c] += int(free * extra[c] / need)
                for c, w in widths.items():
                    self.tree.column(c, width=max(30, int(w)))
            except Exception:       # noqa
                pass

        def _j_click(self, ev):
            self.tree.focus_set()
            if self.joining:
                return None
            if self.tree.identify_region(ev.x, ev.y) != "cell" or self.tree.identify_column(ev.x) != "#1":
                return None
            iid = self.tree.identify_row(ev.y)
            if not iid:
                return None
            inf = self.infos[int(iid)]
            inf.use = not getattr(inf, "use", True)
            self.refresh()
            return "break"

        def refresh(self, select=None):
            if select is None:
                select = [int(i) for i in self.tree.selection() if int(i) < len(self.infos)]
            self.tree.delete(*self.tree.get_children())
            act = [i for i in self.infos if getattr(i, "use", True)]
            ref = act[0] if act and not act[0].pending and not act[0].error else None
            any_bad = pend = False
            total = 0.0
            self.reasons = {}
            self.levels = {}
            self.seams = {}
            prev = None
            for n, inf in enumerate(self.infos):
                use = getattr(inf, "use", True)
                mark = ("\u2611 " if use else "\u2610 ") + str(n + 1)
                if not use:
                    self.reasons[n] = tr("row_skip")
                    self.levels[n] = "skip"
                    if inf.pending or inf.error:
                        vals = (mark, inf.name, "", "", "", "", "", "", "", tr("row_skip"))
                    else:
                        vals = (mark, inf.name, fmt_dur(inf.duration), "%.1f" % (inf.size / 1048576.0),
                                inf.vdesc(), inf.adesc(), delay_text(inf), "", "", tr("row_skip"))
                    self.tree.insert("", "end", iid=str(n), values=vals, tags=("skip",))
                    continue
                lvl, txt = compare(ref, inf, prev)
                self.levels[n] = lvl
                any_bad |= lvl == "bad"
                pend |= lvl == "pend"
                sm = seam_texts(prev, inf)
                prev = inf
                if sm:
                    self.seams[n] = sm
                sc, sq = (sm["cont"], sm["qual"]) if sm else ("", "")
                short = status_short(lvl, inf, inf is ref)
                if lvl == "pend":
                    self.reasons[n] = txt
                    vals = (mark, inf.name, "", "", "", "", "", "", "", short)
                elif inf.error:
                    self.reasons[n] = tr("row_err") + txt
                    vals = (mark, inf.name, "", "", "", "", "", "", "", short)
                else:
                    total += inf.duration
                    prefix = {"ok": "", "warn": tr("row_warn"), "bad": tr("row_bad")}[lvl]
                    self.reasons[n] = prefix + txt
                    vals = (mark, inf.name, fmt_dur(inf.duration), "%.1f" % (inf.size / 1048576.0),
                            inf.vdesc(), inf.adesc(), delay_text(inf), sc, sq, short)
                self.tree.insert("", "end", iid=str(n), values=vals, tags=(lvl,))
            for n in select:
                if n < len(self.infos):
                    self.tree.selection_add(str(n))
            self.summary.set(tr("summary", len(act), fmt_dur(total)) if self.infos else "")
            ok = bool(act) and not any_bad and not pend and not self.joining
            self.btn_start.configure(state="normal" if ok else "disabled")
            self._show_detail()

        def _show_detail(self):
            """A részletes leírás a lista és a gombsor között: a kijelölt sor, különben az első gondos sor."""
            sel = self.tree.selection()
            levels = getattr(self, "levels", {})
            if sel:
                n = int(sel[0])
            else:
                flagged = [k for k in sorted(levels) if levels[k] in ("bad", "warn")]
                n = flagged[0] if flagged else None
            if n is None or n >= len(self.infos):
                self.detail.set("")
                return
            txt = self.reasons.get(n, "")
            sm = self.seams.get(n)
            if sm and sm["detail"]:
                txt += "\n" + sm["detail"]
            self.detail.set("%s – %s" % (self.infos[n].name, txt))

        # -- összefűzés --
        def start(self):
            out = self.out_var.get().strip()
            if not out:
                messagebox.showwarning(tr("m_noout_t"), tr("m_noout"))
                return
            new = uniq_path(out)
            if new != out:
                out = new
                self.out_var.set(out)
            self.joining = True
            self.cancel.clear()
            self.btn_start.configure(state="disabled")
            self.btn_cancel.configure(state="normal")
            self.log(tr("l_start"))
            infos = [i for i in self.infos if getattr(i, "use", True)]

            def work():
                try:
                    ok = join_files(infos, out, lambda f: self.q.put(("prog", f)),
                                    lambda s: self.q.put(("log", s)), self.cancel)
                    self.q.put(("end", None if ok else "cancelled"))
                except BaseException as e:
                    self.q.put(("end", "err:" + (str(e) or e.__class__.__name__)))
            threading.Thread(target=work, daemon=True).start()

        def _poll(self):
            dialogs = []
            try:
                while True:
                    try:
                        m = self.q.get_nowait()
                    except queue.Empty:
                        break
                    try:
                        self._handle(m, dialogs)
                    except Exception as ex:      # egy hibás üzenet ne állítsa le a felületet
                        try:
                            self.log("! %s: %s" % (ex.__class__.__name__, ex))
                        except Exception:
                            pass
            finally:
                try:
                    self.root.after(100, self._poll)
                except tk.TclError:              # az ablak már bezárult
                    return
            for kind, title, text in dialogs:
                try:
                    getattr(messagebox, kind)(title, text)
                except tk.TclError:
                    return

        def _handle(self, m, dialogs):
            if m[0] == "refresh":
                self.refresh()
            elif m[0] == "log":
                self.log(m[1])
            elif m[0] == "prog":
                self.pb_value = m[1] * 1000
                self.pb["value"] = self.pb_value
                self.pct.set("%d%%" % int(m[1] * 100))
            elif m[0] == "tlog":
                self.t_log(m[1])
            elif m[0] == "tprog":
                self.t_pb_value = m[1] * 1000
                self.t_pb["value"] = self.t_pb_value
                self.t_pct.set("%d%%" % int(m[1] * 100))
            elif m[0] == "tend":
                self.t_busy = False
                self.t_btn.configure(state="normal")
                self.t_cancel_btn.configure(state="disabled")
                if m[1]:
                    msg = tr("cancelled") if m[1] == "cancelled" else tr("e_prefix", m[1][4:])
                    self.t_log(msg)
                    dialogs.append(("showwarning", "Lossless Video Toolkit", msg))
                else:
                    self.t_pb_value = 1000
                    self.t_pb["value"] = 1000
                    self.t_pct.set("100%")
                    if self.t_warn:
                        dialogs.append(("showwarning", tr("t_sync_title"),
                                        tr("t_done") + "\n\n" + "\n\n".join(self.t_warn)))
                    else:
                        dialogs.append(("showinfo", "Lossless Video Toolkit", tr("t_done")))
            elif m[0] in ("clog", "cprog", "cready", "cend"):
                if self.cutter is not None:
                    self.cutter.handle(m, dialogs)
            elif m[0] == "end":
                self.joining = False                 # előbb az állapot, hogy hiba esetén is újraindítható legyen
                self.btn_cancel.configure(state="disabled")
                if m[1]:
                    msg = tr("cancelled") if m[1] == "cancelled" else tr("e_prefix", m[1][4:])
                    self.log(msg)
                    dialogs.append(("showwarning", "Lossless Video Toolkit", msg))
                else:
                    self.pb_value = 1000
                    self.pb["value"] = 1000
                    self.pct.set("100%")
                    dialogs.append(("showinfo", "Lossless Video Toolkit", tr("m_done")))
                self.refresh()

    set_app_identity()
    root = tk.Tk()
    install_app_icon(root)
    messagebox.parent = root
    app = App(root)

    def on_close():
        app.cancel.set()
        app.t_cancel.set()
        if app.cutter is not None:
            app.cutter.cancel.set()
        try:
            root.destroy()
        except tk.TclError:
            pass
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


def run_cli(argv):
    ap = argparse.ArgumentParser(description=tr("cli_desc"))
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--lang", choices=sorted(_STR))
    ap.add_argument("--no-verify", action="store_true",
                    help=('az összefűzött fájl ellenőrzésének kihagyása' if LANG == "hu" else 'skip verifying the joined file'))
    ap.add_argument("--no-fix-ps", action="store_true",
                    help=('a hiányzó SPS/PPS pótlásának kihagyása (TS/M2TS, H.264)' if LANG == "hu" else 'skip restoring missing SPS/PPS (TS/M2TS, H.264)'))
    args = ap.parse_args(argv)
    if args.lang:
        set_language(args.lang, save=False)
    infos = [analyze_into(FileInfo(f)) for f in args.files]
    ref = infos[0] if not infos[0].error else None
    bad = False
    for k, i in enumerate(infos):
        lvl, txt = compare(ref, i, infos[k - 1] if k else None)
        print("[%s] %s – %s" % (lvl.upper(), i.name, txt))
        bad |= lvl == "bad"
        sm = seam_texts(infos[k - 1], i) if k else None
        if sm:
            print("      %s: %s | %s: %s" % (tr("col_cont"), sm["cont"], tr("col_seam"), sm["qual"]))
    if bad:
        return 2
    try:
        join_files(infos, args.output, log=print, verify=not args.no_verify, fix_ps=not args.no_fix_ps)
    except MsgError as e:
        print(str(e))
        return 3
    return 0


# ---------------------------------------------------------------- vágó modul --
# A vágó külön fájlban él (lvt_cutter.py), hogy a kész részt ne kelljen mozgatni.
# Ha a fájl hiányzik, a program a vágó nélkül is működik.
try:
    import lvt_cutter
except ImportError as _e:
    if getattr(_e, "name", None) != "lvt_cutter":
        raise
    lvt_cutter = None
else:
    lvt_cutter.install(sys.modules[__name__])


if __name__ == "__main__":
    load_language()
    if len(sys.argv) > 1 and sys.argv[1] == "cut":
        if lvt_cutter is None:
            print("lvt_cutter.py not found / hiányzik")
            sys.exit(3)
        sys.exit(lvt_cutter.cut_cli(sys.argv[1:]))
    if len(sys.argv) > 1 and sys.argv[1] in ("streams", "extract", "replace-audio", "shift-audio"):
        sys.exit(au_cli(sys.argv[1:]))
    if len(sys.argv) > 1:
        sys.exit(run_cli(sys.argv[1:]))
    run_gui()
