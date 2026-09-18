"""Test dell'analisi strutturale preliminare del worker.

Questi casi verificano i metadati tecnici che compaiono soprattutto in
Dettaglio analisi: SHA-256, MIME, entropia, coerenza estensione/MIME e
risk level strutturale prima di ClamAV e YARA.
"""

import hashlib

from app.db.models import RiskLevel
from app.services.file_analyzer import FileAnalyzer


def repeated_byte_range(repetitions: int = 32) -> bytes:
    """Genera contenuto ad alta entropia per i test strutturali."""
    return bytes(range(256)) * repetitions


def high_entropy_pdf_bytes() -> bytes:
    return b"%PDF-1.7\n" + repeated_byte_range()


def high_entropy_zip_bytes() -> bytes:
    return b"PK\x03\x04" + repeated_byte_range()


def high_entropy_png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + repeated_byte_range()


def high_entropy_jpeg_bytes() -> bytes:
    return b"\xff\xd8\xff" + repeated_byte_range()


def high_entropy_executable_bytes() -> bytes:
    return b"MZ" + repeated_byte_range()


def test_text_file_is_low_risk() -> None:
    analyzer = FileAnalyzer()

    result = analyzer.analyze_file(file_name="sample.txt", content=b"hello worker")

    assert result.sha256 == hashlib.sha256(b"hello worker").hexdigest()
    assert result.mime_type == "text/plain"
    assert result.extension_matches_mime is True
    assert result.risk_level == RiskLevel.LOW
    assert result.indicators == []


def test_pdf_with_high_entropy_and_matching_mime_is_low_risk() -> None:
    analyzer = FileAnalyzer()
    content = high_entropy_pdf_bytes()

    result = analyzer.analyze_file(file_name="slides.pdf", content=content)

    assert result.mime_type == "application/pdf"
    assert result.entropy is not None and result.entropy >= 7.2
    assert result.extension_matches_mime is True
    assert result.risk_level == RiskLevel.LOW
    assert any("compatible with compressed content" in indicator for indicator in result.indicators)


def test_zip_with_high_entropy_and_matching_mime_is_low_risk() -> None:
    analyzer = FileAnalyzer()

    result = analyzer.analyze_file(file_name="archive.zip", content=high_entropy_zip_bytes())

    assert result.mime_type == "application/zip"
    assert result.entropy is not None and result.entropy >= 7.2
    assert result.extension_matches_mime is True
    assert result.risk_level == RiskLevel.LOW


def test_jpeg_with_high_entropy_and_matching_mime_is_low_risk() -> None:
    analyzer = FileAnalyzer()

    result = analyzer.analyze_file(file_name="image.jpg", content=high_entropy_jpeg_bytes())

    assert result.mime_type == "image/jpeg"
    assert result.entropy is not None and result.entropy >= 7.2
    assert result.extension_matches_mime is True
    assert result.risk_level == RiskLevel.LOW


def test_unknown_high_entropy_binary_is_medium_risk() -> None:
    analyzer = FileAnalyzer()
    content = repeated_byte_range()

    result = analyzer.analyze_file(file_name="payload.bin", content=content)

    assert result.mime_type == "application/octet-stream"
    assert result.entropy is not None and result.entropy >= 7.2
    assert result.extension_matches_mime is True
    assert result.risk_level == RiskLevel.MEDIUM
    assert any("may indicate compressed or obfuscated content" in indicator for indicator in result.indicators)


def test_extension_mismatch_without_other_signals_is_medium_risk() -> None:
    analyzer = FileAnalyzer()
    content = b"%PDF-1.7\nplain-text-body"

    result = analyzer.analyze_file(file_name="report.txt", content=content)

    assert result.mime_type == "application/pdf"
    assert result.extension_matches_mime is False
    assert result.entropy is not None and result.entropy < 7.2
    assert result.risk_level == RiskLevel.MEDIUM


def test_extension_mismatch_with_high_entropy_is_high_risk() -> None:
    analyzer = FileAnalyzer()

    result = analyzer.analyze_file(file_name="report.txt", content=high_entropy_pdf_bytes())

    assert result.mime_type == "application/pdf"
    assert result.extension_matches_mime is False
    assert result.entropy is not None and result.entropy >= 7.2
    assert result.risk_level == RiskLevel.HIGH


def test_executable_with_matching_extension_is_high_risk() -> None:
    analyzer = FileAnalyzer()

    result = analyzer.analyze_file(file_name="launcher.exe", content=high_entropy_executable_bytes())

    assert result.mime_type == "application/x-dosexec"
    assert result.extension_matches_mime is True
    assert result.risk_level == RiskLevel.HIGH
    assert any("Executable file format detected" in indicator for indicator in result.indicators)


def test_disguised_executable_is_critical_risk() -> None:
    analyzer = FileAnalyzer()

    result = analyzer.analyze_file(file_name="presentation.pdf", content=high_entropy_executable_bytes())

    assert result.mime_type == "application/x-dosexec"
    assert result.extension_matches_mime is False
    assert result.risk_level == RiskLevel.CRITICAL


def test_large_file_without_other_signals_is_low_risk() -> None:
    analyzer = FileAnalyzer()
    content = b"A" * (5 * 1024 * 1024)

    result = analyzer.analyze_file(file_name="large.txt", content=content)

    assert result.mime_type == "text/plain"
    assert result.extension_matches_mime is True
    assert result.risk_level == RiskLevel.LOW
    assert result.indicators == [
        "Large file size may require deeper inspection outside this initial worker implementation."
    ]


def test_png_high_entropy_indicator_message_is_not_alarmist() -> None:
    analyzer = FileAnalyzer()

    result = analyzer.analyze_file(file_name="diagram.png", content=high_entropy_png_bytes())

    entropy_indicator = next(indicator for indicator in result.indicators if "High entropy" in indicator)
    assert "compatible with compressed content" in entropy_indicator
    assert "malware" not in entropy_indicator.lower()
    assert "obfuscated" not in entropy_indicator.lower()


def test_sha256_mime_entropy_and_extension_match_are_calculated_correctly() -> None:
    analyzer = FileAnalyzer()
    content = b"%PDF-1.7\nhello"

    result = analyzer.analyze_file(file_name="hello.pdf", content=content)

    assert result.sha256 == hashlib.sha256(content).hexdigest()
    assert result.mime_type == "application/pdf"
    assert result.entropy is not None
    assert result.extension_matches_mime is True
