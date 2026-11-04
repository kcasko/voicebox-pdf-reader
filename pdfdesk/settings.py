import ctypes
import json
import os
import tempfile

APP_HOME = os.environ.get("PDFDESK_HOME") or os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")), "PDFDesk"
)


DRIVE_REMOTE = 4
THEME_MODES = {"system", "light", "dark"}


def may_exist(path):
    """os.path.exists, except that it doesn't ask a network drive, which can take over a minute if it's offline."""
    if path.startswith(("\\\\", "//")):
        return True
    drive = os.path.splitdrive(path)[0]
    if drive and hasattr(ctypes, "windll") and ctypes.windll.kernel32.GetDriveTypeW(drive + "\\") == DRIVE_REMOTE:
        return True
    return os.path.exists(path)


def clean_settings(data):
    """Drop values of the wrong type, so a damaged settings file can't stop the app from starting."""
    if not (isinstance(data.get("recent"), list) and all(isinstance(p, str) for p in data["recent"])):
        data.pop("recent", None)
    if not isinstance(data.get("geometry"), str):
        data.pop("geometry", None)
    if data.get("theme") not in THEME_MODES:
        data.pop("theme", None)
    if not isinstance(data.get("views"), dict):
        data.pop("views", None)
    return data


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_json(path, data):
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
