# Eventos Bolivia Nacional — Diseño

## Objetivo

Convertir el cron actual en un agregador nacional de eventos de Bolivia que priorice fuentes públicas oficiales y especializadas, mantenga Facebook como fuente secundaria de descubrimiento y entregue a la app datos ricos para cine, teatro, conciertos, ferias, cultura, talleres y otros eventos.

## Principios

- No eludir login, captcha ni controles de acceso de Facebook.
- Priorizar fuentes públicas estructuradas: agendas municipales, ticketeras, carteleras de cine y sitios institucionales.
- No inventar multimedia: foto/video sólo cuando exista en una fuente pública verificable.
- Mantener compatibilidad con el contrato JSON actual y ampliarlo de forma aditiva.
- Fusionar duplicados en vez de mostrar el mismo evento varias veces.
- Conservar historial y estados de cancelación/reprogramación.
- Cubrir los 9 departamentos y reportar huecos de cobertura.

## Arquitectura

### 1. Fuentes

Se mantienen `facebook_public` y `generic_web`. Se añaden lectores especializados seleccionados por `parser` dentro de una fuente web, sin crear un segundo pipeline de clasificación.

Parsers especializados iniciales:

- `santa_cruz_agenda`: agenda oficial de la Secretaría Municipal de Cultura y Turismo de Santa Cruz.
- `jiwaki`: agenda Jiwaki del GAMLP.
- `bolivia_com_cine`: cartelera de cine Bolivia.com, agrupada por película + cine + día con horarios y formatos.

Las demás webs siguen usando el lector genérico JSON-LD/HTML.

### 2. Modelo crudo estructurado

`RawItem` se amplía con `structured_data`, un diccionario opcional para transportar campos confiables obtenidos directamente del sitio: organizador, audiencia, edad, duración, horarios, formatos, dirección, recinto, precio, imágenes, coordenadas y otros metadatos.

### 3. Evento enriquecido

El evento final amplía el contrato con:

- `organizer`
- `audience`
- `age_restriction`
- `duration_minutes`
- `showtimes`
- `formats`
- `media` ampliado con galería y videos ya existentes
- `quality_score` y `is_featured`

Los campos se rellenan desde datos estructurados cuando existan; si no, quedan nulos/listas vacías.

### 4. Cine

Cada ficha representa una película en una sala y un día. `showtimes` contiene las funciones y `formats` resume 2D/3D/4D/XL/PLUS/etc. La primera función alimenta `starts_at` para ordenar la agenda. La descripción conserva todos los horarios para que el clasificador actual no descarte el registro.

### 5. Salida para la app

El payload agrega:

- `sections.today`
- `sections.tomorrow`
- `sections.this_weekend`
- `sections.free`
- `sections.featured`
- `coverage_by_department`
- `coverage_by_category`

La versión lite mantiene las claves existentes y agrega los campos necesarios para tarjetas ricas.

### 6. Calidad

`quality_score` favorece: fecha exacta, foto, video, recinto, ciudad, precio/entradas, fuente oficial y corroboración. `is_featured` se activa para eventos vigentes con calidad alta.

### 7. Cobertura

El catálogo de fuentes incorpora más fuentes web nacionales y regionales verificadas, incluyendo Santa Cruz Cultura, Bolivia.com Cine, Ministerio de Turismo y Culturas vigente, Municipio de Sucre y Gobernación del Beni. Las fuentes de noticias sólo aportan eventos futuros cuando el clasificador detecta fecha utilizable.

### 8. Pruebas

- Reloj inyectable en `runner.correr` para que las pruebas no dependan del día real.
- Fixtures HTML para cada scraper especializado sin depender de internet.
- Pruebas del contrato enriquecido, secciones, cobertura y catálogo de fuentes.
- Suite completa debe quedar verde.
