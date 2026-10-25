# Release signatures: RSA PKCS#1 v1.5 with SHA-256 (what `openssl dgst -sha256
# -sign` makes). The board only verifies; the private key never leaves the PC
# that builds releases (tools/signing_key.py, docs/updates.md).
#
# Verifying is one modular exponentiation with the small public exponent
# 65537: MicroPython's built-in pow() does it in milliseconds, no library needed.
import hashlib

# DER prefix of a SHA-256 DigestInfo (RFC 8017, section 9.2)
_SHA256_INFO = b"\x30\x31\x30\x0d\x06\x09\x60\x86\x48\x01\x65\x03\x04\x02\x01\x05\x00\x04\x20"


def verify(message, signature, n, e, k):
    """True if signature (bytes) is a valid signature of message (bytes) for
    the public key (n, e) of k bytes. (k is given: MicroPython's int has no
    bit_length().)"""
    if len(signature) != k:
        return False
    s = int.from_bytes(signature, "big")
    if s >= n:
        return False
    em = pow(s, e, n).to_bytes(k, "big")
    digest = hashlib.sha256(message).digest()
    expected = b"\x00\x01" + b"\xff" * (k - 3 - len(_SHA256_INFO) - 32) + b"\x00" + _SHA256_INFO + digest
    return em == expected
