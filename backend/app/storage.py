"""Where uploaded files live on disk. Paths stored in the database are relative to
UPLOAD_ROOT, so the folder can move without rewriting rows."""

import os
from pathlib import Path

UPLOAD_ROOT = Path(
    os.getenv("UPLOAD_DIR", Path(__file__).resolve().parent.parent / "uploads")
).resolve()
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
