"""Fechamento mensal (dados, sugestões, PDF, análise do Claude) e alertas por e-mail."""

import hashlib
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.config import settings
from app.db import get_db
from app.main import app
from app.models import Categoria, ContaFinanceira, OrigemTransacao, StatusTitulo, TipoConta, TipoTitulo, Titulo, Transacao


def _db():
    return next(app.dependency_overrides[get_db]())


def _cenario(eid):
    db = _db()
    conta = ContaFinanceira(entidade_id=eid, tipo=TipoConta.CORRENTE, nome="Sicoob")
    db.add(conta)
    db.flush()
    cats = {c.nome: c for c in db.scalars(select(Categoria).where(Categoria.entidade_id == eid))}
    n = [0]

    def lanc(dia, valor, cat, desc="X"):
        n[0] += 1
        db.add(Transacao(conta_id=conta.id, data=dia, valor=Decimal(valor), descricao=desc, origem=OrigemTransacao.OFX,
                         hash=hashlib.sha256(f"{n[0]}".encode()).hexdigest(), categoria_id=cats[cat].id))

    for m in (7, 8, 9):  # histórico: sistemas ~R$ 300
        lanc(date(2026, m, 10), "-300", "Sistemas e softwares")
        lanc(date(2026, m, 5), "-1000", "Aluguel e condomínio")
    lanc(date(2026, 10, 10), "-900", "Sistemas e softwares")  # subiu 200%
    lanc(date(2026, 10, 5), "-1000", "Aluguel e condomínio")
    lanc(date(2026, 10, 7), "-120", "Tarifas bancárias")
    lanc(date(2026, 10, 15), "-80", "Juros e multas")
    lanc(date(2026, 10, 20), "5000", "Comissão - Auto")
    hoje = date.today()
    db.add(Titulo(entidade_id=eid, tipo=TipoTitulo.PAGAR, descricao="DAS 10/2026", valor=Decimal("4472.93"),
                  vencimento=hoje - timedelta(days=3), competencia=hoje.replace(day=1), status=StatusTitulo.ABERTO))
    db.add(Titulo(entidade_id=eid, tipo=TipoTitulo.PAGAR, descricao="ALUGUEL", valor=Decimal("1000"),
                  vencimento=hoje, competencia=hoje.replace(day=1), status=StatusTitulo.ABERTO))
    db.commit()
    db.close()


def test_fechamento_com_sugestoes_pdf_e_analise_do_claude(client, corretora):
    eid = corretora["id"]
    _cenario(eid)
    d = client.get(f"/api/entidades/{eid}/fechamento-mensal?ano=2026&mes=10").json()
    titulos = [s["titulo"] for s in d["sugestoes"]]
    assert "Sistemas e softwares subiu 200%" in titulos
    assert any("Juros" in t for t in titulos) and any("Tarifas" in t for t in titulos)
    desp = {x["categoria"]: x for x in d["despesas"]}
    assert Decimal(desp["Sistemas e softwares"]["media_3m"]) == 300 and desp["Sistemas e softwares"]["variacao_pct"] == 200

    from app.mcp_server import dados_fechamento, salvar_analise_fechamento

    assert dados_fechamento(eid, 2026, 10)["sugestoes"]
    assert salvar_analise_fechamento(eid, 2026, 10, "Outubro: cortar o sistema duplicado.")["ok"]
    pdf = client.get(f"/api/entidades/{eid}/fechamento-mensal/pdf?ano=2026&mes=10")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF" and pdf.headers["content-type"] == "application/pdf"
    assert client.get(f"/api/entidades/{eid}/fechamento-mensal?ano=2026&mes=10").json()["analise_ia"].startswith("Outubro")


def test_alerta_diario_por_email(client, corretora, monkeypatch):
    eid = corretora["id"]
    _cenario(eid)
    previa = client.get("/api/admin/alertas/previa").text
    assert "Contas em atraso" in previa and "DAS 10/2026" in previa and "Vencem hoje" in previa
    assert client.post("/api/admin/alertas/testar").status_code == 422  # sem SMTP configurado

    enviados = []

    class SMTPFalso:
        def __init__(self, host, porta, timeout):
            enviados.append(("conectou", host, porta))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            pass

        def login(self, u, s):
            enviados.append(("login", u))

        def send_message(self, msg):
            enviados.append(("msg", msg["Subject"], msg["To"], [p.get_filename() for p in msg.iter_attachments()]))

    import app.services.email_envio as em

    monkeypatch.setattr(em.smtplib, "SMTP", SMTPFalso)
    for k, v in {"smtp_host": "smtp.gmail.com", "smtp_usuario": "eu@gmail.com", "smtp_senha": "app-pass",
                 "alertas_destinatarios": "eu@gmail.com, socio@gmail.com", "alertas_hora": 0}.items():
        monkeypatch.setattr(settings, k, v)
    r = client.post("/api/admin/alertas/testar").json()
    assert r["resultado"] == "enviado"
    msg = [e for e in enviados if e[0] == "msg"][0]
    assert "1 conta(s) em atraso" in msg[1] and msg[2] == "eu@gmail.com, socio@gmail.com"

    # rotina automática: manda uma vez por dia
    from app.services import alertas

    db = _db()
    assert alertas.enviar_alerta_do_dia(db) == "enviado"
    assert alertas.enviar_alerta_do_dia(db) == "fora do horário ou já enviado hoje"
    r = client.post("/api/admin/fechamento/enviar?ano=2026&mes=10").json()
    assert r["resultado"] == "enviado"
    assert [e for e in enviados if e[0] == "msg"][-1][3][0].endswith("2026-10.pdf")
    db.close()


def test_leitor_sem_painel_nao_ve_fechamento(client, corretora):
    eid = corretora["id"]
    g = client.post("/api/admin/grupos", json={"nome": "Colab", "areas": ["comissoes"], "todas_entidades": True}).json()
    u = client.post("/api/admin/usuarios", json={"nome": "Colab", "email": "c@finbpo.dev", "senha": "Colaborador1", "papel": "leitor", "grupo_id": g["id"]})
    assert u.status_code == 201, u.text
    tok = client.post("/api/auth/login", data={"username": "c@finbpo.dev", "password": "Colaborador1"}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get(f"/api/entidades/{eid}/fechamento-mensal/pdf", headers=h).status_code == 403
    assert client.get("/api/admin/alertas/previa", headers=h).status_code == 403
