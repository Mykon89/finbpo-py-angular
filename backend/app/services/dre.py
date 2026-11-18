"""DRE gerencial simples, regime de caixa (transações categorizadas do mês)."""

from calendar import monthrange
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Categoria, ContaFinanceira, GrupoDRE as G, Transacao

ZERO = Decimal("0.00")

ROTULOS = {
    G.RECEITA_BRUTA: "Receita bruta",
    G.DEDUCOES: "(-) Deduções",
    G.CUSTOS: "(-) Custos",
    G.DESPESAS_PESSOAL: "(-) Despesas com pessoal",
    G.DESPESAS_ADMINISTRATIVAS: "(-) Despesas administrativas",
    G.DESPESAS_COMERCIAIS: "(-) Despesas comerciais",
    G.RECEITAS_FINANCEIRAS: "(+) Receitas financeiras",
    G.DESPESAS_FINANCEIRAS: "(-) Despesas financeiras",
    G.IMPOSTOS_LUCRO: "(-) IRPJ/CSLL",
}


def periodo(ano: int, mes: int) -> tuple[date, date]:
    return date(ano, mes, 1), date(ano, mes, monthrange(ano, mes)[1])


def calcular_dre(db: Session, entidade_id: int, ano: int, mes: int) -> dict:
    inicio, fim = periodo(ano, mes)
    linhas = db.execute(
        select(Categoria.grupo_dre, Categoria.nome, func.sum(Transacao.valor))
        .join(Transacao, Transacao.categoria_id == Categoria.id)
        .join(ContaFinanceira, Transacao.conta_id == ContaFinanceira.id)
        .where(ContaFinanceira.entidade_id == entidade_id, Transacao.data.between(inicio, fim))
        .group_by(Categoria.grupo_dre, Categoria.nome)
    ).all()

    grupos: dict[G, Decimal] = {g: ZERO for g in G}
    detalhe: dict[str, list[dict]] = {g.value: [] for g in G}
    for grupo, nome, total in linhas:
        total = Decimal(str(total or 0)).quantize(Decimal("0.01"))
        grupos[grupo] += total
        detalhe[grupo.value].append({"categoria": nome, "valor": total})

    sem_categoria = db.scalar(
        select(func.coalesce(func.sum(Transacao.valor), 0))
        .join(ContaFinanceira)
        .where(
            ContaFinanceira.entidade_id == entidade_id,
            Transacao.data.between(inicio, fim),
            Transacao.categoria_id.is_(None),
        )
    )

    # Valores já vêm com sinal do extrato (saídas negativas)
    receita_liquida = grupos[G.RECEITA_BRUTA] + grupos[G.DEDUCOES]
    lucro_bruto = receita_liquida + grupos[G.CUSTOS]
    resultado_operacional = (
        lucro_bruto
        + grupos[G.DESPESAS_PESSOAL]
        + grupos[G.DESPESAS_ADMINISTRATIVAS]
        + grupos[G.DESPESAS_COMERCIAIS]
    )
    resultado_financeiro = grupos[G.RECEITAS_FINANCEIRAS] + grupos[G.DESPESAS_FINANCEIRAS]
    resultado_antes_ir = resultado_operacional + resultado_financeiro
    resultado_liquido = resultado_antes_ir + grupos[G.IMPOSTOS_LUCRO]

    def pct(v: Decimal) -> float | None:
        rb = grupos[G.RECEITA_BRUTA]
        return float((v / rb * 100).quantize(Decimal("0.1"))) if rb else None

    linhas_dre = []
    for g, rotulo in ROTULOS.items():
        linhas_dre.append({"grupo": g.value, "rotulo": rotulo, "valor": grupos[g], "detalhe": detalhe[g.value]})
        if g == G.DEDUCOES:
            linhas_dre.append({"grupo": None, "rotulo": "= Receita líquida", "valor": receita_liquida, "detalhe": []})
        elif g == G.CUSTOS:
            linhas_dre.append({"grupo": None, "rotulo": "= Lucro bruto", "valor": lucro_bruto, "detalhe": []})
        elif g == G.DESPESAS_COMERCIAIS:
            linhas_dre.append(
                {"grupo": None, "rotulo": "= Resultado operacional", "valor": resultado_operacional, "detalhe": []}
            )
        elif g == G.DESPESAS_FINANCEIRAS:
            linhas_dre.append(
                {"grupo": None, "rotulo": "= Resultado antes do IR", "valor": resultado_antes_ir, "detalhe": []}
            )

    return {
        "entidade_id": entidade_id,
        "competencia": inicio,
        "linhas": linhas_dre,
        "resultado_liquido": resultado_liquido,
        "margem_liquida_pct": pct(resultado_liquido),
        "nao_operacional": grupos[G.NAO_OPERACIONAL],
        "sem_categoria": Decimal(str(sem_categoria)).quantize(Decimal("0.01")),
    }
