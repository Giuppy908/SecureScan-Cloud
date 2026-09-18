package cloud.securescan.keycloak.emailchange;

import org.keycloak.models.KeycloakSession;
import org.keycloak.services.resource.RealmResourceProvider;

/**
 * Wrapper minimale che collega Keycloak al resource JAX-RS custom.
 */
public final class SecureScanEmailChangeResourceProvider implements RealmResourceProvider {

    private final SecureScanEmailChangeResource resource;

    public SecureScanEmailChangeResourceProvider(KeycloakSession session) {
        this.resource = new SecureScanEmailChangeResource(session);
    }

    @Override
    public Object getResource() {
        return resource;
    }

    @Override
    public void close() {
        // Nessuna risorsa per-request da rilasciare.
    }
}
