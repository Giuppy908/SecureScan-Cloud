"""Test del motore YARA usato dal worker.

Questi casi verificano compilazione delle regole, assenza di match, presenza
di match con metadata e comportamento in caso di regole non valide.
"""

from pathlib import Path

import pytest

from app.services.yara_scanner import YaraRuleCompilerError, YaraScanner


def write_rule(directory: Path, content: str) -> Path:
    """Scrive una regola temporanea per isolare gli scenari di test."""
    target = directory / "rules.yar"
    target.write_text(content, encoding="utf-8")
    return target


def test_yara_scanner_returns_no_match(tmp_path: Path) -> None:
    write_rule(
        tmp_path,
        """
rule test_rule {
  meta:
    description = "test"
    severity = "test"
    category = "validation"
  strings:
    $a = "SECURESCAN_YARA_TEST_MARKER"
  condition:
    $a
}
""".strip(),
    )

    scanner = YaraScanner(tmp_path)
    result = scanner.scan_bytes(b"hello")

    assert result.status == "clean"
    assert result.matches == []


def test_yara_scanner_returns_match_and_metadata(tmp_path: Path) -> None:
    write_rule(
        tmp_path,
        """
rule test_rule {
  meta:
    description = "rule description"
    severity = "test"
    category = "validation"
  strings:
    $a = "SECURESCAN_YARA_TEST_MARKER"
  condition:
    $a
}
""".strip(),
    )

    scanner = YaraScanner(tmp_path)
    result = scanner.scan_bytes(b"SECURESCAN_YARA_TEST_MARKER")

    assert result.status == "matched"
    assert len(result.matches) == 1
    assert result.matches[0].severity == "test"
    assert result.matches[0].category == "validation"


def test_yara_scanner_raises_for_invalid_rule(tmp_path: Path) -> None:
    write_rule(tmp_path, "rule broken { condition: }")

    with pytest.raises(YaraRuleCompilerError):
        YaraScanner(tmp_path)
