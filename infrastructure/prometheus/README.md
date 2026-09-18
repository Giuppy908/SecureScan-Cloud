# SecureScan Prometheus

Prometheus è il componente responsabile della raccolta e conservazione delle metriche tecniche della piattaforma SecureScan Cloud.

All'interno dell'architettura viene utilizzato come sistema di monitoraggio centralizzato per raccogliere informazioni provenienti dai diversi servizi dello stack e renderle disponibili a Grafana per la visualizzazione.

Prometheus non gestisce direttamente log applicativi o dati di business. Il suo compito è osservare lo stato operativo dei componenti attraverso metriche esposte dagli stessi servizi.

Le principali informazioni monitorate riguardano:

- traffico gestito dal gateway;
- disponibilità delle repliche API;
- stato del worker;
- metriche PostgreSQL;
- stato dei target monitorati;
- indicatori utili agli esperimenti di alta disponibilità.

## Ruolo nell'architettura SecureScan Cloud

Prometheus rappresenta il livello di raccolta dati del sistema di osservabilità.

Il flusso generale è:

```text
Servizi SecureScan
        |
        v
     /metrics
        |
        v
  Prometheus
        |
        v
    Grafana
        |
        v
 Dashboard osservabilità
```

I servizi espongono endpoint compatibili con il formato Prometheus.

Prometheus interroga periodicamente questi endpoint tramite il meccanismo di scraping e salva le serie temporali raccolte.

Grafana utilizza successivamente Prometheus come datasource per costruire dashboard e pannelli informativi.

## Configurazione dello scraping

La configurazione principale è contenuta nel file:

```text
prometheus.yml
```

Il file definisce:

- intervallo di raccolta;
- target monitorati;
- endpoint da interrogare;
- configurazioni dei job.

Prometheus utilizza un modello pull:

- non riceve metriche inviate dai servizi;
- interroga autonomamente gli endpoint configurati.

Questo permette di mantenere semplice l'integrazione con i componenti applicativi.

## Target monitorati

La configurazione attuale include i principali componenti dello stack:

```text
prometheus:9090
kong:8100
analysis-api-1:8000
analysis-api-2:8000
analysis-worker:8081
postgres-exporter:9187
```

Ogni target espone metriche specifiche relative al proprio funzionamento.

## Kong API Gateway

Il monitoraggio di Kong permette di osservare il comportamento del punto di ingresso della piattaforma.

Le metriche consentono di analizzare:

- numero di richieste ricevute;
- latenza;
- distribuzione del traffico;
- errori HTTP;
- comportamento degli upstream.

Queste informazioni sono fondamentali durante gli esperimenti di load balancing e fault injection.

## Analysis API

Le due repliche:

```text
analysis-api-1
analysis-api-2
```

espongono metriche applicative indipendenti.

Il monitoraggio permette di verificare:

- disponibilità delle istanze;
- numero di richieste elaborate;
- errori;
- stato operativo delle repliche.

Durante gli esperimenti HA queste metriche permettono di osservare il comportamento del sistema quando una replica viene arrestata intenzionalmente.

## Analysis Worker

Il worker espone metriche relative alla pipeline asincrona.

Sono osservabili informazioni come:

- job acquisiti;
- job completati;
- job falliti;
- tempi di elaborazione;
- errori di scansione;
- attività di recovery.

Questi dati permettono di valutare il comportamento della parte di elaborazione malware.

## PostgreSQL Exporter

Prometheus non interroga direttamente PostgreSQL.

La raccolta delle metriche del database avviene tramite:

```text
postgres-exporter
```

L'exporter converte informazioni interne del database nel formato compatibile con Prometheus.

Le metriche permettono di osservare:

- stato del database;
- utilizzo delle risorse;
- connessioni;
- informazioni operative.

## Persistenza dei dati

Le serie temporali raccolte da Prometheus vengono mantenute attraverso un volume Docker persistente:

```text
securescan-prometheus-data
```

Questo evita la perdita dello storico delle metriche in caso di:

- riavvio del container;
- ricreazione dello stack;
- aggiornamento dell'immagine.

La persistenza è importante soprattutto durante esperimenti e demo, dove è utile confrontare il comportamento del sistema nel tempo.

## Integrazione con Grafana

Grafana utilizza Prometheus come sorgente dati principale.

Il collegamento permette di creare dashboard contenenti:

- grafici temporali;
- indicatori sintetici;
- stato dei servizi;
- andamento delle metriche.

Prometheus si occupa della raccolta e conservazione dei dati, mentre Grafana della loro rappresentazione visiva.

## Porta locale

Nell'ambiente locale Prometheus è disponibile tramite:

```text
http://127.0.0.1:9090
```

L'interfaccia web permette di:

- verificare i target configurati;
- eseguire query PromQL;
- controllare lo stato dello scraping;
- analizzare serie temporali.

## Utilizzo negli esperimenti di alta disponibilità

Prometheus è un componente fondamentale per valutare il comportamento dell'architettura HA.

Durante gli esperimenti permette di osservare:

- distribuzione delle richieste tra le API;
- eventuale perdita di disponibilità;
- recupero dopo il fault;
- stato delle repliche;
- variazione delle metriche durante il carico.

In combinazione con Kong e Grafana permette di fornire una visione completa del comportamento del sistema distribuito.

## Differenza tra metriche e log

Prometheus non sostituisce il sistema di logging.

Le metriche rispondono principalmente a domande come:

- il servizio è disponibile?
- quante richieste sta gestendo?
- quanto tempo impiega?
- quanti errori produce?

I log invece descrivono eventi dettagliati e vengono utilizzati principalmente per diagnostica e debugging.

## File principali

La directory contiene:

```text
prometheus.yml
```

Configurazione principale del server Prometheus.

```text
README.md
```

Documentazione del componente.

## Collegamenti documentazione

Per la descrizione generale dell'osservabilità:

[Osservabilità](../../docs/observability.md)

Per gli esperimenti di alta disponibilità:

[High availability](../../docs/high-availability.md)

Per la descrizione generale dell'architettura:

[Architettura](../../docs/architecture.md)
