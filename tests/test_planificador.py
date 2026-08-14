import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from scraper.planificador import (
    actualizar_rotacion,
    cargar_rotacion,
    matriz_github,
    planificar_grupos,
    puntaje,
    resumen_cobertura,
)

TZ = ZoneInfo("America/La_Paz")
AHORA = datetime(2026, 8, 14, 10, 0, tzinfo=TZ)


def fuentes(n, clase="media", tier=3):
    return [
        {"id": f"fb_{i:02d}", "name": f"Fuente {i}", "source_class": clase, "tier": tier}
        for i in range(n)
    ]


def test_grupos_respetan_el_tamano():
    plan = planificar_grupos(fuentes(20), {}, tamano_grupo=2, max_grupos=20,
                             grupos_solos=0, ahora=AHORA)
    assert all(len(g["fuentes"].split(",")) <= 2 for g in plan["grupos"])
    assert plan["fuentes_en_esta_ola"] == 20


def test_los_grupos_solos_llevan_una_sola_fuente():
    plan = planificar_grupos(fuentes(20), {}, tamano_grupo=2, max_grupos=14,
                             grupos_solos=6, ahora=AHORA)
    solos = plan["grupos"][:6]
    assert all(len(g["fuentes"].split(",")) == 1 for g in solos)


def test_nunca_se_pasa_del_maximo_de_grupos():
    plan = planificar_grupos(fuentes(100), {}, tamano_grupo=2, max_grupos=20,
                             grupos_solos=6, ahora=AHORA)
    assert len(plan["grupos"]) <= 20


def test_lo_que_no_entra_queda_postergado_y_no_se_pierde():
    todas = fuentes(60)
    plan = planificar_grupos(todas, {}, tamano_grupo=2, max_grupos=20,
                             grupos_solos=6, ahora=AHORA)
    # 6 solas + 14 grupos x 2 = 34 en esta ola; las otras 26 esperan turno.
    assert plan["fuentes_en_esta_ola"] == 34
    assert len(plan["postergadas"]) == 26

    en_grupos = {f for g in plan["grupos"] for f in g["fuentes"].split(",")}
    assert en_grupos.isdisjoint(set(plan["postergadas"]))
    assert len(en_grupos) + len(plan["postergadas"]) == len(todas)


def test_la_ola_siguiente_atiende_a_las_postergadas():
    todas = fuentes(60)
    primera = planificar_grupos(todas, {}, tamano_grupo=2, max_grupos=20,
                                grupos_solos=6, ahora=AHORA)

    # Las que sí se leyeron quedan con éxito reciente; las postergadas siguen
    # sin registro y por lo tanto envejeciendo.
    atendidas = {f for g in primera["grupos"] for f in g["fuentes"].split(",")}
    rotacion = {sid: {"ultimo_exito": AHORA.isoformat()} for sid in atendidas}

    despues = AHORA + timedelta(hours=3)
    segunda = planificar_grupos(todas, rotacion, tamano_grupo=2, max_grupos=20,
                                grupos_solos=6, ahora=despues)
    en_segunda = {f for g in segunda["grupos"] for f in g["fuentes"].split(",")}

    # Todas las postergadas de la primera ola entran en la segunda.
    assert set(primera["postergadas"]).issubset(en_segunda)


def test_una_ticketera_le_gana_a_un_medio_con_la_misma_antiguedad():
    ticketera = {"id": "fb_t", "source_class": "ticketera", "tier": 1}
    medio = {"id": "fb_m", "source_class": "media", "tier": 3}
    assert puntaje(ticketera, {}, AHORA) > puntaje(medio, {}, AHORA)


def test_la_fuente_mas_antigua_sube_al_primer_turno():
    dos = [
        {"id": "fb_reciente", "source_class": "media", "tier": 3},
        {"id": "fb_antigua", "source_class": "media", "tier": 3},
    ]
    rotacion = {
        "fb_reciente": {"ultimo_exito": (AHORA - timedelta(hours=1)).isoformat()},
        "fb_antigua": {"ultimo_exito": (AHORA - timedelta(days=4)).isoformat()},
    }
    plan = planificar_grupos(dos, rotacion, tamano_grupo=1, max_grupos=2,
                             grupos_solos=0, ahora=AHORA)
    assert plan["grupos"][0]["fuentes"] == "fb_antigua"


def test_una_fuente_que_falla_seguido_baja_de_prioridad():
    sana = {"id": "fb_sana", "source_class": "media", "tier": 3}
    rota = {"id": "fb_rota", "source_class": "media", "tier": 3}
    rotacion = {
        "fb_sana": {"ultimo_exito": (AHORA - timedelta(hours=10)).isoformat()},
        "fb_rota": {
            "ultimo_exito": (AHORA - timedelta(hours=12)).isoformat(),
            "fallos_seguidos": 5,
        },
    }
    assert puntaje(sana, rotacion, AHORA) > puntaje(rota, rotacion, AHORA)


def test_matriz_github_es_json_de_una_linea():
    plan = planificar_grupos(fuentes(4), {}, tamano_grupo=2, max_grupos=4,
                             grupos_solos=0, ahora=AHORA)
    salida = matriz_github(plan["grupos"])
    assert "\n" not in salida
    assert json.loads(salida)["include"][0]["nombre"] == "g01"


def test_el_bloqueo_no_penaliza_a_la_fuente(tmp_path):
    ruta = tmp_path / "rotacion.json"
    resultados = {
        "fb_bloqueada": {"items": [], "error": "Facebook ocultó el contenido público"},
        "fb_rota": {"items": [], "error": "Timeout al cargar la página"},
        "fb_ok": {"items": [object()], "error": None},
        "fb_omitida": {"items": [], "error": "Omitida: se agotó el presupuesto"},
    }
    estado = actualizar_rotacion(ruta, resultados, AHORA.isoformat())

    assert estado["fb_bloqueada"]["ultimo_estado"] == "bloqueada"
    assert "fallos_seguidos" not in estado["fb_bloqueada"]
    assert "ultimo_exito" not in estado["fb_bloqueada"]

    assert estado["fb_rota"]["fallos_seguidos"] == 1
    assert estado["fb_ok"]["ultimo_estado"] == "ok"
    assert estado["fb_omitida"]["ultimo_estado"] == "omitida"

    assert cargar_rotacion(ruta) == estado


def test_una_fuente_que_carga_sin_novedades_gasta_su_turno(tmp_path):
    ruta = tmp_path / "rotacion.json"
    estado = actualizar_rotacion(
        ruta, {"fb_x": {"items": [], "error": None}}, AHORA.isoformat()
    )
    assert estado["fb_x"]["ultimo_estado"] == "sin_publicaciones"
    assert estado["fb_x"]["ultimo_exito"] == AHORA.isoformat()


def test_resumen_de_cobertura():
    todas = fuentes(3)
    rotacion = {
        "fb_00": {"ultimo_exito": (AHORA - timedelta(hours=2)).isoformat()},
        "fb_01": {"ultimo_estado": "bloqueada"},
    }
    resumen = resumen_cobertura(rotacion, todas, ahora=AHORA)
    assert resumen["fuentes_totales"] == 3
    assert resumen["con_datos_alguna_vez"] == 1
    assert resumen["nunca_vistas"] == ["fb_01", "fb_02"]
    assert resumen["bloqueadas_en_la_ultima_corrida"] == ["fb_01"]
