#!/usr/bin/env python3
"""Build a firmware release for over-the-air updates.

    .venv/bin/python tools/release.py 1.1.0

1. Writes the version into firmware/version.py.
2. Compiles the modules (the list in tools/deploy.sh) with mpy-cross -O3.
3. Collects them with assets.bin, boot.py and main.py in dist/v<version>/,
   with manifest.json: version, release notes (that version's section of
   CHANGELOG.md), .mpy format, and every file's size and SHA-256.
4. Prints how to publish it as a GitHub release; boards then find it at
   https://github.com/machadothi/air_quality_sensor/releases/latest/download/manifest.json

config.json is never part of a release.
"""

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIRMWARE = ROOT / "firmware"
MPY_CROSS = ROOT / ".venv" / "bin" / "mpy-cross"
MPY_VERSION = 6          # MicroPython 1.24's .mpy format (sys.implementation._mpy & 0xFF)


def modules():
    text = (ROOT / "tools" / "deploy.sh").read_text()
    return re.search(r"^MODULES=\(([^)]*)\)", text, re.M).group(1).split()


def notes(version):
    text = (ROOT / "CHANGELOG.md").read_text()
    match = re.search(rf"^## {re.escape(version)}\b.*?\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not match:
        sys.exit(f"CHANGELOG.md has no '## {version}' section")
    return match.group(1).strip()


def main():
    if len(sys.argv) != 2 or not re.fullmatch(r"\d+\.\d+\.\d+", sys.argv[1]):
        sys.exit("usage: tools/release.py MAJOR.MINOR.PATCH")
    version = sys.argv[1]
    release_notes = notes(version)
    (FIRMWARE / "version.py").write_text(
        "# The firmware version: set by tools/release.py, compared by updater.py.\n"
        f'VERSION = "{version}"\n')

    out = ROOT / "dist" / f"v{version}"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    for module in modules():
        subprocess.run([str(MPY_CROSS), "-O3", "-o", str(out / f"{module}.mpy"), str(FIRMWARE / f"{module}.py")], check=True)
    for name in ("assets.bin", "boot.py", "main.py"):
        shutil.copy(FIRMWARE / name, out / name)

    files = [{"name": p.name, "size": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in sorted(out.iterdir())]
    manifest = {"version": version, "notes": release_notes, "mpy": MPY_VERSION, "files": files}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    notes_file = out.parent / f"notes-v{version}.md"   # beside the release, not part of it
    notes_file.write_text(release_notes + "\n")
    print(f"Release v{version}: {len(files)} files in {out.relative_to(ROOT)}\n")
    print("Publish it (the tag must be v<version>; the files go up as release assets):")
    print(f"  git tag v{version} && git push origin v{version}")
    print(f"  gh release create v{version} {out.relative_to(ROOT)}/* --title v{version} --notes-file {notes_file.relative_to(ROOT)}")
    print(f"  (or on github.com: Releases -> Draft a new release -> tag v{version} -> paste {notes_file.relative_to(ROOT)}"
          f" as the description -> attach every file in {out.relative_to(ROOT)})")


if __name__ == "__main__":
    main()
