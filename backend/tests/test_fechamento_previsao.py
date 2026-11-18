import io
from datetime import date
from decimal import Decimal

from openpyxl import Workbook

from app.services import fechamento

CAB = ["Data de e-mail", "Vigência Inicial", "Vigência Final", "Tipo", "Seguradora", "Ramo", "Descrição", "Cliente",
       "Produtor", "Origem ", "Prêmio Líquido", "Comissão", "Com. Bruta", "Imposto", "Com. Corretora", "Parceiro(a)", "Emissão"]


def _fechamento() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "OUT"
    ws.append(["FECHAMENTO DE PROPOSTAS - OUTUBRO 2026"])
    ws.append([])
    ws.append(CAB)
    ws.append(["01/10/2026", "01/10/2026", "01/10/2027", "Seguro Novo", "SULAMERICA", "Saúde PME", "PME 3 VIDAS",
               "EMPRESA NOVA LTDA", "Giovanna", "Kette", "R$ 1.000,00", "100%", "R$ 1.000,00", "", "", "", "EMITIDA"])
    ws.append(["01/10/2026", "01/10/2026", "01/10/2027", "Renovação", "SA SAÚDE", "Saúde PME", "PME", "EMPRESA ANTIGA LTDA",
               "Fabiana C.", "Kette", "", "", "R$ 50,00", "", "", "TRUST", "EMITIDA"])
    ws.append(["02/10/2026", "02/10/2026", "02/10/2027", "Seguro Novo", "AZUL", "Automóvel", "ABC1234", "CLIENTE AUTO",
               "Fabianny A.", "Fabianny A.", "R$ 2.000,00", "15%", "R$ 300,00", "", "", "", "EMITIDA"])
    ws.append(["03/10/2026", "", "", "Seguro Novo", "PORTO", "Residencial", "", "CANCELADO SILVA", "Giovanna", "Kette",
               "", "", "R$ 90,00", "", "", "", "CANCELADA"])
    mai = wb.create_sheet("MAI")  # em MAI o parceiro está numa 2ª coluna "Origem"
    mai.append(["FECHAMENTO DE PROPOSTAS - MAIO 2026"])
    mai.append([])
    mai.append(["Data de e-mail", "Tipo", "Seguradora", "Ramo", "Cliente", "Produtor", "Origem ", "Com. Bruta", "Origem"])
    mai.append(["28/04/2026", "Seguro Novo", "YOUSE", "Automóvel", "TATIANE TESTE", "Giovanna", "Kette", "R$ 377,00", "TRUST "])
    wb.create_sheet("RESUMO").append(["ignorada"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_le_abas_e_normaliza():
    lt = fechamento.ler_xlsx(_fechamento())
    assert lt.abas == ["OUT (4)", "MAI (1)"]
    p = {l["cliente"]: l for l in lt.linhas}
    assert p["EMPRESA ANTIGA LTDA"]["seguradora"] == "SULAMERICA" and p["EMPRESA ANTIGA LTDA"]["produtor"] == "FABIANA"
    assert p["CLIENTE AUTO"]["seguradora"] == "PORTO" and p["CLIENTE AUTO"]["produtor"] == "FABI ANJOS"
    assert p["EMPRESA NOVA LTDA"]["tipo"] == "Seguro Novo" and p["EMPRESA NOVA LTDA"]["com_bruta"] == Decimal("1000.00")
    assert (p["EMPRESA NOVA LTDA"]["ano"], p["EMPRESA NOVA LTDA"]["mes"]) == (2026, 10)
    assert p["TATIANE TESTE"]["parceiro"] == "TRUST" and p["TATIANE TESTE"]["data_email"] == date(2026, 4, 28)
    assert fechamento.extrair_id("https://docs.google.com/spreadsheets/d/1dpyMeb7WDX2z4gviDa_6uiKb1m4i-VDuSRRz7SNnAus/edit#gid=0") \
        == "1dpyMeb7WDX2z4gviDa_6uiKb1m4i-VDuSRRz7SNnAus"


def _sulamerica(nr, data, itens):
    """TXT de largura fixa da SulAmérica: uma linha por item (nome, apólice, parcela, valor)."""
    linhas = []
    total = f"{sum(i[3] for i in itens):.2f}".replace(".", ",")
    vals = ["0,00", "0,00", "0,00", total, "0,00", "0,00", "0,00", total, "0,00", total, total]
    for seq, (nome, apol, parc, valor) in enumerate(itens, 1):
        tot = f"{valor:.2f}".replace(".", ",")
        linhas.append(
            f" {nr}  29456909512J029886115000107202015671     ATUAL PREV CORRETORA DE SEGUROS EIRELI  "
            f"22/10/2026{data}SUL AMERICA COMPANHIA DE SEGURO SAUDE    407BRASILIA                 7564041000000000 0"
            + "".join(f"{v:>15}" for v in vals)
            + f"   {seq}{nome:<40}19804 728PME                      {apol}   540606 1248R0V1   0        0280006/11/2026"
            f"   {parc}   1   1   1       3.998,22     2     0  {tot:>13}  12  2945738        0 "
        )
    return "\n".join(linhas).encode("cp1252")


def test_sulamerica_novo_so_quando_fechamento_diz_seguro_novo(client, corretora):
    eid = corretora["id"]
    imp = lambda nome, conteudo: client.post(  # noqa: E731
        f"/api/entidades/{eid}/extratos-comissao/importar", files=[("arquivos", (nome, conteudo))]
    ).json()
    # histórico: EMPRESA ANTIGA já recebia em julho e agosto (parcela 1 todo mês)
    for i, mes in enumerate(("07", "08", "09")):
        r = imp(f"s{i}.txt", _sulamerica(f"3600000{i}", f"05/{mes}/2026", [("EMPRESA ANTIGA LTDA", "304494600", 1, 50)]))
        assert r[0]["gravadas"] == 1, r
    st = client.post(f"/api/entidades/{eid}/fechamento/importar", files={"arquivo": ("f.xlsx", _fechamento())}).json()
    assert st["propostas"] == 5
    r = imp("out.txt", _sulamerica("36700001", "05/10/2026", [("EMPRESA ANTIGA LTDA", "304494600", 1, 50),
                                                               ("EMPRESA NOVA LTDA", "309999999", 1, 200)]))
    assert r[0]["gravadas"] == 2 and not r[0]["divergencias"], r
    out = {c["cliente"]: c for c in client.get(f"/api/entidades/{eid}/comissoes?mes=2026-10").json()}
    nova, antiga = out["EMPRESA NOVA LTDA"], out["EMPRESA ANTIGA LTDA"]
    assert nova["novo_negocio"] is True and antiga["novo_negocio"] is False  # as duas vêm com "parcela 1"
    assert (nova["origem"], nova["produtor"]) == ("KETTE", "GIOVANNA")  # vínculo pelo FECHAMENTO
    cmp = client.get(f"/api/entidades/{eid}/comissoes/comparativo?mes=2026-10").json()
    assert cmp["novos_qtd"] == 1 and Decimal(cmp["novos_valor"]) == 200

    prev = client.get(f"/api/entidades/{eid}/comissoes/previsao?meses=3&hoje=2026-11-10").json()
    rec = [i for i in prev["itens"] if i["tipo"] == "recorrente" and i["cliente"] == "EMPRESA ANTIGA LTDA"]
    assert [i["mes"] for i in rec] == ["2026-11", "2026-12", "2027-01"] and Decimal(rec[0]["valor"]) == 50
    props = {i["cliente"] for i in prev["itens"] if i["tipo"] == "proposta"}
    assert props == {"CLIENTE AUTO"}  # sem comissão ainda; a cancelada e as já recebidas ficam de fora
    nov = prev["meses"][0]
    assert Decimal(nov["propostas"]) == 300 and Decimal(nov["recorrentes"]) >= 50


def test_previsao_de_parcelas_restantes(client, corretora):
    eid = corretora["id"]
    sura = """Extrato de Comissão
Nº170/2026 R$ 0,00 03/10/2026
Nome do cliente Ramo Apólice
29/09/2026 FULANA DA SILVA 710 - RD 7100024627 0 2/6 R$ 80,53 20,0% R$ 16,11
Total das comissões R$ 16,11
Saldo anterior R$ 0,00
Valor bruto das comissões R$ 16,11
Valor líquido das comissões R$ 16,11"""
    from app.db import get_db
    from app.main import app
    from app.services import comissoes
    from app.services.extratos_seguradoras import ler_sura as leitor

    # grava direto pelo serviço (o texto viria de PDF)
    db = next(app.dependency_overrides[get_db]())
    comissoes.gravar(db, eid, leitor(sura), "sura.pdf")
    prev = client.get(f"/api/entidades/{eid}/comissoes/previsao?meses=6&hoje=2026-11-10").json()
    parc = [i for i in prev["itens"] if i["tipo"] == "parcela"]
    assert [(i["mes"], i["detalhe"]) for i in parc] == [
        ("2026-11", "parcela 3/6"), ("2026-12", "parcela 4/6"), ("2027-01", "parcela 5/6"), ("2027-02", "parcela 6/6")]
    assert prev["atrasados"] == []  # última (2/6) chegou em outubro: a 3/6 é esperada em novembro
    atrasada = client.get(f"/api/entidades/{eid}/comissoes/previsao?meses=1&hoje=2027-01-10").json()
    assert [a["cliente"] for a in atrasada["atrasados"]] == ["FULANA DA SILVA"]


class _Resp:
    def __init__(self, status, content=b"", js=None):
        self.status_code, self.content, self._js = status, content, js

    def json(self):
        return self._js

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError("erro", request=None, response=None)


def test_sincroniza_do_google(client, corretora, monkeypatch, tmp_path):
    import json

    import httpx
    import jwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from app.config import settings

    eid = corretora["id"]
    url = "https://docs.google.com/spreadsheets/d/1dpyMeb7WDX2z4gviDa_6uiKb1m4i-VDuSRRz7SNnAus/edit"
    assert client.put(f"/api/entidades/{eid}/fechamento", json={"planilha": url}).json()["planilha_id"] == \
        "1dpyMeb7WDX2z4gviDa_6uiKb1m4i-VDuSRRz7SNnAus"

    # 1) link público: planilha não compartilhada devolve a página de login
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp(200, b"<html>login</html>"))
    r = client.post(f"/api/entidades/{eid}/fechamento/sincronizar")
    assert r.status_code == 422 and "conta de serviço" in r.json()["detail"]

    # 2) conta de serviço: troca o JWT por token e exporta pelo Drive
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = chave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    arq = tmp_path / "sa.json"
    arq.write_text(json.dumps({"client_email": "finbpo@projeto.iam.gserviceaccount.com", "private_key": pem}))
    monkeypatch.setattr(settings, "google_service_account_file", str(arq))
    vistos = {}

    def post(url, data, timeout):
        vistos["assertion"] = jwt.decode(data["assertion"], chave.public_key(), algorithms=["RS256"],
                                         audience="https://oauth2.googleapis.com/token")
        return _Resp(200, js={"access_token": "tok"})

    def get(url, params=None, headers=None, **k):
        vistos["get"] = (url, params, headers)
        return _Resp(200, _fechamento())

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(httpx, "get", get)
    st = client.post(f"/api/entidades/{eid}/fechamento/sincronizar").json()
    assert st["propostas"] == 5 and st["conta_servico"] and st["sincronizado_em"]
    assert vistos["assertion"]["scope"].endswith("drive.readonly")
    assert vistos["get"][0].endswith("/files/1dpyMeb7WDX2z4gviDa_6uiKb1m4i-VDuSRRz7SNnAus/export")
    assert vistos["get"][2] == {"Authorization": "Bearer tok"}
