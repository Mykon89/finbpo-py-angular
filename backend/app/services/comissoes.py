"""Grava extratos de seguradoras como ExtratoComissao + linhas de Comissao, com vínculo pelo histórico."""

import re
from collections import defaultdict
import unicodedata
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Comissao, ExtratoComissao, PropostaFechamento
from app.services import decisoes
from app.services.fechamento import norm_seguradora
from app.services.extratos_seguradoras import Extrato, parcela_texto
from app.services.planilha import chave_comissao

SEM_VINCULO = "VERIFICAR: SEM VÍNCULO"


@dataclass
class ResultadoExtrato:
    arquivo: str
    codigo: str
    seguradora: str
    data: str
    bruto: Decimal
    iss: Decimal
    liquido: Decimal
    linhas: int
    gravadas: int = 0
    ja_importado: bool = False
    sem_vinculo: list[str] = field(default_factory=list)
    divergencias: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


_FORA = {"LTDA", "ME", "EPP", "EIRELI", "SA", "S", "A", "DE", "DA", "DO", "DOS", "DAS", "E", "EM"}
PRODUTORES_VALIDOS = re.compile(r"^(FABIANA|GIOVANNA)\b", re.I)
REGEX_BONIFICACAO = re.compile(r"^(PAGTO PROG|BONIFIC|PREMIA|PROGRAMA DE)", re.I)
PARCEIRO_COCORRETAGEM = "TRUST CCC"
CLIENTES_SOMADOS = [re.compile(r"AMMO BURG"), re.compile(r"^ADECON\b")]  # uma linha só por extrato


def _sem_acento(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t or "") if unicodedata.category(c) != "Mn")


def _nome_chave(nome: str | None) -> str:
    t = _sem_acento(nome).upper()
    t = re.sub(r"^[A-Z]{1,3}\d{2,4}\s*/\s*\d+\s*-\s*\d+\s*[A-Z\u00aa\u00b0\u00ba]?\s*-\s*", "", t)
    t = re.sub(r"\b\d+\b", " ", re.sub(r"[^A-Z0-9 ]", " ", re.sub(r"\(.*?\)", " ", t)))
    return " ".join(w for w in t.split() if w not in _FORA)


def nomes_batem(a: str, b: str) -> bool:
    """Tolera nome cortado ("ANA CAROLINA ALVES PINTO MARTINS" x "... DE MELLO") e sobrenome abreviado."""
    if not a or not b:
        return False
    if a == b:
        return True
    curto, longo = (a, b) if len(a) <= len(b) else (b, a)
    if len(curto) >= 12 and len(curto.split()) >= 2 and longo.startswith(curto):
        return True
    tc, tl = curto.split(), longo.split()
    if len(tc) >= 2:
        ult = tc[-1]
        inteiras = all(w in tl for w in tc[:-1])
        ult_ok = any(w == ult or (len(ult) >= 3 and w.startswith(ult)) for w in tl)
        return inteiras and ult_ok and tc[0] == tl[0]
    return False


def cat_ramo(r: str | None) -> str:
    s = _sem_acento(r).upper()
    for padrao, cat in ((r"ODONTO", "ODONTO"), (r"VIDA|ACID", "VIDA"), (r"SAUDE|PME|ADESAO", "SAUDE"), (r"AUTO", "AUTO"),
                        (r"CONSORCIO", "CONSORCIO"), (r"^RE$|RESID|EMPRES|CONDOM", "RE")):
        if re.search(padrao, s):
            return cat
    return s


def _cat_ok(a: str, b: str) -> bool:
    return not a or not b or a == b or {a, b} == {"SAUDE", "ODONTO"}


def produtor_valido(p: str | None) -> str | None:
    p = (p or "").strip()
    return p.upper() if PRODUTORES_VALIDOS.match(p) else None


@dataclass
class _Hist:
    data: object
    id: int
    apol: str
    nome: str
    cliente: str
    cat: str
    ramo: str | None
    v: tuple


class Vinculos:
    """Mesma regra do script (buscarVinculo, parte BASE): na mesma seguradora, entre linhas com
    ORIGEM/PRODUTOR/PARCEIRO preenchidos, procura por apólice; senão por nome no mesmo ramo; senão
    por nome em outro ramo (marca VERIFICAR). Vale a linha mais recente."""

    def __init__(self, db: Session, entidade_id: int):
        self.por_seg: dict[str, list[_Hist]] = {}
        linhas = db.execute(
            select(
                Comissao.id, Comissao.data, Comissao.seguradora, Comissao.apolice, Comissao.cliente, Comissao.ramo,
                Comissao.origem, Comissao.produtor, Comissao.parceiro,
            ).where(Comissao.entidade_id == entidade_id)
        ).all()
        for id_, data, seg, apol, cli, ramo, *v in linhas:
            if not any(v):
                continue
            self.por_seg.setdefault(norm_seguradora(seg), []).append(
                _Hist(data, id_, re.sub(r"\D", "", apol or ""), _nome_chave(cli), cli or "", cat_ramo(ramo), ramo, tuple(v))
            )

    def buscar(self, seguradora: str, apolice: str, cliente: str, ramo: str) -> tuple[_Hist | None, str | None]:
        pool = self.por_seg.get(norm_seguradora(seguradora), [])
        apol, nome, cat = re.sub(r"\D", "", apolice or ""), _nome_chave(cliente), cat_ramo(ramo)
        consorcio = cat == "CONSORCIO"
        achados, motivo = [], None
        if len(apol) >= 5 and not consorcio:
            achados = [h for h in pool if h.apol == apol]
        if not achados:
            achados = [h for h in pool if nomes_batem(nome, h.nome) and _cat_ok(cat, h.cat)]
        if not achados and not consorcio:
            achados = [h for h in pool if nomes_batem(nome, h.nome)]
            if achados:
                motivo = f"VERIFICAR VÍNCULO: nome existe em outro ramo ({achados[0].cat})"
        if not achados:
            return None, None
        b = max(achados, key=lambda h: (h.data, h.id))
        mes = (b.data.year, b.data.month)
        combos = {h.v for h in achados if (h.data.year, h.data.month) == mes}
        if len(combos) > 1:
            motivo = "VERIFICAR VÍNCULO: mesmo cliente no mesmo mês com informações diferentes"
        return b, motivo


@dataclass
class _Fech:
    chave: tuple  # (ano, mes, linha): ordem de "mais recente"
    nome: str
    cat: str
    tipo: str
    v: tuple  # origem, produtor, parceiro
    ref: str


class Fechamento:
    """Planilha FECHAMENTO DE PROPOSTAS sincronizada (passo 2 do buscarVinculo do script)."""

    def __init__(self, db: Session, entidade_id: int):
        self.por_seg: dict[str, list[_Fech]] = {}
        for p in db.scalars(select(PropostaFechamento).where(PropostaFechamento.entidade_id == entidade_id)):
            orig, prod, parc = p.origem, p.produtor, p.parceiro
            if orig and not re.fullmatch(r"KETTE|ISADORA|ATUAL\s*PREV", orig):
                # origem fora de Kette/Isadora/AtualPrev = Kette; se for produtora e não há parceiro, ela indicou
                if not parc and produtor_valido(orig):
                    parc = produtor_valido(orig)
                orig = "KETTE"
            if orig and re.fullmatch(r"ATUAL\s*PREV", orig):
                orig = "ATUALPREV"
            self.por_seg.setdefault(p.seguradora, []).append(
                _Fech((p.ano, p.mes, p.linha), _nome_chave(p.cliente), cat_ramo(p.ramo), _sem_acento(p.tipo or "").upper(),
                      (orig, prod, parc), f"FECHAMENTO {p.aba} linha {p.linha}")
            )

    def __bool__(self):
        return bool(self.por_seg)

    def candidatos(self, seguradora: str, cliente: str, ramo: str) -> tuple[list[_Fech], bool]:
        pool = self.por_seg.get(norm_seguradora(seguradora), [])
        nome, cat = _nome_chave(cliente), cat_ramo(ramo)
        achados = [f for f in pool if nomes_batem(nome, f.nome) and _cat_ok(cat, f.cat)]
        if achados:
            return achados, False
        return [f for f in pool if nomes_batem(nome, f.nome)], True

    def buscar(self, seguradora: str, cliente: str, ramo: str) -> tuple[_Fech | None, str | None]:
        achados, outro_ramo = self.candidatos(seguradora, cliente, ramo)
        if not achados:
            return None, None
        f = max(achados, key=lambda x: x.chave)
        motivo = f"VERIFICAR VÍNCULO: nome existe no FECHAMENTO em outro ramo ({f.cat})" if outro_ramo else None
        if len({x.v for x in achados if x.chave[:2] == f.chave[:2]}) > 1:
            motivo = "VERIFICAR VÍNCULO: FECHAMENTO com informações diferentes no mesmo mês"
        return f, motivo

    def mais_novo_que(self, h: "_Hist", seguradora: str, cliente: str, ramo: str) -> _Fech | None:
        """FECHAMENTO do mesmo mês da BASE ou mais novo, com produtor ou parceiro diferente, manda (regra do script)."""
        if cat_ramo(ramo) == "CONSORCIO":
            return None
        achados = [f for f in self.candidatos(seguradora, cliente, ramo)[0] if f.v[1] or f.v[2]]
        achados = [f for f in achados if _cat_ok(cat_ramo(ramo), f.cat)]
        if not achados:
            return None
        f = max(achados, key=lambda x: x.chave)
        if f.chave[:2] < (h.data.year, h.data.month):
            return None
        prod_b, parc_b = (h.v[1] or "").upper(), (h.v[2] or "").upper()
        if (f.v[1] and f.v[1] != prod_b) or (f.v[2] and f.v[2] != parc_b):
            return f
        return None


def consolidar(grupos):
    """CLIENTES_SOMADOS: soma em uma linha (mesmo sinal), com a apólice do primeiro."""
    vistos, saida = {}, []
    for g in grupos:
        nm = _sem_acento(g.cliente).upper()
        ix = next((i for i, rx in enumerate(CLIENTES_SOMADOS) if rx.search(nm)), None)
        if ix is None:
            saida.append(g)
            continue
        k = (ix, g.bruta < 0)
        if k not in vistos:
            vistos[k] = g
            saida.append(g)
            continue
        a = vistos[k]
        a.bruta += g.bruta
        a.parcelas += [p for p in g.parcelas if p not in a.parcelas]
    return saida


def _imposto(bruta: Decimal) -> Decimal:
    if bruta <= 0:
        return Decimal("0")
    return (bruta * Decimal(str(settings.aliquota_imposto_comissao))).quantize(Decimal("0.01"), ROUND_HALF_UP)


def gravar(db: Session, entidade_id: int, extratos: list[Extrato], arquivo: str) -> list[ResultadoExtrato]:
    vinc = Vinculos(db, entidade_id)
    fech = Fechamento(db, entidade_id)
    saida = []
    novas: list = []
    pendentes_div: list = []
    for e in extratos:
        r = ResultadoExtrato(arquivo, e.codigo, e.seguradora, e.data.isoformat(), e.bruto, e.iss, e.liquido, e.linhas,
                             divergencias=list(e.divergencias), avisos=list(e.avisos))
        saida.append(r)
        ext = db.scalar(select(ExtratoComissao).where(ExtratoComissao.entidade_id == entidade_id, ExtratoComissao.codigo == e.codigo))
        if ext and db.scalar(select(Comissao.id).where(Comissao.extrato_id == ext.id).limit(1)):
            r.ja_importado = True
            continue
        if not ext:
            ext = ExtratoComissao(entidade_id=entidade_id, codigo=e.codigo, seguradora=e.seguradora, data=e.data)
            db.add(ext)
        ext.documento, ext.bruto, ext.iss, ext.liquido, ext.debitos = e.documento or None, e.bruto, e.iss, e.liquido, e.debitos
        ext.arquivo = arquivo[:255]
        db.flush()
        grupos = consolidar(e.grupos)
        # negativo e positivo da mesma apólice/parcela no mesmo extrato = cocorretagem (regra do script)
        em_par = set()
        for i, a in enumerate(grupos):
            for j, b in enumerate(grupos):
                if a.bruta < 0 < b.bruta and a.apolice and a.apolice == b.apolice and parcela_texto(e, a) == parcela_texto(e, b):
                    em_par |= {i, j}
        for n, g in enumerate(grupos, 1):
            obs = [g.obs] if g.obs else []
            if REGEX_BONIFICACAO.search(g.cliente or "") and not g.debito:
                g.ramo = "BONIFICACAO"
            if g.ramo in ("VIAGEM", "BONIFICACAO") and not g.origem_fixa:
                g.origem_fixa = "KETTE"  # viagem e bonificação: sempre Kette, sem produtora/parceiro
            if g.origem_fixa:
                origem, produtor, parceiro = g.origem_fixa, None, None
            else:
                h, motivo = vinc.buscar(e.seguradora, g.apolice, g.cliente, g.ramo)
                f = None
                if h and fech:
                    f = fech.mais_novo_que(h, e.seguradora, g.cliente, g.ramo)
                    if f:
                        motivo = None  # o FECHAMENTO é a fonte escolhida: alertas da BASE não valem
                elif fech:
                    f, motivo = fech.buscar(e.seguradora, g.cliente, g.ramo)
                if h:
                    antigo = h.cliente.upper()
                    if (
                        antigo != g.cliente
                        and not re.match(r"^[A-Z]{1,3}\d{2,4}\s*/", antigo)  # nome no formato de consórcio
                        and nomes_batem(_nome_chave(g.cliente), h.nome)
                    ):
                        g.cliente = antigo  # nome já cadastrado na BASE prevalece
                    if g.ramo == "?" and h.ramo:
                        g.ramo = h.ramo
                aprendida = None if (f or h) else decisoes.regra(db, entidade_id, "vinculo", chave_vinculo(e.seguradora, g.cliente, g.ramo))
                if f or h:
                    origem, produtor, parceiro = f.v if f else (x.upper() if x else None for x in h.v)
                    if motivo:
                        obs.insert(0, motivo)
                elif aprendida:
                    origem, produtor, parceiro = (aprendida.acao.get(k) for k in ("origem", "produtor", "parceiro"))
                else:
                    origem = produtor = parceiro = None
                    obs.insert(0, SEM_VINCULO)
                    r.sem_vinculo.append(f"{g.cliente} ({g.apolice})")
                if produtor and not produtor_valido(produtor) and not parceiro and produtor not in ("KETTE", "ISADORA"):
                    parceiro = produtor  # quem não é produtora vira parceiro (regra do script)
                produtor = produtor_valido(produtor)
                if n - 1 in em_par:
                    parceiro = PARCEIRO_COCORRETAGEM
            if g.ramo == "?":
                ra = decisoes.regra(db, entidade_id, "ramo", chave_ramo(e.seguradora, g.apolice, g.cliente))
                if ra:
                    g.ramo = ra.acao["ramo"]
            if g.ramo == "?" and g.ramo_padrao:
                g.ramo = g.ramo_padrao
            if g.ramo == "?":
                obs.insert(0, "VERIFICAR RAMO")
            if g.bruta < 0 and not g.debito and not g.obs and n - 1 not in em_par:
                obs.append("NEGATIVO: verificar o motivo (estorno/ajuste)")
            ptxt = parcela_texto(e, g)
            pnum = next((int(x) for x in re.findall(r"\d+", ptxt)), None) if ptxt else None
            imp = Decimal("0") if g.debito or g.sem_imposto else _imposto(g.bruta)
            nova = Comissao(
                    entidade_id=entidade_id,
                    extrato_id=ext.id,
                    data=g.data or e.data,
                    apolice=g.apolice or None,
                    seguradora=e.seguradora,
                    ramo=g.ramo,
                    cliente=g.cliente,
                    bruta=g.bruta,
                    imposto=imp,
                    liquida=g.bruta - imp,
                    origem=origem,
                    produtor=produtor,
                    parceiro=parceiro,
                    observacao=" | ".join(obs)[:255] or None,
                    parcela=pnum,
                    parcela_texto=ptxt or None,
                    hash=chave_comissao(e.codigo, g.apolice, g.cliente, g.bruta, n),
                )
            db.add(nova)
            novas.append((e, ext, nova))
            r.gravadas += 1
        if e.divergencias:
            pendentes_div.append((e, ext))
    db.flush()
    _perguntas_da_importacao(db, entidade_id, novas, pendentes_div)
    db.commit()
    return saida


def chave_vinculo(seguradora: str, cliente: str, ramo: str | None) -> str:
    return f"{norm_seguradora(seguradora)}|{_nome_chave(cliente)}|{cat_ramo(ramo)}"


def chave_ramo(seguradora: str, apolice: str | None, cliente: str) -> str:
    dig = re.sub(r"\D", "", apolice or "")
    return f"{norm_seguradora(seguradora)}|" + (f"A{dig}" if len(dig) >= 5 else f"N{_nome_chave(cliente)}")


def _perguntas_da_importacao(db: Session, entidade_id: int, novas: list, divergentes: list) -> None:
    """O que a importação não resolveu vira pergunta na Central de decisões (ou é resolvido por regra aprendida)."""
    combos = None
    vinc: dict[str, list] = defaultdict(list)
    ramo: dict[str, list] = defaultdict(list)
    neg: dict[str, list] = defaultdict(list)
    for e, ext, c in novas:
        obs = c.observacao or ""
        if obs.startswith(SEM_VINCULO) or f"| {SEM_VINCULO}" in obs:
            vinc[chave_vinculo(c.seguradora, c.cliente or "", c.ramo)].append(c)
        if "VERIFICAR RAMO" in obs:
            ramo[chave_ramo(c.seguradora, c.apolice, c.cliente or "")].append(c)
        if "NEGATIVO:" in obs:
            r = decisoes.regra(db, entidade_id, "negativo", c.seguradora)
            if r:
                decisoes.aplicar_negativo(c, r.acao["tratamento"])
            else:
                neg[ext.codigo].append(c)
    for k, cs in vinc.items():
        combos = combos if combos is not None else decisoes.combos_vinculo(db, entidade_id)
        decisoes.perguntar_vinculo(db, entidade_id, k, cs[0].cliente or "", cs[0].seguradora, [c.id for c in cs], combos)
    for k, cs in ramo.items():
        decisoes.perguntar(db, entidade_id, "ramo", k, f"Qual o ramo de {cs[0].cliente} ({cs[0].seguradora})?",
                           f"Apólice {cs[0].apolice or '—'}. O extrato não informa um ramo conhecido.",
                           {"ids": [c.id for c in cs], "cliente": cs[0].cliente, "seguradora": cs[0].seguradora},
                           [{"id": x, "rotulo": x.title(), **({"campos": ["ramo"]} if x == "OUTRO" else {})} for x in decisoes.RAMOS])
    for cod, cs in neg.items():
        opcoes = [{"id": k, "rotulo": v} for k, v in decisoes.TRATAMENTO_NEGATIVO.items()]
        decisoes.perguntar(db, entidade_id, "negativo", cod, f"{len(cs)} comissão(ões) negativa(s) no extrato {cod}",
                           "; ".join(f"{c.cliente}: R$ {c.bruta}" for c in cs[:5]),
                           {"ids": [c.id for c in cs], "seguradora": cs[0].seguradora}, opcoes, "ESTORNO")
    for e, ext in divergentes:
        if decisoes.regra(db, entidade_id, "aceitar_divergencia", e.seguradora):
            continue
        decisoes.perguntar(db, entidade_id, "divergencia", ext.codigo, f"Extrato {ext.codigo} com diferença",
                           "; ".join(e.divergencias), {"extrato_id": ext.id, "seguradora": e.seguradora},
                           [{"id": "aceitar", "rotulo": "Está certo assim (aceitar)"},
                            {"id": "excluir", "rotulo": "Excluir o extrato para reimportar"}], "aceitar")
