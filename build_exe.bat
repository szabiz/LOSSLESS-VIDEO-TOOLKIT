@echo off
rem Lossless Video Toolkit - exe epitese (Windows, Python 3.9+ a python.org-rol, Tcl/Tk-val)
rem Futtatas: dupla kattintas, vagy parancssorbol:  build_exe.bat
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo Nem talalom a Python inditot ^(py^). Telepitsd a Pythont a python.org oldalrol.
    exit /b 1
)

py -3 -c "import tkinter" 2>nul
if errorlevel 1 (
    echo A tkinter hianyzik. Telepitsd ujra a Pythont a python.org-rol, es jelold be a "tcl/tk and IDLE" opciot.
    exit /b 1
)

py -3 -m pip install --upgrade -r requirements-build.txt
if errorlevel 1 exit /b 1

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
py -3 -m PyInstaller --noconfirm --clean LVT.spec
if errorlevel 1 (
    echo A build sikertelen.
    exit /b 1
)

rem a parancssori valtozat kulon almappaba kerul, hogy ne zavarja az alapfelhasznalot
move /y dist\LVT_cli dist\LVT\cli >nul
if errorlevel 1 (
    echo Nem sikerult a cli mappat athelyezni.
    exit /b 1
)

rem jogi fajlok a kesz csomag melle
copy /y LICENSE dist\LVT\ >nul
copy /y THIRD_PARTY_NOTICES.txt dist\LVT\ >nul
py -3 collect_licenses.py "dist\LVT\licenses"
if errorlevel 1 (
    echo A licencfajlok gyujtese sikertelen.
    exit /b 1
)
if exist README.md copy /y README.md dist\LVT\ >nul
xcopy /e /i /y examples dist\LVT\examples >nul

echo.
echo Gyors ellenorzes ^(a parancssori valtozat elindul-e^):
"dist\LVT\cli\LVT_cli.exe" -h
echo.
echo Kesz: dist\LVT\LVT.exe
echo Az FFmpeg-et es a VapourSynth-et NEM tartalmazza a csomag - a program elso inditasakor kell megadni az utvonalukat.
endlocal
