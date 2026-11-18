"""Novo negócio x renovação e previsão de recebimentos de comissão."""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Comissao, PropostaFechamento
from app.services.comissoes import _cat_ok, _nome_chave, cat_ramo, nomes_batem
from app.services.fechamento import norm_seguradora

Z = Decimal("0")
_PARCELA_1 = re.compile(r"^\s*(0*1(?!\d)|TOTAL|[UÚ]NICA)", re.I)
_FORA = {"DEBITO", "AJUSTE", "BONIFICACAO", "BONUS", "SALDO"}
RECORRENTES = {"SAUDE", "ODONTO", "VIDA", "PET"}  # comissão mensal enquanto o contrato estiver ativo


def _mes(d: date, n: int = 0) -> date:
    t = d.year * 12 + d.month - 1 + n
    return date(t // 12, t % 12 + 1, 1)


def _chave(seg: str, apolice: str | None, cliente: str | None) -> tuple:
    dig = re.sub(r"\D", "", apolice or "")
    return (norm_seguradora(seg), dig) if len(dig) >= 5 else (norm_seguradora(seg), _nome_chave(cliente))


def _tipo_fechamento(fech: dict, seg: str, cliente: str, ramo: str, data: date) -> str | None:
    """'NOVO' ou 'RENOVACAO' pela proposta do FECHAMENTO do cliente nos 6 meses antes do extrato (ou no mês seguinte)."""
    nome, cat = _nome_chave(cliente), cat_ramo(ramo)
    ini, fim = _mes(data, -6), _mes(data, 1)
    achados = [
        p for p in fech.get(norm_seguradora(seg), [])
        if ini <= date(p.ano, p.mes, 1) <= fim and nomes_batem(nome, p._nome) and _cat_ok(cat, p._cat)
    ]
    if not achados:
        return None
    p = max(achados, key=lambda x: (x.ano, x.mes, x.linha))
    tipo = re.sub(r"[^A-Z]", "", (p.tipo or "").upper().replace("Ç", "C").replace("Ã", "A"))
    if "NOVO" in tipo:
        return "NOVO"
    if "RENOV" in tipo:
        return "RENOVACAO"
    return None


def classificar_novos(db: Session, entidade_id: int) -> int:
    """Marca Comissao.novo_negocio.
    - SulAmérica (manda "parcela 1" o ano inteiro): novo = 1ª comissão do contrato na BASE e, se o cliente estiver
      no FECHAMENTO, a proposta é "Seguro Novo" (renovação não conta).
    - Demais: regra do comparativo da planilha (positivo com parcela 1, TOTAL ou ÚNICA).
    """
    fech: dict[str, list] = defaultdict(list)
    for p in db.scalars(select(PropostaFechamento).where(PropostaFechamento.entidade_id == entidade_id)):
        p._nome, p._cat = _nome_chave(p.cliente), cat_ramo(p.ramo)
        fech[p.seguradora].append(p)
    linhas = db.scalars(select(Comissao).where(Comissao.entidade_id == entidade_id).order_by(Comissao.data, Comissao.id)).all()
    vistos: dict[tuple, date] = {}
    marcados = 0
    # nos 2 primeiros meses do histórico não dá para saber se o contrato é novo (já pagava antes do sistema)
    inicio_historico: dict[str, date] = {}
    for c in linhas:
        inicio_historico.setdefault(norm_seguradora(c.seguradora), _mes(c.data, 2))
    for c in linhas:
        # contrato já visto pela apólice OU pelo nome (linhas antigas da planilha vêm sem apólice)
        seg_n = norm_seguradora(c.seguradora)
        dig = re.sub(r"\D", "", c.apolice or "")
        chaves = [(seg_n, "N", _nome_chave(c.cliente))] + ([(seg_n, "A", dig)] if len(dig) >= 5 else [])
        anteriores = [vistos[k] for k in chaves if k in vistos]
        primeira_vez = not anteriores or min(anteriores) == c.data  # várias coberturas no mesmo extrato
        for k in chaves:
            vistos.setdefault(k, c.data)
        if c.bruta <= 0 or (c.ramo or "") in _FORA:
            novo = False
        elif norm_seguradora(c.seguradora) == "SULAMERICA":
            tipo = _tipo_fechamento(fech, c.seguradora, c.cliente or "", c.ramo or "", c.data) if fech else None
            novo = tipo == "NOVO" if c.data < inicio_historico[norm_seguradora(c.seguradora)] else (primeira_vez and tipo != "RENOVACAO")
        else:
            txt = c.parcela_texto or (str(c.parcela) if c.parcela is not None else "")
            novo = bool(_PARCELA_1.match(txt))
        if c.novo_negocio != novo:
            c.novo_negocio = novo
        marcados += novo
    db.commit()
    return marcados


@dataclass
class ItemPrevisao:
    tipo: str  # parcela / recorrente / proposta
    mes: str
    seguradora: str
    cliente: str
    apolice: str | None
    ramo: str | None
    valor: Decimal
    detalhe: str = ""


@dataclass
class Previsao:
    meses: list[dict] = field(default_factory=list)
    itens: list[ItemPrevisao] = field(default_factory=list)
    atrasados: list[ItemPrevisao] = field(default_factory=list)


_N_DE_T = re.compile(r"(\d+)\s*/\s*(\d+)\s*$")


def prever(db: Session, entidade_id: int, meses: int = 6, hoje: date | None = None) -> Previsao:
    hoje = hoje or date.today()
    mes_atual = _mes(hoje)
    horizonte = [_mes(hoje, i) for i in range(meses)]
    linhas = db.scalars(
        select(Comissao).where(Comissao.entidade_id == entidade_id, Comissao.data >= _mes(hoje, -14)).order_by(Comissao.data, Comissao.id)
    ).all()
    itens: list[ItemPrevisao] = []
    atrasados: list[ItemPrevisao] = []

    # 1) parcelas restantes (n/total): projeta o último valor recebido
    ultima: dict[tuple, Comissao] = {}
    for c in linhas:
        m = _N_DE_T.search(c.parcela_texto or "")
        if m and c.bruta > 0:
            k = _chave(c.seguradora, c.apolice, c.cliente)
            o = ultima.get(k)
            if not o or int(m.group(1)) > int(_N_DE_T.search(o.parcela_texto).group(1)) or (int(m.group(1)) == int(_N_DE_T.search(o.parcela_texto).group(1)) and c.data > o.data):
                ultima[k] = c
    com_parcela = set(ultima)
    for k, c in ultima.items():
        n, tot = (int(x) for x in _N_DE_T.search(c.parcela_texto).groups())
        faixa = re.search(r"(\d+)\s*a\s*(\d+)\s*/", c.parcela_texto)
        qtd_paga = int(faixa.group(2)) - int(faixa.group(1)) + 1 if faixa else max(len(re.findall(r"\d+\s*/\s*\d+", c.parcela_texto)), 1)
        valor = (c.bruta / qtd_paga).quantize(Decimal("0.01"))  # "1 a 10/12" (antecipada): valor de uma parcela
        resta = tot - n
        if resta <= 0:
            continue
        ini = max(_mes(c.data, 1), mes_atual)
        if (mes_atual.year * 12 + mes_atual.month) - (c.data.year * 12 + c.data.month) >= 2:
            atrasados.append(ItemPrevisao("parcela", f"{_mes(c.data, 1):%Y-%m}", c.seguradora, c.cliente or "", c.apolice, c.ramo,
                                          valor, f"última {n}/{tot} em {c.data:%d/%m/%Y}; parcela seguinte não chegou"))
        for i in range(resta):
            m = _mes(ini, i)
            if m in horizonte:
                itens.append(ItemPrevisao("parcela", f"{m:%Y-%m}", c.seguradora, c.cliente or "", c.apolice, c.ramo, valor,
                                          f"parcela {n + i + 1}/{tot}"))

    # 2) recorrentes (saúde, odonto, vida, pet): média dos últimos 3 meses, se recebeu em 2 deles e no último ou penúltimo
    ult3 = [_mes(hoje, -i) for i in (3, 2, 1)]
    por_mes: dict[tuple, dict[date, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    info: dict[tuple, Comissao] = {}
    for c in linhas:
        if cat_ramo(c.ramo) not in RECORRENTES and norm_seguradora(c.seguradora) not in ("SULAMERICA", "AMIL", "ODONTOPREV"):
            continue
        k = _chave(c.seguradora, c.apolice, c.cliente)
        if k in com_parcela:
            continue
        por_mes[k][_mes(c.data)] += c.bruta
        info[k] = c
    for k, valores in por_mes.items():
        presentes = [m for m in ult3 if valores.get(m, Z) > 0]
        if len(presentes) < 2 or not ({ult3[1], ult3[2]} & set(presentes)):
            continue  # parou de pagar
        media = (sum((valores.get(m, Z) for m in ult3), Z) / 3).quantize(Decimal("0.01"))
        c = info[k]
        for m in horizonte:
            if m == mes_atual and valores.get(mes_atual, Z) > 0:
                continue  # já recebeu neste mês
            itens.append(ItemPrevisao("recorrente", f"{m:%Y-%m}", c.seguradora, c.cliente or "", c.apolice, c.ramo, media,
                                      "média dos últimos 3 meses"))

    # 3) propostas do FECHAMENTO (últimos 3 meses) ainda sem comissão na BASE
    recebidos: dict[str, list] = defaultdict(list)
    for c in linhas:
        recebidos[norm_seguradora(c.seguradora)].append((_nome_chave(c.cliente), c.data))
    propostas = db.scalars(select(PropostaFechamento).where(PropostaFechamento.entidade_id == entidade_id)).all()
    for p in propostas:
        mp = date(p.ano, p.mes, 1)
        tipo = (p.tipo or "").upper()
        if not (_mes(hoje, -3) <= mp <= mes_atual) or "ENDOSSO" in tipo or not p.com_bruta or p.com_bruta <= 0:
            continue
        if p.emissao and "CANCEL" in p.emissao:
            continue
        base_dt = p.data_email or mp
        nome = _nome_chave(p.cliente)
        if any(nomes_batem(nome, n) and d >= _mes(base_dt, -1) for n, d in recebidos.get(p.seguradora, [])):
            continue
        m = max(_mes(base_dt, 1), mes_atual)
        if m in horizonte:
            itens.append(ItemPrevisao("proposta", f"{m:%Y-%m}", p.seguradora, p.cliente, p.descricao, p.ramo, p.com_bruta,
                                      f"{p.tipo or 'proposta'} ({p.aba}); comissão do FECHAMENTO"))

    resumo = []
    for m in horizonte:
        chave = f"{m:%Y-%m}"
        doms = [i for i in itens if i.mes == chave]
        por_seg: dict[str, Decimal] = defaultdict(Decimal)
        for i in doms:
            por_seg[i.seguradora] += i.valor
        resumo.append({
            "mes": chave,
            "total": sum((i.valor for i in doms), Z),
            "parcelas": sum((i.valor for i in doms if i.tipo == "parcela"), Z),
            "recorrentes": sum((i.valor for i in doms if i.tipo == "recorrente"), Z),
            "propostas": sum((i.valor for i in doms if i.tipo == "proposta"), Z),
            "por_seguradora": dict(sorted(por_seg.items(), key=lambda x: -x[1])),
        })
    return Previsao(resumo, sorted(itens, key=lambda i: (i.mes, i.seguradora, i.cliente)), atrasados)
