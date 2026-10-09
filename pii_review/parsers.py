"""文档解析适配层。

默认零依赖解析器：JSON 样本（已解析结构）与纯文本（.txt）。
真实解析器：Docling（PDF/DOCX 结构）、PaddleOCR（图片文字），
未安装依赖时给出显式错误提示；两者均把产物归一为 Document（页 → 块 + 坐标）。
"""
from __future__ import annotations

import json
from pathlib import Path

from .models import Block, Document


class ParseError(RuntimeError):
    """解析失败：显式提示，不静默跳过。"""


class Parser:
    def parse(self, path: str | Path) -> Document:
        raise NotImplementedError


class JsonSampleParser(Parser):
    """加载合成样本（JSON），模拟解析产物：页 → 块（含坐标）。"""

    def parse(self, path: str | Path) -> Document:
        p = Path(path)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ParseError(f"无法读取样本 {p.name}：{exc}") from exc
        blocks, errors = [], []
        for page in data.get("pages", []):
            for b in page.get("blocks", []):
                text = b.get("text", "")
                if not text.strip():
                    continue
                blocks.append(Block(text=text, page_no=page.get("page_no", 1),
                                    bbox=b.get("bbox", [0, 0, 0, 0])))
        if not blocks:
            errors.append(f"样本 {p.name} 解析后无文本内容")
        return Document(doc_id=data.get("doc_id", p.stem), title=data.get("title", p.stem),
                        format=data.get("format", "json"), source_path=str(p),
                        blocks=blocks, parse_errors=errors)


class TextParser(Parser):
    """纯文本：每行一个块。"""

    def parse(self, path: str | Path) -> Document:
        p = Path(path)
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ParseError(f"无法读取文件 {p.name}：{exc}") from exc
        blocks = [Block(text=ln, page_no=1, bbox=[0, i * 20, 0, 20])
                  for i, ln in enumerate(lines) if ln.strip()]
        return Document(doc_id=p.stem, title=p.name, format="text", source_path=str(p), blocks=blocks)


class DoclingParser(Parser):
    """PDF / DOCX 结构解析（真实实现，依赖 docling）。"""

    def parse(self, path: str | Path) -> Document:
        p = Path(path)
        if not p.exists():
            raise ParseError(f"文件不存在：{p}")
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as exc:
            raise ParseError("未安装 docling，无法解析 PDF/DOCX。请 `pip install docling` 后重试。") from exc
        try:
            result = DocumentConverter().convert(str(p))
        except Exception as exc:  # noqa: BLE001
            raise ParseError(f"docling 解析失败：{exc}") from exc
        blocks = []
        for item in self._items(result):
            text = self._item_text(item)
            if not text or not text.strip():
                continue
            page_no, bbox = self._prov(item)
            blocks.append(Block(text=text, page_no=page_no, bbox=bbox))
        if not blocks:
            raise ParseError(f"docling 未提取到文本：{p.name}")
        return Document(doc_id=p.stem, title=p.name, format=p.suffix.lstrip(".").lower(),
                        source_path=str(p), blocks=blocks)

    @staticmethod
    def _items(result) -> list:
        doc = getattr(result, "document", result)
        iterate = getattr(doc, "iterate_items", None)
        if callable(iterate):
            return list(iterate())
        items = []
        for attr in ("texts", "tables", "paragraphs"):
            items.extend(getattr(doc, attr, []) or [])
        return items

    @staticmethod
    def _item_text(item) -> str:
        text = getattr(item, "text", None)
        if not text:
            to_text = getattr(item, "to_text", None)
            if callable(to_text):
                try:
                    text = to_text()
                except Exception:  # noqa: BLE001
                    text = ""
        return text or ""

    @staticmethod
    def _prov(item) -> tuple[int, list[int]]:
        page_no, bbox = 1, [0, 0, 0, 0]
        prov = getattr(item, "prov", None)
        if prov:
            prov = prov[0] if isinstance(prov, (list, tuple)) else prov
            page_no = int(getattr(prov, "page_no", 1) or 1)
            bb = getattr(prov, "bbox", None)
            if bb is not None:
                bbox = [int(getattr(bb, "l", 0) or 0), int(getattr(bb, "t", 0) or 0),
                        int(getattr(bb, "r", 0) or 0), int(getattr(bb, "b", 0) or 0)]
        return page_no, bbox


class PaddleOCRParser(Parser):
    """图片文字识别（真实实现，依赖 paddleocr）。"""

    def parse(self, path: str | Path) -> Document:
        p = Path(path)
        if not p.exists():
            raise ParseError(f"文件不存在：{p}")
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise ParseError("未安装 paddleocr，无法识别图片。请 `pip install paddleocr paddlepaddle` 后重试。") from exc
        try:
            ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
            result = ocr.ocr(str(p), cls=True)
        except Exception as exc:  # noqa: BLE001
            raise ParseError(f"paddleocr 识别失败：{exc}") from exc
        blocks = self._blocks_from_ocr(result)
        if not blocks:
            raise ParseError(f"paddleocr 未识别到文字：{p.name}")
        return Document(doc_id=p.stem, title=p.name, format=p.suffix.lstrip(".").lower(),
                        source_path=str(p), blocks=blocks)

    @staticmethod
    def _blocks_from_ocr(result) -> list[Block]:
        blocks: list[Block] = []
        if not result:
            return blocks
        # paddleocr 3.x：list[dict]（含 rec_texts / rec_scores / rec_polys）
        if isinstance(result, list) and result and isinstance(result[0], dict):
            for page_no, page in enumerate(result, 1):
                texts = page.get("rec_texts") or []
                polys = page.get("rec_polys") or []
                for i, text in enumerate(texts):
                    if not text:
                        continue
                    bbox = [0, 0, 0, 0]
                    if i < len(polys) and polys[i]:
                        xs = [pt[0] for pt in polys[i]]
                        ys = [pt[1] for pt in polys[i]]
                        bbox = [int(min(xs)), int(min(ys)), int(max(xs) - min(xs)), int(max(ys) - min(ys))]
                    blocks.append(Block(text=text, page_no=page_no, bbox=bbox))
            return blocks
        # paddleocr 2.x：list[page] -> list[[box, (text, conf)]]
        for page_no, page in enumerate(result, 1):
            if not page:
                continue
            for line in page:
                if len(line) < 2:
                    continue
                box, rec = line[0], line[1]
                text = rec[0] if isinstance(rec, (list, tuple)) else str(rec)
                if not text:
                    continue
                xs = [pt[0] for pt in box]
                ys = [pt[1] for pt in box]
                bbox = [int(min(xs)), int(min(ys)), int(max(xs) - min(xs)), int(max(ys) - min(ys))]
                blocks.append(Block(text=text, page_no=page_no, bbox=bbox))
        return blocks


def parser_for(path: str | Path) -> Parser:
    suffix = Path(path).suffix.lower()
    if suffix == ".json":
        return JsonSampleParser()
    if suffix in (".txt", ".md"):
        return TextParser()
    if suffix in (".pdf", ".docx"):
        return DoclingParser()
    if suffix in (".png", ".jpg", ".jpeg", ".bmp", ".webp"):
        return PaddleOCRParser()
    raise ParseError(f"不支持的格式：{suffix or '(无扩展名)'}")
