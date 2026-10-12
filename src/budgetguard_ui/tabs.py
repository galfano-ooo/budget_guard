# -*- coding: utf-8 -*-
"""The Audit / Tag / Fix / Tiers tabs. Each takes a `ctx` with .status (StatusLine) and
.scan_mode() (the header's scan target); all backend access goes through bridge."""
from PySide6 import QtCore, QtWidgets

from . import bridge, theme, widgets

CATEGORIES = ("Textures", "Meshes", "Materials")


class AuditTab(QtWidgets.QWidget):
    """Owns the scan-target dropdown; Fix reads it through ctx.scan_mode()."""
    scanModeChanged = QtCore.Signal(str)

    def scan_mode(self):
        return self.scan_combo.currentData()

    def set_scan_mode(self, mode):
        i = self.scan_combo.findData(mode)
        if i >= 0:
            self.scan_combo.setCurrentIndex(i)

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        lay = widgets.page_layout(self)

        tiles = QtWidgets.QHBoxLayout()
        tiles.setSpacing(theme.t("space.md"))
        self.tiles = {}
        for key, tone in (("FAIL", "error"), ("WARN", "warning"), ("INFO", None), ("OK", "success")):
            self.tiles[key] = widgets.StatTile(key, tone)
            tiles.addWidget(self.tiles[key], 1)
        lay.addLayout(tiles)

        run, run_lay = widgets.make_section("Run")
        run_lay.addWidget(_field_label("Scan target"))
        self.scan_combo = QtWidgets.QComboBox()
        self.scan_combo.setMinimumWidth(80)
        self.scan_combo.setMaximumWidth(320)
        for mode, label in bridge.SCAN_MODES:
            self.scan_combo.addItem(label, mode)
        self.scan_combo.currentIndexChanged.connect(lambda _i: self.scanModeChanged.emit(self.scan_mode()))
        run_lay.addWidget(self.scan_combo)
        self.run_btn = widgets.button("Run audit", "primary", self._run)
        run_lay.addLayout(widgets.button_row(
            self.run_btn,
            widgets.button("Audit Results", on_click=lambda: ctx.status.run("Audit Results", bridge.audit_results))))
        lay.addWidget(run)

        res, res_lay = widgets.make_section("Results by category")
        self.table = widgets.make_table(["Category", "FAIL", "WARN", "INFO", "OK", "Untagged"])
        res_lay.addWidget(self.table)
        lay.addWidget(res)
        lay.addStretch(1)
        self.show_summary(bridge.last_summary())

    def _run(self):
        result = self.ctx.status.run("Auditing %s" % bridge.describe_target(self.ctx.scan_mode()),
                                     bridge.run_audit, self.ctx.scan_mode())
        if result["ok"]:
            self.show_summary(result["summary"])

    def show_summary(self, summary):
        overall = summary["overall"] if summary else {}
        for key, tile in self.tiles.items():
            tile.set_value(overall.get(key))
        cats = summary["categories"] if summary else {}
        self.table.setRowCount(len(CATEGORIES))
        for row, cat in enumerate(CATEGORIES):
            data = cats.get(cat, {})
            self.table.setItem(row, 0, widgets.table_item(cat, bold=True))
            for col, key in enumerate(("FAIL", "WARN", "INFO", "OK", "untagged"), start=1):
                n = data.get(key, "—")
                self.table.setItem(row, col, widgets.table_item(n, key if key != "untagged" else None))
        widgets.fit_table_height(self.table)


class TagTab(QtWidgets.QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        lay = widgets.page_layout(self)

        boot, boot_lay = widgets.make_section(
            "Bootstrap tagging (folder keywords)",
            "Assigns BudgetTier by folder keywords from the project config. Always preview first. "
            "'hero' is never auto-assigned.")
        boot_lay.addWidget(_field_label("Root folder"))
        self.root_edit = QtWidgets.QLineEdit("/Game")
        self.root_edit.setMaximumWidth(420)
        self.root_edit.setMinimumWidth(80)
        boot_lay.addWidget(self.root_edit)
        self.apply_btn = widgets.button("Apply tags", "danger", self._apply)
        self.apply_btn.setEnabled(False)
        boot_lay.addLayout(widgets.button_row(widgets.button("Preview (dry run)", "primary", self._preview),
                                              self.apply_btn))
        lay.addWidget(boot)

        sel, sel_lay = widgets.make_section("Tag selected assets as")
        self.sel_hint = widgets.hint_label("")
        sel_lay.addWidget(self.sel_hint)
        self.tier_row = widgets.FlowLayout()
        for tier in bridge.tag_tiers():
            self.tier_row.addWidget(widgets.button(tier, on_click=lambda t=tier: self._tag_selected(t)))
        sel_lay.addLayout(self.tier_row)
        lay.addWidget(sel)

        self.result, self.result_lay = widgets.make_section("Preview result")
        self.chips = widgets.FlowLayout()
        self.rows_label = QtWidgets.QLabel()
        self.rows_label.setProperty("role", "mono")
        self.rows_label.setWordWrap(True)
        self.result_lay.addLayout(self.chips)
        self.result_lay.addWidget(self.rows_label)
        self.result.hide()
        lay.addWidget(self.result)
        lay.addStretch(1)
        self._previewed_root = None

    def refresh(self):
        text = bridge.describe_selection()
        self.sel_hint.setText(text + " in Content Browser" if text else "Nothing selected in the Content Browser.")

    def _preview(self):
        root = self.root_edit.text().strip() or "/Game"
        result = self.ctx.status.run("Previewing tags on %s" % root, bridge.tag_preview, root)
        self._previewed_root = root if result["ok"] else None
        # Apply only ever targets the folder that was previewed
        self.apply_btn.setEnabled(result["ok"] and result["result"]["would_tag"] > 0)
        if result["ok"]:
            self._show(result["result"])

    def _apply(self):
        root = self._previewed_root
        if not root or not widgets.confirm(self, "Apply tags", "Write BudgetTier tags under %s?" % root):
            return
        result = self.ctx.status.run("Tagging %s" % root, bridge.tag_apply, root)
        self.apply_btn.setEnabled(False)
        if result["ok"]:
            self._show(result["result"], applied=True)

    def _tag_selected(self, tier):
        if not bridge.describe_selection():
            self.ctx.status.set_state("error", "Nothing selected in the Content Browser.")
            return
        self.ctx.status.run("Tagging selection as %s" % tier, bridge.tag_selected, tier)

    def _show(self, view, applied=False):
        widgets.clear_layout(self.chips)
        self.chips.addWidget(widgets.Chip("%d %s" % (view["would_tag"], "tagged" if applied else "would be tagged"),
                                          "success"))
        self.chips.addWidget(widgets.Chip("%d unmatched — manual review" % view["unmatched"],
                                          "warning" if view["unmatched"] else "neutral"))
        self.chips.addWidget(widgets.Chip("%d already tagged (skipped)" % view["already"], "success"))
        self.rows_label.setText("\n".join("%s   →   %s" % (p, tier or "? unmatched") for p, tier in view["rows"][:12]))
        self.result.show()


class FixTab(QtWidgets.QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        lay = widgets.page_layout(self)

        scope, scope_lay = widgets.make_section("Scope")
        self.sel_btn = _toggle("Selected assets", True)
        self.folder_btn = _toggle("Scan target folder", False)
        group = QtWidgets.QButtonGroup(self)
        for b in (self.sel_btn, self.folder_btn):
            group.addButton(b)
        group.buttonClicked.connect(lambda _b: self.refresh())
        scope_lay.addLayout(widgets.button_row(self.sel_btn, self.folder_btn))
        self.scope_hint = widgets.hint_label("")
        scope_lay.addWidget(self.scope_hint)
        lay.addWidget(scope)

        tex, tex_lay = widgets.make_section(
            "Textures", "Texture group per tier, resolution override, sRGB on normal maps.")
        tex_lay.addLayout(widgets.button_row(widgets.button("Fix textures", "primary", self._fix_textures)))
        lay.addWidget(tex)

        mesh, mesh_lay = widgets.make_section(
            "Meshes", "LOD group, tool-generated LODs, Nanite off (if the rule is enabled). "
                      "Hero LODs are hand-authored and never touched.")
        mesh_lay.addLayout(widgets.button_row(
            widgets.button("Fix meshes", "primary", lambda: self._fix_meshes(False)),
            widgets.button("Regenerate LODs", on_click=lambda: self._fix_meshes(True)),
            widgets.button("Mark LODs as tool-generated", on_click=self._mark)))
        lay.addWidget(mesh)

        self.last, self.last_lay = widgets.make_section("Last fix")
        self.chips = widgets.FlowLayout()
        self.last_lay.addLayout(self.chips)
        self.last.hide()
        lay.addWidget(self.last)
        lay.addStretch(1)

    def selected_mode(self):
        return self.sel_btn.isChecked()

    def refresh(self):
        if self.selected_mode():
            text = bridge.describe_selection()
            self.scope_hint.setText("%s — Fix applies only to these." % text if text
                                    else "Nothing selected in the Content Browser.")
        else:
            self.scope_hint.setText("Fix walks %s (scan target is set in the Audit tab)."
                                    % bridge.describe_target(self.ctx.scan_mode()))

    def _confirm_scope(self, what):
        if self.selected_mode():
            return True
        return widgets.confirm(self, what, "%s on %s?\nThis writes to every tagged asset in scope."
                               % (what, bridge.describe_target(self.ctx.scan_mode())))

    def _fix_textures(self):
        if self._confirm_scope("Fix textures"):
            self._show(self.ctx.status.run("Fixing textures", bridge.fix_textures, self.selected_mode()))

    def _fix_meshes(self, regenerate):
        what = "Regenerate LODs" if regenerate else "Fix meshes"
        if self._confirm_scope(what):
            self._show(self.ctx.status.run(what, bridge.fix_meshes, self.selected_mode(), regenerate))

    def _mark(self):
        if widgets.confirm(self, "Mark as tool-generated",
                           "One-time migration: only for meshes this tool already generated LODs for.\n"
                           "Applies to the selected meshes."):
            self.ctx.status.run("Marking LODs", bridge.mark_lods_tool_generated)

    def _show(self, result):
        fix = result.get("fix") if result.get("ok") else None
        widgets.clear_layout(self.chips)
        if not fix:
            self.last.hide()
            return
        self.chips.addWidget(widgets.Chip("%d fixed" % fix["fixed"], "success"))
        if fix["skipped"]:
            self.chips.addWidget(widgets.Chip("%d skipped (untagged)" % fix["skipped"], "warning"))
        if fix["failed"]:
            self.chips.addWidget(widgets.Chip("%d failed" % fix["failed"], "error"))
        self.last.show()


class TiersTab(QtWidgets.QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        lay = widgets.page_layout(self)
        lay.addWidget(widgets.hint_label(
            "Select a tier's assets in the Content Browser, then use the native 'Add to Collection'. "
            "Counts load every asset once - press Refresh counts.", long=True))
        self.cards = widgets.FlowLayout(h_spacing=theme.t("space.md"), v_spacing=theme.t("space.md"))
        self.values = {}
        for tier in bridge.tag_tiers():
            self.cards.addWidget(self._card(tier))
        lay.addLayout(self.cards)
        self.untagged = widgets.hint_label("")
        lay.addWidget(self.untagged)
        lay.addLayout(widgets.button_row(widgets.button("Refresh counts", on_click=self.refresh_counts)))
        lay.addStretch(1)

    def _card(self, tier):
        frame = QtWidgets.QFrame()
        frame.setProperty("role", "tierCard")
        frame.setMinimumWidth(120)
        col = QtWidgets.QVBoxLayout(frame)
        col.setContentsMargins(theme.t("space.lg"), theme.t("space.md"), theme.t("space.lg"), theme.t("space.lg"))
        col.setSpacing(theme.t("space.sm"))
        title = QtWidgets.QLabel(tier.upper())
        title.setProperty("role", "sectionTitle")
        value = QtWidgets.QLabel("—")
        value.setProperty("role", "statValue")
        col.addWidget(title)
        col.addWidget(value)
        col.addWidget(widgets.hint_label("assets tagged"))
        select = widgets.button("Select", on_click=lambda t=tier: self._select(t))
        select.setToolTip("Select this tier's assets in the Content Browser")
        col.addWidget(select)
        self.values[tier] = value
        return frame

    def refresh_counts(self):
        result = self.ctx.status.run("Counting tagged assets", bridge.count_tiers)
        if not result["ok"]:
            return
        for tier, label in self.values.items():
            label.setText(str(result["counts"].get(tier, 0)))
        self.untagged.setText("%d asset(s) untagged." % result["untagged"])

    def _select(self, tier):
        self.ctx.status.run("Selecting '%s' assets" % tier, bridge.select_tier, tier)


def _field_label(text):
    label = QtWidgets.QLabel(text)
    label.setProperty("role", "fieldLabel")
    return label


def _toggle(text, checked):
    btn = QtWidgets.QPushButton(text)
    btn.setProperty("toggle", "true")
    btn.setCheckable(True)
    btn.setChecked(checked)
    btn.setCursor(QtCore.Qt.PointingHandCursor)
    return btn
