import json
from pathlib import Path

from tests.test_sicoob import OFX_SICOOB, PDF, pdf_bytes

FIXTURE = Path(__file__).parent / "fixtures" / "itau_sgml.ofx"


def _cat(client, eid, nome):
    return next(c for c in client.get(f"/api/entidades/{eid}/categorias").json() if c["nome"] == nome)


def _setup(client, eid, ofx=OFX_SICOOB):
    r = client.post(f"/api/entidades/{eid}/ofx/importar", files=[("arquivo", ("x.ofx", ofx, "application/x-ofx"))]).json()
    client.post(
        f"/api/entidades/{eid}/contas/{r['conta_id']}/complementar",
        files=[("arquivos", ("e.pdf", pdf_bytes(PDF), "application/pdf"))],
    )
    return {t["valor"]: t for t in client.get(f"/api/entidades/{eid}/transacoes").json()}


def test_regra_por_contraparte_categoriza_proximos(client, corretora, monkeypatch):
    monkeypatch.setattr("app.services.contrapartes.consultar", lambda _: (_ for _ in ()).throw(ValueError()))
    eid = corretora["id"]
    trns = _setup(client, eid)
    contab = _cat(client, eid, "Contabilidade")
    r = client.patch(f"/api/entidades/{eid}/transacoes/{trns['-700.00']['id']}", json={"categoria_id": contab["id"], "criar_regra": True})
    assert r.json()["categoria_origem"] == "manual"
    regras = client.get(f"/api/entidades/{eid}/regras").json()
    assert regras[0]["contraparte_id"] and regras[0]["padrao"] is None

    # Novo mês: mesmo CNPJ, descrição diferente → categorizado pela regra da contraparte
    novo = OFX_SICOOB.replace(b"20261110", b"20261210").replace(b"FITID>S1", b"FITID>S9").replace(b"-700.00", b"-650.00")
    client.post(f"/api/entidades/{eid}/ofx/importar", files=[("arquivo", ("y.ofx", novo, "application/x-ofx"))])
    t = next(t for t in client.get(f"/api/entidades/{eid}/transacoes").json() if t["valor"] == "-650.00")
    assert t["categoria_id"] == contab["id"] and t["categoria_origem"] == "regra"


def test_sugestao_por_descricao_parecida(client, corretora):
    eid = corretora["id"]
    base = f"/api/entidades/{eid}"
    client.post(f"{base}/ofx/importar", files=[("arquivo", ("x.ofx", FIXTURE.read_bytes(), "application/x-ofx"))])
    trns = client.get(f"{base}/transacoes").json()
    tarifas = [t for t in trns if "TARIFA" in t["descricao"]]
    tar = _cat(client, eid, "Tarifas bancárias")
    client.patch(f"{base}/transacoes/{tarifas[0]['id']}", json={"categoria_id": tar["id"]})

    sugs = client.get(f"{base}/categorizacao/sugestoes").json()
    s = next(s for s in sugs if s["transacao_id"] == tarifas[1]["id"])
    assert s["categoria_id"] == tar["id"] and s["confianca"] >= 0.45 and "tarifa" in s["motivo"]
    # Receita não recebe sugestão de despesa (sinal diferente)
    entrada = next(t for t in trns if t["valor"] == "4500.00")
    assert all(x["transacao_id"] != entrada["id"] for x in sugs)

    r = client.post(f"{base}/categorizacao/aplicar", json={"itens": [{"transacao_id": s["transacao_id"], "categoria_id": s["categoria_id"]}]})
    assert r.json() == {"alteradas": 1}


def _mcp(client, metodo, params=None, token="token-de-teste"):
    corpo = {"jsonrpc": "2.0", "id": 1, "method": metodo, "params": params or {}}
    return client.post(
        "/mcp",
        content=json.dumps(corpo),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Host": "localhost:8000",
        },
    )


def _ferramenta(client, nome, args):
    r = _mcp(client, "tools/call", {"name": nome, "arguments": args})
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert not res.get("isError"), res
    sc = res.get("structuredContent")
    if sc is not None:
        return sc.get("result", sc) if isinstance(sc, dict) else sc
    return json.loads(res["content"][0]["text"])


def test_mcp_claude_categoriza(client, corretora):
    assert _mcp(client, "tools/list", token="errado").status_code == 401
    init = _mcp(client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "teste", "version": "1"}})
    assert init.status_code == 200 and init.json()["result"]["serverInfo"]["name"] == "FinBPO"
    nomes = {t["name"] for t in _mcp(client, "tools/list").json()["result"]["tools"]}
    assert {"listar_entidades", "listar_categorias", "lancamentos_sem_categoria", "categorizar_lancamentos", "resumo_do_mes"} <= nomes

    eid = corretora["id"]
    client.post(f"/api/entidades/{eid}/ofx/importar", files=[("arquivo", ("x.ofx", FIXTURE.read_bytes(), "application/x-ofx"))])
    ents = _ferramenta(client, "listar_entidades", {})
    assert ents[0]["nome"] == "Corretora A"
    pend = _ferramenta(client, "lancamentos_sem_categoria", {"entidade_id": eid})
    assert len(pend) == 4
    saude = next(c for c in _ferramenta(client, "listar_categorias", {"entidade_id": eid}) if c["nome"] == "Comissão - Saúde")
    receita = next(p for p in pend if p["valor"] > 0)
    res = _ferramenta(client, "categorizar_lancamentos", {"entidade_id": eid, "itens": [{"transacao_id": receita["transacao_id"], "categoria_id": saude["id"]}]})
    assert res["categorizados"] == 1 and res["erros"] == []
    t = next(t for t in client.get(f"/api/entidades/{eid}/transacoes").json() if t["id"] == receita["transacao_id"])
    assert t["categoria_origem"] == "ia"
    resumo = _ferramenta(client, "resumo_do_mes", {"entidade_id": eid, "ano": 2026, "mes": 10})
    assert resumo["linhas"][0]["valor"] == 4500.0
