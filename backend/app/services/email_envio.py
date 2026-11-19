"""Envio de e-mail por SMTP (Gmail: smtp.gmail.com:587 com "senha de app" — gratuito)."""

import smtplib
from email.message import EmailMessage

from app.config import settings


def configurado() -> bool:
    return bool(settings.smtp_host and settings.smtp_usuario and settings.smtp_senha and destinatarios())


def destinatarios() -> list[str]:
    return [e.strip() for e in settings.alertas_destinatarios.split(",") if e.strip()]


def enviar(assunto: str, html: str, texto: str, anexos: list[tuple[str, bytes, str]] | None = None, para: list[str] | None = None) -> None:
    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = settings.smtp_remetente or settings.smtp_usuario
    msg["To"] = ", ".join(para or destinatarios())
    msg.set_content(texto)
    msg.add_alternative(html, subtype="html")
    for nome, conteudo, tipo in anexos or []:
        principal, sub = tipo.split("/")
        msg.add_attachment(conteudo, maintype=principal, subtype=sub, filename=nome)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_porta, timeout=30) as s:
        s.starttls()
        s.login(settings.smtp_usuario, settings.smtp_senha)
        s.send_message(msg)
