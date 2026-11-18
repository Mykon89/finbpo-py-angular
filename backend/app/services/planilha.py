"""Migração da planilha EXTRATOS_SEGURADORAS (Google Sheets → .xlsx) para o FinBPO.

Abas lidas: PAGAR → contas a pagar; RECORRÊNCIAS → recorrências; REGRAS_BANCO → regras de
categorização; RECEBER → extratos de comissão; BASE → linhas de comissão. Reimportar não duplica.
"""

import hashlib
import io
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AjusteDiaUtil,
    Baixa,
    Categoria,
    CentroCusto,
    Comissao,
    Contraparte,
    ExtratoComissao,
    Frequencia,
    GrupoDRE as G,
    Natureza,
    Recorrencia,
    RegraCategorizacao,
    StatusTitulo,
    TipoTitulo,
    Titulo,
)
from app.services.cnpj import so_digitos

# Palavras-chave → grupo da DRE, para categorias novas vindas da planilha (ajustável na tela Plano de contas)
_GRUPOS = [
    (("antecipacao de lucros", "despesas pessoais dos socios", "emprestimo", "transferencia", "aporte"), G.NAO_OPERACIONAL),
    (("simples nacional", "iss"), G.DEDUCOES),
    (("comiss", "repasse", "cashback", "indeniza", "reembolsos a segurados", "sinistro"), G.CUSTOS),
    (
        ("salario", "pro-labore", "fgts", "inss", "irrf", "ferias", "rescis", "gratifica", "plano de saude",
         "exames medicos", "ajuda de custo", "sindical", "cursos", "recrutamento"),
        G.DESPESAS_PESSOAL,
    ),
    (("marketing", "publicidade", "brindes", "doac"), G.DESPESAS_COMERCIAIS),
    (("juros", "tarifa"), G.DESPESAS_FINANCEIRAS),
]


def sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def grupo_por_nome(nome: str, receita: bool = False) -> G:
    n = sem_acento(nome).lower()
    palavras = set(n.replace("/", " ").replace("-", " ").split())
    for chaves, grupo in _GRUPOS:
        if any((k in palavras) if len(k) <= 3 else (k in n) for k in chaves):
            return grupo
    return G.RECEITA_BRUTA if receita else G.DESPESAS_ADMINISTRATIVAS


def _txt(v) -> str | None:
    if v is None:
        return None
    s = " ".join(str(v).split())
    return s or None


def _dec(v) -> Decimal | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return Decimal(str(round(v, 2)))
    s = str(v).replace("R$", "").strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _data(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = _txt(v)
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            pass
    return None


def _int(v) -> int | None:
    try:
        return int(float(v)) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _sim(v) -> bool:
    return v is True or str(v).strip().upper() in ("TRUE", "SIM", "S", "1", "VERDADEIRO")


def normalizar_ramo(v) -> str | None:
    s = _txt(v)
    return sem_acento(s).upper() if s else None


def _linhas(ws, cabecalho_obrigatorio: str) -> list[dict]:
    """Lê a aba como dicionários, achando o cabeçalho nas 5 primeiras linhas (a 1ª costuma ser o ☰ MENU)."""
    linhas = ws.iter_rows(values_only=True)
    cab = None
    for _ in range(5):
        r = next(linhas, None)
        if r is None:
            return []
        nomes = [_txt(c) or "" for c in r]
        if any(n.upper().startswith(cabecalho_obrigatorio) for n in nomes):
            cab = [n.upper() for n in nomes]
            break
    if not cab:
        return []
    saida = []
    for r in linhas:
        if not any(c not in (None, "") for c in r):
            continue
        saida.append({cab[i]: r[i] for i in range(min(len(cab), len(r))) if cab[i]})
    return saida


def _col(linha: dict, *nomes: str):
    for n in nomes:
        for k, v in linha.items():
            if k == n or k.startswith(n):
                return v
    return None


@dataclass
class Resultado:
    contas_pagar: int = 0
    contas_pagas: int = 0
    recorrencias: int = 0
    regras: int = 0
    extratos: int = 0
    comissoes: int = 0
    categorias_criadas: list[str] = field(default_factory=list)
    fornecedores_criados: int = 0
    ignoradas: int = 0
    abas: list[str] = field(default_factory=list)


class _Cadastros:
    def __init__(self, db: Session, entidade_id: int, res: Resultado):
        self.db, self.eid, self.res = db, entidade_id, res
        self.cats = {c.nome.lower(): c for c in db.scalars(select(Categoria).where(Categoria.entidade_id == entidade_id))}
        self.ccs = {c.nome.lower(): c for c in db.scalars(select(CentroCusto).where(CentroCusto.entidade_id == entidade_id))}
        self.cps = {c.nome.upper(): c for c in db.scalars(select(Contraparte).where(Contraparte.entidade_id == entidade_id))}

    def categoria(self, nome, receita: bool = False) -> Categoria | None:
        nome = _txt(nome)
        if not nome:
            return None
        c = self.cats.get(nome.lower())
        if not c:
            c = Categoria(entidade_id=self.eid, nome=nome, grupo_dre=grupo_por_nome(nome, receita))
            self.db.add(c)
            self.db.flush()
            self.cats[nome.lower()] = c
            self.res.categorias_criadas.append(nome)
        return c

    def centro(self, nome) -> CentroCusto | None:
        nome = _txt(nome)
        if not nome:
            return None
        c = self.ccs.get(nome.lower())
        if not c:
            c = CentroCusto(entidade_id=self.eid, nome=nome)
            self.db.add(c)
            self.db.flush()
            self.ccs[nome.lower()] = c
        return c

    def contraparte(self, nome, documento: str | None = None) -> Contraparte | None:
        nome = _txt(nome)
        if not nome:
            return None
        c = self.cps.get(nome.upper())
        if not c and documento:
            c = self.db.scalar(
                select(Contraparte).where(Contraparte.entidade_id == self.eid, Contraparte.documento == documento)
            )
        if not c:
            c = Contraparte(entidade_id=self.eid, nome=nome, documento=documento)
            self.db.add(c)
            self.db.flush()
            self.res.fornecedores_criados += 1
        elif documento and not c.documento:
            c.documento = documento
        self.cps[nome.upper()] = c
        return c


def _pagar(db: Session, cad: _Cadastros, linhas: list[dict]) -> None:
    ja = set(
        db.scalars(select(Titulo.codigo_externo).where(Titulo.entidade_id == cad.eid, Titulo.codigo_externo.is_not(None)))
    )
    for ln in linhas:
        codigo = _txt(_col(ln, "ID"))
        venc = _data(_col(ln, "VENCIMENTO"))
        previsto = _dec(_col(ln, "PREVISTO"))
        pago = _dec(_col(ln, "PAGO"))
        if not codigo or not venc or not (previsto or pago):
            cad.res.ignoradas += 1
            continue
        if codigo in ja:
            continue
        valor = previsto or pago
        situacao = (_txt(_col(ln, "SITUAÇÃO", "SITUACAO")) or "").upper()
        nat = (sem_acento(_txt(_col(ln, "NATUREZA")) or "")).upper()
        t = Titulo(
            entidade_id=cad.eid,
            tipo=TipoTitulo.PAGAR,
            descricao=_txt(_col(ln, "DESCRIÇÃO", "DESCRICAO")) or _txt(_col(ln, "FORNECEDOR")) or codigo,
            contraparte_id=getattr(cad.contraparte(_col(ln, "FORNECEDOR")), "id", None),
            categoria_id=getattr(cad.categoria(_col(ln, "CATEGORIA")), "id", None),
            centro_custo_id=getattr(cad.centro(_col(ln, "CENTRO DE CUSTO")), "id", None),
            competencia=venc.replace(day=1),
            vencimento=venc,
            valor=valor,
            codigo_externo=codigo,
            natureza=Natureza.FIXA if nat == "FIXA" else Natureza.VARIAVEL if nat else None,
            observacao=f"Planilha ({_txt(_col(ln, 'ORIGEM')) or 'PAGAR'})",
        )
        if situacao.startswith("PAGO") and pago:
            if pago > valor:  # pago com juros/multa
                t.observacao += f" · previsto {valor}"
                t.valor = valor = pago
            if pago < valor and "DESCONTO" in situacao:
                t.desconto = valor - pago
            t.baixas.append(Baixa(data=_data(_col(ln, "DATA PAGTO")) or venc, valor=pago))
            t.status = StatusTitulo.PAGO if t.saldo <= 0 else StatusTitulo.PARCIAL
            cad.res.contas_pagas += 1
        db.add(t)
        ja.add(codigo)
        cad.res.contas_pagar += 1


_FREQ = {
    "MENSAL": Frequencia.MENSAL,
    "SEMANAL": Frequencia.SEMANAL,
    "QUINZENAL": Frequencia.QUINZENAL,
    "ANUAL": Frequencia.ANUAL,
    "UNICA": Frequencia.UNICA,
    "PARCELADA": Frequencia.PARCELADA,
}


def _recorrencias(db: Session, cad: _Cadastros, linhas: list[dict]) -> None:
    existentes = {
        (r.contraparte_id, r.descricao.upper())
        for r in db.scalars(select(Recorrencia).where(Recorrencia.entidade_id == cad.eid))
    }
    for ln in linhas:
        desc = _txt(_col(ln, "DESCRIÇÃO", "DESCRICAO"))
        valor = _dec(_col(ln, "VALOR"))
        inicio = _data(_col(ln, "INÍCIO", "INICIO")) or _data(_col(ln, "DIA / DATA"))
        freq_txt = sem_acento(_txt(_col(ln, "FREQUÊNCIA", "FREQUENCIA")) or "").upper()
        if not (_txt(_col(ln, "ID")) and desc and valor and inicio):
            continue
        freq = next((f for k, f in _FREQ.items() if freq_txt.startswith(k)), Frequencia.MENSAL)
        tipo = TipoTitulo.RECEBER if "RECEB" in (_txt(_col(ln, "TIPO")) or "").upper() else TipoTitulo.PAGAR
        cp = cad.contraparte(_col(ln, "FORNECEDOR"))
        if (getattr(cp, "id", None), desc.upper()) in existentes:
            continue
        dia_txt = _txt(_col(ln, "DIA / DATA", "DIA")) or ""
        dia_util = _int("".join(ch for ch in dia_txt if ch.isdigit())) if "UTIL" in sem_acento(dia_txt).upper() else None
        nat = sem_acento(_txt(_col(ln, "NATUREZA")) or "").upper()
        freq_bruta = (_txt(_col(ln, "FREQUÊNCIA", "FREQUENCIA")) or "").upper()
        db.add(
            Recorrencia(
                entidade_id=cad.eid,
                codigo=_txt(_col(ln, "ID")),
                ativa=_sim(_col(ln, "ATIVA")),
                tipo=tipo,
                contraparte_id=getattr(cp, "id", None),
                descricao=desc,
                categoria_id=getattr(cad.categoria(_col(ln, "CATEGORIA"), tipo == TipoTitulo.RECEBER), "id", None),
                centro_custo_id=getattr(cad.centro(_col(ln, "CENTRO DE CUSTO")), "id", None),
                valor=valor,
                frequencia=freq,
                dia=None if dia_util else _int(_col(ln, "DIA / DATA", "DIA")),
                dia_util=dia_util,
                ajuste=AjusteDiaUtil.ANTECIPAR
                if "ANTECIPAR" in freq_bruta
                else AjusteDiaUtil.POSTERGAR
                if "POSTERGAR" in freq_bruta
                else AjusteDiaUtil.NENHUM,
                inicio=inicio,
                fim=_data(_col(ln, "FIM")),
                parcelas=_int(_col(ln, "PARCELAS")),
                reajuste_pct=_dec(_col(ln, "REAJUSTE")),
                mes_reajuste=_int(_col(ln, "MÊS DO REAJUSTE", "MES DO REAJUSTE")),
                natureza=Natureza.FIXA if nat == "FIXA" else Natureza.VARIAVEL if nat else None,
            )
        )
        existentes.add((getattr(cp, "id", None), desc.upper()))
        cad.res.recorrencias += 1


def _regras(db: Session, cad: _Cadastros, linhas: list[dict]) -> None:
    atuais = db.scalars(select(RegraCategorizacao).where(RegraCategorizacao.entidade_id == cad.eid)).all()
    por_padrao = {(r.padrao or "").upper() for r in atuais}
    por_cp = {r.contraparte_id for r in atuais if r.contraparte_id}
    for ln in linhas:
        padrao = _txt(_col(ln, "PADRÃO", "PADRAO"))
        cat = cad.categoria(_col(ln, "CATEGORIA"))
        if not padrao or not cat:
            continue
        doc = so_digitos(padrao)
        if padrao.upper().startswith(("CNPJ", "CPF")) and len(doc) in (11, 14):
            cp = cad.contraparte(_col(ln, "FORNECEDOR") or doc, doc)
            if cp.id in por_cp:
                continue
            db.add(RegraCategorizacao(entidade_id=cad.eid, contraparte_id=cp.id, categoria_id=cat.id, prioridade=50))
            por_cp.add(cp.id)
        else:
            if padrao.upper() in por_padrao:
                continue
            db.add(RegraCategorizacao(entidade_id=cad.eid, padrao=padrao, categoria_id=cat.id))
            por_padrao.add(padrao.upper())
        cad.res.regras += 1


def _extrato(db: Session, cad: _Cadastros, cache: dict, codigo: str, seg: str | None, data: date | None):
    if codigo in cache:
        return cache[codigo]
    e = db.scalar(select(ExtratoComissao).where(ExtratoComissao.entidade_id == cad.eid, ExtratoComissao.codigo == codigo))
    if not e:
        e = ExtratoComissao(
            entidade_id=cad.eid,
            codigo=codigo,
            seguradora=seg or codigo.split("-")[0],
            data=data or date.today(),
            arquivo="planilha",
        )
        db.add(e)
        db.flush()
        cad.res.extratos += 1
    cache[codigo] = e
    return e


def _receber(db: Session, cad: _Cadastros, linhas: list[dict], cache: dict) -> None:
    for ln in linhas:
        codigo = _txt(_col(ln, "EXTRATO"))
        if not codigo:
            continue
        e = _extrato(db, cad, cache, codigo, _txt(_col(ln, "SEG")), _data(_col(ln, "DT EXT")))
        e.documento = _txt(_col(ln, "DOC"))
        e.bruto = _dec(_col(ln, "BRUTO")) or Decimal("0")
        e.iss = _dec(_col(ln, "ISS")) or Decimal("0")
        e.liquido = _dec(_col(ln, "LÍQUIDO", "LIQUIDO")) or Decimal("0")
        e.debitos = _dec(_col(ln, "DÉBITOS", "DEBITOS")) or Decimal("0")
        recebido = _dec(_col(ln, "RECEBIDO NO BANCO"))
        if recebido is not None:
            e.recebido_valor = recebido
            e.recebido_em = _data(_col(ln, "DT BANCO"))


def chave_comissao(*partes) -> str:
    return hashlib.sha256("|".join("" if p is None else str(p) for p in partes).encode()).hexdigest()


def _base(db: Session, cad: _Cadastros, linhas: list[dict], cache: dict) -> None:
    ja = Counter(db.scalars(select(Comissao.hash).where(Comissao.entidade_id == cad.eid)))
    # linhas importadas por versão antiga, sem o texto da parcela ("3/12"): completa na reimportação
    sem_parcela = {c.hash: c for c in db.scalars(
        select(Comissao).where(Comissao.entidade_id == cad.eid, Comissao.parcela_texto.is_(None))
    )}
    vistos: Counter = Counter()
    for ln in linhas:
        data = _data(_col(ln, "DT EXTRATO"))
        seg = _txt(_col(ln, "SEG"))
        bruta = _dec(_col(ln, "C. BRUTA"))
        if not data or not seg or bruta is None:
            cad.res.ignoradas += 1
            continue
        apolice, cliente = _txt(_col(ln, "PROPOSTA")), _txt(_col(ln, "CLIENTE"))
        base = chave_comissao(data, apolice, seg.upper(), cliente, bruta)
        vistos[base] += 1
        h = chave_comissao(base, vistos[base])
        if ja[h]:
            antiga = sem_parcela.get(h)
            ptxt = (_txt(_col(ln, "PARCELA")) or "").removesuffix(".0")
            if antiga is not None and ptxt:
                antiga.parcela_texto = ptxt
            continue
        cod_ext = _txt(_col(ln, "EXTRATO"))
        produtor = _txt(_col(ln, "PRODUTOR"))
        db.add(
            Comissao(
                entidade_id=cad.eid,
                extrato_id=_extrato(db, cad, cache, cod_ext, seg.upper(), data).id if cod_ext else None,
                data=data,
                apolice=apolice,
                seguradora=seg.upper(),
                ramo=normalizar_ramo(_col(ln, "RAMO")),
                cliente=cliente,
                bruta=bruta,
                imposto=_dec(_col(ln, "IMP")) or Decimal("0"),
                liquida=_dec(_col(ln, "C. LÍQUIDA", "C. LIQUIDA")) or bruta,
                origem=_txt(_col(ln, "ORIGEM")),
                produtor=None if not produtor or set(produtor) == {"-"} else produtor,
                parceiro=_txt(_col(ln, "PARCEIRO")),
                observacao=_txt(_col(ln, "OBS")),
                parcela=next((int(x) for x in re.findall(r"\d+", str(_col(ln, "PARCELA") or ""))), None),
                parcela_texto=(_txt(_col(ln, "PARCELA")) or "").removesuffix(".0") or None,
                prevista=_dec(_col(ln, "COM. PREVISTA")),
                hash=h,
            )
        )
        cad.res.comissoes += 1


def importar(db: Session, entidade_id: int, conteudo: bytes) -> Resultado:
    wb = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    res = Resultado()
    cad = _Cadastros(db, entidade_id, res)
    abas = {sem_acento(n).upper().strip(): n for n in wb.sheetnames}
    cache: dict = {}
    passos = [
        ("REGRAS_BANCO", "PADR", _regras),
        ("PAGAR", "ID", _pagar),
        ("RECORRENCIAS", "ID", _recorrencias),
    ]
    for chave, cab, fn in passos:
        if chave in abas:
            fn(db, cad, _linhas(wb[abas[chave]], cab))
            res.abas.append(abas[chave])
    if "RECEBER" in abas:
        _receber(db, cad, _linhas(wb[abas["RECEBER"]], "EXTRATO"), cache)
        res.abas.append(abas["RECEBER"])
    if "BASE" in abas:
        _base(db, cad, _linhas(wb[abas["BASE"]], "DT EXTRATO"), cache)
        res.abas.append(abas["BASE"])
    db.commit()
    return res


def resumo_por(db: Session, entidade_id: int, coluna, inicio: date, fim: date) -> dict[str, dict]:
    """Totais de comissão por ramo/seguradora no período [inicio, fim)."""
    linhas = db.execute(
        select(
            coluna,
            func.count(Comissao.id),
            func.sum(Comissao.bruta),
            func.sum(Comissao.imposto),
            func.sum(Comissao.liquida),
        )
        .where(Comissao.entidade_id == entidade_id, Comissao.data >= inicio, Comissao.data < fim)
        .group_by(coluna)
    ).all()
    return {
        k or "—": {"qtd": q, "bruta": Decimal(str(b or 0)), "imposto": Decimal(str(i or 0)), "liquida": Decimal(str(liq or 0))}
        for k, q, b, i, liq in linhas
    }
