# Estrategia de lectura de Facebook público

## Objetivo

El catálogo usa páginas públicas de Facebook porque muchas instituciones, sedes,
ferias y productores bolivianos anuncian allí sus eventos primero. La prioridad
es obtener datos útiles **sin depender de un barrido agresivo** ni de técnicas de
evasión.

La regla del proyecto es simple: si Facebook deja de mostrar contenido público,
el job se detiene. No se intenta iniciar sesión, resolver captchas, falsificar
huellas, rotar proxies ni extraer streams internos.

## Cómo se mantiene estable

### 1. Una fuente por job por defecto

El workflow usa `--tamano-grupo 1`. Así cada job hace poco trabajo y un fallo en
una página no arrastra a una lista larga de fuentes.

### 2. Olas de rotación

Hay 70 páginas de Facebook configuradas, pero una corrida no necesita leerlas
todas. El planificador elige una ola pequeña según prioridad y antigüedad de la
última lectura. Lo que queda fuera sube de prioridad en las corridas siguientes.

Esto encaja bien con eventos: conciertos, ferias y obras suelen anunciarse con
días o semanas de anticipación.

### 3. Pausas y presupuesto pequeño

`config/sources.yaml` define:

```yaml
facebook_paginas_por_ip: 1   # nombre legado: máximo de páginas por job
facebook_pausa_segundos: 12
facebook_pausa_tras_bloqueo: 45
facebook_enriquecer_limite: 2
```

El nombre `facebook_paginas_por_ip` se conserva para no romper configuraciones
anteriores, pero en esta versión se interpreta como **presupuesto por job**.

### 4. Corte limpio ante bloqueo

Cuando el lector detecta una pantalla de login/bloqueo o ausencia clara del
contenido público esperado, registra el estado, espera el enfriamiento indicado
y termina ese grupo. No encadena reintentos para intentar atravesar el control.

### 5. Historial persistente

`data/_interno/eventos_historial.json` conserva eventos todavía vigentes. Una
corrida que leyó pocas fuentes no vacía la app: devuelve el catálogo válido
anterior más cualquier novedad encontrada hoy.

`data/_interno/facebook_rotacion.json` conserva la memoria de cobertura para que
las fuentes menos vistas ganen prioridad.

### 6. Fuentes web como respaldo

Las 9 fuentes web se procesan aparte. Cuando exponen `schema.org/Event`, se usan
campos estructurados de fecha, sede y precio en vez de intentar deducirlos del
texto.

## Fotos y video

El scraper intenta conservar:

- foto/afiche principal y galería pública disponible;
- icono de la fuente;
- permalink público de Facebook para reels o videos;
- miniatura pública cuando está disponible;
- `video_type` (`facebook_reel` o `facebook_video`).

No busca URLs MP4 internas o temporales. Para la app es más durable guardar el
permalink oficial del reel/video y abrirlo o embeberlo según corresponda.

## Planificación recomendada

```bash
python main.py --planificar-facebook \
  --max-grupos 8 \
  --tamano-grupo 1 \
  --grupos-solos 8
```

Con esos valores entran hasta 8 fuentes de Facebook por ola. El cron de GitHub
Actions corre cada 3 horas, por lo que el catálogo rota gradualmente sin una
ráfaga de 70 páginas.

## Diagnóstico

`data/estado_fuentes.json` permite revisar:

- fuentes con datos recientes;
- fuentes nunca vistas;
- fallos persistentes (URL renombrada, borrada o privada);
- bloqueos/indisponibilidad en la última corrida;
- muestras descartadas y motivo del filtro.

Si una fuente falla de forma persistente, se corrige o elimina su URL. Si una
ola trae pocos datos, el historial mantiene el catálogo y la siguiente corrida
continúa la rotación.
