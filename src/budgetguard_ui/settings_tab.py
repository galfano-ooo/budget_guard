# -*- coding: utf-8 -*-
"""Settings tab: rule profile picker, per-rule switch + severity (WARN/FAIL) + thresholds, editable
tier budgets, project config file actions, presets, tools. Edits are staged (profile, disabled
rules, tier budgets, rule severities/thresholds) and only written when the SaveBar's
'Save to config.json' is pressed; only values that differ from the profile reach the file."""
import copy

from PySide6 import QtCore, QtWidgets

from . import bridge, theme, widgets

CATEGORIES = ("Textures", "Meshes", "Materials")
SEVERITIES = ("WARN", "FAIL")
TIER_FIELDS = (
    ("max_texture_resolution", "Max texture resolution (px)"),
    ("max_triangles", "Max triangles (LOD0)"),
    ("max_material_slots", "Max material slots"),
)
# rule id -> (rule key, label, kind) for the threshold shown on that rule's row. severe_multiplier is one
# shared setting (texture and triangle rules both read it), so both rows edit the same value.
THRESHOLDS = {
    "resolution_over_budget": ("severe_multiplier", "FAIL past ×", "mult"),
    "triangle_count_over_budget": ("severe_multiplier", "FAIL past ×", "mult"),
    "missing_lod": ("missing_lod_triangle_threshold", "Check meshes above (tris)", "int"),
}
RULE_DEFAULTS = {"severe_multiplier": 2.0, "missing_lod_triangle_threshold": 3000}   # same fallbacks as the rules
SEVERE_NOTE = "shared by the texture and triangle rules"


def _fmt(value):
    return "—" if value is None else str(value)


def _parse(text, kind):
    """-> (valid, value). kind: 'opt' = positive int or empty (no limit); 'int' = positive int;
    'mult' = number >= 1."""
    text = text.strip()
    if kind == "opt" and not text:
        return True, None
    if kind in ("opt", "int"):
        return (True, int(text)) if text.isdigit() and int(text) > 0 else (False, None)
    try:
        value = float(text)
    except ValueError:
        return False, None
    return (True, value) if value >= 1 else (False, None)


def _state(widget, state):
    widget.setProperty("state", state)
    theme.repolish(widget)


class SettingsTab(QtWidgets.QWidget):
    configChanged = QtCore.Signal()      # the override was written / deleted: header chip + tabs refresh
    reloadRequested = QtCore.Signal()

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.state = None
        self.pending_profile = None
        self.pending_disabled = set()
        self.pending_tiers = {}
        self.pending_rules = {}
        self.saved_tiers = {}
        self.saved_rules = {}
        self.invalid = {}                # key -> message; any entry blocks Save

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.body = QtWidgets.QWidget()
        self.body_lay = widgets.page_layout(self.body)
        outer.addWidget(widgets.scrolled(self.body), 1)

        self.save_bar = QtWidgets.QFrame()
        self.save_bar.setObjectName("SaveBar")
        bar = QtWidgets.QHBoxLayout(self.save_bar)
        bar.setContentsMargins(theme.t("space.lg"), theme.t("space.sm"), theme.t("space.lg"), theme.t("space.sm"))
        self.save_label = QtWidgets.QLabel()
        self.save_label.setWordWrap(True)
        bar.addWidget(self.save_label, 1)
        bar.addWidget(widgets.button("Discard", on_click=self._discard))
        self.save_btn = widgets.button("Save to config.json", "primary", self._save)
        bar.addWidget(self.save_btn)
        outer.addWidget(self.save_bar)
        self.save_bar.hide()

    # ---- build ----

    def refresh(self):
        try:
            self.state = bridge.settings_state()
        except Exception as exc:  # noqa: BLE001 - an invalid override must not blank the panel
            self.state = None
            self._clear()
            self.body_lay.addWidget(widgets.hint_label("Config could not be loaded: %s" % exc))
            self.body_lay.addLayout(self._file_buttons(False))
            self.body_lay.addStretch(1)
            return
        self._load_pending()
        self._rebuild()

    def _load_pending(self):
        st = self.state
        self.pending_profile = st["profile_id"]
        self.pending_disabled = set(st["disabled"])
        self.pending_tiers = {t["tier"]: {f: t["budget"].get(f) for f, _l in TIER_FIELDS} for t in st["tiers"]}
        self.pending_rules = {r["id"]: str(st["rule_values"].get(r["id"], "WARN")).upper() for r in st["rules"]}
        for key in RULE_DEFAULTS:
            self.pending_rules[key] = st["rule_values"].get(key, RULE_DEFAULTS[key])
        self.saved_tiers = copy.deepcopy(self.pending_tiers)
        self.saved_rules = dict(self.pending_rules)
        self.invalid = {}

    def _base_rule(self, key):
        return self.state["baseline_rules"].get(key, RULE_DEFAULTS.get(key, "WARN"))

    def _clear(self):
        widgets.clear_layout(self.body_lay)

    def _rebuild(self):
        st = self.state
        self._clear()
        self.invalid = {}
        self.mult_edits = []
        self.mult_rows = []      # refresh callbacks of the rows that share severe_multiplier

        prof, lay = widgets.make_section("Rule profile")
        row = widgets.FlowLayout()
        combo = QtWidgets.QComboBox()
        combo.setMinimumWidth(200)
        for p in st["profiles"]:
            combo.addItem(p["label"], p["id"])
        combo.setCurrentIndex(max(combo.findData(self.pending_profile), 0))
        combo.currentIndexChanged.connect(lambda _i: self._set_profile(combo.currentData()))
        row.addWidget(combo)
        row.addWidget(widgets.Chip("active", "success"))
        row.addWidget(widgets.button("Reset rules to profile", on_click=self._reset_rules))
        lay.addLayout(row)
        desc = (st["profile"] or {}).get("description", "")
        lay.addWidget(widgets.hint_label(
            (desc + " " if desc else "") + "Switch a rule off to skip it, or set it to WARN (advisory) or "
            "FAIL (counts as a failure) to suit this project.", long=True))
        self.body_lay.addWidget(prof)

        for cat in CATEGORIES:
            rules = [r for r in st["rules"] if r["category"] == cat]
            if not rules:
                continue
            sec, sec_lay = widgets.make_section(cat)
            for rule in rules:
                sec_lay.addWidget(self._rule_row(rule))
            if cat == CATEGORIES[-1]:
                sec_lay.addWidget(widgets.hint_label(
                    "Severity — WARN: reported as a warning. FAIL: counted as a failure. The switch skips the rule "
                    "entirely (its severity is then greyed out). WARN everywhere suits a relaxed desktop project, "
                    "FAIL a strict target like Quest 3.", long=True))
            self.body_lay.addWidget(sec)

        self.body_lay.addWidget(self._tier_section())
        self.body_lay.addWidget(self._config_section())
        self.body_lay.addWidget(self._presets_section())
        self.body_lay.addWidget(self._tools_section())
        self.body_lay.addStretch(1)
        widgets.apply_compact(self.body, self.ctx.is_compact())
        self._update_bar()

    def _rule_row(self, rule):
        rid = rule["id"]
        frame = QtWidgets.QFrame()
        frame.setProperty("role", "ruleRow")
        frame.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Minimum)
        row = QtWidgets.QHBoxLayout(frame)
        row.setContentsMargins(theme.t("space.md"), theme.t("space.sm"), theme.t("space.md"), theme.t("space.sm"))
        row.setSpacing(theme.t("space.md"))
        switch = widgets.Switch(rid not in self.pending_disabled)
        text = QtWidgets.QVBoxLayout()
        text.setSpacing(0)
        title = QtWidgets.QLabel(rule["label"])
        title.setProperty("role", "optionTitle")
        desc = widgets.hint_label(rule["description"])
        text.addWidget(title)
        text.addWidget(desc)

        sev = QtWidgets.QComboBox()
        sev.setFixedWidth(90)
        current = self.pending_rules[rid]
        for s in SEVERITIES + ((current,) if current not in SEVERITIES else ()):
            sev.addItem(s, s)
        sev.setCurrentIndex(max(sev.findData(current), 0))
        marker = QtWidgets.QLabel()
        marker.setObjectName("RuleMarker")   # hidden in the Compact window (apply_compact)
        marker.setProperty("role", "hint")
        marker.setMinimumWidth(86)

        thr_edit = None
        thr_box = None
        if rid in THRESHOLDS:
            key, label, kind = THRESHOLDS[rid]
            thr_box = QtWidgets.QHBoxLayout()
            thr_box.setSpacing(theme.t("space.sm"))
            thr_label = QtWidgets.QLabel(label)
            thr_label.setProperty("role", "hint")
            thr_edit = QtWidgets.QLineEdit(str(self.pending_rules[key]))
            thr_edit.setFixedWidth(70)
            thr_edit.setToolTip(SEVERE_NOTE if kind == "mult" else "Meshes with more triangles than this need LODs")
            thr_box.addWidget(thr_label)
            thr_box.addWidget(thr_edit)
            thr_box.addStretch(1)
            if kind == "mult":
                self.mult_edits.append(thr_edit)

        def refresh_row():
            on = switch.isChecked()
            sev.setEnabled(on)
            for w in (title, desc):
                w.setEnabled(on)
            if thr_edit is not None:
                thr_edit.setEnabled(on and (THRESHOLDS[rid][2] != "mult" or sev.currentData() != "FAIL"))
            changed = sev.currentData() != self._base_rule(rid) or (thr_edit is not None and
                      self.pending_rules[THRESHOLDS[rid][0]] != self._base_rule(THRESHOLDS[rid][0]))
            over = changed or (rid in self.pending_disabled) != (rid in self.state["baseline_disabled"])
            marker.setText("overridden" if over else "profile default")
            marker.setProperty("tone", "info" if over else None)
            theme.repolish(marker)
            _state(sev, "over" if sev.currentData() != self._base_rule(rid) else None)

        def on_switch(on):
            (self.pending_disabled.discard if on else self.pending_disabled.add)(rid)
            refresh_row()
            self._update_bar()

        def on_sev(_i):
            self.pending_rules[rid] = sev.currentData()
            refresh_row()
            self._update_bar()

        if thr_edit is not None and THRESHOLDS[rid][2] == "mult":
            self.mult_rows.append(refresh_row)
        switch.toggled.connect(on_switch)
        sev.currentIndexChanged.connect(on_sev)
        if thr_edit is not None:
            key, _label, kind = THRESHOLDS[rid]
            ekey = ("rule", key, rid)

            def on_thr(txt, ekey=ekey, key=key, kind=kind):
                ok, value = _parse(txt, kind)
                if ok and value is not None:
                    self.pending_rules[key] = value
                    self.invalid.pop(ekey, None)
                else:
                    self.invalid[ekey] = "%s must be %s." % (
                        rule["label"], "a number of 1 or more" if kind == "mult" else "a positive whole number")
                _state(thr_edit, "err" if ekey in self.invalid else
                       ("over" if ok and value != self._base_rule(key) else None))
                if kind == "mult" and ok:      # keep the shared value in step across rows
                    for other in self.mult_edits:
                        if other is not thr_edit and other.text() != txt:
                            other.blockSignals(True)
                            other.setText(txt)
                            other.blockSignals(False)
                            _state(other, "over" if value != self._base_rule(key) else None)
                for refresh in (self.mult_rows if kind == "mult" else [refresh_row]):
                    refresh()
                self._update_bar()
            thr_edit.textChanged.connect(on_thr)
            on_thr(thr_edit.text())

        refresh_row()
        row.addWidget(switch)
        if thr_box is not None:   # under the description, so the row stays narrow-window friendly
            text.addLayout(thr_box)
        row.addLayout(text, 1)
        row.addWidget(sev)
        row.addWidget(marker)
        return frame

    def _tier_section(self):
        sec, lay = widgets.make_section(
            "Budget per asset tier",
            "Limits each asset is checked against, based on its BudgetTier tag. Edit a value to override the "
            "profile (blue = differs from the profile). Leave a field empty for no limit.")
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(theme.t("space.md"))
        grid.setVerticalSpacing(theme.t("space.sm"))
        grid.addWidget(_field_label("Tier"), 0, 0)
        for col, (_f, label) in enumerate(TIER_FIELDS, start=1):
            head = _field_label(label)
            head.setWordWrap(True)
            grid.addWidget(head, 0, col)
            grid.setColumnStretch(col, 1)
        self.tier_edits = {}
        self.tier_resets = {}
        self.tier_error = widgets.hint_label("")
        self.tier_error.setProperty("tone", "error")

        for row_i, t in enumerate(self.state["tiers"], start=1):
            tier = t["tier"]
            name = QtWidgets.QLabel(tier)
            name.setProperty("role", "optionTitle")
            grid.addWidget(name, row_i, 0)
            for col, (field, label) in enumerate(TIER_FIELDS, start=1):
                value = self.pending_tiers[tier][field]
                edit = QtWidgets.QLineEdit("" if value is None else str(value))
                edit.setPlaceholderText("no limit")
                edit.setMinimumWidth(48)
                edit.setMaximumWidth(130)
                edit.setToolTip("%s — %s" % (tier, label))
                edit.textChanged.connect(lambda txt, tier=tier, field=field: self._on_tier_edit(tier, field, txt))
                grid.addWidget(edit, row_i, col)
                self.tier_edits[(tier, field)] = edit
            reset = widgets.button("↺ reset", on_click=lambda tier=tier: self._reset_tier(tier))
            reset.setToolTip("Back to the profile's values for %s" % tier)
            grid.addWidget(reset, row_i, len(TIER_FIELDS) + 1)
            self.tier_resets[tier] = reset
        lay.addLayout(grid)
        lay.addWidget(self.tier_error)
        lay.addWidget(widgets.hint_label(
            "Max texture resolution: longest side of any texture, in pixels. Max triangles: LOD0 triangle count of "
            "a mesh. Max material slots: material slots on a mesh. Only changed values are written to config.json; "
            "everything else keeps following the profile.", long=True))
        for (tier, field), edit in self.tier_edits.items():
            self._on_tier_edit(tier, field, edit.text())
        return sec

    def _on_tier_edit(self, tier, field, text):
        edit = self.tier_edits[(tier, field)]
        key = ("tier", tier, field)
        ok, value = _parse(text, "opt")
        label = dict(TIER_FIELDS)[field]
        if ok:
            self.invalid.pop(key, None)
            self.pending_tiers[tier][field] = value
        else:
            self.invalid[key] = "%s · %s must be a positive whole number, or empty for no limit." % (tier, label)
        base = (self.state["baseline_tiers"].get(tier) or {}).get(field)
        _state(edit, "err" if not ok else ("over" if value != base else None))
        self.tier_resets[tier].setVisible(any(
            self.pending_tiers[tier][f] != (self.state["baseline_tiers"].get(tier) or {}).get(f)
            or ("tier", tier, f) in self.invalid for f, _l in TIER_FIELDS))
        errors = [m for k, m in self.invalid.items() if k[0] == "tier"]
        self.tier_error.setText(errors[0] if errors else "")
        theme.repolish(self.tier_error)
        self._update_bar()

    def _reset_tier(self, tier):
        base = self.state["baseline_tiers"].get(tier) or {}
        for field, _l in TIER_FIELDS:
            value = base.get(field)
            self.tier_edits[(tier, field)].setText("" if value is None else str(value))

    def _config_section(self):
        sec, lay = widgets.make_section("Project config")
        lay.addWidget(_field("Override file"))
        path = QtWidgets.QLineEdit(self.state["override_path"])
        path.setReadOnly(True)
        path.setMaximumWidth(620)
        path.setMinimumWidth(80)
        lay.addWidget(path)
        lay.addLayout(self._file_buttons(self.state["has_override"]))
        lay.addWidget(widgets.hint_label(
            "Open file shows every editable value (a template is added the first time). Stores: profile, tier "
            "budgets, rule severities, disabled rules, tag keywords, extra excluded folders.", long=True))
        return sec

    def _file_buttons(self, has_override):
        row = widgets.FlowLayout()
        row.addWidget(widgets.Chip("override loaded" if has_override else "no override", "success" if has_override else "info"))
        open_btn = widgets.button("Open file", on_click=lambda: self.ctx.status.run("Open", bridge.open_config_file))
        open_btn.setEnabled(has_override)
        example = widgets.button("Create from example", on_click=self._from_example)
        example.setEnabled(not has_override)
        export = widgets.button("Export…", on_click=self._export)
        export.setEnabled(has_override)
        delete = widgets.button("Delete override", "danger", self._delete)
        delete.setEnabled(has_override)
        for w in (open_btn, example, widgets.button("Import from file…", on_click=self._import), export, delete):
            row.addWidget(w)
        return row

    def _presets_section(self):
        sec, lay = widgets.make_section(
            "Presets", "Named snapshots of this project's config, stored next to it in Saved/BudgetGuard/presets/. "
                       "Loading one replaces the current override; the override it replaces is kept as "
                       "'_previous' so you can always go back.")
        names = bridge.list_presets()
        row = widgets.FlowLayout()
        self.preset_combo = QtWidgets.QComboBox()
        self.preset_combo.setMinimumWidth(200)
        for n in names:
            self.preset_combo.addItem("↩ _previous (auto-backup)" if n == "_previous" else n, n)
        load = widgets.button("Load", "primary", self._load_preset)
        delete = widgets.button("Delete", "danger", self._delete_preset)
        for w in (load, delete):
            w.setEnabled(bool(names))
        save = widgets.button("Save current as…", on_click=self._save_preset)
        save.setEnabled(self.state["has_override"])
        for w in (self.preset_combo, load, save, delete):
            row.addWidget(w)
        lay.addLayout(row)
        if not names:
            lay.addWidget(widgets.hint_label("No presets yet - edit the config, then 'Save current as…'."))
        return sec

    def _save_preset(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "Save preset", "Preset name:")
        if not ok or not name.strip():
            return
        overwrite = bridge.preset_exists(name)
        if overwrite and not widgets.confirm(self, "Overwrite preset", "Preset '%s' already exists. Overwrite it?"
                                             % name.strip()):
            return
        if self.ctx.status.run("Save preset", bridge.save_preset, name, overwrite)["ok"]:
            self.refresh()

    def _load_preset(self):
        name = self.preset_combo.currentData()
        if name and self.ctx.status.run("Load preset", bridge.load_preset, name)["ok"]:
            self.configChanged.emit()

    def _delete_preset(self):
        name = self.preset_combo.currentData()
        if name and widgets.confirm(self, "Delete preset", "Delete preset '%s'?" % name):
            if self.ctx.status.run("Delete preset", bridge.delete_preset, name)["ok"]:
                self.refresh()

    def _tools_section(self):
        sec, lay = widgets.make_section("Tools")
        lay.addLayout(widgets.button_row(
            widgets.button("Reload scripts", on_click=self.reloadRequested.emit),
            widgets.button("Verify API", on_click=lambda: self.ctx.status.run("Verify API", bridge.verify_api))))
        return sec

    # ---- staged edits ----

    def _set_profile(self, profile_id):
        self.pending_profile = profile_id
        self._update_bar()

    def _reset_rules(self):
        self.pending_disabled = set(self.state["baseline_disabled"])
        for key in self.pending_rules:
            self.pending_rules[key] = str(self._base_rule(key)).upper() if key not in RULE_DEFAULTS \
                else self._base_rule(key)
        self._rebuild()

    def _changes(self):
        changes = []
        if self.pending_profile != self.state["profile_id"]:
            changes.append("profile → %s" % self.pending_profile)
        before, after = set(self.state["disabled"]), self.pending_disabled
        changes += ["%s switched off" % r for r in sorted(after - before)]
        changes += ["%s switched on" % r for r in sorted(before - after)]
        for tier, fields in self.pending_tiers.items():
            for field, value in fields.items():
                old = self.saved_tiers[tier][field]
                if value != old:
                    changes.append("%s.%s %s → %s" % (tier, field, _fmt(old), _fmt(value)))
        for key, value in self.pending_rules.items():
            if value != self.saved_rules[key]:
                changes.append("%s %s → %s" % (key, self.saved_rules[key], value))
        return changes

    def _update_bar(self):
        if not self.state:
            self.save_bar.hide()
            return
        changes = self._changes()
        blocked = bool(self.invalid)
        self.save_bar.setVisible(bool(changes) or blocked)
        self.save_btn.setEnabled(not blocked)
        if blocked:
            self.save_label.setText("Fix the highlighted values before saving.")
        elif changes:
            self.save_label.setText("%d unsaved change%s: %s" % (len(changes), "" if len(changes) == 1 else "s",
                                                                  " · ".join(changes)))

    def _discard(self):
        self._load_pending()
        self._rebuild()

    def _save(self):
        if self.invalid:
            return
        result = self.ctx.status.run("Saving config", bridge.save_settings, self.pending_profile,
                                     self.pending_disabled, self.pending_tiers, self.pending_rules)
        if result["ok"]:
            self.configChanged.emit()

    # ---- config file actions ----

    def _from_example(self):
        if self.ctx.status.run("Create from example", bridge.create_config_from_example)["ok"]:
            self.configChanged.emit()

    def _import(self):
        path, _f = QtWidgets.QFileDialog.getOpenFileName(self, "Import BudgetGuard config", "", "JSON (*.json)")
        if path and self.ctx.status.run("Import config", bridge.import_config, path)["ok"]:
            self.configChanged.emit()

    def _export(self):
        path, _f = QtWidgets.QFileDialog.getSaveFileName(self, "Export BudgetGuard config", "config.json",
                                                         "JSON (*.json)")
        if path:
            self.ctx.status.run("Export config", bridge.export_config, path)

    def _delete(self):
        if widgets.confirm(self, "Delete override", "Delete this project's config.json?\n"
                           "Generic defaults apply again (tag keywords, exclusions, disabled rules are lost)."):
            if self.ctx.status.run("Delete config", bridge.delete_config)["ok"]:
                self.configChanged.emit()


def _field(text):
    label = QtWidgets.QLabel(text)
    label.setProperty("role", "fieldLabel")
    return label


_field_label = _field
