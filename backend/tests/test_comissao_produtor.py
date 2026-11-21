"""Comissão das produtoras: nível pela meta, indicações via FECHAMENTO, saúde, conta a pagar e "Minha comissão"."""

import hashlib
import io
from datetime import date
from decimal import Decimal

import openpyxl
from sqlalchemy import select

from app.db import get_db
from app.main import app
from app.models import (
    Categoria, Comissao, Contraparte, GrupoDRE, MetaComissao, PlanoComissao, PropostaFechamento, StatusTitulo, TipoTitulo, Titulo,
)
from app.services import alertas
from app.services import comissao_produtor as cp

FAIXAS = [10000, 20000, 30000, 40000, 50000]


def _db():
    return next(app.dependency_overrides[get_db]())


def _com(db, eid, dia, cliente, bruta, produtor="GIOVANNA", ramo="AUTO", parceiro=None, seg="PORTO"):
    db.add(Comissao(entidade_id=eid, data=dia, seguradora=seg, ramo=ramo, cliente=cliente, bruta=Decimal(bruta), liquida=Decimal(bruta),
                    produtor=produtor, parceiro=parceiro, hash=hashlib.sha256(f"{cliente}{bruta}{dia}".encode()).hexdigest()))


def _fech(db, eid, cliente, premio, produtor="GIOVANNA", parceiro=None, ramo="AUTO", seg="PORTO", linha=1):
    db.add(PropostaFechamento(entidade_id=eid, ano=2026, mes=10, aba="OUT", linha=linha, seguradora=seg, ramo=ramo, cliente=cliente,
                              produtor=produtor, parceiro=parceiro, premio=Decimal(premio), emissao="EMITIDA"))


def _cenario(eid):
    db = _db()
    kette = Contraparte(entidade_id=eid, nome="GIOVANNA BEATRIZ MOREIRA RAMIREZ")
    db.add(kette)
    db.flush()
    p = PlanoComissao(entidade_id=eid, produtor="GIOVANNA", nome="GIOVANNA", niveis=cp.NIVEIS_PADRAO, regras=cp.REGRAS_PADRAO,
                      aliases_indicacao=["GIOVANNA"], excluir_ramos=[], contraparte_id=kette.id, meses_para_pagar=1)
    db.add(p)
    db.flush()
    db.add(MetaComissao(plano_id=p.id, ano=2026, mes=10, tipo="patrimonial", faixas=FAIXAS))
    _com(db, eid, date(2026, 10, 5), "JOAO DA SILVA", "1000")
    _com(db, eid, date(2026, 10, 6), "MARIA SOUZA", "500")
    _com(db, eid, date(2026, 10, 7), "MARIA SOUZA", "-100")         # estorno no mesmo mês
    _com(db, eid, date(2026, 10, 8), "CARLOS LIMA", "300", produtor="KETTE")  # indicação dela via FECHAMENTO
    _fech(db, eid, "JOAO DA SILVA", "15000", linha=1)
    _fech(db, eid, "MARIA SOUZA", "10000", linha=2)
    _fech(db, eid, "CARLOS LIMA", "5000", produtor="KETTE", parceiro="GIOVANNA", linha=3)
    db.commit()
    return db, p


def test_nivel_e_faixas():
    assert cp.nivel(Decimal("10000"), FAIXAS) == 0
    assert cp.nivel(Decimal("25000"), FAIXAS) == 1 and cp.nivel(Decimal("35000"), FAIXAS) == 2
    assert cp.nivel(Decimal("45000"), FAIXAS) == 3 and cp.nivel(Decimal("60000"), FAIXAS) == 4
    assert cp.nivel(Decimal("1"), None) is None


def test_apuracao_com_indicacao_e_estorno(client, corretora):
    db, p = _cenario(corretora["id"])
    a = cp.apurar(db, p, 2026, 10)
    pt = a["patrimonial"]
    assert pt["pl"] == Decimal("25000") and pt["nivel"] == "BRONZE" and pt["pct"] == Decimal("0.08")
    assert pt["base"] == Decimal("1400") and pt["estornos"] == Decimal("-100") and pt["valor"] == Decimal("112.00")
    assert a["indicacoes"]["bruto"] == Decimal("300") and a["indicacoes"]["valor"] == Decimal("49.20")  # (300-18%)×20%
    assert a["total"] == Decimal("161.20") and not a["meta_pendente"]
    assert pt["falta"] == Decimal("5000")
    s = cp.simular(db, p, 2026, 10, Decimal("6000"), Decimal("0"))
    assert s["simulado"]["nivel"] == "PRATA" and s["ganho"] == Decimal("28.00")


def test_meta_faltando_nao_gera_e_avisa_no_email(client, corretora):
    db, p = _cenario(corretora["id"])
    assert cp.gerar_conta(db, p, 2026, 11)["situacao"] == "meta não cadastrada"
    assert cp.metas_faltando(db, date(2026, 11, 2)) == ["GIOVANNA (patrimonial)"]
    a = alertas.montar(db, date(2026, 11, 2))
    _, corpo, texto = alertas.renderizar(a)
    assert "Kette" in corpo and "GIOVANNA" in texto


def test_gera_conta_um_dia_antes_do_imposto_e_atualiza(client, corretora):
    eid = corretora["id"]
    db, p = _cenario(eid)
    das = db.scalar(select(Categoria).where(Categoria.entidade_id == eid, Categoria.grupo_dre == GrupoDRE.DEDUCOES))
    db.add(Titulo(entidade_id=eid, tipo=TipoTitulo.PAGAR, descricao="DAS 10/2026", valor=Decimal("900"), vencimento=date(2026, 11, 20),
                  competencia=date(2026, 10, 1), categoria_id=das.id))
    # cópia de recorrência com rótulo errado no mês de pagamento: é reaproveitada e corrigida
    copia = Titulo(entidade_id=eid, tipo=TipoTitulo.PAGAR, descricao="COMISSÃO GIOVANNA 09/2026", valor=Decimal("1700"),
                   vencimento=date(2026, 11, 19), competencia=date(2026, 9, 1), contraparte_id=p.contraparte_id)
    db.add(copia)
    db.commit()
    r = cp.gerar_conta(db, p, 2026, 10)
    assert r["situacao"] == "atualizada" and r["titulo_id"] == copia.id
    assert r["vencimento"] == date(2026, 11, 19) and r["valor"] == Decimal("161.20")
    db.refresh(copia)
    assert copia.descricao == "COMISSÃO GIOVANNA 10/2026"
    # chegou mais comissão: atualiza o mesmo título
    _com(db, eid, date(2026, 10, 20), "ANA PAULA", "100")
    db.commit()
    r2 = cp.gerar_conta(db, p, 2026, 10)
    assert r2["titulo_id"] == copia.id and r2["valor"] == Decimal("169.20")
    assert db.scalars(select(Titulo).where(Titulo.descricao.ilike("COMISSÃO GIOVANNA%"))).all() == [copia]


def test_saldo_negativo_vai_para_o_mes_seguinte(client, corretora):
    eid = corretora["id"]
    db, p = _cenario(eid)
    db.add(MetaComissao(plano_id=p.id, ano=2026, mes=9, tipo="patrimonial", faixas=FAIXAS))
    _com(db, eid, date(2026, 9, 10), "ESTORNO GRANDE", "-1000")
    db.commit()
    r = cp.gerar_conta(db, p, 2026, 9)
    assert r["total"] == Decimal("-60.00") and "saldo" in r["situacao"]
    a = cp.apurar(db, p, 2026, 10)
    assert a["saldo_anterior"] == Decimal("-60.00") and a["a_pagar"] == Decimal("101.20")


def test_planilha_saude():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "OUTUBRO"
    ws.append(["CLIENTE", "OPERADORA", "PLANO", "FATURA", "COMISSAO", "ADESAO", "PARCELA", "INDICACAO"])
    ws.append(["EMPRESA X", "SULAMERICA", "PME", 2000, 2000, 300, "1/12", ""])
    ws.append(["FULANO", "AMIL", "PF", 500, 200, 0, "2/12", ""])
    buf = io.BytesIO()
    wb.save(buf)
    linhas = cp.ler_planilha_saude(buf.getvalue(), 2026)
    assert len(linhas) == 2 and linhas[0]["mes"] == 10 and linhas[0]["parcela"] == 1 and linhas[1]["parcela"] == 2


def test_minha_comissao_so_a_propria(client, corretora):
    eid = corretora["id"]
    db, p = _cenario(eid)
    g = client.post("/api/admin/grupos", json={"nome": "Produtoras", "areas": ["minha_comissao"], "todas_entidades": False,
                                               "entidades": [eid]}).json()
    u = client.post("/api/admin/usuarios", json={"nome": "Giovanna", "email": "gio@finbpo.dev", "senha": "Giovanna2026",
                                                 "papel": "leitor", "grupo_id": g["id"]}).json()
    tok = client.post("/api/auth/login", data={"username": "gio@finbpo.dev", "password": "Giovanna2026"}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get(f"/api/entidades/{eid}/minha-comissao", headers=h).status_code == 404  # ainda não ligada
    plano = client.get(f"/api/entidades/{eid}/planos-comissao").json()[0]
    plano["usuario_id"] = u["id"]
    assert client.put(f"/api/entidades/{eid}/planos-comissao/{p.id}", json=plano).status_code == 200
    r = client.get(f"/api/entidades/{eid}/minha-comissao?ano=2026&mes=10", headers=h)
    assert r.status_code == 200 and float(r.json()["apuracao"]["total"]) == 161.2
    pdf = client.get(f"/api/entidades/{eid}/minha-comissao/demonstrativo?ano=2026&mes=10", headers=h)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert client.get(f"/api/entidades/{eid}/planos-comissao", headers=h).status_code == 403  # não vê as outras
    assert client.post(f"/api/entidades/{eid}/planos-comissao/{p.id}/gerar-conta?ano=2026&mes=10", headers=h).status_code == 403
    assert db.get(Titulo, 1) is None or db.get(Titulo, 1).status != StatusTitulo.PAGO
