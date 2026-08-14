"""Lectura de fechas y horarios de eventos escritos en español boliviano.

Este módulo es el corazón del proyecto. Un evento sin fecha no sirve para nada
en la app: no se puede ordenar, no se puede filtrar por "esta semana" ni se
puede decir si ya pasó. Y las fechas casi nunca vienen en un campo estructurado
—vienen dentro del texto de un afiche publicado en Facebook, escritas como las
escribe una persona:

    "🎸 SÁBADO 23 DE AGOSTO - 20:00 hrs"
    "Del 5 al 7 de septiembre"
    "Este viernes en el Teatro Achá, puertas 19:30, show 21:00"
    "15/03 | 20:00"

Reglas de diseño:

1. El año casi nunca se escribe. Un afiche que dice "23 de agosto" publicado en
   agosto se refiere a este año; el mismo texto publicado en diciembre se
   refiere al año que viene. Se infiere tomando la próxima ocurrencia futura,
   con unos días de gracia hacia atrás para no empujar al año siguiente un
   evento que fue anteayer.

2. Se prefiere no dar una fecha antes que dar una inventada. Cada resultado
   viene con su nivel de confianza y la app puede decidir qué hacer con los
   eventos de fecha dudosa. Un evento con fecha equivocada es peor que un
   evento sin fecha: manda a la gente al lugar el día que no es.

3. Se distingue la hora de puertas de la hora del show. En Bolivia los afiches
   suelen anunciar las dos y son datos distintos que la gente usa distinto.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

TZ_BOLIVIA = "America/La_Paz"

# Cuántos días hacia atrás se aceptan antes de asumir que la fecha es del año
# siguiente. Un afiche del "23 de agosto" leído el 25 de agosto casi seguro
# habla del evento que acaba de pasar, no del que viene en 12 meses.
DIAS_DE_GRACIA_HACIA_ATRAS = 3

MESES = {
    "enero": 1, "ene": 1,
    "febrero": 2, "feb": 2,
    "marzo": 3, "mar": 3,
    "abril": 4, "abr": 4,
    "mayo": 5, "may": 5,
    "junio": 6, "jun": 6,
    "julio": 7, "jul": 7,
    "agosto": 8, "ago": 8, "agost": 8,
    "septiembre": 9, "setiembre": 9, "sep": 9, "sept": 9, "set": 9,
    "octubre": 10, "oct": 10,
    "noviembre": 11, "nov": 11,
    "diciembre": 12, "dic": 12,
}

MESES_LARGO = [
    "", "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

DIAS_SEMANA = {
    "lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3,
    "viernes": 4, "sabado": 5, "domingo": 6,
}

DIAS_SEMANA_LARGO = [
    "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo",
]

# Alternancia de nombres de mes ordenada de más larga a más corta: si "sep" va
# antes que "septiembre" en el patrón, la regex corta la palabra por la mitad y
# el resto ("tiembre") ensucia la captura siguiente.
_MES_ALT = "|".join(sorted(MESES, key=len, reverse=True))
_DIA_ALT = "|".join(DIAS_SEMANA)


@dataclass
class FechaEvento:
    """Cuándo pasa un evento, más el rastro de cómo se dedujo."""

    inicio: Optional[datetime] = None
    fin: Optional[datetime] = None
    hora_puertas: Optional[str] = None
    todo_el_dia: bool = True
    multidia: bool = False
    # exacta   -> día y hora explícitos en el texto
    # aproximada -> día explícito, hora ausente o ambigua
    # relativa -> "hoy", "este viernes": depende de cuándo se publicó
    # desconocida -> no se encontró nada utilizable
    confianza: str = "desconocida"
    texto_origen: str = ""
    avisos: List[str] = field(default_factory=list)

    @property
    def tiene_fecha(self) -> bool:
        return self.inicio is not None


def _sin_tildes(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in texto if not unicodedata.combining(c))


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes y con espacios colapsados, para que las regex no
    tengan que contemplar 'miércoles', 'miercoles' y 'MIÉRCOLES' por separado."""
    return re.sub(r"\s+", " ", _sin_tildes(texto or "").lower()).strip()


def _tz(nombre: str = TZ_BOLIVIA) -> ZoneInfo:
    return ZoneInfo(nombre)


def _ahora(tz_nombre: str) -> datetime:
    return datetime.now(_tz(tz_nombre))


def _armar(d: date, t: Optional[time], tz_nombre: str) -> datetime:
    return datetime.combine(d, t or time(0, 0), tzinfo=_tz(tz_nombre))


def _resolver_anio(dia: int, mes: int, anio: Optional[int], ahora: datetime) -> Optional[date]:
    """Devuelve la fecha completa, infiriendo el año cuando el texto no lo dice.

    Sin año explícito se elige la próxima ocurrencia que no haya quedado atrás
    hace más de unos pocos días.
    """
    if anio is not None:
        if anio < 100:
            anio += 2000
        try:
            return date(anio, mes, dia)
        except ValueError:
            return None

    limite = ahora.date() - timedelta(days=DIAS_DE_GRACIA_HACIA_ATRAS)
    for candidato in (ahora.year, ahora.year + 1):
        try:
            propuesta = date(candidato, mes, dia)
        except ValueError:
            # 29 de febrero en un año no bisiesto: se prueba el año siguiente.
            continue
        if propuesta >= limite:
            return propuesta
    return None


# --------------------------------------------------------------------------
# Horas
# --------------------------------------------------------------------------

_RE_HORA_HHMM = re.compile(
    r"\b(?:a\s+(?:las|hrs\.?)\s+|horas?\s+|hrs\.?\s+)?"
    r"(?P<h>[0-2]?\d)[:.](?P<m>[0-5]\d)\s*"
    r"(?P<suf>a\.?m\.?|p\.?m\.?|hrs?\.?|horas)?",
    re.IGNORECASE,
)

# Horas sin minutos. Un número suelto en un afiche es casi siempre un precio,
# un aforo o parte de una dirección, así que solo se lee como hora cuando viene
# anunciado por delante ("a las 8") o calificado por detrás ("8 pm", "8 de la
# noche"). Los dos casos van en patrones separados porque en el primero el
# sufijo es opcional y en el segundo es justamente lo que la identifica.
_RE_HORA_CON_PREFIJO = re.compile(
    r"\b(?:a\s+las|desde\s+las|a\s+hrs\.?)\s+(?P<h>[0-2]?\d)\s*"
    r"(?P<suf>a\.?m\.?|p\.?m\.?|hrs?\.?|horas)?"
    r"(?:\s*de\s+la\s+(?P<franja>manana|tarde|noche))?",
    re.IGNORECASE,
)

_RE_HORA_CON_SUFIJO = re.compile(
    r"\b(?P<h>[0-2]?\d)\s*"
    r"(?:(?P<suf>a\.?m\.?|p\.?m\.?|hrs?\.?|horas)"
    r"|de\s+la\s+(?P<franja>manana|tarde|noche))",
    re.IGNORECASE,
)

_RE_PUERTAS = re.compile(
    r"\b(?:puertas?|apertura|ingreso|admision|acceso)\s*"
    r"(?:se\s+abren?\s*)?(?:a\s+(?:las|hrs\.?)\s*)?[:\-]?\s*"
    r"(?P<h>[0-2]?\d)(?:[:.](?P<m>[0-5]\d))?",
    re.IGNORECASE,
)

_RE_SHOW = re.compile(
    r"\b(?:show|concierto|funcion|inicio|comienza|empieza|arranca|start)\s*"
    r"(?:a\s+(?:las|hrs\.?)\s*)?[:\-]?\s*"
    r"(?P<h>[0-2]?\d)(?:[:.](?P<m>[0-5]\d))?",
    re.IGNORECASE,
)


def _a_hora(h: int, m: int, sufijo: Optional[str], franja: Optional[str]) -> Optional[time]:
    suf = (sufijo or "").replace(".", "").lower()
    fr = (franja or "").lower()

    if suf.startswith("p") or fr in {"tarde", "noche"}:
        if h < 12:
            h += 12
    elif suf.startswith("a") or fr == "manana":
        if h == 12:
            h = 0
    elif fr == "" and suf == "" and h <= 11:
        # Un evento anunciado como "a las 8" en Bolivia es de noche salvo que
        # diga lo contrario; a las 8 de la mañana se escribe "8 am" o "8:00 AM".
        # Las horas de 1 a 11 sin sufijo se asumen de la tarde/noche, que es lo
        # que ocurre en la enorme mayoría de los afiches.
        if 1 <= h <= 11:
            h += 12

    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return time(h, m)


def _texto_hora(t: time) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def extraer_horas(texto: str) -> Tuple[Optional[time], Optional[str]]:
    """Devuelve (hora de inicio del show, hora de puertas como texto).

    Cuando el afiche anuncia las dos, la hora del evento es la del show y la de
    puertas se guarda aparte: son datos distintos y la gente los usa distinto.
    """
    plano = normalizar(texto)

    puertas_t: Optional[time] = None
    m = _RE_PUERTAS.search(plano)
    if m:
        puertas_t = _a_hora(int(m.group("h")), int(m.group("m") or 0), None, None)

    show_t: Optional[time] = None
    m = _RE_SHOW.search(plano)
    if m:
        show_t = _a_hora(int(m.group("h")), int(m.group("m") or 0), None, None)

    if show_t:
        return show_t, (_texto_hora(puertas_t) if puertas_t else None)

    # Sin un "show:" explícito, se toma la primera hora con minutos del texto.
    for m in _RE_HORA_HHMM.finditer(plano):
        candidata = _a_hora(
            int(m.group("h")), int(m.group("m")), m.group("suf"), None
        )
        if candidata and (puertas_t is None or candidata != puertas_t):
            return candidata, (_texto_hora(puertas_t) if puertas_t else None)

    for patron in (_RE_HORA_CON_PREFIJO, _RE_HORA_CON_SUFIJO):
        for m in patron.finditer(plano):
            candidata = _a_hora(int(m.group("h")), 0, m.group("suf"), m.group("franja"))
            if candidata and (puertas_t is None or candidata != puertas_t):
                return candidata, (_texto_hora(puertas_t) if puertas_t else None)

    # Solo había hora de puertas: sirve como hora del evento y además se
    # conserva etiquetada como tal.
    if puertas_t:
        return puertas_t, _texto_hora(puertas_t)

    return None, None


# --------------------------------------------------------------------------
# Días
# --------------------------------------------------------------------------

# "del 5 al 7 de septiembre" / "5 al 7 de septiembre de 2026"
_RE_RANGO_MISMO_MES = re.compile(
    rf"\b(?:del?\s+)?(?P<d1>[0-3]?\d)\s*(?:al|hasta el|a|-|–|—)\s*(?P<d2>[0-3]?\d)\s+de\s+"
    rf"(?P<mes>{_MES_ALT})\b(?:\s+(?:de[l]?\s+)?(?P<anio>\d{{4}}))?",
    re.IGNORECASE,
)

# "del 28 de agosto al 2 de septiembre"
_RE_RANGO_CRUZADO = re.compile(
    rf"\b(?:del?\s+)?(?P<d1>[0-3]?\d)\s+de\s+(?P<mes1>{_MES_ALT})"
    rf"(?:\s+(?:de[l]?\s+)?(?P<anio1>\d{{4}}))?"
    rf"\s*(?:al|hasta el|-|–|—)\s*(?P<d2>[0-3]?\d)\s+de\s+(?P<mes2>{_MES_ALT})"
    rf"(?:\s+(?:de[l]?\s+)?(?P<anio2>\d{{4}}))?",
    re.IGNORECASE,
)

# "23 de agosto", "sábado 23 de agosto de 2026"
_RE_DIA_DE_MES = re.compile(
    rf"\b(?:(?P<dia_semana>{_DIA_ALT})\s+)?(?P<dia>[0-3]?\d)\s+de\s+"
    rf"(?P<mes>{_MES_ALT})\b(?:\s+(?:de[l]?\s+)?(?P<anio>\d{{4}}))?",
    re.IGNORECASE,
)

# "2026-08-23", "2026-08-23T20:00". Las ticketeras y los sitios con datos
# estructurados (schema.org/Event) publican así, y es la forma más confiable de
# todas: no hay que inferir el año ni adivinar si 03/05 es marzo o mayo.
_RE_ISO = re.compile(
    r"\b(?P<anio>20\d{2})-(?P<mes>[01]\d)-(?P<dia>[0-3]\d)\b"
)

# "15/03/2026", "15-03", "15.03.26"
_RE_NUMERICA = re.compile(
    r"(?<![\d/.-])(?P<dia>[0-3]?\d)[/\-.](?P<mes>[01]?\d)"
    r"(?:[/\-.](?P<anio>\d{2,4}))?(?![\d/.-])"
)

_RE_HOY = re.compile(r"\bhoy\b", re.IGNORECASE)
_RE_MANANA = re.compile(r"\bmanana\b", re.IGNORECASE)
_RE_PASADO_MANANA = re.compile(r"\bpasado\s+manana\b", re.IGNORECASE)

_RE_DIA_RELATIVO = re.compile(
    rf"\b(?P<cual>este|esta|proximo|proxima|el)\s+(?P<dia>{_DIA_ALT})\b",
    re.IGNORECASE,
)


def _fecha_desde_relativo(plano: str, ahora: datetime) -> Optional[Tuple[date, str]]:
    """Fechas expresadas en relación al momento de publicación."""
    if _RE_PASADO_MANANA.search(plano):
        return ahora.date() + timedelta(days=2), "pasado manana"
    if _RE_MANANA.search(plano):
        return ahora.date() + timedelta(days=1), "manana"
    if _RE_HOY.search(plano):
        return ahora.date(), "hoy"

    m = _RE_DIA_RELATIVO.search(plano)
    if m:
        objetivo = DIAS_SEMANA[m.group("dia")]
        delta = (objetivo - ahora.weekday()) % 7
        if delta == 0 and m.group("cual").lower() in {"proximo", "proxima"}:
            delta = 7
        # "este sábado" dicho un sábado se entiende como hoy mismo; "próximo
        # sábado" siempre empuja a la semana que viene.
        return ahora.date() + timedelta(days=delta), m.group(0)
    return None


def _buscar_dias(plano: str, ahora: datetime) -> Optional[Tuple[date, Optional[date], str]]:
    """Primera fecha (o rango) utilizable del texto.

    El orden importa por dos razones. La fecha ISO va primera porque es la única
    que no necesita inferir nada. Y los rangos van antes que las fechas sueltas
    porque "del 5 al 7 de septiembre" contiene un "7 de septiembre" que, leído
    solo, perdería el día de inicio del festival.
    """
    # Un rango ISO ("2026-09-05 ... 2026-09-07") se arma con las dos primeras
    # fechas si la segunda es posterior; si no, la primera manda sola.
    iso = list(_RE_ISO.finditer(plano))
    if iso:
        def _a_fecha(m):
            try:
                return date(int(m.group("anio")), int(m.group("mes")), int(m.group("dia")))
            except ValueError:
                return None

        d1 = _a_fecha(iso[0])
        if d1:
            d2 = _a_fecha(iso[1]) if len(iso) > 1 else None
            return d1, (d2 if d2 and d2 > d1 else None), iso[0].group(0)

    m = _RE_RANGO_CRUZADO.search(plano)
    if m:
        mes1, mes2 = MESES[m.group("mes1")], MESES[m.group("mes2")]
        anio1 = int(m.group("anio1")) if m.group("anio1") else None
        anio2 = int(m.group("anio2")) if m.group("anio2") else None
        d1 = _resolver_anio(int(m.group("d1")), mes1, anio1, ahora)
        if d1:
            # Un rango que cruza diciembre cae en el año siguiente al del inicio.
            base = d1.year if mes2 >= mes1 else d1.year + 1
            d2 = _resolver_anio(int(m.group("d2")), mes2, anio2 or base, ahora)
            if d2 and d2 >= d1:
                return d1, d2, m.group(0)

    m = _RE_RANGO_MISMO_MES.search(plano)
    if m:
        mes = MESES[m.group("mes")]
        anio = int(m.group("anio")) if m.group("anio") else None
        d1 = _resolver_anio(int(m.group("d1")), mes, anio, ahora)
        d2 = _resolver_anio(int(m.group("d2")), mes, anio or (d1.year if d1 else None), ahora)
        if d1 and d2 and d2 >= d1:
            return d1, d2, m.group(0)

    m = _RE_DIA_DE_MES.search(plano)
    if m:
        d = _resolver_anio(
            int(m.group("dia")), MESES[m.group("mes")],
            int(m.group("anio")) if m.group("anio") else None, ahora,
        )
        if d:
            return d, None, m.group(0)

    m = _RE_NUMERICA.search(plano)
    if m:
        mes = int(m.group("mes"))
        if 1 <= mes <= 12:
            d = _resolver_anio(
                int(m.group("dia")), mes,
                int(m.group("anio")) if m.group("anio") else None, ahora,
            )
            if d:
                return d, None, m.group(0)

    relativo = _fecha_desde_relativo(plano, ahora)
    if relativo:
        return relativo[0], None, relativo[1]

    return None


def parsear_fecha(
    texto: str,
    ahora: Optional[datetime] = None,
    publicado_en: Optional[datetime] = None,
    tz_nombre: str = TZ_BOLIVIA,
) -> FechaEvento:
    """Extrae cuándo ocurre el evento descrito en `texto`.

    `publicado_en` ancla las expresiones relativas: "este viernes" en un post de
    hace tres días no es el mismo viernes que "este viernes" leído hoy.
    """
    if ahora is None:
        ahora = _ahora(tz_nombre)
    ancla = publicado_en or ahora
    if ancla.tzinfo is None:
        ancla = ancla.replace(tzinfo=_tz(tz_nombre))

    plano = normalizar(texto)
    if not plano:
        return FechaEvento(avisos=["texto_vacio"])

    dias = _buscar_dias(plano, ancla)
    if not dias:
        return FechaEvento(confianza="desconocida", avisos=["sin_fecha_en_el_texto"])

    dia_inicio, dia_fin, origen = dias
    hora, puertas = extraer_horas(texto)

    inicio = _armar(dia_inicio, hora, tz_nombre)
    fin = None
    if dia_fin and dia_fin != dia_inicio:
        # El último día de un festival se cierra al final del día: sin hora de
        # cierre publicada, dar por terminado el evento a las 00:00 de ese día
        # lo mostraría como finalizado durante toda su última jornada.
        fin = _armar(dia_fin, time(23, 59), tz_nombre)

    es_relativa = origen in {"hoy", "manana", "pasado manana"} or bool(
        _RE_DIA_RELATIVO.fullmatch(origen or "")
    )
    if hora:
        confianza = "relativa" if es_relativa else "exacta"
    else:
        confianza = "relativa" if es_relativa else "aproximada"

    avisos = []
    if not hora:
        avisos.append("sin_hora_en_el_texto")
    if es_relativa and publicado_en is None:
        # Sin fecha de publicación, "este viernes" se ancla al momento de la
        # corrida, que puede ser días después de que se escribió el afiche.
        avisos.append("fecha_relativa_sin_fecha_de_publicacion")

    return FechaEvento(
        inicio=inicio,
        fin=fin,
        hora_puertas=puertas,
        todo_el_dia=hora is None,
        multidia=bool(fin),
        confianza=confianza,
        texto_origen=origen.strip(),
        avisos=avisos,
    )


# --------------------------------------------------------------------------
# Presentación: la app no debería tener que formatear fechas en español
# --------------------------------------------------------------------------

def fecha_legible(fecha: FechaEvento) -> Optional[str]:
    """Texto listo para pintar en pantalla, ya en español y sin trabajo para la app.

    Ejemplos: "Sábado 23 de agosto · 20:00", "Del 5 al 7 de septiembre".
    """
    if not fecha.inicio:
        return None

    inicio = fecha.inicio
    dia_semana = DIAS_SEMANA_LARGO[inicio.weekday()].capitalize()
    mes = MESES_LARGO[inicio.month]

    if fecha.multidia and fecha.fin:
        if fecha.inicio.month == fecha.fin.month:
            base = f"Del {inicio.day} al {fecha.fin.day} de {mes}"
        else:
            base = (
                f"Del {inicio.day} de {mes} "
                f"al {fecha.fin.day} de {MESES_LARGO[fecha.fin.month]}"
            )
    else:
        base = f"{dia_semana} {inicio.day} de {mes}"

    if not fecha.todo_el_dia:
        base += f" · {inicio.hour:02d}:{inicio.minute:02d}"
    return base


def a_millis(momento: Optional[datetime]) -> Optional[int]:
    """Epoch en milisegundos: la app ordena y filtra con enteros en vez de
    parsear ISO-8601 en cada scroll."""
    if momento is None:
        return None
    return int(momento.timestamp() * 1000)


def ciclo_de_vida(fecha: FechaEvento, ahora: Optional[datetime] = None,
                  tz_nombre: str = TZ_BOLIVIA) -> str:
    """En qué momento de su vida está el evento: sin_fecha, proximo, hoy,
    en_curso o finalizado."""
    if ahora is None:
        ahora = _ahora(tz_nombre)
    if not fecha.inicio:
        return "sin_fecha"

    inicio, fin = fecha.inicio, fecha.fin

    if fin and inicio <= ahora <= fin:
        return "en_curso"
    if ahora.date() == inicio.date():
        return "hoy"
    if inicio > ahora:
        return "proximo"

    if not fin:
        # Un evento de un solo día sin hora de cierre sigue contando como "hoy"
        # hasta que termine la jornada: a las 21:00 la gente todavía busca el
        # concierto que empezó a las 20:00.
        cierre = _armar(inicio.date(), time(23, 59), tz_nombre)
        if ahora <= cierre:
            return "hoy"
    return "finalizado"


def dias_restantes(fecha: FechaEvento, ahora: Optional[datetime] = None,
                   tz_nombre: str = TZ_BOLIVIA) -> Optional[int]:
    """Días calendario que faltan. 0 es hoy, negativo es que ya pasó."""
    if ahora is None:
        ahora = _ahora(tz_nombre)
    if not fecha.inicio:
        return None
    return (fecha.inicio.date() - ahora.date()).days
