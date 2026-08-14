"""Convierte una publicación cualquiera en un evento entendido — o la descarta.

La mayor parte de lo que publica una página de Facebook no es un evento futuro:
son saludos, notas de prensa, fotos de algo que ya pasó, promociones de
productos. El trabajo de este módulo es separar lo poco que sirve.

La señal más fuerte, de lejos, es **una fecha futura**. Un afiche de un
concierto sin fecha es casi siempre una foto del concierto de anoche. Por eso el
puntaje se apoya en la fecha y usa el resto —sede, precio, categoría, entradas—
para confirmar, no para reemplazarla.

El puntaje también resta. "Gracias a todos los que nos acompañaron" contiene la
palabra "concierto", el nombre de un teatro y hasta una fecha, y sin señales
negativas entraría al JSON como un evento por venir.
"""

import hashlib
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from dateutil import parser as dateparser

from .fechas import (
    TZ_BOLIVIA,
    ciclo_de_vida,
    dias_restantes,
    fecha_legible,
    parsear_fecha,
    a_millis,
)
from .lugares import consulta_de_mapa, resolver_ubicacion
from .models import Evento, RawItem

UMBRAL_RELEVANCIA = 55

# --------------------------------------------------------------------------
# Categorías
# --------------------------------------------------------------------------
# El orden importa: la primera categoría que acumula más aciertos gana, y ante
# empate gana la que aparece antes en esta lista. Por eso "concierto" va antes
# que "cultural": un recital en un centro cultural sigue siendo un concierto.

CATEGORIAS: List[Tuple[str, List[str]]] = [
    ("concierto", [
        r"\bconcierto\b", r"\brecital\b", r"\bshow en vivo\b", r"\btocada\b",
        r"\bgira\b", r"\btour\b", r"\bm[uú]sica en vivo\b", r"\ben vivo\b",
        r"\bbanda\b", r"\bdj\b", r"\bset\b", r"\bunplugged\b", r"\bac[uú]stico\b",
        r"\blanzamiento de disco\b", r"\bpresentaci[oó]n musical\b",
    ]),
    ("festival", [
        r"\bfestival\b", r"\bfest\b", r"\bencuentro de\b", r"\bfestividad\b",
        r"\bcarnaval\b", r"\bentrada folkl[oó]rica\b", r"\bcorso\b",
        r"\bfiesta patronal\b", r"\bmegafestival\b",
    ]),
    ("feria", [
        r"\bferia\b", r"\bexpo\b", r"\bexposici[oó]n comercial\b", r"\bexpoferia\b",
        r"\bferia del libro\b", r"\bferia gastron[oó]mica\b", r"\brueda de negocios\b",
        r"\bmercado de\b", r"\bbazar\b", r"\bemprendedor",
    ]),
    ("teatro", [
        r"\bteatro\b", r"\bobra de teatro\b", r"\bmonologo\b", r"\bmon[oó]logo\b",
        r"\bcomedia\b", r"\bstand ?up\b", r"\bpuesta en escena\b", r"\belenco\b",
        r"\bfunci[oó]n\b", r"\bdramaturgia\b", r"\bimprovisaci[oó]n teatral\b",
    ]),
    ("danza", [
        r"\bdanza\b", r"\bballet\b", r"\bbaile\b", r"\bcoreograf[ií]a\b",
        r"\bfolkl[oó]rico\b", r"\bfolcl[oó]rico\b", r"\bsalsa\b", r"\bbachata\b",
        r"\btango\b", r"\bcontempor[aá]nea\b",
    ]),
    ("deporte", [
        r"\bpartido\b", r"\bcampeonato\b", r"\btorneo\b", r"\bmarat[oó]n\b",
        r"\bcarrera\b", r"\bcopa\b", r"\bliga\b", r"\bcl[aá]sico\b",
        r"\bciclismo\b", r"\bautom[oó]vilismo\b", r"\brally\b", r"\bbox\b",
        r"\bmma\b", r"\bfutsal\b", r"\bv[oó]ley\b", r"\bbasquet\b", r"\bb[aá]squet\b",
    ]),
    ("gastronomia", [
        r"\bgastron[oó]mic", r"\bdegustaci[oó]n\b", r"\bcata\b", r"\bfood\b",
        r"\bcerveza artesanal\b", r"\bvino\b", r"\bsingani\b", r"\bchef\b",
        r"\bculinari", r"\bplato\b", r"\bcocina\b", r"\bbrunch\b",
    ]),
    ("cine", [
        r"\bcine\b", r"\bpel[ií]cula\b", r"\bcortometraje\b", r"\bdocumental\b",
        r"\bproyecci[oó]n\b", r"\bestreno\b", r"\bcineclub\b", r"\bfilme\b",
    ]),
    ("exposicion", [
        r"\bexposici[oó]n\b", r"\bmuestra\b", r"\bgaler[ií]a\b", r"\bvernissage\b",
        r"\binauguraci[oó]n de la muestra\b", r"\bcolecci[oó]n\b", r"\bretrospectiva\b",
        r"\bartes visuales\b", r"\bfotograf[ií]a\b", r"\bpintura\b", r"\bescultura\b",
    ]),
    ("conferencia", [
        r"\bconferencia\b", r"\bcongreso\b", r"\bseminario\b", r"\bsimposio\b",
        r"\bforo\b", r"\bpanel\b", r"\bcharla\b", r"\bdisertaci[oó]n\b",
        r"\bconversatorio\b", r"\bjornada\b", r"\bsummit\b", r"\bmeetup\b",
    ]),
    ("taller", [
        r"\btaller\b", r"\bcurso\b", r"\bcapacitaci[oó]n\b", r"\bworkshop\b",
        r"\bdiplomado\b", r"\bmasterclass\b", r"\bclase magistral\b",
        r"\bentrenamiento\b", r"\bbootcamp\b", r"\binscripciones abiertas\b",
    ]),
    ("infantil", [
        r"\binfantil\b", r"\bpara ni[nñ]os\b", r"\bninos y ni[nñ]as\b",
        r"\btiteres\b", r"\bt[ií]teres\b", r"\bcuentacuentos\b", r"\bkids\b",
        r"\bvacaci[oó]n(?:es)? [uú]til(?:es)?\b", r"\bfamiliar\b",
    ]),
    ("religioso", [
        r"\bmisa\b", r"\bprocesi[oó]n\b", r"\bnovena\b", r"\bperegrinaci[oó]n\b",
        r"\bpascua\b", r"\bvigilia de oraci[oó]n\b", r"\bculto\b", r"\bretiro espiritual\b",
    ]),
    ("nightlife", [
        r"\bfiesta\b", r"\bafter\b", r"\bdiscoteca\b", r"\bparty\b",
        r"\bnoche de\b", r"\bopen bar\b", r"\bpre[- ]?fiesta\b", r"\brumba\b",
    ]),
    ("moda", [
        r"\bdesfile de moda\b", r"\bpasarela\b", r"\bfashion\b", r"\bmodelaje\b",
    ]),
    ("tecnologia", [
        r"\bhackath[oó]n\b", r"\btecnolog[ií]a\b", r"\bstartup\b", r"\bgaming\b",
        r"\besports\b", r"\be-sports\b", r"\brobotica\b", r"\brob[oó]tica\b",
        r"\binteligencia artificial\b",
    ]),
]

# Palabras que anuncian que algo está por pasar. Son el contrapeso directo de
# las de tiempo pasado y valen mucho en el puntaje.
CONVOCATORIA = [
    r"\bte esperamos\b", r"\bno te lo pierdas\b", r"\bno faltes\b",
    r"\bs[eé] parte\b", r"\bacomp[aá][nñ]anos\b", r"\bnos vemos\b",
    r"\bprep[aá]rate\b", r"\breserva (?:tu|la) fecha\b", r"\bsave the date\b",
    r"\bya vienen?\b", r"\bpr[oó]ximamente\b", r"\bvuelve\b", r"\bllega\b",
    r"\bpresentamos\b", r"\bse viene\b", r"\bagenda\b", r"\banuncia",
    r"\bcompra tus entradas\b", r"\badquiere tus entradas\b",
    r"\binscr[ií]bete\b", r"\bregistrate\b", r"\breg[ií]strate\b",
    r"\bcupos limitados\b", r"\búltimas entradas\b", r"\bultimas entradas\b",
]

# Lo que delata una crónica de algo que ya ocurrió. Un afiche nunca habla en
# pretérito de su propio evento.
PASADO = [
    r"\bse realiz[oó]\b", r"\bse llev[oó] a cabo\b", r"\bse desarroll[oó]\b",
    r"\btuvo lugar\b", r"\bfue inaugurad", r"\bcerr[oó] sus puertas\b",
    r"\bculmin[oó]\b", r"\bfinaliz[oó]\b", r"\bconcluy[oó]\b",
    r"\bgracias a todos\b", r"\bgracias por acompa[nñ]arnos\b",
    r"\bfue un [eé]xito\b", r"\bas[ií] se vivi[oó]\b", r"\brevive\b",
    r"\bresumen de\b", r"\bbalance de\b", r"\bel pasado\b", r"\banoche\b",
    r"\bayer\b", r"\bla noche del\b", r"\bse present[oó]\b", r"\brecibi[oó] a\b",
    r"\bganador(?:es)? de\b", r"\bpremiaci[oó]n de la pasada\b",
]

# Temas que no son eventos por más que traigan fecha y lugar.
DESCARTES = [
    r"\bfallecimiento\b", r"\bcondolencias\b", r"\bsentido p[eé]same\b",
    r"\bconvocatoria (?:p[uú]blica )?(?:de|para) (?:contrataci[oó]n|personal)\b",
    r"\bofert[ao] laboral\b", r"\bempleo\b", r"\bcurr[ií]culum\b",
    r"\blicitaci[oó]n\b", r"\bcomunicado de prensa sobre\b",
    r"\bhoroscopo\b", r"\bhor[oó]scopo\b", r"\bsorteo de\b", r"\bpromoci[oó]n v[aá]lida\b",
    r"\bdescuento en\b", r"\bcr[eé]dito\b", r"\bpr[eé]stamo\b", r"\bseguro\b",
    r"\btarifa\b", r"\bcorte de agua\b", r"\bcorte de luz\b",
    r"\bbloqueo\b", r"\bparo\b", r"\bmarcha de protesta\b", r"\baccidente\b",
    r"\bdetenido\b", r"\baprehendid", r"\bhurto\b", r"\brobo\b",
]

ESTADOS = [
    ("cancelado", [r"\bcancelad", r"\bsuspendid", r"\bse cancela\b", r"\bqueda sin efecto\b"]),
    ("postergado", [r"\bposterga", r"\breprograma", r"\bnueva fecha\b", r"\baplaza"]),
    ("agotado", [r"\bagotad", r"\bsold ?out\b", r"\bentradas agotadas\b", r"\bno hay entradas\b"]),
]

# --------------------------------------------------------------------------
# Entradas y precios
# --------------------------------------------------------------------------

GRATIS_RE = re.compile(
    r"\b(?:entrada|ingreso|acceso|admisi[oó]n|evento)\s+(?:es\s+)?"
    r"(?:libre|gratuita?|gratis|liberado|sin costo)\b"
    r"|\bgratis\b|\bgratuito\b|\bfree\b|\bsin costo\b|\bentrada libre\b",
    re.IGNORECASE,
)

# "Bs 50", "Bs. 50", "50 Bs", "50 bolivianos". El símbolo puede ir de los dos
# lados y con o sin punto, que es como realmente se escribe en los afiches.
PRECIO_RE = re.compile(
    r"(?:\bbs\.?\s*/?\s*(?P<antes>\d{1,4}(?:[.,]\d{1,2})?)"
    r"|(?P<despues>\d{1,4}(?:[.,]\d{1,2})?)\s*(?:bs\.?\b|bolivianos?\b))",
    re.IGNORECASE,
)

DOMINIOS_TICKETERA = [
    "superticket.bo", "ticket.bo", "tuentrada.com.bo", "passlinebolivia.com",
    "passline.com", "ticketeg.com", "eventbrite.com", "bandsintown.com",
    "fexpocruz.com.bo", "entradas",
]

# (patrón a buscar, cómo mostrarlo en la app). Van separados porque el patrón
# tiene que tolerar cómo se escribe de verdad y el nombre mostrado tiene que
# verse bien en una lista.
PUNTOS_VENTA: List[Tuple[str, str]] = [
    (r"\bfarmacorp\b", "Farmacorp"),
    (r"\bsuper ?ticket\b", "SuperTicket"),
    (r"\bticket\.bo\b", "Ticket.bo"),
    (r"\btu entrada\b", "Tu Entrada"),
    (r"\bpassline\b", "Passline"),
    (r"\bticketeg\b", "Ticketeg"),
    (r"\bboleter[ií]a\b", "Boletería"),
    (r"\bpuntos? de venta\b", "Puntos de venta"),
    (r"\bpreventa\b", "Preventa"),
    (r"\ben puerta\b", "Venta en puerta"),
]

TELEFONO_RE = re.compile(
    r"(?:\+?591[\s\-]?)?(?<!\d)([67]\d{7})(?!\d)"      # celulares
    r"|(?:\+?591[\s\-]?)?(?<!\d)([2-4][\s\-]?\d{6,7})(?!\d)"  # fijos
)

URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+", re.IGNORECASE)

# El nombre capturado suele venir pegado a la frase que lo sigue ("Luis Rico en
# concierto", "Savia Andina este sábado"). Se corta en la primera bisagra que
# claramente ya no es parte del nombre — pero no en "y", porque "Los Kjarkas y
# Savia Andina" son dos artistas de un mismo afiche y ambos importan.
CORTE_ARTISTA_RE = re.compile(
    r"\s+(?:en\s+(?:concierto|vivo|el|la|los|las)"
    r"|est[ae]\b|pr[oó]xim[oa]\b"
    r"|el\s+(?:d[ií]a|pr[oó]ximo|lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)"
    r"|a\s+las\b|desde\s+las\b|por\s+primera\s+vez\b|junto\s+a\b|llega\b|vuelve\b)"
    r".*$",
    re.IGNORECASE,
)

ARTISTA_RE = [
    re.compile(r"\bpresent(?:a|an|amos)\s+a\s+(?P<n>[^.,;:\n!¡?¿]{3,60})", re.IGNORECASE),
    re.compile(r"\bcon\s+la\s+presencia\s+de\s+(?P<n>[^.,;:\n!¡?¿]{3,60})", re.IGNORECASE),
    re.compile(r"\bartista\s+invitad[oa]\s*[:\-]?\s*(?P<n>[^.,;:\n!¡?¿]{3,60})", re.IGNORECASE),
    re.compile(r"\ben\s+concierto\s*[:\-]\s*(?P<n>[^.,;:\n!¡?¿]{3,60})", re.IGNORECASE),
    re.compile(r"\bteloner[oa]s?\s*[:\-]?\s*(?P<n>[^.,;:\n!¡?¿]{3,60})", re.IGNORECASE),
]


def _plano(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", texto).strip()


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKC", texto or "")
    return re.sub(r"[ \t]+", " ", texto).strip()


def _aciertos(patrones: List[str], plano: str) -> int:
    return sum(1 for p in patrones if re.search(p, plano))


def _unicos(valores: List[str], limite: int) -> List[str]:
    vistos, salida = set(), []
    for v in valores:
        v = re.sub(r"\s+", " ", (v or "")).strip(" .,;:-·|")
        clave = v.lower()
        if v and clave not in vistos:
            vistos.add(clave)
            salida.append(v)
        if len(salida) >= limite:
            break
    return salida


def detectar_categoria(texto: str) -> Tuple[str, List[str]]:
    """(categoría principal, otras categorías con señal en el texto)."""
    plano = _plano(texto)
    puntajes = [(nombre, _aciertos(patrones, plano)) for nombre, patrones in CATEGORIAS]
    con_señal = [(n, p) for n, p in puntajes if p > 0]
    if not con_señal:
        return "otro", []

    # max() sobre la lista original conserva el orden de CATEGORIAS al empatar.
    principal = max(con_señal, key=lambda x: x[1])[0]
    secundarias = [n for n, p in con_señal if n != principal and p >= 1]
    return principal, secundarias[:4]


def detectar_estado(texto: str) -> str:
    plano = _plano(texto)
    for estado, patrones in ESTADOS:
        if any(re.search(p, plano) for p in patrones):
            return estado
    return "programado"


def extraer_precios(texto: str) -> Dict[str, Any]:
    """Precio de la entrada tal como lo anuncia el afiche.

    Se guardan el mínimo y el máximo encontrados, no un precio único: casi
    siempre hay al menos dos (preventa y puerta, o platea y general) y la app
    muestra "desde Bs 50".
    """
    plano = _plano(texto)
    gratis = bool(GRATIS_RE.search(plano))

    valores: List[float] = []
    for m in PRECIO_RE.finditer(plano):
        crudo = m.group("antes") or m.group("despues")
        try:
            valor = float(crudo.replace(",", "."))
        except ValueError:
            continue
        # Un afiche no cobra 0 Bs ni 90.000 Bs por una entrada; fuera de ese
        # rango casi siempre es un año, un teléfono o un número de sorteo.
        if 1 <= valor <= 5000:
            valores.append(valor)

    texto_precio = None
    if valores:
        m = PRECIO_RE.search(normalizar(texto))
        if m:
            inicio = max(0, m.start() - 40)
            texto_precio = re.sub(r"\s+", " ", normalizar(texto)[inicio:m.end() + 40]).strip()
    elif gratis:
        texto_precio = "Entrada libre"

    return {
        "is_free": gratis and not valores,
        "price_from": min(valores) if valores else None,
        "price_to": max(valores) if len(valores) > 1 else None,
        "currency": "BOB" if valores else None,
        "price_text": texto_precio,
    }


def extraer_enlaces(texto: str, extra: Optional[List[str]] = None) -> Dict[str, List[str]]:
    urls = URL_RE.findall(texto or "") + list(extra or [])
    entradas = [
        u for u in urls
        if any(d in u.lower() for d in DOMINIOS_TICKETERA)
    ]
    return {"ticket_urls": _unicos(entradas, 6), "all_urls": _unicos(urls, 12)}


def extraer_puntos_venta(texto: str) -> List[str]:
    plano = _plano(texto)
    return _unicos(
        [nombre for patron, nombre in PUNTOS_VENTA if re.search(patron, plano)], 6
    )


def extraer_telefonos(texto: str) -> List[str]:
    numeros = []
    for m in TELEFONO_RE.finditer(texto or ""):
        numero = (m.group(1) or m.group(2) or "").replace(" ", "").replace("-", "")
        if numero:
            numeros.append(numero)
    return _unicos(numeros, 4)


def extraer_artistas(texto: str) -> List[str]:
    """Solo con fórmulas explícitas ("presenta a X").

    Se probó también levantar los renglones en mayúsculas de los afiches, pero
    ahí caen el nombre del lugar, la fecha y el "ENTRADA LIBRE"; un listado de
    artistas equivocado se ve peor en la app que no tener ninguno.
    """
    nombres = []
    for patron in ARTISTA_RE:
        for m in patron.finditer(texto or ""):
            nombre = re.sub(r"\s+", " ", m.group("n")).strip()
            nombre = CORTE_ARTISTA_RE.sub("", nombre).strip(" .,;:-·|\"'")
            if 3 <= len(nombre) <= 60 and not nombre.lower().startswith("todos"):
                nombres.append(nombre)
    return _unicos(nombres, 6)


def extraer_etiquetas(texto: str) -> List[str]:
    etiquetas = re.findall(r"#(\w{3,30})", texto or "")
    return _unicos(etiquetas, 12)


def titulo_de(item: RawItem, texto: str, categoria: str, fecha_txt: Optional[str]) -> str:
    """Un título corto y presentable.

    Los afiches no traen título: traen un bloque de texto que empieza con
    emojis y saltos de línea. Se toma el primer renglón con sustancia y se lo
    limpia; si no hay ninguno, se arma uno con la categoría y la fecha.
    """
    if item.title and len(item.title.strip()) > 10:
        base = item.title.strip()
    else:
        base = ""
        for linea in (texto or "").splitlines():
            limpia = re.sub(r"[^\w\sÁÉÍÓÚÑáéíóúñ¡!¿?'\"().,:&/-]", " ", linea)
            limpia = re.sub(r"\s+", " ", limpia).strip(" .,;:-·|")
            if len(limpia) >= 12:
                base = limpia
                break

    if not base:
        etiqueta = categoria.replace("_", " ").capitalize()
        base = f"{etiqueta} en Bolivia" if not fecha_txt else f"{etiqueta} · {fecha_txt}"

    if len(base) > 120:
        base = base[:117].rsplit(" ", 1)[0] + "…"
    return base


def fecha_de_publicacion(item: RawItem) -> Optional[datetime]:
    """Cuándo se publicó el post, si se puede saber.

    Facebook rara vez entrega una fecha limpia: lo normal es "hace 2 h", "Ayer a
    las 19:30" o el nombre del día. Se resuelven a mano los formatos relativos
    frecuentes y se deja `dateutil` para los casos en que sí vino un `datetime`
    de verdad. Devolver `None` es una respuesta válida y preferible a inventar:
    quien la usa (el ancla de "este viernes") se cae con elegancia al momento de
    la corrida.
    """
    crudo = (item.published_at or "").strip()
    if not crudo:
        return None

    ahora = datetime.now(ZoneInfo(TZ_BOLIVIA))
    plano = _plano(crudo)

    m = re.search(r"\bhace\s+(\d+)\s*(min|minuto|h|hora|d|dia)", plano)
    if m:
        cantidad = int(m.group(1))
        unidad = m.group(2)
        if unidad.startswith("min"):
            return ahora - timedelta(minutes=cantidad)
        if unidad.startswith(("h", "hora")):
            return ahora - timedelta(hours=cantidad)
        return ahora - timedelta(days=cantidad)

    if "ayer" in plano:
        return ahora - timedelta(days=1)
    if "hoy" in plano:
        return ahora

    try:
        parsed = dateparser.parse(crudo, fuzzy=True)
    except (ValueError, OverflowError, TypeError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(TZ_BOLIVIA))
    return parsed


def analizar(item: RawItem, ahora=None) -> Dict[str, Any]:
    """Puntúa la publicación y devuelve todo lo que se logró extraer.

    Se devuelve el análisis completo aunque la publicación se rechace: eso es lo
    que después alimenta `estado_fuentes.json`, que es donde se ve *por qué* una
    fuente no está aportando eventos.
    """
    texto = normalizar(item.text)
    if len(texto) < 25:
        return {
            "accepted": False, "score": 0, "reasons": ["texto_muy_corto"],
            "reason": "texto_muy_corto", "category": "otro",
        }

    plano = _plano(texto)
    fecha = parsear_fecha(
        texto, ahora=ahora, publicado_en=fecha_de_publicacion(item)
    )
    categoria, subcategorias = detectar_categoria(texto)
    ubicacion = resolver_ubicacion(texto, item.region_hint, item.city_hint)
    precios = extraer_precios(texto)
    enlaces = extraer_enlaces(texto, item.external_links)

    convocatoria = _aciertos(CONVOCATORIA, plano)
    pasado = _aciertos(PASADO, plano)
    descartes = _aciertos(DESCARTES, plano)

    ciclo = ciclo_de_vida(fecha, ahora=ahora) if fecha.tiene_fecha else "sin_fecha"

    score = 0
    razones: List[str] = []

    if fecha.tiene_fecha:
        if ciclo in {"proximo", "hoy", "en_curso"}:
            score += 34
            razones.append("fecha_futura")
        else:
            score += 6
            razones.append("fecha_pasada")
        if not fecha.todo_el_dia:
            score += 10
            razones.append("hora_explicita")
        if fecha.confianza == "exacta":
            score += 4
    else:
        razones.append("sin_fecha")

    if categoria != "otro":
        score += 16
        razones.append(f"categoria_{categoria}")
    if ubicacion["venue"]:
        score += 12
        razones.append("sede_detectada")
    if precios["price_from"] is not None or precios["is_free"]:
        score += 13
        razones.append("informacion_de_entradas")
    if enlaces["ticket_urls"] or item.facebook_event_url:
        score += 11
        razones.append("enlace_de_entradas")
    if convocatoria:
        score += min(convocatoria * 6, 14)
        razones.append("lenguaje_de_convocatoria")
    if item.image_urls:
        # Los eventos se anuncian con afiche. Una nota sin ninguna imagen es
        # mucho más probable que sea texto periodístico que una convocatoria.
        score += 6
        razones.append("tiene_afiche")
    if item.source_class in {"eventos", "ticketera", "venue"}:
        score += 8
        razones.append("fuente_especializada")

    if pasado:
        castigo = min(pasado * 14, 34)
        score -= castigo
        razones.append("lenguaje_en_pasado")
    if descartes:
        score -= min(descartes * 18, 40)
        razones.append("tema_no_es_evento")

    score = max(0, min(100, score))

    # Un evento sin fecha ni enlace propio no es utilizable por la app: no se
    # puede ordenar ni avisar cuándo es. Se lo deja pasar solo si trae un evento
    # de Facebook, que la app sí puede abrir para que el usuario vea la fecha.
    utilizable = fecha.tiene_fecha or bool(item.facebook_event_url)
    aceptado = score >= UMBRAL_RELEVANCIA and utilizable

    if aceptado:
        motivo = "aceptado"
    elif not utilizable:
        motivo = "sin_fecha_ni_enlace_de_evento"
    elif pasado and score < UMBRAL_RELEVANCIA:
        motivo = "parece_cronica_de_algo_que_ya_paso"
    elif descartes:
        motivo = "tema_ajeno_a_eventos"
    elif categoria == "otro":
        motivo = "sin_senal_de_evento_en_el_texto"
    else:
        motivo = "relevancia_insuficiente"

    return {
        "accepted": aceptado,
        "score": score,
        "reasons": razones,
        "reason": motivo,
        "texto": texto,
        "fecha": fecha,
        "lifecycle": ciclo,
        "category": categoria,
        "subcategories": subcategorias,
        "ubicacion": ubicacion,
        "precios": precios,
        "enlaces": enlaces,
    }


def motivo_de_rechazo(item: RawItem, ahora=None) -> str:
    return analizar(item, ahora=ahora)["reason"]


def confianza_de(item: RawItem, analisis: Dict[str, Any]) -> float:
    """Qué tan seguro estamos de que este evento es real y está bien leído."""
    base = 0.42
    if item.tier == 1:
        base += 0.20
    elif item.tier == 2:
        base += 0.12

    fecha = analisis["fecha"]
    if fecha.confianza == "exacta":
        base += 0.14
    elif fecha.confianza == "aproximada":
        base += 0.07
    elif fecha.confianza == "relativa":
        base += 0.03

    if analisis["ubicacion"]["venue"]:
        base += 0.07
    if analisis["enlaces"]["ticket_urls"] or item.facebook_event_url:
        base += 0.07
    if analisis["score"] >= 80:
        base += 0.06
    return round(min(base, 0.98), 2)


def construir_evento(item: RawItem, scraped_at: str, ahora=None) -> Optional[Evento]:
    """La publicación convertida en evento, o `None` si no pasó el filtro."""
    analisis = analizar(item, ahora=ahora)
    if not analisis["accepted"]:
        return None

    texto = analisis["texto"]
    fecha = analisis["fecha"]
    ubicacion = analisis["ubicacion"]
    precios = analisis["precios"]
    enlaces = analisis["enlaces"]

    legible = fecha_legible(fecha)
    uid = hashlib.sha1(
        f"{item.source_id}|{item.item_url}|{texto[:400]}".encode("utf-8")
    ).hexdigest()[:16]

    return Evento(
        id=uid,
        source_id=item.source_id,
        source_name=item.source_name,
        source_url=item.source_url,
        source_class=item.source_class,
        source_tier=int(item.tier),
        source_icon_url=item.source_icon_url,
        url=item.item_url or item.source_url,
        facebook_event_url=item.facebook_event_url,
        published_at=item.published_at,
        scraped_at=scraped_at,

        title=titulo_de(item, texto, analisis["category"], legible),
        description=texto[:2500],
        original_text=texto[:8000],
        category=analisis["category"],
        subcategories=analisis["subcategories"],
        tags=extraer_etiquetas(texto),
        artists=extraer_artistas(texto),

        starts_at=fecha.inicio.isoformat(timespec="seconds") if fecha.inicio else None,
        ends_at=fecha.fin.isoformat(timespec="seconds") if fecha.fin else None,
        starts_at_ms=a_millis(fecha.inicio),
        ends_at_ms=a_millis(fecha.fin),
        date_confidence=fecha.confianza,
        date_source_text=fecha.texto_origen,
        all_day=fecha.todo_el_dia,
        multi_day=fecha.multidia,
        doors_time=fecha.hora_puertas,
        display_date=legible,
        days_until=dias_restantes(fecha, ahora=ahora),
        lifecycle=analisis["lifecycle"],

        department=ubicacion["department"],
        city=ubicacion["city"],
        venue=ubicacion["venue"],
        address=ubicacion["address"],
        latitude=None,
        longitude=None,
        location_query=consulta_de_mapa(
            ubicacion["venue"], ubicacion["address"],
            ubicacion["city"], ubicacion["department"],
        ),

        is_free=precios["is_free"],
        price_from=precios["price_from"],
        price_to=precios["price_to"],
        currency=precios["currency"],
        price_text=precios["price_text"],
        ticket_urls=enlaces["ticket_urls"],
        ticket_outlets=extraer_puntos_venta(texto),

        phones=extraer_telefonos(texto),

        status=detectar_estado(texto),
        relevance_score=analisis["score"],
        confidence=confianza_de(item, analisis),
        filter_reasons=analisis["reasons"],
        is_official=int(item.tier) == 1,

        image_urls=item.image_urls or [],
        video_url=item.video_url,
        video_thumbnail_url=item.video_thumbnail_url,
        video_type=item.video_type,
    )
