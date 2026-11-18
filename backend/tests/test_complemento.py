import io
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.services import complemento as c
from app.services.cnpj import ConsultaIndisponivel

OFX = Path(__file__).parent / "fixtures" / "itau_sgml.ofx"
CNPJ = "11.222.333/0001-81"
CPF = "529.982.247-25"


def xlsx_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["Extrato de conta corrente"])
    ws.append(["Agência 1234 Conta 56789-0"])
    ws.append(["Data", "Lançamento", "Nome", "CPF/CNPJ", "Valor (R$)", "Saldo (R$)"])
    ws.append([datetime(2026, 9, 30), "SALDO ANTERIOR", None, None, None, 0])
    ws.append([datetime(2026, 10, 5), "TED RECEBIDA", "SEGURADORA EXEMPLO SA", CNPJ, 4500.00, 4500])
    ws.append(["10/10/2026", "PAG BOLETO", "IMOBILIARIA FULANO", CPF, "-1.200,00", 3300])
    ws.append([datetime(2026, 10, 15), "TARIFA PACOTE SERVIÇOS", None, None, -39.90, 3260.10])
    ws.append([datetime(2026, 10, 15), "TARIFA PACOTE SERVIÇOS", None, None, -39.90, 3220.20])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def pdf_bytes(linhas: list[str]) -> bytes:
    """PDF mínimo com uma linha de texto por linha (sem dependências extras)."""
    ops = ["BT", "/F1 10 Tf", "14 TL", "40 800 Td"]
    for l in linhas:
        ops.append("(" + l.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") Tj T*")
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + o + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (len(objs) + 1, xref))
    return out.getvalue()


PDF_LINHAS = [
    "EXTRATO CONTA CORRENTE - PERIODO 01/10/2026 A 31/10/2026",
    "DATA HISTORICO VALOR SALDO",
    "05/10 TED RECEBIDA 4.500,00 4.500,00",
    "SEGURADORA EXEMPLO SA 11.222.333/0001-81",
    "10/10 PAG BOLETO ALUGUEL 1.200,00- 3.300,00",
    "IMOBILIARIA FULANO CPF 529.982.247-25",
    "15/10 TARIFA PACOTE 39,90-",
    "15/10 TARIFA PACOTE 39,90- 3.220,20",
    "SALDO DO DIA 3.220,20",
]


@pytest.fixture(autouse=True)
def sem_receita(monkeypatch):
    def falha(_):
        raise ConsultaIndisponivel("teste")

    monkeypatch.setattr("app.services.contrapartes.consultar", falha)


def test_utilidades():
    assert c._valor("-1.234,56") == Decimal("-1234.56")
    assert c._valor("1.234,56 D") == Decimal("-1234.56")
    assert c._valor("39,90-") == Decimal("-39.90")
    assert c._valor(12.5) == Decimal("12.50")
    assert c.extrair_documento(f"PIX RECEBIDO {CNPJ} EMPRESA X") == "11222333000181"
    assert c.extrair_documento("PIX 123.456.789-00") is None  # CPF com dígito inválido
    assert c.nome_da_descricao(f"PIX RECEBIDO - {CNPJ} - EMPRESA X LTDA") == "EMPRESA X LTDA"


def test_le_xlsx_com_cabecalho_deslocado():
    linhas = c.ler_xlsx(xlsx_bytes())
    assert len(linhas) == 4  # ignora SALDO ANTERIOR
    assert linhas[0].data == date(2026, 10, 5) and linhas[0].valor == Decimal("4500.00")
    assert linhas[0].nome == "SEGURADORA EXEMPLO SA" and linhas[0].documento == "11222333000181"
    assert linhas[1].valor == Decimal("1200.00") and linhas[1].documento == "52998224725"


def test_le_csv_credito_debito():
    csv = (
        "Data;Histórico;Favorecido;Documento do favorecido;Crédito;Débito;Saldo\n"
        f"05/10/2026;PIX RECEBIDO;SEGURADORA EXEMPLO SA;{CNPJ};4.500,00;;4.500,00\n"
        "10/10/2026;PAGAMENTO;IMOBILIARIA;;;1.200,00;3.300,00\n"
    ).encode("cp1252")
    linhas = c.ler_csv(csv)
    assert [l.valor for l in linhas] == [Decimal("4500.00"), Decimal("1200.00")]
    assert linhas[0].documento == "11222333000181" and linhas[1].nome == "IMOBILIARIA"


def test_le_pdf_generico():
    linhas = c.ler_pdf(pdf_bytes(PDF_LINHAS))
    assert [(l.data, l.valor) for l in linhas] == [
        (date(2026, 10, 5), Decimal("4500.00")),
        (date(2026, 10, 10), Decimal("1200.00")),
        (date(2026, 10, 15), Decimal("39.90")),
        (date(2026, 10, 15), Decimal("39.90")),
    ]
    assert linhas[0].documento == "11222333000181" and "SEGURADORA EXEMPLO SA" in linhas[0].nome
    assert linhas[1].documento == "52998224725"


def _importar(client, eid, complementos):
    files = [("arquivo", ("extrato.ofx", OFX.read_bytes(), "application/x-ofx"))]
    files += [("complementos", f) for f in complementos]
    return client.post(f"/api/entidades/{eid}/ofx/importar", files=files)


def test_importa_ofx_com_xlsx_e_pdf(client, corretora):
    eid = corretora["id"]
    r = _importar(
        client,
        eid,
        [
            ("extrato.xlsx", xlsx_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ("extrato.pdf", pdf_bytes(PDF_LINHAS), "application/pdf"),
        ],
    )
    assert r.status_code == 200, r.text
    comp = r.json()["complemento"]
    assert comp["arquivos"] == ["extrato.xlsx", "extrato.pdf"] and comp["erros"] == []
    assert comp["linhas_lidas"] == 8 and comp["sem_correspondencia"] == 0
    assert comp["contrapartes_criadas"] == 2

    trns = {t["valor"]: t for t in client.get(f"/api/entidades/{eid}/transacoes").json()}
    assert trns["4500.00"]["contraparte_nome"] == "SEGURADORA EXEMPLO SA"
    assert trns["4500.00"]["contraparte_documento"] == "11222333000181"
    assert trns["-1200.00"]["contraparte_documento"] == "52998224725"

    cps = client.get(f"/api/entidades/{eid}/contrapartes").json()
    assert {c["documento"] for c in cps} == {"11222333000181", "52998224725"}


def test_complementa_depois_e_relata_erros(client, corretora):
    eid = corretora["id"]
    conta_id = _importar(client, eid, []).json()["conta_id"]
    r = client.post(
        f"/api/entidades/{eid}/contas/{conta_id}/complementar",
        files=[
            ("arquivos", ("extrato.xlsx", xlsx_bytes(), "application/octet-stream")),
            ("arquivos", ("lixo.pdf", b"%PDF-1.4 quebrado", "application/pdf")),
        ],
    )
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["linhas_lidas"] == 4 and res["sem_correspondencia"] == 0
    assert len(res["erros"]) == 1 and res["erros"][0].startswith("lixo.pdf")
