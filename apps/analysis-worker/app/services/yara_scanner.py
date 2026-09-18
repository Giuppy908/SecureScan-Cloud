"""Supporto YARA per la pipeline malware del worker.

YARA è uno strumento complementare a ClamAV: invece di cercare solo firme
antivirus tradizionali, applica regole descrittive che possono intercettare
marker demo, pattern sospetti o regole dichiarate come malevole.

I match prodotti qui vengono poi mostrati soprattutto in Dettaglio analisi e
influenzano verdict e risk level finali.
"""

# Permette di gestire le annotazioni di tipo in modo posticipato
from __future__ import annotations

# `dataclass` permette di definire strutture dati compatte e immutabili per risultati e match YARA
from dataclasses import dataclass

# `lru_cache` permette di riutilizzare una sola istanza dello scanner YARA nel processo worker
from functools import lru_cache

# `Path` viene utilizzato per gestire la directory contenente i file delle regole YARA
from pathlib import Path

# Libreria Python che compila le regole YARA ed esegue il matching sui byte del file
import yara

# Configurazione del worker da cui vengono lette directory delle regole e timeout di scansione
from app.core.config import settings


# Rappresenta una singola regola YARA che ha prodotto un match sul contenuto analizzato
@dataclass(frozen=True, slots=True)
class YaraRuleMatch:
    """Singola regola YARA trovata con i metadati utili alla GUI."""

    # Nome della regola YARA che ha prodotto il match
    rule_name: str

    # Namespace associato al file di regole durante la compilazione
    namespace: str | None

    # Descrizione opzionale definita nei metadata della regola
    description: str | None

    # Severità opzionale definita nella regola e successivamente utilizzata dalla MalwareScanPipeline
    severity: str | None

    # Categoria opzionale associata alla regola
    category: str | None

    # Autore opzionale dichiarato nei metadata della regola
    author: str | None

    # Riferimento opzionale associato alla regola
    reference: str | None

    # Elenco dei tag YARA associati alla regola
    tags: list[str]

    # Converte il match in un dizionario serializzabile che potrà essere salvato nel database
    def as_dict(self) -> dict[str, object]:
        """Converte il match nel formato serializzabile salvato nel database."""

        # Restituisce tutti i campi del match in una struttura compatibile con la persistenza
        return {
            "rule_name": self.rule_name,
            "namespace": self.namespace,
            "description": self.description,
            "severity": self.severity,
            "category": self.category,
            "author": self.author,
            "reference": self.reference,
            "tags": list(self.tags),
        }


# Raccoglie l'esito complessivo della scansione YARA
@dataclass(frozen=True, slots=True)
class YaraScanResult:
    """Esito normalizzato della scansione YARA."""

    # Stato normalizzato della scansione: clean, matched oppure error
    status: str

    # Elenco delle regole YARA che hanno prodotto un match
    matches: list[YaraRuleMatch]

    # Messaggio tecnico presente quando la scansione termina con un errore
    error_message: str | None = None


# Eccezione specifica usata quando le regole non possono essere trovate, caricate o compilate
class YaraRuleCompilerError(RuntimeError):
    """Errore quando le regole YARA non possono essere compilate o caricate."""


# Scanner che compila le regole YARA e le riutilizza per analizzare più file
class YaraScanner:
    """Compila le regole una sola volta e le riusa per tutte le scansioni.

    Questa scelta evita di ricompilare le stesse regole a ogni file e rende il
    worker più efficiente e prevedibile.
    """

    # Inizializza lo scanner scegliendo la directory delle regole e compilando immediatamente i file .yar
    def __init__(self, rules_dir: str | Path | None = None) -> None:

        # Usa la directory fornita oppure quella configurata nel worker
        self._rules_dir = Path(rules_dir or settings.yara_rules_dir)

        # Compila le regole una sola volta durante la costruzione dello scanner
        self._compiled_rules = self._compile_rules()

    # Esegue il matching delle regole YARA sui byte del file già caricati in memoria
    def scan_bytes(self, content: bytes) -> YaraScanResult:
        """Esegue il matching YARA sui byte del file già caricati in memoria."""

        # Tenta di applicare tutte le regole compilate al contenuto del file
        try:

            # YARA analizza direttamente i byte e interrompe il matching se supera il timeout configurato
            matches = self._compiled_rules.match(data=content, timeout=settings.yara_match_timeout_seconds)

        # Un timeout viene trasformato in un risultato di errore invece di propagare l'eccezione
        except yara.TimeoutError:
            return YaraScanResult(status="error", matches=[], error_message="YARA ha superato il timeout di scansione.")

        # Qualsiasi altro errore YARA durante il matching viene normalizzato come errore di scansione
        except yara.Error as exc:
            return YaraScanResult(status="error", matches=[], error_message=f"Errore YARA: {exc}")

        # Converte ogni match grezzo restituito da yara-python in una struttura applicativa YaraRuleMatch
        normalized_matches = [
            YaraRuleMatch(

                # Nome della regola che ha prodotto il match
                rule_name=match.rule,

                # Namespace associato alla regola durante la compilazione
                namespace=getattr(match, "namespace", None),

                # Metadata opzionali definiti direttamente nel file .yar
                description=match.meta.get("description"),
                severity=match.meta.get("severity"),
                category=match.meta.get("category"),
                author=match.meta.get("author"),
                reference=match.meta.get("reference"),

                # Tag associati alla regola, convertiti in una normale lista Python
                tags=list(getattr(match, "tags", []) or []),
            )
            for match in matches
        ]

        # Se almeno una regola ha prodotto un match lo stato è matched, altrimenti clean
        status = "matched" if normalized_matches else "clean"

        # Restituisce lo stato della scansione insieme all'elenco dei match normalizzati
        return YaraScanResult(status=status, matches=normalized_matches)

    # Cerca e compila tutte le regole .yar presenti nella directory configurata
    def _compile_rules(self) -> yara.Rules:
        """Compila tutte le regole `.yar` presenti nella directory configurata."""

        # Se la directory delle regole non esiste impedisce la costruzione dello scanner
        if not self._rules_dir.exists():
            raise YaraRuleCompilerError(f"Directory regole YARA non trovata: {self._rules_dir}")

        # Cerca ricorsivamente tutti i file .yar e associa a ciascuno un namespace basato sul nome del file
        filepaths = {
            path.stem: str(path)
            for path in sorted(self._rules_dir.rglob("*.yar"))
        }

        # Se non è stata trovata alcuna regola impedisce la costruzione dello scanner
        if not filepaths:
            raise YaraRuleCompilerError(f"Nessuna regola YARA trovata in {self._rules_dir}.")

        # Tenta di compilare insieme tutte le regole individuate
        try:
            return yara.compile(filepaths=filepaths)

        # Un errore di sintassi o compilazione YARA viene convertito in un'eccezione applicativa specifica
        except yara.Error as exc:
            raise YaraRuleCompilerError(f"Compilazione YARA fallita: {exc}") from exc


# Memorizza e riutilizza una sola istanza dello scanner YARA standard all'interno del processo worker
@lru_cache(maxsize=1)
def get_default_yara_scanner() -> YaraScanner:
    """Restituisce l'istanza YARA standard condivisa dal processo worker."""

    # Alla prima chiamata costruisce lo scanner; le successive ricevono la stessa istanza già inizializzata
    return YaraScanner()
