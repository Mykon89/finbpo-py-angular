import io
from datetime import date, datetime
from decimal import Decimal

from openpyxl import Workbook

from app.models import AjusteDiaUtil, Frequencia, Recorrencia
from app.services.recorrencias import ajustar, descricao_na_data, enesimo_dia_util, feriados_bancarios, ocorrencias, valor_na_data

MENU = ["☰ MENU", "RECEBER", "PAGAR"]


def _planilha() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "PAGAR"
    ws.append(MENU)
    ws.append(["ID", "VENCIMENTO", "FORNECEDOR", "DESCRIÇÃO", "CATEGORIA", "CENTRO DE CUSTO", "PREVISTO", "PAGO",
               "DATA PAGTO", "SITUAÇÃO", "ORIGEM", "REGRA", "VÍNCULO BANCO (id:centavos)", "NATUREZA"])
    ws.append(["M0001", datetime(2026, 11, 5, 9), "CONDOMINIO X", "TX COND 11/2026", "Condomínio", "ADMINISTRATIVO",
               434.65, 391.19, datetime(2026, 11, 5, 9), "PAGO C/ DESCONTO", "MIGRADO CA", None, None, "FIXA"])
    ws.append(["M0002", datetime(2026, 11, 20, 9), "MINISTERIO DA FAZENDA", "DAS 10/2026", "Simples Nacional - DAS",
               None, 4472.93, None, None, "PREVISTO", "MIGRADO CA", None, None, "VARIÁVEL"])
    ws.append(["M0003", datetime(2026, 11, 2, 9), "FULANO", "COMISSÃO 10/2026", "Comissões de Vendedores",
               "ORIGEM KETTE", 100, 110, datetime(2026, 11, 3), "PAGO", "BANCO", None, None, "VARIÁVEL"])
    ws = wb.create_sheet("RECORRÊNCIAS")
    ws.append(MENU)
    ws.append(["ID", "ATIVA", "TIPO", "FORNECEDOR / CLIENTE", "DESCRIÇÃO", "CATEGORIA", "CENTRO DE CUSTO", "VALOR",
               "FONTE DO VALOR", "FREQUÊNCIA", "DIA / DATA", "INÍCIO", "FIM", "PARCELAS", "REAJUSTE % ANUAL",
               "MÊS DO REAJUSTE", "NATUREZA"])
    ws.append(["R001", True, "PAGAR", "TOKIO MARINE", "FIANÇA {MES}", "Seguro de Imóveis", None, 249.52, "FIXO",
               "MENSAL", 30, datetime(2026, 11, 28), None, None, None, None, "FIXA"])
    ws.append([None, False])
    ws = wb.create_sheet("REGRAS_BANCO")
    ws.append(["PADRÃO (CNPJ / nome / documento)", "FORNECEDOR", "CATEGORIA", "CRIAR CAP AUTOMÁTICO (SIM)", "DESCRIÇÃO PADRÃO"])
    ws.append(["CNPJ07522669000192", "NEOENERGIA BRASILIA", "Energia Elétrica"])
    ws.append(["ESTACIONAMENTO KETTE", "EMPLAVI", "Estacionamento"])
    ws = wb.create_sheet("RECEBER")
    ws.append(MENU)
    ws.append(["EXTRATO", "SEG", "DT EXT", "DOC", "LINHAS", "BRUTO", "ISS", "LÍQUIDO", "DÉBITOS", "RECEBIDO",
               "IMPORTADO EM", "ISS EXPORTADO", "RECEBER EXPORTADO", "RECEBIDO NO BANCO", "DT BANCO", "SITUAÇÃO"])
    ws.append(["SURA-157-2026", "SURA", datetime(2026, 10, 1), "PAGTO", 2, 300, 26.1, 273.9, None, None, None, None,
               None, 273.9, datetime(2026, 10, 1, 12), "RECEBIDO"])
    ws = wb.create_sheet("BASE")
    ws.append(MENU)
    ws.append(["DT EXTRATO", "PROPOSTA/APÓLICE", "SEG", "RAMO", "CLIENTE", "C. BRUTA", "IMP", "C. LÍQUIDA", "ORIGEM",
               "PRODUTOR", "PARCEIRO", "OBS", "PARCELA", "DESCRIÇÃO CONTA AZUL", "EXTRATO"])
    ws.append([datetime(2026, 10, 1), "751850", "SURA", "AUTO", "CLIENTE A", 200, 17.4, 182.6, "KETTE", "GIOVANNA",
               None, None, 1, None, "SURA-157-2026"])
    ws.append([datetime(2026, 10, 1), "751850", "SURA", "AUTO", "CLIENTE A", 200, 17.4, 182.6, "KETTE", "-----",
               None, None, 2, None, "SURA-157-2026"])  # linha idêntica (outra parcela) não pode ser descartada
    ws.append([datetime(2026, 9, 10), None, "PORTO", "SAÚDE", "CLIENTE B", 50, 4.35, 45.65, "ISADORA", None, None])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _importar(client, eid):
    return client.post(f"/api/entidades/{eid}/importar-planilha", files={"arquivo": ("p.xlsx", _planilha())})


def test_importa_planilha_sem_duplicar(client, corretora):
    eid = corretora["id"]
    r = _importar(client, eid)
    assert r.status_code == 200, r.text
    j = r.json()
    assert (j["contas_pagar"], j["contas_pagas"], j["recorrencias"], j["regras"], j["comissoes"]) == (3, 2, 1, 2, 3)
    assert j["extratos"] == 1
    again = _importar(client, eid).json()
    assert (again["contas_pagar"], again["recorrencias"], again["regras"], again["comissoes"]) == (0, 0, 0, 0)

    titulos = {t["descricao"]: t for t in client.get(f"/api/entidades/{eid}/titulos?tipo=pagar").json()}
    cond = titulos["TX COND 11/2026"]
    assert cond["status"] == "pago" and Decimal(cond["desconto"]) == Decimal("43.46") and Decimal(cond["saldo"]) == 0
    com = titulos["COMISSÃO 10/2026"]
    assert com["status"] == "pago" and Decimal(com["valor"]) == Decimal("110")  # pago com acréscimo
    assert titulos["DAS 10/2026"]["status"] == "aberto"

    cats = {c["nome"]: c["grupo_dre"] for c in client.get(f"/api/entidades/{eid}/categorias").json()}
    assert cats["Simples Nacional - DAS"] == "deducoes"
    assert cats["Comissões de Vendedores"] == "custos"

    regras = client.get(f"/api/entidades/{eid}/regras").json()
    assert any(r["contraparte_id"] for r in regras) and any(r["padrao"] == "ESTACIONAMENTO KETTE" for r in regras)

    com = client.get(f"/api/entidades/{eid}/comissoes?mes=2026-10").json()
    assert len(com) == 2 and com[1]["produtor"] is None
    ext = client.get(f"/api/entidades/{eid}/extratos-comissao").json()
    assert ext[0]["linhas"] == 2 and ext[0]["situacao"] == "RECEBIDO"

    cmp = client.get(f"/api/entidades/{eid}/comissoes/comparativo?mes=2026-10").json()
    assert cmp["anterior"] == "2026-09" and Decimal(cmp["total_atual"]) == 400 and Decimal(cmp["total_anterior"]) == 50
    ramos = {x["chave"]: x for x in cmp["por_ramo"]}
    assert Decimal(ramos["AUTO"]["atual"]) == 400 and Decimal(ramos["SAUDE"]["anterior"]) == 50
    assert cmp["novos_qtd"] == 1 and cmp["sem_vinculo"] == 1


def test_painel_e_geracao_de_recorrencias(client, corretora):
    eid = corretora["id"]
    _importar(client, eid)
    p = client.get(f"/api/entidades/{eid}/painel-pagar?hoje=2026-11-18").json()
    assert Decimal(p["aberto_ate_fim_mes"]) == Decimal("4472.93")
    assert Decimal(p["pago_no_mes"]) == Decimal("501.19")

    gerados = client.post(f"/api/entidades/{eid}/recorrencias/gerar?ate=2027-01-31").json()
    assert [(g["descricao"], g["vencimento"]) for g in gerados] == [
        ("FIANÇA 11/2026", "2026-11-30"),
        ("FIANÇA 12/2026", "2026-12-30"),
        ("FIANÇA 01/2027", "2027-01-30"),
    ]
    assert client.post(f"/api/entidades/{eid}/recorrencias/gerar?ate=2027-01-31").json() == []

    r = client.post(
        f"/api/entidades/{eid}/recorrencias",
        json={"descricao": "PRO-LABORE {COMP}", "valor": 1780, "frequencia": "mensal", "dia_util": 5,
              "inicio": "2026-12-01", "fim": "2027-01-31", "contraparte_nome": "Kette"},
    )
    assert r.status_code == 201 and r.json()["codigo"] == "R002" and r.json()["contraparte_nome"] == "KETTE"
    novos = client.post(f"/api/entidades/{eid}/recorrencias/gerar?ate=2027-02-28&recorrencia_id={r.json()['id']}").json()
    assert [(g["descricao"], g["vencimento"]) for g in novos] == [
        ("PRO-LABORE 11/2026", "2026-12-07"),
        ("PRO-LABORE 12/2026", "2027-01-08"),
    ]


def _rec(**kw) -> Recorrencia:
    base = dict(descricao="X", valor=Decimal("100"), frequencia=Frequencia.MENSAL, inicio=date(2026, 1, 31),
                ajuste=AjusteDiaUtil.NENHUM, dia=None, dia_util=None, fim=None, parcelas=None,
                reajuste_pct=None, mes_reajuste=None)
    base.update(kw)
    return Recorrencia(**base)


def test_regras_de_datas():
    assert date(2026, 2, 16) in feriados_bancarios(2026)  # carnaval
    assert date(2026, 4, 3) in feriados_bancarios(2026)  # sexta-feira santa
    assert ajustar(date(2026, 11, 15), AjusteDiaUtil.POSTERGAR) == date(2026, 11, 16)
    assert ajustar(date(2026, 11, 22), AjusteDiaUtil.ANTECIPAR) == date(2026, 11, 19)  # 20/11 é feriado
    assert enesimo_dia_util(2026, 1, 1) == date(2026, 1, 2)
    datas = [d for _, d in ocorrencias(_rec(), date(2026, 4, 30))]
    assert datas == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]
    parc = _rec(frequencia=Frequencia.PARCELADA, parcelas=3, descricao="EMPRÉSTIMO")
    occ = ocorrencias(parc, date(2027, 1, 1))
    assert len(occ) == 3 and descricao_na_data(parc, occ[2][1], occ[2][0]) == "EMPRÉSTIMO 3/3"
    anual = _rec(frequencia=Frequencia.ANUAL, inicio=date(2026, 9, 15))
    assert [d for _, d in ocorrencias(anual, date(2028, 12, 31))] == [date(2026, 9, 15), date(2027, 9, 15), date(2028, 9, 15)]
    sem = _rec(frequencia=Frequencia.SEMANAL, inicio=date(2026, 11, 2))
    assert len(ocorrencias(sem, date(2026, 11, 30))) == 5
    reaj = _rec(reajuste_pct=Decimal("10"), mes_reajuste=1, inicio=date(2026, 6, 10))
    assert valor_na_data(reaj, date(2026, 12, 10)) == Decimal("100") and valor_na_data(reaj, date(2027, 2, 10)) == Decimal("110.00")
