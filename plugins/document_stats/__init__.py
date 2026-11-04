from PySide6.QtWidgets import QMessageBox

WORDS_PER_MINUTE = 230


def activate(api):
    def show():
        document = api.current_document()
        if document is None:
            api.status("Open a PDF first.")
            return
        words = sum(len(document.words(i)) for i in range(len(document)))
        QMessageBox.information(
            api.window,
            "Document Stats",
            f"{len(document)} pages\n{words:,} words\nAbout {max(1, round(words / WORDS_PER_MINUTE))} min to read",
        )

    api.add_action("Tools", "Document Stats", show)
