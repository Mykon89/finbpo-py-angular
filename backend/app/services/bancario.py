"""Estrutura de integração bancária.

Cada fonte de extrato é um "provedor" com a mesma interface. Hoje existe o gratuito `ofx_pasta` (OFX salvo na
pasta monitorada). Para ligar Open Finance (Pluggy, Belvo) ou a API do Sicoob no futuro, basta criar uma classe
que implemente `ProvedorBancario` e registrá-la em PROVEDORES — conciliação, regras e perguntas já funcionam.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ConexaoBancaria, ContaFinanceira
from app.services import decisoes
from app.services.ofx import OFXInvalido, ler_ofx


@dataclass
class TransacaoExterna:
    data: date
    valor: Decimal
    descricao: str
    id_externo: str  # FITID / id do provedor (deduplicação)
    contraparte_nome: str | None = None
    contraparte_documento: str | None = None


@dataclass
class ResultadoSync:
    novas: int = 0
    lidas: int = 0
    conta_id: int | None = None
    conta_criada: bool = False
    avisos: list[str] = field(default_factory=list)


class ProvedorBancario(Protocol):
    nome: str

    def sincronizar(self, db: Session, conexao: ConexaoBancaria) -> ResultadoSync:
        """Busca as transações desde conexao.cursor, grava e devolve o novo cursor em conexao.cursor."""


PROVEDORES: dict[str, ProvedorBancario] = {}  # futuro: {"pluggy": Pluggy(), "belvo": Belvo(), "sicoob_api": SicoobApi()}


def importar_ofx(db: Session, entidade_id: int, conteudo: bytes, arquivo: str) -> ResultadoSync:
    """OFX recebido sem tela (pasta monitorada): reconhece a conta pelo número ou cria a conta, como na importação manual."""
    from app.routers.transacoes import _contas_do_extrato, _gravar, _sugestao
    from app.services.bancos import normalizar_codigo

    try:
        extrato = ler_ofx(conteudo)
    except OFXInvalido as e:
        raise ValueError(str(e)) from e
    conta = next((c for c in _contas_do_extrato(db, extrato) if c.entidade_id == entidade_id), None)
    criada = False
    if conta is None:
        if not extrato.conta_id:
            raise ValueError("O OFX não informa o número da conta; importe pela tela Contas e extratos")
        tipo, sugestao, saldo = _sugestao(extrato)
        conta = ContaFinanceira(entidade_id=entidade_id, tipo=tipo, nome=sugestao, banco_codigo=normalizar_codigo(extrato.banco_id),
                                agencia=extrato.agencia, numero=extrato.conta_id, saldo_inicial=saldo)
        db.add(conta)
        db.flush()
        criada = True
    try:
        r = _gravar(db, entidade_id, conta, extrato, arquivo)
    except HTTPException as e:
        raise ValueError(e.detail) from e
    con = db.scalar(select(ConexaoBancaria).where(ConexaoBancaria.conta_id == conta.id, ConexaoBancaria.provedor == "ofx_pasta"))
    if not con:
        con = ConexaoBancaria(entidade_id=entidade_id, conta_id=conta.id, provedor="ofx_pasta")
        db.add(con)
    con.ultima_sincronizacao, con.status, con.erro = datetime.now(UTC), "ativa", None
    if extrato.fim:
        con.cursor = extrato.fim.isoformat()
    db.commit()
    return ResultadoSync(novas=r.total_novas, lidas=r.total_lidas, conta_id=conta.id, conta_criada=criada)


def sincronizar_todas(db: Session) -> None:
    """Chamado pelo agendador: provedores com API (quando existirem) buscam sozinhos."""
    for con in db.scalars(select(ConexaoBancaria).where(ConexaoBancaria.status == "ativa")):
        prov = PROVEDORES.get(con.provedor)
        if not prov:
            continue
        try:
            prov.sincronizar(db, con)
            con.ultima_sincronizacao, con.erro = datetime.now(UTC), None
            decisoes.apos_importar_banco(db, con.entidade_id)
        except Exception as e:  # noqa: BLE001
            con.status, con.erro = "erro", str(e)[:2000]
        if con.consentimento_expira_em and con.consentimento_expira_em < date.today():
            con.status = "expirada"
        db.commit()
