"""Astrazioni e implementazioni di persistenza della Analysis API.

Un repository è lo strato che nasconde il modo concreto in cui i dati vengono
letti o scritti. Gli endpoint non interrogano direttamente PostgreSQL: chiamano
questi repository, che si occupano di costruire ed eseguire le query.
"""
