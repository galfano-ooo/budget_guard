# -*- coding: utf-8 -*-
"""Window chrome: NavRail (icon-only), Header (brand + project chip), StatusLine."""
from PySide6 import QtCore, QtWidgets

from . import bridge, theme, widgets

TAB_AUDIT, TAB_TAG, TAB_FIX, TAB_TIERS, TAB_SETTINGS, TAB_HELP = (
    "Audit", "Tag", "Fix", "Tiers", "Settings", "Help")
TAB_ITEMS = (  # (name, icon file, tooltip)
    (TAB_AUDIT, "audit", "Audit"),
    (TAB_TAG, "tag", "Tag content"),
    (TAB_FIX, "fix", "Fix"),
    (TAB_TIERS, "tiers", "Tiers"),
    (TAB_SETTINGS, "settings", "Settings"),
    (TAB_HELP, "help", "Help / tutorial"),
)


class NavRail(QtWidgets.QFrame):
    tabRequested = QtCore.Signal(str)
    reloadRequested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NavRail")
        self.setFixedWidth(theme.t("size.nav.w"))
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, theme.t("space.md"), 6, theme.t("space.md"))
        lay.setSpacing(theme.t("space.sm"))
        self._buttons = {}
        group = QtWidgets.QButtonGroup(self)
        group.setExclusive(True)
        for name, icon, tip in TAB_ITEMS:
            btn = QtWidgets.QPushButton()
            btn.setProperty("role", "navBtn")
            btn.setCheckable(True)
            btn.setIcon(widgets.make_icon(icon))
            btn.setIconSize(QtCore.QSize(20, 20))
            btn.setToolTip(tip)
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, n=name: self.tabRequested.emit(n))
            group.addButton(btn)
            lay.addWidget(btn)
            self._buttons[name] = btn
        lay.addStretch(1)
        # Action button (not a tab): not checkable / not in the exclusive group.
        reload_btn = QtWidgets.QPushButton()
        reload_btn.setProperty("role", "navBtn")
        reload_btn.setIcon(widgets.make_icon("reload"))
        reload_btn.setIconSize(QtCore.QSize(20, 20))
        reload_btn.setToolTip("Reload scripts")
        reload_btn.setCursor(QtCore.Qt.PointingHandCursor)
        reload_btn.clicked.connect(lambda _c=False: self.reloadRequested.emit())
        lay.addWidget(reload_btn)

    def set_current(self, name):
        self._buttons[name].setChecked(True)


class Header(QtWidgets.QFrame):
    """Brand, project chip(s) and the Compact / Full toggle."""
    compactClicked = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Header")
        self.setFixedHeight(theme.t("size.header.h"))
        self._compact = False
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(theme.t("space.lg"), 0, theme.t("space.lg"), 0)
        lay.setSpacing(theme.t("space.md"))
        brand = QtWidgets.QLabel("BudgetGuard")
        brand.setObjectName("Brand")
        self.project_chip = widgets.Chip()
        self.profile_chip = widgets.Chip(tone="neutral")
        lay.addWidget(brand)
        lay.addWidget(self.project_chip)
        lay.addWidget(self.profile_chip)
        lay.addStretch(1)
        self.compact_btn = widgets.button("Compact", on_click=self.compactClicked.emit)
        self.compact_btn.setToolTip("Shrink the window to a narrow panel")
        lay.addWidget(self.compact_btn)
        self._has_profile = False

    def set_compact(self, on):
        """Narrow panel: the profile chip goes (the project chip keeps the state)."""
        self._compact = bool(on)
        self.compact_btn.setText("Full" if on else "Compact")
        self.compact_btn.setToolTip("Back to the full window" if on else "Shrink the window to a narrow panel")
        self.profile_chip.setVisible(self._has_profile and not on)

    def set_project(self, info):
        state, name = info["state"], info["name"]
        text, tone = {
            bridge.PROJECT_OK: ("Project: %s" % name, "success"),
            bridge.PROJECT_NO_OVERRIDE: ("%s · no override" % name, "info"),
            bridge.PROJECT_INVALID: ("%s · config invalid" % name, "error"),
            bridge.PROJECT_NOT_FOUND: ("Project not found", "warning"),
        }[state]
        self.project_chip.setText(text)
        self.project_chip.setToolTip(info.get("error", ""))
        widgets.set_tone(self.project_chip, tone)
        self.profile_chip.setText(info["profile_label"])
        self._has_profile = bool(info["profile_label"])
        self.profile_chip.setVisible(self._has_profile and not self._compact)


class StatusLine(QtWidgets.QFrame):
    """States: idle (grey dot), busy (amber), ok (green), error (red background)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("StatusLine")
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(theme.t("space.lg"), 6, theme.t("space.lg"), 6)
        lay.setSpacing(theme.t("space.sm"))
        self.dot = QtWidgets.QLabel("●")
        self.dot.setObjectName("StatusDot")
        self.text = QtWidgets.QLabel()
        self.text.setObjectName("StatusText")
        self.text.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.text.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        lay.addWidget(self.dot)
        lay.addWidget(self.text, 1)
        # project badge, right-aligned: folder icon + project name
        self.project_icon = QtWidgets.QLabel()
        self.project_icon.setPixmap(widgets.make_icon("project", 16).pixmap(16, 16))
        self.project_name = QtWidgets.QLabel()
        self.project_name.setObjectName("StatusProject")
        lay.addWidget(self.project_icon)
        lay.addWidget(self.project_name)
        self.set_state("idle", "Ready")

    def set_project(self, name):
        self.project_name.setText(name)
        self.project_icon.setToolTip("Project: %s" % name)
        self.project_name.setToolTip("Project: %s" % name)

    def set_state(self, state, msg):
        self.setProperty("state", state)
        self.text.setText(msg)
        self.text.setToolTip(msg)
        theme.repolish(self)
        for child in (self.dot, self.text):
            theme.repolish(child)

    def run(self, label, fn, *args, **kwargs):
        """Run a blocking bridge call (the Editor is frozen until it returns): busy state
        painted first, wait cursor, then the result dict's msg as ok / error. Returns the dict."""
        self.set_state("busy", label + " …")
        self.repaint()
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            result = fn(*args, **kwargs)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.set_state("ok" if result.get("ok") else "error", result.get("msg", ""))
        return result
