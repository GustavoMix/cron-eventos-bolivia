"""Orquestación y línea de comandos.

El runner tiene tres modos, y los tres existen por el mismo motivo: repartir
Facebook entre muchas IPs.

1. `--planificar-facebook` decide qué fuente va en qué grupo y escribe la matrix
   de GitHub Actions. Corre en un job propio y chico.
2. `--facebook-scrape-group-out` lee un grupo y guarda el resultado crudo. Corre
   en N jobs paralelos, cada uno con su IP.
3. Sin banderas (o con `--facebook-raw-in`) hace el resto: lee las fuentes web,
   junta los crudos de Facebook, clasifica, fusiona, reconcilia con el historial
   y escribe los JSON.

Correrlo sin banderas en una sola máquina también funciona y es lo que conviene
para probar en local, pero desde una sola IP Facebook cortará después de las
primeras páginas. Eso no es un bug: es el motivo de que exista el modo repartido.
"""

import argparse
import asyncio
import csv
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import yaml

from .clasificador import analizar, construir_evento
from .estado import guardar_archivo, reconciliar
from .facebook import leer_fuentes_facebook
from .merger import fusionar
from .models import RawItem
from .planificador import (
    actualizar_rotacion,
    cargar_rotacion,
    matriz_github,
    planificar_grupos,
    resumen_cobertura,
)
from .salida import construir_payload, construir_payload_lite, escribir_json
from .web_sources import leer_fuente_web

RAIZ = Path(__file__).resolve().parents[1]


def cargar_config(path: Path) -> Dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def ahora_iso(zona: str) -> str:
    return datetime.now(ZoneInfo(zona)).isoformat(timespec="seconds")


def _compacto(texto: str) -> str:
    return " ".join((texto or "").split())


def _fuentes_facebook(sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [s for s in sources if s.get("type") == "facebook_public"]


def _fuentes_web(sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [s for s in sources if s.get("type") == "generic_web"]


# --------------------------------------------------------------------------
# Modo 1: planificar
# --------------------------------------------------------------------------

def planificar(config_path: Path, rotacion_path: Path, tamano_grupo: int,
               max_grupos: int, grupos_solos: int) -> str:
    cfg = cargar_config(config_path)
    settings, sources = cfg["settings"], cfg["sources"]
    fb = _fuentes_facebook(sources)
    if not fb:
        raise SystemExit("No hay fuentes de Facebook en la configuración")

    zona = settings.get("timezone", "America/La_Paz")
    ahora = datetime.now(ZoneInfo(zona))
    rotacion = cargar_rotacion(rotacion_path)
    plan = planificar_grupos(fb, rotacion, tamano_grupo, max_grupos, grupos_solos, ahora)

    # Todo el diagnóstico va a stderr: stdout lleva solo la línea "matriz=..."
    # que GitHub Actions redirige a $GITHUB_OUTPUT.
    print(
        f"{len(fb)} fuentes de Facebook -> {len(plan['grupos'])} grupos "
        f"({plan['fuentes_en_esta_ola']} en esta ola, "
        f"{len(plan['postergadas'])} postergadas para la siguiente).",
        file=sys.stderr,
    )
    for grupo in plan["grupos"]:
        marca = "SOLA" if "," not in grupo["fuentes"] else "    "
        print(f"  {grupo['nombre']} [{marca}] {grupo['fuentes']}", file=sys.stderr)
    if plan["postergadas"]:
        print(f"  postergadas: {', '.join(plan['postergadas'])}", file=sys.stderr)

    return matriz_github(plan["grupos"])


# --------------------------------------------------------------------------
# Modo 2: leer un grupo de Facebook
# --------------------------------------------------------------------------

async def leer_grupo(config_path: Path, ids: set, salida: Path) -> int:
    cfg = cargar_config(config_path)
    settings, sources = cfg["settings"], cfg["sources"]
    fb = [s for s in _fuentes_facebook(sources) if s["id"] in ids]
    if not fb:
        raise SystemExit(f"Ninguna fuente de Facebook coincide con el grupo: {sorted(ids)}")

    print(f"Leyendo grupo de {len(fb)} fuente(s): {[s['id'] for s in fb]}")
    resultados = await leer_fuentes_facebook(fb, settings)

    serializable = {
        sid: {
            "items": [asdict(i) for i in r.get("items", [])],
            "error": r.get("error"),
        }
        for sid, r in resultados.items()
    }
    escribir_json(salida, {
        "scraped_at": ahora_iso(settings.get("timezone", "America/La_Paz")),
        "results": serializable,
    })

    ok = sum(1 for r in resultados.values() if not r.get("error"))
    posts = sum(len(r.get("items", [])) for r in resultados.values())
    for sid, r in resultados.items():
        estado = "OK" if not r.get("error") else "FALLO"
        print(f"  [{estado}] {sid}: {len(r.get('items', []))} publicaciones"
              + (f" — {_compacto(str(r['error']))[:120]}" if r.get("error") else ""))
    print(f"Grupo terminado: {ok}/{len(fb)} fuentes, {posts} publicaciones. -> {salida}")
    return 0


def _cargar_crudos(rutas: List[Path]) -> Dict[str, Any]:
    """Junta los resultados de varios grupos en un solo diccionario."""
    combinado: Dict[str, Any] = {}
    for ruta in rutas:
        try:
            data = json.loads(ruta.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  aviso: no se pudo leer {ruta}: {exc}", file=sys.stderr)
            continue
        for sid, entrada in data.get("results", {}).items():
            combinado[sid] = {
                "items": [RawItem(**d) for d in entrada.get("items", [])],
                "error": entrada.get("error"),
            }
    return combinado


# --------------------------------------------------------------------------
# Modo 3: corrida completa
# --------------------------------------------------------------------------

async def _leer_webs(sources: List[Dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
    """Las fuentes web sí van en paralelo: son sitios distintos y no bloquean."""
    limite = asyncio.Semaphore(max(1, int(settings.get("web_concurrencia", 5))))
    resultados: Dict[str, Any] = {}

    async def trabajador(source):
        async with limite:
            try:
                items = await asyncio.to_thread(leer_fuente_web, source, settings)
                resultados[source["id"]] = {"items": items, "error": None}
            except Exception as exc:
                resultados[source["id"]] = {"items": [], "error": str(exc)}

    await asyncio.gather(*(trabajador(s) for s in sources))
    return resultados


def _estado_de_fuente(error: Optional[str]) -> str:
    if not error:
        return "ok"
    bajo = str(error).lower()
    if bajo.startswith("omitida"):
        return "skipped"
    if "bloque" in bajo or "ocult" in bajo or "blocked" in bajo:
        return "blocked"
    return "error"


def _muestra_rechazada(item: RawItem, ahora) -> Dict[str, Any]:
    analisis = analizar(item, ahora=ahora)
    return {
        "reason": analisis.get("reason"),
        "score": analisis.get("score", 0),
        "category": analisis.get("category"),
        "url": item.item_url,
        "has_image": bool(item.image_urls),
        "text_preview": _compacto(item.text)[:400],
    }


async def correr(
    config_path: Path,
    out_dir: Path,
    only: Optional[str] = None,
    crudos_facebook: Optional[List[Path]] = None,
    sin_facebook: bool = False,
) -> int:
    cfg = cargar_config(config_path)
    settings, sources = cfg["settings"], cfg["sources"]
    if only:
        deseadas = {x.strip() for x in only.split(",") if x.strip()}
        sources = [s for s in sources if s["id"] in deseadas]
    if sin_facebook:
        sources = _fuentes_web(sources)

    zona = settings.get("timezone", "America/La_Paz")
    generado_en = ahora_iso(zona)
    ahora = datetime.fromisoformat(generado_en)
    max_muestras = int(settings.get("max_muestras_rechazadas", 3))

    fb_sources = _fuentes_facebook(sources)
    web_sources = _fuentes_web(sources)

    print("=" * 62)
    print("EVENTOS BOLIVIA")
    print("=" * 62)
    if crudos_facebook:
        print(f"Facebook: ya leído en {len(crudos_facebook)} job(s) aparte, "
              f"cada uno con su IP.")
    else:
        print(f"Facebook: {len(fb_sources)} fuente(s) desde esta misma IP "
              f"(presupuesto {settings.get('facebook_paginas_por_ip', 2)} páginas).")
    print(f"Web: {len(web_sources)} fuente(s) en paralelo.")

    # Facebook
    if crudos_facebook is not None:
        resultados = dict(_cargar_crudos(crudos_facebook))
    elif fb_sources:
        resultados = dict(await leer_fuentes_facebook(fb_sources, settings))
    else:
        resultados = {}

    # Web
    if web_sources:
        resultados.update(await _leer_webs(web_sources, settings))

    # Memoria de rotación: solo de Facebook, que es la que se reparte por IP.
    ids_fb = {s["id"] for s in fb_sources}
    resultados_fb = {sid: r for sid, r in resultados.items() if sid in ids_fb}
    rotacion = {}
    if resultados_fb:
        rotacion = actualizar_rotacion(
            out_dir / "_interno" / "facebook_rotacion.json", resultados_fb, generado_en
        )

    # Clasificación
    eventos, diagnostico = [], []
    for i, source in enumerate(sources, 1):
        # Una fuente sin resultado no falló: el planificador la dejó para la
        # ola siguiente. Marcarla como error inflaría el conteo de fallos y
        # escondería los problemas de verdad.
        resultado = resultados.get(source["id"], {
            "items": [],
            "error": "Omitida: no le tocó turno en esta ola de rotación.",
        })
        error = resultado.get("error")
        estado = _estado_de_fuente(error)
        crudos = resultado.get("items", [])

        aceptados, rechazados = [], []
        for item in crudos:
            evento = construir_evento(item, generado_en, ahora=ahora)
            if evento:
                aceptados.append(evento)
            elif len(rechazados) < max_muestras:
                rechazados.append(_muestra_rechazada(item, ahora))

        eventos.extend(aceptados)
        icono = next((x.source_icon_url for x in crudos if x.source_icon_url),
                     source.get("icon_url"))

        diagnostico.append({
            "id": source["id"], "name": source["name"], "url": source["url"],
            "type": source["type"], "source_class": source.get("source_class"),
            "tier": source.get("tier"), "region": source.get("region"),
            "city": source.get("city"), "icon_url": icono,
            "status": estado,
            "raw_items": len(crudos), "events": len(aceptados),
            "rejected": len(crudos) - len(aceptados),
            "rejected_samples": rechazados,
            "error": _compacto(str(error))[:500] if error else None,
        })

        etiqueta = {"ok": "OK", "blocked": "BLOQUEADA",
                    "skipped": "OMITIDA", "error": "ERROR"}[estado]
        detalle = (f"{len(crudos)} publicaciones -> {len(aceptados)} eventos"
                   if estado == "ok" else _compacto(str(error))[:100])
        print(f"[{i:>2}/{len(sources)}] {etiqueta:<9} {source['id']:<28} {detalle}")

    # Fusión y reconciliación con lo que ya sabíamos
    eventos = list({e.id: e for e in eventos}.values())
    fusionados = fusionar(
        eventos, umbral=float(settings.get("umbral_fusion", 0.30))
    )

    archivo_path = out_dir / "_interno" / "eventos_historial.json"
    catalogo = reconciliar(
        fusionados, archivo_path, generado_en,
        umbral=float(settings.get("umbral_historial", 0.62)),
        conservar_pasados_dias=int(settings.get("conservar_pasados_dias", 4)),
        tz_nombre=zona,
    )
    guardar_archivo(archivo_path, catalogo, generado_en)

    cobertura = resumen_cobertura(rotacion, fb_sources, ahora) if fb_sources else {}

    payload = construir_payload(
        catalogo, diagnostico, generado_en, zona, cobertura,
        incluir_finalizados=bool(settings.get("incluir_finalizados", True)),
    )
    escribir_json(out_dir / "eventos_bolivia.json", payload)
    escribir_json(out_dir / "eventos_bolivia_lite.json", construir_payload_lite(payload))
    escribir_json(out_dir / "estado_fuentes.json", {
        "generated_at": generado_en,
        "coverage": cobertura,
        "sources": diagnostico,
    })
    _escribir_csv(out_dir / "eventos_bolivia.csv", payload["events"])

    resumen = payload["summary"]
    print("=" * 62)
    print(f"Eventos en el catálogo:      {resumen['events_total']}")
    print(f"  por venir:                 {resumen['events_upcoming']}")
    print(f"  hoy:                       {resumen['events_today']}")
    print(f"  vistos en esta corrida:    {resumen['events_seen_this_run']}")
    print(f"  con foto:                  {resumen['events_with_image']}")
    print(f"  con video:                 {resumen['events_with_video']}")
    print(f"Fuentes ok/bloq/omit/error:  {resumen['sources_ok']}/"
          f"{resumen['sources_blocked']}/{resumen['sources_skipped']}/"
          f"{resumen['sources_error']}")
    if cobertura:
        print(f"Cobertura Facebook:          {cobertura['con_datos_alguna_vez']}"
              f"/{cobertura['fuentes_totales']} fuentes con datos alguna vez")
    print()
    print(f"  APP (lista):   {out_dir / 'eventos_bolivia_lite.json'}")
    print(f"  APP (detalle): {out_dir / 'eventos_bolivia.json'}")
    print(f"  DIAGNÓSTICO:   {out_dir / 'estado_fuentes.json'}")
    return 0


CAMPOS_CSV = [
    "event_id", "title", "category", "starts_at", "display_date", "lifecycle",
    "days_until", "department", "city", "venue", "address", "is_free",
    "price_from", "price_to", "price_label", "status", "confidence",
    "source_count", "image_url", "video_url", "url", "ticket_urls",
]


def _escribir_csv(path: Path, eventos: List[Dict[str, Any]]) -> None:
    """Un CSV para revisar el catálogo a ojo en una planilla. La app usa el JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CAMPOS_CSV)
        writer.writeheader()
        for evento in eventos:
            fila = {c: evento.get(c) for c in CAMPOS_CSV}
            fila["ticket_urls"] = " | ".join(evento.get("ticket_urls") or [])
            writer.writerow(fila)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Scraper de eventos de Bolivia, con Facebook repartido entre varias IPs.",
    )
    p.add_argument("--config", default=str(RAIZ / "config" / "sources.yaml"))
    p.add_argument("--out", default=str(RAIZ / "data"))
    p.add_argument("--only", default=None, help="IDs de fuentes separados por coma")

    p.add_argument(
        "--planificar-facebook", action="store_true",
        help="Imprime 'matriz=<json>' con el reparto de fuentes en grupos para el "
             "fan-out de CI. Pensado para redirigirse a $GITHUB_OUTPUT.",
    )
    p.add_argument(
        "--tamano-grupo", type=int, default=2,
        help="Fuentes por grupo/job (default 2). Facebook corta después de 1-2 "
             "páginas por IP, así que grupos chicos pierden menos fuentes.",
    )
    p.add_argument(
        "--max-grupos", type=int, default=20,
        help="Tope de jobs paralelos (default 20). Es el tope real de IPs "
             "simultáneas y por lo tanto la palanca principal de cobertura.",
    )
    p.add_argument(
        "--grupos-solos", type=int, default=6,
        help="Cuántas fuentes de máxima prioridad se llevan una IP entera para "
             "ellas solas (default 6).",
    )
    p.add_argument(
        "--facebook-scrape-group-out", default=None,
        help="Lee solo las fuentes de --only y guarda el resultado crudo en este "
             "archivo, sin escribir los JSON finales.",
    )
    p.add_argument(
        "--facebook-raw-in", default=None,
        help="Uno o más archivos de --facebook-scrape-group-out separados por coma. "
             "Si se pasa, no se vuelve a leer Facebook.",
    )
    p.add_argument(
        "--sin-facebook", action="store_true",
        help="Corre solo con las fuentes web. Es la red de seguridad para cuando "
             "ningún job de Facebook llegó a entregar resultados: el catálogo se "
             "sostiene con el historial y con lo que aporten las webs.",
    )
    args = p.parse_args()

    if args.planificar_facebook:
        rotacion = Path(args.out) / "_interno" / "facebook_rotacion.json"
        print("matriz=" + planificar(
            Path(args.config), rotacion,
            args.tamano_grupo, args.max_grupos, args.grupos_solos,
        ))
        return 0

    if args.facebook_scrape_group_out:
        if not args.only:
            raise SystemExit("--facebook-scrape-group-out requiere --only con los IDs del grupo")
        ids = {x.strip() for x in args.only.split(",") if x.strip()}
        return asyncio.run(
            leer_grupo(Path(args.config), ids, Path(args.facebook_scrape_group_out))
        )

    crudos = None
    if args.facebook_raw_in:
        crudos = [Path(x.strip()) for x in args.facebook_raw_in.split(",") if x.strip()]

    return asyncio.run(correr(
        Path(args.config), Path(args.out), args.only, crudos, args.sin_facebook
    ))


if __name__ == "__main__":
    raise SystemExit(main())
