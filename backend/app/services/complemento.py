"""Leitura de extratos em XLSX/XLS/CSV/PDF para complementar os lançamentos do OFX.

O OFX é a base (tem FITID e evita duplicidade). Os outros formatos trazem
informações que o OFX costuma omitir: nome e CPF/CNPJ de quem pagou ou recebeu
e descrições mais completas. Cada linha é casada com um lançamento já importado
pela data e pelo valor absoluto (o sinal vem do OFX).
"""

import csv
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from app.services.cnpj import cnpj_valido, cpf_valido, so_digitos


class ArquivoInvalido(ValueError):
    pass


@dataclass
class LinhaComplementar:
    data: date
    valor: Decimal  # absoluto
    descricao: str
    nome: str | None = None
    documento: str | None = None  # CPF/CNPJ, só dígitos


# --- utilidades ---------------------------------------------------------------

# Aceita "12.345.678/0001-90", "12345678000190" e "12.345.678 0001-90" (Sicoob usa espaço)
_RE_CNPJ = re.compile(r"(?<!\d)\d{2}\.?\d{3}\.?\d{3}[/\s]?\d{4}-?\d{2}(?!\d)")
_RE_CPF = re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")
_RE_VALOR = re.compile(r"-?\s?R?\$?\s?\d{1,3}(?:\.\d{3})*,\d{2}\s?-?(?:\s?[CD]\b)?|-?\d+,\d{2}\s?-?(?:\s?[CD]\b)?")
_RE_DATA = re.compile(r"^(\d{2})/(\d{2})(?:/(\d{2,4}))?\b")

# Palavras de banco que cercam o nome da contraparte e não fazem parte dele
_RUIDO = {
    "pix", "ted", "doc", "tef", "transf", "transferencia", "pag", "pagamento", "pagto", "pgto", "receb",
    "recebimento", "recebido", "recebida", "enviado", "enviada", "emitido", "emitida", "outra", "outras",
    "mesma", "if", "ifs", "instituicao", "titularidade", "deposito", "credito", "debito", "boleto", "qr",
    "code", "qrcode", "internet", "sispag", "conta", "corrente", "de", "para", "em", "no", "na", "cpf",
    "cnpj", "chave", "agendado", "agendamento", "compra", "app", "mobile", "banking", "transacao",
    "liquidacao", "cobranca", "tit", "titulo", "estorno", "devolucao", "-", "–", ":", "/", "|",
}


def _norm(s: object) -> str:
    t = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", t).strip()


def extrair_documento(texto: str) -> str | None:
    for regex, valida in ((_RE_CNPJ, cnpj_valido), (_RE_CPF, cpf_valido)):
        for m in regex.finditer(texto or ""):
            d = so_digitos(m.group())
            if valida(d):
                return d
    return None


def documento_valido(valor: object) -> str | None:
    d = so_digitos(str(valor or ""))
    if len(d) == 14 and cnpj_valido(d):
        return d
    if len(d) == 11 and cpf_valido(d):
        return d
    return None


def _limpar_nome(trecho: str) -> str | None:
    tokens = re.sub(r"\d{2}/\d{2}(/\d{2,4})?", " ", trecho).split()
    while tokens and (_norm(tokens[0]) in _RUIDO or not re.search(r"[A-Za-zÀ-ÿ]", tokens[0])):
        tokens.pop(0)
    while tokens and (_norm(tokens[-1]) in _RUIDO or not re.search(r"[A-Za-zÀ-ÿ]", tokens[-1])):
        tokens.pop()
    nome = " ".join(tokens).strip(" -–:/|")
    return nome[:160] if len(re.sub(r"[^A-Za-zÀ-ÿ]", "", nome)) >= 3 else None


def nome_da_descricao(texto: str) -> str | None:
    """Isola o nome da contraparte, ex.: 'Pagamento Pix 64.927.828 0001-72 HELVIS HONORARIOS' → 'HELVIS HONORARIOS'.

    Prefere o texto depois do CPF/CNPJ (padrão mais comum) e cai para o texto antes dele.
    """
    texto = re.sub(r"\s+", " ", texto or "")
    m = _RE_CNPJ.search(texto) or _RE_CPF.search(texto)
    if m:
        return _limpar_nome(texto[m.end() :]) or _limpar_nome(texto[: m.start()])
    return _limpar_nome(texto)


def _valor(v: object) -> Decimal | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float, Decimal)):
        return Decimal(str(v)).quantize(Decimal("0.01"))
    s = str(v).strip().upper().replace("R$", "").replace(" ", "")
    negativo = s.startswith("-") or s.endswith("-") or s.endswith("D") or (s.startswith("(") and s.endswith(")"))
    s = s.strip("-()CD+")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        d = Decimal(s).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return -d if negativo else d


def _data(v: object, ano_padrao: int | None = None) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    m = re.match(r"\s*(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?", str(v or ""))
    if not m:
        m2 = re.match(r"\s*(\d{4})-(\d{2})-(\d{2})", str(v or ""))
        if m2:
            return date(int(m2.group(1)), int(m2.group(2)), int(m2.group(3)))
        return None
    dia, mes, ano = int(m.group(1)), int(m.group(2)), m.group(3)
    if ano is None:
        if not ano_padrao:
            return None
        a = ano_padrao
    else:
        a = int(ano) + (2000 if len(ano) == 2 else 0)
    try:
        return date(a, mes, dia)
    except ValueError:
        return None


# --- planilhas (XLSX, XLS, CSV) ----------------------------------------------

_CABECALHOS = {
    "data": ("data", "dt ", "dt.", "data lancamento", "data mov", "data do lancamento", "data da transacao"),
    "descricao": ("historico", "descricao", "lancamento", "detalhe", "transacao", "memo"),
    "valor": ("valor", "montante", "quantia"),
    "credito": ("credito", "entrada", "creditos"),
    "debito": ("debito", "saida", "debitos"),
    "nome": (
        "nome", "favorecido", "pagador", "beneficiario", "origem/destino", "contraparte",
        "remetente", "destinatario", "razao social", "recebedor", "origem", "destino",
    ),
    "documento": ("cpf/cnpj", "cnpj/cpf", "cpf / cnpj", "cnpj", "cpf", "documento do favorecido", "doc. favorecido"),
}
_IGNORAR_DESC = ("saldo", "s a l d o", "saldo anterior", "saldo do dia", "saldo final")


def _classificar(cabecalho: str) -> str | None:
    c = _norm(cabecalho)
    if not c:
        return None
    if "saldo" in c:
        return "saldo"
    for chave in ("documento", "credito", "debito", "data", "nome", "descricao", "valor"):
        for termo in _CABECALHOS[chave]:
            if c == termo.strip() or c.startswith(termo) or f" {termo.strip()}" in f" {c}":
                return chave
    return None


def _de_linhas(linhas: list[list[object]]) -> list[LinhaComplementar]:
    # Encontra a linha de cabeçalho: a primeira com data + (valor ou crédito/débito)
    mapa: dict[str, int] = {}
    inicio = None
    for i, linha in enumerate(linhas[:40]):
        m: dict[str, int] = {}
        for j, cel in enumerate(linha):
            chave = _classificar(cel) if isinstance(cel, str) else None
            if chave and chave not in m:
                m[chave] = j
        if "data" in m and ("valor" in m or "credito" in m or "debito" in m):
            mapa, inicio = m, i + 1
            break
    if inicio is None:
        raise ArquivoInvalido("Não encontrei o cabeçalho (colunas de data e valor) na planilha")

    def cel(linha, chave):
        j = mapa.get(chave)
        return linha[j] if j is not None and j < len(linha) else None

    resultado = []
    for linha in linhas[inicio:]:
        d = _data(cel(linha, "data"))
        if not d:
            continue
        usadas = {mapa.get(k) for k in ("data", "valor", "credito", "debito", "saldo", "nome", "documento")}
        textos = [
            re.sub(r"\s+", " ", str(v)).strip()
            for j, v in enumerate(linha)
            if j not in usadas and isinstance(v, str) and v.strip() and not _data(v) and _valor(v) is None
        ]
        principal = re.sub(r"\s+", " ", str(cel(linha, "descricao") or "")).strip()
        descricao = " ".join(dict.fromkeys([principal, *textos])).strip() if principal else " ".join(textos)
        if not descricao or _norm(descricao).startswith(_IGNORAR_DESC):
            continue
        if "valor" in mapa:
            valor = _valor(cel(linha, "valor"))
        else:
            cr, db = _valor(cel(linha, "credito")), _valor(cel(linha, "debito"))
            valor = (cr or Decimal(0)) - abs(db or Decimal(0)) if (cr or db) else None
        if not valor:
            continue
        nome = re.sub(r"\s+", " ", str(cel(linha, "nome") or "")).strip() or None
        documento = documento_valido(cel(linha, "documento")) or extrair_documento(f"{descricao} {nome or ''}")
        if not nome:
            # o nome costuma estar na mesma célula do CPF/CNPJ
            com_doc = next((t for t in [*textos, principal] if documento and extrair_documento(t) == documento), None)
            nome = nome_da_descricao(com_doc or descricao) if documento else None
        resultado.append(LinhaComplementar(d, abs(valor), descricao[:255], nome and nome[:160], documento))
    return resultado


def ler_xlsx(conteudo: bytes) -> list[LinhaComplementar]:
    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001 - openpyxl levanta vários tipos
        raise ArquivoInvalido(f"Não foi possível abrir a planilha: {e}") from e
    erros = []
    for ws in wb.worksheets:
        linhas = [list(r) for r in ws.iter_rows(values_only=True)]
        try:
            return _de_linhas(linhas)
        except ArquivoInvalido as e:
            erros.append(str(e))
    raise ArquivoInvalido(erros[0] if erros else "Planilha vazia")


def ler_xls(conteudo: bytes) -> list[LinhaComplementar]:
    import xlrd

    try:
        wb = xlrd.open_workbook(file_contents=conteudo)
    except Exception as e:  # noqa: BLE001
        raise ArquivoInvalido(f"Não foi possível abrir a planilha .xls: {e}") from e
    erros = []
    for ws in wb.sheets():
        linhas = []
        for r in range(ws.nrows):
            linha = []
            for c in range(ws.ncols):
                cel = ws.cell(r, c)
                if cel.ctype == xlrd.XL_CELL_DATE:
                    linha.append(xlrd.xldate_as_datetime(cel.value, wb.datemode))
                else:
                    linha.append(cel.value)
            linhas.append(linha)
        try:
            return _de_linhas(linhas)
        except ArquivoInvalido as e:
            erros.append(str(e))
    raise ArquivoInvalido(erros[0] if erros else "Planilha vazia")


def ler_csv(conteudo: bytes) -> list[LinhaComplementar]:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            texto = conteudo.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    try:
        dialeto = csv.Sniffer().sniff(texto[:4000], delimiters=";,\t|")
    except csv.Error:
        dialeto = csv.excel
        dialeto.delimiter = ";"
    return _de_linhas([list(r) for r in csv.reader(io.StringIO(texto), dialeto)])


# --- PDF ----------------------------------------------------------------------


def ler_pdf(conteudo: bytes, ano_padrao: int | None = None, senha: str | None = None) -> list[LinhaComplementar]:
    """Extração genérica: linhas que começam com data e contêm um valor.

    Linhas seguintes sem data são tratadas como continuação da descrição
    (muitos bancos põem o nome/CNPJ da contraparte na linha de baixo).
    """
    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(conteudo), password=senha or "") as pdf:
            texto = "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception as e:  # noqa: BLE001
        msg = str(e).lower()
        if "password" in msg or "encrypt" in msg:
            raise ArquivoInvalido("PDF protegido por senha") from e
        raise ArquivoInvalido(f"Não foi possível ler o PDF: {e}") from e
    if not texto.strip():
        raise ArquivoInvalido("PDF sem texto (provavelmente é imagem escaneada)")

    if ano_padrao is None:
        anos = re.findall(r"\b\d{2}/\d{2}/(20\d{2})\b", texto)
        ano_padrao = int(max(set(anos), key=anos.count)) if anos else date.today().year

    resultado: list[LinhaComplementar] = []
    atual: LinhaComplementar | None = None  # lançamento com valor, aceitando continuação
    pendente: dict | None = None  # começou com data mas o valor ainda não apareceu
    ultima_data: date | None = None

    def fechar(d: date, descricao: str, valor_txt: str) -> LinhaComplementar | None:
        descricao = re.sub(r"\s+", " ", descricao).strip(" -")
        valor = _valor(valor_txt)
        if not valor or not descricao or _norm(descricao).startswith(_IGNORAR_DESC):
            return None
        item = LinhaComplementar(d, abs(valor), descricao[:255])
        resultado.append(item)
        return item

    for bruta in texto.splitlines():
        linha = re.sub(r"\s+", " ", bruta).strip()
        if not linha:
            continue
        if _norm(linha).startswith(_IGNORAR_DESC):
            atual = pendente = None
            continue
        m = _RE_DATA.match(linha)
        d = _data(m.group(0), ano_padrao) if m else None
        corpo = linha[m.end() :].strip() if d else linha
        valores = list(_RE_VALOR.finditer(corpo))

        if d:
            ultima_data = d
            atual = pendente = None
            if valores:
                atual = fechar(d, corpo[: valores[0].start()], valores[0].group())
            else:
                pendente = {"data": d, "texto": corpo, "linhas": 0}
        elif pendente is not None:
            if valores:
                atual = fechar(pendente["data"], f"{pendente['texto']} {corpo[: valores[0].start()]}", valores[0].group())
                pendente = None
            else:
                pendente["texto"] += f" {corpo}"
                pendente["linhas"] += 1
                if pendente["linhas"] > 3:  # não era lançamento (cabeçalho, rodapé)
                    pendente = None
        elif valores and ultima_data and atual is not None and valores[0].start() > 0:
            # vários lançamentos no mesmo dia: só o primeiro mostra a data
            atual = fechar(ultima_data, corpo[: valores[0].start()], valores[0].group())
        elif atual is not None and not valores and len(linha) < 160:
            atual.descricao = f"{atual.descricao} {linha}"[:255]
        else:
            atual = None

    for item in resultado:
        item.documento = extrair_documento(item.descricao)
        if item.documento and not item.nome:
            item.nome = nome_da_descricao(item.descricao)
    return resultado


def ler_complemento(nome_arquivo: str, conteudo: bytes, ano_padrao: int | None = None) -> list[LinhaComplementar]:
    ext = nome_arquivo.lower().rsplit(".", 1)[-1] if "." in nome_arquivo else ""
    if ext == "xlsx" or conteudo[:2] == b"PK":
        return ler_xlsx(conteudo)
    if ext == "xls" or conteudo[:4] == b"\xd0\xcf\x11\xe0":
        return ler_xls(conteudo)
    if ext == "pdf" or conteudo[:4] == b"%PDF":
        return ler_pdf(conteudo, ano_padrao)
    if ext in ("csv", "txt"):
        return ler_csv(conteudo)
    raise ArquivoInvalido(f"Formato não suportado: {nome_arquivo}")


# --- casamento com os lançamentos --------------------------------------------


def casar(transacoes: list, linhas: list[LinhaComplementar], tolerancia_dias: int = 1) -> list[tuple]:
    """Casa linhas complementares com transações (data e valor absoluto), um para um.

    Primeiro tenta data exata; depois ±tolerância. Retorna pares (transacao, linha).
    """
    livres = list(transacoes)
    pares = []
    pendentes = []
    for linha in linhas:
        alvo = next((t for t in livres if t.data == linha.data and abs(t.valor) == linha.valor), None)
        if alvo:
            livres.remove(alvo)
            pares.append((alvo, linha))
        else:
            pendentes.append(linha)
    for linha in pendentes:
        janela = timedelta(days=tolerancia_dias)
        cands = [t for t in livres if abs(t.valor) == linha.valor and abs(t.data - linha.data) <= janela]
        if len(cands) == 1:
            livres.remove(cands[0])
            pares.append((cands[0], linha))
    return pares
