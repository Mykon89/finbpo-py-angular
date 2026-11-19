"""Central de decisões, "O que o sistema aprendeu" e conexões bancárias."""

from datetime import UTC, date, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from app.deps import DB, EntidadeDep, UsuarioAtual, obter_do_escopo
from app.models import Categoria, ConexaoBancaria, Contraparte, Pendencia, RegraAprendida, RegraCategorizacao
from app.services import decisoes

router = APIRouter(prefix="/entidades/{entidade_id}", tags=["decisoes"])


class PendenciaLer(BaseModel):
    id: int
    tipo: str
    tipo_rotulo: str
    titulo: str
    descricao: str | None
    opcoes: list[dict]
    sugestao: str | None
    status: str
    ocorrencias: int
    criada_em: datetime
    resolvida_em: datetime | None
    resposta: dict | None


def _ler(p: Pendencia) -> PendenciaLer:
    return PendenciaLer(id=p.id, tipo=p.tipo, tipo_rotulo=decisoes.TIPOS.get(p.tipo, p.tipo), titulo=p.titulo, descricao=p.descricao,
                        opcoes=p.opcoes or [], sugestao=p.sugestao, status=p.status, ocorrencias=p.ocorrencias,
                        criada_em=p.criada_em, resolvida_em=p.resolvida_em, resposta=p.resposta)


@router.get("/pendencias", response_model=list[PendenciaLer])
def listar(entidade: EntidadeDep, db: DB, status: str = "aberta", tipo: str | None = None, limite: int = 300):
    stmt = select(Pendencia).where(Pendencia.entidade_id == entidade.id, Pendencia.status == status)
    if tipo:
        stmt = stmt.where(Pendencia.tipo == tipo)
    return [_ler(p) for p in db.scalars(stmt.order_by(Pendencia.criada_em.desc(), Pendencia.id.desc()).limit(limite))]


@router.get("/pendencias/resumo")
def resumo(entidade: EntidadeDep, db: DB):
    abertas = dict(db.execute(select(Pendencia.tipo, func.count(Pendencia.id)).where(
        Pendencia.entidade_id == entidade.id, Pendencia.status == "aberta").group_by(Pendencia.tipo)).all())
    inicio = datetime.combine(date.today().replace(day=1), datetime.min.time(), tzinfo=UTC)
    perguntas_mes = db.scalar(select(func.count(Pendencia.id)).where(Pendencia.entidade_id == entidade.id, Pendencia.criada_em >= inicio)) or 0
    automaticas = db.scalar(select(func.coalesce(func.sum(RegraAprendida.vezes_aplicada), 0)).where(
        RegraAprendida.entidade_id == entidade.id, RegraAprendida.ultima_aplicacao >= inicio)) or 0
    total = perguntas_mes + automaticas
    return {"abertas": sum(abertas.values()), "por_tipo": {decisoes.TIPOS.get(k, k): v for k, v in abertas.items()},
            "resolvidas_sozinho_no_mes": automaticas, "perguntas_no_mes": perguntas_mes,
            "automatico_pct": round(100 * automaticas / total) if total else None}


class Resposta(BaseModel):
    opcao: str
    valores: dict = {}
    sempre: bool = True


@router.post("/pendencias/{pendencia_id}/responder", response_model=PendenciaLer)
def responder(pendencia_id: int, dados: Resposta, entidade: EntidadeDep, db: DB, usuario: UsuarioAtual):
    p = obter_do_escopo(db, Pendencia, pendencia_id, entidade.id)
    return _ler(decisoes.responder(db, p, dados.opcao, dados.valores, dados.sempre, usuario.id))


@router.post("/pendencias/{pendencia_id}/descartar", response_model=PendenciaLer)
def descartar(pendencia_id: int, entidade: EntidadeDep, db: DB, usuario: UsuarioAtual):
    p = obter_do_escopo(db, Pendencia, pendencia_id, entidade.id)
    p.status, p.resolvida_em, p.resolvida_por = "descartada", datetime.now(UTC), usuario.id
    db.commit()
    return _ler(p)


@router.post("/pendencias/verificar")
def verificar(entidade: EntidadeDep, db: DB):
    """Roda agora as verificações (créditos x extratos, lançamentos sem categoria)."""
    rec = decisoes.conciliar_receber(db, entidade.id)
    grupos = decisoes.gerar_categorias(db, entidade.id)
    return {**rec, "grupos_sem_categoria": grupos}


# --- o que o sistema aprendeu
class Aprendido(BaseModel):
    id: str  # "a:<id>" regra aprendida / "c:<id>" regra de categorização
    tipo: str
    descricao: str
    ativa: bool
    vezes_aplicada: int | None
    criada_em: datetime | None


@router.get("/aprendizado", response_model=list[Aprendido])
def aprendizado(entidade: EntidadeDep, db: DB):
    saida = [
        Aprendido(id=f"a:{r.id}", tipo=decisoes.TIPOS.get(r.tipo, r.tipo.replace("_", " ")), descricao=r.descricao, ativa=r.ativa,
                  vezes_aplicada=r.vezes_aplicada, criada_em=r.criada_em)
        for r in db.scalars(select(RegraAprendida).where(RegraAprendida.entidade_id == entidade.id, RegraAprendida.tipo != "categoria")
                            .order_by(RegraAprendida.criada_em.desc()))
    ]
    cats = {c.id: c.nome for c in db.scalars(select(Categoria).where(Categoria.entidade_id == entidade.id))}
    cps = {c.id: c.nome for c in db.scalars(select(Contraparte).where(Contraparte.entidade_id == entidade.id))}
    for r in db.scalars(select(RegraCategorizacao).where(RegraCategorizacao.entidade_id == entidade.id)):
        quem = cps.get(r.contraparte_id) if r.contraparte_id else f'texto "{r.padrao}"'
        saida.append(Aprendido(id=f"c:{r.id}", tipo="Categoria de lançamento", descricao=f"{quem} → {cats.get(r.categoria_id, '?')}",
                               ativa=True, vezes_aplicada=None, criada_em=None))
    return saida


class AprendidoAlterar(BaseModel):
    ativa: bool


@router.patch("/aprendizado/{regra}", response_model=dict)
def alterar_aprendido(regra: str, dados: AprendidoAlterar, entidade: EntidadeDep, db: DB):
    tipo, _, id_ = regra.partition(":")
    if tipo != "a":
        raise HTTPException(422, "Regras de categorização se desligam excluindo")
    r = obter_do_escopo(db, RegraAprendida, int(id_), entidade.id)
    r.ativa = dados.ativa
    db.commit()
    return {"ok": True}


@router.delete("/aprendizado/{regra}", status_code=204)
def excluir_aprendido(regra: str, entidade: EntidadeDep, db: DB):
    tipo, _, id_ = regra.partition(":")
    modelo = RegraAprendida if tipo == "a" else RegraCategorizacao
    db.delete(obter_do_escopo(db, modelo, int(id_), entidade.id))
    db.commit()


# --- conexões bancárias (estrutura para Open Finance / API do banco)
@router.get("/conexoes-bancarias")
def conexoes(entidade: EntidadeDep, db: DB):
    return [
        {"id": c.id, "conta_id": c.conta_id, "provedor": c.provedor, "status": c.status, "ultima_sincronizacao": c.ultima_sincronizacao,
         "lido_ate": c.cursor, "consentimento_expira_em": c.consentimento_expira_em, "erro": c.erro}
        for c in db.scalars(select(ConexaoBancaria).where(ConexaoBancaria.entidade_id == entidade.id))
    ]
