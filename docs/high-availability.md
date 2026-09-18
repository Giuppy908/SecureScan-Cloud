# High availability, load balancing e fault tolerance

SecureScan Cloud è stato progettato come un sistema distribuito composto da più servizi indipendenti, con l'obiettivo di analizzare il comportamento di un'architettura cloud nella quale alcuni componenti possano continuare a operare anche in presenza di un guasto locale.

Uno degli aspetti principali studiati nel progetto riguarda la disponibilità dell'Analysis API, il servizio responsabile della gestione delle richieste relative alle analisi dei file. Per evitare che una singola istanza rappresenti un punto critico dell'intero sistema, l'API è stata configurata con due repliche eseguite contemporaneamente:

- `analysis-api-1`
- `analysis-api-2`

Le due istanze vengono esposte attraverso Kong API Gateway, che rappresenta l'unico punto di ingresso per le richieste provenienti dal frontend.

Questa configurazione permette di valutare concretamente alcune proprietà tipiche delle architetture cloud distribuite:

- distribuzione del traffico tra più istanze;
- rilevamento di servizi non disponibili;
- continuità operativa durante il guasto di una replica;
- ripristino automatico dopo il ritorno di un componente;
- comportamento del sistema durante condizioni di carico.

L'obiettivo non è ottenere una disponibilità assoluta, caratteristica che richiederebbe un'infrastruttura più complessa, ma dimostrare come la presenza di ridondanza e di un livello intermedio di gestione del traffico possa ridurre l'impatto di un singolo fault.

## Architettura attuale

L'architettura di alta disponibilità implementata in SecureScan Cloud è basata sulla separazione tra il livello di accesso, il livello applicativo e il livello di persistenza.

Il percorso principale seguito da una richiesta è il seguente:

```text
Browser
   |
   v
Frontend React
   |
   v
Kong API Gateway
   |
   +----------------+
   |                |
   v                v
analysis-api-1   analysis-api-2
   |
   v
PostgreSQL
```

Il frontend non comunica direttamente con nessuna delle due repliche dell'Analysis API. Tutte le richieste passano attraverso Kong, che si occupa di individuare il backend corretto e inoltrare il traffico verso una delle istanze disponibili.

Questa scelta permette di nascondere al client la complessità interna dell'architettura. Dal punto di vista dell'utente, il servizio viene percepito come una singola API, mentre internamente il traffico viene distribuito tra più componenti.

La presenza di due repliche permette inoltre di simulare scenari tipici dei sistemi cloud reali, nei quali una componente può temporaneamente diventare indisponibile senza provocare necessariamente il blocco completo dell'applicazione.

## Load balancing tramite Kong

Kong API Gateway svolge il ruolo di livello intermedio tra frontend e servizi applicativi.

Il gateway utilizza un upstream configurato con due target statici:

```text
analysis-api-1:8000
analysis-api-2:8000
```

L'algoritmo di bilanciamento utilizzato è il round-robin.

Quando entrambe le repliche risultano disponibili, Kong distribuisce le richieste in modo alternato tra le due istanze. Questo permette di verificare che il traffico venga effettivamente ripartito e che il carico non venga concentrato su un solo servizio.

La scelta di utilizzare un API Gateway consente inoltre di mantenere separati il frontend e il livello applicativo. Eventuali modifiche al numero delle repliche o alla loro configurazione interna non richiedono modifiche lato client.

Il gateway diventa quindi un elemento centrale dell'architettura perché concentra diverse responsabilità:

- instradamento delle richieste;
- bilanciamento del traffico;
- verifica dello stato dei backend;
- esclusione temporanea delle istanze non disponibili.

## Health check e rilevamento delle anomalie

Per garantire che le richieste vengano indirizzate solamente verso servizi funzionanti, Kong utilizza meccanismi di health check sugli upstream configurati.

I principali parametri utilizzati sono:

- `connect_timeout = 500 ms`;
- `read_timeout = 60000 ms`;
- `write_timeout = 60000 ms`;
- massimo numero di retry pari a 5;
- controllo attivo ogni 1 secondo;
- soglia unhealthy del controllo attivo pari a 1;
- soglia unhealthy del controllo passivo pari a 1.

Il controllo attivo permette al gateway di verificare periodicamente la disponibilità delle repliche anche quando non sono presenti richieste applicative.

Il controllo passivo invece considera il comportamento osservato durante il normale traffico. Se una replica restituisce errori o non risponde correttamente, Kong può marcarla come temporaneamente non disponibile.

La combinazione dei due meccanismi permette di ottenere un rilevamento rapido delle anomalie e una modifica automatica del routing.

## Fault tolerance

La tolleranza ai guasti in SecureScan Cloud deriva dalla combinazione di tre elementi principali:

- presenza di due repliche dell'Analysis API;
- utilizzo di Kong come punto unico di ingresso;
- monitoraggio continuo dello stato dei backend.

Quando una replica diventa indisponibile, il comportamento previsto è il seguente:

1. Kong rileva il mancato funzionamento del target;
2. la replica viene esclusa temporaneamente dal bilanciamento;
3. il traffico viene indirizzato verso l'altra istanza disponibile;
4. dopo il ripristino del servizio, la replica torna disponibile per le nuove richieste.

Questo comportamento permette di mantenere operativo il servizio anche quando una componente interna non è momentaneamente raggiungibile.

È importante distinguere il concetto di fault tolerance dalla semplice restart policy dei container.

La restart policy di Docker permette di riavviare automaticamente un container terminato, ma durante il periodo di arresto il servizio potrebbe risultare non disponibile.

La fault tolerance invece riguarda la capacità dell'intero sistema di continuare a funzionare anche quando una singola componente fallisce. Nel caso di SecureScan Cloud questa proprietà deriva principalmente dalla presenza di più repliche e dalla gestione del traffico tramite Kong.

## Esperimenti di valutazione

Per verificare il comportamento dell'architettura sono stati definiti diversi scenari sperimentali all'interno della directory:

```text
experiments/
```

Gli scenari considerati sono:

- `baseline_two_replicas`
- `single_replica`
- `failover_during_load`
- `recovery_after_restart`

Ogni scenario permette di osservare una diversa condizione operativa del sistema, confrontando il comportamento normale con situazioni di riduzione delle risorse disponibili o recupero dopo un fault.

I risultati vengono raccolti nella directory:

```text
experiments/results/
```

e vengono utilizzati per valutare quantitativamente il comportamento dell'architettura.

## Scenario baseline con due repliche

Lo scenario baseline rappresenta il funzionamento normale del sistema con entrambe le repliche dell'Analysis API attive.

Il risultato ottenuto è:

- richieste totali: `24331`;
- error rate: `0.0`.

La distribuzione del traffico osservata è stata:

- `analysis-api-1`: `12167` richieste;
- `analysis-api-2`: `12164` richieste.

Il risultato conferma il corretto funzionamento del bilanciamento round-robin configurato all'interno di Kong.

## Scenario con una sola replica disponibile

Nel secondo scenario una delle due repliche viene rimossa, lasciando operativo solamente un backend.

Il sistema ha gestito:

- richieste totali: `13190`;
- error rate: `0.0`.

Tutto il traffico è stato correttamente indirizzato verso l'unica istanza disponibile.

Questo esperimento dimostra che il sistema può continuare a fornire il servizio anche quando una replica dell'API non è raggiungibile.

## Scenario di failover durante carico

Durante questo esperimento una replica viene resa indisponibile mentre il sistema sta gestendo richieste.

I risultati ottenuti sono:

- richieste totali: `20137`;
- error rate: `0.0`.

I tempi misurati sono:

- transizione rilevata da Kong: circa `0.0059 s`;
- transizione rilevata tramite Prometheus: circa `4.539 s`;
- variazione del routing: circa `0.099 s`.

Il risultato mostra che il gateway riesce a modificare rapidamente il comportamento del sistema senza introdurre errori osservabili lato client.

## Scenario di recovery dopo riavvio

L'ultimo scenario valuta il ritorno operativo di una replica precedentemente arrestata.

I risultati osservati sono:

- richieste totali: `23437`;
- error rate: `0.0`.

I tempi misurati sono:

- transizione Kong: circa `1.417 s`;
- transizione Prometheus: circa `0.504 s`;
- ripristino del routing: circa `3.301 s`.

La replica viene quindi reintegrata automaticamente dopo il recupero del servizio.