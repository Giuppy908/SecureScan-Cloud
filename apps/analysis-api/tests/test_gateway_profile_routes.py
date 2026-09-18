"""Test statico delle route profilo esposte da Kong.

Protegge il collegamento tra frontend e backend per Profilo e Modifica profilo
senza richiedere uno stack Kong realmente avviato durante i test Python.
"""

from __future__ import annotations

from pathlib import Path


def test_kong_template_exposes_profile_routes_with_required_methods() -> None:
    template_path = Path(__file__).resolve().parents[3] / "infrastructure" / "kong" / "kong.template.yaml"
    template = template_path.read_text(encoding="utf-8")

    assert "name: analysis-api-me-read-route" in template
    assert "name: analysis-api-me-post-route" in template
    assert "name: analysis-api-me-put-route" in template
    assert "name: analysis-api-me-delete-route" in template
    assert "name: analysis-api-me-options-route" in template
    assert "- /api/v1/me" in template
    assert "__KONG_RATE_LIMIT_ME_GET_PER_MINUTE__" in template
    assert "__KONG_RATE_LIMIT_ME_WRITE_PER_MINUTE__" in template
