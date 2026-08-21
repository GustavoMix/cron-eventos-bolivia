"""Memoria entre corridas. Es lo que hace que el bloqueo de Facebook no importe.

Cada corrida ve una porción distinta del catálogo: Facebook corta unas IPs, el
planificador posterga otras fuentes, y algunas páginas simplemente no publicaron
nada. Si el JSON se armara solo con lo visto en la corrida actual, la lista de
la app cambiaría por completo cada hora y los eventos aparecerían y
desaparecerían sin razón.

Acá está la diferencia de fondo con un scraper de tránsito, y es lo que permite
que todo el enfoque funcione: **un evento no caduca porque dejemos de verlo**.
Un bloqueo de carretera que ninguna fuente menciona hoy probablemente ya se
levantó. Un concierto anunciado hace dos semanas sigue en pie aunque hoy nadie
haya vuelto a postear sobre él — y de hecho es lo normal, porque un evento se
anuncia una vez y se comenta pocas veces más.

Entonces el archivo no es un respaldo: es la fuente de verdad. Cada corrida
suma lo que encontró y arrastra lo que sigue vigente. El catálogo se acumula, y
lo que en una corrida suelta parecería una cobertura pobre —quince fuentes de
sesenta— termina siendo un catálogo completo después de unas pocas vueltas.
"""

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from .fechas import (
    TZ_BOLIVIA,
    FechaEvento,
    cuenta_regresiva,
    detalle_de_fecha,
    fecha_corta,
    fecha_legible,
)

# Cuántos días se conserva un evento ya terminado. Sirve para que la app pueda
# mostrar "esta semana" incluyendo lo de anteayer, y para que un evento que se
# repite no se lea como nuevo cada vez.
DIAS_CONSERVAR_PASADOS = 4

# Tope duro del archivo. Un catálogo nacional de eventos futuros no llega a
# tanto; el límite es contra un bug que infle el archivo, no contra el uso real.
MAX_EVENTOS_ARCHIVADOS = 3000

VACIAS = {
    "de", "la", "el", "los", "las", "en", "y", "del", "con", "por", "para",
    "un", "una", "gran", "evento", "bolivia", "vivo", "presenta", "entrada",
}


def _norm(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c)).lower()
    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _tokens(d: Dict[str, Any]) -> set:
    partes = " ".join([
        d.get("title") or "",
        " ".join(d.get("artists") or []),
        (d.get("description") or "")[:500],
        d.get("venue") or "",
    ])
    return {t for t in _norm(partes).split() if len(t) >= 4 and t not in VACIAS}


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def puntaje_coincidencia(actual: Dict[str, Any], viejo: Dict[str, Any]) -> float:
    """Qué tan probable es que estos dos registros sean el mismo evento.

    Se apoya en la fecha: si los dos la tienen y no coincide, no hay nada que
    discutir. El resto de las señales solo confirman.
    """
    dia_a = (actual.get("starts_at") or "")[:10]
    dia_b = (viejo.get("starts_at") or "")[:10]
    if dia_a and dia_b and dia_a != dia_b:
        return 0.0

    ciudad_a, ciudad_b = _norm(actual.get("city") or ""), _norm(viejo.get("city") or "")
    if ciudad_a and ciudad_b and ciudad_a != ciudad_b:
        return 0.0

    puntos = 0.30 if (dia_a and dia_a == dia_b) else 0.0

    sede_a, sede_b = _norm(actual.get("venue") or ""), _norm(viejo.get("venue") or "")
    if sede_a and sede_a == sede_b:
        puntos += 0.22
    elif sede_a and sede_b:
        puntos -= 0.12

    if ciudad_a and ciudad_a == ciudad_b:
        puntos += 0.08
    if actual.get("category") == viejo.get("category"):
        puntos += 0.06

    # Dos anuncios del mismo evento suelen compartir la URL del post cuando la
    # misma fuente lo republica.
    urls_a = set(actual.get("all_urls") or [actual.get("url")]) - {None}
    urls_b = set(viejo.get("all_urls") or [viejo.get("url")]) - {None}
    if urls_a & urls_b:
        puntos += 0.20

    puntos += min(_jaccard(_tokens(actual), _tokens(viejo)), 0.34)
    return max(0.0, min(puntos, 1.0))


def _id_estable(d: Dict[str, Any]) -> str:
    """Identificador que sobrevive entre corridas.

    Tiene que ser estable de verdad: la app lo usa para guardar favoritos y para
    no volver a notificar un evento que el usuario ya vio. Se arma con lo que no
    cambia de un anuncio a otro —día, ciudad, sede, categoría y las palabras
    fuertes del título— y no con la URL del post, que cambia con cada fuente.
    """
    tokens = sorted(_tokens(d))[:6]
    base = "|".join([
        (d.get("starts_at") or "")[:10],
        _norm(d.get("city") or ""),
        _norm(d.get("venue") or ""),
        d.get("category") or "",
        " ".join(tokens),
    ])
    return "evt_" + hashlib.sha1(base.encode("utf-8")).hexdigest()[:14]


def _ahora(tz_nombre: str = TZ_BOLIVIA) -> datetime:
    return datetime.now(ZoneInfo(tz_nombre))


def _parse(iso: Optional[str], tz_nombre: str = TZ_BOLIVIA) -> Optional[datetime]:
    if not iso:
        return None
    try:
        valor = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return None
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=ZoneInfo(tz_nombre))
    return valor


def _refrescar_presentacion(d: Dict[str, Any], inicio: Optional[datetime],
                            fin: Optional[datetime], ahora: datetime,
                            tz_nombre: str) -> None:
    """Reescribe los textos de fecha que dependen de cuándo se los mira.

    "En 3 días" es cierto el martes y mentira el viernes. Como el catálogo
    arrastra eventos que ninguna fuente volvió a publicar, esos textos hay que
    rehacerlos en cada corrida o la app termina mostrando una cuenta regresiva
    congelada en el día que se scrapeó el afiche. De paso, un evento guardado
    por una versión anterior del scraper se completa acá con las claves nuevas.
    """
    if inicio is None:
        d["display_date"] = None
        d["display_date_short"] = None
        d["countdown_label"] = None
        d["date_detail"] = detalle_de_fecha(FechaEvento(), ahora=ahora, tz_nombre=tz_nombre)
        return

    todo_el_dia = d.get("all_day")
    if todo_el_dia is None:
        todo_el_dia = inicio.hour == 0 and inicio.minute == 0

    fecha = FechaEvento(
        inicio=inicio,
        fin=fin,
        hora_puertas=d.get("doors_time"),
        todo_el_dia=bool(todo_el_dia),
        multidia=bool(fin and fin.date() != inicio.date()),
        confianza=d.get("date_confidence") or "aproximada",
        texto_origen=d.get("date_source_text") or "",
    )
    d["display_date"] = fecha_legible(fecha, ahora=ahora, tz_nombre=tz_nombre)
    d["display_date_short"] = fecha_corta(fecha)
    d["countdown_label"] = cuenta_regresiva(fecha, ahora=ahora, tz_nombre=tz_nombre)
    d["date_detail"] = detalle_de_fecha(fecha, ahora=ahora, tz_nombre=tz_nombre)


def recalcular_tiempo(d: Dict[str, Any], ahora: datetime,
                      tz_nombre: str = TZ_BOLIVIA) -> Dict[str, Any]:
    """Vuelve a calcular todo lo que depende de "ahora".

    Un evento archivado guarda su fecha, no su estado: el que era "próximo"
    ayer es "hoy" hoy y "finalizado" mañana. Si esto no se recalculara en cada
    corrida, la app mostraría eventos de la semana pasada marcados como que
    faltan tres días.
    """
    inicio = _parse(d.get("starts_at"), tz_nombre)
    fin = _parse(d.get("ends_at"), tz_nombre)
    _refrescar_presentacion(d, inicio, fin, ahora, tz_nombre)

    if not inicio:
        d["lifecycle"] = "sin_fecha"
        d["days_until"] = None
        d["is_upcoming"] = False
        return d

    if fin and inicio <= ahora <= fin:
        ciclo = "en_curso"
    elif ahora.date() == inicio.date():
        # Sigue siendo "hoy" toda la jornada: a las 21:00 la gente todavía
        # busca el concierto que empezó a las 20:00.
        ciclo = "hoy"
    elif inicio > ahora:
        ciclo = "proximo"
    else:
        ciclo = "finalizado"

    d["lifecycle"] = ciclo
    d["days_until"] = (inicio.date() - ahora.date()).days
    d["is_upcoming"] = ciclo in {"proximo", "hoy", "en_curso"}
    return d


def cargar_archivo(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("events", [])
    except (json.JSONDecodeError, OSError):
        return []


def _entrada_de_historial(d: Dict[str, Any], cuando: str, motivo: str) -> Dict[str, Any]:
    return {
        "at": cuando,
        "reason": motivo,
        "status": d.get("status"),
        "lifecycle": d.get("lifecycle"),
        "starts_at": d.get("starts_at"),
        "price_from": d.get("price_from"),
        "source_count": d.get("source_count", 1),
    }


def _cambios_relevantes(viejo: Dict[str, Any], nuevo: Dict[str, Any]) -> List[str]:
    """Cambios que a un usuario le importarían lo suficiente como para avisarle."""
    cambios = []
    if viejo.get("status") != nuevo.get("status"):
        cambios.append(f"estado:{viejo.get('status')}->{nuevo.get('status')}")
    if (viejo.get("starts_at") or "")[:10] != (nuevo.get("starts_at") or "")[:10]:
        cambios.append("fecha_cambiada")
    if viejo.get("price_from") != nuevo.get("price_from"):
        cambios.append("precio_cambiado")
    if viejo.get("venue") != nuevo.get("venue") and nuevo.get("venue"):
        cambios.append("sede_cambiada")
    return cambios


def reconciliar(
    actuales: List[Dict[str, Any]],
    ruta_archivo: Path,
    generado_en: str,
    umbral: float = 0.62,
    conservar_pasados_dias: int = DIAS_CONSERVAR_PASADOS,
    tz_nombre: str = TZ_BOLIVIA,
) -> List[Dict[str, Any]]:
    """Cruza lo visto en esta corrida con lo que ya se sabía.

    Devuelve el catálogo completo: los eventos vistos hoy más los arrastrados
    del archivo que siguen vigentes. Es a la vez lo que se guarda y la base de
    lo que la app muestra — que es justamente lo que evita que la lista parpadee
    cuando Facebook bloquea la mitad de las fuentes.
    """
    ahora = _parse(generado_en, tz_nombre) or _ahora(tz_nombre)
    previos = cargar_archivo(ruta_archivo)

    usados: set = set()
    resueltos: List[Dict[str, Any]] = []

    for actual in actuales:
        mejor_i, mejor_puntaje = None, 0.0
        for i, viejo in enumerate(previos):
            if i in usados:
                continue
            p = puntaje_coincidencia(actual, viejo)
            if p > mejor_puntaje:
                mejor_i, mejor_puntaje = i, p

        viejo = previos[mejor_i] if mejor_i is not None and mejor_puntaje >= umbral else None

        if viejo is not None:
            usados.add(mejor_i)
            actual["event_id"] = viejo.get("event_id") or _id_estable(actual)
            actual["first_seen_at"] = viejo.get("first_seen_at") or generado_en
            historial = list(viejo.get("history") or [])
            cambios = _cambios_relevantes(viejo, actual)
            if cambios:
                entrada = _entrada_de_historial(actual, generado_en, "actualizacion")
                entrada["changes"] = cambios
                historial.append(entrada)
            actual["history"] = historial[-40:]
            actual["changed_this_run"] = cambios
            # Las fuentes que vieron el evento antes siguen contando: la app
            # muestra "confirmado por 4 fuentes" aunque hoy solo lo haya visto una.
            actual["source_count"] = max(
                int(actual.get("source_count", 1)), int(viejo.get("source_count", 1))
            )
        else:
            actual["event_id"] = _id_estable(actual)
            actual["first_seen_at"] = generado_en
            actual["history"] = [
                _entrada_de_historial(actual, generado_en, "primera_deteccion")
            ]
            actual["changed_this_run"] = []

        actual["last_seen_at"] = generado_en
        actual["last_confirmed_at"] = generado_en
        actual["seen_this_run"] = True
        actual["history_count"] = len(actual["history"])
        recalcular_tiempo(actual, ahora, tz_nombre)
        resueltos.append(actual)

    # Arrastrar lo que no se vio hoy pero sigue en pie.
    limite_pasado = ahora - timedelta(days=max(0, conservar_pasados_dias))
    for i, viejo in enumerate(previos):
        if i in usados:
            continue

        copia = dict(viejo)
        recalcular_tiempo(copia, ahora, tz_nombre)
        copia["seen_this_run"] = False
        copia["last_seen_at"] = viejo.get("last_seen_at") or viejo.get("first_seen_at")

        inicio = _parse(copia.get("starts_at"))
        if inicio is not None:
            cierre = _parse(copia.get("ends_at")) or inicio
            if cierre < limite_pasado:
                continue  # ya pasó hace rato: se lo deja ir
        else:
            # Sin fecha no hay forma de saber si sigue vigente; se conserva unos
            # días desde que se lo vio por última vez y después se descarta.
            visto = _parse(copia.get("last_seen_at"))
            if visto is None or visto < limite_pasado:
                continue

        resueltos.append(copia)

    # Un mismo event_id puede llegar por dos caminos si dos clusters de esta
    # corrida coincidieron con el mismo registro viejo. Gana el de esta corrida.
    unicos: Dict[str, Dict[str, Any]] = {}
    for evento in resueltos:
        clave = evento.get("event_id") or _id_estable(evento)
        anterior = unicos.get(clave)
        if anterior is None or (evento.get("seen_this_run") and not anterior.get("seen_this_run")):
            unicos[clave] = evento

    salida = list(unicos.values())
    salida.sort(key=lambda e: (
        e.get("starts_at") is None,          # los sin fecha, al final
        e.get("starts_at") or "",            # los más próximos primero
        -float(e.get("confidence") or 0),
    ))
    return salida[:MAX_EVENTOS_ARCHIVADOS]


def guardar_archivo(path: Path, eventos: List[Dict[str, Any]], generado_en: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"generated_at": generado_en, "events": eventos},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
