"""Fechamento mensal (PDF com análise) e e-mails (alerta diário, envio do fechamento)."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.acesso import somente_admin
from app.config import settings
from app.deps import DB, EntidadeDep
from app.models import AnaliseMensal
from app.services import alertas, email_envio, fechamento_mensal

router = APIRouter(prefix="/entidades/{entidade_id}/fechamento-mensal", tags=["fechamento mensal"])
admin = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(somente_admin)])


def _mes_padrao(ano, mes):
    if ano and mes:
        return ano, mes
    h = date.today()
    return (h.year - 1, 12) if h.month == 1 else (h.year, h.month - 1)


@router.get("")
def dados(entidade: EntidadeDep, db: DB, ano: int | None = Query(None, ge=2000), mes: int | None = Query(None, ge=1, le=12)):
    a, m = _mes_padrao(ano, mes)
    return jsonable_encoder(fechamento_mensal.dados(db, entidade.id, a, m))


@router.get("/pdf")
def pdf(entidade: EntidadeDep, db: DB, ano: int | None = Query(None, ge=2000), mes: int | None = Query(None, ge=1, le=12)):
    a, m = _mes_padrao(ano, mes)
    nome = f"fechamento-{a}-{m:02d}.pdf"
    return Response(fechamento_mensal.gerar_pdf(db, entidade.id, a, m), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{nome}"'})


class Analise(BaseModel):
    ano: int
    mes: int
    texto: str


@router.put("/analise")
def salvar_analise(dados: Analise, entidade: EntidadeDep, db: DB):
    return {"ok": True, "id": gravar_analise(db, entidade.id, dados.ano, dados.mes, dados.texto)}


def gravar_analise(db, entidade_id: int, ano: int, mes: int, texto: str) -> int:
    a = db.scalar(select(AnaliseMensal).where(AnaliseMensal.entidade_id == entidade_id, AnaliseMensal.ano == ano, AnaliseMensal.mes == mes))
    if not a:
        a = AnaliseMensal(entidade_id=entidade_id, ano=ano, mes=mes, texto="")
        db.add(a)
    a.texto = texto.strip()[:20000]
    db.commit()
    return a.id


@admin.get("/email")
def status_email():
    return {"configurado": email_envio.configurado(), "destinatarios": email_envio.destinatarios(), "hora": settings.alertas_hora,
            "dia_fechamento": settings.fechamento_dia, "servidor": settings.smtp_host or None}


@admin.get("/alertas/previa", response_class=HTMLResponse)
def previa(db: DB):
    """Como fica o e-mail de hoje (sem enviar)."""
    return alertas.renderizar(alertas.montar(db))[1]


@admin.post("/alertas/testar")
def testar(db: DB):
    if not email_envio.configurado():
        raise HTTPException(422, "Configure SMTP_HOST, SMTP_USUARIO, SMTP_SENHA e ALERTAS_DESTINATARIOS no .env")
    try:
        return {"resultado": alertas.enviar_alerta_do_dia(db, forcar=True)}
    except OSError as e:
        raise HTTPException(502, f"Falha no envio: {e}") from e


@admin.post("/fechamento/enviar")
def enviar_fechamento(db: DB, ano: int, mes: int = Query(ge=1, le=12)):
    if not email_envio.configurado():
        raise HTTPException(422, "E-mail não configurado")
    try:
        return {"resultado": alertas.enviar_fechamentos(db, (ano, mes))}
    except OSError as e:
        raise HTTPException(502, f"Falha no envio: {e}") from e
