# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 szabiz <szabiz@yahoo.com>
# Copyright (c) 2026 szabiz <szabiz@yahoo.com>
"""Külső ellenőrzés (ffmpeg/ffprobe) és ellenőrzött javítás tesztjei.
Futtatás: python -m unittest -v test_lvt_external.py
Az ffmpeg és az ffprobe hiányában a tesztek kihagyódnak."""
import os
import shutil
import subprocess
import tempfile
import threading
import unittest

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # a programmodulok a szülőmappában vannak
import lvt_analyzer as la

FF = shutil.which("ffmpeg")
FP = shutil.which("ffprobe")


class _Core:
    EXTERNAL_OK = True


class _Off:
    EXTERNAL_OK = False


def _make_mp4(path):
    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=duration=3:size=320x240:rate=25", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-g", "12", path], check=True)


def _corrupt(src, dst):
    import random
    with open(src, "rb") as f:
        data = bytearray(f.read())
    random.seed(1)
    for _ in range(40):
        p = random.randrange(len(data) // 3, len(data) * 2 // 3)
        data[p] = random.randrange(256)
    with open(dst, "wb") as f:
        f.write(bytes(data))


def _ext_section(rep):
    for s in rep.sections:
        if s.title.startswith(("External check (ffmpeg", "Külső ellenőrzés (ffmpeg")):
            return s
    return None


@unittest.skipUnless(FF and FP, "ffmpeg/ffprobe nincs a gépen")
class ExternalStageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="lvt_ext_")
        cls.ok = os.path.join(cls.dir, "ok.mp4")
        cls.bad = os.path.join(cls.dir, "bad.mp4")
        _make_mp4(cls.ok)
        _corrupt(cls.ok, cls.bad)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_clean_file_has_no_decode_errors(self):
        rep = la.analyze_file(self.ok, _Core())
        sec = _ext_section(rep)
        self.assertIsNotNone(sec, "a külső szakasz hiányzik")
        vals = {k: v for k, v, _ in sec.rows}
        self.assertEqual(vals.get("Decoding errors"), "0")
        self.assertEqual(rep.verdict, "OK", rep.to_text())

    def test_corrupt_file_decode_errors_are_error(self):
        rep = la.analyze_file(self.bad, _Core())
        self.assertIsNotNone(_ext_section(rep))
        self.assertEqual(rep.verdict, "E")
        self.assertTrue(any(l == "E" for l, _ in rep.problems))

    def test_disabled_external_has_no_section(self):
        rep = la.analyze_file(self.bad, _Off())
        self.assertIsNone(_ext_section(rep))
        self.assertTrue(any("nincs ffmpeg" in n or "no ffmpeg" in n for n in rep.notes))

    def test_cancel_stops_decoding(self):
        ev = threading.Event()
        ev.set()
        with self.assertRaises(la.AnalyzeCancelled):
            la.analyze_file(self.bad, _Core(), None, ev)

    def test_verified_repair_gives_clean_output(self):
        dst = os.path.join(self.dir, "bad_javitott.mkv")
        log = la.repair_verified(self.bad, dst, FF, FP)
        self.assertTrue(log["clean"], log)
        self.assertEqual(log["method"], "reencode")
        self.assertTrue(os.path.isfile(dst))
        self.assertEqual(la._ext_verify(dst, FF, FP)["dec"], 0)

    def test_repair_of_clean_file_is_lossless_remux(self):
        dst = os.path.join(self.dir, "ok_javitott.mp4")
        log = la.repair_verified(self.ok, dst, FF, FP)
        self.assertTrue(log["clean"])
        self.assertEqual(log["method"], "remux")
        self.assertFalse([d for d in os.listdir(self.dir) if d.startswith("lvt_fix_")])


if __name__ == "__main__":
    unittest.main()
