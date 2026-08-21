"""Fotos: quedarse con el afiche y tirar todo lo demás.

Una tarjeta de evento vive de su foto. El problema es que una página de la que
sacamos el afiche trae, en el mismo HTML, el logo del sitio, el avatar de quien
publicó, los banners de la barra lateral, los íconos de compartir y las
miniaturas de "notas relacionadas". Si se guardan todas en `image_urls`, la app
termina pintando el logo de un diario como si fuera el afiche del concierto —
que es exactamente lo que pasaba antes de este módulo.

Tres trabajos, en este orden:

1. **Descartar** lo que nunca es la foto de un evento: logos, avatares,
   sprites, banners de publicidad, píxeles de tracking, íconos, spinners.
2. **Agrandar**: casi todos los CMS sirven miniaturas recortadas y guardan el
   original a un par de segmentos de distancia. Un afiche de 300×200 se lee
   borroso a pantalla completa y el original suele estar ahí, gratis.
3. **Ordenar y deduplicar**: la misma foto aparece tres veces en tres tamaños.
   La app quiere una galería, no un catálogo de miniaturas repetidas.

Nunca se descarga la imagen: todo se decide por la forma de la URL y, cuando el
scraper pudo medirla en el navegador, por sus dimensiones reales. Bajar cada
candidata para medirla costaría más que todo el resto del scraping junto.
"""

import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Extensiones que sí pueden ser el afiche. `.svg` y `.gif` quedan afuera a
# propósito: en la práctica son íconos y animaciones de interfaz, nunca la foto
# del evento.
EXTENSIONES_VALIDAS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".jfif"}
EXTENSIONES_INVALIDAS = {".svg", ".gif", ".ico", ".bmp", ".tif", ".tiff"}

# Fragmentos que delatan que la imagen es parte de la interfaz del sitio y no
# del contenido. Se buscan en la URL completa, en minúsculas.
RUIDO_EN_URL = [
    "/logo", "logo.", "-logo", "_logo", "isotipo", "favicon", "apple-touch",
    "avatar", "profile_pic", "profilepic", "/perfil/", "gravatar",
    "sprite", "placeholder", "no-image", "noimage", "sin-imagen", "default-",
    "blank.", "spacer", "pixel.", "1x1", "transparent",
    "/emoji", "emoji.php", "rsrc.php", "static.xx.fbcdn.net",
    "/icons/", "/icon-", "icon_", "-icon.", "badge", "boton", "button",
    "/banner", "banner-", "publicidad", "/ads/", "/ad-", "doubleclick",
    "share", "whatsapp", "facebook-f", "instagram-", "twitter-", "tiktok-",
    "loading", "spinner", "ajax-loader", "watermark", "marca-de-agua",
    "qr-", "qrcode", "/qr/",
]

# Palabras del `alt` que descartan la imagen aunque la URL se vea bien.
RUIDO_EN_ALT = [
    "logo", "emoji", "avatar", "foto de perfil", "profile picture",
    "reacción", "reaccion", "reaction", "icono", "icon", "publicidad",
    "advertisement", "banner",
]

# Debajo de esto no es un afiche: es un ícono o una miniatura de listado. Se
# aplica solo cuando conocemos las medidas de verdad (el scraper las midió en
# el navegador); una URL sin medidas no se descarta por tamaño.
LADO_MINIMO = 200
AREA_MINIMA = 200 * 200

# Parámetros de query que solo piden un recorte. Sacarlos suele devolver el
# original; se conservan en los CDN firmados, donde tocarlos rompe el enlace.
PARAMS_DE_RECORTE = {
    "w", "h", "width", "height", "resize", "fit", "crop", "size", "s",
    "thumb", "thumbnail", "itok", "quality", "q", "maxwidth", "maxheight",
    "scale", "zoom",
}

# CDN que firman la URL: cualquier cambio en el query la invalida y devuelve
# 403. Con estos no se toca nada, ni siquiera para "agrandar".
CDN_FIRMADOS = (
    "fbcdn.net", "cdninstagram.com", "licdn.com", "twimg.com",
    "amazonaws.com", "cloudfront.net", "supabase.co", "googleusercontent.com",
)

# --- Reglas para llegar al original ---------------------------------------

# Drupal: /sites/default/files/styles/<estilo>/public/<resto> -> /sites/default/files/<resto>
_DRUPAL = re.compile(r"/styles/[^/]+/public/", re.IGNORECASE)

# WordPress y compañía: foto-1024x768.jpg -> foto.jpg
_SUFIJO_TAMANO = re.compile(r"-\d{2,4}x\d{2,4}(?=\.[a-z]{3,4}$)", re.IGNORECASE)

# Rutas por tamaño: /thumbs/, /small/, /medium/, /150x150/
_CARPETA_MINIATURA = re.compile(
    r"/(?:thumbs?|thumbnails?|miniaturas?|small|medium|mini|cache|resized?"
    r"|\d{2,4}x\d{2,4})/", re.IGNORECASE
)


def _partes(url: str):
    try:
        return urlsplit(url)
    except ValueError:
        return None


def normalizar(url: Optional[str]) -> Optional[str]:
    """La URL lista para guardar, o `None` si no sirve como foto de un evento."""
    if not url:
        return None
    url = str(url).strip().strip('"\'')
    if url.startswith("//"):
        url = "https:" + url
    if not url.lower().startswith(("http://", "https://")):
        return None
    if len(url) > 1200:
        return None

    partes = _partes(url)
    if partes is None or not partes.netloc:
        return None

    camino = partes.path.lower()
    extension = camino[camino.rfind("."):] if "." in camino.rsplit("/", 1)[-1] else ""
    if extension in EXTENSIONES_INVALIDAS:
        return None
    # Sin extensión se acepta: los CDN modernos sirven las fotos por id.
    if extension and extension not in EXTENSIONES_VALIDAS:
        return None
    return url


def es_ruido(url: str, alt: str = "") -> bool:
    """¿Es parte de la interfaz del sitio en vez de la foto del evento?

    Se mira el host y el camino, nunca el query. Los CDN firmados meten hashes
    largos en el query y tarde o temprano uno contiene "share" o "banner" por
    puro azar; descartar el afiche de un concierto por eso sería un error
    invisible y difícil de rastrear.
    """
    partes = _partes(url or "")
    bajo = f"{partes.netloc}{partes.path}".lower() if partes else (url or "").lower()
    if any(x in bajo for x in RUIDO_EN_URL):
        return True
    alt_bajo = (alt or "").lower()
    return any(x in alt_bajo for x in RUIDO_EN_ALT)


def _firmada(url: str) -> bool:
    partes = _partes(url)
    host = (partes.netloc if partes else "").lower()
    return any(host.endswith(cdn) or cdn in host for cdn in CDN_FIRMADOS)


def version_grande(url: str) -> str:
    """La misma foto en su tamaño original, cuando se puede deducir.

    Todas las reglas son puramente de forma de URL y reversibles: si el sitio no
    sigue esa convención, la URL vuelve igual que entró. No se verifica que el
    original exista —eso costaría una petición por imagen— así que las reglas
    son solo las que en la práctica no fallan.
    """
    if not url or _firmada(url):
        return url

    partes = _partes(url)
    if partes is None:
        return url

    camino = _DRUPAL.sub("/", partes.path)
    camino = _SUFIJO_TAMANO.sub("", camino)

    query = [
        (k, v) for k, v in parse_qsl(partes.query, keep_blank_values=True)
        if k.lower() not in PARAMS_DE_RECORTE
    ]
    return urlunsplit((
        partes.scheme, partes.netloc, camino, urlencode(query), "",
    ))


def clave(url: str) -> str:
    """Identidad de la foto, para que tres tamaños de la misma no sean tres fotos.

    Se queda con el nombre del archivo sin el sufijo de tamaño. En los CDN
    firmados eso alcanza y sobra: el nombre lleva el id del archivo y lo que
    cambia entre variantes es la firma, que justamente hay que ignorar.
    """
    partes = _partes(version_grande(url))
    if partes is None:
        return (url or "").lower()

    archivo = partes.path.rsplit("/", 1)[-1].lower()
    archivo = _SUFIJO_TAMANO.sub("", archivo)
    if len(archivo) >= 12:
        return archivo
    # Nombres cortos y repetidos ("1.jpg") necesitan el resto del camino para
    # no colapsar fotos distintas en una sola.
    return f"{partes.netloc.lower()}{partes.path.lower()}"


def puntaje(url: str, ancho: int = 0, alto: int = 0, origen: str = "") -> int:
    """Qué tan probable es que ESTA sea la foto principal del evento.

    El orden importa mucho más que el número: la primera de la lista es la que
    la app pinta en la tarjeta, y una tarjeta con la foto equivocada se ve peor
    que una sin foto.
    """
    valor = 0

    # `og:image` es el sitio diciendo "esta es la imagen de esta página". En un
    # afiche de Facebook o en la ficha de una ticketera, es exactamente el afiche.
    valor += {"og": 60, "jsonld": 55, "post": 30, "articulo": 20, "galeria": 10}.get(origen, 0)

    area = int(ancho or 0) * int(alto or 0)
    if area:
        valor += min(area // 20000, 40)
        if ancho and alto:
            proporcion = max(ancho, alto) / max(1, min(ancho, alto))
            # Los afiches son cuadrados o verticales; una tira de 6:1 es un
            # banner de cabecera.
            if proporcion > 3.0:
                valor -= 30
            elif proporcion <= 1.6:
                valor += 8

    bajo = (url or "").lower()
    if _CARPETA_MINIATURA.search(bajo):
        valor -= 12
    if _SUFIJO_TAMANO.search(bajo):
        valor -= 8
    if any(x in bajo for x in ("original", "full", "large", "grande", "1200", "1080")):
        valor += 6
    return valor


def _medidas_suficientes(ancho: int, alto: int) -> bool:
    if not ancho or not alto:
        return True  # sin medidas no se descarta por tamaño
    if ancho < LADO_MINIMO or alto < LADO_MINIMO:
        return False
    return ancho * alto >= AREA_MINIMA


def elegir(
    candidatas: List[Dict],
    icono_fuente: Optional[str] = None,
    limite: int = 12,
) -> List[str]:
    """La galería final, ya limpia, agrandada, ordenada y sin repetidos.

    Cada candidata es un dict con `url` y, si se conocen, `width`, `height`,
    `alt` y `origen`. Se devuelven URLs sueltas porque es lo que consume el
    resto del pipeline; el orden es la única información que hace falta
    conservar y viaja en la lista misma.
    """
    icono = normalizar(icono_fuente)
    clave_icono = clave(icono) if icono else None

    puntuadas: List[Tuple[int, int, str]] = []
    vistas: set = set()

    for posicion, candidata in enumerate(candidatas or []):
        if isinstance(candidata, str):
            candidata = {"url": candidata}
        url = normalizar(candidata.get("url"))
        if not url:
            continue

        alt = str(candidata.get("alt") or "")
        if es_ruido(url, alt):
            continue

        ancho = int(candidata.get("width") or 0)
        alto = int(candidata.get("height") or 0)
        if not _medidas_suficientes(ancho, alto):
            continue

        grande = version_grande(url)
        k = clave(grande)
        if k in vistas or (clave_icono and k == clave_icono):
            continue
        vistas.add(k)

        # `posicion` desempata: ante igual puntaje gana la que el scraper
        # encontró primero, que es la que está más arriba en la página.
        puntuadas.append((
            -puntaje(grande, ancho, alto, str(candidata.get("origen") or "")),
            posicion,
            grande,
        ))

    puntuadas.sort()
    return [url for _, _, url in puntuadas[:max(1, limite)]]


def limpiar_galeria(urls: List[str], icono_fuente: Optional[str] = None,
                    limite: int = 12) -> List[str]:
    """`elegir` para cuando solo se tienen las URLs y ya vienen en orden.

    Es el camino que usan el clasificador y la fusión, que reciben listas
    planas de corridas anteriores: ahí ya no hay medidas ni `alt`, pero el
    saneado, el agrandado y la deduplicación siguen valiendo.
    """
    return elegir(
        [{"url": u, "origen": "post" if i == 0 else "galeria"}
         for i, u in enumerate(urls or [])],
        icono_fuente,
        limite,
    )


def hay_afiche(urls: List[str]) -> bool:
    return bool(urls)
