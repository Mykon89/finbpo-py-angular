import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from app.models import Segmento
from app.services import cnpj as svc

FIX = Path(__file__).parent / "fixtures"
BRASILAPI = json.loads((FIX / "cnpj_brasilapi.json").read_text())
CNPJA = json.loads((FIX / "cnpj_cnpja.json").read_text())


@pytest.fixture(autouse=True)
def limpar_cache():
    svc._cache.clear()


def cliente(respostas: dict[str, httpx.Response]) -> httpx.Client:
    def handler(req: httpx.Request) -> httpx.Response:
        for host, resp in respostas.items():
            if req.url.host == host:
                return resp
        raise httpx.ConnectError("sem rota")

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_validacao_documentos():
    assert svc.cnpj_valido("00.000.000/0001-91")
    assert svc.cnpj_valido("11222333000181")
    assert not svc.cnpj_valido("11222333000182")
    assert not svc.cnpj_valido("11111111111111")
    assert svc.cpf_valido("529.982.247-25")
    assert not svc.cpf_valido("529.982.247-26")


def test_sugestao_de_segmento():
    assert svc.sugerir_segmento("6622300") == Segmento.CORRETORA
    assert svc.sugerir_segmento("9602502") == Segmento.CLINICA
    assert svc.sugerir_segmento("8630503") == Segmento.CLINICA
    assert svc.sugerir_segmento("6422100") is None


def test_converte_brasilapi():
    d = svc.de_brasilapi(BRASILAPI)
    assert d.razao_social == "BANCO DO BRASIL SA"
    assert d.cnae_principal == "6422100"
    assert d.data_abertura == date(1966, 8, 1)
    assert d.situacao_cadastral == "ATIVA"
    assert d.uf == "DF" and d.cep == "70040912"
    assert d.logradouro.startswith("QUADRA")
    assert d.cnaes_secundarios[0].codigo == "6499999"


def test_converte_cnpja():
    d = svc.de_cnpja(CNPJA)
    assert d.razao_social == "BANCO DO BRASIL SA"
    assert d.nome_fantasia == "Direcao Geral"
    assert d.cnae_principal == "6422100"
    assert d.telefone == "6134939002"
    assert d.optante_simples is False


def test_usa_cnpja_quando_brasilapi_limita():
    c = cliente(
        {
            "brasilapi.com.br": httpx.Response(429, text="Too Many Requests"),
            "open.cnpja.com": httpx.Response(200, json=CNPJA),
        }
    )
    d = svc.consultar("00000000000191", c)
    assert d.fonte == "CNPJá"


def test_nao_encontrado_e_indisponivel():
    c = cliente({"brasilapi.com.br": httpx.Response(404), "open.cnpja.com": httpx.Response(404)})
    with pytest.raises(svc.CNPJNaoEncontrado):
        svc.consultar("11222333000181", c)
    c = cliente({"brasilapi.com.br": httpx.Response(500), "open.cnpja.com": httpx.Response(503)})
    with pytest.raises(svc.ConsultaIndisponivel):
        svc.consultar("11222333000181", c)


def test_endpoint(client, monkeypatch):
    monkeypatch.setattr("app.routers.cnpj.consultar", lambda c: svc.de_brasilapi(BRASILAPI))
    r = client.get("/api/cnpj/00000000000191")
    assert r.status_code == 200 and r.json()["fonte"] == "BrasilAPI"
    assert client.get("/api/cnpj/123").status_code == 422


def test_cadastro_com_dados_da_receita(client):
    dados = svc.de_brasilapi(BRASILAPI).model_dump(mode="json", exclude={"cnpj", "fonte", "segmento_sugerido"})
    corpo = {**dados, "tipo": "PJ", "segmento": "corretora", "nome": "BB", "documento": "00.000.000/0001-91"}
    r = client.post("/api/entidades", json=corpo)
    assert r.status_code == 201, r.text
    e = r.json()
    assert e["documento"] == "00000000000191"
    assert e["municipio"] == "BRASILIA"
    assert e["cnaes_secundarios"][0]["codigo"] == "6499999"
    assert e["dados_atualizados_em"]

    assert client.post("/api/entidades", json=corpo).status_code == 409
    corpo["documento"] = "11222333000182"
    assert client.post("/api/entidades", json=corpo).status_code == 422

    r = client.patch(f"/api/entidades/{e['id']}", json={"nome": "Banco do Brasil", "cep": "70.040-912"})
    assert r.json()["nome"] == "Banco do Brasil" and r.json()["cep"] == "70040912"
