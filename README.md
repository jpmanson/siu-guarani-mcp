# siu-guarani-mcp

CLI y servidor MCP para consultar SIU Guaraní Autogestión desde el perfil Docente.

El proyecto está pensado para automatizar consultas docentes de Guaraní sin depender de una instalación institucional específica. Por defecto apunta a Autogestión UNR, pero puede usarse con otras instalaciones configurando `GUARANI_BASE_URL`.

> Proyecto no oficial. No está afiliado, avalado ni mantenido por SIU, UNR ni ninguna universidad. Usalo respetando las políticas de tu institución y las credenciales de una cuenta propia.

## Estado

Funcional para consultas read-only probadas sobre el perfil Docente:

- períodos lectivos visibles en `zona_clases`
- cursadas/comisiones del docente desde `zona_clases`
- mesas de examen desde `zona_examenes`
- agenda de exámenes desde `agenda_examenes`
- exploración estructural de páginas detalle, como `zona_clases/home/<hash>` y `zona_examenes/home/<hash>`

También expone herramientas MCP por stdio y puede empaquetarse como Agent Plugin v1.0.0.

## Requisitos

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Credenciales válidas de SIU Guaraní con perfil `Docente`

## Instalación local

```bash
git clone https://github.com/jpmanson/siu-guarani-mcp.git
cd siu-guarani-mcp
uv sync
```

Si todavía no está publicado en GitHub, clonar desde tu copia local o inicializar el repo normalmente.

## Configuración

Copiá el ejemplo y completá tus credenciales:

```bash
cp .env.example .env
```

```env
GUARANI_BASE_URL="https://autogestion-guarani.unr.edu.ar/"
GUARANI_USER="tu_usuario"
GUARANI_PASSWORD="tu_password"
```

Variables:

| Variable | Requerida | Descripción |
| --- | --- | --- |
| `GUARANI_BASE_URL` | No | URL base de la instalación Guaraní. Si se omite, usa `https://autogestion-guarani.unr.edu.ar/`. |
| `GUARANI_USER` | Sí | Usuario de SIU Guaraní. |
| `GUARANI_PASSWORD` | Sí | Contraseña de SIU Guaraní. |

`GUARANI_BASE_URL` se normaliza con `/` final. El `.env` está ignorado por git.

## Uso CLI

Validar login y perfil docente:

```bash
uv run siu-guarani-mcp login-check --json
```

Listar períodos lectivos:

```bash
uv run siu-guarani-mcp periodos --json
```

Listar cursadas/comisiones del docente:

```bash
uv run siu-guarani-mcp cursadas --json
```

Listar mesas de examen operables:

```bash
uv run siu-guarani-mcp mesas --json
```

Listar agenda de exámenes:

```bash
uv run siu-guarani-mcp agenda-examenes --json
```

Explorar una operación docente arbitraria:

```bash
uv run siu-guarani-mcp raw inscriptos_cursadas --text
uv run siu-guarani-mcp raw inscriptos_examenes --json
```

Resumir una página detalle del portal:

```bash
uv run siu-guarani-mcp detalle-url "https://autogestion-guarani.unr.edu.ar/zona_clases/home/<hash>" --json
uv run siu-guarani-mcp detalle-url "https://autogestion-guarani.unr.edu.ar/zona_examenes/home/<hash>" --json
```

`detalle-url` devuelve una síntesis read-only con:

- pagelets detectados
- texto limpio
- tablas y filas de muestra
- formularios detectados
- links internos descubiertos

## Servidor MCP

Levantar el servidor MCP por stdio:

```bash
uv run siu-guarani-mcp serve
```

Config manual para clientes MCP/Hermes:

```yaml
mcp_servers:
  siu_guarani:
    command: "uv"
    args:
      - "--directory"
      - "/ruta/absoluta/a/siu-guarani-mcp"
      - "run"
      - "siu-guarani-mcp"
      - "serve"
    timeout: 120
    connect_timeout: 60
```

Herramientas MCP expuestas:

| Tool | Descripción |
| --- | --- |
| `login_check` | Valida login y cambio al perfil Docente. |
| `periodos_lectivos` | Lista períodos visibles en `zona_clases`. |
| `cursadas_docente` | Lista cursadas/comisiones del docente. |
| `mesas_examen_docente` | Lista mesas de examen operables. |
| `agenda_examenes_docente` | Lista agenda de exámenes docente. |
| `operacion_docente(operation)` | Trae una operación arbitraria del perfil Docente. |
| `detalle_url_docente(url)` | Resume una URL detalle del portal configurado. |

## Agent Plugins v1.0.0

El repositorio incluye manifiestos compatibles con la especificación Agent Plugins v1.0.0:

- `plugin.json`
- `mcp.json`

`mcp.json` declara un servidor stdio llamado `siu-guarani`:

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
  "mcpServers": {
    "siu-guarani": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "siu-guarani-mcp", "serve"],
      "cwd": "${PLUGIN_ROOT}"
    }
  }
}
```

La configuración portable no embebe credenciales ni URLs institucionales. El proceso toma `GUARANI_BASE_URL`, `GUARANI_USER` y `GUARANI_PASSWORD` desde el entorno o desde `.env` en el working directory del plugin.

## Modelo de scraping

Guaraní Autogestión renderiza contenido en pagelets JavaScript del tipo:

```js
kernel.renderer.on_arrival({...})
```

El cliente:

1. inicia sesión con `acceso?auth=form`
2. cambia al perfil `Docente`
3. descarga operaciones del portal
4. extrae pagelets `kernel.renderer.on_arrival(...)`
5. parsea tablas, links y formularios con BeautifulSoup

No usa Selenium ni navegador.

## Alcance descubierto

### Cursadas

`zona_clases/home/<hash>` expone:

- detalle de comisión
- clases dictadas / sin dictar / anuladas
- links internos a:
  - `temas_dictados/<hash>`
  - `asistencias/<hash>`
  - `asistencias_planilla/<hash>`

### Exámenes

`zona_examenes/home/<hash>` expone:

- detalle de mesa
- docentes, fecha, turno, llamado, ubicación e instancias
- links internos a:
  - `notas_mesa_examen/edicion/<hash>`
  - `inscriptos_examen/info/<hash>`
  - `actas_examen/<hash>`

Las operaciones de carga de asistencia, temas o notas contienen formularios POST. Este proyecto por ahora solo las inspecciona en modo read-only; no envía modificaciones.

## Seguridad y privacidad

- No commitear `.env` ni credenciales.
- Las salidas pueden contener datos personales de estudiantes según la operación consultada.
- Evitar publicar logs, JSON completos o capturas con información personal.
- No usar contra cuentas ajenas ni para eludir controles institucionales.
- Las herramientas implementadas son de consulta; cualquier operación POST de escritura debería agregarse explícitamente, con confirmaciones y validaciones fuertes.

## Desarrollo

Ejecutar chequeos básicos:

```bash
uv run python -m compileall -q src
uv run siu-guarani-mcp login-check --json
uv run siu-guarani-mcp periodos --json
```

Validar manifiestos JSON:

```bash
uv run python -m json.tool plugin.json >/dev/null
uv run python -m json.tool mcp.json >/dev/null
```

## Roadmap

- `detalle_cursada(url)` con parseo específico de clases.
- `detalle_mesa(url)` con parseo específico de mesa.
- `inscriptos_mesa(url)` con salida minimizada para PII.
- Exportadores CSV/JSON limpios.
- Tests con fixtures HTML anonimizados.
- Mejor soporte para variaciones entre instalaciones Guaraní.

## Licencia

MIT. Ver `LICENSE`.
