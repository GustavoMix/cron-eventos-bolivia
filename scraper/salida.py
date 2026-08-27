"""Armado de los JSON que consume la app.

Todo lo que este módulo hace de más existe para que la app tenga que hacer de
menos. Un teléfono de gama media renderizando una lista con scroll no debería
estar parseando fechas ISO, formateando texto en español ni recorriendo el
catálogo entero para contar cuántos conciertos hay en Santa Cruz. Todo eso se
calcula una vez acá, en el runner, y viaja resuelto en el JSON.

Concretamente:

- Cada fecha viaja además en epoch milisegundos (`starts_at_ms`). Ordenar y
  filtrar por rango se vuelve comparar enteros.
- Cada evento trae su fecha ya escrita en español (`display_date`).
- Las facetas de los filtros vienen contadas (`filters`), así los chips se
  pintan sin recorrer nada.
- Hay un archivo liviano aparte para la pantalla de lista, que es la que tiene
  que abrir rápido, y el pesado queda para el detalle.

Las claves son en inglés y snake_case —igual que en el proyecto de tránsito, así
una misma app puede compartir utilidades entre los dos— y los valores que se
muestran al usuario están en español.
"""

import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "1.1"

# Etiquetas listas para pintar. Van en el JSON y no en la app para que agregar
# una categoría no obligue a publicar una versión nueva en la tienda.
ETIQUETAS_CATEGORIA = {
    "concierto": "Conciertos",
    "festival": "Festivales",
    "feria": "Ferias y expos",
    "teatro": "Teatro",
    "danza": "Danza",
    "deporte": "Deportes",
    "gastronomia": "Gastronomía",
    "cine": "Cine",
    "exposicion": "Exposiciones",
    "literatura": "Literatura y libros",
    "turismo": "Turismo y patrimonio",
    "conferencia": "Conferencias",
    "taller": "Talleres y cursos",
    "infantil": "Para niños",
    "religioso": "Religiosos",
    "nightlife": "Vida nocturna",
    "moda": "Moda",
    "tecnologia": "Tecnología",
    "otro": "Otros",
}

ETIQUETAS_CICLO = {
    "hoy": "Hoy",
    "en_curso": "En curso",
    "proximo": "Próximos",
    "finalizado": "Finalizados",
    "sin_fecha": "Sin fecha confirmada",
}

# Los campos que necesita una tarjeta de la lista. Todo lo demás —descripción
# completa, historial, texto original, listado de fuentes— se queda en el
# archivo pesado y se lee recién al abrir el detalle.
CAMPOS_LITE = [
    "event_id", "title", "category", "category_label",
    "starts_at", "starts_at_ms", "ends_at_ms", "multi_day",
    "display_date", "lifecycle", "lifecycle_label", "days_until", "is_upcoming",
    "city", "department", "venue",
    "image_url", "has_video", "video_thumbnail_url",
    "is_free", "price_from", "currency", "price_label",
    "organizer", "showtimes", "formats", "occurrences",
    "content_genre", "duration_minutes", "age_restriction", "director", "cast",
    "quality_score", "is_featured",
    "status", "source_count",
]


def _fecha(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return None


def _faceta(eventos: List[Dict[str, Any]], campo: str,
            etiquetas: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Cuenta cuántos eventos hay por valor, ya ordenado de mayor a menor."""
    conteo = Counter(e.get(campo) for e in eventos if e.get(campo))
    return [
        {
            "key": valor,
            "label": (etiquetas or {}).get(valor, valor),
            "count": cantidad,
        }
        for valor, cantidad in conteo.most_common()
    ]


def _faceta_lista(eventos: List[Dict[str, Any]], campo: str, limite: int = 20) -> List[Dict[str, Any]]:
    """Cuenta valores que vienen en listas, por ejemplo tags."""
    conteo = Counter()
    for evento in eventos:
        for valor in evento.get(campo) or []:
            if valor:
                conteo[str(valor)] += 1
    return [
        {"key": valor, "label": valor, "count": cantidad}
        for valor, cantidad in conteo.most_common(limite)
    ]


def _faceta_precio(eventos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    libres = sum(1 for e in eventos if e.get("is_free"))
    pagados = sum(1 for e in eventos if not e.get("is_free") and e.get("price_from") is not None)
    confirmar = max(0, len(eventos) - libres - pagados)
    return [
        {"key": "gratis", "label": "Gratis", "count": libres},
        {"key": "pagado", "label": "Con entrada", "count": pagados},
        {"key": "por_confirmar", "label": "Precio por confirmar", "count": confirmar},
    ]


def _faceta_media(eventos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {"key": "con_foto", "label": "Con foto", "count": sum(1 for e in eventos if e.get("has_image"))},
        {"key": "con_video", "label": "Con video", "count": sum(1 for e in eventos if e.get("has_video"))},
    ]


def _grupos_ui() -> List[Dict[str, Any]]:
    """Metadatos simples para que la app pinte filtros coherentes sin hardcodear labels."""
    return [
        {"key": "when", "label": "Cuándo", "selection": "single", "icon": "calendar"},
        {"key": "categories", "label": "Tipo de evento", "selection": "multi", "icon": "category"},
        {"key": "departments", "label": "Departamento", "selection": "multi", "icon": "map"},
        {"key": "cities", "label": "Ciudad", "selection": "multi", "icon": "location_city"},
        {"key": "price", "label": "Precio", "selection": "single", "icon": "payments"},
        {"key": "media", "label": "Multimedia", "selection": "multi", "icon": "photo_library"},
        {"key": "tags", "label": "Temas", "selection": "multi", "icon": "sell"},
    ]


def _faceta_temporal(eventos: List[Dict[str, Any]], ahora: datetime) -> List[Dict[str, Any]]:
    """Los filtros de "cuándo", que son los que la gente usa primero.

    Los rangos se solapan a propósito: un evento de mañana cuenta en "esta
    semana" y también en "este mes". Son atajos de navegación, no categorías
    excluyentes.
    """
    hoy = ahora.date()
    fin_semana = hoy + timedelta(days=7)
    fin_mes = hoy + timedelta(days=30)

    hoy_n = semana_n = mes_n = 0
    for e in eventos:
        inicio = _fecha(e.get("starts_at"))
        if not inicio:
            continue
        dia = inicio.date()
        fin = _fecha(e.get("ends_at"))
        dia_fin = fin.date() if fin else dia
        if dia <= hoy <= dia_fin:
            hoy_n += 1
        if dia <= fin_semana and dia_fin >= hoy:
            semana_n += 1
        if dia <= fin_mes and dia_fin >= hoy:
            mes_n += 1

    return [
        {"key": "hoy", "label": "Hoy", "count": hoy_n},
        {"key": "esta_semana", "label": "Esta semana", "count": semana_n},
        {"key": "este_mes", "label": "Este mes", "count": mes_n},
        {"key": "todos", "label": "Todos", "count": len(eventos)},
    ]


DEPARTAMENTOS_BOLIVIA = [
    "La Paz", "Cochabamba", "Santa Cruz", "Chuquisaca", "Oruro",
    "Potosí", "Tarija", "Beni", "Pando",
]


def _quality_score(evento: Dict[str, Any]) -> int:
    """Puntaje editorial simple y explicable para ordenar destacados.

    Favorece datos que hacen una tarjeta realmente útil: fecha, afiche, sede,
    entradas y una fuente confiable. No mide popularidad ni inventa tendencias.
    """
    score = 0
    if evento.get("starts_at"):
        score += 24
    if evento.get("has_image"):
        score += 14
    if evento.get("has_video"):
        score += 7
    if evento.get("venue"):
        score += 10
    if evento.get("city"):
        score += 6
    if evento.get("is_free") or evento.get("price_from") is not None or evento.get("ticket_urls"):
        score += 8
    tier = evento.get("source_tier")
    if tier == 1:
        score += 9
    elif tier == 2:
        score += 5
    if evento.get("corroborated"):
        score += 8
    if evento.get("organizer"):
        score += 5
    if evento.get("showtimes") or evento.get("occurrences"):
        score += 5
    if evento.get("formats"):
        score += 2
    if evento.get("address") or evento.get("location_query"):
        score += 2
    return max(0, min(100, score))


def _proximo_fin_de_semana(ahora: datetime):
    """Devuelve sábado/domingo del fin de semana actual o próximo."""
    hoy = ahora.date()
    # weekday: lunes=0 ... sábado=5, domingo=6.
    dias_hasta_sabado = (5 - hoy.weekday()) % 7
    if hoy.weekday() == 6:  # domingo: conservar el fin de semana actual
        sabado = hoy - timedelta(days=1)
    else:
        sabado = hoy + timedelta(days=dias_hasta_sabado)
    return sabado, sabado + timedelta(days=1)


def _secciones(eventos: List[Dict[str, Any]], ahora: datetime) -> Dict[str, List[str]]:
    hoy = ahora.date()
    manana = hoy + timedelta(days=1)
    sabado, domingo = _proximo_fin_de_semana(ahora)
    salida = {"today": [], "tomorrow": [], "this_weekend": [], "free": [], "featured": []}
    for evento in eventos:
        if not evento.get("is_upcoming") or not evento.get("event_id"):
            continue
        inicio = _fecha(evento.get("starts_at"))
        fin = _fecha(evento.get("ends_at")) or inicio
        inicio_dia = inicio.date() if inicio else None
        fin_dia = fin.date() if fin else inicio_dia
        event_id = evento["event_id"]
        if inicio_dia and inicio_dia <= hoy <= (fin_dia or inicio_dia):
            salida["today"].append(event_id)
        if inicio_dia and inicio_dia <= manana <= (fin_dia or inicio_dia):
            salida["tomorrow"].append(event_id)
        if inicio_dia and fin_dia and inicio_dia <= domingo and fin_dia >= sabado:
            salida["this_weekend"].append(event_id)
        if evento.get("is_free"):
            salida["free"].append(event_id)
        if evento.get("is_featured"):
            salida["featured"].append(event_id)
    return salida


def _cobertura_departamentos(eventos: List[Dict[str, Any]], fuentes: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    """Radiografía nacional; devuelve los nueve departamentos aunque estén en cero."""
    salida: Dict[str, Dict[str, int]] = {}
    for departamento in DEPARTAMENTOS_BOLIVIA:
        evs = [e for e in eventos if e.get("department") == departamento]
        proximos = [e for e in evs if e.get("is_upcoming")]
        fs = [f for f in fuentes if f.get("region") == departamento]
        salida[departamento] = {
            "events_total": len(evs),
            "events_upcoming": len(proximos),
            "events_with_image": sum(1 for e in proximos if e.get("has_image")),
            "events_with_video": sum(1 for e in proximos if e.get("has_video")),
            "sources_total": len(fs),
            "sources_ok": sum(1 for f in fs if f.get("status") == "ok"),
        }
    return salida


def _cobertura_categorias(eventos: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    salida: Dict[str, Dict[str, int]] = {}
    for categoria in sorted({e.get("category") for e in eventos if e.get("category")}):
        evs = [e for e in eventos if e.get("category") == categoria]
        proximos = [e for e in evs if e.get("is_upcoming")]
        salida[categoria] = {
            "label": ETIQUETAS_CATEGORIA.get(categoria, categoria),
            "events_total": len(evs),
            "events_upcoming": len(proximos),
            "events_with_image": sum(1 for e in proximos if e.get("has_image")),
            "events_with_video": sum(1 for e in proximos if e.get("has_video")),
        }
    return salida


def enriquecer_para_la_app(evento: Dict[str, Any]) -> Dict[str, Any]:
    """Agrega las etiquetas ya traducidas y las banderas que la lista necesita."""
    evento["category_label"] = ETIQUETAS_CATEGORIA.get(
        evento.get("category") or "otro", "Otros"
    )
    evento["lifecycle_label"] = ETIQUETAS_CICLO.get(
        evento.get("lifecycle") or "sin_fecha", "Sin fecha confirmada"
    )
    evento.setdefault("is_upcoming", evento.get("lifecycle") in {"proximo", "hoy", "en_curso"})
    # Los catálogos históricos creados con versiones anteriores no tenían estos
    # campos. Mantener listas vacías evita contratos variables en la app.
    evento.setdefault("showtimes", [])
    evento.setdefault("formats", [])
    evento.setdefault("occurrences", [])
    evento.setdefault("organizer", None)
    evento.setdefault("content_genre", None)
    evento.setdefault("director", None)
    evento.setdefault("cast", [])
    evento.setdefault("duration_minutes", None)
    evento.setdefault("age_restriction", None)
    evento.setdefault("video_thumbnail_url", None)
    evento["quality_score"] = _quality_score(evento)
    evento["is_featured"] = bool(
        evento.get("is_upcoming")
        and evento.get("status") not in {"cancelado", "postergado"}
        and evento["quality_score"] >= 65
    )

    # Un precio ya escrito: la app no debería tener que decidir entre "Gratis",
    # "Bs 80" y "Desde Bs 80" cada vez que pinta una tarjeta.
    def _monto(valor):
        # "Bs 80", no "Bs 80.0": los precios de entradas son enteros salvo
        # excepción, y el decimal colgando se ve mal en una tarjeta.
        return int(valor) if float(valor).is_integer() else valor

    if evento.get("is_free"):
        evento["price_label"] = "Entrada libre"
    elif evento.get("price_from") is not None:
        desde = evento["price_from"]
        hasta = evento.get("price_to")
        evento["price_label"] = (
            f"Bs {_monto(desde)} - {_monto(hasta)}" if hasta and hasta != desde
            else f"Bs {_monto(desde)}"
        )
    else:
        evento["price_label"] = None

    return evento


def construir_payload(
    eventos: List[Dict[str, Any]],
    fuentes: List[Dict[str, Any]],
    generado_en: str,
    zona: str,
    cobertura: Optional[Dict[str, Any]] = None,
    incluir_finalizados: bool = True,
) -> Dict[str, Any]:
    """El JSON principal: catálogo completo más todo lo precalculado."""
    ahora = _fecha(generado_en) or datetime.now()

    for evento in eventos:
        enriquecer_para_la_app(evento)

    visibles = eventos if incluir_finalizados else [
        e for e in eventos if e.get("is_upcoming")
    ]
    proximos = [e for e in visibles if e.get("is_upcoming")]

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generado_en,
        "timezone": zona,
        "summary": {
            "events_total": len(visibles),
            "events_upcoming": len(proximos),
            "events_today": sum(1 for e in visibles if e.get("lifecycle") == "hoy"),
            "events_with_date": sum(1 for e in visibles if e.get("starts_at")),
            "events_free": sum(1 for e in proximos if e.get("is_free")),
            "events_with_image": sum(1 for e in visibles if e.get("has_image")),
            "events_with_video": sum(1 for e in visibles if e.get("has_video")),
            "events_corroborated": sum(1 for e in visibles if e.get("corroborated")),
            "events_seen_this_run": sum(1 for e in visibles if e.get("seen_this_run")),
            "sources_total": len(fuentes),
            "sources_ok": sum(1 for f in fuentes if f.get("status") == "ok"),
            "sources_blocked": sum(1 for f in fuentes if f.get("status") == "blocked"),
            "sources_error": sum(1 for f in fuentes if f.get("status") == "error"),
            "sources_skipped": sum(1 for f in fuentes if f.get("status") == "skipped"),
        },
        # Contadas sobre los próximos: un chip que promete 40 conciertos y al
        # tocarlo muestra 3 porque los otros 37 ya pasaron es un chip roto.
        "filters": {
            "ui_groups": _grupos_ui(),
            "categories": _faceta(proximos, "category", ETIQUETAS_CATEGORIA),
            "cities": _faceta(proximos, "city"),
            "departments": _faceta(proximos, "department"),
            "when": _faceta_temporal(proximos, ahora),
            "price": _faceta_precio(proximos),
            "media": _faceta_media(proximos),
            "tags": _faceta_lista(proximos, "tags", 24),
            "source_classes": _faceta(proximos, "source_class"),
        },
        "sections": _secciones(visibles, ahora),
        "coverage_by_department": _cobertura_departamentos(visibles, fuentes),
        "coverage_by_category": _cobertura_categorias(visibles),
        "coverage": cobertura or {},
        "events": visibles,
        "sources": fuentes,
    }


def construir_payload_lite(payload: Dict[str, Any]) -> Dict[str, Any]:
    """La versión liviana: solo eventos vigentes y solo los campos de la lista.

    La pantalla que se abre primero es la que más rápido tiene que cargar. Este
    archivo suele pesar menos de la décima parte del completo.
    """
    proximos = [e for e in payload["events"] if e.get("is_upcoming")]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": payload["generated_at"],
        "timezone": payload["timezone"],
        "summary": {
            "events_total": len(proximos),
            "events_today": sum(1 for e in proximos if e.get("lifecycle") == "hoy"),
        },
        "filters": payload["filters"],
        "sections": payload.get("sections", {}),
        "coverage_by_department": payload.get("coverage_by_department", {}),
        "coverage_by_category": payload.get("coverage_by_category", {}),
        "events": [
            {campo: evento.get(campo) for campo in CAMPOS_LITE}
            for evento in proximos
        ],
    }


def escribir_json(path: Path, dato: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dato, ensure_ascii=False, indent=2), encoding="utf-8"
    )
