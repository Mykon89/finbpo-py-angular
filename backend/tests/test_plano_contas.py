from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "itau_sgml.ofx"


def test_crud_do_plano_de_contas(client, corretora):
    base = f"/api/entidades/{corretora['id']}"
    r = client.post(f"{base}/categorias", json={"nome": "  Seguros   da empresa ", "grupo_dre": "despesas_adm"})
    assert r.status_code == 201 and r.json()["nome"] == "Seguros da empresa" and r.json()["ativo"] is True
    cid = r.json()["id"]

    assert client.post(f"{base}/categorias", json={"nome": "seguros DA empresa", "grupo_dre": "custos"}).status_code == 409
    r = client.patch(f"{base}/categorias/{cid}", json={"nome": "Seguros", "grupo_dre": "custos"})
    assert r.json()["nome"] == "Seguros" and r.json()["grupo_dre"] == "custos"

    # sem uso: pode excluir
    assert client.delete(f"{base}/categorias/{cid}").status_code == 204
    assert all(c["id"] != cid for c in client.get(f"{base}/categorias").json())


def test_categoria_em_uso_so_desativa(client, corretora):
    base = f"/api/entidades/{corretora['id']}"
    client.post(f"{base}/ofx/importar", files=[("arquivo", ("x.ofx", FIXTURE.read_bytes(), "application/x-ofx"))])
    trn = client.get(f"{base}/transacoes").json()[0]
    cat = next(c for c in client.get(f"{base}/categorias").json() if c["nome"] == "Tarifas bancárias")
    client.patch(f"{base}/transacoes/{trn['id']}", json={"categoria_id": cat["id"]})

    lida = next(c for c in client.get(f"{base}/categorias").json() if c["id"] == cat["id"])
    assert lida["qtd_lancamentos"] == 1
    assert client.delete(f"{base}/categorias/{cat['id']}").status_code == 409

    assert client.patch(f"{base}/categorias/{cat['id']}", json={"ativo": False}).json()["ativo"] is False
    outro = client.get(f"{base}/transacoes").json()[1]
    r = client.patch(f"{base}/transacoes/{outro['id']}", json={"categoria_id": cat["id"]})
    assert r.status_code == 422  # desativada não aceita novos lançamentos
    # histórico preservado
    assert next(t for t in client.get(f"{base}/transacoes").json() if t["id"] == trn["id"])["categoria_id"] == cat["id"]
