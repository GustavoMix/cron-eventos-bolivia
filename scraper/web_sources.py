"""Fuentes web: ticketeras, agendas culturales y sitios de sedes.

Facebook es la fuente principal de este proyecto, pero es también la única que
bloquea. Estas fuentes son el piso de garantía: no bloquean, se leen en
paralelo y en muchos casos publican datos estructurados. Cuando una corrida
pierde medio Facebook, el catálogo igual se mueve.

Lo que hace valiosas a estas fuentes por encima de su disponibilidad es
`schema.org/Event`. Una ticketera que publica JSON-LD nos está entregando la
fecha exacta, el nombre del recinto y el precio en campos separados — sin
adivinar nada. Un afiche de Facebook, por bueno que sea el parser, siempre es
una interpretación. Por eso el JSON-LD se lee primero y el HTML queda como
respaldo.
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .models import RawItem

TIPOS_DE_EVENTO_JSONLD = {
    "event", "musicevent", "theaterevent", "festival", "sportsevent",
    "socialevent", "businessevent", "educationevent", "exhibitionevent",
    "screeningevent", "comedyevent", "danceevent", "foodevent",
    "childrensevent", "literaryevent", "visualartsevent",
}

PALABRAS_DE_EVENTO = [
    "evento", "eventos", "agenda", "cartelera", "concierto", "conciertos",
    "festival", "feria", "teatro", "espectaculo", "espectáculo", "show",
    "funcion", "función", "entradas", "boleteria", "boletería", "programacion",
    "programación", "actividad", "actividades", "cultura", "exposicion",
    "exposición", "taller", "curso", "proximos", "próximos",
]

META_FECHA = {
    "article:published_time", "date", "datepublished", "publishdate",
    "pubdate", "article:modified_time",
}


def _texto(nodo) -> str:
    return nodo.get_text(" ", strip=True) if nodo else ""


def _absoluta(base: str, href: Optional[str]) -> Optional[str]:
    if not href:
        return None
    url = urljoin(base, href.strip())
    return url if url.startswith(("http://", "https://")) else None


def _es_relevante(texto: str) -> bool:
    bajo = (texto or "").lower()
    return any(p in bajo for p in PALABRAS_DE_EVENTO)


# --------------------------------------------------------------------------
# schema.org/Event
# --------------------------------------------------------------------------

def _aplanar_jsonld(dato: Any) -> List[Dict[str, Any]]:
    """Saca todos los objetos de un bloque JSON-LD.

    Los sitios reales anidan de todas las formas posibles: una lista suelta, un
    @graph, un ItemList con itemListElement. Se recorre todo y se devuelven los
    diccionarios, que después se filtran por @type.
    """
    salida: List[Dict[str, Any]] = []
    if isinstance(dato, list):
        for x in dato:
            salida.extend(_aplanar_jsonld(x))
    elif isinstance(dato, dict):
        salida.append(dato)
        for clave in ("@graph", "itemListElement", "item", "subEvent", "events"):
            if clave in dato:
                salida.extend(_aplanar_jsonld(dato[clave]))
    return salida


def _es_evento(obj: Dict[str, Any]) -> bool:
    tipos = obj.get("@type")
    if isinstance(tipos, str):
        tipos = [tipos]
    if not isinstance(tipos, list):
        return False
    return any(str(t).lower() in TIPOS_DE_EVENTO_JSONLD for t in tipos)


def _primero(valor: Any) -> Any:
    return valor[0] if isinstance(valor, list) and valor else valor


def _nombre_de_lugar(location: Any) -> Tuple[Optional[str], Optional[str]]:
    """(nombre del recinto, dirección) desde el campo location."""
    location = _primero(location)
    if isinstance(location, str):
        return location, None
    if not isinstance(location, dict):
        return None, None

    nombre = location.get("name")
    direccion = location.get("address")
    if isinstance(direccion, dict):
        partes = [
            direccion.get("streetAddress"),
            direccion.get("addressLocality"),
            direccion.get("addressRegion"),
        ]
        direccion = ", ".join(p for p in partes if p) or None
    elif not isinstance(direccion, str):
        direccion = None
    return (nombre if isinstance(nombre, str) else None), direccion


def _precio_de_ofertas(offers: Any) -> Tuple[Optional[str], List[str]]:
    """(texto del precio, URLs de compra)."""
    precios, urls = [], []
    for oferta in (offers if isinstance(offers, list) else [offers]):
        if not isinstance(oferta, dict):
            continue
        for clave in ("price", "lowPrice", "highPrice"):
            valor = oferta.get(clave)
            if valor not in (None, ""):
                precios.append(str(valor))
        url = oferta.get("url")
        if isinstance(url, str):
            urls.append(url)

    if not precios:
        return None, urls
    numeros = sorted({p for p in precios})
    return f"Bs {' - '.join(numeros)}", urls


def _imagenes_jsonld(valor: Any, base: str) -> List[str]:
    salida = []
    for img in (valor if isinstance(valor, list) else [valor]):
        if isinstance(img, dict):
            img = img.get("url")
        if isinstance(img, str):
            absoluta = _absoluta(base, img)
            if absoluta and absoluta not in salida:
                salida.append(absoluta)
    return salida[:12]


def _texto_desde_evento(obj: Dict[str, Any], sede: Optional[str],
                        direccion: Optional[str], precio: Optional[str]) -> str:
    """Rearma el evento estructurado como un bloque de texto.

    Puede parecer un rodeo —tenemos los campos separados y los volvemos a pegar
    para que el clasificador los separe otra vez— pero mantiene un solo camino
    de análisis para todo el proyecto. Las fechas ISO, la sede y el precio ya
    vienen en el formato que los extractores leen mejor, así que no se pierde
    precisión, y a cambio no hay dos rutas distintas que puedan divergir.
    """
    lineas = [
        str(obj.get("name") or "").strip(),
        str(obj.get("startDate") or "").strip(),
        str(obj.get("endDate") or "").strip(),
        sede or "",
        direccion or "",
        precio or "",
        re.sub(r"<[^>]+>", " ", str(obj.get("description") or "")).strip(),
    ]
    return "\n".join(l for l in lineas if l)


def _eventos_estructurados(soup: BeautifulSoup, base: str,
                           source: Dict[str, Any]) -> List[RawItem]:
    items: List[RawItem] = []
    for bloque in soup.find_all("script", attrs={"type": "application/ld+json"}):
        crudo = bloque.string or bloque.get_text() or ""
        try:
            dato = json.loads(crudo)
        except (json.JSONDecodeError, ValueError):
            continue

        for obj in _aplanar_jsonld(dato):
            if not _es_evento(obj) or not obj.get("name"):
                continue

            sede, direccion = _nombre_de_lugar(obj.get("location"))
            precio, urls_compra = _precio_de_ofertas(obj.get("offers"))
            url_evento = _absoluta(base, obj.get("url")) or base

            items.append(RawItem(
                source_id=source["id"],
                source_name=source["name"],
                source_url=source["url"],
                item_url=url_evento,
                text=_texto_desde_evento(obj, sede, direccion, precio),
                title=str(obj.get("name"))[:200],
                published_at=obj.get("startDate"),
                region_hint=source.get("region"),
                city_hint=source.get("city"),
                source_class=source.get("source_class", "web"),
                tier=int(source.get("tier", 2)),
                image_urls=_imagenes_jsonld(obj.get("image"), base),
                external_links=[u for u in urls_compra if u][:6],
            ))
    return items


# --------------------------------------------------------------------------
# Respaldo en HTML
# --------------------------------------------------------------------------

def _titulo(soup: BeautifulSoup) -> str:
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        return og["content"].strip()
    h1 = soup.find("h1")
    if h1:
        return _texto(h1)
    return _texto(soup.title)


def _fecha_meta(soup: BeautifulSoup) -> Optional[str]:
    for meta in soup.find_all("meta"):
        nombre = (meta.get("property") or meta.get("name") or "").lower()
        if nombre in META_FECHA and meta.get("content"):
            return meta["content"]
    t = soup.find("time")
    if t:
        return t.get("datetime") or _texto(t)
    return None


def _cuerpo(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav"]):
        tag.decompose()
    candidatos = []
    for selector in ["article", "main", ".entry-content", ".post-content",
                     ".content", "#content", ".event", ".evento"]:
        for nodo in soup.select(selector):
            txt = _texto(nodo)
            if len(txt) > 120:
                candidatos.append(txt)
    if candidatos:
        return max(candidatos, key=len)
    return _texto(soup.body) if soup.body else _texto(soup)


def _icono(soup: BeautifulSoup, base: str) -> Optional[str]:
    for selector in ['img[class*="logo"][src]', 'img[id*="logo"][src]', "header img[src]"]:
        nodo = soup.select_one(selector)
        if nodo and nodo.get("src"):
            return _absoluta(base, nodo["src"])
    for nombre in ["apple-touch-icon", "icon", "shortcut icon"]:
        for nodo in soup.find_all("link", href=True):
            if nombre in " ".join(nodo.get("rel") or []).lower():
                return _absoluta(base, nodo["href"])
    return None


def _imagenes_html(soup: BeautifulSoup, base: str, icono: Optional[str]) -> List[str]:
    urls: List[str] = []
    for prop in ["og:image", "twitter:image"]:
        nodo = (soup.find("meta", attrs={"property": prop})
                or soup.find("meta", attrs={"name": prop}))
        if nodo and nodo.get("content"):
            u = _absoluta(base, nodo["content"])
            if u and u != icono and u not in urls:
                urls.append(u)
    for selector in ["article img[src]", "main img[src]", ".event img[src]",
                     ".entry-content img[src]"]:
        for img in soup.select(selector):
            u = _absoluta(base, img.get("data-src") or img.get("src"))
            if u and u != icono and u not in urls:
                urls.append(u)
                if len(urls) >= 12:
                    return urls
    return urls[:12]


def _video(soup: BeautifulSoup, base: str, imagenes: List[str]):
    for prop in ["og:video:url", "og:video", "twitter:player"]:
        nodo = (soup.find("meta", attrs={"property": prop})
                or soup.find("meta", attrs={"name": prop}))
        if nodo and nodo.get("content"):
            return _absoluta(base, nodo["content"]), (imagenes[0] if imagenes else None), "web_video"
    iframe = soup.select_one(
        'iframe[src*="youtube.com"], iframe[src*="youtu.be"], iframe[src*="vimeo.com"]'
    )
    if iframe and iframe.get("src"):
        return _absoluta(base, iframe["src"]), (imagenes[0] if imagenes else None), "web_embed"
    return None, None, None


def _item_html(source: Dict[str, Any], url_item: str, soup: BeautifulSoup,
               texto: str, icono: Optional[str]) -> RawItem:
    imagenes = _imagenes_html(soup, url_item, icono)
    url_video, miniatura, tipo = _video(soup, url_item, imagenes)
    return RawItem(
        source_id=source["id"], source_name=source["name"],
        source_url=source["url"], item_url=url_item,
        text=texto, title=_titulo(soup), published_at=_fecha_meta(soup),
        region_hint=source.get("region"), city_hint=source.get("city"),
        source_class=source.get("source_class", "web"),
        tier=int(source.get("tier", 2)),
        source_icon_url=icono, image_urls=imagenes,
        video_url=url_video, video_thumbnail_url=miniatura, video_type=tipo,
    )


def leer_fuente_web(source: Dict[str, Any], settings: Dict[str, Any]) -> List[RawItem]:
    url = source["url"]
    timeout = float(settings.get("request_timeout_seconds", 20))
    max_items = int(settings.get("max_items_por_fuente", 20))
    seguir = bool(source.get("follow_links", True))
    max_enlaces = int(settings.get("web_max_enlaces", 12))

    cabeceras = {
        "User-Agent": settings.get(
            "user_agent",
            "EventosBoliviaBot/1.0 (+agenda-publica-de-eventos; crawler respetuoso)",
        ),
        "Accept-Language": "es-BO,es;q=0.9,en;q=0.6",
    }

    items: List[RawItem] = []
    with httpx.Client(headers=cabeceras, follow_redirects=True, timeout=timeout) as cliente:
        r = cliente.get(url)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        base = str(r.url)
        icono = source.get("icon_url") or _icono(soup, base)

        # Datos estructurados primero: si el sitio los publica, ya está todo.
        estructurados = _eventos_estructurados(soup, base, source)
        for item in estructurados:
            item.source_icon_url = item.source_icon_url or icono
        items.extend(estructurados)

        if len(items) < max_items:
            cuerpo = _cuerpo(r.text)
            if _es_relevante(cuerpo):
                items.append(_item_html(source, base, soup, cuerpo, icono))

        if seguir and len(items) < max_items:
            host = urlparse(base).netloc
            enlaces, vistos = [], set()
            for a in soup.find_all("a", href=True):
                href = _absoluta(base, a["href"])
                if not href or urlparse(href).netloc != host:
                    continue
                if not _es_relevante(f"{_texto(a)} {href}"):
                    continue
                limpio = href.split("#")[0]
                if limpio not in vistos and limpio != base:
                    vistos.add(limpio)
                    enlaces.append(limpio)

            for enlace in enlaces[:max_enlaces]:
                if len(items) >= max_items:
                    break
                try:
                    rr = cliente.get(enlace)
                    if rr.status_code >= 400:
                        continue
                    ss = BeautifulSoup(rr.text, "html.parser")
                    detalle = _eventos_estructurados(ss, str(rr.url), source)
                    if detalle:
                        items.extend(detalle)
                        continue
                    texto = _cuerpo(rr.text)
                    if _es_relevante(texto):
                        items.append(_item_html(source, str(rr.url), ss, texto, icono))
                except (httpx.HTTPError, ValueError):
                    continue

    unicos: Dict[str, RawItem] = {}
    for item in items:
        clave = f"{item.item_url}|{item.title[:80]}"
        unicos.setdefault(clave, item)
    return list(unicos.values())[:max_items]
