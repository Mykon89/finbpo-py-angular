from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ContaFinanceira, RegraCategorizacao, Transacao


def aplicar_regras(db: Session, entidade_id: int, somente_sem_categoria: bool = True) -> int:
    regras = db.scalars(
        select(RegraCategorizacao)
        .where(RegraCategorizacao.entidade_id == entidade_id)
        .order_by(RegraCategorizacao.prioridade, RegraCategorizacao.id)
    ).all()
    if not regras:
        return 0

    stmt = select(Transacao).join(ContaFinanceira).where(ContaFinanceira.entidade_id == entidade_id)
    if somente_sem_categoria:
        stmt = stmt.where(Transacao.categoria_id.is_(None))

    alteradas = 0
    for trn in db.scalars(stmt):
        desc = trn.descricao.upper()
        for regra in regras:
            if regra.padrao.upper() in desc:
                if trn.categoria_id != regra.categoria_id:
                    trn.categoria_id = regra.categoria_id
                    alteradas += 1
                break
    db.commit()
    return alteradas
