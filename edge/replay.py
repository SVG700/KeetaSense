"""Record every edge cycle, and replay recordings when the hardware fails on stage.

RECORDING (on by default, RECORD=1): each cycle saves the tape image plus what
was measured (detections, detector, temperature, humidity) into
    edge/data/recording/<trap id>/images/...
    edge/data/recording/<trap id>/manifest.jsonl    (one JSON line per cycle)

REPLAY: python -m edge.main --demo --replay <folder>
reads such a folder in order (and loops), and sends each entry to the backend as
a NEW tape section, exactly like a live cycle - no camera, motor or sensor needed.
The backend stores it with source="replay" and the dashboard labels it "Replay".

Copy a good recording (e.g. from a rehearsal with the real trap) into
demo/replay_real/ before the event. demo/replay/ ships with a SYNTHETIC pack
recorded from the mock trap, so replay works out of the box.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class ReplayEntry:
    image: Path
    detections: list | None
    detector_mode: str | None
    temperature_c: float | None
    humidity_pct: float | None
    simulated: bool
    captured_at: str | None


class Recorder:
    def __init__(self, folder: Path):
        self.folder = folder
        (folder / "images").mkdir(parents=True, exist_ok=True)
        self.manifest = folder / "manifest.jsonl"

    def record(self, image_path: Path, payload: dict, climate: tuple[float, float] | None) -> None:
        dest = self.folder / "images" / image_path.name
        shutil.copy2(image_path, dest)
        entry = {
            "image": f"images/{dest.name}",
            "trap_id": payload["trap_id"],
            "captured_at": payload["timestamp"],
            "detections": payload.get("detections"),
            "detector_mode": payload.get("detector_mode"),
            "temperature_c": climate[0] if climate else None,
            "humidity_pct": climate[1] if climate else None,
            "simulated": payload.get("simulated", False),
            "source": payload.get("source", "live"),
        }
        with open(self.manifest, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


def load_manifest(folder: Path) -> list[ReplayEntry]:
    """Read manifest.jsonl; entries whose image is missing are skipped."""
    manifest = folder / "manifest.jsonl"
    if not manifest.exists():
        raise FileNotFoundError(f"{manifest} not found - not a replay folder (see edge/replay.py)")
    entries = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        img = folder / e["image"]
        if not img.exists():
            continue
        entries.append(ReplayEntry(img, e.get("detections"), e.get("detector_mode"), e.get("temperature_c"),
                                   e.get("humidity_pct"), bool(e.get("simulated", False)), e.get("captured_at")))
    if not entries:
        raise ValueError(f"{manifest} has no usable entries")
    return entries


class ReplaySource:
    """Hands out recorded entries in order, looping forever."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.entries = load_manifest(folder)
        self.index = 0

    def next(self) -> ReplayEntry:
        e = self.entries[self.index % len(self.entries)]
        self.index += 1
        return e


def make_pack(recording: Path, out: Path, note: str = "") -> int:
    """Copy a recording folder into a self-contained replay pack (e.g. demo/replay_real)."""
    entries = load_manifest(recording)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(recording, out)
    (out / "README.txt").write_text(
        f"KeetaSense replay pack, made {datetime.now():%Y-%m-%d %H:%M} from {recording}.\n{note}\n"
        "Use: python -m edge.main --demo --replay <this folder>\n", encoding="utf-8")
    return len(entries)


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Turn a recording into a replay pack.")
    ap.add_argument("recording", help="e.g. edge/data/recording/T1-polyhouse")
    ap.add_argument("out", help="e.g. demo/replay_real")
    ap.add_argument("--note", default="")
    args = ap.parse_args()
    n = make_pack(Path(args.recording), Path(args.out), args.note)
    print(f"[replay] pack with {n} cycles -> {args.out}")


if __name__ == "__main__":
    main()
