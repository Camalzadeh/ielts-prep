"""Point the backend at fixtures + a temporary data dir BEFORE the app modules are imported."""
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIXTURES = HERE / "fixtures"

os.environ["IELTS_DATA_DIR"] = tempfile.mkdtemp(prefix="ielts-test-")
os.environ["IELTS_CONTENT_DIR"] = str(FIXTURES / "content")
os.environ["IELTS_KNOWLEDGE_DIR"] = str(FIXTURES / "knowledge")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
