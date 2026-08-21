"""Prueba de extremo a extremo, sin red.

Se simula lo que dejarían los jobs de Facebook (el archivo crudo de un grupo) y
se corre el pipeline completo desde ahí: clasificar, fusionar, reconciliar y
escribir los JSON. Es la prueba que verifica el contrato con la app.
"""

import asyncio
import json
from zoneinfo import ZoneInfo

import pytest
import yaml

from scraper.entradas import es_enlace_de_compra
from scraper.runner import correr
from scraper.salida import CAMPOS_LITE

TZ = ZoneInfo("America/La_Paz")

CONFIG = {
    "settings": {
        "timezone": "America/La_Paz",
        "max_items_por_fuente": 20,
        "umbral_fusion": 0.30,
        "umbral_historial": 0.62,
        "conservar_pasados_dias": 4,
        "incluir_finalizados": True,
    },
    "sources": [
        {"id": "fb_teatro", "name": "Teatro Achá", "type": "facebook_public",
         "source_class": "venue", "tier": 1,
         "url": "https://www.facebook.com/teatro/", "region": "Cochabamba",
         "city": "Cochabamba"},
        {"id": "fb_medio", "name": "Diario Opinión", "type": "facebook_public",
         "source_class": "media", "tier": 3,
         "url": "https://www.facebook.com/medio/", "region": "Cochabamba",
         "city": "Cochabamba"},
        {"id": "fb_bloqueada", "name": "Fuente bloqueada", "type": "facebook_public",
         "source_class": "eventos", "tier": 1,
         "url": "https://www.facebook.com/bloqueada/", "region": "Bolivia",
         "city": None},
    ],
}


def _post(source_id, source_name, texto, imagenes, **kw):
    base = {
        "source_id": source_id, "source_name": source_name,
        "source_url": f"https://www.facebook.com/{source_id}/",
        "item_url": f"https://www.facebook.com/{source_id}/posts/1",
        "text": texto, "title": "", "published_at": "2026-08-14T09:00:00-04:00",
        "region_hint": "Cochabamba", "city_hint": "Cochabamba",
        "source_class": "media", "tier": 3,
        "source_icon_url": f"https://img/{source_id}-icono.jpg",
        "image_urls": imagenes, "video_url": None,
        "video_thumbnail_url": None, "video_type": None,
        "facebook_event_url": None, "external_links": [],
    }
    base.update(kw)
    return base


AFICHE = """🎸 LOS KJARKAS EN CONCIERTO
Sábado 23 de agosto · 20:00 hrs
Puertas 19:00
Teatro Achá, Cochabamba
Preventa Bs 80 / En puerta Bs 120
Entradas en SuperTicket y Farmacorp
Comprá acá: https://superticket.bo/los-kjarkas-teatro-acha/
¡Te esperamos! Informes 70123456
"""

NOTA_DEL_MEDIO = """Los Kjarkas se presentan en Cochabamba
El grupo ofrecerá un concierto el 23 de agosto a las 20:00 en el Teatro Achá.
Las entradas ya están a la venta. No te lo pierdas.
"""

FERIA = """FERIA DEL LIBRO DE COCHABAMBA
Del 5 al 7 de septiembre
Campo ferial, entrada libre
Te esperamos, actividades para toda la familia
"""

RUIDO = """Gracias a todos los que nos acompañaron anoche. Fue un éxito total,
así se vivió la noche del 12 de agosto en nuestra sala. Revive los momentos.
"""


@pytest.fixture
def entorno(tmp_path):
    config = tmp_path / "sources.yaml"
    config.write_text(yaml.safe_dump(CONFIG, allow_unicode=True), encoding="utf-8")

    crudo = tmp_path / "raw_g01.json"
    crudo.write_text(json.dumps({
        "scraped_at": "2026-08-14T10:00:00-04:00",
        "results": {
            "fb_teatro": {
                "items": [
                    # El ícono de la página va primero a propósito: es lo que
                    # devuelve el DOM de Facebook y no puede terminar siendo la
                    # foto del evento.
                    _post("fb_teatro", "Teatro Achá", AFICHE,
                          ["https://img/fb_teatro-icono.jpg",
                           "https://img/afiche-kjarkas.jpg"],
                          source_class="venue", tier=1),
                    _post("fb_teatro", "Teatro Achá", FERIA,
                          ["https://img/afiche-feria.jpg"],
                          source_class="venue", tier=1),
                    _post("fb_teatro", "Teatro Achá", RUIDO, []),
                ],
                "error": None,
            },
            "fb_medio": {
                "items": [
                    _post("fb_medio", "Diario Opinión", NOTA_DEL_MEDIO,
                          ["https://img/foto-nota.jpg"]),
                ],
                "error": None,
            },
            "fb_bloqueada": {
                "items": [],
                "error": "Facebook ocultó el contenido público en esta corrida.",
            },
        },
    }, ensure_ascii=False), encoding="utf-8")

    salida = tmp_path / "data"
    return config, crudo, salida


def _correr(config, crudo, salida):
    return asyncio.run(correr(config, salida, only=None, crudos_facebook=[crudo]))


def test_el_pipeline_completo_escribe_los_cuatro_archivos(entorno):
    config, crudo, salida = entorno
    assert _correr(config, crudo, salida) == 0

    for nombre in ["eventos_bolivia.json", "eventos_bolivia_lite.json",
                   "estado_fuentes.json", "eventos_bolivia.csv"]:
        assert (salida / nombre).exists(), f"falta {nombre}"
    assert (salida / "_interno" / "eventos_historial.json").exists()
    assert (salida / "_interno" / "facebook_rotacion.json").exists()


def test_el_concierto_de_dos_fuentes_queda_como_un_solo_evento(entorno):
    config, crudo, salida = entorno
    _correr(config, crudo, salida)

    payload = json.loads((salida / "eventos_bolivia.json").read_text(encoding="utf-8"))
    conciertos = [e for e in payload["events"] if e["category"] == "concierto"]
    assert len(conciertos) == 1

    concierto = conciertos[0]
    assert concierto["source_count"] == 2
    assert concierto["corroborated"] is True
    # Las fotos de las dos fuentes viajan juntas.
    assert len(concierto["image_urls"]) == 2


def test_la_cronica_de_algo_que_ya_paso_no_entra(entorno):
    config, crudo, salida = entorno
    _correr(config, crudo, salida)

    payload = json.loads((salida / "eventos_bolivia.json").read_text(encoding="utf-8"))
    assert not any("Gracias a todos" in (e.get("title") or "") for e in payload["events"])


def test_los_datos_del_afiche_llegan_completos_al_json(entorno):
    config, crudo, salida = entorno
    _correr(config, crudo, salida)

    payload = json.loads((salida / "eventos_bolivia.json").read_text(encoding="utf-8"))
    concierto = next(e for e in payload["events"] if e["category"] == "concierto")

    assert concierto["starts_at"].startswith("2026-08-23T20:00")
    assert isinstance(concierto["starts_at_ms"], int)
    assert concierto["display_date"] == "Domingo 23 de agosto · 20:00"
    assert concierto["doors_time"] == "19:00"
    assert concierto["venue"] == "Teatro Achá"
    assert concierto["city"] == "Cochabamba"
    assert concierto["department"] == "Cochabamba"
    assert concierto["price_from"] == 80.0
    assert concierto["price_label"] == "Bs 80 - 120"
    assert concierto["category_label"] == "Conciertos"
    assert concierto["lifecycle"] == "proximo"
    assert concierto["is_upcoming"] is True
    assert "SuperTicket" in concierto["ticket_outlets"]
    assert concierto["event_id"].startswith("evt_")


def test_la_fecha_llega_desarmada_y_ya_escrita(entorno):
    config, crudo, salida = entorno
    _correr(config, crudo, salida)

    payload = json.loads((salida / "eventos_bolivia.json").read_text(encoding="utf-8"))
    concierto = next(e for e in payload["events"] if e["category"] == "concierto")
    fecha = concierto["date_detail"]

    assert fecha["known"] is True
    assert fecha["weekday"] == "Domingo"
    assert (fecha["day"], fecha["month_label"], fecha["year"]) == (23, "agosto", 2026)
    assert fecha["has_time"] is True
    assert fecha["time_label"] == "20:00"
    assert fecha["doors_label"] == "19:00"
    assert fecha["long_label"] == "Domingo 23 de agosto · 20:00"
    assert concierto["display_date_short"] == "Dom 23 ago · 20:00"
    assert concierto["countdown_label"]
    assert fecha["confidence"] == "exacta"
    assert fecha["is_estimated"] is False
    assert fecha["timezone"] == "America/La_Paz"


def test_la_feria_de_varios_dias_trae_el_rango_desarmado(entorno):
    config, crudo, salida = entorno
    _correr(config, crudo, salida)

    payload = json.loads((salida / "eventos_bolivia.json").read_text(encoding="utf-8"))
    feria = next(e for e in payload["events"] if e["category"] == "feria")
    fecha = feria["date_detail"]

    assert fecha["multi_day"] is True
    assert fecha["days_count"] == 3
    assert fecha["range_label"] == "5 de septiembre — 7 de septiembre"


def test_ningun_campo_del_json_lleva_a_comprar(entorno):
    # La regla es de producto y se verifica como tal: no alcanza con que
    # `ticket_urls` esté vacío, no puede quedar ninguna puerta de salida a un
    # checkout en todo el archivo que consume la app.
    config, crudo, salida = entorno
    _correr(config, crudo, salida)

    for archivo in ("eventos_bolivia.json", "eventos_bolivia_lite.json",
                    "eventos_bolivia.csv"):
        texto = (salida / archivo).read_text(encoding="utf-8")
        for dominio in ("superticket.bo", "passline", "tuentrada", "eventbrite"):
            assert dominio not in texto, f"{archivo} filtra un enlace de compra"

    payload = json.loads((salida / "eventos_bolivia.json").read_text(encoding="utf-8"))

    # Recorrido campo por campo, para que un campo con enlaces que se agregue
    # mañana no se salte la regla sin que nadie se entere. Las imágenes quedan
    # afuera a propósito: el afiche suele estar alojado en el CDN de la
    # ticketera y ahí la app muestra, no navega.
    def _urls(nodo, en_imagen=False):
        if isinstance(nodo, dict):
            for clave, valor in nodo.items():
                yield from _urls(valor, en_imagen or any(
                    x in clave for x in ("image", "thumbnail", "icon", "media")
                ))
        elif isinstance(nodo, list):
            for valor in nodo:
                yield from _urls(valor, en_imagen)
        elif isinstance(nodo, str) and nodo.startswith("http") and not en_imagen:
            yield nodo

    for url in _urls(payload):
        assert not es_enlace_de_compra(url), f"quedó un enlace de compra: {url}"
    assert payload["policy"]["purchase_links"] is False
    assert payload["policy"]["external_redirects"] is False

    concierto = next(e for e in payload["events"] if e["category"] == "concierto")
    assert concierto["ticket_urls"] == []
    # Pero sí dice dónde se consiguen.
    assert concierto["ticket_info"]["where_to_buy_label"].startswith("En ")
    assert "SuperTicket" in concierto["ticket_info"]["where_to_buy"]
    assert concierto["ticket_info"]["purchase_links"] is False


def test_el_icono_de_la_pagina_no_entra_como_foto_del_evento(entorno):
    config, crudo, salida = entorno
    _correr(config, crudo, salida)

    payload = json.loads((salida / "eventos_bolivia.json").read_text(encoding="utf-8"))
    for evento in payload["events"]:
        for url in evento["image_urls"]:
            assert "icono" not in url, f"el ícono de la fuente entró en {evento['title']}"


def test_cada_evento_publicado_trae_su_calidad_evaluada(entorno):
    config, crudo, salida = entorno
    _correr(config, crudo, salida)

    payload = json.loads((salida / "eventos_bolivia.json").read_text(encoding="utf-8"))
    assert payload["quality"]["average_score"] > 0

    for evento in payload["events"]:
        calidad = evento["quality"]
        assert 0 <= calidad["score"] <= 100
        assert calidad["tier"] in {"excelente", "bueno", "aceptable", "incompleto"}
        assert calidad["score"] >= payload["summary"]["quality_min_score"]
        assert len(calidad["checks"]) == 8


def test_la_feria_de_varios_dias_se_lee_como_rango(entorno):
    config, crudo, salida = entorno
    _correr(config, crudo, salida)

    payload = json.loads((salida / "eventos_bolivia.json").read_text(encoding="utf-8"))
    feria = next(e for e in payload["events"] if e["category"] == "feria")

    assert feria["starts_at"].startswith("2026-09-05")
    assert feria["ends_at"].startswith("2026-09-07")
    assert feria["multi_day"] is True
    assert feria["display_date"] == "Del 5 al 7 de septiembre"
    assert feria["is_free"] is True
    assert feria["price_label"] == "Entrada libre"


def test_los_filtros_vienen_contados(entorno):
    config, crudo, salida = entorno
    _correr(config, crudo, salida)

    payload = json.loads((salida / "eventos_bolivia.json").read_text(encoding="utf-8"))
    filtros = payload["filters"]

    categorias = {c["key"]: c for c in filtros["categories"]}
    assert categorias["concierto"]["count"] == 1
    assert categorias["concierto"]["label"] == "Conciertos"
    assert {c["key"] for c in filtros["cities"]} == {"Cochabamba"}
    assert {f["key"] for f in filtros["when"]} == {"hoy", "esta_semana", "este_mes", "todos"}
    assert {f["key"] for f in filtros["price"]} == {"gratis", "pagado", "por_confirmar"}
    assert {f["key"] for f in filtros["media"]} == {"con_foto", "con_galeria", "con_video"}
    assert {f["key"] for f in filtros["quality"]} == {
        "excelente", "bueno", "aceptable", "incompleto"
    }
    assert {g["key"] for g in filtros["ui_groups"]} >= {
        "when", "categories", "departments", "cities", "price", "media", "quality"
    }


def test_la_fuente_bloqueada_se_reporta_como_tal(entorno):
    config, crudo, salida = entorno
    _correr(config, crudo, salida)

    estado = json.loads((salida / "estado_fuentes.json").read_text(encoding="utf-8"))
    bloqueada = next(f for f in estado["sources"] if f["id"] == "fb_bloqueada")
    assert bloqueada["status"] == "blocked"

    payload = json.loads((salida / "eventos_bolivia.json").read_text(encoding="utf-8"))
    assert payload["summary"]["sources_blocked"] == 1
    assert payload["summary"]["sources_ok"] == 2


def test_el_archivo_lite_es_liviano_y_tiene_lo_justo(entorno):
    config, crudo, salida = entorno
    _correr(config, crudo, salida)

    completo = (salida / "eventos_bolivia.json").read_text(encoding="utf-8")
    lite_texto = (salida / "eventos_bolivia_lite.json").read_text(encoding="utf-8")
    lite = json.loads(lite_texto)

    assert len(lite_texto) < len(completo)
    assert lite["events"]
    for evento in lite["events"]:
        assert set(evento.keys()) == set(CAMPOS_LITE)
        assert evento["is_upcoming"] is True


def test_las_claves_del_contrato_estan_siempre(entorno):
    config, crudo, salida = entorno
    _correr(config, crudo, salida)

    payload = json.loads((salida / "eventos_bolivia.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.1"

    obligatorias = [
        "event_id", "title", "description", "category", "category_label",
        "starts_at", "starts_at_ms", "ends_at", "display_date",
        "display_date_short", "countdown_label", "date_detail", "lifecycle",
        "lifecycle_label", "days_until", "is_upcoming", "department", "city",
        "venue", "location_query", "is_free", "price_from", "price_label",
        "ticket_urls", "ticket_outlets", "ticket_info", "image_url",
        "image_urls", "has_image", "has_video", "videos", "media", "status",
        "confidence", "quality", "quality_score", "quality_tier",
        "sources", "source_count", "first_seen_at", "last_seen_at", "history",
    ]
    listas = [
        "image_urls", "videos", "ticket_urls", "ticket_outlets", "tags",
        "artists", "sources",
    ]

    for evento in payload["events"]:
        for clave in obligatorias:
            assert clave in evento, f"falta {clave} en {evento.get('title')}"
        for clave in listas:
            assert isinstance(evento[clave], list), f"{clave} debería ser lista"
        for clave in ["date_detail", "ticket_info", "quality", "media"]:
            assert isinstance(evento[clave], dict), f"{clave} debería ser objeto"


def test_una_segunda_corrida_conserva_los_ids_y_arrastra_el_catalogo(entorno):
    config, crudo, salida = entorno
    _correr(config, crudo, salida)
    primera = json.loads((salida / "eventos_bolivia.json").read_text(encoding="utf-8"))
    ids_primera = {e["event_id"] for e in primera["events"]}

    # Segunda corrida simulando que Facebook bloqueó absolutamente todo.
    vacio = crudo.parent / "raw_vacio.json"
    vacio.write_text(json.dumps({
        "scraped_at": "2026-08-14T13:00:00-04:00",
        "results": {
            sid: {"items": [], "error": "Facebook ocultó el contenido público."}
            for sid in ["fb_teatro", "fb_medio", "fb_bloqueada"]
        },
    }), encoding="utf-8")

    asyncio.run(correr(config, salida, only=None, crudos_facebook=[vacio]))
    segunda = json.loads((salida / "eventos_bolivia.json").read_text(encoding="utf-8"))

    # El catálogo no se vació: los eventos siguen ahí, con los mismos IDs.
    assert {e["event_id"] for e in segunda["events"]} == ids_primera
    assert all(e["seen_this_run"] is False for e in segunda["events"])
    assert segunda["summary"]["sources_blocked"] == 3


def test_una_fuente_postergada_se_reporta_como_omitida_y_no_como_error(entorno):
    # El planificador deja fuentes para la ola siguiente. Que no vengan en el
    # crudo es lo esperado, no una falla — contarlas como error escondería los
    # problemas de verdad.
    config, crudo, salida = entorno
    parcial = crudo.parent / "raw_parcial.json"
    datos = json.loads(crudo.read_text(encoding="utf-8"))
    datos["results"].pop("fb_medio")
    parcial.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")

    asyncio.run(correr(config, salida, only=None, crudos_facebook=[parcial]))

    estado = json.loads((salida / "estado_fuentes.json").read_text(encoding="utf-8"))
    omitida = next(f for f in estado["sources"] if f["id"] == "fb_medio")
    assert omitida["status"] == "skipped"

    payload = json.loads((salida / "eventos_bolivia.json").read_text(encoding="utf-8"))
    assert payload["summary"]["sources_error"] == 0
    assert payload["summary"]["sources_skipped"] == 1


def test_sin_facebook_no_revienta_aunque_no_queden_fuentes(entorno):
    # Red de seguridad del workflow: si ningún job de Facebook entregó nada, la
    # corrida sigue y el catálogo se sostiene con el historial.
    config, crudo, salida = entorno
    _correr(config, crudo, salida)
    antes = json.loads((salida / "eventos_bolivia.json").read_text(encoding="utf-8"))

    assert asyncio.run(correr(config, salida, sin_facebook=True)) == 0
    despues = json.loads((salida / "eventos_bolivia.json").read_text(encoding="utf-8"))

    assert despues["summary"]["sources_total"] == 0
    assert {e["event_id"] for e in despues["events"]} == {
        e["event_id"] for e in antes["events"]
    }


def test_el_csv_sale_bien_formado(entorno):
    config, crudo, salida = entorno
    _correr(config, crudo, salida)

    import csv
    with (salida / "eventos_bolivia.csv").open(encoding="utf-8-sig") as f:
        filas = list(csv.DictReader(f))
    assert filas
    assert all(fila["event_id"] for fila in filas)
