# -*- coding: utf-8 -*-
"""
BudgetGuard Qt panel (PySide6, runs inside the UE5 Editor's Python).

    import budgetguard_ui
    budgetguard_ui.show()      # open / raise the panel
    budgetguard_ui.reload()    # re-import this package and reopen the panel

Needs PySide6 in the Editor's Python (phase 4's installer pip-installs it into
<Project>/Content/Python/Lib/site-packages). The panel only calls the backend through
budgetguard_ui/bridge.py.
"""
import importlib
import sys

# dependency order: leaves first
_SUBMODULES = ("theme", "bridge", "widgets", "chrome", "tabs", "settings_tab", "help_tab", "setup_dialog", "app")


def show():
    from . import app
    return app.show(on_reload=reload)


def close():
    from . import app
    app.close()


MENU_PARENT = "LevelEditor.MainMenu.Tools"
MENU_SECTION = "BudgetGuard"
MENU_ENTRY = "BudgetGuardPanel"
MENU_COMMAND = "import budgetguard_ui; budgetguard_ui.show()"


def register_menu():
    """Add Tools -> "BudgetGuard" to the Level Editor main menu. Idempotent: an entry with the
    same name in the same section is replaced, not duplicated. Called from the installer's
    managed block in <Project>/Content/Python/init_unreal.py (inside a try/except)."""
    import unreal
    menus = unreal.ToolMenus.get()
    menu = menus.find_menu(MENU_PARENT)
    if menu is None:
        # init_unreal.py can run before the Level Editor registered its menus;
        # extend_menu() queues the entry until that menu exists.
        menu = menus.extend_menu(MENU_PARENT)
    if menu is None:
        unreal.log_warning("[BudgetGuard] menu '%s' not found - Tools entry not added" % MENU_PARENT)
        return False
    menu.add_section(MENU_SECTION, unreal.Text("BudgetGuard"))
    entry = unreal.ToolMenuEntry(name=MENU_ENTRY, type=unreal.MultiBlockType.MENU_ENTRY)
    entry.set_label(unreal.Text("BudgetGuard"))
    entry.set_tool_tip(unreal.Text("Open the BudgetGuard content-budget panel"))
    entry.set_string_command(unreal.ToolMenuStringCommandType.PYTHON, "", MENU_COMMAND)
    menu.add_menu_entry(MENU_SECTION, entry)
    menus.refresh_all_widgets()
    unreal.log("[BudgetGuard] Tools -> BudgetGuard registered")
    return True


def reload():
    """Close the panel, reload every submodule of this package, reopen. Used by the Settings
    tab's 'Reload scripts' (after it reloaded the backend) and when iterating on the UI."""
    from . import app
    app.close()
    for name in _SUBMODULES:
        full = "%s.%s" % (__name__, name)
        if full in sys.modules:
            importlib.reload(sys.modules[full])
    return show()
