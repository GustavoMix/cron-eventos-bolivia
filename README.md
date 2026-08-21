# Eventos Bolivia

Cron que arma un catálogo nacional de eventos —conciertos, festivales, ferias,
teatro, deportes, cultura— leyendo páginas públicas de Facebook y sitios de
ticketeras y agendas culturales, y lo publica como JSON listo para una app.

**Salida para la app:**

- `data/eventos_bolivia_lite.json` — índice liviano, para la pantalla de lista
- `data/eventos_bolivia.json` — catálogo completo, para el detalle
- `data/estado_fuentes.json` — diagnóstico: qué fuente aportó qué y por qué no
- `data/eventos_bolivia.csv` — el catálogo en planilla, para revisar a ojo

El contrato con la app, con las data classes de Kotlin listas para copiar, está
en **[docs/FORMATO_JSON.md](docs/FORMATO_JSON.md)**.

## Facebook: rotación conservadora

Facebook aporta gran parte de la agenda local, pero su contenido público puede
variar o dejar de mostrarse a automatizaciones. Este proyecto no intenta eludir
esos controles. En vez de barrer las 70 páginas de una sola vez, usa **olas
pequeñas**, una fuente por job por defecto, pausas y memoria entre corridas.

```
planificar ─┬─► fuente 01 ─┐
            ├─► fuente 02 ─┤
            ├─► ...       ├─► consolidar ─► JSON + historial
            └─► fuente 08 ─┘
```

El catálogo se acumula: un evento vigente no desaparece sólo porque su fuente no
entró en la ola actual. La siguiente corrida continúa la rotación. Ante una
pantalla de bloqueo/login, el job registra el estado y corta sin intentar
atravesarla.

Todo el detalle está en **[docs/ESTRATEGIA_FACEBOOK.md](docs/ESTRATEGIA_FACEBOOK.md)**.

## Qué se extrae de cada evento

De un afiche como este:

```
🎸 LOS KJARKAS EN CONCIERTO
Sábado 23 de agosto · 20:00 hrs
Puertas 19:00
Teatro Achá, Cochabamba
Preventa Bs 80 / En puerta Bs 120
Entradas en SuperTicket y Farmacorp
```

sale esto:

| | |
|---|---|
| Fecha y hora | `2026-08-23T20:00:00-04:00` + epoch millis |
| Para mostrar | `"Domingo 23 de agosto · 20:00"` · `"Dom 23 ago · 20:00"` · `"En 9 días"` |
| Fecha desarmada | día de la semana, día, mes, año, hora, puertas y rango, ya escritos |
| Puertas | `19:00` (dato aparte del show) |
| Sede | `Teatro Achá` → ciudad y departamento deducidos |
| Precio | `80.0` a `120.0` BOB → `"Bs 80 - 120"` |
| Dónde comprar | `["SuperTicket", "Farmacorp"]` → `"En SuperTicket y Farmacorp"` |
| Categoría | `concierto` → `"Conciertos"` |
| Ciclo de vida | `proximo`, faltan 9 días |
| Fotos y videos | afiche en alta + galería + enlaces de video |
| Calidad | `93/100`, `excelente`, nada faltante |

## Dos reglas que definen el catálogo

**Solo eventos que se puedan mostrar.** Cada evento se puntúa por completitud
—foto, día, hora, sede, ciudad, categoría, entradas, descripción— y lo que no
llega al mínimo no se publica. No se borra: queda en el historial y entra en
cuanto alguna fuente aporte el dato que le faltaba. El puntaje viaja en el JSON
con su checklist, así que la app puede ordenar por él y el diagnóstico dice *qué*
le falta al catálogo, no solo cuánto tiene. Está en
[`scraper/calidad.py`](scraper/calidad.py).

**Dice dónde comprar, no lleva a comprar.** El JSON no publica ni un enlace de
compra: ni en `ticket_urls` (que viaja siempre vacía), ni en `url`, ni dentro de
la descripción. Lo que sí publica es *dónde* se consiguen las entradas, en
texto: "En SuperTicket y Farmacorp", "En boletería del lugar". Con un botón de
compra la app deja de ser una agenda y pasa a ser intermediaria de una venta que
no controla. La política entera está en
[`scraper/entradas.py`](scraper/entradas.py).

Y para que la foto sea la del evento y no el logo del diario, todas las
imágenes pasan por [`scraper/imagenes.py`](scraper/imagenes.py): descarta
logos, avatares y banners, sube cada miniatura a su versión original y ordena
la galería con el afiche adelante.

El parser de fechas entiende cómo escribe la gente: `"sábado 23 de agosto"`,
`"del 5 al 7 de septiembre"`, `"este viernes"` (anclado a la fecha de
publicación), `"15/03"`, `"a las 8"` (que en un afiche son las 20:00), e
ISO-8601 cuando la fuente publica datos estructurados.

Y descarta lo que no es un evento futuro: crónicas de lo de anoche
(`"gracias a todos los que nos acompañaron"`), notas policiales, avisos
laborales, promociones. Cada descarte queda registrado con su motivo en
`estado_fuentes.json`.

## Uso

### En GitHub Actions (lo normal)

El workflow corre solo cada 3 horas y también se puede lanzar a mano desde la
pestaña **Actions** → *Actualizar eventos Bolivia* → *Run workflow*, donde se
pueden ajustar los jobs paralelos y el tamaño de grupo.

Antes de depender del cron, corré una vez a mano y comprobá que `data/` se
actualizó.

El repo puede ser privado: el workflow usa el `GITHUB_TOKEN` propio con
`contents: write`. Si la rama principal tiene reglas que impiden pushes de
Actions, el paso de guardado va a fallar y hay que ajustarlas.

### En local

```bash
pip install -r requirements.txt
python -m playwright install chromium

python main.py                      # corrida completa
python main.py --only web_superticket,web_ticketbo   # solo algunas fuentes
python main.py --sin-facebook       # solo fuentes web, sin tocar Facebook
```

Para probar en local conviene `--sin-facebook` o `--only` con unas pocas
fuentes. Si Facebook deja de mostrar contenido público, el lector lo registra y
termina ese grupo.

### Modos del CLI

```bash
# 1. Planificar: imprime la matrix de GitHub Actions
python main.py --planificar-facebook --max-grupos 8 --tamano-grupo 1 --grupos-solos 8

# 2. Leer un grupo pequeño (por defecto, una fuente por job)
python main.py --only fb_superticket --facebook-scrape-group-out data/_interno/raw_g01.json

# 3. Consolidar: junta los crudos, lee las webs, clasifica y escribe los JSON
python main.py --facebook-raw-in data/_interno/raw_g01.json,data/_interno/raw_g02.json
```

## Estructura

```
scraper/
  fechas.py        Fechas y horarios en español boliviano, ya desarmados
  lugares.py       Departamentos, ciudades y sedes de los 9 departamentos
  imagenes.py      Qué imagen es el afiche y cuál es el logo del sitio
  entradas.py      Dónde se compran las entradas — y ningún enlace de compra
  calidad.py       Qué tan completo llegó el evento; qué se publica
  clasificador.py  ¿Es un evento? Categoría, precio, entradas, artistas
  facebook.py      Lectura de páginas públicas + detección de bloqueo
  web_sources.py   Ticketeras y agendas; lee schema.org/Event si está
  planificador.py  Reparto en grupos, olas de rotación, memoria entre corridas
  merger.py        Un evento anunciado por cinco fuentes es uno solo
  estado.py        Historial: el catálogo que se acumula
  salida.py        Armado de los JSON, facetas y textos ya formateados
  runner.py        Orquestación y CLI
config/sources.yaml
docs/
tests/
```

## Fuentes

**70 páginas de Facebook y 9 sitios web**, configurados en
[`config/sources.yaml`](config/sources.yaml). El catálogo cubre los 9
departamentos y combina:

- ticketeras y páginas dedicadas a eventos;
- teatros, museos, centros culturales y ferias;
- municipios, gobernaciones y universidades;
- medios generales como respaldo de descubrimiento.

Las fuentes web siguen siendo un respaldo importante y varias pueden publicar
`schema.org/Event`, que permite obtener fecha, sede y precio con campos
estructurados.

La lista completa está en **[docs/FUENTES.md](docs/FUENTES.md)**. Para agregar una
fuente, sumá una entrada al YAML; si es Facebook, entra automáticamente a la
rotación.

## Tests

```bash
python -m pytest tests/ -q
```

148 tests, sin red. Cubren el parser de fechas caso por caso, el clasificador con
afiches y con ruido realista, la elección de fotos con URLs reales de cada CDN,
el puntaje de calidad, el reparto en grupos y las olas de rotación, la fusión
entre fuentes, el historial y una prueba de extremo a extremo del pipeline
completo — incluida una corrida donde Facebook bloquea todo, para comprobar que
el catálogo sale intacto.

Dos de esas pruebas cuidan las reglas de arriba: una recorre los tres archivos
que se publican buscando el dominio de cada ticketera, y otra verifica que el
ícono de la página no termine siendo la foto del evento.
