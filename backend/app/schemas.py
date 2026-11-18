from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import (
    GrupoDRE,
    OrigemTransacao,
    Segmento,
    StatusTitulo,
    TipoConta,
    TipoEntidade,
    TipoTitulo,
)


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UsuarioCriar(BaseModel):
    nome: str
    email: EmailStr
    senha: str = Field(min_length=8)


class UsuarioLer(ORM):
    id: int
    nome: str
    email: str


# --- entidade
class CNAELer(BaseModel):
    codigo: str
    descricao: str


class EntidadeCampos(BaseModel):
    """Campos opcionais comuns a criação e edição."""

    documento: str | None = None
    email: EmailStr | None = None
    telefone: str | None = None
    razao_social: str | None = None
    nome_fantasia: str | None = None
    situacao_cadastral: str | None = None
    data_abertura: date | None = None
    natureza_juridica: str | None = None
    porte: str | None = None
    cnae_principal: str | None = None
    cnae_descricao: str | None = None
    cnaes_secundarios: list[CNAELer] | None = None
    optante_simples: bool | None = None
    mei: bool | None = None
    cep: str | None = None
    logradouro: str | None = None
    numero: str | None = None
    complemento: str | None = None
    bairro: str | None = None
    municipio: str | None = None
    uf: str | None = Field(None, max_length=2)


class EntidadeCriar(EntidadeCampos):
    tipo: TipoEntidade
    segmento: Segmento
    nome: str = Field(min_length=1)
    criar_plano_contas: bool = True


class EntidadeAtualizar(EntidadeCampos):
    nome: str | None = Field(None, min_length=1)
    ativo: bool | None = None


class EntidadeLer(ORM, EntidadeCampos):
    id: int
    tipo: TipoEntidade
    segmento: Segmento
    nome: str
    ativo: bool
    email: str | None = None  # sem validação na leitura
    dados_atualizados_em: datetime | None = None


# --- cadastros
class CategoriaCriar(BaseModel):
    nome: str
    grupo_dre: GrupoDRE


class CategoriaLer(ORM):
    id: int
    entidade_id: int
    nome: str
    grupo_dre: GrupoDRE


class ContraparteCriar(BaseModel):
    nome: str
    documento: str | None = None


class ContraparteLer(ORM):
    id: int
    entidade_id: int
    nome: str
    documento: str | None


class CentroCustoCriar(BaseModel):
    nome: str


class CentroCustoLer(ORM):
    id: int
    entidade_id: int
    nome: str


class ContaCriar(BaseModel):
    tipo: TipoConta
    nome: str
    banco_codigo: str | None = None
    agencia: str | None = None
    numero: str | None = None
    saldo_inicial: Decimal = Decimal("0")


class ContaLer(ORM):
    id: int
    entidade_id: int
    tipo: TipoConta
    nome: str
    banco_codigo: str | None
    agencia: str | None
    numero: str | None
    saldo_inicial: Decimal
    ativo: bool


class ContaSaldo(ContaLer):
    saldo_atual: Decimal


class RegraCriar(BaseModel):
    padrao: str = Field(min_length=2)
    categoria_id: int
    prioridade: int = 100


class RegraLer(ORM):
    id: int
    entidade_id: int
    padrao: str
    categoria_id: int
    prioridade: int


# --- títulos
class TituloCriar(BaseModel):
    tipo: TipoTitulo
    descricao: str
    valor: Decimal = Field(gt=0, description="Valor de cada parcela")
    vencimento: date = Field(description="Vencimento da 1ª parcela")
    competencia: date | None = None
    contraparte_id: int | None = None
    categoria_id: int | None = None
    centro_custo_id: int | None = None
    parcelas: int = Field(1, ge=1, le=360)
    observacao: str | None = None


class TituloAtualizar(BaseModel):
    descricao: str | None = None
    valor: Decimal | None = Field(None, gt=0)
    vencimento: date | None = None
    competencia: date | None = None
    contraparte_id: int | None = None
    categoria_id: int | None = None
    centro_custo_id: int | None = None
    observacao: str | None = None


class BaixaLer(ORM):
    id: int
    transacao_id: int | None
    data: date
    valor: Decimal


class TituloLer(ORM):
    id: int
    entidade_id: int
    tipo: TipoTitulo
    descricao: str
    contraparte_id: int | None
    categoria_id: int | None
    centro_custo_id: int | None
    competencia: date
    vencimento: date
    valor: Decimal
    saldo: Decimal
    status: StatusTitulo
    parcela: int
    total_parcelas: int
    observacao: str | None
    baixas: list[BaixaLer] = []


class BaixaManual(BaseModel):
    data: date
    valor: Decimal | None = Field(None, gt=0, description="Padrão: saldo do título")


# --- transações / importação
class TransacaoLer(ORM):
    id: int
    conta_id: int
    data: date
    valor: Decimal
    descricao: str
    fitid: str | None
    origem: OrigemTransacao
    categoria_id: int | None
    conciliada: bool
    contraparte_id: int | None = None
    contraparte_nome: str | None = None
    contraparte_documento: str | None = None
    complemento: str | None = None


class TransacaoAtualizar(BaseModel):
    categoria_id: int | None = None
    criar_regra: bool = Field(False, description="Cria regra de categorização com a descrição")


class ComplementoResultado(BaseModel):
    arquivos: list[str] = []
    linhas_lidas: int = 0
    enriquecidas: int = 0
    sem_correspondencia: int = 0
    contrapartes_criadas: int = 0
    erros: list[str] = []


class ImportacaoResultado(BaseModel):
    importacao_id: int
    conta_id: int
    conta_nome: str
    conta_criada: bool = False
    total_lidas: int
    total_novas: int
    duplicadas: int
    categorizadas: int
    conciliadas: int
    saldo_extrato: Decimal | None
    com_documento_no_ofx: int = 0
    complemento: ComplementoResultado | None = None


class AnaliseOFX(BaseModel):
    banco_codigo: str | None
    banco_nome: str | None
    agencia: str | None
    numero: str | None
    tipo: TipoConta
    inicio: date | None
    fim: date | None
    total_transacoes: int
    saldo_extrato: Decimal | None
    data_saldo: date | None
    conta_existente: "ContaLer | None"
    outra_entidade: str | None = Field(None, description="Entidade que já tem esta conta cadastrada")
    sugestao_nome: str
    sugestao_saldo_inicial: Decimal


class ConciliacaoResultado(BaseModel):
    conciliadas: int
    ambiguas: int
    sem_candidato: int


class VinculoManual(BaseModel):
    transacao_id: int
    titulo_id: int


# --- relatórios
class LinhaDetalhe(BaseModel):
    categoria: str
    valor: Decimal


class LinhaDRE(BaseModel):
    grupo: str | None
    rotulo: str
    valor: Decimal
    detalhe: list[LinhaDetalhe]


class DRE(BaseModel):
    entidade_id: int
    competencia: date
    linhas: list[LinhaDRE]
    resultado_liquido: Decimal
    margem_liquida_pct: float | None
    nao_operacional: Decimal
    sem_categoria: Decimal


class AgingFaixa(BaseModel):
    faixa: str
    quantidade: int
    valor: Decimal


class Aging(BaseModel):
    tipo: TipoTitulo
    data_base: date
    faixas: list[AgingFaixa]
