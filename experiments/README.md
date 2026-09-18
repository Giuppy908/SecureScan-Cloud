# SecureScan Experiments

Questa directory contiene la suite sperimentale usata per misurare il comportamento HA del progetto e gli output già prodotti durante le esecuzioni locali.

## Contenuto

- `scenarios/`: definizione dichiarativa degli scenari benchmark
- `scripts/run_experiments.py`: runner della suite
- `results/`: risultati già generati, da preservare come evidenza

## Scenari disponibili

- `baseline_two_replicas`
- `single_replica`
- `failover_during_load`
- `recovery_after_restart`

## Cosa misura

La suite misura principalmente:

- distribuzione del traffico tra `analysis-api-1` e `analysis-api-2`
- throughput
- latenze
- error rate
- tempi di failover
- tempi di recovery

## Cosa non fa

Non sostituisce:

- i test funzionali del backend;
- i test della GUI;
- i controlli RBAC;
- la validazione del deployment pubblico.

## Output presenti

Sotto `results/` sono già presenti output reali di benchmark:

- JSON scenario-by-scenario
- CSV riepilogativi
- log
- grafici SVG

Questi file non vanno trattati come sorgente: sono artefatti di esecuzione.

## Approfondimento

Per metodologia e risultati verificati: [../docs/experiments.md](../docs/experiments.md)
