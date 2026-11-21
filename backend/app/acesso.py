"""Grupos de políticas: o administrador edita tudo; leitores (diretoria, colaboradores) só VEEM as áreas e as
empresas liberadas no seu grupo. Parceiros não têm acesso (não existe papel para eles)."""

import re
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app.models import GrupoAcesso, Usuario
from app.security import usuario_atual

AREAS: dict[str, str] = {
    "painel": "Painel e relatórios (DRE, contas a pagar do mês)",
    "pagar": "Contas a pagar",
    "receber": "Contas a receber",
    "recorrencias": "Recorrências",
    "comissoes": "Comissões (extratos, comparativo, FECHAMENTO)",
    "previsao": "Previsão de recebimentos",
    "lancamentos": "Contas bancárias e lançamentos",
    "conciliacao": "Conciliação",
    "plano_contas": "Plano de contas",
    "entidades": "Cadastro das empresas",
    "decisoes": "Central de decisões",
    "aprendizado": "O que o sistema aprendeu",
    "comissao_produtoras": "Comissões das produtoras (todas)",
    "minha_comissao": "Minha comissão (só a da própria produtora)",
}

# caminho (depois de /api/entidades/{id}) -> área
_MAPA = [
    (r"^/fechamento-mensal", "painel"),
    (r"^/minha-comissao", "minha_comissao"),
    (r"^/planos-comissao", "comissao_produtoras"),
    (r"^/comissoes/previsao", "previsao"),
    (r"^/(comissoes|extratos-comissao|fechamento|pasta|importar-planilha)", "comissoes"),
    (r"^/recorrencias", "recorrencias"),
    (r"^/(painel-pagar|relatorios)", "painel"),
    (r"^/(contas|transacoes|contrapartes|ofx|conexoes-bancarias)", "lancamentos"),
    (r"^/(conciliacao|categorizacao)", "conciliacao"),
    (r"^/(categorias|centros-custo|regras)", "plano_contas"),
    (r"^/pendencias", "decisoes"),
    (r"^/aprendizado", "aprendizado"),
]


def area_do_caminho(caminho: str, tipo_titulo: str | None = None) -> str | None:
    """Área de uma rota da API, ou None se a rota não é liberável para leitores."""
    if caminho.startswith("/api/cnpj"):
        return "entidades"
    m = re.match(r"^/api/entidades/\d+(/.*)?$", caminho)
    if not m:
        return None
    resto = m.group(1) or ""
    if resto == "":
        return ""  # dados da própria empresa (nome, segmento): basta ter acesso à empresa
    if resto.startswith("/titulos"):
        return {"pagar": "pagar", "receber": "receber"}.get(tipo_titulo or "", "pagar|receber")
    return next((area for rx, area in _MAPA if re.match(rx, resto)), None)


def pode_ver_entidade(usuario: Usuario, grupo: GrupoAcesso | None, entidade_id: int) -> bool:
    if usuario.papel == "admin":
        return True
    return bool(grupo) and (grupo.todas_entidades or entidade_id in (grupo.entidades or []))


def autorizar(request: Request, usuario: Annotated[Usuario, Depends(usuario_atual)]) -> Usuario:
    if usuario.papel == "admin":
        return usuario
    grupo = usuario.grupo
    if request.method not in ("GET", "HEAD"):
        raise HTTPException(403, "Acesso somente para consulta")
    caminho = request.url.path
    if caminho == "/api/entidades":  # lista (filtrada) para o seletor de empresa
        return usuario
    area = area_do_caminho(caminho, request.query_params.get("tipo"))
    m = re.match(r"^/api/entidades/(\d+)", caminho)
    if m and not pode_ver_entidade(usuario, grupo, int(m.group(1))):
        raise HTTPException(403, "Sem acesso a esta empresa")
    areas = set(grupo.areas or []) if grupo else set()
    if area is None or (area and not (set(area.split("|")) & areas)):
        raise HTTPException(403, "Área não liberada para o seu grupo")
    return usuario


def somente_admin(usuario: Annotated[Usuario, Depends(usuario_atual)]) -> Usuario:
    if usuario.papel != "admin":
        raise HTTPException(403, "Somente o administrador")
    return usuario
