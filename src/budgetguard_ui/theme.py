# -*- coding: utf-8 -*-
"""
Colours / type / spacing for the BudgetGuard Qt panel.

TOKENS mirrors the `budgetguard-ui` token set of the approved Penpot design (file "Nuovo File 1",
page "Panel"), which itself mirrors greybox_gen's theme.py. This file is the only place a hex
value is written down: widgets opt into non-default looks through dynamic properties
(role / state / tone), never inline styles.
"""

TOKENS = {
    "color.bg.window": "#151515",
    "color.bg.panel": "#1C1C1C",
    "color.bg.surface": "#262626",
    "color.bg.input": "#0F0F0F",
    "color.bg.hover": "#303030",
    "color.border.default": "#383838",
    "color.border.focus": "#0070E0",
    "color.text.primary": "#E0E0E0",
    "color.text.secondary": "#9A9A9A",
    "color.text.disabled": "#5A5A5A",
    "color.text.onAccent": "#FFFFFF",
    "color.accent.default": "#0070E0",
    "color.accent.hover": "#1A8CFF",
    "color.accent.disabled": "#243447",
    "color.state.success": "#4FB84F",
    "color.state.successBg": "#16301A",
    "color.state.error": "#E04848",
    "color.state.errorBg": "#3A1C1C",
    "color.state.errorText": "#F08080",
    "color.state.errorHover": "#4A2222",
    "color.state.warning": "#E0A020",
    "color.state.warningBg": "#2E2410",
    "color.toggle.on": "#2A4A6E",
    "font.size.caption": 11,
    "font.size.body": 12,
    "font.size.label": 13,
    "font.size.title": 16,
    "font.size.stat": 22,
    "font.family.ui": "Roboto",
    "font.family.mono": "Roboto Mono",
    "space.xs": 4,
    "space.sm": 8,
    "space.md": 12,
    "space.lg": 16,
    "radius.sm": 3,
    "radius.md": 4,
    "size.control.h": 28,
    "size.window.w": 1100,
    "size.window.h": 720,
    "size.compact.w": 420,
    "size.compact.h": 640,
    "size.nav.w": 48,
    "size.nav.btn": 36,
    "size.header.h": 56,
    "size.status.h": 28,
}

# Roboto may not be installed on the machine running the Editor; Qt takes the first family it has.
UI_FONT_STACK = '"%s", "Segoe UI", sans-serif' % TOKENS["font.family.ui"]
MONO_FONT_STACK = '"%s", "Consolas", monospace' % TOKENS["font.family.mono"]

# severity / tone -> (foreground token, background token); drives chips and table cells
TONES = {
    "FAIL": "error", "WARN": "warning", "INFO": "neutral", "OK": "success",
    "error": "error", "warning": "warning", "success": "success", "info": "info", "neutral": "neutral",
}


def t(key):
    return TOKENS[key]


def qss(compact=False):
    c = dict(TOKENS)
    if compact:   # smaller type + controls for the narrow panel
        c.update({"size.control.h": 24, "font.size.body": 11, "font.size.caption": 10,
                  "font.size.label": 12, "font.size.title": 14, "font.size.stat": 18})
    return """
* {{ font-family: {ui}; font-size: {body}px; color: {text}; }}
QWidget#BudgetGuardWindow, QWidget#Body {{ background: {window}; }}
QScrollArea {{ background: {window}; border: none; }}
QScrollArea > QWidget > QWidget {{ background: {window}; }}

/* ---- chrome ---- */
QFrame#Header {{ background: {panel}; border-bottom: 1px solid {border}; }}
QFrame#NavRail {{ background: {panel}; border-right: 1px solid {border}; }}
QLabel#Brand {{ font-size: {title}px; font-weight: bold; }}
QFrame#StatusLine {{ background: {window}; border-top: 1px solid {border}; }}
QFrame#StatusLine[state="error"] {{ background: {error_bg}; border-top: 1px solid {error}; }}
QFrame#StatusLine QLabel {{ background: transparent; font-family: {mono}; font-size: {caption}px; }}
QFrame#StatusLine[state="error"] QLabel#StatusText {{ color: {error_text}; }}
QLabel#StatusDot {{ font-size: 10px; color: {text2}; }}
QFrame#StatusLine[state="ok"] QLabel#StatusDot {{ color: {success}; }}
QFrame#StatusLine[state="busy"] QLabel#StatusDot {{ color: {warning}; }}
QFrame#StatusLine[state="error"] QLabel#StatusDot {{ color: {error}; }}
QPushButton[role="navBtn"] {{
    background: transparent; border: 1px solid transparent; border-radius: {r_md}px; padding: 0;
    min-height: {nav_btn}px; max-height: {nav_btn}px; min-width: {nav_btn}px; max-width: {nav_btn}px;
}}
QPushButton[role="navBtn"]:hover {{ background: {hover}; }}
QPushButton[role="navBtn"]:checked {{ background: {toggle_on}; border-color: {accent}; }}
QFrame#SaveBar {{ background: {toggle_on}; border-top: 1px solid {accent}; }}
QFrame#SaveBar QLabel {{ background: transparent; }}
QFrame#Banner {{ background: {warning_bg}; border: 1px solid {warning}; border-radius: {r_md}px; }}
QFrame#Banner QLabel {{ background: transparent; color: {warning}; }}

/* ---- sections / cards ---- */
QFrame[role="section"] {{
    background: {panel}; border: 1px solid {border}; border-radius: {r_md}px;
}}
QFrame[role="section"] QLabel {{ background: transparent; }}
QLabel[role="sectionTitle"] {{ color: {text2}; font-size: {caption}px; font-weight: bold; }}
QLabel[role="fieldLabel"] {{ color: {text2}; font-size: {caption}px; }}
QLabel[role="hint"] {{ color: {text2}; font-size: {caption}px; }}
QLabel[role="optionTitle"] {{ font-size: {label}px; font-weight: bold; }}
QLabel[role="mono"] {{ font-family: {mono}; font-size: {caption}px; }}
QLabel:disabled {{ color: {text_dis}; }}
QFrame[role="stat"], QFrame[role="tierCard"] {{
    background: {surface}; border: 1px solid {border}; border-radius: {r_md}px;
}}
QFrame[role="tierCard"] {{ background: {panel}; }}
QFrame[role="stat"] QLabel, QFrame[role="tierCard"] QLabel {{ background: transparent; }}
QLabel[role="statValue"] {{ font-family: {ui}; font-size: {stat}px; font-weight: bold; }}
QLabel[role="statValue"][tone="error"] {{ color: {error}; }}
QLabel[role="statValue"][tone="warning"] {{ color: {warning}; }}
QLabel[role="statValue"][tone="success"] {{ color: {success}; }}
QFrame[role="ruleRow"] {{
    background: {window}; border: 1px solid {border}; border-radius: {r_sm}px;
}}
QFrame[role="ruleRow"] QLabel {{ background: transparent; }}
QFrame[role="profileCard"] {{
    background: {surface}; border: 1px solid {border}; border-radius: {r_md}px;
}}
QFrame[role="profileCard"][state="active"] {{ background: {toggle_on}; border-color: {accent}; }}

/* ---- tables ---- */
QTableWidget {{
    background: {panel}; border: none; gridline-color: {border}; selection-background-color: {hover};
}}
QTableWidget::item {{ padding: 0 6px; border-bottom: 1px solid {border}; }}
QHeaderView::section {{
    background: {panel}; color: {text2}; border: none; padding: 4px 6px; font-weight: normal;
}}

/* ---- inputs ---- */
QLineEdit, QComboBox {{
    background: {input}; border: 1px solid {border}; border-radius: {r_sm}px;
    min-height: {ctl_h}px; max-height: {ctl_h}px; padding: 0 8px;
    selection-background-color: {accent};
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {focus}; }}
QLineEdit[state="over"], QComboBox[state="over"] {{ border-color: {accent}; }}
QLineEdit[state="err"] {{ border-color: {error}; }}
QLabel[role="hint"][tone="info"] {{ color: {accent_h}; }}
QLabel[role="hint"][tone="error"] {{ color: {error_text}; }}
QLineEdit:disabled, QComboBox:disabled {{ color: {text_dis}; }}
QComboBox QAbstractItemView {{
    background: {surface}; border: 1px solid {border}; selection-background-color: {hover};
}}

/* ---- scrollbars ---- */
QScrollBar:vertical {{ background: {window}; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {border}; border-radius: 4px; min-height: 30px; margin: 2px; }}
QScrollBar::handle:vertical:hover {{ background: {text_dis}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

/* ---- buttons ---- */
QPushButton {{
    background: {surface}; border: 1px solid {border}; border-radius: {r_sm}px;
    min-height: {ctl_h}px; padding: 0 {btn_pad}px; font-weight: bold;
}}
QPushButton:hover {{ background: {hover}; }}
QPushButton:disabled {{ color: {text_dis}; background: {panel}; }}
QPushButton[role="primary"] {{ background: {accent}; border-color: {accent}; color: {on_accent}; }}
QPushButton[role="primary"]:hover {{ background: {accent_h}; border-color: {accent_h}; }}
QPushButton[role="primary"]:disabled {{
    background: {accent_dis}; border-color: {accent_dis}; color: {text2};
}}
QPushButton[role="danger"] {{ background: {error_bg}; border-color: {error}; color: {error}; }}
QPushButton[role="danger"]:hover {{ background: {error_hover}; }}
QPushButton[toggle="true"] {{ font-weight: normal; color: {text2}; padding: 0 10px; }}
QPushButton[toggle="true"]:checked {{
    background: {toggle_on}; border-color: {accent}; color: {text};
}}

/* ---- chips ---- */
QLabel[role="chip"] {{ border-radius: 9px; padding: 2px 8px; font-size: {caption}px; }}
QLabel[role="chip"][tone="success"] {{
    color: {success}; border: 1px solid {success}; background: {success_bg};
}}
QLabel[role="chip"][tone="warning"] {{
    color: {warning}; border: 1px solid {warning}; background: {warning_bg};
}}
QLabel[role="chip"][tone="error"] {{
    color: {error_text}; border: 1px solid {error}; background: {error_bg};
}}
QLabel[role="chip"][tone="info"] {{
    color: {accent_h}; border: 1px solid {accent}; background: {toggle_on};
}}
QLabel[role="chip"][tone="neutral"] {{
    color: {text2}; border: 1px solid {border}; background: {surface};
}}
QLabel[role="chip"][tone="off"] {{
    color: {text_dis}; border: 1px solid {border}; background: {panel};
}}

/* ---- dialog ---- */
QDialog#SetupDialog {{ background: {panel}; }}
""".format(
        ui=UI_FONT_STACK, mono=MONO_FONT_STACK,
        body=c["font.size.body"], caption=c["font.size.caption"], label=c["font.size.label"],
        title=c["font.size.title"], stat=c["font.size.stat"],
        window=c["color.bg.window"], panel=c["color.bg.panel"], surface=c["color.bg.surface"],
        input=c["color.bg.input"], hover=c["color.bg.hover"],
        border=c["color.border.default"], focus=c["color.border.focus"],
        text=c["color.text.primary"], text2=c["color.text.secondary"], text_dis=c["color.text.disabled"],
        accent=c["color.accent.default"], accent_h=c["color.accent.hover"],
        accent_dis=c["color.accent.disabled"], on_accent=c["color.text.onAccent"],
        success=c["color.state.success"], success_bg=c["color.state.successBg"],
        error=c["color.state.error"], error_bg=c["color.state.errorBg"],
        error_text=c["color.state.errorText"], error_hover=c["color.state.errorHover"],
        warning=c["color.state.warning"], warning_bg=c["color.state.warningBg"],
        toggle_on=c["color.toggle.on"],
        r_sm=c["radius.sm"], r_md=c["radius.md"], ctl_h=c["size.control.h"],
        nav_btn=c["size.nav.btn"], btn_pad=8 if compact else 14,
    )


def repolish(widget):
    """Re-apply the stylesheet after a dynamic property (state/role/tone) changed."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
