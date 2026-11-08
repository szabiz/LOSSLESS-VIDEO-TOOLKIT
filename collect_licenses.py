# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 szabiz
# Copyright (c) 2026 szabiz
"""Copies the license texts of the components bundled into the exe next to the built program.

Usage (called by build_exe.bat):  python collect_licenses.py dist\\LVT\\licenses

1. Everything from the `licenses` source folder (official texts: Tcl/Tk, OpenSSL, libffi, PyInstaller,
   a reference copy of the Python license and of Python's "incorporated software" notices).
2. The license file of the Python installation actually used for the build (overwrites the reference copy).
3. The license files of the installed Pillow wheel, if Pillow is installed (it is then bundled into the exe;
   the wheel's license file also contains the licenses of the libraries Pillow itself bundles).
"""
import importlib.metadata as md
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    dst = os.path.abspath(sys.argv[1])
    os.makedirs(dst, exist_ok=True)
    done = []

    src = os.path.join(HERE, "licenses")
    if os.path.isdir(src):
        for name in sorted(os.listdir(src)):
            p = os.path.join(src, name)
            if os.path.isfile(p):
                shutil.copy2(p, os.path.join(dst, name))
                done.append(name)
    else:
        print("WARNING: the 'licenses' source folder is missing")

    for cand in ("LICENSE.txt", "LICENSE"):
        p = os.path.join(sys.base_prefix, cand)
        if os.path.isfile(p):
            shutil.copy2(p, os.path.join(dst, "Python-LICENSE.txt"))
            done.append("Python-LICENSE.txt  (from this Python installation)")
            break
    else:
        print("NOTE: no LICENSE.txt in %s - the reference copy of the Python license is used." % sys.base_prefix)

    try:
        dist = md.distribution("pillow")
    except md.PackageNotFoundError:
        dist = None
        print("NOTE: Pillow is not installed, so it is not bundled; no Pillow license needed.")
    if dist is not None:
        n = 0
        for f in dist.files or []:
            low = str(f).lower()
            if os.path.basename(low).startswith(("license", "copying", "notice")) and "licenses" in low.replace("\\", "/") \
                    or os.path.basename(low) in ("license", "license.txt", "copying", "copying.txt"):
                p = str(dist.locate_file(f))
                if os.path.isfile(p):
                    name = "Pillow-LICENSE%s.txt" % ("" if n == 0 else "-%d" % (n + 1))
                    shutil.copy2(p, os.path.join(dst, name))
                    done.append("%s  (Pillow %s)" % (name, dist.version))
                    n += 1
        if n == 0:
            print("WARNING: Pillow is installed but its license file was not found - add it by hand to the licenses folder.")

    print("License files in %s:" % dst)
    for d in done:
        print("  " + d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
