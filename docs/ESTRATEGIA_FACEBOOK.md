# La estrategia frente al bloqueo de Facebook

## El hecho

Facebook deja pasar **alrededor de dos páginas públicas por IP** antes de
devolver la pantalla de bloqueo o de login. Está medido en corridas reales del
proyecto hermano de tránsito, no estimado.

Lo importante es *dónde* vive ese límite: **en la IP, no en nuestro patrón de
tráfico**. Eso descarta de entrada toda una familia de supuestas soluciones:

| Idea | Por qué no sirve |
|---|---|
| Pausas más largas entre páginas | El corte llega igual en la tercera página, con 8 o con 60 segundos de pausa. |
| Otro User-Agent | El de Chromium real es menos delator que cualquiera que inventemos. |
| Más scrolls o más reintentos | Insistir desde una IP quemada no devuelve datos y la marca para la corrida siguiente. |
| Un solo job "más inteligente" | El techo es de ~2 páginas por IP, y un job es una IP. |

**La única palanca real es tener más IPs y grupos más chicos.** Todo lo demás
son detalles.

## Cómo se aplica

Cada job de GitHub Actions corre en un runner distinto, con su propia IP de
salida. El workflow tiene tres etapas:

```
planificar  ─┬─► leer-facebook g01 (IP 1) ─┐
             ├─► leer-facebook g02 (IP 2) ─┤
             ├─► ...                       ├─► consolidar ─► JSON + commit
             └─► leer-facebook g20 (IP 20)─┘
```

### 1. Grupos chicos

`--tamano-grupo 2`. Con grupos de cinco, un bloqueo en la primera página se
llevaba puestas las otras cuatro. Con dos, casi ninguna fuente se pierde en
cascada detrás de otra.

### 2. Turnos solos para las que más valen

`--grupos-solos 6`. Las seis fuentes más prioritarias no comparten job con
nadie: se llevan una IP entera. El primer turno de una IP es el que casi siempre
pasa; la segunda lectura es una apuesta. Las ticketeras y las páginas dedicadas
a eventos —las que de verdad alimentan la app— no deberían estar apostando.

### 3. Presupuesto explícito por IP

`facebook_paginas_por_ip: 2`. Aunque un job tenga tres fuentes asignadas y
ninguna haya fallado, se detiene al llegar al presupuesto. Insistir con la
tercera casi nunca trae datos y sí aumenta la chance de que esa IP quede marcada.

### 4. Olas de rotación

El catálogo de Facebook es más grande de lo que entra en una corrida. Cada ola
atiende a las más prioritarias y el resto espera a la siguiente.

**Esto acá se puede hacer y en el proyecto de tránsito no.** Un bloqueo de
carretera caduca en minutos; un concierto se anuncia con días o semanas de
anticipación. Ver una fuente cada tres horas en vez de cada hora no pierde un
solo evento — y permite tener un catálogo de fuentes mucho más grande.

### 5. Memoria entre corridas

`data/_interno/facebook_rotacion.json` guarda cómo le fue a cada fuente. La que
lleva más tiempo sin traer datos sube al primer turno.

Un bloqueo **no se le cuenta como culpa** a la fuente: es de la IP, no de ella.
Así sigue envejeciendo y sube sola en la corrida siguiente. Un error de verdad
—página renombrada, borrada o vuelta privada— sí baja su prioridad, para que no
acapare los turnos buenos corrida tras corrida.

### 6. Arranques escalonados

Si los veinte jobs golpean Facebook en el mismo segundo desde IPs del mismo
rango de Azure, el patrón se lee como una sola flota aunque las IPs sean
distintas. `sleep $(( orden * 5 + RANDOM % 9 ))` los separa. El viewport también
se varía unos píxeles por el mismo motivo: no oculta nada, solo evita que los
veinte runners coincidan por accidente en el mismo tamaño de ventana exacto.

## La red de seguridad: el catálogo se acumula

Esta es la pieza que hace que todo lo anterior alcance.

**Un evento no caduca porque dejemos de verlo.** Un concierto anunciado hace dos
semanas sigue en pie aunque hoy ninguna fuente lo haya vuelto a mencionar — y de
hecho eso es lo normal: un evento se anuncia una vez y se comenta pocas veces
más.

Entonces `data/_interno/eventos_historial.json` no es un respaldo, es la fuente
de verdad. Cada corrida suma lo que encontró y arrastra lo que sigue vigente,
recalculando el ciclo de vida de cada evento con la fecha actual.

La consecuencia práctica: **una corrida que solo consigue leer 15 de 30 fuentes
no produce un catálogo a la mitad.** Produce el catálogo completo de antes, más
lo nuevo que encontraron esas 15. Después de unas pocas vueltas, la cobertura
efectiva es del catálogo entero aunque ninguna corrida individual lo haya visto
completo.

Hay un test que verifica exactamente esto: `test_pipeline.py` simula una corrida
donde **Facebook bloquea absolutamente todo** y comprueba que el catálogo sale
intacto, con los mismos `event_id`.

## Qué NO hace este scraper

Por si queda duda al leer el código:

- No inicia sesión ni usa cookies de una cuenta.
- No resuelve captchas.
- No extrae streams de video internos: guarda el enlace público del post.
- No rota proxies ni falsea la procedencia del tráfico.
- No reintenta indefinidamente: ante un bloqueo confirmado, corta la corrida.

Lee páginas públicas como cualquier visitante sin cuenta, con pausas, con un
presupuesto acotado y aceptando el "no" cuando llega.

## Ajustar la cobertura

Todo se controla desde el workflow (`workflow_dispatch`) o la línea de comandos:

```bash
python main.py --planificar-facebook \
  --max-grupos 20 \      # jobs paralelos = IPs simultáneas. La palanca principal.
  --tamano-grupo 2 \     # fuentes por job
  --grupos-solos 6       # cuántas se llevan una IP entera
```

Capacidad por corrida = `grupos_solos + (max_grupos - grupos_solos) × tamano_grupo`.

Con los valores por defecto: `6 + 14 × 2 = 34` fuentes por ola.

**Si querés más cobertura, subí `--max-grupos` antes que `--tamano-grupo`.**
Más jobs son más IPs; grupos más grandes son más fuentes compitiendo por las
mismas dos lecturas buenas. Tené en cuenta el límite de jobs concurrentes de tu
plan de GitHub (20 en el plan gratuito, más en los pagos).

## Cómo saber si está funcionando

`data/estado_fuentes.json` trae un bloque `coverage`:

```json
{
  "fuentes_totales": 29,
  "con_datos_alguna_vez": 26,
  "nunca_vistas": ["fb_ejemplo"],
  "bloqueadas_en_la_ultima_corrida": ["fb_otra"],
  "con_fallos_persistentes": [],
  "horas_promedio_sin_datos": 4.2,
  "horas_maximo_sin_datos": 11.0
}
```

Cómo leerlo:

- **`horas_promedio_sin_datos` que crece corrida tras corrida** → hacen falta
  más IPs. Subí `--max-grupos`.
- **`nunca_vistas` que no se vacía** → esas fuentes nunca llegan a un turno
  bueno, o su URL está mal. Revisalas a mano.
- **`con_fallos_persistentes`** → no es bloqueo. La página se renombró, se
  borró o se volvió privada. Corregí o quitá esas entradas de `sources.yaml`.
- **`bloqueadas_en_la_ultima_corrida` con unas pocas** → es lo esperado y no hay
  nada que arreglar.

Y en `estado_fuentes.json`, cada fuente trae `rejected_samples`: si una fuente
devuelve publicaciones pero cero eventos, ahí se ve exactamente por qué se
descartó cada una.
