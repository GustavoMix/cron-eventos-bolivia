"""Fotos: que el afiche gane y el logo del sitio no entre.

Los casos son URLs reales de las fuentes del catálogo (fbcdn, Drupal de un
diario, un CDN de ticketera), porque el módulo decide todo mirando la forma de
la URL y ahí las convenciones de cada sitio son lo único que importa.
"""

from scraper.imagenes import (
    clave,
    elegir,
    es_ruido,
    limpiar_galeria,
    normalizar,
    version_grande,
)

AFICHE_FB = (
    "https://scontent-lga3-1.xx.fbcdn.net/v/t39.30808-6/775471464_158026_n.jpg"
    "?stp=dst-jpg_tt6&_nc_cat=110&oh=00_AQHr8xdFRIGz&oe=6A8A323D"
)


def test_descarta_lo_que_no_es_una_foto():
    assert normalizar("https://sitio.bo/icono.svg") is None
    assert normalizar("https://sitio.bo/animado.gif") is None
    assert normalizar("data:image/png;base64,iVBORw0KGgo=") is None
    assert normalizar("/relativa/afiche.jpg") is None
    assert normalizar("") is None


def test_acepta_una_foto_normal_y_una_sin_extension():
    assert normalizar("https://sitio.bo/afiche.jpg")
    assert normalizar("https://cdn.sitio.bo/imagen/9f2a1c")


def test_el_logo_y_el_avatar_son_ruido():
    assert es_ruido("https://diario.bo/assets/logo-cabecera.png")
    assert es_ruido("https://sitio.bo/img/avatar-usuario.jpg")
    assert es_ruido("https://sitio.bo/pixel.png")
    assert es_ruido("https://sitio.bo/foto.jpg", alt="Logo del teatro")
    assert not es_ruido(AFICHE_FB)


def test_el_hash_del_cdn_no_convierte_el_afiche_en_ruido():
    # El query de un CDN firmado es un hash: tarde o temprano contiene
    # "banner" o "share" por azar y eso no puede descartar la foto.
    assert not es_ruido("https://scontent.xx.fbcdn.net/v/t39/afiche.jpg?oh=xxsharexx")


def test_sube_la_miniatura_de_drupal_a_la_original():
    chica = ("https://www.lostiempos.com/sites/default/files/styles/"
             "noticia_home_apertura/public/media_imagen/2026/8/20/afiche.jpg"
             "?itok=NlP7de9h")
    assert version_grande(chica) == (
        "https://www.lostiempos.com/sites/default/files/media_imagen/2026/8/20/afiche.jpg"
    )


def test_sube_la_miniatura_de_wordpress_a_la_original():
    assert version_grande("https://sitio.bo/wp-content/2026/afiche-1024x768.jpg") == (
        "https://sitio.bo/wp-content/2026/afiche.jpg"
    )


def test_no_se_toca_una_url_firmada():
    # Sacarle el query a un CDN firmado devuelve 403: la foto se rompe.
    assert version_grande(AFICHE_FB) == AFICHE_FB


def test_la_misma_foto_en_dos_tamanos_es_una_sola():
    assert clave("https://sitio.bo/fotos/kjarkas-teatro-acha-1024x768.jpg") == clave(
        "https://sitio.bo/fotos/kjarkas-teatro-acha.jpg"
    )


def test_gana_la_foto_grande_y_declarada_por_el_sitio():
    elegidas = elegir([
        {"url": "https://sitio.bo/galeria/chica.jpg", "width": 400, "height": 300,
         "origen": "articulo"},
        {"url": "https://sitio.bo/afiche-oficial.jpg", "origen": "og"},
    ])
    assert elegidas[0] == "https://sitio.bo/afiche-oficial.jpg"


def test_se_descarta_lo_que_mide_como_un_icono():
    elegidas = elegir([
        {"url": "https://sitio.bo/compartir.png", "width": 32, "height": 32},
        {"url": "https://sitio.bo/afiche.jpg", "width": 1080, "height": 1080},
    ])
    assert elegidas == ["https://sitio.bo/afiche.jpg"]


def test_una_tira_ancha_es_un_banner_y_pierde():
    elegidas = elegir([
        {"url": "https://sitio.bo/cabecera.jpg", "width": 1600, "height": 220,
         "origen": "articulo"},
        {"url": "https://sitio.bo/afiche.jpg", "width": 800, "height": 800,
         "origen": "articulo"},
    ])
    assert elegidas[0] == "https://sitio.bo/afiche.jpg"


def test_el_icono_de_la_fuente_nunca_entra_a_la_galeria():
    icono = "https://sitio.bo/media/identidad-de-la-pagina.jpg"
    assert elegir([{"url": icono, "width": 500, "height": 500}], icono_fuente=icono) == []


def test_la_galeria_conserva_el_orden_cuando_no_hay_mas_datos():
    urls = [
        "https://sitio.bo/primera-foto-del-evento.jpg",
        "https://sitio.bo/segunda-foto-del-evento.jpg",
    ]
    assert limpiar_galeria(urls) == urls


def test_la_galeria_saca_los_repetidos_y_el_ruido():
    galeria = limpiar_galeria([
        "https://sitio.bo/fotos/afiche-del-concierto.jpg",
        "https://sitio.bo/fotos/afiche-del-concierto-300x200.jpg",
        "https://sitio.bo/assets/logo.png",
    ])
    assert galeria == ["https://sitio.bo/fotos/afiche-del-concierto.jpg"]
