from pathlib import Path
import sys

# Make /src importable when running: pytest tests/
PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def pytest_ignore_collect(collection_path, config):
    """
    Ignore large/generated/temp directories if pytest is run from repo root.
    """
    parts = set(collection_path.parts)
    ignored = {
        "out_tmp_dirs",
        ".git",
        ".venv",
        "__pycache__",
        "build",
        "dist",
    }
    return not parts.isdisjoint(ignored)

