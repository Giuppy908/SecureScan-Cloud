<#import "template.ftl" as layout>
<@layout.emailLayout>
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="margin:0;padding:0;background-color:#07111b;font-family:Arial,'Segoe UI',sans-serif;color:#eff7fb;">
  <tr>
    <td align="center" style="padding:32px 16px;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="max-width:600px;background-color:#0a1824;border:1px solid rgba(143,211,220,0.18);border-radius:24px;box-shadow:0 20px 40px rgba(0,0,0,0.28);overflow:hidden;">
        <tr>
          <td style="padding:32px 32px 12px;text-align:center;">
            <div style="display:inline-block;padding:8px 14px;border-radius:999px;border:1px solid rgba(66,217,234,0.32);background-color:rgba(16,37,53,0.82);color:#9be8f0;font-size:12px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;">
              SecureScan Cloud
            </div>
          </td>
        </tr>
        <tr>
          <td style="padding:0 32px 32px;">
            <h1 style="margin:12px 0 16px;color:#f8fcff;font-size:30px;line-height:1.2;text-align:center;">${msg("emailUpdateConfirmationHeading")}</h1>
            <p style="margin:0 0 14px;color:#eff7fb;font-size:16px;line-height:1.7;text-align:center;">${msg("emailUpdateConfirmationLead")}</p>
            <p style="margin:0 0 24px;color:#9eb2bf;font-size:15px;line-height:1.7;text-align:center;">${msg("emailUpdateConfirmationBody")}</p>
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center" style="margin:0 auto 24px;">
              <tr>
                <td align="center" bgcolor="#42d9ea" style="border-radius:16px;">
                  <a href="${link}" style="display:inline-block;padding:15px 28px;font-size:16px;font-weight:700;color:#042534;text-decoration:none;border-radius:16px;">
                    ${msg("emailUpdateConfirmationCta")}
                  </a>
                </td>
              </tr>
            </table>
            <div style="padding:16px 18px;border-radius:18px;background-color:rgba(16,37,53,0.82);border:1px solid rgba(143,211,220,0.18);">
              <p style="margin:0 0 8px;color:#eff7fb;font-size:14px;font-weight:700;">${msg("emailUpdateConfirmationExpiryTitle")}</p>
              <p style="margin:0;color:#9eb2bf;font-size:14px;line-height:1.7;">${msg("emailUpdateConfirmationExpiry", linkExpirationFormatter(linkExpiration))}</p>
            </div>
            <p style="margin:18px 0 0;color:#9eb2bf;font-size:13px;line-height:1.7;text-align:center;">${msg("emailUpdateConfirmationIgnore")}</p>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
</@layout.emailLayout>
