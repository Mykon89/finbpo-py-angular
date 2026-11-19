from app.config import settings
from tests.test_extratos_seguradoras import PORTO


def test_pasta_importa_uma_vez_e_ignora_o_resto(client, corretora, tmp_path, monkeypatch):
    eid = corretora["id"]
    monkeypatch.setattr(settings, "extratos_pasta", str(tmp_path))
    monkeypatch.setattr(settings, "extratos_entidade_id", None)
    sub = tmp_path / str(eid)
    sub.mkdir()
    (sub / "PORTO_EXTRATO_17-11-2026.do").write_bytes(PORTO.encode("cp1252"))
    (sub / "boleto.pdf").write_bytes(b"%PDF-1.4 nada")
    (sub / "baixando.pdf.crdownload").write_bytes(b"x")
    (tmp_path / "solto.txt").write_text("sem entidade padrão: fica de fora")

    st = client.post(f"/api/entidades/{eid}/pasta/varrer").json()
    sit = {a["nome"].replace("\\\\", "/"): a["situacao"] for a in st["arquivos"]}
    assert sit[f"{eid}/PORTO_EXTRATO_17-11-2026.do"] == "importado"
    assert sit[f"{eid}/boleto.pdf"] in ("ignorado", "erro")
    assert len(sit) == 2
    assert client.get(f"/api/entidades/{eid}/comissoes?mes=2026-11").json()

    (sub / "copia.do").write_bytes(PORTO.encode("cp1252"))  # mesmo conteúdo com outro nome: já processado
    st = client.post(f"/api/entidades/{eid}/pasta/varrer").json()
    assert len(st["arquivos"]) == 2

    monkeypatch.setattr(settings, "extratos_entidade_id", eid)
    st = client.post(f"/api/entidades/{eid}/pasta/varrer").json()
    assert any(a["nome"] == "solto.txt" and a["situacao"] == "ignorado" for a in st["arquivos"])
