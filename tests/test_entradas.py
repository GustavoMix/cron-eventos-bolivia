"""Entradas: decir dónde se compran y no llevar a comprar.

Es una regla de producto, así que se prueba como tal: no alcanza con que
`ticket_urls` esté vacío, tiene que no quedar **ningún** campo del evento por el
que la app pueda abrir un checkout.
"""

import pytest

from scraper.entradas import (
    describir,
    detectar_puntos_venta,
    es_enlace_de_compra,
    etiqueta_de_precio,
    limpiar_texto,
    sanear_evento,
    sin_enlaces_de_compra,
)

COMPRA = [
    "https://superticket.bo/Curso-Inteligencia-Artificial/",
    "https://www.passline.com/eventos/kjarkas",
    "https://tuentrada.com.bo/evento/123",
    "https://www.eventbrite.com/e/456",
    "https://sitio.bo/comprar/entradas",
    "https://wa.me/59170123456",
]

NO_COMPRA = [
    "https://www.facebook.com/teatroacha/posts/123",
    "https://www.lostiempos.com/agenda/cultura/nota",
    "https://municipio.gob.bo/agenda",
]


@pytest.mark.parametrize("url", COMPRA)
def test_reconoce_un_enlace_de_compra(url):
    assert es_enlace_de_compra(url)


@pytest.mark.parametrize("url", NO_COMPRA)
def test_un_enlace_informativo_no_es_de_compra(url):
    assert not es_enlace_de_compra(url)


def test_filtrar_deja_solo_los_informativos():
    assert sin_enlaces_de_compra(COMPRA + NO_COMPRA) == NO_COMPRA


def test_el_texto_publicado_no_lleva_urls_de_compra():
    texto = ("Los Kjarkas en el Teatro Achá.\n"
             "Entradas en https://superticket.bo/kjarkas y en Farmacorp.\n"
             "Más info en https://www.facebook.com/teatroacha/")
    limpio = limpiar_texto(texto)
    assert "superticket.bo/kjarkas" not in limpio
    # Lo útil se queda: el nombre del punto de venta y el enlace informativo.
    assert "Farmacorp" in limpio
    assert "facebook.com/teatroacha" in limpio


def test_los_puntos_de_venta_salen_con_nombre_presentable():
    puntos = detectar_puntos_venta(
        "Entradas en SuperTicket, Farmacorp y boleteria del teatro",
        "entradas en superticket, farmacorp y boleteria del teatro",
    )
    assert "SuperTicket" in puntos
    assert "Farmacorp" in puntos
    assert "Boletería del lugar" in puntos


def test_la_ficha_de_entradas_dice_donde_y_no_a_donde_ir():
    info = describir(["SuperTicket", "Farmacorp"], False, "Bs 80 - 120")
    assert info["where_to_buy"] == ["SuperTicket", "Farmacorp"]
    assert info["where_to_buy_label"] == "En SuperTicket y Farmacorp"
    assert info["purchase_links"] is False
    assert info["opens_external_checkout"] is False
    # Ni una URL en toda la ficha.
    assert "http" not in repr(info)


def test_un_evento_gratis_no_habla_de_comprar():
    info = describir([], True, "Entrada libre")
    assert info["is_free"] is True
    assert "no se compra" in info["note"]


def test_un_evento_cancelado_avisa_antes_de_que_alguien_compre():
    info = describir(["SuperTicket"], False, "Bs 80", estado="cancelado")
    assert "cancelado" in info["note"].lower()


def test_las_etiquetas_de_precio_no_arrastran_decimales():
    assert etiqueta_de_precio(False, 80.0, 120.0) == "Bs 80 - 120"
    assert etiqueta_de_precio(False, 80.0, 80.0) == "Bs 80"
    assert etiqueta_de_precio(False, 12.5, None) == "Bs 12.5"
    assert etiqueta_de_precio(True, None) == "Entrada libre"
    assert etiqueta_de_precio(False, None) is None


def test_el_saneado_deja_al_evento_sin_una_sola_puerta_de_compra():
    evento = sanear_evento({
        "url": "https://superticket.bo/kjarkas",
        "ticket_urls": ["https://superticket.bo/kjarkas"],
        "all_urls": ["https://superticket.bo/kjarkas",
                     "https://www.facebook.com/teatro/posts/1"],
        "facebook_event_url": None,
        "description": "Entradas en https://passline.com/kjarkas",
        "sources": [{"post_url": "https://superticket.bo/kjarkas",
                     "page_url": "https://superticket.bo/"}],
    })

    assert evento["url"] is None
    assert evento["ticket_urls"] == []
    assert evento["all_urls"] == ["https://www.facebook.com/teatro/posts/1"]
    assert evento["sources"][0]["post_url"] is None
    assert "passline" not in evento["description"]
    assert evento["has_source_link"] is False


def test_el_saneado_no_toca_los_enlaces_informativos():
    evento = sanear_evento({
        "url": "https://www.facebook.com/teatroacha/posts/123",
        "facebook_event_url": "https://www.facebook.com/events/999",
        "all_urls": ["https://www.facebook.com/teatroacha/posts/123"],
    })
    assert evento["url"] == "https://www.facebook.com/teatroacha/posts/123"
    assert evento["facebook_event_url"] == "https://www.facebook.com/events/999"
    assert evento["has_source_link"] is True


def test_el_post_de_una_ticketera_en_facebook_no_es_un_checkout():
    # La ticketera publica sus eventos en su página de Facebook. Ese post es el
    # anuncio del evento, no la venta: filtrarlo dejaría al evento sin la
    # publicación de origen a cambio de nada.
    assert not es_enlace_de_compra("https://www.facebook.com/SuperTicketBol/")
    assert not es_enlace_de_compra("https://www.facebook.com/SuperTicketBol/posts/123")


def test_cualquier_dominio_de_la_ticketera_cuenta():
    assert es_enlace_de_compra("https://sucursales.superticket.io/oruro/")
    assert es_enlace_de_compra("https://superticket.bo/evento/kjarkas")


def test_una_ruta_de_compra_en_el_query_no_convierte_en_tienda_a_una_agenda():
    assert not es_enlace_de_compra("https://municipio.gob.bo/agenda?ref=/comprar")
    assert es_enlace_de_compra("https://municipio.gob.bo/comprar/entradas")


def test_el_afiche_alojado_en_la_ticketera_se_publica_igual():
    # Es una imagen: la app la muestra, no navega a ella. Filtrarla por el host
    # dejaría sin foto justo a los eventos mejor documentados del catálogo.
    afiche = "https://superticket.bo/media/imagenes_eventos/2026/08/afiche.jpg"
    evento = sanear_evento({
        "url": "https://www.facebook.com/teatro/posts/1",
        "image_urls": [afiche],
        "all_urls": [],
    })
    assert evento["image_urls"] == [afiche]
