# Build multi-stage del frontend SecureScan Cloud.
# Il primo stage compila l'app React/Vite; il secondo la serve come bundle
# statico tramite Nginx. Non implementa direttamente una pagina, ma rende
# distribuibili Dashboard, Cronologia, Profilo e le altre viste nel browser.
FROM node:22.23.0-bookworm-slim AS build

WORKDIR /workspace

# Il browser usa questo URL per le API; il valore può essere fornito come argomento della build.
ARG VITE_ANALYSIS_API_URL=http://localhost:8000
# Le variabili VITE_* vengono incorporate nel bundle in fase di build.
ENV VITE_ANALYSIS_API_URL=${VITE_ANALYSIS_API_URL}
# Il limite viene incorporato nella validazione client dell'upload e non configura il backend.
ARG VITE_MAX_UPLOAD_SIZE_MB=250
ENV VITE_MAX_UPLOAD_SIZE_MB=${VITE_MAX_UPLOAD_SIZE_MB}
# URL, realm e client identificano il server di autenticazione e l'applicazione registrata in Keycloak.
ARG VITE_KEYCLOAK_URL=http://localhost:8180
ENV VITE_KEYCLOAK_URL=${VITE_KEYCLOAK_URL}
ARG VITE_KEYCLOAK_REALM=securescan
ENV VITE_KEYCLOAK_REALM=${VITE_KEYCLOAK_REALM}
ARG VITE_KEYCLOAK_CLIENT_ID=securescan-frontend
ENV VITE_KEYCLOAK_CLIENT_ID=${VITE_KEYCLOAK_CLIENT_ID}

# Copia prima i manifest per riutilizzare il livello delle dipendenze quando cambiano solo i sorgenti.
COPY package.json package-lock.json ./
# Installa le versioni del lockfile, incluse le dipendenze opzionali richieste dagli strumenti di build.
RUN npm ci --include=optional

# Aggiunge al filesystem dello stage i sorgenti ammessi dal file .dockerignore.
COPY . .
# Esegue lo script del manifest per controllare TypeScript e produrre gli asset statici.
RUN npm run build

# Lo stage finale contiene server web e asset compilati, senza il processo di sviluppo Vite.
FROM nginx:1.27.2-alpine3.20

# Nginx espone la Single Page Application già compilata e delega il routing interno a React Router.
COPY nginx.conf /etc/nginx/nginx.conf
# Trasferisce soltanto il risultato compilato dallo stage Node alla directory pubblicata da Nginx.
COPY --from=build /workspace/dist /usr/share/nginx/html

EXPOSE 80

# Controlla che Nginx risponda alla radice; questo test non verifica login o disponibilità delle API.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1

# Mantiene Nginx in primo piano come processo principale del container.
CMD ["nginx", "-g", "daemon off;"]
