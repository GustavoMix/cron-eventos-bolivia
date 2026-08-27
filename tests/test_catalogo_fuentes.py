from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_catalogo_tiene_70_fuentes_facebook_y_urls_unicas():
    cfg = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    fuentes = cfg["sources"]
    fb = [f for f in fuentes if f.get("type") == "facebook_public"]
    web = [f for f in fuentes if f.get("type") == "generic_web"]

    assert len(fb) == 70
    assert len(web) >= 20
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


def test_catalogo_incluye_fuentes_web_especializadas_y_actuales():
    cfg = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    por_id = {f["id"]: f for f in cfg["sources"]}

    assert por_id["web_scz_agenda"]["parser"] == "santa_cruz_agenda"
    assert por_id["web_agenda_jiwaki"]["parser"] == "jiwaki"
    assert por_id["web_agenda_jiwaki"]["url"].startswith("https://lapaz.bo/agendajiwaki/")

    ciudades_cine = {
        "web_cine_lapaz": ("La Paz", "La Paz"),
        "web_cine_el_alto": ("La Paz", "El Alto"),
        "web_cine_cochabamba": ("Cochabamba", "Cochabamba"),
        "web_cine_quillacollo": ("Cochabamba", "Quillacollo"),
        "web_cine_santa_cruz": ("Santa Cruz", "Santa Cruz de la Sierra"),
        "web_cine_sucre": ("Chuquisaca", "Sucre"),
        "web_cine_tarija": ("Tarija", "Tarija"),
    }
    for source_id, (region, ciudad) in ciudades_cine.items():
        fuente = por_id[source_id]
        assert fuente["parser"] == "bolivia_com_cine"
        assert fuente["source_class"] == "cartelera_cine"
        assert fuente["region"] == region
        assert fuente["city"] == ciudad

    # El ministerio viejo dejó de ser la URL canónica; el cron debe apuntar a
    # la cartera vigente y conservar fuentes oficiales extra en regiones donde
    # Facebook puede no aportar nada durante una corrida.
    assert "turismoyculturas.gob.bo" in por_id["web_turismo_culturas"]["url"]
    for source_id in ["web_beni_cultura", "web_potosi_municipio", "web_tarija_gob", "web_uto_cultura", "web_sucre_municipio"]:
        assert source_id in por_id
