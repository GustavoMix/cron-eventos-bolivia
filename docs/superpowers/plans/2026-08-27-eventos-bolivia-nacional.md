# Eventos Bolivia Nacional Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ampliar el cron a un agregador nacional con scrapers especializados de cultura/cine, multimedia real, eventos enriquecidos y mejor salida para la app.

**Architecture:** Mantener un único pipeline `RawItem -> clasificador -> Evento -> merger -> salida`. Los scrapers especializados producen `RawItem` con `structured_data`, evitando duplicar lógica de clasificación y reconciliación. El JSON se amplía de forma aditiva.

**Tech Stack:** Python 3, httpx, BeautifulSoup4, PyYAML, pytest.

**Spec:** `docs/superpowers/specs/2026-08-27-eventos-bolivia-nacional-design.md`

## Global Constraints

- No eludir login, captcha ni controles de acceso.
- No inventar fotos ni videos.
- Mantener compatibilidad aditiva con el JSON existente.
- Cubrir los nueve departamentos mediante catálogo y diagnóstico.

---

### Task 1: Reloj determinista del pipeline

**Files:** `scraper/runner.py`, `tests/test_pipeline.py`

**Interfaces:** `correr(..., ahora: Optional[datetime] = None) -> int`.

- [ ] Escribir prueba que invoque `correr` con fecha fija y verifique `generated_at`/lifecycle.
- [ ] Ejecutar la prueba y comprobar que falla por parámetro inexistente.
- [ ] Implementar inyección de reloj sin cambiar el comportamiento por defecto.
- [ ] Actualizar helper E2E para usar fecha fija y ejecutar suite del pipeline.

### Task 2: Datos estructurados y contrato enriquecido

**Files:** `scraper/models.py`, `scraper/clasificador.py`, `scraper/merger.py`, `tests/test_merger.py`, `tests/test_pipeline.py`

**Interfaces:** `RawItem.structured_data: Dict[str, Any]`; Evento agrega `organizer`, `audience`, `age_restriction`, `duration_minutes`, `showtimes`, `formats`.

- [ ] Escribir pruebas de propagación/fusión de campos estructurados.
- [ ] Verificar RED.
- [ ] Implementar campos y precedencia estructurada.
- [ ] Verificar GREEN.

### Task 3: Scrapers especializados

**Files:** crear `scraper/specialized_sources.py`; modificar `scraper/web_sources.py`; crear `tests/test_specialized_sources.py`.

**Interfaces:** `leer_fuente_especializada(source, settings, html_loader=None) -> Optional[List[RawItem]]` y parsers puros por HTML.

- [ ] Escribir fixtures HTML y pruebas para Santa Cruz, Jiwaki y Bolivia.com Cine.
- [ ] Verificar RED.
- [ ] Implementar parsers y despacho por `source.parser`.
- [ ] Verificar GREEN y que el lector genérico siga funcionando.

### Task 4: Calidad, secciones y cobertura

**Files:** `scraper/salida.py`, `tests/test_pipeline.py`.

**Interfaces:** payload agrega `sections`, `coverage_by_department`, `coverage_by_category`; eventos agregan `quality_score`, `is_featured`.

- [ ] Escribir pruebas de secciones/quality/coverage.
- [ ] Verificar RED.
- [ ] Implementar cálculo determinista.
- [ ] Verificar GREEN.

### Task 5: Catálogo nacional de fuentes

**Files:** `config/sources.yaml`, `tests/test_catalogo_fuentes.py`, `docs/FUENTES.md`, `README.md`.

**Interfaces:** fuentes web pueden usar `parser` y se amplía la lista con fuentes públicas verificadas.

- [ ] Cambiar pruebas para exigir las fuentes nuevas y parsers esenciales.
- [ ] Verificar RED.
- [ ] Actualizar configuración y documentación.
- [ ] Verificar GREEN.

### Task 6: Verificación integral y paquete final

**Files:** toda la suite; ZIP de entrega.

- [ ] Ejecutar `python -m pytest -q`.
- [ ] Ejecutar compilación sintáctica con `python -m compileall scraper tests`.
- [ ] Generar ZIP limpio excluyendo `.git`, caches y artefactos temporales.
- [ ] Inspeccionar contenido del ZIP y reportar cambios y limitaciones reales de red.
