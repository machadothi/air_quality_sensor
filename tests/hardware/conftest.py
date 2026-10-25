"""Hardware tests: the real test board on a serial port, Bluetooth from this PC.

    .venv/bin/pytest tests/hardware --board /dev/ttyUSB0

Skipped without --board (CI has no board). The board's config.json,
settings.json and paired phones are backed up first and restored at the end,
and the firmware of this checkout is deployed again, so the board ends as it
started (apart from the code, which is this checkout's).
"""

import json

import pytest

import board as hw


def pytest_collection_modifyitems(config, items):
    if config.getoption("--board"):
        return
    skip = pytest.mark.skip(reason="no test board: run with --board /dev/ttyUSB0")
    for item in items:
        if "hardware" in str(item.fspath):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def dut(request):
    """The device under test, with this checkout's firmware on it."""
    b = hw.Board(request.config.getoption("--board"))
    saved = b.backup()
    b.deploy()
    b.restart_app()
    yield b
    b.restore(saved)
    for name in ("update_source", "update_status.json", "update_bad", "update_check", "update_install"):
        b.remove_file(name)         # back to GitHub, no test release state
    b.deploy()                      # undoes test releases installed over the air
    b.restart_app()
    b.close()


@pytest.fixture(scope="session")
def address(dut):
    """The board's Bluetooth address, found by scanning; no pairing left on this PC."""
    found = hw.find()
    assert found, "the board doesn't show up in a Bluetooth scan"
    hw.forget(found[0])
    yield found[0]
    hw.forget(found[0])


@pytest.fixture(scope="session")
def online(dut):
    """Skips a test when the board has no Wi-Fi (its config.json's network)."""
    if not any("Wi-Fi: connected" in t for t in dut.log()):
        pytest.skip("the board isn't on Wi-Fi: its config.json network isn't reachable")
    return True


@pytest.fixture
def config_json(dut):
    """The board's config.json as a dict (the app is stopped)."""
    dut.interrupt()
    return json.loads(dut.read_file("config.json") or b"{}")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """On a failure, attach the board's whole log since the test started."""
    outcome = yield
    report = outcome.get_result()
    dut = item.funcargs.get("dut") if hasattr(item, "funcargs") else None
    if report.when == "call" and report.failed and dut is not None:
        report.sections.append(("board log", "\n".join(dut.log(getattr(item, "_log_mark", 0)))))


@pytest.fixture(autouse=True)
def _mark_log(request):
    dut = request.node.funcargs.get("dut") if "dut" in request.fixturenames else None
    if dut is not None:
        request.node._log_mark = dut.mark()
    yield
