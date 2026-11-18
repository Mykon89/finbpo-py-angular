"""Categorização automática sem custo de IA.

1. Regras explícitas (por contraparte ou por trecho da descrição).
2. Aprendizado com o histórico: mesma contraparte → mesma categoria; senão,
   lançamentos com descrição parecida (palavras em comum) e mesmo sinal.
"""

import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Categoria, ContaFinanceira, RegraCategorizacao, Transacao

# Palavras que aparecem em quase todo extrato e não ajudam a diferenciar
_IRRELEVANTES = {
    "pix", "ted", "doc", "tef", "pagamento", "pagto", "pag", "recebimento", "recebido", "recebida", "emitido",
    "enviado", "outra", "mesma", "if", "de", "da", "do", "das", "dos", "para", "em", "no", "na", "transf",
    "transferencia", "credito", "debito", "compra", "conta", "corrente", "ltda", "me", "sa", "eireli", "epp",
}


def _texto(trn: Transacao) -> str:
    return " ".join(x for x in (trn.descricao, trn.complemento, trn.contraparte_nome) if x)


def palavras(texto: str) -> set[str]:
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return {w for w in re.findall(r"[a-z]{3,}", t) if w not in _IRRELEVANTES}


def _transacoes(db: Session, entidade_id: int, somente_sem_categoria: bool):
    stmt = select(Transacao).join(ContaFinanceira).where(ContaFinanceira.entidade_id == entidade_id)
    if somente_sem_categoria:
        stmt = stmt.where(Transacao.categoria_id.is_(None))
    return db.scalars(stmt).all()


def regra_para(regras: list[RegraCategorizacao], trn: Transacao) -> RegraCategorizacao | None:
    if trn.contraparte_id:
        r = next((r for r in regras if r.contraparte_id == trn.contraparte_id), None)
        if r:
            return r
    texto = _texto(trn).upper()
    return next((r for r in regras if r.padrao and not r.contraparte_id and r.padrao.upper() in texto), None)


def aplicar_regras(db: Session, entidade_id: int, somente_sem_categoria: bool = True) -> int:
    regras = db.scalars(
        select(RegraCategorizacao)
        .join(Categoria, Categoria.id == RegraCategorizacao.categoria_id)
        .where(RegraCategorizacao.entidade_id == entidade_id, Categoria.ativo.is_(True))
        .order_by(RegraCategorizacao.prioridade, RegraCategorizacao.id)
    ).all()
    if not regras:
        return 0
    alteradas = 0
    for trn in _transacoes(db, entidade_id, somente_sem_categoria):
        regra = regra_para(regras, trn)
        if regra and trn.categoria_id != regra.categoria_id:
            trn.categoria_id = regra.categoria_id
            trn.categoria_origem = "regra"
            alteradas += 1
    db.commit()
    return alteradas


def criar_regra_de(db: Session, entidade_id: int, trn: Transacao, categoria_id: int) -> RegraCategorizacao:
    """Cria (ou atualiza) a regra mais forte possível a partir de um lançamento categorizado."""
    if trn.contraparte_id:
        regra = db.scalar(
            select(RegraCategorizacao).where(
                RegraCategorizacao.entidade_id == entidade_id, RegraCategorizacao.contraparte_id == trn.contraparte_id
            )
        )
        if regra:
            regra.categoria_id = categoria_id
            return regra
        regra = RegraCategorizacao(entidade_id=entidade_id, contraparte_id=trn.contraparte_id, categoria_id=categoria_id)
    else:
        regra = RegraCategorizacao(entidade_id=entidade_id, padrao=trn.descricao[:160], categoria_id=categoria_id)
    db.add(regra)
    return regra


@dataclass
class Sugestao:
    transacao_id: int
    categoria_id: int
    categoria: str
    confianca: float  # 0 a 1
    motivo: str


def sugerir(db: Session, entidade_id: int, limite: int = 500) -> list[Sugestao]:
    todas = _transacoes(db, entidade_id, somente_sem_categoria=False)
    categorizadas = [t for t in todas if t.categoria_id]
    pendentes = [t for t in todas if not t.categoria_id][:limite]
    if not categorizadas or not pendentes:
        return []
    nomes = dict(
        db.execute(
            select(Categoria.id, Categoria.nome).where(Categoria.entidade_id == entidade_id, Categoria.ativo.is_(True))
        ).all()
    )

    por_contraparte: dict[int, Counter] = defaultdict(Counter)
    for t in categorizadas:
        if t.contraparte_id:
            por_contraparte[t.contraparte_id][t.categoria_id] += 1

    # Índice de palavras → categorias (com sinal), estilo Naive Bayes simplificado
    docs = [(palavras(_texto(t)), t.categoria_id, t.valor < 0) for t in categorizadas]
    freq_doc = Counter(w for ws, _, _ in docs for w in ws)
    n = len(docs)

    resultado = []
    for t in pendentes:
        hist = por_contraparte.get(t.contraparte_id) if t.contraparte_id else None
        if hist:
            hist = Counter({c: q for c, q in hist.items() if c in nomes})  # ignora categorias desativadas
        if hist:
            cat, qtd = hist.most_common(1)[0]
            total = sum(hist.values())
            resultado.append(
                Sugestao(t.id, cat, nomes.get(cat, ""), round(min(0.99, 0.6 + 0.4 * qtd / total), 2),
                         f"{qtd} lançamento(s) anterior(es) de {t.contraparte_nome or 'mesma contraparte'}")
            )
            continue
        ws = palavras(_texto(t))
        if not ws:
            continue
        pontos: Counter = Counter()
        exemplos: dict[int, set[str]] = defaultdict(set)
        for dws, cat, saida in docs:
            if saida != (t.valor < 0) or cat not in nomes:
                continue
            comuns = ws & dws
            if not comuns:
                continue
            # peso maior para palavras raras (IDF)
            peso = sum(math.log(1 + n / freq_doc[w]) for w in comuns) / math.sqrt(len(ws | dws))
            pontos[cat] += peso
            exemplos[cat] |= comuns
        if not pontos:
            continue
        (cat, melhor), *resto = pontos.most_common(2) + [(None, 0.0)]
        segundo = resto[0][1] if resto else 0.0
        confianca = round(min(0.9, melhor / (melhor + segundo + 0.5)), 2)
        if confianca < 0.45:
            continue
        resultado.append(
            Sugestao(t.id, cat, nomes.get(cat, ""), confianca, "descrição parecida com: " + ", ".join(sorted(exemplos[cat])[:4]))
        )
    return resultado
