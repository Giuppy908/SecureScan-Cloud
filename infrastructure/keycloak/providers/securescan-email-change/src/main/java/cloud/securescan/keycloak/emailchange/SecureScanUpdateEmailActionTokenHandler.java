package cloud.securescan.keycloak.emailchange;

import jakarta.ws.rs.core.Response;
import java.util.Objects;
import org.keycloak.authentication.actiontoken.AbstractActionTokenHandler;
import org.keycloak.authentication.actiontoken.ActionTokenContext;
import org.keycloak.authentication.requiredactions.UpdateEmail;
import org.keycloak.events.EventType;
import org.keycloak.events.Errors;
import org.keycloak.forms.login.LoginFormsProvider;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.UserModel;
import org.keycloak.models.UserSessionModel;
import org.keycloak.services.messages.Messages;
import org.keycloak.services.managers.AuthenticationManager;
import org.keycloak.sessions.AuthenticationSessionModel;
import org.keycloak.userprofile.UserProfile;
import org.keycloak.userprofile.ValidationException;

/**
 * Conferma il cambio email SecureScan senza coinvolgere il required action
 * UPDATE_EMAIL durante il login normale.
 */
public final class SecureScanUpdateEmailActionTokenHandler
    extends AbstractActionTokenHandler<SecureScanUpdateEmailActionToken> {

    public SecureScanUpdateEmailActionTokenHandler() {
        super(
            SecureScanUpdateEmailActionToken.TOKEN_TYPE,
            SecureScanUpdateEmailActionToken.class,
            Messages.EXPIRED_ACTION,
            EventType.EXECUTE_ACTION_TOKEN,
            Errors.INVALID_CODE
        );
    }

    @Override
    public Response handleToken(
        SecureScanUpdateEmailActionToken token,
        ActionTokenContext<SecureScanUpdateEmailActionToken> tokenContext
    ) {
        KeycloakSession session = tokenContext.getSession();
        AuthenticationSessionModel authenticationSession = tokenContext.getAuthenticationSession();
        UserModel user = authenticationSession.getAuthenticatedUser();
        LoginFormsProvider forms = session.getProvider(LoginFormsProvider.class)
            .setAuthenticationSession(authenticationSession)
            .setUser(user);

        String currentEmail = normalizeEmail(user.getEmail());
        String pendingEmail = normalizeEmail(user.getFirstAttribute(SecureScanEmailChangeResource.SECURESCAN_PENDING_EMAIL_ATTRIBUTE));
        if (pendingEmail == null) {
            pendingEmail = normalizeEmail(user.getFirstAttribute(SecureScanEmailChangeResource.LEGACY_KEYCLOAK_PENDING_EMAIL_ATTRIBUTE));
        }
        String tokenOldEmail = normalizeEmail(token.getOldEmail());
        String tokenNewEmail = normalizeEmail(token.getNewEmail());

        if (currentEmail == null
            || pendingEmail == null
            || tokenOldEmail == null
            || tokenNewEmail == null
            || !Objects.equals(currentEmail, tokenOldEmail)
            || !Objects.equals(pendingEmail, tokenNewEmail)) {
            tokenContext.getEvent().error(Errors.INVALID_CODE);
            return forms.setError(Messages.EXPIRED_ACTION).createErrorPage(Response.Status.BAD_REQUEST);
        }

        UserProfile validatedProfile;
        try {
            validatedProfile = UpdateEmail.validateEmailUpdate(session, user, tokenNewEmail);
        } catch (ValidationException exception) {
            tokenContext.getEvent().error(Errors.INVALID_CODE);
            return forms.setError(Messages.EXPIRED_ACTION).createErrorPage(Response.Status.BAD_REQUEST);
        }

        UpdateEmail.updateEmailNow(tokenContext.getEvent(), user, validatedProfile);
        user.removeAttribute(SecureScanEmailChangeResource.SECURESCAN_PENDING_EMAIL_ATTRIBUTE);
        user.removeAttribute(SecureScanEmailChangeResource.LEGACY_KEYCLOAK_PENDING_EMAIL_ATTRIBUTE);
        user.removeRequiredAction(UserModel.RequiredAction.UPDATE_EMAIL.name());
        user.removeRequiredAction(UserModel.RequiredAction.VERIFY_EMAIL.name());
        user.setEmailVerified(true);

        if (authenticationSession != null) {
            authenticationSession.removeRequiredAction(UserModel.RequiredAction.UPDATE_EMAIL.name());
            authenticationSession.removeRequiredAction(UserModel.RequiredAction.VERIFY_EMAIL.name());
        }

        if (Boolean.TRUE.equals(token.getLogoutSessions())) {
            session.sessions()
                .getUserSessionsStream(session.getContext().getRealm(), user)
                .toList()
                .forEach(userSession -> logoutUserSession(session, userSession));
        }

        tokenContext.getEvent().success();
        return forms
            .setAttribute("messageHeader", forms.getMessage("emailUpdatedTitle"))
            .setSuccess("emailUpdated")
            .createInfoPage();
    }

    private static String normalizeEmail(String value) {
        if (value == null) {
            return null;
        }
        String normalized = value.trim().toLowerCase();
        return normalized.isEmpty() ? null : normalized;
    }

    private static void logoutUserSession(KeycloakSession session, UserSessionModel userSession) {
        AuthenticationManager.backchannelLogout(
            session,
            session.getContext().getRealm(),
            userSession,
            session.getContext().getUri(),
            session.getContext().getConnection(),
            session.getContext().getRequestHeaders(),
            true
        );
    }
}
