"""Kannada review helper: export the alert texts to a spreadsheet and import the corrections.

Our Kannada alert texts were machine-drafted. A native Kannada speaker should
check them before farmers receive them.

1. Export (creates docs/kannada_review.csv - opens in Excel / Google Sheets / LibreOffice):
       python -m backend.kannada_review export
   Columns: key, English text, Kannada text, reviewer correction
2. The reviewer fills in "reviewer correction" ONLY where the Kannada is wrong:
     - write the full corrected Kannada text, or
     - write OK if the Kannada text is correct as it is, or
     - leave it empty if not reviewed.
   Keep every {placeholder} exactly as it is (e.g. {trap_name}, {pests_per_day}) -
   they are replaced by numbers and names when the alert is sent.
3. Import:
       python -m backend.kannada_review import docs/kannada_review.csv --reviewer "Name"
   Checks every correction (placeholders must match), keeps a .bak copy of each
   file it changes, writes the corrections into backend/alert_templates.yaml
   (and Kannada pest names into config/pests.yaml), and notes the reviewer and
   date at the top of the templates file. Restart the backend afterwards.

Rows by key prefix:
  (no prefix)        alert texts       backend/alert_templates.yaml
  advisory.<key>     advisory texts    backend/advisory_templates.yaml
  ui.<key>           dashboard texts   frontend/src/locales/strings.json
  pest_name.<class>  insect names      config/pests.yaml
The "status" column says "needs review" for every Kannada text that is new or
changed since the last export (information only; import ignores it).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from datetime import date
from pathlib import Path

import yaml

from backend.settings import ROOT, pests_yaml_path

TEMPLATES = Path(__file__).resolve().parent / "alert_templates.yaml"
ADVISORY = Path(__file__).resolve().parent / "advisory_templates.yaml"
UI_STRINGS = ROOT / "frontend" / "src" / "locales" / "strings.json"
DEFAULT_CSV = ROOT / "docs" / "kannada_review.csv"
COLUMNS = ["key", "English text", "Kannada text", "reviewer correction"]
STATUS = "status"
PEST_PREFIX = "pest_name."
ADVISORY_PREFIX = "advisory."
UI_PREFIX = "ui."
NEEDS_REVIEW = "needs review"
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def placeholders(text: str) -> set[str]:
    return set(_PLACEHOLDER.findall(text or ""))


def _yaml_rows(path: Path, prefix: str) -> list[dict]:
    t = yaml.safe_load(path.read_text(encoding="utf-8"))
    en, kn = t.get("en", {}), t.get("kn", {})
    return [{"key": prefix + k, "English text": en.get(k, ""), "Kannada text": kn.get(k, ""), "reviewer correction": ""}
            for k in list(dict.fromkeys([*en, *kn]))]


def _previous_kannada(csv_file: Path | None) -> dict[str, tuple[str, str]]:
    """{key: (Kannada text, status)} from the last export, to spot new or changed texts."""
    if not csv_file or not csv_file.exists():
        return {}
    with open(csv_file, encoding="utf-8-sig", newline="") as f:
        return {r["key"]: (r.get("Kannada text", ""), r.get(STATUS) or "machine-drafted") for r in csv.DictReader(f)}


def export_rows(templates_file: Path = TEMPLATES, pests_file: Path | None = None,
                advisory_file: Path | None = ADVISORY, ui_file: Path | None = UI_STRINGS,
                previous_csv: Path | None = None) -> list[dict]:
    rows = _yaml_rows(templates_file, "")
    if advisory_file and advisory_file.exists():
        rows += _yaml_rows(advisory_file, ADVISORY_PREFIX)
    if ui_file and ui_file.exists():
        for k, v in json.loads(ui_file.read_text(encoding="utf-8")).items():
            if not k.startswith("_"):
                rows.append({"key": UI_PREFIX + k, "English text": v.get("en", ""), "Kannada text": v.get("kn", ""),
                             "reviewer correction": ""})
    pests = yaml.safe_load((pests_file or pests_yaml_path()).read_text(encoding="utf-8"))
    for c in pests.get("classes", []):
        rows.append({"key": f"{PEST_PREFIX}{c['name']}", "English text": c.get("display_en", c["name"]),
                     "Kannada text": c.get("display_kn", ""), "reviewer correction": ""})
    old = _previous_kannada(previous_csv)
    for r in rows:
        prev = old.get(r["key"])
        r[STATUS] = prev[1] if prev and prev[0] == r["Kannada text"] else NEEDS_REVIEW
    return rows


def write_csv(rows: list[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig = UTF-8 with a BOM, so Excel shows Kannada correctly
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS + [STATUS], extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def read_corrections(csv_file: Path) -> tuple[dict, list[str], int]:
    """Return ({key: corrected text}, problems, number of rows marked OK)."""
    with open(csv_file, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            return {}, [f"CSV is missing column(s): {missing}"], 0
        corrections, problems, ok = {}, [], 0
        for n, row in enumerate(reader, start=2):
            fix = (row["reviewer correction"] or "").strip()
            if not fix:
                continue
            if fix.upper() == "OK":
                ok += 1
                continue
            key = row["key"].strip()
            want, got = placeholders(row["Kannada text"]), placeholders(fix)
            if want != got:
                problems.append(f"row {n} ({key}): placeholders must stay the same - expected "
                                f"{sorted(want) or 'none'}, found {sorted(got) or 'none'}")
                continue
            corrections[key] = fix.replace("\r\n", "\n")
    return corrections, problems, ok


class _BlockDumper(yaml.SafeDumper):
    """Write multi-line texts as readable YAML blocks ( | ) instead of one long quoted line."""


def _str(dumper, s):
    return dumper.represent_scalar("tag:yaml.org,2002:str", s, style="|" if "\n" in s else None)


_BlockDumper.add_representer(str, _str)


def apply_template_corrections(corrections: dict, templates_file: Path, reviewer: str, today: date) -> int:
    """Alert texts (keys without a prefix)."""
    changes = {k: v for k, v in corrections.items()
               if not k.startswith((PEST_PREFIX, ADVISORY_PREFIX, UI_PREFIX))}
    return _apply_yaml(changes, templates_file, reviewer, today)


def apply_advisory_corrections(corrections: dict, advisory_file: Path, reviewer: str, today: date) -> int:
    changes = {k[len(ADVISORY_PREFIX):]: v for k, v in corrections.items() if k.startswith(ADVISORY_PREFIX)}
    return _apply_yaml(changes, advisory_file, reviewer, today)


def apply_ui_corrections(corrections: dict, ui_file: Path) -> int:
    """Dashboard texts in frontend/src/locales/strings.json (rebuild the dashboard afterwards)."""
    changes = {k[len(UI_PREFIX):]: v for k, v in corrections.items() if k.startswith(UI_PREFIX)}
    if not changes:
        return 0
    data = json.loads(ui_file.read_text(encoding="utf-8"))
    unknown = [k for k in changes if k not in data]
    if unknown:
        raise ValueError(f"unknown dashboard text key(s): {unknown}")
    for k, v in changes.items():
        data[k]["kn"] = v
    shutil.copy2(ui_file, ui_file.with_name(ui_file.name + ".bak"))
    ui_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(changes)


def _apply_yaml(changes: dict, templates_file: Path, reviewer: str, today: date) -> int:
    t = yaml.safe_load(templates_file.read_text(encoding="utf-8"))
    unknown = [k for k in changes if k not in t.get("kn", {})]
    if unknown:
        raise ValueError(f"unknown template key(s): {unknown}")
    if not changes:
        return 0
    for k, v in changes.items():
        # keep the trailing newline style of block texts
        t["kn"][k] = v if not t["kn"][k].endswith("\n") or v.endswith("\n") else v + "\n"
    lines = templates_file.read_text(encoding="utf-8").splitlines()
    header = []
    for line in lines:                       # keep the comment block at the top of the file
        if line.startswith("#") or not line.strip():
            header.append(line)
        else:
            break
    header = [h for h in header if not h.startswith("# Kannada reviewed by")]
    while header and not header[-1].strip():
        header.pop()
    header.append(f"# Kannada reviewed by {reviewer} on {today.isoformat()} ({len(changes)} correction(s) imported).")
    body = yaml.dump(t, Dumper=_BlockDumper, allow_unicode=True, sort_keys=False, width=1000)
    shutil.copy2(templates_file, templates_file.with_name(templates_file.name + ".bak"))
    templates_file.write_text("\n".join(header) + "\n\n" + body, encoding="utf-8")
    yaml.safe_load(templates_file.read_text(encoding="utf-8"))   # must still be valid
    return len(changes)


def apply_pest_name_corrections(corrections: dict, pests_file: Path) -> int:
    """Replace display_kn lines in pests.yaml (line edit: keeps every comment)."""
    changes = {k[len(PEST_PREFIX):]: v for k, v in corrections.items() if k.startswith(PEST_PREFIX)}
    if not changes:
        return 0
    lines = pests_file.read_text(encoding="utf-8").splitlines(keepends=True)
    current, done = None, set()
    for i, line in enumerate(lines):
        m = re.match(r"^\s*-\s*name:\s*(\S+)", line)
        if m:
            current = m.group(1)
        elif current in changes and re.match(r"^\s+display_kn:", line):
            indent = line[:len(line) - len(line.lstrip())]
            ending = "\r\n" if line.endswith("\r\n") else "\n"
            lines[i] = f"{indent}display_kn: {changes[current]}{ending}"
            done.add(current)
    missing = set(changes) - done
    if missing:
        raise ValueError(f"no display_kn line found for: {sorted(missing)}")
    shutil.copy2(pests_file, pests_file.with_name(pests_file.name + ".bak"))
    pests_file.write_text("".join(lines), encoding="utf-8")
    yaml.safe_load(pests_file.read_text(encoding="utf-8"))
    return len(done)


def main() -> None:
    ap = argparse.ArgumentParser(description="Export/import the Kannada alert texts for review.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--out", default=str(DEFAULT_CSV))
    i = sub.add_parser("import")
    i.add_argument("csv", nargs="?", default=str(DEFAULT_CSV))
    i.add_argument("--reviewer", required=True, help="name of the Kannada reviewer")
    args = ap.parse_args()

    if args.cmd == "export":
        rows = export_rows(previous_csv=Path(args.out))
        write_csv(rows, Path(args.out))
        print(f"[kannada] exported {len(rows)} texts -> {args.out}")
        print("          Send it to a native Kannada speaker; then: python -m backend.kannada_review import "
              f"{args.out} --reviewer \"Name\"")
        return

    corrections, problems, ok = read_corrections(Path(args.csv))
    if problems:
        print("[kannada] NOT imported - fix these rows first:")
        for p in problems:
            print(f"   - {p}")
        raise SystemExit(1)
    today = date.today()
    try:
        n_templates = apply_template_corrections(corrections, TEMPLATES, args.reviewer, today)
        n_templates += apply_advisory_corrections(corrections, ADVISORY, args.reviewer, today)
        n_ui = apply_ui_corrections(corrections, UI_STRINGS)
        n_pests = apply_pest_name_corrections(corrections, pests_yaml_path())
    except ValueError as err:
        raise SystemExit(f"[kannada] NOT imported: {err}")
    if n_ui:
        print(f"[kannada] {n_ui} dashboard text(s) updated - rebuild: npm --prefix frontend run build")
    print(f"[kannada] imported {n_templates} template correction(s) and {n_pests} pest name correction(s); "
          f"{ok} text(s) marked OK by {args.reviewer}.")
    if n_templates or n_pests:
        print("[kannada] old files kept as .bak. Restart the backend to use the new texts.")


if __name__ == "__main__":
    main()
