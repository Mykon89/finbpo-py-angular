"""Grupos de acesso (somente leitura), auditoria, CPF cifrado, direitos do titular e Central de decisões."""

import json
from pathlib import Path

from sqlalchemy import text

from app.db import get_db
from app.main import app
from tests.test_extratos_seguradoras import PORTO
from tests.test_fechamento_previsao import _sulamerica

OFX = (Path(__file__).parent / "fixtures" / "itau_sgml.ofx").read_bytes()


def _db():
    return next(app.dependency_overrides[get_db]())


def _login(client, email, senha):
    tok = client.post("/api/auth/login", data={"username": email, "password": senha}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _leitor(client, eid, areas, todas=False):
    g = client.post("/api/admin/grupos", json={"nome": "Diretoria", "areas": areas, "todas_entidades": todas,
                                               "entidades": [] if todas else [eid]}).json()
    u = client.post("/api/admin/usuarios", json={"nome": "Diretor", "email": "dir@finbpo.dev", "senha": "Diretoria2026",
                                                 "papel": "leitor", "grupo_id": g["id"]})
    assert u.status_code == 201, u.text
    return _login(client, "dir@finbpo.dev", "Diretoria2026")


def test_leitor_so_ve_o_liberado_e_nao_altera(client, corretora):
    eid = corretora["id"]
    outra = client.post("/api/entidades", json={"tipo": "PJ", "segmento": "clinica", "nome": "Clínica"}).json()["id"]
    fraca = client.post("/api/admin/usuarios", json={"nome": "X", "email": "x@finbpo.dev", "senha": "curta", "papel": "admin"})
    assert fraca.status_code == 422
    h = _leitor(client, eid, ["comissoes", "previsao"])

    eu = client.get("/api/auth/eu", headers=h).json()
    assert eu["somente_leitura"] and eu["areas"] == ["comissoes", "previsao"] and eu["grupo"] == "Diretoria"
    assert [e["id"] for e in client.get("/api/entidades", headers=h).json()] == [eid]  # só a empresa liberada
    assert client.get(f"/api/entidades/{eid}/comissoes", headers=h).status_code == 200
    assert client.get(f"/api/entidades/{eid}/comissoes/previsao", headers=h).status_code == 200
    assert client.get(f"/api/entidades/{eid}/titulos?tipo=pagar", headers=h).status_code == 403  # área não liberada
    assert client.get(f"/api/entidades/{outra}/comissoes", headers=h).status_code == 403  # empresa não liberada
    r = client.post(f"/api/entidades/{eid}/extratos-comissao/importar", headers=h, files=[("arquivos", ("p.do", b"x"))])
    assert r.status_code == 403 and "consulta" in r.json()["detail"]
    assert client.patch(f"/api/entidades/{eid}", headers=h, json={"nome": "hack"}).status_code == 403
    assert client.get("/api/admin/usuarios", headers=h).status_code == 403
    assert client.post("/api/auth/usuarios", headers=h, json={"nome": "a", "email": "a@b.dev", "senha": "12345678"}).status_code == 403

    # auditoria: login, leituras do leitor e a tentativa negada
    ev = client.get("/api/admin/auditoria").json()
    acoes = {(e["acao"], e["caminho"], e["status"]) for e in ev}
    assert ("login", "/api/auth/login", 200) in acoes
    assert ("leitura", f"/api/entidades/{eid}/comissoes", 200) in acoes
    assert ("criacao", f"/api/entidades/{eid}/extratos-comissao/importar", 403) in acoes
    assert all("busca" not in e["caminho"] for e in ev)


def test_cpf_cifrado_e_direitos_do_titular(client):
    pf = client.post("/api/entidades", json={"tipo": "PF", "segmento": "pf", "nome": "Fulano", "documento": "529.982.247-25"})
    assert pf.status_code == 201 and pf.json()["documento"] == "52998224725"
    db = _db()
    bruto = db.execute(text("SELECT documento FROM entidade WHERE id = :i"), {"i": pf.json()["id"]}).scalar()
    assert bruto.startswith("c1:") and "52998224725" not in bruto  # em repouso, cifrado
    dup = client.post("/api/entidades", json={"tipo": "PF", "segmento": "pf", "nome": "B", "documento": "52998224725"})
    assert dup.status_code == 409  # busca por igualdade continua funcionando

    eid = pf.json()["id"]
    db.execute(text("INSERT INTO contraparte (entidade_id, nome, documento) VALUES (:e, 'MARIA DA SILVA', :d)"),
               {"e": eid, "d": __import__("app.cripto", fromlist=["cifrar"]).cifrar("11144477735")})
    db.commit()
    achado = client.get("/api/admin/privacidade/titular?busca=111.444.777-35").json()
    assert achado["ocorrencias"]["contrapartes"] == 1 and achado["amostra"]["contrapartes"][0]["nome"] == "MARIA DA SILVA"
    exp = client.get("/api/admin/privacidade/titular/exportar?busca=MARIA DA SILVA").json()
    assert exp["dados"]["contrapartes"][0]["documento"] == "11144477735"
    assert client.post("/api/admin/privacidade/titular/anonimizar", json={"busca": "MARIA DA SILVA"}).status_code == 422
    r = client.post("/api/admin/privacidade/titular/anonimizar", json={"busca": "MARIA DA SILVA", "confirmar": True}).json()
    assert r["registros_anonimizados"] == 1
    assert client.get("/api/admin/privacidade/titular?busca=11144477735").json()["ocorrencias"]["contrapartes"] == 0


def test_mcp_mascara_pessoa_fisica(client, corretora):
    from app.mcp_server import _protegido
    from app.models import Transacao

    t = Transacao(descricao="PIX MARIA DA SILVA 111.444.777-35", contraparte_nome="MARIA DA SILVA", contraparte_documento="11144477735")
    p = _protegido(t)
    assert p["contraparte"] == "M. D. S." and p["contraparte_documento"] == "***.444.777-**"
    assert "MARIA" not in p["descricao"] and "111.444.777-35" not in p["descricao"] and p["pessoa_fisica"]
    emp = _protegido(Transacao(descricao="PIX EMPRESA X", contraparte_nome="EMPRESA X LTDA", contraparte_documento="64927828000172"))
    assert emp["contraparte"] == "EMPRESA X LTDA" and emp["contraparte_documento"] == "64927828000172"


def _responder(client, eid, tipo, opcao, contem="", **kw):
    ps = [p for p in client.get(f"/api/entidades/{eid}/pendencias").json() if p["tipo"] == tipo and contem in p["titulo"]]
    assert ps, f"sem pendência {tipo}"
    r = client.post(f"/api/entidades/{eid}/pendencias/{ps[0]['id']}/responder", json={"opcao": opcao, **kw})
    assert r.status_code == 200, r.text
    return ps[0], r.json()


def test_vinculo_pergunta_uma_vez_e_aprende(client, corretora):
    eid = corretora["id"]
    imp = lambda conteudo: client.post(f"/api/entidades/{eid}/extratos-comissao/importar",  # noqa: E731
                                       files=[("arquivos", ("p.do", conteudo.encode("cp1252")))]).json()
    imp(PORTO)
    p, _ = _responder(client, eid, "vinculo", "informar", contem="FULANO", valores={"origem": "Kette", "produtor": "Giovanna"}, sempre=True)
    assert "FULANO DE TAL" in p["titulo"]
    com = {c["cliente"]: c for c in client.get(f"/api/entidades/{eid}/comissoes?mes=2026-11").json()}
    assert (com["FULANO DE TAL"]["origem"], com["FULANO DE TAL"]["produtor"]) == ("KETTE", "GIOVANNA")
    assert "SEM VÍNCULO" not in (com["FULANO DE TAL"]["observacao"] or "")

    # outro extrato do mesmo cliente: resolvido sozinho pela regra aprendida, sem nova pergunta
    outro = PORTO.replace("Pagamento:</td><td>123", "Pagamento:</td><td>124").replace("17/11/2026", "18/11/2026")
    r = imp(outro)
    assert "FULANO DE TAL (111222)" not in r[0]["sem_vinculo"]
    abertas = [p for p in client.get(f"/api/entidades/{eid}/pendencias").json() if p["tipo"] == "vinculo"]
    assert all("FULANO" not in p["titulo"] for p in abertas)

    aprendido = client.get(f"/api/entidades/{eid}/aprendizado").json()
    assert any(a["tipo"] == "Comissão sem origem/produtor/parceiro" and "FULANO" in a["descricao"] for a in aprendido)
    res = client.get(f"/api/entidades/{eid}/pendencias/resumo").json()
    assert res["perguntas_no_mes"] >= 1 and "automatico_pct" in res


def test_ofx_gera_perguntas_e_concilia_comissao(client, corretora):
    eid = corretora["id"]
    # extrato da SulAmérica com líquido R$ 4.500,00 (crédito do OFX em 05/10)
    r = client.post(f"/api/entidades/{eid}/extratos-comissao/importar",
                    files=[("arquivos", ("s.txt", _sulamerica("36900001", "03/10/2026", [("EMPRESA X", "304494600", 1, 4500)])))]).json()
    assert r[0]["gravadas"] == 1
    imp = client.post(f"/api/entidades/{eid}/ofx/importar", files={"arquivo": ("e.ofx", OFX)}).json()
    assert imp["total_novas"] > 0
    ext = client.get(f"/api/entidades/{eid}/extratos-comissao").json()[0]
    assert ext["situacao"] == "RECEBIDO" and ext["recebido_em"] == "2026-10-05"  # crédito casado com o extrato

    cats = {c["nome"]: c["id"] for c in client.get(f"/api/entidades/{eid}/categorias").json()}
    p, _ = _responder(client, eid, "categoria", "outra", contem="TARIFA", valores={"categoria_id": cats["Tarifas bancárias"]}, sempre=True)
    assert "TARIFA" in p["titulo"]
    lanc = [t for t in client.get(f"/api/entidades/{eid}/transacoes").json() if "TARIFA" in t["descricao"]]
    assert lanc and all(t["categoria_id"] == cats["Tarifas bancárias"] for t in lanc)
    regras = client.get(f"/api/entidades/{eid}/regras").json()
    assert any((r["padrao"] or "").upper().startswith("TARIFA") for r in regras)  # próximas tarifas: automático


def test_pasta_importa_ofx_e_pergunta_arquivo_desconhecido(client, corretora, tmp_path, monkeypatch):
    from app.config import settings

    eid = corretora["id"]
    monkeypatch.setattr(settings, "extratos_pasta", str(tmp_path))
    monkeypatch.setattr(settings, "extratos_entidade_id", eid)
    (tmp_path / "extrato_sicoob.ofx").write_bytes(OFX)
    (tmp_path / "boleto_123.pdf").write_bytes(b"%PDF-1.4 nada")
    st = client.post(f"/api/entidades/{eid}/pasta/varrer").json()
    sit = {a["nome"]: a for a in st["arquivos"]}
    assert sit["extrato_sicoob.ofx"]["situacao"] == "importado" and "conta criada" in sit["extrato_sicoob.ofx"]["extratos"]
    con = client.get(f"/api/entidades/{eid}/conexoes-bancarias").json()
    assert con[0]["provedor"] == "ofx_pasta" and con[0]["lido_ate"] == "2026-10-31"
    _responder(client, eid, "arquivo", "ignorar")
    (tmp_path / "boleto_456.pdf").write_bytes(b"%PDF-1.4 outro")
    client.post(f"/api/entidades/{eid}/pasta/varrer")
    assert not [p for p in client.get(f"/api/entidades/{eid}/pendencias").json() if p["tipo"] == "arquivo"]  # aprendeu
    assert json.dumps(st)  # serializável
