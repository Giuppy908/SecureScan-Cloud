"""Package principale della SecureScan Analysis API.

Qui si trova il backend FastAPI che serve il frontend di SecureScan Cloud.
Le sue responsabilità principali sono:
- ricevere gli upload di Nuova analisi;
- esporre Cronologia e Dettaglio analisi;
- alimentare Dashboard e Stato del sistema;
- gestire Profilo e Amministrazione;
- applicare autenticazione, RBAC e ownership server-side.
"""
