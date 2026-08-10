from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag


DEFAULT_BASE_URL = "https://autogestion-guarani.unr.edu.ar/"


class GuaraniError(RuntimeError):
    pass


def read_local_env(path: str = ".env") -> dict[str, str]:
    """Minimal .env reader tolerant of informal/comment lines; avoids python-dotenv warnings in CLI JSON mode."""
    values: dict[str, str] = {}
    if not os.path.exists(path):
        return values
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            value = value.strip().strip('"').strip("'")
            values[key] = value
    return values


def env_value(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name) or read_local_env().get(name) or default
    if value is None:
        return None
    return value.strip().strip('"').strip("'")


def configured_base_url(default: str = DEFAULT_BASE_URL) -> str:
    value = env_value("GUARANI_BASE_URL", default) or default
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise GuaraniError(f"GUARANI_BASE_URL inválida: {value!r}")
    return value.rstrip("/") + "/"


@dataclass
class Credentials:
    user: str
    password: str

    @classmethod
    def from_env(cls) -> "Credentials":
        user = env_value("GUARANI_USER")
        password = env_value("GUARANI_PASSWORD")
        if not user or not password:
            raise GuaraniError("Faltan GUARANI_USER/GUARANI_PASSWORD en el entorno o .env")
        return cls(user=user, password=password)


class GuaraniClient:
    def __init__(self, base_url: str | None = None, credentials: Credentials | None = None, timeout: int = 30):
        self.base_url = (base_url.rstrip("/") + "/") if base_url else configured_base_url()
        self.credentials = credentials or Credentials.from_env()
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "siu-guarani-mcp/0.1 (+requests)",
            "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
        })
        self._logged_in = False

    def login(self) -> dict[str, Any]:
        self.session.get(self.base_url, timeout=self.timeout)
        login_url = urljoin(self.base_url, "acceso?auth=form")
        response = self.session.post(
            login_url,
            data={"usuario": self.credentials.user, "password": self.credentials.password, "login": "Ingresar"},
            timeout=self.timeout,
            allow_redirects=True,
        )
        response.raise_for_status()
        if "error_login" in response.text or "guarani_form_login" in response.text and "inicio_" not in response.url:
            raise GuaraniError("Login falló: el portal devolvió la pantalla de acceso/error_login")
        self._logged_in = True
        self.switch_profile("Docente")
        return {"ok": True, "base_url": self.base_url, "url": response.url, "cookies": sorted(c.name for c in self.session.cookies)}

    def ensure_login(self) -> None:
        if not self._logged_in:
            self.login()

    def switch_profile(self, profile: str = "Docente") -> None:
        response = self.session.get(urljoin(self.base_url, f"acceso/perfil?id={profile}"), timeout=self.timeout, allow_redirects=True)
        response.raise_for_status()
        if profile.lower() == "docente" and "inicio_docente" not in response.url and "zona_clases" not in response.text:
            # Some installs keep same URL but render docente menu. This condition is intentionally conservative.
            if 'data-perfil="Docente"' not in response.text and "zona_clases" not in response.text:
                raise GuaraniError("No pude activar el perfil Docente")

    def get_operation(self, operation: str, *, method: str = "get", data: dict[str, Any] | None = None) -> dict[str, Any]:
        self.ensure_login()
        url = urljoin(self.base_url, operation.lstrip("/"))
        return self.get_url(url, method=method, data=data, operation=operation.strip("/"))

    def get_url(self, url: str, *, method: str = "get", data: dict[str, Any] | None = None, operation: str | None = None) -> dict[str, Any]:
        self.ensure_login()
        self._validate_portal_url(url)
        if method.lower() == "post":
            response = self.session.post(url, data=data or {}, timeout=self.timeout)
        else:
            response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        pagelets = extract_pagelets(response.text)
        op_name = operation or urlparse(response.url).path.strip("/").split("/")[0]
        op_pagelets = [p for p in pagelets if p.get("op") == op_name]
        content = "\n".join(p.get("content", "") for p in (op_pagelets or pagelets) if p.get("content"))
        all_content = "\n".join(p.get("content", "") for p in pagelets if p.get("content"))
        return {
            "operation": op_name,
            "url": response.url,
            "title": extract_title(response.text),
            "pagelets": pagelets,
            "content_html": content,
            "all_content_html": all_content,
            "content_text": html_to_text(content),
        }

    def _validate_portal_url(self, url: str) -> None:
        target = urlparse(urljoin(self.base_url, url))
        base = urlparse(self.base_url)
        if target.scheme not in {"http", "https"} or target.hostname != base.hostname:
            raise GuaraniError(f"URL fuera del portal Guaraní configurado: {url}")

    def periodos_lectivos(self) -> list[dict[str, str]]:
        page = self.get_operation("zona_clases")
        soup = BeautifulSoup(page["content_html"], "html.parser")
        select = soup.find("select", id="periodo_lectivo") or soup.find("select", attrs={"name": "periodo_lectivo"})
        return parse_select_options(select)

    def cursadas(self) -> list[dict[str, Any]]:
        page = self.get_operation("zona_clases")
        return parse_activity_tables(page["content_html"], context_kind="periodo")

    def mesas_examen(self, desde: str | None = None, hasta: str | None = None) -> list[dict[str, Any]]:
        """Lista mesas de examen. Si no se pasan fechas, usa un rango amplio para no depender del default corto de SIU.

        `desde`/`hasta` aceptan dd/mm/aaaa o ISO (yyyy-mm-dd[/T...]).
        """
        from datetime import date, timedelta

        from .dates import parse_date_input

        try:
            desde_norm = parse_date_input(desde, field_name="desde")
            hasta_norm = parse_date_input(hasta, field_name="hasta")
        except ValueError as exc:
            raise GuaraniError(str(exc)) from exc

        today = date.today()
        # Default SIU is roughly ±7 days; widen so recent/upcoming mesas are visible.
        desde_norm = desde_norm or (today - timedelta(days=90)).strftime("%d/%m/%Y")
        hasta_norm = hasta_norm or (today + timedelta(days=180)).strftime("%d/%m/%Y")
        page = self.get_operation(
            "zona_examenes",
            method="post",
            data={
                "filtrar_por": "r",
                "desde": desde_norm,
                "hasta": hasta_norm,
                "fecha": desde_norm,
            },
        )
        rows = parse_activity_tables(page["content_html"], context_kind="general")
        for row in rows:
            row.setdefault("filtro_desde", desde_norm)
            row.setdefault("filtro_hasta", hasta_norm)
        return rows
    def agenda_examenes(self) -> list[dict[str, Any]]:
        page = self.get_operation("agenda_examenes")
        return parse_activity_tables(page["content_html"], context_kind="general")

    def detalle_url(self, url: str) -> dict[str, Any]:
        page = self.get_url(url)
        return summarize_detail_page(page)

    def alumnos_cursada(self, url: str) -> list[dict[str, Any]]:
        """Lista alumnos de una cursada desde zona_clases/home/<hash> o asistencias/<hash>."""
        page = self.get_url(url)
        operation = page["operation"]
        if operation == "zona_clases":
            detail = summarize_detail_page(page)
            asistencia_links = [link for link in detail["links"] if link.get("operation") == "asistencias"]
            if not asistencia_links:
                return []
            # Prefer the zone-level Asistencia link, which appears after per-class action links.
            page = self.get_url(asistencia_links[-1]["href"])
        elif operation != "asistencias":
            raise GuaraniError("alumnos_cursada requiere una URL zona_clases/home/<hash> o asistencias/<hash>")
        return parse_alumnos_asistencia_page(page)

    def notas_cursada(self, url: str) -> list[dict[str, Any]]:
        """Lista notas cargadas desde zona_comisiones/home/<hash> o cursada/edicion/<hash>."""
        page = self.get_url(url)
        edit_url = url
        if page["operation"] == "zona_comisiones":
            detail = summarize_detail_page(page)
            links = [link for link in detail["links"] if link.get("operation") == "cursada" and "Cargar Notas" in link.get("text", "")]
            if not links:
                return []
            edit_url = links[-1]["href"]
        elif page["operation"] != "cursada":
            raise GuaraniError("notas_cursada requiere una URL zona_comisiones/home/<hash> o cursada/edicion/<hash>")
        base = edit_url.rstrip("/")
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for page_number in range(1, 100):
            page_url = f"{base}/{page_number}"
            page_data = self.get_url(page_url)
            parsed = parse_notas_cursada_page(page_data, page_number=page_number)
            new_rows = [row for row in parsed if row.get("renglon_id") not in seen]
            for row in new_rows:
                if row.get("renglon_id"):
                    seen.add(row["renglon_id"])
            rows.extend(new_rows)
            if not parsed or "Siguiente" not in (page_data.get("content_text") or ""):
                break
        return rows

    def actas_cursada(self) -> list[dict[str, Any]]:
        page = self.get_operation("reporte_actas")
        return parse_reporte_actas(page.get("content_html") or "")

    def buscar_acta_cursada(self, numero_acta: str) -> dict[str, Any] | None:
        numero = str(numero_acta).strip()
        for acta in self.actas_cursada():
            if str(acta.get("acta", "")).strip() == numero:
                url_acta = acta.get("url_acta") or ""
                acta["detalle_url"] = urljoin(self.base_url, f"reporte_actas/detalle?url_acta={url_acta}&actividad=&per_lec=&acta={numero}&origen=R")
                return acta
        return None

    def detalle_acta_cursada(self, numero_acta: str) -> dict[str, Any] | None:
        acta = self.buscar_acta_cursada(numero_acta)
        if not acta:
            return None
        page = self.get_url(acta["detalle_url"], operation="reporte_actas")
        detail = summarize_detail_page(page)
        detail["acta"] = acta
        detail["renglones"] = parse_detalle_acta_cursada(page.get("content_html") or page.get("all_content_html") or "")
        return detail

    def resolver_cursada(self, url: str) -> dict[str, Any]:
        """Resuelve los enlaces operativos de una cursada a partir de una sola URL.

        Acepta `zona_clases/home/<hash>` o `zona_comisiones/home/<hash>` y devuelve
        los enlaces a Cargar Notas, Alumnos, Evaluaciones, Actas y Asistencia.
        """
        resolved_pairs = self._resolve_cursada_pairs(url)
        if not resolved_pairs:
            raise GuaraniError("No encontré la cursada. Pasá una URL de zona_clases/home o zona_comisiones/home.")
        zone = resolved_pairs["zona_comisiones_url"] or resolved_pairs["zona_clases_url"]
        page = self.get_url(zone)
        links = extract_links(BeautifulSoup(page.get("all_content_html") or page.get("content_html") or "", "html.parser"))
        enlaces: dict[str, str] = {}
        for text, op, href in [(l.get("text", ""), l.get("operation", ""), l.get("href", "")) for l in links]:
            label = text.strip()
            if not label or not href:
                continue
            if "Cargar Notas" in label and "cursada" not in enlaces:
                enlaces["notas"] = href
            elif label == "Alumnos" and "alumnos" not in enlaces:
                enlaces["alumnos"] = href
            elif label == "Evaluaciones" and "evaluaciones" not in enlaces:
                enlaces["evaluaciones"] = href
            elif label == "Actas" and "actas" not in enlaces:
                enlaces["actas"] = href
            elif label == "Asistencia" and "asistencia" not in enlaces:
                enlaces["asistencia"] = href
        resolved_pairs["enlaces"] = enlaces
        return resolved_pairs

    def _resolve_cursada_pairs(self, url: str) -> dict[str, Any] | None:
        self.ensure_login()
        target = url.rstrip("/")
        clases = self.cursadas()
        comisiones = self.get_operation("zona_comisiones")
        comisiones_rows = parse_activity_tables(comisiones.get("content_html") or "", context_kind="periodo")

        def key(row: dict[str, Any]) -> tuple:
            return (
                row.get("periodo_lectivo"),
                row.get("comision") or row.get("mesa"),
                str(row.get("inscripciones", "")),
            )

        by_url = {}
        for row in list(clases) + list(comisiones_rows):
            u = (row.get("url") or "").rstrip("/")
            if u:
                by_url[u] = row

        start = by_url.get(target)
        if start is None:
            return None
        base = key(start)
        match_clases = next((r for r in clases if key(r) == base and r.get("url")), None)
        match_comisiones = next((r for r in comisiones_rows if key(r) == base and r.get("url")), None)
        return {
            "zona_clases_url": match_clases.get("url") if match_clases else None,
            "zona_comisiones_url": match_comisiones.get("url") if match_comisiones else None,
            "identificacion": {k: start.get(k) for k in ("actividad", "periodo_lectivo", "comision", "inscripciones") if k in start},
        }

    def inscriptos_cursada(self, url: str) -> list[dict[str, Any]]:
        """Lista inscriptos de una comisión desde zona_comisiones/home o inscriptos_cursadas/info_comision."""
        page = self.get_url(url)
        info_url = url
        if page["operation"] == "zona_comisiones":
            detail = summarize_detail_page(page)
            alumnos_links = [link for link in detail["links"] if link.get("operation", "").startswith("inscriptos_cursadas")]
            if not alumnos_links:
                return []
            info_url = alumnos_links[-1]["href"]
        elif not page["operation"].startswith("inscriptos_cursadas"):
            raise GuaraniError("inscriptos_cursada requiere zona_comisiones/home o inscriptos_cursadas/info_comision")
        info_page = self.get_url(info_url)
        return parse_plain_tables(info_page.get("content_html") or info_page.get("all_content_html") or "")

    def detalle_cursada(self, url: str) -> dict[str, Any]:
        """Detalle de una cursada: metadatos + clases agrupadas por categoría."""
        page = self.get_url(url)
        operation = page["operation"]
        if operation != "zona_clases":
            raise GuaraniError("detalle_cursada requiere una URL zona_clases/home/<hash>")
        html = page.get("content_html") or ""
        return parse_detalle_cursada(html)

    def detalle_mesa(self, url: str) -> dict[str, Any]:
        """Detalle de una mesa de examen: metadatos + docentes e instancias."""
        page = self.get_url(url)
        operation = page["operation"]
        if operation != "zona_examenes":
            raise GuaraniError("detalle_mesa requiere una URL zona_examenes/home/<hash>")
        html = page.get("content_html") or ""
        return parse_detalle_mesa(html)

    def inscriptos_examen(self, url: str, *, include_pii: bool = False) -> list[dict[str, Any]]:
        """Lista inscriptos a una mesa de examen.

        `url` puede ser `zona_examenes/home/<hash>` o `inscriptos_examen/info/<hash>`.
        Por defecto NO devuelve email/teléfono (PII). Usa `include_pii=True` para incluirlos.
        """
        page = self.get_url(url)
        info_url = url
        if page["operation"] == "zona_examenes":
            detail = summarize_detail_page(page)
            links = [link for link in detail["links"] if link.get("operation", "").startswith("inscriptos_examen")]
            if not links:
                return []
            info_url = links[-1]["href"]
        elif not page["operation"].startswith("inscriptos_examen"):
            raise GuaraniError("inscriptos_examen requiere zona_examenes/home o inscriptos_examen/info")
        info_page = self.get_url(info_url)
        rows = parse_plain_tables(info_page.get("content_html") or info_page.get("all_content_html") or "")
        if not include_pii:
            for row in rows:
                row.pop("email", None)
                row.pop("telefono", None)
        return rows

    def reporte_actas(self, origen: str = "R", periodo: str | None = None, actividad: str | None = None) -> list[dict[str, Any]]:
        """Lista actas de Reporte de Actas con filtros opcionales período/actividad.

        `origen`: R (cursadas), E (exámenes), P (promociones).
        `periodo`: hash o label del período lectivo. `actividad`: nombre de actividad.
        """
        origin_origen = origen.upper()
        params = {"origen": origin_origen, "actividad": actividad or "", "per_lec": periodo or ""}
        url = urljoin(self.base_url, "reporte_actas/filtrar_actas")
        self.ensure_login()
        response = self.session.post(url, data=params, timeout=self.timeout)
        response.raise_for_status()
        html = response.text
        try:
            payload = response.json()
            html = payload.get("html", html)
        except ValueError:
            pass
        return parse_reporte_actas(html)


def extract_title(html: str) -> str | None:
    m = re.search(r"<title>(.*?)</title>", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else None


def extract_pagelets(html: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    pattern = re.compile(r"kernel\.renderer\.on_arrival\((\{.*?\})\);</script>", re.S)
    for match in pattern.finditer(html):
        raw = match.group(1)
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out


def html_to_text(fragment: str) -> str:
    soup = BeautifulSoup(fragment or "", "html.parser")
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()


def parse_select_options(select: Tag | None) -> list[dict[str, str]]:
    if not select:
        return []
    rows = []
    for opt in select.find_all("option"):
        rows.append({
            "value": opt.get("value", ""),
            "label": opt.get_text(" ", strip=True),
            "selected": "true" if opt.has_attr("selected") else "false",
        })
    return rows


def table_headers(table: Tag) -> list[str]:
    header_rows = table.find_all("tr")
    for tr in header_rows:
        ths = tr.find_all("th")
        labels = [th.get_text(" ", strip=True) for th in ths if not th.has_attr("colspan")]
        if labels:
            return labels
    return []


def activity_name(table: Tag) -> str | None:
    th = table.select_one("th.header-actividad")
    if th:
        return th.get_text(" ", strip=True)
    cc = table.select_one("td.cc-titulo-nivel-0")
    return cc.get_text(" ", strip=True) if cc else None


def enclosing_period(table: Tag) -> str | None:
    parent = table.parent
    while parent and isinstance(parent, Tag):
        legend = parent.find("legend", recursive=False)
        if legend:
            return legend.get_text(" ", strip=True)
        parent = parent.parent
    return None


def parse_activity_tables(fragment: str, context_kind: str = "general") -> list[dict[str, Any]]:
    soup = BeautifulSoup(fragment or "", "html.parser")
    rows: list[dict[str, Any]] = []
    for table in soup.select("table"):
        headers = table_headers(table)
        if not headers:
            continue
        act = activity_name(table)
        period = enclosing_period(table) if context_kind == "periodo" else None
        for tr in table.find_all("tr"):
            cells = tr.find_all("td", recursive=False)
            if not cells:
                continue
            # Skip group-title rows like <td class="cc-titulo-nivel-0" colspan="9">Actividad</td>.
            if len(cells) == 1 and cells[0].has_attr("colspan"):
                continue
            item: dict[str, Any] = {}
            if period:
                item["periodo_lectivo"] = period
            if act:
                item["actividad"] = act
            for idx, header in enumerate(headers):
                if idx >= len(cells):
                    continue
                item[normalize_key(header)] = cells[idx].get_text(" ", strip=True)
            link = tr.get("data-link")
            a = tr.find("a", href=True)
            href = a.get("href") if isinstance(a, Tag) else None
            if link or href:
                item["url"] = link or href
            rows.append(item)
    return rows


def summarize_detail_page(page: dict[str, Any]) -> dict[str, Any]:
    """Return a compact, read-only structural summary of a Guaraní detail page."""
    soup = BeautifulSoup(page.get("all_content_html") or page.get("content_html") or "", "html.parser")
    links = extract_links(soup)
    forms = summarize_forms(soup)
    tables = summarize_tables(soup)
    return {
        "operation": page.get("operation"),
        "url": page.get("url"),
        "title": page.get("title"),
        "pagelets": [
            {
                "op": p.get("op"),
                "id": (p.get("info") or {}).get("id"),
                "content_length": len(p.get("content") or ""),
            }
            for p in page.get("pagelets", [])
        ],
        "text": page.get("content_text"),
        "links": links,
        "forms": forms,
        "tables": tables,
    }


def extract_links(soup: BeautifulSoup) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        href = str(a.get("href") or "")
        key = (text, href)
        if key in seen:
            continue
        seen.add(key)
        links.append({
            "text": text,
            "href": href,
            "operation": urlparse(href).path.strip("/").split("/")[0] if href else "",
        })
    return links


def summarize_forms(soup: BeautifulSoup) -> list[dict[str, Any]]:
    forms: list[dict[str, Any]] = []
    for form in soup.find_all("form"):
        fields = []
        for field in form.find_all(["input", "select", "button", "textarea"]):
            fields.append({
                "tag": field.name,
                "name": field.get("name"),
                "id": field.get("id"),
                "type": field.get("type"),
                "options": [o.get_text(" ", strip=True) for o in field.find_all("option")][:20] if field.name == "select" else None,
            })
        forms.append({
            "method": form.get("method"),
            "action": form.get("action"),
            "field_count": len(fields),
            "fields": fields[:80],
        })
    return forms


def summarize_tables(soup: BeautifulSoup) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    for table in soup.find_all("table"):
        headers = table_headers(table)
        rows = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td", recursive=False)]
            if cells:
                rows.append(cells)
        tables.append({
            "headers": headers,
            "row_count": len(rows),
            "sample_rows": rows[:5],
        })
    return tables


def parse_detalle_cursada(fragment: str) -> dict[str, Any]:
    """Parse zona_clases/home/<hash> content into metadatos + clases por categoría.

    Las categorías se delimitan por `<h4>` (Clases dictadas / sin dictar / anuladas),
    cada una seguida de una tabla de clases o un aviso "No hay registros disponibles".
    """
    soup = BeautifulSoup(fragment or "", "html.parser")
    categories: dict[str, Any] = {}
    order: list[str] = []
    current: str | None = None
    for node in soup.find_all(["h4", "table", "div"]):
        if node.name == "h4":
            current = node.get_text(" ", strip=True).strip()
            if current and current not in categories:
                categories[current] = []
                order.append(current)
            continue
        if node.name == "table" and current is not None:
            headers = table_headers(node)
            for tr in node.find_all("tr"):
                cells = [td.get_text(" ", strip=True) for td in tr.find_all("td", recursive=False)]
                if not cells or set(cells) == set(headers):
                    continue
                row = {}
                for i, header in enumerate(headers):
                    if i < len(cells):
                        row[normalize_key(header)] = cells[i]
                link = tr.get("data-link")
                a = tr.find("a", href=True)
                href = str(a.get("href")) if isinstance(a, Tag) else ""
                if link or href:
                    row["url"] = link or href
                if row:
                    categories[current].append(row)
            continue
        if node.name == "div" and current is not None and "alert" in " ".join(node.get("class") or []):
            categories[current].append(node.get_text(" ", strip=True).strip())
    return {"categorias": [{"categoria": name, "items": categories[name]} for name in order]}


def parse_detalle_mesa(fragment: str) -> dict[str, Any]:
    """Parse zona_examenes/home/<hash> content into mesa metadata.

    Extrae los pares `<p><strong>Etiqueta:</strong> valor</p>` del hero-unit.
    """
    soup = BeautifulSoup(fragment or "", "html.parser")
    hero = soup.select_one(".hero-unit") or soup
    data: dict[str, Any] = {}
    for p in hero.find_all("p"):
        strong = p.find("strong")
        if not strong:
            continue
        label = strong.get_text(" ", strip=True).rstrip(":")
        value = strong.next_sibling
        value_text = ""
        if value:
            tail = [x for x in p.contents if x is not strong]
            parts = []
            for x in tail:
                try:
                    parts.append(x.get_text(" ", strip=True) if hasattr(x, "get_text") else str(x))
                except Exception:
                    parts.append(str(x))
            value_text = " ".join(parts)
        data[normalize_key(label)] = " ".join(value_text.split()).strip()
    h2 = soup.select_one(".actividad-titulo")
    if h2:
        data["actividad"] = h2.get_text(" ", strip=True)
    return data


def parse_alumnos_asistencia_page(page: dict[str, Any]) -> list[dict[str, Any]]:
    html = "\n".join(
        p.get("content", "")
        for p in page.get("pagelets", [])
        if p.get("op") == "asistencias" and (p.get("info") or {}).get("id") == "edicion_asistencias"
    )
    if not html:
        html = page.get("all_content_html") or page.get("content_html") or ""
    soup = BeautifulSoup(html, "html.parser")
    alumnos: list[dict[str, Any]] = []
    for box in soup.select(".box-asistencia"):
        checkbox = box.find("input", attrs={"type": "checkbox", "name": re.compile(r"^alumnos\[[^]]+\]\[PRESENTE\]$")})
        if not checkbox:
            continue
        name_attr = str(checkbox.get("name") or "")
        match = re.search(r"alumnos\[([^]]+)\]\[PRESENTE\]", name_attr)
        alumno_hash = match.group(1) if match else None
        name_node = box.select_one(".info .truncate")
        nombre = (name_node.get("title") if name_node else None) or (name_node.get_text(" ", strip=True) if name_node else "")
        info = box.select_one(".info")
        legajo = ""
        if info:
            divs = info.find_all("div", recursive=False)
            if len(divs) > 1:
                legajo = divs[1].get_text(" ", strip=True)
        classes = set(box.get("class") or [])
        alumnos.append({
            "nombre": str(nombre).strip(),
            "legajo": legajo,
            "alumno_hash": alumno_hash,
            "presente": bool(checkbox.has_attr("checked") or "presente" in classes),
        })
    return alumnos


def selected_option(select: Tag | None) -> tuple[str, str]:
    if not select:
        return "", ""
    option = select.find("option", selected=True) or select.select_one("option[selected]")
    if option is None:
        # Fall back to data-valor-original if present on the select.
        original = select.get("data-valor-original")
        if original not in (None, ""):
            for opt in select.find_all("option"):
                if str(opt.get("value") or "") == str(original):
                    return str(original), opt.get_text(" ", strip=True)
        return "", ""
    return str(option.get("value") or ""), option.get_text(" ", strip=True)


def parse_notas_cursada_page(page: dict[str, Any], page_number: int | None = None) -> list[dict[str, Any]]:
    html = "\n".join(
        p.get("content", "")
        for p in page.get("pagelets", [])
        if p.get("op") == "notas_cursada_comision" and (p.get("info") or {}).get("id") == "renglones"
    )
    if not html:
        html = page.get("all_content_html") or page.get("content_html") or ""
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, Any]] = []
    for tr in soup.select("tr[id^='renglon_']"):
        nombre_node = tr.select_one(".datos-alumno .nombre")
        identificacion_node = tr.select_one(".datos-alumno .identificacion")
        renglon_id = str(tr.get("data-renglon") or "")
        fecha = tr.find("input", attrs={"name": re.compile(r"^renglones\[[^]]+\]\[fecha_promocion\]$")})
        nota_select = tr.find("select", attrs={"name": re.compile(r"^renglones\[[^]]+\]\[nota_promocion\]$")})
        resultado_select = tr.find("select", attrs={"name": re.compile(r"^renglones\[[^]]+\]\[resultado_promocion\]$")})
        observacion = tr.find("input", attrs={"name": re.compile(r"^renglones\[[^]]+\]\[observacion_promocion\]$")})
        nota_valor, nota_label = selected_option(nota_select if isinstance(nota_select, Tag) else None)
        resultado_valor, resultado_label = selected_option(resultado_select if isinstance(resultado_select, Tag) else None)
        acta_cell = tr.select_one(".col-nro-acta")
        asistencia_cell = tr.select_one(".col-asistencia")
        rows.append({
            "renglon_id": renglon_id,
            "nombre": (nombre_node.get("title") if nombre_node else "") or (nombre_node.get_text(" ", strip=True) if nombre_node else ""),
            "identificacion": (identificacion_node.get("title") if identificacion_node else "") or (identificacion_node.get_text(" ", strip=True) if identificacion_node else ""),
            "asistencia": asistencia_cell.get_text(" ", strip=True) if asistencia_cell else "",
            "acta": acta_cell.get_text(" ", strip=True) if acta_cell else "",
            "fecha_promocion": str(fecha.get("value") or "") if isinstance(fecha, Tag) else "",
            "nota_promocion": nota_valor,
            "nota_promocion_label": nota_label,
            "resultado_promocion": resultado_valor,
            "resultado_promocion_label": resultado_label,
            "observacion_promocion": str(observacion.get("value") or "") if isinstance(observacion, Tag) else "",
            "pagina": page_number,
        })
    return rows


def parse_reporte_actas(fragment: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(fragment or "", "html.parser")
    rows: list[dict[str, Any]] = []
    for tr in soup.select("tr[data-acta]"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td", recursive=False)]
        is_examen = "examen" in (tr.get("class") or [])
        if is_examen:
            if len(cells) < 12:
                continue
            rows.append({
                "tipo": "examen",
                "acta": cells[0],
                "actividad": cells[1],
                "mesa": cells[2],
                "llamado": cells[3],
                "fecha": cells[4],
                "ubicacion": cells[5],
                "estado": cells[6],
                "acta_digital": cells[7],
                "estado_firma": cells[8],
                "firmantes": cells[9],
                "pendientes_firma": cells[10],
                "rechazado_por": cells[11],
                "url_acta": tr.get("data-link") or tr.get("id") or "",
            })
            continue
        if len(cells) < 10:
            continue
        rows.append({
            "tipo": "cursada",
            "acta": cells[0],
            "actividad": cells[1],
            "comision": cells[2],
            "ubicacion": cells[3],
            "estado": cells[4],
            "acta_digital": cells[5],
            "estado_firma": cells[6],
            "firmantes": cells[7],
            "pendientes_firma": cells[8],
            "rechazado_por": cells[9],
            "url_acta": tr.get("data-link") or tr.get("id") or "",
        })
    return rows


def parse_detalle_acta_cursada(fragment: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(fragment or "", "html.parser")
    renglones: list[dict[str, Any]] = []
    current_folio = ""
    for tr in soup.find_all("tr"):
        text = html_to_text(str(tr))
        if text.startswith("Folio:"):
            current_folio = text.replace("Folio:", "", 1).strip()
            continue
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td", recursive=False)]
        if len(cells) >= 6 and cells[0] != "Legajo":
            renglones.append({
                "folio": current_folio,
                "legajo": cells[0],
                "alumno": cells[1],
                "fecha": cells[2],
                "nota": cells[3],
                "condicion": cells[4],
                "resultado": cells[5],
            })
    return renglones


def normalize_key(label: str) -> str:
    s = label.strip().lower()
    repl = str.maketrans("áéíóúñüº°", "aeiounuoo")
    s = s.translate(repl)
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "campo"


def parse_plain_tables(fragment: str) -> list[dict[str, Any]]:
    """Parse the first meaningful data table (header + rows) from a Guaraní fragment.

    Headers may be `<th>` or `<td>`. Used for listado de inscriptos
    (inscriptos_cursadas/info_comision), which uses `td.cc-titulo-nivel-0`.
    """
    soup = BeautifulSoup(fragment or "", "html.parser")
    result: list[dict[str, Any]] = []
    for table in soup.find_all("table"):
        headers: list[str] = []
        for tr in table.find_all("tr"):
            header_cells = tr.find_all("th") or tr.find_all("td", class_=re.compile("cc-titulo"))
            texts = [h.get_text(" ", strip=True) for h in header_cells if h.get_text(" ", strip=True)]
            if texts:
                headers = texts
                break
        if not headers:
            continue
        header_row_index = None
        for tr in table.find_all("tr"):
            header_cells = tr.find_all("th") or tr.find_all("td", class_=re.compile("cc-titulo"))
            header_texts = [h.get_text(" ", strip=True) for h in header_cells if h.get_text(" ", strip=True)]
            if header_texts == headers and tr.find_all("td"):
                header_row_index = id(tr)
                break
        for tr in table.find_all("tr"):
            if header_row_index is not None and id(tr) == header_row_index:
                continue
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td", recursive=False)]
            if not cells:
                continue
            row = {normalize_key(headers[i]): cells[i] for i in range(min(len(headers), len(cells)))}
            if row:
                result.append(row)
        if result:
            return result
    return result
