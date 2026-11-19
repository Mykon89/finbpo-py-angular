from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.acesso import pode_ver_entidade
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
    Titulo,
    Transacao,
)
from app.schemas import (
    CategoriaAtualizar,
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
def listar(db: DB, usuario: UsuarioAtual, incluir_inativas: bool = False):
    stmt = select(Entidade).order_by(Entidade.nome)
    if not incluir_inativas:
        stmt = stmt.where(Entidade.ativo.is_(True))
    return [e for e in db.scalars(stmt).all() if pode_ver_entidade(usuario, usuario.grupo, e.id)]


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


# --- categorias (plano de contas)
def _uso_categorias(db, entidade_id: int) -> tuple[dict[int, int], dict[int, int]]:
    lanc = dict(
        db.execute(
            select(Transacao.categoria_id, func.count(Transacao.id))
            .join(ContaFinanceira)
            .where(ContaFinanceira.entidade_id == entidade_id, Transacao.categoria_id.is_not(None))
            .group_by(Transacao.categoria_id)
        ).all()
    )
    tit = dict(
        db.execute(
            select(Titulo.categoria_id, func.count(Titulo.id))
            .where(Titulo.entidade_id == entidade_id, Titulo.categoria_id.is_not(None))
            .group_by(Titulo.categoria_id)
        ).all()
    )
    return lanc, tit


def _ler_categoria(c: Categoria, lanc: dict, tit: dict) -> CategoriaLer:
    return CategoriaLer.model_validate(c).model_copy(
        update={"qtd_lancamentos": lanc.get(c.id, 0), "qtd_titulos": tit.get(c.id, 0)}
    )


def _nome_livre(db, entidade_id: int, nome: str, ignorar_id: int | None = None) -> str:
    nome = " ".join(nome.split())
    existente = db.scalar(
        select(Categoria).where(Categoria.entidade_id == entidade_id, func.lower(Categoria.nome) == nome.lower())
    )
    if existente and existente.id != ignorar_id:
        raise HTTPException(409, f"Já existe a categoria '{existente.nome}'")
    return nome


@router.get("/{entidade_id}/categorias", response_model=list[CategoriaLer])
def listar_categorias(entidade: EntidadeDep, db: DB):
    lanc, tit = _uso_categorias(db, entidade.id)
    cats = db.scalars(
        select(Categoria).where(Categoria.entidade_id == entidade.id).order_by(Categoria.grupo_dre, Categoria.nome)
    ).all()
    return [_ler_categoria(c, lanc, tit) for c in cats]


@router.post("/{entidade_id}/categorias", response_model=CategoriaLer, status_code=201)
def criar_categoria(dados: CategoriaCriar, entidade: EntidadeDep, db: DB):
    cat = Categoria(entidade_id=entidade.id, nome=_nome_livre(db, entidade.id, dados.nome), grupo_dre=dados.grupo_dre)
    db.add(cat)
    db.commit()
    return _ler_categoria(cat, {}, {})


@router.patch("/{entidade_id}/categorias/{categoria_id}", response_model=CategoriaLer)
def atualizar_categoria(categoria_id: int, dados: CategoriaAtualizar, entidade: EntidadeDep, db: DB):
    """Renomear, mudar o grupo da DRE (afeta relatórios, inclusive de meses anteriores) ou ativar/desativar."""
    cat = obter_do_escopo(db, Categoria, categoria_id, entidade.id)
    valores = dados.model_dump(exclude_unset=True)
    if valores.get("nome"):
        valores["nome"] = _nome_livre(db, entidade.id, valores["nome"], cat.id)
    for k, v in valores.items():
        if v is not None:
            setattr(cat, k, v)
    db.commit()
    lanc, tit = _uso_categorias(db, entidade.id)
    return _ler_categoria(cat, lanc, tit)


@router.delete("/{entidade_id}/categorias/{categoria_id}", status_code=204)
def remover_categoria(categoria_id: int, entidade: EntidadeDep, db: DB):
    """Só remove categoria sem uso; com uso, desative (preserva o histórico)."""
    cat = obter_do_escopo(db, Categoria, categoria_id, entidade.id)
    lanc, tit = _uso_categorias(db, entidade.id)
    if lanc.get(cat.id) or tit.get(cat.id):
        raise HTTPException(409, "Categoria em uso: desative em vez de excluir, para manter o histórico")
    db.delete(cat)
    db.commit()


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
    if not dados.padrao and not dados.contraparte_id:
        raise HTTPException(422, "Informe o trecho da descrição ou a contraparte")
    if dados.contraparte_id:
        obter_do_escopo(db, Contraparte, dados.contraparte_id, entidade.id)
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
