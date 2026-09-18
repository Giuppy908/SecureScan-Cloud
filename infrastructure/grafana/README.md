# SecureScan Grafana

Grafana è il componente responsabile della visualizzazione delle metriche raccolte dalla piattaforma SecureScan Cloud.

All'interno dell'architettura viene utilizzato come livello di presentazione del sistema di osservabilità: non raccoglie direttamente informazioni dai servizi, ma utilizza Prometheus come datasource per mostrare dashboard e indicatori relativi allo stato operativo della piattaforma.

Grafana permette di trasformare le metriche tecniche raccolte dallo stack in informazioni facilmente interpretabili durante sviluppo, monitoraggio e demo.

Le principali informazioni visualizzate riguardano:

- traffico gestito dal gateway;
- comportamento delle repliche API;
- stato del worker;
- disponibilità dei servizi;
- metriche del database;
- andamento temporale delle prestazioni.

## Ruolo nell'architettura SecureScan Cloud

Grafana rappresenta il livello visuale del sistema di monitoraggio.

Il flusso delle informazioni è:

```text
Servizi SecureScan
        |
        v
     Endpoint
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

I servizi applicativi espongono metriche nel formato compatibile con Prometheus.

Prometheus raccoglie e conserva tali informazioni, mentre Grafana le interroga per costruire pannelli grafici e indicatori.

## Differenza tra Grafana e pagina Stato del sistema

SecureScan Cloud possiede due livelli differenti di monitoraggio.

### Stato del sistema

La pagina applicativa:

- è integrata nel frontend;
- è pensata per gli utenti della piattaforma;
- mostra informazioni sintetiche;
- utilizza dati provenienti dai servizi backend.

Esempi:

- stato API;
- stato worker;
- disponibilità dei servizi principali.

### Grafana

Grafana è destinato principalmente a:

- sviluppatori;
- amministratori;
- analisi tecnica;
- esperimenti.

Permette una visione più dettagliata attraverso metriche temporali e grafici.

Le due componenti non si sostituiscono, ma hanno finalità differenti.

## Endpoint locale

Nell'ambiente locale Grafana è disponibile tramite:

```text
http://127.0.0.1:3000
```

L'interfaccia permette di consultare le dashboard provisionate automaticamente dallo stack.

## Provisioning automatico

La configurazione di Grafana viene caricata automaticamente all'avvio.

Questo evita operazioni manuali come:

- creazione datasource;
- importazione dashboard;
- configurazione ripetitiva dopo ogni ricreazione del container.

Il provisioning è gestito tramite i file presenti nella directory:

```text
provisioning/
```

## Datasource Prometheus

Il datasource principale è definito tramite:

```text
provisioning/datasources/prometheus.yml
```

Questo file configura automaticamente la connessione tra Grafana e Prometheus.

Grafana utilizza Prometheus come sorgente dati per tutte le dashboard di osservabilità.

## Dashboard SecureScan Cloud

La dashboard principale è:

```text
SecureScan Cloud Observability
```

La configurazione è mantenuta nel file:

```text
dashboards/securescan-observability.json
```

La dashboard viene caricata automaticamente tramite:

```text
provisioning/dashboards/dashboards.yml
```

## Informazioni visualizzate

La dashboard permette di osservare diversi aspetti della piattaforma.

## Kong API Gateway

Le metriche relative a Kong permettono di analizzare:

- numero di richieste;
- distribuzione del traffico;
- latenza;
- errori HTTP;
- comportamento degli upstream.

Queste informazioni sono particolarmente importanti durante gli esperimenti di load balancing.

## Analysis API

Le metriche delle due repliche:

```text
analysis-api-1
analysis-api-2
```

permettono di verificare:

- attività delle istanze;
- distribuzione delle richieste;
- disponibilità dei servizi;
- eventuali differenze tra repliche.

Durante un fault controllato è possibile osservare come il traffico venga ribilanciato.

## Analysis Worker

Grafana visualizza le metriche relative al componente asincrono:

- job elaborati;
- job completati;
- job falliti;
- tempi di elaborazione;
- errori.

Questo permette di valutare il comportamento della pipeline malware.

## PostgreSQL exporter

Le metriche del database vengono raccolte tramite:

```text
postgres-exporter
```

e rese disponibili attraverso Prometheus.

Grafana può mostrare informazioni relative allo stato operativo del database e all'attività delle connessioni.

## Utilizzo negli esperimenti HA

Grafana è fondamentale durante la valutazione dell'alta disponibilità.

Durante gli esperimenti permette di osservare:

- distribuzione del carico tra le API;
- effetto dell'arresto di una replica;
- recupero del servizio;
- variazioni di latenza;
- disponibilità complessiva del sistema.

In combinazione con Kong e Prometheus fornisce una visione completa del comportamento dell'architettura distribuita.

## Persistenza

Grafana utilizza un volume Docker persistente:

```text
securescan-grafana-data
```

Il volume mantiene:

- configurazioni interne;
- stato del servizio;
- informazioni necessarie al funzionamento.

La persistenza evita di perdere configurazioni durante riavvii o ricreazioni del container.

## Struttura della directory

La directory contiene:

```text
dashboards/securescan-observability.json
```

Dashboard principale della piattaforma.

```text
provisioning/dashboards/dashboards.yml
```

Configurazione del caricamento automatico delle dashboard.

```text
provisioning/datasources/prometheus.yml
```

Configurazione del datasource Prometheus.

```text
provisioning/alerting/
```

Directory predisposta per configurazioni di alerting future.

```text
provisioning/plugins/
```

Directory predisposta per eventuali plugin aggiuntivi.

## Configurazione tramite Docker Compose

Grafana viene eseguito come servizio indipendente nello stack Docker.

Durante l'avvio:

1. il container viene creato;
2. viene configurato il datasource Prometheus;
3. vengono caricate le dashboard versionate nel repository;
4. il servizio diventa disponibile sulla porta locale.

Questo rende l'ambiente riproducibile anche dopo una completa ricreazione dello stack.

## Differenza tra sviluppo e produzione

Nell'ambiente locale Grafana viene esposto direttamente per facilitare:

- sviluppo;
- diagnostica;
- demo;
- esperimenti.

In un ambiente pubblico Grafana non dovrebbe essere normalmente esposto senza protezioni aggiuntive.

La configurazione production può prevedere:

- accesso limitato;
- autenticazione dedicata;
- esposizione tramite reverse proxy;
- restrizioni di rete.

## File principali

La directory contiene:

```text
README.md
```

Documentazione del componente.

```text
dashboards/securescan-observability.json
```

Dashboard principale.

```text
provisioning/dashboards/dashboards.yml
```

Configurazione provisioning dashboard.

```text
provisioning/datasources/prometheus.yml
```

Configurazione datasource.

## Collegamenti documentazione

Per la raccolta delle metriche:

[Prometheus](../prometheus/README.md)

Per la descrizione generale dell'osservabilità:

[Osservabilità](../../docs/observability.md)

Per gli esperimenti di alta disponibilità:

[High availability](../../docs/high-availability.md)

Per la descrizione generale dell'architettura:

[Architettura](../../docs/architecture.md)