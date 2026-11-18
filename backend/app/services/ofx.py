"""Leitor tolerante de OFX (1.x SGML e 2.x XML).

Bancos brasileiros costumam gerar OFX com:
- cabeçalho SGML e tags sem fechamento;
- encoding cp1252/latin-1 declarado (ou não) no cabeçalho;
- datas com fuso ``[-3:BRT]``;
- valores com vírgula decimal;
- FITID repetido ou ausente.
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation


class OFXInvalido(ValueError):
    pass


@dataclass
class TransacaoOFX:
    data: date
    valor: Decimal
    descricao: str
    fitid: str | None
    tipo: str | None
    hash: str = ""


@dataclass
class ExtratoOFX:
    banco_id: str | None
    instituicao: str | None  # <FI><ORG>, comum em OFX de cartão
    conta_id: str | None
    agencia: str | None
    moeda: str | None
    inicio: date | None
    fim: date | None
    saldo: Decimal | None
    data_saldo: date | None
    cartao: bool
    transacoes: list[TransacaoOFX] = field(default_factory=list)


_RE_TRN = re.compile(r"<STMTTRN>(.*?)(?=</STMTTRN>|<STMTTRN>|</BANKTRANLIST>)", re.S | re.I)


def decodificar(conteudo: bytes) -> str:
    cabecalho = conteudo[:600].decode("ascii", errors="ignore").upper()
    candidatos = []
    if "CHARSET:1252" in cabecalho or "WINDOWS-1252" in cabecalho:
        candidatos.append("cp1252")
    if "UTF-8" in cabecalho or "CHARSET:UTF" in cabecalho:
        candidatos.append("utf-8")
    candidatos += ["utf-8", "cp1252", "latin-1"]
    for enc in candidatos:
        try:
            return conteudo.decode(enc)
        except UnicodeDecodeError:
            continue
    raise OFXInvalido("Não foi possível decodificar o arquivo")


def _tag(bloco: str, nome: str) -> str | None:
    m = re.search(rf"<{nome}>([^<\r\n]*)", bloco, re.I)
    if not m:
        return None
    valor = m.group(1).strip()
    return valor or None


def _data(valor: str | None) -> date | None:
    if not valor:
        return None
    m = re.match(r"(\d{4})(\d{2})(\d{2})", valor)
    if not m:
        return None
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _valor(valor: str | None) -> Decimal | None:
    if valor is None:
        return None
    v = valor.replace(" ", "")
    if "," in v and "." in v:  # 1.234,56
        v = v.replace(".", "").replace(",", ".")
    elif "," in v:
        v = v.replace(",", ".")
    try:
        return Decimal(v).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _limpar(texto: str | None) -> str:
    return re.sub(r"\s+", " ", texto or "").strip()


def hash_transacao(conta: str, data: date, valor: Decimal, descricao: str, fitid: str | None, seq: int) -> str:
    # seq diferencia lançamentos idênticos no mesmo dia (ex.: duas tarifas iguais)
    base = f"{conta}|{fitid or ''}|{data.isoformat()}|{valor}|{descricao.upper()}|{seq}"
    return hashlib.sha256(base.encode()).hexdigest()


def ler_ofx(conteudo: bytes) -> ExtratoOFX:
    texto = decodificar(conteudo)
    if "<OFX>" not in texto.upper():
        raise OFXInvalido("Arquivo não parece ser OFX (tag <OFX> ausente)")

    cartao = "<CCSTMTRS>" in texto.upper()
    corpo_upper = texto.upper()
    i_saldo = corpo_upper.find("<LEDGERBAL>")
    bloco_saldo = texto[i_saldo : i_saldo + 300] if i_saldo >= 0 else ""

    extrato = ExtratoOFX(
        banco_id=_tag(texto, "BANKID") or _tag(texto, "FID"),
        instituicao=_tag(texto, "ORG"),
        conta_id=_tag(texto, "ACCTID"),
        agencia=_tag(texto, "BRANCHID"),
        moeda=_tag(texto, "CURDEF"),
        inicio=_data(_tag(texto, "DTSTART")),
        fim=_data(_tag(texto, "DTEND")),
        saldo=_valor(_tag(bloco_saldo, "BALAMT")),
        data_saldo=_data(_tag(bloco_saldo, "DTASOF")),
        cartao=cartao,
    )

    vistos: dict[tuple, int] = {}
    for m in _RE_TRN.finditer(texto):
        bloco = m.group(1)
        data = _data(_tag(bloco, "DTPOSTED"))
        valor = _valor(_tag(bloco, "TRNAMT"))
        if data is None or valor is None:
            continue
        memo = _limpar(_tag(bloco, "MEMO"))
        nome = _limpar(_tag(bloco, "NAME"))
        descricao = memo if not nome or nome in memo else f"{nome} {memo}".strip()
        descricao = descricao[:255] or "(sem descrição)"
        fitid = _tag(bloco, "FITID")
        trn = TransacaoOFX(data=data, valor=valor, descricao=descricao, fitid=fitid, tipo=_tag(bloco, "TRNTYPE"))
        chave = (data, valor, descricao, fitid)
        seq = vistos.get(chave, 0)
        vistos[chave] = seq + 1
        trn.hash = hash_transacao(extrato.conta_id or "", data, valor, descricao, fitid, seq)
        extrato.transacoes.append(trn)

    return extrato
