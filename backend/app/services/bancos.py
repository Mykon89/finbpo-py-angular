"""Nomes de bancos pelo código COMPE (o BANKID do OFX)."""

import httpx

from app.services.cnpj import so_digitos

# Bancos mais comuns; os demais são consultados na BrasilAPI
BANCOS = {
    "001": "Banco do Brasil",
    "033": "Santander",
    "041": "Banrisul",
    "070": "BRB",
    "077": "Inter",
    "085": "Ailos",
    "102": "XP",
    "104": "Caixa",
    "136": "Unicred",
    "197": "Stone",
    "208": "BTG Pactual",
    "212": "Banco Original",
    "237": "Bradesco",
    "260": "Nubank",
    "290": "PagBank",
    "323": "Mercado Pago",
    "336": "C6 Bank",
    "341": "Itaú",
    "380": "PicPay",
    "403": "Cora",
    "422": "Safra",
    "655": "Banco BV",
    "748": "Sicredi",
    "756": "Sicoob",
}

_cache: dict[str, str | None] = {}


def normalizar_codigo(codigo: str | None) -> str | None:
    d = so_digitos(codigo or "").lstrip("0")
    if not d or len(d) > 3:
        return None
    return d.zfill(3)


def nome_banco(codigo: str | None, consultar_api: bool = True) -> str | None:
    cod = normalizar_codigo(codigo)
    if not cod:
        return None
    if cod in BANCOS:
        return BANCOS[cod]
    if cod in _cache or not consultar_api:
        return _cache.get(cod)
    nome = None
    try:
        r = httpx.get(f"https://brasilapi.com.br/api/banks/v1/{int(cod)}", timeout=5)
        if r.status_code == 200:
            nome = (r.json().get("name") or "").strip().title() or None
    except (httpx.HTTPError, ValueError):
        pass
    _cache[cod] = nome
    return nome
