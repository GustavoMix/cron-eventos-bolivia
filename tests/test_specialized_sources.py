from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/La_Paz")
AHORA = datetime(2026, 8, 27, 9, 0, tzinfo=TZ)

SANTA_LISTADO = """
<html><body>
<a href="/eventos/b90ed849-5727-4824-939e-4691fc52d9b3">MAMMA MIA! El Musical</a>
<a href="/eventos/c2142a74-22dc-41b8-9755-dfdcc3bae297">1er Concierto</a>
<a href="/lugares">Lugares</a>
</body></html>
"""

SANTA_DETALLE = """
<html><head><meta property="og:image" content="https://ik.imagekit.io/poster-mamma.jpg"></head>
<body><main>
<h1>MAMMA MIA! El Musical</h1>
<p>vie, 28 de agosto, 19:30</p><p>sáb, 29 de agosto, 19:30</p><p>dom, 30 de agosto, 18:00</p>
<a href="/lugares/teatro">Teatro Casa Municipal de Cultura Raúl Otero Reiche</a>
<p>Calle Libertad, frente a la plaza principal</p>
<h2>Ingreso</h2><p>Ingreso con costo</p><p>100 Bs - 130 Bs</p>
<p>Público</p><p>Todo público</p><p>Edades</p><p>Todas las edades</p>
<h2>Sobre el evento</h2><p>Musical completo en dos actos con canto en vivo, actuación y danza.</p>
<h2>Organizador</h2><p>Fundación Coral y Orquestal ArteCanto</p>
<h2>Contacto</h2><p>60800616</p>
</main></body></html>
"""

JIWAKI_LISTADO = """
<html><body><main>
<article><a href="https://lapaz.bo/agendajiwaki/event/fitaz-2026/"><img src="https://lapaz.bo/fitaz.jpg">FITAZ 2026</a></article>
<article><a href="https://lapaz.bo/agendajiwaki/event/el-quita-penitas/">EL QUITA PENITAS</a></article>
<a href="https://lapaz.bo/agendajiwaki/event_listing_category/teatro/">Categoría teatro</a>
</main></body></html>
"""

JIWAKI_DETALLE = """
<html><head><meta property="og:image" content="https://lapaz.bo/fitaz-poster.jpg"></head><body><main>
<h1>FITAZ 2026</h1><p>2026-08-30 a las 19:30</p>
<p>Teatro Municipal Alberto Saavedra Pérez</p>
<p>Festival Internacional de Teatro de La Paz. Entradas disponibles.</p>
<iframe src="https://www.youtube.com/embed/abc123"></iframe>
</main></body></html>
"""

CINE_SALA = """
<html><body><main>
<h1>Multicine</h1><h2>La Paz</h2>
<a href="https://maps.google.com/?q=Av+Arce+2631">Av. Arce 2631</a>
<a href="/cine/la-paz/coyote-vs-acme-12215_41">Coyote vs. ACME</a>
<div>2D</div><ul><li>13:50 hrs</li><li>16:00 hrs</li></ul>
<div>2D PLUS</div><ul><li>20:00 hrs</li></ul>
<a href="/cine/la-paz/spider-man-un-nuevo-dia-12000_41">Spider Man: Un Nuevo Dia</a>
<div>2D XL</div><ul><li>13:20 hrs</li><li>16:10 hrs</li></ul>
<div>3D PLUS</div><ul><li>17:00 hrs</li></ul>
<h3>Lo último en Bolivia.com</h3>
<a href="/noticias/otra-cosa">Noticia</a>
</main></body></html>
"""


def _mod():
    try:
        from scraper import specialized_sources
    except ModuleNotFoundError as exc:
        raise AssertionError("falta scraper.specialized_sources") from exc
    return specialized_sources


def test_santa_cruz_descubre_solo_fichas_de_evento():
    m = _mod()
    links = m.descubrir_santa_cruz(SANTA_LISTADO, "https://culturayturismo.gmsantacruz.gob.bo/eventos")
    assert links == [
        "https://culturayturismo.gmsantacruz.gob.bo/eventos/b90ed849-5727-4824-939e-4691fc52d9b3",
        "https://culturayturismo.gmsantacruz.gob.bo/eventos/c2142a74-22dc-41b8-9755-dfdcc3bae297",
    ]


def test_santa_cruz_extrae_afiche_funciones_precio_lugar_y_organizador():
    m = _mod()
    source = {"id": "scz", "name": "Santa Cruz Cultura", "url": "https://culturayturismo.gmsantacruz.gob.bo/eventos", "source_class": "cultura_oficial", "tier": 1, "region": "Santa Cruz", "city": "Santa Cruz de la Sierra"}
    item = m.parsear_santa_cruz_detalle(SANTA_DETALLE, "https://culturayturismo.gmsantacruz.gob.bo/eventos/abc", source, AHORA)
    assert item.title == "MAMMA MIA! El Musical"
    assert item.image_urls == ["https://ik.imagekit.io/poster-mamma.jpg"]
    assert item.structured_data["organizer"] == "Fundación Coral y Orquestal ArteCanto"
    assert item.structured_data["audience"] == "Todo público"
    assert item.structured_data["age_restriction"] == "Todas las edades"
    assert item.structured_data["venue"].startswith("Teatro Casa Municipal")
    assert item.structured_data["price_from"] == 100.0
    assert item.structured_data["price_to"] == 130.0
    assert item.structured_data["showtimes"] == ["19:30", "19:30", "18:00"]
    assert len(item.structured_data["occurrences"]) == 3
    assert item.structured_data["occurrences"][1].startswith("2026-08-29T19:30")
    assert item.structured_data["starts_at"].startswith("2026-08-28T19:30")
    assert item.structured_data["phones"] == ["60800616"]


def test_jiwaki_descubre_eventos_y_extrae_video_publico():
    m = _mod()
    links = m.descubrir_jiwaki(JIWAKI_LISTADO, "https://lapaz.bo/agendajiwaki/")
    assert len(links) == 2
    source = {"id": "jiwaki", "name": "Jiwaki", "url": "https://lapaz.bo/agendajiwaki/", "source_class": "cultura_oficial", "tier": 1, "region": "La Paz", "city": "La Paz"}
    item = m.parsear_jiwaki_detalle(JIWAKI_DETALLE, links[0], source, AHORA)
    assert item.title == "FITAZ 2026"
    assert item.image_urls[0].endswith("fitaz-poster.jpg")
    assert item.video_url == "https://www.youtube.com/embed/abc123"
    assert item.video_type == "web_embed"
    assert item.structured_data["starts_at"].startswith("2026-08-30T19:30")
    assert item.structured_data["venue"] == "Teatro Municipal Alberto Saavedra Pérez"


def test_bolivia_com_cine_agrupa_pelicula_sala_dia_con_formatos_y_horarios():
    m = _mod()
    source = {"id": "cine_lp", "name": "Bolivia.com Cine La Paz", "url": "https://www.bolivia.com/cine/la-paz-c41", "source_class": "cartelera_cine", "tier": 2, "region": "La Paz", "city": "La Paz"}
    items = m.parsear_bolivia_com_sala(CINE_SALA, "https://www.bolivia.com/cine/multicine-la-paz-s180", source, AHORA)
    assert [i.title for i in items] == ["Coyote vs. ACME", "Spider Man: Un Nuevo Dia"]
    coyote = items[0]
    assert coyote.structured_data["venue"] == "Multicine"
    assert coyote.structured_data["address"] == "Av. Arce 2631"
    assert coyote.structured_data["showtimes"] == ["13:50", "16:00", "20:00"]
    assert coyote.structured_data["formats"] == ["2D", "2D PLUS"]
    assert coyote.structured_data["starts_at"].startswith("2026-08-27T13:50")
    assert "película" in coyote.text.lower()


CINE_DETALLE = """
<html><head>
<meta property="og:image" content="https://www.bolivia.com/posters/odisea.jpg">
</head><body><main>
<h1>La Odisea (The Odyssey)</h1>
<p>Género: Drama</p><p>Duración: 170 minutos</p><p>Clasificación: 12 Años</p>
<p>Director: Christopher Nolan</p>
<p>Actores: Matt Damon, Anne Hathaway, Tom Holland, Zendaya</p>
<iframe src="https://www.youtube.com/embed/trailer123"></iframe>
</main></body></html>
"""


def test_bolivia_com_reconoce_salas_con_sufijo_de_programacion():
    m = _mod()
    html = '<a href="/cine/cine-center-quillacollo-s235_02032025">Cine Center</a>'
    assert m.descubrir_salas_bolivia_com(html, "https://www.bolivia.com/cine/cartelera/quillacollo-c210") == [
        "https://www.bolivia.com/cine/cine-center-quillacollo-s235_02032025"
    ]


def test_detalle_de_pelicula_enriquece_ficha_con_genero_duracion_clasificacion_director_y_reparto():
    m = _mod()
    from scraper.models import RawItem
    item = RawItem(
        source_id="cine_lp", source_name="Bolivia.com Cine", source_url="https://www.bolivia.com/cine/",
        item_url="https://www.bolivia.com/cine/la-paz/la-odisea-12131_41", text="La Odisea\nPelícula en cartelera de cine",
        title="La Odisea", source_class="cartelera_cine", tier=2, structured_data={},
    )
    m._enriquecer_multimedia(item, CINE_DETALLE)
    assert item.image_urls == ["https://www.bolivia.com/posters/odisea.jpg"]
    assert item.video_url == "https://www.youtube.com/embed/trailer123"
    assert item.structured_data["content_genre"] == "Drama"
    assert item.structured_data["duration_minutes"] == 170
    assert item.structured_data["age_restriction"] == "12 Años"
    assert item.structured_data["director"] == "Christopher Nolan"
    assert item.structured_data["cast"] == ["Matt Damon", "Anne Hathaway", "Tom Holland", "Zendaya"]


def test_fuente_especializada_puede_subir_su_limite_sin_afectar_el_global():
    m = _mod()
    assert m._limite_items({"max_items": 80}, {"max_items_por_fuente": 20}) == 80
    assert m._limite_items({}, {"max_items_por_fuente": 20}) == 20
