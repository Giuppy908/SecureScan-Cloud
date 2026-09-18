// Regole di test/demo usate per verificare che YARA venga realmente invocato
// nella pipeline del worker senza dover versionare malware reale nel repository.

rule securescan_test_marker
{
    // Questa regola produce un match innocuo di tipo "test".
    // Serve a dimostrare il funzionamento del motore YARA senza rendere il
    // verdetto finale "malicious".
    meta:
        description = "Marker innocuo per validare l'invocazione reale di YARA"
        severity = "test"
        category = "validation"
        author = "SecureScan Cloud"
        reference = "local-test-marker"
    strings:
        $marker = "SECURESCAN_YARA_TEST_MARKER" ascii wide
    condition:
        $marker
}

rule securescan_suspicious_marker
{
    // Questa regola permette di simulare un caso "suspicious" controllato.
    // Il file non contiene malware reale, ma la pipeline può verificare che
    // Cronologia e Dettaglio analisi mostrino correttamente un esito sospetto.
    meta:
        description = "Marker controllato per testare un verdetto sospetto senza usare malware reale"
        severity = "suspicious"
        category = "validation"
        author = "SecureScan Cloud"
        reference = "local-suspicious-marker"
    strings:
        $marker = "SECURESCAN_YARA_SUSPICIOUS_MARKER" ascii wide
    condition:
        $marker
}

rule securescan_malicious_marker
{
    // Questa regola demo forza un comportamento equivalente a un match
    // malevolo YARA senza salvare nel repository un campione dannoso reale.
    meta:
        description = "Marker controllato per testare un verdetto malevolo senza versionare malware"
        severity = "malicious"
        category = "validation"
        author = "SecureScan Cloud"
        reference = "local-malicious-marker"
    strings:
        $marker = "SECURESCAN_YARA_MALICIOUS_MARKER" ascii wide
    condition:
        $marker
}
