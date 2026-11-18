from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.deps import DB, EntidadeDep
from app.models import StatusTitulo, TipoTitulo, Titulo
from app.schemas import DRE, Aging, AgingFaixa
from app.services.dre import calcular_dre

router = APIRouter(prefix="/entidades/{entidade_id}/relatorios", tags=["relatorios"])

FAIXAS = [
    ("A vencer", None, 0),
    ("Vencido 1-30 dias", 1, 30),
    ("Vencido 31-60 dias", 31, 60),
    ("Vencido 61-90 dias", 61, 90),
    ("Vencido +90 dias", 91, None),
]


@router.get("/dre", response_model=DRE)
def dre(entidade: EntidadeDep, db: DB, ano: int = Query(ge=2000, le=2100), mes: int = Query(ge=1, le=12)):
    return calcular_dre(db, entidade.id, ano, mes)


@router.get("/aging", response_model=Aging)
def aging(entidade: EntidadeDep, db: DB, tipo: TipoTitulo, data_base: date | None = None):
    base = data_base or date.today()
    titulos = db.scalars(
        select(Titulo)
        .options(selectinload(Titulo.baixas))
        .where(
            Titulo.entidade_id == entidade.id,
            Titulo.tipo == tipo,
            Titulo.status.in_([StatusTitulo.ABERTO, StatusTitulo.PARCIAL]),
        )
    ).all()
    faixas = []
    for rotulo, de, ate in FAIXAS:
        sel = []
        for t in titulos:
            atraso = (base - t.vencimento).days
            if (de is None or atraso >= de) and (ate is None or atraso <= ate):
                sel.append(t)
        faixas.append(AgingFaixa(faixa=rotulo, quantidade=len(sel), valor=sum((t.saldo for t in sel), Decimal("0"))))
    return Aging(tipo=tipo, data_base=base, faixas=faixas)
