from fastapi import APIRouter, HTTPException

from app.services.cnpj import CNPJNaoEncontrado, ConsultaIndisponivel, DadosCNPJ, cnpj_valido, consultar

router = APIRouter(prefix="/cnpj", tags=["cnpj"])


@router.get("/{cnpj}", response_model=DadosCNPJ)
def consultar_cnpj(cnpj: str):
    if not cnpj_valido(cnpj):
        raise HTTPException(422, "CNPJ inválido")
    try:
        return consultar(cnpj)
    except CNPJNaoEncontrado:
        raise HTTPException(404, "CNPJ não encontrado na Receita Federal")
    except ConsultaIndisponivel:
        raise HTTPException(503, "Serviço de consulta de CNPJ indisponível. Tente novamente em instantes.")
