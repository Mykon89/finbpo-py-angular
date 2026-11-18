"""Consulta de CNPJ em APIs públicas (BrasilAPI, com CNPJá como reserva)."""

import re
import time
from datetime import date

import httpx
from pydantic import BaseModel

from app.models import Segmento

BRASILAPI = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
CNPJA = "https://open.cnpja.com/office/{cnpj}"
TIMEOUT = httpx.Timeout(10.0)
CACHE_SEGUNDOS = 24 * 3600

# CNAE (7 dígitos) ou prefixo → segmento sugerido
_SEGMENTO_POR_CNAE = [
    ("6622300", Segmento.CORRETORA),  # corretores e agentes de seguros, previdência e saúde
    ("6622", Segmento.CORRETORA),
    ("9602502", Segmento.CLINICA),  # estética e outros cuidados com a beleza
    ("9602", Segmento.CLINICA),
    ("86", Segmento.CLINICA),  # atividades de atenção à saúde humana
]


class CNAE(BaseModel):
    codigo: str
    descricao: str


class DadosCNPJ(BaseModel):
    cnpj: str
    razao_social: str
    nome_fantasia: str | None = None
    situacao_cadastral: str | None = None
    data_abertura: date | None = None
    natureza_juridica: str | None = None
    porte: str | None = None
    cnae_principal: str | None = None
    cnae_descricao: str | None = None
    cnaes_secundarios: list[CNAE] = []
    optante_simples: bool | None = None
    mei: bool | None = None
    cep: str | None = None
    logradouro: str | None = None
    numero: str | None = None
    complemento: str | None = None
    bairro: str | None = None
    municipio: str | None = None
    uf: str | None = None
    telefone: str | None = None
    email: str | None = None
    segmento_sugerido: Segmento | None = None
    fonte: str


class CNPJNaoEncontrado(Exception):
    pass


class ConsultaIndisponivel(Exception):
    pass


def so_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


def cnpj_valido(cnpj: str) -> bool:
    c = so_digitos(cnpj)
    if len(c) != 14 or c == c[0] * 14:
        return False

    def dv(base: str) -> str:
        pesos = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2][-len(base) :]
        r = sum(int(d) * p for d, p in zip(base, pesos)) % 11
        return "0" if r < 2 else str(11 - r)

    return c[12] == dv(c[:12]) and c[13] == dv(c[:13])


def cpf_valido(cpf: str) -> bool:
    c = so_digitos(cpf)
    if len(c) != 11 or c == c[0] * 11:
        return False
    for i in (9, 10):
        r = sum(int(c[j]) * (i + 1 - j) for j in range(i)) * 10 % 11
        if str(r % 10) != c[i]:
            return False
    return True


def sugerir_segmento(cnae: str | None) -> Segmento | None:
    if not cnae:
        return None
    for prefixo, seg in _SEGMENTO_POR_CNAE:
        if cnae.startswith(prefixo):
            return seg
    return None


def _txt(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _data(v) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _cnae(v) -> str | None:
    d = so_digitos(str(v)) if v is not None else ""
    return d.zfill(7) if d else None


def de_brasilapi(d: dict) -> DadosCNPJ:
    tipo_logr = _txt(d.get("descricao_tipo_de_logradouro"))
    logr = _txt(d.get("logradouro"))
    if tipo_logr and logr and not logr.upper().startswith(tipo_logr.upper()):
        logr = f"{tipo_logr} {logr}"
    cnae = _cnae(d.get("cnae_fiscal"))
    return DadosCNPJ(
        cnpj=so_digitos(d.get("cnpj", "")),
        razao_social=_txt(d.get("razao_social")) or "",
        nome_fantasia=_txt(d.get("nome_fantasia")),
        situacao_cadastral=_txt(d.get("descricao_situacao_cadastral")),
        data_abertura=_data(d.get("data_inicio_atividade")),
        natureza_juridica=_txt(d.get("natureza_juridica")),
        porte=_txt(d.get("porte")),
        cnae_principal=cnae,
        cnae_descricao=_txt(d.get("cnae_fiscal_descricao")),
        cnaes_secundarios=[
            CNAE(codigo=_cnae(c.get("codigo")) or "", descricao=c.get("descricao") or "")
            for c in d.get("cnaes_secundarios") or []
            if c.get("codigo")
        ],
        optante_simples=d.get("opcao_pelo_simples"),
        mei=d.get("opcao_pelo_mei"),
        cep=_txt(d.get("cep")),
        logradouro=logr,
        numero=_txt(d.get("numero")),
        complemento=_txt(d.get("complemento")),
        bairro=_txt(d.get("bairro")),
        municipio=_txt(d.get("municipio")),
        uf=_txt(d.get("uf")),
        telefone=_txt(d.get("ddd_telefone_1")),
        email=_txt(d.get("email")),
        segmento_sugerido=sugerir_segmento(cnae),
        fonte="BrasilAPI",
    )


def de_cnpja(d: dict) -> DadosCNPJ:
    emp = d.get("company") or {}
    end = d.get("address") or {}
    principal = d.get("mainActivity") or {}
    fones = d.get("phones") or []
    emails = d.get("emails") or []
    cnae = _cnae(principal.get("id"))
    return DadosCNPJ(
        cnpj=so_digitos(d.get("taxId", "")),
        razao_social=_txt(emp.get("name")) or "",
        nome_fantasia=_txt(d.get("alias")),
        situacao_cadastral=_txt((d.get("status") or {}).get("text")),
        data_abertura=_data(d.get("founded")),
        natureza_juridica=_txt((emp.get("nature") or {}).get("text")),
        porte=_txt((emp.get("size") or {}).get("acronym")),
        cnae_principal=cnae,
        cnae_descricao=_txt(principal.get("text")),
        cnaes_secundarios=[
            CNAE(codigo=_cnae(a.get("id")) or "", descricao=a.get("text") or "")
            for a in d.get("sideActivities") or []
            if a.get("id")
        ],
        optante_simples=(emp.get("simples") or {}).get("optant"),
        mei=(emp.get("simei") or {}).get("optant"),
        cep=_txt(end.get("zip")),
        logradouro=_txt(end.get("street")),
        numero=_txt(end.get("number")),
        complemento=_txt(end.get("details")),
        bairro=_txt(end.get("district")),
        municipio=_txt(end.get("city")),
        uf=_txt(end.get("state")),
        telefone=f"{fones[0].get('area', '')}{fones[0].get('number', '')}" if fones else None,
        email=_txt(emails[0].get("address")) if emails else None,
        segmento_sugerido=sugerir_segmento(cnae),
        fonte="CNPJá",
    )


_cache: dict[str, tuple[float, DadosCNPJ]] = {}


def consultar(cnpj: str, cliente: httpx.Client | None = None) -> DadosCNPJ:
    c = so_digitos(cnpj)
    if not cnpj_valido(c):
        raise ValueError("CNPJ inválido")
    em_cache = _cache.get(c)
    if em_cache and time.monotonic() - em_cache[0] < CACHE_SEGUNDOS:
        return em_cache[1]

    http = cliente or httpx.Client(timeout=TIMEOUT, headers={"User-Agent": "FinBPO/0.1"})
    nao_encontrado = 0
    try:
        for url, conversor in ((BRASILAPI, de_brasilapi), (CNPJA, de_cnpja)):
            try:
                r = http.get(url.format(cnpj=c))
            except httpx.HTTPError:
                continue
            if r.status_code == 404:
                nao_encontrado += 1
                continue
            if r.status_code != 200:
                continue  # 429/5xx: tenta a próxima fonte
            try:
                dados = conversor(r.json())
            except (ValueError, TypeError, AttributeError):
                continue
            _cache[c] = (time.monotonic(), dados)
            return dados
    finally:
        if cliente is None:
            http.close()

    if nao_encontrado:
        raise CNPJNaoEncontrado(c)
    raise ConsultaIndisponivel(c)
