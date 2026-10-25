"""Updates: only a manifest signed with the release key is believed, and its
files are checked by name, size and SHA-256 (security review)."""

import hashlib
import json
import subprocess

import pytest


@pytest.fixture(scope="session")
def keypair(tmp_path_factory):
    """A throwaway 2048-bit key (the real one is 3072-bit and never in tests)."""
    path = tmp_path_factory.mktemp("key") / "key.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(path)],
                   check=True, capture_output=True)
    out = subprocess.run(["openssl", "rsa", "-in", str(path), "-noout", "-modulus"],
                         check=True, capture_output=True, text=True).stdout
    return path, int(out.strip().split("=", 1)[1], 16)


@pytest.fixture
def updater(firmware, keypair, monkeypatch):
    u = firmware("updater")
    release_key = firmware("release_key")
    monkeypatch.setattr(release_key, "N", keypair[1])
    monkeypatch.setattr(release_key, "BYTES", 256)
    return u


def sign(keypair, data, tmp_path):
    (tmp_path / "m").write_bytes(data)
    subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(keypair[0]), "-out", str(tmp_path / "s"),
                    str(tmp_path / "m")], check=True)
    return (tmp_path / "s").read_bytes()


def manifest(version="9.0.0", files=None, **extra):
    files = files if files is not None else [{"name": "app.mpy", "size": 3, "sha256": hashlib.sha256(b"new").hexdigest()}]
    return json.dumps(dict({"version": version, "notes": "n", "mpy": 6, "files": files}, **extra)).encode()


def test_signed_manifest_is_accepted(updater, keypair, tmp_path):
    data = manifest()
    assert updater.check_manifest(data, sign(keypair, data, tmp_path))["version"] == "9.0.0"


@pytest.mark.parametrize("tamper", ["data", "signature", "empty", "other key"])
def test_unsigned_or_tampered_manifest_is_refused(updater, keypair, tmp_path, tamper):
    data = manifest()
    sig = sign(keypair, data, tmp_path)
    if tamper == "data":
        data = data.replace(b"9.0.0", b"9.0.1")
    elif tamper == "signature":
        sig = sig[:-1] + bytes([sig[-1] ^ 1])
    elif tamper == "empty":
        sig = b""
    else:
        sig = b"\x00" + sig[1:]
    with pytest.raises(OSError, match="signature"):
        updater.check_manifest(data, sig)


@pytest.mark.parametrize("name", ["../boot.py", "lib/x.mpy", "config.json", "settings.json", ".hidden.mpy",
                                  "notes.txt", "", "a" * 40 + ".mpy", 5])
def test_signed_manifest_with_bad_file_names_is_refused(updater, keypair, tmp_path, name):
    data = manifest(files=[{"name": name, "size": 3, "sha256": "0" * 64}])
    with pytest.raises(OSError, match="bad file entry"):
        updater.check_manifest(data, sign(keypair, data, tmp_path))


@pytest.mark.parametrize("entry", [{"size": 0}, {"size": 10 ** 7}, {"size": "3"}, {"sha256": "abc"}])
def test_signed_manifest_with_bad_sizes_or_hashes_is_refused(updater, keypair, tmp_path, entry):
    f = dict({"name": "app.mpy", "size": 3, "sha256": "0" * 64}, **entry)
    data = manifest(files=[f])
    with pytest.raises(OSError):
        updater.check_manifest(data, sign(keypair, data, tmp_path))


def test_long_release_notes_are_cut(updater, keypair, tmp_path):
    data = json.dumps({"version": "9.0.0", "notes": "x" * 5000, "mpy": 6,
                       "files": [{"name": "app.mpy", "size": 3, "sha256": "0" * 64}]}).encode()
    assert len(updater.check_manifest(data, sign(keypair, data, tmp_path))["notes"]) == 1000


class FakeSocket:
    def __init__(self, body, headers=b""):
        self.body = body
        self.headers = headers

    def read(self, n):
        chunk, self.body = self.body[:n], self.body[n:]
        return chunk

    def close(self):
        pass


def serve(monkeypatch, updater, files):
    """updater._open answers from files: url -> bytes."""
    def _open(url):
        for suffix, body in files.items():
            if url.endswith(suffix):
                return FakeSocket(body), {"content-length": str(len(body))}
        raise OSError("HTTP 404")
    monkeypatch.setattr(updater, "_open", _open)


@pytest.mark.parametrize("body,error", [(b"new", None), (b"newer", "larger than announced"),
                                        (b"old", "checksum"), (b"ne", "checksum")])
def test_download_checks_size_and_hash(updater, monkeypatch, body, error):
    serve(monkeypatch, updater, {"app.mpy": body})
    if error:
        with pytest.raises(OSError, match=error):
            updater._download("http://x/app.mpy", "app.mpy", 3, hashlib.sha256(b"new").hexdigest())
    else:
        updater._download("http://x/app.mpy", "app.mpy", 3, hashlib.sha256(b"new").hexdigest())
        assert open("app.mpy", "rb").read() == b"new"


def test_oversized_manifest_is_refused(updater, monkeypatch):
    serve(monkeypatch, updater, {"manifest.json": b" " * 20000})
    with pytest.raises(OSError, match="too large"):
        updater._get("http://x/manifest.json", updater._MANIFEST_MAX)


def maintenance_check(board, updater, monkeypatch, files):
    board.networks = {"Home": "pw"}
    json.dump({"wifi": {"ssid": "Home", "password": "pw"}}, open("config.json", "w"))
    open("update_check", "w").write("1")
    serve(monkeypatch, updater, files)
    updater.maintenance()
    return json.load(open("update_status.json"))


def test_check_finds_a_signed_release(board, updater, keypair, monkeypatch, tmp_path):
    data = manifest()
    status = maintenance_check(board, updater, monkeypatch,
                               {"manifest.json": data, "manifest.sig": sign(keypair, data, tmp_path)})
    assert status["state"] == updater.AVAILABLE and status["manifest"]["version"] == "9.0.0"


def test_check_refuses_an_unsigned_release(board, updater, monkeypatch):
    status = maintenance_check(board, updater, monkeypatch, {"manifest.json": manifest()})
    assert status["state"] == updater.FAILED and "404" in status["error"]


def test_check_refuses_a_forged_release(board, updater, monkeypatch):
    status = maintenance_check(board, updater, monkeypatch, {"manifest.json": manifest(), "manifest.sig": b"\1" * 256})
    assert status["state"] == updater.FAILED and "signature" in status["error"]


def test_committed_public_key_is_well_formed(firmware):
    key = firmware("release_key")
    assert key.E == 65537 and 256 ** (key.BYTES - 1) <= key.N < 256 ** key.BYTES and key.BYTES >= 384


def test_confirmed_update_frees_the_previous_files(firmware):
    import os
    app = firmware("app")
    os.mkdir("previous")
    open("previous/app.mpy", "w").write("old")
    open("update_trial", "w").write("1 9.0.0")
    app._confirm_update(root="")
    assert not os.path.exists("previous") and not os.path.exists("update_trial")


def test_no_trial_no_cleanup(firmware):
    import os
    app = firmware("app")
    os.mkdir("previous")                       # e.g. a rollback in progress: keep it
    app._confirm_update(root="")
    assert os.path.exists("previous")
