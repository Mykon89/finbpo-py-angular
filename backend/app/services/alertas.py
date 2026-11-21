"""Alerta diário por e-mail: contas atrasadas e vencendo, comissões que não chegaram, perguntas abertas.
LGPD: o e-mail leva só o necessário — fornecedor, seguradora e apólice; nunca CPF nem nome de cliente pessoa física."""

import html
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.models import (
    ConexaoBancaria,
    Contraparte,
    Entidade,
    ExtratoComissao,
    Pendencia,
    RegistroEnvio,
    Segmento,
    StatusTitulo,
    TipoTitulo,
    Titulo,
)
from app.services import email_envio, previsao
from app.services.fechamento_mensal import MESES, brl, gerar_pdf

Z = Decimal("0")


def montar(db: Session, hoje: date | None = None) -> dict:
    hoje = hoje or date.today()
    blocos = []
    for ent in db.scalars(select(Entidade).where(Entidade.ativo.is_(True)).order_by(Entidade.nome)):
        cps = {c.id: c.nome for c in db.scalars(select(Contraparte).where(Contraparte.entidade_id == ent.id))}
        abertos = db.scalars(select(Titulo).options(selectinload(Titulo.baixas)).where(
            Titulo.entidade_id == ent.id, Titulo.tipo == TipoTitulo.PAGAR, Titulo.status.in_([StatusTitulo.ABERTO, StatusTitulo.PARCIAL]))).all()
        nome = lambda t: cps.get(t.contraparte_id) or t.descricao  # noqa: E731
        atrasadas = sorted((t for t in abertos if t.vencimento < hoje), key=lambda t: t.vencimento)
        hoje_ = [t for t in abertos if t.vencimento == hoje]
        prox = sorted((t for t in abertos if hoje < t.vencimento <= hoje + timedelta(days=3)), key=lambda t: t.vencimento)
        receber_atras = []
        parcelas = []
        if ent.segmento == Segmento.CORRETORA:
            receber_atras = db.scalars(select(ExtratoComissao).where(
                ExtratoComissao.entidade_id == ent.id, ExtratoComissao.recebido_valor.is_(None),
                ExtratoComissao.data < hoje - timedelta(days=10), ExtratoComissao.data >= hoje - timedelta(days=120))).all()
            parcelas = previsao.prever(db, ent.id, 1, hoje).atrasados
        pend = dict(db.execute(select(Pendencia.tipo, func.count(Pendencia.id)).where(
            Pendencia.entidade_id == ent.id, Pendencia.status == "aberta").group_by(Pendencia.tipo)).all())
        consent = db.scalars(select(ConexaoBancaria).where(
            ConexaoBancaria.entidade_id == ent.id, ConexaoBancaria.consentimento_expira_em.is_not(None),
            ConexaoBancaria.consentimento_expira_em <= hoje + timedelta(days=30))).all()
        b = {
            "entidade": ent.nome,
            "atrasadas": [(nome(t), t.descricao, t.vencimento, t.saldo, (hoje - t.vencimento).days) for t in atrasadas],
            "hoje": [(nome(t), t.descricao, t.saldo) for t in hoje_],
            "proximos": [(nome(t), t.descricao, t.vencimento, t.saldo) for t in prox],
            "receber_atrasado": [(e.codigo, e.data, e.liquido) for e in receber_atras],
            "parcelas": [(i.seguradora, i.apolice or "-", i.valor, i.detalhe) for i in parcelas],
            "pendencias": sum(pend.values()),
            "consentimentos": [(c.provedor, c.consentimento_expira_em) for c in consent],
        }
        if any(b[k] for k in ("atrasadas", "hoje", "proximos", "receber_atrasado", "parcelas", "pendencias", "consentimentos")):
            blocos.append(b)
    from app.services.comissao_produtor import metas_faltando

    return {"data": hoje, "blocos": blocos, "metas_faltando": metas_faltando(db, hoje)}


def _tabela(titulo: str, cab: list[str], linhas: list[list[str]], cor: str = "#1f4e79") -> str:
    if not linhas:
        return ""
    th = "".join(f'<th style="text-align:left;padding:4px 8px;background:#eef2f8">{html.escape(c)}</th>' for c in cab)
    trs = "".join("<tr>" + "".join(f'<td style="padding:4px 8px;border-top:1px solid #eee">{html.escape(str(c))}</td>' for c in l) + "</tr>" for l in linhas)
    return f'<h3 style="color:{cor};margin:16px 0 6px">{html.escape(titulo)}</h3><table style="border-collapse:collapse;font-size:13px">{th and "<tr>" + th + "</tr>"}{trs}</table>'


def renderizar(a: dict) -> tuple[str, str, str]:
    d: date = a["data"]
    total_atr = sum((Decimal(x[3]) for b in a["blocos"] for x in b["atrasadas"]), Z)
    qtd_atr = sum(len(b["atrasadas"]) for b in a["blocos"])
    assunto = f"FinBPO {d:%d/%m}: " + (f"{qtd_atr} conta(s) em atraso ({brl(total_atr)})" if qtd_atr else "resumo do dia")
    partes, texto = [f'<p style="font-family:Arial">Bom dia! Resumo de {d:%d/%m/%Y}.</p>'], [f"Resumo de {d:%d/%m/%Y}"]
    if a.get("metas_faltando"):
        m = f"{MESES[d.month - 1]}/{d.year}"
        partes.append(f'<p style="background:#fff7d6;padding:8px"><b>Metas de comissão de {m} não cadastradas:</b> '
                      f'{html.escape(", ".join(a["metas_faltando"]))}. Pegue com a Kette e cadastre em Comissões das produtoras.</p>')
        texto.append(f"METAS DE {m} NÃO CADASTRADAS: {', '.join(a['metas_faltando'])} (pegar com a Kette)")
    if not a["blocos"] and not a.get("metas_faltando"):
        partes.append("<p>Tudo em dia: nada atrasado, vencendo ou pendente.</p>")
        texto.append("Tudo em dia.")
    for b in a["blocos"]:
        partes.append(f'<h2 style="font-family:Arial;border-bottom:2px solid #1f4e79">{html.escape(b["entidade"])}</h2>')
        texto.append(f"\n== {b['entidade']}")
        partes.append(_tabela("Contas em atraso", ["Fornecedor", "Conta", "Venceu", "Saldo", "Dias"],
                              [[f, c, v.strftime("%d/%m"), brl(s), str(n)] for f, c, v, s, n in b["atrasadas"][:30]], "#b91c1c"))
        partes.append(_tabela("Vencem hoje", ["Fornecedor", "Conta", "Valor"], [[f, c, brl(s)] for f, c, s in b["hoje"]], "#c2410c"))
        partes.append(_tabela("Próximos 3 dias", ["Fornecedor", "Conta", "Vence", "Valor"],
                              [[f, c, v.strftime("%d/%m"), brl(s)] for f, c, v, s in b["proximos"]]))
        partes.append(_tabela("Comissões sem crédito no banco (mais de 10 dias)", ["Extrato", "Data", "Líquido"],
                              [[c, dt.strftime("%d/%m"), brl(v)] for c, dt, v in b["receber_atrasado"]]))
        partes.append(_tabela("Parcelas de comissão que não chegaram", ["Seguradora", "Apólice", "Valor", ""],
                              [[s, ap, brl(v), det] for s, ap, v, det in b["parcelas"][:20]]))
        if b["pendencias"]:
            partes.append(f'<p><b>{b["pendencias"]}</b> pergunta(s) aguardando você na Central de decisões.</p>')
        for prov, exp in b["consentimentos"]:
            partes.append(f"<p>Consentimento bancário ({html.escape(prov)}) vence em {exp:%d/%m/%Y}: renove no app do banco.</p>")
        for f, c, v, s, n in b["atrasadas"]:
            texto.append(f"ATRASO {n}d  {f} | {c} | venceu {v:%d/%m} | {brl(s)}")
        for f, c, s in b["hoje"]:
            texto.append(f"HOJE  {f} | {c} | {brl(s)}")
        for f, c, v, s in b["proximos"]:
            texto.append(f"{v:%d/%m}  {f} | {c} | {brl(s)}")
        if b["pendencias"]:
            texto.append(f"{b['pendencias']} pergunta(s) na Central de decisões")
    partes.append('<p style="color:#888;font-size:11px">Enviado pelo FinBPO. Sem CPF nem dados de clientes pessoa física.</p>')
    return assunto, "".join(partes), "\n".join(texto)


def _ja_enviado(db, tipo: str, ref: str) -> bool:
    return bool(db.scalar(select(RegistroEnvio.id).where(RegistroEnvio.tipo == tipo, RegistroEnvio.referencia == ref)))


def enviar_alerta_do_dia(db: Session, forcar: bool = False) -> str:
    hoje = date.today()
    if not email_envio.configurado():
        return "e-mail não configurado"
    if not forcar and (datetime.now().hour < settings.alertas_hora or _ja_enviado(db, "alerta_diario", hoje.isoformat())):
        return "fora do horário ou já enviado hoje"
    a = montar(db, hoje)
    if not a["blocos"] and not a["metas_faltando"] and not settings.alertas_sempre and not forcar:
        db.add(RegistroEnvio(tipo="alerta_diario", referencia=hoje.isoformat(), detalhe="nada a avisar"))
        db.commit()
        return "nada a avisar"
    assunto, corpo, texto = renderizar(a)
    email_envio.enviar(assunto, corpo, texto)
    if not forcar:
        db.add(RegistroEnvio(tipo="alerta_diario", referencia=hoje.isoformat(), detalhe=assunto[:255]))
        db.commit()
    return "enviado"


def enviar_fechamentos(db: Session, forcar_mes: tuple[int, int] | None = None) -> str:
    """No dia FECHAMENTO_DIA, manda o PDF do mês anterior de cada empresa."""
    hoje = date.today()
    if not email_envio.configurado():
        return "e-mail não configurado"
    if forcar_mes:
        ano, mes = forcar_mes
    else:
        if hoje.day < settings.fechamento_dia or datetime.now().hour < settings.alertas_hora:
            return "ainda não é o dia"
        ano, mes = (hoje.year - 1, 12) if hoje.month == 1 else (hoje.year, hoje.month - 1)
        if _ja_enviado(db, "fechamento", f"{ano}-{mes:02d}"):
            return "já enviado"
    anexos = [(f"fechamento-{ent.nome[:30].replace(' ', '_')}-{ano}-{mes:02d}.pdf", gerar_pdf(db, ent.id, ano, mes), "application/pdf")
              for ent in db.scalars(select(Entidade).where(Entidade.ativo.is_(True)))]
    rot = f"{MESES[mes - 1]} de {ano}"
    email_envio.enviar(f"FinBPO: fechamento de {rot}", f"<p>Segue o fechamento de {rot} com a análise e as sugestões de economia.</p>",
                       f"Segue o fechamento de {rot}.", anexos)
    if not forcar_mes:
        db.add(RegistroEnvio(tipo="fechamento", referencia=f"{ano}-{mes:02d}", detalhe=f"{len(anexos)} PDF(s)"))
        db.commit()
    return "enviado"


def tarefas(db: Session) -> None:
    """Chamado a cada volta do laço em segundo plano (barato quando já foi enviado)."""
    for f in (enviar_alerta_do_dia, enviar_fechamentos):
        try:
            f(db)
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger("finbpo.alertas").exception("falha ao enviar e-mail")
            db.rollback()
    _ = datetime.now(UTC)
