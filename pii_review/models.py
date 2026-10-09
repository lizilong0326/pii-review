"""个人信息复核器（PII Review）—— 核心数据模型。

纯 dataclass，可 JSON 序列化，不引入重型依赖。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

PII_TYPE_LABEL = {"phone": "电话", "id_card": "证件号", "name": "姓名", "address": "地址"}


@dataclass
class Block:
    """一个文本块（段落 / 行 / OCR 文本行）。"""
    text: str
    page_no: int = 1
    bbox: list[int] = field(default_factory=lambda: [0, 0, 0, 0])  # [x, y, w, h]


@dataclass
class Document:
    """解析后的文档：按页/块组织，保留页码与坐标；解析失败显式记录。"""
    doc_id: str
    title: str
    format: str = "text"          # pdf / docx / image / text
    source_path: str = ""
    blocks: list[Block] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n".join(b.text for b in self.blocks)


@dataclass
class Candidate:
    """一个候选个人信息命中。"""
    id: str
    pii_type: str                 # phone / id_card / name / address
    text: str                     # 命中的原文片段
    page_no: int
    block_index: int
    start: int                    # 相对 block 文本的字符偏移
    end: int
    confidence: str               # high=高把握命中；low=需人工判断
    source: str                   # 命中的规则名
    context: str = ""             # 上下文片段（供左右对照）
    parts: list[dict] = field(default_factory=list)  # 跨块命中（如断行电话）


@dataclass
class ReviewDecision:
    candidate_id: str
    action: str                   # redact / replace / keep / false_positive
    reason: str = ""
    reviewed_at: str = ""


@dataclass
class FileState:
    sha256: str
    title: str
    format: str
    rule_version: str
    imported_at: str
    status: str = "in_review"     # in_review / exported
    candidates: list[Candidate] = field(default_factory=list)
    decisions: dict[str, ReviewDecision] = field(default_factory=dict)
    parse_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "FileState":
        state = FileState(
            sha256=d["sha256"], title=d.get("title", ""), format=d.get("format", ""),
            rule_version=d.get("rule_version", ""), imported_at=d.get("imported_at", ""),
            status=d.get("status", "in_review"), parse_errors=list(d.get("parse_errors", [])),
        )
        state.candidates = [Candidate(**c) for c in d.get("candidates", [])]
        state.decisions = {k: ReviewDecision(**v) for k, v in d.get("decisions", {}).items()}
        return state
