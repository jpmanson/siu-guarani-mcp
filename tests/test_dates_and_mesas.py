from __future__ import annotations

from siu_guarani_mcp.client import Credentials, GuaraniClient, GuaraniError
from siu_guarani_mcp.dates import parse_date_input


def test_mesas_examen_normalizes_iso_before_request(monkeypatch):
    captured = {}

    client = GuaraniClient(
        base_url="https://example.test/",
        credentials=Credentials(user="u", password="p"),
    )
    client._logged_in = True

    def fake_get_operation(operation, *, method="get", data=None):
        captured["operation"] = operation
        captured["method"] = method
        captured["data"] = data
        return {
            "operation": operation,
            "url": f"https://example.test/{operation}",
            "title": "t",
            "pagelets": [],
            "content_html": "",
            "all_content_html": "",
            "content_text": "",
        }

    monkeypatch.setattr(client, "get_operation", fake_get_operation)
    rows = client.mesas_examen(desde="2026-07-15", hasta="2026-08-10T23:59:59Z")
    assert rows == []
    assert captured["operation"] == "zona_examenes"
    assert captured["method"] == "post"
    assert captured["data"]["desde"] == "15/07/2026"
    assert captured["data"]["hasta"] == "10/08/2026"
    assert captured["data"]["filtrar_por"] == "r"


def test_mesas_examen_rejects_invalid_date():
    client = GuaraniClient(
        base_url="https://example.test/",
        credentials=Credentials(user="u", password="p"),
    )
    client._logged_in = True
    try:
        client.mesas_examen(desde="nope", hasta="2026-08-01")
        assert False, "expected GuaraniError"
    except GuaraniError as exc:
        assert "desde inválida" in str(exc)


def test_parse_date_roundtrip_helpers():
    assert parse_date_input("2026-07-21") == parse_date_input("21/07/2026")
