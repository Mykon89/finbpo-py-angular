"""Administração: usuários, grupos de acesso, auditoria e direitos do titular (LGPD art. 18)."""

import re
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, or_, select

from app.acesso import AREAS, somente_admin
from app.cripto import e_cpf
from app.deps import DB
from app.models import Comissao, Contraparte, Entidade, EventoAuditoria, GrupoAcesso, PropostaFechamento, Transacao, Usuario
from app.security import hash_senha
from app.services import auditoria
from app.services.cnpj import so_digitos

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(somente_admin)])


# --- grupos
class GrupoDados(BaseModel):
    nome: str = Field(min_length=2, max_length=80)
    descricao: str | None = None
    areas: list[str] = []
    todas_entidades: bool = False
    entidades: list[int] = []

    @field_validator("areas")
    @classmethod
    def _areas(cls, v):
        invalidas = set(v) - set(AREAS)
        if invalidas:
            raise ValueError(f"Áreas inválidas: {', '.join(sorted(invalidas))}")
        return sorted(set(v))


class GrupoLer(GrupoDados):
    id: int
    usuarios: int = 0


@router.get("/areas")
def areas():
    return [{"codigo": k, "rotulo": v} for k, v in AREAS.items()]


def _ler_grupo(db, g: GrupoAcesso) -> GrupoLer:
    n = db.scalar(select(func.count(Usuario.id)).where(Usuario.grupo_id == g.id)) or 0
    return GrupoLer(id=g.id, nome=g.nome, descricao=g.descricao, areas=g.areas or [], todas_entidades=g.todas_entidades,
                    entidades=g.entidades or [], usuarios=n)


@router.get("/grupos", response_model=list[GrupoLer])
def listar_grupos(db: DB):
    return [_ler_grupo(db, g) for g in db.scalars(select(GrupoAcesso).order_by(GrupoAcesso.nome))]


@router.post("/grupos", response_model=GrupoLer, status_code=201)
def criar_grupo(dados: GrupoDados, db: DB):
    if db.scalar(select(GrupoAcesso).where(func.lower(GrupoAcesso.nome) == dados.nome.lower())):
        raise HTTPException(409, "Já existe um grupo com esse nome")
    g = GrupoAcesso(**dados.model_dump())
    db.add(g)
    db.commit()
    return _ler_grupo(db, g)


@router.put("/grupos/{grupo_id}", response_model=GrupoLer)
def atualizar_grupo(grupo_id: int, dados: GrupoDados, db: DB):
    g = db.get(GrupoAcesso, grupo_id) or _404("Grupo")
    for k, v in dados.model_dump().items():
        setattr(g, k, v)
    db.commit()
    auditoria._papeis.clear()
    return _ler_grupo(db, g)


@router.delete("/grupos/{grupo_id}", status_code=204)
def remover_grupo(grupo_id: int, db: DB):
    g = db.get(GrupoAcesso, grupo_id) or _404("Grupo")
    if db.scalar(select(func.count(Usuario.id)).where(Usuario.grupo_id == g.id)):
        raise HTTPException(409, "Há usuários neste grupo: mude-os de grupo antes")
    db.delete(g)
    db.commit()


# --- usuários
def _senha_forte(v: str) -> str:
    if len(v) < 10 or not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
        raise ValueError("A senha precisa de 10 caracteres ou mais, com letras e números")
    return v


class UsuarioNovo(BaseModel):
    nome: str = Field(min_length=2)
    email: EmailStr
    senha: str
    papel: str = Field("leitor", pattern="^(admin|leitor)$")
    grupo_id: int | None = None

    @field_validator("senha")
    @classmethod
    def _s(cls, v):
        return _senha_forte(v)


class UsuarioAlterar(BaseModel):
    nome: str | None = None
    papel: str | None = Field(None, pattern="^(admin|leitor)$")
    grupo_id: int | None = None
    ativo: bool | None = None
    senha: str | None = None

    @field_validator("senha")
    @classmethod
    def _s(cls, v):
        return _senha_forte(v) if v else v


class UsuarioAdmin(BaseModel):
    id: int
    nome: str
    email: str
    papel: str
    grupo_id: int | None
    ativo: bool
    criado_em: datetime


def _ler_usuario(u: Usuario) -> UsuarioAdmin:
    return UsuarioAdmin(id=u.id, nome=u.nome, email=u.email, papel=u.papel, grupo_id=u.grupo_id, ativo=u.ativo, criado_em=u.criado_em)


@router.get("/usuarios", response_model=list[UsuarioAdmin])
def listar_usuarios(db: DB):
    return [_ler_usuario(u) for u in db.scalars(select(Usuario).order_by(Usuario.nome))]


def _validar_papel(db, papel: str, grupo_id: int | None):
    if papel == "leitor" and not grupo_id:
        raise HTTPException(422, "Leitor precisa de um grupo de acesso")
    if grupo_id and not db.get(GrupoAcesso, grupo_id):
        raise HTTPException(404, "Grupo não encontrado")


@router.post("/usuarios", response_model=UsuarioAdmin, status_code=201)
def criar_usuario(dados: UsuarioNovo, db: DB):
    if db.scalar(select(Usuario).where(Usuario.email == dados.email.lower())):
        raise HTTPException(409, "E-mail já cadastrado")
    _validar_papel(db, dados.papel, dados.grupo_id)
    u = Usuario(nome=dados.nome, email=dados.email.lower(), senha_hash=hash_senha(dados.senha), papel=dados.papel,
                grupo_id=dados.grupo_id if dados.papel == "leitor" else None)
    db.add(u)
    db.commit()
    db.refresh(u)
    return _ler_usuario(u)


@router.patch("/usuarios/{usuario_id}", response_model=UsuarioAdmin)
def alterar_usuario(usuario_id: int, dados: UsuarioAlterar, db: DB, request: Request):
    u = db.get(Usuario, usuario_id) or _404("Usuário")
    v = dados.model_dump(exclude_unset=True)
    papel = v.get("papel", u.papel)
    grupo = v.get("grupo_id", u.grupo_id)
    _validar_papel(db, papel, grupo)
    if u.papel == "admin" and (papel != "admin" or v.get("ativo") is False):
        outros = db.scalar(select(func.count(Usuario.id)).where(Usuario.papel == "admin", Usuario.ativo.is_(True), Usuario.id != u.id))
        if not outros:
            raise HTTPException(409, "É preciso ter pelo menos um administrador ativo")
    if "senha" in v:
        senha = v.pop("senha")
        if senha:
            u.senha_hash = hash_senha(senha)
    for k, val in v.items():
        setattr(u, k, val)
    if u.papel == "admin":
        u.grupo_id = None
    db.commit()
    auditoria._papeis.pop(u.id, None)
    return _ler_usuario(u)


# --- auditoria
class EventoLer(BaseModel):
    id: int
    quando: datetime
    usuario: str | None
    acao: str
    metodo: str | None
    caminho: str
    entidade_id: int | None
    status: int | None
    ip: str | None
    detalhe: str | None


@router.get("/auditoria", response_model=list[EventoLer])
def listar_auditoria(db: DB, usuario_id: int | None = None, acao: str | None = None, de: date | None = None,
                     ate: date | None = None, limite: int = Query(200, le=2000)):
    stmt = select(EventoAuditoria, Usuario.nome).outerjoin(Usuario, Usuario.id == EventoAuditoria.usuario_id)
    if usuario_id:
        stmt = stmt.where(EventoAuditoria.usuario_id == usuario_id)
    if acao:
        stmt = stmt.where(EventoAuditoria.acao == acao)
    if de:
        stmt = stmt.where(EventoAuditoria.quando >= datetime.combine(de, datetime.min.time()))
    if ate:
        stmt = stmt.where(EventoAuditoria.quando < datetime.combine(ate, datetime.max.time()))
    linhas = db.execute(stmt.order_by(EventoAuditoria.id.desc()).limit(limite)).all()
    return [EventoLer(usuario=n, **{k: getattr(e, k) for k in EventoLer.model_fields if k != "usuario"}) for e, n in linhas]


# --- direitos do titular
def _consultas(busca: str):
    busca = (busca or "").strip()
    doc = so_digitos(busca)
    if e_cpf(doc):
        return {
            "contrapartes": select(Contraparte).where(Contraparte.documento == doc),
            "transacoes": select(Transacao).where(Transacao.contraparte_documento == doc),
            "comissoes": None,
            "propostas": None,
        }, doc
    if len(busca) < 5:
        raise HTTPException(422, "Informe o CPF ou pelo menos 5 letras do nome")
    termo = f"%{busca}%"
    return {
        "contrapartes": select(Contraparte).where(Contraparte.nome.ilike(termo)),
        "transacoes": select(Transacao).where(or_(Transacao.contraparte_nome.ilike(termo), Transacao.descricao.ilike(termo))),
        "comissoes": select(Comissao).where(Comissao.cliente.ilike(termo)),
        "propostas": select(PropostaFechamento).where(PropostaFechamento.cliente.ilike(termo)),
    }, None


_CAMPOS = {
    "contrapartes": ("id", "entidade_id", "nome", "documento"),
    "transacoes": ("id", "conta_id", "data", "valor", "descricao", "contraparte_nome", "contraparte_documento"),
    "comissoes": ("id", "entidade_id", "data", "seguradora", "ramo", "apolice", "cliente", "bruta"),
    "propostas": ("id", "entidade_id", "aba", "seguradora", "ramo", "cliente", "tipo", "com_bruta"),
}


def _dados(db, busca: str) -> dict:
    consultas, _ = _consultas(busca)
    saida = {}
    for nome, stmt in consultas.items():
        objs = db.scalars(stmt.limit(5000)).all() if stmt is not None else []
        saida[nome] = [{c: (str(getattr(o, c)) if getattr(o, c) is not None else None) for c in _CAMPOS[nome]} for o in objs]
    return saida


@router.get("/privacidade/titular")
def buscar_titular(busca: str, db: DB):
    """Onde aparecem os dados de uma pessoa (por CPF ou nome)."""
    d = _dados(db, busca)
    return {"busca": busca, "ocorrencias": {k: len(v) for k, v in d.items()}, "amostra": {k: v[:20] for k, v in d.items()}}


@router.get("/privacidade/titular/exportar")
def exportar_titular(busca: str, db: DB):
    """Cópia completa dos dados do titular (pedido de acesso/portabilidade)."""
    return {"gerado_em": datetime.now().isoformat(), "busca": busca, "dados": _dados(db, busca)}


class Anonimizar(BaseModel):
    busca: str
    confirmar: bool = False


@router.post("/privacidade/titular/anonimizar")
def anonimizar_titular(dados: Anonimizar, db: DB):
    """Troca nome e CPF do titular por um marcador em todos os registros (os valores financeiros ficam)."""
    if not dados.confirmar:
        raise HTTPException(422, "Confirme a anonimização (não pode ser desfeita)")
    consultas, _ = _consultas(dados.busca)
    marca = f"TITULAR ANONIMIZADO {datetime.now():%Y%m%d%H%M}"
    total = 0
    for nome, stmt in consultas.items():
        if stmt is None:
            continue
        for o in db.scalars(stmt):
            total += 1
            if nome == "contrapartes":
                o.nome, o.documento = marca, None
            elif nome == "transacoes":
                o.contraparte_nome, o.contraparte_documento = marca, None
            elif nome in ("comissoes", "propostas"):
                o.cliente = marca
    db.commit()
    return {"registros_anonimizados": total, "marcador": marca}


def _404(o: str):
    raise HTTPException(404, f"{o} não encontrado")
