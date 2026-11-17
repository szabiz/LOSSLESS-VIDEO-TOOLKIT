LOSSLESS VIDEO TOOLKIT (LVT)
============================

A video toolkit for Windows that works on your recordings WITHOUT QUALITY
LOSS: join, cut, extract, analyze and (optionally) convert video files.
It started as a joiner for AVCHD (.MTS / .M2TS) camera files and grew into a
small editing suite built around lossless stream copying, with FFmpeg as an
optional extra.

License: MIT (see LICENSE).
Third-party notices: THIRD_PARTY_NOTICES.txt and the "licenses" folder.


CONTENTS
--------
 1. Quick start
 2. Features at a glance
 3. Joiner and extractor
 4. Cutter and Smart Cut
 5. FFmpeg window
      5.1 Editor
      5.2 Saving cuts
      5.3 Convert / exact cut
      5.4 Image effects and VapourSynth
      5.5 Video analyzer
      5.6 Setup
 6. Keyboard shortcuts
 7. External programs (NOT included)
 8. Package contents
 9. Disclaimer


1. QUICK START
--------------
 1. Extract the WHOLE folder. The "_internal" folder next to LVT.exe is
    required; the program does not start without it.
 2. Run LVT.exe.

The interface starts in English. The language can be switched in the
program, and the choice is remembered.

The joiner, extractor and cutter work right away. The FFmpeg-based features
(Smart Cut, the FFmpeg window, image effects) need your own FFmpeg: see
5.6 Setup and 7. External programs.


2. FEATURES AT A GLANCE
-----------------------
 Joiner            Joins video and audio files losslessly, no
                   re-encoding.
 Extractor         Extracts audio or video streams, replaces audio,
                   verifies the result.
 Cutter            Lossless cutting on keyframes.
 Smart Cut         Frame-accurate cuts: re-encodes only the cut edges and
                   copies everything between. (Needs FFmpeg.)
 Editor            Live preview, waveform timeline, frame-by-frame
                   stepping, A/B markers, cut list with undo/redo.
                   (Needs FFmpeg.)
 Convert           Re-encoding with presets, one-pass cut-and-join,
                   container and codec choice. (Needs FFmpeg.)
 Image effects     Resize, crop, rotate, deinterlace, colour, sharpen,
                   denoise, VapourSynth filters, custom -vf. (Needs FFmpeg.)
 Analyzer          Checks the structure and timing of a video file.
 Command line      Joiner without the GUI (cli\LVT_cli.exe).

Supported formats for joining: AVCHD (.MTS / .M2TS), MP4 / MOV,
MKV / WebM, MPEG-PS and DVD VOB, and audio files (.m4a / .m4b, .aac,
.mp3, .mp2, .ac3, .eac3, .opus / .ogg, .mka).


3. JOINER AND EXTRACTOR
-----------------------
 - Lossless joining of AVCHD (.MTS / .M2TS), MP4 / MOV, MKV / WebM,
   MPEG-PS and DVD VOB files. Nothing is re-encoded, so there is no quality
   loss and the job is as fast as the disk allows.
 - Lossless joining of audio files: .m4a / .m4b (AAC, ALAC and others in
   MP4), raw .aac (ADTS), .mp3, .mp2, .ac3, .eac3, .opus / .ogg (Ogg Opus)
   and .mka. The audio frames are copied byte for byte. All files must have
   the same codec and parameters (sample rate, channels, profile);
   otherwise the file is rejected. Tags (ID3, APE) and the MP3 VBR header
   frame (Xing / Info) are not carried over, because their length and seek
   data would be wrong for the joined file. For MP3, the first 1-2 frames
   after a seam may be audibly damaged because of the bit reservoir.
   FLAC and WAV are not supported.
 - Extract audio and video streams into separate files.
 - Replace the audio of a video.
 - Verify the result after joining.

Command line (in the exe build: cli\LVT_cli.exe):

    LVT_cli.exe -o out.m2ts a.mts b.mts
    LVT_cli.exe -o out.mp3 a.mp3 b.mp3


4. CUTTER AND SMART CUT
-----------------------
 - Cutter: lossless cutting. Without re-encoding, a cut can only start on a
   keyframe (I-frame), so the cut point snaps to the nearest one.

 - Smart Cut: cuts at any frame. Only the short pieces at the cut edges are
   re-encoded; the part between safe keyframes is copied untouched.
   Requires FFmpeg. It is experimental: the result is not guaranteed to
   match the original stream parameters exactly.

Smart Cut works on H.264 / AVC, HEVC / H.265, VP9 and AV1 video in
MPEG-TS / MTS / M2TS, MKV and MP4 / M4V / MOV files, keeps the source
container and codecs, and encodes the audio once per output file. If a
selection contains no copyable middle part, the whole selection is
re-encoded.


5. FFMPEG WINDOW
----------------
Optional. It uses your own FFmpeg and has these tabs: Editor,
Convert / exact cut, Video analyzer and Setup.


5.1 Editor
~~~~~~~~~~
An Avidemux-style editor for marking what to keep or cut out.

 - Live picture and a timeline with waveform. Zoom with the mouse wheel,
   pan with the right mouse button, adjustable waveform gain. The waveform
   can be hidden to give the picture more room.
 - Frame-accurate stepping (one frame, one second, ten seconds) and direct
   time entry.
 - A / B markers for a range, plus a cut-out list. Overlapping ranges are
   merged; ranges can be reordered, deleted and sent to other tabs.
 - Undo / redo for markers and the cut list.
 - Playback options: loop A-B, mute (works during playback), skip cuts or
   play cuts only, volume, and an audio/video offset with a sync test to
   calibrate your computer's audio delay.
 - I-frame markers: show the keyframes on the timeline and jump to the
   previous / next one. The file info window (I button) shows the GOP
   statistics.

The preview shows the video as it is, with no automatic deinterlacing.


5.2 Saving cuts
~~~~~~~~~~~~~~~
From the Editor you can save:

 - the cut-outs as separate files,
 - the cut-outs joined into one file,
 - the whole file without the cut-outs.

On saving you choose the method:

 Smart export   Keeps the source container and codecs, copies the middle
                parts, re-encodes only the cut edges. Cuts need not be on
                I-frames.
 I-frame export Pure stream copy: cuts on keyframes, video is not
                re-encoded. The classic fast path.

To re-encode instead, send the selection to the Convert tab.


5.3 Convert / exact cut
~~~~~~~~~~~~~~~~~~~~~~~
Re-encoding and exact cutting with a visible, checkable FFmpeg command.

 - Segment list with order control. With several items you can join them
   into one file (cut and joined in a single FFmpeg pass, so picture and
   sound stay in sync at the joins) or write separate files
   (name_001, name_002, ...).
 - Presets: built-in ones (fast copy, H.264, H.265, exact cut, interlaced
   to progressive, audio only, video without audio) and your own saved
   presets (marked with a star).
 - Fields filled from the source: choosing a file fills the video and audio
   settings from its own data (codec, bitrate, size, fps, pixel format,
   channels, sample rate, container). Unknown values stay empty and can be
   picked by hand.
 - Container, extension and codec lists come from your FFmpeg build;
   incompatible codecs are filtered out, and a searchable codec picker
   lists everything the build can encode.
 - Quality (CRF / CQ or bitrate), preset speed, GOP length, scaling, fps,
   pixel format, hardware decoding, deinterlace, volume, custom -vf / -af
   and extra arguments.
 - "Show command" before you start. "Cancel" asks whether to keep the part
   encoded so far (with audio) or discard it.
 - A built-in help (H button) explains every field.


5.4 Image effects and VapourSynth
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Opened from the Editor ("Selected to Image effects"), in a separate window
with a live preview:

 - resize, crop, rotate, deinterlace,
 - light / shadow / colour, sharpness, noise reduction,
 - VapourSynth filters (optional),
 - a custom -vf filter chain.

Settings are kept per segment. The "Output" button sends the segments, with
their filter chains, to the Convert tab. VapourSynth segments stream
straight from vspipe into FFmpeg: no intermediate file, one single encode.


5.5 Video analyzer
~~~~~~~~~~~~~~~~~~
Checks the structure and timing of a video file. It works on the file
currently open in the FFmpeg window.


5.6 Setup
~~~~~~~~~
 1. Open the Setup tab and point it to your ffmpeg, ffprobe and ffplay
    (or use "Find in folder / PATH").
 2. Press "Test and save", then tick "Module enabled".

Until you do this, the module is completely inactive and starts no external
program. The first time the window opens, a licence notice is shown; the
confirmation is stored in a marker file next to the program
(lvt_ffmpeg_licenc.txt). You can read the notice again on the Setup tab.


6. KEYBOARD SHORTCUTS (EDITOR TAB)
----------------------------------
 Space                         Play / pause
 Left / Right                  Step one frame
 Shift + Left / Right          Step one second
 Ctrl + Left / Right           Step ten seconds
 Home / End                    Go to start / end
 PageUp / PageDown             Previous / next I-frame
 I / O                         Set marker A (in) / B (out)
 P                             Cut out the selected A-B range
 Ctrl + Z / Ctrl + Y           Undo / redo
 Ctrl + O                      Open a file
 Ctrl + A                      Select all segments in a list
 Delete / Backspace            Remove the selected segments
 Enter                         Load the selected segment into A-B
 Esc                           Clear the selection
 Wheel on the picture          Step by frame (Shift = seconds)
 Wheel on the timeline         Zoom (Shift = pan)
 Right mouse drag, timeline    Pan the timeline


7. EXTERNAL PROGRAMS (NOT INCLUDED)
-----------------------------------
 FFmpeg, ffprobe, ffplay
     Used for: Smart Cut, the FFmpeg window, image effects, the
     analyzer's external check.
     Get it:   https://ffmpeg.org/

 VapourSynth (vspipe) + plugins
     Used for: VapourSynth filters only (optional).
     Get it:   https://www.vapoursynth.com/

The joiner and the extractor work without them. Set the paths in the FFmpeg
window and on the VapourSynth tab.

FFmpeg runs as a separate program under its own licence (LGPL or GPL,
depending on the build); LVT does not include, bundle or download it.
FFmpeg and VapourSynth (and its plugins) are covered by their own licences;
complying with them is the responsibility of the person who installs them.


8. PACKAGE CONTENTS
-------------------
 LVT.exe                  The graphical program.
 _internal\               Required runtime files (Python, Tcl/Tk, Pillow
                          and others). Do not delete or move.
 cli\LVT_cli.exe          Command-line version (only if included).
 cli\_internal\           Runtime files of the command-line version.
 LICENSE                  MIT licence of LVT.
 THIRD_PARTY_NOTICES.txt  Licences of the bundled third-party components.

Source code and the latest version: see the project page (GitHub).


9. DISCLAIMER
-------------
The program is provided "AS IS", without warranty of any kind. Use it only
with recordings you have the right to use. Always keep a backup of
important recordings.

-------------------------------------------------------------------------------

Full license texts of the components bundled with the Lossless Video Toolkit exe.
(The program's own license is the LICENSE file in the parent folder.)

Python-LICENSE.txt                     Python Software Foundation License (CPython runtime and standard library)
Python-incorporated-software-licenses  Licenses of software incorporated into Python (expat, zlib, bzip2, libmpdec, ...)
Tcl-LICENSE.txt, Tk-LICENSE.txt        Tcl/Tk (used by tkinter, the graphical interface)
OpenSSL-LICENSE.txt                    OpenSSL 3 (Apache License 2.0) - bundled by Python's hashlib support
libffi-LICENSE.txt                     libffi (MIT) - bundled by Python's ctypes support
PyInstaller-COPYING.txt                PyInstaller (GPL-2.0 with the bootloader exception that allows
                                       bundling programs under any license)
Pillow-LICENSE.txt                     Pillow (HPND) and the libraries bundled in the Pillow wheel -
                                       present only if Pillow was installed when the exe was built

Sources of the reference texts: the official repositories of CPython 3.12, Tcl, Tk, OpenSSL, libffi and
PyInstaller. build_exe.bat replaces the Python and Pillow files with the ones that belong to the exact
installation used for the build.
