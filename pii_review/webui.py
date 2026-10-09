"""本地 Web 复核界面（stdlib http.server，零依赖，macOS 风格）。

左右对照：左 = 原文（高亮候选），右 = 脱敏预览；逐项遮盖/替换/保留/误报 + 理由；批量操作逐项落盘。
"""
from __future__ import annotations

import html
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .models import PII_TYPE_LABEL
from .pipeline import export_file, import_file, record_decision
from .redact import apply_decisions
from .state import cleanup_state, load_index, load_parsed, load_state, unreviewed_count

SAMPLES_DIR = Path("data/samples")

CSS = """
:root{
  --bg:#f5f5f7;--card:#ffffff;--text:#1d1d1f;--text-2:#6e6e73;
  --separator:rgba(0,0,0,0.10);
  --blue:#007aff;--green:#34c759;--red:#ff3b30;--orange:#ff9500;--purple:#af52de;--gray:#8e8e93;--indigo:#5856d6;
  --shadow:0 1px 2px rgba(0,0,0,0.04),0 8px 24px rgba(0,0,0,0.06);
  --radius:14px;
}
@media (prefers-color-scheme: dark){
  :root{--bg:#1e1e20;--card:#2c2c2e;--text:#f5f5f7;--text-2:#a1a1a6;
        --separator:rgba(255,255,255,0.10);--shadow:0 1px 2px rgba(0,0,0,0.4),0 8px 24px rgba(0,0,0,0.4)}
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Helvetica Neue","PingFang SC",sans-serif;
     background:var(--bg);color:var(--text);-webkit-font-smoothing:antialiased;line-height:1.55}
.top{position:sticky;top:0;z-index:10;display:flex;align-items:center;gap:12px;padding:13px 24px;
     border-bottom:1px solid var(--separator);background:rgba(248,248,250,0.82);
     backdrop-filter:saturate(180%) blur(20px);-webkit-backdrop-filter:saturate(180%) blur(20px)}
@media (prefers-color-scheme: dark){.top{background:rgba(40,40,42,0.85)}}
.top .title{font-weight:600;font-size:14px}
.top .crumb{color:var(--text-2);font-size:13px}
.top a{color:var(--blue);text-decoration:none;font-size:13px;margin-left:auto}
.wrap{max-width:1440px;margin:0 auto;padding:24px}
h2{font-size:20px;font-weight:700;letter-spacing:-0.02em;margin:8px 0 4px}
.sub{color:var(--text-2);font-size:13px;margin-bottom:16px}
.panel{background:var(--card);border:1px solid var(--separator);border-radius:var(--radius);
       padding:18px;box-shadow:var(--shadow);margin:14px 0}
.panel h3{font-size:14px;margin-bottom:10px}
.doc{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media (max-width:820px){.doc{grid-template-columns:1fr}}
p.blk{margin:7px 0;font-size:14px}
p.blk .meta{color:var(--text-2);font-size:11px;margin-right:6px}
mark{padding:1px 4px;border-radius:4px;box-shadow:inset 0 -2px 0 var(--accent,var(--blue))}
mark.high{background:rgba(52,199,89,0.15);--accent:#34c759}
mark.low{background:rgba(255,149,0,0.15);--accent:#ff9500}
sup{font-size:10px;color:var(--text-2)}
pre{white-space:pre-wrap;word-break:break-word;font-size:13px;font-family:inherit}
.ph{background:rgba(0,122,255,0.12);color:var(--blue);border-radius:4px;padding:0 3px}
.warn{color:#c62828;font-weight:600;margin:8px 0}
@media (prefers-color-scheme: dark){.warn{color:#ff6961}}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--separator)}
th{color:var(--text-2);font-weight:600;font-size:12px}
a{color:var(--blue);text-decoration:none}
.cand{background:var(--card);border:1px solid var(--separator);border-left:4px solid var(--accent);
      border-radius:var(--radius);padding:14px 16px;margin:12px 0;box-shadow:var(--shadow)}
.cand.high{--accent:#34c759}.cand.low{--accent:#ff9500}
.cand .head{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.cand .cid{font-weight:700;font-size:14px}
.cand .pill{color:#fff;font-size:12px;font-weight:600;padding:1px 10px;border-radius:999px}
.cand code{font-family:"SF Mono",ui-monospace,Menlo,monospace;font-size:13px;background:var(--bg);
           padding:1px 7px;border-radius:6px}
.cand .ctx{color:var(--text-2);font-size:12px;margin:4px 0}
.cand .row{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:8px}
.status{font-size:12px;font-weight:600}
.status.done{color:var(--green)}.status.pending{color:var(--orange)}
button{background:var(--blue);color:#fff;border:0;border-radius:7px;padding:6px 14px;margin:2px;
       font-size:13px;cursor:pointer;font-weight:500}
button.red{background:var(--red)}button.green{background:var(--green)}
button.gray{background:var(--gray)}button.indigo{background:var(--indigo)}
button.ghost{background:transparent;color:var(--blue);border:1px solid var(--separator)}
input[type=text]{border:1px solid var(--separator);border-radius:7px;padding:6px 10px;font-size:13px;
       background:var(--card);color:var(--text);flex:1;min-width:180px}
.sample-list{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}
.sample-list a{font-size:12px;background:var(--card);border:1px solid var(--separator);
       border-radius:999px;padding:4px 12px}
.sample-list a:hover{border-color:var(--blue)}
"""


def _esc(s) -> str:
    return html.escape(str(s))


def _candidate_marks(state, document):
    marks: dict[int, list] = {}
    for c in state.candidates:
        if c.parts:
            for p in c.parts:
                marks.setdefault(p["block_index"], []).append(
                    (p["start"], p["end"], c.pii_type, c.confidence, c.id))
        else:
            marks.setdefault(c.block_index, []).append((c.start, c.end, c.pii_type, c.confidence, c.id))
    return marks


def _left_html(state, document) -> str:
    marks = _candidate_marks(state, document)
    parts = []
    for bi, b in enumerate(document.blocks):
        entries = sorted(marks.get(bi, []), key=lambda x: x[0])
        out, pos = [], 0
        for start, end, pii_type, conf, cid in entries:
            out.append(_esc(b.text[pos:start]))
            out.append(f'<mark class="{conf}" title="{_esc(cid)}">{_esc(b.text[start:end])}<sup>{_esc(cid)}</sup></mark>')
            pos = end
        out.append(_esc(b.text[pos:]))
        parts.append(f'<p class="blk"><span class="meta">第{b.page_no}页 · {b.bbox}</span>' + "".join(out) + "</p>")
    return "\n".join(parts)


def _style_redacted(text: str) -> str:
    t = _esc(text)
    return re.sub(r"(\[已(?:遮盖|替换):[^\]]+\])", r'<span class="ph">\1</span>', t)


def _candidate_form(c, state) -> str:
    d = state.decisions.get(c.id)
    label = PII_TYPE_LABEL.get(c.pii_type, c.pii_type)
    conf = "高把握命中" if c.confidence == "high" else "需人工判断"
    pill = "background:#34c759" if c.confidence == "high" else "background:#ff9500"
    status = "已处理" if d else "未处理"
    status_cls = "done" if d else "pending"
    action_label = {"redact": "遮盖", "replace": "替换", "keep": "保留", "false_positive": "误报"}.get(d.action, "") if d else ""
    return f"""
<form method="post" class="cand {c.confidence}">
  <div class="head">
    <span class="cid">{_esc(c.id)}</span>
    <span class="pill" style="{pill}">{_esc(label)}</span>
    <span class="pill" style="background:var(--text-2)">{_esc(conf)}</span>
    <span class="status {status_cls}">{_esc(status)}{(' · ' + action_label) if d else ''}</span>
  </div>
  <div>命中原文：<code>{_esc(c.text)}</code></div>
  <div class="ctx">上下文：…{_esc(c.context)}…（第{c.page_no}页 · {_esc(c.source)}）</div>
  <div class="row">
    <input type="hidden" name="candidate_id" value="{_esc(c.id)}">
    <input type="text" name="reason" placeholder="填写理由（可空）" value="{_esc(d.reason) if d else ''}">
    <button name="action" value="redact" class="red">遮盖</button>
    <button name="action" value="replace">替换</button>
    <button name="action" value="keep" class="green">保留</button>
    <button name="action" value="false_positive" class="gray">误报</button>
  </div>
</form>"""


def _page(sha: str, message: str = "") -> str:
    state = load_state(sha)
    if state is None:
        return _wrap(f"<p>未找到状态 {_esc(sha)}</p>")
    document = load_parsed(sha)
    redacted, summary = apply_decisions(document, state) if document else ("", {})
    forms = "\n".join(_candidate_form(c, state) for c in state.candidates)
    warning = ""
    if summary.get("unprocessed_count"):
        warning += f'<p class="warn">⚠️ 未处理 {summary["unprocessed_count"]} 项</p>'
    if summary.get("parse_errors"):
        warning += f'<p class="warn">⚠️ 解析失败 {len(summary["parse_errors"])} 处</p>'
    msg = f'<p class="warn">{_esc(message)}</p>' if message else ""
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>复核 · {_esc(state.title)}</title><style>{CSS}</style></head><body>
<div class="top"><span class="title">个人信息复核器</span><span class="crumb">· {_esc(state.title)}</span>
<a href="/">← 返回列表</a></div>
<div class="wrap">{msg}{warning}
<div class="doc">
  <div class="panel"><h3>原文（候选高亮）</h3>{_left_html(state, document) if document else ""}</div>
  <div class="panel"><h3>脱敏预览</h3><pre>{_style_redacted(redacted)}</pre></div>
</div>
<div class="panel">
  <h3>逐项复核（未审核 {unreviewed_count(state)} 项）</h3>
  <form method="post"><button name="action" value="batch_redact" class="indigo">批量：全部遮盖（逐项落盘）</button></form>
  {forms}
</div>
<div class="panel">
  <h3>导出 / 清理</h3>
  <form method="post" action="/export/{sha}" style="display:inline"><button>导出脱敏文件 + 审计清单</button></form>
  <form method="post" action="/cleanup/{sha}" style="display:inline"><button class="gray">清理本机状态（破坏性）</button></form>
</div>
</div></body></html>"""


def _index() -> str:
    index = load_index()
    rows = []
    for sha, meta in index.items():
        reviewed = meta.get("reviewed_count", 0)
        total = meta.get("candidate_count", 0)
        pct = round(reviewed / total * 100) if total else 0
        rows.append(
            f"<tr><td><a href='/review/{sha}'>{_esc(meta.get('title',''))}</a></td>"
            f"<td><code>{sha[:16]}…</code></td><td>{_esc(meta.get('status',''))}</td>"
            f"<td>{reviewed}/{total}（{pct}%）</td></tr>")
    samples = sorted(SAMPLES_DIR.glob("*.json")) if SAMPLES_DIR.exists() else []
    sample_links = "".join(
        f'<a href="/import?file={urllib.parse.quote(str(s))}">{_esc(s.stem)}</a>' for s in samples)
    return _wrap(f"""
<h2>个人信息复核器</h2>
<div class="sub">文档进入知识库前，定位疑似个人信息，逐项人工复核后导出脱敏版与审计清单。</div>
<div class="panel"><h3>已导入文件</h3>
<table><tr><th>文件</th><th>摘要</th><th>状态</th><th>复核进度</th></tr>
{''.join(rows) or '<tr><td colspan=4>（空）</td></tr>'}</table></div>
<div class="panel"><h3>导入合成样本（{len(samples)} 份）</h3>
<div class="sample-list">{sample_links}</div>
<form method="get" action="/import"><input type="text" name="file" placeholder="或粘贴文件路径，如 data/samples/s01.json"><button>导入</button></form>
</div>""")


def _wrap(body: str) -> str:
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>个人信息复核器</title><style>{CSS}</style></head><body>
<div class="top"><span class="title">个人信息复核器</span><span class="crumb">（PII Review）</span></div>
<div class="wrap">{body}</div></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urllib.parse.urlparse(self.path)
        if path.path == "/":
            return self._html(_index())
        if path.path == "/import":
            q = urllib.parse.parse_qs(path.query)
            return self._import(q.get("file", [""])[0])
        if path.path.startswith("/review/"):
            return self._html(_page(path.path.split("/")[-1]))
        self.send_error(404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
        if path.path.startswith("/review/"):
            sha = path.path.split("/")[-1]
            action = form.get("action", [""])[0]
            if action == "batch_redact":
                state = load_state(sha)
                for c in state.candidates:
                    if c.id not in state.decisions:
                        record_decision(sha, c.id, "redact", "批量遮盖")
                return self._redirect(f"/review/{sha}")
            cid = form.get("candidate_id", [""])[0]
            reason = form.get("reason", [""])[0]
            if cid and action:
                try:
                    record_decision(sha, cid, action, reason)
                except ValueError as exc:
                    return self._html(_page(sha, str(exc)))
            return self._redirect(f"/review/{sha}")
        if path.path.startswith("/export/"):
            sha = path.path.split("/")[-1]
            try:
                export_file(sha, "out")
                return self._redirect(f"/review/{sha}")
            except ValueError as exc:
                return self._html(_page(sha, str(exc)))
        if path.path.startswith("/cleanup/"):
            sha = path.path.split("/")[-1]
            cleanup_state(sha)
            return self._redirect("/")
        self.send_error(404)

    def _import(self, file: str):
        if not file:
            return self._html(_wrap("<p class='warn'>请填写文件路径</p>"))
        try:
            state, dup = import_file(file)
        except Exception as exc:  # noqa: BLE001
            return self._html(_wrap(f"<p class='warn'>导入失败：{_esc(exc)}</p>"))
        return self._redirect(f"/review/{state.sha256}")

    def _html(self, content: str):
        data = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, location: str):
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def log_message(self, *args):
        pass


def run_server(port: int = 8000) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"个人信息复核器已启动：http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
