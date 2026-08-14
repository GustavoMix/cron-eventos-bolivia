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

## El problema y la estrategia

Facebook es la mejor fuente de eventos de Bolivia y también la única que
bloquea. Deja pasar **~2 páginas por IP** antes de cortar, y ese límite vive en
la IP, no en nuestro patrón de tráfico: no se arregla con pausas más largas ni
con otro navegador.

La palanca real es **más IPs y grupos más chicos**. Cada job de GitHub Actions
es una IP distinta, así que el workflow reparte las fuentes en ~20 jobs de 1-2
fuentes cada uno:

```
planificar  ─┬─► g01 (IP 1)  ─┐
             ├─► g02 (IP 2)  ─┤
             ├─► ...          ├─► consolidar ─► JSON + commit
             └─► g20 (IP 20) ─┘
```

Y por encima de eso, la pieza que hace que alcance: **el catálogo se acumula.**
Un evento no caduca porque dejemos de verlo — un concierto anunciado hace dos
semanas sigue en pie aunque hoy nadie lo republique. El historial es la fuente
de verdad y cada corrida le suma. Por eso una corrida que solo lee 15 de 30
fuentes no da un catálogo a la mitad: da el de antes más lo nuevo.

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
| Para mostrar | `"Domingo 23 de agosto · 20:00"` |
| Puertas | `19:00` (dato aparte del show) |
| Sede | `Teatro Achá` → ciudad y departamento deducidos |
| Precio | `80.0` a `120.0` BOB → `"Bs 80 - 120"` |
| Puntos de venta | `["SuperTicket", "Farmacorp"]` |
| Categoría | `concierto` → `"Conciertos"` |
| Ciclo de vida | `proximo`, faltan 9 días |
| Fotos y videos | afiche en alta + galería + enlaces de video |

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

Desde una sola IP, Facebook va a cortar después de las primeras páginas. **Eso
no es un bug**: es exactamente el motivo de que exista el modo repartido. Para
probar en local conviene `--sin-facebook` o `--only` con unas pocas fuentes.

### Modos del CLI

```bash
# 1. Planificar: imprime la matrix de GitHub Actions
python main.py --planificar-facebook --max-grupos 20 --tamano-grupo 2 --grupos-solos 6

# 2. Leer un grupo (esto corre en cada job, con su propia IP)
python main.py --only fb_superticket --facebook-scrape-group-out data/_interno/raw_g01.json

# 3. Consolidar: junta los crudos, lee las webs, clasifica y escribe los JSON
python main.py --facebook-raw-in data/_interno/raw_g01.json,data/_interno/raw_g02.json
```

## Estructura

```
scraper/
  fechas.py        Fechas y horarios en español boliviano
  lugares.py       Departamentos, ciudades y sedes de los 9 departamentos
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

29 páginas de Facebook y 9 sitios web, en
[`config/sources.yaml`](config/sources.yaml). Las de Facebook están ordenadas
por tier:

- **tier 1** — publican eventos como su razón de ser: ticketeras (SuperTicket),
  páginas de agenda (Conciertos en Bolivia, Eventos Bolivia) y sedes (Fexpocruz,
  Teatro al Aire Libre).
- **tier 2** — municipios, gobernaciones y casas de cultura.
- **tier 3** — medios generales, que publican un evento entre veinte noticias.

Las fuentes web son el piso de garantía: no bloquean y varias publican
`schema.org/Event`, que da la fecha y el precio exactos sin adivinar nada.

Para agregar una fuente, sumá una entrada al YAML. Si es de Facebook, el
planificador la incorpora sola a la rotación en la corrida siguiente.

## Tests

```bash
python -m pytest tests/ -q
```

86 tests, sin red. Cubren el parser de fechas caso por caso, el clasificador con
afiches y con ruido realista, el reparto en grupos y las olas de rotación, la
fusión entre fuentes, el historial y una prueba de extremo a extremo del
pipeline completo — incluida una corrida donde Facebook bloquea todo, para
comprobar que el catálogo sale intacto.
