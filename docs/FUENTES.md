# Fuentes configuradas

Generado desde `config/sources.yaml`. Para agregar una fuente, editá
ese archivo: el planificador incorpora las de Facebook a la rotación
en la corrida siguiente, sin más pasos.

**29 páginas de Facebook** y **9 sitios web**.

## Facebook

Ordenadas por tier. El tier decide la prioridad en el reparto por IP:
las de tier 1 son las que se llevan una IP entera para ellas solas.

### Tier 1 — publican eventos como razón de ser

| Fuente | Tipo | Alcance | URL |
|---|---|---|---|
| SuperTicket Bolivia | Ticketera | Bolivia | `https://www.facebook.com/SuperTicketBol/` |
| Conciertos en Bolivia | Página de eventos | Bolivia | `https://www.facebook.com/ConciertosEnBolivia/` |
| Eventos Bolivia | Página de eventos | Bolivia | `https://www.facebook.com/EventosBoliviaOficial/` |
| Festivales & Eventos Bolivia | Página de eventos | Bolivia | `https://www.facebook.com/FestivalesEventosBolivia/` |
| Fexpocruz | Sede | Santa Cruz de la Sierra | `https://www.facebook.com/Fexpocruz/` |
| Teatro al Aire Libre Jaime Laredo | Sede | La Paz | `https://www.facebook.com/profile.php?id=386877428010579` |

### Tier 2 — cultura oficial, municipios y gobernaciones

| Fuente | Tipo | Alcance | URL |
|---|---|---|---|
| Gobierno Autónomo Municipal de La Paz | Municipio / gobernación | La Paz | `https://www.facebook.com/MunicipioLaPaz/` |
| Agencia Municipal de Noticias La Paz - AMUN | Cultura oficial | La Paz | `https://www.facebook.com/AMUNLaPaz/` |
| Gobierno Autónomo Municipal de El Alto | Municipio / gobernación | El Alto | `https://www.facebook.com/ElAltoAlcaldia/` |
| Gobierno Autónomo Departamental de La Paz | Municipio / gobernación | La Paz | `https://www.facebook.com/gobernaciondelapaz/` |
| Gobierno Autónomo Municipal de Cochabamba | Municipio / gobernación | Cochabamba | `https://www.facebook.com/gamcochabamba/` |
| Gobernación de Cochabamba | Municipio / gobernación | Cochabamba | `https://www.facebook.com/GobernacionDeCochabamba/` |
| Gobierno Autónomo Municipal de Santa Cruz de la Sierra | Municipio / gobernación | Santa Cruz de la Sierra | `https://www.facebook.com/gamscs/` |
| Gobernación de Santa Cruz | Municipio / gobernación | Santa Cruz | `https://www.facebook.com/GobSantaCruz/` |

### Tier 3 — medios generales

| Fuente | Tipo | Alcance | URL |
|---|---|---|---|
| Los Tiempos | Medio de comunicación | Cochabamba | `https://www.facebook.com/LosTiemposBolivia/` |
| Diario Opinión | Medio de comunicación | Cochabamba | `https://www.facebook.com/DiarioOpinion/` |
| EL DEBER | Medio de comunicación | Santa Cruz de la Sierra | `https://www.facebook.com/GrupoELDEBER/` |
| Red Uno de Bolivia | Medio de comunicación | Bolivia | `https://www.facebook.com/RedUnotv/` |
| UNITEL Bolivia | Medio de comunicación | Bolivia | `https://www.facebook.com/unitelbolivia/` |
| ATB Digital | Medio de comunicación | Bolivia | `https://www.facebook.com/ATBDigital/` |
| Noticias Bolivisión | Medio de comunicación | Bolivia | `https://www.facebook.com/NoticiasBolivision/` |
| Periódico Digital ERBOL | Medio de comunicación | La Paz | `https://www.facebook.com/ErbolDigital/` |
| El Diario Bolivia | Medio de comunicación | La Paz | `https://www.facebook.com/eldiario.bolivia/` |
| Radio Fides de Bolivia | Medio de comunicación | La Paz | `https://www.facebook.com/RadioFidesBolivia/` |
| Agencia de Noticias Fides - ANF | Medio de comunicación | Bolivia | `https://www.facebook.com/ANFidesBolivia/` |
| RTP Bolivia | Medio de comunicación | La Paz | `https://www.facebook.com/rtpbolivia/` |
| Abya Yala TV | Medio de comunicación | La Paz | `https://www.facebook.com/AbyaYalaTv/` |
| El Deber Radio | Medio de comunicación | Santa Cruz de la Sierra | `https://www.facebook.com/eldeberradio/` |
| Radio Fides Cochabamba | Medio de comunicación | Cochabamba | `https://www.facebook.com/radiofidescb/` |

## Web

No bloquean, se leen en paralelo y varias publican `schema.org/Event`,
que entrega fecha, sede y precio en campos separados — lo más confiable
que hay, porque no hay que interpretar nada.

| Sitio | Tipo | Alcance | URL |
|---|---|---|---|
| SuperTicket | Ticketera | Bolivia | `https://superticket.bo/` |
| TicketBO | Ticketera | Bolivia | `https://ticket.bo/` |
| Tu Entrada Bolivia | Ticketera | Bolivia | `https://tuentrada.com.bo/` |
| Passline Bolivia | Ticketera | Bolivia | `https://passlinebolivia.com/` |
| Agenda Jiwaki - GAMLP | Cultura oficial | La Paz | `https://agendajiwaki.lapaz.bo/buscar-eventos/` |
| Eventos culturales - GAM La Paz | Cultura oficial | La Paz | `https://lapaz.bo/eventos-culturales/` |
| Agenda Cultural Plurinacional - Ministerio de Culturas | Cultura oficial | Bolivia | `https://www.minculturas.gob.bo/agenda-cultural-plurinacional/` |
| Agenda Cultural - Los Tiempos | Medio de comunicación | Cochabamba | `https://www.lostiempos.com/servicios/agenda-cultural` |
| Fexpocruz | Sede | Santa Cruz de la Sierra | `https://www.fexpocruz.com.bo/` |

## Verificación

Las URLs se comprobaron al armar el catálogo, pero las páginas de Facebook se
renombran y se borran con el tiempo. La forma de detectarlo es
`data/estado_fuentes.json`: una fuente que acumula `con_fallos_persistentes`
—a diferencia de una simplemente `bloqueada`— casi siempre cambió de dirección
o dejó de existir.

## Agregar una fuente

```yaml
- id: fb_mi_fuente          # único; con prefijo fb_ o web_
  name: Nombre visible
  type: facebook_public     # o generic_web
  source_class: eventos     # ticketera | eventos | venue | cultura_oficial | municipio | media
  tier: 1                   # 1, 2 o 3
  url: https://www.facebook.com/mifuente/
  region: Cochabamba        # departamento, o Bolivia si es nacional
  city: Cochabamba          # o null
  # follow_links: true      # solo para generic_web
```

`source_class` y `tier` no son decorativos: multiplican el puntaje de prioridad
y por lo tanto deciden qué fuentes entran en cada ola y cuáles se llevan una IP
propia.

