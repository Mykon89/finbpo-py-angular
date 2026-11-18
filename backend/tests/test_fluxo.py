from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "itau_sgml.ofx"


def _categoria(client, ent_id, nome):
    cats = client.get(f"/api/entidades/{ent_id}/categorias").json()
    return next(c for c in cats if c["nome"] == nome)


def test_exige_autenticacao(client):
    client.headers.pop("Authorization")
    assert client.get("/api/entidades").status_code == 401


def test_plano_de_contas_criado(client, corretora):
    nomes = {c["nome"] for c in client.get(f"/api/entidades/{corretora['id']}/categorias").json()}
    assert "Comissão - Saúde" in nomes and "Repasse a produtores" in nomes


def test_parcelamento(client, corretora):
    r = client.post(
        f"/api/entidades/{corretora['id']}/titulos",
        json={"tipo": "pagar", "descricao": "Notebook", "valor": "500.00", "vencimento": "2026-01-31", "parcelas": 3},
    )
    assert r.status_code == 201
    assert [t["vencimento"] for t in r.json()] == ["2026-01-31", "2026-02-28", "2026-03-31"]


def test_importacao_conciliacao_e_dre(client, corretora):
    eid = corretora["id"]
    base = f"/api/entidades/{eid}"
    conta = client.post(f"{base}/contas", json={"tipo": "corrente", "nome": "Itaú", "numero": "56789-0"}).json()
    aluguel = _categoria(client, eid, "Aluguel e condomínio")
    saude = _categoria(client, eid, "Comissão - Saúde")
    tarifa = _categoria(client, eid, "Tarifas bancárias")

    client.post(f"{base}/regras", json={"padrao": "TARIFA", "categoria_id": tarifa["id"]})
    client.post(f"{base}/regras", json={"padrao": "SULAMERICA", "categoria_id": saude["id"]})
    titulo = client.post(
        f"{base}/titulos",
        json={
            "tipo": "pagar",
            "descricao": "Aluguel outubro",
            "valor": "1200.00",
            "vencimento": "2026-10-08",
            "categoria_id": aluguel["id"],
        },
    ).json()[0]

    arquivo = {"arquivo": ("extrato.ofx", FIXTURE.read_bytes(), "application/x-ofx")}
    r = client.post(f"{base}/contas/{conta['id']}/importar-ofx", files=arquivo)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["total_novas"] == 4
    assert res["categorizadas"] == 3
    assert res["conciliadas"] == 1

    # reimportar não duplica
    r2 = client.post(f"{base}/contas/{conta['id']}/importar-ofx", files=arquivo).json()
    assert r2["total_novas"] == 0 and r2["duplicadas"] == 4

    t = client.get(f"{base}/titulos/{titulo['id']}").json()
    assert t["status"] == "pago" and t["saldo"] == "0.00"

    contas = client.get(f"{base}/contas").json()
    assert contas[0]["saldo_atual"] == "3220.20"

    dre = client.get(f"{base}/relatorios/dre", params={"ano": 2026, "mes": 10}).json()
    assert dre["resultado_liquido"] == "3220.20"
    linhas = {l["rotulo"]: l["valor"] for l in dre["linhas"]}
    assert linhas["Receita bruta"] == "4500.00"
    assert linhas["(-) Despesas financeiras"] == "-79.80"


def test_ofx_de_outra_conta_e_rejeitado(client, corretora):
    base = f"/api/entidades/{corretora['id']}"
    conta = client.post(f"{base}/contas", json={"tipo": "corrente", "nome": "BB", "numero": "99999-9"}).json()
    r = client.post(
        f"{base}/contas/{conta['id']}/importar-ofx",
        files={"arquivo": ("x.ofx", FIXTURE.read_bytes(), "application/x-ofx")},
    )
    assert r.status_code == 422


def test_isolamento_entre_entidades(client, corretora):
    clinica = client.post("/api/entidades", json={"tipo": "PJ", "segmento": "clinica", "nome": "Clínica"}).json()
    t = client.post(
        f"/api/entidades/{corretora['id']}/titulos",
        json={"tipo": "receber", "descricao": "X", "valor": "10", "vencimento": "2026-10-01"},
    ).json()[0]
    assert client.get(f"/api/entidades/{clinica['id']}/titulos/{t['id']}").status_code == 404
