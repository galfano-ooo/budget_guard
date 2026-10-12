# -*- coding: utf-8 -*-
"""First-run 'Set up BudgetGuard for <project>' dialog (the Penpot 'Setup wizard' frame):
profile card, tag keyword source, extra excluded folders -> audit_config.create_project_config()."""
from PySide6 import QtCore, QtWidgets

from . import bridge, theme, widgets


class SetupDialog(QtWidgets.QDialog):
    def __init__(self, project_name, parent=None):
        super().__init__(parent)
        self.setObjectName("SetupDialog")
        self.setWindowTitle("Set up BudgetGuard")
        self.setMinimumWidth(680)
        self.profile_id = None
        self.tag_rules = "generic"

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(theme.t("space.md"))
        title = QtWidgets.QLabel("Set up BudgetGuard for %s" % project_name)
        title.setObjectName("Brand")
        lay.addWidget(title)
        lay.addWidget(widgets.hint_label("Creates Saved/BudgetGuard/config.json for this project. "
                                         "Everything can be changed later in Settings."))

        lay.addWidget(_step("1 · Rule profile"))
        self.profile_row = QtWidgets.QHBoxLayout()
        self.profile_row.setSpacing(theme.t("space.md"))
        self._cards = {}
        profiles = bridge.list_profiles()
        for p in profiles:
            card = self._profile_card(p)
            self._cards[p["id"]] = card
            self.profile_row.addWidget(card, 1)
        self.profile_row.addWidget(self._coming_soon_card(), 1)
        lay.addLayout(self.profile_row)
        if profiles:
            self._select_profile(profiles[0]["id"])

        lay.addWidget(_step("2 · Tag keywords"))
        kw = QtWidgets.QHBoxLayout()
        kw.setSpacing(theme.t("space.sm"))
        self.kw_generic = _toggle("Generic starter keywords", True)
        self.kw_empty = _toggle("Start empty", False)
        group = QtWidgets.QButtonGroup(self)
        for b in (self.kw_generic, self.kw_empty):
            group.addButton(b)
        kw.addWidget(self.kw_generic)
        kw.addWidget(self.kw_empty)
        kw.addStretch(1)
        lay.addLayout(kw)

        lay.addWidget(_step("3 · Extra excluded folders (optional)"))
        lay.addWidget(widgets.hint_label("Comma separated path fragments, e.g. /Enums/, /Blueprints_scripts/"))
        self.excluded = QtWidgets.QLineEdit()
        lay.addWidget(self.excluded)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(widgets.button("Cancel", on_click=self.reject))
        self.create_btn = widgets.button("Create config", "primary", self.accept)
        buttons.addWidget(self.create_btn)
        buttons.addStretch(1)
        lay.addLayout(buttons)

    def _profile_card(self, p):
        card = QtWidgets.QFrame()
        card.setProperty("role", "profileCard")
        card.setCursor(QtCore.Qt.PointingHandCursor)
        col = QtWidgets.QVBoxLayout(card)
        col.setContentsMargins(14, 12, 14, 12)
        head = QtWidgets.QLabel(p["label"])
        head.setProperty("role", "optionTitle")
        col.addWidget(head)
        col.addWidget(widgets.hint_label(p["description"]))
        card.mousePressEvent = lambda _e, pid=p["id"]: self._select_profile(pid)
        return card

    def _coming_soon_card(self):
        card = QtWidgets.QFrame()
        card.setProperty("role", "profileCard")
        card.setEnabled(False)
        col = QtWidgets.QVBoxLayout(card)
        col.setContentsMargins(14, 12, 14, 12)
        head = QtWidgets.QHBoxLayout()
        head.addWidget(QtWidgets.QLabel("Desktop / PC"))
        head.addWidget(widgets.Chip("coming soon", "warning"))
        head.addStretch(1)
        col.addLayout(head)
        col.addWidget(widgets.hint_label("Nanite allowed, relaxed budgets."))
        return card

    def _select_profile(self, profile_id):
        self.profile_id = profile_id
        for pid, card in self._cards.items():
            card.setProperty("state", "active" if pid == profile_id else None)
            theme.repolish(card)

    def values(self):
        """(profile_id, tag_rules, [extra excluded fragments])"""
        extra = [s.strip() for s in self.excluded.text().split(",") if s.strip()]
        return self.profile_id, "empty" if self.kw_empty.isChecked() else "generic", extra


def _step(text):
    label = QtWidgets.QLabel(text.upper())
    label.setProperty("role", "sectionTitle")
    return label


def _toggle(text, checked):
    btn = QtWidgets.QPushButton(text)
    btn.setProperty("toggle", "true")
    btn.setCheckable(True)
    btn.setChecked(checked)
    return btn
