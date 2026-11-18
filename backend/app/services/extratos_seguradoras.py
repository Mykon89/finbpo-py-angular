"""Leitura dos extratos de comissão das seguradoras (mesma lógica do Apps Script da planilha).

Cada leitor devolve um ou mais `Extrato` com `Grupo`s (uma linha da BASE por apólice/parcela).
Reconhecidos: Porto (Gerais, Saúde, Vida — .do/HTML), Bradesco (TXT por fatura), Odontoprev (TXT).
"""

import html
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

Z = Decimal("0")


@dataclass
class Grupo:
    apolice: str
    ramo: str
    cliente: str
    bruta: Decimal = Z
    parcelas: list[int] = field(default_factory=list)
    obs: str | None = None
    debito: bool = False  # débito da seguradora (ex.: empréstimo PORTOSEG): fica fora da conferência
    origem_fixa: str | None = None
    data: date | None = None  # quando a linha tem data própria (MAG, Azos)
    parcela_fixa: str | None = None  # texto pronto (Sura/Allianz: "2/6")

    @property
    def parcela_txt(self) -> str:
        if self.parcela_fixa:
            return self.parcela_fixa
        ps = sorted({p for p in self.parcelas if p > 0})
        if not ps:
            return ""
        return str(ps[0]) if len(ps) == 1 else ", ".join(map(str, ps[:-1])) + " e " + str(ps[-1])


@dataclass
class Extrato:
    codigo: str
    seguradora: str
    data: date
    documento: str
    bruto: Decimal
    iss: Decimal
    liquido: Decimal
    debitos: Decimal = Z
    grupos: list[Grupo] = field(default_factory=list)
    divergencias: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    linhas: int = 0


def decodificar(conteudo: bytes) -> str:
    """UTF-8 quando possível; bytes soltos (arquivo misto, comum na Porto) são lidos como Windows-1252."""
    t = conteudo.decode("utf-8", errors="surrogateescape").lstrip("\ufeff")
    if not any("\udc80" <= ch <= "\udcff" for ch in t):
        return t
    return re.sub(
        r"[\udc80-\udcff]+",
        lambda m: bytes(ord(c) - 0xDC00 for c in m.group(0)).decode("cp1252", errors="replace"),
        t,
    )


def _sem_acento(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def _br(txt) -> Decimal:
    """'R$ 1.234,56' / '-0,14' / '-' → Decimal."""
    t = re.sub(r"R\$|\s", "", str(txt or ""))
    if not re.search(r"\d", t):
        return Z
    neg = t.startswith("-") or t.endswith("-")
    t = t.strip("-").replace(".", "").replace(",", ".")
    v = Decimal(t)
    return -v if neg else v


def _ponto(txt) -> Decimal:
    """'46.04' (ponto decimal) → Decimal."""
    t = str(txt or "").strip()
    return Decimal(t) if re.fullmatch(r"-?\d+(\.\d+)?", t) else Z


def _dmy(t: str) -> date:
    return datetime.strptime(t.strip(), "%d/%m/%Y").date()


def _int(t) -> int | None:
    try:
        return int(str(t).strip())
    except ValueError:
        return None


def _brl(v: Decimal) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ---------------------------------------------------------------- Porto
_RAMO_AUTO = {531, 553, 581, 582}
_RAMO_RE = {112, 114, 116, 118, 141, 167, 171, 393}


def _ramo_porto(codigo: str, saude: bool) -> str:
    n = _int(codigo)
    if n in _RAMO_AUTO:
        return "AUTO"
    if n in _RAMO_RE:
        return "RE"
    if n in (2, 57, 58) or re.fullmatch(r"13\d\d|9[89]\d", str(n)):
        return "VIDA"
    if n == 1901 or saude:
        return "SAUDE"
    return "?"


def _celulas(tr: str) -> list[str]:
    return [
        " ".join(html.unescape(re.sub(r"<[^>]*>", " ", td)).replace("\xa0", " ").split())
        for td in re.findall(r"<td[\s\S]*?</td>", tr, re.I)
    ]


def ler_porto(texto: str) -> list[Extrato]:
    plano = " ".join(html.unescape(re.sub(r"<[^>]*>", " ", texto)).replace("\xa0", " ").split())
    ordem = (re.search(r"Ordem de Pagamento:?\s*(\d+)", plano, re.I) or [None, ""])[1]
    dt = re.search(r"Data de Pagamento:?\s*(\d{2}/\d{2}/\d{4})", plano, re.I)
    empresa = _sem_acento((re.search(r"Empresa:?\s*(.+?)\s+Susep Favorecida", plano, re.I) or [None, ""])[1]).upper()
    saude = "SAUDE" in empresa
    vida = not saude and bool(re.search(r"VIDA|PREVID", empresa))
    num = r"(-?[\d.]*\d,\d{2})"
    tot = re.search(r"Bruta\s+INSS\s+IRRF\s+ISS\s+L\S{1,3}quido\s+D\S{1,3}bito/Cr\S{1,3}dito\s+A pagar" + (r"\s+" + num) * 7, plano, re.I)

    linhas = []
    for tr in re.findall(r"<tr[\s\S]*?</tr>", texto, re.I):
        c = _celulas(tr)
        n = len(c)
        if n == 5 and re.match(r"^(D.BITO|CR.DITO)\s", c[0], re.I) and re.match(r"^\d+\s*-", c[4]):
            linhas.append({"deb": True, "nome": c[0], "com": _br(c[3])})
            continue
        if n < 12 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", c[n - 5]) or not re.match(r"^\d+\s*-", c[n - 1]):
            continue
        linhas.append({"nome": c[0], "ramo": c[n - 10], "apol": c[n - 9], "parc": c[n - 7], "com": _br(c[n - 2]), "tipo": c[n - 1]})
    if not linhas:
        raise ValueError("Nenhuma linha reconhecida no extrato da Porto")

    grupos: dict[str, Grupo] = {}
    tipos: dict[str, list[str]] = {}
    soma, qtd, debitos = Z, 0, Z
    for x in linhas:
        if x["com"] == 0:
            continue
        if x.get("deb"):
            k = "DEB|" + x["nome"]
            g = grupos.setdefault(k, Grupo("", "DEBITO", x["nome"].upper(), debito=True, origem_fixa="KETTE"))
            g.bruta += x["com"]
            debitos += x["com"]
            continue
        nome = re.sub(r"\s+-\s+\(\d+\).*$", "", x["nome"])
        nome = " ".join(re.sub(r"^\d{6,}\s+", "", nome).split()).upper()  # Saúde: código do beneficiário na frente
        apol, pn = x["apol"].strip(), _int(x["parc"])
        qtd += 1
        soma += x["com"]
        k = apol + ("|NEG" if x["com"] < 0 else f"|{pn if pn is not None else ''}")
        g = grupos.setdefault(k, Grupo(apol, _ramo_porto(x["ramo"], saude), nome))
        g.bruta += x["com"]
        tp = re.sub(r"^(\d+)\s*-\s*", r"\1-", " ".join(x["tipo"].split()))
        if tp and not re.match(r"^(45|69)-", tp) and tp not in tipos.setdefault(k, []):
            tipos[k].append(tp)
        if pn is not None and pn not in g.parcelas:
            g.parcelas.append(pn)
    for k, ts in tipos.items():
        if ts:
            grupos[k].obs = " / ".join(ts)
    v = [_br(tot.group(i)) for i in range(1, 8)] if tot else None
    bruto = v[0] if v else soma
    e = Extrato(
        codigo=f"PORTO-{ordem}",
        seguradora="PORTO",
        data=_dmy(dt.group(1)) if dt else date.today(),
        documento=f"ORDEM {ordem} " + ("VIDA" if vida else "SAUDE" if saude else "AUTO/RE"),
        bruto=bruto,
        iss=(v[1] + v[2] + v[3]) if v else Z,
        liquido=v[4] if v else bruto,
        debitos=v[5] if v else Z,
        grupos=list(grupos.values()),
        linhas=qtd,
    )
    if soma != bruto:
        e.divergencias.append(f"Soma das linhas {_brl(soma)} x total do extrato {_brl(bruto)}")
    if debitos:
        e.avisos.append(f"Débitos PORTOSEG lançados: {_brl(debitos)}. A pagar: {_brl(v[6]) if v else '—'}.")
    return [e]


# ---------------------------------------------------------------- Bradesco
def ler_bradesco(texto: str) -> list[Extrato]:
    por_fatura: dict[str, list[list[str]]] = {}
    for linha in texto.splitlines()[1:]:
        f = linha.split(";")
        if len(f) >= 75 and re.fullmatch(r"\d{2}/\d{2}/\d{4}", f[0]):
            por_fatura.setdefault(f[1], []).append(f)
    if not por_fatura:
        raise ValueError("Nenhuma linha reconhecida no TXT do Bradesco")
    saida = []
    for fat, rows in por_fatura.items():
        c = rows[0]
        vert = _sem_acento(c[15]).upper().strip()
        saude = vert == "SAUDE"
        ramo = "SAUDE" if saude else vert if vert in ("AUTO", "RE") else "?"
        vert2 = _sem_acento(c[30] or "").upper().strip()
        bruto = _br(c[29]) + _br(c[44])
        iss, irrf, liquido = _br(c[52]), _br(c[48]), _br(c[53])
        grupos: dict[str, Grupo] = {}
        soma, qtd = Z, 0
        for f in rows:
            valor = _br(f[74])
            if valor == 0:
                continue
            apol = f[67].strip().lstrip("0")
            nome = re.sub(r" ?COM\.PG$", "", " ".join(f[70].split()))
            if saude:
                nome = re.sub(r" ?\d{2}$", "", nome)  # sufixo 00/01 do dependente
            ramo_l = "RE" if vert2 == "RE" and not saude and f[69].strip() not in ("00120", "00460", "00519") else ramo
            qtd += 1
            soma += valor
            k = f"{apol}|{nome.upper() if saude else ''}|{ramo_l}" + (f"|NEG{qtd}" if valor < 0 else "")
            g = grupos.setdefault(k, Grupo(apol, ramo_l, nome.upper()))
            g.bruta += valor
            pn = _int(f[71])
            if pn is not None and pn not in g.parcelas:
                g.parcelas.append(pn)
        e = Extrato(
            codigo=f"BRADESCO-{fat}",
            seguradora="BRADESCO",
            data=_dmy(c[0]),
            documento=f"FATURA {fat}",
            bruto=bruto,
            iss=iss + irrf,
            liquido=liquido,
            grupos=list(grupos.values()),
            linhas=qtd,
        )
        if soma != _br(c[16]) + _br(c[31]) - _br(c[18]) and soma != bruto:
            e.divergencias.append(f"Fatura {fat}: soma das linhas {_brl(soma)} x total do extrato {_brl(bruto)}")
        saida.append(e)
    return saida


# ---------------------------------------------------------------- Odontoprev
def ler_odontoprev(texto: str) -> list[Extrato]:
    grupos: dict[str, Grupo] = {}
    nomes: dict[str, Counter] = {}
    soma, qtd, tot, iss, ir, liq, dt_raw = Z, 0, None, Z, Z, Z, ""
    for linha in texto.splitlines()[1:]:
        f = linha.split(";")
        if len(f) < 31 or not re.fullmatch(r"\d{8}", f[5].strip()):
            continue
        valor, apol = _ponto(f[14]), f[7].strip()
        nome = " ".join(f[17].split()).upper()
        tot, iss, ir, dt_raw = _ponto(f[30]), _ponto(f[23]), _ponto(f[24]), f[5].strip()
        liq += _ponto(f[25])
        if valor == 0:
            continue
        qtd += 1
        soma += valor
        k = apol + (f"|NEG|{nome}" if valor < 0 else "")
        g = grupos.setdefault(k, Grupo(apol, "ODONTO", "", origem_fixa="KETTE"))
        g.bruta += valor
        nomes.setdefault(k, Counter())[nome] += 1
        pn = _int(f[10])
        if pn is not None and pn not in g.parcelas:
            g.parcelas.append(pn)
    if not qtd:
        raise ValueError("Nenhuma linha de comissão reconhecida no TXT da Odontoprev")
    avisos, divergencias = [], []
    if tot is not None and soma != tot and soma == liq + iss + ir:
        avisos.append(f"Total do arquivo ({_brl(tot)}) é acumulado; importado só o pago nesta data: {_brl(soma)}.")
        tot = soma
    if tot is not None and soma != tot:
        divergencias.append(f"Soma das linhas {_brl(soma)} x total do extrato {_brl(tot)}")
    for k, g in grupos.items():
        principal = nomes[k].most_common(1)[0][0]
        neg = g.bruta < 0
        g.cliente = f"RESTITUICAO DE COMISSAO APL. CANC. - CONTRATO {g.apolice}" if neg and "RESTITUI" in principal else principal
    d = datetime.strptime(dt_raw, "%Y%m%d").date()
    bruto = tot if tot is not None else soma
    return [
        Extrato(
            codigo=f"ODONTOPREV-{d:%d%m%Y}",
            seguradora="ODONTOPREV",
            data=d,
            documento="",
            bruto=bruto,
            iss=iss + ir,
            liquido=bruto - iss - ir,
            grupos=list(grupos.values()),
            divergencias=divergencias,
            avisos=avisos,
            linhas=qtd,
        )
    ]


def _parcela_odonto(g: Grupo) -> str:
    ps = sorted(set(g.parcelas))
    return "" if not ps else str(ps[0]) if ps[0] == ps[-1] else f"{ps[0]} a {ps[-1]}"


# ---------------------------------------------------------------- Sura (PDF)
_RAMO_SURA = [("RD", "RE"), ("RESID", "RE"), ("EMPRES", "RE"), ("CONDOM", "RE"), ("AUTO", "AUTO"), ("VIDA", "VIDA"), ("ACID", "VIDA")]
_RAMO_ALLIANZ = [("RESID", "RE"), ("EMPRES", "RE"), ("CONDOM", "RE"), ("AUTO", "AUTO"), ("MOTO", "AUTO"), ("CAMINH", "AUTO"),
                 ("VIDA", "VIDA"), ("ACID", "VIDA")]


def _ramo_por_texto(txt: str, tabela) -> str:
    t = _sem_acento(txt).upper()
    return next((r for chave, r in tabela if chave in t), "?")


def _proximo_dia_util(d: date, n: int = 1) -> date:
    from datetime import timedelta

    while n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def ler_sura(texto: str, arquivo: str = "") -> list[Extrato]:
    t = re.sub(r"[ \t]+", " ", texto.replace("\r", ""))
    rs = r"(-?R\$\s*-?[\d.]*\d,\d{2})"
    cab = re.search(r"(\d{1,5})\s*/\s*(\d{4})\s+R\$\s*([\d.]*\d,\d{2})\s+(\d{2}/\d{2}/\d{4})", t)
    numero, ano = (cab.group(1), cab.group(2)) if cab else ("", "")
    pagto = _br(cab.group(3)) if cab else None
    dt_pag = cab.group(4) if cab else ""
    if not numero:
        m = re.search(r"EXTRATO[_ -]?(\d+)", arquivo, re.I)
        numero = m.group(1) if m else ""
    if not dt_pag:
        m = re.search(r"(\d{2})[-_.](\d{2})[-_.](\d{4})", arquivo)
        dt_pag = "/".join(m.groups()) if m else ""
    if not numero or not dt_pag:
        raise ValueError("Sura: faltou o número do extrato ou a data do pagamento")
    ano = ano or dt_pag[-4:]

    def campo(rot):
        m = re.search(rot + r"\s*" + rs, t, re.I)
        return _br(m.group(1)) if m else None

    tot_com = campo(r"Total das comiss\S{1,3}es")
    bruto_res = campo(r"Valor bruto das comiss\S{1,3}es")
    iss = abs(campo(r"ISS\s*\(-\)") or Z)
    liquido = campo(r"Valor l\S{1,3}quido das comiss\S{1,3}es")
    re_l = re.compile(
        r"^(\d{2}/\d{2}/\d{4}) (.+?) (\d{2,4}) ?- ?([A-ZÀ-Ú][A-ZÀ-Ú ]*?) (\d{5,}) (\d+) (\d+(?:/\d+)?) "
        r"(-?R\$ ?-?[\d.]*\d,\d{2}) (-?[\d.,]+) ?% (-?R\$ ?-?[\d.]*\d,\d{2})$"
    )
    grupos: dict[str, Grupo] = {}
    soma, qtd = Z, 0
    for linha in t.split("\n"):
        m = re_l.match(" ".join(linha.split()))
        if not m:
            continue
        ramo = _ramo_por_texto(m.group(4), _RAMO_SURA)
        valor = _br(m.group(10))
        soma += valor
        qtd += 1
        k = f"{m.group(5)}|{m.group(7)}|{ramo}" + (f"|NEG{qtd}" if valor < 0 else "")
        g = grupos.setdefault(k, Grupo(m.group(5), ramo, m.group(2).upper(), parcela_fixa=m.group(7)))
        g.bruta += valor
    e = Extrato(
        codigo=f"SURA-{numero}-{ano}",
        seguradora="SURA",
        data=_proximo_dia_util(_dmy(dt_pag)),  # crédito cai 1 dia útil após o pagamento
        documento=f"PAGTO {_brl(pagto)}" if pagto is not None else "",
        bruto=bruto_res if bruto_res is not None else soma,
        iss=iss,
        liquido=Z,
        grupos=list(grupos.values()),
        linhas=qtd,
    )
    e.liquido = liquido if liquido is not None else e.bruto - iss
    if not qtd and re.search(r"sem lan\S{1,2}amentos", t, re.I):
        e.avisos.append("Sura: extrato sem comissões novas.")
    elif tot_com is not None and soma != tot_com:
        e.divergencias.append(f"Soma das linhas {_brl(soma)} x Total das comissões {_brl(tot_com)}")
    return [e]


# ---------------------------------------------------------------- AKAD (PDF)
def ler_akad(texto: str, arquivo: str = "") -> list[Extrato]:
    linhas = [" ".join(l.split()) for l in texto.replace("\r", "").split("\n") if l.strip()]
    m = re.search(r"Data do Pagamento\s*(\d{2}/\d{2}/\d{4})", texto, re.I) or re.search(r"(\d{2})[-_.](\d{2})[-_.](\d{4})", arquivo)
    if not m:
        raise ValueError("AKAD: não achei a data do pagamento")
    dt = _dmy(m.group(1) if m.lastindex == 1 else "/".join(m.groups()))
    num = (re.search(r"\bN:\s*([A-Z]?\d[\d.]*)", texto, re.I) or [None, ""])[1]
    re_l = re.compile(
        r"^(\d{5}) (\d{4}) (\d{2}) (\d{4}) (\d+) (\d+) (\d+) (\d+) (.+?) [A-Z]{2} (\d{2}/\d{2}/\d{4}) (-?[\d.,]+) [A-Z]{3} [\d.,]+ (-?[\d.,]+) [\d.,]+ (-?[\d.,]+)$"
    )
    fim = re.compile(r"^(Total|I\.|PIS|L.quido|Pag\.|Extrato|Tipo|Endosso|Cia|/)", re.I)
    grupos: dict[str, Grupo] = {}
    soma, qtd = Z, 0
    for i, linha in enumerate(linhas):
        mm = re_l.match(linha)
        if not mm:
            continue
        nome = mm.group(9)
        prox = linhas[i + 1] if i + 1 < len(linhas) else ""
        if prox and not prox[0].isdigit() and not fim.match(prox):
            nome += " " + prox
        v, pn = _br(mm.group(13)), int(mm.group(7))
        apol = mm.group(5).lstrip("0") or mm.group(5)
        qtd += 1
        soma += v
        k = f"{apol}|{pn}" + (f"|NEG{qtd}" if v < 0 else "")
        g = grupos.setdefault(k, Grupo(apol, "AUTO" if mm.group(4) == "0531" else "RE", " ".join(nome.split()).upper()))
        g.bruta += v
        if pn not in g.parcelas:
            g.parcelas.append(pn)
        if v < 0:
            g.obs = "ESTORNO"

    def f(rot):
        x = re.search(rot + r"\s*(-?[\d.,]+)", texto, re.I)
        return _br(x.group(1)) if x else Z

    tb = f(r"Total Bruto em R\$:")
    imp = f(r"I\.R\.:") + f(r"I\.S\.S\.:") + f(r"I\.N\.S\.S:") + f(r"PIS/COFINS/CSLL:")
    e = Extrato(f"AKAD-{dt:%d%m%Y}", "AKAD", dt, f"EXTRATO {num}" if num else "EXTRATO AKAD", soma, imp, soma - imp,
                grupos=list(grupos.values()), linhas=qtd)
    if not qtd:
        e.divergencias.append("AKAD: nenhuma linha de comissão reconhecida no PDF")
    elif tb and soma != tb:
        e.divergencias.append(f"Soma das linhas {_brl(soma)} x Total Bruto {_brl(tb)}")
    return [e]


# ---------------------------------------------------------------- Allianz (PDF)
def ler_allianz(texto: str, arquivo: str = "") -> list[Extrato]:
    linhas = [" ".join(l.split()) for l in texto.replace("\r", "").split("\n") if l.strip()]

    def total(rot):
        m = re.search(rot + r":?\s*(-?[\d.]+)", texto, re.I)
        return Decimal(m.group(1)) if m else None

    tot_bruto, iss, liquido = total("Total Bruto"), total("Total ISS"), total(r"Total L\S{1,3}quido")
    re_l = re.compile(
        r"^(\d{2}/\d{2}/\d{4}) (\d+) (\d{10,}) (\d+(?: \d+){1,2}) (\d+/\d+) (?:ATUAL PREV CORRETORA DE SEGUROS (?:EIRELI|LTDA) ?)?"
        r"(.*?) ?(\d{3,4}) ?- ?([A-Za-zÀ-ú ]+?) (-?[\d.]+) (-?[\d.]+) ?% (-?[\d.]+)(?: [SN])?$"
    )

    def so_texto(x):
        return bool(x) and re.fullmatch(r"[A-Za-zÀ-ú.&' -]+", x) and not re.match(r"^(P.gina|Total|Data|Mediador|Ramo)\b", x, re.I)

    det = []
    for i, linha in enumerate(linhas):
        m = re_l.match(linha)
        if not m:
            continue
        nome = m.group(6).strip()
        if not nome:
            ant = linhas[i - 1] if i else ""
            prox = linhas[i + 1] if i + 1 < len(linhas) else ""
            nome = " ".join(((ant if so_texto(ant) else "") + " " + (prox if so_texto(prox) else "")).split())
        det.append((m.group(1), m.group(4).split(" ")[0], m.group(5), nome, f"{m.group(7)} - {m.group(8)}", Decimal(m.group(11))))
    if not det:
        raise ValueError("Nenhuma linha de comissão reconhecida no extrato da Allianz")
    mp = re.search(r"Data Pagto\.[\s\S]{0,200}?(\d{2}/\d{2}/\d{4})", texto, re.I)
    dt = _dmy(mp.group(1) if mp else det[0][0])

    def pad(p):
        m = re.fullmatch(r"(\d+)/(\d+)", p)
        return f"{int(m.group(1)):02d}/{m.group(2)}" if m else p

    grupos: dict[str, Grupo] = {}
    soma = Z
    for n, (_, apol, parc, nome, ramo_txt, valor) in enumerate(det):
        soma += valor
        ramo = _ramo_por_texto(ramo_txt, _RAMO_ALLIANZ)
        k = f"{apol}|{pad(parc)}|{ramo}" + (f"|NEG{n}" if valor < 0 else "")
        g = grupos.setdefault(k, Grupo(apol, ramo, nome.upper(), parcela_fixa=pad(parc)))
        g.bruta += valor
    bruto = tot_bruto if tot_bruto is not None else soma
    e = Extrato(f"ALLIANZ-{dt:%d%m%Y}", "ALLIANZ", dt, "", bruto, iss or Z,
                liquido if liquido is not None else bruto - (iss or Z), grupos=list(grupos.values()), linhas=len(det))
    if tot_bruto is None:
        e.avisos.append("Não encontrei o total do extrato para conferir a soma.")
    elif soma != tot_bruto:
        e.divergencias.append(f"Soma das linhas {_brl(soma)} x total do extrato {_brl(tot_bruto)}")
    return [e]


# ---------------------------------------------------------------- Azos (XLSX → texto com tabs)
def _num_livre(t: str) -> Decimal:
    t = str(t).strip()
    return _br(t) if "," in t else Decimal(t)


def ler_azos(texto: str, arquivo: str = "") -> list[Extrato]:
    grupos: dict[str, Grupo] = {}
    soma, qtd, ultima, tot = Z, 0, None, None
    for linha in texto.replace("\r", "").split("\n"):
        c = [x.strip() for x in linha.split("\t")]
        if re.match(r"^Total Comiss.o Bruta", c[0], re.I):
            nums = [x for x in c if re.fullmatch(r"-?[\d.]*\d[,.]?\d*", x)]
            tot = _num_livre(nums[-1]) if nums else None
            continue
        if len(c) < 11 or not re.fullmatch(r"-?[\d.]*\d([,.]\d{1,2})?", c[10]):
            continue
        md = re.search(r"\d{2}/\d{2}/\d{4}", c[8])
        if not md:
            continue
        d = _dmy(md.group(0))
        valor, apol, pn = _num_livre(c[10]), c[3].replace(" ", ""), _int(c[6])
        ultima = max(ultima or d, d)
        soma += valor
        qtd += 1
        k = f"{apol}|{pn if pn is not None else ''}|{d}" + (f"|NEG{qtd}" if valor < 0 else "")
        g = grupos.setdefault(k, Grupo(apol, "VIDA", " ".join(c[0].split()).upper(), data=d))
        g.bruta += valor
        if pn is not None and pn not in g.parcelas:
            g.parcelas.append(pn)
        if valor < 0:
            g.obs = "ESTORNO"
    if not qtd:
        raise ValueError("Nenhuma linha da Azos reconhecida")
    e = Extrato(f"AZOS-{ultima:%d%m%Y}", "AZOS", ultima, "EXTRATO AZOS", soma, Z, soma,
                grupos=sorted(grupos.values(), key=lambda g: g.data), linhas=qtd)
    e.avisos.append("Azos: arquivo sem ISS.")
    if tot is not None and tot != soma:
        e.divergencias.append(f"Soma das linhas {_brl(soma)} x Total Comissão Bruta {_brl(tot)}")
    return [e]


# ---------------------------------------------------------------- MAG (CSV ;)
def ler_mag(texto: str, arquivo: str = "") -> list[Extrato]:
    linhas = [l for l in texto.replace("\r", "").split("\n") if l.strip()]
    hd = [_sem_acento(x.replace("\t", "").strip()).upper() for x in linhas[0].split(";")]

    def ix(padrao):
        return next((i for i, h in enumerate(hd) if re.match(padrao, h)), -1)

    c_nome, c_prop, c_parc, c_dt = ix(r"^NOME/RAZAO"), ix(r"^PROPOSTA$"), ix(r"^PARCELA COMISSIONADA"), ix(r"^DATA DE EFETIVACAO")
    c_ang, c_com, c_est = ix(r"^VALOR ANGARIACAO"), ix(r"^VALOR COMISSAO"), ix(r"^VALOR ESTORNO")
    c_inc, c_bon, c_tp = ix(r"^VALOR INCENTIVO"), ix(r"^VALOR BONIFICACAO"), ix(r"^TIPO DE PAGAMENTO")
    if min(c_nome, c_prop, c_parc, c_dt, c_com) < 0:
        raise ValueError("MAG: colunas não reconhecidas no CSV")

    def val(c, i):
        if i < 0 or i >= len(c):
            return Z
        s_ = c[i].replace("\t", "").strip()
        return _br(s_) if s_ else Z

    grupos: dict[str, Grupo] = {}
    soma, qtd, datas = Z, 0, []
    for linha in linhas[1:]:
        c = linha.split(";")
        if len(c) < 20:
            continue
        dt_txt = c[c_dt].strip()
        if not re.fullmatch(r"\d{2}/\d{2}/\d{4}", dt_txt):
            continue
        v = val(c, c_com) + val(c, c_ang) + val(c, c_inc) + val(c, c_bon) - abs(val(c, c_est))
        if c_tp >= 0 and "DEBITO" in _sem_acento(c[c_tp]).upper() and v > 0:
            v = -v
        d = _dmy(dt_txt)
        prop, pn = re.sub(r"\D", "", c[c_prop]), _int(c[c_parc])
        qtd += 1
        soma += v
        datas.append(d)
        k = f"{prop}|{d}" + (f"|NEG{qtd}" if v < 0 else "")
        g = grupos.setdefault(k, Grupo(prop, "VIDA", " ".join(c[c_nome].split()).upper(), data=d))
        g.bruta += v
        if pn is not None and pn not in g.parcelas:
            g.parcelas.append(pn)
        if v < 0:
            g.obs = "ESTORNO"
    if not qtd:
        raise ValueError("MAG: nenhuma linha reconhecida")
    fim = max(datas)
    e = Extrato(f"MAG-{fim:%d%m%Y}", "MAG", fim, "EXTRATO MAG", soma, Z, soma,
                grupos=sorted(grupos.values(), key=lambda g: g.data), linhas=qtd)
    e.avisos.append("MAG: o CSV não traz a taxa administrativa VGBL nem o ISS; ajuste o recebido se necessário.")
    return [e]


def texto_de_planilha(conteudo: bytes) -> str:
    import io

    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    saida = []
    for ws in wb.worksheets:
        for r in ws.iter_rows(values_only=True):
            cel = []
            for v in r:
                if v is None:
                    cel.append("")
                elif isinstance(v, float):
                    cel.append(f"{round(v, 2):.2f}")
                elif isinstance(v, datetime):
                    cel.append(f"{v:%d/%m/%Y}")
                else:
                    cel.append(str(v))
            saida.append("\t".join(cel).rstrip("\t"))
    return "\n".join(saida)


def texto_de_pdf(conteudo: bytes) -> str:
    import io

    import pdfplumber

    with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def ler(conteudo: bytes, nome_arquivo: str = "") -> list[Extrato]:
    if conteudo[:4] == b"%PDF":
        texto = texto_de_pdf(conteudo)
    elif conteudo[:2] == b"PK":
        texto = texto_de_planilha(conteudo)
    else:
        texto = decodificar(conteudo)
    inicio = texto.lstrip("\ufeff \t\r\n")[:300]
    if re.match(r"Data Pagamento;Fatura;", inicio, re.I):
        return ler_bradesco(texto)
    if inicio.startswith("NCO_CPF_CGC;") and "NSE_TOT_COMISSAO" in texto:
        return ler_odontoprev(texto)
    if re.match(r"CPF/CNPJ do Produtor;C.digo do produtor;Tipo de cliente;", inicio, re.I):
        return ler_mag(texto, nome_arquivo)
    if re.search(r"^Nome do Segurado\tCPF do Segurado\t", texto, re.M) and re.search(r"Comiss.o Bruta", texto, re.I):
        return ler_azos(texto, nome_arquivo)
    if re.search(r"Extrato de Pagamento de Comiss", texto, re.I) and re.search(r"CB-Comiss.o de Corretagem", texto, re.I):
        return ler_akad(texto, nome_arquivo)
    if re.search(r"Anal\S{1,3}tico (dos |de )?Pagamentos? de Comiss", texto, re.I) and re.search(r"Susep Favorecida", texto, re.I):
        return ler_porto(texto)
    if re.search(r"EXTRATO DE COMISS\S{1,3}ES PAGAS POR SUSEP", texto, re.I) and re.search(r"Allianz", texto, re.I):
        return ler_allianz(texto, nome_arquivo)
    if re.search(r"Extrato de Comiss\S{1,3}o", texto, re.I) and re.search(r"Nome do cliente|sem lan\S{1,2}amentos", texto, re.I) \
            and re.search(r"Saldo anterior", texto, re.I):
        return ler_sura(texto, nome_arquivo)
    raise ValueError(
        f"{nome_arquivo or 'Arquivo'}: formato não reconhecido "
        "(aceitos hoje: Porto, Bradesco, Odontoprev, Sura, AKAD, Allianz, Azos, MAG)"
    )


def parcela_texto(e: Extrato, g: Grupo) -> str:
    return _parcela_odonto(g) if e.seguradora == "ODONTOPREV" else g.parcela_txt
