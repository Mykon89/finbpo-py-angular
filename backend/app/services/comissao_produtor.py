"""Comissão das produtoras (regras do script da planilha + painel, simulador, conta a pagar e demonstrativo).

Nível (regra do "mês 9"): PL <= SEM META -> SEM META; <= PRATA -> BRONZE; <= OURO -> PRATA; <= DIAMANTE -> OURO;
acima -> DIAMANTE (a faixa BRONZE da tabela não entra no cálculo). Sem meta cadastrada: não calcula e avisa.
PL patrimonial = prêmio líquido (FECHAMENTO, mesma produtora) dos clientes com comissão positiva no extrato do mês.
Patrimonial: % do nível × comissão bruta do extrato da produtora (estornos abatem; saldo negativo passa para o mês seguinte).
Indicação pessoal: (bruto − imposto) × % da indicação, nas comissões em que ela é parceira (BASE ou FECHAMENTO).
Saúde (planilha da produtora): PL = fatura × 12 nas metas de saúde; 1ª parcela PME/PF e adesão pelo % do nível;
parcelas 2 até a N-ésima a % fixo.
"""

import calendar
import re
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AjustePL,
    ApuracaoComissao,
    Categoria,
    Comissao,
    Contraparte,
    GrupoDRE,
    LinhaSaude,
    MetaComissao,
    PlanoComissao,
    PropostaFechamento,
    StatusTitulo,
    TipoTitulo,
    Titulo,
)
from app.services.comissoes import _cat_ok, _nome_chave, cat_ramo, nomes_batem
from app.services.fechamento import norm_seguradora

Z = Decimal("0")
C = Decimal("0.01")
NIVEIS_PADRAO = [
    {"nome": "SEM META", "pct": 0.06, "pct_saude": 0.10},
    {"nome": "BRONZE", "pct": 0.08, "pct_saude": 0.30},
    {"nome": "PRATA", "pct": 0.10, "pct_saude": 0.32},
    {"nome": "OURO", "pct": 0.12, "pct_saude": 0.34},
    {"nome": "DIAMANTE", "pct": 0.15, "pct_saude": 0.36},
]
REGRAS_PADRAO = {"imposto_indicacao": 0.18, "pct_indicacao": 0.20, "desconto_cartao": 10, "saude_parcela_ate": 3, "saude_pct_demais": 0.10}
_FORA_PL = re.compile(r"DEBITO|SALDO|BONIF|CARTAO|BONUS|AJUSTE")
MESES = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]

# Metas de 2026 copiadas do script (abril a setembro; jan-mar zeradas = não cadastradas)
METAS_CP_2026 = {4: [144299.99, 144300, 165945, 190836.75, 219462.26], 5: [95999, 96000, 110400, 126960, 146004],
                 6: [79499, 79500, 91425, 105138.75, 120909.56], 7: [109999, 110000, 126500, 145475, 167296.25],
                 8: [139999, 140000, 161000, 185150, 212922.5], 9: [294000, 356000, 409400, 470810, 541431.5]}
METAS_CS_2026 = {4: [144299.99, 144300, 165945, 190836.75, 219462.26], 5: [95999, 96000, 110400, 126960, 146004],
                 6: [149999, 150000, 172500, 198375, 228131.25], 7: [150000, 150001, 172501, 198376, 228132.25],
                 8: [149999, 150000, 172500, 198375, 228131.25], 9: [149999, 150000, 172500, 198375, 228131.25]}


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


def _intervalo(ano: int, mes: int) -> tuple[date, date]:
    return date(ano, mes, 1), (date(ano + 1, 1, 1) if mes == 12 else date(ano, mes + 1, 1))


def _soma_mes(ano: int, mes: int, n: int) -> tuple[int, int]:
    t = ano * 12 + mes - 1 + n
    return t // 12, t % 12 + 1


def rotulo(ano: int, mes: int) -> str:
    return f"{MESES[mes - 1]}/{ano}"


def metas(db, plano_id: int, ano: int, mes: int, tipo: str) -> list[Decimal] | None:
    m = db.scalar(select(MetaComissao).where(MetaComissao.plano_id == plano_id, MetaComissao.ano == ano, MetaComissao.mes == mes, MetaComissao.tipo == tipo))
    if not m or len(m.faixas or []) != 5 or not _d(m.faixas[2]):
        return None
    return [_d(x) for x in m.faixas]


def nivel(pl: Decimal, faixas: list[Decimal] | None) -> int | None:
    if not faixas:
        return None
    sem, _, prata, ouro, diamante = faixas
    if pl <= sem:
        return 0
    if pl <= prata:
        return 1
    if pl <= ouro:
        return 2
    if pl <= diamante:
        return 3
    return 4


def proxima_faixa(pl: Decimal, faixas: list[Decimal] | None) -> Decimal | None:
    if not faixas:
        return None
    return next((f for f in (faixas[0], faixas[2], faixas[3], faixas[4]) if f >= pl), None)


def _pct(plano: PlanoComissao, idx: int | None, chave: str = "pct") -> Decimal:
    return _d(plano.niveis[idx][chave]) if idx is not None else Z


def _regra(plano: PlanoComissao, k: str) -> Decimal:
    return _d((plano.regras or {}).get(k, REGRAS_PADRAO[k]))


# ----------------------------------------------------------------- PL
def pl_clientes(db: Session, plano: PlanoComissao, ano: int, mes: int) -> list[dict]:
    ini, fim = _intervalo(ano, mes)
    excluir = {cat_ramo(r) for r in plano.excluir_ramos or []}
    linhas = db.scalars(select(Comissao).where(Comissao.entidade_id == plano.entidade_id, Comissao.data >= ini, Comissao.data < fim,
                                               Comissao.produtor == plano.produtor, Comissao.bruta > 0)).all()
    fech: dict[str, list] = {}
    for p in db.scalars(select(PropostaFechamento).where(PropostaFechamento.entidade_id == plano.entidade_id)):
        if (p.emissao and "CANCEL" in p.emissao) or not p.premio or p.premio <= 0 or (p.produtor or "") != plano.produtor:
            continue
        fech.setdefault(p.seguradora, []).append(p)
    aj = db.scalar(select(AjustePL).where(AjustePL.plano_id == plano.id, AjustePL.ano == ano, AjustePL.mes == mes))
    excluidos = set(aj.excluidos or []) if aj else set()
    vistos, saida = set(), []
    for c in linhas:
        ramo = cat_ramo(c.ramo)
        if _FORA_PL.search(ramo) or ramo in excluir:
            continue
        seg = norm_seguradora(c.seguradora)
        chave = f"{seg}|{_nome_chave(c.cliente)}"
        if chave in vistos:
            continue
        vistos.add(chave)
        nome = _nome_chave(c.cliente)
        cand = [p for p in fech.get(seg, []) if nomes_batem(nome, _nome_chave(p.cliente))]
        p = max(cand, key=lambda x: (x.ano, x.mes, x.linha)) if cand else None
        saida.append({"chave": chave, "cliente": c.cliente, "seguradora": seg, "ramo": c.ramo, "pl": _d(p.premio) if p else Z,
                      "fonte": f"FECHAMENTO {p.aba} linha {p.linha}" if p else "sem FECHAMENTO", "incluido": chave not in excluidos})
    return sorted(saida, key=lambda x: -x["pl"])


# ----------------------------------------------------------------- indicações
def _indicacoes(db: Session, plano: PlanoComissao, ano: int, mes: int) -> list[Comissao]:
    """Comissões do mês em que a produtora é parceira (na BASE) ou o FECHAMENTO diz que a indicação é dela."""
    ini, fim = _intervalo(ano, mes)
    aliases = {a.upper() for a in (plano.aliases_indicacao or [])}
    if not aliases:
        return []
    comissoes = db.scalars(select(Comissao).where(Comissao.entidade_id == plano.entidade_id, Comissao.data >= ini, Comissao.data < fim)).all()
    indicados: dict[str, list[tuple[str, str]]] = {}
    for p in db.scalars(select(PropostaFechamento).where(PropostaFechamento.entidade_id == plano.entidade_id)):
        quem = {(p.parceiro or "").upper(), (p.origem or "").upper()}
        if quem & aliases:
            indicados.setdefault(p.seguradora, []).append((_nome_chave(p.cliente), cat_ramo(p.ramo)))
    saida = []
    for c in comissoes:
        if (c.parceiro or "").upper() in aliases:
            saida.append(c)
            continue
        if (c.produtor or "") == plano.produtor:
            continue  # já é dela como produtora
        nome, cat = _nome_chave(c.cliente), cat_ramo(c.ramo)
        if any(nomes_batem(nome, n) and _cat_ok(cat, r) for n, r in indicados.get(norm_seguradora(c.seguradora), [])):
            saida.append(c)
    return saida


# ----------------------------------------------------------------- saúde (planilha)
def _saude(db: Session, plano: PlanoComissao, ano: int, mes: int) -> dict | None:
    if not plano.usa_planilha_saude:
        return None
    ls = db.scalars(select(LinhaSaude).where(LinhaSaude.plano_id == plano.id, LinhaSaude.ano == ano, LinhaSaude.mes == mes)).all()
    fatura = sum((l.fatura for l in ls), Z)
    pl = fatura * 12
    faixas = metas(db, plano.id, ano, mes, "saude")
    idx = nivel(pl, faixas)
    pct = _pct(plano, idx, "pct_saude")
    ate = int(_regra(plano, "saude_parcela_ate"))
    primeira = sum((l.comissao for l in ls if (l.plano or "") in ("PME", "PF") and l.parcela == 1), Z)
    ate_n = sum((l.comissao for l in ls if l.parcela is not None and l.parcela <= ate), Z)
    demais = ate_n - primeira
    adesao = sum((l.adesao for l in ls), Z)
    pct_dem = _regra(plano, "saude_pct_demais")
    itens = [
        {"item": "1ª parcela PME/PF (comissão)", "base": primeira, "pct": pct, "valor": (primeira * pct).quantize(C)},
        {"item": f"Demais parcelas até a {ate}ª e outros planos", "base": demais, "pct": pct_dem, "valor": (demais * pct_dem).quantize(C)},
        {"item": "Adesão", "base": adesao, "pct": pct, "valor": (adesao * pct).quantize(C)},
    ]
    return {"linhas": len(ls), "fatura": fatura, "pl": pl, "faixas": faixas, "nivel": _rot(plano, idx), "pct": pct,
            "proxima": proxima_faixa(pl, faixas), "itens": itens, "subtotal": sum((i["valor"] for i in itens), Z) if idx is not None else Z,
            "meta_cadastrada": faixas is not None}


def _rot(plano, idx):
    return plano.niveis[idx]["nome"] if idx is not None else "META NÃO CADASTRADA"


# ----------------------------------------------------------------- apuração
def apurar(db: Session, plano: PlanoComissao, ano: int, mes: int, pl_extra: Decimal = Z, comissao_extra: Decimal = Z) -> dict:
    ini, fim = _intervalo(ano, mes)
    excluir = {cat_ramo(r) for r in plano.excluir_ramos or []}
    clientes = pl_clientes(db, plano, ano, mes)
    aj = db.scalar(select(AjustePL).where(AjustePL.plano_id == plano.id, AjustePL.ano == ano, AjustePL.mes == mes))
    ajuste = _d(aj.valor) if aj else Z
    pl = sum((c["pl"] for c in clientes if c["incluido"]), Z) + ajuste + pl_extra
    faixas = metas(db, plano.id, ano, mes, "patrimonial")
    idx = nivel(pl, faixas)
    pct = _pct(plano, idx)
    prox = proxima_faixa(pl, faixas)

    linhas = db.scalars(select(Comissao).where(Comissao.entidade_id == plano.entidade_id, Comissao.data >= ini, Comissao.data < fim,
                                               Comissao.produtor == plano.produtor).order_by(Comissao.data, Comissao.id)).all()
    base_l = [c for c in linhas if cat_ramo(c.ramo) not in excluir and cat_ramo(c.ramo) != "CARTAO"]
    base = sum((c.bruta for c in base_l), Z) + comissao_extra
    estornos = sum((c.bruta for c in base_l if c.bruta < 0), Z)
    cartao = sum((c.bruta for c in linhas if cat_ramo(c.ramo) == "CARTAO"), Z)
    patrimonial = (base * pct).quantize(C) if idx is not None else Z

    ind = _indicacoes(db, plano, ano, mes)
    ind_bruto = sum((c.bruta for c in ind), Z)
    imp = (ind_bruto * _regra(plano, "imposto_indicacao")).quantize(C)
    ind_valor = ((ind_bruto - imp) * _regra(plano, "pct_indicacao")).quantize(C)

    saude = _saude(db, plano, ano, mes)
    ant_a, ant_m = _soma_mes(ano, mes, -1)
    ant = db.scalar(select(ApuracaoComissao).where(ApuracaoComissao.plano_id == plano.id, ApuracaoComissao.ano == ant_a, ApuracaoComissao.mes == ant_m))
    saldo_anterior = ant.total if ant and ant.total < 0 else Z
    bruto_total = patrimonial + ind_valor + (saude["subtotal"] if saude else Z) + saldo_anterior
    pendente_meta = idx is None or (saude is not None and not saude["meta_cadastrada"])
    return {
        "plano_id": plano.id, "produtor": plano.produtor, "nome": plano.nome, "ano": ano, "mes": mes, "rotulo": rotulo(ano, mes),
        "patrimonial": {"pl_clientes": sum((c["pl"] for c in clientes if c["incluido"]), Z), "ajuste": ajuste, "pl": pl, "faixas": faixas,
                        "nivel": _rot(plano, idx), "nivel_idx": idx, "pct": pct, "proxima": prox,
                        "falta": max(prox - pl, Z) if prox is not None else None, "base": base, "estornos": estornos, "valor": patrimonial,
                        "meta_cadastrada": faixas is not None},
        "indicacoes": {"bruto": ind_bruto, "imposto": imp, "base": ind_bruto - imp, "pct": _regra(plano, "pct_indicacao"), "valor": ind_valor,
                       "linhas": [{"data": c.data, "seguradora": c.seguradora, "cliente": c.cliente, "bruta": c.bruta} for c in ind]},
        "saude": saude,
        "cartao_informativo": cartao,
        "saldo_anterior": saldo_anterior,
        "total": bruto_total,
        "a_pagar": max(bruto_total, Z) if not pendente_meta else Z,
        "meta_pendente": pendente_meta,
        "clientes_pl": clientes,
        "linhas": [{"data": c.data, "seguradora": c.seguradora, "ramo": c.ramo, "cliente": c.cliente, "bruta": c.bruta, "parcela": c.parcela_texto}
                   for c in linhas],
    }


def painel(db: Session, plano: PlanoComissao, hoje: date | None = None) -> dict:
    """Mês corrente em tempo real, com projeção linear do PL até o fim do mês."""
    hoje = hoje or date.today()
    a = apurar(db, plano, hoje.year, hoje.month)
    dias = calendar.monthrange(hoje.year, hoje.month)[1]
    pl = a["patrimonial"]["pl"]
    projetado = (pl * dias / max(hoje.day, 1)).quantize(C)
    faixas = a["patrimonial"]["faixas"]
    return {**a, "dias_passados": hoje.day, "dias_mes": dias, "pl_projetado": projetado,
            "nivel_projetado": _rot(plano, nivel(projetado, faixas))}


def simular(db: Session, plano: PlanoComissao, ano: int, mes: int, pl_extra: Decimal, comissao_extra: Decimal) -> dict:
    atual = apurar(db, plano, ano, mes)
    novo = apurar(db, plano, ano, mes, pl_extra, comissao_extra)
    return {"atual": {"nivel": atual["patrimonial"]["nivel"], "total": atual["total"]},
            "simulado": {"nivel": novo["patrimonial"]["nivel"], "pct": novo["patrimonial"]["pct"], "total": novo["total"],
                         "pl": novo["patrimonial"]["pl"], "proxima": novo["patrimonial"]["proxima"], "falta": novo["patrimonial"]["falta"]},
            "ganho": novo["total"] - atual["total"]}


def historico(db: Session, plano: PlanoComissao, ano: int) -> list[dict]:
    saida = []
    for m in range(1, 13):
        a = apurar(db, plano, ano, m)
        saida.append({"mes": m, "rotulo": a["rotulo"], "pl": a["patrimonial"]["pl"], "nivel": a["patrimonial"]["nivel"],
                      "base": a["patrimonial"]["base"], "pct": a["patrimonial"]["pct"], "indicacoes": a["indicacoes"]["valor"],
                      "saude": a["saude"]["subtotal"] if a["saude"] else None, "total": a["total"]})
    return saida


# ----------------------------------------------------------------- conta a pagar
def vencimento(db: Session, entidade_id: int, ano: int, mes: int) -> date:
    """Um dia (útil) antes do primeiro imposto do mês de pagamento (DAS/INSS/FGTS...); sem imposto lançado, dia 19."""
    from app.models import AjusteDiaUtil
    from app.services.recorrencias import ajustar

    ini, fim = _intervalo(ano, mes)
    impostos = db.scalars(select(Titulo.vencimento).join(Categoria, Categoria.id == Titulo.categoria_id).where(
        Titulo.entidade_id == entidade_id, Titulo.tipo == TipoTitulo.PAGAR, Titulo.vencimento >= ini, Titulo.vencimento < fim,
        Categoria.grupo_dre.in_([GrupoDRE.DEDUCOES, GrupoDRE.IMPOSTOS_LUCRO]) | Categoria.nome.ilike("%DAS%") | Categoria.nome.ilike("%INSS%")
        | Categoria.nome.ilike("%FGTS%") | Categoria.nome.ilike("%IRRF%")).order_by(Titulo.vencimento)).all()
    base = impostos[0] if impostos else date(ano, mes, 20)
    return ajustar(base - timedelta(days=1), AjusteDiaUtil.ANTECIPAR)


def gerar_conta(db: Session, plano: PlanoComissao, ano: int, mes: int) -> dict:
    """Cria/atualiza a conta a pagar da comissão da competência (enquanto não paga). Sem meta: não gera."""
    a = apurar(db, plano, ano, mes)
    ap = db.scalar(select(ApuracaoComissao).where(ApuracaoComissao.plano_id == plano.id, ApuracaoComissao.ano == ano, ApuracaoComissao.mes == mes))
    if a["meta_pendente"]:
        return {"situacao": "meta não cadastrada", "total": a["total"]}
    if not ap:
        ap = ApuracaoComissao(plano_id=plano.id, ano=ano, mes=mes)
        db.add(ap)
    ap.total = a["total"]
    pa, pm = _soma_mes(ano, mes, plano.meses_para_pagar)
    venc = vencimento(db, plano.entidade_id, pa, pm)
    desc = f"COMISSÃO {plano.produtor} {mes:02d}/{ano}"
    tit = db.get(Titulo, ap.titulo_id) if ap.titulo_id else None
    if tit is None and plano.contraparte_id:
        ini, fim = _intervalo(pa, pm)  # conta já lançada à mão/planilha no mês de pagamento: aproveita
        tit = db.scalar(select(Titulo).where(Titulo.entidade_id == plano.entidade_id, Titulo.tipo == TipoTitulo.PAGAR,
                                             Titulo.contraparte_id == plano.contraparte_id, Titulo.descricao.ilike("%COMISS%"),
                                             Titulo.vencimento >= ini, Titulo.vencimento < fim))
    if a["a_pagar"] <= 0:
        db.commit()
        return {"situacao": "sem valor a pagar (saldo vai para o mês seguinte)" if a["total"] < 0 else "sem comissão", "total": a["total"]}
    if tit is None:
        tit = Titulo(entidade_id=plano.entidade_id, tipo=TipoTitulo.PAGAR, descricao=desc, contraparte_id=plano.contraparte_id,
                     categoria_id=plano.categoria_id, competencia=date(ano, mes, 1), vencimento=venc, valor=a["a_pagar"],
                     observacao="Gerada pelo FinBPO (comissão da produtora)")
        db.add(tit)
        db.flush()
        situacao = "criada"
    elif tit.status == StatusTitulo.ABERTO and not tit.baixas:
        tit.valor, tit.descricao, tit.vencimento = a["a_pagar"], desc, venc  # corrige cópia de recorrência ("09/2026" em novembro)
        tit.competencia = date(ano, mes, 1)
        situacao = "atualizada"
    else:
        situacao = "já paga (não alterada)"
    ap.titulo_id = tit.id
    db.commit()
    return {"situacao": situacao, "titulo_id": tit.id, "vencimento": tit.vencimento, "valor": tit.valor, "total": a["total"]}


def gerar_contas_do_mes(db: Session, hoje: date | None = None) -> list[dict]:
    """Rotina diária: comissão do mês anterior de cada produtora ativa (cria no dia 1, atualiza até ser paga)."""
    hoje = hoje or date.today()
    a, m = _soma_mes(hoje.year, hoje.month, -1)
    return [{"produtor": p.produtor, **gerar_conta(db, p, a, m)} for p in db.scalars(select(PlanoComissao).where(PlanoComissao.ativo.is_(True)))]


def metas_faltando(db: Session, hoje: date | None = None) -> list[str]:
    hoje = hoje or date.today()
    faltam = []
    for p in db.scalars(select(PlanoComissao).where(PlanoComissao.ativo.is_(True))):
        tipos = ["patrimonial"] + (["saude"] if p.usa_planilha_saude else [])
        sem = [t for t in tipos if metas(db, p.id, hoje.year, hoje.month, t) is None]
        if sem:
            faltam.append(f"{p.nome} ({', '.join(sem)})")
    return faltam


# ----------------------------------------------------------------- planilha de saúde
MESES_LONGOS = ["JANEIRO", "FEVEREIRO", "MARCO", "ABRIL", "MAIO", "JUNHO", "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"]


def ler_planilha_saude(conteudo: bytes, ano: int) -> list[dict]:
    import io

    from openpyxl import load_workbook

    from app.services.fechamento import _hdr, _num

    wb = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    saida = []
    for ws in wb.worksheets:
        nome = _hdr(ws.title)
        if nome not in MESES_LONGOS:
            continue
        mes = MESES_LONGOS.index(nome) + 1
        linhas = list(ws.iter_rows(values_only=True, max_col=20))
        if not linhas:
            continue
        H = [_hdr(c) for c in linhas[0]]

        def ix(n, prefixo=False):
            return next((i for i, x in enumerate(H) if (x.startswith(n) if prefixo else x == n)), -1)

        c = {"cli": ix("CLIENTE"), "op": ix("OPERADORA"), "plano": ix("PLANO"), "fat": ix("FATURA"), "com": ix("COMISSAO"),
             "ad": ix("ADESAO"), "parc": ix("PARCELA", True), "ind": ix("INDICA", True)}
        if c["cli"] < 0 or c["com"] < 0:
            continue

        def v(r, k):
            i = c[k]
            return r[i] if 0 <= i < len(r) else None

        for r in linhas[1:]:
            cli = " ".join(str(v(r, "cli") or "").split())
            if not cli:
                continue
            mp = re.match(r"^(\d+)\s*/\s*(\d+)", str(v(r, "parc") or ""))
            saida.append({"ano": ano, "mes": mes, "cliente": cli.upper()[:200], "operadora": (str(v(r, "op") or "").strip().upper() or None),
                          "plano": re.sub(r"[^A-Z]", "", str(v(r, "plano") or "").upper()) or None, "fatura": _num(v(r, "fat")) or Z,
                          "comissao": _num(v(r, "com")) or Z, "adesao": _num(v(r, "ad")) or Z,
                          "parcela": int(mp.group(1)) if mp else None, "indicacao": (str(v(r, "ind") or "").strip().upper() or None)})
    return saida


def gravar_planilha_saude(db: Session, plano: PlanoComissao, linhas: list[dict]) -> int:
    from sqlalchemy import delete

    anos = {l["ano"] for l in linhas}
    if anos:
        db.execute(delete(LinhaSaude).where(LinhaSaude.plano_id == plano.id, LinhaSaude.ano.in_(anos)))
    for l in linhas:
        db.add(LinhaSaude(plano_id=plano.id, **l))
    db.commit()
    return len(linhas)


def sincronizar_saude(db: Session, plano: PlanoComissao, ano: int | None = None) -> int:
    from app.services.fechamento import baixar

    if not plano.planilha_saude_id:
        raise ValueError("Informe o link da planilha de saúde da produtora")
    return gravar_planilha_saude(db, plano, ler_planilha_saude(baixar(plano.planilha_saude_id), ano or date.today().year))


# ----------------------------------------------------------------- modelo do script
def criar_planos_modelo(db: Session, entidade_id: int) -> list[PlanoComissao]:
    def cp(nome):
        return db.scalar(select(Contraparte).where(Contraparte.entidade_id == entidade_id, Contraparte.nome.ilike(f"{nome}%")))

    cat = db.scalar(select(Categoria).where(Categoria.entidade_id == entidade_id, Categoria.nome.ilike("%comiss%vendedor%")))
    criados = []
    for produtor, nome, aliases, saude in (
        ("GIOVANNA", "GIOVANNA BEATRIZ MOREIRA RAMIREZ", ["GIOVANNA"], False),
        ("FABIANA", "FABIANA RODRIGUES CAIXETA", ["FABIANA", "FABI CAIXETA"], True),
    ):
        if db.scalar(select(PlanoComissao).where(PlanoComissao.entidade_id == entidade_id, PlanoComissao.produtor == produtor)):
            continue
        c = cp(nome)
        p = PlanoComissao(entidade_id=entidade_id, produtor=produtor, nome=nome, niveis=NIVEIS_PADRAO, regras=REGRAS_PADRAO,
                          aliases_indicacao=aliases, excluir_ramos=["SAUDE", "ODONTO"] if saude else [], usa_planilha_saude=saude,
                          planilha_saude_id="11qd_JIJtyRhI_rygYZUMw598e-fUHV2dZoRoeEcQIjc" if saude else None,
                          contraparte_id=c.id if c else None, categoria_id=cat.id if cat else None)
        db.add(p)
        db.flush()
        for m, f in METAS_CP_2026.items():
            db.add(MetaComissao(plano_id=p.id, ano=2026, mes=m, tipo="patrimonial", faixas=f))
        if saude:
            for m, f in METAS_CS_2026.items():
                db.add(MetaComissao(plano_id=p.id, ano=2026, mes=m, tipo="saude", faixas=f))
        criados.append(p)
    db.commit()
    return criados


def arred(v: Decimal) -> Decimal:
    return Decimal(v).quantize(C, ROUND_HALF_UP)
