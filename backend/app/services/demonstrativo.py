"""Demonstrativo de comissão em PDF (o que a produtora recebe e por quê)."""

from decimal import Decimal

from app.services.fechamento_mensal import _PDF, _secao, _t, _tabela, brl


def _pct(v) -> str:
    return f"{Decimal(v) * 100:.0f}%"


def gerar_pdf(a: dict) -> bytes:
    p = _PDF(format="A4")
    p.titulo = f"Demonstrativo de comissão - {a['nome']} - {a['rotulo']}"
    p.set_auto_page_break(True, 15)
    p.add_page()
    p.set_font("Helvetica", "B", 16)
    p.cell(0, 9, _t(f"Comissão de {a['rotulo']}"), new_x="LMARGIN", new_y="NEXT")
    p.set_font("Helvetica", "", 10)
    p.cell(0, 6, _t(a["nome"]), new_x="LMARGIN", new_y="NEXT")
    pt = a["patrimonial"]
    _secao(p, "Meta do mês")
    _tabela(p, ["", ""], [
        ["PL dos clientes com comissão no mês", brl(pt["pl_clientes"])],
        ["Ajuste manual", brl(pt["ajuste"])],
        ["PL para a meta", brl(pt["pl"])],
        ["Nível atingido", pt["nivel"]],
        ["% de comissão", _pct(pt["pct"])],
        ["Próxima faixa acima de", brl(pt["proxima"]) if pt["proxima"] is not None else "-"],
        ["Falta para a próxima faixa", brl(pt["falta"]) if pt["falta"] is not None else "-"],
    ], [120, 70])
    _secao(p, "Comissão")
    linhas = [["Comissão bruta do extrato (estornos já abatidos)", brl(pt["base"]), _pct(pt["pct"]), brl(pt["valor"])]]
    if pt["estornos"]:
        linhas.append(["   dos quais estornos", brl(pt["estornos"]), "", ""])
    ind = a["indicacoes"]
    if ind["bruto"]:
        linhas.append(["Indicações pessoais (bruto - impostos)", brl(ind["base"]), _pct(ind["pct"]), brl(ind["valor"])])
    if a["saude"]:
        for i in a["saude"]["itens"]:
            linhas.append(["Saúde: " + i["item"], brl(i["base"]), _pct(i["pct"]), brl(i["valor"])])
    if a["saldo_anterior"]:
        linhas.append(["Saldo negativo do mês anterior", "", "", brl(a["saldo_anterior"])])
    linhas.append(["TOTAL A RECEBER", "", "", brl(a["a_pagar"])])
    _tabela(p, ["Item", "Base", "%", "Valor"], linhas, [100, 35, 20, 35], "LRRR")
    if a["meta_pendente"]:
        p.set_font("Helvetica", "B", 9)
        p.multi_cell(0, 5, _t("Meta do mês ainda não cadastrada: o valor final sai quando a meta for informada."), new_x="LMARGIN", new_y="NEXT")
    _secao(p, "Lançamentos do mês")
    _tabela(p, ["Data", "Seguradora", "Cliente", "Bruta"],
            [[l["data"].strftime("%d/%m"), l["seguradora"], (l["cliente"] or "")[:40], brl(l["bruta"])] for l in a["linhas"][:150]],
            [20, 35, 100, 35], "LLLR")
    return bytes(p.output())
