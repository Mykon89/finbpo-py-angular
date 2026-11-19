"""Conciliação do contas a pagar com débitos do banco: 6 passadas, perguntas e aprendizado."""

import hashlib
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.db import get_db
from app.main import app
from app.models import (
    Categoria,
    ContaFinanceira,
    Contraparte,
    Frequencia,
    Natureza,
    OrigemTransacao,
    Pendencia,
    Recorrencia,
    StatusTitulo,
    TipoConta,
    TipoTitulo,
    Titulo,
    Transacao,
)
from app.services import decisoes
from app.services.conciliacao_pagar import conciliar_pagar, texto_bate

HOJE = date(2026, 11, 10)


def _db():
    return next(app.dependency_overrides[get_db]())


class Cenario:
    def __init__(self, eid):
        self.db, self.eid = _db(), eid
        self.conta = ContaFinanceira(entidade_id=eid, tipo=TipoConta.CORRENTE, nome="Sicoob")
        self.db.add(self.conta)
        self.db.flush()
        self.n = 0

    def cp(self, nome):
        c = Contraparte(entidade_id=self.eid, nome=nome)
        self.db.add(c)
        self.db.flush()
        return c

    def cat(self, nome):
        return self.db.scalar(select(Categoria).where(Categoria.entidade_id == self.eid, Categoria.nome == nome))

    def titulo(self, desc, valor, venc, cp=None, cat=None, natureza=Natureza.FIXA, rec=None):
        t = Titulo(entidade_id=self.eid, tipo=TipoTitulo.PAGAR, descricao=desc, valor=Decimal(valor), vencimento=venc,
                   competencia=venc.replace(day=1), contraparte_id=cp.id if cp else None, categoria_id=cat.id if cat else None,
                   natureza=natureza, recorrencia_id=rec)
        self.db.add(t)
        self.db.flush()
        return t

    def debito(self, valor, dia, desc, cp=None, nome=None, cat=None):
        self.n += 1
        t = Transacao(conta_id=self.conta.id, data=dia, valor=-Decimal(valor), descricao=desc, origem=OrigemTransacao.OFX,
                      hash=hashlib.sha256(f"{self.n}{desc}".encode()).hexdigest(), contraparte_id=cp.id if cp else None,
                      contraparte_nome=nome or (cp.nome if cp else None), categoria_id=cat.id if cat else None)
        self.db.add(t)
        self.db.flush()
        return t

    def rodar(self, **kw):
        self.db.commit()
        return conciliar_pagar(self.db, self.eid, dias=400, **kw)


def test_seis_passadas(client, corretora):
    c = Cenario(corretora["id"])
    kette, cond, luz = c.cp("KETTE"), c.cp("CONDOMINIO MIX"), c.cp("NEOENERGIA")
    pro = c.titulo("PRO-LABORE 10/2026", "1780", date(2026, 11, 5), kette)
    ret = c.titulo("RETIRADA KETTE", "795", date(2026, 11, 6), kette)
    tx = c.titulo("TX COND SALA 102", "590", date(2026, 11, 5), cond)
    energia = c.titulo("NEOENERGIA SALA 104", "112.05", date(2026, 11, 20), luz, natureza=Natureza.VARIAVEL)
    va = c.cat("Benefícios")
    va1 = c.titulo("VA FABIANA 11/2026", "760", date(2026, 10, 27), cat=va)
    va2 = c.titulo("VA GIOVANNA 11/2026", "760", date(2026, 10, 27), cat=va)
    aluguel = c.titulo("ALUGUEL SALA", "1200", date(2026, 11, 5))

    d1 = c.debito("2575", date(2026, 11, 6), "PIX", kette)                          # fornecedor+valor (2 contas)
    d2 = c.debito("113.12", date(2026, 11, 4), "PIX", luz)                          # fornecedor+valor aprox. (variável)
    d3 = c.debito("520", date(2026, 11, 5), "DEB.TIT.COMPE TX COND SL 102")        # descrição+desconto
    d4 = c.debito("1520", date(2026, 10, 29), "PIX PEDIDO 701DA742", cat=va)       # categoria+valor (2 contas)
    d5 = c.debito("1200", date(2026, 11, 6), "PAG BOLETO")                          # valor+data
    res = c.rodar()
    assert res["conciliados"] == 5 and res["sem_conta"] == 0, res
    for tit in (pro, ret, tx, energia, va1, va2, aluguel):
        c.db.refresh(tit)
        assert tit.status == StatusTitulo.PAGO, tit.descricao
    assert tx.desconto == Decimal("70.00")
    assert energia.valor == Decimal("113.12")  # pago a mais: acréscimo
    assert all(d.conciliada for d in (d1, d2, d3, d4, d5))
    assert texto_bate("TX COND SL 104", "TX COND SALA 104") and not texto_bate("TX COND SL 104", "TX COND SALA 102")


def test_debito_sem_conta_pergunta_e_aprende(client, corretora):
    eid = corretora["id"]
    c = Cenario(eid)
    posto = c.cp("POSTO SHELL")
    c.titulo("CONTA QUALQUER", "999", date(2026, 11, 5))  # existe PAGAR, então débitos sem conta perguntam
    d = c.debito("150", date(2026, 11, 3), "COMPRA DEBITO", posto)
    c.rodar()
    p = c.db.scalar(select(Pendencia).where(Pendencia.tipo == "debito_sem_conta"))
    assert p and "POSTO SHELL" in p.titulo
    comb = c.cat("Material de escritório")
    r = client.post(f"/api/entidades/{eid}/pendencias/{p.id}/responder",
                    json={"opcao": "lancar", "valores": {"categoria_id": comb.id, "descricao": "ABASTECIMENTO"}, "sempre": True})
    assert r.status_code == 200, r.text
    novo = _db().scalar(select(Titulo).where(Titulo.descricao == "ABASTECIMENTO"))
    assert novo.status == StatusTitulo.PAGO and novo.categoria_id == comb.id

    # próximo abastecimento no mesmo posto: lançado sozinho, sem pergunta
    c2 = Cenario(eid)
    c2.debito("180", date(2026, 11, 9), "COMPRA DEBITO", c2.db.get(Contraparte, posto.id))
    res = c2.rodar()
    assert res["lancados_automaticamente"] == 1
    assert c2.db.scalar(select(Pendencia).where(Pendencia.tipo == "debito_sem_conta", Pendencia.status == "aberta")) is None
    assert d.id


def test_favorecido_desconhecido_vira_apelido_do_fornecedor(client, corretora):
    eid = corretora["id"]
    c = Cenario(eid)
    kette = c.cp("KETTE BARBARA SOARES FERREIRA")
    c.titulo("PRO-LABORE 10/2026", "1780", date(2026, 11, 5), kette)
    c.titulo("RETIRADA KETTE", "795", date(2026, 11, 6), kette)
    c.debito("2575", date(2026, 11, 6), "PIX EMITIDO", nome="Pagamento Pix ***.476.251-**")
    c.rodar()
    p = c.db.scalar(select(Pendencia).where(Pendencia.tipo == "debito_sem_conta"))
    r = client.post(f"/api/entidades/{eid}/pendencias/{p.id}/responder",
                    json={"opcao": "fornecedor", "valores": {"fornecedor": "kette"}, "sempre": True})
    assert r.status_code == 200, r.text
    db = _db()
    assert all(t.status == StatusTitulo.PAGO for t in db.scalars(select(Titulo).where(Titulo.contraparte_id == kette.id)))
    assert db.scalar(select(decisoes.RegraAprendida).where(decisoes.RegraAprendida.tipo == "favorecido"))


def test_recorrencia_com_valor_diferente_pergunta(client, corretora):
    eid = corretora["id"]
    c = Cenario(eid)
    claro = c.cp("CLARO")
    rec = Recorrencia(entidade_id=eid, tipo=TipoTitulo.PAGAR, descricao="CONTA CLARO", valor=Decimal("817.74"),
                      frequencia=Frequencia.MENSAL, inicio=date(2026, 1, 22), contraparte_id=claro.id, natureza=Natureza.VARIAVEL)
    c.db.add(rec)
    c.db.flush()
    c.titulo("CONTA CLARO 10/2026", "817.74", date(2026, 11, 22), claro, natureza=Natureza.VARIAVEL, rec=rec.id)
    c.debito("899.90", date(2026, 11, 20), "DEBITO AUTOMATICO", claro)
    res = c.rodar()
    assert res["conciliados"] == 1
    p = c.db.scalar(select(Pendencia).where(Pendencia.tipo == "recorrencia_valor"))
    assert p and "899.90" in p.titulo
    client.post(f"/api/entidades/{eid}/pendencias/{p.id}/responder", json={"opcao": "atualizar", "sempre": False})
    assert _db().get(Recorrencia, rec.id).valor == Decimal("899.90")
