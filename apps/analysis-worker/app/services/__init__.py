"""Servizi applicativi del worker.

Qui si trova la logica vera della pipeline: lettura file, analisi strutturale,
ClamAV, YARA, aggregazione verdict, polling dei job e metriche Prometheus.
"""
