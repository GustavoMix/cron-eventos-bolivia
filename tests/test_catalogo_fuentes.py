from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_catalogo_tiene_70_fuentes_facebook_y_urls_unicas():
    cfg = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    fuentes = cfg["sources"]
    fb = [f for f in fuentes if f.get("type") == "facebook_public"]
    web = [f for f in fuentes if f.get("type") == "generic_web"]

    assert len(fb) == 70
    assert len(web) == 9
    assert len({f["id"] for f in fuentes}) == len(fuentes)
    assert len({f["url"] for f in fb}) == len(fb)


def test_catalogo_facebook_cubre_los_nueve_departamentos():
    cfg = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    fb = [f for f in cfg["sources"] if f.get("type") == "facebook_public"]
    regiones = {f.get("region") for f in fb}
    esperados = {
        "La Paz", "Cochabamba", "Santa Cruz", "Chuquisaca", "Oruro",
        "Potosí", "Tarija", "Beni", "Pando",
    }
    assert esperados <= regiones
