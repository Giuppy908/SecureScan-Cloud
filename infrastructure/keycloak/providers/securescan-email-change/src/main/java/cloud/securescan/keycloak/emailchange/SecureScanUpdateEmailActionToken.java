package cloud.securescan.keycloak.emailchange;

import java.util.UUID;
import org.keycloak.authentication.actiontoken.DefaultActionToken;

/**
 * Token SecureScan dedicato al cambio email degli account già esistenti.
 *
 * A differenza del token nativo UPDATE_EMAIL, questo token non dipende da
 * UserModel.EMAIL_PENDING durante il login: la pending email persistente resta
 * separata dal flow di required actions standard di Keycloak.
 */
public final class SecureScanUpdateEmailActionToken extends DefaultActionToken {

    public static final String TOKEN_TYPE = "securescan-update-email";

    private String oldEmail;
    private String newEmail;
    private Boolean logoutSessions;
    private String redirectUri;

    public SecureScanUpdateEmailActionToken() {
        super();
        type(TOKEN_TYPE);
    }

    public SecureScanUpdateEmailActionToken(
        String userId,
        int absoluteExpirationInSecs,
        String oldEmail,
        String newEmail,
        String clientId,
        Boolean logoutSessions,
        String redirectUri
    ) {
        super(userId, TOKEN_TYPE, absoluteExpirationInSecs, UUID.randomUUID());
        this.oldEmail = oldEmail;
        this.newEmail = newEmail;
        this.logoutSessions = logoutSessions;
        this.redirectUri = redirectUri;
        issuedFor(clientId);
    }

    public String getOldEmail() {
        return oldEmail;
    }

    public void setOldEmail(String oldEmail) {
        this.oldEmail = oldEmail;
    }

    public String getNewEmail() {
        return newEmail;
    }

    public void setNewEmail(String newEmail) {
        this.newEmail = newEmail;
    }

    public Boolean getLogoutSessions() {
        return logoutSessions;
    }

    public void setLogoutSessions(Boolean logoutSessions) {
        this.logoutSessions = logoutSessions;
    }

    public String getRedirectUri() {
        return redirectUri;
    }

    public void setRedirectUri(String redirectUri) {
        this.redirectUri = redirectUri;
    }
}
