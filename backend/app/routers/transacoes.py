from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, UploadFile
from sqlalchemy import select

from app.deps import DB, EntidadeDep, obter_do_escopo
from app.models import (
    Categoria,
    ContaFinanceira,
    Entidade,
    Importacao,
    OrigemTransacao,
    StatusTitulo,
    TipoConta,
    Titulo,
    Transacao,
)
from app.schemas import (
    AnaliseOFX,
    ComplementoResultado,
    ConciliacaoResultado,
    Categorizacao,
    ContaLer,
    SugestaoLer,
    ImportacaoResultado,
    TituloLer,
    TransacaoAtualizar,
    TransacaoLer,
    VinculoManual,
)
from app.services.categorizacao import aplicar_regras, criar_regra_de, sugerir
from app.services.complemento import ArquivoInvalido, ler_complemento
from app.services.conciliacao import candidatos, conciliar_entidade, vincular
from app.services.contrapartes import ResultadoComplemento, complementar, extrair_do_ofx
from app.services.bancos import nome_banco, normalizar_codigo
from app.services.cnpj import so_digitos
from app.services.ofx import ExtratoOFX, OFXInvalido, ler_ofx

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
        _categoria_ativa(db, dados.categoria_id, entidade.id)
    trn.categoria_id = dados.categoria_id
    trn.categoria_origem = "manual" if dados.categoria_id else None
    if dados.criar_regra and dados.categoria_id:
        criar_regra_de(db, entidade.id, trn, dados.categoria_id)
        db.flush()
        aplicar_regras(db, entidade.id)  # aplica a nova regra aos demais pendentes
    db.commit()
    return trn


def _categoria_ativa(db, categoria_id: int, entidade_id: int) -> Categoria:
    cat = obter_do_escopo(db, Categoria, categoria_id, entidade_id)
    if not cat.ativo:
        raise HTTPException(422, f"A categoria '{cat.nome}' está desativada")
    return cat


@router.get("/categorizacao/sugestoes", response_model=list[SugestaoLer])
def sugestoes(entidade: EntidadeDep, db: DB):
    """Sugestões aprendidas com o histórico (mesma contraparte ou descrição parecida). Não grava nada."""
    return [SugestaoLer(**s.__dict__) for s in sugerir(db, entidade.id)]


@router.post("/categorizacao/aplicar")
def aplicar_categorias(dados: Categorizacao, entidade: EntidadeDep, db: DB):
    """Grava categorias em lote (aceite de sugestões, ou categorização feita pelo Claude via MCP)."""
    return {"alteradas": categorizar_lote(db, entidade.id, dados.itens, dados.origem)}


def categorizar_lote(db, entidade_id: int, itens, origem: str) -> int:
    alteradas = 0
    for item in itens:
        trn = obter_do_escopo(db, Transacao, item.transacao_id, entidade_id)
        _categoria_ativa(db, item.categoria_id, entidade_id)
        trn.categoria_id = item.categoria_id
        trn.categoria_origem = origem
        if item.criar_regra:
            criar_regra_de(db, entidade_id, trn, item.categoria_id)
            db.flush()
        alteradas += 1
    db.commit()
    aplicar_regras(db, entidade_id)
    return alteradas


@router.post("/transacoes/{transacao_id}/ignorar", response_model=TransacaoLer)
def ignorar(transacao_id: int, entidade: EntidadeDep, db: DB):
    """Marca como conciliada sem título (ex.: tarifa, transferência entre contas)."""
    trn = obter_do_escopo(db, Transacao, transacao_id, entidade.id)
    trn.conciliada = True
    db.commit()
    return trn


async def _ler_arquivo(arquivo: UploadFile) -> ExtratoOFX:
    conteudo = await arquivo.read(TAMANHO_MAXIMO + 1)
    if len(conteudo) > TAMANHO_MAXIMO:
        raise HTTPException(413, "Arquivo maior que 10 MB")
    try:
        return ler_ofx(conteudo)
    except OFXInvalido as e:
        raise HTTPException(422, str(e))


def _num(s: str | None) -> str:
    return so_digitos(s or "").lstrip("0")


def _mesma_conta(conta: ContaFinanceira, extrato: ExtratoOFX) -> bool:
    if not extrato.conta_id or _num(conta.numero) != _num(extrato.conta_id):
        return False
    banco = normalizar_codigo(extrato.banco_id)
    return not (banco and conta.banco_codigo and normalizar_codigo(conta.banco_codigo) != banco)


def _contas_do_extrato(db, extrato: ExtratoOFX) -> list[ContaFinanceira]:
    if not extrato.conta_id:
        return []
    return [c for c in db.scalars(select(ContaFinanceira).where(ContaFinanceira.numero.is_not(None))) if _mesma_conta(c, extrato)]


def _sugestao(extrato: ExtratoOFX) -> tuple[TipoConta, str, Decimal]:
    tipo = TipoConta.CARTAO if extrato.cartao else TipoConta.CORRENTE
    banco = nome_banco(extrato.banco_id) or extrato.instituicao or "Banco"
    numero = extrato.conta_id or ""
    if tipo == TipoConta.CARTAO:
        nome = f"Cartão {banco} final {_num(numero)[-4:]}" if numero else f"Cartão {banco}"
    else:
        partes = [banco]
        if extrato.agencia:
            partes.append(f"Ag {extrato.agencia}")
        if numero:
            partes.append(f"C/C {numero}")
        nome = " ".join(partes)
    # Saldo antes do 1º lançamento do arquivo, para o saldo do sistema bater com o do banco
    saldo_inicial = Decimal("0")
    if extrato.saldo is not None:
        saldo_inicial = extrato.saldo - sum((t.valor for t in extrato.transacoes), Decimal("0"))
    return tipo, nome[:120], saldo_inicial


def _gravar(db, entidade_id: int, conta: ContaFinanceira, extrato: ExtratoOFX, arquivo: str) -> ImportacaoResultado:
    if extrato.conta_id and conta.numero and _num(extrato.conta_id) != _num(conta.numero):
        raise HTTPException(422, f"O OFX é da conta {extrato.conta_id}, mas a conta selecionada é {conta.numero}")
    if extrato.cartao and conta.tipo != TipoConta.CARTAO:
        raise HTTPException(422, "O OFX é de cartão de crédito; selecione uma conta do tipo cartão")
    if not conta.numero and extrato.conta_id:
        conta.numero = extrato.conta_id
    if not conta.banco_codigo and normalizar_codigo(extrato.banco_id):
        conta.banco_codigo = normalizar_codigo(extrato.banco_id)
    if not conta.agencia and extrato.agencia:
        conta.agencia = extrato.agencia

    existentes = set(
        db.scalars(
            select(Transacao.hash).where(
                Transacao.conta_id == conta.id, Transacao.hash.in_([t.hash for t in extrato.transacoes])
            )
        )
    )
    imp = Importacao(conta_id=conta.id, arquivo=arquivo, origem=OrigemTransacao.OFX)
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
    db.flush()
    com_doc = extrair_do_ofx(db, entidade_id, list(db.scalars(select(Transacao).where(Transacao.importacao_id == imp.id))))
    db.commit()

    categorizadas = aplicar_regras(db, entidade_id)
    conc = conciliar_entidade(db, entidade_id)
    return ImportacaoResultado(
        importacao_id=imp.id,
        conta_id=conta.id,
        conta_nome=conta.nome,
        total_lidas=imp.total_lidas,
        total_novas=novas,
        duplicadas=imp.total_lidas - novas,
        categorizadas=categorizadas,
        conciliadas=conc.conciliadas,
        saldo_extrato=extrato.saldo,
        com_documento_no_ofx=com_doc,
    )


async def _complementar(db, entidade_id: int, conta: ContaFinanceira, arquivos: list[UploadFile], ano: int | None):
    res = ResultadoComplemento()
    for arq in arquivos:
        nome = arq.filename or "arquivo"
        conteudo = await arq.read(TAMANHO_MAXIMO + 1)
        if len(conteudo) > TAMANHO_MAXIMO:
            res.erros.append(f"{nome}: maior que 10 MB")
            continue
        try:
            linhas = ler_complemento(nome, conteudo, ano)
        except ArquivoInvalido as e:
            res.erros.append(f"{nome}: {e}")
            continue
        res.arquivos.append(nome)
        # Cada arquivo é casado separadamente: XLSX e PDF do mesmo período se somam
        r = complementar(db, entidade_id, conta, linhas)
        res.linhas_lidas += r.linhas_lidas
        res.enriquecidas += r.enriquecidas
        res.sem_correspondencia += r.sem_correspondencia
        res.contrapartes_criadas += r.contrapartes_criadas
    aplicar_regras(db, entidade_id)
    conciliar_entidade(db, entidade_id)
    return ComplementoResultado(**res.__dict__)


@router.post("/contas/{conta_id}/complementar", response_model=ComplementoResultado)
async def complementar_conta(conta_id: int, arquivos: list[UploadFile], entidade: EntidadeDep, db: DB):
    """Completa lançamentos já importados com nome/CPF/CNPJ vindos de XLSX, XLS, CSV ou PDF do banco."""
    conta = obter_do_escopo(db, ContaFinanceira, conta_id, entidade.id)
    return await _complementar(db, entidade.id, conta, arquivos, None)


@router.post("/contas/{conta_id}/importar-ofx", response_model=ImportacaoResultado)
async def importar_ofx(conta_id: int, arquivo: UploadFile, entidade: EntidadeDep, db: DB):
    conta = obter_do_escopo(db, ContaFinanceira, conta_id, entidade.id)
    extrato = await _ler_arquivo(arquivo)
    return _gravar(db, entidade.id, conta, extrato, arquivo.filename or "extrato.ofx")


@router.post("/ofx/analisar", response_model=AnaliseOFX)
async def analisar_ofx(arquivo: UploadFile, entidade: EntidadeDep, db: DB):
    """Lê o OFX sem gravar: identifica banco e conta e diz se a conta já existe."""
    extrato = await _ler_arquivo(arquivo)
    tipo, nome, saldo_inicial = _sugestao(extrato)
    contas = _contas_do_extrato(db, extrato)
    desta = next((c for c in contas if c.entidade_id == entidade.id), None)
    outra = next((c for c in contas if c.entidade_id != entidade.id), None)
    datas = [t.data for t in extrato.transacoes]
    return AnaliseOFX(
        banco_codigo=normalizar_codigo(extrato.banco_id),
        banco_nome=nome_banco(extrato.banco_id) or extrato.instituicao,
        agencia=extrato.agencia,
        numero=extrato.conta_id,
        tipo=tipo,
        inicio=extrato.inicio or (min(datas) if datas else None),
        fim=extrato.fim or (max(datas) if datas else None),
        total_transacoes=len(extrato.transacoes),
        saldo_extrato=extrato.saldo,
        data_saldo=extrato.data_saldo,
        conta_existente=ContaLer.model_validate(desta) if desta else None,
        outra_entidade=db.get(Entidade, outra.entidade_id).nome if outra and not desta else None,
        sugestao_nome=nome,
        sugestao_saldo_inicial=saldo_inicial,
    )


@router.post("/ofx/importar", response_model=ImportacaoResultado)
async def importar_ofx_auto(
    arquivo: UploadFile,
    entidade: EntidadeDep,
    db: DB,
    conta_id: Annotated[int | None, Form()] = None,
    nome: Annotated[str | None, Form(max_length=120)] = None,
    saldo_inicial: Annotated[Decimal | None, Form()] = None,
    complementos: list[UploadFile] | None = None,
):
    """Importa o OFX na conta informada, na conta já reconhecida pelo número ou numa conta nova.

    `complementos`: XLSX/XLS/CSV/PDF do mesmo período, usados para completar nome e CPF/CNPJ.
    """
    extrato = await _ler_arquivo(arquivo)
    ano = (extrato.fim or extrato.inicio).year if (extrato.fim or extrato.inicio) else None
    if conta_id:
        conta = obter_do_escopo(db, ContaFinanceira, conta_id, entidade.id)
    else:
        conta = next((c for c in _contas_do_extrato(db, extrato) if c.entidade_id == entidade.id), None)
        if conta is None:
            if not extrato.conta_id:
                raise HTTPException(422, "O OFX não informa o número da conta; escolha a conta manualmente")
            tipo, sugestao, saldo = _sugestao(extrato)
            conta = ContaFinanceira(
                entidade_id=entidade.id,
                tipo=tipo,
                nome=(nome or "").strip() or sugestao,
                banco_codigo=normalizar_codigo(extrato.banco_id),
                agencia=extrato.agencia,
                numero=extrato.conta_id,
                saldo_inicial=saldo if saldo_inicial is None else saldo_inicial,
            )
            db.add(conta)
            db.flush()
            resultado = _gravar(db, entidade.id, conta, extrato, arquivo.filename or "extrato.ofx")
            resultado.conta_criada = True
            if complementos:
                resultado.complemento = await _complementar(db, entidade.id, conta, complementos, ano)
            return resultado
    resultado = _gravar(db, entidade.id, conta, extrato, arquivo.filename or "extrato.ofx")
    if complementos:
        resultado.complemento = await _complementar(db, entidade.id, conta, complementos, ano)
    return resultado


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
