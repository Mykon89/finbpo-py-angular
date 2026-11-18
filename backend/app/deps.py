from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Entidade, Usuario
from app.security import usuario_atual

DB = Annotated[Session, Depends(get_db)]
UsuarioAtual = Annotated[Usuario, Depends(usuario_atual)]


def obter_entidade(entidade_id: int, db: DB, _: UsuarioAtual) -> Entidade:
    entidade = db.get(Entidade, entidade_id)
    if not entidade:
        raise HTTPException(404, "Entidade não encontrada")
    return entidade


EntidadeDep = Annotated[Entidade, Depends(obter_entidade)]


def obter_do_escopo(db: Session, modelo, id_: int, entidade_id: int):
    """Busca um registro garantindo que pertence à entidade."""
    obj = db.get(modelo, id_)
    if obj is None:
        raise HTTPException(404, f"{modelo.__name__} não encontrado(a)")
    dono = obj.entidade_id if hasattr(obj, "entidade_id") else obj.conta.entidade_id
    if dono != entidade_id:
        raise HTTPException(404, f"{modelo.__name__} não encontrado(a)")
    return obj
