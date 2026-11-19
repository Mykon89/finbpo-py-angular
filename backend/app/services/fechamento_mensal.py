"""Fechamento mensal: números do mês, análise automática com sugestões de corte de gastos e PDF.

A análise tem duas partes:
- automática (regras, sem custo): variações por categoria, juros e multas, tarifas, assinaturas, retiradas x lucro...
- do Claude (opcional, pela assinatura): pelo conector MCP, o Claude lê `dados_fechamento` e grava o texto com
  `salvar_analise_fechamento`; o PDF passa a trazer essa seção.
"""

import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from fpdf import FPDF
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AnaliseMensal,
    Baixa,
    Categoria,
    Comissao,
    ContaFinanceira,
    Contraparte,
    Entidade,
    GrupoDRE as G,
    Pendencia,
    Segmento,
    StatusTitulo,
    TipoTitulo,
    Titulo,
    Transacao,
)
from app.services.dre import calcular_dre

Z = Decimal("0")
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
_DESPESA = {G.CUSTOS, G.DESPESAS_PESSOAL, G.DESPESAS_ADMINISTRATIVAS, G.DESPESAS_COMERCIAIS, G.DESPESAS_FINANCEIRAS, G.DEDUCOES}


def _mes(ano: int, mes: int, n: int) -> tuple[int, int]:
    t = ano * 12 + mes - 1 + n
    return t // 12, t % 12 + 1


def _intervalo(ano, mes):
    a2, m2 = _mes(ano, mes, 1)
    return date(ano, mes, 1), date(a2, m2, 1)


def brl(v) -> str:
    v = Decimal(v or 0)
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-R$ " if v < 0 else "R$ ") + s


def _por_categoria(db, eid: int, ano: int, mes: int) -> dict[int, Decimal]:
    ini, fim = _intervalo(ano, mes)
    linhas = db.execute(
        select(Transacao.categoria_id, func.sum(Transacao.valor)).join(ContaFinanceira).where(
            ContaFinanceira.entidade_id == eid, Transacao.data >= ini, Transacao.data < fim, Transacao.categoria_id.is_not(None))
        .group_by(Transacao.categoria_id)
    ).all()
    return {c: Decimal(str(v or 0)) for c, v in linhas}


def dados(db: Session, entidade_id: int, ano: int, mes: int) -> dict:
    ent = db.get(Entidade, entidade_id)
    ini, fim = _intervalo(ano, mes)
    dre = calcular_dre(db, entidade_id, ano, mes)
    anteriores = [calcular_dre(db, entidade_id, *_mes(ano, mes, -i)) for i in (1, 2, 3)]
    cats = {c.id: c for c in db.scalars(select(Categoria).where(Categoria.entidade_id == entidade_id))}
    atual = _por_categoria(db, entidade_id, ano, mes)
    hist = [_por_categoria(db, entidade_id, *_mes(ano, mes, -i)) for i in (1, 2, 3)]
    despesas = []
    for cid, v in atual.items():
        c = cats.get(cid)
        if not c or c.grupo_dre not in _DESPESA or v >= 0:
            continue
        media = -sum((h.get(cid, Z) for h in hist), Z) / 3  # positivo
        despesas.append({"categoria": c.nome, "grupo": c.grupo_dre.value, "valor": -v, "media_3m": media,
                         "variacao_pct": float((-v - media) / media * 100) if media > 0 else None})  # + = gastou mais
    despesas.sort(key=lambda x: -x["valor"])
    total_desp = sum((d["valor"] for d in despesas), Z)

    # contas a pagar
    pagar = db.scalars(select(Titulo).options(selectinload(Titulo.baixas)).where(
        Titulo.entidade_id == entidade_id, Titulo.tipo == TipoTitulo.PAGAR)).all()
    hoje = date.today()
    ref = min(fim - timedelta(days=1), hoje)
    atrasadas = [t for t in pagar if t.status in (StatusTitulo.ABERTO, StatusTitulo.PARCIAL) and t.vencimento < ref]
    pagas_mes = [(t, b) for t in pagar for b in t.baixas if ini <= b.data < fim]
    pagas_atraso = [(t, b) for t, b in pagas_mes if b.data > t.vencimento + timedelta(days=1)]
    acrescimos = [t for t, _ in pagas_mes if "acréscimo" in (t.observacao or "") or (t.observacao or "").find("previsto") >= 0]
    descontos = sum((t.desconto or Z for t, _ in pagas_mes), Z)
    proximos = [t for t in pagar if t.status in (StatusTitulo.ABERTO, StatusTitulo.PARCIAL) and ref <= t.vencimento <= ref + timedelta(days=30)]

    # fornecedores
    cps = {c.id: c.nome for c in db.scalars(select(Contraparte).where(Contraparte.entidade_id == entidade_id))}
    por_forn: dict[str, Decimal] = defaultdict(Decimal)
    for t, b in pagas_mes:
        por_forn[cps.get(t.contraparte_id, t.descricao[:40])] += b.valor
    top_forn = sorted(por_forn.items(), key=lambda x: -x[1])[:8]

    comissoes = None
    if ent.segmento == Segmento.CORRETORA:
        linhas = db.execute(select(Comissao.seguradora, func.sum(Comissao.bruta), func.count(Comissao.id)).where(
            Comissao.entidade_id == entidade_id, Comissao.data >= ini, Comissao.data < fim).group_by(Comissao.seguradora)).all()
        ini_a, fim_a = _intervalo(*_mes(ano, mes, -1))
        ant = db.scalar(select(func.coalesce(func.sum(Comissao.bruta), 0)).where(
            Comissao.entidade_id == entidade_id, Comissao.data >= ini_a, Comissao.data < fim_a))
        novos = db.execute(select(func.count(Comissao.id), func.coalesce(func.sum(Comissao.bruta), 0)).where(
            Comissao.entidade_id == entidade_id, Comissao.data >= ini, Comissao.data < fim, Comissao.novo_negocio.is_(True))).one()
        comissoes = {
            "bruta": sum((Decimal(str(v)) for _, v, _ in linhas), Z), "anterior": Decimal(str(ant or 0)),
            "por_seguradora": sorted(((s, Decimal(str(v))) for s, v, _ in linhas), key=lambda x: -x[1])[:8],
            "novos_qtd": novos[0], "novos_valor": Decimal(str(novos[1])),
        }
    pend = db.scalar(select(func.count(Pendencia.id)).where(Pendencia.entidade_id == entidade_id, Pendencia.status == "aberta")) or 0
    analise_ia = db.scalar(select(AnaliseMensal).where(AnaliseMensal.entidade_id == entidade_id, AnaliseMensal.ano == ano, AnaliseMensal.mes == mes))
    d = {
        "entidade": ent.nome, "segmento": ent.segmento.value, "ano": ano, "mes": mes, "rotulo": f"{MESES[mes - 1]} de {ano}",
        "dre": dre, "resultado_anteriores": [a["resultado_liquido"] for a in anteriores],
        "receita": dre["linhas"][0]["valor"], "despesas_total": total_desp, "despesas": despesas,
        "sem_categoria": dre["sem_categoria"], "nao_operacional": dre["nao_operacional"],
        "atrasadas": [{"descricao": t.descricao, "vencimento": t.vencimento, "saldo": t.saldo, "dias": (ref - t.vencimento).days} for t in atrasadas],
        "pagas_com_atraso": len(pagas_atraso), "acrescimos": len(acrescimos), "descontos_obtidos": descontos,
        "proximos_30": sum((t.saldo for t in proximos), Z), "proximos_30_qtd": len(proximos),
        "top_fornecedores": top_forn, "comissoes": comissoes, "pendencias_abertas": pend,
        "analise_ia": analise_ia.texto if analise_ia else None,
    }
    d["sugestoes"] = sugestoes(db, entidade_id, d, cats, atual, hist)
    return d


_ASSINATURA = re.compile(r"software|licen|mensalidade|assinatura|sistema|telefon|internet|cloud|streaming", re.I)


def sugestoes(db, eid: int, d: dict, cats: dict, atual: dict, hist: list) -> list[dict]:
    """Regras simples e explicáveis; cada sugestão diz o porquê e, quando dá, a economia estimada por mês."""
    s: list[dict] = []
    for x in d["despesas"]:
        if x["variacao_pct"] is not None and x["variacao_pct"] >= 20 and x["valor"] - x["media_3m"] >= 100:
            s.append({"titulo": f"{x['categoria']} subiu {x['variacao_pct']:.0f}%",
                      "texto": f"{brl(x['valor'])} no mês contra média de {brl(x['media_3m'])} nos 3 anteriores. Verifique o que mudou.",
                      "economia": x["valor"] - x["media_3m"]})
    juros = sum((-v for cid, v in atual.items() if cats.get(cid) and re.search(r"juro|multa", cats[cid].nome, re.I) and v < 0), Z)
    if juros > 0 or d["pagas_com_atraso"]:
        s.append({"titulo": "Juros, multas e pagamentos atrasados",
                  "texto": f"{brl(juros)} em juros/multas e {d['pagas_com_atraso']} conta(s) paga(s) depois do vencimento. "
                           "Os alertas diários por e-mail ajudam a pagar em dia.", "economia": juros})
    tarifas = sum((-v for cid, v in atual.items() if cats.get(cid) and re.search(r"tarifa", cats[cid].nome, re.I) and v < 0), Z)
    if tarifas >= 50:
        s.append({"titulo": "Tarifas bancárias", "texto": f"{brl(tarifas)} no mês ({brl(tarifas * 12)} por ano). Compare o pacote "
                  "com o que você usa e peça uma proposta ao gerente; tarifas costumam ser negociáveis.", "economia": tarifas / 2})
    assin = [(cats[cid].nome, -v) for cid, v in atual.items() if cats.get(cid) and _ASSINATURA.search(cats[cid].nome) and v < 0]
    if assin:
        tot = sum((v for _, v in assin), Z)
        s.append({"titulo": "Assinaturas, sistemas e telefonia", "texto": f"{brl(tot)} no mês ({brl(tot * 12)} por ano) em "
                  + ", ".join(n for n, _ in assin[:4]) + ". Revise o que não é usado e renegocie planos.", "economia": tot * Decimal("0.15")})
    resultado = Decimal(d["dre"]["resultado_liquido"])
    retiradas = sum((-v for cid, v in atual.items() if cats.get(cid) and re.search(r"antecipa..o de lucros|distribui..o|retirada|pessoais dos s", cats[cid].nome, re.I) and v < 0), Z)
    if retiradas > 0 and retiradas > max(resultado, Z):
        s.append({"titulo": "Retiradas acima do lucro", "texto": f"Retiradas dos sócios de {brl(retiradas)} com resultado de {brl(resultado)}. "
                  "O caixa está financiando a diferença.", "economia": Z})
    if d["despesas_total"] and d["top_fornecedores"]:
        top3 = sum((v for _, v in d["top_fornecedores"][:3]), Z)
        if top3 / d["despesas_total"] >= Decimal("0.5"):
            s.append({"titulo": "Concentração em poucos fornecedores",
                      "texto": f"3 fornecedores somam {top3 / d['despesas_total'] * 100:.0f}% dos pagamentos: "
                      + ", ".join(n for n, _ in d["top_fornecedores"][:3]) + ". Bons candidatos a renegociação ou cotação.",
                      "economia": top3 * Decimal("0.05")})
    if Decimal(d["sem_categoria"] or 0):
        s.append({"titulo": "Lançamentos sem categoria", "texto": f"{brl(d['sem_categoria'])} sem categoria distorcem a análise. "
                  "Responda as perguntas na Central de decisões.", "economia": Z})
    return s


# ----------------------------------------------------------------- PDF
def _t(texto) -> str:
    """Fonte padrão do PDF é latin-1: troca o que não cabe."""
    trocas = {"—": "-", "–": "-", "→": "->", "“": '"', "”": '"', "‘": "'", "’": "'", "•": "-", "…": "...", "≥": ">=", "≤": "<="}
    t = "".join(trocas.get(c, c) for c in str(texto))
    return t.encode("latin-1", "replace").decode("latin-1")


class _PDF(FPDF):
    titulo = ""

    def header(self):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(110)
        self.cell(0, 6, _t(self.titulo), align="L")
        self.ln(8)
        self.set_text_color(0)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(140)
        self.cell(0, 6, _t(f"FinBPO - página {self.page_no()}"), align="R")


def _secao(p: _PDF, texto: str):
    p.ln(3)
    p.set_font("Helvetica", "B", 12)
    p.set_text_color(31, 78, 121)
    p.cell(0, 7, _t(texto), new_x="LMARGIN", new_y="NEXT")
    p.set_text_color(0)
    p.set_font("Helvetica", "", 9)


def _tabela(p: _PDF, cab: list[str], linhas: list[list], larg: list[int], alinhar: str = "LRR"):
    p.set_font("Helvetica", "B", 8)
    p.set_fill_color(230, 236, 245)
    for c, w, a in zip(cab, larg, alinhar.ljust(len(cab), "R")):
        p.cell(w, 6, _t(c), border=0, fill=True, align=a)
    p.ln()
    p.set_font("Helvetica", "", 8)
    for i, l in enumerate(linhas):
        p.set_fill_color(247, 249, 252)
        for c, w, a in zip(l, larg, alinhar.ljust(len(cab), "R")):
            p.cell(w, 5.5, _t(c)[:70], border=0, fill=i % 2 == 1, align=a)
        p.ln()


def gerar_pdf(db: Session, entidade_id: int, ano: int, mes: int) -> bytes:
    d = dados(db, entidade_id, ano, mes)
    p = _PDF(format="A4")
    p.titulo = f"{d['entidade']} - fechamento de {d['rotulo']}"
    p.set_auto_page_break(True, 15)
    p.add_page()
    p.set_font("Helvetica", "B", 18)
    p.cell(0, 10, _t(f"Fechamento de {d['rotulo']}"), new_x="LMARGIN", new_y="NEXT")
    p.set_font("Helvetica", "", 10)
    p.cell(0, 6, _t(d["entidade"]), new_x="LMARGIN", new_y="NEXT")

    res = Decimal(d["dre"]["resultado_liquido"])
    ant = [Decimal(x) for x in d["resultado_anteriores"]]
    _secao(p, "Resumo")
    resumo = [
        ["Receita bruta", brl(d["receita"])],
        ["Despesas e deduções", brl(-d["despesas_total"])],
        ["Resultado do mês", brl(res)],
        ["Média do resultado nos 3 meses anteriores", brl(sum(ant, Z) / 3)],
        ["Margem líquida", f"{d['dre']['margem_liquida_pct']}%" if d["dre"].get("margem_liquida_pct") is not None else "-"],
        ["Contas atrasadas", f"{len(d['atrasadas'])} ({brl(sum((a['saldo'] for a in d['atrasadas']), Z))})"],
        ["A pagar nos próximos 30 dias", f"{d['proximos_30_qtd']} ({brl(d['proximos_30'])})"],
        ["Descontos obtidos no mês", brl(d["descontos_obtidos"])],
        ["Perguntas abertas na Central de decisões", str(d["pendencias_abertas"])],
    ]
    if d["comissoes"]:
        c = d["comissoes"]
        resumo.insert(1, ["Comissões (bruto dos extratos)", f"{brl(c['bruta'])} (mês anterior {brl(c['anterior'])})"])
        resumo.insert(2, ["Novos negócios", f"{c['novos_qtd']} ({brl(c['novos_valor'])})"])
    _tabela(p, ["", ""], resumo, [120, 70])

    if d["analise_ia"]:
        _secao(p, "Análise do Claude")
        p.multi_cell(0, 5, _t(d["analise_ia"]), new_x="LMARGIN", new_y="NEXT")
    _secao(p, "Onde dá para economizar")
    if d["sugestoes"]:
        total = sum((Decimal(x["economia"]) for x in d["sugestoes"]), Z)
        for x in d["sugestoes"]:
            p.set_font("Helvetica", "B", 9)
            p.multi_cell(0, 5, _t("- " + x["titulo"] + (f" (economia estimada {brl(x['economia'])}/mês)" if Decimal(x["economia"]) > 0 else "")), new_x="LMARGIN", new_y="NEXT")
            p.set_font("Helvetica", "", 9)
            p.multi_cell(0, 5, _t("  " + x["texto"]), new_x="LMARGIN", new_y="NEXT")
        if total > 0:
            p.set_font("Helvetica", "B", 9)
            p.multi_cell(0, 6, _t(f"Potencial somado: {brl(total)} por mês ({brl(total * 12)} por ano)."), new_x="LMARGIN", new_y="NEXT")
    else:
        p.multi_cell(0, 5, _t("Nenhum ponto de atenção pelas regras automáticas neste mês."), new_x="LMARGIN", new_y="NEXT")
    if not d["analise_ia"]:
        p.set_font("Helvetica", "I", 8)
        p.set_text_color(110)
        p.multi_cell(0, 4.5, _t(f"Para incluir a análise do Claude, peça no Claude (conector finbpo): \"faça a análise do fechamento de "
                                f"{d['rotulo']} da {d['entidade']}\" e gere o PDF de novo."))
        p.set_text_color(0)

    _secao(p, "DRE gerencial (regime de caixa)")
    _tabela(p, ["Linha", "Valor"], [[l["rotulo"], brl(l["valor"])] for l in d["dre"]["linhas"]], [140, 50])
    _secao(p, "Despesas por categoria")
    _tabela(p, ["Categoria", "No mês", "Média 3 meses", "Variação"],
            [[x["categoria"], brl(x["valor"]), brl(x["media_3m"]), "-" if x["variacao_pct"] is None else f"{x['variacao_pct']:+.0f}%"]
             for x in d["despesas"][:20]], [90, 35, 35, 30])
    if d["top_fornecedores"]:
        _secao(p, "Maiores pagamentos por fornecedor")
        _tabela(p, ["Fornecedor", "Pago no mês"], [[n, brl(v)] for n, v in d["top_fornecedores"]], [140, 50])
    if d["comissoes"]:
        _secao(p, "Comissões por seguradora")
        _tabela(p, ["Seguradora", "Bruto"], [[s, brl(v)] for s, v in d["comissoes"]["por_seguradora"]], [140, 50])
    if d["atrasadas"]:
        _secao(p, "Contas em atraso")
        _tabela(p, ["Conta", "Vencimento", "Saldo", "Dias"],
                [[a["descricao"], a["vencimento"].strftime("%d/%m/%Y"), brl(a["saldo"]), str(a["dias"])] for a in d["atrasadas"][:25]],
                [100, 30, 35, 25], "LRRR")
    return bytes(p.output())
