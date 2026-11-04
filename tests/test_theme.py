import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from pdfdesk.main_window import MainWindow
from pdfdesk.theme import DARK, ICONS, LIGHT, icon_pixmap, theme


@pytest.fixture
def window(qapp, tmp_path):
    win = MainWindow([], home=str(tmp_path / "home"))
    win.show()
    QApplication.processEvents()
    yield win
    for view in win.views():
        view.document.dirty = False
    win.close()
    theme.apply(qapp, "light")


@pytest.mark.parametrize("name", sorted(ICONS))
def test_every_icon_draws_something(qapp, name):
    image = icon_pixmap(name, "#000000").toImage()
    assert any(
        image.pixelColor(x, y).alpha() > 0
        for x in range(image.width())
        for y in range(image.height())
    ), name


def test_both_themes_define_the_same_colors():
    assert set(LIGHT) == set(DARK)


def test_switching_theme_is_remembered(window, tmp_path, qapp):
    window.set_theme("dark")
    assert theme.is_dark
    window.set_theme("light")
    assert not theme.is_dark
    window.set_theme("dark")
    again = MainWindow([], home=str(tmp_path / "home"))
    assert theme.is_dark
    again.close()


def test_welcome_page_shows_only_without_a_document(window, pdf_factory):
    assert window.center.currentWidget() is window.welcome
    view = window.open_path(pdf_factory([[(100, "Hello")]]))
    assert window.center.currentWidget() is window.tabs
    assert window.page_controls.isVisible()
    window.close_tab(window.tabs.indexOf(view))
    QApplication.processEvents()
    assert window.center.currentWidget() is window.welcome
    assert not window.page_controls.isVisible()


def test_welcome_page_lists_recent_files(window, pdf_factory):
    path = pdf_factory([[(100, "Hello")]])
    window.open_path(path)
    assert window.welcome.recent_box.count() == 1


def test_side_panel_opens_collapses_and_switches(window, pdf_factory):
    side = window.side
    assert not side.isVisible()
    window.open_path(pdf_factory([[(100, "Hello")]]))
    QApplication.processEvents()
    assert side.isVisible()
    assert side.is_open()
    _page, pages_button = side._panels["pages"]
    pages_button.click()
    assert not side.is_open()
    assert not pages_button.isChecked()
    assert side.width() == 48
    pages_button.click()
    assert side.is_open()
    assert side.width() >= 200
    window.act_find.trigger()
    assert side.stack.currentWidget() is side._panels["search"][0]
    assert side._panels["search"][1].isChecked()
    assert not pages_button.isChecked()
