"""核心流程：导入 → 检测 → 复核 → 导出 → 清理 → 回归。"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .audit import build_audit, render_audit_html
from .detectors import RULESET_VERSION, detect
from .models import FileState
from .parsers import ParseError, parser_for
from .redact import apply_decisions
from .state import (exists, load_index, load_parsed, load_state, save_parsed, save_state,
                    sha256_of_file, unreviewed_count)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def import_file(path: str | Path, force: bool = False) -> tuple[FileState, bool]:
    """解析 + 检测 + 入库。返回 (state, is_duplicate)。"""
    parser = parser_for(path)
    document = parser.parse(path)
    sha = sha256_of_file(path)
    if exists(sha) and not force:
        return load_state(sha), True
    candidates = detect(document)
    state = FileState(
        sha256=sha, title=document.title, format=document.format,
        rule_version=RULESET_VERSION, imported_at=_now(),
        candidates=candidates, parse_errors=list(document.parse_errors),
    )
    save_parsed(sha, document)
    save_state(state)
    return state, False


def record_decision(sha: str, candidate_id: str, action: str, reason: str = "") -> FileState:
    from .models import ReviewDecision
    state = load_state(sha)
    if state is None:
        raise ValueError(f"未找到状态：{sha}")
    if not any(c.id == candidate_id for c in state.candidates):
        raise ValueError(f"未找到候选：{candidate_id}")
    state.decisions[candidate_id] = ReviewDecision(
        candidate_id=candidate_id, action=action, reason=reason, reviewed_at=_now())
    save_state(state)
    return state


def export_file(sha: str, out_dir: str | Path) -> dict:
    """导出脱敏文件 + 审计清单（JSON + HTML），返回审计记录。"""
    state = load_state(sha)
    if state is None:
        raise ValueError(f"未找到状态：{sha}")
    document = load_parsed(sha)
    if document is None:
        raise ValueError(f"未找到解析产物：{sha}")
    redacted_text, summary = apply_decisions(document, state)
    audit = build_audit(state, summary)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{sha[:8]}.redacted.txt").write_text(
        summary["header"] + "\n\n" + redacted_text, encoding="utf-8")
    (out / f"{sha[:8]}.audit.json").write_text(
        __import__("json").dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / f"{sha[:8]}.audit.html").write_text(render_audit_html(audit), encoding="utf-8")

    state.status = "exported"
    save_state(state)
    return audit


def run_regression(samples_dir: str | Path, ground_truth: dict) -> dict:
    """在固定合成题集上测量漏检/误报（按字段计）。"""
    import json
    samples = Path(samples_dir)
    misses = []        # 漏检：标注正例未被命中
    false_pos = []     # 误报：命中了标注为「非个人信息」的片段
    total_pos = 0
    total_candidates = 0
    for gt in ground_truth.get("samples", []):
        sample_file = samples / gt["file"]
        document = parser_for(sample_file).parse(sample_file)
        cands = detect(document)
        total_candidates += len(cands)
        hit_texts = {c.text for c in cands}
        for pos in gt.get("positive", []):
            total_pos += 1
            if pos["text"] not in hit_texts:
                misses.append({"file": gt["file"], "type": pos["type"], "text": pos["text"]})
        for neg in gt.get("negative", []):
            if neg in hit_texts:
                false_pos.append({"file": gt["file"], "text": neg})
    recall = (total_pos - len(misses)) / total_pos if total_pos else 1.0
    false_pos_rate = len(false_pos) / total_candidates if total_candidates else 0.0
    return {
        "total_positive": total_pos,
        "misses": misses,
        "false_positives": false_pos,
        "recall": round(recall, 4),
        "false_positive_rate": round(false_pos_rate, 4),
    }
