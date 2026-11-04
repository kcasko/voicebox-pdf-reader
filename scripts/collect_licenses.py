"""Copies the licence files of everything the app ships into licenses\\third-party.

    .venv\\Scripts\\python scripts\\collect_licenses.py

Run it after changing dependencies.
"""

import importlib.metadata
import os
import re
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "licenses", "third-party")
# Build and test tools aren't part of what's distributed.
NOT_SHIPPED = re.compile(r"^(pip|setuptools|wheel|pytest|pluggy|iniconfig|packaging|colorama|exceptiongroup|tomli|pygments|pyinstaller.*|altgraph|pefile|pywin32.ctypes|pymupdf4llm|pymupdf.layout)$", re.I)
LICENCE_FILE = re.compile(r"(licen[cs]e|copying|notice|authors)", re.I)


def main():
    shutil.rmtree(TARGET, ignore_errors=True)
    copied = missing = 0
    for distribution in sorted(importlib.metadata.distributions(), key=lambda d: d.metadata["Name"].lower()):
        name = distribution.metadata["Name"]
        if NOT_SHIPPED.match(name):
            continue
        files = [f for f in distribution.files or [] if ".dist-info" in str(f) and LICENCE_FILE.search(os.path.basename(str(f)))]
        if not files:
            missing += 1
            print(f"No licence file: {name} {distribution.version}")
            continue
        folder = os.path.join(TARGET, f"{name}-{distribution.version}")
        os.makedirs(folder, exist_ok=True)
        for file in files:
            shutil.copyfile(distribution.locate_file(file), os.path.join(folder, os.path.basename(str(file))))
            copied += 1
    print(f"Copied {copied} files. {missing} packages have no licence file; cover them in THIRD_PARTY_NOTICES.md.")


if __name__ == "__main__":
    main()
