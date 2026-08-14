"""Estructuras de datos que viajan por el pipeline.

Hay dos niveles:

- `RawItem`: una publicación tal como se leyó de una fuente, sin interpretar.
- `Evento`: esa publicación ya entendida como un evento, con fecha, lugar,
  precio y categoría resueltos. Es lo que termina en el JSON que lee la app.

`Evento.to_dict()` decide el contrato con la app Kotlin y por eso es
deliberadamente aburrido: las mismas claves siempre presentes, las listas nunca
en `null`, los booleanos nunca ausentes y las fechas duplicadas en epoch
milisegundos para que ordenar y filtrar no requiera parsear texto.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RawItem:
    """Una publicación cruda, antes de saber si es un evento siquiera."""

    source_id: str
    source_name: str
    source_url: str
    item_url: str
    text: str
    title: str = ""
    published_at: Optional[str] = None
    region_hint: Optional[str] = None
    city_hint: Optional[str] = None
    source_class: str = "media"
    tier: int = 3

    # Multimedia pública. Nunca se extrae el stream MP4 interno de Facebook: se
    # conserva el enlace público del post/reel y sus miniaturas, que es lo que
    # la app puede abrir o incrustar con el reproductor oficial.
    source_icon_url: Optional[str] = None
    image_urls: List[str] = field(default_factory=list)
    video_url: Optional[str] = None
    video_thumbnail_url: Optional[str] = None
    video_type: Optional[str] = None

    # Específicos de eventos: un post que enlaza a un evento de Facebook o a una
    # ticketera trae la información más confiable que vamos a conseguir, así que
    # esos enlaces se guardan aparte en vez de perderse dentro del texto.
    facebook_event_url: Optional[str] = None
    external_links: List[str] = field(default_factory=list)


@dataclass
class Evento:
    """Un evento entendido, proveniente de una sola publicación."""

    id: str
    source_id: str
    source_name: str
    source_url: str
    source_class: str
    source_tier: int
    source_icon_url: Optional[str]
    url: str
    facebook_event_url: Optional[str]
    published_at: Optional[str]
    scraped_at: str

    # Qué es
    title: str
    description: str
    original_text: str
    category: str
    subcategories: List[str]
    tags: List[str]
    artists: List[str]

    # Cuándo
    starts_at: Optional[str]
    ends_at: Optional[str]
    starts_at_ms: Optional[int]
    ends_at_ms: Optional[int]
    date_confidence: str
    date_source_text: str
    all_day: bool
    multi_day: bool
    doors_time: Optional[str]
    display_date: Optional[str]
    days_until: Optional[int]
    lifecycle: str

    # Dónde
    department: Optional[str]
    city: Optional[str]
    venue: Optional[str]
    address: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    location_query: Optional[str]

    # Cuánto
    is_free: bool
    price_from: Optional[float]
    price_to: Optional[float]
    currency: Optional[str]
    price_text: Optional[str]
    ticket_urls: List[str]
    ticket_outlets: List[str]

    # Cómo contactar
    phones: List[str]

    # Estado y calidad
    status: str
    relevance_score: int
    confidence: float
    filter_reasons: List[str]
    is_official: bool

    # Multimedia
    image_urls: List[str]
    video_url: Optional[str]
    video_thumbnail_url: Optional[str]
    video_type: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.update(_bloque_multimedia(
            self.image_urls,
            [_video_dict(self.video_url, self.video_thumbnail_url, self.video_type, self.source_id)]
            if self.video_url else [],
        ))
        return d


def _video_dict(url: Optional[str], thumbnail: Optional[str],
                tipo: Optional[str], source_id: Optional[str] = None) -> Dict[str, Any]:
    """Un video listo para que la app decida cómo mostrarlo.

    `use_official_embed` le dice a la app que este video se reproduce con el
    reproductor incrustado de Facebook y no descargando un archivo: no existe
    una URL de archivo que se pueda pasar a un reproductor nativo.
    """
    facebook = (tipo or "").startswith("facebook")
    return {
        "url": url,
        "thumbnail_url": thumbnail,
        "type": tipo,
        "provider": "facebook" if facebook else "web",
        "use_official_embed": facebook,
        "source_id": source_id,
    }


def _bloque_multimedia(imagenes: List[str], videos: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Claves de multimedia, siempre completas.

    Se repiten los mismos datos en forma plana (`image_url`, `has_video`) y
    agrupada (`media`) a propósito: la pantalla de lista solo necesita la imagen
    principal y un par de banderas, y la de detalle necesita la galería entera.
    Duplicar unos campos cuesta bytes; obligar a la app a recorrer la galería
    para pintar una miniatura cuesta scroll trabado.
    """
    imagenes = imagenes or []
    videos = videos or []
    return {
        "image_urls": imagenes,
        "image_url": imagenes[0] if imagenes else None,
        "has_image": bool(imagenes),
        "videos": videos,
        "video_url": videos[0]["url"] if videos else None,
        "video_thumbnail_url": videos[0]["thumbnail_url"] if videos else None,
        "has_video": bool(videos),
        "media": {
            "images": imagenes,
            "main_image_url": imagenes[0] if imagenes else None,
            "image_count": len(imagenes),
            "videos": videos,
        },
    }
