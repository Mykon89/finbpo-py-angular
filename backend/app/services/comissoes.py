"""Grava extratos de seguradoras como ExtratoComissao + linhas de Comissao, com vínculo pelo histórico."""

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Comissao, ExtratoComissao
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
            self.por_seg.setdefault(seg, []).append(
                _Hist(data, id_, re.sub(r"\D", "", apol or ""), _nome_chave(cli), cli or "", cat_ramo(ramo), ramo, tuple(v))
            )

    def buscar(self, seguradora: str, apolice: str, cliente: str, ramo: str) -> tuple[_Hist | None, str | None]:
        pool = self.por_seg.get(seguradora, [])
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
    saida = []
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
                if h:
                    origem, produtor, parceiro = (x.upper() if x else None for x in h.v)
                    antigo = h.cliente.upper()
                    if (
                        antigo != g.cliente
                        and not re.match(r"^[A-Z]{1,3}\d{2,4}\s*/", antigo)  # nome no formato de consórcio
                        and nomes_batem(_nome_chave(g.cliente), h.nome)
                    ):
                        g.cliente = antigo  # nome já cadastrado na BASE prevalece
                    if g.ramo == "?" and h.ramo:
                        g.ramo = h.ramo
                    if motivo:
                        obs.insert(0, motivo)
                else:
                    origem = produtor = parceiro = None
                    obs.insert(0, SEM_VINCULO)
                    r.sem_vinculo.append(f"{g.cliente} ({g.apolice})")
                if produtor and not produtor_valido(produtor) and not parceiro and produtor not in ("KETTE", "ISADORA"):
                    parceiro = produtor  # quem não é produtora vira parceiro (regra do script)
                produtor = produtor_valido(produtor)
                if n - 1 in em_par:
                    parceiro = PARCEIRO_COCORRETAGEM
            if g.ramo == "?" and g.ramo_padrao:
                g.ramo = g.ramo_padrao
            if g.ramo == "?":
                obs.insert(0, "VERIFICAR RAMO")
            if g.bruta < 0 and not g.debito and not g.obs and n - 1 not in em_par:
                obs.append("NEGATIVO: verificar o motivo (estorno/ajuste)")
            ptxt = parcela_texto(e, g)
            pnum = next((int(x) for x in re.findall(r"\d+", ptxt)), None) if ptxt else None
            imp = Decimal("0") if g.debito or g.sem_imposto else _imposto(g.bruta)
            db.add(
                Comissao(
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
            )
            r.gravadas += 1
    db.commit()
    return saida
