"""Get the real "Yellow Sticky Traps" dataset ready in ml/data/raw/.

The dataset lives on 4TU.ResearchData (Wageningen University & Research, CC0):
    https://data.4tu.nl/articles/_/12707066/1
It is one ~800 MB file, data.zip. 4TU's download links change, so we do NOT
download automatically; this script tells you what to do, then checks and
unpacks the file once you have placed it.

Steps:
  1. Open the link above in a browser and download data.zip.
  2. Put data.zip (or whatever archive you downloaded) into ml/data/raw/.
  3. Run:  python -m ml.download_4tu
     - checks the file size and MD5 checksum of data.zip (if it is that file)
     - extracts every .zip / .tar / .tar.gz archive in ml/data/raw/
       (also archives found inside archives, one level deep)
     - counts the images and label files and tells you the next step

Fallback: a Kaggle mirror with your own API key -> python -m ml.download_kaggle
"""
from __future__ import annotations

import argparse
import hashlib
import tarfile
import zipfile
from pathlib import Path

from ml.common import ROOT

DATASET_URL = "https://data.4tu.nl/articles/_/12707066/1"
DATASET_DOI = "10.4121/uuid:8b8ba63a-1010-4de7-a7fb-6f9e3baf128e"
# Published on the 4TU page for data.zip
EXPECTED = {"data.zip": {"bytes": 800_596_912, "md5": "141d48b274d7d3daf78ecfaa5bf39410"}}

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
ARCHIVE_SUFFIXES = (".zip", ".tar", ".tar.gz", ".tgz")

INSTRUCTIONS = f"""
================================================================
 The real dataset is not in {{raw}} yet.

 1. Open in a browser:  {DATASET_URL}
    ("Raw data from Yellow Sticky Traps with insects for training of
     deep learning Convolutional Neural Network for object detection",
     Wageningen University & Research, CC0, DOI {DATASET_DOI})
 2. Download data.zip (~800 MB).
 3. Move data.zip into:  {{raw}}
 4. Run again:           python -m ml.download_4tu

 No browser access? Kaggle fallback: python -m ml.download_kaggle --dataset <owner>/<name>
================================================================
"""


def md5sum(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def is_archive(path: Path) -> bool:
    return path.name.lower().endswith(ARCHIVE_SUFFIXES) and not path.name.startswith(".extracted_")


def verify_archive(path: Path, check_md5: bool = True) -> tuple[bool, str]:
    """Compare with the published size/MD5 when we know them. Unknown files pass with a note."""
    info = EXPECTED.get(path.name)
    size = path.stat().st_size
    if info is None:
        return True, f"{path.name}: {size / 1e6:.1f} MB (no published checksum to compare)"
    if size != info["bytes"]:
        return False, (f"{path.name}: size {size:,} bytes, expected {info['bytes']:,}. "
                       "The download is probably incomplete - download it again.")
    if check_md5:
        digest = md5sum(path)
        if digest != info["md5"]:
            return False, f"{path.name}: MD5 {digest} does not match {info['md5']} - download it again."
        return True, f"{path.name}: size and MD5 match the published values"
    return True, f"{path.name}: size matches (MD5 not checked)"


def _safe_target(base: Path, member_name: str) -> Path:
    """Refuse archive entries that would land outside the target folder ("../" tricks)."""
    target = (base / member_name).resolve()
    if base.resolve() not in target.parents and target != base.resolve():
        raise ValueError(f"unsafe path in archive: {member_name}")
    return target


def extract(path: Path, dest: Path) -> int:
    """Extract an archive safely into dest. Returns the number of files written."""
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    if path.name.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            for m in z.infolist():
                _safe_target(dest, m.filename)
                if not m.is_dir():
                    n += 1
            z.extractall(dest)
    else:
        with tarfile.open(path) as t:
            members = [m for m in t.getmembers() if m.isfile() or m.isdir()]  # no links/devices
            for m in members:
                _safe_target(dest, m.name)
            t.extractall(dest, members=members)
            n = sum(1 for m in members if m.isfile())
    return n


def extract_all(raw: Path, check_md5: bool = True) -> list[str]:
    """Verify and extract every archive in raw (and archives inside them, one level)."""
    messages = []
    for level in range(2):
        archives = sorted(p for p in raw.rglob("*") if p.is_file() and is_archive(p))
        for arc in archives:
            marker = arc.with_name(f".extracted_{arc.name}")
            if marker.exists():
                continue
            ok, msg = verify_archive(arc, check_md5=check_md5 and level == 0)
            messages.append(("OK   " if ok else "FAIL ") + msg)
            if not ok:
                continue
            dest = arc.parent / arc.name.split(".")[0]
            n = extract(arc, dest)
            marker.write_text("extracted\n")
            messages.append(f"     extracted {n} files from {arc.name} -> {dest}")
    return messages


def count_files(raw: Path) -> dict:
    files = [p for p in raw.rglob("*") if p.is_file()]
    return {
        "images": sum(1 for p in files if p.suffix.lower() in IMAGE_EXTS),
        "xml": sum(1 for p in files if p.suffix.lower() == ".xml"),
        "txt": sum(1 for p in files if p.suffix.lower() == ".txt" and p.name != "README.txt"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Verify and unpack the 4TU Yellow Sticky Traps dataset.")
    ap.add_argument("--raw", default=str(ROOT / "ml/data/raw"))
    ap.add_argument("--skip-md5", action="store_true", help="only check the file size (faster)")
    args = ap.parse_args()
    raw = Path(args.raw)
    raw.mkdir(parents=True, exist_ok=True)

    for line in extract_all(raw, check_md5=not args.skip_md5):
        print(f"[4tu] {line}")
    counts = count_files(raw)
    if counts["images"] == 0:
        print(INSTRUCTIONS.format(raw=raw))
        return
    print(f"[4tu] found {counts['images']} images, {counts['xml']} .xml and {counts['txt']} .txt label files")
    if counts["xml"] == 0 and counts["txt"] == 0:
        print("[4tu] WARNING: no label files found - the converter needs .xml (VOC) or .txt (YOLO) labels.")
        return
    print("[4tu] Next: python -m ml.convert_dataset   (also writes ml/reports/dataset_summary.md)")


if __name__ == "__main__":
    main()
