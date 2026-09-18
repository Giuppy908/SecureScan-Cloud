"""Analisi strutturale preliminare dei file caricati.

Questo servizio non è la pipeline antimalware completa. Serve a ricavare
metadati tecnici come hash, MIME, entropia e indicatori strutturali che poi
appaiono soprattutto nel Dettaglio analisi.

La scansione antimalware vera e propria resta in carico al worker con ClamAV
e YARA.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings
from app.models.analysis import AnalysisCreateResult, AnalysisStatus, RiskLevel

MIME_BY_EXTENSION: dict[str, set[str]] = {
    ".txt": {"text/plain"},
    ".csv": {"text/csv", "text/plain"},
    ".json": {"application/json", "text/plain"},
    ".pdf": {"application/pdf"},
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".gif": {"image/gif"},
    ".zip": {"application/zip"},
    ".exe": {"application/x-dosexec", "application/octet-stream"},
}

MAGIC_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"PK\x03\x04", "application/zip"),
    (b"MZ", "application/x-dosexec"),
)

TEXT_MIME_PREFIXES: tuple[str, ...] = ("text/",)
TEXT_EXTENSIONS: set[str] = {".txt", ".csv", ".json", ".py", ".js", ".md", ".xml", ".html"}


class FileAnalyzer:
    """Analizza file senza eseguirli e senza affidarsi a processi esterni."""

    async def analyze_upload(self, uploaded_file: UploadFile) -> AnalysisCreateResult:
        """Legge l'upload in memoria e calcola metadati e indicatori di base."""
        file_name = uploaded_file.filename or "uploaded-file"
        content = await uploaded_file.read()

        size_bytes = len(content)
        if size_bytes == 0:
            raise ValueError("Uploaded file is empty.")
        if size_bytes > settings.max_upload_size_bytes:
            raise ValueError(
                f"Uploaded file exceeds the maximum allowed size of {settings.max_upload_size_label}."
            )

        mime_type = self._detect_mime_type(content, uploaded_file.content_type)
        extension = Path(file_name).suffix.lower()
        extension_matches_mime = self._extension_matches_mime(extension, mime_type)
        entropy = self._calculate_shannon_entropy(content)

        indicators = self._build_indicators(
            size_bytes=size_bytes,
            mime_type=mime_type,
            entropy=entropy,
            extension=extension,
            extension_matches_mime=extension_matches_mime,
        )
        risk_level = self._classify_risk(indicators)

        return AnalysisCreateResult(
            file_name=file_name,
            status=AnalysisStatus.COMPLETED,
            risk_level=risk_level,
            size_bytes=size_bytes,
            mime_type=mime_type,
            sha256=hashlib.sha256(content).hexdigest(),
            entropy=round(entropy, 4),
            extension_matches_mime=extension_matches_mime,
            indicators=indicators,
            error_message=None,
        )

    def _detect_mime_type(self, content: bytes, declared_mime_type: str | None) -> str:
        """Infer a preliminary MIME type from file signatures and text heuristics."""
        for signature, mime_type in MAGIC_SIGNATURES:
            if content.startswith(signature):
                return mime_type

        if self._looks_like_text(content):
            return declared_mime_type or "text/plain"

        if declared_mime_type:
            return declared_mime_type

        return "application/octet-stream"

    def _looks_like_text(self, content: bytes) -> bool:
        """Approximate whether the content resembles text."""
        if not content:
            return False

        printable = sum(
            1
            for byte in content
            if byte in (9, 10, 13) or 32 <= byte <= 126
        )
        return printable / len(content) >= 0.95

    def _extension_matches_mime(self, extension: str, mime_type: str) -> bool:
        """Check whether the file extension is coherent with the inferred MIME type."""
        if not extension:
            return True

        expected_mime_types = MIME_BY_EXTENSION.get(extension)
        if expected_mime_types is not None:
            return mime_type in expected_mime_types

        if extension in TEXT_EXTENSIONS and mime_type.startswith(TEXT_MIME_PREFIXES):
            return True

        return mime_type == "application/octet-stream"

    def _calculate_shannon_entropy(self, content: bytes) -> float:
        """Compute Shannon entropy over byte frequencies."""
        counts = Counter(content)
        length = len(content)
        return -sum(
            (count / length) * math.log2(count / length)
            for count in counts.values()
        )

    def _build_indicators(
        self,
        *,
        size_bytes: int,
        mime_type: str,
        entropy: float,
        extension: str,
        extension_matches_mime: bool,
    ) -> list[str]:
        """Costruisce indicatori descrittivi che non equivalgono a una detection."""
        indicators: list[str] = []

        if not extension_matches_mime:
            indicators.append(
                f"Extension '{extension or '[none]'}' does not match the inferred MIME type '{mime_type}'."
            )

        if entropy >= settings.entropy_medium_threshold:
            indicators.append(
                f"High entropy ({entropy:.2f}) suggests compressed or obfuscated content, but does not prove malware."
            )

        if mime_type == "application/x-dosexec":
            indicators.append(
                "Executable file format detected; treat with caution because this service does not execute the file."
            )

        if size_bytes >= 5 * 1024 * 1024:
            indicators.append(
                "Large file size may require deeper inspection outside this initial local API."
            )

        return indicators

    def _classify_risk(self, indicators: list[str]) -> RiskLevel:
        """Deriva un rischio preliminare dalla sola analisi strutturale."""
        if not indicators:
            return RiskLevel.LOW
        if len(indicators) >= 2:
            return RiskLevel.HIGH
        return RiskLevel.MEDIUM


file_analyzer = FileAnalyzer()


def get_file_analyzer() -> FileAnalyzer:
    """Dependency FastAPI per il servizio di analisi strutturale."""
    return file_analyzer
