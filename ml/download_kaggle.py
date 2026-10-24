"""Optional: download the dataset from Kaggle using your own Kaggle API key.

If no Kaggle credential is found this script prints how to get one and
exits WITHOUT an error, so it never breaks a setup script.

Where we look for the credential (Kaggle's own rules):
  - environment variables KAGGLE_USERNAME and KAGGLE_KEY, or
  - ~/.kaggle/kaggle.json, or
  - kaggle.json in the project root (it is git-ignored; never commit it).

Usage:
    pip install kaggle==1.7.4.5
    python -m ml.download_kaggle --dataset <owner>/<dataset-name>

The Kaggle mirror name of the "Yellow Sticky Traps" dataset is not fixed,
so search Kaggle for "yellow sticky traps" and pass its <owner>/<name>.
Files are unzipped into ml/data/raw/.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ml.common import ROOT


def find_credentials() -> str | None:
    """Return a description of where credentials were found, or None."""
    if os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY"):
        return "environment variables"
    home_json = Path.home() / ".kaggle" / "kaggle.json"
    if home_json.exists():
        return str(home_json)
    project_json = ROOT / "kaggle.json"
    if project_json.exists():
        # The Kaggle library reads KAGGLE_CONFIG_DIR, so point it at the project root
        os.environ["KAGGLE_CONFIG_DIR"] = str(ROOT)
        return str(project_json)
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Download a Kaggle dataset into ml/data/raw/")
    ap.add_argument("--dataset", help="Kaggle dataset slug, e.g. owner/yellow-sticky-traps")
    ap.add_argument("--out", default=str(ROOT / "ml/data/raw"))
    args = ap.parse_args()

    where = find_credentials()
    if where is None:
        print("[kaggle] No Kaggle credentials found - skipping download (this is fine).\n"
              "         To use Kaggle: kaggle.com -> Settings -> API -> 'Create New Token',\n"
              "         then save kaggle.json to the project root or ~/.kaggle/.\n"
              "         Or download the dataset manually (see python -m ml.convert_dataset).")
        sys.exit(0)
    if not args.dataset:
        print(f"[kaggle] Credentials found ({where}). Pass --dataset <owner>/<name> to download.")
        sys.exit(0)
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi  # lazy: optional dependency
    except ImportError:
        print("[kaggle] The 'kaggle' package is not installed. Run: pip install kaggle==1.7.4.5")
        sys.exit(0)

    api = KaggleApi()
    api.authenticate()
    Path(args.out).mkdir(parents=True, exist_ok=True)
    print(f"[kaggle] downloading {args.dataset} -> {args.out} (credentials: {where})")
    api.dataset_download_files(args.dataset, path=args.out, unzip=True, quiet=False)
    print("[kaggle] done. Next: python -m ml.convert_dataset")


if __name__ == "__main__":
    main()
