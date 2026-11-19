"""Conciliação do contas a pagar com os débitos do banco (mesmas 6 passadas do script da planilha).

Passadas, em ordem (dias = data do débito - vencimento):
 1. fornecedor+valor          tolerância R$ 0,05, -45..+120 dias, até 6 contas somadas
 2. fornecedor+valor aprox.   até 25% (conta variável) ou 5% (fixa), -30..+20 dias, 1 conta
 3. fornecedor+desconto       pago até 30% a menos, -15..+3 dias, 1 conta (o resto vira desconto)
 4. descrição+desconto        texto do banco contém a descrição da conta (com número), -15..+5 dias
 5. categoria+valor           mesma categoria, -20..+30 dias, até 6 contas (ex.: Caju recarrega VA e VT)
 6. valor+data                só valor, -5..+15 dias, 1 conta (não casa com conta de outro fornecedor conhecido)
O fornecedor do débito é a contraparte do lançamento ou um "apelido" aprendido (favorecido do banco -> fornecedor).
Débito que sobra: regra aprendida (lançar como conta paga / ignorar) ou pergunta na Central de decisões.
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Categoria,
    ContaFinanceira,
    Contraparte,
    Natureza,
    Recorrencia,
    StatusTitulo,
    TipoTitulo,
    Titulo,
    Transacao,
)
from app.services import decisoes
from app.services.conciliacao import vincular

TOL = Decimal("0.05")
PASSADAS = [
    dict(nome="fornecedor+valor", dmin=-45, dmax=120, max_n=6, forn=True),
    dict(nome="fornecedor+valor aprox.", dmin=-30, dmax=20, max_n=1, forn=True, pct=Decimal("0.25")),
    dict(nome="fornecedor+desconto", dmin=-15, dmax=3, max_n=1, forn=True, pct=Decimal("0.30"), desc=True),
    dict(nome="descrição+desconto", dmin=-15, dmax=5, max_n=1, txt=True, pct=Decimal("0.30"), desc=True),
    dict(nome="categoria+valor", dmin=-20, dmax=30, max_n=6, cat=True),
    dict(nome="valor+data", dmin=-5, dmax=15, max_n=1),
]


@dataclass
class _Deb:
    t: Transacao
    valor: Decimal
    forn: int | None
    cat: int | None
    txt: str


_SIN = {"SL": "SALA", "SLA": "SALA", "AP": "APTO", "APT": "APTO", "CONDOM": "COND", "TAXA": "TX", "PARC": "PARCELA"}
_GEN = {"DE", "DA", "DO", "DOS", "DAS", "E", "A", "O", "EM"}


def _toks(t: str) -> list[str]:
    return [_SIN.get(x, x) for x in decisoes._norm(t).split() if x not in _GEN]


def texto_bate(banco: str, desc_conta: str) -> bool:
    a, b = _toks(desc_conta), set(_toks(banco))
    if len(a) < 3 or not any(re.search(r"\d", x) for x in a):
        return False
    return all(x in b for x in a if not re.fullmatch(r"\d{2}/?\d{4}", x))


def _achar(itens: list[tuple[int, Decimal]], alvo: Decimal, max_n: int) -> list[tuple[int, Decimal]] | None:
    """Subconjunto de até max_n contas que soma o débito (busca limitada, como no script)."""
    ordem = sorted(itens, key=lambda x: -x[1])
    passos = [0]

    def dfs(i, soma, esc):
        passos[0] += 1
        if passos[0] > 200000:
            return None
        if esc and abs(soma - alvo) <= TOL:
            return list(esc)
        if len(esc) >= max_n or soma > alvo + TOL:
            return None
        for j in range(i, len(ordem)):
            esc.append(ordem[j])
            r = dfs(j + 1, soma + ordem[j][1], esc)
            esc.pop()
            if r:
                return r
        return None

    return dfs(0, Decimal(0), [])


def chave_favorecido(t: Transacao) -> str:
    return decisoes._pagador(t)[0]


def conciliar_pagar(db: Session, entidade_id: int, dias: int = 180, perguntar: bool = True) -> dict:
    debitos_t = db.scalars(
        select(Transacao).join(ContaFinanceira).where(
            ContaFinanceira.entidade_id == entidade_id, Transacao.valor < 0, Transacao.conciliada.is_(False),
            Transacao.data >= date.today() - timedelta(days=dias)).order_by(Transacao.data)
    ).all()
    titulos = db.scalars(
        select(Titulo).options(selectinload(Titulo.baixas)).where(
            Titulo.entidade_id == entidade_id, Titulo.tipo == TipoTitulo.PAGAR,
            Titulo.status.in_([StatusTitulo.ABERTO, StatusTitulo.PARCIAL]))
    ).all()
    saldo = {t.id: t.saldo for t in titulos}
    por_id = {t.id: t for t in titulos}
    livres: list[_Deb] = []
    for t in debitos_t:
        if decisoes.regra(db, entidade_id, "ignorar_lancamento", decisoes._grupo_transacao(t)[0]):
            t.conciliada = True
            continue
        apelido = decisoes.regra(db, entidade_id, "favorecido", chave_favorecido(t))
        forn = apelido.acao["contraparte_id"] if apelido else t.contraparte_id
        livres.append(_Deb(t, -t.valor, forn, t.categoria_id, f"{t.descricao} {t.complemento or ''}"))
    feitos = 0
    variaveis_dif: list[tuple[Titulo, Decimal]] = []
    for ps in PASSADAS:
        for d in list(livres):
            abertos = [l for l in titulos if saldo[l.id] > TOL]
            cand = []
            for l in abertos:
                dd = (d.t.data - l.vencimento).days
                if dd < ps["dmin"] or dd > ps["dmax"]:
                    continue
                if ps.get("txt"):
                    ok = texto_bate(d.txt, l.descricao)
                elif ps.get("cat"):
                    ok = d.cat is not None and l.categoria_id == d.cat
                elif ps.get("forn"):
                    ok = d.forn is not None and l.contraparte_id == d.forn
                else:
                    ok = not (d.forn and l.contraparte_id and l.contraparte_id != d.forn)
                if ok:
                    cand.append(l)
            cand.sort(key=lambda l: abs((d.t.data - l.vencimento).days))
            if ps["max_n"] > 1:
                cand = cand[:16]
            if not cand:
                continue
            hit = None
            if ps.get("pct"):
                for l in cand:
                    s = saldo[l.id]
                    if ps.get("txt") and abs(s - d.valor) <= TOL:
                        ok = True
                    elif ps.get("desc"):
                        ok = d.valor < s and s - d.valor <= s * ps["pct"]
                    else:
                        lim = ps["pct"] if l.natureza == Natureza.VARIAVEL else Decimal("0.05")
                        ok = abs(s - d.valor) <= s * lim
                    if ok:
                        hit = [(l.id, d.valor)]
                        break
            else:
                hit = _achar([(l.id, saldo[l.id]) for l in cand], d.valor, ps["max_n"])
            if not hit:
                continue
            for tid, v in hit:
                tit = por_id[tid]
                if ps.get("pct"):
                    dif = saldo[tid] - v
                    if dif > 0:
                        tit.desconto = (tit.desconto or Decimal(0)) + dif  # pago a menos: desconto
                    elif dif < 0:
                        tit.valor += -dif  # pago a mais: juros/multa
                        tit.observacao = ((tit.observacao or "") + f" · pago com acréscimo de R$ {-dif}").strip(" ·")
                    if tit.recorrencia_id and abs(dif) > saldo[tid] * Decimal("0.05"):
                        variaveis_dif.append((tit, v))
                    saldo[tid] = Decimal(0)
                else:
                    saldo[tid] -= v
                vincular(db, d.t, tit, v)
                tit.observacao = ((tit.observacao or "") + f" · conciliado ({ps['nome']})").strip(" ·")[:2000]
            livres.remove(d)
            feitos += 1
    criadas = _auto_lancar(db, entidade_id, livres)
    if perguntar:
        _perguntar(db, entidade_id, [d for d in livres if not d.t.conciliada], titulos, saldo)
        for tit, v in variaveis_dif:
            _perguntar_recorrencia(db, entidade_id, tit, v)
    db.commit()
    return {"conciliados": feitos, "lancados_automaticamente": criadas, "sem_conta": sum(1 for d in livres if not d.t.conciliada)}


def _lancar_pago(db, entidade_id: int, t: Transacao, contraparte_id: int | None, categoria_id: int | None, descricao: str) -> Titulo:
    tit = Titulo(entidade_id=entidade_id, tipo=TipoTitulo.PAGAR, descricao=descricao[:255], contraparte_id=contraparte_id,
                 categoria_id=categoria_id, competencia=t.data.replace(day=1), vencimento=t.data, valor=-t.valor,
                 natureza=Natureza.VARIAVEL, observacao="Lançado a partir do banco")
    db.add(tit)
    db.flush()
    vincular(db, t, tit, -t.valor)
    if categoria_id:
        t.categoria_id, t.categoria_origem = categoria_id, "regra"
    return tit


def _auto_lancar(db, entidade_id: int, livres: list[_Deb]) -> int:
    """Favorecidos aprendidos como "lançar como conta paga" (ex.: retirada de sócio, abastecimento, tarifas fixas)."""
    n = 0
    for d in livres:
        r = decisoes.regra(db, entidade_id, "criar_cap", chave_favorecido(d.t))
        if r:
            _lancar_pago(db, entidade_id, d.t, r.acao.get("contraparte_id") or d.t.contraparte_id, r.acao.get("categoria_id"),
                         r.acao.get("descricao") or d.t.descricao)
            n += 1
    return n


def _perguntar(db, entidade_id: int, livres: list[_Deb], titulos: list[Titulo], saldo: dict) -> None:
    for d in livres:
        t = d.t
        perto = sorted((l for l in titulos if saldo[l.id] > TOL and abs((t.data - l.vencimento).days) <= 45),
                       key=lambda l: (abs(saldo[l.id] - d.valor), abs((t.data - l.vencimento).days)))[:5]
        opcoes = [{"id": f"tit:{l.id}", "rotulo": f"É a conta {l.descricao[:60]} — R$ {saldo[l.id]} (venc. {l.vencimento:%d/%m})"} for l in perto]
        opcoes += [
            {"id": "fornecedor", "rotulo": "É de um fornecedor/sócio que já tem contas (pode pagar várias de uma vez)", "campos": ["fornecedor"]},
            {"id": "lancar", "rotulo": "Não tem conta: lançar como conta paga", "campos": ["categoria_id", "descricao"]},
            {"id": "socio", "rotulo": "Retirada de sócio (antecipação de lucros)"},
            {"id": "ignorar", "rotulo": "Transferência entre contas / aplicação (não é despesa)"},
        ]
        nome = t.contraparte_nome or t.complemento or t.descricao
        decisoes.perguntar(db, entidade_id, "debito_sem_conta", f"tr:{t.id}", f"Pagamento de R$ {d.valor} para {nome[:80]}",
                           f"{t.data:%d/%m/%Y} · {t.descricao[:120]}. Nenhuma conta a pagar bateu.",
                           {"ids": [t.id], "nome": nome[:80]}, opcoes,
                           opcoes[0]["id"] if perto and abs(saldo[perto[0].id] - d.valor) <= d.valor * Decimal("0.3") else None)


def _perguntar_recorrencia(db, entidade_id: int, tit: Titulo, pago: Decimal) -> None:
    rec = db.get(Recorrencia, tit.recorrencia_id)
    if not rec or rec.valor == pago:
        return
    decisoes.perguntar(db, entidade_id, "recorrencia_valor", f"rec:{rec.id}",
                       f"{rec.descricao[:80]} veio R$ {pago} (previsto R$ {rec.valor})",
                       "Atualizar o valor das próximas contas desta recorrência?",
                       {"recorrencia_id": rec.id, "valor": str(pago)},
                       [{"id": "atualizar", "rotulo": f"Sim, passar a prever R$ {pago}"}, {"id": "manter", "rotulo": "Não, foi só este mês"}], "manter")


def _categoria_socio(db, entidade_id: int) -> Categoria | None:
    cats = db.scalars(select(Categoria).where(Categoria.entidade_id == entidade_id, Categoria.ativo.is_(True))).all()
    return next((c for c in cats if re.search(r"antecipa..o de lucros|distribui..o de lucros|retirada", c.nome, re.I)), None)


def responder_debito(db, p, opcao, valores, sempre, uid):
    t = db.get(Transacao, p.contexto["ids"][0])
    if t.conciliada:
        return None
    chave = chave_favorecido(t)
    nome = p.contexto.get("nome", "")
    if opcao.startswith("tit:"):
        tit = db.scalar(select(Titulo).options(selectinload(Titulo.baixas)).where(Titulo.id == int(opcao[4:])))
        v = min(-t.valor, tit.saldo) if -t.valor <= tit.saldo else -t.valor
        if -t.valor > tit.saldo:
            tit.valor += -t.valor - tit.saldo
        vincular(db, t, tit, v)
        if sempre and tit.contraparte_id and tit.contraparte_id != t.contraparte_id:
            cp = db.get(Contraparte, tit.contraparte_id)
            return decisoes.aprender(db, p.entidade_id, "favorecido", chave, f"Pagamentos para {nome} são do fornecedor {cp.nome}",
                                     {"contraparte_id": cp.id}, uid)
        return None
    if opcao == "fornecedor":
        from fastapi import HTTPException
        from sqlalchemy import func

        nome_f = " ".join((valores.get("fornecedor") or "").split())
        cps = db.scalars(select(Contraparte).where(Contraparte.entidade_id == p.entidade_id, Contraparte.nome.ilike(f"%{nome_f}%"))).all() if len(nome_f) >= 3 else []
        com_conta = [c for c in cps if db.scalar(select(func.count(Titulo.id)).where(Titulo.contraparte_id == c.id))]
        if len(com_conta) != 1:
            raise HTTPException(422, "Não achei um único fornecedor com esse nome que tenha contas" + (f": {', '.join(c.nome for c in com_conta[:5])}" if com_conta else ""))
        cp = com_conta[0]
        r = decisoes.aprender(db, p.entidade_id, "favorecido", chave, f"Pagamentos para {nome} são do fornecedor {cp.nome}", {"contraparte_id": cp.id}, uid)
        db.flush()
        conciliar_pagar(db, p.entidade_id, perguntar=False)
        if not t.conciliada:
            raise HTTPException(422, f"Aprendi que é {cp.nome}, mas nenhuma combinação das contas dele bate com R$ {-t.valor}")
        return r
    if opcao == "ignorar":
        t.conciliada = True
        if sempre:
            k = decisoes._grupo_transacao(t)[0]
            return decisoes.aprender(db, p.entidade_id, "ignorar_lancamento", k, f"Ignorar pagamentos para {nome} (transferência)", {}, uid)
        return None
    if opcao == "socio":
        cat = _categoria_socio(db, p.entidade_id)
        cat_id, desc = (cat.id if cat else None), f"RETIRADA {nome}"[:120]
    else:
        cat_id = int(valores.get("categoria_id") or 0) or None
        cat = db.get(Categoria, cat_id) if cat_id else None
        if not cat or cat.entidade_id != p.entidade_id:
            from fastapi import HTTPException

            raise HTTPException(422, "Escolha a categoria")
        desc = (valores.get("descricao") or "").strip() or nome or t.descricao
    _lancar_pago(db, p.entidade_id, t, t.contraparte_id, cat_id, desc)
    if sempre:
        return decisoes.aprender(db, p.entidade_id, "criar_cap", chave,
                                 f"Pagamentos para {nome}: lançar como conta paga ({cat.nome if cat else 'sem categoria'})",
                                 {"categoria_id": cat_id, "descricao": desc, "contraparte_id": t.contraparte_id}, uid)
    return None


def responder_recorrencia(db, p, opcao, valores, sempre, uid):
    if opcao == "atualizar":
        rec = db.get(Recorrencia, p.contexto["recorrencia_id"])
        rec.valor = Decimal(p.contexto["valor"])
        for tit in db.scalars(select(Titulo).where(Titulo.recorrencia_id == rec.id, Titulo.status == StatusTitulo.ABERTO,
                                                   Titulo.vencimento > date.today())):
            tit.valor = rec.valor
    return None


decisoes.RESPONDER["debito_sem_conta"] = responder_debito
decisoes.RESPONDER["recorrencia_valor"] = responder_recorrencia
decisoes.TIPOS["debito_sem_conta"] = "Pagamento sem conta a pagar"
decisoes.TIPOS["recorrencia_valor"] = "Conta recorrente com valor diferente"
