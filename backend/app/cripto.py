"""Criptografia de dados pessoais (LGPD): CPF guardado cifrado no banco.

AES-SIV é determinístico: o mesmo CPF gera sempre o mesmo texto cifrado, então buscas por igualdade
(WHERE documento = ...) continuam funcionando. CNPJ (dado de empresa) fica em claro.
A chave vem de DADOS_CHAVE (base64, 64 bytes) ou é derivada do SECRET_KEY — não troque o SECRET_KEY depois de usar.
"""

import base64
from functools import lru_cache

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESSIV
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

from app.config import settings

PREFIXO = "c1:"


@lru_cache(maxsize=4)
def _cifra(chave_b64: str, segredo: str) -> AESSIV:
    if chave_b64:
        chave = base64.b64decode(chave_b64)
    else:
        chave = HKDF(algorithm=hashes.SHA256(), length=64, salt=b"finbpo", info=b"dados-pessoais").derive(segredo.encode())
    return AESSIV(chave)


def _c() -> AESSIV:
    return _cifra(settings.dados_chave, settings.secret_key)


def e_cpf(v: str | None) -> bool:
    return bool(v) and len(v) == 11 and v.isdigit()


def cifrar(v: str | None) -> str | None:
    if not e_cpf(v):
        return v
    return PREFIXO + base64.urlsafe_b64encode(_c().encrypt(v.encode(), None)).decode().rstrip("=")


def decifrar(v: str | None) -> str | None:
    if not v or not v.startswith(PREFIXO):
        return v
    dado = v[len(PREFIXO):]
    return _c().decrypt(base64.urlsafe_b64decode(dado + "=" * (-len(dado) % 4)), None).decode()


class Documento(TypeDecorator):
    """CPF/CNPJ só com dígitos; CPF é cifrado ao gravar e decifrado ao ler."""

    impl = String(64)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return cifrar(value)

    def process_result_value(self, value, dialect):
        return decifrar(value)


def mascarar_cpf(v: str | None) -> str | None:
    if not e_cpf(v):
        return v
    return f"***.{v[3:6]}.{v[6:9]}-**"
