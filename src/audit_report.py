"""
audit_report.py
------------------------------------------------------------------------------
Collects findings from the rule modules and prints the categorized console
log: one section per asset category (Textures / Meshes / Materials), each
finding tagged FAIL/WARN/INFO, with per-category and overall summaries.

INFO-severity findings mean "a rule couldn't be evaluated — the expected
engine API wasn't found," not an actual content problem. They're printed
but kept out of the FAIL/WARN pass/fail tally.
------------------------------------------------------------------------------
"""

import csv
import json
import os
from collections import namedtuple, defaultdict
from datetime import datetime, timezone

Finding = namedtuple(
    "Finding", ["asset_path", "asset_class", "category", "rule", "severity", "message"]
)

SEVERITY_ORDER = ["FAIL", "WARN", "INFO"]
SEVERITY_TAG = {"FAIL": "[FAIL]", "WARN": "[WARN]", "INFO": "[INFO]"}

CATEGORIES = ["Textures", "Meshes", "Materials"]


class Report:
    def __init__(self, scope_label=""):
        self.scope_label = scope_label
        self.findings = []                     # list[Finding]
        self.scanned = defaultdict(dict)        # category -> {asset_path: {"asset_class", "tier"}}
        self.untagged = defaultdict(set)        # category -> set(asset_path)
        self.skipped_sublevels = []

    def add(self, finding):
        self.findings.append(finding)

    def mark_scanned(self, category, asset_path, asset_class=None, tier=None):
        self.scanned[category][asset_path] = {"asset_class": asset_class, "tier": tier}

    def mark_untagged(self, category, asset_path):
        self.untagged[category].add(asset_path)

    def note_skipped_sublevel(self, level_name):
        self.skipped_sublevels.append(level_name)

    def summary(self):
        """Same per-asset FAIL/WARN/INFO/OK tally print_console() prints, as data (the panel's
        Audit tab): {"categories": {cat: {total, FAIL, WARN, INFO, OK, untagged}},
        "overall": {FAIL, WARN, INFO, OK}, "total": n}."""
        categories = {}
        overall = defaultdict(int)
        for category in CATEGORIES:
            entries = [f for f in self.findings if f.category == category]
            total = len(self.scanned.get(category, {}))
            fail = {f.asset_path for f in entries if f.severity == "FAIL"}
            warn = {f.asset_path for f in entries if f.severity == "WARN"} - fail
            info = {f.asset_path for f in entries if f.severity == "INFO"} - fail - warn
            ok = max(total - len(fail) - len(warn) - len(info), 0)
            categories[category] = {"total": total, "FAIL": len(fail), "WARN": len(warn),
                                    "INFO": len(info), "OK": ok,
                                    "untagged": len(self.untagged.get(category, ()))}
            for key, n in (("FAIL", len(fail)), ("WARN", len(warn)), ("INFO", len(info)), ("OK", ok)):
                overall[key] += n
        return {"categories": categories, "overall": dict(overall),
                "total": sum(c["total"] for c in categories.values())}

    def print_console(self):
        print("=" * 78)
        print(f"BUDGETGUARD AUDIT — {self.scope_label}")
        print("=" * 78)

        if self.skipped_sublevels:
            print(f"\nSkipped (not loaded): {', '.join(self.skipped_sublevels)}")

        overall = defaultdict(int)

        for category in CATEGORIES:
            entries = [f for f in self.findings if f.category == category]
            scanned_paths = self.scanned.get(category, {})
            total = len(scanned_paths)

            fail_paths = {f.asset_path for f in entries if f.severity == "FAIL"}
            warn_paths = {f.asset_path for f in entries if f.severity == "WARN"} - fail_paths
            info_paths = (
                {f.asset_path for f in entries if f.severity == "INFO"}
                - fail_paths - warn_paths
            )
            ok_count = max(total - len(fail_paths) - len(warn_paths) - len(info_paths), 0)

            print(f"\n{category.upper()} AUDIT — {total} asset(s) scanned")
            print("-" * 78)
            for f in sorted(entries, key=lambda f: SEVERITY_ORDER.index(f.severity)):
                print(f"{SEVERITY_TAG[f.severity]} {f.asset_path} — {f.message}")

            print(
                f"Summary: {len(fail_paths)} FAIL / {len(warn_paths)} WARN / "
                f"{len(info_paths)} INFO / {ok_count} OK"
            )
            untagged = self.untagged.get(category, set())
            if untagged:
                print(f"  ({len(untagged)} asset(s) untagged — used the default tier budget)")

            overall["FAIL"] += len(fail_paths)
            overall["WARN"] += len(warn_paths)
            overall["INFO"] += len(info_paths)

        print("\n" + "=" * 78)
        print(
            f"OVERALL: {overall['FAIL']} FAIL / {overall['WARN']} WARN / "
            f"{overall['INFO']} INFO (unverifiable — check API)"
        )
        print("=" * 78)

    def _rows(self):
        """One row per scanned asset: worst severity + all messages joined.
        Feeds both export_csv and export_json so the two stay in sync."""
        findings_by_path = defaultdict(list)
        for f in self.findings:
            findings_by_path[f.asset_path].append(f)

        rows = []
        for category in CATEGORIES:
            untagged = self.untagged.get(category, set())
            for asset_path, info in self.scanned.get(category, {}).items():
                entries = findings_by_path.get(asset_path, [])
                if entries:
                    severity = min(
                        (e.severity for e in entries), key=SEVERITY_ORDER.index
                    )
                else:
                    severity = "OK"
                messages = " | ".join(
                    f"{SEVERITY_TAG[e.severity]} {e.message}"
                    for e in sorted(entries, key=lambda e: SEVERITY_ORDER.index(e.severity))
                )
                rows.append({
                    "category": category,
                    "asset_path": asset_path,
                    "asset_class": info.get("asset_class") or "",
                    "tier": info.get("tier") or "",
                    "untagged": asset_path in untagged,
                    "severity": severity,
                    "messages": messages,
                })
        return rows

    def export_csv(self, filepath):
        """Write one row per scanned asset (Category/AssetPath/AssetClass/
        Tier/Untagged/Severity/Messages) — for spreadsheet review outside
        the UE5 console (e.g. a meeting handout)."""
        rows = self._rows()
        fieldnames = ["category", "asset_path", "asset_class", "tier", "untagged", "severity", "messages"]
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        unreal_log(f"[Report] Wrote {len(rows)} row(s) to {filepath}")
        return filepath

    def export_json(self, filepath):
        """Write the same per-asset rows as export_csv, plus the scope label
        and a generation timestamp, as structured JSON. The timestamp lets
        the dashboard (exports/dashboard_template.html) label and order
        runs when comparing two exports."""
        payload = {
            "scope_label": self.scope_label,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "assets": self._rows(),
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        unreal_log(f"[Report] Wrote {len(payload['assets'])} asset row(s) to {filepath}")
        return filepath

    def export_all(self, directory, basename="audit_asis"):
        """Writes CSV+JSON to <directory>/<basename>.{csv,json} (the
        always-current "latest" pair generate_dashboard.js / the
        panel's actions expect at a fixed name), PLUS a timestamped archive copy
        of each under <directory>/history/ — so every run leaves a
        distinct file behind instead of silently overwriting the last
        one, and the dashboard's Compare mode has actual history to load.

        Returns (csv_latest, json_latest, csv_dated, json_dated)."""
        history_dir = os.path.join(directory, "history")
        os.makedirs(directory, exist_ok=True)
        os.makedirs(history_dir, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_latest = os.path.join(directory, f"{basename}.csv")
        json_latest = os.path.join(directory, f"{basename}.json")
        csv_dated = os.path.join(history_dir, f"{basename}_{ts}.csv")
        json_dated = os.path.join(history_dir, f"{basename}_{ts}.json")

        self.export_csv(csv_latest)
        self.export_csv(csv_dated)
        self.export_json(json_latest)
        self.export_json(json_dated)

        return csv_latest, json_latest, csv_dated, json_dated


def unreal_log(message):
    try:
        import unreal
        unreal.log(message)
    except ImportError:
        print(message)
