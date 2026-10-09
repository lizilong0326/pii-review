"""脱敏应用与醒目标记。

- 已确认「遮盖/替换」→ 占位符替换，导出不含已确认遮盖的原文片段；
- 「保留/误报」→ 保留原文；
- 未处理项、低置信候选、解析失败页 → 醒目标记，不阻断导出。
"""
from __future__ import annotations

from .models import Candidate, Document, FileState, PII_TYPE_LABEL


def _placeholder(action: str, pii_type: str) -> str:
    label = PII_TYPE_LABEL.get(pii_type, pii_type)
    return f"[已{'遮盖' if action == 'redact' else '替换'}:{label}]"


def apply_decisions(document: Document, state: FileState) -> tuple[str, dict]:
    """返回 (脱敏全文, 标记汇总)。"""
    repls: dict[int, list[tuple[int, int, str]]] = {}
    unprocessed: list[Candidate] = []
    low_confidence_unreviewed: list[Candidate] = []

    for c in state.candidates:
        decision = state.decisions.get(c.id)
        if decision is None:
            unprocessed.append(c)
            if c.confidence == "low":
                low_confidence_unreviewed.append(c)
            continue
        if decision.action in ("keep", "false_positive"):
            continue
        ph = _placeholder(decision.action, c.pii_type)
        if c.parts:
            for part in c.parts:
                repls.setdefault(part["block_index"], []).append((part["start"], part["end"], ph))
        else:
            repls.setdefault(c.block_index, []).append((c.start, c.end, ph))

    new_blocks: list[str] = []
    for bi, b in enumerate(document.blocks):
        text = b.text
        if bi in repls:
            for start, end, rep in sorted(repls[bi], key=lambda x: -x[0]):
                text = text[:start] + rep + text[end:]
        new_blocks.append(text)

    redacted = "\n".join(new_blocks)
    summary = {
        "unprocessed": [{"id": c.id, "type": c.pii_type, "text": c.text} for c in unprocessed],
        "low_confidence_unreviewed": [{"id": c.id, "type": c.pii_type, "text": c.text}
                                      for c in low_confidence_unreviewed],
        "unprocessed_count": len(unprocessed),
        "parse_errors": list(state.parse_errors),
        "header": _header(state, len(unprocessed), list(state.parse_errors)),
    }
    return redacted, summary


def _header(state: FileState, unprocessed: int, parse_errors: list[str]) -> str:
    lines = [
        f"文件摘要：{state.sha256[:16]}…",
        f"规则版本：{state.rule_version}",
        f"复核时间：{state.imported_at}",
        f"处理项：{len(state.candidates)} 个候选，已复核 {len(state.decisions)} 项",
    ]
    if unprocessed:
        lines.append(f"⚠️ 未处理项：{unprocessed} 项（见审计清单）")
    if parse_errors:
        lines.append(f"⚠️ 解析失败页/块：{len(parse_errors)} 处（见审计清单）")
    return "\n".join(lines)
