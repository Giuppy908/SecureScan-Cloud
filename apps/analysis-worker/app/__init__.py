"""Package principale del SecureScan Analysis Worker.

Questo package contiene il processo in background che completa davvero le
scansioni dopo l'upload inviato dalla pagina Nuova analisi.

Il frontend non parla direttamente con questo servizio, ma Cronologia,
Dettaglio analisi, Dashboard e Stato del sistema dipendono dai dati che
questo worker scrive e aggiorna nel database condiviso.
"""
