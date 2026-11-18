from datetime import date

from fastapi import APIRouter, HTTPException, UploadFile
from sqlalchemy import select

from app.deps import DB, EntidadeDep, obter_do_escopo
from app.models import (
    Categoria,
    ContaFinanceira,
    Importacao,
    OrigemTransacao,
    RegraCategorizacao,
    StatusTitulo,
    TipoConta,
    Titulo,
    Transacao,
)
from app.schemas import (
    ConciliacaoResultado,
    ImportacaoResultado,
    TituloLer,
    TransacaoAtualizar,
    TransacaoLer,
    VinculoManual,
)
from app.services.categorizacao import aplicar_regras
from app.services.conciliacao import candidatos, conciliar_entidade, vincular
from app.services.ofx import OFXInvalido, ler_ofx

router = APIRouter(prefix="/entidades/{entidade_id}", tags=["transacoes"])

TAMANHO_MAXIMO = 10 * 1024 * 1024


@router.get("/transacoes", response_model=list[TransacaoLer])
def listar(
    entidade: EntidadeDep,
    db: DB,
    conta_id: int | None = None,
    data_de: date | None = None,
    data_ate: date | None = None,
    conciliada: bool | None = None,
    sem_categoria: bool = False,
    limite: int = 1000,
):
    stmt = select(Transacao).join(ContaFinanceira).where(ContaFinanceira.entidade_id == entidade.id)
    if conta_id:
        stmt = stmt.where(Transacao.conta_id == conta_id)
    if data_de:
        stmt = stmt.where(Transacao.data >= data_de)
    if data_ate:
        stmt = stmt.where(Transacao.data <= data_ate)
    if conciliada is not None:
        stmt = stmt.where(Transacao.conciliada.is_(conciliada))
    if sem_categoria:
        stmt = stmt.where(Transacao.categoria_id.is_(None))
    return db.scalars(stmt.order_by(Transacao.data.desc(), Transacao.id.desc()).limit(limite)).all()


@router.patch("/transacoes/{transacao_id}", response_model=TransacaoLer)
def atualizar(transacao_id: int, dados: TransacaoAtualizar, entidade: EntidadeDep, db: DB):
    trn = obter_do_escopo(db, Transacao, transacao_id, entidade.id)
    if dados.categoria_id is not None:
        obter_do_escopo(db, Categoria, dados.categoria_id, entidade.id)
    trn.categoria_id = dados.categoria_id
    if dados.criar_regra and dados.categoria_id:
        db.add(RegraCategorizacao(entidade_id=entidade.id, padrao=trn.descricao[:160], categoria_id=dados.categoria_id))
    db.commit()
    return trn


@router.post("/transacoes/{transacao_id}/ignorar", response_model=TransacaoLer)
def ignorar(transacao_id: int, entidade: EntidadeDep, db: DB):
    """Marca como conciliada sem título (ex.: tarifa, transferência entre contas)."""
    trn = obter_do_escopo(db, Transacao, transacao_id, entidade.id)
    trn.conciliada = True
    db.commit()
    return trn


@router.post("/contas/{conta_id}/importar-ofx", response_model=ImportacaoResultado)
async def importar_ofx(conta_id: int, arquivo: UploadFile, entidade: EntidadeDep, db: DB):
    conta = obter_do_escopo(db, ContaFinanceira, conta_id, entidade.id)
    conteudo = await arquivo.read(TAMANHO_MAXIMO + 1)
    if len(conteudo) > TAMANHO_MAXIMO:
        raise HTTPException(413, "Arquivo maior que 10 MB")
    try:
        extrato = ler_ofx(conteudo)
    except OFXInvalido as e:
        raise HTTPException(422, str(e))

    if extrato.conta_id and conta.numero and _so_digitos(extrato.conta_id) != _so_digitos(conta.numero):
        raise HTTPException(
            422, f"O OFX é da conta {extrato.conta_id}, mas a conta selecionada é {conta.numero}"
        )
    if extrato.cartao and conta.tipo != TipoConta.CARTAO:
        raise HTTPException(422, "O OFX é de cartão de crédito; selecione uma conta do tipo cartão")
    if not conta.numero and extrato.conta_id:
        conta.numero = extrato.conta_id
    if not conta.banco_codigo and extrato.banco_id:
        conta.banco_codigo = extrato.banco_id

    existentes = set(
        db.scalars(
            select(Transacao.hash).where(
                Transacao.conta_id == conta.id, Transacao.hash.in_([t.hash for t in extrato.transacoes])
            )
        )
    )
    imp = Importacao(conta_id=conta.id, arquivo=arquivo.filename or "extrato.ofx", origem=OrigemTransacao.OFX)
    db.add(imp)
    db.flush()
    novas = 0
    for t in extrato.transacoes:
        if t.hash in existentes:
            continue
        db.add(
            Transacao(
                conta_id=conta.id,
                data=t.data,
                valor=t.valor,
                descricao=t.descricao,
                fitid=t.fitid,
                hash=t.hash,
                origem=OrigemTransacao.OFX,
                importacao_id=imp.id,
            )
        )
        existentes.add(t.hash)
        novas += 1
    imp.total_lidas = len(extrato.transacoes)
    imp.total_novas = novas
    db.commit()

    categorizadas = aplicar_regras(db, entidade.id)
    conc = conciliar_entidade(db, entidade.id)
    return ImportacaoResultado(
        importacao_id=imp.id,
        total_lidas=imp.total_lidas,
        total_novas=novas,
        duplicadas=imp.total_lidas - novas,
        categorizadas=categorizadas,
        conciliadas=conc.conciliadas,
        saldo_extrato=extrato.saldo,
    )


def _so_digitos(s: str) -> str:
    return "".join(c for c in s if c.isdigit()).lstrip("0")


@router.post("/conciliacao/automatica", response_model=ConciliacaoResultado)
def conciliar(entidade: EntidadeDep, db: DB, tolerancia_dias: int | None = None):
    r = conciliar_entidade(db, entidade.id, tolerancia_dias)
    return ConciliacaoResultado(conciliadas=r.conciliadas, ambiguas=r.ambiguas, sem_candidato=r.sem_candidato)


@router.get("/conciliacao/{transacao_id}/candidatos", response_model=list[TituloLer])
def listar_candidatos(transacao_id: int, entidade: EntidadeDep, db: DB, tolerancia_dias: int = 15):
    trn = obter_do_escopo(db, Transacao, transacao_id, entidade.id)
    return candidatos(db, entidade.id, trn, tolerancia_dias)


@router.post("/conciliacao/vincular", response_model=TituloLer)
def vincular_manual(dados: VinculoManual, entidade: EntidadeDep, db: DB):
    trn = obter_do_escopo(db, Transacao, dados.transacao_id, entidade.id)
    titulo = obter_do_escopo(db, Titulo, dados.titulo_id, entidade.id)
    if trn.conciliada:
        raise HTTPException(409, "Transação já conciliada")
    if titulo.status in (StatusTitulo.PAGO, StatusTitulo.CANCELADO):
        raise HTTPException(409, "Título já pago ou cancelado")
    if (trn.valor < 0) != (titulo.tipo.value == "pagar"):
        raise HTTPException(422, "Saída só concilia com título a pagar; entrada, com título a receber")
    valor = min(abs(trn.valor), titulo.saldo)
    vincular(db, trn, titulo, valor)
    db.commit()
    return titulo
