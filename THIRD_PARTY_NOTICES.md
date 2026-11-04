# Third-party notices

PDF Desk includes the components below. Each remains under its own licence.

**Draft:** this list was prepared from package metadata and project pages, and it hasn't had a
legal review. Licence texts and source code offers still have to be added before public release.
`scripts\list_licenses.py` lists what a build's Python environment contains.

## Strong copyleft

These set the terms for the app as a whole unless they are replaced or separately licensed.

| Component | Used for | Licence | Source |
|---|---|---|---|
| PyMuPDF and MuPDF | Opening, showing and editing PDFs, and OCR | AGPL-3.0, or a commercial licence from Artifex | https://github.com/pymupdf/PyMuPDF |
| phonemizer | Turning text into speech sounds | GPL-3.0-or-later | https://github.com/bootphon/phonemizer |
| espeak-ng, through espeakng-loader | Pronunciation for the voices | GPL-3.0-or-later | https://github.com/espeak-ng/espeak-ng |

## Weak copyleft

These must stay replaceable by the user, which the folder and installer builds allow.

| Component | Used for | Licence | Source |
|---|---|---|---|
| PySide6 and Qt | Windows, controls, audio playback | LGPL-3.0 (also offered under GPL) | https://code.qt.io/cgit/pyside/pyside-setup.git |
| FFmpeg libraries included with Qt Multimedia | Audio playback | LGPL | https://ffmpeg.org |
| lameenc and LAME | MP3 export | LGPL-3.0-or-later | https://github.com/chrisstaite/lameenc |

## Permissive

| Component | Used for | Licence | Source |
|---|---|---|---|
| Kokoro-82M model weights | The voices | Apache-2.0 | https://huggingface.co/hexgrad/Kokoro-82M |
| kokoro-onnx | Running the voices | MIT | https://github.com/thewh1teagle/kokoro-onnx |
| ONNX Runtime | Running the voices | MIT | https://github.com/microsoft/onnxruntime |
| NumPy | Audio data | BSD-3-Clause | https://github.com/numpy/numpy |
| Tesseract language data (`eng.traineddata`) | OCR | Apache-2.0 | https://github.com/tesseract-ocr/tessdata |
| Python | Runtime | PSF-2.0 | https://www.python.org |

The Kokoro model card says that its training data includes CC BY datasets: Koniwa (CC BY 3.0) and
SIWIS (CC BY 4.0). The separate voice file, `voices-v1.0.bin`, states no licence of its own.

## Packaged with

PyInstaller (GPL-2.0-or-later with an exception for bundled applications) builds the app, and Inno
Setup builds the installer. Neither sets the licence of the app.
