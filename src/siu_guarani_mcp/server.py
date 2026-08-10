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


@mcp.tool(description="Lista mesas de examen operables del docente desde zona_examenes.")
def mesas_examen_docente() -> list[dict[str, Any]]:
    return GuaraniClient().mesas_examen()


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


def main() -> None:
    mcp.run("stdio")
