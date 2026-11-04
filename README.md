# PDF Desk

A PDF reader and editor for Windows with a plugin system. Read Aloud, the main
plugin, reads PDFs with natural Kokoro voices that run inside the app. Nothing
else needs to be open or installed.

## Run it

Run `dist\PDFDesk\PDFDesk.exe`. It needs nothing else installed and opens in under
2 seconds, but it has to stay inside its folder. This is the version to distribute,
through the installer below.

A single-file `dist\PDFDesk.exe` is also possible. It takes about 9 seconds to open
because it unpacks 700 MB to the temp folder each time, and a crash leaves that behind.

Only one window runs per user: opening another PDF sends it to the running app.

If a plugin stops the app from working, start it with `PDFDesk.exe --no-plugins` and
turn that plugin off. Errors are logged to `%APPDATA%\PDFDesk\logs\pdfdesk.log`.

## Develop

```
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
PDFDesk.bat
```

`requirements.lock` lists the exact versions of the last build; install from it to
reproduce that build.

## Build

The voice files need to be in `plugins\read_aloud\models` first; a read from
`PDFDesk.bat` downloads them. Then:

```
.venv\Scripts\pyinstaller --noconfirm PDFDesk.spec
```

That builds the folder version. Set `PDFDESK_ONEFILE=1` first for the single exe.
Check any build with `PDFDesk.exe --self-check results.txt`. It exits with 0 if the
voices, MP3 export and OCR all work, and writes the details to the file.

`installer\pdfdesk.iss` packages the folder build with Inno Setup 6, and adds PDF Desk
to Open With for PDFs. Uninstalling asks before deleting settings and saved audio. Sign the
exe and the installer before distributing them.

`THIRD_PARTY_NOTICES.md` lists the bundled components and their licences. After changing
dependencies, check it against `scripts\list_licenses.py`.

## Limits

Read Aloud is English only. A screen reader can use the app's controls but can't read the
page itself, and PDF Desk doesn't block edits that a PDF's permissions forbid: it warns, and
a saved copy keeps the restrictions. Very large saves and prints can pause the window.

## License

PDF Desk is free software under the GNU Affero General Public License, version 3 or later: see
[LICENSE](LICENSE). Copyright (C) 2026 Keith Casko. It comes with no warranty.

Anyone who gets the app must be able to get its source code, so `scripts\make_source_zip.py`
puts it in the installer. Run it before compiling the installer, and run
`scripts\collect_licenses.py` after changing dependencies. The bundled copyleft components need
their source available too: `scripts\collect_third_party_source.py` downloads it into
`dist\third-party-source`, to attach to each GitHub release alongside the installer. Plugins run inside the app, so ones
you distribute should use a compatible licence.

## What it does

- **View:** tabs, continuous scrolling, zoom, thumbnails, outline, search, links, print
- **Mark up:** highlight, underline, strikethrough, sticky notes, text boxes, boxes, drawing, undo and redo
- **Forms:** click a text field, checkbox or dropdown to fill it in
- **Pages:** rotate, delete, extract, reorder, insert pages or PDFs, page numbers, watermarks
- **Files:** merge, split, compress, passwords, export pages as images, export text
- **Look:** light and dark themes under **View > Theme**, matching Windows by default

## Read Aloud

Press **F5** to read or pause, **F6** and **F7** for the previous and next sentence,
and **Shift+F5** to stop. Right-click a page for **Read Aloud From Here** or
**Read Selection Aloud**. Each PDF remembers its own place. If you've moved to another
page, F5 reads that page and the panel offers a way back to your place.

Read Aloud handles English only. It reads columns in order, says numbers and dates
naturally, and by default skips citations, links, footnotes and reference lists.

Voices run on the CPU and are kept in `plugins\read_aloud\models`. If that folder is
missing, they download once on the first read (about 350 MB).

Audio is saved on your computer so that sentences don't have to be generated twice. Clear
it with **Read Aloud > Clear Saved Audio**. Audio of a PDF with a password or restrictions
is deleted when the PDF closes.

## Plugins

Turn plugins on or off under **Plugins > Manage Plugins**. To add one, put a folder in
`%APPDATA%\PDFDesk\plugins` or this project's `plugins` folder:

```
my_plugin/
  plugin.json    {"id": "my_plugin", "name": "My Plugin", "version": "1.0", "description": "..."}
  __init__.py
```

```python
def activate(api):
    api.add_action("Tools", "Say Hello", lambda: api.status("Hello!"))

def deactivate():      # optional
    pass
```

`api` gives a plugin:

| Call | What it does |
| --- | --- |
| `add_action(menu, text, callback, shortcut=None, toolbar=False, icon=None, primary=False)` | Adds a menu command; `icon` is a name from `pdfdesk.theme.ICONS` |
| `add_panel(title, widget)` | Adds a dockable side panel |
| `add_context_provider(fn)` | Adds items to the page right-click menu |
| `on(event, fn)` | Listens for `document_opened`, `document_closed`, `document_changed` or `current_view_changed` |
| `current_view()`, `current_document()`, `view_for(document)` | Gets the open PDFs |
| `settings`, `save_settings()`, `data_dir` | Stores the plugin's own data |
| `status(message)` | Shows a status bar message |

On a view, `set_overlay(owner, {page: [rects]}, color)` marks text on screen without
changing the PDF. `plugins/document_stats` is a small example to copy.

Plugins run with the same access as the app, so only install ones you trust. One added to
`%APPDATA%\PDFDesk\plugins` stays off until you turn it on in **Manage Plugins**, and again
if its files change.

## Tests

```
.venv\Scripts\python -m pytest tests
.venv\Scripts\python tests\live_read_aloud.py
```

The second command checks real read-aloud, MP3 export and OCR, muted, with any
separately installed ffmpeg or Tesseract hidden from the app. It uses a separately
installed `ffprobe` to measure the exported MP3.

To see how PDFs will be read, run `tests\reading_report.py` for the generated cases, or
give it a folder of your own PDFs and a file to write the spoken text to:

```
.venv\Scripts\python tests\reading_report.py C:\my-pdfs report.txt
```
