from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select

from fastapi import Request

from app.acesso import AREAS, somente_admin
from app.deps import DB, UsuarioAtual
from app.models import Usuario
from app.services import auditoria
from app.schemas import Token, UsuarioCriar, UsuarioLer
from app.security import criar_token, hash_senha, verificar_senha

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DB, request: Request):
    usuario = db.scalar(select(Usuario).where(Usuario.email == form.username.lower()))
    ip = request.client.host if request.client else None
    if not usuario or not usuario.ativo or not verificar_senha(form.password, usuario.senha_hash):
        auditoria.registrar("login_falhou", "/api/auth/login", usuario.id if usuario else None, "POST", 401, ip)
        raise HTTPException(401, "E-mail ou senha inválidos")
    auditoria.registrar("login", "/api/auth/login", usuario.id, "POST", 200, ip)
    return Token(access_token=criar_token(usuario.id))


@router.post("/primeiro-acesso", response_model=UsuarioLer, status_code=201)
def primeiro_acesso(dados: UsuarioCriar, db: DB):
    """Cria o usuário administrador. Só funciona enquanto não houver usuários."""
    if db.scalar(select(func.count(Usuario.id))):
        raise HTTPException(403, "Já existe usuário cadastrado")
    usuario = Usuario(nome=dados.nome, email=dados.email.lower(), senha_hash=hash_senha(dados.senha), papel="admin")
    db.add(usuario)
    db.commit()
    return usuario


@router.post("/usuarios", response_model=UsuarioLer, status_code=201, dependencies=[Depends(somente_admin)])
def criar_usuario(dados: UsuarioCriar, db: DB):
    if db.scalar(select(Usuario).where(Usuario.email == dados.email.lower())):
        raise HTTPException(409, "E-mail já cadastrado")
    usuario = Usuario(nome=dados.nome, email=dados.email.lower(), senha_hash=hash_senha(dados.senha))
    db.add(usuario)
    db.commit()
    return usuario


@router.get("/eu", response_model=UsuarioLer)
def eu(usuario: UsuarioAtual):
    """Usuário logado, com o que ele pode ver (o menu do sistema se monta por aqui)."""
    admin = usuario.papel == "admin"
    g = usuario.grupo
    return UsuarioLer(
        id=usuario.id, nome=usuario.nome, email=usuario.email, papel=usuario.papel,
        areas=list(AREAS) if admin else (g.areas if g else []), somente_leitura=not admin,
        grupo=g.nome if g else None,
    )
