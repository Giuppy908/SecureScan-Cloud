"""Health check minimali usati dall'infrastruttura.

Questo file non corrisponde a una pagina del sito. Serve a Docker, Kong e ai
test di reachability per capire se una replica API è viva e raggiungibile.
È quindi un pezzo fondamentale del comportamento HA, anche se invisibile
all'utente finale.
"""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.db.session import is_database_reachable

router = APIRouter(tags=["health"])


@router.get("/health")
def get_health() -> JSONResponse:
    """Restituisce uno stato sintetico della replica API corrente.

    È volutamente separato dalla logica di business: deve continuare a
    rispondere in modo veloce e affidabile perché Kong lo interroga spesso
    per distribuire traffico e reagire rapidamente ai fault.
    """
    payload = {
        "service": "analysis-api",
        "version": settings.app_version,
        "instance_id": settings.instance_id,
    }
    if not is_database_reachable():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "database": "unreachable",
                **payload,
            },
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "healthy",
            "database": "reachable",
            **payload,
        },
    )
