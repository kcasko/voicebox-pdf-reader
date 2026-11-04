# Builds the app with: .venv\Scripts\pyinstaller.exe --noconfirm PDFDesk.spec
# Set PDFDESK_ONEFILE=1 to build one self-unpacking exe instead of a folder.
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ONEFILE = os.environ.get("PDFDESK_ONEFILE") == "1"

# pdfdesk/__init__.py holds only the name and version, so this imports nothing else.
sys.path.insert(0, SPECPATH)
from pdfdesk import APP_NAME, __version__

numbers = tuple(int(part) for part in __version__.split(".")) + (0,)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",
                    [
                        StringStruct("FileDescription", APP_NAME),
                        StringStruct("FileVersion", __version__),
                        StringStruct("InternalName", "PDFDesk"),
                        StringStruct("OriginalFilename", "PDFDesk.exe"),
                        StringStruct("ProductName", APP_NAME),
                        StringStruct("ProductVersion", __version__),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)

datas = [
    ("plugins", "plugins"),
    ("assets/pdfdesk.ico", "assets"),
    ("THIRD_PARTY_NOTICES.md", "."),
]
binaries = []
# Plugins load from a folder at runtime, so PyInstaller can't see what they import.
hiddenimports = collect_submodules("pdfdesk") + [
    "PySide6.QtMultimedia",
    "PySide6.QtNetwork",
    "PySide6.QtSvg",
    "lameenc",
    "numpy",
    "statistics",
    "wave",
]
for package in (
    "kokoro_onnx",
    "espeakng_loader",
    "phonemizer",
    "language_tags",
    "segments",
    "csvw",
    "onnxruntime",
):
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports

a = Analysis(
    ["run.pyw"],
    pathex=["."],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    # PyMuPDF 2 brings in tools for AI text extraction, which the app doesn't use.
    excludes=["tkinter", "pytest", "matplotlib", "IPython", "pymupdf4llm", "pymupdf_layout"],
)
# Python caches from development shouldn't ship.
a.datas = [entry for entry in a.datas if "__pycache__" not in entry[0]]
# The app uses Qt Widgets. These come along with PySide6 but nothing loads them, and
# Qt Virtual Keyboard has stricter licence terms than the rest of Qt.
UNUSED = ("qt6quick", "qt6qml", "qt6virtualkeyboard", "qtvirtualkeyboardplugin", "qtquick", "opengl32sw", "qt6pdf", "qt6webengine", "qt6charts", "qt6datavisualization", "qt63d")
a.binaries = [entry for entry in a.binaries if not os.path.basename(entry[0]).lower().startswith(UNUSED)]
a.datas = [entry for entry in a.datas if os.path.basename(entry[0]).lower() != "pyside6.qml"]
pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        name="PDFDesk",
        icon="assets/pdfdesk.ico",
        console=False,
        version=version_info,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        exclude_binaries=True,
        name="PDFDesk",
        icon="assets/pdfdesk.ico",
        console=False,
        version=version_info,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="PDFDesk")
