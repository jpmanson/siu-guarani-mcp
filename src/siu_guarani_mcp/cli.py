from __future__ import annotations

import json
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .client import GuaraniClient

app = typer.Typer(help="CLI para SIU Guaraní Autogestión - perfil docente")
console = Console()


def emit(data, json_output: bool) -> None:
    if json_output:
        # Use plain print: Rich wraps long JSON strings, making stdout invalid JSON.
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    if isinstance(data, list):
        if not data:
            console.print("Sin resultados")
            return
        keys = []
        for row in data:
            for k in row.keys():
                if k not in keys and k != "url":
                    keys.append(k)
        table = Table(show_lines=False)
        for k in keys:
            table.add_column(k)
        for row in data:
            table.add_row(*(str(row.get(k, "")) for k in keys))
        console.print(table)
    else:
        console.print(data)


@app.callback()
def callback() -> None:
    pass


@app.command("login-check")
def login_check(json_output: bool = typer.Option(False, "--json", help="Emitir JSON")) -> None:
    """Valida credenciales del .env y acceso al perfil Docente."""
    client = GuaraniClient()
    emit(client.login(), json_output)


@app.command("periodos")
def periodos(json_output: bool = typer.Option(False, "--json", help="Emitir JSON")) -> None:
    """Lista períodos lectivos visibles en zona_clases."""
    emit(GuaraniClient().periodos_lectivos(), json_output)


@app.command("cursadas")
def cursadas(json_output: bool = typer.Option(False, "--json", help="Emitir JSON")) -> None:
    """Lista cursadas/comisiones del docente desde zona_clases."""
    emit(GuaraniClient().cursadas(), json_output)


@app.command("mesas")
def mesas(json_output: bool = typer.Option(False, "--json", help="Emitir JSON")) -> None:
    """Lista mesas de examen operables desde zona_examenes."""
    emit(GuaraniClient().mesas_examen(), json_output)


@app.command("agenda-examenes")
def agenda_examenes(json_output: bool = typer.Option(False, "--json", help="Emitir JSON")) -> None:
    """Lista agenda de exámenes docente."""
    emit(GuaraniClient().agenda_examenes(), json_output)


@app.command("raw")
def raw(operation: str, json_output: bool = typer.Option(True, "--json/--text", help="JSON o texto limpio")) -> None:
    """Trae una operación arbitraria del perfil docente (ej: inscriptos_cursadas)."""
    page = GuaraniClient().get_operation(operation)
    emit(page if json_output else page["content_text"], json_output)


@app.command("detalle-url")
def detalle_url(url: str, json_output: bool = typer.Option(True, "--json/--text", help="JSON o texto limpio")) -> None:
    """Resume una URL detalle del portal, por ejemplo zona_clases/home/<hash>."""
    detail = GuaraniClient().detalle_url(url)
    emit(detail if json_output else detail["text"], json_output)


@app.command("alumnos-cursada")
def alumnos_cursada(url: str, json_output: bool = typer.Option(True, "--json", help="Emitir JSON")) -> None:
    """Lista alumnos de una cursada desde zona_clases/home/<hash> o asistencias/<hash>."""
    emit(GuaraniClient().alumnos_cursada(url), json_output)


@app.command("notas-cursada")
def notas_cursada(url: str, json_output: bool = typer.Option(True, "--json", help="Emitir JSON")) -> None:
    """Lista notas cargadas desde zona_comisiones/home/<hash> o cursada/edicion/<hash>."""
    emit(GuaraniClient().notas_cursada(url), json_output)


@app.command("export-cursada")
def export_cursada(
    zona_clases_url: str,
    zona_comisiones_url: str,
    output_dir: str = typer.Option("export", "--output-dir", "-o", help="Directorio de salida"),
    basename: str = typer.Option("estudiantes_notas_cursada", "--basename", help="Nombre base de archivos"),
) -> None:
    """Exporta alumnos + notas de una cursada a CSV, XLSX y JSON."""
    from .export import export_cursada_con_notas

    emit(export_cursada_con_notas(zona_clases_url, zona_comisiones_url, output_dir, basename), True)


@app.command("serve")
def serve() -> None:
    """Levanta el servidor MCP por stdio."""
    from .server import mcp

    mcp.run("stdio")


def main() -> None:
    app()
