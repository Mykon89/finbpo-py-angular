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
    ramo_padrao: str | None = None  # se o ramo vier "?" e a BASE não souber (Yelum: AUTO)
    sem_imposto: bool = False  # valor já líquido (Zurich parceria)

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


# ---------------------------------------------------------------- Tokio (XLSX "Extrato Comissão" ou PDF)
TOKIO_ISS = Decimal("0.0411")


def _ramo_tokio(tx: str) -> str:
    t = _sem_acento(tx).upper()
    for padrao, ramo in ((r"ALUGUEL|FIANCA", "FIANCA"), (r"VIAGEM", "VIAGEM"), (r"AUTO", "AUTO"),
                         (r"RESID|EMPRES|CONDOM|PATRIM", "RE"), (r"VIDA|ACID", "VIDA")):
        if re.search(padrao, t):
            return ramo
    return "?"


def _mon_livre(x) -> Decimal:
    t = re.sub(r"R\$|\s", "", str(x or ""))
    neg = t.startswith("-") or t.endswith("-")
    t = t.replace("-", "")
    if not t or not re.search(r"\d", t):
        return Z
    v = Decimal(t.replace(".", "").replace(",", ".")) if "," in t else Decimal(t)
    return -v if neg else v


def ler_tokio(texto: str, arquivo: str = "") -> list[Extrato]:
    linhas = [" ".join(l.split(" ")).strip() for l in texto.replace("\r", "").split("\n") if l.strip()]
    xlsx = any(re.match(r"^Segurado\tNegocio\t", l, re.I) for l in linhas)
    det, ajustes, tot = [], [], {}
    if xlsx:
        for l in linhas:
            f = [v.strip() for v in l.split("\t")] + [""] * 10
            r_ = _sem_acento(f[0]).upper()
            v = f[2] if f[2] else f[1]
            if v and re.search(r"\d", v) and not re.search(r"\d", f[3] or ""):
                if r_.startswith("TOTAL DO PAGAMENTO"):
                    tot["bruto"] = _mon_livre(v)
                elif r_ in ("ISS", "IRRF", "INSS"):
                    tot[r_.lower()] = _mon_livre(v)
                elif r_.startswith("OUTROS AJUSTES"):
                    tot["ajuste"] = _mon_livre(v)
                elif r_.startswith("TOTAL COMISSAO LIQUIDA"):
                    tot["liquido"] = _mon_livre(v)
                continue
            if re.fullmatch(r"Segurado", f[0], re.I) or not re.match(r"^-?\d", f[9]):
                continue
            if re.match(r"^AJUSTE", f[6], re.I):
                ajustes.append((f[0], f[6], _mon_livre(f[9])))
                continue
            det.append((f[0], f[2], f[3], f[4], f[6], _mon_livre(f[9])))
        m = re.search(r"(\d{2})-(\d{2})-(\d{4})", arquivo)
        dt = _dmy("/".join(m.groups())) if m else None
    else:
        plano = " ".join(" ".join(linhas).split())

        def g1(rx):
            m = re.search(rx, plano, re.I)
            return m.group(1) if m else ""

        dt = _dmy(g1(r"Data de Cr.dito:?\s*(\d{2}/\d{2}/\d{4})")) if g1(r"Data de Cr.dito:?\s*(\d{2}/\d{2}/\d{4})") else None
        tot["num"] = g1(r"Extrato n\S{0,2}\s+(\d+)")
        for chave, rx in (("bruto", r"Total da Comiss.o Bruta:?\s*(-?R\$\s*-?[\d.,]+)"), ("iss", r"I\.S\.S:?\s*(-?R\$\s*-?[\d.,]+)"),
                          ("irrf", r"\bI\.R:?\s*(-?R\$\s*-?[\d.,]+)"), ("inss", r"I\.N\.S\.S:?\s*(-?R\$\s*-?[\d.,]+)"),
                          ("ajuste", r"Outros Ajustes sem Impostos:?\s*(-?R\$\s*-?[\d.,]+)"),
                          ("liquido", r"Total Comiss.o L.quida:?\s*(-?R\$\s*-?[\d.,]+)")):
            if g1(rx):
                tot[chave] = _mon_livre(g1(rx))
        re_l = re.compile(r"^(.+?) (\d{3,}) (.*?) (\d{4,}) (\d+) (COMISSAO(?: [A-Z]+)?|ESTORNO[A-Z ]*|CANCELAMENTO[A-Z ]*) (\d+/\d+|-/-) R\$ ?[\d.,]+ -?[\d.,]+ ?% (-?R\$ ?-?[\d.,]+)$")
        re_a = re.compile(r"^(ACERTO .+?) \d+ (AJUSTE IMPOSTOS(?: SIMPLES)?) .*?(-?R\$ ?-?[\d.,]+)$")
        for l in linhas:
            m, a = re_l.match(l), re_a.match(l)
            if m:
                det.append((m.group(1), m.group(3), m.group(4), m.group(7), m.group(6), _mon_livre(m.group(8))))
            elif a:
                ajustes.append((a.group(1), a.group(2), _mon_livre(a.group(3))))
    if not det:
        raise ValueError("Nenhuma linha de comissão reconhecida no extrato da Tokio")
    if not dt:
        raise ValueError("Tokio: não encontrei a data (no XLSX ela vem do nome do arquivo, ex.: TOKIO_EXTRATO_06-10-2026.xlsx)")
    grupos: dict[str, Grupo] = {}
    tipos: dict[str, list[str]] = {}
    soma = Z
    for i, (nome, ramo_txt, apol, parc, tipo, valor) in enumerate(det):
        soma += valor
        pn = _int(str(parc).split("/")[0])
        k = f"{apol}|{pn if pn is not None else ''}" + (f"|NEG{i}" if valor < 0 else "")
        g = grupos.setdefault(k, Grupo(apol, _ramo_tokio(ramo_txt), " ".join(nome.split()).upper()))
        g.bruta += valor
        if pn is not None and pn not in g.parcelas:
            g.parcelas.append(pn)
        tp = tipo.strip().upper()
        if tp and tp != "COMISSAO" and tp not in tipos.setdefault(k, []):
            tipos[k].append(tp)
    for k, ts in tipos.items():
        if ts:
            grupos[k].obs = " / ".join(ts)
    ajuste = sum((a[2] for a in ajustes), Z)
    calc_iss = xlsx and "liquido" not in tot
    bruto = tot["bruto"] if "bruto" in tot and not calc_iss else soma
    if calc_iss:
        iss = (bruto * TOKIO_ISS).quantize(Decimal("0.01"))
        liquido = bruto - iss + ajuste
    else:
        iss = abs(tot.get("iss", Z)) + abs(tot.get("irrf", Z)) + abs(tot.get("inss", Z))
        liquido = tot["liquido"]
    lista = list(grupos.values()) + [
        Grupo("", "AJUSTE", nome.upper(), valor, obs=tipo.upper(), debito=True, origem_fixa="KETTE")
        for nome, tipo, valor in ajustes if valor
    ]
    e = Extrato(f"TOKIO-{dt:%d%m%Y}", "TOKIO", dt, f"EXTRATO {tot['num']}" if tot.get("num") else "", bruto, iss, liquido,
                debitos=ajuste, grupos=lista, linhas=len(det))
    if soma != bruto:
        e.divergencias.append(f"Soma das linhas {_brl(soma)} x total do extrato {_brl(bruto)}")
    if not calc_iss and liquido != bruto - iss + tot.get("ajuste", Z):
        e.divergencias.append(f"Líquido {_brl(liquido)} x bruto - impostos + ajustes {_brl(bruto - iss + tot.get('ajuste', Z))}")
    if calc_iss:
        e.avisos.append("XLSX sem totais: ISS calculado a 4,11%.")
    return [e]


# ---------------------------------------------------------------- HDI (PDF)
HDI_ISS = Decimal("0.03968")


def ler_hdi(texto: str, arquivo: str = "") -> list[Extrato]:
    linhas = [" ".join(l.split()) for l in texto.replace("\r", "").split("\n") if l.strip()]
    mdt = re.search(r"Data do Pagamento:\s*(\d{2}/\d{2}/\d{4})", texto, re.I)
    num = (re.search(r"Extrato:\s*(\d+)", texto, re.I) or [None, ""])[1]
    tb = re.search(r"Total Bruto\s+(-?[\d.,]+)", texto, re.I)
    re_l = re.compile(
        r"^(\d{2}/\d{2}/\d{4}) (\d{2})\.(\d{3})\.(\d{3})\.(\d{6})\.(\d{6})(?: - (\d+)/(\d+))? (.+?)"
        r"(?: (-?[\d.,]+) (-?[\d.,]+) (-?[\d.,]+)| ABATIMENTO -? ?([\d.,]+))$"
    )
    grupos: dict[str, Grupo] = {}
    soma, qtd = Z, 0
    for l in linhas:
        m = re_l.match(l)
        if not m:
            continue
        neg = m.group(13) is not None
        valor = -_br(m.group(13)) if neg else _br(m.group(12))
        nome = " ".join(re.sub(r" - Recup\..*$", "", m.group(9), flags=re.I).split()).upper()
        endo = int(m.group(6))
        apol = m.group(5) + (f"/{endo}" if endo else "")
        pn = int(m.group(7)) if m.group(7) else None
        k = f"{apol}|{pn if pn is not None else ''}" + (f"|NEG{qtd}" if neg else "")
        qtd += 1
        soma += valor
        ramo = "AUTO" if m.group(3) in ("531", "553", "581", "582") else "RE"
        g = grupos.setdefault(k, Grupo(apol, ramo, nome))
        g.bruta += valor
        if pn is not None and pn not in g.parcelas:
            g.parcelas.append(pn)
        if neg:
            rc = re.search(r"Recup\..*$", m.group(9), re.I)
            g.obs = "ABATIMENTO" + (" - " + " ".join(rc.group(0).split()) if rc else "")
    if not qtd or not mdt:
        raise ValueError("Nenhuma linha de comissão (ou data) reconhecida no extrato da HDI")
    bruto = _br(tb.group(1)) if tb else soma
    iss = Z if bruto == 0 else (bruto * HDI_ISS).quantize(Decimal("0.01"))
    dt = _dmy(mdt.group(1))
    e = Extrato(f"HDI-{dt:%d%m%Y}", "HDI", dt, f"EXTRATO {num}" if num else "", bruto, iss, bruto - iss,
                grupos=list(grupos.values()), linhas=qtd)
    e.avisos.append("HDI: PDF sem ISS; calculado a 3,968% do bruto. Ajuste pelo valor recebido no banco.")
    if tb and soma != bruto:
        e.divergencias.append(f"Soma das linhas {_brl(soma)} x total do extrato {_brl(bruto)}")
    return [e]


# ---------------------------------------------------------------- Mapfre (PDF)
_RAMO_MAPFRE = [(r"^31$", "AUTO"), (r"^(77|81|82|91|92|93|94|95|96|97|98)$", "VIDA"),
                (r"^(11|12|13|14|15|16|17|18|19|22|53|54|55|71|72|73|75)$", "RE")]


def ler_mapfre(texto: str, arquivo: str = "") -> list[Extrato]:
    plano = " ".join(texto.replace("\r", "").split())
    num_ = r"(-?R\$ ?-?[\d.]*\d,\d{2})"

    def campo(rot):
        m = re.search(rot + " " + num_, plano, re.I)
        return _br(m.group(1)) if m else None

    num = (re.search(r"N[º°o]? ?Extrato:? ?(\d{5,})", plano, re.I) or [None, ""])[1]
    mdt = re.search(r"Data Cr[eé]dito:? ?(\d{2}/\d{2}/\d{4})", plano, re.I) or re.search(r"DATA DO PAGAMENTO:? ?(\d{2}/\d{2}/\d{4})", plano, re.I)
    tot_bruto, deb, iss = campo(r"Total da Comiss.o Bruta"), campo(r"D.bitos"), campo(r"ISS Retido")
    irrf, inss, liq = campo(r"IRRF Retido"), campo(r"INSS Retido"), campo(r"Total da Comiss.o L.quida")
    re_l = re.compile(r"(\d{1,3}) (\d{1,4}) (\d{4,}) (\d+) (.+?) (\d+) (\d{2}/\d{2}/\d{2,4}) R\$ ?(-?[\d.]*\d,\d{2}) (-?[\d.,]+) ?% R\$ ?(-?[\d.]*\d,\d{2})")
    grupos: dict[str, Grupo] = {}
    soma, qtd = Z, 0
    for m in re_l.finditer(plano):
        valor = _br(m.group(10))
        if valor == 0:  # "SALDO DEMONSTRATIVO ANTERIOR"
            continue
        ramo = next((r for rx, r in _RAMO_MAPFRE if re.match(rx, m.group(1))), "?")
        endo = int(m.group(4))
        apol = m.group(3) + (f"/{endo}" if endo else "")
        pn = int(m.group(6))
        qtd += 1
        soma += valor
        k = f"{apol}|{pn}" + (f"|NEG{qtd}" if valor < 0 else "")
        g = grupos.setdefault(k, Grupo(apol, ramo, " ".join(m.group(5).split()).upper(), parcelas=[pn]))
        g.bruta += valor
        if valor < 0:
            g.obs = "ESTORNO"
    if not qtd or not mdt:
        raise ValueError(f"Mapfre {num}: nenhuma linha de comissão (ou data de crédito) reconhecida")
    bruto = tot_bruto if tot_bruto is not None else soma
    isv, outros, dv = abs(iss or Z), abs(irrf or Z) + abs(inss or Z), abs(deb or Z)
    dt = _dmy(mdt.group(1))
    e = Extrato(f"MAPFRE-{num or f'{dt:%d%m%Y}'}", "MAPFRE", dt, f"EXTRATO {num}" if num else "", bruto, isv + outros,
                liq if liq is not None else bruto - dv - isv - outros, debitos=-dv, grupos=list(grupos.values()), linhas=qtd)
    if tot_bruto is not None and soma != tot_bruto:
        e.divergencias.append(f"Soma das linhas {_brl(soma)} x Total da Comissão Bruta {_brl(tot_bruto)}")
    if liq is not None and bruto - dv - isv - outros != liq:
        e.divergencias.append(f"Bruta - débitos - impostos difere da líquida {_brl(liq)}")
    if dv:
        e.avisos.append(f"Extrato com DÉBITOS de {_brl(dv)}; confira se há estornos não lidos.")
    return [e]


# ---------------------------------------------------------------- Amil (TXT com #)
CODIGOS_AMIL = {"238325", "127086"}


def _limpar_nome_amil(nome: str) -> str:
    m = re.match(r"^([\d][\d ./-]*\d)\s+(.*)$", nome.strip())
    nome = m.group(2) if m and len(re.sub(r"\D", "", m.group(1))) >= 8 else nome.strip()
    return re.sub(r"\s+\d{11}$", "", nome)  # CPF colado no fim


def ler_amil(texto: str, arquivo: str = "") -> list[Extrato]:
    t = texto.replace("\r", "\n")

    def cab(rx):
        m = re.search(rx, t, re.I)
        return m.group(1) if m else ""

    def ponto(rx):
        x = cab(rx)
        return None if x == "" else Decimal(x).quantize(Decimal("0.01"))

    if len(re.findall(r"N.{1,3}mero\s*Extrato:#", t, re.I)) > 1:
        raise ValueError("Este arquivo tem mais de um extrato da Amil. Importe um por vez.")
    numero, codigo = cab(r"N.{1,3}mero\s*Extrato:#(\d+)"), cab(r"Produtor:#(\d{4,})")
    dt_txt = cab(r"Dt\.?\s*Pagto\s*Efetivo:#(\d{2}/\d{2}/\d{4})") or cab(r"Dt\.?\s*Pagto\s*Previsto:#(\d{2}/\d{2}/\d{4})")
    if not dt_txt:
        m = re.search(r"(\d{2})[-_.](\d{2})[-_.](\d{4})", arquivo)
        dt_txt = "/".join(m.groups()) if m else ""
    if not (numero and codigo and dt_txt):
        raise ValueError("Faltou no TXT da Amil: número do extrato, código do produtor ou data de pagamento")
    num_rx = r"(-?(?:\d+\.?\d*|\.\d+))"
    apurado, emissao = ponto(r"Valor Apurado:#" + num_rx), ponto(r"Valor para Emiss.{1,3}o de NF:#" + num_rx)
    iss, liquido = ponto(r"Valor ISS:#" + num_rx) or Z, ponto(r"Valor L.{1,3}quido a Receber:#" + num_rx)
    nf = cab(r"Nota\s*Fiscal:#(\d+)")
    seg = f"AMIL {codigo}"
    grupos: dict[str, Grupo] = {}
    soma, qtd = Z, 0
    for l in t.split("\n"):
        f = l.split("#")
        if len(f) < 17 or not re.fullmatch(r"\d+", f[2]) or not re.fullmatch(r"\d{2}/\d{2}/\d{4}", f[3]):
            continue
        com, parcela, prop = _br(f[16]), _int(f[5]), f[2]
        nome = _limpar_nome_amil(f[17] if len(f) > 17 and f[17] else re.sub(r"^\d+\s+", "", f[1])).upper()
        soma += com
        qtd += 1
        ramo = "ODONTO" if re.search(r"dental|odonto", f[11], re.I) else "SAUDE"
        k = prop + ("|ODO" if ramo == "ODONTO" else "") + (f"|NEG{qtd}" if com < 0 else "")
        g = grupos.setdefault(k, Grupo(prop, ramo, nome))
        g.bruta += com
        if parcela is not None and parcela not in g.parcelas:
            g.parcelas.append(parcela)
    bruto = emissao if emissao is not None else apurado if apurado is not None else soma
    if liquido is not None and bruto - liquido > iss:
        iss = bruto - liquido
    dt = _dmy(dt_txt)
    e = Extrato(f"AMIL-{codigo}-{numero}", seg, dt, f"NF {nf}" if nf else "", bruto, iss,
                liquido if liquido is not None else bruto - iss, grupos=list(grupos.values()), linhas=qtd)
    if codigo not in CODIGOS_AMIL:
        e.avisos.append(f"Código de produtor Amil não configurado: {codigo}.")
    if not qtd:
        e.divergencias.append(f"{numero}: nenhuma linha de fatura reconhecida no TXT da Amil")
    elif apurado is not None and soma != apurado:
        e.divergencias.append(f"{numero}: soma das linhas {_brl(soma)} x Valor Apurado {_brl(apurado)}")
    return [e]


# ---------------------------------------------------------------- Petlove (XLSX)
def ler_petlove(texto: str, arquivo: str = "") -> list[Extrato]:
    linhas = [[x.strip() for x in l.split("\t")] for l in texto.replace("\r", "").split("\n")]
    tot_com = tot_liq = None
    ajuste = Z
    ci: dict[str, int] = {}
    grupos: dict[str, Grupo] = {}
    soma, qtd, ultima = Z, 0, None
    for c in linhas:
        c += [""] * 25
        if re.fullmatch(r"Valor de comiss.o", c[0], re.I):
            tot_com = _num_livre(c[1].replace("R$", ""))
        elif re.fullmatch(r"Valor de ajuste", c[0], re.I):
            ajuste = _num_livre(c[1].replace("R$", "")) or Z
        elif re.fullmatch(r"Valor total l.quido", c[0], re.I):
            tot_liq = _num_livre(c[1].replace("R$", ""))
        if re.fullmatch(r"Ano", c[0], re.I) and "Nome do Pet" in "|".join(c):
            ci = {re.sub(r"[^A-Z]", "", _sem_acento(h).upper()): k for k, h in enumerate(c) if h}
            continue
        if not ci or not re.fullmatch(r"\d{4}", c[0]):
            continue
        pet = " ".join(c[ci["NOMEDOPET"]].split()).upper()
        cpf = re.sub(r"\D", "", c[ci.get("CPFDOTUTOR", 0)])
        if not pet or not c[ci["VALOR"]]:
            continue
        valor = _num_livre(c[ci["VALOR"]].replace("R$", ""))
        prop = re.sub(r"\D", "", c[ci.get("PROPOSTA", 0)]) if "PROPOSTA" in ci else ""
        parc = _int(c[ci.get("NUMERODAPARCELA", 0)])
        qtd += 1
        soma += valor
        k = f"{prop or cpf}|{pet}|{parc if parc is not None else ''}" + (f"|NEG{qtd}" if valor < 0 else "")
        g = grupos.setdefault(k, Grupo(prop, "SAUDE", pet))
        g.bruta += valor
        if parc is not None and parc not in g.parcelas:
            g.parcelas.append(parc)
        if valor < 0:
            g.obs = "ESTORNO"
        dp = re.search(r"(\d{2})/(\d{2})/(\d{4})", c[ci.get("DATADEPAGAMENTO", 0)])
        if dp:
            d = _dmy("/".join(dp.groups()))
            ultima = max(ultima or d, d)
    if not qtd:
        raise ValueError("Petlove: nenhuma linha reconhecida no arquivo")
    md = re.search(r"(\d{2})[-_.](\d{2})[-_.](\d{4})", arquivo)
    dt = _dmy("/".join(md.groups())) if md else ultima
    if not dt:
        raise ValueError("Petlove: informe a data no nome do arquivo (dd-mm-aaaa)")
    e = Extrato(f"PETLOVE-{dt:%d%m%Y}", "PETLOVE", dt, "EXTRATO PETLOVE", soma, Z, tot_liq if tot_liq is not None else soma,
                grupos=list(grupos.values()), linhas=qtd)
    e.avisos.append("Petlove: cliente = nome do pet; arquivo sem ISS.")
    if tot_com is not None and soma != tot_com:
        e.divergencias.append(f"Soma das linhas {_brl(soma)} x Valor de comissão {_brl(tot_com)}")
    if ajuste:
        e.avisos.append(f"Petlove: valor de ajuste {_brl(ajuste)} no cabeçalho. Confira.")
    return [e]


def _parcela_intervalo(g: Grupo, total: str = "") -> str:
    ps = sorted(set(g.parcelas))
    if not ps:
        return ""
    return (str(ps[0]) if len(ps) == 1 else f"{ps[0]} a {ps[-1]}") + (f"/{total}" if total else "")


# ---------------------------------------------------------------- Yelum / Aliro (CSV ;)
def ler_yelum(texto: str, arquivo: str = "") -> list[Extrato]:
    linhas = texto.lstrip("﻿").replace("\r", "").split("\n")
    dt = doc = dem = ""
    tot = None
    grupos: dict[str, Grupo] = {}
    totais: dict[str, str] = {}
    antecip: set[str] = set()
    soma, qtd = Z, 0
    for i, l in enumerate(linhas):
        c = [x.strip() for x in l.split(";")]
        prox = linhas[i + 1].split(";") if i + 1 < len(linhas) else []
        if re.match(r"^DOC nr\.", c[0], re.I) and prox:
            doc, dem, dt = (prox + ["", "", ""])[:3]
        if re.match(r"^Total Bruto", c[0], re.I) and prox:
            v = [_br(x) for x in prox]
            tot = {"bruto": v[0], "adiant": v[1], "ir": v[3], "iss": v[4], "inss": v[5], "pago": v[6]}
        if len(c) >= 9 and re.fullmatch(r"\d{9,}", c[2]):
            valor = _br(c[8])
            pr = re.search(r"(\d+)\s*/\s*(\d+)", c[4].replace("'", ""))
            qtd += 1
            soma += valor
            k = f"{c[2]}|{c[3] or '0'}" + (f"|NEG{qtd}" if valor < 0 else "")
            g = grupos.setdefault(k, Grupo(c[2], "?", " ".join(c[1].split()).upper(), ramo_padrao="AUTO"))
            g.bruta += valor
            if pr:
                totais[k] = pr.group(2)
                if int(pr.group(1)) not in g.parcelas:
                    g.parcelas.append(int(pr.group(1)))
            if re.search(r"ANTECIP", c[5], re.I):
                antecip.add(k)
            if valor < 0:
                g.obs = "ESTORNO"
    if not qtd or not dt.strip() or not tot:
        raise ValueError("Yelum: não reconheci linhas, data ou totalizador no CSV")
    for k, g in grupos.items():
        g.parcela_fixa = _parcela_intervalo(g, totais.get(k, ""))
        if k in antecip:
            g.obs = (g.obs + " | " if g.obs else "") + "COMISSAO ANTECIPADA"
    d = _dmy(dt.strip())
    e = Extrato(f"YELUM-{d:%d%m%Y}", "YELUM", d, f"DOC {doc.strip()} DEM {dem.strip()}", tot["bruto"],
                tot["ir"] + tot["iss"] + tot["inss"], tot["pago"], grupos=list(grupos.values()), linhas=qtd)
    if soma != tot["bruto"]:
        e.divergencias.append(f"Soma das linhas {_brl(soma)} x Total Bruto {_brl(tot['bruto'])}")
    if tot["adiant"]:
        e.avisos.append(f"Yelum: desconto de adiantamento {_brl(tot['adiant'])} no totalizador.")
    return [e]


# ---------------------------------------------------------------- Pier (PDF do portal)
def ler_pier(texto: str, arquivo: str = "") -> list[Extrato]:
    linhas = [" ".join(l.split()) for l in texto.replace("\r", "").split("\n") if l.strip()]
    md = re.search(r"(\d{2})[-_.](\d{2})[-_.](\d{4})", arquivo)
    mp = re.search(r"data de pagamento realizado em\s*(\d{2}/\d{2}/\d{4})", texto, re.I)
    if not md and not mp:
        raise ValueError("Pier: não achei a data no nome do arquivo (dd-mm-aaaa) nem no PDF")
    dt = _dmy("/".join(md.groups()) if md else mp.group(1))
    ciclo = (re.search(r"Ciclo\s*#(\d+)\s+\d{2}/\d{2}/\d{4}", texto, re.I) or [None, ""])[1]
    re_l = re.compile(r"^(\d{12,}) (.+?) R\$ ?([\d.,]+) ([+-]) ?R\$ ?([\d.,]+)(?: \( ?[\d.,]+ ?% ?\))?(?: (\d{2}/\d{2}/\d{4}))?$")
    mn = re.search(r"Novos contratos\s*\+\s*R\$\s*([\d.,]+)", texto, re.I)
    mc = re.search(r"Contratos cancelados\s*-\s*[A-Z\s-]*R\$\s*([\d.,]+)", texto, re.I)
    esperado = (_br(mn.group(1)) if mn else Z) - (_br(mc.group(1)) if mc else Z)

    def valor(m):
        return _br(m.group(5)) * (-1 if m.group(4) == "-" else 1)

    achadas = [(l, re_l.match(l)) for l in linhas]
    achadas = [(l, m) for l, m in achadas if m]
    soma_bruta = sum((valor(m) for _, m in achadas), Z)
    unicas = list(dict(achadas).items())
    dedup = (mn or mc) and soma_bruta != esperado and sum((valor(m) for _, m in unicas), Z) == esperado
    grupos: dict[str, Grupo] = {}
    soma, qtd = Z, 0
    for _, m in unicas if dedup else achadas:  # o PDF do portal às vezes repete a página
        v = valor(m)
        qtd += 1
        soma += v
        k = m.group(1) + (f"|NEG{qtd}" if v < 0 else "")
        g = grupos.setdefault(k, Grupo(m.group(1), "AUTO", " ".join(m.group(2).split()).upper()))
        g.bruta += v
        if v < 0:
            g.obs = "CANCELAMENTO"
    mi = re.search(r"Impostos e taxas\s*-\s*R\$\s*([\d.,]+)", texto, re.I)
    imp = _br(mi.group(1)) if mi else Z
    e = Extrato(f"PIER-{dt:%d%m%Y}", "PIER", dt, f"CICLO {ciclo}" if ciclo else "", soma, imp, soma - imp,
                grupos=list(grupos.values()), linhas=qtd)
    if not qtd:
        e.divergencias.append("Pier: nenhuma linha de comissão reconhecida no PDF")
    elif (mn or mc) and soma != esperado:
        e.divergencias.append(f"Soma das linhas {_brl(soma)} x total do portal {_brl(esperado)}")
    return [e]


# ---------------------------------------------------------------- EZZE (PDF)
def ler_ezze(texto: str, arquivo: str = "") -> list[Extrato]:
    linhas = [" ".join(l.split()) for l in texto.replace("\r", "").split("\n") if l.strip()]
    mp = re.search(r"Pagamento\s*\n?[^\n]*?(\d{2}/\d{2}/\d{4})", texto)
    md = re.search(r"(\d{2})[-_.](\d{2})[-_.](\d{4})", arquivo)
    if not mp and not md:
        raise ValueError("EZZE: não achei a data de pagamento")
    dt = _dmy(mp.group(1) if mp else "/".join(md.groups()))
    recibo = (re.search(r"RECIBO N.:?\s*([\d/]+)", texto, re.I) or [None, ""])[1]
    re_l = re.compile(r"^(\D+?) (\d{10,}) (\d+) (\d{3}) (\d{2}/\d{2}/\d{4}) (.+?) (-?[\d.]*\d,\d{2}) (-?[\d.]*\d,\d{1,2}) (-?[\d.]*\d,\d{2})$")
    por_parc: dict[str, dict] = {}
    soma, qtd = Z, 0
    for l in linhas:
        m = re_l.match(l)
        if not m or not re.search(r"Comiss|Adiantamento", m.group(1), re.I):
            continue
        v, pn = _br(m.group(9)), int(m.group(4))
        qtd += 1
        soma += v
        p = por_parc.setdefault(f"{m.group(2)}|{pn}", {"apol": m.group(2), "pn": pn, "nome": " ".join(m.group(6).split()).upper(), "v": Z, "tipos": set()})
        p["v"] += v
        p["tipos"].add("REC" if re.match(r"^Recupera", m.group(1), re.I) else "ADI" if re.match(r"^Adiant", m.group(1), re.I) else "PAG")

    def f(rot):
        x = re.search(rot + r"\s*(-?[\d.]*\d,\d{2})", texto, re.I)
        return _br(x.group(1)) if x else None

    tot_bruto, liq = f("TOTAL BRUTO"), f(r"L.QUIDO")
    iss = sum((f(r) or Z for r in (r"I\.S\.S\.", r"I\.R\.R\.F\.", r"I\.N\.S\.S\.", r"PIS/COFINS/CSLL")), Z)
    grupos: dict[str, Grupo] = {}
    zerados = []
    for p in por_parc.values():
        if p["v"] == 0:
            zerados.append(p["nome"])
            continue
        neg = p["v"] < 0
        g = grupos.setdefault(p["apol"] + ("|NEG" if neg else ""), Grupo(p["apol"], "AUTO", p["nome"]))
        g.bruta += p["v"]
        if p["pn"] not in g.parcelas:
            g.parcelas.append(p["pn"])
        if neg:
            g.obs = "RECUPERAÇÃO DE ADIANTAMENTO"
        elif "ADI" in p["tipos"]:
            g.obs = "COMISSAO ANTECIPADA"
    bruto = tot_bruto if tot_bruto is not None else soma
    e = Extrato(f"EZZE-{dt:%d%m%Y}", "EZZE", dt, f"RECIBO {recibo}" if recibo else "RECIBO EZZE", bruto, iss,
                liq if liq is not None else bruto - iss, grupos=list(grupos.values()), linhas=len(grupos))
    if not qtd:
        e.divergencias.append("EZZE: nenhuma linha reconhecida no PDF")
    elif tot_bruto is not None and soma != tot_bruto:
        e.divergencias.append(f"Soma das linhas {_brl(soma)} x TOTAL BRUTO {_brl(tot_bruto)}")
    if zerados:
        e.avisos.append(f"EZZE: {len(zerados)} apólice(s) com pagamento e recuperação de mesmo valor (sem lançamento).")
    return [e]


# ---------------------------------------------------------------- SulAmérica (TXT largura fixa)
def _cat_ramo(r: str) -> str:
    t = _sem_acento(r or "").upper()
    for rx, cat in ((r"ODONTO", "ODONTO"), (r"VIDA|ACID", "VIDA"), (r"SAUDE|PME|ADESAO", "SAUDE"), (r"AUTO", "AUTO"),
                    (r"CONSORCIO", "CONSORCIO"), (r"^RE$|RESID|EMPRES|CONDOM", "RE")):
        if re.search(rx, t):
            return cat
    return t


def ler_sulamerica(texto: str, arquivo: str = "") -> list[Extrato]:
    mny = r"-?[\d.]*\d,\d{2}"
    re_l = re.compile(r"^\s*(\d+)\s+\S+.*?(\d{2}/\d{2}/\d{4})(\d{2}/\d{2}/\d{4})SUL AMERICA.*?\s0((?:\s+" + mny + r"){11})\s+(.*)$")
    re_d = re.compile(r"^\s*\d+\s+(\d{3})(.*?)\s+(\d{8,9})\s+\d+\s+\S+\s+0\s+0\s*\d*?(\d{2}/\d{2}/\d{4})\s+(\d+)\s+\d+\s+\d+\s+\d+\s+([\d.]*\d,\d{2})\s+\d+\s+\d+\s+(-?[\d.]*\d,\d{2})\s")
    re_p = re.compile(r"^\s*(\d+)\s+(\d{2,3})(.*?)\s+(?:\d+\s+)?\d+\s+0\s+\d(\d{2}/\d{2}/\d{4})\s+(\d+)\s+\d+\s+\d+\s+\d+\s+([\d.]*\d,\d{2})\s+\d+\s+\d+\s+(-?[\d.]*\d,\d{2})\s")
    pags: dict[str, dict] = {}
    cont: dict[str, int] = {}
    avisos: list[str] = []
    qtd = 0
    for l in texto.replace("\r", "").split("\n"):
        m = re_l.match(l)
        if not m:
            continue
        t, nr, dt_pag = m.group(4).split(), m.group(1), m.group(3)
        p = pags.setdefault(nr, {"dt": _dmy(dt_pag), "iss": _br(t[1]), "bruto": _br(t[9]), "liq": _br(t[10]), "soma": Z, "grupos": {}})
        cont[nr] = cont.get(nr, 0) + 1
        resto, seq = m.group(5), str(cont[nr])
        if not resto.startswith(seq):
            avisos.append(f"SulAmérica: item fora do padrão no pagamento {nr} (seq {seq}).")
            continue
        resto = resto[len(seq):]
        nome, r2 = " ".join(resto[:40].split()).upper(), resto[40:]
        d = re_d.match(r2)
        pessoas = False
        if d:
            prod, apol, pn, valor_txt = d.group(2).strip(), d.group(3), int(d.group(5)), d.group(7)
        else:
            d2 = re_p.match(r2)  # Seguros de Pessoas (vida, viagem, AP): menos campos
            if not d2:
                avisos.append(f"SulAmérica: não li o item {nome} (pagamento {nr}).")
                continue
            pessoas = True
            prod, apol, pn, valor_txt = re.sub(r"(\s+\d+)+\s*$", "", d2.group(3)).strip(), d2.group(1), int(d2.group(5)), d2.group(7)
            nome = re.sub(r"\s+\d{10}$", "", nome)
        v = _br(valor_txt)
        neg = "-" in valor_txt
        if neg:
            v = -abs(v)
        qtd += 1
        p["soma"] += v
        k = f"{apol}|{'' if pessoas else pn}" + (f"|NEG{qtd}" if neg else "")
        ramo = "VIAGEM" if re.search(r"VIAGEM", prod, re.I) else (_cat_ramo(prod) or ("VIDA" if pessoas else "SAUDE"))
        g = p["grupos"].setdefault(k, Grupo(apol, ramo, nome))
        g.bruta += v
        if pn not in g.parcelas:
            g.parcelas.append(pn)
        if neg:
            g.obs = "ESTORNO"
    if not qtd:
        raise ValueError("Nenhuma linha da SulAmérica reconhecida")
    saida = []
    for nr, p in sorted(pags.items(), key=lambda x: (x[1]["dt"], x[0])):
        e = Extrato(f"SULAMERICA-{p['dt']:%d%m%Y}", "SULAMERICA", p["dt"], f"PAGTO {nr}", p["bruto"], p["iss"], p["liq"],
                    grupos=list(p["grupos"].values()), linhas=sum(len(g.parcelas) for g in p["grupos"].values()))
        if p["soma"] != p["bruto"]:
            e.divergencias.append(f"Pagamento {nr}: soma dos itens {_brl(p['soma'])} x bruto {_brl(p['bruto'])}")
        if p["bruto"] - p["iss"] != p["liq"]:
            e.divergencias.append(f"Pagamento {nr}: bruto - ISS x líquido não fecha")
        saida.append(e)
    saida[0].avisos += avisos
    return saida


# ---------------------------------------------------------------- Zurich (parceria: tabela/XLSX)
_MESES = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6, "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12}


def ler_zurich(texto: str, arquivo: str = "") -> list[Extrato]:
    from datetime import date as _d

    linhas = [" ".join(re.sub(r"(-?)R\$\s*", r"\1", l).split()) for l in texto.replace("\r", "").split("\n") if l.strip()]
    n = r"(-?[\d.]*\d(?:[,.]\d{1,2})?)"
    re_l = re.compile(r"^(\d{1,2})/([A-Za-zçÇ]{3,4}|\d{1,2})\.?(?:/(\d{2,4}))? ZURICH (\S+) (.+?) " + n + " " + n + " " + n + "$", re.I)
    re_t = re.compile(r"^TOTAL (-?[\d.]*\d[,.]\d{2}) (-?[\d.]*\d[,.]\d{2}) (-?[\d.]*\d[,.]\d{2})$", re.I)
    grupos: dict[str, Grupo] = {}
    liq, qtd, ultima, tot = Z, 0, None, None
    divergencias = []
    for l in linhas:
        t = re_t.match(l)
        if t:
            tot = _num_livre(t.group(3))
            continue
        m = re_l.match(l)
        if not m:
            continue
        mes = int(m.group(2)) if m.group(2).isdigit() else _MESES.get(_sem_acento(m.group(2)).lower()[:3])
        if not mes:
            continue
        ano = (2000 + int(m.group(3)) if len(m.group(3)) == 2 else int(m.group(3))) if m.group(3) else date.today().year
        d = _d(ano, mes, int(m.group(1)))
        ultima = max(ultima or d, d)
        b, imp, q = _num_livre(m.group(6)), _num_livre(m.group(7)), _num_livre(m.group(8))
        liq += q
        qtd += 1
        nome = " ".join(m.group(5).split()).upper()
        k = nome + (f"|NEG{qtd}" if q < 0 else "")
        cat = _cat_ramo(m.group(4))
        g = grupos.setdefault(k, Grupo("", cat or m.group(4).upper(), nome, sem_imposto=True))
        g.bruta += q
        if q < 0:
            g.obs = "ESTORNO"
        if b - imp != q:
            divergencias.append(f"{nome}: bruto {_brl(b)} - imposto {_brl(imp)} difere do líquido {_brl(q)}")
    if not qtd:
        raise ValueError("Nenhuma linha da Zurich reconhecida (esperado: data, ZURICH, ramo, cliente, bruto, imposto, líquido)")
    if tot is not None and tot != liq:
        divergencias.append(f"Soma do líquido {_brl(liq)} x linha TOTAL {_brl(tot)}")
    e = Extrato(f"ZURICH-{ultima:%d%m%Y}", "ZURICH", ultima, "PARCERIA", liq, Z, liq, grupos=list(grupos.values()),
                divergencias=divergencias, linhas=qtd)
    e.avisos.append("Zurich: valor lançado = coluna líquido (sem imposto, sem ISS).")
    return [e]


# ---------------------------------------------------------------- MetLife (PDF)
_RAMO_METLIFE = [("VIDA", "VIDA"), ("ACID", "VIDA"), ("PESSOAIS", "VIDA"), ("SAUDE", "SAUDE"), ("ODONTO", "ODONTO")]


def ler_metlife(texto: str, arquivo: str = "") -> list[Extrato]:
    linhas = [" ".join(l.replace("|", "  ").split()) for l in texto.split("\n")]
    linhas = [l for l in linhas if l and not re.fullmatch(r"[-\s]+", l)]
    md = re.search(r"Data Pagamento:\s*\|?\s*(\d{2}/\d{2}/\d{4})", texto, re.I)
    mt = re.search(r"Sub-Total\s*\(Produ.{1,3}o\)\s*:\s*(-?[\d.]*\d,\d{2})", texto, re.I)
    if not md:
        raise ValueError('Não encontrei a "Data Pagamento" no extrato da MetLife')
    v = r"(-?[\d.]*\d,\d{2})"
    # a apólice pode vir na mesma linha (pdfplumber/pdftotext) ou na linha anterior (pypdf)
    re_det = re.compile(r"^(?:(\d[\d.]*)\s+)?(.+?)\s+(\d+)\s+(\d+)\s+\(([A-Z])\)\s+(\S+)\s+(\d{2}/\d{4})\s+" + r"\s+".join([v] * 4) + "$")
    re_sec = re.compile(r"^(\d{2,4})\s+(.+?)\s+(\d{2,3})\s+([A-ZÀ-Ú][A-ZÀ-Ú ]+)$")
    ramo, ult_apol = "", ""
    grupos: dict[str, Grupo] = {}
    soma, qtd = Z, 0
    avisos = []
    for l in linhas:
        if re.fullmatch(r"\d{1,3}(\.\d{3,})+", l):
            ult_apol = l
            continue
        m = re_det.match(l)
        if m and (m.group(1) or ult_apol):
            apol = m.group(1) or ult_apol
            if not ramo:
                avisos.append(f"Linha sem seção de ramo: {m.group(2)}")
                ramo = "?"
            com, parc = _br(m.group(11)), int(m.group(4))
            soma += com
            qtd += 1
            k = f"{apol}|{ramo}" + (f"|NEG{qtd}" if com < 0 else "")
            g = grupos.setdefault(k, Grupo(apol, ramo, m.group(2).upper()))
            g.bruta += com
            if parc not in g.parcelas:
                g.parcelas.append(parc)
            continue
        if re.search(r"Sub-Total|TOTAL|RESUMO|IRRF|ISS|INSS|CSLL|Adiantamentos|Demonstrativo|Produ.{1,3}o$", l, re.I):
            continue
        sec = re_sec.match(l)
        if sec:
            ramo = _ramo_por_texto(sec.group(4), _RAMO_METLIFE)
            if ramo == "?":
                avisos.append(f'Ramo MetLife sem correspondência: "{sec.group(4).strip()}".')

    def total(rot):
        for l in linhas:
            m = re.fullmatch(rf"{rot}\s+(-?[\d.]*\d,\d{{2}})", l) or re.fullmatch(rf"(-?[\d.]*\d,\d{{2}})\s*{rot}", l)
            if m:
                return _br(m.group(1))
        return None

    iss, tt = total("ISS"), total("TOTAL")
    dt = _dmy(md.group(1))
    e = Extrato(f"METLIFE-{dt:%d%m%Y}", "METLIFE", dt, "", soma, iss or Z, tt if tt is not None else soma,
                grupos=list(grupos.values()), avisos=avisos, linhas=qtd)
    if not qtd:
        e.divergencias.append("Nenhuma linha de comissão reconhecida no extrato da MetLife")
    elif mt and _br(mt.group(1)) != soma:
        e.divergencias.append(f"Soma das linhas {_brl(soma)} x Sub-Total (Produção) {_brl(_br(mt.group(1)))}")
    return [e]


# ---------------------------------------------------------------- Suhai (XLSX ou PDF)
def ler_suhai(texto: str, arquivo: str = "") -> list[Extrato]:
    linhas = [l.strip() for l in texto.replace("\r", "").split("\n") if l.strip()]
    xlsx = any(re.match(r"^nm_cliente\t", l, re.I) for l in linhas)
    dt_txt, det, tot_bruto, iss, liquido = "", [], None, Z, None
    if xlsx:
        cols = None
        for i, l in enumerate(linhas):
            f = l.split("\t")
            prox = linhas[i + 1].split("\t") if i + 1 < len(linhas) else []
            if "dt_pagto" in f:
                v = prox[f.index("dt_pagto")] if len(prox) > f.index("dt_pagto") else ""
                m = re.search(r"(\d{4})-(\d{2})-(\d{2})", v)
                dt_txt = f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else (v[:10] if re.match(r"\d{2}/\d{2}/\d{4}", v) else "")
            if f[0] == "nm_cliente":
                cols = {n: k for k, n in enumerate(f)}
                continue
            if f[0] == "vl_bruto":
                vv = prox + ["0"] * 6
                tot_bruto, iss, liquido = _num_livre(vv[0]), _num_livre(vv[2] or "0"), _num_livre(vv[5] or vv[0])
                cols = None
                continue
            if cols and len(f) >= 8 and "cd_apolice" in cols:
                ap = re.match(r"^(\S+)", f[cols["cd_apolice"]] or "")
                if ap:
                    det.append((f[cols["nm_cliente"]], ap.group(1), _int(f[cols["nr_parcela"]]) or 0,
                                f[cols.get("nm_tp_pagamento", 0)], _num_livre(f[cols["vl_pagamento"]])))
    else:
        mdt = re.search(r"Data\s*Pagto\s*:?\s*(\d{2}/\d{2}/\d{4})", texto, re.I)
        dt_txt = mdt.group(1) if mdt else ""
        re_l = re.compile(r"^(.+?) (\d{6,}\S*) End: ?(\d+) (\d{1,3}) (-?[\d.]*\d,\d{2}) (.+?) (-?[\d.]*\d,\d{2}) (-?[\d.]*\d,\d{2})$")
        for l in linhas:
            l = " ".join(l.split())
            m = re_l.match(l)
            if m:
                det.append((m.group(1), m.group(2), int(m.group(4)), m.group(6), _br(m.group(8))))
            for rx, alvo in ((r"^Valor Total \(Tribut.{1,3}rio\)\s*(-?[\d.]*\d,\d{2})", "b"), (r"^I\.S\.S\.\s*(-?[\d.]*\d,\d{2})", "i"),
                             (r"^Valor L.{1,3}quido\s*(-?[\d.]*\d,\d{2})", "l")):
                t = re.match(rx, l, re.I)
                if t:
                    if alvo == "b":
                        tot_bruto = _br(t.group(1))
                    elif alvo == "i":
                        iss = _br(t.group(1))
                    else:
                        liquido = _br(t.group(1))
    if not dt_txt:
        md = re.search(r"(\d{2})[-_.](\d{2})[-_.](\d{4})", arquivo)
        dt_txt = "/".join(md.groups()) if md else ""
    if not dt_txt:
        raise ValueError("Não encontrei a data de pagamento no extrato da Suhai")
    grupos: dict[str, Grupo] = {}
    soma = Z
    avisos = []
    for n, (nome, apol, parc, tipo, valor) in enumerate(det):
        soma += valor
        g = grupos.setdefault(apol + (f"|NEG{n}" if valor < 0 else ""), Grupo(apol, "AUTO", nome.upper()))
        g.bruta += valor
        if parc and parc not in g.parcelas:
            g.parcelas.append(parc)
        if len(nome) > len(g.cliente):
            g.cliente = nome.upper()
        if re.search(r"estorno|cancel|devol|recup", tipo, re.I):
            if valor > 0:
                avisos.append(f'Lançamento de tipo "{tipo}" ({nome}): confira o sinal do valor.')
            else:
                g.obs = "CANCELAMENTO" if re.search(r"cancel", tipo, re.I) else "ESTORNO"
    dt = _dmy(dt_txt)
    e = Extrato(f"SUHAI-{dt:%d%m%Y}", "SUHAI", dt, "", tot_bruto if tot_bruto is not None else soma, iss,
                liquido if liquido is not None else soma - iss, grupos=list(grupos.values()), avisos=avisos, linhas=len(det))
    if not det:
        e.divergencias.append("Nenhuma linha de comissão reconhecida no extrato da Suhai")
    elif tot_bruto is not None and soma != tot_bruto:
        e.divergencias.append(f"Soma das linhas {_brl(soma)} x total do extrato {_brl(tot_bruto)}")
    return [e]


# ---------------------------------------------------------------- Porto Consórcio (PDF)
def ler_porto_consorcio(texto: str, arquivo: str = "") -> list[Extrato]:
    linhas = [" ".join(l.split()) for l in texto.replace("\r", "").split("\n") if l.strip()]
    r_ = r"(?:R\$ ?)?"
    re_cab = re.compile(r"^(\d{6,}) (\d{2}/\d{2}/\d{4}) " + " ".join([r_ + r"(-?[\d.,]+)"] * 6) + "$")
    re_item = re.compile(r"^(.+?) (\d{2}/\d{2}/\d{4}) (\d{2}/\d{2}/\d{4}) " + r_ + r"([\d.,]+) ([\d.,]+) ?% " + r_ + r"(-?[\d.,]+) (\d+)/(\d+)(?: (.*))?$")
    re_prod = re.compile(r"^(.*?)\s*(Bens Pesados|Bens M.veis|Bens Im.veis|Im.veis|Im.vel|Ve.culos|Ve.culo|Autom.veis|Autom.vel|Motos?|"
                         r"Motocicletas?|Servi.os|Caminh.es|Pesados|Leves)$", re.I)
    cab, itens, atual = None, [], None
    for l in linhas:
        m = re_cab.match(l)
        if m:
            v = [_br(x) for x in m.groups()[2:]]
            cab = {"op": m.group(1), "dt": _dmy(m.group(2)), "bruto": v[0], "inss": v[1], "ir": v[2], "iss": v[3], "dc": v[4], "liq": v[5]}
            continue
        m = re_item.match(l)
        if m:
            pr = re_prod.match(m.group(1))
            nome = pr.group(1) if pr else " ".join(m.group(1).split()[:-1])
            atual = {"nome": nome.strip(), "valor": _br(m.group(6)), "parc": int(m.group(7)), "total": int(m.group(8)),
                     "contrato": "", "grupo": "", "cota": ""}
            itens.append(atual)
            continue
        if not atual:
            continue
        c = re.search(r"(\d{5,})\|([^|\s]+)", l)
        if c:
            atual["contrato"], atual["grupo"] = c.group(1), c.group(2)
        q = re.search(r"(?:^|\s)\|(\d+)(?:\s|$)", l)
        if q:
            atual["cota"] = q.group(1)
        nm = re.sub(r"\d{5,}\|[^|\s]+", " ", l)
        nm = re.sub(r"(^|\s)\|\d+(?=\s|$)", " ", nm)
        nm = re.sub(r"N.\s*contrato", " ", nm, flags=re.I)
        nm = " ".join(re.sub(r"SOBRE VENDA|DE CONSORCIO|COMISS.O", " ", nm).split())
        if nm:
            atual["nome"] += " " + nm
    if not cab or not itens:
        raise ValueError("Nenhuma linha reconhecida no extrato Porto Consórcio")
    grupos: dict[str, Grupo] = {}
    totais: dict[str, int] = {}
    soma = Z
    avisos = []
    for i, d in enumerate(itens):
        if not d["contrato"]:
            avisos.append(f"Contrato não encontrado para {d['nome']}")
            continue
        soma += d["valor"]
        chv = f"{d['grupo']}/{d['cota']}" if d["grupo"] and d["cota"] else d["contrato"]
        nm = " ".join(d["nome"].split()).upper()
        k = f"{chv}|{d['parc']}" + (f"|NEG{i}" if d["valor"] < 0 else "")
        g = grupos.setdefault(k, Grupo(chv, "CONSORCIO", f"{chv} - {d['parc']}ª - {nm}"))
        g.bruta += d["valor"]
        totais[k] = d["total"]
        if d["parc"] not in g.parcelas:
            g.parcelas.append(d["parc"])
    for k, g in grupos.items():
        g.parcela_fixa = ", ".join(f"{p}/{totais[k]}" for p in g.parcelas)
    imp = cab["inss"] + cab["ir"] + cab["iss"]
    e = Extrato(f"PORTO-{cab['op']}", "PORTO", cab["dt"], f"CONSORCIO OP {cab['op']}", cab["bruto"], imp, cab["liq"],
                grupos=list(grupos.values()), avisos=avisos, linhas=len(itens))
    if soma != cab["bruto"]:
        e.divergencias.append(f"Soma das linhas {_brl(soma)} x bruto da OP {_brl(cab['bruto'])}")
    if cab["dc"]:
        e.avisos.append(f"A OP tem Débito/Crédito de {_brl(cab['dc'])} ainda não lançado.")
    if cab["liq"] != cab["bruto"] - imp + cab["dc"]:
        e.divergencias.append(f"Líquido da OP {_brl(cab['liq'])} x bruto - impostos + déb/créd")
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
    """pdfplumber (mantém o layout das linhas); PDF com proteção que ele não abre (MetLife) vai pelo pypdf."""
    import io

    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception:  # noqa: BLE001 - pdfminer levanta vários tipos para criptografia desconhecida
        import pypdf

        leitor = pypdf.PdfReader(io.BytesIO(conteudo))
        if leitor.is_encrypted:
            leitor.decrypt("")
        return "\n".join((p.extract_text() or "") for p in leitor.pages)


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
    if re.search(r"^\s*\d{1,2}/[A-Za-zçÇ0-9]{2,4}\.?(/\d{2,4})?[\t ]+ZURICH\b", texto, re.I | re.M):
        return ler_zurich(texto, nome_arquivo)
    if re.search(r"Demonstrativo de Comiss", texto, re.I) and re.search(r"METROPOLITAN LIFE|METLIFE", texto, re.I):
        return ler_metlife(texto, nome_arquivo)
    if re.search(r"Extrato da Ordem de Pagamento", texto, re.I) and re.search(r"Valores da OP", texto, re.I):
        return ler_porto_consorcio(texto, nome_arquivo)
    if re.search(r"Tipo de Pagamento|nm_tp_pagamento", texto, re.I) and re.search(r"Demonstrativo de Comiss|nm_formulario", texto, re.I) \
            and not re.search(r"METLIFE|METROPOLITAN", texto, re.I):
        return ler_suhai(texto, nome_arquivo)
    if re.match(r"Demonstrativo de Corretagem", inicio, re.I) and re.search(r"Marca;Segurado;Apolice", texto, re.I):
        return ler_yelum(texto, nome_arquivo)
    if re.search(r"^Parceiro\t", texto, re.M) and re.search(r"^Ano\tM.s\tNome do Tutor", texto, re.M):
        return ler_petlove(texto, nome_arquivo)
    if re.search(r"data de pagamento realizado em", texto, re.I) and re.search(r"Valor total liquido", texto, re.I):
        return ler_pier(texto, nome_arquivo)
    if re.search(r"Demonstrativo de Corretagem", texto, re.I) and re.search(r"Tipo Pagto\.", texto, re.I) \
            and re.search(r"Pagto\. Comiss|Adiantamento de Comiss|Recupera..o de Adiantamento", texto, re.I):
        return ler_ezze(texto, nome_arquivo)
    if re.search(r"ATUAL PREV CORRETORA", texto, re.I) and re.search(r"SUL AMERICA COMPANHIA|SUL AMERICA SEGUROS", texto, re.I) \
            and re.search(r"\d{2}/\d{2}/\d{4}\d{2}/\d{2}/\d{4}SUL AMERICA", texto):
        return ler_sulamerica(texto, nome_arquivo)
    if re.search(r"###Extrato", texto, re.I) and re.search(r"Operadora:\s*#?\s*AMIL", texto, re.I):
        return ler_amil(texto, nome_arquivo)
    if re.search(r"DETALHAMENTO DE COMISS\S{1,3}O DE CORRETAGEM", texto, re.I) and re.search(r"Data do Pagamento", texto, re.I):
        return ler_hdi(texto, nome_arquivo)
    if re.search(r"EXTRATO DE COMISS\S{1,3}ES", texto, re.I) and re.search(r"Total da Comiss.o Bruta", texto, re.I) \
            and re.search(r"Ramo\s+Produto\s+Ap.lice\s+Endosso", texto, re.I):
        return ler_mapfre(texto, nome_arquivo)
    if (re.search(r"Extrato do Corretor", texto, re.I) and re.search(r"Total da Comiss.o Bruta", texto, re.I)) \
            or re.search(r"^Segurado\tNegocio\t", texto, re.M):
        return ler_tokio(texto, nome_arquivo)
    if re.search(r"EXTRATO DE COMISS\S{1,3}ES PAGAS POR SUSEP", texto, re.I) and re.search(r"Allianz", texto, re.I):
        return ler_allianz(texto, nome_arquivo)
    if re.search(r"Extrato de Comiss\S{1,3}o", texto, re.I) and re.search(r"Nome do cliente|sem lan\S{1,2}amentos", texto, re.I) \
            and re.search(r"Saldo anterior", texto, re.I):
        return ler_sura(texto, nome_arquivo)
    raise ValueError(
        f"{nome_arquivo or 'Arquivo'}: formato não reconhecido "
        "(aceitos hoje: Porto, Bradesco, Odontoprev, Sura, AKAD, Allianz, Azos, MAG, Tokio, HDI, Mapfre, Amil, SulAmérica, Yelum, Pier, Petlove, EZZE, Zurich, MetLife, Suhai, Porto Consórcio)"
    )


def parcela_texto(e: Extrato, g: Grupo) -> str:
    return _parcela_odonto(g) if e.seguradora == "ODONTOPREV" else g.parcela_txt
