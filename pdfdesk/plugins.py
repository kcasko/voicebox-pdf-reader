"""Plugin system.

A plugin is a folder holding plugin.json and an __init__.py:

    plugin.json   {"id": "my_plugin", "name": "My Plugin", "version": "1.0", "description": "..."}
    __init__.py   def activate(api): ...
                  def deactivate(): ...     (optional)

Everything registered through the PluginApi is removed automatically when the
plugin is turned off. Plugins run with the same access as the app, so only
install ones you trust.
"""

import importlib.util
import json
import logging
import os
import re
import sys
import traceback
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QDockWidget

from .settings import APP_HOME, load_json, save_json
from .theme import theme

log = logging.getLogger(__name__)

ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
# A plugin calling sys.exit() mustn't take the whole app down.
PLUGIN_ERRORS = (Exception, SystemExit)
EVENTS = {
    "document_opened",  # (document)
    "document_closed",  # (document)
    "document_changed",  # (document, structural)
    "current_view_changed",  # (view or None)
}


@dataclass
class PluginInfo:
    id: str
    name: str
    version: str
    description: str
    folder: str
    module: object = None
    api: object = None
    error: str = ""
    active: bool = False
    invalid: bool = False


def read_manifest(path, folder):
    """Return a PluginInfo from a plugin.json. Raises ValueError or OSError if it's unusable."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("it must be a JSON object")
    plugin_id = data.get("id")
    if not isinstance(plugin_id, str) or not ID_PATTERN.fullmatch(plugin_id):
        raise ValueError('"id" must use only letters, digits, - and _')
    for key in ("name", "description"):
        if not isinstance(data.get(key, ""), str):
            raise ValueError(f'"{key}" must be text')
    version = data.get("version", "")
    if not isinstance(version, (str, int, float)):
        raise ValueError('"version" must be text')
    return PluginInfo(plugin_id, data.get("name") or plugin_id, str(version), data.get("description", ""), folder)


@dataclass
class ContextInfo:
    """What the user right-clicked on in a page."""

    view: object
    document: object
    page: int
    point: tuple
    word_index: object = None
    selection: object = None


class PluginApi:
    def __init__(self, manager, info):
        self._manager = manager
        self._window = manager.window
        self.info = info
        self.data_dir = os.path.join(manager.home, "plugin-data", info.id)
        os.makedirs(self.data_dir, exist_ok=True)
        self._settings_path = os.path.join(self.data_dir, "settings.json")
        self.settings = load_json(self._settings_path)
        self._actions = []
        self._panels = []
        self._handlers = []
        self._context_providers = []

    @property
    def window(self):
        return self._window

    def current_view(self):
        return self._window.current_view()

    def current_document(self):
        view = self.current_view()
        return view.document if view else None

    def views(self):
        return self._window.views()

    def view_for(self, document):
        for view in self.views():
            if view.document is document:
                return view
        return None

    def save_settings(self):
        save_json(self._settings_path, self.settings)

    def status(self, message, timeout=5000):
        self._window.statusBar().showMessage(message, timeout)

    def add_action(self, menu, text, callback, shortcut=None, toolbar=False, icon=None, primary=False):
        """Add a command to a top-level menu (created if needed) and optionally the toolbar.

        `icon` is a name from pdfdesk.theme.ICONS. `primary` makes the toolbar button stand out.
        """
        action = QAction(text, self._window)
        action.triggered.connect(lambda _checked=False: callback())
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        if icon:
            theme.bind(action, icon, "on_accent" if primary and toolbar else "text")
        self._window.plugin_menu(menu).addAction(action)
        if toolbar:
            bar = self._window.plugin_toolbar()
            bar.addAction(action)
            button = bar.widgetForAction(action)
            if button is not None:
                button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
                if primary:
                    button.setObjectName("primaryAction")
                    button.setCursor(Qt.PointingHandCursor)
                    button.style().unpolish(button)
                    button.style().polish(button)
        self._actions.append((menu, action, toolbar))
        return action

    def add_panel(self, title, widget, area=Qt.RightDockWidgetArea):
        dock = QDockWidget(title, self._window)
        dock.setObjectName(f"plugin-{self.info.id}-{title}")
        dock.setFeatures(QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable)
        dock.setWidget(widget)
        self._window.addDockWidget(area, dock)
        self._panels.append(dock)
        return dock

    def add_context_provider(self, provider):
        """`provider(ContextInfo)` returns a list of (label, callback) for the page right-click menu."""
        self._context_providers.append(provider)

    def on(self, event, handler):
        if event not in EVENTS:
            raise ValueError(f"Unknown event: {event}")
        self._handlers.append((event, handler))

    def _teardown(self):
        for menu, action, toolbar in self._actions:
            self._window.plugin_menu(menu).removeAction(action)
            if toolbar:
                self._window.plugin_toolbar().removeAction(action)
            action.deleteLater()
        for dock in self._panels:
            self._window.removeDockWidget(dock)
            dock.deleteLater()
        self._window.prune_plugin_ui()
        self._actions, self._panels, self._handlers, self._context_providers = [], [], [], []


class PluginManager:
    def __init__(self, window, folders, home=APP_HOME):
        self.window = window
        self.folders = folders
        self.home = home
        self.plugins = {}
        self._state_path = os.path.join(home, "plugins.json")
        self._disabled = set(load_json(self._state_path).get("disabled", []))

    def discover(self):
        for root in self.folders:
            if not os.path.isdir(root):
                continue
            for name in sorted(os.listdir(root)):
                folder = os.path.join(root, name)
                manifest = os.path.join(folder, "plugin.json")
                if not os.path.isfile(manifest):
                    continue
                try:
                    info = read_manifest(manifest, folder)
                except (OSError, ValueError) as e:
                    log.warning("Bad plugin.json in %s: %s", folder, e)
                    info = PluginInfo(name, name, "", "", folder, error=f"Bad plugin.json: {e}", invalid=True)
                self.plugins.setdefault(info.id, info)

    def load_enabled(self):
        for info in self.plugins.values():
            if info.id not in self._disabled and not info.error:
                self.activate(info.id)

    def is_enabled(self, plugin_id):
        return plugin_id not in self._disabled

    def set_enabled(self, plugin_id, enabled):
        if enabled:
            self._disabled.discard(plugin_id)
            self.activate(plugin_id)
        else:
            self._disabled.add(plugin_id)
            self.deactivate(plugin_id)
        save_json(self._state_path, {"disabled": sorted(self._disabled)})

    def _import(self, info):
        name = f"pdfdesk_plugin_{info.id}"
        spec = importlib.util.spec_from_file_location(
            name,
            os.path.join(info.folder, "__init__.py"),
            submodule_search_locations=[info.folder],
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[name]
            raise
        return module

    def activate(self, plugin_id):
        info = self.plugins[plugin_id]
        if info.invalid:
            return False
        if info.active:
            return True
        info.error = ""
        api = PluginApi(self, info)
        try:
            info.module = info.module or self._import(info)
            info.api = api
            info.module.activate(api)
            info.active = True
            return True
        except PLUGIN_ERRORS:
            info.error = traceback.format_exc()
            log.error("Plugin %s failed to start\n%s", info.id, info.error)
            api._teardown()
            info.api = None
            return False

    def deactivate(self, plugin_id):
        info = self.plugins[plugin_id]
        if not info.active:
            return
        try:
            if hasattr(info.module, "deactivate"):
                info.module.deactivate()
        except PLUGIN_ERRORS:
            info.error = traceback.format_exc()
            log.error("Plugin %s failed to stop\n%s", info.id, info.error)
        info.api._teardown()
        info.api = None
        info.active = False

    def shutdown(self):
        for plugin_id, info in self.plugins.items():
            if info.active:
                self.deactivate(plugin_id)

    def emit(self, event, *args):
        for info in self.plugins.values():
            if not info.active:
                continue
            for name, handler in list(info.api._handlers):
                if name != event:
                    continue
                try:
                    handler(*args)
                except PLUGIN_ERRORS:
                    info.error = traceback.format_exc()
                    log.error("Plugin %s failed on %s\n%s", info.id, event, info.error)
                    self.window.statusBar().showMessage(f"Plugin {info.name} hit an error.", 5000)

    def context_items(self, context):
        items = []
        for info in self.plugins.values():
            if not info.active:
                continue
            for provider in info.api._context_providers:
                try:
                    items.extend(provider(context) or [])
                except PLUGIN_ERRORS:
                    info.error = traceback.format_exc()
                    log.error("Plugin %s failed on the page menu\n%s", info.id, info.error)
        return items
