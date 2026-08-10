from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from siu_guarani_mcp.client import (
    extract_pagelets,
    parse_activity_tables,
    parse_alumnos_asistencia_page,
    parse_detalle_acta_cursada,
    parse_detalle_cursada,
    parse_detalle_mesa,
    parse_notas_cursada_page,
    parse_plain_tables,
    parse_reporte_actas,
)
from siu_guarani_mcp.dates import parse_date_input
from siu_guarani_mcp.export import merge_alumnos_notas


FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def page_from_fixture(name: str, operation: str) -> dict:
    html = load_fixture(name)
    pagelets = extract_pagelets(html)
    content = "\n".join(p.get("content", "") for p in pagelets if p.get("content"))
    return {
        "operation": operation,
        "url": f"https://example.test/{operation}",
        "title": f"fixture {operation}",
        "pagelets": pagelets,
        "content_html": content,
        "all_content_html": content,
        "content_text": content,
    }


class TestDateParsing:
    def test_none_and_empty(self):
        assert parse_date_input(None) is None
        assert parse_date_input("") is None
        assert parse_date_input("   ") is None

    def test_dd_mm_yyyy(self):
        assert parse_date_input("21/07/2026") == "21/07/2026"
        assert parse_date_input("04-08-2026") == "04/08/2026"

    def test_iso_date(self):
        assert parse_date_input("2026-07-21") == "21/07/2026"
        assert parse_date_input("2026-08-04") == "04/08/2026"

    def test_iso_datetime(self):
        assert parse_date_input("2026-07-21T18:00:00") == "21/07/2026"
        assert parse_date_input("2026-07-21T18:00:00Z") == "21/07/2026"
        assert parse_date_input("2026-07-21T18:00:00-03:00") == "21/07/2026"

    def test_date_objects(self):
        assert parse_date_input(date(2026, 7, 21)) == "21/07/2026"
        assert parse_date_input(datetime(2026, 8, 4, 18, 0, 0)) == "04/08/2026"

    def test_invalid(self):
        with pytest.raises(ValueError, match="fecha inválida"):
            parse_date_input("not-a-date")


class TestPageletExtractionQuality:
    def test_extracts_pagelets_from_kernel_on_arrival(self):
        html = load_fixture("zona_clases_pagelets.html")
        pagelets = extract_pagelets(html)
        assert len(pagelets) == 1
        assert pagelets[0]["op"] == "zona_clases"
        assert "content" in pagelets[0]
        assert "Materia Demo (DM01)" in pagelets[0]["content"]

    def test_rejects_broken_json_silently(self):
        html = "kernel.renderer.on_arrival({not valid json});</script>"
        assert extract_pagelets(html) == []


class TestActivityTableParsing:
    def test_cursadas_table_shape(self):
        page = page_from_fixture("zona_clases_pagelets.html", "zona_clases")
        rows = parse_activity_tables(page["content_html"], context_kind="periodo")
        assert len(rows) == 1
        row = rows[0]
        assert row["periodo_lectivo"] == "2026 - 1º Cuatrimestre 2026"
        assert row["actividad"] == "Materia Demo (DM01)"
        assert row["comision"] == "Comision Demo"
        assert row["inscripciones"] == "2"
        assert row["url"].endswith("/zona_clases/home/hash1")

    def test_mesas_table_shape(self):
        page = page_from_fixture("zona_examenes_pagelets.html", "zona_examenes")
        rows = parse_activity_tables(page["content_html"], context_kind="general")
        assert len(rows) == 2
        assert rows[0]["mesa"] == "Mesa Demo 1"
        assert rows[0]["fecha_del_examen"] == "21/07/2026 18:00"
        assert rows[1]["mesa"] == "Mesa Demo 2"
        assert rows[1]["fecha_del_examen"] == "04/08/2026 18:00"
        assert all(r["ubicacion"] == "Sede Demo" for r in rows)
        assert all(r["lugar"] == "-" for r in rows)


class TestAlumnosAndNotasParsers:
    def test_alumnos_asistencia_parser(self):
        page = page_from_fixture("asistencias_pagelets.html", "asistencias")
        rows = parse_alumnos_asistencia_page(page)
        assert len(rows) == 2
        assert rows[0]["nombre"] == "Alumno Uno, Demo"
        assert rows[0]["legajo"] == "Z-0001/1"
        assert rows[0]["alumno_hash"] == "aaa111"
        assert rows[0]["presente"] is False
        assert rows[1]["presente"] is True

    def test_notas_cursada_parser(self):
        page = page_from_fixture("notas_cursada_pagelets.html", "cursada")
        rows = parse_notas_cursada_page(page, page_number=1)
        assert len(rows) == 2
        assert rows[0]["acta"] == "Promoción ( DEMO-PN-0001 )"
        assert rows[0]["nota_promocion"] == "8"
        assert rows[0]["resultado_promocion_label"] == "Promocionado"
        assert rows[1]["resultado_promocion_label"] == "Ausente"
        assert rows[1]["nota_promocion"] == ""

    def test_merge_alumnos_notas_by_name(self):
        alumnos = [
            {"nombre": "Alumna Dos, Demo", "legajo": "Z-2", "alumno_hash": "b", "presente": False},
            {"nombre": "Alumno Uno, Demo", "legajo": "Z-1", "alumno_hash": "a", "presente": True},
        ]
        notas = [
            {
                "nombre": "Alumno Uno, Demo",
                "identificacion": "DNI 20000001",
                "acta": "Promoción ( DEMO-PN-0001 )",
                "fecha_promocion": "03/07/2026",
                "nota_promocion": "8",
                "resultado_promocion_label": "Promocionado",
                "observacion_promocion": "",
                "renglon_id": "1",
            }
        ]
        merged = merge_alumnos_notas(alumnos, notas)
        assert len(merged) == 2
        assert merged[0]["Nombre"] == "Alumna Dos, Demo"
        assert merged[0]["Tiene nota cargada"] == "No"
        assert merged[1]["Nombre"] == "Alumno Uno, Demo"
        assert merged[1]["Tiene nota cargada"] == "Sí"
        assert merged[1]["Nota promoción"] == "8"


class TestActasParsers:
    def test_reporte_actas_cursada_and_examen(self):
        page = page_from_fixture("reporte_actas_pagelets.html", "reporte_actas")
        rows = parse_reporte_actas(page["content_html"])
        assert len(rows) == 2
        by_acta = {r["acta"]: r for r in rows}
        cursada = by_acta["90001"]
        assert cursada["tipo"] == "cursada"
        assert cursada["actividad"] == "Materia Demo (DM01)"
        assert cursada["url_acta"] == "hashacta"
        examen = by_acta["DEMO-EN-0001"]
        assert examen["tipo"] == "examen"
        assert examen["mesa"] == "Mesa Demo 1"
        assert examen["fecha"] == "21/07/2026"

    def test_detalle_acta_renglones(self):
        page = page_from_fixture("detalle_acta_pagelets.html", "reporte_actas")
        rows = parse_detalle_acta_cursada(page["content_html"])
        assert len(rows) == 2
        assert rows[0]["folio"] == "1"
        assert rows[0]["legajo"] == "Z-0001/1"
        assert rows[0]["nota"] == "9 (Nueve)"
        assert rows[0]["resultado"] == "Aprobado"
        assert rows[1]["resultado"] == "Ausente"


class TestNuevosDetalles:
    def test_detalle_cursada_por_categoria(self):
        page = page_from_fixture("zona_clases_home_pagelets.html", "zona_clases")
        detail = parse_detalle_cursada(page["content_html"])
        cats = {c["categoria"]: c["items"] for c in detail["categorias"]}
        assert "Clases dictadas" in cats
        assert "Clases sin dictar" in cats
        assert "Clases anuladas" in cats
        assert len(cats["Clases dictadas"]) == 1
        assert cats["Clases dictadas"][0]["fecha"] == "03/03/2026"
        assert cats["Clases dictadas"][0]["dia"] == "Martes"
        assert len(cats["Clases sin dictar"]) == 1
        assert "No hay registros disponibles" in cats["Clases anuladas"][0]

    def test_detalle_mesa_metadatos(self):
        page = page_from_fixture("zona_examenes_home_pagelets.html", "zona_examenes")
        detail = parse_detalle_mesa(page["content_html"])
        assert detail["actividad"] == "Materia Demo (DM01)"
        assert detail["mesa"] == "Mesa Demo 2"
        assert detail["turno"] == "DEMO 2026"
        assert detail["fecha_del_examen"] == "04/08/2026 18:00"
        assert detail["ubicacion"] == "Sede Demo"
        assert detail["lugar"] == "-"

    def test_inscriptos_examen_plain_table_con_headers_td(self):
        page = page_from_fixture("inscriptos_examen_pagelets.html", "inscriptos_examen")
        rows = parse_plain_tables(page["content_html"])
        assert len(rows) == 2
        assert rows[0]["legajo"] == "Z-0001/1"
        assert rows[0]["alumno"] == "Alumno Uno, Demo"
        assert rows[0]["email"].startswith("Email Principal:")
        assert rows[1]["telefono"].startswith("Telefono Celular:")
        # PII keys present in raw parse
        assert "email" in rows[0]
        assert "telefono" in rows[0]


class TestSourceQualityContracts:
    """Contracts that protect against SIU HTML regressions using synthetic fixtures only."""

    def test_required_fields_cursadas(self):
        page = page_from_fixture("zona_clases_pagelets.html", "zona_clases")
        rows = parse_activity_tables(page["content_html"], context_kind="periodo")
        required = {"periodo_lectivo", "actividad", "comision", "inscripciones", "url"}
        assert required.issubset(rows[0].keys())

    def test_required_fields_mesas(self):
        page = page_from_fixture("zona_examenes_pagelets.html", "zona_examenes")
        rows = parse_activity_tables(page["content_html"], context_kind="general")
        required = {
            "actividad",
            "fecha_del_examen",
            "mesa",
            "turno_de_examen",
            "llamado",
            "ubicacion",
            "lugar",
            "url",
        }
        assert required.issubset(rows[0].keys())

    def test_required_fields_notas(self):
        page = page_from_fixture("notas_cursada_pagelets.html", "cursada")
        rows = parse_notas_cursada_page(page)
        required = {
            "renglon_id",
            "nombre",
            "identificacion",
            "acta",
            "fecha_promocion",
            "nota_promocion",
            "resultado_promocion_label",
        }
        assert required.issubset(rows[0].keys())

    def test_acta_promo_code_present(self):
        page = page_from_fixture("notas_cursada_pagelets.html", "cursada")
        rows = parse_notas_cursada_page(page)
        assert any("DEMO-PN-0001" in r["acta"] for r in rows)

    def test_mesa_names_present(self):
        page = page_from_fixture("zona_examenes_pagelets.html", "zona_examenes")
        rows = parse_activity_tables(page["content_html"], context_kind="general")
        names = {r["mesa"] for r in rows}
        assert "Mesa Demo 1" in names
        assert "Mesa Demo 2" in names

    def test_fixtures_have_no_real_looking_student_pii(self):
        banned = [
            "Alva,",
            "Perez, Ana",
            "Aguirre,",
            "Alomar,",
            "Juarez,",
            "43580504",
            "39567704",
            "A-4671",
            "A-4516",
            "A-4520",
            "7126PN00393",
            "7126EN01394",
            "7126EN01665",
            "Facultad de Ciencias Exactas",
        ]
        for path in FIXTURES.glob("*.html"):
            text = path.read_text(encoding="utf-8")
            for token in banned:
                assert token not in text, f"PII/real token {token!r} found in {path.name}"
