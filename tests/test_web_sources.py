import json
from bs4 import BeautifulSoup

from scraper.web_sources import _eventos_estructurados


def test_jsonld_event_conserva_datos_confiables_y_multimedia():
    dato = {
        "@context": "https://schema.org",
        "@type": "MusicEvent",
        "name": "Concierto Nacional",
        "startDate": "2026-09-05T20:00:00-04:00",
        "endDate": "2026-09-05T22:00:00-04:00",
        "url": "/evento/concierto-nacional",
        "description": "Una noche de música en vivo.",
        "image": ["/img/poster.jpg"],
        "location": {
            "@type": "Place",
            "name": "Teatro Municipal",
            "address": {
                "streetAddress": "Calle 1 #123",
                "addressLocality": "La Paz",
                "addressRegion": "La Paz",
            },
        },
        "organizer": {"@type": "Organization", "name": "Fundación Cultural"},
        "offers": {
            "@type": "Offer",
            "price": "80",
            "priceCurrency": "BOB",
            "url": "https://tickets.bo/concierto",
        },
        "video": {
            "@type": "VideoObject",
            "embedUrl": "https://www.youtube.com/embed/abc",
            "thumbnailUrl": "https://img.youtube.com/abc.jpg",
        },
    }
    html = f'<script type="application/ld+json">{json.dumps(dato)}</script>'
    source = {
        "id": "web_agenda", "name": "Agenda", "url": "https://agenda.bo/",
        "source_class": "ticketera", "tier": 1, "region": "La Paz", "city": "La Paz",
    }
    items = _eventos_estructurados(BeautifulSoup(html, "html.parser"), "https://agenda.bo/", source)
    assert len(items) == 1
    item = items[0]
    assert item.image_urls == ["https://agenda.bo/img/poster.jpg"]
    assert item.video_url == "https://www.youtube.com/embed/abc"
    assert item.video_thumbnail_url == "https://img.youtube.com/abc.jpg"
    assert item.structured_data["starts_at"] == "2026-09-05T20:00:00-04:00"
    assert item.structured_data["ends_at"] == "2026-09-05T22:00:00-04:00"
    assert item.structured_data["venue"] == "Teatro Municipal"
    assert item.structured_data["address"] == "Calle 1 #123, La Paz, La Paz"
    assert item.structured_data["organizer"] == "Fundación Cultural"
    assert item.structured_data["price_from"] == 80.0
    assert item.structured_data["price_to"] == 80.0
    assert item.structured_data["currency"] == "BOB"
    assert item.structured_data["ticket_urls"] == ["https://tickets.bo/concierto"]
