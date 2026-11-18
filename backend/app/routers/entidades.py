from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.deps import DB, EntidadeDep, UsuarioAtual, obter_do_escopo
from app.models import (
    Categoria,
    CentroCusto,
    ContaFinanceira,
    Contraparte,
    Entidade,
    RegraCategorizacao,
    TipoEntidade,
    Segmento,
    Transacao,
)
from app.schemas import (
    CategoriaCriar,
    CategoriaLer,
    CentroCustoCriar,
    CentroCustoLer,
    ContaCriar,
    ContaLer,
    ContaSaldo,
    ContraparteCriar,
    ContraparteLer,
    EntidadeAtualizar,
    EntidadeCriar,
    EntidadeLer,
    RegraCriar,
    RegraLer,
)
from app.services.categorizacao import aplicar_regras
from app.services.cnpj import cnpj_valido, cpf_valido, so_digitos
from app.services.plano_contas import PLANOS

router = APIRouter(prefix="/entidades", tags=["entidades"])


@router.get("", response_model=list[EntidadeLer])
def listar(db: DB, _: UsuarioAtual, incluir_inativas: bool = False):
    stmt = select(Entidade).order_by(Entidade.nome)
    if not incluir_inativas:
        stmt = stmt.where(Entidade.ativo.is_(True))
    return db.scalars(stmt).all()


def _normalizar_documento(db, tipo: TipoEntidade, documento: str | None, ignorar_id: int | None = None) -> str | None:
    if not documento:
        return None
    doc = so_digitos(documento)
    if tipo == TipoEntidade.PJ and not cnpj_valido(doc):
        raise HTTPException(422, "CNPJ inválido")
    if tipo == TipoEntidade.PF and not cpf_valido(doc):
        raise HTTPException(422, "CPF inválido")
    existente = db.scalar(select(Entidade).where(Entidade.documento == doc))
    if existente and existente.id != ignorar_id:
        raise HTTPException(409, f"Documento já cadastrado na entidade '{existente.nome}'")
    return doc


def _limpar(dados: dict) -> dict:
    for campo in ("cep", "telefone"):
        if dados.get(campo):
            dados[campo] = so_digitos(dados[campo])
    if dados.get("uf"):
        dados["uf"] = dados["uf"].upper()
    if dados.get("razao_social"):
        dados["dados_atualizados_em"] = datetime.now(UTC)
    return dados


@router.post("", response_model=EntidadeLer, status_code=201)
def criar(dados: EntidadeCriar, db: DB, _: UsuarioAtual):
    if (dados.segmento == Segmento.PF) != (dados.tipo == TipoEntidade.PF):
        raise HTTPException(422, "Segmento 'pf' exige tipo PF (e vice-versa)")
    valores = _limpar(dados.model_dump(exclude={"criar_plano_contas"}))
    valores["documento"] = _normalizar_documento(db, dados.tipo, dados.documento)
    entidade = Entidade(**valores)
    db.add(entidade)
    db.flush()
    if dados.criar_plano_contas:
        for nome, grupo in PLANOS[dados.segmento]:
            db.add(Categoria(entidade_id=entidade.id, nome=nome, grupo_dre=grupo))
    db.commit()
    return entidade


@router.get("/{entidade_id}", response_model=EntidadeLer)
def obter(entidade: EntidadeDep):
    return entidade


@router.patch("/{entidade_id}", response_model=EntidadeLer)
def atualizar(dados: EntidadeAtualizar, entidade: EntidadeDep, db: DB):
    valores = _limpar(dados.model_dump(exclude_unset=True))
    if "documento" in valores:
        valores["documento"] = _normalizar_documento(db, entidade.tipo, valores["documento"], entidade.id)
    for k, v in valores.items():
        setattr(entidade, k, v)
    db.commit()
    return entidade


# --- categorias
@router.get("/{entidade_id}/categorias", response_model=list[CategoriaLer])
def listar_categorias(entidade: EntidadeDep, db: DB):
    return db.scalars(
        select(Categoria).where(Categoria.entidade_id == entidade.id).order_by(Categoria.grupo_dre, Categoria.nome)
    ).all()


@router.post("/{entidade_id}/categorias", response_model=CategoriaLer, status_code=201)
def criar_categoria(dados: CategoriaCriar, entidade: EntidadeDep, db: DB):
    cat = Categoria(entidade_id=entidade.id, **dados.model_dump())
    db.add(cat)
    db.commit()
    return cat


# --- centros de custo
@router.get("/{entidade_id}/centros-custo", response_model=list[CentroCustoLer])
def listar_centros(entidade: EntidadeDep, db: DB):
    return db.scalars(select(CentroCusto).where(CentroCusto.entidade_id == entidade.id).order_by(CentroCusto.nome)).all()


@router.post("/{entidade_id}/centros-custo", response_model=CentroCustoLer, status_code=201)
def criar_centro(dados: CentroCustoCriar, entidade: EntidadeDep, db: DB):
    cc = CentroCusto(entidade_id=entidade.id, **dados.model_dump())
    db.add(cc)
    db.commit()
    return cc


# --- contrapartes
@router.get("/{entidade_id}/contrapartes", response_model=list[ContraparteLer])
def listar_contrapartes(entidade: EntidadeDep, db: DB, busca: str | None = None):
    stmt = select(Contraparte).where(Contraparte.entidade_id == entidade.id)
    if busca:
        stmt = stmt.where(Contraparte.nome.ilike(f"%{busca}%"))
    return db.scalars(stmt.order_by(Contraparte.nome)).all()


@router.post("/{entidade_id}/contrapartes", response_model=ContraparteLer, status_code=201)
def criar_contraparte(dados: ContraparteCriar, entidade: EntidadeDep, db: DB):
    cp = Contraparte(entidade_id=entidade.id, **dados.model_dump())
    db.add(cp)
    db.commit()
    return cp


# --- contas financeiras
@router.get("/{entidade_id}/contas", response_model=list[ContaSaldo])
def listar_contas(entidade: EntidadeDep, db: DB):
    contas = db.scalars(
        select(ContaFinanceira).where(ContaFinanceira.entidade_id == entidade.id).order_by(ContaFinanceira.nome)
    ).all()
    somas = dict(
        db.execute(
            select(Transacao.conta_id, func.sum(Transacao.valor))
            .where(Transacao.conta_id.in_([c.id for c in contas]))
            .group_by(Transacao.conta_id)
        ).all()
    )
    return [
        ContaSaldo(
            **ContaLer.model_validate(c).model_dump(),
            saldo_atual=c.saldo_inicial + Decimal(str(somas.get(c.id) or 0)),
        )
        for c in contas
    ]


@router.post("/{entidade_id}/contas", response_model=ContaLer, status_code=201)
def criar_conta(dados: ContaCriar, entidade: EntidadeDep, db: DB):
    conta = ContaFinanceira(entidade_id=entidade.id, **dados.model_dump())
    db.add(conta)
    db.commit()
    return conta


# --- regras de categorização
@router.get("/{entidade_id}/regras", response_model=list[RegraLer])
def listar_regras(entidade: EntidadeDep, db: DB):
    return db.scalars(
        select(RegraCategorizacao)
        .where(RegraCategorizacao.entidade_id == entidade.id)
        .order_by(RegraCategorizacao.prioridade, RegraCategorizacao.id)
    ).all()


@router.post("/{entidade_id}/regras", response_model=RegraLer, status_code=201)
def criar_regra(dados: RegraCriar, entidade: EntidadeDep, db: DB):
    obter_do_escopo(db, Categoria, dados.categoria_id, entidade.id)
    regra = RegraCategorizacao(entidade_id=entidade.id, **dados.model_dump())
    db.add(regra)
    db.commit()
    return regra


@router.delete("/{entidade_id}/regras/{regra_id}", status_code=204)
def remover_regra(regra_id: int, entidade: EntidadeDep, db: DB):
    db.delete(obter_do_escopo(db, RegraCategorizacao, regra_id, entidade.id))
    db.commit()


@router.post("/{entidade_id}/regras/aplicar")
def aplicar(entidade: EntidadeDep, db: DB, somente_sem_categoria: bool = True):
    return {"alteradas": aplicar_regras(db, entidade.id, somente_sem_categoria)}
