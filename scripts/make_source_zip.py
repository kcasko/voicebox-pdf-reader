"""Builds the source code archive that goes in the installer, as the AGPL requires.

    .venv\\Scripts\\python scripts\\make_source_zip.py

Run it before compiling the installer, from the code the build was made from. It holds every
file git tracks, plus new files that aren't ignored. The voice model isn't included: it's
listed in THIRD_PARTY_NOTICES.md, and tts.py says where it comes from.
"""

import os
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pdfdesk import __version__


def main():
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout.decode("utf-8")
    files = [name for name in listed.split("\0") if name and os.path.isfile(os.path.join(ROOT, name))]
    out = os.path.join(ROOT, "dist", f"PDFDesk-source-{__version__}.zip")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            archive.write(os.path.join(ROOT, name), f"PDFDesk-{__version__}/{name}")
    print(f"{out}: {len(files)} files, {os.path.getsize(out) // 1024} KB")


if __name__ == "__main__":
    main()
