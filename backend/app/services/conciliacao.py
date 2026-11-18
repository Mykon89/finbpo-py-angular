"""Conciliação automática: casa transações do extrato com títulos em aberto.

Critério: mesmo valor (saída = pagar, entrada = receber) e vencimento dentro da
tolerância. Só concilia quando existe exatamente um candidato; empates ficam
para revisão manual.
"""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.models import (
    Baixa,
    ContaFinanceira,
    StatusTitulo,
    TipoTitulo,
    Titulo,
    Transacao,
)


@dataclass
class ResultadoConciliacao:
    conciliadas: int
    ambiguas: int
    sem_candidato: int


def atualizar_status(titulo: Titulo) -> None:
    if titulo.status == StatusTitulo.CANCELADO:
        return
    saldo = titulo.saldo
    if saldo <= 0:
        titulo.status = StatusTitulo.PAGO
    elif saldo < titulo.valor:
        titulo.status = StatusTitulo.PARCIAL
    else:
        titulo.status = StatusTitulo.ABERTO


def vincular(db: Session, transacao: Transacao, titulo: Titulo, valor: Decimal | None = None) -> Baixa:
    baixa = Baixa(
        titulo=titulo,
        transacao_id=transacao.id,
        data=transacao.data,
        valor=valor if valor is not None else abs(transacao.valor),
    )
    db.add(baixa)
    titulo.baixas.append(baixa)
    if transacao.categoria_id is None and titulo.categoria_id is not None:
        transacao.categoria_id = titulo.categoria_id
    transacao.conciliada = True
    atualizar_status(titulo)
    return baixa


def candidatos(db: Session, entidade_id: int, transacao: Transacao, tolerancia: int) -> list[Titulo]:
    tipo = TipoTitulo.PAGAR if transacao.valor < 0 else TipoTitulo.RECEBER
    titulos = db.scalars(
        select(Titulo)
        .options(selectinload(Titulo.baixas))
        .where(
            Titulo.entidade_id == entidade_id,
            Titulo.tipo == tipo,
            Titulo.status.in_([StatusTitulo.ABERTO, StatusTitulo.PARCIAL]),
            Titulo.vencimento.between(
                transacao.data - timedelta(days=tolerancia),
                transacao.data + timedelta(days=tolerancia),
            ),
        )
    ).all()
    valor = abs(transacao.valor)
    return [t for t in titulos if t.saldo == valor]


def conciliar_entidade(db: Session, entidade_id: int, tolerancia: int | None = None) -> ResultadoConciliacao:
    tol = settings.conciliacao_tolerancia_dias if tolerancia is None else tolerancia
    pendentes = db.scalars(
        select(Transacao)
        .join(ContaFinanceira)
        .where(ContaFinanceira.entidade_id == entidade_id, Transacao.conciliada.is_(False))
        .order_by(Transacao.data)
    ).all()

    res = ResultadoConciliacao(0, 0, 0)
    usados: set[int] = set()
    for trn in pendentes:
        cands = [t for t in candidatos(db, entidade_id, trn, tol) if t.id not in usados]
        if len(cands) == 1:
            vincular(db, trn, cands[0])
            usados.add(cands[0].id)
            res.conciliadas += 1
        elif cands:
            res.ambiguas += 1
        else:
            res.sem_candidato += 1
    db.commit()
    return res
