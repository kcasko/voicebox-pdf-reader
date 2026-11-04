"""Downloads the source code of the copyleft components the app ships, and lists it in a manifest.

    .venv\\Scripts\\python scripts\\collect_third_party_source.py

The results go in dist\\third-party-source, to publish alongside each installer. The versions must
match requirements.lock, so update this list and run it again after changing dependencies. It
stops if an installed version differs from this list.
"""

import hashlib
import importlib.metadata
import json
import os
import shutil
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "dist", "third-party-source")
AGENT = {"User-Agent": "pdfdesk-source-collector"}
BLOCK = 1024 * 1024
ESPEAK_COMMIT = "4870adfa25b1a32b4361592f1be8a40337c58d6c"
LOADER_COMMIT = "146599e29b"

# Package to check, version, what it is, licence, file name, address, and the published SHA-256 if any.
COMPONENTS = [
    ("pymupdf", "2.1", "PyMuPDF", "AGPL-3.0", "pymupdf-2.1.tar.gz",
     "https://files.pythonhosted.org/packages/source/p/pymupdf/pymupdf-2.1.tar.gz",
     "9ac95f98016e83eafb8f1d786396f9c60e400d559590596e5b2df9eb6384948b"),
    (None, "1.28.6", "MuPDF, built into PyMuPDF", "AGPL-3.0", "mupdf-1.28.6-source.tar.gz",
     "https://mupdf.com/downloads/archive/mupdf-1.28.6-source.tar.gz", None),
    ("phonemizer", "3.6.0", "phonemizer", "GPL-3.0-or-later", "phonemizer-3.6.0.tar.gz",
     "https://files.pythonhosted.org/packages/source/p/phonemizer/phonemizer-3.6.0.tar.gz",
     "9808c897773a23def58d89e1a3ac3506f56e8d04ee806d3ee80214880e2c9261"),
    (None, ESPEAK_COMMIT[:10], "espeak-ng, the commit espeakng-loader 0.2.4 pins", "GPL-3.0-or-later", f"espeak-ng-{ESPEAK_COMMIT[:10]}.tar.gz",
     f"https://codeload.github.com/espeak-ng/espeak-ng/tar.gz/{ESPEAK_COMMIT}", None),
    ("espeakng-loader", "0.2.4", "espeakng-loader, including how espeak-ng is built", "MIT", "espeakng-loader-0.2.4.tar.gz",
     f"https://codeload.github.com/thewh1teagle/espeakng-loader/tar.gz/{LOADER_COMMIT}", None),
    ("lameenc", "1.9.0", "lameenc", "LGPL-3.0-or-later", "lameenc-1.9.0.tar.gz",
     "https://codeload.github.com/chrisstaite/lameenc/tar.gz/refs/tags/v1.9.0", None),
    (None, "4.0", "LAME, the version lameenc 1.9.0 builds", "LGPL", "lame-4.0.tar.gz",
     "https://downloads.sourceforge.net/project/lame/lame/4.0/lame-4.0.tar.gz",
     "3df5124d5ad3a98312ffd7ba6a9b36230e4f8a3e66d3ce0f425e336c32d216eb"),
    ("PySide6-Essentials", "6.12.0", "PySide6", "LGPL-3.0", "pyside-setup-everywhere-src-6.12.0.tar.xz",
     "https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/pyside-setup-everywhere-src-6.12.0.tar.xz", None),
    (None, "6.12.0", "Qt", "LGPL-3.0", "qt-everywhere-src-6.12.0.tar.xz",
     "https://download.qt.io/official_releases/qt/6.12/6.12.0/single/qt-everywhere-src-6.12.0.tar.xz", None),
]
NOT_COLLECTED = [
    "FFmpeg libraries in Qt Multimedia (avcodec-63, avformat-63, avutil-61, swresample-7, swscale-10): "
    "Qt builds these, and the exact FFmpeg source hasn't been identified. See https://ffmpeg.org.",
]


def download(url, path):
    digest = hashlib.sha256()
    partial = path + ".part"
    request = urllib.request.Request(url, headers=AGENT)
    with urllib.request.urlopen(request, timeout=120) as response, open(partial, "wb") as out:
        while True:
            block = response.read(BLOCK)
            if not block:
                break
            out.write(block)
            digest.update(block)
    os.replace(partial, path)
    return digest.hexdigest()


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(BLOCK), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    for package, version, label, *_ in COMPONENTS:
        if package and importlib.metadata.version(package) != version:
            sys.exit(f"{label}: this list says {version}, but {importlib.metadata.version(package)} is installed. Update the list.")
    os.makedirs(TARGET, exist_ok=True)
    rows = []
    for _package, version, label, licence, name, url, expected in COMPONENTS:
        path = os.path.join(TARGET, name)
        print(f"{name} ...", flush=True)
        actual = sha256_of(path) if os.path.exists(path) else download(url, path)
        if expected and actual != expected:
            os.remove(path)
            sys.exit(f"{name}: the download doesn't match its published hash, so it was deleted.")
        size = os.path.getsize(path)
        print(f"  {size / BLOCK:.0f} MB, hash {'matches the published one' if expected else 'recorded'}", flush=True)
        rows.append({"component": label, "version": version, "licence": licence, "file": name, "from": url, "sha256": actual, "hash_published_upstream": bool(expected), "bytes": size})
    with open(os.path.join(TARGET, "sources.json"), "w", encoding="utf-8") as out:
        json.dump({"components": rows, "not_collected": NOT_COLLECTED}, out, indent=2)
    with open(os.path.join(TARGET, "SOURCES.txt"), "w", encoding="utf-8") as out:
        out.write("Source code for the copyleft components included in PDF Desk.\n\n")
        for row in rows:
            out.write(f"{row['component']} {row['version']} ({row['licence']})\n  {row['file']}\n  from {row['from']}\n  SHA-256 {row['sha256']}\n\n")
        out.write("Not collected:\n")
        for note in NOT_COLLECTED:
            out.write(f"  {note}\n")
    print(f"Total {sum(r['bytes'] for r in rows) / BLOCK:.0f} MB in {TARGET}")


if __name__ == "__main__":
    main()
