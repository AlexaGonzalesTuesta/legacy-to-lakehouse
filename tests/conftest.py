import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lakehouse.demo import local_spark  # noqa: E402


@pytest.fixture(scope="session")
def spark():
    s = local_spark("tests")
    yield s
    s.stop()
