"""Comissões das produtoras: planos, metas, PL, apuração, painel, simulador, conta a pagar, demonstrativo e "Minha comissão"."""

from datetime import date
from decimal import Decimal

import httpx
from fastapi import APIRouter, HTTPException, Query, Response, UploadFile
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.deps import DB, EntidadeDep, UsuarioAtual, obter_do_escopo
from app.models import AjustePL, MetaComissao, PlanoComissao, Usuario
from app.services import comissao_produtor as cp
from app.services.demonstrativo import gerar_pdf as demonstrativo_pdf
from app.services.fechamento import extrair_id

router = APIRouter(prefix="/entidades/{entidade_id}", tags=["comissão das produtoras"])


class PlanoDados(BaseModel):
    produtor: str = Field(min_length=2)
    nome: str = Field(min_length=2)
    ativo: bool = True
    niveis: list[dict] = cp.NIVEIS_PADRAO
    regras: dict = cp.REGRAS_PADRAO
    aliases_indicacao: list[str] = []
    excluir_ramos: list[str] = []
    usa_planilha_saude: bool = False
    planilha_saude_id: str | None = None
    meses_para_pagar: int = Field(1, ge=0, le=3)
    contraparte_id: int | None = None
    categoria_id: int | None = None
    usuario_id: int | None = None


def _ler(p: PlanoComissao) -> dict:
    return {k: getattr(p, k) for k in ("id", *PlanoDados.model_fields)}


def _plano(db, entidade_id: int, plano_id: int) -> PlanoComissao:
    return obter_do_escopo(db, PlanoComissao, plano_id, entidade_id)


@router.get("/planos-comissao")
def listar(entidade: EntidadeDep, db: DB):
    return [_ler(p) for p in db.scalars(select(PlanoComissao).where(PlanoComissao.entidade_id == entidade.id).order_by(PlanoComissao.nome))]


@router.post("/planos-comissao/modelo")
def modelo(entidade: EntidadeDep, db: DB):
    """Cria Giovanna e Fabiana com as regras, os níveis e as metas de 2026 do script da planilha."""
    return [_ler(p) for p in cp.criar_planos_modelo(db, entidade.id)]


@router.post("/planos-comissao", status_code=201)
def criar(dados: PlanoDados, entidade: EntidadeDep, db: DB):
    p = PlanoComissao(entidade_id=entidade.id, **_normalizar(dados))
    db.add(p)
    db.commit()
    return _ler(p)


def _normalizar(d: PlanoDados) -> dict:
    v = d.model_dump()
    v["produtor"] = v["produtor"].strip().upper()
    v["aliases_indicacao"] = [a.strip().upper() for a in v["aliases_indicacao"] if a.strip()]
    v["excluir_ramos"] = [a.strip().upper() for a in v["excluir_ramos"] if a.strip()]
    if v["planilha_saude_id"]:
        v["planilha_saude_id"] = extrair_id(v["planilha_saude_id"])
    if len(v["niveis"]) != 5:
        raise HTTPException(422, "São 5 níveis: SEM META, BRONZE, PRATA, OURO e DIAMANTE")
    return v


@router.put("/planos-comissao/{plano_id}")
def atualizar(plano_id: int, dados: PlanoDados, entidade: EntidadeDep, db: DB):
    p = _plano(db, entidade.id, plano_id)
    for k, v in _normalizar(dados).items():
        setattr(p, k, v)
    if p.usuario_id and not db.get(Usuario, p.usuario_id):
        raise HTTPException(404, "Usuário não encontrado")
    db.commit()
    return _ler(p)


# --- metas e ajustes
class Meta(BaseModel):
    ano: int
    mes: int = Field(ge=1, le=12)
    tipo: str = Field(pattern="^(patrimonial|saude)$")
    faixas: list[Decimal] = Field(min_length=5, max_length=5)


@router.get("/planos-comissao/{plano_id}/metas")
def listar_metas(plano_id: int, entidade: EntidadeDep, db: DB, ano: int):
    _plano(db, entidade.id, plano_id)
    return [{"mes": m.mes, "tipo": m.tipo, "faixas": m.faixas} for m in db.scalars(
        select(MetaComissao).where(MetaComissao.plano_id == plano_id, MetaComissao.ano == ano).order_by(MetaComissao.mes))]


@router.put("/planos-comissao/{plano_id}/metas")
def salvar_meta(plano_id: int, dados: Meta, entidade: EntidadeDep, db: DB):
    _plano(db, entidade.id, plano_id)
    m = db.scalar(select(MetaComissao).where(MetaComissao.plano_id == plano_id, MetaComissao.ano == dados.ano,
                                             MetaComissao.mes == dados.mes, MetaComissao.tipo == dados.tipo))
    if not m:
        m = MetaComissao(plano_id=plano_id, ano=dados.ano, mes=dados.mes, tipo=dados.tipo)
        db.add(m)
    m.faixas = [float(x) for x in dados.faixas]
    db.commit()
    return {"ok": True}


class Ajuste(BaseModel):
    ano: int
    mes: int = Field(ge=1, le=12)
    valor: Decimal = Decimal("0")
    excluidos: list[str] = []


@router.put("/planos-comissao/{plano_id}/ajuste-pl")
def ajustar_pl(plano_id: int, dados: Ajuste, entidade: EntidadeDep, db: DB):
    _plano(db, entidade.id, plano_id)
    a = db.scalar(select(AjustePL).where(AjustePL.plano_id == plano_id, AjustePL.ano == dados.ano, AjustePL.mes == dados.mes))
    if not a:
        a = AjustePL(plano_id=plano_id, ano=dados.ano, mes=dados.mes)
        db.add(a)
    a.valor, a.excluidos = dados.valor, dados.excluidos
    db.commit()
    return {"ok": True}


# --- apuração
@router.get("/planos-comissao/{plano_id}/apuracao")
def apuracao(plano_id: int, entidade: EntidadeDep, db: DB, ano: int, mes: int = Query(ge=1, le=12)):
    return jsonable_encoder(cp.apurar(db, _plano(db, entidade.id, plano_id), ano, mes))


@router.get("/planos-comissao/{plano_id}/painel")
def painel(plano_id: int, entidade: EntidadeDep, db: DB, hoje: date | None = None):
    return jsonable_encoder(cp.painel(db, _plano(db, entidade.id, plano_id), hoje))


@router.get("/planos-comissao/{plano_id}/historico")
def historico(plano_id: int, entidade: EntidadeDep, db: DB, ano: int):
    return jsonable_encoder(cp.historico(db, _plano(db, entidade.id, plano_id), ano))


@router.get("/planos-comissao/{plano_id}/simular")
def simular(plano_id: int, entidade: EntidadeDep, db: DB, ano: int, mes: int = Query(ge=1, le=12),
            pl_extra: Decimal = Decimal("0"), comissao_extra: Decimal = Decimal("0")):
    return jsonable_encoder(cp.simular(db, _plano(db, entidade.id, plano_id), ano, mes, pl_extra, comissao_extra))


@router.post("/planos-comissao/{plano_id}/gerar-conta")
def gerar_conta(plano_id: int, entidade: EntidadeDep, db: DB, ano: int, mes: int = Query(ge=1, le=12)):
    return jsonable_encoder(cp.gerar_conta(db, _plano(db, entidade.id, plano_id), ano, mes))


@router.get("/planos-comissao/{plano_id}/demonstrativo")
def demonstrativo(plano_id: int, entidade: EntidadeDep, db: DB, ano: int, mes: int = Query(ge=1, le=12)):
    p = _plano(db, entidade.id, plano_id)
    return Response(demonstrativo_pdf(cp.apurar(db, p, ano, mes)), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="comissao-{p.produtor.lower()}-{ano}-{mes:02d}.pdf"'})


@router.post("/planos-comissao/{plano_id}/saude/sincronizar")
def sincronizar_saude(plano_id: int, entidade: EntidadeDep, db: DB, ano: int | None = None):
    try:
        return {"linhas": cp.sincronizar_saude(db, _plano(db, entidade.id, plano_id), ano)}
    except (ValueError, OSError, httpx.HTTPError) as e:
        raise HTTPException(422, str(e)) from e


@router.post("/planos-comissao/{plano_id}/saude/importar")
async def importar_saude(plano_id: int, arquivo: UploadFile, entidade: EntidadeDep, db: DB, ano: int | None = None):
    p = _plano(db, entidade.id, plano_id)
    try:
        linhas = cp.ler_planilha_saude(await arquivo.read(), ano or date.today().year)
    except (KeyError, ValueError, OSError) as e:
        raise HTTPException(422, f"Não consegui ler a planilha: {e}") from e
    return {"linhas": cp.gravar_planilha_saude(db, p, linhas)}


# --- "Minha comissão": a produtora vê só a dela
def _meu_plano(db, entidade_id: int, usuario: Usuario) -> PlanoComissao:
    p = db.scalar(select(PlanoComissao).where(PlanoComissao.entidade_id == entidade_id, PlanoComissao.usuario_id == usuario.id))
    if not p:
        raise HTTPException(404, "Seu usuário não está ligado a um plano de comissão")
    return p


@router.get("/minha-comissao")
def minha(entidade: EntidadeDep, db: DB, usuario: UsuarioAtual, ano: int | None = None, mes: int | None = Query(None, ge=1, le=12)):
    p = _meu_plano(db, entidade.id, usuario)
    h = date.today()
    return jsonable_encoder({"painel": cp.painel(db, p), "apuracao": cp.apurar(db, p, ano or h.year, mes or h.month),
                             "historico": cp.historico(db, p, ano or h.year)})


@router.get("/minha-comissao/simular")
def minha_simular(entidade: EntidadeDep, db: DB, usuario: UsuarioAtual, ano: int, mes: int = Query(ge=1, le=12),
                  pl_extra: Decimal = Decimal("0"), comissao_extra: Decimal = Decimal("0")):
    return jsonable_encoder(cp.simular(db, _meu_plano(db, entidade.id, usuario), ano, mes, pl_extra, comissao_extra))


@router.get("/minha-comissao/demonstrativo")
def minha_demonstrativo(entidade: EntidadeDep, db: DB, usuario: UsuarioAtual, ano: int, mes: int = Query(ge=1, le=12)):
    p = _meu_plano(db, entidade.id, usuario)
    return Response(demonstrativo_pdf(cp.apurar(db, p, ano, mes)), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="minha-comissao-{ano}-{mes:02d}.pdf"'})
