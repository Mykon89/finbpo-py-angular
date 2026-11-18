from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select

from app.deps import DB, UsuarioAtual
from app.models import Usuario
from app.schemas import Token, UsuarioCriar, UsuarioLer
from app.security import criar_token, hash_senha, verificar_senha

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DB):
    usuario = db.scalar(select(Usuario).where(Usuario.email == form.username.lower()))
    if not usuario or not usuario.ativo or not verificar_senha(form.password, usuario.senha_hash):
        raise HTTPException(401, "E-mail ou senha inválidos")
    return Token(access_token=criar_token(usuario.id))


@router.post("/primeiro-acesso", response_model=UsuarioLer, status_code=201)
def primeiro_acesso(dados: UsuarioCriar, db: DB):
    """Cria o usuário administrador. Só funciona enquanto não houver usuários."""
    if db.scalar(select(func.count(Usuario.id))):
        raise HTTPException(403, "Já existe usuário cadastrado")
    usuario = Usuario(nome=dados.nome, email=dados.email.lower(), senha_hash=hash_senha(dados.senha))
    db.add(usuario)
    db.commit()
    return usuario


@router.post("/usuarios", response_model=UsuarioLer, status_code=201)
def criar_usuario(dados: UsuarioCriar, db: DB, _: UsuarioAtual):
    if db.scalar(select(Usuario).where(Usuario.email == dados.email.lower())):
        raise HTTPException(409, "E-mail já cadastrado")
    usuario = Usuario(nome=dados.nome, email=dados.email.lower(), senha_hash=hash_senha(dados.senha))
    db.add(usuario)
    db.commit()
    return usuario


@router.get("/eu", response_model=UsuarioLer)
def eu(usuario: UsuarioAtual):
    return usuario
