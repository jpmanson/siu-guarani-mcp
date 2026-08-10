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

    def mesas_examen(self) -> list[dict[str, Any]]:
        page = self.get_operation("zona_examenes")
        return parse_activity_tables(page["content_html"], context_kind="general")

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


def normalize_key(label: str) -> str:
    s = label.strip().lower()
    repl = str.maketrans("áéíóúñüº°", "aeiounuoo")
    s = s.translate(repl)
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "campo"
