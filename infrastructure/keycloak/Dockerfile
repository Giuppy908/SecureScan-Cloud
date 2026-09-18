FROM maven:3.9.9-eclipse-temurin-21 AS provider-builder

WORKDIR /build/securescan-email-change

# Compila il provider custom che estende Keycloak solo per il cambio email
# self-service degli account già esistenti. Il realm e il theme restano montati
# a runtime come prima: qui costruiamo esclusivamente il JAR del provider.
COPY providers/securescan-email-change/pom.xml ./pom.xml
COPY providers/securescan-email-change/src ./src

RUN mvn -q -DskipTests package

FROM quay.io/keycloak/keycloak:26.7.0

# Il provider viene copiato nell'immagine finale senza alterare theme,
# configurazione realm o comportamento della registrazione.
COPY --from=provider-builder \
  /build/securescan-email-change/target/securescan-email-change-provider-1.0.0.jar \
  /opt/keycloak/providers/securescan-email-change-provider.jar
