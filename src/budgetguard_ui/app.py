# -*- coding: utf-8 -*-
"""
QApplication bootstrap, Slate parenting, tick pump and the singleton window - the mechanism
proven live in greybox_gen's panel (never app.exec(): events are pumped from
unreal.register_slate_post_tick_callback; the window is parented to Slate with
unreal.parent_external_window_to_slate).

Reload-safe: the tick handle lives on `sys` and the open window is found by objectName
(importlib.reload resets module globals and would otherwise register a second pump / open a
second window). Geometry + current tab survive a reload the same way.
"""
import sys

import unreal
from PySide6 import QtCore, QtWidgets

from . import bridge, chrome, help_tab, settings_tab, setup_dialog, tabs, theme, widgets

WINDOW_OBJECT_NAME = "BudgetGuardWindow"
_TICK_ATTR = "_budgetguard_ui_tick_handle"
_STATE_ATTR = "_budgetguard_ui_window_state"   # {geometry, tab, scan_mode} kept across Reload

_window = None  # module-level ref: without it the window is garbage-collected and vanishes


def ensure_app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)   # our window must not tear down the editor-lifetime app
    return app


def ensure_tick_pump(app):
    if getattr(sys, _TICK_ATTR, None) is not None:
        return
    handle = unreal.register_slate_post_tick_callback(lambda dt: app.processEvents())
    setattr(sys, _TICK_ATTR, handle)
    unreal.log("[BudgetGuard] Qt tick pump registered")


class BudgetGuardWindow(QtWidgets.QWidget):
    def __init__(self, on_reload):
        super().__init__(None, QtCore.Qt.Window)
        self.setObjectName(WINDOW_OBJECT_NAME)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        self.setWindowTitle("BudgetGuard")
        self.setStyleSheet(theme.qss())
        self._on_reload = on_reload
        self._compact = False
        self._geom_full = None      # saveGeometry() blobs, one per mode, so each comes back as left
        self._geom_compact = None

        self.status = chrome.StatusLine()
        self.header = chrome.Header()
        self.header.compactClicked.connect(lambda: self.set_compact(not self._compact))
        self.nav = chrome.NavRail()
        self.nav.tabRequested.connect(self.set_tab)

        self.audit = tabs.AuditTab(self)
        self.tag = tabs.TagTab(self)
        self.fix = tabs.FixTab(self)
        self.tiers = tabs.TiersTab(self)
        self.settings = settings_tab.SettingsTab(self)
        self.help = help_tab.HelpTab(self)
        self.settings.configChanged.connect(self.refresh_project)
        self.settings.reloadRequested.connect(self._reload)
        self.nav.reloadRequested.connect(self._reload)
        self.audit.scanModeChanged.connect(lambda _m: self.fix.refresh())
        self._pages = {chrome.TAB_AUDIT: self.audit, chrome.TAB_TAG: self.tag, chrome.TAB_FIX: self.fix,
                       chrome.TAB_TIERS: self.tiers, chrome.TAB_SETTINGS: self.settings,
                       chrome.TAB_HELP: self.help}
        self.stack = QtWidgets.QStackedWidget()
        for name, _i, _t in chrome.TAB_ITEMS:
            self.stack.addWidget(widgets.scrolled(self._pages[name]) if name != chrome.TAB_SETTINGS
                                 else self._pages[name])

        self.banner = self._make_banner()

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.header)
        body = QtWidgets.QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.nav)
        main = QtWidgets.QVBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        main.addWidget(self.banner)
        main.addWidget(self.stack, 1)
        body.addLayout(main, 1)
        root.addLayout(body, 1)
        root.addWidget(self.status)

        self._restore_state()
        self.refresh_project()

    # ctx used by the tabs
    def scan_mode(self):
        return self.audit.scan_mode()

    def is_compact(self):
        return self._compact

    def set_compact(self, on):
        """Full window <-> narrow panel: smaller type/controls/margins, long hints hidden. Only
        presentation changes. Full reflows to whatever size the window has; Compact is a fixed-size panel."""
        on = bool(on)
        if on == self._compact:
            return
        leaving = self.saveGeometry()
        if on:
            self._geom_full = leaving
        else:
            self._geom_compact = leaving
        self._compact = on
        self.setStyleSheet(theme.qss(on))
        self.header.set_compact(on)
        widgets.apply_compact(self, on)
        self.layout().invalidate()
        self.layout().activate()
        # explicit minimum FIRST, or resize() is clamped up to the previous mode's layout minimum
        if on:
            # fixed size: the panel is meant to stay a small, constant-footprint widget
            self.setMinimumSize(0, 0)
            if self._geom_compact:
                self.restoreGeometry(self._geom_compact)   # keeps the position
            avail = QtWidgets.QApplication.primaryScreen().availableGeometry()
            self.setFixedSize(theme.t("size.compact.w"), min(theme.t("size.compact.h"), avail.height() - 80))
        else:
            self.setMinimumSize(0, 0)
            self.setMaximumSize(16777215, 16777215)
            self.setMinimumSize(self.minimumSizeHint())
            if not self._geom_full or not self.restoreGeometry(self._geom_full):
                avail = QtWidgets.QApplication.primaryScreen().availableGeometry()
                self.resize(min(theme.t("size.window.w"), avail.width() - 80),
                            min(theme.t("size.window.h"), avail.height() - 80))

    def _make_banner(self):
        frame = QtWidgets.QFrame()
        frame.setObjectName("Banner")
        row = QtWidgets.QHBoxLayout(frame)
        row.setContentsMargins(theme.t("space.lg"), theme.t("space.sm"), theme.t("space.sm"), theme.t("space.sm"))
        self.banner_text = QtWidgets.QLabel()
        self.banner_text.setWordWrap(True)
        row.addWidget(self.banner_text, 1)
        row.addWidget(widgets.button("Set up project…", "primary", self.run_setup))
        wrap = QtWidgets.QWidget()
        wl = QtWidgets.QVBoxLayout(wrap)
        wl.setContentsMargins(theme.t("space.lg"), theme.t("space.lg"), theme.t("space.lg"), 0)
        wl.addWidget(frame)
        wrap.hide()
        return wrap

    def refresh_project(self):
        info = bridge.project_info()
        self.header.set_project(info)
        self.status.set_project(info["name"])
        no_override = info["state"] == bridge.PROJECT_NO_OVERRIDE
        self.banner.setVisible(no_override)
        if no_override:
            self.banner_text.setText("No project config yet — using generic defaults (%s). "
                                     "Set up this project to choose its rule profile." % info["profile_label"])
        self.tag.refresh()
        self.fix.refresh()
        self.settings.refresh()

    def run_setup(self):
        dlg = setup_dialog.SetupDialog(bridge.project_info()["name"], self)
        dlg.setStyleSheet(theme.qss())
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        profile_id, tag_rules, extra = dlg.values()
        if self.status.run("Creating config", bridge.create_config, profile_id, tag_rules, extra)["ok"]:
            self.refresh_project()

    def set_tab(self, name):
        if name not in self._pages:
            return
        self.stack.setCurrentIndex([n for n, _i, _t in chrome.TAB_ITEMS].index(name))
        self.nav.set_current(name)
        if name in (chrome.TAB_TAG, chrome.TAB_FIX):
            self._pages[name].refresh()

    def current_tab(self):
        return chrome.TAB_ITEMS[self.stack.currentIndex()][0]

    def _reload(self):
        if self.status.run("Reloading scripts", bridge.reload_scripts)["ok"]:
            self._on_reload()

    def _restore_state(self):
        state = getattr(sys, _STATE_ATTR, None) or {}
        if state.get("geometry") is not None:
            self.restoreGeometry(state["geometry"])
        else:
            avail = QtWidgets.QApplication.primaryScreen().availableGeometry()
            self.resize(min(theme.t("size.window.w"), avail.width() - 80),
                        min(theme.t("size.window.h"), avail.height() - 80))
        self.audit.set_scan_mode(state.get("scan_mode", bridge.SCAN_LEVEL))
        tab = state.get("tab")
        self.set_tab(tab if tab in self._pages else chrome.TAB_AUDIT)
        self._geom_compact = state.get("geometry_compact")
        if state.get("mode") == "compact":
            self.set_compact(True)

    def closeEvent(self, event):
        global _window
        here = self.saveGeometry()
        setattr(sys, _STATE_ATTR, {
            "geometry": (self._geom_full or here) if self._compact else here,
            "geometry_compact": here if self._compact else self._geom_compact,
            "mode": "compact" if self._compact else "full",
            "tab": self.current_tab(), "scan_mode": self.scan_mode()})
        if _window is self:
            _window = None
        super().closeEvent(event)


def find_open_window(app=None):
    app = app or QtWidgets.QApplication.instance()
    if app is None:
        return None
    for w in app.topLevelWidgets():
        if w.objectName() == WINDOW_OBJECT_NAME and w.isVisible():
            return w
    return None


def show(on_reload):
    """Open the window, or raise it if it's already open."""
    global _window
    app = ensure_app()
    ensure_tick_pump(app)
    existing = find_open_window(app)
    if existing is not None:
        existing.raise_()
        existing.activateWindow()
        _window = existing
        return existing
    win = BudgetGuardWindow(on_reload)
    win.show()
    unreal.parent_external_window_to_slate(int(win.winId()))
    _window = win
    unreal.log("[BudgetGuard] panel opened")
    return win


def close():
    win = find_open_window()
    if win is not None:
        win.close()
