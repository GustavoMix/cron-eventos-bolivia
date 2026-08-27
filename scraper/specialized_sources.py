"""Lectores especializados para agendas bolivianas con estructura repetible.

El lector genérico sigue siendo el fallback para cualquier web. Este módulo se
usa sólo cuando una fuente declara ``parser`` en ``sources.yaml`` y la página
tiene suficiente estructura para extraer mejor que un bloque de texto completo.

No intenta saltar login, captcha ni protecciones. Trabaja únicamente con HTML
público y conserva enlaces públicos de imagen/video.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, time
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag

from .models import RawItem

TZ_BOLIVIA = ZoneInfo("America/La_Paz")

_MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5,
    "junio": 6, "julio": 7, "agosto": 8, "septiembre": 9,
    "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

_RE_EVENTO_SCZ = re.compile(r"/eventos/[0-9a-f]{8}-[0-9a-f-]{20,}", re.I)
_RE_EVENTO_JIWAKI = re.compile(r"/agendajiwaki/event/[^/?#]+/?$", re.I)
_RE_SALA_CINE = re.compile(r"/cine/[^?#]+-s\d+(?:_\d+)?(?:$|[?#])", re.I)
_RE_PELICULA = re.compile(r"/cine/[^?#]+-\d+_\d+(?:$|[?#])", re.I)
_RE_HORA = re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b")
_RE_ISO_FECHA_HORA = re.compile(
    r"\b(20\d{2}-\d{2}-\d{2})\b.{0,24}?\b((?:[01]?\d|2[0-3]):[0-5]\d)\b",
    re.I | re.S,
)
_RE_FECHA_ES = re.compile(
    r"(?:(?:lun|mar|mi[eé]|jue|vie|s[aá]b|dom)[a-z]*\s*,?\s*)?"
    r"(?P<dia>\d{1,2})\s+de\s+(?P<mes>[a-záéíóúñ]+)"
    r"(?:\s*[–—-]\s*(?P<dia_fin>\d{1,2})\s+de\s+(?P<mes_fin>[a-záéíóúñ]+))?"
    r"\s*,?\s*(?P<hora>(?:[01]?\d|2[0-3]):[0-5]\d)",
    re.I,
)
_RE_PRECIO_RANGO = re.compile(
    r"(?:(?:Bs\.?\s*)?(\d+(?:[.,]\d+)?)\s*Bs?)\s*[-–—]\s*"
    r"(?:(?:Bs\.?\s*)?(\d+(?:[.,]\d+)?)\s*Bs?)",
    re.I,
)
_RE_PRECIO_UNICO = re.compile(r"(?:Bs\.?\s*)(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)\s*Bs\b", re.I)
_RE_TELEFONO = re.compile(r"(?<!\d)(?:\+?591\s*)?([67]\d{7})(?!\d)")
_RE_FORMATO_CINE = re.compile(
    r"\b(?:2D|3D|4D|DBOX|XD|PLUS|XL|KRONOS|PRE|DOBLADA|SUBTITULADA|SUB)\b",
    re.I,
)


def _sin_tildes(texto: str) -> str:
    normal = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in normal if not unicodedata.combining(c)).lower()


def _abs(base: str, href: Optional[str]) -> Optional[str]:
    if not href:
        return None
    url = urljoin(base, href.strip())
    return url if url.startswith(("http://", "https://")) else None


def _texto(nodo: Optional[Tag]) -> str:
    return nodo.get_text(" ", strip=True) if nodo else ""


def _contenido_principal(soup: BeautifulSoup) -> Tag:
    return soup.find("main") or soup.find("article") or soup.body or soup


def _meta_imagen(soup: BeautifulSoup, base: str) -> List[str]:
    salida: List[str] = []
    for selector in [
        ('meta', {"property": "og:image"}),
        ('meta', {"name": "twitter:image"}),
    ]:
        nodo = soup.find(selector[0], attrs=selector[1])
        if nodo and nodo.get("content"):
            u = _abs(base, nodo.get("content"))
            if u and u not in salida:
                salida.append(u)
    h1 = soup.find("h1")
    titulo = _texto(h1).lower()
    if titulo:
        for img in soup.find_all("img", src=True):
            alt = (img.get("alt") or "").strip().lower()
            if alt and (alt in titulo or titulo in alt):
                u = _abs(base, img.get("data-src") or img.get("src"))
                if u and u not in salida:
                    salida.append(u)
    return salida[:12]


def _video_publico(soup: BeautifulSoup, base: str, miniatura: Optional[str]):
    for prop in ["og:video:url", "og:video", "twitter:player"]:
        nodo = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        if nodo and nodo.get("content"):
            u = _abs(base, nodo.get("content"))
            if u:
                return u, miniatura, "web_video"
    iframe = soup.select_one(
        'iframe[src*="youtube.com"], iframe[src*="youtu.be"], iframe[src*="vimeo.com"]'
    )
    if iframe and iframe.get("src"):
        return _abs(base, iframe.get("src")), miniatura, "web_embed"
    return None, None, None


def _ahora(settings: Optional[Dict[str, Any]] = None) -> datetime:
    valor = (settings or {}).get("now_iso")
    if valor:
        try:
            dt = datetime.fromisoformat(str(valor))
            return dt.replace(tzinfo=TZ_BOLIVIA) if dt.tzinfo is None else dt.astimezone(TZ_BOLIVIA)
        except ValueError:
            pass
    return datetime.now(TZ_BOLIVIA)


def _mes(numero_o_nombre: str) -> Optional[int]:
    return _MESES.get(_sin_tildes(numero_o_nombre))


def _funciones_espanol(texto: str, ahora: datetime) -> List[datetime]:
    funciones: List[datetime] = []
    for m in _RE_FECHA_ES.finditer(texto):
        mes = _mes(m.group("mes"))
        if not mes:
            continue
        hh, mm = map(int, m.group("hora").split(":"))
        try:
            inicio = datetime(ahora.year, mes, int(m.group("dia")), hh, mm, tzinfo=TZ_BOLIVIA)
        except ValueError:
            continue
        # Las agendas consultadas son del año actual. A fin de año, si aparece
        # enero/febrero muy por delante, se interpreta como el siguiente año.
        if inicio.date() < ahora.date() and (ahora.date() - inicio.date()).days > 120:
            try:
                inicio = inicio.replace(year=ahora.year + 1)
            except ValueError:
                pass
        funciones.append(inicio)
    return funciones


def _valor_despues_de_etiqueta(principal: Tag, etiqueta: str) -> Optional[str]:
    objetivo = _sin_tildes(etiqueta)
    textos = [t.strip() for t in principal.stripped_strings if t.strip()]
    for i, texto in enumerate(textos[:-1]):
        if _sin_tildes(texto) == objetivo:
            candidato = textos[i + 1].strip()
            if candidato:
                return candidato
    return None


def _precios(texto: str):
    rango = _RE_PRECIO_RANGO.search(texto)
    if rango:
        a = float(rango.group(1).replace(",", "."))
        b = float(rango.group(2).replace(",", "."))
        return min(a, b), max(a, b), f"Bs {min(a,b):g} - {max(a,b):g}"
    uno = _RE_PRECIO_UNICO.search(texto)
    if uno:
        valor = float((uno.group(1) or uno.group(2)).replace(",", "."))
        return valor, valor, f"Bs {valor:g}"
    return None, None, None


def descubrir_santa_cruz(html: str, base: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    salida: List[str] = []
    for a in soup.find_all("a", href=True):
        href = a.get("href") or ""
        if not _RE_EVENTO_SCZ.search(href):
            continue
        u = _abs(base, href)
        if u and u not in salida:
            salida.append(u)
    return salida


def parsear_santa_cruz_detalle(html: str, url: str, source: Dict[str, Any], ahora: datetime) -> RawItem:
    soup = BeautifulSoup(html, "html.parser")
    principal = _contenido_principal(soup)
    titulo = _texto(principal.find("h1") or soup.find("h1"))
    texto = _texto(principal)
    imagenes = _meta_imagen(soup, url)
    video_url, video_thumb, video_type = _video_publico(
        soup, url, imagenes[0] if imagenes else None
    )

    funciones = _funciones_espanol(texto, ahora)
    showtimes = [f"{dt.hour:02d}:{dt.minute:02d}" for dt in funciones]

    # En estas fichas el primer enlace a /lugares/ tras el título es la sede.
    venue = None
    for a in principal.find_all("a", href=True):
        if "/lugares/" in (a.get("href") or "") and _texto(a):
            venue = _texto(a)
            break

    address = None
    if venue:
        venue_node = next((a for a in principal.find_all("a", href=True) if _texto(a) == venue), None)
        if venue_node:
            siguiente = venue_node.find_next(string=lambda s: bool(s and s.strip() and s.strip() != venue))
            if siguiente:
                candidato = str(siguiente).strip()
                if candidato and "cómo llegar" not in _sin_tildes(candidato):
                    address = candidato

    organizer = _valor_despues_de_etiqueta(principal, "Organizador")
    audience = _valor_despues_de_etiqueta(principal, "Público")
    age = _valor_despues_de_etiqueta(principal, "Edades")
    price_from, price_to, price_text = _precios(texto)
    gratis = any(x in _sin_tildes(texto) for x in ["ingreso gratuito", "entrada libre", "gratis"])
    phones = list(dict.fromkeys(_RE_TELEFONO.findall(texto)))[:6]

    structured: Dict[str, Any] = {
        "organizer": organizer,
        "audience": audience,
        "age_restriction": age,
        "showtimes": showtimes,
        "occurrences": [dt.isoformat(timespec="seconds") for dt in funciones],
        "venue": venue,
        "address": address,
        "city": source.get("city") or "Santa Cruz de la Sierra",
        "department": source.get("region") or "Santa Cruz",
        "price_from": price_from,
        "price_to": price_to,
        "currency": "BOB" if price_from is not None else None,
        "price_text": price_text,
        "is_free": gratis and price_from is None,
        "phones": phones,
    }
    if funciones:
        structured["starts_at"] = funciones[0].isoformat(timespec="seconds")
        if len(funciones) > 1 and funciones[-1] > funciones[0]:
            structured["ends_at"] = funciones[-1].isoformat(timespec="seconds")

    return RawItem(
        source_id=source["id"], source_name=source["name"], source_url=source["url"],
        item_url=url, text=texto, title=titulo,
        region_hint=source.get("region"), city_hint=source.get("city"),
        source_class=source.get("source_class", "cultura_oficial"), tier=int(source.get("tier", 1)),
        image_urls=imagenes, video_url=video_url, video_thumbnail_url=video_thumb,
        video_type=video_type, structured_data=structured,
    )


def descubrir_jiwaki(html: str, base: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    salida: List[str] = []
    for a in soup.find_all("a", href=True):
        href = a.get("href") or ""
        absoluto = _abs(base, href)
        if absoluto and _RE_EVENTO_JIWAKI.search(absoluto) and absoluto not in salida:
            salida.append(absoluto)
    return salida


def parsear_jiwaki_detalle(html: str, url: str, source: Dict[str, Any], ahora: datetime) -> RawItem:
    soup = BeautifulSoup(html, "html.parser")
    principal = _contenido_principal(soup)
    titulo = _texto(principal.find("h1") or soup.find("h1"))
    texto = _texto(principal)
    imagenes = _meta_imagen(soup, url)
    video_url, video_thumb, video_type = _video_publico(
        soup, url, imagenes[0] if imagenes else None
    )

    structured: Dict[str, Any] = {
        "city": source.get("city") or "La Paz",
        "department": source.get("region") or "La Paz",
    }
    m = _RE_ISO_FECHA_HORA.search(texto)
    if m:
        inicio = datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}:00").replace(tzinfo=TZ_BOLIVIA)
        structured["starts_at"] = inicio.isoformat(timespec="seconds")
        structured["showtimes"] = [m.group(2)]
        structured["occurrences"] = [inicio.isoformat(timespec="seconds")]

    # Jiwaki lista la sede como una línea corta junto a la fecha. Se favorecen
    # nombres típicos de recintos y se evita adivinar desde párrafos largos.
    for cadena in principal.stripped_strings:
        limpio = cadena.strip()
        bajo = _sin_tildes(limpio)
        if len(limpio) <= 140 and re.search(
            r"\b(teatro|museo|biblioteca|casa del poeta|casa de la cultura|centro cultural|cine teatro|auditorio)\b",
            bajo,
        ):
            if limpio != titulo:
                structured["venue"] = limpio
                break

    return RawItem(
        source_id=source["id"], source_name=source["name"], source_url=source["url"],
        item_url=url, text=texto, title=titulo,
        region_hint=source.get("region"), city_hint=source.get("city"),
        source_class=source.get("source_class", "cultura_oficial"), tier=int(source.get("tier", 1)),
        image_urls=imagenes, video_url=video_url, video_thumbnail_url=video_thumb,
        video_type=video_type, structured_data=structured,
    )


def descubrir_salas_bolivia_com(html: str, base: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    salida: List[str] = []
    for a in soup.find_all("a", href=True):
        u = _abs(base, a.get("href"))
        if u and _RE_SALA_CINE.search(u) and u not in salida:
            salida.append(u)
    return salida


def _anclas_peliculas_despues_del_h1(soup: BeautifulSoup) -> List[Tag]:
    h1 = soup.find("h1")
    if not h1:
        return []
    salida: List[Tag] = []
    for tag in h1.find_all_next():
        if tag.name in {"h2", "h3", "h4"} and "lo ultimo" in _sin_tildes(_texto(tag)):
            break
        if tag.name == "a" and tag.get("href") and _RE_PELICULA.search(tag.get("href")):
            salida.append(tag)
    return salida


def _textos_entre(ancla: Tag, siguiente: Optional[Tag]) -> Iterable[str]:
    for nodo in ancla.next_elements:
        if nodo is siguiente:
            break
        if isinstance(nodo, Tag) and nodo.name in {"h2", "h3", "h4"} and "lo ultimo" in _sin_tildes(_texto(nodo)):
            break
        if isinstance(nodo, NavigableString):
            t = str(nodo).strip()
            if t:
                yield t


def parsear_bolivia_com_sala(html: str, url: str, source: Dict[str, Any], ahora: datetime) -> List[RawItem]:
    soup = BeautifulSoup(html, "html.parser")
    venue = _texto(soup.find("h1")) or source.get("name")
    h2 = soup.find("h2")
    city = _texto(h2) or source.get("city")
    address = None
    if h2:
        maps = h2.find_next("a", href=lambda h: bool(h and "maps.google" in h))
        if maps:
            address = _texto(maps)

    anclas = _anclas_peliculas_despues_del_h1(soup)
    items: List[RawItem] = []
    for i, ancla in enumerate(anclas):
        siguiente = anclas[i + 1] if i + 1 < len(anclas) else None
        fragmentos = list(_textos_entre(ancla, siguiente))
        horarios: List[str] = []
        formatos: List[str] = []
        for frag in fragmentos:
            for hora in _RE_HORA.findall(frag):
                normal = hora if len(hora) == 5 else f"0{hora}"
                if normal not in horarios:
                    horarios.append(normal)
            limpio = " ".join(frag.split())
            if limpio and len(limpio) <= 80 and _RE_FORMATO_CINE.search(limpio) and not _RE_HORA.fullmatch(limpio):
                if limpio not in formatos:
                    formatos.append(limpio)
        if not horarios:
            continue

        hh, mm = map(int, horarios[0].split(":"))
        inicio = datetime.combine(ahora.date(), time(hh, mm), tzinfo=TZ_BOLIVIA)
        titulo = _texto(ancla)
        item_url = _abs(url, ancla.get("href")) or url
        img = ancla.find("img")
        imagenes = []
        if img:
            u = _abs(url, img.get("data-src") or img.get("src"))
            if u:
                imagenes.append(u)

        texto = "\n".join([
            titulo,
            "Película en cartelera de cine",
            inicio.strftime("%d/%m/%Y %H:%M"),
            f"Sala: {venue}",
            f"Ciudad: {city}",
            f"Dirección: {address}" if address else "",
            f"Horarios: {', '.join(horarios)}",
            f"Formatos: {', '.join(formatos)}" if formatos else "",
        ]).strip()
        occurrences = []
        for horario in horarios:
            ohh, omm = map(int, horario.split(":"))
            ocurrencia = datetime.combine(ahora.date(), time(ohh, omm), tzinfo=TZ_BOLIVIA)
            occurrences.append(ocurrencia.isoformat(timespec="seconds"))

        items.append(RawItem(
            source_id=source["id"], source_name=source["name"], source_url=source["url"],
            item_url=item_url, text=texto, title=titulo,
            region_hint=source.get("region"), city_hint=source.get("city") or city,
            source_class=source.get("source_class", "cartelera_cine"), tier=int(source.get("tier", 2)),
            image_urls=imagenes,
            structured_data={
                "starts_at": inicio.isoformat(timespec="seconds"),
                "showtimes": horarios,
                "formats": formatos,
                "occurrences": occurrences,
                "venue": venue,
                "address": address,
                "city": source.get("city") or city,
                "department": source.get("region"),
            },
        ))
    return items


def _dato_cine_etiquetado(soup: BeautifulSoup, etiqueta: str) -> Optional[str]:
    buscada = _sin_tildes(etiqueta).rstrip(":")
    for fragmento in _contenido_principal(soup).stripped_strings:
        limpio = " ".join(str(fragmento).split())
        sin = _sin_tildes(limpio)
        if sin.startswith(buscada + ":"):
            valor = limpio.split(":", 1)[1].strip()
            if valor:
                return valor
    return None


def _enriquecer_multimedia(item: RawItem, html: str) -> None:
    soup = BeautifulSoup(html, "html.parser")
    imagenes = _meta_imagen(soup, item.item_url)
    for u in imagenes:
        if u not in item.image_urls:
            item.image_urls.append(u)
    video_url, thumb, tipo = _video_publico(
        soup, item.item_url, item.image_urls[0] if item.image_urls else None
    )
    if video_url and not item.video_url:
        item.video_url = video_url
        item.video_thumbnail_url = thumb
        item.video_type = tipo

    # Bolivia.com publica estos datos como líneas visibles en la ficha. Son
    # mejores que intentar deducirlos del título o de la clasificación general.
    genero = _dato_cine_etiquetado(soup, "Género")
    duracion = _dato_cine_etiquetado(soup, "Duración")
    clasificacion = _dato_cine_etiquetado(soup, "Clasificación")
    director = _dato_cine_etiquetado(soup, "Director")
    actores = _dato_cine_etiquetado(soup, "Actores")
    if genero:
        item.structured_data["content_genre"] = genero
    if duracion:
        m = re.search(r"\b(\d{1,3})\s*min", duracion, re.I)
        if m:
            item.structured_data["duration_minutes"] = int(m.group(1))
    if clasificacion:
        item.structured_data["age_restriction"] = clasificacion
    if director:
        item.structured_data["director"] = director
    if actores:
        reparto = [x.strip() for x in re.split(r"[,;]", actores) if x.strip()]
        item.structured_data["cast"] = reparto[:20]


def _limite_items(source: Dict[str, Any], settings: Dict[str, Any]) -> int:
    """Permite subir/bajar el cupo sólo en fuentes con estructura controlada."""
    return max(1, int(source.get("max_items", settings.get("max_items_por_fuente", 20))))


def leer_fuente_especializada(source: Dict[str, Any], settings: Dict[str, Any]) -> Optional[List[RawItem]]:
    """Lee una fuente declarada con ``parser``; devuelve ``None`` si no aplica."""
    parser = source.get("parser")
    if parser not in {"santa_cruz_agenda", "jiwaki", "bolivia_com_cine"}:
        return None

    timeout = float(settings.get("request_timeout_seconds", 20))
    max_items = _limite_items(source, settings)
    now = _ahora(settings)
    headers = {
        "User-Agent": settings.get("user_agent", "EventosBoliviaBot/1.0 (+agenda-publica-de-eventos)"),
        "Accept-Language": "es-BO,es;q=0.9,en;q=0.5",
    }
    items: List[RawItem] = []
    with httpx.Client(headers=headers, follow_redirects=True, timeout=timeout) as cliente:
        r = cliente.get(source["url"])
        r.raise_for_status()
        base = str(r.url)

        if parser == "santa_cruz_agenda":
            for enlace in descubrir_santa_cruz(r.text, base)[:max_items]:
                rr = cliente.get(enlace)
                if rr.status_code < 400:
                    items.append(parsear_santa_cruz_detalle(rr.text, str(rr.url), source, now))

        elif parser == "jiwaki":
            for enlace in descubrir_jiwaki(r.text, base)[:max_items]:
                rr = cliente.get(enlace)
                if rr.status_code < 400:
                    items.append(parsear_jiwaki_detalle(rr.text, str(rr.url), source, now))

        elif parser == "bolivia_com_cine":
            max_salas = int(source.get("max_salas", 8))
            for sala in descubrir_salas_bolivia_com(r.text, base)[:max_salas]:
                if len(items) >= max_items:
                    break
                rr = cliente.get(sala)
                if rr.status_code >= 400:
                    continue
                items.extend(parsear_bolivia_com_sala(rr.text, str(rr.url), source, now))
                items = items[:max_items]

            # El detalle de la película puede traer poster o trailer. Se limita
            # para no multiplicar cientos de requests en cada ejecución.
            limite = int(settings.get("cine_enriquecer_limite", 6))
            vistos = set()
            for item in items:
                if len(vistos) >= limite:
                    break
                if item.item_url in vistos:
                    continue
                vistos.add(item.item_url)
                try:
                    rr = cliente.get(item.item_url)
                    if rr.status_code < 400:
                        _enriquecer_multimedia(item, rr.text)
                except httpx.HTTPError:
                    continue

    return items[:max_items]
