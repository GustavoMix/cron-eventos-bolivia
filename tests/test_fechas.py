from datetime import datetime
from zoneinfo import ZoneInfo

from scraper.fechas import (
    ciclo_de_vida,
    cuenta_regresiva,
    detalle_de_fecha,
    dias_restantes,
    fecha_corta,
    fecha_legible,
    parsear_fecha,
)

TZ = ZoneInfo("America/La_Paz")


def ahora(anio=2026, mes=8, dia=14, hora=10):
    return datetime(anio, mes, dia, hora, 0, tzinfo=TZ)


def test_dia_de_mes_con_hora():
    f = parsear_fecha("🎸 SÁBADO 23 DE AGOSTO - 20:00 hrs", ahora=ahora())
    assert f.inicio.date().isoformat() == "2026-08-23"
    assert (f.inicio.hour, f.inicio.minute) == (20, 0)
    assert f.confianza == "exacta"
    assert f.todo_el_dia is False


def test_dia_sin_hora_es_aproximada():
    f = parsear_fecha("Gran feria el 30 de agosto en la plaza", ahora=ahora())
    assert f.inicio.date().isoformat() == "2026-08-30"
    assert f.todo_el_dia is True
    assert f.confianza == "aproximada"
    assert "sin_hora_en_el_texto" in f.avisos


def test_infiere_el_anio_siguiente_cuando_el_mes_ya_paso():
    f = parsear_fecha("Festival del 10 de marzo", ahora=ahora(mes=8))
    assert f.inicio.year == 2027


def test_respeta_dias_de_gracia_hacia_atras():
    # Un afiche del 12 de agosto leído el 14 habla del evento que recién pasó,
    # no del mismo día del año que viene.
    f = parsear_fecha("Concierto 12 de agosto", ahora=ahora(dia=14))
    assert f.inicio.year == 2026
    assert f.inicio.month == 8


def test_anio_explicito_manda():
    f = parsear_fecha("23 de agosto de 2027, 19:00", ahora=ahora())
    assert f.inicio.year == 2027


def test_rango_en_el_mismo_mes():
    f = parsear_fecha("Del 5 al 7 de septiembre, Feria del Libro", ahora=ahora())
    assert f.inicio.date().isoformat() == "2026-09-05"
    assert f.fin.date().isoformat() == "2026-09-07"
    assert f.multidia is True


def test_rango_que_cruza_de_mes():
    f = parsear_fecha("Expo del 28 de agosto al 2 de septiembre", ahora=ahora())
    assert f.inicio.date().isoformat() == "2026-08-28"
    assert f.fin.date().isoformat() == "2026-09-02"
    assert f.multidia is True


def test_rango_gana_a_la_fecha_suelta_que_contiene():
    # "del 5 al 7 de septiembre" contiene un "7 de septiembre"; si ganara la
    # fecha suelta se perdería el día de inicio del festival.
    f = parsear_fecha("Del 5 al 7 de septiembre", ahora=ahora())
    assert f.inicio.day == 5


def test_formato_numerico():
    f = parsear_fecha("15/03/2027 | 21:00", ahora=ahora())
    assert f.inicio.date().isoformat() == "2027-03-15"
    assert f.inicio.hour == 21


def test_puertas_y_show_son_datos_distintos():
    f = parsear_fecha(
        "Este viernes en el Teatro Achá. Puertas 19:30, show 21:00",
        ahora=ahora(), publicado_en=ahora(),
    )
    assert f.inicio.hour == 21
    assert f.hora_puertas == "19:30"


def test_solo_hora_de_puertas_sirve_como_hora_del_evento():
    f = parsear_fecha("20 de agosto, puertas 18:00", ahora=ahora())
    assert f.inicio.hour == 18
    assert f.hora_puertas == "18:00"


def test_hoy_y_manana_se_anclan_a_la_publicacion():
    publicado = datetime(2026, 8, 10, 9, 0, tzinfo=TZ)
    f = parsear_fecha("¡Hoy nos vemos! 20:00", ahora=ahora(), publicado_en=publicado)
    assert f.inicio.date().isoformat() == "2026-08-10"
    assert f.confianza == "relativa"


def test_este_viernes_cae_en_el_proximo_viernes():
    # 14/08/2026 es viernes; "este viernes" dicho ese día es ese mismo día.
    f = parsear_fecha("Este viernes 21:00", ahora=ahora(dia=14), publicado_en=ahora(dia=14))
    assert f.inicio.date().isoformat() == "2026-08-14"


def test_proximo_viernes_empuja_una_semana():
    f = parsear_fecha("Próximo viernes 21:00", ahora=ahora(dia=14), publicado_en=ahora(dia=14))
    assert f.inicio.date().isoformat() == "2026-08-21"


def test_hora_sin_sufijo_se_asume_de_la_noche():
    f = parsear_fecha("23 de agosto a las 8", ahora=ahora())
    assert f.inicio.hour == 20


def test_am_explicito_se_respeta():
    f = parsear_fecha("23 de agosto a las 8:00 am", ahora=ahora())
    assert f.inicio.hour == 8


def test_sin_fecha_devuelve_desconocida():
    f = parsear_fecha("Gracias a todos por acompañarnos anoche", ahora=ahora())
    assert f.tiene_fecha is False
    assert f.confianza == "desconocida"


def test_fecha_legible_de_un_dia():
    f = parsear_fecha("23 de agosto 20:00", ahora=ahora())
    assert fecha_legible(f) == "Domingo 23 de agosto · 20:00"


def test_fecha_legible_de_un_rango():
    f = parsear_fecha("Del 5 al 7 de septiembre", ahora=ahora())
    assert fecha_legible(f) == "Del 5 al 7 de septiembre"


def test_ciclo_de_vida():
    futuro = parsear_fecha("30 de agosto 20:00", ahora=ahora())
    assert ciclo_de_vida(futuro, ahora=ahora()) == "proximo"

    hoy = parsear_fecha("14 de agosto 20:00", ahora=ahora())
    assert ciclo_de_vida(hoy, ahora=ahora()) == "hoy"

    # Un evento que empezó hace una hora sigue siendo "hoy", no "finalizado".
    assert ciclo_de_vida(hoy, ahora=ahora(hora=21)) == "hoy"

    festival = parsear_fecha("Del 12 al 20 de agosto", ahora=ahora())
    assert ciclo_de_vida(festival, ahora=ahora()) == "en_curso"

    pasado = parsear_fecha("2 de agosto de 2026 20:00", ahora=ahora())
    assert ciclo_de_vida(pasado, ahora=ahora()) == "finalizado"


def test_dias_restantes():
    f = parsear_fecha("20 de agosto 20:00", ahora=ahora(dia=14))
    assert dias_restantes(f, ahora=ahora(dia=14)) == 6


def test_fecha_iso_de_schema_org_con_la_hora_pegada():
    # `startDate` de schema.org viene así, y es la fecha más confiable del
    # catálogo: si esta no se lee, las ticketeras no aportan nada.
    f = parsear_fecha("EL VAR La Gran Final\n2026-09-19T15:00:00-04:00\nLa Paz",
                      ahora=ahora())
    assert f.inicio.date().isoformat() == "2026-09-19"
    assert (f.inicio.hour, f.inicio.minute) == (15, 0)
    assert f.todo_el_dia is False


def test_un_anio_imposible_no_se_toma_como_fecha():
    # El "© 2019" del pie de página no puede fechar un evento.
    f = parsear_fecha("Concierto · © 2019 Todos los derechos\n5 de octubre",
                      ahora=ahora())
    assert f.inicio.year == 2026


def test_una_fecha_iso_vieja_del_html_se_ignora():
    f = parsear_fecha("Nota publicada 2019-03-04. Feria el 5 de octubre",
                      ahora=ahora())
    assert f.inicio.date().isoformat() == "2026-10-05"


def test_la_fecha_corta_entra_en_un_chip():
    f = parsear_fecha("23 de agosto 20:00", ahora=ahora())
    assert fecha_corta(f) == "Dom 23 ago · 20:00"


def test_la_cuenta_regresiva_se_lee_como_una_agenda():
    hoy = parsear_fecha("14 de agosto 20:00", ahora=ahora())
    assert cuenta_regresiva(hoy, ahora=ahora()) == "Hoy"

    manana = parsear_fecha("15 de agosto 20:00", ahora=ahora())
    assert cuenta_regresiva(manana, ahora=ahora()) == "Mañana"

    proximo = parsear_fecha("20 de agosto 20:00", ahora=ahora())
    assert cuenta_regresiva(proximo, ahora=ahora()) == "En 6 días"

    festival = parsear_fecha("Del 12 al 20 de agosto", ahora=ahora())
    assert cuenta_regresiva(festival, ahora=ahora()) == "En curso"


def test_el_detalle_trae_la_fecha_desarmada_y_escrita():
    f = parsear_fecha("Sábado 23 de agosto 20:00 hrs, puertas 19:00", ahora=ahora())
    d = detalle_de_fecha(f, ahora=ahora())

    assert d["known"] is True
    assert (d["weekday"], d["weekday_short"]) == ("Domingo", "Dom")
    assert (d["day"], d["month_label"], d["month_short"], d["year"]) == (
        23, "agosto", "ago", 2026,
    )
    assert d["time_label"] == "20:00"
    assert d["doors_label"] == "19:00"
    assert d["long_label"] == "Domingo 23 de agosto · 20:00"
    assert d["countdown_label"] == "En 9 días"
    assert d["confidence_label"] == "Fecha y hora confirmadas"
    assert d["is_estimated"] is False


def test_el_detalle_sin_fecha_igual_trae_todas_las_claves():
    f = parsear_fecha("Gracias por acompañarnos", ahora=ahora())
    d = detalle_de_fecha(f, ahora=ahora())
    assert d["known"] is False
    for clave in ["weekday", "day", "month_label", "year", "time_label",
                  "long_label", "short_label", "countdown_label"]:
        assert clave in d and d[clave] is None


def test_el_anio_aparece_solo_cuando_no_es_el_de_este_ano():
    este_ano = parsear_fecha("23 de agosto 20:00", ahora=ahora())
    assert "de 2026" not in fecha_legible(este_ano, ahora=ahora())

    el_que_viene = parsear_fecha("10 de marzo 20:00", ahora=ahora())
    assert fecha_legible(el_que_viene, ahora=ahora()).endswith(
        "10 de marzo de 2027 · 20:00"
    )
