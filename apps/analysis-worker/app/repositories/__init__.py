"""Repository del worker.

Un repository è lo strato che nasconde le query SQL/SQLAlchemy. Il worker non
aggiorna PostgreSQL “a mano” dentro il loop: delega a questi oggetti la presa
in carico dei job, il recovery dei job bloccati e gli heartbeat.
"""
