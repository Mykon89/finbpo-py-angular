"""Auditoria (LGPD art. 37 e 46): registra logins, todas as alterações e as consultas dos leitores.
Guarda só usuário, rota (sem parâmetros de busca), empresa, status e IP — nunca o conteúdo dos dados."""

import re
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import delete
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.db import SessionLocal
from app.models import EventoAuditoria, Usuario

abrir_sessao = SessionLocal  # trocado nos testes
_ACOES = {"POST": "criacao", "PUT": "alteracao", "PATCH": "alteracao", "DELETE": "exclusao"}
_SENSIVEIS = re.compile(r"/(admin/privacidade|comissoes$|contrapartes|transacoes$|fechamento)")


def registrar(acao: str, caminho: str, usuario_id: int | None = None, metodo: str | None = None,
              status: int | None = None, ip: str | None = None, detalhe: str | None = None) -> None:
    m = re.match(r"^/api/entidades/(\d+)", caminho)
    with abrir_sessao() as db:
        db.add(EventoAuditoria(usuario_id=usuario_id, acao=acao, metodo=metodo, caminho=caminho[:255],
                               entidade_id=int(m.group(1)) if m else None, status=status, ip=ip, detalhe=(detalhe or "")[:255] or None))
        db.commit()


def _usuario_do_token(request) -> int | None:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    try:
        return int(jwt.decode(auth[7:], settings.secret_key, algorithms=["HS256"])["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


class Auditoria(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resposta = await call_next(request)
        caminho = request.url.path
        if not caminho.startswith("/api/") or caminho.startswith("/api/auth/login"):
            return resposta
        uid = _usuario_do_token(request)
        metodo = request.method
        acao = _ACOES.get(metodo)
        if acao is None:
            if metodo != "GET" or uid is None:
                return resposta
            leitor = _e_leitor(uid)
            if not (leitor or _SENSIVEIS.search(caminho)):
                return resposta
            acao = "exportacao" if "exportar" in caminho else "leitura"
        registrar(acao, caminho, uid, metodo, resposta.status_code, request.client.host if request.client else None)
        return resposta


_papeis: dict[int, tuple[str, datetime]] = {}


def _e_leitor(uid: int) -> bool:
    cache = _papeis.get(uid)
    if not cache or cache[1] < datetime.now(UTC):
        with abrir_sessao() as db:
            u = db.get(Usuario, uid)
            _papeis[uid] = (u.papel if u else "?", datetime.now(UTC) + timedelta(minutes=5))
    return _papeis[uid][0] != "admin"


def limpar_antigos(db) -> int:
    limite = datetime.now(UTC) - timedelta(days=settings.auditoria_dias)
    r = db.execute(delete(EventoAuditoria).where(EventoAuditoria.quando < limite))
    db.commit()
    return r.rowcount or 0
