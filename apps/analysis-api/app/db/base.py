"""Base dichiarativa comune ai modelli SQLAlchemy.

In termini semplici: i modelli ORM descrivono come i dati sono salvati in
PostgreSQL. Questa classe è il punto comune da cui partono tutti quei modelli.
"""

# `DeclarativeBase` è la classe di SQLAlchemy che permette di definire modelli ORM tramite normali classi Python e di raccoglierne la struttura in una metadata comune
from sqlalchemy.orm import DeclarativeBase


# Classe base comune da cui ereditano tutti i modelli ORM dell'applicazione, così SQLAlchemy può riconoscerli e registrarne tabelle, colonne, indici e vincoli nella stessa metadata
class Base(DeclarativeBase):
    """Classe radice dei modelli ORM persistiti nel database applicativo."""
