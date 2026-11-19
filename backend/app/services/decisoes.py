"""Central de decisões: o sistema pergunta o que não sabe e aprende com cada resposta.

Fluxo: uma rotina automática chama `regra()` (já aprendi?) -> se não, `perguntar()` cria uma pendência com
opções e sugestão. Quando o usuário responde (`responder()`), a ação é executada e, com "sempre fazer assim",
vira uma `RegraAprendida` que resolve sozinha os próximos casos iguais.
"""

import re
import unicodedata
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Categoria,
    Comissao,
    ContaFinanceira,
    Entidade,
    ExtratoComissao,
    Pendencia,
    RegraAprendida,
    Segmento,
    Transacao,
)

RAMOS = ["AUTO", "RE", "VIDA", "SAUDE", "ODONTO", "CONSORCIO", "VIAGEM", "FIANCA", "RC PROFISSIONAL", "PET", "OUTRO"]
TIPOS = {
    "categoria": "Lançamento sem categoria",
    "pagador": "Crédito de quem?",
    "credito_sem_extrato": "Crédito sem extrato de comissão",
    "vinculo": "Comissão sem origem/produtor/parceiro",
    "ramo": "Ramo desconhecido",
    "divergencia": "Extrato com diferença",
    "arquivo": "Arquivo não reconhecido",
    "negativo": "Comissão negativa",
    "novo_negocio": "Cliente novo?",
}


def _norm(t: str | None) -> str:
    t = "".join(c for c in unicodedata.normalize("NFD", t or "") if unicodedata.category(c) != "Mn").upper()
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", t).split())


# ----------------------------------------------------------------- regras
def regra(db: Session, entidade_id: int, tipo: str, chave: str) -> RegraAprendida | None:
    r = db.scalar(select(RegraAprendida).where(RegraAprendida.entidade_id == entidade_id, RegraAprendida.tipo == tipo,
                                               RegraAprendida.chave == chave[:255], RegraAprendida.ativa.is_(True)))
    if r:
        r.vezes_aplicada += 1
        r.ultima_aplicacao = datetime.now(UTC)
    return r


def aprender(db: Session, entidade_id: int, tipo: str, chave: str, descricao: str, acao: dict, usuario_id: int | None) -> RegraAprendida:
    r = db.scalar(select(RegraAprendida).where(RegraAprendida.entidade_id == entidade_id, RegraAprendida.tipo == tipo,
                                               RegraAprendida.chave == chave[:255]))
    if not r:
        r = RegraAprendida(entidade_id=entidade_id, tipo=tipo, chave=chave[:255], criada_por=usuario_id)
        db.add(r)
    r.descricao, r.acao, r.ativa = descricao[:255], acao, True
    db.flush()
    return r


def perguntar(db: Session, entidade_id: int, tipo: str, chave: str, titulo: str, descricao: str, contexto: dict,
              opcoes: list[dict], sugestao: str | None = None) -> Pendencia:
    """Cria a pendência ou soma a ocorrência na que já está aberta (mesmo tipo e chave)."""
    p = db.scalar(select(Pendencia).where(Pendencia.entidade_id == entidade_id, Pendencia.tipo == tipo,
                                          Pendencia.chave == chave[:255], Pendencia.status == "aberta"))
    if p:
        ctx = dict(p.contexto or {})
        for k, v in contexto.items():
            if isinstance(v, list) and isinstance(ctx.get(k), list):
                ctx[k] = list(dict.fromkeys(ctx[k] + v))
            else:
                ctx[k] = v
        p.contexto, p.opcoes, p.titulo, p.descricao = ctx, opcoes, titulo[:255], descricao
        p.sugestao = sugestao or p.sugestao
        p.ocorrencias = len(ctx.get("ids", [])) or p.ocorrencias + 1
        return p
    p = Pendencia(entidade_id=entidade_id, tipo=tipo, chave=chave[:255], titulo=titulo[:255], descricao=descricao,
                  contexto=contexto, opcoes=opcoes, sugestao=sugestao, ocorrencias=len(contexto.get("ids", [])) or 1)
    db.add(p)
    db.flush()
    return p


# ----------------------------------------------------------------- 1) categoria de lançamento
def _grupo_transacao(t: Transacao) -> tuple[str, str]:
    if t.contraparte_id:
        return f"cp:{t.contraparte_id}", t.contraparte_nome or t.descricao
    texto = _norm(re.sub(r"\d", " ", t.complemento or t.descricao))[:60]
    return f"tx:{'+' if t.valor > 0 else '-'}{texto}", (t.complemento or t.descricao)


def gerar_categorias(db: Session, entidade_id: int, dias: int = 120) -> int:
    """Lançamentos que as regras não categorizaram viram uma pergunta por contraparte (ou texto)."""
    from app.services.categorizacao import sugerir

    sug = {s.transacao_id: s for s in sugerir(db, entidade_id)}
    trs = db.scalars(
        select(Transacao).join(ContaFinanceira).where(
            ContaFinanceira.entidade_id == entidade_id, Transacao.categoria_id.is_(None), Transacao.conciliada.is_(False),
            Transacao.data >= date.today() - timedelta(days=dias))
    ).all()
    grupos: dict[str, list[Transacao]] = defaultdict(list)
    rotulo: dict[str, str] = {}
    for t in trs:
        k, r = _grupo_transacao(t)
        if regra(db, entidade_id, "ignorar_lancamento", k):
            t.conciliada = True
            continue
        grupos[k].append(t)
        rotulo[k] = r
    cats = {c.id: c.nome for c in db.scalars(select(Categoria).where(Categoria.entidade_id == entidade_id, Categoria.ativo.is_(True)))}
    for k, ts in grupos.items():
        votos = Counter(sug[t.id].categoria_id for t in ts if t.id in sug)
        opcoes = [{"id": f"cat:{c}", "rotulo": f"Categorizar como {cats[c]}"} for c, _ in votos.most_common(3) if c in cats]
        opcoes += [{"id": "outra", "rotulo": "Escolher outra categoria", "campos": ["categoria_id"]},
                   {"id": "ignorar", "rotulo": "Não é receita nem despesa (transferência entre contas, aplicação)"}]
        total = sum((t.valor for t in ts), Decimal(0))
        perguntar(db, entidade_id, "categoria", k, f"Como categorizar: {rotulo[k][:120]}",
                  f"{len(ts)} lançamento(s), total R$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                  {"ids": [t.id for t in ts]}, opcoes, opcoes[0]["id"] if votos else None)
    db.commit()
    return len(grupos)


def _resp_categoria(db, p: Pendencia, opcao: str, valores: dict, sempre: bool, uid):
    from app.services.categorizacao import criar_regra_de

    ids = p.contexto.get("ids", [])
    trs = db.scalars(select(Transacao).where(Transacao.id.in_(ids))).all()
    if opcao == "ignorar":
        for t in trs:
            t.conciliada = True
        if sempre and trs:
            k, r = _grupo_transacao(trs[0])
            return aprender(db, p.entidade_id, "ignorar_lancamento", k, f"Ignorar lançamentos de {r[:80]} (não é receita/despesa)", {}, uid)
        return None
    cat_id = int(opcao.split(":")[1]) if opcao.startswith("cat:") else int(valores.get("categoria_id") or 0)
    cat = db.get(Categoria, cat_id)
    if not cat or cat.entidade_id != p.entidade_id:
        raise HTTPException(422, "Escolha uma categoria")
    for t in trs:
        t.categoria_id, t.categoria_origem = cat.id, "manual"
    if sempre and trs:
        rc = criar_regra_de(db, p.entidade_id, trs[0], cat.id)
        k, r = _grupo_transacao(trs[0])
        return aprender(db, p.entidade_id, "categoria", k, f"{r[:80]} → {cat.nome}", {"categoria_id": cat.id, "regra_categorizacao_id": rc.id}, uid)
    return None


# ----------------------------------------------------------------- 2) créditos x extratos de comissão
_PALAVRAS_SEGURADORA = re.compile(r"SEGUR|SAUDE|PREVID|CAPITALIZ|ODONTO|ASSIST|VIDA\b|CONSORCIO")


def _pagador(t: Transacao) -> tuple[str, str]:
    from app.services.cnpj import so_digitos

    doc = so_digitos(t.contraparte_documento or "")
    nome = _norm(t.contraparte_nome or t.complemento or t.descricao)
    return (f"doc:{doc}" if len(doc) == 14 else f"nome:{nome[:60]}"), (t.contraparte_nome or t.descricao)


def conciliar_receber(db: Session, entidade_id: int) -> dict:
    """Casa créditos do banco com extratos de comissão (1 crédito = 1 extrato, ou soma de até 4 extratos),
    com tolerância de R$ 0,05. Pagador desconhecido ou crédito sem extrato vira pergunta."""
    from app.services.fechamento import norm_seguradora

    ent = db.get(Entidade, entidade_id)
    abertos = db.scalars(select(ExtratoComissao).where(ExtratoComissao.entidade_id == entidade_id,
                                                       ExtratoComissao.recebido_valor.is_(None))).all()
    if not abertos or ent.segmento != Segmento.CORRETORA:
        return {"conciliados": 0, "perguntas": 0}
    inicio = min(e.data for e in abertos) - timedelta(days=5)
    vinculados = set(db.scalars(select(ExtratoComissao.transacao_id).where(ExtratoComissao.transacao_id.is_not(None))))
    creditos = db.scalars(
        select(Transacao).join(ContaFinanceira).where(
            ContaFinanceira.entidade_id == entidade_id, Transacao.valor > 0, Transacao.conciliada.is_(False), Transacao.data >= inicio)
        .order_by(Transacao.data)
    ).all()
    por_seg: dict[str, list[ExtratoComissao]] = defaultdict(list)
    for e in abertos:
        por_seg[norm_seguradora(e.seguradora)].append(e)
    conciliados = perguntas = 0
    for t in creditos:
        if t.id in vinculados:
            continue
        chave, nome = _pagador(t)
        r = regra(db, entidade_id, "pagador", chave)
        seg = None
        if r:
            if r.acao.get("nao_comissao"):
                continue
            seg = r.acao.get("seguradora")
        else:
            texto = _norm(f"{t.contraparte_nome or ''} {t.descricao} {t.complemento or ''}")
            seg = next((s for s in por_seg if re.search(rf"\b{re.escape(s.split()[0])}\b", texto)), None)
            if seg is None:
                if chave.startswith("doc:") or _PALAVRAS_SEGURADORA.search(texto):
                    opcoes = [{"id": f"seg:{s}", "rotulo": f"É da {s}"} for s in sorted(por_seg)]
                    opcoes.append({"id": "nao", "rotulo": "Não é seguradora (não perguntar mais deste pagador)"})
                    perguntar(db, entidade_id, "pagador", chave, f"De quem é o crédito de {nome[:80]}?",
                              f"R$ {t.valor} em {t.data:%d/%m/%Y}. Respondendo, os próximos créditos dele são reconhecidos sozinhos.",
                              {"ids": [t.id], "nome": nome[:80]}, opcoes)
                    perguntas += 1
                continue
        cands = [e for e in por_seg.get(seg, []) if e.recebido_valor is None and e.data - timedelta(days=3) <= t.data <= e.data + timedelta(days=20)]
        par = _casar(t.valor, cands)
        if par:
            for e in par:
                e.recebido_valor, e.recebido_em, e.transacao_id = e.liquido, t.data, t.id
            t.conciliada = True
            conciliados += 1
        elif cands or por_seg.get(seg):
            opcoes = [{"id": f"ext:{e.id}", "rotulo": f"{e.codigo} — líquido R$ {e.liquido} ({e.data:%d/%m})"}
                      for e in sorted(por_seg.get(seg, []), key=lambda e: abs(e.liquido - t.valor))[:6] if e.recebido_valor is None]
            opcoes += [{"id": "nao_extrato", "rotulo": "Não é de extrato (outro recebimento)"},
                       {"id": "aguardar", "rotulo": "Ainda não importei o extrato (perguntar de novo depois)"}]
            perguntar(db, entidade_id, "credito_sem_extrato", f"tr:{t.id}", f"Crédito de R$ {t.valor} da {seg} sem extrato que bata",
                      f"{nome[:80]} em {t.data:%d/%m/%Y}. Escolha o extrato (pode ser pago com diferença) ou diga o que é.",
                      {"ids": [t.id], "seguradora": seg}, opcoes, opcoes[0]["id"] if opcoes and opcoes[0]["id"].startswith("ext:") else None)
            perguntas += 1
    db.commit()
    return {"conciliados": conciliados, "perguntas": perguntas}


def _casar(valor: Decimal, cands: list[ExtratoComissao]) -> list[ExtratoComissao] | None:
    from itertools import combinations

    tol = Decimal("0.05")
    um = sorted((e for e in cands if abs(e.liquido - valor) <= tol), key=lambda e: abs(e.liquido - valor))
    if um:
        return [um[0]]
    cands = cands[:12]
    for n in (2, 3, 4):
        for comb in combinations(cands, n):
            if abs(sum((e.liquido for e in comb), Decimal(0)) - valor) <= tol:
                return list(comb)
    return None


def _resp_pagador(db, p, opcao, valores, sempre, uid):
    chave = p.chave
    if opcao == "nao":
        return aprender(db, p.entidade_id, "pagador", chave, f"{p.contexto.get('nome', chave)}: não é seguradora", {"nao_comissao": True}, uid)
    seg = opcao.split(":", 1)[1]
    r = aprender(db, p.entidade_id, "pagador", chave, f"Créditos de {p.contexto.get('nome', chave)} são da {seg}", {"seguradora": seg}, uid)
    db.flush()
    conciliar_receber(db, p.entidade_id)
    return r


def _resp_credito(db, p, opcao, valores, sempre, uid):
    t = db.get(Transacao, p.contexto["ids"][0])
    if opcao == "aguardar":
        raise _Manter()
    if opcao == "nao_extrato":
        t.conciliada = True
        return None
    e = db.get(ExtratoComissao, int(opcao.split(":")[1]))
    e.recebido_valor, e.recebido_em, e.transacao_id = t.valor, t.data, t.id
    t.conciliada = True
    return None


class _Manter(Exception):
    """A resposta mantém a pendência aberta (ex.: aguardar o extrato)."""


# ----------------------------------------------------------------- 3..5, 7) comissões
def combos_vinculo(db, entidade_id: int) -> list[tuple]:
    linhas = db.execute(select(Comissao.origem, Comissao.produtor, Comissao.parceiro).where(
        Comissao.entidade_id == entidade_id, Comissao.origem.is_not(None))).all()
    return [c for c, _ in Counter(tuple(l) for l in linhas).most_common(5)]


def perguntar_vinculo(db, entidade_id: int, chave: str, cliente: str, seguradora: str, ids: list[int], combos: list[tuple]):
    opcoes = [{"id": "c:" + "|".join(x or "" for x in c), "rotulo": " / ".join(x or "—" for x in c)} for c in combos]
    opcoes.append({"id": "informar", "rotulo": "Informar origem, produtor e parceiro", "campos": ["origem", "produtor", "parceiro"]})
    perguntar(db, entidade_id, "vinculo", chave, f"Quem vendeu {cliente[:90]} ({seguradora})?",
              "Cliente não encontrado na BASE nem no FECHAMENTO. Responda uma vez e marque 'sempre' para os próximos extratos.",
              {"ids": ids, "cliente": cliente, "seguradora": seguradora}, opcoes)


def _resp_vinculo(db, p, opcao, valores, sempre, uid):
    if opcao.startswith("c:"):
        o, pr, pa = (x or None for x in opcao[2:].split("|"))
    else:
        o, pr, pa = ((valores.get(k) or "").strip().upper() or None for k in ("origem", "produtor", "parceiro"))
    if not o:
        raise HTTPException(422, "Informe pelo menos a origem")
    for c in db.scalars(select(Comissao).where(Comissao.id.in_(p.contexto.get("ids", [])))):
        c.origem, c.produtor, c.parceiro = o, pr, pa
        c.observacao = _sem_obs(c.observacao, "VERIFICAR: SEM VÍNCULO")
    if sempre:
        return aprender(db, p.entidade_id, "vinculo", p.chave, f"{p.contexto.get('cliente')} ({p.contexto.get('seguradora')}) → {o} / {pr or '—'} / {pa or '—'}",
                        {"origem": o, "produtor": pr, "parceiro": pa}, uid)
    return None


def _sem_obs(obs: str | None, tirar: str) -> str | None:
    partes = [x for x in (obs or "").split(" | ") if x and not x.startswith(tirar)]
    return " | ".join(partes) or None


def _resp_ramo(db, p, opcao, valores, sempre, uid):
    ramo = (valores.get("ramo") or "").strip().upper() if opcao == "OUTRO" else opcao
    if not ramo:
        raise HTTPException(422, "Informe o ramo")
    for c in db.scalars(select(Comissao).where(Comissao.id.in_(p.contexto.get("ids", [])))):
        c.ramo = ramo
        c.observacao = _sem_obs(c.observacao, "VERIFICAR RAMO")
    if sempre:
        return aprender(db, p.entidade_id, "ramo", p.chave, f"{p.contexto.get('cliente')} ({p.contexto.get('seguradora')}) → {ramo}", {"ramo": ramo}, uid)
    return None


TRATAMENTO_NEGATIVO = {"ESTORNO": "Estorno", "CANCELAMENTO": "Cancelamento", "COCORRETAGEM": "Cocorretagem (TRUST CCC)", "AJUSTE": "Ajuste"}


def aplicar_negativo(c: Comissao, tratamento: str):
    c.observacao = _sem_obs(c.observacao, "NEGATIVO:")
    c.observacao = " | ".join(x for x in (c.observacao, tratamento) if x)
    if tratamento == "COCORRETAGEM":
        c.parceiro = "TRUST CCC"


def _resp_negativo(db, p, opcao, valores, sempre, uid):
    for c in db.scalars(select(Comissao).where(Comissao.id.in_(p.contexto.get("ids", [])))):
        aplicar_negativo(c, opcao)
    if sempre:
        seg = p.contexto.get("seguradora", "")
        return aprender(db, p.entidade_id, "negativo", seg, f"Negativos da {seg} → {TRATAMENTO_NEGATIVO[opcao]}", {"tratamento": opcao}, uid)
    return None


def _resp_divergencia(db, p, opcao, valores, sempre, uid):
    e = db.get(ExtratoComissao, p.contexto.get("extrato_id"))
    if opcao == "excluir" and e:
        for c in db.scalars(select(Comissao).where(Comissao.extrato_id == e.id)):
            db.delete(c)
        db.delete(e)
        return None
    if sempre:
        seg = p.contexto.get("seguradora", "")
        return aprender(db, p.entidade_id, "aceitar_divergencia", seg, f"Aceitar diferenças nos extratos da {seg}", {}, uid)
    return None


def _resp_arquivo(db, p, opcao, valores, sempre, uid):
    if opcao == "ignorar":
        return aprender(db, p.entidade_id, "ignorar_arquivo", p.chave, f"Ignorar arquivos como {p.contexto.get('exemplo', p.chave)}", {}, uid)
    return None


def _resp_novo(db, p, opcao, valores, sempre, uid):
    from app.services.previsao import classificar_novos

    r = aprender(db, p.entidade_id, "novo_negocio", p.chave, f"{p.titulo[:-1]}: {'sim' if opcao == 'sim' else 'não'}",
                 {"novo": opcao == "sim"}, uid)
    db.flush()
    classificar_novos(db, p.entidade_id)
    return r


RESPONDER = {
    "categoria": _resp_categoria, "pagador": _resp_pagador, "credito_sem_extrato": _resp_credito, "vinculo": _resp_vinculo,
    "ramo": _resp_ramo, "negativo": _resp_negativo, "divergencia": _resp_divergencia, "arquivo": _resp_arquivo,
    "novo_negocio": _resp_novo,
}


def responder(db: Session, p: Pendencia, opcao: str, valores: dict | None, sempre: bool, usuario_id: int | None) -> Pendencia:
    if p.status != "aberta":
        raise HTTPException(409, "Esta pendência já foi resolvida")
    validas = {o["id"] for o in p.opcoes}
    if opcao not in validas:
        raise HTTPException(422, "Opção inválida")
    try:
        r = RESPONDER[p.tipo](db, p, opcao, valores or {}, sempre, usuario_id)
    except _Manter:
        db.commit()
        return p
    p.status, p.resposta, p.resolvida_em, p.resolvida_por = "resolvida", {"opcao": opcao, "valores": valores or {}, "sempre": sempre}, datetime.now(UTC), usuario_id
    p.regra_id = r.id if r else None
    db.commit()
    return p


def apos_importar_banco(db: Session, entidade_id: int) -> None:
    """Depois de um extrato bancário: conciliar créditos de comissão e perguntar o que ficou sem categoria."""
    conciliar_receber(db, entidade_id)
    gerar_categorias(db, entidade_id)
