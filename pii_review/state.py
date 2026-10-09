"""状态持久化与断点续跑、重复导入识别。

- 每个文件按 SHA256 建目录：.state/<sha256>/state.json
- 索引：.state/index.json（sha -> 元信息），用于重复导入识别
- 中断恢复：只加载已保存状态，绝不把未审核项误标为已通过
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from .models import FileState

STATE_DIR = Path(os.environ.get("PII_REVIEW_STATE_DIR", ".state"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_of_file(path: str | Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_of_document(document) -> str:
    import hashlib
    h = hashlib.sha256()
    for b in document.blocks:
        h.update(f"{b.page_no}:{b.text}\n".encode("utf-8"))
    return h.hexdigest()


def _index_path() -> Path:
    return STATE_DIR / "index.json"


def load_index() -> dict:
    p = _index_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_index(index: dict) -> None:
    _index_path().parent.mkdir(parents=True, exist_ok=True)
    _index_path().write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def exists(sha: str) -> bool:
    return sha in load_index()


def state_path(sha: str) -> Path:
    return STATE_DIR / sha / "state.json"


def load_state(sha: str) -> FileState | None:
    p = state_path(sha)
    if not p.exists():
        return None
    try:
        return FileState.from_dict(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, KeyError):
        return None


def save_state(state: FileState) -> None:
    p = state_path(state.sha256)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    index = load_index()
    index[state.sha256] = {
        "title": state.title, "format": state.format, "imported_at": state.imported_at,
        "status": state.status, "candidate_count": len(state.candidates),
        "reviewed_count": len(state.decisions),
    }
    _save_index(index)


def cleanup_state(sha: str) -> bool:
    """清理某个文件的 .state 目录（破坏性，需权限校验）。"""
    d = STATE_DIR / sha
    if not d.exists():
        return False
    import shutil
    shutil.rmtree(d)
    index = load_index()
    index.pop(sha, None)
    _save_index(index)
    return True


def unreviewed_count(state: FileState) -> int:
    return sum(1 for c in state.candidates if c.id not in state.decisions)


def parsed_path(sha: str) -> Path:
    return STATE_DIR / sha / "parsed.json"


def save_parsed(sha: str, document) -> None:
    p = parsed_path(sha)
    p.parent.mkdir(parents=True, exist_ok=True)
    from .models import Document
    data = {"title": document.title, "format": document.format,
            "blocks": [{"text": b.text, "page_no": b.page_no, "bbox": b.bbox}
                       for b in document.blocks]}
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_parsed(sha: str):
    from .models import Block, Document
    p = parsed_path(sha)
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    return Document(doc_id=sha[:8], title=data["title"], format=data["format"],
                    blocks=[Block(**b) for b in data["blocks"]])
