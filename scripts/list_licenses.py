"""Lists every installed package and its stated licence, flagging the ones to check.

    .venv\\Scripts\\python scripts\\list_licenses.py

Run it after changing dependencies, and update THIRD_PARTY_NOTICES.md to match.
"""

import importlib.metadata
import re

COPYLEFT = re.compile(r"\b(A?GPL|LGPL|GNU|MPL|EPL|CC-BY-SA)\b", re.I)


def licence_of(distribution):
    metadata = distribution.metadata
    stated = metadata.get("License-Expression") or (metadata.get("License") or "").split("\n")[0]
    classifiers = [c.split("::")[-1].strip() for c in metadata.get_all("Classifier", []) if c.startswith("License")]
    return "; ".join(part for part in [stated[:70], *classifiers] if part) or "NOT STATED"


def main():
    rows = sorted(((d.metadata["Name"], d.version, licence_of(d)) for d in importlib.metadata.distributions()), key=lambda r: r[0].lower())
    for name, version, licence in rows:
        flag = "CHECK" if licence == "NOT STATED" or COPYLEFT.search(licence) else "     "
        print(f"{flag}  {name} {version}: {licence}")


if __name__ == "__main__":
    main()
