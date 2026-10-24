"""Shared helpers: project paths and the insect class list from config/pests.yaml.

Every part of the system (converter, synthetic generator, detector, backend)
asks THIS module which classes exist and whether each one is a pest or a
predator, so the mapping lives in exactly one place: config/pests.yaml.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

# Project root = the folder that contains ml/, backend/, config/ ...
ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
PESTS_YAML = CONFIG_DIR / "pests.yaml"


def pests_yaml_path() -> Path:
    """config/pests.yaml, or KEETA_PESTS_YAML (tests point this at a temporary copy)."""
    return Path(os.environ.get("KEETA_PESTS_YAML", str(PESTS_YAML)))


@dataclass
class InsectClass:
    """One insect class as described in pests.yaml."""
    id: int                 # YOLO class id (position in the list)
    name: str               # canonical name, e.g. "whitefly"
    category: str           # "pest" or "predator"
    display_en: str = ""
    display_kn: str = ""
    aliases: list[str] = field(default_factory=list)
    synthetic_shape: str = "round"   # shape used by the synthetic generator
    confidence_threshold: float | None = None  # per-class minimum confidence (optional)


@lru_cache(maxsize=1)
def load_pests_config() -> dict:
    """Read config/pests.yaml once and cache it (reload_config() clears the cache)."""
    with open(pests_yaml_path(), encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_classes() -> list[InsectClass]:
    """All classes in YOLO id order."""
    classes = []
    for i, c in enumerate(load_pests_config()["classes"]):
        classes.append(InsectClass(
            id=i,
            name=c["name"],
            category=c["category"],
            display_en=c.get("display_en", c["name"]),
            display_kn=c.get("display_kn", ""),
            aliases=[str(a) for a in c.get("aliases", [])],
            synthetic_shape=c.get("synthetic_shape", "round"),
            confidence_threshold=(float(c["confidence_threshold"])
                                  if c.get("confidence_threshold") is not None else None),
        ))
    return classes


def class_names() -> list[str]:
    return [c.name for c in get_classes()]


def category_of(class_name: str) -> str:
    """Return "pest", "predator" or "unknown" for a class name or alias."""
    canonical = resolve_alias(class_name)
    for c in get_classes():
        if c.name == canonical:
            return c.category
    return "unknown"


def resolve_alias(raw_label: str) -> str | None:
    """Map a raw dataset label (e.g. "WF") to its canonical name ("whitefly").

    Matching is case-insensitive. Returns None if the label is not known.
    """
    key = raw_label.strip().lower()
    for c in get_classes():
        if key == c.name.lower() or key in (a.lower() for a in c.aliases):
            return c.name
    return None
