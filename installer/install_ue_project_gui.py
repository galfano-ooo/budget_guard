# -*- coding: utf-8 -*-
"""
Minimal-dependency GUI front end for install_ue_project.py (phase 4).

Stdlib-only (tkinter) so it runs on any system Python with zero extra installs.
Launched via install.bat, or directly:
    python installer/install_ue_project_gui.py

Flow: "Locate Project" opens a file picker for the target's .uproject (a typed
folder is resolved to its project root, or refused, by install_ue_project's
resolve_project_dir()); "Install to Project" runs the same
install() used by the CLI installer against that folder and streams its output
into the window - no console needed. That includes the PySide6 pip step for the
BudgetGuard Qt panel: the engine is auto-detected
from the .uproject, the optional Engine folder field overrides it (same as the
CLI's --engine), and the checkbox skips the step (--no-pyside). The install runs
on a worker thread so the window stays responsive during the ~250 MB download.
"""
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import install_ue_project as installer

_DONE = object()


class InstallerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BudgetGuard - UE Project Installer")
        self.resizable(False, False)
        self._queue = queue.Queue()
        self._worker = None

        pad = {"padx": 10, "pady": 6}

        tk.Label(self, text="UE project folder (contains the .uproject file):").grid(
            row=0, column=0, columnspan=3, sticky="w", **pad
        )

        self.path_var = tk.StringVar()
        self.path_entry = tk.Entry(self, textvariable=self.path_var, width=55)
        self.path_entry.grid(row=1, column=0, columnspan=2, sticky="we", padx=(10, 0), pady=6)

        tk.Button(self, text="Locate Project...", command=self.locate_project).grid(
            row=1, column=2, sticky="e", padx=(6, 10), pady=6
        )

        tk.Label(self, text="Engine folder (optional - blank = detect from the .uproject):").grid(
            row=2, column=0, columnspan=3, sticky="w", padx=10, pady=(6, 0)
        )
        self.engine_var = tk.StringVar()
        tk.Entry(self, textvariable=self.engine_var, width=55).grid(
            row=3, column=0, columnspan=2, sticky="we", padx=(10, 0), pady=6
        )
        tk.Button(self, text="Locate Engine...", command=self.locate_engine).grid(
            row=3, column=2, sticky="e", padx=(6, 10), pady=6
        )

        self.pyside_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            self, variable=self.pyside_var,
            text="Install PySide6 with UE's Python (BudgetGuard panel; skipped if already there)",
        ).grid(row=4, column=0, columnspan=3, sticky="w", padx=6, pady=(0, 4))

        self.install_btn = tk.Button(
            self, text="Install to Project", command=self.install, height=2, bg="#2e7d32", fg="white"
        )
        self.install_btn.grid(row=5, column=0, columnspan=3, sticky="we", padx=10, pady=(6, 4))

        self.status = tk.Text(self, width=90, height=16, state="disabled", wrap="word")
        self.status.grid(row=6, column=0, columnspan=3, sticky="we", padx=10, pady=(4, 10))

        self.log("Linked repo folder: {}".format(installer.REPO_DIR))

    def log(self, text):
        self.status.configure(state="normal")
        self.status.insert("end", text + "\n")
        self.status.see("end")
        self.status.configure(state="disabled")

    def locate_project(self):
        # Picking the .uproject file itself leaves no room for a wrong (e.g. Content/) folder.
        chosen = filedialog.askopenfilename(
            title="Locate the UE project (.uproject file)",
            filetypes=[("Unreal project", "*.uproject")],
        )
        if chosen:
            self.path_var.set(os.path.normpath(os.path.dirname(chosen)))

    def locate_engine(self):
        chosen = filedialog.askdirectory(title="Locate the engine root (the folder holding Engine/)")
        if chosen:
            self.engine_var.set(chosen)

    def install(self):
        if self._worker is not None:
            return
        project_dir = self.path_var.get().strip()
        if not project_dir:
            messagebox.showwarning("No project selected", "Click 'Locate Project...' first.")
            return
        try:
            project_dir = installer.resolve_project_dir(project_dir, log=self.log)
        except SystemExit as exc:
            messagebox.showerror("No UE project here", str(exc))
            return
        self.path_var.set(project_dir)
        engine_dir = self.engine_var.get().strip() or None
        if engine_dir and not os.path.isdir(engine_dir):
            messagebox.showerror("Invalid folder", "Engine folder is not a directory:\n{}".format(engine_dir))
            return

        self.install_btn.configure(state="disabled", text="Installing...")
        self._worker = threading.Thread(
            target=self._run, args=(project_dir, engine_dir, self.pyside_var.get()), daemon=True
        )
        self._worker.start()
        self.after(100, self._drain)

    def _run(self, project_dir, engine_dir, pyside):
        # Worker thread: never touches Tk directly, only the queue.
        try:
            installer.install(project_dir, dry_run=False, engine_dir=engine_dir, pyside=pyside,
                              log=self._queue.put)
            self._queue.put((_DONE, None))
        except BaseException as exc:  # SystemExit from install() included
            self._queue.put((_DONE, exc))

    def _drain(self):
        try:
            while True:
                item = self._queue.get_nowait()
                if isinstance(item, tuple) and item and item[0] is _DONE:
                    self._finish(project_dir=self.path_var.get().strip(), exc=item[1])
                    return
                self.log(str(item))
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def _finish(self, project_dir, exc):
        self._worker = None
        self.install_btn.configure(state="normal", text="Install to Project")
        if exc is None:
            self.log("Done. Restart the Unreal Editor for the change to take effect.")
            messagebox.showinfo("Install complete", "Installed into:\n{}".format(project_dir))
        else:
            self.log("ERROR: {}".format(exc))
            messagebox.showerror("Install failed", str(exc))


def main():
    app = InstallerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
