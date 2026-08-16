"""
Shared setup for the test suite.

The tests run on a development machine, never on the robot, and only cover code that does not need the
hardware to exist: the rate-limit logic and the consistency of the config files with the code that
reads them. Anything touching I2C, GPIO, the camera or a live socket is deliberately left out, because
mocking those would test the mock rather than the robot, and those faults show up when the thing runs.

Requires pytest, which lives in the local .venv only. The robot's environment does not need it.
Run the whole suite from PyCharm by right-clicking the tests folder, or with:

    .venv/Scripts/python.exe -m pytest
"""

import sys
from pathlib import Path

import pytest

# Project modules are imported as top-level names ('import args'), which needs the repository root on
# the path. Pytest only adds the folder containing the test file, so it has to be added here.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from google_ai_studio import rate_limit_guard  # noqa: E402


class FakeClock:
    """
    A stand-in for the time module, so cooldowns can be waited out without actually waiting.

    RateLimitGuard is almost entirely about what happens after N seconds, and the values involved are
    minutes long. Advancing a fake clock keeps the tests instant and, more importantly, exact: a real
    clock would make every assertion about a remaining cooldown approximate.
    """

    def __init__(self, now: float = 1_000_000.0):
        self.now = now

    def time(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    """Replace the clock RateLimitGuard reads, for the duration of one test."""
    fake_clock = FakeClock()
    monkeypatch.setattr(rate_limit_guard, 'time', fake_clock)
    return fake_clock
