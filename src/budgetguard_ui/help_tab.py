# -*- coding: utf-8 -*-
"""Help tab: a self-contained tutorial for someone who has never seen the project. Static text
only - no backend calls - so it works even when the project/config is broken."""
import html
import re

from PySide6 import QtCore, QtWidgets

from . import theme, widgets

# (title, intro, [(step title, body), ...]) - kept as data so the text is easy to edit.
INTRO = (
    "BudgetGuard checks that the 3D content of your Unreal project stays within a performance budget "
    "(texture sizes, triangle counts, LODs, material settings...) and can fix the most common problems "
    "automatically. It only looks at textures, meshes and materials")

CONCEPTS = (
    ("Budget tier",
     "Every asset belongs to a tier that says how much it is allowed to cost: architecture, hero, props, "
     "background or utility. A background clutter item gets a much smaller budget than a hero object. "
     "The tier is stored on the asset as a tag called BudgetTier."),
    ("Rule",
     "A single check, for example 'texture resolution over budget' or 'Nanite enabled'. Each rule can be "
     "switched off, or set to WARN (worth a look) or FAIL (must be fixed) in the Settings tab."),
    ("Profile",
     "A ready-made set of budgets and rules for a target platform (for example Mobile VR - Quest 3). "
     "Your project can override any number in Settings; the override is saved inside the project."),
)  # "Result levels" is rendered separately (colour-coded) by _levels_html()

STEPS = (
    ("1. Open the panel",
     "In the Unreal Editor menu choose Tools > BudgetGuard. The project name appears at the top. If a banner "
     "says 'No project config yet', click 'Set up project...' and pick the profile closest to your target platform."),
    ("2. Tag your content (Tag tab)",
     "The tool needs to know each asset's tier. Click 'Preview (dry run)' to see what would be tagged from "
     "the folder names - nothing is written yet. Check the 'unmatched' list, then 'Apply tags'. "
     "For single assets, select them in the Content Browser and click a tier button. "
     "'hero' is never assigned automatically: tag unique, story-critical objects by hand."),
    ("3. Run an audit (Audit tab)",
     "Choose a scan target: the open level, the folder selected in the Content Browser, or the whole project. "
     "Click 'Run audit'. The tiles and the table show how many assets FAIL / WARN / are OK per category. "
     "Details are printed in the Output Log."),
    ("4. Read the report",
     "'Audit Results' exports CSV + JSON into <Project>/Saved/BudgetGuard/ and builds an HTML dashboard "
     "(needs Node.js installed). Old runs are kept in a history folder so you can compare them."),
    ("5. Fix problems (Fix tab)",
     "Choose the scope - the assets selected in the Content Browser, or the whole scan target - then use "
     "'Fix textures' or 'Fix meshes'. Untagged assets are skipped: tag them first. Fixes write to your "
     "assets immediately, so save them and use source control. Hero LODs are hand-authored and never touched."),
    ("6. Browse by tier (Tiers tab)",
     "'Refresh counts' shows how many assets each tier holds. 'Select' selects a tier's assets in the Content "
     "Browser; right-click > Add to Collection to keep them as a collection."),
    ("7. Tune the budgets (Settings tab)",
     "Switch rules on/off, change WARN/FAIL, edit tier numbers, and save named presets. Only values that "
     "differ from the profile are stored. Defaults are placeholders until your technical artist validates them."),
)

TIPS = (
    "Always preview before applying tags; unmatched folders are listed, never guessed.",
    "A high untagged count after auditing a new folder usually means 'tag it first', not 'it is over budget'.",
    "Fix and tag actions can take a while on big projects - the Editor is busy until the status bar turns green.",
    "After editing the tool's scripts press the reload button at the bottom of the left rail.",
    "Nanite is flagged by default because the baseline target is mobile/standalone VR; a desktop project "
    "that uses Nanite sets that rule to OFF in Settings.",
)


class HelpTab(QtWidgets.QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        lay = widgets.page_layout(self)

        what, what_lay = widgets.make_section("What is BudgetGuard?")
        what_lay.addWidget(_prose(_fmt(INTRO)))
        lay.addWidget(what)

        words, words_lay = widgets.make_section("Key words")
        for title, body in CONCEPTS:
            words_lay.addWidget(_card(_heading(title), _fmt(body)))
        words_lay.addWidget(_card(_heading("Result levels"), _levels_html()))
        lay.addWidget(words)

        how, how_lay = widgets.make_section("How to use it, step by step")
        for title, body in STEPS:
            num, _, name = title.partition(". ")
            how_lay.addWidget(_card(_heading(name), _fmt(body), badge=num))
        lay.addWidget(how)

        tips, tips_lay = widgets.make_section("Good to know")
        for tip in TIPS:
            tips_lay.addWidget(_card(None, _fmt(tip), badge="•"))
        lay.addWidget(tips)

        more, more_lay = widgets.make_section("More")
        more_lay.addWidget(_prose(_fmt("The full user manual is in the repository: <code>docs/USER_MANUAL.md</code>.",
                                       escape=False)))
        lay.addWidget(more)
        lay.addStretch(1)


def _prose(text):
    label = QtWidgets.QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(QtCore.Qt.RichText)
    label.setStyleSheet("line-height: 140%;")
    return label


def _fmt(text, escape=True):
    """Plain text -> rich text: escape HTML, then highlight 'quoted' UI names and 'A > B' menu paths."""
    if escape:
        text = html.escape(text, quote=False)
    accent = theme.t("color.accent.hover")
    text = re.sub(r"(?<!\w)'([^']+?)'(?!\w)",
                  lambda m: '<b style="color:%s">%s</b>' % (accent, m.group(1)), text)
    text = re.sub(r"(Tools &gt; BudgetGuard)", r'<b style="color:%s">\1</b>' % accent, text)
    return text


def _heading(text):
    return '<span style="font-size:%dpx; font-weight:600; color:%s">%s</span>' % (
        theme.t("font.size.label"), theme.t("color.text.primary"), html.escape(text, quote=False))


def _levels_html():
    rows = []
    for level, tone, meaning in (
            ("FAIL", "color.state.error", "over budget"),
            ("WARN", "color.state.warning", "suspicious, worth a look"),
            ("INFO", "color.text.secondary", "the check could not be evaluated"),
            ("OK", "color.state.success", "fine")):
        rows.append('<b style="color:%s">%s</b> &nbsp;%s' % (theme.t(tone), level, meaning))
    rows.append(_fmt("'Untagged' assets have no tier yet and are checked against the default tier."))
    return "<br>".join(rows)


def _card(heading_html, body_html, badge=None):
    """Surface-coloured card: optional accent badge (step number / bullet), heading, body."""
    frame = QtWidgets.QFrame()
    frame.setObjectName("helpCard")
    frame.setStyleSheet("#helpCard { background: %s; border: 1px solid %s; border-radius: %dpx; }"
                        % (theme.t("color.bg.surface"), theme.t("color.border.default"), theme.t("radius.md")))
    row = QtWidgets.QHBoxLayout(frame)
    row.setContentsMargins(theme.t("space.md"), theme.t("space.md"), theme.t("space.md"), theme.t("space.md"))
    row.setSpacing(theme.t("space.md"))
    if badge:
        chip = QtWidgets.QLabel(badge)
        chip.setAlignment(QtCore.Qt.AlignCenter)
        chip.setFixedSize(24, 24)
        chip.setStyleSheet("background: %s; color: %s; border-radius: 12px; font-weight: 600;"
                           % (theme.t("color.accent.default"), theme.t("color.text.onAccent")))
        row.addWidget(chip, 0, QtCore.Qt.AlignTop)
    col = QtWidgets.QVBoxLayout()
    col.setSpacing(theme.t("space.xs"))
    if heading_html:
        col.addWidget(_prose(heading_html))
    col.addWidget(_prose(body_html))
    row.addLayout(col, 1)
    return frame
