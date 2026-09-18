"""Base dichiarativa SQLAlchemy del worker.

In termini semplici: i modelli ORM descrivono come i dati vengono salvati in
PostgreSQL. Questa classe è il punto comune da cui quei modelli ereditano.
"""

# Importa la classe SQLAlchemy usata come fondamento per definire modelli ORM dichiarativi
from sqlalchemy.orm import DeclarativeBase


# Definisce la base ORM comune da cui ereditano i modelli che rappresentano le tabelle usate dal worker
class Base(DeclarativeBase):

    """Classe base dei modelli ORM usati dal worker."""
