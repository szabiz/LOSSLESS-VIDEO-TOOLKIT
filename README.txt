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
