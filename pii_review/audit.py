"""审计清单：JSON（机器可读）+ HTML（可读）。

字段：文件摘要、规则版本、处理项、复核时间、结果；未处理/低置信/解析失败醒目标记。
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone

from .models import FileState, PII_TYPE_LABEL


def build_audit(state: FileState, redacted_summary: dict) -> dict:
    items = []
    for c in state.candidates:
        d = state.decisions.get(c.id)
        items.append({
            "id": c.id,
            "type": c.pii_type,
            "text": c.text,
            "page": c.page_no,
            "confidence": "高把握命中" if c.confidence == "high" else "需人工判断",
            "source": c.source,
            "action": d.action if d else None,
            "reason": d.reason if d else "",
            "reviewed_at": d.reviewed_at if d else None,
            "result": _result_label(c, d),
        })
    return {
        "file_sha256": state.sha256,
        "title": state.title,
        "rule_version": state.rule_version,
        "imported_at": state.imported_at,
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": {
            "candidate_total": len(state.candidates),
            "reviewed": len(state.decisions),
            "unprocessed": redacted_summary["unprocessed_count"],
            "parse_errors": len(redacted_summary["parse_errors"]),
        },
        "items": items,
        "unprocessed": redacted_summary["unprocessed"],
        "low_confidence_unreviewed": redacted_summary["low_confidence_unreviewed"],
        "parse_errors": redacted_summary["parse_errors"],
    }


def _result_label(c, d) -> str:
    if d is None:
        return "未处理"
    return {"redact": "遮盖", "replace": "替换", "keep": "保留", "false_positive": "误报"}.get(d.action, d.action)


def _esc(s) -> str:
    return html.escape(str(s))


def render_audit_html(audit: dict) -> str:
    rows = []
    for it in audit["items"]:
        action = it["action"] or "—"
        badge = {
            "redact": "遮盖", "replace": "替换", "keep": "保留", "false_positive": "误报", None: "未处理",
        }.get(it["action"], it["action"])
        conf_cls = "high" if it["confidence"] == "高把握命中" else "low"
        rows.append(
            f"<tr><td>{_esc(it['id'])}</td><td>{_esc(PII_TYPE_LABEL.get(it['type'], it['type']))}</td>"
            f"<td><code>{_esc(it['text'])}</code></td><td>{it['page']}</td>"
            f"<td class='{conf_cls}'>{_esc(it['confidence'])}</td>"
            f"<td class='badge-{badge}'>{_esc(badge)}</td><td>{_esc(it['reason'])}</td></tr>"
        )
    warn = ""
    if audit["summary"]["unprocessed"]:
        warn += f"<p class='warn'>⚠️ 未处理 {audit['summary']['unprocessed']} 项</p>"
    if audit["summary"]["parse_errors"]:
        warn += f"<p class='warn'>⚠️ 解析失败 {audit['summary']['parse_errors']} 处</p>"
    return f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><title>审计清单</title>
<style>
 body {{ font-family:-apple-system,"PingFang SC",sans-serif; margin:32px; color:#1d1d1f; }}
 table {{ border-collapse:collapse; width:100%; font-size:13px; }}
 th,td {{ text-align:left; padding:8px 10px; border-bottom:1px solid #e5e5e5; }}
 th {{ color:#6e6e73; font-size:12px; }}
 code {{ background:#f5f5f7; padding:1px 6px; border-radius:5px; }}
 .high {{ color:#34c759; font-weight:600; }} .low {{ color:#ff9500; font-weight:600; }}
 .badge-遮盖 {{ color:#ff3b30; }} .badge-替换 {{ color:#007aff; }} .badge-保留 {{ color:#34c759; }}
 .badge-误报 {{ color:#8e8e93; }} .badge-未处理 {{ color:#ff9500; font-weight:700; }}
 .warn {{ color:#c62828; font-weight:600; }}
</style></head><body>
<h1>审计清单</h1>
<p>文件摘要：<code>{_esc(audit['file_sha256'][:16])}…</code> · 规则版本：{_esc(audit['rule_version'])} · 导入：{_esc(audit['imported_at'])} · 导出：{_esc(audit['exported_at'])}</p>
{warn}
<table><tr><th>ID</th><th>类型</th><th>命中原文</th><th>页</th><th>置信</th><th>处理</th><th>理由</th></tr>{''.join(rows)}</table>
</body></html>"""
