"""Planilha FECHAMENTO DE PROPOSTAS (Google Sheets): leitura, download direto do Google e sincronização.

Uma aba por mês (JAN..DEZ, JAN27...). Cabeçalho nas 10 primeiras linhas com CLIENTE e SEGURADORA.
O download usa a conta de serviço do Google (settings.google_service_account_file) ou, sem ela,
o link de exportação (a planilha precisa estar com "qualquer pessoa com o link pode ver").
"""

import io
import json
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

import httpx
import jwt
from openpyxl import load_workbook
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Entidade, PropostaFechamento
from app.services.planilha import sem_acento

MESES = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]
MAPA_PRODUTOR = {"FABIANA C.": "FABIANA", "ANDREZA PORTFEL": "ANDREZA", "FABIANNY A.": "FABI ANJOS"}
MAPA_PARCEIRO = {"FABY ANJOS": "FABI ANJOS", "ANDREZA PORTFEL": "ANDREZA", "FABIANNY A.": "FABI ANJOS"}
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def norm_seguradora(seg: str | None) -> str:
    """Seguradora comparável entre BASE e FECHAMENTO (mesma regra do script)."""
    s = " ".join(sem_acento(str(seg or "")).upper().split())
    if s.startswith("AMIL"):
        return "AMIL"
    if s in ("AZUL", "ITAU"):
        return "PORTO"
    if s.startswith("TOKIO"):
        return "TOKIO"
    if re.match(r"^(YELUM|ALIRO|LIBERTY)\b", s):
        return "YELUM"
    if re.match(r"^(SA |SULAMERICA|SUL AMERICA)", s):
        return "SULAMERICA"
    if "UNIMED" in s:
        return "UNIMED"
    if re.match(r"^PORTO\b", s):
        return "PORTO"
    return re.sub(r"^COTRASEG ", "", s)


def mapear(valor: str | None, mapa: dict) -> str | None:
    v = " ".join(str(valor or "").split())
    if not v or set(v) <= {"-"}:
        return None
    k = sem_acento(v).upper()
    return mapa.get(k, v.upper())


def _hdr(v) -> str:
    return re.sub(r"[^A-Z]", "", sem_acento(str(v or "")).upper())


def _num(v) -> Decimal | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return Decimal(str(round(v, 2)))
    t = re.sub(r"R\$|\s", "", str(v))
    neg = t.startswith("-")
    t = t.lstrip("-")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        d = Decimal(t).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return -d if neg else d


def _data(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", str(v or ""))
    return date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None


@dataclass
class Leitura:
    linhas: list[dict] = field(default_factory=list)
    abas: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


def ler_xlsx(conteudo: bytes, ano_padrao: int | None = None) -> Leitura:
    wb = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    res = Leitura()
    ano_padrao = ano_padrao or date.today().year
    for ws in wb.worksheets:
        nome = ws.title.upper().strip()
        m = re.fullmatch(r"([A-Z]{3})(\d{2})?", nome)
        if not m or m.group(1) not in MESES:
            continue
        mes = MESES.index(m.group(1)) + 1
        linhas = list(ws.iter_rows(values_only=True, max_col=40))
        topo = " ".join(str(c) for r in linhas[:2] for c in r if c)
        ma = re.search(r"\b(20\d{2})\b", topo)
        ano = 2000 + int(m.group(2)) if m.group(2) else int(ma.group(1)) if ma else ano_padrao
        h = next((i for i, r in enumerate(linhas[:10]) if {"CLIENTE", "SEGURADORA"} <= {_hdr(c) for c in r}
                  or ("CLIENTE" in {_hdr(c) for c in r} and "SEG" in {_hdr(c) for c in r})), None)
        if h is None:
            res.avisos.append(f"aba {nome}: não achei o cabeçalho (CLIENTE e SEGURADORA); ignorada")
            continue
        H = [_hdr(c) for c in linhas[h]]

        def pos(*nomes, nth=1, prefixo=False):
            for n in nomes:
                achados = [i for i, x in enumerate(H) if (x.startswith(n) if prefixo else x == n)]
                if len(achados) >= nth:
                    return achados[nth - 1]
            return -1

        c = {
            "cli": pos("CLIENTE", "SEGURADO", "NOMEDOCLIENTE"),
            "seg": pos("SEGURADORA", "SEG", "SEGURADORAS", "CIA"),
            "ramo": pos("RAMO"),
            "tipo": pos("TIPO"),
            "prod": pos("PRODUTOR"),
            "orig": pos("ORIGEM"),
            "desc": pos("DESCRICAO"),
            "dt": pos("DATADEEMAIL", prefixo=True),
            "vig": pos("VIGENCIAINICIAL", prefixo=True),
            "pl": pos("PREMIOLIQ", prefixo=True),
            "bruta": pos("COMBRUTA", "COMISSAOBRUTA", "CBRUTA"),
            "em": pos("EMISSAO"),
            "rec": pos("RECEBIDO"),
        }
        c["parc"] = pos("PARCEIROA", "PARCEIRO", prefixo=True)
        if c["parc"] < 0:
            c["parc"] = pos("ORIGEM", nth=2)  # em MAI a coluna do parceiro se chama "Origem"

        def v(r, k):
            i = c[k]
            return r[i] if 0 <= i < len(r) else None

        n = 0
        for k, r in enumerate(linhas[h + 1:]):
            cli = " ".join(str(v(r, "cli") or "").split())
            if not cli:
                continue
            n += 1
            res.linhas.append({
                "ano": ano, "mes": mes, "aba": nome, "linha": h + 2 + k,
                "data_email": _data(v(r, "dt")), "vigencia_inicio": _data(v(r, "vig")),
                "tipo": " ".join(str(v(r, "tipo") or "").split()) or None,
                "seguradora": norm_seguradora(v(r, "seg")), "ramo": " ".join(str(v(r, "ramo") or "").split()) or None,
                "descricao": " ".join(str(v(r, "desc") or "").split())[:120] or None, "cliente": cli.upper()[:200],
                "produtor": mapear(v(r, "prod"), MAPA_PRODUTOR), "origem": mapear(v(r, "orig"), {}),
                "parceiro": mapear(v(r, "parc"), MAPA_PARCEIRO), "premio": _num(v(r, "pl")), "com_bruta": _num(v(r, "bruta")),
                "emissao": (str(v(r, "em") or "").strip().upper() or None), "recebido": _num(v(r, "rec")),
            })
        res.abas.append(f"{nome} ({n})")
    return res


# ---------------------------------------------------------------- download do Google
def _token_conta_servico(caminho: str) -> str:
    with open(caminho, encoding="utf-8") as f:
        sa = json.load(f)
    agora = int(time.time())
    afirmacao = jwt.encode(
        {"iss": sa["client_email"], "scope": "https://www.googleapis.com/auth/drive.readonly",
         "aud": sa.get("token_uri", "https://oauth2.googleapis.com/token"), "iat": agora, "exp": agora + 3600},
        sa["private_key"], algorithm="RS256",
    )
    r = httpx.post(sa.get("token_uri", "https://oauth2.googleapis.com/token"),
                   data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": afirmacao}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def baixar(planilha_id: str) -> bytes:
    planilha_id = extrair_id(planilha_id)
    if settings.google_service_account_file:
        token = _token_conta_servico(settings.google_service_account_file)
        r = httpx.get(f"https://www.googleapis.com/drive/v3/files/{planilha_id}/export", params={"mimeType": XLSX},
                      headers={"Authorization": f"Bearer {token}"}, timeout=60)
        if r.status_code in (403, 404):
            raise ValueError("A conta de serviço não tem acesso: compartilhe a planilha com o e-mail dela (leitor)")
        r.raise_for_status()
        return r.content
    r = httpx.get(f"https://docs.google.com/spreadsheets/d/{planilha_id}/export", params={"format": "xlsx"},
                  follow_redirects=True, timeout=60)
    if r.status_code != 200 or r.content[:2] != b"PK":
        raise ValueError(
            "Não consegui baixar a planilha. Configure a conta de serviço do Google (recomendado) "
            "ou deixe a planilha com 'qualquer pessoa com o link pode ver'."
        )
    return r.content


def extrair_id(texto: str) -> str:
    m = re.search(r"/d/([A-Za-z0-9_-]{20,})", texto or "")
    return m.group(1) if m else (texto or "").strip()


def gravar(db: Session, entidade: Entidade, leitura: Leitura) -> int:
    db.execute(delete(PropostaFechamento).where(PropostaFechamento.entidade_id == entidade.id))
    for l in leitura.linhas:
        db.add(PropostaFechamento(entidade_id=entidade.id, **l))
    entidade.fechamento_sincronizado_em = datetime.now(UTC)
    db.commit()
    return len(leitura.linhas)


def sincronizar(db: Session, entidade: Entidade) -> Leitura:
    if not entidade.fechamento_planilha_id:
        raise ValueError("Informe o link ou ID da planilha FECHAMENTO DE PROPOSTAS")
    leitura = ler_xlsx(baixar(entidade.fechamento_planilha_id))
    gravar(db, entidade, leitura)
    return leitura
