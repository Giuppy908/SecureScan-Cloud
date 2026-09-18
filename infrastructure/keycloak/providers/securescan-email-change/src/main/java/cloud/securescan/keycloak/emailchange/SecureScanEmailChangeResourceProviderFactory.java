package cloud.securescan.keycloak.emailchange;

import org.keycloak.models.KeycloakSession;
import org.keycloak.models.KeycloakSessionFactory;
import org.keycloak.services.resource.RealmResourceProvider;
import org.keycloak.services.resource.RealmResourceProviderFactory;

/**
 * Espone un piccolo endpoint realm-scoped usato solo dall'Analysis API.
 *
 * Serve a far partire il workflow sicuro di cambio email senza costringere il
 * frontend SecureScan a mostrare un secondo form Keycloak per reinserire la
 * stessa email già digitata nella pagina "Modifica profilo".
 */
public final class SecureScanEmailChangeResourceProviderFactory implements RealmResourceProviderFactory {

    public static final String ID = "securescan-account";

    @Override
    public RealmResourceProvider create(KeycloakSession session) {
        return new SecureScanEmailChangeResourceProvider(session);
    }

    @Override
    public void init(org.keycloak.Config.Scope config) {
        // Nessuna configurazione custom aggiuntiva.
    }

    @Override
    public void postInit(KeycloakSessionFactory factory) {
        // Nessun hook globale richiesto.
    }

    @Override
    public void close() {
        // Nessuna risorsa condivisa da chiudere.
    }

    @Override
    public String getId() {
        return ID;
    }
}
