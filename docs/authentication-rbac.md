# Autenticazione e RBAC

SecureScan Cloud separa in modo esplicito autenticazione e autorizzazione.

L'autenticazione stabilisce chi è l'utente ed è affidata a Keycloak. L'autorizzazione stabilisce invece quali operazioni sono consentite all'utente autenticato ed è applicata principalmente dall'Analysis API.

Questa distinzione evita che il frontend diventi il punto in cui viene presa una decisione di sicurezza definitiva.

## Ruolo di Keycloak

Keycloak è l'Identity and Access Management utilizzato dal progetto.

Gestisce:

- login;
- registrazione;
- verifica dell'indirizzo email;
- recupero della password;
- reimpostazione della password;
- sessioni utente;
- ruoli;
- emissione dei token JWT;
- operazioni sensibili relative all'identità.

Il frontend non memorizza le password degli utenti e non mantiene un database separato delle credenziali.

Il realm utilizzato dal progetto è:

```text id="g4t1mo"
securescan
```

## Client principali

La configurazione Keycloak comprende più client con responsabilità differenti.

Il frontend utilizza il client destinato all'applicazione browser:

```text id="w4r1gf"
securescan-frontend
```

Il login utilizza Authorization Code Flow con PKCE.

Sono presenti anche client backend utilizzati dall'Analysis API per operazioni che non devono essere eseguite direttamente dal browser.

Tra queste rientrano l'accesso alle funzionalità amministrative di Keycloak e la verifica della password corrente durante il cambio password.

I secret di questi client non vengono incorporati nel bundle frontend.

## Flusso di login

Il percorso di autenticazione è:

```text id="e5gyrd"
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

Quando l'utente accede a una pagina protetta, il frontend avvia il flow OIDC verso Keycloak.

Dopo l'autenticazione, il frontend riceve i token necessari alla sessione e utilizza il bearer token nelle richieste verso l'Analysis API.

Il traffico backend segue:

```text id="he47ku"
Frontend
   |
   | Authorization: Bearer <token>
   v
Kong
   |
   v
Analysis API
```

Kong inoltra il token alla replica backend selezionata.

La decisione finale sulla validità del JWT e sui privilegi dell'utente viene presa dall'Analysis API.

## Verifica JWT

L'Analysis API non considera attendibile un token soltanto perché proviene dal frontend.

Il backend valida la firma mediante le chiavi pubbliche esposte da Keycloak tramite JWKS.

I controlli comprendono almeno:

- firma;
- issuer;
- audience;
- scadenza;
- presenza del subject;
- struttura delle informazioni richieste dal backend.

Il subject del JWT viene utilizzato come identificatore stabile dell'utente.

## Claim utilizzati

Il backend ricava dal payload le informazioni applicative necessarie.

Tra i claim utilizzati rientrano:

```text id="lrg1he"
sub
preferred_username
realm_access.roles
jti
sid
session_state
```

### `sub`

`sub` identifica in modo stabile l'utente all'interno del realm.

È il riferimento principale per applicare ownership e per collegare le operazioni all'identità autenticata.

### `preferred_username`

`preferred_username` viene utilizzato come nome leggibile dell'utente quando disponibile.

Lo username può essere modificato, quindi non viene usato come chiave stabile per la proprietà delle analisi.

### `realm_access.roles`

I ruoli applicativi vengono estratti da:

```text id="pjly8t"
realm_access.roles
```

Il backend considera in particolare:

```text id="iypaqk"
analyst
admin
```

### `jti`

`jti` identifica il token.

Può essere utilizzato per audit e diagnostica delle richieste.

### `sid`

`sid` identifica la sessione Keycloak associata al token quando il claim è disponibile.

Nel progetto viene utilizzato in particolare durante il cambio password per distinguere la sessione corrente dalle altre sessioni dell'utente.

### `session_state`

Quando `sid` non è disponibile, il backend può utilizzare `session_state` come fallback per ricavare l'identificatore della sessione corrente.

## Ruoli applicativi

I due ruoli principali sono:

```text id="2ksodl"
analyst
admin
```

### Analyst

Un utente `analyst` può utilizzare le funzionalità ordinarie della piattaforma.

Può:

- accedere alla Dashboard;
- caricare file;
- consultare la propria Cronologia;
- aprire il dettaglio delle proprie analisi;
- consultare Stato del sistema;
- utilizzare il proprio Profilo;
- modificare i dati consentiti del proprio account.

Non può utilizzare le funzioni amministrative e non può accedere alle analisi appartenenti ad altri utenti.

### Admin

Un utente `admin` dispone delle funzionalità ordinarie e delle operazioni amministrative previste dal backend.

Può accedere alla vista globale autorizzata delle analisi e alle pagine dedicate alla gestione utenti secondo le policy definite dagli endpoint amministrativi.

La presenza del ruolo `admin` nel frontend non è sufficiente da sola ad autorizzare l'operazione. Ogni endpoint amministrativo verifica nuovamente il ruolo sul server.

## RBAC nel frontend

Il frontend utilizza i ruoli per costruire una navigazione coerente.

Per esempio può:

- mostrare o nascondere voci della sidebar;
- impedire la navigazione ordinaria verso route amministrative;
- mostrare una pagina `Unauthorized`.

Questi controlli hanno valore di interfaccia e non devono essere considerati una barriera di sicurezza sufficiente.

Un utente può inviare richieste direttamente alle API indipendentemente da ciò che viene mostrato nel browser. Per questo i controlli reali vengono ripetuti dal backend.

## RBAC nel backend

Gli endpoint protetti richiedono un utente autenticato.

Il comportamento previsto distingue almeno i seguenti casi:

```text id="1zev9o"
nessun token valido     -> 401 Unauthorized
token non valido        -> 401 Unauthorized
token scaduto           -> 401 Unauthorized
ruolo insufficiente     -> 403 Forbidden
```

Gli endpoint amministrativi richiedono il ruolo `admin`.

Le normali funzionalità utente accettano i ruoli previsti dall'applicazione e applicano poi lo scope di ownership.

## Ownership delle analisi

Ogni analisi salva due informazioni relative al proprietario:

```text id="d5kpug"
owner_sub
owner_username
```

`owner_sub` è il riferimento principale.

La proprietà non viene legata esclusivamente allo username perché lo username può essere modificato nel tempo.

Il subject Keycloak rimane invece il riferimento stabile utilizzato dal backend per stabilire se una determinata analisi appartenga all'utente autenticato.

## Scope Analyst

Quando un `analyst` richiede la Cronologia, il backend applica automaticamente:

```text id="my7l4t"
owner_sub = subject utente corrente
```

Il browser non può disattivare questo vincolo aggiungendo o modificando parametri di query.

Lo stesso principio viene applicato al recupero del Dettaglio analisi.

Se un analyst prova ad accedere a una risorsa di un altro utente, il backend non considera la sola conoscenza dell'identificatore sufficiente per autorizzare la lettura.

## Scope Admin

Per un admin lo scope personale non viene applicato allo stesso modo.

Gli endpoint autorizzati possono accedere alla vista globale e, dove previsto, utilizzare filtri relativi all'owner.

Il comportamento viene comunque deciso server-side.

## Dashboard e ownership

La Dashboard rispetta lo stesso modello.

Un analyst riceve aggregati calcolati sul proprio scope.

Un admin può ricevere gli aggregati globali previsti.

Il frontend non scarica tutte le analisi per ricostruire statistiche che potrebbero violare i confini di ownership.

## Profilo utente

Il Profilo combina dati provenienti da Keycloak con informazioni applicative locali.

Keycloak mantiene:

- username;
- nome;
- cognome;
- email;
- stato verifica email;
- ruoli;
- password;
- sessioni.

PostgreSQL conserva invece dati specifici di SecureScan, come le informazioni relative all'avatar.

La risposta restituita al frontend combina queste sorgenti in uno snapshot coerente.

## Modifica dei dati personali

L'utente può modificare i campi consentiti del proprio profilo attraverso l'Analysis API.

Il backend utilizza il subject del token corrente e non accetta dal browser un identificatore arbitrario dell'utente da modificare.

In questo modo una normale operazione self-service rimane sempre riferita all'account autenticato.

Nome, cognome e username possono essere aggiornati senza utilizzare il workflow di verifica dell'email.

La modifica dell'indirizzo email segue invece un percorso distinto.

## Cambio email

Il cambio email è stato progettato per evitare di sostituire immediatamente un indirizzo già verificato con un nuovo valore non ancora confermato.

Quando l'utente inserisce un nuovo indirizzo, il backend verifica prima che il flow possa essere eseguito.

Sono necessari:

- verifica email abilitata;
- SMTP configurato;
- email corrente disponibile;
- email corrente già verificata.

Il sistema verifica inoltre che il nuovo indirizzo non sia già utilizzato da un altro account.

Se l'indirizzo risulta già associato a un altro utente, l'operazione viene rifiutata.

Il frontend mostra in questo caso:

```text id="v7ctmb"
Questo indirizzo email è già associato a un altro account.
```

Il backend restituisce semanticamente un conflitto e non deve lasciare una modifica parziale.

## Email pending

Quando il nuovo indirizzo è valido, non viene applicato immediatamente come email principale.

Viene mantenuto come indirizzo pending.

Il comportamento è:

```text id="z5zq4u"
email attuale verificata
        |
        v
richiesta nuova email
        |
        v
nuova email pending
        |
        +------> email attuale rimane attiva
        |
        v
utente apre link di verifica
        |
        v
nuova email confermata
        |
        v
sostituzione email attiva
```

Questa scelta evita di lasciare l'account associato a un indirizzo che l'utente potrebbe non controllare.

Il frontend mostra l'indirizzo in attesa di verifica quando la modifica è ancora pending.

## Provider Keycloak personalizzato

Il workflow di cambio email utilizza un provider Keycloak personalizzato presente sotto:

```text id="4ym9do"
infrastructure/keycloak/providers/securescan-email-change/
```

Il provider aggiunge le operazioni necessarie per:

- validare la richiesta di cambio email;
- avviare il cambio;
- reinviare il link per un indirizzo già pending;
- gestire l'action token utilizzato nella conferma.

Questo permette di mantenere la semantica desiderata senza spostare la gestione dell'identità fuori da Keycloak.

## Reinvio verifica email

Il backend espone una funzione per richiedere nuovamente l'email di verifica.

Il comportamento dipende dallo stato corrente dell'account.

Se è presente una nuova email pending, viene reinviato il link relativo al cambio email.

Se non esiste un indirizzo pending e l'indirizzo corrente non è ancora verificato, viene inviato il normale flow di verifica.

Se l'indirizzo corrente risulta già verificato, non viene avviata una verifica inutile.

## Forgot password e reset password

Il recupero della password resta un flow Keycloak.

Il frontend applicativo non implementa un proprio sistema di reset.

Il percorso è:

```text id="u51zrt"
utente
  |
  v
Password dimenticata
  |
  v
Keycloak
  |
  v
email reset
  |
  v
link
  |
  v
Reimposta password
```

Al termine viene mostrata la pagina personalizzata `Password aggiornata`.

Il ritorno al login avviene tramite l'azione prevista dalla pagina e non mediante un redirect automatico immediato.

## Cambio password da Profilo

Il cambio password effettuato da un utente già autenticato segue un flusso differente dal reset tramite email.

L'utente deve fornire:

```text id="15qp1j"
password attuale
nuova password
conferma nuova password
```

Il frontend esegue alcuni controlli preliminari per fornire feedback immediato.

Tra i requisiti verificati dalla UI rientrano:

- lunghezza compresa tra 8 e 24 caratteri;
- almeno una lettera maiuscola;
- almeno una lettera minuscola;
- almeno una cifra;
- almeno un carattere speciale;
- nuova password diversa dalla password corrente;
- corrispondenza tra nuova password e conferma.

Questi controlli non sostituiscono la logica backend e le policy applicate da Keycloak.

## Verifica della password corrente

Prima di aggiornare la credenziale, il backend verifica esplicitamente che la password corrente sia corretta.

Questa verifica utilizza un client Keycloak dedicato utilizzato esclusivamente dal backend per verificare la password corrente dell'utente durante il cambio credenziale.

Il client utilizzato per questa operazione dispone della propria configurazione e del proprio secret lato server.

Il browser non riceve questo secret.

Se la password corrente è errata, la modifica viene rifiutata.

## Aggiornamento password

Dopo la verifica della password corrente, il backend utilizza le API amministrative di Keycloak per impostare la nuova credenziale.

La password non viene mai salvata in PostgreSQL.

Al completamento il frontend chiude il dialog e mostra il feedback:

```text id="wzlmx7"
Password aggiornata correttamente.
```

Gli errori di validazione o di verifica vengono invece visualizzati all'interno del dialog.

## Gestione delle altre sessioni

Durante il cambio password l'utente può scegliere l'opzione:

```text id="wi1y9v"
Disconnetti le altre sessioni attive
```

L'opzione è selezionata di default.

Se rimane selezionata, dopo l'aggiornamento della password il backend recupera le sessioni attive dell'utente.

La sessione corrente viene identificata usando il claim `sid` del JWT. Quando necessario può essere utilizzato il fallback `session_state`.

Il backend termina le altre sessioni, preservando quella utilizzata per effettuare il cambio password.

Il comportamento può essere rappresentato come:

```text id="10c40d"
sessione corrente
     |
     | sid
     v
backend identifica sessione da preservare

altre sessioni
     |
     v
terminate
```

Se l'opzione viene deselezionata, la password viene aggiornata ma le altre sessioni restano attive.

## Perché preservare la sessione corrente

Terminare indiscriminatamente tutte le sessioni subito dopo il cambio password costringerebbe l'utente che ha appena completato correttamente l'operazione a effettuare immediatamente un nuovo login.

La preservazione della sessione corrente permette invece di revocare l'accesso agli altri dispositivi senza interrompere l'interazione da cui è partita la modifica.

## Operazioni amministrative

Le funzioni amministrative sugli utenti seguono un modello server-side.

Il browser non utilizza direttamente un token con privilegi amministrativi Keycloak.

Il percorso è:

```text id="jzm9db"
Admin autenticato
      |
      v
Frontend
      |
      v
Analysis API
      |
      | verifica ruolo admin
      v
Keycloak Admin API
```

Il backend mantiene quindi il controllo sulle operazioni amministrative e sui secret necessari.

## Protezione dell'ultimo amministratore

La logica amministrativa include controlli per evitare di lasciare il sistema senza amministratori attivi.

Quando una modifica potrebbe rimuovere il ruolo `admin` o disabilitare un utente amministratore, il backend verifica lo stato degli altri account gestiti prima di consentire l'operazione.

Questo evita che un'azione amministrativa valida dal punto di vista sintattico renda poi impossibile gestire la piattaforma.

## Avatar e autorizzazione

Gli avatar vengono gestiti tramite endpoint riferiti all'utente corrente.

Le route self-service non accettano un subject arbitrario dal frontend.

Il backend utilizza il subject autenticato per recuperare o modificare il file associato al profilo corretto.

## Audit

Il progetto mantiene informazioni utili alla diagnostica e alla ricostruzione del contesto delle richieste. Non è presente un sistema SIEM o un audit log dedicato.

Tra i dati che possono essere associati agli eventi rientrano:

- subject;
- username;
- ruoli;
- identificatori del token;
- informazioni sulla richiesta.

L'obiettivo è poter ricostruire il contesto dell'operazione senza affidarsi esclusivamente ai log del frontend.

## Configurazione SMTP

SMTP viene utilizzato da Keycloak per i flow che richiedono l'invio di email.

Tra questi:

```text id="usz53j"
verifica email
cambio email
forgot password
reset password
```

Le credenziali SMTP non sono memorizzate nel codice sorgente.

Vengono fornite attraverso la configurazione dell'ambiente e applicate a Keycloak dal runtime config.

## Ambiente locale

L'ambiente locale può includere utenti demo e configurazioni localhost utili allo sviluppo e alla presentazione.

Keycloak viene eseguito con impostazioni adatte a questo contesto e non deve essere interpretato come la configurazione usata per l'accesso pubblico.

## Ambiente production

Nel deployment Azure vengono utilizzati hostname pubblici, HTTPS e una configurazione Keycloak distinta da quella locale.

Gli utenti demo vengono disabilitati e i secret richiesti devono essere forniti esplicitamente.

Le configurazioni operative sensibili restano fuori dal repository.

Il deployment pubblico mantiene comunque la stessa separazione logica:

```text id="pqncqm"
Keycloak -> autenticazione
Analysis API -> autorizzazione
```

## Considerazioni di sicurezza

Le principali decisioni adottate in questa parte del progetto sono:

- password gestite esclusivamente da Keycloak;
- JWT verificati server-side;
- ruoli applicati dal backend;
- ownership basata sul subject stabile;
- secret dei client amministrativi non esposti al frontend;
- cambio email con conferma prima della sostituzione;
- controllo dell'unicità dell'indirizzo email;
- cambio password con verifica della password corrente;
- revoca opzionale delle altre sessioni;
- protezione della sessione corrente;
- protezione contro la rimozione dell'ultimo amministratore.

Queste misure non costituiscono un audit completo di sicurezza, ma fanno parte delle proprietà effettivamente implementate e testate nel progetto.

## Documenti correlati

Per il flusso completo delle richieste:

[Flussi end-to-end](request-flow.md)

Per la struttura dei componenti:

[Architettura](architecture.md)

Per la parte gateway e replica:

[High availability](high-availability.md)

Per una panoramica generale:

[README principale](../README.md)