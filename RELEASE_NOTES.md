# PDF Desk 0.1.0 (beta)

Listen to your PDFs with natural voices that run on your own computer. There's no account, and your
documents aren't uploaded. This is an early beta for Windows 10 and 11 (64-bit), in English.

## Install

Download `PDFDesk-Setup-0.1.0.exe` and run it. It needs no administrator rights, and it doesn't
change your default PDF app.

**Windows may warn you about an unknown publisher,** because this beta isn't code-signed yet. To go
ahead, choose **More info**, then **Run anyway**.

## Try it

Open a PDF and press **F5** to read or pause. **F6** and **F7** go to the previous and next sentence.
For a scanned PDF, run **Tools > Make Searchable (OCR)** first.

## Known limits

- English only, for both the voices and OCR.
- Complex layouts, such as long tables, slides with code and tables printed from web pages, can read
  awkwardly.
- A screen reader can reach the app's controls, but can't read the PDF page itself.
- Very large saves and prints can pause the window.
- Plugins you add run with full access to your files, so they stay off until you approve them.

## Source code and licences

PDF Desk is free software under the GNU Affero General Public License, version 3 or later, with no
warranty. Its source is in this repository and in the installer.

The other files here are the source code of the copyleft components it includes. You don't need them
to use the app. `SOURCES.txt` lists each one and its hash, and `THIRD_PARTY_NOTICES.md` lists every
component and its licence.
