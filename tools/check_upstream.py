"""Verify the extraction against its recorded upstream commit and file bytes."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("upstream", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    baseline = json.loads((root / "tests/compat/upstream_api.json").read_text())
    commit = subprocess.check_output(
        ["git", "-C", str(args.upstream), "rev-parse", "HEAD"], text=True
    ).strip()
    if commit != baseline["source_commit"]:
        raise SystemExit(f"Expected upstream {baseline['source_commit']}, got {commit}")
    for relative, record in baseline["files"].items():
        original = (args.upstream / "src" / relative).read_bytes()
        assert hashlib.sha256(original).hexdigest() == record["sha256"], relative
        extracted = (root / "src" / relative).read_bytes()
        if relative == "linkerbot/arm/kinetix/__init__.py":
            original = original.replace(
                b"linkerbot-py[kinetix]", b"linkerbot-arm[kinetix]"
            )
        assert extracted == original, f"Extraction differs: {relative}"
    print(f"Verified {len(baseline['files'])} files against {commit}")


if __name__ == "__main__":
    main()
