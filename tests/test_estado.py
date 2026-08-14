from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from scraper.estado import (
    cargar_archivo,
    guardar_archivo,
    puntaje_coincidencia,
    recalcular_tiempo,
    reconciliar,
)

TZ = ZoneInfo("America/La_Paz")
AHORA = datetime(2026, 8, 14, 10, 0, tzinfo=TZ)


def ev(titulo, dia, ciudad="Cochabamba", sede="Teatro Achá", **kw):
    base = {
        "title": titulo,
        "starts_at": f"2026-08-{dia:02d}T20:00:00-04:00",
        "ends_at": None,
        "city": ciudad,
        "venue": sede,
        "category": "concierto",
        "description": titulo,
        "artists": [],
        "status": "programado",
        "confidence": 0.8,
        "source_count": 1,
        "url": f"https://fb/{titulo}",
    }
    base.update(kw)
    return base


def test_un_evento_nuevo_recibe_id_estable_y_primera_deteccion(tmp_path):
    archivo = tmp_path / "hist.json"
    salida = reconciliar([ev("Los Kjarkas", 23)], archivo, AHORA.isoformat())

    assert len(salida) == 1
    evento = salida[0]
    assert evento["event_id"].startswith("evt_")
    assert evento["first_seen_at"] == AHORA.isoformat()
    assert evento["seen_this_run"] is True
    assert evento["history"][0]["reason"] == "primera_deteccion"


def test_el_id_se_mantiene_entre_corridas(tmp_path):
    archivo = tmp_path / "hist.json"

    primera = reconciliar([ev("Los Kjarkas", 23)], archivo, AHORA.isoformat())
    guardar_archivo(archivo, primera, AHORA.isoformat())
    id_original = primera[0]["event_id"]

    despues = AHORA + timedelta(hours=3)
    segunda = reconciliar([ev("Los Kjarkas", 23)], archivo, despues.isoformat())

    assert len(segunda) == 1
    assert segunda[0]["event_id"] == id_original
    assert segunda[0]["first_seen_at"] == AHORA.isoformat()


def test_un_evento_que_hoy_nadie_publico_sigue_en_el_catalogo(tmp_path):
    # Esta es la propiedad que hace que el bloqueo de Facebook no rompa la app:
    # el concierto del 23 sigue estando aunque en esta corrida ninguna fuente
    # lo haya vuelto a mencionar.
    archivo = tmp_path / "hist.json"
    primera = reconciliar([ev("Los Kjarkas", 23)], archivo, AHORA.isoformat())
    guardar_archivo(archivo, primera, AHORA.isoformat())

    despues = AHORA + timedelta(hours=6)
    segunda = reconciliar([], archivo, despues.isoformat())

    assert len(segunda) == 1
    assert segunda[0]["title"] == "Los Kjarkas"
    assert segunda[0]["seen_this_run"] is False
    assert segunda[0]["is_upcoming"] is True


def test_los_eventos_ya_pasados_se_van_del_catalogo(tmp_path):
    archivo = tmp_path / "hist.json"
    primera = reconciliar([ev("Los Kjarkas", 14)], archivo, AHORA.isoformat())
    guardar_archivo(archivo, primera, AHORA.isoformat())

    # Diez días después, el evento del 14 ya quedó muy atrás.
    mucho_despues = AHORA + timedelta(days=10)
    segunda = reconciliar([], archivo, mucho_despues.isoformat())
    assert segunda == []


def test_el_ciclo_de_vida_se_recalcula_con_el_paso_del_tiempo(tmp_path):
    archivo = tmp_path / "hist.json"
    primera = reconciliar([ev("Los Kjarkas", 20)], archivo, AHORA.isoformat())
    assert primera[0]["lifecycle"] == "proximo"
    assert primera[0]["days_until"] == 6
    guardar_archivo(archivo, primera, AHORA.isoformat())

    el_dia_del_evento = datetime(2026, 8, 20, 12, 0, tzinfo=TZ)
    segunda = reconciliar([], archivo, el_dia_del_evento.isoformat())
    assert segunda[0]["lifecycle"] == "hoy"
    assert segunda[0]["days_until"] == 0

    al_dia_siguiente = datetime(2026, 8, 21, 12, 0, tzinfo=TZ)
    tercera = reconciliar([], archivo, al_dia_siguiente.isoformat())
    assert tercera[0]["lifecycle"] == "finalizado"
    assert tercera[0]["is_upcoming"] is False


def test_una_cancelacion_queda_registrada_en_el_historial(tmp_path):
    archivo = tmp_path / "hist.json"
    primera = reconciliar([ev("Los Kjarkas", 23)], archivo, AHORA.isoformat())
    guardar_archivo(archivo, primera, AHORA.isoformat())

    despues = AHORA + timedelta(hours=5)
    segunda = reconciliar(
        [ev("Los Kjarkas", 23, status="cancelado")], archivo, despues.isoformat()
    )

    evento = segunda[0]
    assert evento["status"] == "cancelado"
    assert "estado:programado->cancelado" in evento["changed_this_run"]
    assert any("estado:programado->cancelado" in (h.get("changes") or [])
               for h in evento["history"])


def test_el_conteo_de_fuentes_no_retrocede(tmp_path):
    # Si ayer lo confirmaron cuatro fuentes y hoy solo lo vio una porque
    # Facebook bloqueó al resto, el evento no pasa a estar "menos confirmado".
    archivo = tmp_path / "hist.json"
    primera = reconciliar([ev("Los Kjarkas", 23, source_count=4)], archivo, AHORA.isoformat())
    guardar_archivo(archivo, primera, AHORA.isoformat())

    despues = AHORA + timedelta(hours=5)
    segunda = reconciliar([ev("Los Kjarkas", 23, source_count=1)], archivo, despues.isoformat())
    assert segunda[0]["source_count"] == 4


def test_dos_eventos_distintos_no_se_confunden_entre_corridas(tmp_path):
    archivo = tmp_path / "hist.json"
    primera = reconciliar(
        [ev("Los Kjarkas", 23), ev("Bernarda Alba", 23)], archivo, AHORA.isoformat()
    )
    guardar_archivo(archivo, primera, AHORA.isoformat())
    assert len({e["event_id"] for e in primera}) == 2

    despues = AHORA + timedelta(hours=4)
    segunda = reconciliar([ev("Los Kjarkas", 23)], archivo, despues.isoformat())
    assert len(segunda) == 2
    vistos = {e["title"]: e["seen_this_run"] for e in segunda}
    assert vistos["Los Kjarkas"] is True
    assert vistos["Bernarda Alba"] is False


def test_el_catalogo_sale_ordenado_por_fecha(tmp_path):
    archivo = tmp_path / "hist.json"
    salida = reconciliar(
        [ev("Tercero", 28), ev("Primero", 16), ev("Segundo", 20)],
        archivo, AHORA.isoformat(),
    )
    assert [e["title"] for e in salida] == ["Primero", "Segundo", "Tercero"]


def test_los_eventos_sin_fecha_van_al_final(tmp_path):
    archivo = tmp_path / "hist.json"
    salida = reconciliar(
        [ev("Sin fecha", 23, starts_at=None), ev("Con fecha", 23)],
        archivo, AHORA.isoformat(),
    )
    assert [e["title"] for e in salida] == ["Con fecha", "Sin fecha"]
    assert salida[-1]["lifecycle"] == "sin_fecha"


def test_fechas_distintas_nunca_coinciden():
    assert puntaje_coincidencia(ev("Los Kjarkas", 23), ev("Los Kjarkas", 24)) == 0.0


def test_ciudades_distintas_nunca_coinciden():
    a = ev("Los Kjarkas", 23, ciudad="Cochabamba")
    b = ev("Los Kjarkas", 23, ciudad="La Paz")
    assert puntaje_coincidencia(a, b) == 0.0


def test_recalcular_tiempo_sin_fecha():
    d = recalcular_tiempo({"starts_at": None}, AHORA)
    assert d["lifecycle"] == "sin_fecha"
    assert d["days_until"] is None
    assert d["is_upcoming"] is False


def test_guardar_y_cargar_el_archivo(tmp_path):
    archivo = tmp_path / "hist.json"
    guardar_archivo(archivo, [ev("Los Kjarkas", 23)], AHORA.isoformat())
    assert cargar_archivo(archivo)[0]["title"] == "Los Kjarkas"


def test_un_archivo_corrupto_no_rompe_la_corrida(tmp_path):
    archivo = tmp_path / "hist.json"
    archivo.write_text("{esto no es json", encoding="utf-8")
    assert cargar_archivo(archivo) == []
    assert len(reconciliar([ev("Los Kjarkas", 23)], archivo, AHORA.isoformat())) == 1
