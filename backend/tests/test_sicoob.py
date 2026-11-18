"""Formatos reais do Sicoob (CNPJ com espaço, valor na 2ª linha do PDF, nome em coluna de detalhe)."""

import io
from datetime import date, datetime
from decimal import Decimal

from openpyxl import Workbook

from app.services import complemento as c
from tests.test_complemento import pdf_bytes

OFX_SICOOB = """OFXHEADER:100
DATA:OFXSGML
VERSION:102
CHARSET:1252

<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><CURDEF>BRL
<BANKACCTFROM><BANKID>756<BRANCHID>4041-0<ACCTID>25864-4<ACCTTYPE>CHECKING</BANKACCTFROM>
<BANKTRANLIST><DTSTART>20261101<DTEND>20261111
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20261110<TRNAMT>-700.00<FITID>S1
<MEMO>Pagamento Pix 64.927.828 0001-72 PIX EMITIDO OUTRA IF
</STMTTRN>
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20261105<TRNAMT>1500.00<FITID>S2
<MEMO>Recebimento Pix PIX RECEBIDO OUTRA IF
</STMTTRN>
</BANKTRANLIST><LEDGERBAL><BALAMT>800.00<DTASOF>20261111</LEDGERBAL>
</STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
""".encode("cp1252")

PDF = [
    "SICOOB - EXTRATO CONTA CORRENTE",
    "PERIODO: 01/11/2026 A 11/11/2026",
    "DATA HISTORICO VALOR",
    "SALDO ANTERIOR 0,00C",
    "05/11 Pix PIX RECEBIDO OUTRA IF",
    "Recebimento Pix 529.982.247-25 MARIA DA SILVA R$ 1.500,00C",
    "10/11 Pix PIX EMITIDO OUTRA IF",
    "Pagamento Pix 64.927.828 0001-72 HELVIS HONORARIOS R$ 700,00D",
    "SALDO DO DIA 800,00C",
]


def xlsx_sicoob() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["Data", "Tipo", "Histórico", "Descrição", "Valor"])
    ws.append([datetime(2026, 11, 5), "Pix", "PIX RECEBIDO OUTRA IF", "Recebimento Pix 529.982.247-25\nMARIA DA SILVA", "1.500,00"])
    ws.append(["10/11/2026", "Pix", "PIX EMITIDO OUTRA IF", "Pagamento Pix 64.927.828 0001-72\nHELVIS HONORARIOS", "-700,00"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_pdf_sicoob_valor_na_segunda_linha():
    linhas = c.ler_pdf(pdf_bytes(PDF))
    assert [(l.data, l.valor, l.documento, l.nome) for l in linhas] == [
        (date(2026, 11, 5), Decimal("1500.00"), "52998224725", "MARIA DA SILVA"),
        (date(2026, 11, 10), Decimal("700.00"), "64927828000172", "HELVIS HONORARIOS"),
    ]


def test_xlsx_sicoob_nome_na_coluna_de_detalhe():
    linhas = c.ler_xlsx(xlsx_sicoob())
    assert [(l.valor, l.documento, l.nome) for l in linhas] == [
        (Decimal("1500.00"), "52998224725", "MARIA DA SILVA"),
        (Decimal("700.00"), "64927828000172", "HELVIS HONORARIOS"),
    ]


def test_fluxo_sicoob(client, corretora, monkeypatch):
    from app.services.cnpj import ConsultaIndisponivel

    def falha(_):
        raise ConsultaIndisponivel("x")

    monkeypatch.setattr("app.services.contrapartes.consultar", falha)
    eid = corretora["id"]
    r = client.post(
        f"/api/entidades/{eid}/ofx/importar",
        files=[("arquivo", ("sicoob.ofx", OFX_SICOOB, "application/x-ofx"))],
    ).json()
    assert r["com_documento_no_ofx"] == 1  # CNPJ com espaço já é lido do próprio OFX

    # Complementa depois, com PDF e Excel (como no uso real)
    res = client.post(
        f"/api/entidades/{eid}/contas/{r['conta_id']}/complementar",
        files=[
            ("arquivos", ("extrato.pdf", pdf_bytes(PDF), "application/pdf")),
            ("arquivos", ("extrato.xlsx", xlsx_sicoob(), "application/octet-stream")),
        ],
    ).json()
    assert res["erros"] == [] and res["sem_correspondencia"] == 0 and res["linhas_lidas"] == 4

    trns = {t["valor"]: t for t in client.get(f"/api/entidades/{eid}/transacoes").json()}
    assert trns["-700.00"]["contraparte_nome"] == "HELVIS HONORARIOS"
    assert trns["-700.00"]["contraparte_documento"] == "64927828000172"
    assert trns["1500.00"]["contraparte_nome"] == "MARIA DA SILVA"
    cps = {c["documento"]: c["nome"] for c in client.get(f"/api/entidades/{eid}/contrapartes").json()}
    assert cps == {"64927828000172": "HELVIS HONORARIOS", "52998224725": "MARIA DA SILVA"}
