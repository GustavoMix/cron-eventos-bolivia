"""Lectura de páginas públicas de Facebook.

No inicia sesión, no resuelve captchas y no intenta eludir controles de acceso.
Lee únicamente lo que Facebook muestra públicamente a un visitante sin cuenta.

La estrategia de estabilidad es deliberadamente conservadora: catálogo grande,
rotación entre corridas, muy pocas páginas por job, pausas, corte inmediato ante
bloqueo y conservación del historial. Así una fuente puede estar en el catálogo
sin necesidad de golpearla en cada ejecución.
"""

import asyncio
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from .models import RawItem


class FacebookBlockedError(RuntimeError):
    """Facebook mostró la pantalla de bloqueo o de login en vez del contenido."""


# Señales de que estamos ante la pantalla de bloqueo y no ante una página que
# simplemente no publicó nada. Se revisan SOLO cuando no se encontró ningún
# post real: Facebook incluye un formulario de login en el DOM de cualquier
# página pública, así que buscarlas antes daría un falso positivo siempre.
SEÑALES_DE_BLOQUEO = [
    "temporarily blocked", "you're temporarily blocked", "you’re temporarily blocked",
    "temporalmente bloqueado", "has superado el límite", "has superado el limite",
    "correo electrónico o número de celular", "correo electronico o numero de celular",
    "olvidaste tu contraseña", "email or phone number", "forgotten password",
    "log in to continue", "inicia sesión para continuar",
    "inicia sesion para continuar", "contenido no disponible por ahora",
]

RUIDO_DE_INTERFAZ = {
    "me gusta", "comentar", "compartir", "enviar", "seguir", "seguidores",
    "reacciones", "todos", "más relevantes", "mas relevantes", "ver más",
    "ver mas", "facebook", "reproducir", "pausar", "silenciar", "activar sonido",
    "crear cuenta", "iniciar sesión", "iniciar sesion", "ver traducción",
    "ver traduccion", "escribe un comentario", "más opciones", "mas opciones",
}

# Palabras que hacen que valga la pena mirar un post con más detalle. No se usan
# para aceptar ni rechazar —de eso se encarga el clasificador— sino para decidir
# a cuáles posts les gastamos una visita extra de enriquecimiento.
PISTAS_DE_EVENTO = [
    "evento", "concierto", "festival", "feria", "expo", "teatro", "show",
    "función", "funcion", "entrada", "entradas", "preventa", "boletería",
    "boleteria", "taller", "curso", "conferencia", "exposición", "exposicion",
    "presentación", "presentacion", "gira", "tour", "fiesta", "campeonato",
    "torneo", "maratón", "maraton", "desfile", "carnaval", "agenda",
    "te esperamos", "no te lo pierdas", "próximamente", "proximamente",
    "inscripciones", "cupos", "en vivo", "invitamos",
]


def _limpiar_imagen(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return None
    bajo = url.lower()
    if any(x in bajo for x in ["emoji.php", "rsrc.php", "static.xx.fbcdn.net", "/images/emoji"]):
        return None
    return url


def _limpiar_url_fb(href: Optional[str]) -> Optional[str]:
    if not href:
        return None
    href = href.strip()
    if href.startswith("/"):
        href = urljoin("https://www.facebook.com", href)
    if not href.startswith(("http://", "https://")):
        return None
    return href.replace("https://m.facebook.com/", "https://www.facebook.com/")


def _parece_evento(texto: str) -> bool:
    bajo = (texto or "").lower()
    return any(p in bajo for p in PISTAS_DE_EVENTO)


def _limpiar_partes(partes: List[str], nombre_fuente: str = "") -> str:
    salida, vistos = [], set()
    fuente = (nombre_fuente or "").strip().lower()
    for crudo in partes:
        t = re.sub(r"[ \t]+", " ", (crudo or "")).strip()
        if not t:
            continue
        bajo = t.lower().strip(" .:-")
        if bajo in RUIDO_DE_INTERFAZ or (fuente and bajo == fuente):
            continue
        if len(t) <= 3 and not any(c.isalpha() for c in t):
            continue
        if re.fullmatch(r"\d+[KkMm]?", t):
            continue
        if bajo not in vistos:
            vistos.add(bajo)
            salida.append(t)
    return "\n".join(salida).strip()


async def _icono_de_fuente(page, source: Dict[str, Any]) -> Optional[str]:
    explicito = source.get("icon_url")
    if explicito:
        return explicito

    nombre = source.get("name", "").split(" - ")[0].strip()
    candidatos: List[Tuple[int, str]] = []

    if nombre:
        try:
            loc = page.locator("img[src]")
            n = min(await loc.count(), 150)
            for i in range(n):
                img = loc.nth(i)
                alt = (await img.get_attribute("alt")) or ""
                if nombre.lower() not in alt.lower():
                    continue
                src = _limpiar_imagen(await img.get_attribute("src"))
                if not src:
                    continue
                try:
                    tam = await img.evaluate(
                        "(e)=>({w:e.naturalWidth||e.width||0,h:e.naturalHeight||e.height||0})"
                    )
                    area = int(tam.get("w", 0)) * int(tam.get("h", 0))
                except Exception:
                    area = 0
                candidatos.append((area, src))
        except Exception:
            pass

    try:
        meta = page.locator('meta[property="og:image"]')
        if await meta.count():
            src = _limpiar_imagen(await meta.first.get_attribute("content"))
            if src:
                candidatos.append((1, src))
    except Exception:
        pass

    if not candidatos:
        return None
    candidatos.sort(key=lambda x: x[0], reverse=True)
    return candidatos[0][1]


async def _texto_del_post(nodo, nombre_fuente: str) -> str:
    """El texto del afiche, sin los botones ni los contadores del article.

    Los saltos de línea se conservan: en un afiche, cada renglón es un dato
    distinto (título, fecha, lugar, precio) y aplanarlos a un solo párrafo hace
    que las expresiones regulares del clasificador se coman de un campo al
    siguiente.
    """
    partes: List[str] = []
    for selector in [
        '[data-ad-preview="message"]',
        '[data-ad-comet-preview="message"]',
        'div[dir="auto"]',
        'span[dir="auto"]',
    ]:
        try:
            loc = nodo.locator(selector)
            n = min(await loc.count(), 60)
            for i in range(n):
                try:
                    txt = (await loc.nth(i).inner_text(timeout=1200)).strip()
                except Exception:
                    continue
                if txt:
                    partes.append(txt)
        except Exception:
            pass

    limpio = _limpiar_partes(partes, nombre_fuente)
    if len(limpio) >= 40:
        return limpio

    try:
        respaldo = (await nodo.inner_text(timeout=3500)).strip()
    except Exception:
        respaldo = ""
    return _limpiar_partes(respaldo.splitlines(), nombre_fuente)


async def _imagenes_del_post(nodo, icono_fuente: Optional[str]) -> List[str]:
    """El afiche es el activo más valioso de un evento, así que el filtro de
    tamaño es generoso: se descartan iconos y avatares, no fotos chicas."""
    urls: List[str] = []
    try:
        imgs = nodo.locator("img[src]")
        n = min(await imgs.count(), 60)
        for i in range(n):
            img = imgs.nth(i)
            src = _limpiar_imagen(await img.get_attribute("src"))
            if not src or src == icono_fuente or src in urls:
                continue
            try:
                tam = await img.evaluate(
                    "(e)=>({w:e.naturalWidth||e.width||0,h:e.naturalHeight||e.height||0})"
                )
                w, h = int(tam.get("w", 0)), int(tam.get("h", 0))
            except Exception:
                w = h = 0
            if w and h and (w < 180 or h < 180):
                continue
            alt = ((await img.get_attribute("alt")) or "").lower()
            if any(x in alt for x in [
                "emoji", "profile picture", "foto del perfil", "reacción", "reaction",
            ]):
                continue
            urls.append(src)
    except Exception:
        pass
    return urls[:12]


async def _video_del_post(nodo, url_post: str, imagenes: List[str]):
    """Se conserva el enlace público del video o reel, nunca un stream interno."""
    url_video = tipo = miniatura = None
    try:
        links = nodo.locator(
            'a[href*="/videos/"], a[href*="/reel/"], a[href*="/watch/"], a[href*="watch?v="]'
        )
        n = min(await links.count(), 15)
        for i in range(n):
            href = _limpiar_url_fb(await links.nth(i).get_attribute("href"))
            if href:
                url_video = href
                tipo = "facebook_reel" if "/reel/" in href.lower() else "facebook_video"
                break
    except Exception:
        pass

    if not url_video:
        bajo = (url_post or "").lower()
        if any(x in bajo for x in ["/videos/", "/reel/", "watch?v="]):
            url_video = url_post
            tipo = "facebook_reel" if "/reel/" in bajo else "facebook_video"

    if url_video:
        try:
            vids = nodo.locator("video")
            if await vids.count():
                miniatura = _limpiar_imagen(await vids.first.get_attribute("poster"))
        except Exception:
            pass
        if not miniatura and imagenes:
            miniatura = imagenes[0]

    return url_video, miniatura, tipo


async def _enlaces_del_post(nodo) -> Tuple[Optional[str], List[str]]:
    """(evento de Facebook, enlaces externos).

    Un enlace a /events/ es el dato más confiable que puede traer un post: es el
    propio Facebook diciendo que esto es un evento, con su fecha adentro.
    """
    evento_fb: Optional[str] = None
    externos: List[str] = []
    try:
        links = nodo.locator("a[href]")
        n = min(await links.count(), 60)
        for i in range(n):
            href = await links.nth(i).get_attribute("href")
            if not href:
                continue
            limpio = _limpiar_url_fb(href)
            if not limpio:
                continue
            bajo = limpio.lower()
            if "/events/" in bajo and not evento_fb:
                evento_fb = limpio.split("?")[0]
                continue
            host = urlparse(bajo).netloc
            if host and "facebook.com" not in host and limpio not in externos:
                # Facebook envuelve los enlaces salientes en /l.php?u=...; esos
                # ya quedaron filtrados arriba por tener host de facebook.com.
                externos.append(limpio)
    except Exception:
        pass
    return evento_fb, externos[:8]


async def _fecha_de_publicacion(nodo) -> Optional[str]:
    try:
        marca = nodo.locator("abbr, time")
        if await marca.count():
            return (
                await marca.first.get_attribute("datetime")
                or await marca.first.get_attribute("title")
                or (await marca.first.inner_text(timeout=1000)).strip()
            )
    except Exception:
        pass
    try:
        anclas = nodo.locator("a[aria-label], a[title]")
        n = min(await anclas.count(), 30)
        for i in range(n):
            a = anclas.nth(i)
            valor = (await a.get_attribute("aria-label")) or (await a.get_attribute("title"))
            if valor and any(x in valor.lower() for x in [
                "hora", "ayer", "hoy", "lunes", "martes", "miércoles", "miercoles",
                "jueves", "viernes", "sábado", "sabado", "domingo",
                "ene", "feb", "mar", "abr", "may", "jun",
                "jul", "ago", "sep", "oct", "nov", "dic",
            ]):
                return valor.strip()
    except Exception:
        pass
    return None


async def _enriquecer_post(context, item: RawItem, timeout_ms: int = 12000) -> RawItem:
    """Abre el post público para recuperar el texto completo y el afiche grande.

    En el feed, Facebook recorta los textos largos con un "Ver más" y sirve las
    imágenes en miniatura. Los afiches de eventos son justamente textos largos
    con toda la información —fecha, lugar, precios, puntos de venta— así que en
    este proyecto el enriquecimiento no es un lujo: es donde aparecen los datos.

    Cada visita consume parte del presupuesto del job, así que el runner
    decide con cuentagotas qué posts vale la pena enriquecer.
    """
    if not item.item_url or item.item_url == item.source_url:
        return item

    page = await context.new_page()
    try:
        await page.goto(item.item_url, wait_until="domcontentloaded", timeout=timeout_ms)
        await page.wait_for_timeout(1000)

        partes: List[str] = []
        for selector in ['meta[property="og:description"]', 'meta[name="description"]']:
            try:
                loc = page.locator(selector)
                if await loc.count():
                    valor = (await loc.first.get_attribute("content")) or ""
                    if valor:
                        partes.append(valor)
            except Exception:
                pass

        try:
            loc = page.locator('div[dir="auto"]')
            n = min(await loc.count(), 60)
            del_dom = []
            for i in range(n):
                try:
                    txt = (await loc.nth(i).inner_text(timeout=700)).strip()
                except Exception:
                    continue
                if txt:
                    del_dom.append(txt)
            texto_dom = _limpiar_partes(del_dom, item.source_name)
            if texto_dom:
                partes.append(texto_dom)
        except Exception:
            pass

        mas_rico = _limpiar_partes(partes, item.source_name)
        if len(mas_rico) > len(item.text):
            item.text = mas_rico

        try:
            og = page.locator('meta[property="og:image"]')
            if await og.count():
                img = _limpiar_imagen(await og.first.get_attribute("content"))
                if img and img != item.source_icon_url and img not in item.image_urls:
                    # Al frente: og:image es el afiche en tamaño completo y es la
                    # imagen que la app debería mostrar como principal.
                    item.image_urls.insert(0, img)
                    item.image_urls = item.image_urls[:12]
        except Exception:
            pass

        # Si el detalle es un reel/video, conservar siempre la URL pública
        # canónica. No se extraen streams MP4 internos ni URLs temporales.
        try:
            canonical = page.locator('link[rel="canonical"]')
            if await canonical.count():
                href = _limpiar_url_fb(await canonical.first.get_attribute("href"))
                if href:
                    item.item_url = href
                    bajo = href.lower()
                    if any(x in bajo for x in ["/videos/", "/reel/", "watch?v="]):
                        item.video_url = href
                        item.video_type = "facebook_reel" if "/reel/" in bajo else "facebook_video"
                        if not item.video_thumbnail_url and item.image_urls:
                            item.video_thumbnail_url = item.image_urls[0]
        except Exception:
            pass

        try:
            titulo = page.locator('meta[property="og:title"]')
            if await titulo.count():
                valor = (await titulo.first.get_attribute("content")) or ""
                if valor and len(valor) > 8:
                    item.title = valor
        except Exception:
            pass
    except Exception:
        pass
    finally:
        await page.close()
    return item


async def _leer_fuente(source: Dict[str, Any], settings: Dict[str, Any], context) -> List[RawItem]:
    url = source["url"]
    espera = float(settings.get("facebook_espera_segundos", 2.5))
    max_items = int(settings.get("max_items_por_fuente", 20))
    scrolls = int(settings.get("facebook_scrolls", 3))
    enriquecer = bool(settings.get("facebook_enriquecer", True))
    limite_enriquecer = int(settings.get("facebook_enriquecer_limite", 4))
    timeout_enriquecer = int(settings.get("facebook_enriquecer_timeout_ms", 12000))

    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(int(espera * 1000))

        icono = await _icono_de_fuente(page, source)

        for _ in range(scrolls):
            try:
                if await page.locator('[role="article"]').count() >= max_items:
                    break
                await page.mouse.wheel(0, 2400)
                await page.wait_for_timeout(500)
            except Exception:
                break

        crudos: List[RawItem] = []
        articles = page.locator('[role="article"]')
        total = min(await articles.count(), max_items)

        for i in range(total):
            nodo = articles.nth(i)
            texto = await _texto_del_post(nodo, source.get("name", ""))
            if len(texto) < 25:
                continue

            url_post = url
            try:
                links = nodo.locator(
                    'a[href*="/posts/"], a[href*="/videos/"], a[href*="/reel/"], '
                    'a[href*="story_fbid="], a[href*="/permalink/"], a[href*="watch?v="]'
                )
                n = min(await links.count(), 15)
                for j in range(n):
                    href = _limpiar_url_fb(await links.nth(j).get_attribute("href"))
                    if href:
                        url_post = href
                        break
            except Exception:
                pass

            imagenes = await _imagenes_del_post(nodo, icono)
            url_video, miniatura, tipo_video = await _video_del_post(nodo, url_post, imagenes)
            evento_fb, externos = await _enlaces_del_post(nodo)

            crudos.append(RawItem(
                source_id=source["id"],
                source_name=source["name"],
                source_url=url,
                item_url=url_post,
                text=texto,
                title="",
                published_at=await _fecha_de_publicacion(nodo),
                region_hint=source.get("region"),
                city_hint=source.get("city"),
                source_class=source.get("source_class", "media"),
                tier=int(source.get("tier", 3)),
                source_icon_url=icono,
                image_urls=imagenes,
                video_url=url_video,
                video_thumbnail_url=miniatura,
                video_type=tipo_video,
                facebook_event_url=evento_fb,
                external_links=externos,
            ))

        if not crudos:
            # Recién ahora vale la pena preguntarse si Facebook bloqueó: hasta
            # acá, "cero posts" podía ser simplemente una página sin novedades.
            cuerpo = await page.locator("body").inner_text(timeout=7000)
            bajo = cuerpo.lower()
            if any(s in bajo for s in SEÑALES_DE_BLOQUEO):
                vista = re.sub(r"\s+", " ", cuerpo).strip()[:200]
                raise FacebookBlockedError(
                    f"Facebook ocultó el contenido público en esta corrida. Vista previa: {vista!r}"
                )

        if enriquecer and crudos:
            # El presupuesto se gasta primero en los posts que más lo necesitan:
            # los que parecen un evento pero llegaron recortados por el "Ver más".
            candidatos = sorted(
                range(len(crudos)),
                key=lambda i: (
                    not _parece_evento(crudos[i].text),
                    -min(len(crudos[i].text), 600),
                ),
            )
            usados = 0
            for i in candidatos:
                if usados >= limite_enriquecer:
                    break
                item = crudos[i]
                if item.item_url == url or not _parece_evento(item.text):
                    continue
                if len(item.text) > 700 and item.image_urls:
                    # Ya vino completo y con afiche: gastar una visita acá sería
                    # quitarle presupuesto a un post que sí llegó recortado.
                    continue
                crudos[i] = await _enriquecer_post(context, item, timeout_enriquecer)
                usados += 1

        vistos, salida = set(), []
        for x in crudos:
            clave = (x.item_url, x.text[:300])
            if clave not in vistos:
                vistos.add(clave)
                salida.append(x)
        return salida[:max_items]
    finally:
        await page.close()


async def leer_fuentes_facebook(
    sources: List[Dict[str, Any]],
    settings: Dict[str, Any],
) -> Dict[str, Any]:
    """Lee las fuentes de este grupo una por una, en un solo navegador.

    Sin concurrencia dentro del mismo job: se navega una fuente a la vez.

    Tres cosas terminan el grupo antes de tiempo: un bloqueo confirmado, agotar
    el presupuesto de páginas del job o quedarse sin fuentes. Las pendientes se
    reportan como omitidas y vuelven por rotación en corridas posteriores.
    """
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        raise RuntimeError(
            "Playwright no está instalado. Ejecuta: python -m playwright install chromium"
        ) from exc

    pausa = max(5.0, float(settings.get("facebook_pausa_segundos", 9.0)))
    reintento = max(20.0, float(settings.get("facebook_pausa_tras_bloqueo", 35.0)))
    presupuesto = int(settings.get("facebook_paginas_por_ip", 2))

    resultados: Dict[str, Any] = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-dev-shm-usage",
                "--disable-background-networking",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
            ],
        )
        # Un solo contexto para el grupo, sin falsificar huellas del navegador.
        # La estabilidad viene del bajo volumen y la rotación, no de camuflaje.
        context = await browser.new_context(
            locale="es-BO",
            timezone_id=settings.get("timezone", "America/La_Paz"),
            viewport={"width": 1366, "height": 864},
            service_workers="block",
        )

        async def enrutar(route):
            tipo = route.request.resource_type
            url = route.request.url.lower()
            # Las fuentes y los videos no aportan nada a la lectura y sí cuestan
            # tiempo. Las imágenes SÍ se cargan: sin ellas no hay naturalWidth y
            # el filtro que distingue un afiche de un icono deja de funcionar.
            if tipo in {"font", "media"}:
                await route.abort()
                return
            if any(x in url for x in [
                "doubleclick.net", "google-analytics.com", "googletagmanager.com",
            ]):
                await route.abort()
                return
            await route.continue_()

        await context.route("**/*", enrutar)

        bloqueado = False
        leidas = 0

        for i, source in enumerate(sources):
            if bloqueado:
                resultados[source["id"]] = {
                    "items": [],
                    "error": "Omitida: Facebook bloqueó otra fuente antes en esta misma corrida.",
                }
                continue
            if leidas >= presupuesto:
                resultados[source["id"]] = {
                    "items": [],
                    "error": (
                        f"Omitida: se agotó el presupuesto de {presupuesto} páginas "
                        f"para la IP de este job."
                    ),
                }
                continue

            try:
                items = await _leer_fuente(source, settings, context)
                resultados[source["id"]] = {"items": items, "error": None}
            except FacebookBlockedError as exc:
                # Un bloqueo confirmado corta el grupo: no insistimos ni tratamos
                # de esquivarlo. La fuente vuelve a entrar por rotación después.
                resultados[source["id"]] = {"items": [], "error": str(exc)}
                bloqueado = True
                await asyncio.sleep(reintento)
            except Exception as exc:
                resultados[source["id"]] = {"items": [], "error": str(exc)}

            leidas += 1

            quedan = i < len(sources) - 1 and not bloqueado and leidas < presupuesto
            if quedan:
                # Pausa con ruido: una espera de exactamente 9.000 s repetida
                # igual en treinta jobs es más delatora que la pausa misma.
                await asyncio.sleep(pausa * random.uniform(0.8, 1.5))

        await context.close()
        await browser.close()

    return resultados
