from datetime import datetime
from zoneinfo import ZoneInfo

from scraper.clasificador import (
    analizar,
    construir_evento,
    detectar_categoria,
    detectar_estado,
    extraer_artistas,
    extraer_precios,
    extraer_puntos_venta,
    extraer_telefonos,
)
from scraper.models import RawItem

TZ = ZoneInfo("America/La_Paz")
AHORA = datetime(2026, 8, 14, 10, 0, tzinfo=TZ)
SCRAPED = AHORA.isoformat(timespec="seconds")


def item(texto, **kwargs):
    base = dict(
        source_id="fb_test", source_name="Fuente de prueba",
        source_url="https://www.facebook.com/test/",
        item_url="https://www.facebook.com/test/posts/123",
        text=texto, tier=2, source_class="eventos",
        image_urls=["https://scontent.example/afiche.jpg"],
    )
    base.update(kwargs)
    return RawItem(**base)


AFICHE_CONCIERTO = """🎸 ¡GRAN CONCIERTO! 🎸
Los Kjarkas en vivo
📅 Sábado 23 de agosto
🕗 20:00 hrs · Puertas 19:00
📍 Teatro Achá
🎟️ Preventa Bs 80 / En puerta Bs 120
Entradas en SuperTicket y Farmacorp
¡No te lo pierdas! Informes 70123456
#Kjarkas #Cochabamba
"""

CRONICA_PASADA = """Gracias a todos los que nos acompañaron anoche en el
concierto del Teatro Achá. Fue un éxito total. Así se vivió la noche del
12 de agosto con más de 2000 personas. Revive los mejores momentos.
"""

NOTA_POLICIAL = """La Policía informó que se registró un accidente de tránsito
en la avenida Blanco Galindo el 13 de agosto. Un detenido fue aprehendido tras
el hecho. Se recomienda precaución a los conductores.
"""


def test_afiche_de_concierto_se_acepta():
    a = analizar(item(AFICHE_CONCIERTO), ahora=AHORA)
    assert a["accepted"] is True
    assert a["category"] == "concierto"
    assert a["score"] >= 80


def test_cronica_de_evento_pasado_se_rechaza():
    a = analizar(item(CRONICA_PASADA), ahora=AHORA)
    assert a["accepted"] is False
    assert "lenguaje_en_pasado" in a["reasons"]


def test_nota_policial_se_rechaza():
    a = analizar(item(NOTA_POLICIAL), ahora=AHORA)
    assert a["accepted"] is False


def test_texto_muy_corto_se_rechaza():
    a = analizar(item("Hola"), ahora=AHORA)
    assert a["accepted"] is False
    assert a["reason"] == "texto_muy_corto"


def test_sin_fecha_ni_enlace_no_es_utilizable():
    a = analizar(item(
        "Gran concierto de rock en el Teatro Achá, entradas Bs 50, te esperamos"
    ), ahora=AHORA)
    assert a["accepted"] is False
    assert a["reason"] == "sin_fecha_ni_enlace_de_evento"


def test_sin_fecha_pero_con_evento_de_facebook_pasa():
    a = analizar(item(
        "Gran concierto de rock en el Teatro Achá, entradas Bs 50, te esperamos",
        facebook_event_url="https://www.facebook.com/events/123456789/",
    ), ahora=AHORA)
    assert a["accepted"] is True


def test_categorias():
    assert detectar_categoria("Obra de teatro: el elenco presenta")[0] == "teatro"
    assert detectar_categoria("Feria del libro en el campo ferial")[0] == "feria"
    assert detectar_categoria("Maratón 10K inscripciones abiertas")[0] == "deporte"
    assert detectar_categoria("Taller de cerámica, cupos limitados")[0] == "taller"
    assert detectar_categoria("Comunicado institucional")[0] == "otro"


def test_precios():
    p = extraer_precios("Preventa Bs 80 / En puerta Bs 120")
    assert p["price_from"] == 80.0
    assert p["price_to"] == 120.0
    assert p["currency"] == "BOB"
    assert p["is_free"] is False


def test_precio_escrito_al_reves():
    p = extraer_precios("La entrada cuesta 50 bolivianos")
    assert p["price_from"] == 50.0


def test_entrada_libre():
    p = extraer_precios("ENTRADA LIBRE para toda la familia")
    assert p["is_free"] is True
    assert p["price_from"] is None


def test_precio_absurdo_se_ignora():
    # "2026" es un año, no un precio; "0" no es una entrada.
    p = extraer_precios("Edición 2026 del festival, entradas Bs 0")
    assert p["price_from"] is None


def test_estado():
    assert detectar_estado("El concierto fue CANCELADO") == "cancelado"
    assert detectar_estado("Se posterga para nueva fecha") == "postergado"
    assert detectar_estado("Entradas agotadas, sold out") == "agotado"
    assert detectar_estado("Nos vemos el sábado") == "programado"


def test_telefonos():
    assert extraer_telefonos("Informes al 70123456 o +591 76543210") == [
        "70123456", "76543210",
    ]


def test_puntos_de_venta():
    puntos = extraer_puntos_venta("Entradas en SuperTicket y Farmacorp, preventa")
    assert "SuperTicket" in puntos
    assert "Farmacorp" in puntos


def test_artistas():
    assert extraer_artistas("Presenta a Luis Rico en concierto") == ["Luis Rico"]


def test_evento_completo():
    evento = construir_evento(item(AFICHE_CONCIERTO), SCRAPED, ahora=AHORA)
    assert evento is not None

    d = evento.to_dict()
    assert d["category"] == "concierto"
    assert d["starts_at"].startswith("2026-08-23T20:00")
    assert isinstance(d["starts_at_ms"], int)
    assert d["display_date"] == "Domingo 23 de agosto · 20:00"
    assert d["doors_time"] == "19:00"
    assert d["venue"] == "Teatro Achá"
    assert d["city"] == "Cochabamba"
    assert d["department"] == "Cochabamba"
    assert d["price_from"] == 80.0
    assert d["lifecycle"] == "proximo"
    assert d["days_until"] == 9
    assert d["has_image"] is True
    assert d["has_video"] is False
    assert d["media"]["image_count"] == 1
    assert "Kjarkas" in d["tags"]
    assert d["location_query"].endswith("Bolivia")


def test_evento_rechazado_devuelve_none():
    assert construir_evento(item(CRONICA_PASADA), SCRAPED, ahora=AHORA) is None


def test_claves_estables_en_el_dict():
    # El contrato con la app depende de que estas claves existan siempre, aunque
    # el evento no tenga el dato: en Kotlin un campo ausente y uno nulo no se
    # deserializan igual.
    d = construir_evento(item(AFICHE_CONCIERTO), SCRAPED, ahora=AHORA).to_dict()
    for clave in [
        "id", "title", "category", "starts_at", "starts_at_ms", "ends_at",
        "display_date", "lifecycle", "department", "city", "venue",
        "is_free", "price_from", "ticket_urls", "image_urls", "image_url",
        "has_image", "has_video", "videos", "media", "status", "confidence",
    ]:
        assert clave in d, f"falta la clave {clave}"
    for clave in ["ticket_urls", "image_urls", "videos", "tags", "artists"]:
        assert isinstance(d[clave], list)


AFICHE_CON_RUIDO_DE_FACEBOOK = """16 reacciones · 3 comentarios
🎸 GRAN CONCIERTO DE LOS KJARKAS EN EL TEATRO
Sábado 23 de agosto · 20:00 hrs
Teatro Achá, Cochabamba
Entradas Bs 80 en SuperTicket https://superticket.bo/kjarkas
Te esperamos
"""

AFICHE_VIEJO = """Concierto de Los Kjarkas
Sábado 12 de julio de 2026, 20:00 hrs
Teatro Achá, Cochabamba
Entradas Bs 80 en SuperTicket, te esperamos
"""


def test_el_contador_de_facebook_no_termina_siendo_el_titulo():
    evento = construir_evento(item(AFICHE_CON_RUIDO_DE_FACEBOOK), SCRAPED, ahora=AHORA)
    assert "reacciones" not in evento.title
    assert "Kjarkas" in evento.title
    # Y el grito se convierte en un título legible.
    assert evento.title == "Gran Concierto de los Kjarkas en el Teatro"


def test_el_evento_no_publica_enlaces_de_compra():
    evento = construir_evento(item(AFICHE_CON_RUIDO_DE_FACEBOOK), SCRAPED, ahora=AHORA)
    assert evento.ticket_urls == []
    assert "superticket.bo" not in evento.description
    # Pero sí dice dónde se consiguen.
    assert "SuperTicket" in evento.ticket_outlets
    assert evento.ticket_info["where_to_buy_label"] == "En SuperTicket"
    assert evento.ticket_info["purchase_links"] is False


def test_un_evento_que_ya_paso_no_entra_al_catalogo():
    # Antes bastaba con tener sede, precio y ticketera para entrar: así llegaban
    # al catálogo conciertos de hace meses.
    assert construir_evento(item(AFICHE_VIEJO), SCRAPED, ahora=AHORA) is None
    assert analizar(item(AFICHE_VIEJO), ahora=AHORA)["reason"] == "el_evento_ya_paso"


def test_el_de_anteayer_sigue_entrando():
    # La app muestra "esta semana" incluyendo lo que recién pasó.
    anteayer = AFICHE_CONCIERTO.replace("Sábado 23 de agosto", "12 de agosto")
    assert construir_evento(item(anteayer), SCRAPED, ahora=AHORA) is not None


def test_el_icono_de_la_pagina_no_entra_como_foto():
    icono = "https://scontent.example/identidad-de-la-pagina.jpg"
    evento = construir_evento(
        item(AFICHE_CONCIERTO,
             image_urls=[icono, "https://scontent.example/afiche-del-show.jpg"],
             source_icon_url=icono),
        SCRAPED, ahora=AHORA,
    )
    assert evento.image_urls == ["https://scontent.example/afiche-del-show.jpg"]


def test_la_fecha_viaja_desarmada_en_el_evento():
    evento = construir_evento(item(AFICHE_CONCIERTO), SCRAPED, ahora=AHORA)
    assert evento.display_date_short == "Dom 23 ago · 20:00"
    assert evento.countdown_label == "En 9 días"
    assert evento.date_detail["weekday"] == "Domingo"
    assert evento.date_detail["doors_label"] == "19:00"


NOTA_JUDICIAL = """La hermana del narcotraficante uruguayo dejó el penal de
Palmasol este 20 de agosto tras la audiencia cautelar. La Fiscalía informó que
seguirá el proceso en libertad. El caso se conocerá el próximo mes.
"""


def test_una_nota_judicial_no_es_un_evento():
    # Traen fecha, ciudad y foto: sin señales negativas entran al catálogo con
    # la misma pinta que un concierto.
    assert construir_evento(item(NOTA_JUDICIAL), SCRAPED, ahora=AHORA) is None
