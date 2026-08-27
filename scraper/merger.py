"""Un evento anunciado por cinco páginas tiene que aparecer una sola vez.

La fecha hace este trabajo mucho más fácil que en un scraper de noticias: dos
publicaciones que anuncian algo para el mismo día, en el mismo lugar y con
palabras parecidas son el mismo evento, sin lugar a mucha duda. Un concierto
distinto el mismo día en el mismo teatro es raro; el mismo concierto anunciado
por el teatro, la ticketera y tres medios es lo normal.

Al fusionar no se elige "la mejor versión y se descarta el resto": se toma la
mejor como base y se rellenan sus huecos con lo que traigan las demás. El medio
puede tener el mejor texto, la ticketera el precio exacto y el teatro el afiche
en alta. El evento fusionado se queda con las tres cosas.
"""

import re
import unicodedata
from typing import Any, Dict, List, Optional

from .models import _bloque_multimedia, _video_dict

VACIAS = {
    "de", "la", "el", "los", "las", "en", "a", "y", "del", "por", "para", "un",
    "una", "se", "con", "que", "al", "su", "sus", "es", "esta", "este", "desde",
    "hasta", "sobre", "gran", "nuevo", "nueva", "bolivia", "boliviano",
    "boliviana", "evento", "entrada", "entradas", "vivo", "presenta",
}


def _norm(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c)).lower()
    texto = re.sub(r"https?://\S+", " ", texto)
    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


# Vocabulario que aparece en TODOS los afiches y por lo tanto no distingue un
# evento de otro: fechas, logística de entradas y los nombres de las categorías.
GENERICAS = {
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
    "septiembre", "setiembre", "octubre", "noviembre", "diciembre",
    "lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo",
    "concierto", "festival", "feria", "teatro", "show", "funcion", "obra",
    "espectaculo", "evento", "eventos", "fiesta", "taller", "curso", "expo",
    "entrada", "entradas", "preventa", "boleteria", "puertas", "horas",
    "esperamos", "pierdas", "presentan", "presentamos", "invitamos", "vivo",
    "tour", "gira", "informes", "reserva", "reservas", "cupos", "venta",
    "ingreso", "gratis", "gratuito", "libre", "noche", "tarde", "hora",
}


def _tokens(evento) -> set:
    partes = " ".join([
        getattr(evento, "title", "") or "",
        " ".join(getattr(evento, "artists", []) or []),
        (getattr(evento, "description", "") or "")[:600],
        getattr(evento, "venue", "") or "",
    ])
    return {t for t in _norm(partes).split() if len(t) >= 4 and t not in VACIAS}


def _tokens_de(*valores) -> set:
    texto = " ".join(v for v in valores if v)
    return {t for t in _norm(texto).split() if len(t) >= 4}


def _identidad(evento) -> set:
    """Las palabras que nombran a ESTE evento y no a cualquier otro.

    "Los Kjarkas, sábado 23 de agosto, Teatro Achá, entradas Bs 80" y "La Casa
    de Bernarda Alba, sábado 23 de agosto, Teatro Achá, entradas Bs 40"
    comparten casi todo su vocabulario: el día, la sede, la ciudad y toda la
    logística de entradas. Lo único que de verdad los diferencia son los
    nombres propios — y son justamente los que quedan al sacar todo lo demás.
    """
    base = " ".join([
        getattr(evento, "title", "") or "",
        " ".join(getattr(evento, "artists", []) or []),
    ])
    tokens = {
        t for t in _norm(base).split()
        if len(t) >= 4 and t not in VACIAS and t not in GENERICAS
    }
    return tokens - _tokens_de(
        getattr(evento, "venue", None),
        getattr(evento, "city", None),
        getattr(evento, "department", None),
    )


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _dia(iso: Optional[str]) -> Optional[str]:
    return iso[:10] if iso else None


def mismo_evento(a, b, umbral: float = 0.30) -> bool:
    """¿Son la misma cosa anunciada dos veces?"""
    dia_a, dia_b = _dia(a.starts_at), _dia(b.starts_at)

    if dia_a and dia_b:
        if dia_a != dia_b:
            # Salvo que uno de los dos sea un festival de varios días que
            # contenga al otro: el afiche general y el del día concreto son el
            # mismo evento.
            if not (_abarca(a, b) or _abarca(b, a)):
                return False
    elif dia_a or dia_b:
        # Uno tiene fecha y el otro no. Se los une solo con evidencia fuerte,
        # porque unir mal deja al evento con la fecha equivocada.
        return _jaccard(_tokens(a), _tokens(b)) >= 0.62
    else:
        return _jaccard(_tokens(a), _tokens(b)) >= 0.55

    sede_a, sede_b = _norm(a.venue or ""), _norm(b.venue or "")
    if sede_a and sede_b and sede_a != sede_b:
        # Mismo día, sedes distintas: son dos eventos distintos salvo que el
        # texto sea prácticamente el mismo (una sede suele estar mal leída).
        return _jaccard(_tokens(a), _tokens(b)) >= 0.70

    ciudad_a, ciudad_b = _norm(a.city or ""), _norm(b.city or "")
    if ciudad_a and ciudad_b and ciudad_a != ciudad_b:
        return False

    # Cuando los dos anuncios traen nombres propios, mandan ellos. Sin esto, un
    # concierto y una obra de teatro el mismo sábado en la misma sala se
    # fusionan: comparten el día, el lugar, la ciudad y todo el vocabulario de
    # entradas, que es casi todo el texto.
    ident_a, ident_b = _identidad(a), _identidad(b)
    if ident_a and ident_b:
        if not (ident_a & ident_b):
            return False
        return _jaccard(ident_a, ident_b) >= 0.20 or _jaccard(_tokens(a), _tokens(b)) >= umbral

    similitud = _jaccard(_tokens(a), _tokens(b))
    misma_sede = bool(sede_a and sede_a == sede_b)
    return similitud >= (max(0.16, umbral - 0.14) if misma_sede else umbral)


def _abarca(grande, chico) -> bool:
    """¿El rango de `grande` contiene el día de inicio de `chico`?"""
    if not (grande.starts_at and grande.ends_at and chico.starts_at):
        return False
    return grande.starts_at[:10] <= chico.starts_at[:10] <= grande.ends_at[:10]


def _ranking(evento):
    """La mejor versión de un evento: primero la fuente más confiable, después
    la que trae más información."""
    return (
        -int(evento.source_tier),
        float(evento.confidence),
        int(evento.relevance_score),
        len(evento.image_urls or []),
        len(evento.description or ""),
    )


def _primer_valor(cluster, atributo):
    for evento in cluster:
        valor = getattr(evento, atributo, None)
        if valor not in (None, "", [], {}):
            return valor
    return None


def _unir_listas(cluster, atributo, limite):
    salida, vistos = [], set()
    for evento in cluster:
        for valor in getattr(evento, atributo, []) or []:
            # Clave literal, no `_norm`: estas listas llevan URLs y `_norm` las
            # borra enteras, con lo que todo colapsaría a la cadena vacía.
            clave = str(valor).strip().lower()
            if clave and clave not in vistos:
                vistos.add(clave)
                salida.append(valor)
            if len(salida) >= limite:
                return salida
    return salida


def _etiqueta_verificacion(tiers: List[int], n_fuentes: int) -> str:
    if n_fuentes <= 1:
        return "una_fuente"
    if 1 in tiers and 2 in tiers:
        return "oficial_y_especializada"
    if 1 in tiers:
        return "confirmado_por_fuente_oficial"
    if 2 in tiers:
        return "confirmado_por_ticketera"
    return "varios_medios"


def _confianza(base: float, tiers: List[int], n_fuentes: int) -> float:
    valor = float(base)
    if n_fuentes >= 2:
        valor += 0.08
    if n_fuentes >= 3:
        valor += 0.05
    if 1 in tiers:
        valor += 0.04
    return round(min(valor, 0.99), 2)


def fusionar(eventos: List[Any], umbral: float = 0.30) -> List[Dict[str, Any]]:
    """Agrupa los eventos repetidos y devuelve un dict por evento único."""
    clusters: List[List[Any]] = []
    for evento in eventos:
        for cluster in clusters:
            if any(mismo_evento(evento, otro, umbral) for otro in cluster):
                cluster.append(evento)
                break
        else:
            clusters.append([evento])

    salida = []
    for cluster in clusters:
        ordenado = sorted(cluster, key=_ranking, reverse=True)
        mejor = ordenado[0]
        d = mejor.to_dict()

        # Rellenar huecos de la mejor versión con lo que traigan las otras.
        for campo in [
            "starts_at", "ends_at", "starts_at_ms", "ends_at_ms", "display_date",
            "doors_time", "venue", "address", "city", "department",
            "price_from", "price_to", "currency", "price_text",
            "facebook_event_url", "location_query",
            "organizer", "audience", "age_restriction", "duration_minutes",
            "content_genre", "director", "latitude", "longitude",
        ]:
            if d.get(campo) in (None, "", []):
                d[campo] = _primer_valor(ordenado, campo)

        # Si la mejor versión no traía fecha y otra sí, hay que rehacer todo lo
        # que se deriva de la fecha o quedarían contradiciéndose entre sí.
        if not mejor.starts_at:
            con_fecha = next((e for e in ordenado if e.starts_at), None)
            if con_fecha:
                for campo in ["date_confidence", "all_day", "multi_day",
                              "lifecycle", "days_until", "date_source_text"]:
                    d[campo] = getattr(con_fecha, campo)

        # Un solo aviso de cancelación pesa más que cinco publicaciones que aún
        # no se enteraron: si alguien dice que se canceló, se anuncia cancelado.
        estados = [e.status for e in ordenado]
        for critico in ("cancelado", "postergado", "agotado"):
            if critico in estados:
                d["status"] = critico
                break

        d["is_free"] = any(e.is_free for e in ordenado) and d.get("price_from") is None

        imagenes = _unir_listas(ordenado, "image_urls", 24)
        videos = []
        for e in ordenado:
            if e.video_url and all(v["url"] != e.video_url for v in videos):
                videos.append(_video_dict(
                    e.video_url, e.video_thumbnail_url, e.video_type, e.source_id
                ))
        d.update(_bloque_multimedia(imagenes, videos[:8]))

        d["subcategories"] = _unir_listas(ordenado, "subcategories", 6)
        d["tags"] = _unir_listas(ordenado, "tags", 15)
        d["artists"] = _unir_listas(ordenado, "artists", 10)
        d["ticket_urls"] = _unir_listas(ordenado, "ticket_urls", 8)
        d["ticket_outlets"] = _unir_listas(ordenado, "ticket_outlets", 8)
        d["showtimes"] = _unir_listas(ordenado, "showtimes", 32)
        d["formats"] = _unir_listas(ordenado, "formats", 16)
        d["occurrences"] = _unir_listas(ordenado, "occurrences", 64)
        d["cast"] = _unir_listas(ordenado, "cast", 24)
        d["phones"] = _unir_listas(ordenado, "phones", 6)

        fuentes, vistas, urls = [], set(), []
        for e in sorted(ordenado, key=lambda x: x.source_tier):
            if e.source_id not in vistas:
                vistas.add(e.source_id)
                fuentes.append({
                    "id": e.source_id,
                    "name": e.source_name,
                    "class": e.source_class,
                    "tier": e.source_tier,
                    "page_url": e.source_url,
                    "post_url": e.url,
                    "icon_url": e.source_icon_url,
                    "published_at": e.published_at,
                })
            if e.url and e.url not in urls:
                urls.append(e.url)

        tiers = sorted({e.source_tier for e in ordenado})
        d["sources"] = fuentes
        d["source_count"] = len(fuentes)
        d["all_urls"] = urls[:12]
        d["corroborated"] = len(fuentes) >= 2
        d["verification"] = _etiqueta_verificacion(tiers, len(fuentes))
        d["confidence"] = _confianza(mejor.confidence, tiers, len(fuentes))
        d["merged_count"] = len(cluster)
        salida.append(d)

    return salida
