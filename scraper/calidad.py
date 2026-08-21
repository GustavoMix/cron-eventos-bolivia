"""¿Este evento está lo bastante completo como para mostrarlo?

El clasificador ya decidió que la publicación **es** un evento. Esta es la otra
pregunta, y es la que decide cómo se ve la app: un evento con afiche, día, hora,
sede y precio se pinta en una tarjeta que da ganas de tocar; el mismo evento sin
foto ni hora ni lugar es una línea de texto gris que solo estorba entre las
buenas.

La diferencia con `relevance_score` es de fondo. Aquel mide *confianza*: qué tan
seguros estamos de que esto es un evento real y futuro. Este mide *completitud*:
cuánto de lo que la app necesita pintar llegó de verdad. Un aviso de una fuente
oficial que solo dice "concierto el sábado" tiene relevancia alta y calidad
baja, y las dos cosas son ciertas al mismo tiempo.

El puntaje se publica entero —con el detalle de qué falta y qué no— en vez de
usarse solo como un filtro secreto. Así la app puede ordenar por él, mostrar los
buenos primero y decidir por su cuenta dónde poner el corte, y el diagnóstico
dice *qué* le falta al catálogo y no solo cuánto.
"""

from typing import Any, Dict, List, Optional

# (clave, peso, etiqueta). Los pesos están ordenados por lo que de verdad cambia
# la experiencia: sin foto y sin fecha no hay tarjeta que valga, y todo lo demás
# la mejora de a poco.
#
# Suman 88 y no 100 a propósito: los 12 puntos que quedan son para las
# bonificaciones. Si la checklist llegara a 100 por sí sola, un evento completo
# tocaría el techo y ya nada podría distinguir al que además tiene galería,
# video y tres fuentes que lo confirman — que es justamente el que la app
# debería mostrar primero.
PESO_CHECKLIST = 88

CRITERIOS = [
    ("foto", 21, "Foto del evento"),
    ("fecha", 19, "Día confirmado"),
    ("hora", 11, "Hora de inicio"),
    ("lugar", 12, "Sede o dirección"),
    ("ciudad", 7, "Ciudad y departamento"),
    ("categoria", 6, "Tipo de evento"),
    ("entradas", 6, "Información de entradas"),
    ("descripcion", 6, "Descripción con sustancia"),
]

NIVELES = [
    (80, "excelente", "Completo"),
    (60, "bueno", "Bien documentado"),
    (42, "aceptable", "Datos básicos"),
    (0, "incompleto", "Faltan datos"),
]

# Debajo de esto un evento no se publica: no le alcanza ni para una tarjeta.
# Es un piso, no el corte fino — la app ordena por `quality.score` y decide.
MINIMO_PUBLICABLE = 42

DESCRIPCION_MINIMA = 90


def _tiene(valor: Any) -> bool:
    return valor not in (None, "", [], {}, 0.0) or valor is True


def _evaluar(evento: Dict[str, Any]) -> Dict[str, bool]:
    """Qué trae y qué no. Un dict por criterio, sin puntajes todavía."""
    fecha = evento.get("date_detail") or {}
    descripcion = (evento.get("description") or "").strip()

    return {
        "foto": bool(evento.get("image_urls")),
        "fecha": bool(evento.get("starts_at")),
        # "Hora conocida" no es lo mismo que "hay un starts_at con hora": una
        # fecha sin hora se guarda a las 00:00 y quedaría contando como hora.
        "hora": bool(fecha.get("has_time")) or not evento.get("all_day", True),
        "lugar": _tiene(evento.get("venue")) or _tiene(evento.get("address")),
        "ciudad": _tiene(evento.get("city")) or _tiene(evento.get("department")),
        "categoria": (evento.get("category") or "otro") != "otro",
        "entradas": bool(
            evento.get("is_free")
            or evento.get("price_from") is not None
            or evento.get("ticket_outlets")
        ),
        "descripcion": len(descripcion) >= DESCRIPCION_MINIMA,
    }


def _bonificaciones(evento: Dict[str, Any]) -> int:
    """Lo que no es un requisito pero sí mejora la tarjeta."""
    extra = 0
    if len(evento.get("image_urls") or []) >= 3:
        extra += 3          # galería, no una sola foto
    if evento.get("has_video"):
        extra += 2
    if int(evento.get("source_count") or 1) >= 2:
        extra += 4          # lo confirmó más de una fuente
    if (evento.get("date_confidence") or "") == "exacta":
        extra += 3
    if int(evento.get("source_tier") or 3) == 1:
        extra += 2
    if evento.get("artists"):
        extra += 1
    return extra


def _penalizaciones(evento: Dict[str, Any]) -> int:
    castigo = 0
    fecha = evento.get("date_detail") or {}
    if fecha.get("is_estimated") and (evento.get("date_confidence") == "relativa"):
        # Una fecha deducida de "este viernes" puede mandar a la gente el día
        # equivocado, que es el peor error posible en una agenda.
        castigo += 8
    if float(evento.get("confidence") or 0) < 0.5:
        castigo += 5
    if (evento.get("status") or "programado") in {"cancelado", "postergado"}:
        # No se esconde —avisar que algo se canceló es un servicio— pero deja
        # de competir por los primeros lugares de la lista.
        castigo += 6
    return castigo


def evaluar(evento: Dict[str, Any]) -> Dict[str, Any]:
    """El bloque `quality` que viaja en el JSON, con su checklist entera."""
    presentes = _evaluar(evento)

    puntaje = sum(peso for clave, peso, _ in CRITERIOS if presentes.get(clave))
    puntaje += _bonificaciones(evento)
    puntaje -= _penalizaciones(evento)
    puntaje = max(0, min(100, puntaje))

    nivel, etiqueta = next(
        (n, e) for corte, n, e in NIVELES if puntaje >= corte
    )
    faltan = [texto for clave, _, texto in CRITERIOS if not presentes.get(clave)]

    return {
        "score": puntaje,
        "tier": nivel,
        "label": etiqueta,
        "publishable": puntaje >= MINIMO_PUBLICABLE,
        "complete": not faltan,
        "has_photo": presentes["foto"],
        "has_date": presentes["fecha"],
        "has_time": presentes["hora"],
        "has_venue": presentes["lugar"],
        "has_ticket_info": presentes["entradas"],
        "missing": faltan,
        "checks": [
            {"key": clave, "label": texto, "ok": bool(presentes.get(clave)),
             "weight": peso}
            for clave, peso, texto in CRITERIOS
        ],
    }


def anotar(evento: Dict[str, Any]) -> Dict[str, Any]:
    """Agrega (o recalcula) `quality` sobre el evento y lo devuelve."""
    evento["quality"] = evaluar(evento)
    evento["quality_score"] = evento["quality"]["score"]
    evento["quality_tier"] = evento["quality"]["tier"]
    return evento


def filtrar(eventos: List[Dict[str, Any]],
            minimo: Optional[int] = None) -> List[Dict[str, Any]]:
    """Deja solo los eventos que llegan al mínimo, ya anotados y ordenados.

    El orden es el que la app muestra por defecto: primero por fecha —una agenda
    se lee cronológicamente y eso no se discute— y la calidad desempata entre
    los del mismo día. Lo que no llega al mínimo no se borra del historial: solo
    no se publica en esta corrida, porque la próxima puede llegar la foto que le
    faltaba y entonces sí entra.
    """
    corte = MINIMO_PUBLICABLE if minimo is None else int(minimo)
    buenos = [anotar(e) for e in eventos]
    buenos = [e for e in buenos if e["quality"]["score"] >= corte]
    buenos.sort(key=lambda e: (
        e.get("starts_at") is None,
        e.get("starts_at") or "",
        -int(e.get("quality_score") or 0),
    ))
    return buenos


def resumen(eventos: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Cuántos eventos hay de cada nivel y qué es lo que más falta.

    Va al diagnóstico: si "Foto del evento" encabeza la lista de faltantes
    corrida tras corrida, el problema no está en el clasificador sino en la
    extracción de imágenes, y esto es lo que lo hace visible.
    """
    conteo: Dict[str, int] = {}
    faltantes: Dict[str, int] = {}
    for evento in eventos:
        calidad = evento.get("quality") or {}
        conteo[calidad.get("tier", "incompleto")] = conteo.get(
            calidad.get("tier", "incompleto"), 0
        ) + 1
        for falta in calidad.get("missing") or []:
            faltantes[falta] = faltantes.get(falta, 0) + 1

    puntajes = [int(e.get("quality_score") or 0) for e in eventos]
    return {
        "by_tier": [
            {"key": nivel, "label": etiqueta, "count": conteo.get(nivel, 0)}
            for _, nivel, etiqueta in NIVELES
        ],
        "average_score": round(sum(puntajes) / len(puntajes), 1) if puntajes else 0.0,
        "most_missing": [
            {"label": texto, "count": cantidad}
            for texto, cantidad in sorted(
                faltantes.items(), key=lambda x: x[1], reverse=True
            )[:8]
        ],
    }
