package cloud.securescan.keycloak.emailchange;

import jakarta.ws.rs.BadRequestException;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.ForbiddenException;
import jakarta.ws.rs.InternalServerErrorException;
import jakarta.ws.rs.NotAuthorizedException;
import jakarta.ws.rs.NotFoundException;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import java.util.List;
import java.util.Locale;
import java.util.Objects;
import java.util.concurrent.TimeUnit;
import org.keycloak.authentication.requiredactions.UpdateEmail;
import org.keycloak.common.util.Time;
import org.keycloak.email.EmailException;
import org.keycloak.email.EmailTemplateProvider;
import org.keycloak.models.ClientModel;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.RealmModel;
import org.keycloak.models.UserModel;
import org.keycloak.models.utils.FormMessage;
import org.keycloak.protocol.oidc.utils.RedirectUtils;
import org.keycloak.representations.AccessToken;
import org.keycloak.services.ErrorResponse;
import org.keycloak.services.ErrorResponseException;
import org.keycloak.services.managers.AppAuthManager;
import org.keycloak.services.managers.AuthenticationManager;
import org.keycloak.services.messages.Messages;
import org.keycloak.services.resources.LoginActionsService;
import org.keycloak.services.validation.Validation;
import org.keycloak.userprofile.UserProfile;
import org.keycloak.userprofile.ValidationException;

/**
 * Endpoint interno usato solo dal backend applicativo.
 *
 * Il provider non sostituisce il flow nativo di registrazione: riusa invece le
 * primitive ufficiali di Keycloak 26.7.0 per UPDATE_EMAIL, così l'email
 * corrente resta attiva finché il link ricevuto sul nuovo indirizzo non viene
 * confermato.
 */
@Path("/")
@Produces(MediaType.APPLICATION_JSON)
public final class SecureScanEmailChangeResource {

    private static final String ADMIN_CLIENT_ID_ENV = "KEYCLOAK_ADMIN_CLIENT_ID";
    private static final String DEFAULT_ADMIN_CLIENT_ID = "securescan-admin-api";
    public static final String SECURESCAN_PENDING_EMAIL_ATTRIBUTE = "securescan.email.pending";
    public static final String LEGACY_KEYCLOAK_PENDING_EMAIL_ATTRIBUTE = UserModel.EMAIL_PENDING;

    private final KeycloakSession session;
    private final RealmModel realm;
    private final String expectedAdminClientId;

    public SecureScanEmailChangeResource(KeycloakSession session) {
        this.session = session;
        this.realm = session.getContext().getRealm();
        this.expectedAdminClientId = normalizeExpectedAdminClientId(System.getenv(ADMIN_CLIENT_ID_ENV));
    }

    @POST
    @Path("email-change/validate")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response validateEmailChange(EmailChangeRequest payload) {
        requireAdminClient();
        UserModel user = requireUser(payload);
        requireVerifiedCurrentEmail(user);

        try {
            UpdateEmail.validateEmailUpdate(session, user, normalizeEmail(payload.newEmail()));
        } catch (ValidationException exception) {
            throw toValidationError(exception);
        }

        return Response.noContent().build();
    }

    @POST
    @Path("email-change")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response initiateEmailChange(EmailChangeRequest payload) {
        requireAdminClient();
        UserModel user = requireUser(payload);
        requireVerifiedCurrentEmail(user);

        String newEmail = normalizeEmail(payload.newEmail());
        if (Objects.equals(normalizeEmail(user.getEmail()), newEmail)) {
            throw new BadRequestException("La nuova email coincide già con quella attuale.");
        }

        UserProfile validatedProfile;
        try {
            validatedProfile = UpdateEmail.validateEmailUpdate(session, user, newEmail);
        } catch (ValidationException exception) {
            throw toValidationError(exception);
        }

        EmailActionContext emailActionContext = resolveEmailActionContext(payload);
        // UserModel.EMAIL_PENDING appartiene al flow nativo UPDATE_EMAIL di
        // Keycloak e fa scattare di nuovo la required action durante il login.
        // SecureScan conserva quindi la pending email in un attributo separato,
        // così l'account esistente resta utilizzabile fino alla conferma.
        user.setSingleAttribute(SECURESCAN_PENDING_EMAIL_ATTRIBUTE, newEmail);
        user.removeAttribute(UserModel.EMAIL_PENDING);
        user.removeRequiredAction(UserModel.RequiredAction.UPDATE_EMAIL.name());
        user.removeRequiredAction(UserModel.RequiredAction.VERIFY_EMAIL.name());

        sendEmailChangeConfirmation(user, validatedProfile, emailActionContext);
        return Response.noContent().build();
    }

    @POST
    @Path("email-change/resend")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response resendPendingEmailChange(EmailChangeResendRequest payload) {
        requireAdminClient();
        UserModel user = requireUser(payload.subject());
        requireVerifiedCurrentEmail(user);

        String pendingEmail = getPendingEmail(user);
        if (pendingEmail == null) {
            throw new BadRequestException("Nessuna nuova email in attesa di verifica.");
        }
        user.setSingleAttribute(SECURESCAN_PENDING_EMAIL_ATTRIBUTE, pendingEmail);
        user.removeAttribute(UserModel.EMAIL_PENDING);
        user.removeRequiredAction(UserModel.RequiredAction.UPDATE_EMAIL.name());
        user.removeRequiredAction(UserModel.RequiredAction.VERIFY_EMAIL.name());

        UserProfile validatedProfile;
        try {
            validatedProfile = UpdateEmail.validateEmailUpdate(session, user, pendingEmail);
        } catch (ValidationException exception) {
            throw toValidationError(exception);
        }

        EmailActionContext emailActionContext = resolveEmailActionContext(
            new EmailChangeRequest(payload.subject(), pendingEmail, payload.clientId(), payload.redirectUri(), payload.lifespanSeconds())
        );
        sendEmailChangeConfirmation(user, validatedProfile, emailActionContext);
        return Response.noContent().build();
    }

    private void sendEmailChangeConfirmation(
        UserModel user,
        UserProfile validatedProfile,
        EmailActionContext emailActionContext
    ) {
        String newEmail = normalizeEmail(validatedProfile.getAttributes().getFirst(UserModel.EMAIL));
        if (newEmail == null) {
            throw new BadRequestException("L'indirizzo email non è valido.");
        }

        SecureScanUpdateEmailActionToken token = new SecureScanUpdateEmailActionToken(
            user.getId(),
            Time.currentTime() + emailActionContext.lifespanSeconds(),
            user.getEmail(),
            newEmail,
            emailActionContext.clientId(),
            // Dopo la conferma vogliamo invalidare le sessioni attive
            // dell'account, così il successivo accesso rilegge subito l'email
            // aggiornata senza lasciare sessioni Keycloak precedenti aperte.
            Boolean.TRUE,
            emailActionContext.redirectUri()
        );

        String link = LoginActionsService.actionTokenProcessor(session.getContext().getUri())
            .queryParam("key", token.serialize(session, realm, session.getContext().getUri()))
            .build(realm.getName())
            .toString();

        try {
            session.getProvider(EmailTemplateProvider.class)
                .setRealm(realm)
                .setUser(user)
                .sendEmailUpdateConfirmation(link, TimeUnit.SECONDS.toMinutes(emailActionContext.lifespanSeconds()), newEmail);
        } catch (EmailException exception) {
            throw new InternalServerErrorException("L'invio dell'email non è disponibile. Configura correttamente il server SMTP.");
        }
    }

    private EmailActionContext resolveEmailActionContext(EmailChangeRequest payload) {
        String clientId = normalizeOptionalClientId(payload.clientId());
        if (clientId == null) {
            throw new BadRequestException("Il client Keycloak per il redirect non è configurato.");
        }

        ClientModel client = realm.getClientByClientId(clientId);
        if (client == null) {
            throw new BadRequestException("Il client Keycloak per il redirect non esiste.");
        }
        if (!client.isEnabled()) {
            throw new BadRequestException("Il client Keycloak per il redirect non è abilitato.");
        }

        String redirectUri = normalizeRedirectUri(payload.redirectUri());
        if (redirectUri != null) {
            redirectUri = RedirectUtils.verifyRedirectUri(session, redirectUri, client);
            if (redirectUri == null) {
                throw new BadRequestException("Il redirect configurato per il cambio email non è valido.");
            }
        }

        int lifespanSeconds = payload.lifespanSeconds() != null
            ? payload.lifespanSeconds()
            : realm.getActionTokenGeneratedByUserLifespan(SecureScanUpdateEmailActionToken.TOKEN_TYPE);
        if (lifespanSeconds <= 0) {
            throw new BadRequestException("La durata del token di cambio email non è valida.");
        }

        return new EmailActionContext(clientId, redirectUri, lifespanSeconds);
    }

    private UserModel requireUser(EmailChangeRequest payload) {
        return requireUser(payload.subject());
    }

    private UserModel requireUser(String subject) {
        if (subject == null || subject.isBlank()) {
            throw new BadRequestException("Il subject utente è obbligatorio.");
        }

        UserModel user = session.users().getUserById(realm, subject.trim());
        if (user == null) {
            throw new NotFoundException("L'utente richiesto non è stato trovato in Keycloak.");
        }
        return user;
    }

    private void requireVerifiedCurrentEmail(UserModel user) {
        String currentEmail = normalizeEmail(user.getEmail());
        if (currentEmail == null) {
            throw new BadRequestException("Nessun indirizzo email attualmente associato all'account.");
        }
        if (!user.isEmailVerified()) {
            throw new ForbiddenException("Completa prima la verifica dell'indirizzo email attuale.");
        }
    }

    private static String getPendingEmail(UserModel user) {
        String pendingEmail = normalizeEmail(user.getFirstAttribute(SECURESCAN_PENDING_EMAIL_ATTRIBUTE));
        if (pendingEmail != null) {
            return pendingEmail;
        }
        return normalizeEmail(user.getFirstAttribute(LEGACY_KEYCLOAK_PENDING_EMAIL_ATTRIBUTE));
    }

    private void requireAdminClient() {
        AuthenticationManager.AuthResult authResult = new AppAuthManager.BearerTokenAuthenticator(session)
            .setRealm(realm)
            .setHeaders(session.getContext().getRequestHeaders())
            .setConnection(session.getContext().getConnection())
            .authenticate();

        if (authResult == null) {
            throw new NotAuthorizedException("Bearer");
        }

        AccessToken token = authResult.getToken();
        String issuedFor = normalizeOptionalClientId(token != null ? token.getIssuedFor() : null);
        if (issuedFor == null || !issuedFor.equals(expectedAdminClientId)) {
            throw new ForbiddenException("Il token usato non è autorizzato a gestire il cambio email self-service.");
        }
    }

    private ErrorResponseException toValidationError(ValidationException exception) {
        List<FormMessage> errors = Validation.getFormErrorsFromValidation(exception.getErrors());
        ValidationErrorDetails error = errors.isEmpty()
            ? new ValidationErrorDetails(Response.Status.BAD_REQUEST, "La richiesta di cambio email non è valida.")
            : mapValidationError(errors.get(0));
        return error.status() == Response.Status.CONFLICT
            ? ErrorResponse.exists(error.message())
            : ErrorResponse.error(error.message(), error.status());
    }

    private static ValidationErrorDetails mapValidationError(FormMessage error) {
        if (error == null) {
            return new ValidationErrorDetails(Response.Status.BAD_REQUEST, "La richiesta di cambio email non è valida.");
        }
        return mapValidationMessage(error.getMessage());
    }

    private static ValidationErrorDetails mapValidationMessage(String rawMessage) {
        if (rawMessage == null || rawMessage.isBlank()) {
            return new ValidationErrorDetails(Response.Status.BAD_REQUEST, "La richiesta di cambio email non è valida.");
        }

        if (Messages.EMAIL_EXISTS.equals(rawMessage)) {
            return new ValidationErrorDetails(Response.Status.CONFLICT, "Esiste già un account con questa email");
        }
        if (Messages.INVALID_EMAIL.equals(rawMessage)) {
            return new ValidationErrorDetails(Response.Status.BAD_REQUEST, "L'indirizzo email non è valido");
        }

        String lowered = rawMessage.toLowerCase(Locale.ROOT);
        if (lowered.contains("email") && lowered.contains("exist")) {
            return new ValidationErrorDetails(Response.Status.CONFLICT, "Esiste già un account con questa email");
        }
        if (lowered.contains("invalid") && lowered.contains("email")) {
            return new ValidationErrorDetails(Response.Status.BAD_REQUEST, "L'indirizzo email non è valido");
        }
        return new ValidationErrorDetails(Response.Status.BAD_REQUEST, rawMessage);
    }

    private static String normalizeEmail(String value) {
        if (value == null) {
            return null;
        }
        String normalized = value.trim().toLowerCase(Locale.ROOT);
        return normalized.isEmpty() ? null : normalized;
    }

    private static String normalizeRedirectUri(String value) {
        if (value == null) {
            return null;
        }
        String normalized = value.trim();
        return normalized.isEmpty() ? null : normalized;
    }

    private static String normalizeExpectedAdminClientId(String value) {
        if (value == null || value.isBlank()) {
            return DEFAULT_ADMIN_CLIENT_ID;
        }
        return value.trim();
    }

    private static String normalizeOptionalClientId(String value) {
        if (value == null) {
            return null;
        }
        String normalized = value.trim();
        return normalized.isEmpty() ? null : normalized;
    }

    public record EmailChangeRequest(
        String subject,
        String newEmail,
        String clientId,
        String redirectUri,
        Integer lifespanSeconds
    ) {
    }

    public record EmailChangeResendRequest(
        String subject,
        String clientId,
        String redirectUri,
        Integer lifespanSeconds
    ) {
    }

    private record EmailActionContext(
        String clientId,
        String redirectUri,
        int lifespanSeconds
    ) {
    }

    private record ValidationErrorDetails(
        Response.Status status,
        String message
    ) {
    }
}
