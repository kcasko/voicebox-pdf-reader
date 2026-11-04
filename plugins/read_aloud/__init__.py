import os

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QProgressBar,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pdfdesk import tools
from pdfdesk.theme import theme

from .controller import ReadAloudController
from .export import Mp3Export
from .tts import VOICES

SPEEDS = [0.75, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.75, 2.0]
PANEL_WIDTH = 300
IDLE_TEXT = "Press play to start listening from where you left off."

_controller = None
_panel = None


def api_for_check():
    return _controller.api


def _voice_label(name):
    accent = "British" if VOICES[name].startswith("b") else "American"
    return f"{name}  ·  {accent}"


class ReadAloudPanel(QWidget):
    def __init__(self, api, controller):
        super().__init__(objectName="readAloudPanel")
        self.setAttribute(Qt.WA_StyledBackground)
        self.api = api
        self.controller = controller

        self.play_button = QToolButton(objectName="playButton", toolTip="Read or pause (F5)")
        self.play_button.setFixedSize(54, 54)
        self.play_button.setIconSize(QSize(24, 24))
        self.play_button.setCursor(Qt.PointingHandCursor)
        previous = self._transport_button("previous", "Previous sentence (F6)")
        following = self._transport_button("next", "Next sentence (F7)")
        stop = self._transport_button("stop", "Stop and save your place (Shift+F5)")
        transport = QHBoxLayout()
        transport.setSpacing(10)
        transport.addStretch()
        transport.addWidget(previous)
        transport.addWidget(self.play_button)
        transport.addWidget(following)
        transport.addWidget(stop)
        transport.addStretch()

        card = QFrame(objectName="card")
        self.page_label = QLabel("NOW READING", objectName="sectionLabel")
        self.sentence = QLabel(IDLE_TEXT, objectName="nowReading", wordWrap=True)
        self.sentence.setMinimumHeight(84)
        self.sentence.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.sentence.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.progress = QProgressBar(textVisible=False)
        self.progress.setRange(0, 1000)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 14)
        card_layout.setSpacing(8)
        card_layout.addWidget(self.page_label)
        card_layout.addWidget(self.sentence, 1)
        card_layout.addWidget(self.progress)

        self.voice = QComboBox()
        for name in VOICES:
            self.voice.addItem(_voice_label(name), name)
        self.voice.setCurrentIndex(self.voice.findData(controller.voice_name))
        self.speed = QComboBox()
        self.speed.addItems([f"{s:g}×" for s in SPEEDS])
        self.speed.setCurrentText(f"{controller.speed:g}×")
        self.follow = QCheckBox("Follow along in the page")
        self.follow.setChecked(controller.follow)
        read_page = QPushButton("Read This Page")
        export = QPushButton("Export MP3...")
        theme.bind(export, "export", "text")
        extra = QHBoxLayout()
        extra.setSpacing(8)
        extra.addWidget(read_page)
        extra.addWidget(export)
        self.status = QLabel("", objectName="panelStatus", wordWrap=True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 6, 16, 16)
        layout.setSpacing(8)
        layout.addLayout(transport)
        layout.addSpacing(8)
        layout.addWidget(card)
        layout.addSpacing(8)
        layout.addWidget(QLabel("VOICE", objectName="sectionLabel"))
        layout.addWidget(self.voice)
        layout.addSpacing(4)
        layout.addWidget(QLabel("SPEED", objectName="sectionLabel"))
        layout.addWidget(self.speed)
        layout.addSpacing(4)
        layout.addWidget(self.follow)
        layout.addSpacing(6)
        layout.addLayout(extra)
        layout.addWidget(self.status)
        layout.addStretch()

        self.play_button.clicked.connect(controller.toggle)
        previous.clicked.connect(controller.previous)
        following.clicked.connect(controller.next)
        stop.clicked.connect(self.stop)
        self.voice.currentIndexChanged.connect(lambda _i: controller.set_voice(self.voice.currentData()))
        self.speed.currentTextChanged.connect(lambda text: controller.set_speed(float(text.rstrip("×"))))
        self.follow.toggled.connect(controller.set_follow)
        read_page.clicked.connect(self._read_page)
        export.clicked.connect(self._export)
        controller.state_changed.connect(self._on_state)
        controller.message.connect(self.status.setText)
        controller.now_reading.connect(self._on_now_reading)
        self._on_state()

    def _transport_button(self, icon, tip):
        button = QToolButton(toolTip=tip)
        button.setIconSize(QSize(20, 20))
        theme.bind(button, icon, "text")
        return button

    def _on_state(self):
        reading = self.controller.state in ("playing", "waiting")
        theme.bind(self.play_button, "pause" if reading else "play", "on_accent")

    def _on_now_reading(self, text, page):
        if page < 0:
            self.page_label.setText("NOW READING")
            self.sentence.setText(IDLE_TEXT)
            self.progress.setValue(0)
            return
        document = self.controller.document
        total = len(document) if document else 1
        self.page_label.setText(f"PAGE {page + 1} OF {total}")
        self.sentence.setText(text)
        self.progress.setValue(round(1000 * (page + 1) / max(1, total)))

    def stop(self):
        self.controller._save_position()
        self.controller.stop()
        self.status.setText("Stopped. Your place in this PDF is saved.")

    def _read_page(self):
        view = self.api.current_view()
        if view:
            self.controller.read_from(view.document, view.current_page, 0)
        else:
            self.status.setText("Open a PDF first.")

    def _export(self):
        view = self.api.current_view()
        if not view:
            self.status.setText("Open a PDF first.")
            return
        document = view.document
        text, ok = QInputDialog.getText(
            self, "Export MP3", "Pages to export:", text=f"1-{len(document)}"
        )
        if not ok:
            return
        try:
            pages = [page for group in tools.parse_ranges(text, len(document)) for page in group]
        except ValueError as e:
            self.status.setText(str(e))
            return
        stem = os.path.splitext(document.title)[0]
        out, _ = QFileDialog.getSaveFileName(self, "Save MP3", f"{stem}.mp3", "MP3 audio (*.mp3)")
        if not out:
            return
        controller = self.controller
        Mp3Export(
            self.api,
            document,
            min(pages),
            max(pages),
            VOICES[controller.voice_name],
            controller.speed,
            out,
            controller.cache_dir,
        ).start()


def activate(api):
    global _controller, _panel
    _controller = ReadAloudController(api)
    _panel = ReadAloudPanel(api, _controller)
    dock = api.add_panel("Read Aloud", _panel)
    dock.setMinimumWidth(PANEL_WIDTH)
    dock.hide()

    def read_or_pause():
        dock.show()
        _controller.toggle()

    api.add_action("Read Aloud", "Read Aloud", read_or_pause, shortcut="F5", toolbar=True, icon="volume", primary=True)
    api.add_action("Read Aloud", "Stop", _panel.stop, shortcut="Shift+F5")
    api.add_action("Read Aloud", "Previous Sentence", _controller.previous, shortcut="F6")
    api.add_action("Read Aloud", "Next Sentence", _controller.next, shortcut="F7")
    api.add_action("Read Aloud", "Show Panel", dock.show)
    api.on("document_changed", _controller.on_document_changed)
    api.on("document_closed", _controller.on_document_closed)

    def context_items(context):
        items = _context_items(context)
        return [(label, lambda c=callback: (dock.show(), c())) for label, callback in items]

    api.add_context_provider(context_items)


def _context_items(context):
    items = []
    if context.selection:
        items.append(("Read Selection Aloud", lambda: _controller.read_selection(context.view)))
    if context.word_index is not None:
        items.append(
            ("Read Aloud From Here", lambda: _controller.read_from(context.document, context.page, context.word_index))
        )
    return items


def deactivate():
    global _controller, _panel
    if _controller:
        _controller._save_position()
        _controller.shutdown()
    _controller = None
    _panel = None
