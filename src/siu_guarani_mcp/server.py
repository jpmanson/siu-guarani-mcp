from __future__ import annotations

from typing import Any

from mcp.server.mcpserver.server import MCPServer

from .client import GuaraniClient

mcp = MCPServer(
    name="siu-guarani",
    title="SIU Guaraní Docente",
    description="Herramientas MCP para consultar SIU Guaraní Autogestión con perfil Docente.",
    version="0.1.0",
)


@mcp.tool(description="Valida login y cambio al perfil Docente de SIU Guaraní UNR.")
def login_check() -> dict[str, Any]:
    return GuaraniClient().login()


@mcp.tool(description="Lista períodos lectivos visibles en zona_clases para el docente autenticado.")
def periodos_lectivos() -> list[dict[str, str]]:
    return GuaraniClient().periodos_lectivos()


@mcp.tool(description="Lista cursadas/comisiones del docente desde zona_clases.")
def cursadas_docente() -> list[dict[str, Any]]:
    return GuaraniClient().cursadas()


@mcp.tool(description="Lista mesas de examen operables del docente desde zona_examenes. Por defecto usa un rango amplio de fechas (-90/+180 días). Opcionalmente acepta desde/hasta en dd/mm/aaaa.")
def mesas_examen_docente(desde: str | None = None, hasta: str | None = None) -> list[dict[str, Any]]:
    return GuaraniClient().mesas_examen(desde=desde, hasta=hasta)


@mcp.tool(description="Lista agenda de exámenes del docente desde agenda_examenes.")
def agenda_examenes_docente() -> list[dict[str, Any]]:
    return GuaraniClient().agenda_examenes()


@mcp.tool(description="Trae y parsea una operación arbitraria del perfil Docente. Ej: inscriptos_cursadas, inscriptos_examenes, reporte_actas.")
def operacion_docente(operation: str) -> dict[str, Any]:
    page = GuaraniClient().get_operation(operation)
    # No devolvemos todo pagelets para no inflar el contexto MCP; HTML + texto bastan para exploración.
    return {
        "operation": page["operation"],
        "url": page["url"],
        "title": page["title"],
        "content_text": page["content_text"],
        "content_html": page["content_html"],
    }


@mcp.tool(description="Resume una URL detalle del portal Guaraní Docente, por ejemplo zona_clases/home/<hash> o zona_examenes/home/<hash>. Solo acepta URLs del portal configurado.")
def detalle_url_docente(url: str) -> dict[str, Any]:
    return GuaraniClient().detalle_url(url)


@mcp.tool(description="Lista alumnos de una cursada desde una URL zona_clases/home/<hash> o asistencias/<hash>. Devuelve nombre, legajo, hash interno y presente para la clase mostrada.")
def alumnos_cursada_docente(url: str) -> list[dict[str, Any]]:
    return GuaraniClient().alumnos_cursada(url)


@mcp.tool(description="Lista notas cargadas de una cursada desde zona_comisiones/home/<hash> o cursada/edicion/<hash>.")
def notas_cursada_docente(url: str) -> list[dict[str, Any]]:
    return GuaraniClient().notas_cursada(url)


@mcp.tool(description="Exporta alumnos + notas de una cursada a CSV, XLSX y JSON. Requiere URL zona_clases/home/<hash> y zona_comisiones/home/<hash>.")
def exportar_cursada_docente(zona_clases_url: str, zona_comisiones_url: str, output_dir: str = "export", basename: str = "estudiantes_notas_cursada") -> dict[str, Any]:
    from .export import export_cursada_con_notas

    return export_cursada_con_notas(zona_clases_url, zona_comisiones_url, output_dir, basename)


@mcp.tool(description="Busca un acta de cursada por número dentro de Reporte de Actas.")
def buscar_acta_cursada_docente(numero_acta: str) -> dict[str, Any] | None:
    return GuaraniClient().buscar_acta_cursada(numero_acta)


@mcp.tool(description="Busca un acta de cursada por número y devuelve sus renglones de detalle.")
def detalle_acta_cursada_docente(numero_acta: str) -> dict[str, Any] | None:
    return GuaraniClient().detalle_acta_cursada(numero_acta)


@mcp.tool(description="Resuelve los enlaces operativos de una cursada a partir de una SOLA URL (zona_clases/home/<hash> o zona_comisiones/home/<hash>). Devuelve URLs a Cargar Notas, Alumnos, Evaluaciones, Actas y Asistencia.")
def resolver_cursada_docente(url: str) -> dict[str, Any]:
    return GuaraniClient().resolver_cursada(url)


@mcp.tool(description="Lista inscriptos de una comisión a partir de una SOLA URL (zona_comisiones/home/<hash> o inscriptos_cursadas/info_comision/<hash>).")
def inscriptos_cursada_docente(url: str) -> list[dict[str, Any]]:
    return GuaraniClient().inscriptos_cursada(url)


def main() -> None:
    mcp.run("stdio")
