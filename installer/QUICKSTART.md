# BudgetGuard — install into a UE project

1. Get this repo on your machine (clone or unzip) and keep it where it is — the project is *linked* to it, nothing is copied.
2. Double-click `installer/install.bat`, pick the project's `.uproject`, click **Install to Project**.
   (CLI: `python installer/install_ue_project.py "D:/MyGame" [--dry-run] [--engine "D:/UE_5.7"] [--no-pyside] [--uninstall]`)
3. Restart the Editor, open **Tools → BudgetGuard**.

What it does: adds a managed block to `<Project>/Content/Python/init_unreal.py` (repo dir on `sys.path` + menu entry), enables the Python Editor Script Plugin (`.uproject.bak` written first), pip-installs PySide6 with UE's own Python into `Content/Python/Lib/site-packages`.

- **Update**: `git pull` (or replace the repo folder). Re-run the installer only if the repo moved.
- **Remove**: `--uninstall` strips the managed block.
- **Old copy-model install?** Delete the stale `audit_*.py`, `budgetguard_ui/`, etc. from `Content/Python` — they'd shadow the repo (the installer warns).
- Optional: Node.js on PATH for the HTML dashboard.
