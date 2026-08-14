"""Reparto de las fuentes de Facebook entre los jobs de CI.

Este módulo es la estrategia anti-bloqueo escrita en código. El dato duro que la
motiva, medido en corridas reales: **Facebook deja pasar alrededor de dos
páginas por IP**. No es un límite que se pueda negociar con pausas más largas ni
con otro navegador — lo lleva la IP.

De ahí salen las cuatro decisiones de este archivo:

1. **Más IPs, grupos más chicos.** Cada job de GitHub Actions corre en un runner
   distinto y por lo tanto sale por una IP distinta. La palanca real no es
   hacer más trucos dentro de un job, es tener más jobs. Con grupos de dos, casi
   ninguna fuente se pierde en cascada detrás de otra; con grupos de cinco se
   perdían cuatro por cada bloqueo.

2. **Turnos solos para las que más valen.** Las primeras fuentes de la lista de
   prioridad no comparten job con nadie: se llevan una IP entera para ellas.
   El primer turno de una IP es el que casi siempre pasa, y la segunda lectura
   es una apuesta. Las fuentes que de verdad publican eventos no deberían estar
   apostando.

3. **Olas, no barridos.** Si hay más fuentes que capacidad de jobs, esta corrida
   se lleva las más prioritarias y el resto espera a la siguiente. Esto acá se
   puede hacer y en un proyecto de tránsito no: un bloqueo de carretera caduca
   en minutos, pero un concierto se anuncia con días o semanas de anticipación.
   Ver una fuente cada tres horas en vez de cada hora no pierde un solo evento,
   y permite tener un catálogo de fuentes mucho más grande del que entra en una
   sola corrida.

4. **Memoria entre corridas.** Se guarda cómo le fue a cada fuente. La que lleva
   más tiempo sin traer datos sube al primer turno, y el bloqueo no se le cuenta
   como culpa suya —porque no lo es— así que sigue envejeciendo y sube sola.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

# Una fuente que nunca trajo nada tiene que ganarle a cualquiera que sí, por
# vieja que sea. Solo necesita ser mayor a cualquier antigüedad real en horas.
HORAS_NUNCA_VISTA = 100_000.0

# Cuánto pesa la calidad de la fuente frente a su antigüedad. Una ticketera o
# una página dedicada a eventos publica agenda todos los días; un medio general
# publica un evento entre veinte noticias.
PESO_CLASE = {
    "ticketera": 2.0,
    "eventos": 1.8,
    "venue": 1.5,
    "cultura_oficial": 1.3,
    "municipio": 1.1,
    "media": 1.0,
}

PESO_TIER = {1: 1.5, 2: 1.2, 3: 1.0}


def cargar_rotacion(path: Path) -> Dict[str, Any]:
    """Estado de rotación guardado. Si no existe o está corrupto se arranca
    vacío: la primera corrida simplemente prioriza por tier y clase."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    fuentes = data.get("fuentes")
    return fuentes if isinstance(fuentes, dict) else {}


def _horas_desde(iso: Optional[str], ahora: datetime) -> float:
    if not iso:
        return HORAS_NUNCA_VISTA
    try:
        visto = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return HORAS_NUNCA_VISTA
    if visto.tzinfo is None:
        visto = visto.replace(tzinfo=ahora.tzinfo)
    return max(0.0, (ahora - visto).total_seconds() / 3600.0)


def puntaje(source: Dict[str, Any], rotacion: Dict[str, Any], ahora: datetime) -> float:
    """Cuánto merece esta fuente un turno bueno. Más alto, más temprano."""
    estado = rotacion.get(source["id"], {})
    horas = _horas_desde(estado.get("ultimo_exito"), ahora)

    valor = horas
    valor *= PESO_CLASE.get(source.get("source_class", "media"), 1.0)
    valor *= PESO_TIER.get(int(source.get("tier", 3)), 1.0)

    # Una fuente que falla por algo que no es un bloqueo —página renombrada,
    # borrada o vuelta privada— no debería acaparar los turnos buenos corrida
    # tras corrida. Se la sigue intentando, pero más atrás en la fila.
    fallos = int(estado.get("fallos_seguidos", 0))
    if fallos >= 5:
        valor *= 0.15
    elif fallos >= 3:
        valor *= 0.35
    elif fallos == 2:
        valor *= 0.7

    return valor


def planificar_grupos(
    sources: List[Dict[str, Any]],
    rotacion: Dict[str, Any],
    tamano_grupo: int = 2,
    max_grupos: int = 20,
    grupos_solos: int = 6,
    ahora: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Reparte las fuentes en grupos, uno por job de CI.

    Devuelve los grupos y también qué quedó afuera, porque saber qué fuentes se
    postergaron es justamente lo que permite comprobar que la rotación avanza y
    no está dejando siempre a las mismas atrás.
    """
    if ahora is None:
        ahora = datetime.now(ZoneInfo("America/La_Paz"))

    tamano_grupo = max(1, int(tamano_grupo))
    max_grupos = max(1, int(max_grupos))
    grupos_solos = max(0, min(int(grupos_solos), max_grupos))

    ordenadas = sorted(sources, key=lambda s: (-puntaje(s, rotacion, ahora), s["id"]))

    solos = ordenadas[:grupos_solos]
    resto = ordenadas[grupos_solos:]

    grupos_para_el_resto = max_grupos - len(solos)
    capacidad = grupos_para_el_resto * tamano_grupo
    en_esta_ola = resto[:capacidad]
    postergadas = resto[capacidad:]

    cubos: List[List[str]] = [[s["id"]] for s in solos]

    if en_esta_ola and grupos_para_el_resto > 0:
        n = min(grupos_para_el_resto, -(-len(en_esta_ola) // tamano_grupo))
        compartidos: List[List[str]] = [[] for _ in range(n)]
        # Round-robin y no bloques: repartiendo de a uno, las fuentes más
        # prioritarias caen cada una en el *primer* turno de un grupo distinto,
        # que es el turno que casi siempre pasa. En bloques, la primera y la
        # segunda prioridad competirían dentro del mismo job.
        for i, source in enumerate(en_esta_ola):
            compartidos[i % n].append(source["id"])
        cubos.extend(compartidos)

    grupos = [
        {"nombre": f"g{i + 1:02d}", "orden": i, "fuentes": ",".join(ids)}
        for i, ids in enumerate(cubos) if ids
    ]

    return {
        "grupos": grupos,
        "postergadas": [s["id"] for s in postergadas],
        "total_fuentes": len(sources),
        "fuentes_en_esta_ola": sum(len(g["fuentes"].split(",")) for g in grupos),
    }


def matriz_github(grupos: List[Dict[str, Any]]) -> str:
    """Los grupos serializados como matrix de GitHub Actions, en una sola línea
    y listos para pasar por fromJSON() desde el output de un job."""
    return json.dumps({"include": grupos}, ensure_ascii=False, separators=(",", ":"))


def actualizar_rotacion(
    path: Path,
    resultados: Dict[str, Any],
    scraped_at: str,
    conservar_dias: int = 45,
) -> Dict[str, Any]:
    """Anota cómo le fue a cada fuente para que la próxima corrida sepa a quién
    le toca un turno bueno.

    `resultados` es {source_id: {"items": [...], "error": str|None}}.
    """
    rotacion = cargar_rotacion(path)

    try:
        ahora = datetime.fromisoformat(scraped_at)
    except (ValueError, TypeError):
        ahora = datetime.now(ZoneInfo("America/La_Paz"))

    for source_id, resultado in resultados.items():
        estado = dict(rotacion.get(source_id, {}))
        error = resultado.get("error")
        items = resultado.get("items") or []

        estado["ultimo_intento"] = scraped_at

        if error:
            texto = str(error).lower()
            if texto.startswith("omitida"):
                # No llegó a intentarse: ni éxito ni fallo propio. Sigue
                # envejeciendo y por eso sube sola en la corrida siguiente.
                estado["ultimo_estado"] = "omitida"
                rotacion[source_id] = estado
                continue
            if "bloque" in texto or "ocult" in texto or "blocked" in texto:
                # El bloqueo es de la IP, no de la fuente: no se la penaliza.
                estado["ultimo_estado"] = "bloqueada"
                estado["bloqueos"] = int(estado.get("bloqueos", 0)) + 1
                estado["ultimo_bloqueo"] = scraped_at
            else:
                estado["ultimo_estado"] = "error"
                estado["fallos_seguidos"] = int(estado.get("fallos_seguidos", 0)) + 1
                estado["ultimo_error"] = " ".join(str(error).split())[:200]
        elif items:
            estado["ultimo_estado"] = "ok"
            estado["ultimo_exito"] = scraped_at
            estado["fallos_seguidos"] = 0
            estado["exitos"] = int(estado.get("exitos", 0)) + 1
            estado.pop("ultimo_error", None)
        else:
            # Cargó bien pero no había nada nuevo. Cuenta como turno gastado:
            # se refresca la antigüedad y baja la prioridad.
            estado["ultimo_estado"] = "sin_publicaciones"
            estado["ultimo_exito"] = scraped_at
            estado["fallos_seguidos"] = 0

        rotacion[source_id] = estado

    # Olvidar fuentes que ya no están en la configuración.
    limite_horas = max(1, conservar_dias) * 24
    vigentes = {
        sid: est for sid, est in rotacion.items()
        if _horas_desde(est.get("ultimo_intento"), ahora) <= limite_horas
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"actualizado": scraped_at, "fuentes": vigentes},
            ensure_ascii=False, indent=2, sort_keys=True,
        ),
        encoding="utf-8",
    )
    return vigentes


def resumen_cobertura(rotacion: Dict[str, Any], sources: List[Dict[str, Any]],
                      ahora: Optional[datetime] = None) -> Dict[str, Any]:
    """Cuánto del catálogo se está alcanzando de verdad.

    Es la métrica que dice si la estrategia está funcionando. Si crece
    `nunca_vistas` o sube el promedio de horas sin datos, hacen falta más
    grupos —o sea más IPs—, no más trucos dentro de cada job.
    """
    if ahora is None:
        ahora = datetime.now(ZoneInfo("America/La_Paz"))

    horas = []
    nunca, bloqueadas, con_error = [], [], []
    for source in sources:
        estado = rotacion.get(source["id"], {})
        ultimo = estado.get("ultimo_exito")
        if not ultimo:
            nunca.append(source["id"])
        else:
            horas.append(_horas_desde(ultimo, ahora))
        if estado.get("ultimo_estado") == "bloqueada":
            bloqueadas.append(source["id"])
        if int(estado.get("fallos_seguidos", 0)) >= 3:
            con_error.append(source["id"])

    return {
        "fuentes_totales": len(sources),
        "con_datos_alguna_vez": len(horas),
        "nunca_vistas": sorted(nunca),
        "bloqueadas_en_la_ultima_corrida": sorted(bloqueadas),
        "con_fallos_persistentes": sorted(con_error),
        "horas_promedio_sin_datos": round(sum(horas) / len(horas), 1) if horas else None,
        "horas_maximo_sin_datos": round(max(horas), 1) if horas else None,
    }
