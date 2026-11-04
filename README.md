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
python -m venv .venv
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
to Open With for PDFs. Sign the exe and the installer before distributing them.

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
**Read Selection Aloud**. Each PDF remembers its own place.

Voices run on the CPU and are kept in `plugins\read_aloud\models`. If that folder is
missing, they download once on the first read (about 350 MB).

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

Plugins run with the same access as the app, so only install ones you trust.

## Tests

```
.venv\Scripts\python -m pytest tests
.venv\Scripts\python tests\live_read_aloud.py
```

The second command checks real read-aloud, MP3 export and OCR, muted, with any
separately installed ffmpeg or Tesseract hidden from the app.
