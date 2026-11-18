"""Leitores de extrato de seguradora, com arquivos fictícios no mesmo formato dos reais."""

import io
from decimal import Decimal

from openpyxl import Workbook

from app.services.extratos_seguradoras import ler, ler_akad, ler_allianz, ler_sura

PORTO = """<html><body><table>
<tr><td>Anal\xedtico dos Pagamentos de Comiss\xf5es</td></tr>
<tr><td>Ordem de Pagamento:</td><td>123</td><td>Data de Pagamento:</td><td>17/11/2026</td></tr>
<tr><td>Empresa: </td><td>PORTO SEGURO CIA DE SEGUROS GERAIS</td></tr>
<tr><td>Susep Favorecida:</td><td>1730ZJ&nbsp;-&nbsp;CORRETORA</td></tr>
<tr><td>FULANO DE TAL</td><td>Porto</td><td>11</td><td>531</td><td>111222</td><td>9</td><td>3</td><td>0</td>
<td>2026-11-04</td><td>1.000,00</td><td>10,00</td><td>100,00</td><td>45 - COMISSAO FRACIONADA</td></tr>
<tr><td>FULANO DE TAL</td><td>Porto</td><td>11</td><td>531</td><td>111222</td><td>9</td><td>3</td><td>0</td>
<td>2026-11-04</td><td>200,00</td><td>10,00</td><td>20,00</td><td>45 - COMISSAO FRACIONADA</td></tr>
<tr><td>CICLANO SILVA - (017) X</td><td>Porto</td><td>11</td><td>114</td><td>333444</td><td>0</td><td>2</td><td>0</td>
<td>2026-11-05</td><td>-500,00</td><td>10,00</td><td>-50,00</td><td>72 - CANCELAMENTO DA APOLICE</td></tr>
<tr><td>DEBITO PORTOSEG CTO: 1 PARCELA:1/36</td><td></td><td></td><td>-30,00</td><td>99 - DEBITO</td></tr>
<tr><td>Comiss\xe3o Bruta</td><td>INSS</td><td>IRRF</td><td>ISS</td><td>L\xedquido</td><td>D\xe9bito/Cr\xe9dito</td><td>A pagar</td></tr>
<tr><td>70,00</td><td>0,00</td><td>0,00</td><td>2,78</td><td>67,22</td><td>-30,00</td><td>37,22</td></tr>
</table></body></html>"""

CAMPOS_BRADESCO = 95


def _linha_bradesco(fatura, apolice, nome, parcela, valor):
    f = [""] * CAMPOS_BRADESCO
    f[0], f[1], f[15] = "09/11/2026", fatura, "SAÚDE"
    f[16], f[18], f[29], f[30], f[31], f[44] = "150,00", "0,00", "150,00", "-", "-", "-"
    f[48], f[52], f[53] = "0,00", "5,95", "144,05"
    f[67], f[69], f[70], f[71], f[74] = apolice, "00876", nome, parcela, valor
    return ";".join(f)


def test_porto_html_cp1252():
    [e] = ler(PORTO.encode("cp1252"), "PORTO.do")
    assert (e.codigo, e.documento, e.bruto, e.iss, e.liquido, e.debitos) == (
        "PORTO-123", "ORDEM 123 AUTO/RE", Decimal("70.00"), Decimal("2.78"), Decimal("67.22"), Decimal("-30.00")
    )
    assert not e.divergencias
    g = {x.cliente: x for x in e.grupos}
    assert g["FULANO DE TAL"].bruta == Decimal("120.00") and g["FULANO DE TAL"].ramo == "AUTO"  # coberturas somadas
    assert g["CICLANO SILVA"].bruta == Decimal("-50.00") and g["CICLANO SILVA"].ramo == "RE"
    assert g["CICLANO SILVA"].obs == "72-CANCELAMENTO DA APOLICE"
    assert g["DEBITO PORTOSEG CTO: 1 PARCELA:1/36"].debito


def test_bradesco_uma_linha_por_beneficiario():
    txt = "Data Pagamento;Fatura;" + ";".join(["x"] * 93) + "\n"
    txt += _linha_bradesco("777", "00099911", "MARIA SOUZA     00", "12", "R$ 100,00") + "\n"
    txt += _linha_bradesco("777", "00099911", "JOAO SOUZA      01", "12", "R$ 50,00") + "\n"
    [e] = ler(txt.encode("utf-8-sig"), "b.txt")
    assert e.codigo == "BRADESCO-777" and e.bruto == Decimal("150.00") and e.iss == Decimal("5.95")
    assert sorted(g.cliente for g in e.grupos) == ["JOAO SOUZA", "MARIA SOUZA"]
    assert all(g.apolice == "99911" and g.ramo == "SAUDE" for g in e.grupos)


def test_odontoprev_agrupa_por_contrato():
    cab = "NCO_CPF_CGC;" + ";".join(f"C{i}" for i in range(1, 40)) + ";NSE_TOT_COMISSAO"
    def linha(apol, nome, prest, valor):
        f = ["0"] * 41
        f[5], f[7], f[10], f[14], f[17], f[23], f[24], f[25], f[30] = "20261106", apol, prest, valor, nome, "0.00", "0.00", "10.00", "30.00"
        return ";".join(f)
    txt = "\n".join([cab, linha("555", "ANA", "1", "10.00"), linha("555", "BIA", "1", "10.00"), linha("555", "ANA", "2", "10.00")])
    [e] = ler(txt.encode(), "o.txt")
    assert e.codigo == "ODONTOPREV-06112026" and e.bruto == Decimal("30.00")
    [g] = e.grupos
    assert g.cliente == "ANA" and g.ramo == "ODONTO" and g.origem_fixa == "KETTE"


def test_mag_csv_e_azos_xlsx():
    cab = ["CPF/CNPJ do Produtor", "Código do produtor", "Tipo de cliente", "Nome/Razão social", "x", "Proposta"] + [
        f"c{i}" for i in range(6, 11)] + ["Parcela comissionada"] + [f"d{i}" for i in range(12, 18)] + [
        "Data de efetivação do crédito/débito", "Valor Angariação", "% a", "Valor Comissão", "% c", "Valor estorno"]
    def linha(prop, nome, parc, com):
        f = [""] * len(cab)
        f[3], f[5], f[11], f[18], f[21] = nome, prop, parc, "30/10/2026", com
        return ";".join(f)
    csv = "\n".join([";".join(cab), "\t" + linha("60940", "EMPRESA X", "13", "10,00"), "\t" + linha("60940", "EMPRESA X", "13", "5,50")])
    [e] = ler(csv.encode("utf-8-sig"), "MAG.csv")
    assert e.codigo == "MAG-30102026" and e.bruto == Decimal("15.50") and len(e.grupos) == 1

    wb = Workbook()
    ws = wb.active
    ws.append(["Azos"])
    ws.append(["Nome do Segurado", "CPF do Segurado", "ID", "Nº da Apólice", "Coberturas", "Mês", "Parcela",
               "Pagamento Segurado", "Pagamento Comissão", "Valor da Fatura", "Comissão Bruta"])
    ws.append(["Heitor Teste", "1", "x", "0569 0001", "Vida", "11/2026", 5, "27/10/2026", "03/11/2026", 175.98, 43.83])
    ws.append(["Total Comissão Bruta no Período", None, None, None, None, None, None, None, None, None, 43.83])
    buf = io.BytesIO()
    wb.save(buf)
    [a] = ler(buf.getvalue(), "AZOS.xlsx")
    assert a.codigo == "AZOS-03112026" and a.bruto == Decimal("43.83") and a.grupos[0].apolice == "05690001"
    assert not a.divergencias


def test_pdfs_sura_akad_allianz_texto():
    sura = """Extrato de Comissão
Nº167/2026 R$ 0,00 03/11/2026
Nome do cliente Ramo Apólice
29/10/2026 FULANA DA SILVA 710 - RD 7100024627 0 2/6 R$ 5,28 20,0% R$ 1,06
29/10/2026 FULANA DA SILVA 710 - RD 7100024627 0 2/6 R$ 80,53 20,0% R$ 16,11
Total das comissões R$ 17,17
ISS (-) -R$ 0,50
Saldo anterior R$ 0,00
Valor bruto das comissões R$ 17,17
Valor líquido das comissões R$ 16,67"""
    [s] = ler_sura(sura)
    assert s.codigo == "SURA-167-2026" and str(s.data) == "2026-11-04"  # 1 dia útil depois
    assert (s.bruto, s.iss, s.liquido) == (Decimal("17.17"), Decimal("0.50"), Decimal("16.67"))
    assert s.grupos[0].ramo == "RE" and s.grupos[0].parcela_txt == "2/6" and not s.divergencias

    akad = """Extrato de Pagamento de Comissão
N: C841.837 - Data do Pagamento 04/11/2026
Tipo de Comissão: CB-Comissão de Corretagem
02798 2026 02 0378 001486 000000 02 10 EMPRESA DEPILACAO CB 30/10/2026 146,39 BRL 1,0000 146,39 20,000 29,28
LTDA
Total Bruto em R$: 29,28
I.S.S.: 0,00
Líquido em R$: 29,28"""
    [k] = ler_akad(akad)
    assert k.codigo == "AKAD-04112026" and k.grupos[0].cliente == "EMPRESA DEPILACAO LTDA" and k.grupos[0].apolice == "1486"

    allianz = """Allianz EXTRATO DE COMISSÕES PAGAS POR SUSEP
Total Bruto: 34.43 Total IR:0.00 Total INSS: 0.00 Total ISS: 1.37 Total Descontos: 0.00 Total Líquido: 33.06
Data Pagto. CNPJ Filial Bruto
03/11/2026 61.573.796/0018-04 34.43
30/10/2026 4023893 5177202675312276030 141120308 481954332 2/10 ATUAL PREV CORRETORA DE SEGUROS EIRELI FULANO A 1211 - Automóvel 244.2 10% 0.02 S
31/10/2026 4023893 5177202675140366619 140068195 414163514 4/12 ATUAL PREV CORRETORA DE SEGUROS EIRELI BELTRANO B 2013 - Residencia digital 57.33 30% 34.41 S"""
    [z] = ler_allianz(allianz)
    assert z.codigo == "ALLIANZ-03112026" and z.iss == Decimal("1.37") and not z.divergencias
    assert [(g.ramo, g.parcela_txt) for g in z.grupos] == [("AUTO", "02/10"), ("RE", "04/12")]


def test_importa_com_vinculo_do_historico_e_nao_duplica(client, corretora):
    eid = corretora["id"]
    # histórico na BASE: CLIENTE B (PORTO, SAÚDE, origem ISADORA)
    from tests.test_planilha import _planilha  # planilha mínima com BASE
    client.post(f"/api/entidades/{eid}/importar-planilha", files={"arquivo": ("p.xlsx", _planilha())})
    html = PORTO.replace("FULANO DE TAL", "CLIENTE B")
    arq = [("arquivos", ("PORTO.do", html.encode("cp1252"))), ("arquivos", ("x.txt", b"qualquer coisa"))]
    r = client.post(f"/api/entidades/{eid}/extratos-comissao/importar", files=arq).json()
    assert r[0]["codigo"] == "PORTO-123" and r[0]["gravadas"] == 3
    assert r[0]["sem_vinculo"] == ["CICLANO SILVA (333444)"]
    assert "não reconhecido" in r[1]["erro"]
    linhas = {c["cliente"]: c for c in client.get(f"/api/entidades/{eid}/comissoes?mes=2026-11").json()}
    a = linhas["CLIENTE B"]
    assert (a["origem"], a["produtor"], a["parcela_texto"]) == ("ISADORA", None, "3")
    assert a["observacao"].startswith("VERIFICAR VÍNCULO: nome existe em outro ramo")
    assert Decimal(a["imposto"]) == Decimal("10.44")  # 8,7% de 120,00
    assert linhas["CICLANO SILVA"]["observacao"].startswith("VERIFICAR: SEM VÍNCULO")
    assert Decimal(linhas["CICLANO SILVA"]["imposto"]) == 0
    deb = linhas["DEBITO PORTOSEG CTO: 1 PARCELA:1/36"]
    assert deb["origem"] == "KETTE" and deb["ramo"] == "DEBITO"
    de_novo = client.post(f"/api/entidades/{eid}/extratos-comissao/importar", files=arq[:1]).json()
    assert de_novo[0]["ja_importado"] and de_novo[0]["gravadas"] == 0
