# Flussi principali end-to-end

Questo documento descrive i principali flussi di SecureScan Cloud seguendo il percorso effettivo delle operazioni tra frontend, Keycloak, Kong, Analysis API, PostgreSQL, storage e worker.

L'obiettivo non è elencare soltanto gli endpoint disponibili, ma chiarire quale componente interviene in ogni fase e dove vengono applicati i controlli di sicurezza o aggiornati i dati persistenti.

## 1. Apertura dell'applicazione e autenticazione

L'utente accede al frontend SecureScan Cloud dal browser.

Se la pagina richiesta è protetta e non è disponibile una sessione valida, il frontend avvia il flusso di autenticazione verso Keycloak.

Il percorso logico è:

```text
Browser
   |
   v
Frontend
   |
   v
Keycloak
   |
   v
Autenticazione
   |
   v
Token
   |
   v
Frontend
```

Il frontend utilizza il client Keycloak dedicato all'applicazione browser e Authorization Code Flow con PKCE.

Le credenziali non vengono inviate all'Analysis API e non vengono salvate nel database applicativo.

Dopo l'autenticazione, Keycloak restituisce i token necessari alla sessione. Le successive richieste alle API protette includono il bearer token.

Il percorso verso il backend diventa:

```text
Frontend
   |
   | Authorization: Bearer <token>
   v
Kong
   |
   v
analysis-api-1 / analysis-api-2
```

Kong decide a quale replica inoltrare la richiesta. L'Analysis API valida poi il JWT e ricava le informazioni necessarie, tra cui subject, username, ruoli e identificatori di token o sessione.

Un token mancante, non valido o scaduto determina normalmente una risposta `401 Unauthorized`.

Quando l'utente è autenticato ma non dispone del ruolo richiesto per una determinata operazione, la risposta è `403 Forbidden`.

## 2. Creazione di un nuovo account

La registrazione viene gestita da Keycloak e non dall'Analysis API.

Il flusso è:

```text
Utente
   |
   v
Frontend / pagina di accesso
   |
   v
Keycloak
   |
   v
Registrazione
   |
   v
Account
```

Keycloak raccoglie le informazioni previste dal realm e crea l'identità.

Nel contesto configurato per il progetto, il normale utente registrato riceve il ruolo applicativo destinato all'utilizzo ordinario della piattaforma, cioè `analyst`.

Il frontend non dispone di un endpoint che inserisce direttamente username e password nel database applicativo.

Quando la verifica dell'indirizzo email è attiva e SMTP è configurato, il nuovo account può essere sottoposto al relativo flusso di conferma.

## 3. Verifica dell'indirizzo email

La verifica email viene gestita da Keycloak.

L'utente riceve un messaggio contenente un link associato all'azione prevista dal realm.

Il percorso è:

```text
Keycloak
   |
   v
Server SMTP
   |
   v
Email utente
   |
   v
Link di verifica
   |
   v
Keycloak
```

Dopo il completamento del flow, lo stato `emailVerified` dell'utente viene aggiornato in Keycloak.

Il frontend recupera successivamente questa informazione attraverso lo snapshot del profilo prodotto dall'Analysis API.

Le credenziali SMTP non vengono inviate al browser.

## 4. Login e caricamento iniziale del profilo

Dopo l'autenticazione il frontend necessita di alcune informazioni applicative sull'utente corrente.

La richiesta passa attraverso:

```text
Frontend
   |
   v
Kong
   |
   v
GET /api/v1/me/profile
   |
   v
Analysis API
```

Il backend identifica l'utente dal JWT.

Lo snapshot del profilo combina dati provenienti da Keycloak e dati locali associati al subject.

Tra le informazioni provenienti dall'identità rientrano username, nome, cognome, email, stato della verifica e ruoli.

Le informazioni applicative locali comprendono, per esempio, il riferimento all'avatar.

Questa risposta viene utilizzata in più parti dell'interfaccia, evitando che ogni componente del frontend interroghi autonomamente sorgenti diverse.

## 5. Creazione di una nuova analisi

Quando l'utente seleziona un file dalla pagina `Nuova analisi`, il frontend invia:

```text
POST /api/v1/analyses
```

Il percorso completo è:

```text
Browser
   |
   v
Frontend
   |
   v
Kong
   |
   +------------------------+
   |                        |
   v                        v
analysis-api-1        analysis-api-2
          \              /
           \            /
            v          v
          PostgreSQL + storage
```

Kong seleziona una delle due repliche disponibili.

L'Analysis API verifica innanzitutto il token e applica lo scope dell'utente. L'upload viene validato secondo i limiti previsti dall'applicazione.

Il file viene quindi scritto nella directory condivisa:

```text
/data/uploads
```

e viene creato in PostgreSQL un record iniziale dell'analisi.

Lo stato iniziale del job è:

```text
queued
```

Il record contiene anche le informazioni necessarie all'ownership, tra cui:

```text
owner_sub
owner_username
```

Il backend restituisce la risposta iniziale senza aspettare l'esecuzione di ClamAV e YARA.

Questo è il punto in cui termina la parte sincrona della creazione.

## 6. Presa in carico da parte del worker

L'Analysis Worker esegue un polling periodico del database alla ricerca di job disponibili.

Il percorso è:

```text
PostgreSQL
   |
   v
Analysis Worker
```

Quando trova un job `queued`, il worker tenta di acquisirlo.

L'acquisizione nel repository SQL utilizza una strategia basata su:

```text
FOR UPDATE SKIP LOCKED
```

Questo meccanismo permette a più worker, qualora venissero eseguiti contemporaneamente, di non selezionare lo stesso job.

Dopo l'acquisizione lo stato passa a:

```text
processing
```

Vengono inoltre aggiornate le informazioni necessarie a gestire tentativi, timeout e recovery.

## 7. Accesso al file da parte del worker

Il record dell'analisi contiene il riferimento al file precedentemente salvato dall'API.

Analysis API e worker utilizzano lo stesso storage persistente.

Il worker recupera quindi il file dal percorso associato al job.

Se il file non esiste più o non può essere letto, la pipeline non può essere completata normalmente.

In un caso di errore reale di questo tipo l'analisi può terminare in stato:

```text
failed
```

`failed` non significa che il file sia stato classificato come malware. Indica che il job non è stato portato a termine correttamente dal punto di vista operativo.

Questa distinzione è importante perché stato del job e risultato della scansione descrivono due aspetti diversi.

## 8. Analisi strutturale

Una volta ottenuto il file, il worker esegue i controlli strutturali previsti.

Tra le informazioni ricavate rientrano:

```text
SHA-256
MIME type
entropia
estensione
corrispondenza tra estensione e MIME type
```

Queste informazioni costituiscono indicatori utili, ma non vengono interpretate automaticamente come prova che il file sia malevolo.

Per esempio, un'entropia elevata può essere dovuta a compressione o a contenuto binario. Una discordanza tra estensione e MIME type è sospetta, ma non equivale da sola a una rilevazione malware.

## 9. Scansione ClamAV

Il worker comunica con il servizio ClamAV attraverso la rete Docker.

Il percorso è:

```text
Analysis Worker
      |
      v
   ClamAV
```

ClamAV verifica il contenuto rispetto alle firme antivirus disponibili.

Il risultato può indicare che il file non contiene firme note oppure che è stata trovata una rilevazione.

La pipeline distingue inoltre i casi in cui ClamAV non riesce a completare correttamente la richiesta, ad esempio per indisponibilità o timeout.

Un errore del motore non viene trasformato automaticamente in un risultato `clean`.

## 10. Scansione YARA

Il worker applica anche le regole YARA configurate nel progetto.

Il percorso logico è interno alla pipeline:

```text
Analysis Worker
      |
      v
regole YARA
```

Le regole possono produrre match con informazioni associate alla severità e al motivo della rilevazione.

YARA completa il ruolo di ClamAV permettendo di esprimere regole specifiche del progetto e pattern non necessariamente rappresentati dalle sole firme antivirus.

## 11. Aggregazione del risultato

Dopo i controlli strutturali, ClamAV e YARA, il worker aggrega i risultati.

I verdict gestiti dalla pipeline sono:

```text
clean
suspicious
malicious
scan_error
```

Il verdict è distinto dal `risk_level`, che utilizza:

```text
low
medium
high
critical
```

`scan_error` viene utilizzato quando almeno uno dei motori obbligatori non completa correttamente la scansione. Il sistema evita quindi di dichiarare pulito un file che non è stato sottoposto all'intera pipeline prevista.

Una volta conclusa correttamente l'elaborazione, il record viene aggiornato in PostgreSQL.

Lo stato operativo del job diventa:

```text
completed
```

Se invece si verifica un errore non recuperabile nella lavorazione, lo stato può diventare:

```text
failed
```

## 12. Polling durante l'elaborazione

Il frontend non mantiene aperta la richiesta di upload.

Dopo aver ricevuto il record iniziale può interrogare periodicamente il backend per verificare lo stato dell'analisi.

Il percorso è:

```text
Frontend
   |
   v
Kong
   |
   v
GET /api/v1/analyses/{analysis_id}
   |
   v
Analysis API
   |
   v
PostgreSQL
```

Finché lo stato è `queued` o `processing`, la UI può continuare il polling.

Quando viene raggiunto uno stato conclusivo, il polling può terminare.

## 13. Cronologia

La pagina Cronologia utilizza:

```text
GET /api/v1/analyses
```

La richiesta può contenere:

```text
page
page_size
search
status
risk
owner
```

Il backend non restituisce l'intero dataset.

Il flusso logico della query è:

```text
utente autenticato
        |
        v
scope RBAC / ownership
        |
        v
filtri
        |
        v
COUNT filtrato
        |
        v
ordinamento
        |
        v
OFFSET / LIMIT
        |
        v
pagina richiesta
```

Per un `analyst`, lo scope sull'owner viene imposto automaticamente attraverso il subject dell'utente.

Un parametro inviato dal browser non può trasformare l'analyst in un utente con vista globale.

Per un `admin` è disponibile, dove previsto, anche il filtro per owner.

## 14. Ricerca nella Cronologia

Il testo inserito nella barra di ricerca viene utilizzato come filtro server-side.

Il frontend non scarica tutte le analisi per filtrare localmente.

La ricerca è sottoposta a un breve debounce prima della nuova richiesta, evitando di inviare inutilmente una chiamata per ogni singolo evento di tastiera.

Durante il refresh vengono mantenuti i risultati precedenti finché non arriva la nuova risposta.

Questo evita di smontare la tabella e mantiene stabile l'interazione con la barra di ricerca.

Il focus e la posizione del cursore restano quindi utilizzabili durante la digitazione.

## 15. Paginazione della Cronologia

Il frontend utilizza come dimensione iniziale:

```text
5
```

e permette di scegliere:

```text
5
10
20
```

Il default dell'endpoint backend, quando `page_size` non viene specificato, è invece:

```text
10
```

La UI passa esplicitamente il valore selezionato, quindi i due default non sono in conflitto.

Il frontend mostra il range nel formato:

```text
X - Y di Z
```

Se sono presenti analisi ancora in esecuzione, il polling conserva pagina, page size e filtri selezionati.

## 16. Dettaglio di un'analisi

Quando l'utente apre una voce della Cronologia, il frontend invia:

```text
GET /api/v1/analyses/{analysis_id}
```

Il backend recupera il record ma applica anche il controllo di accesso.

Per un analyst non è sufficiente conoscere l'identificatore di un'analisi appartenente a un altro utente.

Il backend confronta l'ownership con il subject autenticato.

Un admin utilizza invece lo scope previsto dal proprio ruolo.

La pagina può mostrare:

- metadati;
- hash;
- MIME type;
- informazioni strutturali;
- risultati ClamAV;
- risultati YARA;
- indicatori;
- verdict;
- livello di rischio;
- stato operativo.

Se il job non è ancora terminato, anche questa pagina può continuare il polling.

## 17. Dashboard

La Dashboard utilizza:

```text
GET /api/v1/dashboard
```

Il backend costruisce uno snapshot aggregato.

Per un analyst gli aggregati vengono calcolati sul proprio scope.

Per un admin vengono utilizzati i dati previsti dalla vista globale autorizzata.

Il frontend non deve quindi scaricare la Cronologia completa per calcolare statistiche nel browser.

Tra le informazioni restituite possono rientrare:

```text
conteggi
distribuzione del rischio
analisi recenti
andamento temporale
```

## 18. Stato del sistema

La pagina `Stato del sistema` interroga:

```text
GET /api/v1/system/status
```

L'Analysis API costruisce lo snapshot combinando più sorgenti.

Tra queste rientrano:

- heartbeat delle repliche API;
- heartbeat del worker;
- controlli verso componenti tecnici;
- stato dei servizi monitorati dall'applicazione.

La risposta non equivale semplicemente a `docker ps`.

L'obiettivo è distinguere il fatto che un container esista dal fatto che il processo applicativo continui effettivamente a comunicare.

La pagina fornisce una vista sintetica, mentre Prometheus e Grafana restano gli strumenti destinati all'osservazione tecnica nel tempo.

## 19. Heartbeat delle Analysis API

Ogni replica dell'Analysis API aggiorna periodicamente il proprio heartbeat in PostgreSQL.

Il record permette di associare l'attività a:

```text
analysis-api-1
analysis-api-2
```

La logica di Stato del sistema può confrontare il timestamp con il timeout configurato.

Un heartbeat troppo vecchio può quindi indicare che l'istanza non sta più comunicando correttamente, anche se il container potrebbe ancora esistere.

## 20. Heartbeat del worker

Il worker applica lo stesso principio.

Aggiorna periodicamente un heartbeat nel database e viene considerato attivo solo se il timestamp rientra nella finestra prevista.

La configurazione corrente utilizza normalmente:

```text
WORKER_HEARTBEAT_INTERVAL_SECONDS=5
WORKER_HEARTBEAT_TIMEOUT_SECONDS=15
```

L'heartbeat non sostituisce il normale health endpoint del container. Le due informazioni hanno scopi differenti.

## 21. Lettura del profilo

Quando viene aperta la pagina Profilo, il frontend richiede:

```text
GET /api/v1/me/profile
```

La chiamata è self-service: il subject dell'utente non viene deciso dal browser.

Il backend lo ricava dal token corrente.

Lo snapshot restituito combina identità Keycloak e dati applicativi locali.

## 22. Modifica di nome, cognome e username

Dalla pagina Modifica profilo l'utente può aggiornare i campi consentiti.

La richiesta passa attraverso:

```text
Frontend
   |
   v
Kong
   |
   v
Analysis API
   |
   v
Keycloak
```

L'operazione rimane riferita al subject del token corrente.

Nome, cognome e username possono essere aggiornati senza utilizzare il workflow di verifica dell'email.

## 23. Richiesta di cambio email

La modifica dell'email viene trattata diversamente dagli altri campi.

Il nuovo indirizzo viene prima validato.

Il backend verifica che:

```text
verifica email sia attiva
SMTP sia disponibile
email corrente esista
email corrente sia verificata
nuovo indirizzo sia utilizzabile
```

Il flusso coinvolge il provider Keycloak personalizzato:

```text
Frontend
   |
   v
Analysis API
   |
   v
Keycloak Admin / provider SecureScan
   |
   v
validazione nuova email
```

Se il nuovo indirizzo appartiene già a un altro account, la richiesta viene rifiutata.

In questo caso l'email corrente deve rimanere invariata e non deve essere creata una modifica pending valida.

## 24. Cambio email in attesa di verifica

Quando la nuova email supera i controlli, viene avviato il flow dedicato.

Il comportamento è:

```text
email corrente
     |
     v
richiesta nuova email
     |
     v
nuova email pending
     |
     +------ email corrente resta attiva
     |
     v
invio link
     |
     v
utente conferma
     |
     v
nuova email diventa attiva
```

Il frontend può mostrare l'indirizzo pending mentre la verifica non è ancora conclusa.

Questa scelta evita di sostituire un indirizzo verificato con un valore sul quale l'utente non ha ancora dimostrato il controllo.

## 25. Reinvio della verifica email

Il frontend può richiedere:

```text
POST /api/v1/me/verification-email
```

Il backend controlla lo stato dell'account.

Se esiste un cambio email pending, viene reinviato il link relativo al nuovo indirizzo.

Se non esiste un pending ma l'email corrente non è verificata, viene usato il normale flow `VERIFY_EMAIL`.

Non viene avviata inutilmente una nuova verifica quando l'indirizzo risulta già verificato.

## 26. Cambio password da Profilo

Il cambio password di un utente già autenticato utilizza:

```text
POST /api/v1/me/password
```

Il payload contiene:

```text
current_password
new_password
confirm_new_password
logout_other_sessions
```

Prima dell'invio il frontend controlla alcuni requisiti di base della nuova password.

La decisione finale rimane comunque server-side.

## 27. Verifica della password corrente

L'Analysis API non cambia direttamente la password appena riceve la richiesta.

Prima verifica la credenziale corrente attraverso Keycloak.

Il flusso è:

```text
Frontend
   |
   v
Analysis API
   |
   | password corrente
   v
client Keycloak dedicato
   |
   v
verifica credenziale
```

Il client utilizzato a questo scopo è configurato lato server.

Il relativo secret non viene inviato al frontend.

Se la password corrente è errata, il cambio viene interrotto.

## 28. Impostazione della nuova password

Dopo la verifica della password corrente, l'Analysis API utilizza Keycloak per impostare la nuova password.

PostgreSQL non viene utilizzato per memorizzare credenziali.

Se l'operazione riesce, il frontend chiude il dialog e mostra il feedback di successo.

## 29. Revoca opzionale delle altre sessioni

Il payload di cambio password contiene:

```text
logout_other_sessions
```

Nel frontend l'opzione è selezionata di default.

Quando vale `true`, il backend deve distinguere la sessione da cui è stata effettuata la modifica dalle altre sessioni dell'utente.

L'identificatore corrente viene ricavato dal token utilizzando:

```text
sid
```

con fallback su:

```text
session_state
```

quando necessario.

Il flusso diventa:

```text
password aggiornata
       |
       v
lista sessioni Keycloak
       |
       v
identificazione sessione corrente
       |
       +------> preservata
       |
       v
altre sessioni
       |
       v
terminate
```

Quando `logout_other_sessions=false`, l'aggiornamento della password viene eseguito senza revocare le altre sessioni.

## 30. Forgot password

Il recupero della password per un utente che non può effettuare il login resta interamente sotto Keycloak.

Il percorso è:

```text
Pagina login
    |
    v
Password dimenticata
    |
    v
Keycloak
    |
    v
SMTP
    |
    v
Email reset
```

Il frontend applicativo non gestisce il token di reset e non conosce la password.

## 31. Reimpostazione password tramite email

Quando l'utente apre il link ricevuto, Keycloak presenta il flow di reimpostazione.

Dopo il completamento viene mostrata la pagina personalizzata:

```text
Password aggiornata
```

La pagina resta stabile e permette il ritorno al login tramite l'azione prevista, senza richiedere al frontend React di reimplementare il flow.

## 32. Caricamento dell'avatar

Il frontend invia l'immagine tramite:

```text
POST /api/v1/me/avatar
```

L'Analysis API identifica il proprietario attraverso il token corrente.

Il file viene validato prima della persistenza.

Lo storage utilizzato si trova sotto:

```text
/data/avatars
```

Il database conserva il riferimento applicativo necessario a recuperare l'avatar.

## 33. Sostituzione dell'avatar

Quando viene caricato un nuovo avatar, il backend deve mantenere coerenti database e filesystem.

Il nuovo file viene salvato e associato al profilo.

Solo quando l'operazione è stata completata correttamente il precedente avatar può essere rimosso.

In caso di errore durante l'aggiornamento del record, la logica evita per quanto possibile di lasciare il profilo in uno stato che punti a un file inesistente.

## 34. Rimozione dell'avatar

La cancellazione utilizza:

```text
DELETE /api/v1/me/avatar
```

Il backend recupera il profilo dell'utente corrente, elimina il riferimento applicativo e rimuove il file associato secondo la logica prevista dal servizio di storage.

La richiesta non permette a un normale utente di indicare arbitrariamente il subject di un altro account.

## 35. Eliminazione del proprio profilo

Il backend espone anche la gestione delle operazioni self-service previste sul profilo.

Quando un'operazione comporta la rimozione dell'account o dei dati associati, deve essere mantenuta la coerenza tra identità Keycloak, record applicativi e file locali collegati all'utente.

Le operazioni di questo tipo vengono eseguite server-side e non mediante accesso diretto del browser alle API amministrative di Keycloak.

## 36. Accesso alla sezione Amministrazione

Un utente admin può aprire la sezione amministrativa.

Il frontend invia richieste verso endpoint sotto:

```text
/api/v1/admin/users
```

Il percorso è:

```text
Admin
  |
  v
Frontend
  |
  v
Kong
  |
  v
Analysis API
  |
  | verifica ruolo admin
  v
Keycloak Admin API
```

La presenza della pagina nel frontend non costituisce l'autorizzazione.

Il backend verifica ogni richiesta.

## 37. Elenco degli utenti

L'Analysis API utilizza le funzionalità amministrative di Keycloak per recuperare gli account gestiti e costruire i dati necessari al frontend.

Le credenziali amministrative e i client secret rimangono lato server.

Il browser riceve soltanto le informazioni che l'endpoint ha deciso di esporre.

## 38. Dettaglio amministrativo di un utente

Quando un admin apre il dettaglio di un utente, il backend combina le informazioni identitarie con i dati applicativi collegati al subject.

La sezione può includere anche le analisi appartenenti all'utente selezionato.

L'ownership continua a basarsi sul subject e non sul semplice username visualizzato.

## 39. Modifica amministrativa di un account

Le modifiche amministrative passano attraverso l'Analysis API.

Il backend può coordinare:

```text
dati Keycloak
ruoli
stato account
dati applicativi
```

prima di restituire il nuovo snapshot.

Questo impedisce al frontend di utilizzare direttamente privilegi Keycloak elevati.

## 40. Protezione dell'ultimo amministratore

Alcune operazioni amministrative possono cambiare il ruolo di un account o disabilitarlo.

Prima di consentire una modifica che rimuoverebbe un amministratore attivo, il backend controlla che non si stia eliminando l'ultimo account in grado di amministrare la piattaforma.

La verifica evita situazioni nelle quali una sequenza formalmente valida di richieste renda poi impossibile gestire gli utenti.

## 41. Traffico attraverso Kong

Per le API applicative il frontend utilizza sempre il gateway.

Kong gestisce:

```text
routing
load balancing
CORS
correlation ID
rate limiting
request size limiting
health check upstream
metriche
```

Quando entrambe le repliche sono healthy, il round-robin distribuisce il traffico tra:

```text
analysis-api-1
analysis-api-2
```

La replica che riceve la richiesta applica poi la stessa logica backend.

## 42. Failover di una replica API

Se una replica diventa indisponibile durante il normale funzionamento, Kong può rilevare il fault tramite i meccanismi di health check e routing configurati.

Un esempio è:

```text
analysis-api-1   healthy
analysis-api-2   down
```

Il traffico può continuare attraverso:

```text
Kong
  |
  v
analysis-api-1
```

senza che il frontend debba conoscere quale replica sia rimasta disponibile.

Questo comportamento è uno degli oggetti principali degli esperimenti HA del progetto.

## 43. Recovery di una replica

Quando una replica precedentemente indisponibile torna a rispondere e viene nuovamente considerata healthy, Kong può reinserirla nel pool.

Il traffico torna quindi a essere distribuito tra entrambe le istanze.

Il tempo necessario perché questo comportamento diventi osservabile viene misurato negli esperimenti dedicati.

## 44. Monitoring tramite Prometheus

Prometheus interroga periodicamente gli endpoint metrici configurati.

Il flusso è di tipo pull:

```text
Prometheus
   |
   +----> Kong
   |
   +----> analysis-api-1
   |
   +----> analysis-api-2
   |
   +----> analysis-worker
   |
   +----> postgres-exporter
```

Le serie raccolte vengono conservate nel relativo storage persistente.

## 45. Visualizzazione tramite Grafana

Grafana non interroga direttamente tutti i servizi.

Utilizza Prometheus come datasource:

```text
Servizi
   |
   v
Prometheus
   |
   v
Grafana
```

La dashboard `SecureScan Cloud Observability` permette di leggere le metriche nel tempo e viene utilizzata anche durante gli esperimenti.

## 46. Metriche PostgreSQL

Per le metriche del database il percorso è:

```text
PostgreSQL
   |
   v
postgres-exporter
   |
   v
Prometheus
   |
   v
Grafana
```

Questo separa le query applicative utilizzate da API e worker dal percorso dedicato all'osservabilità.

## 47. Avvio locale

Lo stack ordinario può essere avviato tramite:

```bash
./scripts/start-local.sh
```

oppure mediante il Compose base.

Per il primo avvio o quando devono essere ricostruite le immagini viene usata esplicitamente l'opzione `--build`.

La variante dedicata alla demo utilizza:

```bash
./scripts/start-demo.sh
```

e applica sia `compose.yaml` sia `compose.demo.yaml`.

Le procedure dettagliate sono documentate in:

```text
infrastructure/compose/README.md
```

## 48. Arresto locale

Per una normale sessione di sviluppo o demo, i container possono essere arrestati senza eliminare i dati persistenti.

La procedura consigliata utilizza `docker compose stop`.

La cancellazione dei volumi non fa parte del normale spegnimento.

In particolare, opzioni come `down -v` non devono essere utilizzate come semplice equivalente di `stop`, perché possono eliminare dati persistenti.

## 49. Reset delle analisi demo

Quando è necessario ripulire soltanto le analisi locali, è disponibile:

```bash
./scripts/reset-demo-analyses.sh
```

Lo script opera sulle analisi e sugli upload collegati alla demo senza eliminare avatar, profili, Keycloak o gli altri dati persistenti.

Durante la parte distruttiva sospende temporaneamente i componenti applicativi necessari a evitare race condition e successivamente ripristina quelli che risultavano attivi.

È disponibile anche:

```bash
./scripts/reset-demo-analyses.sh --dry-run
```

per osservare preventivamente ciò che verrebbe interessato.

## 50. Ingresso production

Nel deployment Azure l'accesso pubblico aggiunge Caddy davanti ai servizi.

Il percorso dell'applicazione è:

```text
Internet
   |
   v
Caddy
   |
   +----> Frontend
   |
   +----> /api/* ----> Kong
```

Keycloak utilizza un hostname pubblico separato:

```text
Internet
   |
   v
Caddy
   |
   v
Keycloak
```

Caddy gestisce HTTPS e reverse proxy.

Kong rimane il gateway applicativo delle Analysis API.

## 51. Perché Caddy e Kong sono entrambi presenti

Caddy e Kong non svolgono lo stesso lavoro.

Caddy gestisce l'ingresso pubblico, TLS e il reverse proxy verso i servizi che devono essere raggiungibili da Internet.

Kong gestisce invece il traffico applicativo verso le API, comprese policy e load balancing.

Il percorso production della parte backend è quindi:

```text
Browser
   |
 HTTPS
   |
   v
Caddy
   |
   v
Kong
   |
   +-------------------+
   |                   |
   v                   v
analysis-api-1     analysis-api-2
```

## 52. Persistenza durante la ricreazione dei container

I dati che devono sopravvivere alla vita dei singoli container sono mantenuti tramite volumi.

Questo vale per database, upload, avatar, stato Keycloak, firme ClamAV, Prometheus, Grafana e, in production, dati e configurazione persistente di Caddy.

Il codice applicativo può quindi essere aggiornato separatamente dallo stato persistente.

## 53. Confini del sistema

Non tutti i componenti sono ridondati.

La configurazione attuale comprende due repliche dell'Analysis API, mentre altri componenti sono presenti in singola istanza.

Per questo i test di failover delle API dimostrano la continuità del livello gateway/API rispetto alla perdita di una replica, non una disponibilità totale dell'intero sistema rispetto a qualunque guasto possibile.

Questa distinzione viene mantenuta anche nell'interpretazione dei risultati sperimentali.

## Documenti correlati

Per approfondire autenticazione, ruoli e gestione delle sessioni:

[Autenticazione e RBAC](authentication-rbac.md)

Per la struttura complessiva:

[Architettura](architecture.md)

Per la pipeline:

[Malware scanning](malware-scanning.md)

Per gateway, fault tolerance e load balancing:

[High availability](high-availability.md)

Per metriche e dashboard:

[Osservabilità](observability.md)

Per la metodologia sperimentale:

[Esperimenti e benchmark](experiments.md)