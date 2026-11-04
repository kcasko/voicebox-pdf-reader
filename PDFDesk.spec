# Builds the app with: .venv\Scripts\pyinstaller.exe --noconfirm PDFDesk.spec
# Set PDFDESK_ONEFILE=1 to build one self-unpacking exe instead of a folder.
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

ONEFILE = os.environ.get("PDFDESK_ONEFILE") == "1"

datas = [
    ("plugins", "plugins"),
    ("assets/pdfdesk.ico", "assets"),
]
binaries = []
# Plugins load from a folder at runtime, so PyInstaller can't see what they import.
hiddenimports = collect_submodules("pdfdesk") + [
    "PySide6.QtMultimedia",
    "PySide6.QtSvg",
    "imageio_ffmpeg",
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
    "imageio_ffmpeg",
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
    excludes=["tkinter", "pytest", "matplotlib", "IPython"],
)
# Python caches from development shouldn't ship.
a.datas = [entry for entry in a.datas if "__pycache__" not in entry[0]]
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
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        exclude_binaries=True,
        name="PDFDesk",
        icon="assets/pdfdesk.ico",
        console=False,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="PDFDesk")
