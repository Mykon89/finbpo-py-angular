from decimal import Decimal
from pathlib import Path

import pytest

from app.services.ofx import OFXInvalido, ler_ofx

FIXTURE = Path(__file__).parent / "fixtures" / "itau_sgml.ofx"


def test_le_ofx_sgml_cp1252():
    ext = ler_ofx(FIXTURE.read_bytes())
    assert ext.banco_id == "0341"
    assert ext.conta_id == "56789-0"
    assert ext.saldo == Decimal("3220.20")
    assert not ext.cartao
    assert len(ext.transacoes) == 4
    assert ext.transacoes[1].valor == Decimal("-1200.00")  # vírgula decimal
    assert "Ç" in ext.transacoes[1].descricao


def test_lancamentos_identicos_tem_hash_distinto():
    ext = ler_ofx(FIXTURE.read_bytes())
    assert ext.transacoes[2].hash != ext.transacoes[3].hash
    assert ler_ofx(FIXTURE.read_bytes()).transacoes[2].hash == ext.transacoes[2].hash


def test_ofx_xml_com_fechamento():
    xml = b"""<?xml version="1.0"?><OFX><CREDITCARDMSGSRSV1><CCSTMTTRNRS><CCSTMTRS><CURDEF>BRL</CURDEF>
<CCACCTFROM><ACCTID>1111</ACCTID></CCACCTFROM><BANKTRANLIST>
<STMTTRN><TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>20261002</DTPOSTED><TRNAMT>-89.90</TRNAMT>
<FITID>x1</FITID><NAME>IFOOD</NAME><MEMO>Parcela 1/3</MEMO></STMTTRN>
</BANKTRANLIST></CCSTMTRS></CCSTMTTRNRS></CREDITCARDMSGSRSV1></OFX>"""
    ext = ler_ofx(xml)
    assert ext.cartao
    assert len(ext.transacoes) == 1
    assert ext.transacoes[0].descricao == "IFOOD Parcela 1/3"


def test_rejeita_arquivo_invalido():
    with pytest.raises(OFXInvalido):
        ler_ofx(b"nao sou ofx")
