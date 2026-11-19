"""Pasta monitorada: importa sozinho os extratos que os robôs (ou o Claude in Chrome) salvam nela.

Estrutura:  <pasta>/arquivo.pdf            -> entidade de EXTRATOS_ENTIDADE_ID
            <pasta>/<id ou CNPJ>/arquivo   -> essa entidade
Cada arquivo é processado uma vez (pelo conteúdo). Arquivos que não são extrato de seguradora são ignorados.
"""

import asyncio
import hashlib
import logging
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import ArquivoMonitorado, Entidade
from datetime import UTC, timedelta
from app.services import auditoria, bancario, comissoes, decisoes, extratos_seguradoras, previsao
from app.services.cnpj import so_digitos

log = logging.getLogger("finbpo.pasta")
EXTENSOES = {".pdf", ".txt", ".csv", ".xlsx", ".xls", ".do", ".htm", ".html", ".ofx"}
TAMANHO_MAX = 20 * 1024 * 1024


def _entidade_da_pasta(db: Session, pasta: str, raiz: Path, arquivo: Path) -> int | None:
    rel = arquivo.relative_to(raiz)
    if len(rel.parts) > 1:
        nome = rel.parts[0]
        dig = so_digitos(nome)
        if dig.isdigit() and len(dig) in (11, 14):
            ent = db.scalar(select(Entidade).where(Entidade.documento == dig))
            return ent.id if ent else None
        if nome.isdigit():
            return int(nome) if db.get(Entidade, int(nome)) else None
        return None
    return settings.extratos_entidade_id


def varrer(db: Session, pasta: str | None = None) -> list[ArquivoMonitorado]:
    if not (pasta or settings.extratos_pasta):
        return []
    raiz = Path(pasta or settings.extratos_pasta)
    if not raiz.is_dir():
        return []
    novos: list[ArquivoMonitorado] = []
    tocadas: set[int] = set()
    for arq in sorted(raiz.rglob("*")):
        if not arq.is_file() or arq.suffix.lower() not in EXTENSOES or arq.name.startswith((".", "~$")):
            continue
        if arq.stat().st_size > TAMANHO_MAX or arq.name.endswith((".crdownload", ".part")):
            continue
        eid = _entidade_da_pasta(db, str(raiz), raiz, arq)
        if not eid:
            continue
        conteudo = arq.read_bytes()
        h = hashlib.sha256(conteudo).hexdigest()
        if db.scalar(select(ArquivoMonitorado.id).where(ArquivoMonitorado.entidade_id == eid, ArquivoMonitorado.hash == h)):
            continue
        reg = ArquivoMonitorado(entidade_id=eid, nome=str(arq.relative_to(raiz))[:255], hash=h, situacao="importado")
        nome_leitura = arq.name
        if not re.search(r"\d{2}[-_.]\d{2}[-_.]\d{4}", arq.name):
            # alguns arquivos (Tokio XLSX, Petlove) só têm a data no nome: usa o dia em que foi baixado
            nome_leitura = f"{arq.stem}_{datetime.fromtimestamp(arq.stat().st_mtime):%d-%m-%Y}{arq.suffix}"
        if arq.suffix.lower() == ".ofx":
            try:
                rs = bancario.importar_ofx(db, eid, conteudo, arq.name)
                reg.extratos = f"conta {rs.conta_id}: {rs.novas} lançamento(s) novo(s)" + (" (conta criada)" if rs.conta_criada else "")
                reg.situacao = "importado" if rs.novas else "ja_importado"
            except ValueError as e:
                db.rollback()
                reg.situacao, reg.mensagem = "erro", str(e)
            db.add(reg)
            db.commit()
            novos.append(reg)
            continue
        try:
            lidos = extratos_seguradoras.ler(conteudo, nome_leitura)
        except ValueError as e:
            reg.situacao, reg.mensagem = ("ignorado", str(e)) if "não reconhecido" in str(e) else ("erro", str(e))
        except Exception as e:  # noqa: BLE001 - arquivo corrompido não pode parar a varredura
            reg.situacao, reg.mensagem = "erro", f"{type(e).__name__}: {e}"
        else:
            res = comissoes.gravar(db, eid, lidos, arq.name)
            reg.extratos = ", ".join(r.codigo for r in res)[:255]
            if all(r.ja_importado for r in res):
                reg.situacao = "ja_importado"
            avisos = [d for r in res for d in r.divergencias] + [f"{len(r.sem_vinculo)} sem vínculo em {r.codigo}" for r in res if r.sem_vinculo]
            reg.mensagem = "; ".join(avisos)[:2000] or None
            tocadas.add(eid)
        if reg.situacao in ("ignorado", "erro"):
            padrao = padrao_arquivo(arq.name)
            if decisoes.regra(db, eid, "ignorar_arquivo", padrao):
                reg.situacao, reg.mensagem = "ignorado", "ignorado por regra aprendida"
            else:
                decisoes.perguntar(db, eid, "arquivo", padrao, f"Arquivo não reconhecido: {arq.name[:120]}",
                                   reg.mensagem or "Não é um extrato que o sistema conheça.", {"exemplo": arq.name},
                                   [{"id": "ignorar", "rotulo": "Ignorar arquivos assim (não perguntar mais)"},
                                    {"id": "leitor", "rotulo": "É extrato de seguradora: preciso de um leitor novo (vou enviar o arquivo)"}], "ignorar")
        db.add(reg)
        db.commit()
        novos.append(reg)
        log.info("pasta monitorada: %s -> %s", reg.nome, reg.situacao)
    for eid in tocadas:
        previsao.classificar_novos(db, eid)
    return novos


def padrao_arquivo(nome: str) -> str:
    """'boleto_123.pdf' e 'boleto_456.pdf' têm o mesmo padrão: extensão + nome sem números."""
    p = Path(nome)
    base = re.sub(r"[^a-z]+", "_", re.sub(r"\d", "", p.stem.lower())).strip("_")
    return f"{p.suffix.lower()}:{base[:80]}"


def limpar_importados(db: Session, pasta: str | None = None) -> int:
    """Retenção (LGPD, minimização): apaga da pasta os arquivos já importados há mais de N dias."""
    if not (pasta or settings.extratos_pasta):
        return 0
    raiz = Path(pasta or settings.extratos_pasta)
    if not raiz.is_dir() or settings.retencao_arquivos_dias <= 0:
        return 0
    limite = datetime.now(UTC) - timedelta(days=settings.retencao_arquivos_dias)
    feitos = {(a.nome, a.hash) for a in db.scalars(select(ArquivoMonitorado).where(
        ArquivoMonitorado.situacao.in_(("importado", "ja_importado")), ArquivoMonitorado.processado_em < limite))}
    apagados = 0
    for nome, h in feitos:
        arq = raiz / nome
        if arq.is_file() and hashlib.sha256(arq.read_bytes()).hexdigest() == h:
            arq.unlink()
            apagados += 1
    return apagados


def tarefas_diarias() -> None:
    with SessionLocal() as db:
        limpar_importados(db)
        auditoria.limpar_antigos(db)
        bancario.sincronizar_todas(db)


_ultimo_dia: list = [None]


async def vigiar() -> None:
    """Laço em segundo plano (iniciado no lifespan quando EXTRATOS_PASTA está configurada)."""
    while True:
        try:
            def _rodar():
                with SessionLocal() as db:
                    varrer(db)
                    from app.services import alertas

                    alertas.tarefas(db)  # e-mail do dia e fechamento do mês (só manda uma vez)
                if _ultimo_dia[0] != datetime.now().date():
                    _ultimo_dia[0] = datetime.now().date()
                    tarefas_diarias()

            await asyncio.to_thread(_rodar)
        except Exception:  # noqa: BLE001
            log.exception("pasta monitorada: falha na varredura")
        await asyncio.sleep(max(settings.extratos_intervalo_segundos, 10))
