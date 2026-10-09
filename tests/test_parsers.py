"""解析适配层测试：真实 Docling / PaddleOCR 转换逻辑（用假模块注入，无需安装依赖）。"""
import sys
import types

import pytest

from pii_review.parsers import (DoclingParser, JsonSampleParser, ParseError, PaddleOCRParser,
                                TextParser, parser_for)


class _BBox:
    l, t, r, b = 10, 20, 110, 40


class _Prov:
    page_no = 3
    bbox = _BBox()


class _Item:
    text = "联系13800138000"
    prov = [_Prov()]


def test_parser_for_routing():
    assert isinstance(parser_for("a.json"), JsonSampleParser)
    assert isinstance(parser_for("a.txt"), TextParser)
    assert isinstance(parser_for("a.pdf"), DoclingParser)
    assert isinstance(parser_for("a.docx"), DoclingParser)
    assert isinstance(parser_for("a.png"), PaddleOCRParser)
    assert isinstance(parser_for("a.jpg"), PaddleOCRParser)
    with pytest.raises(ParseError):
        parser_for("a.xyz")


def test_docling_missing_dep(tmp_path):
    f = tmp_path / "x.pdf"
    f.write_bytes(b"%PDF-1.4")
    with pytest.raises(ParseError, match="未安装 docling"):
        DoclingParser().parse(str(f))


def test_paddleocr_missing_dep(tmp_path):
    f = tmp_path / "x.png"
    f.write_bytes(b"\x89PNG")
    with pytest.raises(ParseError, match="未安装 paddleocr"):
        PaddleOCRParser().parse(str(f))


def test_docling_prov_extraction():
    page_no, bbox = DoclingParser._prov(_Item())
    assert page_no == 3
    assert bbox == [10, 20, 110, 40]


def test_docling_end_to_end(tmp_path, monkeypatch):
    f = tmp_path / "x.pdf"
    f.write_bytes(b"%PDF")

    class _Doc:
        def iterate_items(self):
            return [_Item()]

    class _Result:
        document = _Doc()

    class _Converter:
        def convert(self, p):
            return _Result()

    mod = types.ModuleType("docling.document_converter")
    mod.DocumentConverter = _Converter
    monkeypatch.setitem(sys.modules, "docling.document_converter", mod)

    doc = DoclingParser().parse(str(f))
    assert len(doc.blocks) == 1
    assert doc.blocks[0].text == "联系13800138000"
    assert doc.blocks[0].page_no == 3
    assert doc.blocks[0].bbox == [10, 20, 110, 40]


def test_blocks_from_ocr_2x():
    result = [[[[[0, 0], [100, 0], [100, 20], [0, 20]], ("13800138000", 0.99)]]]
    blocks = PaddleOCRParser._blocks_from_ocr(result)
    assert len(blocks) == 1
    assert blocks[0].text == "13800138000"
    assert blocks[0].page_no == 1
    assert blocks[0].bbox == [0, 0, 100, 20]


def test_blocks_from_ocr_3x():
    result = [{"rec_texts": ["王伟先生", ""],
               "rec_polys": [[[0, 0], [50, 0], [50, 20], [0, 20]], None]}]
    blocks = PaddleOCRParser._blocks_from_ocr(result)
    assert len(blocks) == 1
    assert blocks[0].text == "王伟先生"
    assert blocks[0].page_no == 1


def test_blocks_from_ocr_skips_empty():
    result = [[[[[0, 0], [10, 0], [10, 10], [0, 10]], ("", 0.99)]]]
    assert PaddleOCRParser._blocks_from_ocr(result) == []


def test_paddleocr_end_to_end(tmp_path, monkeypatch):
    f = tmp_path / "x.png"
    f.write_bytes(b"\x89PNG")

    class _OCR:
        def __init__(self, **kw):
            pass

        def ocr(self, p, cls=True):
            return [[[[[0, 0], [100, 0], [100, 20], [0, 20]], ("13800138000", 0.99)]]]

    mod = types.ModuleType("paddleocr")
    mod.PaddleOCR = _OCR
    monkeypatch.setitem(sys.modules, "paddleocr", mod)

    doc = PaddleOCRParser().parse(str(f))
    assert len(doc.blocks) == 1
    assert doc.blocks[0].text == "13800138000"
