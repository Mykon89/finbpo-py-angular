"""Conector MCP: deixa o Claude (Desktop ou Code, pela assinatura do usuário) ler e categorizar lançamentos.

Endpoint: POST /mcp  —  cabeçalho `Authorization: Bearer <MCP_TOKEN>`.
"""

import hmac
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal

from mcp.server.fastmcp import FastMCP
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import Categoria, ContaFinanceira, Entidade, StatusTitulo, TipoTitulo, Titulo, Transacao
from app.services.categorizacao import aplicar_regras, criar_regra_de, sugerir
from app.services.dre import calcular_dre

INSTRUCOES = """FinBPO: gestão financeira de corretoras de seguros, clínica de estética e pessoas físicas.
Para categorizar: chame listar_entidades, depois listar_categorias e lancamentos_sem_categoria da entidade,
decida a categoria de cada lançamento (use descrição, complemento, quem pagou/recebeu, sinal do valor e a
sugestao_interna quando houver) e grave com categorizar_lancamentos. Na dúvida, não categorize: deixe para
revisão humana. Use criar_regra=true só quando a contraparte sempre terá a mesma categoria."""

mcp = FastMCP(
    "FinBPO",
    instructions=INSTRUCOES,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*", "backend:*"],
        allowed_origins=["http://localhost:*", "http://127.0.0.1:*"],
    ),
)


def abrir_sessao():
    return SessionLocal()


def _num(v: Decimal | None) -> float | None:
    return float(v) if v is not None else None


@mcp.tool()
def listar_entidades() -> list[dict]:
    """Lista as empresas e pessoas físicas cadastradas (id, nome, segmento)."""
    with abrir_sessao() as db:
        return [
            {"id": e.id, "nome": e.nome, "segmento": e.segmento.value, "tipo": e.tipo.value, "cnae": e.cnae_descricao}
            for e in db.scalars(select(Entidade).where(Entidade.ativo.is_(True)).order_by(Entidade.nome))
        ]


@mcp.tool()
def listar_categorias(entidade_id: int) -> list[dict]:
    """Plano de contas da entidade (id, nome e grupo da DRE)."""
    with abrir_sessao() as db:
        return [
            {"id": c.id, "nome": c.nome, "grupo_dre": c.grupo_dre.value}
            for c in db.scalars(
                select(Categoria).where(Categoria.entidade_id == entidade_id).order_by(Categoria.grupo_dre, Categoria.nome)
            )
        ]


@mcp.tool()
def lancamentos_sem_categoria(
    entidade_id: int, limite: int = 50, data_de: date | None = None, data_ate: date | None = None
) -> list[dict]:
    """Lançamentos do extrato ainda sem categoria (valor negativo = saída), com a sugestão do aprendizado interno."""
    with abrir_sessao() as db:
        sugestoes = {s.transacao_id: s for s in sugerir(db, entidade_id)}
        stmt = (
            select(Transacao, ContaFinanceira.nome)
            .join(ContaFinanceira)
            .where(ContaFinanceira.entidade_id == entidade_id, Transacao.categoria_id.is_(None))
        )
        if data_de:
            stmt = stmt.where(Transacao.data >= data_de)
        if data_ate:
            stmt = stmt.where(Transacao.data <= data_ate)
        linhas = db.execute(stmt.order_by(Transacao.data).limit(max(1, min(limite, 200)))).all()
        resultado = []
        for t, conta in linhas:
            s = sugestoes.get(t.id)
            resultado.append(
                {
                    "transacao_id": t.id,
                    "data": t.data.isoformat(),
                    "conta": conta,
                    "valor": _num(t.valor),
                    "descricao": t.descricao,
                    "complemento": t.complemento,
                    "contraparte": t.contraparte_nome,
                    "contraparte_documento": t.contraparte_documento,
                    "sugestao_interna": {"categoria_id": s.categoria_id, "categoria": s.categoria, "confianca": s.confianca}
                    if s
                    else None,
                }
            )
        return resultado


class ItemCategoria(BaseModel):
    transacao_id: int
    categoria_id: int
    criar_regra: bool = Field(False, description="Cria regra para os próximos lançamentos da mesma contraparte")


@mcp.tool()
def categorizar_lancamentos(entidade_id: int, itens: list[ItemCategoria]) -> dict:
    """Grava a categoria de vários lançamentos de uma vez. Ficam marcados com origem 'ia' para revisão."""
    with abrir_sessao() as db:
        cats = set(db.scalars(select(Categoria.id).where(Categoria.entidade_id == entidade_id)))
        ok, erros = 0, []
        for item in itens:
            trn = db.get(Transacao, item.transacao_id)
            if not trn or trn.conta.entidade_id != entidade_id:
                erros.append(f"lançamento {item.transacao_id} não pertence à entidade")
                continue
            if item.categoria_id not in cats:
                erros.append(f"categoria {item.categoria_id} não existe na entidade")
                continue
            trn.categoria_id = item.categoria_id
            trn.categoria_origem = "ia"
            if item.criar_regra:
                criar_regra_de(db, entidade_id, trn, item.categoria_id)
                db.flush()
            ok += 1
        db.commit()
        extras = aplicar_regras(db, entidade_id)
        return {"categorizados": ok, "categorizados_por_regra_nova": extras, "erros": erros}


@mcp.tool()
def resumo_do_mes(entidade_id: int, ano: int, mes: int) -> dict:
    """DRE gerencial do mês (caixa) e contas a pagar/receber em aberto, para análises e fechamento."""
    with abrir_sessao() as db:
        dre = calcular_dre(db, entidade_id, ano, mes)
        abertos = db.scalars(
            select(Titulo).where(
                Titulo.entidade_id == entidade_id, Titulo.status.in_([StatusTitulo.ABERTO, StatusTitulo.PARCIAL])
            )
        ).all()
        return {
            "competencia": dre["competencia"].isoformat(),
            "linhas": [{"rotulo": l["rotulo"], "valor": _num(l["valor"])} for l in dre["linhas"]],
            "resultado_liquido": _num(dre["resultado_liquido"]),
            "margem_liquida_pct": dre["margem_liquida_pct"],
            "sem_categoria": _num(dre["sem_categoria"]),
            "a_pagar_em_aberto": _num(sum((t.saldo for t in abertos if t.tipo == TipoTitulo.PAGAR), Decimal(0))),
            "a_receber_em_aberto": _num(sum((t.saldo for t in abertos if t.tipo == TipoTitulo.RECEBER), Decimal(0))),
        }


_estado: dict = {"gerenciador": None}


@asynccontextmanager
async def ciclo_de_vida():
    """Um gerenciador por ciclo de vida da aplicação (o do SDK só pode rodar uma vez)."""
    gerenciador = StreamableHTTPSessionManager(
        app=mcp._mcp_server,
        json_response=True,
        stateless=True,
        security_settings=mcp.settings.transport_security,
    )
    _estado["gerenciador"] = gerenciador
    async with gerenciador.run():
        yield
    _estado["gerenciador"] = None


async def _responder(send, status: int, corpo: bytes):
    await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": corpo})


async def app_mcp(scope, receive, send):
    """App ASGI montado na raiz: atende só /mcp, exigindo o token."""
    if scope["type"] != "http":
        return
    if scope["path"].rstrip("/") != "/mcp":
        await _responder(send, 404, b'{"detail":"Not Found"}')
        return
    if not settings.mcp_token:
        await _responder(send, 401, b'{"detail":"Conector MCP desligado: defina MCP_TOKEN no .env"}')
        return
    auth = dict(scope.get("headers") or []).get(b"authorization", b"").decode()
    if not hmac.compare_digest(auth, f"Bearer {settings.mcp_token}"):
        await _responder(send, 401, b'{"detail":"Token MCP invalido"}')
        return
    await _estado["gerenciador"].handle_request(scope, receive, send)
