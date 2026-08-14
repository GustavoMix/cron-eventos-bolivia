"""Dónde pasa el evento: departamento, ciudad y sede.

Bolivia tiene nueve departamentos y la app los usa como filtro principal, así
que están todos, no solo el eje troncal. Un evento sin departamento es un
evento que nadie encuentra.

La detección va en tres niveles, del más específico al más general:

1. Sede conocida. "Teatro Achá" identifica ciudad y departamento sin que el
   afiche los nombre — y casi nunca los nombra, porque quien publica da por
   sentado que su público sabe en qué ciudad está.
2. Ciudad o localidad mencionada en el texto.
3. La pista que trae la fuente. Una página municipal de Cochabamba habla de
   Cochabamba salvo que el texto diga otra cosa.
"""

import re
import unicodedata
from typing import Dict, List, Optional, Tuple

DEPARTAMENTOS = [
    "La Paz", "Cochabamba", "Santa Cruz", "Oruro", "Potosí",
    "Chuquisaca", "Tarija", "Beni", "Pando",
]

# Localidades que identifican departamento sin ambigüedad. Se excluyen a
# propósito los nombres que se repiten entre departamentos.
DEPTO_ALIAS: Dict[str, List[str]] = {
    "La Paz": [
        "la paz", "el alto", "chuquiago", "sopocachi", "miraflores", "calacoto",
        "san miguel", "obrajes", "zona sur", "achumani", "irpavi", "villa fatima",
        "el prado", "san pedro", "cota cota", "mallasa", "viacha", "achocalla",
        "copacabana", "coroico", "chulumani", "caranavi", "yungas", "tiwanaku",
        "sorata", "patacamaya", "desaguadero", "guaqui", "batallas",
    ],
    "Cochabamba": [
        "cochabamba", "llajta", "cercado", "sacaba", "quillacollo", "tiquipaya",
        "colcapirhua", "vinto", "sipe sipe", "villa tunari", "chapare", "punata",
        "cliza", "mizque", "tarata", "aiquile", "totora", "tiraque", "colomi",
        "el prado cochabamba", "recoleta", "queru queru", "tupuraya", "sarco",
        "muyurina", "america", "hipodromo",
    ],
    "Santa Cruz": [
        "santa cruz", "santa cruz de la sierra", "equipetrol", "urubo",
        "plan 3000", "villa 1ro de mayo", "pampa de la isla", "el torno",
        "la guardia", "cotoca", "warnes", "montero", "porongo", "buena vista",
        "samaipata", "vallegrande", "camiri", "san ignacio de velasco",
        "san jose de chiquitos", "concepcion", "roboré", "robore", "yapacani",
        "portachuelo", "mineros", "san julian", "guarayos", "ascension",
    ],
    "Oruro": [
        "oruro", "huanuni", "challapata", "caracollo", "poopo", "sabaya",
        "curahuara", "totora oruro", "av. civica", "avenida civica",
    ],
    "Potosí": [
        "potosi", "villa imperial", "uyuni", "llallagua", "tupiza", "villazon",
        "cerro rico", "colquechaca", "betanzos", "cotagaita", "atocha",
    ],
    "Chuquisaca": [
        "sucre", "chuquisaca", "ciudad blanca", "monteagudo", "camargo",
        "villa serrano", "padilla", "zudanez", "yotala", "tarabuco",
    ],
    "Tarija": [
        "tarija", "yacuiba", "bermejo", "villamontes", "villa montes",
        "entre rios tarija", "san lorenzo tarija", "el valle de la concepcion",
        "uriondo", "padcaya",
    ],
    "Beni": [
        "beni", "trinidad", "riberalta", "guayaramerin", "rurrenabaque",
        "san borja", "santa ana del yacuma", "san ignacio de moxos", "reyes",
    ],
    "Pando": [
        "pando", "cobija", "porvenir", "puerto rico", "filadelfia", "bella flor",
    ],
}

CIUDAD_ALIAS: Dict[str, Tuple[List[str], str]] = {
    "La Paz": (["ciudad de la paz", "la paz", "chuquiago"], "La Paz"),
    "El Alto": (["el alto", "ciudad de el alto"], "La Paz"),
    "Cochabamba": (["ciudad de cochabamba", "cochabamba", "llajta"], "Cochabamba"),
    "Sacaba": (["sacaba"], "Cochabamba"),
    "Quillacollo": (["quillacollo"], "Cochabamba"),
    "Tiquipaya": (["tiquipaya"], "Cochabamba"),
    "Santa Cruz de la Sierra": (
        ["santa cruz de la sierra", "ciudad de santa cruz", "santa cruz"], "Santa Cruz",
    ),
    "Montero": (["montero"], "Santa Cruz"),
    "Warnes": (["warnes"], "Santa Cruz"),
    "La Guardia": (["la guardia"], "Santa Cruz"),
    "Cotoca": (["cotoca"], "Santa Cruz"),
    "Oruro": (["ciudad de oruro", "oruro"], "Oruro"),
    "Potosí": (["ciudad de potosi", "potosi", "villa imperial"], "Potosí"),
    "Uyuni": (["uyuni"], "Potosí"),
    "Sucre": (["ciudad de sucre", "sucre", "ciudad blanca"], "Chuquisaca"),
    "Tarija": (["ciudad de tarija", "tarija"], "Tarija"),
    "Yacuiba": (["yacuiba"], "Tarija"),
    "Trinidad": (["ciudad de trinidad", "trinidad"], "Beni"),
    "Riberalta": (["riberalta"], "Beni"),
    "Cobija": (["cobija"], "Pando"),
}

# Sedes reconocidas. Identificar la sede resuelve ciudad y departamento de una
# sola vez, que es justo lo que el afiche no dice.
# nombre canónico -> (alias en minúsculas y sin tildes, ciudad, departamento)
SEDES: Dict[str, Tuple[List[str], str, str]] = {
    # La Paz
    "Teatro Municipal Alberto Saavedra Pérez": (
        ["teatro municipal alberto saavedra", "teatro municipal de la paz"], "La Paz", "La Paz"),
    "Teatro al Aire Libre Jaime Laredo": (
        ["teatro al aire libre", "jaime laredo", "aire libre jaime laredo"], "La Paz", "La Paz"),
    "Cine Teatro Municipal 6 de Agosto": (
        ["cine teatro municipal 6 de agosto", "teatro 6 de agosto"], "La Paz", "La Paz"),
    "Teatro Modesta Sanjinés": (["modesta sanjines"], "La Paz", "La Paz"),
    "Teatro Nuna": (["teatro nuna"], "La Paz", "La Paz"),
    "Coliseo Julio Borelli Viterito": (
        ["julio borelli", "coliseo cerrado julio borelli", "coliseo borelli"], "La Paz", "La Paz"),
    "Estadio Hernando Siles": (["hernando siles"], "La Paz", "La Paz"),
    "Casa de la Cultura Franz Tamayo": (
        ["casa de la cultura franz tamayo", "casa de la cultura de la paz"], "La Paz", "La Paz"),
    "Espacio Simón I. Patiño La Paz": (
        ["espacio simon i. patino", "espacio simon patino"], "La Paz", "La Paz"),
    "Centro Cultural de España en La Paz": (
        ["centro cultural de espana en la paz", "ccelp"], "La Paz", "La Paz"),
    "Museo Nacional de Arte": (["museo nacional de arte"], "La Paz", "La Paz"),
    "Parque Urbano Central": (
        ["parque urbano central", "puc la paz"], "La Paz", "La Paz"),
    "Multicine La Paz": (["multicine"], "La Paz", "La Paz"),
    "Megacenter La Paz": (["megacenter"], "La Paz", "La Paz"),
    "Coliseo Cerrado de El Alto": (
        ["coliseo cerrado de el alto", "coliseo de el alto"], "El Alto", "La Paz"),

    # Cochabamba
    "Teatro Achá": (
        ["teatro acha", "teatro jose maria acha", "teatro jose maria de acha"],
        "Cochabamba", "Cochabamba"),
    "Estadio Félix Capriles": (["felix capriles"], "Cochabamba", "Cochabamba"),
    "Coliseo Evo Morales": (
        ["coliseo evo morales", "coliseo cerrado de cochabamba"], "Cochabamba", "Cochabamba"),
    "Centro Pedagógico y Cultural Simón I. Patiño": (
        ["centro pedagogico y cultural simon i. patino", "palacio portales",
         "centro simon patino"], "Cochabamba", "Cochabamba"),
    "mARTadero": (["martadero", "el martadero"], "Cochabamba", "Cochabamba"),
    "Casa de la Cultura Cochabamba": (
        ["casa de la cultura de cochabamba"], "Cochabamba", "Cochabamba"),
    "Cine Center Cochabamba": (["cine center"], "Cochabamba", "Cochabamba"),

    # Santa Cruz
    "Fexpocruz": (
        ["fexpocruz", "campo ferial fexpocruz", "expocruz", "recinto ferial fexpocruz"],
        "Santa Cruz de la Sierra", "Santa Cruz"),
    "Estadio Ramón Tahuichi Aguilera": (
        ["tahuichi aguilera", "estadio tahuichi"], "Santa Cruz de la Sierra", "Santa Cruz"),
    "Coliseo Don Bosco": (["don bosco"], "Santa Cruz de la Sierra", "Santa Cruz"),
    "Casa de la Cultura Raúl Otero Reiche": (
        ["casa de la cultura raul otero reiche", "casa de la cultura de santa cruz"],
        "Santa Cruz de la Sierra", "Santa Cruz"),
    "Manzana Uno Espacio de Arte": (
        ["manzana uno", "manzana 1"], "Santa Cruz de la Sierra", "Santa Cruz"),
    "Centro de Convenciones Sirionó": (
        ["siriono", "centro de convenciones siriono"], "Santa Cruz de la Sierra", "Santa Cruz"),
    "Ventura Mall": (["ventura mall"], "Santa Cruz de la Sierra", "Santa Cruz"),
    "Cine Center Santa Cruz": (
        ["cine center santa cruz"], "Santa Cruz de la Sierra", "Santa Cruz"),

    # Resto del país
    "Teatro Gran Mariscal Sucre": (
        ["gran mariscal sucre", "teatro gran mariscal"], "Sucre", "Chuquisaca"),
    "Casa de la Libertad": (["casa de la libertad"], "Sucre", "Chuquisaca"),
    "Estadio Patria": (["estadio patria"], "Sucre", "Chuquisaca"),
    "Casa Dorada": (["casa dorada"], "Tarija", "Tarija"),
    "Estadio IV Centenario": (["iv centenario", "cuarto centenario"], "Tarija", "Tarija"),
    "Avenida Cívica Oruro": (
        ["avenida civica", "av. civica"], "Oruro", "Oruro"),
    "Teatro Palais Concert": (["palais concert"], "Oruro", "Oruro"),
    "Casa Nacional de Moneda": (
        ["casa nacional de moneda", "casa de la moneda"], "Potosí", "Potosí"),
}

# Patrones para sedes que no están en el catálogo. Se quedan cortos a propósito:
# capturar "Teatro" y ochenta caracteres de relleno es peor que no capturar nada,
# porque la app muestra ese texto tal cual como nombre del lugar.
SEDE_GENERICA_RE = re.compile(
    r"\b(?P<tipo>teatro|coliseo|estadio|auditorio|auditorium|sal[oó]n|salon de eventos|"
    r"casa de la cultura|centro cultural|centro de convenciones|campo ferial|"
    r"predio ferial|anfiteatro|paraninfo|plaza|parque|club|caf[eé] cultural|"
    r"pe[ñn]a|discoteca|complejo|polideportivo|cancha|galer[ií]a|museo)"
    r"\s+(?P<nombre>(?:[A-ZÁÉÍÓÚÑ0-9][\wÁÉÍÓÚÑáéíóúñ'’.-]*)(?:\s+(?:de|del|la|el|los|las|y)\s+|\s+)"
    r"?(?:[A-ZÁÉÍÓÚÑ0-9][\wÁÉÍÓÚÑáéíóúñ'’.-]*)?(?:\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ'’.-]*)?)",
)

DIRECCION_RE = re.compile(
    r"\b(?:av\.?|avenida|calle|c\.|esq\.?|esquina|zona|barrio|km\.?|kil[oó]metro|"
    r"anillo|radial|pasaje)\s+[^\n,;|]{3,70}",
    re.IGNORECASE,
)


def _plano(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", texto).strip()


def _contiene(plano: str, alias: str) -> bool:
    """Coincidencia por palabra completa: sin esto, 'oruro' aparece dentro de
    otras palabras y 'la paz' dentro de 'la paza'."""
    return re.search(rf"(?<![\w]){re.escape(alias)}(?![\w])", plano) is not None


def detectar_sede(texto: str) -> Optional[Tuple[str, Optional[str], Optional[str]]]:
    """(nombre de la sede, ciudad, departamento). Ciudad y departamento son
    `None` cuando la sede se dedujo por patrón y no está en el catálogo."""
    plano = _plano(texto)

    # El catálogo primero, y dentro del catálogo los alias más largos: "teatro
    # municipal alberto saavedra" debe ganarle a "teatro municipal".
    mejor: Optional[Tuple[int, str, str, str]] = None
    for canonico, (alias_lista, ciudad, depto) in SEDES.items():
        for alias in alias_lista:
            if _contiene(plano, alias) and (mejor is None or len(alias) > mejor[0]):
                mejor = (len(alias), canonico, ciudad, depto)
    if mejor:
        return mejor[1], mejor[2], mejor[3]

    m = SEDE_GENERICA_RE.search(texto or "")
    if m:
        nombre = re.sub(r"\s+", " ", m.group(0)).strip(" .,;:-")
        if 6 <= len(nombre) <= 70:
            return nombre, None, None
    return None


def detectar_departamento(texto: str, pista: Optional[str] = None) -> Optional[str]:
    plano = _plano(texto)
    for depto, alias_lista in DEPTO_ALIAS.items():
        if any(_contiene(plano, a) for a in alias_lista):
            return depto
    if pista:
        pista_plana = _plano(pista)
        for depto in DEPARTAMENTOS:
            if _plano(depto) == pista_plana:
                return depto
        for depto, alias_lista in DEPTO_ALIAS.items():
            if any(_contiene(pista_plana, a) for a in alias_lista):
                return depto
    return None


def detectar_ciudad(texto: str, pista: Optional[str] = None) -> Optional[str]:
    plano = _plano(texto)
    # Los alias más largos primero: "santa cruz de la sierra" antes que
    # "santa cruz", y "el alto" antes que cualquier mención suelta de La Paz.
    candidatas = sorted(
        ((ciudad, alias) for ciudad, (alias_lista, _) in CIUDAD_ALIAS.items() for alias in alias_lista),
        key=lambda x: len(x[1]), reverse=True,
    )
    for ciudad, alias in candidatas:
        if _contiene(plano, alias):
            return ciudad
    if pista:
        pista_plana = _plano(pista)
        for ciudad, (alias_lista, _) in CIUDAD_ALIAS.items():
            if any(_contiene(pista_plana, a) for a in alias_lista):
                return ciudad
    return None


def departamento_de_ciudad(ciudad: Optional[str]) -> Optional[str]:
    if not ciudad:
        return None
    entrada = CIUDAD_ALIAS.get(ciudad)
    return entrada[1] if entrada else None


def detectar_direccion(texto: str) -> Optional[str]:
    m = DIRECCION_RE.search(texto or "")
    if not m:
        return None
    direccion = re.sub(r"\s+", " ", m.group(0)).strip(" .,;:-")
    return direccion if 6 <= len(direccion) <= 90 else None


def resolver_ubicacion(
    texto: str,
    pista_region: Optional[str] = None,
    pista_ciudad: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    """Junta los tres niveles de detección en un solo resultado coherente.

    La sede manda sobre el texto y el texto manda sobre la pista de la fuente:
    un post de una página nacional que menciona el Teatro Achá es un evento en
    Cochabamba, aunque la fuente esté registrada como "Bolivia".
    """
    sede = detectar_sede(texto)
    nombre_sede = sede[0] if sede else None
    ciudad_sede = sede[1] if sede else None
    depto_sede = sede[2] if sede else None

    ciudad = ciudad_sede or detectar_ciudad(texto, pista_ciudad)
    departamento = (
        depto_sede
        or departamento_de_ciudad(ciudad)
        or detectar_departamento(texto, pista_region)
    )

    return {
        "venue": nombre_sede,
        "city": ciudad,
        "department": departamento,
        "address": detectar_direccion(texto),
    }


def consulta_de_mapa(
    venue: Optional[str], direccion: Optional[str],
    ciudad: Optional[str], departamento: Optional[str],
) -> Optional[str]:
    """Texto para pasarle a Google Maps o al intent de mapas de Android.

    La app no tiene coordenadas —los afiches nunca las traen— así que se arma la
    mejor consulta posible y se deja que el mapa resuelva.
    """
    partes = [p for p in (venue, direccion, ciudad, departamento) if p]
    if not partes:
        return None
    vistos, unicas = set(), []
    for parte in partes:
        clave = _plano(parte)
        if clave and clave not in vistos:
            vistos.add(clave)
            unicas.append(parte)
    return ", ".join(unicas[:3] + ["Bolivia"])
