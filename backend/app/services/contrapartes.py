"""Vincula lançamentos a contrapartes (quem pagou/recebeu) pelo CPF/CNPJ."""

from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ContaFinanceira, Contraparte, Transacao
from app.services.complemento import LinhaComplementar, casar, extrair_documento, nome_da_descricao
from app.services.cnpj import CNPJNaoEncontrado, ConsultaIndisponivel, consultar

MAX_CONSULTAS_CNPJ = 15  # por importação, para não estourar limite das APIs públicas


@dataclass
class ResultadoComplemento:
    linhas_lidas: int = 0
    enriquecidas: int = 0
    sem_correspondencia: int = 0
    contrapartes_criadas: int = 0
    arquivos: list[str] = field(default_factory=list)
    erros: list[str] = field(default_factory=list)


class Vinculador:
    def __init__(self, db: Session, entidade_id: int, consultar_receita: bool = True):
        self.db = db
        self.entidade_id = entidade_id
        self.consultar_receita = consultar_receita
        self.consultas = 0
        self.criadas = 0
        self._cache: dict[str, Contraparte] = {
            c.documento: c
            for c in db.scalars(
                select(Contraparte).where(Contraparte.entidade_id == entidade_id, Contraparte.documento.is_not(None))
            )
        }

    def _nome_receita(self, documento: str) -> str | None:
        if len(documento) != 14 or not self.consultar_receita or self.consultas >= MAX_CONSULTAS_CNPJ:
            return None
        self.consultas += 1
        try:
            d = consultar(documento)
        except (CNPJNaoEncontrado, ConsultaIndisponivel, ValueError):
            return None
        return d.nome_fantasia or d.razao_social

    def contraparte(self, documento: str, nome: str | None) -> Contraparte:
        c = self._cache.get(documento)
        if c is None:
            nome_final = nome or self._nome_receita(documento) or documento
            c = Contraparte(entidade_id=self.entidade_id, nome=nome_final[:160], documento=documento)
            self.db.add(c)
            self.db.flush()
            self._cache[documento] = c
            self.criadas += 1
        elif nome and c.nome == c.documento:
            c.nome = nome[:160]  # contraparte criada só com o documento ganha nome
        return c

    def aplicar(self, trn: Transacao, documento: str | None, nome: str | None, complemento: str | None = None):
        texto = (complemento or "").strip()
        if texto and texto.upper() not in trn.descricao.upper() and len(texto) > len(trn.complemento or ""):
            trn.complemento = texto[:255]  # só guarda se acrescenta algo à descrição do OFX
        sem_nome = not trn.contraparte_nome or trn.contraparte_nome == trn.contraparte_documento
        if nome and sem_nome:
            trn.contraparte_nome = nome[:160]
        if documento and trn.contraparte_documento and trn.contraparte_documento != documento:
            return  # já identificado por outro arquivo; não sobrescreve
        if documento:
            trn.contraparte_documento = documento
            c = self.contraparte(documento, nome if nome and sem_nome else None)
            trn.contraparte_id = c.id
            if not trn.contraparte_nome and c.nome != documento:
                trn.contraparte_nome = c.nome


def extrair_do_ofx(db: Session, entidade_id: int, transacoes: list[Transacao]) -> int:
    """Alguns bancos já põem CPF/CNPJ no MEMO do OFX: aproveita."""
    v = Vinculador(db, entidade_id, consultar_receita=False)
    n = 0
    for t in transacoes:
        doc = extrair_documento(t.descricao)
        if doc and not t.contraparte_documento:
            v.aplicar(t, doc, nome_da_descricao(t.descricao))
            n += 1
    return n


def complementar(db: Session, entidade_id: int, conta: ContaFinanceira, linhas: list[LinhaComplementar]) -> ResultadoComplemento:
    res = ResultadoComplemento(linhas_lidas=len(linhas))
    if not linhas:
        return res
    inicio = min(l.data for l in linhas)
    fim = max(l.data for l in linhas)

    transacoes = db.scalars(
        select(Transacao)
        .where(
            Transacao.conta_id == conta.id,
            Transacao.data.between(inicio - timedelta(days=1), fim + timedelta(days=1)),
        )
        .order_by(Transacao.data, Transacao.id)
    ).all()
    pares = casar(list(transacoes), linhas)
    v = Vinculador(db, entidade_id)
    for trn, linha in pares:
        documento = linha.documento or extrair_documento(trn.descricao)
        v.aplicar(trn, documento, linha.nome, linha.descricao)
    res.enriquecidas = sum(1 for _, l in pares if l.documento or l.nome or l.descricao)
    res.sem_correspondencia = len(linhas) - len(pares)
    res.contrapartes_criadas = v.criadas
    db.commit()
    return res
