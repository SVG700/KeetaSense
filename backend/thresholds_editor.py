"""Read, validate and save the decision thresholds in config/pests.yaml.

Used by the dashboard's Settings page so IIHR mentors' values can be entered
during the event. Saving:
  1. validates every value (no empty, negative or absurd numbers),
  2. copies the old file to config/backups/pests_<date_time>.yaml,
  3. rewrites ONLY the edited lines, so every other line and comment stays as it was,
  4. replaces each edited line's comment "PLACEHOLDER - confirm with IIHR mentor"
     with "Confirmed with IIHR mentor on <date>".
The caller then reloads the config and recalculates the decisions.
"""
from __future__ import annotations

import re
import shutil
from datetime import date, datetime
from pathlib import Path

import yaml

from backend.settings import pests_yaml_path

PLACEHOLDER = "PLACEHOLDER - confirm with IIHR mentor"
CONFIRMED_PREFIX = "Confirmed with IIHR mentor on"

# What can be edited, with simple sanity limits (min is exclusive when min_exclusive=True)
FIELDS = {
    "base_temp_c": {"label": "Base temperature", "unit": "°C", "type": "float", "min": 0, "min_exclusive": False,
                    "max": 40, "help": "Below this temperature the pest does not develop (degree-day base)."},
    "degree_days_per_generation": {"label": "Degree-days per generation", "unit": "°C·days", "type": "float",
                                   "min": 0, "min_exclusive": True, "max": 5000,
                                   "help": "Accumulated warmth for one generation (egg to adult)."},
    "action_threshold_per_day": {"label": "Action threshold", "unit": "pests / day", "type": "float", "min": 0,
                                 "min_exclusive": True, "max": 10000,
                                 "help": "Average pests per tape section (day) at which action is needed."},
    "spray_ratio": {"label": "Spray ratio", "unit": "pests per predator", "type": "float", "min": 0,
                    "min_exclusive": True, "max": 1000,
                    "help": "At or above this ratio predators are not keeping pace -> SPRAY; below it -> RELEASE BIOCONTROL."},
    "rolling_window_days": {"label": "Rolling window", "unit": "days", "type": "int", "min": 1, "min_exclusive": False,
                            "max": 30, "help": "How many recent tape sections are averaged."},
}

_LINE = re.compile(r"^(?P<indent>\s+)(?P<key>\w+):\s*(?P<value>[^#\s]+)\s*(?:#\s*(?P<comment>.*))?$")


def _blocks(lines: list[str]) -> dict[str, dict[str, int]]:
    """Map pest -> {field: line index} for the "thresholds:" section."""
    out: dict[str, dict[str, int]] = {}
    in_thresholds, pest = False, None
    for i, line in enumerate(lines):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            in_thresholds = line.strip().startswith("thresholds:")
            pest = None
            continue
        if not in_thresholds:
            continue
        if indent == 2 and line.strip().endswith(":"):
            pest = line.strip()[:-1]
            out[pest] = {}
        elif pest and indent >= 4:
            m = _LINE.match(line.rstrip("\r\n"))
            if m and m.group("key") in FIELDS:
                out[pest][m.group("key")] = i
    return out


def status_of(comment: str | None) -> tuple[str, str | None]:
    """("placeholder" | "confirmed" | "unmarked", confirmed date)."""
    comment = comment or ""
    if comment.startswith(CONFIRMED_PREFIX):
        return "confirmed", comment[len(CONFIRMED_PREFIX):].strip() or None
    if "PLACEHOLDER" in comment:
        return "placeholder", None
    return "unmarked", None


def read_thresholds(path: Path | None = None) -> dict:
    path = path or pests_yaml_path()
    lines = path.read_text(encoding="utf-8").splitlines()
    data = yaml.safe_load("\n".join(lines))["thresholds"]
    pests = {}
    for pest, fields in _blocks(lines).items():
        pests[pest] = {}
        for key, idx in fields.items():
            status, confirmed_on = status_of(_LINE.match(lines[idx]).group("comment"))
            pests[pest][key] = {**FIELDS[key], "value": data[pest][key], "status": status,
                                "confirmed_on": confirmed_on}
    return pests


def validate(values: dict) -> tuple[dict, dict]:
    """Return (clean values, errors). Errors map field -> message for the form."""
    clean, errors = {}, {}
    for key, raw in values.items():
        spec = FIELDS.get(key)
        if spec is None:
            errors[key] = "Unknown setting."
            continue
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            errors[key] = "Required - enter a number."
            continue
        try:
            num = float(raw)
        except (TypeError, ValueError):
            errors[key] = "Must be a number."
            continue
        if num != num or num in (float("inf"), float("-inf")):
            errors[key] = "Must be a number."
            continue
        if spec["type"] == "int":
            if num != int(num):
                errors[key] = "Must be a whole number."
                continue
            num = int(num)
        if num < 0:
            errors[key] = "Cannot be negative."
        elif spec["min_exclusive"] and num <= spec["min"]:
            errors[key] = f"Must be greater than {spec['min']}."
        elif num < spec["min"]:
            errors[key] = f"Must be at least {spec['min']}."
        elif num > spec["max"]:
            errors[key] = f"Must be at most {spec['max']} (is this a typo?)."
        else:
            clean[key] = num
    return clean, errors


def _fmt(v, old_text: str) -> str:
    """Write the number in the same style as before: "25" stays whole, "10.0" keeps a decimal."""
    if float(v).is_integer():
        return str(int(v)) if "." not in old_text else f"{float(v):.1f}"
    return f"{v:.4f}".rstrip("0").rstrip(".")


def save(pest: str, values: dict, confirm_unchanged: bool = False, path: Path | None = None,
         today: date | None = None) -> dict:
    """Validate and write values for one pest. Raises ValueError({"errors": ...}) on bad input."""
    path = path or pests_yaml_path()
    clean, errors = validate(values)
    current = read_thresholds(path)
    if pest not in current:
        raise ValueError({"errors": {"_": f"Unknown pest '{pest}'."}})
    missing = [k for k in FIELDS if k in current[pest] and k not in values]
    for k in missing:
        errors[k] = "Required - enter a number."
    if errors:
        raise ValueError({"errors": errors})

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    index = _blocks([l.rstrip("\r\n") for l in lines])[pest]
    stamp = f"{CONFIRMED_PREFIX} {(today or date.today()).isoformat()}"
    changed, confirmed = [], []
    for key, value in clean.items():
        old = current[pest][key]
        is_changed = float(old["value"]) != float(value)
        if not is_changed and not (confirm_unchanged and old["status"] != "confirmed"):
            continue
        idx = index[key]
        m = _LINE.match(lines[idx].rstrip("\r\n"))
        ending = "\r\n" if lines[idx].endswith("\r\n") else "\n"
        lines[idx] = f"{m.group('indent')}{key}: {_fmt(value, m.group('value'))}  # {stamp}{ending}"
        (changed if is_changed else confirmed).append(key)

    backup = None
    if changed or confirmed:
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(exist_ok=True)
        backup = backup_dir / f"{path.stem}_{datetime.now():%Y%m%d_%H%M%S_%f}.yaml"
        shutil.copy2(path, backup)
        text = "".join(lines)
        yaml.safe_load(text)                       # never write a file that no longer parses
        tmp = path.with_suffix(".yaml.tmp")
        tmp.write_text(text, encoding="utf-8", newline="")
        tmp.replace(path)                          # atomic: no half-written config
    return {"pest": pest, "changed": changed, "confirmed_unchanged": confirmed,
            "backup": str(backup) if backup else None}


def list_backups(path: Path | None = None) -> list[str]:
    path = path or pests_yaml_path()
    folder = path.parent / "backups"
    return sorted((p.name for p in folder.glob(f"{path.stem}_*.yaml")), reverse=True) if folder.exists() else []
