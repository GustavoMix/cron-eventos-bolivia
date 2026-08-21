"""Calidad: qué tan completo llegó el evento y cuál se publica.

La prueba de fondo es la comparación: el mismo concierto, uno con afiche, hora,
sede y precio y el otro con nada más que el día, no pueden salir con el mismo
puntaje ni ocupar el mismo lugar en la lista.
"""

from scraper.calidad import (
    MINIMO_PUBLICABLE,
    PESO_CHECKLIST,
    evaluar,
    filtrar,
    resumen,
)


def evento(**kw):
    base = {
        "title": "Los Kjarkas en concierto",
        "description": "x" * 200,
        "starts_at": "2026-08-23T20:00:00-04:00",
        "date_detail": {"has_time": True, "is_estimated": False},
        "date_confidence": "exacta",
        "all_day": False,
        "category": "concierto",
        "city": "Cochabamba",
        "department": "Cochabamba",
        "venue": "Teatro Achá",
        "image_urls": ["https://sitio.bo/afiche.jpg"],
        "is_free": False,
        "price_from": 80.0,
        "ticket_outlets": ["SuperTicket"],
        "confidence": 0.8,
        "source_count": 1,
        "source_tier": 1,
        "status": "programado",
    }
    base.update(kw)
    return base


def test_un_evento_completo_llega_al_nivel_mas_alto():
    calidad = evaluar(evento())
    assert calidad["tier"] == "excelente"
    assert calidad["complete"] is True
    assert calidad["missing"] == []
    assert calidad["publishable"] is True


def test_el_mismo_evento_sin_foto_ni_hora_ni_sede_vale_mucho_menos():
    completo = evaluar(evento())["score"]
    pelado = evaluar(evento(
        image_urls=[], venue=None, address=None, all_day=True,
        date_detail={"has_time": False, "is_estimated": False},
        description="corto",
    ))
    assert pelado["score"] < completo
    assert "Foto del evento" in pelado["missing"]
    assert "Hora de inicio" in pelado["missing"]
    assert "Sede o dirección" in pelado["missing"]


def test_la_checklist_dice_criterio_por_criterio_que_falta():
    calidad = evaluar(evento(image_urls=[]))
    foto = next(c for c in calidad["checks"] if c["key"] == "foto")
    fecha = next(c for c in calidad["checks"] if c["key"] == "fecha")
    assert foto["ok"] is False
    assert fecha["ok"] is True
    # La checklist deja lugar para las bonificaciones: si sumara 100, un evento
    # completo tocaría el techo y no habría con qué desempatar arriba.
    assert sum(c["weight"] for c in calidad["checks"]) == PESO_CHECKLIST


def test_una_fecha_deducida_de_este_viernes_pesa_en_contra():
    exacto = evaluar(evento())["score"]
    deducido = evaluar(evento(
        date_confidence="relativa",
        date_detail={"has_time": True, "is_estimated": True},
    ))["score"]
    assert deducido < exacto


def test_un_evento_confirmado_por_dos_fuentes_sube():
    solo = evaluar(evento())["score"]
    corroborado = evaluar(evento(source_count=3))["score"]
    assert corroborado > solo


def test_lo_que_no_llega_al_minimo_no_se_publica():
    vacio = evento(
        image_urls=[], starts_at=None, date_detail={}, all_day=True,
        venue=None, address=None, city=None, department=None,
        category="otro", is_free=False, price_from=None, ticket_outlets=[],
        description="corto", confidence=0.3,
    )
    assert evaluar(vacio)["score"] < MINIMO_PUBLICABLE

    publicados = filtrar([vacio, evento()])
    assert len(publicados) == 1
    assert publicados[0]["title"] == "Los Kjarkas en concierto"


def test_el_orden_es_cronologico_y_la_calidad_desempata():
    temprano_pobre = evento(
        starts_at="2026-08-20T20:00:00-04:00", image_urls=[], venue=None,
    )
    tarde_bueno = evento(starts_at="2026-08-25T20:00:00-04:00")
    mismo_dia_pobre = evento(
        starts_at="2026-08-25T20:00:00-04:00", venue=None, title="Otro",
    )

    orden = filtrar([tarde_bueno, mismo_dia_pobre, temprano_pobre])
    assert [e["starts_at"][:10] for e in orden] == [
        "2026-08-20", "2026-08-25", "2026-08-25",
    ]
    assert orden[1]["quality_score"] >= orden[2]["quality_score"]


def test_el_resumen_dice_que_es_lo_que_mas_falta():
    eventos = filtrar([evento(image_urls=[]), evento(image_urls=[]), evento()])
    datos = resumen(eventos)
    assert datos["most_missing"][0]["label"] == "Foto del evento"
    assert datos["most_missing"][0]["count"] == 2
    assert 0 < datos["average_score"] <= 100
