# Contrato JSON para la app Kotlin

## Los dos archivos

| Archivo | Para qué | Cuándo se lee |
|---|---|---|
| `data/eventos_bolivia_lite.json` | Pantalla de lista | Al abrir la app |
| `data/eventos_bolivia.json` | Pantalla de detalle | Al tocar un evento |

El liviano trae **solo los eventos vigentes** y **solo los campos de una
tarjeta**. Suele pesar menos de la décima parte del completo. La idea es que la
pantalla que se abre primero sea la que menos bytes necesita.

URLs crudas:

```
https://raw.githubusercontent.com/GustavoMix/cron-eventos-bolivia/main/data/eventos_bolivia_lite.json
https://raw.githubusercontent.com/GustavoMix/cron-eventos-bolivia/main/data/eventos_bolivia.json
```

Si el repositorio es privado, `raw.githubusercontent.com` devuelve 404 sin
autenticación. En ese caso hay dos caminos: hacerlo público (los datos son de
páginas públicas, no hay nada sensible), o servir el JSON desde tu backend.
Meter un token de GitHub dentro de la app no es una opción: cualquiera puede
extraerlo del APK.

## Principios del formato

Todo lo que sigue existe para que la app no tenga que calcular nada mientras
hace scroll:

1. **Las claves siempre están.** Un campo sin dato viaja como `null`, nunca
   ausente. En `kotlinx.serialization` un campo faltante y uno nulo no se
   deserializan igual, y eso rompe apps.
2. **Las listas nunca son `null`.** Vienen como `[]`. No hace falta
   `?: emptyList()` en ningún lado.
3. **Las fechas viajan dos veces**: en ISO-8601 con offset (`starts_at`) y en
   epoch milisegundos (`starts_at_ms`). Ordenar y filtrar por rango es comparar
   `Long`, sin parsear texto.
4. **Los textos de pantalla vienen escritos.** `display_date`, `price_label`,
   `category_label` y `lifecycle_label` ya están en español y listos para
   pintar. Agregar una categoría no obliga a publicar una versión nueva.
5. **Los filtros vienen contados.** El bloque `filters` trae las facetas con su
   conteo, así los chips se dibujan sin recorrer el catálogo.
6. **Las claves son `snake_case` en inglés**, igual que en el proyecto de
   tránsito, para que una misma app pueda compartir utilidades entre los dos.
   Los *valores* que ve el usuario están en español.

## Estructura

```jsonc
{
  "schema_version": "1.0",
  "generated_at": "2026-08-14T06:37:11-04:00",
  "timezone": "America/La_Paz",

  "summary": { "events_total": 128, "events_upcoming": 96, "events_today": 7, ... },

  "filters": {
    "ui_groups": [
      { "key": "when", "label": "Cuándo", "selection": "single", "icon": "calendar" },
      { "key": "categories", "label": "Tipo de evento", "selection": "multi", "icon": "category" },
      { "key": "departments", "label": "Departamento", "selection": "multi", "icon": "map" },
      { "key": "cities", "label": "Ciudad", "selection": "multi", "icon": "location_city" },
      { "key": "price", "label": "Precio", "selection": "single", "icon": "payments" },
      { "key": "media", "label": "Multimedia", "selection": "multi", "icon": "photo_library" },
      { "key": "tags", "label": "Temas", "selection": "multi", "icon": "sell" }
    ],
    "categories": [ { "key": "concierto", "label": "Conciertos", "count": 24 } ],
    "cities":     [ { "key": "Cochabamba", "label": "Cochabamba", "count": 31 } ],
    "departments":[ { "key": "Santa Cruz", "label": "Santa Cruz", "count": 44 } ],
    "when":       [ { "key": "hoy", "label": "Hoy", "count": 7 },
                    { "key": "esta_semana", "label": "Esta semana", "count": 22 },
                    { "key": "este_mes", "label": "Este mes", "count": 61 },
                    { "key": "todos", "label": "Todos", "count": 96 } ],
    "price":      [ { "key": "gratis", "label": "Gratis", "count": 18 },
                    { "key": "pagado", "label": "Con entrada", "count": 56 },
                    { "key": "por_confirmar", "label": "Precio por confirmar", "count": 22 } ],
    "media":      [ { "key": "con_foto", "label": "Con foto", "count": 82 },
                    { "key": "con_galeria", "label": "Con galería", "count": 41 },
                    { "key": "con_video", "label": "Con video", "count": 19 } ],
    "quality":    [ { "key": "excelente", "label": "Completo", "count": 38 },
                    { "key": "bueno", "label": "Bien documentado", "count": 31 },
                    { "key": "aceptable", "label": "Datos básicos", "count": 27 },
                    { "key": "incompleto", "label": "Faltan datos", "count": 0 } ],
    "tags":       [ { "key": "rock", "label": "rock", "count": 11 } ]
  },

  "policy": {            // ver "Entradas: dónde comprar, sin redirección"
    "purchase_links": false,
    "external_redirects": false,
    "note": "El catálogo informa dónde conseguir entradas, sin enlaces de compra ni redirecciones."
  },

  "quality": {           // cuántos eventos completos hay y qué es lo que más falta
    "by_tier": [ { "key": "excelente", "label": "Completo", "count": 38 } ],
    "average_score": 71.4,
    "most_missing": [ { "label": "Información de entradas", "count": 22 } ]
  },

  "coverage": { ... },   // salud del scraping, útil para diagnóstico
  "events":   [ ... ],
  "sources":  [ ... ]
}
```

Los conteos de `filters` se calculan **sobre los eventos vigentes**: un chip que
promete 40 conciertos y al tocarlo muestra 3 porque los otros 37 ya pasaron es
un chip roto.

Los rangos de `when` **se solapan a propósito**: un evento de mañana cuenta en
`esta_semana` y también en `este_mes`. Son atajos de navegación, no categorías
excluyentes.

## Campos de un evento

### Identidad

| Campo | Tipo | Notas |
|---|---|---|
| `event_id` | `String` | **Estable entre corridas.** Usalo para favoritos y notificaciones. |
| `title` | `String` | Título ya recortado y limpio. |
| `description` | `String` | Texto del anuncio, hasta 2500 caracteres. |
| `url` | `String` | Publicación de origen. |
| `facebook_event_url` | `String?` | Evento de Facebook, si el post enlazaba a uno. |

`event_id` se arma con el día, la ciudad, la sede, la categoría y las palabras
fuertes del título — no con la URL, que cambia según qué fuente lo publicó. Si
el mismo concierto aparece mañana anunciado por otra página, conserva su id.

### Cuándo

| Campo | Tipo | Notas |
|---|---|---|
| `starts_at` | `String?` | ISO-8601 con offset, ej. `2026-08-23T20:00:00-04:00`. |
| `starts_at_ms` | `Long?` | Epoch milisegundos. **Usá este para ordenar y filtrar.** |
| `ends_at` / `ends_at_ms` | `String?` / `Long?` | Solo en eventos de varios días. |
| `display_date` | `String?` | `"Domingo 23 de agosto · 20:00"`, `"Del 5 al 7 de septiembre"`. |
| `display_date_short` | `String?` | `"Dom 23 ago · 20:00"`. Para chips y tarjetas angostas. |
| `countdown_label` | `String?` | `"Hoy"`, `"Mañana"`, `"En 6 días"`, `"En curso"`, `"Fue ayer"`. |
| `date_detail` | `DateDetail` | La fecha entera desarmada. Ver abajo. |
| `all_day` | `Boolean` | `true` si el afiche no traía hora. |
| `multi_day` | `Boolean` | Festival o feria de varios días. |
| `doors_time` | `String?` | `"19:00"`. Hora de puertas, distinta de la del show. |
| `date_confidence` | `String` | `exacta` \| `aproximada` \| `relativa` \| `desconocida`. |
| `lifecycle` | `String` | `proximo` \| `hoy` \| `en_curso` \| `finalizado` \| `sin_fecha`. |
| `days_until` | `Int?` | `0` es hoy, negativo ya pasó. |
| `is_upcoming` | `Boolean` | Atajo de `lifecycle in (proximo, hoy, en_curso)`. |

`date_confidence` importa: `aproximada` significa que se conoce el día pero no
la hora, y `relativa` que la fecha se dedujo de un "este viernes" anclado a la
fecha de publicación. Si tu app manda notificaciones, conviene tratarlas
distinto que a una `exacta`.

`lifecycle`, `countdown_label`, `display_date` y `date_detail` **se recalculan
en cada corrida**, así que un evento archivado nunca queda mostrando "faltan 3
días" para siempre.

#### `date_detail`: la fecha ya desarmada

Existe para que la app no formatee ni una coma. Todas las claves están siempre;
las que no se saben van en `null`.

```jsonc
"date_detail": {
  "known": true,
  "weekday": "Domingo",        "weekday_short": "Dom",
  "day": 23,                   "month": 8,
  "month_label": "agosto",     "month_short": "ago",
  "year": 2026,

  "has_time": true,            "time_label": "20:00",
  "doors_label": "19:00",      // puertas, distinta de la del show

  "multi_day": false,          "days_count": 1,
  "end_day": null,             "end_month_label": null,
  "end_year": null,            "end_time_label": null,
  "range_label": null,         // "5 de septiembre — 7 de septiembre"

  "long_label": "Domingo 23 de agosto · 20:00",
  "short_label": "Dom 23 ago · 20:00",
  "countdown_label": "En 9 días",

  "confidence": "exacta",
  "confidence_label": "Fecha y hora confirmadas",
  "is_estimated": false,       // true si la fecha se dedujo de "este viernes"
  "source_text": "23 de agosto",
  "warnings": [],
  "timezone": "America/La_Paz"
}
```

El año aparece en `long_label` **solo cuando el evento no cae en el año en
curso**: escribirlo siempre alarga la tarjeta con un dato obvio, omitirlo
siempre hace que un festival de enero se lea como si fuera el mes que viene.

`countdown_label` se calcula en la zona horaria de Bolivia, no en la del
teléfono: alguien mirando la app desde España tiene que ver "Mañana" para un
evento que en La Paz es mañana.

### Dónde

`department`, `city`, `venue`, `address` — todos `String?`.

`location_query` es un texto listo para pasarle a Google Maps o al intent de
mapas de Android, ej. `"Teatro Achá, Cochabamba, Bolivia"`. No hay coordenadas
porque los afiches no las traen.

### Cuánto

| Campo | Tipo | Notas |
|---|---|---|
| `is_free` | `Boolean` | |
| `price_from` / `price_to` | `Double?` | Mínimo y máximo. Suele haber dos (preventa y puerta). |
| `currency` | `String?` | `"BOB"` o `null`. |
| `price_label` | `String?` | **Ya escrito**: `"Entrada libre"`, `"Bs 80"`, `"Bs 80 - 120"`. |
| `ticket_outlets` | `List<String>` | `["SuperTicket", "Farmacorp"]`. Nombres, no enlaces. |
| `ticket_info` | `TicketInfo` | Dónde se consiguen, en texto. Ver abajo. |
| `ticket_urls` | `List<String>` | **Siempre `[]`.** Ver la sección siguiente. |

### Entradas: dónde comprar, sin redirección

Este catálogo **no publica enlaces de compra**. Dice dónde se consiguen las
entradas —"en SuperTicket y Farmacorp", "en boletería del teatro"— y ahí
termina: no hay ninguna URL en el JSON que abra un checkout, ni en
`ticket_urls`, ni en `url`, ni en `all_urls`, ni dentro de `description`.

Es una decisión de producto: con un botón de compra la app deja de ser una
agenda y pasa a ser un intermediario de venta, con precios que cambian, enlaces
que caducan y responsabilidad sobre una transacción que nadie acá controla.

```jsonc
"ticket_info": {
  "is_free": false,
  "price_label": "Bs 80 - 120",
  "where_to_buy": ["SuperTicket", "Farmacorp"],
  "where_to_buy_label": "En SuperTicket y Farmacorp",
  "note": "Consultá precio y disponibilidad directamente en el punto de venta.",
  "contact_phones": ["70123456"],
  "purchase_links": false,
  "opens_external_checkout": false
}
```

`ticket_urls` se conserva vacía y no se elimina para no romper las apps que ya
la deserializan. Si el enlace principal del evento *era* la ficha de la
ticketera, `url` viaja en `null` y `has_source_link` en `false`: toda la
información —fecha, sede, precio, dónde se compra— ya está en el JSON, así que
lo único que se pierde es el redirect.

La regla se aplica también a lo que viene del historial: un evento guardado por
una corrida vieja se sanea antes de publicarse, así que el archivo de hoy
cumple la política de hoy. La implementación está entera en
`scraper/entradas.py`.

### Calidad: qué tan completo llegó el evento

`relevance_score` mide *confianza* (qué tan seguros estamos de que esto es un
evento real). `quality` mide *completitud*: cuánto de lo que la app necesita
pintar llegó de verdad. Un aviso oficial que solo dice "concierto el sábado"
tiene relevancia alta y calidad baja, y las dos cosas son ciertas.

```jsonc
"quality_score": 93,          // atajo plano, para ordenar
"quality_tier": "excelente",  // excelente | bueno | aceptable | incompleto
"quality": {
  "score": 93,
  "tier": "excelente",
  "label": "Completo",
  "publishable": true,
  "complete": true,
  "has_photo": true, "has_date": true, "has_time": true,
  "has_venue": true, "has_ticket_info": true,
  "missing": [],
  "checks": [ { "key": "foto", "label": "Foto del evento", "ok": true, "weight": 21 } ]
}
```

Los eventos que no llegan al mínimo (`summary.quality_min_score`, 42 por
defecto) **no se publican**, pero tampoco se borran: quedan en el historial y
entran en cuanto alguna fuente aporte el dato que les faltaba. El corte se
configura con `minimo_calidad` en `config/sources.yaml`.

Ordenar por `quality_score` dentro del mismo día es lo que hace que la lista
abra con los eventos que tienen afiche, hora y sede en vez de con los que solo
tienen un título.

### Fotos y videos

```jsonc
"image_url":  "https://...",          // la principal, para la tarjeta
"image_urls": ["https://...", ...],   // la galería completa
"has_image":  true,
"has_video":  false,
"videos": [
  {
    "url": "https://www.facebook.com/.../videos/123",
    "thumbnail_url": "https://...",
    "type": "facebook_video",          // o "facebook_reel", "web_video", "web_embed"
    "provider": "facebook",
    "use_official_embed": true,
    "source_id": "fb_teatro"
  }
],
"media": { "images": [...], "main_image_url": "...", "image_count": 3, "videos": [...] }
```

Los mismos datos van planos y agrupados a propósito: la tarjeta de la lista solo
necesita `image_url` y `has_video`, y el detalle necesita la galería. Duplicar
unos campos cuesta bytes; obligar a la app a recorrer `media.images` para pintar
una miniatura cuesta scroll trabado.

**`use_official_embed: true` significa que ese video se reproduce con el
reproductor incrustado de Facebook.** No existe una URL de archivo que le puedas
pasar a ExoPlayer: nunca se extraen streams internos. Abrilo en un WebView o
delegá en la app de Facebook.

### Estado y confianza

| Campo | Tipo | Notas |
|---|---|---|
| `status` | `String` | `programado` \| `cancelado` \| `postergado` \| `agotado`. |
| `confidence` | `Double` | 0 a 1. |
| `source_count` | `Int` | Cuántas fuentes lo anunciaron. **No baja** aunque hoy Facebook las haya bloqueado. |
| `corroborated` | `Boolean` | `source_count >= 2`. |
| `verification` | `String` | `una_fuente`, `confirmado_por_fuente_oficial`, … |
| `sources` | `List<Source>` | Con `name`, `tier`, `icon_url`, `post_url`. |
| `seen_this_run` | `Boolean` | `false` = viene del historial, hoy nadie lo republicó. |
| `last_confirmed_at` | `String` | Última vez que una fuente lo confirmó. |
| `history` | `List<HistoryEntry>` | Cambios de estado, fecha o precio. |
| `changed_this_run` | `List<String>` | `["estado:programado->cancelado"]`. Útil para notificar. |

**`seen_this_run: false` no es un problema.** Un evento se anuncia una vez y no
se vuelve a mencionar; lo normal es que la mayoría del catálogo tenga `false`.
Si querés mostrar frescura, usá `last_confirmed_at`.

Una cancelación gana sobre cualquier cantidad de anuncios que todavía no se
enteraron: si una sola fuente dice que se canceló, el evento sale `cancelado`.

## Data classes de Kotlin

Para la pantalla de lista, con `eventos_bolivia_lite.json`:

```kotlin
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class EventosLite(
    @SerialName("schema_version") val schemaVersion: String,
    @SerialName("generated_at") val generatedAt: String,
    val timezone: String,
    val summary: Resumen,
    val filters: Filtros,
    val events: List<EventoLite>,
)

@Serializable
data class Resumen(
    @SerialName("events_total") val total: Int = 0,
    @SerialName("events_today") val hoy: Int = 0,
    @SerialName("events_with_image") val conFoto: Int = 0,
    @SerialName("events_complete") val completos: Int = 0,
)

@Serializable
data class Politica(
    @SerialName("purchase_links") val enlacesDeCompra: Boolean = false,
    @SerialName("external_redirects") val redirecciones: Boolean = false,
    val note: String = "",
)

@Serializable
data class Filtros(
    @SerialName("ui_groups") val uiGroups: List<GrupoFiltro> = emptyList(),
    val categories: List<Faceta> = emptyList(),
    val cities: List<Faceta> = emptyList(),
    val departments: List<Faceta> = emptyList(),
    val `when`: List<Faceta> = emptyList(),
    val price: List<Faceta> = emptyList(),
    val media: List<Faceta> = emptyList(),
    val quality: List<Faceta> = emptyList(),
    val tags: List<Faceta> = emptyList(),
)

@Serializable
data class GrupoFiltro(
    val key: String,
    val label: String,
    val selection: String,
    val icon: String,
)

@Serializable
data class Faceta(val key: String, val label: String, val count: Int)

@Serializable
data class EventoLite(
    @SerialName("event_id") val id: String,
    val title: String,
    val category: String,
    @SerialName("category_label") val categoryLabel: String,

    @SerialName("starts_at") val startsAt: String? = null,
    @SerialName("starts_at_ms") val startsAtMs: Long? = null,
    @SerialName("ends_at_ms") val endsAtMs: Long? = null,
    @SerialName("multi_day") val multiDay: Boolean = false,
    @SerialName("display_date") val displayDate: String? = null,
    @SerialName("display_date_short") val displayDateShort: String? = null,
    @SerialName("countdown_label") val countdownLabel: String? = null,
    val lifecycle: String,
    @SerialName("lifecycle_label") val lifecycleLabel: String,
    @SerialName("days_until") val daysUntil: Int? = null,
    @SerialName("is_upcoming") val isUpcoming: Boolean = true,

    val city: String? = null,
    val department: String? = null,
    val venue: String? = null,

    @SerialName("image_url") val imageUrl: String? = null,
    @SerialName("has_image") val hasImage: Boolean = false,
    @SerialName("has_video") val hasVideo: Boolean = false,

    @SerialName("is_free") val isFree: Boolean = false,
    @SerialName("price_from") val priceFrom: Double? = null,
    val currency: String? = null,
    @SerialName("price_label") val priceLabel: String? = null,
    @SerialName("ticket_outlets") val ticketOutlets: List<String> = emptyList(),

    val status: String = "programado",
    @SerialName("source_count") val sourceCount: Int = 1,
    @SerialName("quality_score") val qualityScore: Int = 0,
    @SerialName("quality_tier") val qualityTier: String = "aceptable",
)
```

Para el detalle, con `eventos_bolivia.json`:

```kotlin
@Serializable
data class Evento(
    @SerialName("event_id") val id: String,
    val title: String,
    val description: String = "",
    val url: String,
    @SerialName("facebook_event_url") val facebookEventUrl: String? = null,

    val category: String,
    @SerialName("category_label") val categoryLabel: String,
    val subcategories: List<String> = emptyList(),
    val tags: List<String> = emptyList(),
    val artists: List<String> = emptyList(),

    @SerialName("starts_at") val startsAt: String? = null,
    @SerialName("starts_at_ms") val startsAtMs: Long? = null,
    @SerialName("ends_at") val endsAt: String? = null,
    @SerialName("ends_at_ms") val endsAtMs: Long? = null,
    @SerialName("display_date") val displayDate: String? = null,
    @SerialName("display_date_short") val displayDateShort: String? = null,
    @SerialName("countdown_label") val countdownLabel: String? = null,
    @SerialName("date_detail") val dateDetail: DetalleFecha = DetalleFecha(),
    @SerialName("all_day") val allDay: Boolean = true,
    @SerialName("multi_day") val multiDay: Boolean = false,
    @SerialName("doors_time") val doorsTime: String? = null,
    @SerialName("date_confidence") val dateConfidence: String = "desconocida",
    val lifecycle: String,
    @SerialName("days_until") val daysUntil: Int? = null,
    @SerialName("is_upcoming") val isUpcoming: Boolean = true,

    val department: String? = null,
    val city: String? = null,
    val venue: String? = null,
    val address: String? = null,
    @SerialName("location_query") val locationQuery: String? = null,

    @SerialName("is_free") val isFree: Boolean = false,
    @SerialName("price_from") val priceFrom: Double? = null,
    @SerialName("price_to") val priceTo: Double? = null,
    @SerialName("price_label") val priceLabel: String? = null,
    @SerialName("ticket_outlets") val ticketOutlets: List<String> = emptyList(),
    @SerialName("ticket_info") val ticketInfo: InfoEntradas = InfoEntradas(),
    val phones: List<String> = emptyList(),
    // `ticket_urls` viaja siempre vacía; no hace falta declararla.

    @SerialName("image_url") val imageUrl: String? = null,
    @SerialName("image_urls") val imageUrls: List<String> = emptyList(),
    @SerialName("has_image") val hasImage: Boolean = false,
    @SerialName("has_video") val hasVideo: Boolean = false,
    val videos: List<Video> = emptyList(),

    val status: String = "programado",
    val confidence: Double = 0.0,
    val quality: Calidad = Calidad(),
    @SerialName("quality_score") val qualityScore: Int = 0,
    @SerialName("quality_tier") val qualityTier: String = "aceptable",
    @SerialName("has_source_link") val hasSourceLink: Boolean = false,
    @SerialName("source_count") val sourceCount: Int = 1,
    val corroborated: Boolean = false,
    val verification: String = "una_fuente",
    val sources: List<Fuente> = emptyList(),

    @SerialName("seen_this_run") val seenThisRun: Boolean = false,
    @SerialName("last_confirmed_at") val lastConfirmedAt: String? = null,
    @SerialName("changed_this_run") val changedThisRun: List<String> = emptyList(),
)

@Serializable
data class DetalleFecha(
    val known: Boolean = false,
    val weekday: String? = null,
    @SerialName("weekday_short") val weekdayShort: String? = null,
    val day: Int? = null,
    @SerialName("month_label") val monthLabel: String? = null,
    @SerialName("month_short") val monthShort: String? = null,
    val year: Int? = null,
    @SerialName("has_time") val hasTime: Boolean = false,
    @SerialName("time_label") val timeLabel: String? = null,
    @SerialName("doors_label") val doorsLabel: String? = null,
    @SerialName("multi_day") val multiDay: Boolean = false,
    @SerialName("days_count") val daysCount: Int? = null,
    @SerialName("range_label") val rangeLabel: String? = null,
    @SerialName("long_label") val longLabel: String? = null,
    @SerialName("short_label") val shortLabel: String? = null,
    @SerialName("countdown_label") val countdownLabel: String? = null,
    val confidence: String = "desconocida",
    @SerialName("confidence_label") val confidenceLabel: String = "",
    @SerialName("is_estimated") val isEstimated: Boolean = true,
    val timezone: String = "America/La_Paz",
)

@Serializable
data class InfoEntradas(
    @SerialName("is_free") val isFree: Boolean = false,
    @SerialName("price_label") val priceLabel: String? = null,
    @SerialName("where_to_buy") val whereToBuy: List<String> = emptyList(),
    @SerialName("where_to_buy_label") val whereToBuyLabel: String? = null,
    val note: String = "",
    @SerialName("contact_phones") val contactPhones: List<String> = emptyList(),
    // Siempre false: el catálogo informa, no vende.
    @SerialName("purchase_links") val purchaseLinks: Boolean = false,
    @SerialName("opens_external_checkout") val opensCheckout: Boolean = false,
)

@Serializable
data class Calidad(
    val score: Int = 0,
    val tier: String = "aceptable",
    val label: String = "",
    val complete: Boolean = false,
    @SerialName("has_photo") val hasPhoto: Boolean = false,
    @SerialName("has_time") val hasTime: Boolean = false,
    @SerialName("has_venue") val hasVenue: Boolean = false,
    val missing: List<String> = emptyList(),
)

@Serializable
data class Video(
    val url: String,
    @SerialName("thumbnail_url") val thumbnailUrl: String? = null,
    val type: String? = null,
    val provider: String? = null,
    @SerialName("use_official_embed") val useOfficialEmbed: Boolean = false,
)

@Serializable
data class Fuente(
    val id: String,
    val name: String,
    val tier: Int = 3,
    @SerialName("icon_url") val iconUrl: String? = null,
    @SerialName("post_url") val postUrl: String? = null,
)
```

Configurá el `Json` para tolerar campos nuevos — así agregar un campo al scraper
no rompe las versiones ya instaladas:

```kotlin
val json = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
}
```

## Recetas

**Ordenar por proximidad** (los sin fecha al final):

```kotlin
events.sortedWith(compareBy(nullsLast()) { it.startsAtMs })
```

**Filtrar "esta semana"**:

```kotlin
val ahora = System.currentTimeMillis()
val enUnaSemana = ahora + 7L * 24 * 60 * 60 * 1000
events.filter { it.startsAtMs?.let { ms -> ms in ahora..enUnaSemana } == true }
```

**Notificar solo los cambios que importan**:

```kotlin
events.filter { it.changedThisRun.isNotEmpty() && it.id in favoritos }
```

**Abrir el mapa**:

```kotlin
val intent = Intent(Intent.ACTION_VIEW,
    Uri.parse("geo:0,0?q=" + Uri.encode(evento.locationQuery ?: evento.venue ?: ""))
)
```

**Mostrar primero los eventos completos**:

```kotlin
events.sortedWith(
    compareBy<EventoLite>(nullsLast()) { it.startsAtMs }.thenByDescending { it.qualityScore }
)
```

**Pintar dónde se consiguen las entradas** (no hay nada que abrir):

```kotlin
Text(evento.ticketInfo.whereToBuyLabel ?: evento.ticketInfo.note)
```

## Versionado

`schema_version` es `"1.1"`.

**1.0 → 1.1** es aditivo salvo en un punto, y con `ignoreUnknownKeys = true` una
app de 1.0 sigue funcionando:

- se suman `date_detail`, `display_date_short`, `countdown_label`, `quality`,
  `quality_score`, `quality_tier`, `ticket_info`, `has_source_link`, la faceta
  `filters.quality` y los bloques `policy` y `quality` del payload;
- `ticket_urls` sigue existiendo pero **viaja siempre vacía**. Es el único
  cambio de comportamiento: una app que pintaba un botón "Comprar" con ese
  campo ahora no lo pinta. Mostrá `ticket_info.where_to_buy_label` en su lugar.

Los cambios que agreguen campos no suben la versión mayor; si alguna vez se
quita o se renombra un campo, sube a `"2.0"` y este documento lo dirá.
