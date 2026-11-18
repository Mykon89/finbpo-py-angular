from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Usuario

_hasher = PasswordHash.recommended()
_oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
ALGORITMO = "HS256"


def hash_senha(senha: str) -> str:
    return _hasher.hash(senha)


def verificar_senha(senha: str, hash_: str) -> bool:
    return _hasher.verify(senha, hash_)


def criar_token(usuario_id: int) -> str:
    exp = datetime.now(UTC) + timedelta(minutes=settings.access_token_minutes)
    return jwt.encode({"sub": str(usuario_id), "exp": exp}, settings.secret_key, algorithm=ALGORITMO)


def usuario_atual(token: Annotated[str, Depends(_oauth2)], db: Annotated[Session, Depends(get_db)]) -> Usuario:
    erro = HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciais inválidas", {"WWW-Authenticate": "Bearer"})
    try:
        dados = jwt.decode(token, settings.secret_key, algorithms=[ALGORITMO])
        usuario = db.get(Usuario, int(dados["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        raise erro
    if not usuario or not usuario.ativo:
        raise erro
    return usuario
