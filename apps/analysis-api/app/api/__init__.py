"""Router HTTP della Analysis API.

Questo package contiene gli endpoint chiamati dal frontend di SecureScan Cloud.
Da qui passano le richieste provenienti da Dashboard, Nuova analisi,
Cronologia, Dettaglio analisi, Profilo, Stato del sistema e Amministrazione.

Ogni file raggruppa endpoint di una stessa area funzionale. La logica più
complessa non viene però tenuta direttamente nei router: i router validano
input e permessi, poi delegano il lavoro a servizi e repository.
"""
