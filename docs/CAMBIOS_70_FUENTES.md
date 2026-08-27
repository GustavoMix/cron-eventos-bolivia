# Cambios — versión 70 fuentes Facebook

## Catálogo

- 70 páginas públicas de Facebook.
- 23 fuentes web, incluyendo agendas oficiales, ticketeras y carteleras de cine.
- Cobertura de los 9 departamentos de Bolivia.
- Más municipios, gobernaciones, universidades, museos, centros culturales, ferias y sedes.

## Multimedia

- icono público de la fuente;
- afiche/foto principal;
- galería de imágenes públicas;
- permalink público para reels/videos;
- miniatura del video cuando está disponible;
- tipo de video (`facebook_reel` / `facebook_video`).

No se extraen streams MP4 internos o temporales.

## Filtros para la app

El bloque `filters` incorpora metadata y conteos listos para pintar:

- Cuándo: hoy / esta semana / este mes / todos.
- Tipo de evento.
- Departamento.
- Ciudad.
- Precio: gratis / con entrada / por confirmar.
- Multimedia: con foto / con video.
- Tags/temas.

## Robustez

- una fuente Facebook por job por defecto;
- 8 fuentes por ola por defecto;
- rotación automática de las fuentes postergadas;
- pausas conservadoras;
- corte del grupo ante bloqueo/login;
- historial persistente para no perder eventos vigentes;
- sin login, captcha, fingerprinting, proxy rotation ni evasión de controles.

## Compatibilidad

Se conserva `schema_version: 1.0` y los campos anteriores. Los filtros y datos de multimedia agregados son aditivos.

## Validación

La suite offline incluye 102 tests y valida además que el catálogo tenga exactamente 70 fuentes de Facebook, URLs/IDs únicos y presencia de los 9 departamentos.
