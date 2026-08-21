"""Entradas: decir dónde se compran, sin llevar a nadie a comprar.

Esta es una decisión de producto y está toda acá, en un solo archivo, para que
sea auditable de un vistazo: **el catálogo no publica enlaces de compra**.

Un afiche suele traer un enlace a la ticketera. Si ese enlace viaja en el JSON,
la app termina con un botón que saca al usuario a un checkout de un tercero:
deja de ser una agenda y pasa a ser un intermediario de venta, con todo lo que
eso arrastra —precios que cambian, enlaces que caducan, responsabilidad sobre
una transacción que no controlamos—.

Lo que sí sirve, y es lo que se publica, es **dónde** se consiguen: "en
SuperTicket y Farmacorp", "en boletería del teatro", "preventa y venta en
puerta". Eso es información útil escrita en texto, que el usuario resuelve por
su cuenta, y no un embudo hacia una transacción.

Entonces:

- `ticket_urls` existe en el contrato pero viaja **siempre vacío**. Se conserva
  la clave para no romper el `data class` de Kotlin que ya la deserializa.
- Cualquier URL que apunte a una ticketera o a un checkout se filtra de todos
  los campos de enlaces antes de escribir el JSON.
- `ticket_info.where_to_buy` lleva los puntos de venta en texto, y
  `ticket_info.purchase_links` va en `false` para que quede explícito que la app
  no tiene a dónde redirigir aunque quisiera.
"""

import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

# Vendedores de entradas y pasarelas de pago. Se buscan **en el host**, no en la
# URL entera: `facebook.com/SuperTicketBol/posts/123` es el anuncio de un
# evento publicado por la ticketera en su página, no un checkout, y filtrarlo
# dejaría al evento sin la publicación de origen a cambio de nada.
DOMINIOS_DE_COMPRA = [
    "superticket", "ticketbo", "ticket.bo", "tuentrada", "passline",
    "ticketeg", "eventbrite", "bandsintown", "ticketmaster", "boleteria",
    "entradas.com", "ticketera", "tickets.",
    "paypal", "mercadopago", "stripe.com", "checkout.",
    "wa.me", "api.whatsapp.com",  # los "escribinos para comprar"
]

# Rutas que delatan un checkout aunque el host no esté en la lista. Se buscan
# **en el camino**, no en el query: un `?ref=/comprar` cualquiera no convierte
# en tienda a la agenda de un municipio.
RUTAS_DE_COMPRA = [
    "/comprar", "/compra", "/carrito", "/cart", "/buy", "/pagar", "/payment",
    "/pago", "/orden", "/order", "/entradas/", "/boleteria", "/checkout",
    "/tickets",
]

# (patrón tal como se escribe, nombre tal como se muestra).
PUNTOS_VENTA: List[Tuple[str, str]] = [
    (r"\bfarmacorp\b", "Farmacorp"),
    (r"\bsuper ?ticket\b", "SuperTicket"),
    (r"\bticket\.?bo\b", "Ticket.bo"),
    (r"\btu ?entrada\b", "Tu Entrada"),
    (r"\bpassline\b", "Passline"),
    (r"\bticketeg\b", "Ticketeg"),
    (r"\bboleter[ií]a\b", "Boletería del lugar"),
    (r"\bpuntos? de venta\b", "Puntos de venta autorizados"),
    (r"\bpreventa\b", "Preventa"),
    (r"\ben puerta\b", "Venta en puerta"),
    (r"\bfarmacias?\b", "Farmacias"),
    (r"\bventa en el lugar\b", "Venta en el lugar"),
    (r"\bwhats ?app\b", "Por WhatsApp con el organizador"),
    (r"\binscripci[oó]n(?:es)? (?:abiertas?|en l[ií]nea)\b", "Inscripción previa"),
]

_URL = re.compile(r"https?://[^\s<>\"'\)\]]+", re.IGNORECASE)


def es_enlace_de_compra(url: Optional[str]) -> bool:
    """¿Este enlace lleva a comprar una entrada?

    Ojo con qué se le pasa: esto es para **enlaces**, no para imágenes. El
    afiche de un evento suele estar alojado en el CDN de la ticketera
    (`superticket.bo/media/...jpg`) y esa foto sí se publica —la app la muestra,
    no navega a ella—. Filtrar por host dejaría sin afiche justo a los eventos
    mejor documentados del catálogo.
    """
    bajo = (url or "").strip().lower()
    if not bajo:
        return False

    try:
        partes = urlsplit(bajo)
    except ValueError:
        return False

    host = partes.netloc or ""
    camino = partes.path or ""
    if not host:
        # Un fragmento suelto ("/comprar/entradas") sin host: se juzga por la ruta.
        camino = bajo

    return (any(d in host for d in DOMINIOS_DE_COMPRA)
            or any(r in camino for r in RUTAS_DE_COMPRA))


def sin_enlaces_de_compra(urls: Optional[List[str]]) -> List[str]:
    """La misma lista, sin nada que redirija a una venta."""
    return [u for u in (urls or []) if u and not es_enlace_de_compra(u)]


def limpiar_texto(texto: str) -> str:
    """Saca las URLs de compra del texto que se publica.

    La descripción de un evento se muestra tal cual en el detalle. Dejar ahí un
    `https://superticket.bo/...` es publicar el enlace igual, solo que sin
    botón: el teléfono lo convierte en enlace tocable y estamos en el mismo
    lugar. Se reemplaza por el nombre del punto de venta, que es el dato que de
    verdad importaba.
    """
    def _reemplazo(m):
        return "" if es_enlace_de_compra(m.group(0)) else m.group(0)

    limpio = _URL.sub(_reemplazo, texto or "")
    return re.sub(r"[ \t]{2,}", " ", limpio).strip()


def detectar_puntos_venta(texto: str, plano: str) -> List[str]:
    """Dónde se consiguen las entradas, en nombres presentables.

    `plano` es el texto sin tildes y en minúsculas (lo arma el clasificador);
    se recibe hecho para no normalizar dos veces el mismo afiche.
    """
    nombres, vistos = [], set()
    for patron, nombre in PUNTOS_VENTA:
        if re.search(patron, plano) and nombre.lower() not in vistos:
            vistos.add(nombre.lower())
            nombres.append(nombre)
    return nombres[:6]


# Todos los campos del evento que pueden llevar una URL. La lista está acá y no
# repartida por el pipeline para que agregar un campo con enlaces no se olvide
# de pasar por el filtro.
CAMPOS_CON_ENLACE = ["url", "ticket_urls", "all_urls"]


def sanear_evento(evento: Dict[str, Any]) -> Dict[str, Any]:
    """Deja el evento sin un solo enlace que lleve a comprar.

    Se aplica al final, sobre el diccionario ya armado, y también sobre lo que
    viene del historial: un evento archivado por una corrida vieja puede traer
    enlaces guardados con las reglas de antes, y el catálogo que se publica hoy
    tiene que cumplir la política de hoy.

    Cuando el enlace principal del evento *era* la ficha de la ticketera, el
    evento se queda sin "ver más" y con `has_source_link` en `false`. Es a
    propósito: toda la información —fecha, sede, precio, dónde se compra— ya
    viaja en el JSON, así que no se pierde nada más que el redirect.
    """
    # `source_url` es la portada de la fuente, y varias fuentes del catálogo
    # SON ticketeras: sin esto, cada evento leído de una ticketera seguía
    # llevando su portada encima.
    for clave in ("url", "source_url", "facebook_event_url"):
        if evento.get(clave) and es_enlace_de_compra(evento[clave]):
            evento[clave] = None

    evento["ticket_urls"] = []
    evento["all_urls"] = sin_enlaces_de_compra(evento.get("all_urls"))

    for fuente in evento.get("sources") or []:
        for clave in ("post_url", "page_url"):
            if fuente.get(clave) and es_enlace_de_compra(fuente[clave]):
                fuente[clave] = None

    for clave in ("description", "original_text"):
        if evento.get(clave):
            evento[clave] = limpiar_texto(evento[clave])

    evento["has_source_link"] = bool(evento.get("url") or evento.get("facebook_event_url"))
    return evento


def _monto(valor: float):
    """"Bs 80", no "Bs 80.0": las entradas se cobran en enteros y el decimal
    colgando se ve mal en una tarjeta."""
    return int(valor) if float(valor).is_integer() else valor


def etiqueta_de_precio(es_gratis: bool, desde: Optional[float],
                       hasta: Optional[float] = None) -> Optional[str]:
    """El precio ya escrito: "Entrada libre", "Bs 80" o "Bs 80 - 120"."""
    if es_gratis:
        return "Entrada libre"
    if desde is None:
        return None
    if hasta and hasta != desde:
        return f"Bs {_monto(desde)} - {_monto(hasta)}"
    return f"Bs {_monto(desde)}"


def _frase(nombres: List[str]) -> Optional[str]:
    """["SuperTicket", "Farmacorp"] -> "En SuperTicket y Farmacorp"."""
    if not nombres:
        return None
    if len(nombres) == 1:
        return f"En {nombres[0]}"
    return f"En {', '.join(nombres[:-1])} y {nombres[-1]}"


def describir(
    puntos: List[str],
    es_gratis: bool,
    etiqueta_precio: Optional[str] = None,
    estado: str = "programado",
    telefonos: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """El bloque `ticket_info`: todo lo que la app puede decir sobre entradas.

    Sin una sola URL. `purchase_links` y `opens_external_checkout` van siempre
    en `false` y son parte del contrato: la app puede confiar en que no hay nada
    que abrir y pintar la sección como texto informativo.
    """
    puntos = [p for p in (puntos or []) if p]

    if es_gratis:
        nota = "Entrada libre, no se compra."
    elif estado == "agotado":
        nota = "Entradas agotadas según el último anuncio."
    elif estado == "cancelado":
        nota = "Evento cancelado: no compres entradas."
    elif estado == "postergado":
        nota = "Evento postergado: confirmá antes de comprar."
    elif puntos:
        nota = "Consultá precio y disponibilidad directamente en el punto de venta."
    else:
        nota = "El anuncio no dice dónde se consiguen las entradas."

    return {
        "is_free": bool(es_gratis),
        "price_label": etiqueta_precio,
        "where_to_buy": puntos,
        "where_to_buy_label": _frase(puntos),
        "note": nota,
        "contact_phones": list(telefonos or [])[:4],
        # Explícito y a propósito: este catálogo informa, no vende.
        "purchase_links": False,
        "opens_external_checkout": False,
    }
