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

from . import calidad as calidad_mod
from . import entradas as entradas_mod

# 1.1: se suman `date_detail`, `quality` y `ticket_info`; `ticket_urls` pasa a
# viajar siempre vacío. Todas las claves de 1.0 siguen estando y con el mismo
# significado, así que una app vieja sigue funcionando contra este JSON.
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
    "display_date", "display_date_short", "countdown_label",
    "lifecycle", "lifecycle_label", "days_until", "is_upcoming",
    "city", "department", "venue",
    "image_url", "has_image", "has_video",
    "is_free", "price_from", "currency", "price_label",
    "ticket_outlets",
    "status", "source_count", "quality_score", "quality_tier",
]

ETIQUETAS_CALIDAD = {
    "excelente": "Completo",
    "bueno": "Bien documentado",
    "aceptable": "Datos básicos",
    "incompleto": "Faltan datos",
}


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
        {"key": "con_galeria", "label": "Con galería",
         "count": sum(1 for e in eventos if len(e.get("image_urls") or []) >= 3)},
        {"key": "con_video", "label": "Con video", "count": sum(1 for e in eventos if e.get("has_video"))},
    ]


def _faceta_calidad(eventos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Un chip para "mostrame solo los eventos completos".

    Es el filtro que más cambia la primera impresión de la app: con él, la
    pantalla inicial puede abrir mostrando solo eventos con afiche, fecha, hora
    y sede, y dejar el resto para quien vaya a buscarlo.
    """
    conteo = Counter(e.get("quality_tier") for e in eventos if e.get("quality_tier"))
    return [
        {"key": nivel, "label": ETIQUETAS_CALIDAD[nivel], "count": conteo.get(nivel, 0)}
        for nivel in ("excelente", "bueno", "aceptable", "incompleto")
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
        {"key": "quality", "label": "Nivel de detalle", "selection": "single", "icon": "verified"},
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


def _fuentes_para_la_app(fuentes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """El listado de fuentes tal como lo ve la app, sin enlaces a ticketeras.

    Varias fuentes del catálogo **son** ticketeras, así que su `url` es la
    portada de una tienda de entradas. En el diagnóstico esa URL hace falta
    —es donde el mantenedor va a ver por qué falló la lectura— pero en el
    archivo que abre la app sería justo el redirect que este catálogo no
    publica. El nombre de la fuente se conserva: la atribución no se pierde.
    """
    salida = []
    for fuente in fuentes:
        copia = dict(fuente)
        if copia.get("url") and entradas_mod.es_enlace_de_compra(copia["url"]):
            copia["url"] = None
        salida.append(copia)
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

    # Un precio ya escrito: la app no debería tener que decidir entre "Gratis",
    # "Bs 80" y "Desde Bs 80" cada vez que pinta una tarjeta.
    evento["price_label"] = entradas_mod.etiqueta_de_precio(
        bool(evento.get("is_free")), evento.get("price_from"), evento.get("price_to")
    )

    # Claves nuevas sobre eventos viejos: los que vienen del historial se
    # escribieron con un esquema anterior y la app espera el contrato completo.
    evento.setdefault("date_detail", {})
    evento.setdefault("display_date_short", None)
    evento.setdefault("countdown_label", None)
    evento.setdefault("ticket_outlets", [])
    if not evento.get("ticket_info"):
        evento["ticket_info"] = entradas_mod.describir(
            evento.get("ticket_outlets") or [],
            bool(evento.get("is_free")),
            evento["price_label"],
            evento.get("status") or "programado",
            evento.get("phones") or [],
        )

    # El saneado se repite acá a propósito. La fusión ya lo hizo para lo de esta
    # corrida, pero el catálogo arrastra eventos guardados por corridas
    # anteriores: lo que se publica hoy cumple la política de hoy.
    entradas_mod.sanear_evento(evento)
    calidad_mod.anotar(evento)
    return evento


def construir_payload(
    eventos: List[Dict[str, Any]],
    fuentes: List[Dict[str, Any]],
    generado_en: str,
    zona: str,
    cobertura: Optional[Dict[str, Any]] = None,
    incluir_finalizados: bool = True,
    minimo_calidad: Optional[int] = None,
) -> Dict[str, Any]:
    """El JSON principal: catálogo completo más todo lo precalculado."""
    ahora = _fecha(generado_en) or datetime.now()

    for evento in eventos:
        enriquecer_para_la_app(evento)

    # El corte de calidad se aplica sobre lo que se publica, no sobre lo que se
    # archiva: un evento al que hoy le falta el afiche se guarda igual, y si la
    # próxima corrida se lo trae, entra sin haber perdido su id ni su historial.
    corte = calidad_mod.MINIMO_PUBLICABLE if minimo_calidad is None else int(minimo_calidad)
    # `filtrar` además ordena: cronológico, y entre eventos del mismo día
    # primero el más completo. Eso es lo que hace que la lista abra con los que
    # tienen afiche, hora y sede en vez de con los que solo tienen un título.
    publicables = calidad_mod.filtrar(eventos, corte)
    descartados_por_calidad = len(eventos) - len(publicables)

    visibles = publicables if incluir_finalizados else [
        e for e in publicables if e.get("is_upcoming")
    ]
    proximos = [e for e in visibles if e.get("is_upcoming")]
    calidad = calidad_mod.resumen(visibles)

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
            "events_complete": sum(1 for e in visibles if e.get("quality_tier") == "excelente"),
            "events_below_quality": descartados_por_calidad,
            "quality_min_score": corte,
            "quality_average": calidad["average_score"],
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
            "quality": _faceta_calidad(proximos),
            "tags": _faceta_lista(proximos, "tags", 24),
            "source_classes": _faceta(proximos, "source_class"),
        },
        "coverage": cobertura or {},
        "quality": calidad,
        # Parte del contrato, no una nota al pie: este catálogo dice dónde se
        # compran las entradas y nunca lleva a comprarlas. `ticket_urls` viaja
        # vacío siempre y ningún campo del JSON abre un checkout.
        "policy": {
            "purchase_links": False,
            "external_redirects": False,
            "note": ("El catálogo informa dónde conseguir entradas, "
                     "sin enlaces de compra ni redirecciones."),
        },
        "events": visibles,
        "sources": _fuentes_para_la_app(fuentes),
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
            "events_with_image": sum(1 for e in proximos if e.get("has_image")),
            "events_complete": sum(1 for e in proximos if e.get("quality_tier") == "excelente"),
        },
        "policy": payload["policy"],
        "filters": payload["filters"],
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
