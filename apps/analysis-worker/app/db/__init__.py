"""Package database del worker.

Il worker non possiede un database separato: usa lo stesso PostgreSQL già
alimentato dall'Analysis API. Qui si trovano i moduli che descrivono quello
schema e aprono le sessioni necessarie a leggere e aggiornare i job.
"""
