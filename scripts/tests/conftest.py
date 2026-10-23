import os
import sys
import tempfile
from pathlib import Path

# Isolate test data and make backend modules importable. This must happen
# before `tools` is imported anywhere.
os.environ["ORION_DATA_DIR"] = tempfile.mkdtemp(prefix="orion-test-")
BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_tasks():
    import tools

    tools.tasks[:] = [t.copy() for t in tools.DEFAULT_TASKS]
    tools.save_tasks()
    yield
