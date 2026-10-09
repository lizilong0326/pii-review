"""规则型个人信息识别器（确定性，零依赖）。

- 电话 / 证件号 / 姓名 / 地址 四类；
- 区分「高把握命中」(confidence=high) 与「需人工判断」(confidence=low)；
- 不默认删除所有数字：普通编号、日期、订单号等不匹配规则则不标；
- 覆盖断行电话、OCR 错字、同名实体、地址上下文等回归重点。
"""
from __future__ import annotations

import re

from .models import Block, Candidate, Document

RULESET_VERSION = "1.0.0"

PHONE_RE = re.compile(r"1[3-9]\d{9}")
PHONE_HYPHEN_RE = re.compile(r"1[3-9]\d-\d{4}-\d{4}")
ID_RE = re.compile(r"\d{17}[\dXx]|\d{15}")

# 地址上下文词
ADDR_LEAD = ("地址", "住址", "联系地址", "邮寄地址", "位于")
ADDR_STRUCT = ("省", "市", "区", "县", "路", "街", "号", "室", "栋", "镇", "乡")

# 常见姓氏（合成演示用，非完整百家姓）
SURNAMES = set("赵钱孙李周吴郑王冯陈蒋沈韩杨朱秦许何吕张孔曹严华金魏陶姜谢邹苏潘葛范彭鲁韦马苗方俞任袁柳唐")

NAME_HONORIFICS = ("先生", "女士", "小姐", "老师", "经理", "师傅")

# OCR 常见错字映射
OCR_MAP = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "L": "1", "S": "5", "B": "8", "Z": "2"})


def detect(document: Document) -> list[Candidate]:
    cands: list[Candidate] = []
    for bi, block in enumerate(document.blocks):
        cands += _phone(block, bi)
        cands += _id(block, bi)
        cands += _address(block, bi)
        cands += _name(block, bi)
    cands += _broken_phone(document.blocks)
    for i, c in enumerate(cands):
        c.id = f"c{i:03d}"
    return cands


def _ctx(block: Block, start: int, end: int, pad: int = 12) -> str:
    s = max(0, start - pad)
    e = min(len(block.text), end + pad)
    return block.text[s:e]


def _mk(block: Block, bi: int, pii_type: str, text: str, start: int, end: int,
        confidence: str, source: str) -> Candidate:
    return Candidate(id="", pii_type=pii_type, text=text, page_no=block.page_no,
                     block_index=bi, start=start, end=end, confidence=confidence,
                     source=source, context=_ctx(block, start, end))


# ---- 电话 ----
def _phone(block: Block, bi: int) -> list[Candidate]:
    out = []
    for m in PHONE_RE.finditer(block.text):
        out.append(_mk(block, bi, "phone", m.group(), m.start(), m.end(), "high", "phone_exact"))
    for m in PHONE_HYPHEN_RE.finditer(block.text):
        out.append(_mk(block, bi, "phone", m.group(), m.start(), m.end(), "low", "phone_hyphen"))
    # OCR 错字电话：归一化后命中但原文不同 → 需人工判断
    normalized = block.text.translate(OCR_MAP)
    for m in PHONE_RE.finditer(normalized):
        orig = block.text[m.start():m.end()]
        if orig != m.group():
            out.append(_mk(block, bi, "phone", orig, m.start(), m.end(), "low", "phone_ocr_fuzzy"))
    return out


def _broken_phone(blocks: list[Block]) -> list[Candidate]:
    """断行电话：相邻两行各持一部分数字，拼接后构成完整手机号。"""
    out = []
    for i in range(len(blocks) - 1):
        a, b = blocks[i], blocks[i + 1]
        joined = a.text + b.text
        for m in PHONE_RE.finditer(joined):
            if m.start() < len(a.text) and m.end() > len(a.text):
                # 命中跨行边界
                out.append(Candidate(
                    id="", pii_type="phone", text=m.group(), page_no=a.page_no,
                    block_index=i, start=m.start(), end=len(a.text),
                    confidence="low", source="phone_broken_line",
                    context=(a.text[m.start():] + b.text[:m.end() - len(a.text)]),
                    parts=[
                        {"block_index": i, "start": m.start(), "end": len(a.text)},
                        {"block_index": i + 1, "start": 0, "end": m.end() - len(a.text)},
                    ],
                ))
    return out


# ---- 证件号 ----
def _id(block: Block, bi: int) -> list[Candidate]:
    out = []
    for m in ID_RE.finditer(block.text):
        out.append(_mk(block, bi, "id_card", m.group(), m.start(), m.end(), "high", "id_exact"))
    normalized = block.text.translate(OCR_MAP)
    for m in ID_RE.finditer(normalized):
        orig = block.text[m.start():m.end()]
        if orig != m.group():
            out.append(_mk(block, bi, "id_card", orig, m.start(), m.end(), "low", "id_ocr_fuzzy"))
    return out


# ---- 地址 ----
def _address(block: Block, bi: int) -> list[Candidate]:
    text = block.text
    out = []
    for lead in ADDR_LEAD:
        idx = text.find(lead)
        if idx < 0:
            continue
        start = idx + len(lead)
        while start < len(text) and text[start] in "：: ":
            start += 1
        end = start
        while end < len(text) and text[end] not in "，。；、,;.!！？? \n":
            end += 1
        seg = text[start:end].strip()
        if seg:
            out.append(_mk(block, bi, "address", seg, start, end, "low", "address_lead"))
    # 纯结构地址（无引导词，但含省/市/路/号等结构词 + 数字）→ 整块作为候选
    if not any(lead in text for lead in ADDR_LEAD):
        struct_hits = sum(1 for w in ADDR_STRUCT if w in text)
        if struct_hits >= 2 and re.search(r"\d", text):
            out.append(_mk(block, bi, "address", text, 0, len(text), "low", "address_structure"))
    return out


# ---- 姓名 ----
def _name(block: Block, bi: int) -> list[Candidate]:
    text = block.text
    out = []
    # 「姓名：张三」
    idx = text.find("姓名")
    if idx >= 0:
        m = re.match(r"[\u4e00-\u9fa5]{2,3}", text[idx + 2:].lstrip("：: "))
        if m:
            tail = text[idx + 2:].lstrip("：: ")
            s = idx + 2 + (text[idx + 2:].index(tail))
            out.append(_mk(block, bi, "name", m.group(), s, s + len(m.group()), "low", "name_lead"))
    # 姓氏 + 1~2 字 + 称谓（如「张伟先生」）
    pat = re.compile(rf"([{''.join(sorted(SURNAMES))}][\u4e00-\u9fa5]{{1,2}})({'|'.join(NAME_HONORIFICS)})")
    for m in pat.finditer(text):
        out.append(_mk(block, bi, "name", m.group(1), m.start(), m.start() + len(m.group(1)),
                       "low", "name_honorific"))
    return out
