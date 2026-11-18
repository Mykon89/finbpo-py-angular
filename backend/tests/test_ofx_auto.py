from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "itau_sgml.ofx"


def _arquivo():
    return {"arquivo": ("extrato.ofx", FIXTURE.read_bytes(), "application/x-ofx")}


def test_analisa_sem_conta_cadastrada(client, corretora):
    r = client.post(f"/api/entidades/{corretora['id']}/ofx/analisar", files=_arquivo())
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["banco_codigo"] == "341" and a["banco_nome"] == "Itaú"
    assert a["agencia"] == "1234" and a["numero"] == "56789-0"
    assert a["tipo"] == "corrente"
    assert a["conta_existente"] is None
    assert a["sugestao_nome"] == "Itaú Ag 1234 C/C 56789-0"
    assert a["sugestao_saldo_inicial"] == "0.00"
    assert a["total_transacoes"] == 4 and a["inicio"] == "2026-10-01"


def test_importa_criando_conta_e_reconhece_depois(client, corretora):
    base = f"/api/entidades/{corretora['id']}"
    r = client.post(f"{base}/ofx/importar", files=_arquivo(), data={"nome": "Itaú PJ"})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["conta_criada"] is True and res["conta_nome"] == "Itaú PJ" and res["total_novas"] == 4

    contas = client.get(f"{base}/contas").json()
    assert len(contas) == 1
    assert contas[0]["banco_codigo"] == "341" and contas[0]["agencia"] == "1234"
    assert contas[0]["saldo_atual"] == "3220.20"  # bate com o saldo do extrato

    a = client.post(f"{base}/ofx/analisar", files=_arquivo()).json()
    assert a["conta_existente"]["id"] == res["conta_id"]

    r2 = client.post(f"{base}/ofx/importar", files=_arquivo()).json()
    assert r2["conta_criada"] is False and r2["conta_id"] == res["conta_id"] and r2["duplicadas"] == 4
    assert len(client.get(f"{base}/contas").json()) == 1


def test_avisa_conta_de_outra_entidade(client, corretora):
    client.post(f"/api/entidades/{corretora['id']}/ofx/importar", files=_arquivo())
    clinica = client.post("/api/entidades", json={"tipo": "PJ", "segmento": "clinica", "nome": "Clínica"}).json()
    a = client.post(f"/api/entidades/{clinica['id']}/ofx/analisar", files=_arquivo()).json()
    assert a["conta_existente"] is None and a["outra_entidade"] == "Corretora A"


def test_saldo_inicial_informado(client, corretora):
    base = f"/api/entidades/{corretora['id']}"
    client.post(f"{base}/ofx/importar", files=_arquivo(), data={"saldo_inicial": "100.00"})
    assert client.get(f"{base}/contas").json()[0]["saldo_atual"] == "3320.20"
