"""Geração de títulos a partir de recorrências (mensal, semanal, anual, parcelada...) com dias úteis bancários."""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AjusteDiaUtil, Frequencia, Recorrencia, Titulo


def _pascoa(ano: int) -> date:
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    mes = (h + l_ - 7 * m + 114) // 31
    dia = (h + l_ - 7 * m + 114) % 31 + 1
    return date(ano, mes, dia)


@lru_cache(maxsize=64)
def feriados_bancarios(ano: int) -> frozenset[date]:
    fixos = [(1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (11, 20), (12, 25)]
    p = _pascoa(ano)
    moveis = [p - timedelta(days=48), p - timedelta(days=47), p - timedelta(days=2), p + timedelta(days=60)]
    return frozenset([date(ano, m, d) for m, d in fixos] + moveis)


def dia_util(d: date) -> bool:
    return d.weekday() < 5 and d not in feriados_bancarios(d.year)


def ajustar(d: date, ajuste: AjusteDiaUtil) -> date:
    if ajuste == AjusteDiaUtil.NENHUM:
        return d
    passo = timedelta(days=-1 if ajuste == AjusteDiaUtil.ANTECIPAR else 1)
    while not dia_util(d):
        d += passo
    return d


def enesimo_dia_util(ano: int, mes: int, n: int) -> date:
    d = date(ano, mes, 1)
    conta = 0
    while True:
        if dia_util(d):
            conta += 1
            if conta == n:
                return d
        d += timedelta(days=1)


def _dia_no_mes(ano: int, mes: int, dia: int) -> date:
    prox = date(ano + mes // 12, mes % 12 + 1, 1)
    return date(ano, mes, min(dia, (prox - timedelta(days=1)).day))


def _somar_meses(ano: int, mes: int, n: int) -> tuple[int, int]:
    t = ano * 12 + mes - 1 + n
    return t // 12, t % 12 + 1


def ocorrencias(r: Recorrencia, ate: date) -> list[tuple[int, date]]:
    """(nº da ocorrência, data nominal antes do ajuste) da recorrência até a data, em ordem."""
    fim = min(ate, r.fim) if r.fim else ate
    saida: list[tuple[int, date]] = []
    if r.frequencia == Frequencia.UNICA:
        return [(1, r.inicio)] if r.inicio <= fim else []
    if r.frequencia in (Frequencia.SEMANAL, Frequencia.QUINZENAL):
        passo = timedelta(days=7 if r.frequencia == Frequencia.SEMANAL else 14)
        d, n = r.inicio, 1
        while d <= fim:
            saida.append((n, d))
            d, n = d + passo, n + 1
        return saida
    intervalo = 12 if r.frequencia == Frequencia.ANUAL else 1
    limite = r.parcelas if r.frequencia == Frequencia.PARCELADA else None
    n, k = 1, 0
    while k < 1200:
        ano, mes = _somar_meses(r.inicio.year, r.inicio.month, k)
        if r.dia_util:
            d = enesimo_dia_util(ano, mes, r.dia_util)
        else:
            d = _dia_no_mes(ano, mes, r.dia or r.inicio.day)
        k += intervalo
        if d < r.inicio:
            continue
        if d > fim or (limite and n > limite):
            break
        saida.append((n, d))
        n += 1
    return saida


def valor_na_data(r: Recorrencia, d: date) -> Decimal:
    if not r.reajuste_pct:
        return r.valor
    mes = r.mes_reajuste or r.inicio.month
    reajustes = sum(1 for ano in range(r.inicio.year, d.year + 1) if r.inicio < date(ano, mes, 1) <= d)
    fator = (1 + Decimal(r.reajuste_pct) / 100) ** reajustes
    return (r.valor * fator).quantize(Decimal("0.01"), ROUND_HALF_UP)


def descricao_na_data(r: Recorrencia, d: date, n: int) -> str:
    ano, mes = _somar_meses(d.year, d.month, -1)
    texto = r.descricao.replace("{COMP}", f"{mes:02d}/{ano}").replace("{MES}", f"{d.month:02d}/{d.year}")
    if r.frequencia == Frequencia.PARCELADA and r.parcelas:
        texto += f" {n}/{r.parcelas}"
    return texto


def gerar(db: Session, entidade_id: int, ate: date, recorrencia_id: int | None = None) -> list[Titulo]:
    """Cria os títulos que faltam até a data. Não duplica: pula a ocorrência que já tem título
    (gerado antes ou lançado à mão com mesma contraparte, descrição e mês)."""
    stmt = select(Recorrencia).where(Recorrencia.entidade_id == entidade_id, Recorrencia.ativa.is_(True))
    if recorrencia_id:
        stmt = stmt.where(Recorrencia.id == recorrencia_id)
    existentes = db.execute(
        select(Titulo.recorrencia_id, Titulo.contraparte_id, Titulo.descricao, Titulo.vencimento).where(
            Titulo.entidade_id == entidade_id
        )
    ).all()
    # semanal/quinzenal: chave pelo dia; demais: pelo mês
    por_rec = {(e.recorrencia_id, e.vencimento.year, e.vencimento.month) for e in existentes if e.recorrencia_id}
    por_rec |= {(e.recorrencia_id, e.vencimento) for e in existentes if e.recorrencia_id}
    por_texto = {
        (e.contraparte_id, e.descricao.strip().upper(), e.vencimento.year, e.vencimento.month) for e in existentes
    }
    novos: list[Titulo] = []
    for r in db.scalars(stmt).all():
        for n, nominal in ocorrencias(r, ate):
            venc = ajustar(nominal, r.ajuste)
            desc = descricao_na_data(r, nominal, n)
            chave = (r.id, venc) if r.frequencia in (Frequencia.SEMANAL, Frequencia.QUINZENAL) else (r.id, venc.year, venc.month)
            if chave in por_rec:
                continue
            if (r.contraparte_id, desc.strip().upper(), venc.year, venc.month) in por_texto:
                continue
            t = Titulo(
                entidade_id=entidade_id,
                tipo=r.tipo,
                descricao=desc,
                contraparte_id=r.contraparte_id,
                categoria_id=r.categoria_id,
                centro_custo_id=r.centro_custo_id,
                competencia=nominal.replace(day=1),
                vencimento=venc,
                valor=valor_na_data(r, nominal),
                natureza=r.natureza,
                recorrencia_id=r.id,
                observacao=f"Gerado pela recorrência {r.codigo or r.id}",
            )
            db.add(t)
            novos.append(t)
            por_rec.add(chave)
            por_texto.add((r.contraparte_id, desc.strip().upper(), venc.year, venc.month))
    db.flush()
    return novos
