"""Analisi strutturale preliminare dei file caricati.

Questo servizio calcola metadati tecnici che poi compaiono soprattutto in
Dettaglio analisi:
- SHA-256;
- MIME type;
- entropia;
- coerenza tra estensione e MIME;
- alcuni indicatori tecnici descrittivi.

È importante capire cosa NON fa: da solo non stabilisce se un file è malware.
Per quello servono ClamAV, YARA e l'aggregazione finale della pipeline.
"""

# Permette di gestire le annotazioni di tipo in modo posticipato
from __future__ import annotations

# `hashlib` viene utilizzato per calcolare l'hash SHA-256 del contenuto del file
import hashlib

# `math` fornisce log2(), necessario per il calcolo dell'entropia di Shannon
import math

# `Counter` conta quante volte compare ciascun byte all'interno del file
from collections import Counter

# `dataclass` permette di definire strutture dati compatte usate per raccogliere segnali e risultati
from dataclasses import dataclass

# `Path` viene utilizzato per ricavare l'estensione dal nome originale del file
from pathlib import Path

# Configurazione applicativa da cui viene letta la soglia utilizzata per considerare elevata l'entropia
from app.core.config import settings

# Enum che rappresenta i possibili livelli di rischio assegnati all'analisi
from app.db.models import RiskLevel

# Associa alcune estensioni note ai MIME type considerati compatibili con esse
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

# Elenca alcune firme binarie riconoscibili all'inizio del file e il MIME type corrispondente
MAGIC_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"PK\x03\x04", "application/zip"),
    (b"MZ", "application/x-dosexec"),
)

# Prefisso MIME utilizzato per riconoscere genericamente i file di testo
TEXT_MIME_PREFIXES: tuple[str, ...] = ("text/",)

# Estensioni che possono essere considerate coerenti con un MIME type testuale
TEXT_EXTENSIONS: set[str] = {".txt", ".csv", ".json", ".py", ".js", ".md", ".xml", ".html"}

# Formati normalmente compressi per i quali un'entropia elevata può essere perfettamente normale
NATURALLY_COMPRESSED_MIME_TYPES: set[str] = {
    "application/pdf",
    "application/zip",
    "image/png",
    "image/jpeg",
    "image/gif",
}

# Soglia di 5 MiB usata per classificare descrittivamente un file come grande
LARGE_FILE_SIZE_THRESHOLD_BYTES = 5 * 1024 * 1024


# Raccoglie i segnali tecnici intermedi ricavati dal file prima della classificazione del rischio
@dataclass(frozen=True, slots=True)
class AnalysisSignals:
    """Segnali tecnici estratti dal file prima della scansione antimalware."""

    # Dimensione effettiva del contenuto analizzato, espressa in byte
    size_bytes: int

    # MIME type inferito dal contenuto del file
    mime_type: str

    # Valore dell'entropia di Shannon calcolato sui byte del file
    entropy: float

    # Estensione ricavata dal filename originale
    extension: str

    # Indica se l'estensione è coerente con il MIME type individuato
    extension_matches_mime: bool

    # Indica se l'entropia supera la soglia configurata
    is_high_entropy: bool

    # Indica se il contenuto è stato riconosciuto come eseguibile DOS/Windows
    is_executable: bool

    # Indica se il MIME appartiene a un formato che normalmente contiene dati compressi
    is_naturally_compressed_format: bool

    # Indica se il file supera la soglia descrittiva di 5 MiB
    is_large_file: bool


# Raccoglie il risultato finale prodotto dalla sola analisi strutturale
@dataclass(frozen=True, slots=True)
class StructuralAnalysisResult:
    """Risultato dell'analisi strutturale eseguita senza ClamAV o YARA."""

    # Livello di rischio preliminare derivato esclusivamente dai segnali strutturali
    risk_level: RiskLevel

    # MIME type inferito dal contenuto
    mime_type: str

    # Fingerprint SHA-256 del contenuto del file
    sha256: str

    # Entropia di Shannon arrotondata
    entropy: float

    # Esito del controllo di coerenza tra estensione e MIME
    extension_matches_mime: bool

    # Elenco delle osservazioni tecniche prodotte durante l'analisi
    indicators: list[str]


# Esegue l'analisi strutturale sui byte del file senza eseguirne il contenuto
class FileAnalyzer:
    """Analizza i byte di un file senza eseguirlo.

    Il worker usa questo passaggio per ottenere segnali utili ma non conclusivi:
    un'entropia elevata o un'estensione incoerente possono essere interessanti,
    ma non dimostrano da soli che il file sia malevolo.
    """

    # Analizza filename e contenuto del file e restituisce tutti i risultati strutturali calcolati
    def analyze_file(
        self,
        *,
        file_name: str,
        content: bytes,
        declared_mime_type: str | None = None,
    ) -> StructuralAnalysisResult:

        # Un file privo di contenuto non può essere sottoposto all'analisi strutturale
        if not content:
            raise ValueError("Stored file is empty.")

        # Determina preliminarmente il MIME type osservando prima il contenuto del file
        mime_type = self._detect_mime_type(content, declared_mime_type)

        # Ricava dal filename solamente l'estensione e la normalizza in minuscolo
        extension = Path(file_name).suffix.lower()

        # Verifica se l'estensione dichiarata dal nome del file è coerente con il MIME rilevato
        extension_matches_mime = self._extension_matches_mime(extension, mime_type)

        # Calcola l'entropia di Shannon del contenuto binario
        entropy = self._calculate_shannon_entropy(content)

        # Riunisce i valori appena calcolati in un'unica struttura di segnali tecnici
        signals = self._build_signals(
            size_bytes=len(content),
            mime_type=mime_type,
            entropy=entropy,
            extension=extension,
            extension_matches_mime=extension_matches_mime,
        )

        # Converte i segnali tecnici rilevanti in descrizioni comprensibili da mostrare nel risultato
        indicators = self._build_indicators(
            signals=signals,
        )

        # Assegna un rischio strutturale preliminare in base alla combinazione dei segnali rilevati
        risk_level = self._classify_risk(signals)

        # Restituisce il risultato strutturale che la pipeline unirà successivamente agli esiti di ClamAV e YARA
        return StructuralAnalysisResult(
            risk_level=risk_level,
            mime_type=mime_type,
            sha256=hashlib.sha256(content).hexdigest(),
            entropy=round(entropy, 4),
            extension_matches_mime=extension_matches_mime,
            indicators=indicators,
        )

    # Determina un MIME type preliminare dando priorità alle firme binarie presenti nel contenuto
    def _detect_mime_type(self, content: bytes, declared_mime_type: str | None) -> str:

        # Confronta l'inizio del file con ciascuna firma conosciuta
        for signature, mime_type in MAGIC_SIGNATURES:

            # Se il contenuto inizia con una firma nota restituisce immediatamente il MIME associato
            if content.startswith(signature):
                return mime_type

        # Se il contenuto appare prevalentemente testuale utilizza il MIME dichiarato oppure text/plain
        if self._looks_like_text(content):
            return declared_mime_type or "text/plain"

        # Per contenuti non riconosciuti usa il MIME dichiarato, se disponibile
        if declared_mime_type:
            return declared_mime_type

        # Se non è possibile riconoscere il formato usa il MIME generico per dati binari
        return "application/octet-stream"

    # Stima se il contenuto del file può essere considerato prevalentemente testo
    def _looks_like_text(self, content: bytes) -> bool:

        # Conta tab, newline, carriage return e caratteri ASCII stampabili
        printable = sum(
            1
            for byte in content
            if byte in (9, 10, 13) or 32 <= byte <= 126
        )

        # Considera testuale il file se almeno il 95% dei byte rientra tra quelli considerati stampabili
        return printable / len(content) >= 0.95

    # Controlla se l'estensione del file è compatibile con il MIME type individuato
    def _extension_matches_mime(self, extension: str, mime_type: str) -> bool:

        # L'assenza di un'estensione non viene considerata automaticamente una discordanza
        if not extension:
            return True

        # Cerca l'estensione nella tabella delle associazioni note
        expected_mime_types = MIME_BY_EXTENSION.get(extension)

        # Per un'estensione conosciuta verifica che il MIME rilevato sia tra quelli ammessi
        if expected_mime_types is not None:
            return mime_type in expected_mime_types

        # Per altre estensioni testuali accetta qualsiasi MIME appartenente alla famiglia text/*
        if extension in TEXT_EXTENSIONS and mime_type.startswith(TEXT_MIME_PREFIXES):
            return True

        # Per un'estensione non riconosciuta considera coerente soltanto un contenuto binario generico
        return mime_type == "application/octet-stream"

    # Calcola l'entropia di Shannon, che misura quanto è uniforme e quindi poco prevedibile la distribuzione dei byte nel file
    def _calculate_shannon_entropy(self, content: bytes) -> float:
        """Calcola l'entropia di Shannon, utile per notare contenuti molto densi."""

        # Conta quante volte compare ciascun possibile valore di byte
        counts = Counter(content)

        # Memorizza il numero totale di byte per calcolare la frequenza relativa di ciascun valore
        length = len(content)

        # Applica la formula di Shannon: valori più alti indicano una distribuzione dei byte più uniforme
        return -sum((count / length) * math.log2(count / length) for count in counts.values())

    # Trasforma i valori tecnici calcolati in segnali booleani più semplici da usare nelle regole successive
    def _build_signals(
        self,
        *,
        size_bytes: int,
        mime_type: str,
        entropy: float,
        extension: str,
        extension_matches_mime: bool,
    ) -> AnalysisSignals:

        # Costruisce la struttura che riassume le caratteristiche rilevanti individuate nel file
        return AnalysisSignals(
            size_bytes=size_bytes,
            mime_type=mime_type,
            entropy=entropy,
            extension=extension,
            extension_matches_mime=extension_matches_mime,
            is_high_entropy=entropy >= settings.entropy_medium_threshold,
            is_executable=mime_type == "application/x-dosexec",
            is_naturally_compressed_format=mime_type in NATURALLY_COMPRESSED_MIME_TYPES,
            is_large_file=size_bytes >= LARGE_FILE_SIZE_THRESHOLD_BYTES,
        )

    # Crea un elenco di messaggi che descrivono le caratteristiche rilevanti individuate durante l'analisi strutturale del file
    def _build_indicators(
        self,
        *,
        signals: AnalysisSignals,
    ) -> list[str]:

        # L'elenco parte vuoto e viene popolato soltanto quando viene individuato un segnale rilevante
        indicators: list[str] = []

        # Segnala quando il tipo reale inferito dal contenuto non è coerente con l'estensione del filename
        if not signals.extension_matches_mime:
            indicators.append(
                f"Extension '{signals.extension or '[none]'}' does not match the inferred MIME type '{signals.mime_type}'."
            )

        # Un'entropia elevata viene registrata come indicatore, ma non viene considerata da sola una prova di malware
        if signals.is_high_entropy:

            # Nei formati normalmente compressi un'alta entropia può essere perfettamente compatibile con il formato
            if signals.is_naturally_compressed_format and signals.extension_matches_mime:
                indicators.append(
                    f"High entropy ({signals.entropy:.2f}) is compatible with compressed content in this file format."
                )

            # Negli altri casi può suggerire compressione, packing, cifratura o offuscamento del contenuto
            else:
                indicators.append(
                    f"High entropy ({signals.entropy:.2f}) may indicate compressed or obfuscated content."
                )

        # Segnala esplicitamente quando il formato riconosciuto è quello di un eseguibile
        if signals.is_executable:
            indicators.append(
                "Executable file format detected; treat with caution because this service does not execute the file."
            )

        # Segnala i file che superano la soglia descrittiva di 5 MiB
        if signals.is_large_file:
            indicators.append(
                "Large file size may require deeper inspection outside this initial worker implementation."
            )

        # Restituisce tutti gli indicatori descrittivi prodotti
        return indicators

    # Determina un livello di rischio preliminare dai soli segnali strutturali; la pipeline lo combinerà successivamente con gli esiti di ClamAV e YARA
    def _classify_risk(self, signals: AnalysisSignals) -> RiskLevel:
        """Deriva un rischio strutturale prudente prima della pipeline malware."""

        # Un eseguibile mascherato con un'estensione incoerente viene considerato il caso strutturalmente più critico
        if signals.is_executable and not signals.extension_matches_mime:
            return RiskLevel.CRITICAL

        # Un eseguibile riconosciuto correttamente viene comunque considerato ad alto rischio strutturale
        if signals.is_executable:
            return RiskLevel.HIGH

        # La combinazione di estensione incoerente e alta entropia produce un rischio elevato
        if not signals.extension_matches_mime and signals.is_high_entropy:
            return RiskLevel.HIGH

        # Una sola discordanza tra estensione e MIME produce un rischio medio
        if not signals.extension_matches_mime:
            return RiskLevel.MEDIUM

        # Se l'unico segnale significativo è l'alta entropia il rischio dipende dal tipo di formato
        if signals.is_high_entropy:

            # Nei formati normalmente compressi un'entropia alta viene considerata normale
            if signals.is_naturally_compressed_format:
                return RiskLevel.LOW

            # Negli altri formati l'alta entropia produce un rischio medio
            return RiskLevel.MEDIUM

        # Un file grande, senza altri segnali sospetti, mantiene un rischio basso
        if signals.is_large_file:
            return RiskLevel.LOW

        # Un file piccolo, coerente, non eseguibile e senza alta entropia viene classificato a basso rischio
        if (
            not signals.is_large_file
            and not signals.is_high_entropy
            and not signals.is_executable
            and signals.extension_matches_mime
        ):
            return RiskLevel.LOW

        # Qualsiasi caso residuo non coperto dalle regole precedenti viene classificato a basso rischio
        return RiskLevel.LOW


# Istanza condivisa e stateless del servizio utilizzata dalla pipeline del worker
file_analyzer = FileAnalyzer()
