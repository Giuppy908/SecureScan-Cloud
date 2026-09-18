<#ftl output_format="plainText">
${msg("emailVerificationPlainTextIntro")}

${msg("emailVerificationPlainTextBody")}

${msg("emailVerificationPlainTextExpiry", linkExpirationFormatter(linkExpiration))}

${msg("emailVerificationPlainTextAction")}
${link}

${msg("emailVerificationPlainTextIgnore")}
