# Esperimenti e benchmark

La suite sperimentale di SecureScan Cloud ha l'obiettivo di valutare il comportamento dell'architettura distribuita in condizioni controllate, analizzando in particolare gli aspetti legati all'alta disponibilità, al bilanciamento del carico e alla capacità del sistema di continuare a gestire richieste anche in presenza di eventi di fault.

Gli esperimenti non sono finalizzati solamente a misurare le prestazioni assolute dell'applicazione, ma soprattutto a verificare il comportamento dei componenti coinvolti nella gestione delle richieste. In particolare, l'attenzione è rivolta al ruolo svolto dall'API Gateway Kong come punto centrale dell'architettura, responsabile del routing verso le repliche dell'Analysis API, del controllo dello stato dei backend e della distribuzione del traffico.

La valutazione sperimentale considera diversi scenari operativi: configurazione con più repliche attive, confronto con una singola replica, simulazione di un guasto durante un carico continuo e verifica del recupero dopo il riavvio di un servizio. Attraverso questi scenari è possibile osservare il comportamento del sistema rispetto a disponibilità del servizio, continuità delle richieste e tempi di transizione verso una nuova configurazione operativa.

Gli esperimenti sono stati progettati per essere riproducibili attraverso gli script presenti nella directory `experiments/`, utilizzando l'ambiente containerizzato Docker Compose adottato durante lo sviluppo del progetto.

## Obiettivo della suite sperimentale

L'obiettivo principale della suite sperimentale è verificare alcune proprietà non funzionali considerate fondamentali per un'architettura cloud distribuita:

- disponibilità del servizio in presenza di più istanze applicative;
- distribuzione delle richieste tra più backend;
- comportamento del sistema durante il fallimento di una replica;
- capacità del gateway di rilevare cambiamenti nello stato dei servizi;
- tempo necessario per il ripristino del corretto instradamento delle richieste.

L'analisi non considera solamente il numero totale di richieste gestite, ma integra informazioni relative alla latenza, agli errori restituiti agli utenti e alla distribuzione del traffico tra le diverse repliche.

L'elemento centrale della valutazione è quindi il comportamento dell'API Gateway come componente di coordinamento tra il client e i servizi applicativi. La presenza di più repliche dell'Analysis API permette di studiare come il sistema reagisce quando una delle istanze non è più disponibile, verificando se le richieste possono essere indirizzate verso un backend ancora operativo.

La suite sperimentale supporta quindi la validazione delle scelte architetturali adottate, senza rappresentare una certificazione delle prestazioni del sistema in ambiente produttivo.

## Organizzazione della directory experiments/

La directory `experiments/` contiene gli strumenti necessari per eseguire, raccogliere e analizzare gli esperimenti effettuati sul sistema.

La struttura principale è organizzata nel seguente modo:

```text
experiments/
├── scenarios/
├── scripts/
└── results/
```

La directory `scenarios/` contiene la definizione degli scenari sperimentali disponibili. Ogni scenario rappresenta una specifica configurazione o condizione operativa del sistema, ad esempio presenza di più repliche, simulazione di fault o procedure di recovery.

La directory `scripts/` contiene gli script utilizzati per automatizzare l'esecuzione dei test. Gli script si occupano della generazione del carico, della raccolta delle metriche e dell'archiviazione dei risultati prodotti dai vari componenti.

La directory `results/` raccoglie gli output generati durante gli esperimenti. I risultati comprendono dati strutturati in formato JSON e CSV, log operativi e grafici utilizzati per l'analisi successiva.

Questa separazione permette di mantenere distinti il modello sperimentale, gli strumenti di esecuzione e i dati ottenuti dalle misurazioni.

## Prerequisiti e ambiente di esecuzione

Gli esperimenti vengono eseguiti sull'ambiente containerizzato definito tramite Docker Compose.

Prima dell'avvio della suite sperimentale devono essere attivi tutti i servizi necessari alla piattaforma:

- frontend React + Vite;
- Kong API Gateway;
- Analysis API con due repliche applicative;
- PostgreSQL;
- Keycloak per autenticazione e gestione dei ruoli;
- ClamAV per l'analisi antivirus;
- Analysis Worker per l'elaborazione asincrona;
- Prometheus per la raccolta delle metriche;
- Grafana per la visualizzazione.

L'architettura sperimentale considera il seguente percorso delle richieste:

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
```

Kong utilizza un upstream statico configurato verso le due repliche dell'Analysis API e distribuisce le richieste tramite algoritmo round-robin.

La disponibilità delle repliche viene verificata attraverso gli health check configurati sul gateway. Quando un backend non risulta più raggiungibile, Kong può rimuoverlo temporaneamente dal pool disponibile e instradare il traffico verso le istanze rimanenti.

Gli esperimenti sono stati eseguiti localmente tramite Docker Compose. L'ambiente utilizzato consente di riprodurre il comportamento distribuito dell'applicazione, mantenendo però alcune differenze rispetto ad un deployment reale su infrastruttura cloud.

## Scenari sperimentali

La suite comprende quattro scenari principali, progettati per valutare configurazioni differenti dell'architettura.

### baseline_two_replicas

Questo scenario rappresenta la configurazione di riferimento del sistema.

Sono presenti entrambe le repliche dell'Analysis API:

```text
Kong
 |
 +-- analysis-api-1
 |
 +-- analysis-api-2
```

Il traffico viene distribuito tra le due istanze attraverso il load balancing configurato nel gateway.

L'obiettivo è misurare il comportamento normale del sistema in condizioni operative stabili, verificando throughput, assenza di errori e corretta distribuzione delle richieste.

Risultati ottenuti:

| Parametro | Valore |
|---|---:|
| Richieste totali | 24331 |
| Error rate | 0.0 |

Il risultato conferma che, nella configurazione con due repliche disponibili, il gateway riesce a gestire il carico generato senza errori applicativi rilevati.

### single_replica

Questo scenario utilizza una sola replica dell'Analysis API.

La configurazione permette di confrontare il comportamento del sistema senza ridondanza applicativa e rappresenta il caso base rispetto alla configurazione ad alta disponibilità.

L'obiettivo non è dimostrare necessariamente una maggiore velocità della configurazione con più repliche, ma evidenziare la differenza architetturale in termini di capacità di tollerare guasti.

Risultati ottenuti:

| Parametro | Valore |
|---|---:|
| Richieste totali | 13190 |
| Error rate | 0.0 |

Anche con una singola istanza il servizio rimane operativo durante il test, ma l'architettura non dispone di un componente alternativo verso cui spostare il traffico in caso di indisponibilità.

### failover_during_load

Questo scenario valuta il comportamento del sistema durante un evento di fault generato mentre è presente traffico attivo.

Durante l'esecuzione viene rimossa una replica dell'Analysis API mentre Kong continua a ricevere richieste. L'obiettivo è osservare il processo di rilevamento del guasto e la successiva transizione verso il backend ancora disponibile.

Il flusso analizzato è:

```text
Traffico attivo
      |
      v
Kong
      |
      +--> analysis-api-1  (failure)
      |
      +--> analysis-api-2  (operativo)
```

Sono stati misurati tre intervalli temporali distinti:

- tempo rilevato da Kong per aggiornare lo stato del backend;
- tempo osservato tramite Prometheus;
- tempo complessivo necessario affinché il routing ritorni operativo.

Risultati ottenuti:

| Parametro | Valore |
|---|---:|
| Richieste totali | 20137 |
| Error rate | 0.0 |
| kong_transition_seconds | ≈ 0.0059 |
| prometheus_transition_seconds | ≈ 4.539 |
| routing_transition_seconds | ≈ 0.099 |

Il risultato più significativo è l'assenza di errori durante la transizione. Il gateway riesce quindi a mantenere disponibile il servizio utilizzando la replica rimanente.

### recovery_after_restart

Questo scenario analizza il comportamento del sistema dopo il riavvio di una replica precedentemente arrestata.

L'obiettivo è verificare il tempo necessario affinché il servizio torni ad essere nuovamente disponibile nel pool gestito dal gateway.

Il flusso considerato è:

```text
Replica arrestata
        |
        v
Riavvio servizio
        |
        v
Health check positivo
        |
        v
Nuovo inserimento nel routing
```

Risultati ottenuti:

| Parametro | Valore |
|---|---:|
| Richieste totali | 23437 |
| Error rate | 0.0 |
| kong_transition_seconds | ≈ 1.417 |
| prometheus_transition_seconds | ≈ 0.504 |
| routing_transition_seconds | ≈ 3.301 |

Il test mostra che il sistema riesce a reintegrare una replica disponibile dopo il riavvio, ripristinando progressivamente la configurazione iniziale.

## Esecuzione degli esperimenti

L'esecuzione della suite segue un workflow composto da più fasi.

Prima dell'avvio viene verificato che l'ambiente Docker Compose sia operativo e che tutti i servizi abbiano completato la fase di inizializzazione.

Successivamente viene selezionato lo scenario da eseguire. Lo script associato prepara la configurazione richiesta, avvia il generatore di carico e raccoglie le informazioni prodotte durante il test.

Durante l'esecuzione vengono monitorati:

- numero di richieste inviate;
- risposte ricevute;
- errori HTTP;
- tempi di risposta;
- stato dei backend;
- eventi di fault e recovery.

Al termine dello scenario gli output vengono salvati nella directory `results/`, dove possono essere analizzati singolarmente oppure confrontati tra scenari differenti.

Il workflow consente di ripetere gli esperimenti mantenendo una configurazione coerente e confrontabile.

## Output prodotti

Ogni esecuzione produce diversi tipi di output utilizzati per l'analisi.

I file JSON contengono i risultati strutturati degli esperimenti, inclusi parametri aggregati, tempi di transizione e informazioni relative allo scenario eseguito.

I file CSV vengono utilizzati per rappresentare dati tabellari facilmente importabili in strumenti di analisi e visualizzazione.

I log raccolti durante l'esecuzione permettono di ricostruire la sequenza temporale degli eventi, identificando momenti come:

- avvio del test;
- generazione del fault;
- rilevamento del cambiamento;
- recupero del servizio.

I grafici SVG consentono una rappresentazione visiva dell'andamento delle metriche raccolte, facilitando il confronto tra configurazioni differenti.

## Metriche raccolte

La suite sperimentale raccoglie diverse metriche per valutare il comportamento del sistema.

### Throughput

Il throughput rappresenta il numero complessivo di richieste gestite durante lo scenario.

Questa misura permette di confrontare la capacità operativa delle diverse configurazioni, evidenziando il comportamento con una o più repliche disponibili.

### Latenza

La latenza misura il tempo necessario per completare le richieste.

Questa metrica permette di osservare eventuali variazioni durante eventi di fault o recovery, quando il sistema deve modificare il percorso di routing.

### Error rate

L'error rate indica la percentuale di richieste terminate con errore.

È una delle metriche principali per valutare la continuità del servizio durante scenari di guasto.

### Distribuzione backend

La distribuzione delle richieste tra le repliche permette di verificare il corretto funzionamento del load balancing effettuato da Kong.

La metrica evidenzia se il traffico viene effettivamente suddiviso tra le istanze disponibili.

### Tempi di transizione

I tempi di transizione misurano la velocità con cui il sistema reagisce ai cambiamenti dello stato dei servizi.

Sono stati considerati:

- tempo di aggiornamento percepito da Kong;
- tempo rilevato dal sistema di monitoring;
- tempo complessivo necessario al ripristino del routing.

## Risultati verificati

Gli esperimenti hanno prodotto i seguenti risultati:

| Scenario | Richieste totali | Error rate |
|---|---:|---:|
| baseline_two_replicas | 24331 | 0.0 |
| single_replica | 13190 | 0.0 |
| failover_during_load | 20137 | 0.0 |
| recovery_after_restart | 23437 | 0.0 |

Gli scenari di fault e recovery hanno mostrato la capacità dell'architettura di mantenere operativo il servizio senza errori durante le transizioni.

Nel caso di `failover_during_load`, il sistema ha completato il cambio di configurazione con tempi ridotti:

- transizione Kong: circa 0.0059 secondi;
- transizione routing complessiva: circa 0.099 secondi.

Nel caso di `recovery_after_restart`, il reinserimento della replica ha richiesto tempi maggiori, coerentemente con il fatto che il servizio deve essere nuovamente avviato, verificato tramite health check e reintegrato nel flusso operativo.

## Interpretazione dei risultati

I risultati ottenuti confermano il comportamento atteso dall'architettura progettata.

La presenza di due repliche dell'Analysis API permette al sistema di continuare a gestire richieste anche durante la perdita temporanea di una delle istanze. L'API Gateway rappresenta quindi un elemento fondamentale per isolare il client dai cambiamenti dello stato interno dei servizi.

Gli esperimenti mostrano anche che il meccanismo di fault tolerance dipende dalla combinazione di più componenti: la presenza delle repliche applicative, il controllo dello stato effettuato dal gateway e il routing dinamico verso backend disponibili.

I risultati non dimostrano una disponibilità assoluta del sistema in qualsiasi condizione, ma evidenziano il corretto funzionamento del modello architetturale adottato e la capacità di gestire specifici scenari di guasto controllati.

## Limiti metodologici

Gli esperimenti presentano alcuni limiti che devono essere considerati nell'interpretazione dei risultati.

Le misurazioni sono state eseguite localmente tramite Docker Compose e non rappresentano automaticamente il comportamento del sistema in un ambiente cloud di produzione.

Il carico generato e le tempistiche osservate dipendono dalle caratteristiche dell'ambiente utilizzato, dalle risorse disponibili e dalla configurazione locale dei container.

La valutazione è principalmente concentrata sul comportamento del gateway e dell'API layer. Non vengono analizzati in modo approfondito aspetti come scalabilità automatica su infrastruttura cloud, distribuzione geografica, gestione di grandi volumi di dati o resilienza dell'intero ecosistema applicativo.

Gli esperimenti devono quindi essere interpretati come una validazione sperimentale dell'architettura proposta, utile a dimostrare il comportamento dei principali meccanismi di alta disponibilità e fault tolerance implementati.