# Osservabilità del sistema

In un'architettura distribuita come SecureScan Cloud, conoscere solamente lo stato di disponibilità dei singoli servizi non è sufficiente per comprendere il comportamento complessivo del sistema.

L'osservabilità permette di raccogliere informazioni provenienti dai diversi componenti dell'architettura e analizzare come il sistema evolve nel tempo. Attraverso metriche, dashboard e strumenti di monitoraggio è possibile identificare anomalie, valutare le prestazioni dei servizi e supportare le attività di diagnosi durante lo sviluppo e gli esperimenti.

Nel progetto SecureScan Cloud l'osservabilità è utilizzata principalmente per analizzare il comportamento dell'API Gateway, delle repliche dell'Analysis API, del servizio worker e dei componenti infrastrutturali collegati.

L'obiettivo non è solamente verificare che i servizi siano attivi, ma comprendere come interagiscono tra loro e come reagiscono durante condizioni operative differenti, come distribuzione del carico, fault di una replica e procedure di recovery.

## Ruolo dell'osservabilità nell'architettura

L'architettura di SecureScan Cloud è composta da diversi servizi distribuiti che collaborano attraverso una serie di comunicazioni interne.

Il flusso principale delle richieste è il seguente:

```text
Client
  |
  v
Kong API Gateway
  |
  +----------------+
  |                |
  v                v
analysis-api-1  analysis-api-2
  |
  v
Analysis Worker
  |
  v
PostgreSQL
```

Ogni componente produce informazioni utili per valutare il comportamento del sistema.

In particolare:

- Kong permette di osservare il traffico ricevuto, i codici HTTP restituiti e le latenze delle richieste;
- le repliche dell'Analysis API permettono di analizzare la distribuzione del carico e il comportamento delle istanze applicative;
- l'Analysis Worker fornisce informazioni sull'elaborazione asincrona delle analisi;
- PostgreSQL viene monitorato attraverso un exporter dedicato.

L'osservabilità rappresenta quindi uno strumento trasversale all'intera architettura e consente di correlare informazioni provenienti da livelli differenti.

## Prometheus

Prometheus è il componente responsabile della raccolta e della conservazione delle metriche generate dai servizi della piattaforma.

Il sistema utilizza un modello di raccolta basato su pull: Prometheus interroga periodicamente gli endpoint esposti dai componenti monitorati e acquisisce le metriche disponibili.

I servizi espongono le proprie informazioni attraverso endpoint compatibili con il formato utilizzato da Prometheus, tipicamente raggiungibili tramite il percorso:

```text
/metrics
```

Le metriche raccolte vengono memorizzate come serie temporali, permettendo di analizzare non solamente il valore corrente di un parametro, ma anche la sua evoluzione nel tempo.

I principali target configurati nel progetto sono:

- `prometheus`;
- `kong`;
- `analysis-api`;
- `analysis-worker`;
- `postgres-exporter`.

Questa configurazione permette di raccogliere informazioni sia dal livello applicativo sia dal livello infrastrutturale.

Durante gli esperimenti descritti nella suite sperimentale, Prometheus viene utilizzato come supporto per osservare variazioni nello stato dei servizi e correlare gli eventi di fault e recovery con l'andamento delle metriche raccolte.

## Grafana

Grafana è utilizzato come livello di visualizzazione delle metriche raccolte.

A differenza di Prometheus, Grafana non acquisisce direttamente i dati, ma utilizza Prometheus come datasource per costruire dashboard e rappresentazioni grafiche.

Questa separazione permette di mantenere distinti:

- il livello di raccolta e archiviazione delle metriche;
- il livello di visualizzazione e analisi.

Nel progetto è presente una dashboard dedicata:

```text
SecureScan Cloud Observability
```

La dashboard consente di avere una visione complessiva dello stato operativo della piattaforma e di analizzare il comportamento dei diversi servizi durante il normale funzionamento o durante gli esperimenti.

## Dashboard di monitoraggio

La dashboard Grafana raccoglie le principali informazioni relative ai componenti della piattaforma.

Le metriche visualizzate comprendono:

- richieste al secondo gestite da Kong;
- numero di repliche API attive;
- stato dei worker;
- disponibilità del PostgreSQL exporter;
- distribuzione dei codici HTTP restituiti dal gateway;
- latenze del gateway e dei servizi upstream;
- richieste distribuite tra le repliche dell'Analysis API;
- analisi create dalle diverse repliche;
- job del worker completati o falliti;
- durata delle elaborazioni;
- disponibilità dei target monitorati da Prometheus.

Queste informazioni permettono di osservare sia il comportamento applicativo sia il funzionamento dei componenti che compongono l'infrastruttura.

## Metriche raccolte

Le metriche raccolte sono suddivise in base al componente osservato.

## Kong API Gateway

Kong rappresenta il punto centrale di ingresso delle richieste verso i servizi applicativi.

Le metriche principali riguardano:

- numero di richieste ricevute;
- throughput del gateway;
- distribuzione dei codici HTTP;
- latenza totale della richiesta;
- latenza verso i servizi upstream;
- comportamento del routing verso i backend disponibili.

Queste informazioni sono particolarmente importanti negli scenari di alta disponibilità, perché permettono di verificare il comportamento del gateway quando una replica dell'Analysis API viene rimossa o reintegrata.

## Analysis API

Le metriche relative all'Analysis API permettono di analizzare il comportamento delle repliche applicative.

Sono osservabili:

- volume delle richieste ricevute;
- distribuzione del traffico tra le repliche;
- numero di analisi create;
- risposte applicative critiche come errori di autenticazione o autorizzazione.

La distribuzione delle richieste tra `analysis-api-1` e `analysis-api-2` permette di verificare il corretto funzionamento del load balancing configurato tramite Kong.

## Analysis Worker

L'Analysis Worker è responsabile dell'elaborazione asincrona delle analisi.

Le metriche disponibili consentono di osservare:

- numero di worker attivi;
- quantità di job completati;
- job terminati con errore;
- durata delle elaborazioni.

Questi dati permettono di valutare il comportamento della pipeline di analisi e individuare eventuali rallentamenti nella fase di processamento.

## PostgreSQL

Il database PostgreSQL viene monitorato attraverso il componente `postgres-exporter`.

Le metriche non vengono raccolte direttamente dal database verso Grafana, ma attraverso il servizio exporter che espone informazioni compatibili con Prometheus.

Questo approccio consente di osservare parametri relativi allo stato del database mantenendo separato il sistema di monitoraggio dal componente applicativo.

## Differenza tra stato applicativo e osservabilità tecnica

SecureScan Cloud distingue tra la vista applicativa disponibile nel frontend e il livello tecnico di osservabilità.

La pagina frontend `Stato del sistema` fornisce una rappresentazione semplificata dello stato della piattaforma.

È pensata per:

- utenti dell'applicazione;
- operatori durante una demo;
- verifica rapida dello stato generale dei servizi.

La pagina utilizza informazioni applicative come heartbeat e probe tecnici per fornire una visione sintetica.

Grafana invece rappresenta una vista maggiormente tecnica.

È utilizzato per:

- analisi dettagliata del comportamento del sistema;
- diagnosi dei problemi;
- valutazione degli esperimenti;
- confronto temporale delle metriche.

Le due viste hanno quindi obiettivi differenti e complementari.

## Relazione con alta disponibilità e fault tolerance

L'osservabilità è un elemento importante per valutare il comportamento dell'architettura ad alta disponibilità.

In particolare:

- la metrica relativa alle richieste per replica permette di osservare il load balancing effettuato da Kong;
- il numero di repliche API attive permette di verificare la disponibilità dei backend;
- le metriche del gateway permettono di analizzare il comportamento durante eventi di fault;
- le serie temporali raccolte da Prometheus consentono di correlare cambiamenti dello stato dei servizi con gli effetti osservati.

Durante gli esperimenti di failover e recovery, gli strumenti di osservabilità permettono quindi di verificare il comportamento del sistema oltre alla semplice disponibilità finale del servizio.

## Utilizzo negli esperimenti

La componente di osservabilità viene utilizzata come supporto alla suite sperimentale descritta in `experiments.md`.

Durante gli scenari di benchmark vengono raccolte informazioni utili per interpretare i risultati ottenuti.

In particolare, Prometheus e Grafana permettono di osservare:

- variazioni del traffico durante il failover;
- stato delle repliche applicative;
- tempi di transizione;
- comportamento del gateway durante il cambio del backend disponibile.

Le metriche raccolte non sostituiscono le misurazioni prodotte dagli script sperimentali, ma forniscono una vista complementare utile a comprendere il comportamento interno dell'architettura.

## Limiti attuali

L'attuale configurazione di osservabilità è principalmente orientata allo sviluppo locale e alla valutazione sperimentale dell'architettura.

Sono presenti alcuni limiti:

- il monitoring è configurato sull'ambiente Docker Compose utilizzato durante lo sviluppo;
- non sono ancora presenti procedure complete di alerting automatico;
- non è stato effettuato il deployment pubblico dell'infrastruttura di monitoring;
- non sono state definite policy avanzate di retention e gestione storica delle metriche.

Il sistema attuale rappresenta quindi una base funzionale per analisi, debugging ed esperimenti, ma non equivale ad una piattaforma completa di monitoring enterprise per ambienti produttivi.