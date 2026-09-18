# SecureScan ClamAV

ClamAV è il motore antivirus utilizzato all'interno della pipeline di analisi malware di SecureScan Cloud.

Il servizio viene eseguito come componente indipendente dello stack Docker e viene utilizzato esclusivamente dall'Analysis Worker durante l'elaborazione dei file caricati dagli utenti.

## Ruolo nella pipeline

ClamAV rappresenta il livello antivirus della scansione.

Il flusso completo è:

Frontend

↓

Kong API Gateway

↓

Analysis API

↓

PostgreSQL

↓

Analysis Worker

↓

ClamAV / YARA

↓

PostgreSQL

↓

Frontend

Il browser non comunica mai direttamente con ClamAV.

Il file viene ricevuto dall'API, persistito nello storage condiviso e successivamente analizzato dal worker tramite il servizio antivirus interno.

## Modalità di comunicazione

L'Analysis Worker comunica con ClamAV attraverso il servizio `clamd`.

La comunicazione utilizza:

- protocollo TCP;
- porta interna `3310`;
- rete Docker privata `securescan-local`.

Il servizio non espone porte direttamente verso l'host o verso Internet.

L'accesso avviene tramite il nome del servizio Compose:

```text
clamav:3310
```

## Motivo della separazione

ClamAV viene mantenuto come container indipendente per separare il motore antivirus dal codice applicativo.

Questa scelta permette di:

- aggiornare il database delle firme senza modificare l'applicazione;
- isolare il processo antivirus;
- controllare disponibilità e salute del servizio;
- scalare o sostituire il motore di scansione indipendentemente.

## Database delle firme

Il database delle firme antivirus viene mantenuto in un volume Docker persistente:

```text
securescan-clamav-db
```

La persistenza evita che il servizio debba ricostruire completamente il database delle firme ogni volta che il container viene ricreato.

## Configurazione

Il file principale della configurazione è:

```text
clamd.conf
```

Il file viene montato nel container durante l'avvio tramite Docker Compose.

Le impostazioni principali riguardano:

- modalità di esecuzione del demone;
- configurazione della comunicazione TCP;
- timeout;
- comportamento del servizio durante la scansione.

## Utilizzo da parte dell'Analysis Worker

Durante una scansione il worker:

1. acquisisce il job dal database;
2. legge il file dallo storage condiviso;
3. invia il contenuto binario a ClamAV;
4. riceve il risultato antivirus;
5. salva l'esito insieme agli altri indicatori tecnici.

Il file non viene eseguito durante l'analisi.

ClamAV opera esclusivamente sul contenuto binario ricevuto.

## Risultati della scansione

Il risultato restituito da ClamAV contribuisce alla generazione del verdict finale.

Gli esiti principali sono:

- file pulito;
- rilevamento malware;
- errore del servizio;
- timeout della scansione.

La decisione finale viene comunque effettuata dall'Analysis Worker combinando i risultati di tutti i livelli di analisi.

## Health e disponibilità

ClamAV viene monitorato tramite health check Docker.

Lo stato del servizio viene utilizzato per verificare che il motore antivirus sia disponibile prima dell'elaborazione delle analisi.

Eventuali problemi di disponibilità vengono propagati alla pipeline attraverso lo stato dell'analisi.

## Sicurezza

ClamAV opera come servizio interno.

Il file analizzato:

- non viene eseguito;
- non viene aperto dal browser;
- non viene esposto pubblicamente;
- viene trattato esclusivamente come sequenza di byte.

Il container utilizza inoltre:

- rete privata Docker;
- `no-new-privileges`;
- volume dedicato per il database firme.

## Collegamenti documentazione

- [Malware scanning](../../docs/malware-scanning.md)
- [Analysis Worker](../../apps/analysis-worker/README.md)
- [Architettura](../../docs/architecture.md)