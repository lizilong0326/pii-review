"""识别器单元测试：四类 PII + 断行 / OCR 错字 / 同名实体 / 地址上下文 + 普通编号不误报。"""
from pii_review.detectors import detect
from pii_review.models import Block, Document


def _doc(*texts):
    return Document(doc_id="t", title="t", blocks=[Block(text=t, page_no=1) for t in texts])


def test_phone_exact_high():
    c = detect(_doc("联系13800138000"))
    assert len(c) == 1 and c[0].pii_type == "phone" and c[0].confidence == "high"


def test_phone_hyphen_low():
    c = detect(_doc("联系138-0013-8000"))
    assert c[0].text == "138-0013-8000" and c[0].confidence == "low"


def test_phone_broken_line():
    c = detect(_doc("客户电话：1380013", "8000，请回电。"))
    hits = [x for x in c if x.pii_type == "phone"]
    assert hits and hits[0].text == "13800138000" and hits[0].confidence == "low"
    assert len(hits[0].parts) == 2


def test_phone_ocr_fuzzy():
    c = detect(_doc("138O0138000"))
    assert any(x.text == "138O0138000" and x.confidence == "low" for x in c)


def test_id_exact_high():
    c = detect(_doc("身份证110101199003071234"))
    assert any(x.pii_type == "id_card" and x.confidence == "high" for x in c)


def test_id_ocr_fuzzy():
    c = detect(_doc("11010119900307l234"))
    assert any(x.pii_type == "id_card" and x.text == "11010119900307l234" for x in c)


def test_address_lead():
    c = detect(_doc("联系地址：北京市海淀区中关村大街1号"))
    assert any(x.pii_type == "address" and "中关村" in x.text for x in c)


def test_address_structure():
    c = detect(_doc("北京市朝阳区建国路88号院"))
    assert any(x.pii_type == "address" for x in c)


def test_name_honorific():
    c = detect(_doc("王伟先生您好"))
    assert any(x.pii_type == "name" and x.text == "王伟" for x in c)


def test_ordinary_numbers_not_flagged():
    c = detect(_doc("订单号：A20240101-1234，产品编号：SKU-ABC-12345，日期：2024-01-15"))
    assert c == []
