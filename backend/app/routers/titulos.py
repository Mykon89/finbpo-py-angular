import uuid
from datetime import date

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.deps import DB, EntidadeDep, obter_do_escopo
from app.models import Baixa, Categoria, CentroCusto, Contraparte, StatusTitulo, TipoTitulo, Titulo, Transacao
from app.schemas import BaixaManual, TituloAtualizar, TituloCriar, TituloLer
from app.services.conciliacao import atualizar_status

router = APIRouter(prefix="/entidades/{entidade_id}/titulos", tags=["titulos"])


def _somar_meses(d: date, meses: int) -> date:
    mes = d.month - 1 + meses
    ano = d.year + mes // 12
    mes = mes % 12 + 1
    dias = [31, 29 if ano % 4 == 0 and (ano % 100 != 0 or ano % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(ano, mes, min(d.day, dias[mes - 1]))


def _validar_refs(db, entidade_id: int, dados) -> None:
    for campo, modelo in (("categoria_id", Categoria), ("contraparte_id", Contraparte), ("centro_custo_id", CentroCusto)):
        valor = getattr(dados, campo, None)
        if valor is not None:
            obter_do_escopo(db, modelo, valor, entidade_id)


def _obter(db, entidade_id: int, titulo_id: int) -> Titulo:
    return obter_do_escopo(db, Titulo, titulo_id, entidade_id)


@router.get("", response_model=list[TituloLer])
def listar(
    entidade: EntidadeDep,
    db: DB,
    tipo: TipoTitulo | None = None,
    status: list[StatusTitulo] | None = None,
    vencimento_de: date | None = None,
    vencimento_ate: date | None = None,
    limite: int = 500,
):
    stmt = select(Titulo).options(selectinload(Titulo.baixas)).where(Titulo.entidade_id == entidade.id)
    if tipo:
        stmt = stmt.where(Titulo.tipo == tipo)
    if status:
        stmt = stmt.where(Titulo.status.in_(status))
    if vencimento_de:
        stmt = stmt.where(Titulo.vencimento >= vencimento_de)
    if vencimento_ate:
        stmt = stmt.where(Titulo.vencimento <= vencimento_ate)
    return db.scalars(stmt.order_by(Titulo.vencimento, Titulo.id).limit(limite)).all()


@router.post("", response_model=list[TituloLer], status_code=201)
def criar(dados: TituloCriar, entidade: EntidadeDep, db: DB):
    _validar_refs(db, entidade.id, dados)
    grupo = str(uuid.uuid4()) if dados.parcelas > 1 else None
    competencia = (dados.competencia or dados.vencimento).replace(day=1)
    titulos = []
    for i in range(dados.parcelas):
        sufixo = f" ({i + 1}/{dados.parcelas})" if dados.parcelas > 1 else ""
        t = Titulo(
            entidade_id=entidade.id,
            tipo=dados.tipo,
            descricao=dados.descricao + sufixo,
            contraparte_id=dados.contraparte_id,
            categoria_id=dados.categoria_id,
            centro_custo_id=dados.centro_custo_id,
            competencia=_somar_meses(competencia, i),
            vencimento=_somar_meses(dados.vencimento, i),
            valor=dados.valor,
            parcela=i + 1,
            total_parcelas=dados.parcelas,
            grupo_parcelas=grupo,
            observacao=dados.observacao,
        )
        db.add(t)
        titulos.append(t)
    db.commit()
    return titulos


@router.get("/{titulo_id}", response_model=TituloLer)
def obter(titulo_id: int, entidade: EntidadeDep, db: DB):
    return _obter(db, entidade.id, titulo_id)


@router.patch("/{titulo_id}", response_model=TituloLer)
def atualizar(titulo_id: int, dados: TituloAtualizar, entidade: EntidadeDep, db: DB):
    titulo = _obter(db, entidade.id, titulo_id)
    if titulo.status in (StatusTitulo.PAGO, StatusTitulo.CANCELADO):
        raise HTTPException(409, "Título pago ou cancelado não pode ser alterado")
    _validar_refs(db, entidade.id, dados)
    for k, v in dados.model_dump(exclude_unset=True).items():
        setattr(titulo, k, v.replace(day=1) if k == "competencia" and v else v)
    atualizar_status(titulo)
    db.commit()
    return titulo


@router.post("/{titulo_id}/baixar", response_model=TituloLer)
def baixar(titulo_id: int, dados: BaixaManual, entidade: EntidadeDep, db: DB):
    """Baixa manual (sem transação de extrato), ex.: pagamento em dinheiro."""
    titulo = _obter(db, entidade.id, titulo_id)
    if titulo.status in (StatusTitulo.PAGO, StatusTitulo.CANCELADO):
        raise HTTPException(409, "Título já pago ou cancelado")
    valor = dados.valor or titulo.saldo
    if valor > titulo.saldo:
        raise HTTPException(422, "Valor maior que o saldo do título")
    titulo.baixas.append(Baixa(data=dados.data, valor=valor))
    atualizar_status(titulo)
    db.commit()
    return titulo


@router.post("/{titulo_id}/cancelar", response_model=TituloLer)
def cancelar(titulo_id: int, entidade: EntidadeDep, db: DB):
    titulo = _obter(db, entidade.id, titulo_id)
    if titulo.baixas:
        raise HTTPException(409, "Estorne as baixas antes de cancelar")
    titulo.status = StatusTitulo.CANCELADO
    db.commit()
    return titulo


@router.delete("/{titulo_id}/baixas/{baixa_id}", response_model=TituloLer)
def estornar_baixa(titulo_id: int, baixa_id: int, entidade: EntidadeDep, db: DB):
    titulo = _obter(db, entidade.id, titulo_id)
    baixa = next((b for b in titulo.baixas if b.id == baixa_id), None)
    if not baixa:
        raise HTTPException(404, "Baixa não encontrada")
    if baixa.transacao_id:
        trn = db.get(Transacao, baixa.transacao_id)
        if trn:
            trn.conciliada = False
    titulo.baixas.remove(baixa)
    atualizar_status(titulo)
    db.commit()
    return titulo
