# -*- mode: python ; coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 szabiz <szabiz@yahoo.com>
#
# Lossless Video Toolkit - PyInstaller build (onedir, két különálló mappa):
#   dist\LVT      - LVT.exe: grafikus felület (nincs konzolablak)  <- az alapfelhasználónak
#   dist\LVT_cli  - LVT_cli.exe: ugyanaz konzollal (parancssor: LVT_cli.exe -o ki.m2ts a.mts b.mts)
# A build_exe.bat a második mappát a végén a dist\LVT\cli helyre mozgatja. Mindkettőnek saját
# _internal mappája van (az exe csak a saját mappája melletti _internal-t keresi).
# Az FFmpeg és a VapourSynth NINCS a csomagban: a felhasználó telepíti őket.
import os

HERE = os.path.abspath(SPECPATH)
# az exe fájl ikonja (az ablakok / tálca ikonját a program futás közben maga rajzolja, ugyanezt a motívumot)
ICON = os.path.join(HERE, 'app.ico')

a = Analysis(
    [os.path.join(HERE, 'mts_joiner.py')],
    pathex=[HERE],
    binaries=[],
    # a metaadat-JSON-ok: az efekt_vs.py a __file__ melletti vs_filters mappából olvassa
    datas=[(os.path.join(HERE, 'vs_filters'), 'vs_filters')],
    # a modulokat kivétel nélkül egyszerű import-utasítások hívják (try / függvényen belül is),
    # de a biztonság kedvéért kifejezetten felsoroljuk őket
    hiddenimports=['lvt_cutter', 'lvt_mp4', 'lvt_smartcut', 'lvt_iframe', 'lvt_ffmpeg', 'lvt_analyzer',
                   'efekt', 'efekt_vs', 'vs_bridge', 'vs_code', 'vs_env', 'vs_meta', 'vs_pyscan', 'vs_render'],
    hookspath=[],
    runtime_hooks=[],
    excludes=['numpy', 'scipy', 'pandas', 'matplotlib', 'IPython', 'pytest', 'setuptools', 'pip'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe_gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='LVT',
              debug=False, strip=False, upx=False, console=False, icon=ICON)
exe_cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name='LVT_cli',
              debug=False, strip=False, upx=False, console=True, icon=ICON)

coll_gui = COLLECT(exe_gui, a.binaries, a.datas, strip=False, upx=False, name='LVT')
coll_cli = COLLECT(exe_cli, a.binaries, a.datas, strip=False, upx=False, name='LVT_cli')
