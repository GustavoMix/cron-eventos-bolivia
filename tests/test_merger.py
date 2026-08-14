from datetime import datetime
from zoneinfo import ZoneInfo

from scraper.clasificador import construir_evento
from scraper.merger import fusionar, mismo_evento
from scraper.models import RawItem

TZ = ZoneInfo("America/La_Paz")
AHORA = datetime(2026, 8, 14, 10, 0, tzinfo=TZ)
SCRAPED = AHORA.isoformat(timespec="seconds")


def evento(texto, source_id="fb_a", tier=3, clase="media", imagenes=None, **kw):
    item = RawItem(
        source_id=source_id, source_name=f"Fuente {source_id}",
        source_url=f"https://www.facebook.com/{source_id}/",
        item_url=f"https://www.facebook.com/{source_id}/posts/1",
        text=texto, tier=tier, source_class=clase,
        image_urls=imagenes if imagenes is not None else [f"https://img/{source_id}.jpg"],
        **kw,
    )
    e = construir_evento(item, SCRAPED, ahora=AHORA)
    assert e is not None, f"el texto de prueba no pasó el filtro: {texto[:60]}"
    return e


CONCIERTO_TEATRO = """Los Kjarkas en concierto
Sábado 23 de agosto, 20:00 hrs
Teatro Achá
Entradas Bs 80, te esperamos
"""

CONCIERTO_MEDIO = """Los Kjarkas se presentan en Cochabamba
El grupo dará un concierto el 23 de agosto a las 20:00 en el Teatro Achá.
Las entradas están a la venta, no te lo pierdas.
"""

CONCIERTO_OTRO_DIA = """Los Kjarkas en concierto
Domingo 24 de agosto, 20:00 hrs
Teatro Achá
Entradas Bs 80, te esperamos
"""

OBRA_DISTINTA = """Obra de teatro La Casa de Bernarda Alba
Sábado 23 de agosto, 20:00 hrs
Teatro Achá
Entradas Bs 40, te esperamos
"""


def test_el_mismo_concierto_en_dos_fuentes_es_uno_solo():
    a = evento(CONCIERTO_TEATRO, "fb_teatro", tier=1, clase="venue")
    b = evento(CONCIERTO_MEDIO, "fb_medio", tier=3)
    assert mismo_evento(a, b) is True

    fusionados = fusionar([a, b])
    assert len(fusionados) == 1
    assert fusionados[0]["source_count"] == 2
    assert fusionados[0]["corroborated"] is True


def test_eventos_en_dias_distintos_no_se_fusionan():
    a = evento(CONCIERTO_TEATRO, "fb_a")
    b = evento(CONCIERTO_OTRO_DIA, "fb_b")
    assert mismo_evento(a, b) is False
    assert len(fusionar([a, b])) == 2


def test_eventos_distintos_el_mismo_dia_y_sede_no_se_fusionan():
    a = evento(CONCIERTO_TEATRO, "fb_a")
    b = evento(OBRA_DISTINTA, "fb_b")
    assert mismo_evento(a, b) is False


def test_la_fusion_junta_las_fotos_de_todas_las_fuentes():
    a = evento(CONCIERTO_TEATRO, "fb_a", imagenes=["https://img/a1.jpg", "https://img/a2.jpg"])
    b = evento(CONCIERTO_MEDIO, "fb_b", imagenes=["https://img/b1.jpg"])
    d = fusionar([a, b])[0]
    assert set(d["image_urls"]) == {"https://img/a1.jpg", "https://img/a2.jpg", "https://img/b1.jpg"}
    assert d["media"]["image_count"] == 3
    assert d["image_url"] == d["media"]["main_image_url"]


def test_la_fusion_rellena_los_huecos_de_la_mejor_version():
    # El teatro tiene el precio; el medio, no. El evento fusionado se queda con
    # el precio aunque la mejor versión haya sido la del medio.
    sin_precio = evento(
        """Los Kjarkas se presentan en Cochabamba
        Concierto el 23 de agosto a las 20:00 en el Teatro Achá.
        Una noche imperdible, te esperamos, entradas en boletería.
        """, "fb_medio", tier=1)
    con_precio = evento(CONCIERTO_TEATRO, "fb_teatro", tier=3)

    d = fusionar([sin_precio, con_precio])[0]
    assert d["price_from"] == 80.0


def test_una_cancelacion_gana_sobre_los_anuncios_normales():
    normal = evento(CONCIERTO_TEATRO, "fb_a")
    cancelado = evento(
        """Los Kjarkas en concierto CANCELADO
        Sábado 23 de agosto, 20:00 hrs
        Teatro Achá. El show queda sin efecto, se devolverán las entradas Bs 80.
        """, "fb_b")
    d = fusionar([normal, cancelado])[0]
    assert d["status"] == "cancelado"


def test_un_evento_solo_queda_marcado_como_no_corroborado():
    d = fusionar([evento(CONCIERTO_TEATRO)])[0]
    assert d["source_count"] == 1
    assert d["corroborated"] is False
    assert d["verification"] == "una_fuente"
