# SecureScan Keycloak

Keycloak è il componente responsabile della gestione delle identità e dell'autenticazione all'interno della piattaforma SecureScan Cloud.

Il servizio fornisce tutte le funzionalità relative alla gestione degli utenti e dei flussi di autenticazione, evitando che la logica di sicurezza degli account venga implementata direttamente nel frontend o nei servizi applicativi.

All'interno del progetto Keycloak gestisce:

- login degli utenti;
- registrazione degli account;
- verifica dell'indirizzo email;
- recupero password;
- reset password;
- gestione dei ruoli applicativi;
- emissione dei token JWT utilizzati dalle API.

L'Analysis API non gestisce direttamente credenziali o password degli utenti. L'autenticazione viene delegata completamente a Keycloak, mentre il backend verifica successivamente identità e autorizzazioni contenute nel token ricevuto.

## Ruolo nell'architettura SecureScan Cloud

Keycloak rappresenta l'Identity Provider della piattaforma.

Il flusso generale di autenticazione è:

```text
Utente
   |
   v
Frontend React
   |
   v
Keycloak
   |
   v
JWT Access Token
   |
   v
Analysis API
```

Il frontend avvia il processo di login tramite Keycloak utilizzando Authorization Code Flow con PKCE.

Dopo l'autenticazione:

1. Keycloak verifica le credenziali dell'utente;
2. genera un token JWT;
3. restituisce il token al frontend;
4. il frontend utilizza il token nelle richieste verso il backend;
5. l'Analysis API verifica firma, issuer, audience e ruoli.

Keycloak non comunica direttamente con PostgreSQL applicativo utilizzato da SecureScan per le analisi.

La gestione delle identità rimane separata dalla gestione dei dati applicativi.

## Separazione tra autenticazione e autorizzazione

SecureScan Cloud separa due responsabilità differenti:

### Autenticazione

L'autenticazione verifica chi è l'utente.

Questa fase è gestita completamente da Keycloak attraverso:

- credenziali;
- sessioni;
- token JWT;
- procedure di recupero account.

### Autorizzazione

L'autorizzazione stabilisce cosa può fare l'utente.

Il progetto utilizza principalmente due ruoli applicativi:

```text
analyst
admin
```

Il frontend utilizza il ruolo per adattare l'interfaccia mostrata.

Il controllo effettivo delle autorizzazioni viene comunque effettuato dal backend.

Un utente non può ottenere privilegi aggiuntivi modificando solamente il codice frontend.

## Realm SecureScan

La configurazione principale è contenuta nel file:

```text
realm-securescan.json
```

Il realm definisce:

- utenti iniziali;
- ruoli;
- client;
- configurazioni di autenticazione;
- impostazioni email;
- flow disponibili.

Durante l'avvio del container Keycloak il realm viene importato automaticamente attraverso Docker Compose.

## Client configurati

I principali client presenti nel realm sono:

```text
securescan-frontend
securescan-admin-api
securescan-rbac-demo
```

## securescan-frontend

È il client utilizzato dall'applicazione React.

Il frontend utilizza:

```text
Authorization Code Flow con PKCE
```

Questo approccio evita di memorizzare secret sensibili nel browser e rappresenta il flusso consigliato per applicazioni pubbliche.

Il client gestisce:

- login;
- logout;
- redirect;
- gestione sessione utente;
- rinnovo token.

## securescan-admin-api

È utilizzato dai servizi backend che devono effettuare operazioni amministrative tramite Keycloak.

Il client utilizza un secret mantenuto lato server e non esposto al frontend.

## securescan-rbac-demo

È un client utilizzato per scenari dimostrativi relativi alla gestione dei ruoli.

Permette di mostrare il comportamento differenziato tra utenti con privilegi diversi.

## Ruoli applicativi

SecureScan utilizza due ruoli principali.

## analyst

Un utente analyst può:

- caricare file;
- consultare le proprie analisi;
- visualizzare risultati;
- gestire il proprio profilo.

## admin

Un utente admin dispone inoltre delle funzionalità amministrative:

- visualizzazione utenti;
- gestione informazioni utente;
- consultazione globale delle analisi.

La presenza del ruolo nel JWT permette al backend di applicare controlli RBAC.

## Theme personalizzato

La directory:

```text
theme/securescan/
```

contiene il tema grafico personalizzato utilizzato da Keycloak.

Il tema permette di mantenere coerenza visiva tra:

- pagina di login;
- registrazione;
- recupero password;
- schermate generate direttamente da Keycloak.

In questo modo l'esperienza utente rimane integrata con il resto della piattaforma.

## Runtime configuration

Il file:

```text
apply_runtime_config.py
```

viene eseguito tramite il servizio:

```text
keycloak-runtime-config
```

durante l'avvio dello stack.

Il suo scopo è applicare configurazioni che non devono essere necessariamente mantenute staticamente nel realm JSON.

Tra queste:

- redirect URI;
- web origins;
- hostname;
- configurazione SMTP;
- impostazione SSL richiesta;
- secret dei client backend;
- gestione utenti demo.

Questa separazione permette di utilizzare lo stesso realm di base in ambienti differenti.

## Flusso reset password

SecureScan utilizza il flusso password recovery fornito da Keycloak.

Il comportamento previsto è:

1. l'utente seleziona "password dimenticata";
2. Keycloak invia il link di recupero;
3. l'utente aggiorna la password;
4. Keycloak completa il reset.

Il flusso attuale mantiene la pagina finale di conferma:

```text
Password aggiornata
```

senza effettuare redirect automatici.

Questa scelta evita comportamenti poco chiari dopo una modifica della password.

## Configurazione email e SMTP

Keycloak supporta la configurazione SMTP necessaria per:

- verifica email;
- reset password;
- comunicazioni automatiche.

I parametri vengono forniti tramite variabili ambiente e applicati dalla runtime configuration.

In ambiente locale la configurazione può essere disabilitata per facilitare sviluppo e demo.

In produzione deve essere configurata utilizzando un servizio SMTP reale.

## Provider personalizzato

La directory contiene:

```text
providers/securescan-email-change/
```

che contiene un provider custom Keycloak.

Il provider estende i flow standard quando sono necessarie funzionalità specifiche del progetto relative alla gestione email.

Il progetto mantiene quindi la possibilità di personalizzare alcuni comportamenti senza modificare direttamente il codice interno di Keycloak.

## Ambiente locale e demo

Lo stack locale utilizza una configurazione pensata per sviluppo e presentazione.

Sono mantenuti:

```text
start-dev
localhost redirect URI
sslRequired=none
utenti demo
```

Queste impostazioni riducono la complessità durante sviluppo e demo.

Non rappresentano una configurazione adatta a un ambiente pubblico.

## Configurazione production

L'ambiente production utilizza:

```text
compose.production.yaml
```

che modifica il comportamento di Keycloak.

Le principali differenze sono:

- avvio tramite modalità production;
- hostname pubblico;
- database dedicato;
- secret obbligatori;
- utenti demo disabilitati;
- configurazione HTTPS tramite reverse proxy.

In produzione Keycloak viene raggiunto attraverso Caddy:

```text
Internet
   |
   v
Caddy HTTPS
   |
   v
Keycloak
```

La porta interna di Keycloak non viene pubblicata direttamente.

## File principali

La directory contiene:

```text
realm-securescan.json
```

Configurazione principale del realm.

```text
apply_runtime_config.py
```

Script che applica configurazioni dipendenti dall'ambiente.

```text
Dockerfile
```

Immagine personalizzata di Keycloak.

```text
providers/securescan-email-change/
```

Provider custom per funzionalità aggiuntive.

```text
theme/securescan/
```

Tema grafico personalizzato.

## Integrazione con Docker Compose

Keycloak viene eseguito come servizio indipendente nello stack.

Il servizio:

- espone il provider di identità;
- mantiene dati persistenti tramite volume;
- viene utilizzato dal frontend per il login;
- viene utilizzato dal backend per validare gli utenti.

Il servizio:

```text
keycloak-runtime-config
```

viene eseguito successivamente per applicare la configurazione runtime.

La sua terminazione con codice:

```text
Exited (0)
```

è prevista e indica completamento corretto.

## Collegamenti documentazione

Per il modello di autenticazione e RBAC:

[Autenticazione e RBAC](../../docs/authentication-rbac.md)

Per la descrizione generale dell'architettura:

[Architettura](../../docs/architecture.md)

Per il flusso completo delle richieste:

[Request flow](../../docs/request-flow.md)
