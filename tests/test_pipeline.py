"""核心流程测试：导入 → 检测 → 复核 → 导出 → 断点恢复 → 重复导入。"""
from pathlib import Path

from pii_review.pipeline import export_file, import_file, record_decision
from pii_review.state import load_state, unreviewed_count

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data" / "samples"


def test_import_and_detect(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    state, dup = import_file(str(SAMPLES / "s01.json"))
    assert not dup
    assert state.sha256 and state.candidates
    assert unreviewed_count(state) == len(state.candidates)


def test_duplicate_detection(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    s1, dup1 = import_file(str(SAMPLES / "s01.json"))
    s2, dup2 = import_file(str(SAMPLES / "s01.json"))
    assert dup1 is False and dup2 is True
    assert s2.sha256 == s1.sha256


def test_export_without_confirmed_fragment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    state, _ = import_file(str(SAMPLES / "s01.json"))
    for c in state.candidates:
        record_decision(state.sha256, c.id, "redact", "测试遮盖")
    export_file(state.sha256, str(tmp_path / "out"))
    redacted = (tmp_path / "out" / f"{state.sha256[:8]}.redacted.txt").read_text(encoding="utf-8")
    assert "13800138000" not in redacted
    assert "[已遮盖:电话]" in redacted


def test_broken_phone_redaction(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    state, _ = import_file(str(SAMPLES / "s03.json"))
    broken = [c for c in state.candidates if c.source == "phone_broken_line"][0]
    record_decision(state.sha256, broken.id, "redact", "遮盖断行电话")
    export_file(state.sha256, str(tmp_path / "out"))
    redacted = (tmp_path / "out" / f"{state.sha256[:8]}.redacted.txt").read_text(encoding="utf-8")
    assert "1380013" not in redacted and "8000" not in redacted


def test_resume_does_not_mark_unreviewed(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    state, _ = import_file(str(SAMPLES / "s06.json"))
    reloaded = load_state(state.sha256)
    assert unreviewed_count(reloaded) == len(reloaded.candidates)
    assert all(c.id not in reloaded.decisions for c in reloaded.candidates)
