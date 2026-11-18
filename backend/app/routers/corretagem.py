"""Comissões de seguradoras (BASE/RECEBER da planilha), recorrências e painel do contas a pagar."""

import calendar

import httpx
from dataclasses import asdict
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.deps import DB, EntidadeDep, obter_do_escopo
from app.models import (
    Baixa,
    Categoria,
    CentroCusto,
    Comissao,
    Contraparte,
    ExtratoComissao,
    Recorrencia,
    StatusTitulo,
    TipoTitulo,
    Titulo,
)
from app.schemas import (
    ComissaoAtualizar,
    ComissaoLer,
    Comparativo,
    ExtratoComissaoLer,
    ExtratoImportado,
    FechamentoConfig,
    FechamentoStatus,
    PrevisaoLer,
    ImportacaoPlanilha,
    LinhaComparativo,
    PainelPagar,
    RecorrenciaAtualizar,
    RecorrenciaCriar,
    RecorrenciaLer,
    TituloLer,
)
from app.config import settings
from app.models import PropostaFechamento
from app.services import comissoes, extratos_seguradoras, fechamento, planilha, previsao, recorrencias

router = APIRouter(prefix="/entidades/{entidade_id}", tags=["corretagem"])

_ABERTOS = (StatusTitulo.ABERTO, StatusTitulo.PARCIAL)


def _mes(texto: str) -> tuple[date, date]:
    try:
        ano, mes = (int(x) for x in texto.split("-"))
        inicio = date(ano, mes, 1)
    except ValueError as e:
        raise HTTPException(422, "Mês no formato AAAA-MM") from e
    return inicio, date(ano + mes // 12, mes % 12 + 1, 1)


def _rotulo(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


# --- importação da planilha
@router.post("/importar-planilha", response_model=ImportacaoPlanilha)
async def importar_planilha(arquivo: UploadFile, entidade: EntidadeDep, db: DB):
    """Migra a planilha do Google Sheets (baixada em .xlsx). Pode reimportar: nada é duplicado."""
    if not (arquivo.filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(422, "Envie a planilha em .xlsx (Google Sheets: Arquivo → Fazer download → .xlsx)")
    try:
        res = planilha.importar(db, entidade.id, await arquivo.read())
        previsao.classificar_novos(db, entidade.id)
    except (KeyError, ValueError, OSError) as e:
        raise HTTPException(422, f"Não consegui ler a planilha: {e}") from e
    return ImportacaoPlanilha(**asdict(res))


@router.post("/extratos-comissao/importar", response_model=list[ExtratoImportado])
async def importar_extratos(arquivos: list[UploadFile], entidade: EntidadeDep, db: DB):
    """Extratos das seguradoras (Porto .do, Bradesco/Odontoprev TXT, MAG CSV, Azos XLSX, Sura/AKAD/Allianz PDF).
    O formato é reconhecido pelo conteúdo; extrato já importado é ignorado."""
    saida: list[ExtratoImportado] = []
    for arq in arquivos:
        nome = arq.filename or "arquivo"
        try:
            lidos = extratos_seguradoras.ler(await arq.read(), nome)
        except (ValueError, KeyError, IndexError) as e:
            saida.append(ExtratoImportado(arquivo=nome, erro=str(e)))
            continue
        saida += [ExtratoImportado(**asdict(r)) for r in comissoes.gravar(db, entidade.id, lidos, nome)]
    previsao.classificar_novos(db, entidade.id)
    return saida


# --- FECHAMENTO DE PROPOSTAS (Google Sheets)
def _status(db, entidade, leitura=None, novos=None) -> FechamentoStatus:
    qtd = db.scalar(select(func.count(PropostaFechamento.id)).where(PropostaFechamento.entidade_id == entidade.id)) or 0
    return FechamentoStatus(
        planilha_id=entidade.fechamento_planilha_id, sincronizado_em=entidade.fechamento_sincronizado_em, propostas=qtd,
        conta_servico=bool(settings.google_service_account_file), abas=leitura.abas if leitura else [],
        avisos=leitura.avisos if leitura else [], novos_negocios=novos,
    )


@router.get("/fechamento", response_model=FechamentoStatus)
def status_fechamento(entidade: EntidadeDep, db: DB):
    return _status(db, entidade)


@router.put("/fechamento", response_model=FechamentoStatus)
def configurar_fechamento(dados: FechamentoConfig, entidade: EntidadeDep, db: DB):
    entidade.fechamento_planilha_id = fechamento.extrair_id(dados.planilha) if dados.planilha else None
    db.commit()
    return _status(db, entidade)


@router.post("/fechamento/sincronizar", response_model=FechamentoStatus)
def sincronizar_fechamento(entidade: EntidadeDep, db: DB):
    """Baixa a planilha do Google e atualiza as propostas (vínculo e novo negócio passam a usá-las)."""
    try:
        leitura = fechamento.sincronizar(db, entidade)
    except (ValueError, OSError, httpx.HTTPError) as e:
        raise HTTPException(422, str(e)) from e
    return _status(db, entidade, leitura, previsao.classificar_novos(db, entidade.id))


@router.post("/fechamento/importar", response_model=FechamentoStatus)
async def importar_fechamento(arquivo: UploadFile, entidade: EntidadeDep, db: DB):
    """Alternativa sem Google: sobe o .xlsx da planilha FECHAMENTO."""
    try:
        leitura = fechamento.ler_xlsx(await arquivo.read())
    except (KeyError, ValueError, OSError) as e:
        raise HTTPException(422, f"Não consegui ler a planilha: {e}") from e
    fechamento.gravar(db, entidade, leitura)
    return _status(db, entidade, leitura, previsao.classificar_novos(db, entidade.id))


@router.get("/comissoes/previsao", response_model=PrevisaoLer)
def previsao_recebimentos(entidade: EntidadeDep, db: DB, meses: int = Query(6, ge=1, le=24), hoje: date | None = None):
    """Parcelas restantes (n/total), comissões recorrentes (saúde/odonto/vida) e propostas fechadas ainda sem comissão."""
    p = previsao.prever(db, entidade.id, meses, hoje)
    return PrevisaoLer(meses=p.meses, itens=[asdict(i) for i in p.itens], atrasados=[asdict(i) for i in p.atrasados])


# --- comissões
@router.get("/comissoes", response_model=list[ComissaoLer])
def listar_comissoes(
    entidade: EntidadeDep,
    db: DB,
    mes: str | None = None,
    seguradora: str | None = None,
    ramo: str | None = None,
    extrato_id: int | None = None,
    busca: str | None = None,
    sem_vinculo: bool = False,
    limite: int = Query(2000, le=10000),
):
    stmt = select(Comissao).where(Comissao.entidade_id == entidade.id)
    if mes:
        ini, fim = _mes(mes)
        stmt = stmt.where(Comissao.data >= ini, Comissao.data < fim)
    if seguradora:
        stmt = stmt.where(Comissao.seguradora == seguradora.upper())
    if ramo:
        stmt = stmt.where(Comissao.ramo == ramo.upper())
    if extrato_id:
        stmt = stmt.where(Comissao.extrato_id == extrato_id)
    if busca:
        termo = f"%{busca}%"
        stmt = stmt.where(or_(Comissao.cliente.ilike(termo), Comissao.apolice.ilike(termo)))
    if sem_vinculo:
        stmt = stmt.where(Comissao.produtor.is_(None), Comissao.parceiro.is_(None))
    return db.scalars(stmt.order_by(Comissao.data, Comissao.seguradora, Comissao.id).limit(limite)).all()


@router.patch("/comissoes/{comissao_id}", response_model=ComissaoLer)
def atualizar_comissao(comissao_id: int, dados: ComissaoAtualizar, entidade: EntidadeDep, db: DB):
    c = obter_do_escopo(db, Comissao, comissao_id, entidade.id)
    for k, v in dados.model_dump(exclude_unset=True).items():
        setattr(c, k, v if k == "observacao" else ((v or "").strip().upper() or None))
    db.commit()
    return c


def _linhas_comparativo(ant: dict, atu: dict) -> list[LinhaComparativo]:
    saida = []
    for k in sorted(set(ant) | set(atu)):
        a = ant.get(k, {}).get("bruta", Decimal(0))
        b = atu.get(k, {}).get("bruta", Decimal(0))
        saida.append(
            LinhaComparativo(
                chave=k,
                anterior=a,
                atual=b,
                variacao=b - a,
                variacao_pct=float((b - a) / abs(a)) if a else None,
                qtd=atu.get(k, {}).get("qtd", 0),
            )
        )
    return sorted(saida, key=lambda x: -x.atual)


@router.get("/comissoes/comparativo", response_model=Comparativo)
def comparativo(entidade: EntidadeDep, db: DB, mes: str):
    """Mês escolhido x mês anterior, por ramo e por seguradora (como a aba COMPARATIVO)."""
    ini, fim = _mes(mes)
    ini_ant = (ini - timedelta(days=1)).replace(day=1)
    if db.scalar(select(Comissao.id).where(Comissao.entidade_id == entidade.id, Comissao.novo_negocio.is_(None)).limit(1)):
        previsao.classificar_novos(db, entidade.id)  # dados de antes desta versão
    ramo_ant = planilha.resumo_por(db, entidade.id, Comissao.ramo, ini_ant, ini)
    ramo_atu = planilha.resumo_por(db, entidade.id, Comissao.ramo, ini, fim)
    seg_ant = planilha.resumo_por(db, entidade.id, Comissao.seguradora, ini_ant, ini)
    seg_atu = planilha.resumo_por(db, entidade.id, Comissao.seguradora, ini, fim)
    no_mes = (Comissao.entidade_id == entidade.id, Comissao.data >= ini, Comissao.data < fim)
    novos_qtd, novos_valor = db.execute(
        select(func.count(Comissao.id), func.coalesce(func.sum(Comissao.bruta), 0)).where(*no_mes, Comissao.novo_negocio.is_(True))
    ).one()
    sem_vinculo = db.scalar(
        select(func.count(Comissao.id)).where(*no_mes, Comissao.produtor.is_(None), Comissao.parceiro.is_(None))
    )
    return Comparativo(
        mes=_rotulo(ini),
        anterior=_rotulo(ini_ant),
        por_ramo=_linhas_comparativo(ramo_ant, ramo_atu),
        por_seguradora=_linhas_comparativo(seg_ant, seg_atu),
        total_anterior=sum((v["bruta"] for v in ramo_ant.values()), Decimal(0)),
        total_atual=sum((v["bruta"] for v in ramo_atu.values()), Decimal(0)),
        imposto_atual=sum((v["imposto"] for v in ramo_atu.values()), Decimal(0)),
        liquido_atual=sum((v["liquida"] for v in ramo_atu.values()), Decimal(0)),
        novos_qtd=novos_qtd,
        novos_valor=Decimal(str(novos_valor)),
        sem_vinculo=sem_vinculo or 0,
    )


@router.get("/extratos-comissao", response_model=list[ExtratoComissaoLer])
def listar_extratos(entidade: EntidadeDep, db: DB, mes: str | None = None, situacao: str | None = None):
    stmt = select(ExtratoComissao).where(ExtratoComissao.entidade_id == entidade.id)
    if mes:
        ini, fim = _mes(mes)
        stmt = stmt.where(ExtratoComissao.data >= ini, ExtratoComissao.data < fim)
    extratos = db.scalars(stmt.order_by(ExtratoComissao.data, ExtratoComissao.seguradora)).all()
    qtd = dict(
        db.execute(
            select(Comissao.extrato_id, func.count(Comissao.id))
            .where(Comissao.extrato_id.in_([e.id for e in extratos]))
            .group_by(Comissao.extrato_id)
        ).all()
    )
    saida = []
    for e in extratos:
        if e.recebido_valor is None:
            sit = "A RECEBER"
        elif abs(e.recebido_valor - e.liquido) <= Decimal("0.05"):
            sit = "RECEBIDO"
        else:
            sit = "DIVERGENTE"
        item = ExtratoComissaoLer.model_validate(e).model_copy(update={"linhas": qtd.get(e.id, 0), "situacao": sit})
        if not situacao or situacao.upper() == sit:
            saida.append(item)
    return saida


# --- recorrências
def _validar(db, entidade_id: int, dados) -> None:
    for campo, modelo in (("categoria_id", Categoria), ("contraparte_id", Contraparte), ("centro_custo_id", CentroCusto)):
        v = getattr(dados, campo, None)
        if v is not None:
            obter_do_escopo(db, modelo, v, entidade_id)


def _resolver_contraparte(db, entidade_id: int, valores: dict) -> None:
    nome = " ".join((valores.pop("contraparte_nome", None) or "").split())
    if nome and not valores.get("contraparte_id"):
        cp = db.scalar(
            select(Contraparte).where(Contraparte.entidade_id == entidade_id, func.upper(Contraparte.nome) == nome.upper())
        )
        if not cp:
            cp = Contraparte(entidade_id=entidade_id, nome=nome.upper())
            db.add(cp)
            db.flush()
        valores["contraparte_id"] = cp.id


def _ler_rec(r: Recorrencia) -> RecorrenciaLer:
    prox = None
    if r.ativa:
        hoje = date.today()
        futuras = [d for _, d in recorrencias.ocorrencias(r, hoje + timedelta(days=800)) if d >= hoje]
        prox = recorrencias.ajustar(futuras[0], r.ajuste) if futuras else None
    return RecorrenciaLer.model_validate(r).model_copy(
        update={"proximo_vencimento": prox, "contraparte_nome": r.contraparte.nome if r.contraparte else None}
    )


@router.get("/recorrencias", response_model=list[RecorrenciaLer])
def listar_recorrencias(entidade: EntidadeDep, db: DB):
    recs = db.scalars(
        select(Recorrencia).where(Recorrencia.entidade_id == entidade.id).order_by(Recorrencia.ativa.desc(), Recorrencia.descricao)
    ).all()
    return [_ler_rec(r) for r in recs]


@router.post("/recorrencias", response_model=RecorrenciaLer, status_code=201)
def criar_recorrencia(dados: RecorrenciaCriar, entidade: EntidadeDep, db: DB):
    _validar(db, entidade.id, dados)
    total = db.scalar(select(func.count(Recorrencia.id)).where(Recorrencia.entidade_id == entidade.id)) or 0
    valores = dados.model_dump()
    _resolver_contraparte(db, entidade.id, valores)
    r = Recorrencia(entidade_id=entidade.id, codigo=f"R{total + 1:03d}", **valores)
    db.add(r)
    db.commit()
    return _ler_rec(r)


@router.patch("/recorrencias/{recorrencia_id}", response_model=RecorrenciaLer)
def atualizar_recorrencia(recorrencia_id: int, dados: RecorrenciaAtualizar, entidade: EntidadeDep, db: DB):
    r = obter_do_escopo(db, Recorrencia, recorrencia_id, entidade.id)
    _validar(db, entidade.id, dados)
    valores = dados.model_dump(exclude_unset=True)
    _resolver_contraparte(db, entidade.id, valores)
    for k, v in valores.items():
        setattr(r, k, v)
    db.commit()
    return _ler_rec(r)


@router.delete("/recorrencias/{recorrencia_id}", status_code=204)
def remover_recorrencia(recorrencia_id: int, entidade: EntidadeDep, db: DB):
    """Remove o modelo; títulos já gerados continuam (desvinculados)."""
    db.delete(obter_do_escopo(db, Recorrencia, recorrencia_id, entidade.id))
    db.commit()


@router.post("/recorrencias/gerar", response_model=list[TituloLer])
def gerar_recorrencias(entidade: EntidadeDep, db: DB, ate: date | None = None, recorrencia_id: int | None = None):
    """Cria as contas que faltam até a data (padrão: fim do mês seguinte)."""
    if ate is None:
        hoje = date.today()
        ano, mes = (hoje.year + 1, 1) if hoje.month == 12 else (hoje.year, hoje.month + 1)
        ate = date(ano, mes, calendar.monthrange(ano, mes)[1])
    novos = recorrencias.gerar(db, entidade.id, ate, recorrencia_id)
    db.commit()
    return novos


# --- painel do contas a pagar (aba PAINEL)
@router.get("/painel-pagar", response_model=PainelPagar)
def painel_pagar(entidade: EntidadeDep, db: DB, dias: int = Query(7, ge=0, le=3650), hoje: date | None = None):
    hoje = hoje or date.today()
    fim_mes = date(hoje.year, hoje.month, calendar.monthrange(hoje.year, hoje.month)[1])
    titulos = db.scalars(
        select(Titulo)
        .options(selectinload(Titulo.baixas))
        .where(Titulo.entidade_id == entidade.id, Titulo.tipo == TipoTitulo.PAGAR, Titulo.status.in_(_ABERTOS))
        .order_by(Titulo.vencimento, Titulo.id)
    ).all()
    limite = hoje + timedelta(days=dias)

    def soma(cond) -> Decimal:
        return sum((t.saldo for t in titulos if cond(t)), Decimal(0))

    ini_mes = hoje.replace(day=1)
    pago_no_mes = db.scalar(
        select(func.coalesce(func.sum(Baixa.valor), 0))
        .join(Titulo)
        .where(
            Titulo.entidade_id == entidade.id,
            Titulo.tipo == TipoTitulo.PAGAR,
            Baixa.data >= ini_mes,
            Baixa.data <= fim_mes,
        )
    )
    return PainelPagar(
        vence_hoje=soma(lambda t: t.vencimento == hoje),
        atrasado=soma(lambda t: t.vencimento < hoje),
        proximos_dias=soma(lambda t: hoje < t.vencimento <= hoje + timedelta(days=7)),
        aberto_ate_fim_mes=soma(lambda t: hoje <= t.vencimento <= fim_mes),
        pago_no_mes=Decimal(str(pago_no_mes)),
        dias=dias,
        titulos=[t for t in titulos if t.vencimento <= limite],
    )
