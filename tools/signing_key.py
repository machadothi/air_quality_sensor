#!/usr/bin/env python3
"""The release signing key: the board installs an update only if its manifest
is signed with it (firmware/signature.py, docs/updates.md).

    .venv/bin/python tools/signing_key.py new     # create a key, write firmware/release_key.py
    .venv/bin/python tools/signing_key.py show    # where the key is, its fingerprint

The private key stays on this PC, outside the repository:
    $AQS_RELEASE_KEY, default ~/.config/air_quality_sensor/release-key.pem
Keep a copy offline (e.g. a USB stick in a drawer). Without it, boards can only
be updated over USB; with it, anyone can make updates your boards accept.

Only firmware/release_key.py (the public part) is committed. Changing the key
means boards must get the new release_key.py first, signed with the old key.
Needs the openssl command line tool.
"""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "firmware" / "release_key.py"
BITS = 3072


def key_path():
    return Path(os.environ.get("AQS_RELEASE_KEY", Path.home() / ".config" / "air_quality_sensor" / "release-key.pem"))


def modulus(path):
    out = subprocess.run(["openssl", "rsa", "-in", str(path), "-noout", "-modulus"],
                         check=True, capture_output=True, text=True).stdout
    return int(out.strip().split("=", 1)[1], 16)


def fingerprint(n):
    return hashlib.sha256(n.to_bytes((n.bit_length() + 7) // 8, "big")).hexdigest()[:16]


def write_public(n):
    PUBLIC.write_text(
        "# The public half of the release signing key (tools/signing_key.py).\n"
        "# Updates whose manifest isn't signed with the matching private key are refused.\n"
        f"# Fingerprint: {fingerprint(n)}\n"
        f"N = 0x{n:x}\n"
        "E = 65537\n"
        f"BYTES = {(n.bit_length() + 7) // 8}\n")


def sign(path, data_file, signature_file):
    subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(path), "-out", str(signature_file), str(data_file)],
                   check=True)


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "show"
    path = key_path()
    if command == "new":
        if path.exists():
            sys.exit(f"{path} exists already; move it away first if you really want a new key")
        path.parent.mkdir(parents=True, exist_ok=True)
        old = os.umask(0o077)
        try:
            subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", f"rsa_keygen_bits:{BITS}",
                            "-out", str(path)], check=True, capture_output=True)
        finally:
            os.umask(old)
        n = modulus(path)
        write_public(n)
        print(f"New key: {path} (fingerprint {fingerprint(n)})")
        print(f"Public part written to {PUBLIC.relative_to(ROOT)}: commit it.")
        print("Keep a copy of the private key offline; never commit it.")
    elif command == "show":
        if not path.exists():
            sys.exit(f"No key at {path}: tools/signing_key.py new")
        n = modulus(path)
        committed = PUBLIC.read_text() if PUBLIC.exists() else ""
        match = f"N = 0x{n:x}" in committed
        print(f"{path}: fingerprint {fingerprint(n)}; {'matches' if match else 'does NOT match'} "
              f"{PUBLIC.relative_to(ROOT)}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
