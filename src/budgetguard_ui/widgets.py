# -*- coding: utf-8 -*-
"""Small reusable widgets for the BudgetGuard panel. Colours come from theme.py only."""
import os

from PySide6 import QtCore, QtGui, QtSvg, QtWidgets

from . import theme

_ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")


def make_icon(name, size=20):
    """QIcon for icons/<name>.svg: grey normally, white when checked (nav button states)."""
    icon = QtGui.QIcon()
    path = os.path.join(_ICON_DIR, name + ".svg")
    with open(path, "r", encoding="utf-8") as f:
        svg = f.read()
    for mode, key in ((QtGui.QIcon.Normal, "color.text.secondary"), (QtGui.QIcon.Active, "color.text.primary")):
        for state in (QtGui.QIcon.Off,):
            icon.addPixmap(_render(svg, theme.t(key), size), mode, state)
    icon.addPixmap(_render(svg, theme.t("color.text.primary"), size), QtGui.QIcon.Normal, QtGui.QIcon.On)
    return icon


def _render(svg_text, color, size):
    renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(svg_text.replace("currentColor", color).encode("utf-8")))
    ratio = 2  # crisp on hi-dpi
    pix = QtGui.QPixmap(size * ratio, size * ratio)
    pix.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pix)
    renderer.render(painter)
    painter.end()
    pix.setDevicePixelRatio(ratio)
    return pix


def set_tone(widget, tone):
    widget.setProperty("tone", tone)
    theme.repolish(widget)


class FlowLayout(QtWidgets.QLayout):
    """Left-to-right layout that wraps to a new row when the width runs out (heightForWidth), so a
    narrow window grows taller instead of clipping. Minimum width = the widest single item."""

    def __init__(self, parent=None, h_spacing=None, v_spacing=None):
        super().__init__(parent)
        self._items = []
        self._h = theme.t("space.sm") if h_spacing is None else h_spacing
        self._v = theme.t("space.sm") if v_spacing is None else v_spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return QtCore.Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._flow(QtCore.QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._flow(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QtCore.QSize(0, 0)
        for item in self._items:
            if not item.isEmpty():
                size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QtCore.QSize(m.left() + m.right(), m.top() + m.bottom())

    def _flow(self, rect, measure_only):
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = area.x(), area.y(), 0
        for item in self._items:
            if item.isEmpty():
                continue
            hint = item.sizeHint()
            w = min(hint.width(), max(area.width(), item.minimumSize().width()))
            if x > area.x() and x + w > area.right() + 1:
                x, y, line_h = area.x(), y + line_h + self._v, 0
            if not measure_only:
                item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), QtCore.QSize(w, hint.height())))
            x += w + self._h
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + m.bottom()


def apply_compact(root, on):
    """Reflow everything under `root` for the Compact window: tighter page / section margins, long
    explanatory hints (property long=True) and rule markers (objectName RuleMarker) hidden.
    Idempotent; call again after a tab rebuilds its content."""
    page_m = theme.t("space.sm") if on else theme.t("space.lg")
    sec_h, sec_top, sec_bot = ((theme.t("space.md"), theme.t("space.sm"), theme.t("space.md")) if on else
                               (theme.t("space.lg"), theme.t("space.md"), theme.t("space.lg")))
    for w in [root] + root.findChildren(QtWidgets.QWidget):
        if w.property("page") and w.layout() is not None:
            w.layout().setContentsMargins(page_m, page_m, page_m, page_m)
        elif w.property("role") == "section" and w.layout() is not None:
            w.layout().setContentsMargins(sec_h, sec_top, sec_h, sec_bot)
        elif isinstance(w, QtWidgets.QLabel) and (w.property("long") or w.objectName() == "RuleMarker"):
            w.setVisible(not on)


def make_section(title, hint=None):
    """Titled panel; returns (frame, body_layout)."""
    frame = QtWidgets.QFrame()
    frame.setProperty("role", "section")
    # Minimum (not Preferred): a section never shrinks below its content, so the page scrolls
    # instead of squeezing sections over each other (wrapped labels under-report their minimum)
    frame.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Minimum)
    lay = QtWidgets.QVBoxLayout(frame)
    lay.setContentsMargins(theme.t("space.lg"), theme.t("space.md"), theme.t("space.lg"), theme.t("space.lg"))
    lay.setSpacing(theme.t("space.sm"))
    head = QtWidgets.QLabel(title.upper())
    head.setProperty("role", "sectionTitle")
    lay.addWidget(head)
    if hint:
        lay.addWidget(hint_label(hint, long=True))
    return frame, lay


def hint_label(text, long=False):
    """`long` = explanatory prose that the Compact window hides (status-like hints stay)."""
    label = QtWidgets.QLabel(text)
    label.setProperty("role", "hint")
    if long:
        label.setProperty("long", True)
    label.setWordWrap(True)
    return label


def button(text, role=None, on_click=None):
    btn = QtWidgets.QPushButton(text)
    btn.setCursor(QtCore.Qt.PointingHandCursor)
    if role:
        btn.setProperty("role", role)
    if on_click:
        btn.clicked.connect(lambda _checked=False: on_click())
    return btn


def button_row(*buttons):
    row = FlowLayout()
    for b in buttons:
        row.addWidget(b)
    return row


class Chip(QtWidgets.QLabel):
    """Pill label; tone = success / warning / error / info / neutral / off."""

    def __init__(self, text="", tone="neutral", parent=None):
        super().__init__(text, parent)
        self.setProperty("role", "chip")
        self.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)
        set_tone(self, tone)


class StatTile(QtWidgets.QFrame):
    def __init__(self, label, tone=None, parent=None):
        super().__init__(parent)
        self.setProperty("role", "stat")
        self.setMinimumWidth(56)
        col = QtWidgets.QVBoxLayout(self)
        col.setContentsMargins(theme.t("space.md"), theme.t("space.sm"), theme.t("space.md"), theme.t("space.sm"))
        col.setSpacing(0)
        self.value_label = QtWidgets.QLabel("—")
        self.value_label.setProperty("role", "statValue")
        self.value_label.setAlignment(QtCore.Qt.AlignHCenter)
        if tone:
            set_tone(self.value_label, tone)
        caption = QtWidgets.QLabel(label)
        caption.setProperty("role", "hint")
        caption.setAlignment(QtCore.Qt.AlignHCenter)
        col.addWidget(self.value_label)
        col.addWidget(caption)

    def set_value(self, value):
        self.value_label.setText("—" if value is None else str(value))


class Switch(QtWidgets.QCheckBox):
    """Painted on/off switch (track + thumb), no label."""
    TRACK_W, TRACK_H = 34, 18

    def __init__(self, checked=True, parent=None):
        super().__init__(parent)
        self.setChecked(checked)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setFixedSize(self.TRACK_W, self.TRACK_H)

    def hitButton(self, _pos):
        return True

    def paintEvent(self, _event):
        c = QtGui.QColor
        on = self.isChecked()
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        fill = c(theme.t("color.accent.default")) if on else c(theme.t("color.bg.input"))
        edge = fill if on else c(theme.t("color.border.default"))
        p.setPen(QtGui.QPen(edge, 1))
        p.setBrush(fill)
        h = self.TRACK_H
        p.drawRoundedRect(QtCore.QRectF(0.5, 0.5, self.TRACK_W - 1, h - 1), h / 2.0, h / 2.0)
        d = h - 6
        x = self.TRACK_W - 3 - d if on else 3
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(c(theme.t("color.text.onAccent" if on else "color.text.secondary")))
        p.drawEllipse(QtCore.QRectF(x, 3, d, d))
        p.end()


def make_table(headers, row_h=30):
    table = QtWidgets.QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(row_h)
    table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
    table.horizontalHeader().setDefaultAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
    table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
    table.setShowGrid(False)
    table.setFocusPolicy(QtCore.Qt.NoFocus)
    table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    table.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    return table


def fit_table_height(table):
    rows = table.rowCount()
    table.setFixedHeight(table.horizontalHeader().height() + rows * table.verticalHeader().defaultSectionSize() + 2)


def table_item(text, tone=None, bold=False):
    item = QtWidgets.QTableWidgetItem(str(text))
    if tone:
        colour = {"FAIL": "color.state.error", "WARN": "color.state.warning", "OK": "color.state.success",
                  "INFO": "color.text.secondary"}.get(tone)
        if colour:
            item.setForeground(QtGui.QColor(theme.t(colour)))
    if bold:
        font = item.font()
        font.setBold(True)
        item.setFont(font)
    return item


def scrolled(widget):
    area = QtWidgets.QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QtWidgets.QFrame.NoFrame)
    area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    area.setWidget(widget)
    return area


def page_layout(page):
    """Standard tab body: vertical stack with the design's 16px margins; returns the layout."""
    page.setProperty("page", True)   # apply_compact tightens these margins
    lay = QtWidgets.QVBoxLayout(page)
    lay.setContentsMargins(theme.t("space.lg"), theme.t("space.lg"), theme.t("space.lg"), theme.t("space.lg"))
    lay.setSpacing(theme.t("space.md"))
    return lay


def clear_layout(layout):
    """Empty a layout. Widgets are detached (setParent(None)) as well as deleteLater()'d: the
    tick pump's processEvents() does not run deferred deletes, so a deleteLater alone leaves
    ghost widgets painted at their old position."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout():
            clear_layout(item.layout())


def confirm(parent, title, text):
    reply = QtWidgets.QMessageBox.question(
        parent, title, text, QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No)
    return reply == QtWidgets.QMessageBox.Yes
