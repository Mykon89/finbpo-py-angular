import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

Dinheiro = Numeric(14, 2)


def _enum(cls: type[enum.Enum]) -> Enum:
    # native_enum=False: armazena como VARCHAR, facilita migrações
    return Enum(cls, native_enum=False, length=20, values_callable=lambda e: [m.value for m in e])


class TipoEntidade(str, enum.Enum):
    PJ = "PJ"
    PF = "PF"


class Segmento(str, enum.Enum):
    CORRETORA = "corretora"
    CLINICA = "clinica"
    PF = "pf"


class TipoConta(str, enum.Enum):
    CORRENTE = "corrente"
    POUPANCA = "poupanca"
    CARTAO = "cartao"
    CAIXA = "caixa"
    MAQUININHA = "maquininha"


class TipoTitulo(str, enum.Enum):
    PAGAR = "pagar"
    RECEBER = "receber"


class StatusTitulo(str, enum.Enum):
    ABERTO = "aberto"
    PARCIAL = "parcial"
    PAGO = "pago"
    CANCELADO = "cancelado"


class OrigemTransacao(str, enum.Enum):
    OFX = "ofx"
    PDF = "pdf"
    API = "api"
    MANUAL = "manual"


class GrupoDRE(str, enum.Enum):
    RECEITA_BRUTA = "receita_bruta"
    DEDUCOES = "deducoes"
    CUSTOS = "custos"
    DESPESAS_PESSOAL = "despesas_pessoal"
    DESPESAS_ADMINISTRATIVAS = "despesas_adm"
    DESPESAS_COMERCIAIS = "despesas_comerciais"
    RECEITAS_FINANCEIRAS = "receitas_fin"
    DESPESAS_FINANCEIRAS = "despesas_fin"
    IMPOSTOS_LUCRO = "impostos_lucro"
    NAO_OPERACIONAL = "nao_operacional"  # transferências, aportes, retiradas


class Usuario(Base):
    __tablename__ = "usuario"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    senha_hash: Mapped[str] = mapped_column(String(255))
    ativo: Mapped[bool] = mapped_column(default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Entidade(Base):
    __tablename__ = "entidade"
    __table_args__ = (UniqueConstraint("documento", name="uq_entidade_documento"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[TipoEntidade] = mapped_column(_enum(TipoEntidade))
    segmento: Mapped[Segmento] = mapped_column(_enum(Segmento))
    nome: Mapped[str] = mapped_column(String(160))  # nome de exibição
    documento: Mapped[str | None] = mapped_column(String(20))  # CNPJ/CPF, só dígitos
    email: Mapped[str | None] = mapped_column(String(180))
    telefone: Mapped[str | None] = mapped_column(String(30))
    ativo: Mapped[bool] = mapped_column(default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Dados cadastrais (Receita Federal, para PJ)
    razao_social: Mapped[str | None] = mapped_column(String(200))
    nome_fantasia: Mapped[str | None] = mapped_column(String(200))
    situacao_cadastral: Mapped[str | None] = mapped_column(String(40))
    data_abertura: Mapped[date | None] = mapped_column(Date)
    natureza_juridica: Mapped[str | None] = mapped_column(String(120))
    porte: Mapped[str | None] = mapped_column(String(40))
    cnae_principal: Mapped[str | None] = mapped_column(String(7))
    cnae_descricao: Mapped[str | None] = mapped_column(String(255))
    cnaes_secundarios: Mapped[list | None] = mapped_column(JSON)
    optante_simples: Mapped[bool | None] = mapped_column()
    mei: Mapped[bool | None] = mapped_column()
    dados_atualizados_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Endereço
    cep: Mapped[str | None] = mapped_column(String(8))
    logradouro: Mapped[str | None] = mapped_column(String(200))
    numero: Mapped[str | None] = mapped_column(String(20))
    complemento: Mapped[str | None] = mapped_column(String(200))
    bairro: Mapped[str | None] = mapped_column(String(120))
    municipio: Mapped[str | None] = mapped_column(String(120))
    uf: Mapped[str | None] = mapped_column(String(2))

    contas: Mapped[list["ContaFinanceira"]] = relationship(back_populates="entidade")


class Categoria(Base):
    __tablename__ = "categoria"
    __table_args__ = (UniqueConstraint("entidade_id", "nome"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entidade_id: Mapped[int] = mapped_column(ForeignKey("entidade.id", ondelete="CASCADE"), index=True)
    nome: Mapped[str] = mapped_column(String(120))
    grupo_dre: Mapped[GrupoDRE] = mapped_column(_enum(GrupoDRE))
    ativo: Mapped[bool] = mapped_column(default=True, server_default="true")  # inativa some das listas de escolha


class CentroCusto(Base):
    __tablename__ = "centro_custo"
    __table_args__ = (UniqueConstraint("entidade_id", "nome"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entidade_id: Mapped[int] = mapped_column(ForeignKey("entidade.id", ondelete="CASCADE"), index=True)
    nome: Mapped[str] = mapped_column(String(120))


class Contraparte(Base):
    """Fornecedor, cliente, seguradora, profissional etc."""

    __tablename__ = "contraparte"
    __table_args__ = (UniqueConstraint("entidade_id", "documento", name="uq_contraparte_documento"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entidade_id: Mapped[int] = mapped_column(ForeignKey("entidade.id", ondelete="CASCADE"), index=True)
    nome: Mapped[str] = mapped_column(String(160))
    documento: Mapped[str | None] = mapped_column(String(20))


class ContaFinanceira(Base):
    __tablename__ = "conta_financeira"

    id: Mapped[int] = mapped_column(primary_key=True)
    entidade_id: Mapped[int] = mapped_column(ForeignKey("entidade.id", ondelete="CASCADE"), index=True)
    tipo: Mapped[TipoConta] = mapped_column(_enum(TipoConta))
    nome: Mapped[str] = mapped_column(String(120))
    banco_codigo: Mapped[str | None] = mapped_column(String(10))  # código COMPE (ex.: 341, 077)
    agencia: Mapped[str | None] = mapped_column(String(20))
    numero: Mapped[str | None] = mapped_column(String(40))  # ACCTID do OFX
    saldo_inicial: Mapped[Decimal] = mapped_column(Dinheiro, default=Decimal("0"))
    ativo: Mapped[bool] = mapped_column(default=True)

    entidade: Mapped[Entidade] = relationship(back_populates="contas")


class Transacao(Base):
    __tablename__ = "transacao"
    __table_args__ = (UniqueConstraint("conta_id", "hash", name="uq_transacao_conta_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    conta_id: Mapped[int] = mapped_column(ForeignKey("conta_financeira.id", ondelete="CASCADE"), index=True)
    data: Mapped[date] = mapped_column(Date, index=True)
    valor: Mapped[Decimal] = mapped_column(Dinheiro)  # negativo = saída
    descricao: Mapped[str] = mapped_column(String(255))
    fitid: Mapped[str | None] = mapped_column(String(255))
    hash: Mapped[str] = mapped_column(String(64))  # deduplicação
    origem: Mapped[OrigemTransacao] = mapped_column(_enum(OrigemTransacao))
    categoria_id: Mapped[int | None] = mapped_column(ForeignKey("categoria.id", ondelete="SET NULL"))
    # Como a categoria foi definida: manual, regra, sugestao (aprendizado interno) ou ia (Claude via MCP)
    categoria_origem: Mapped[str | None] = mapped_column(String(10))
    conciliada: Mapped[bool] = mapped_column(default=False, index=True)
    importacao_id: Mapped[int | None] = mapped_column(ForeignKey("importacao.id", ondelete="SET NULL"))
    # Quem pagou/recebeu: vem do próprio OFX (quando o banco informa) ou de XLSX/PDF complementar
    contraparte_id: Mapped[int | None] = mapped_column(ForeignKey("contraparte.id", ondelete="SET NULL"), index=True)
    contraparte_nome: Mapped[str | None] = mapped_column(String(160))
    contraparte_documento: Mapped[str | None] = mapped_column(String(14))
    complemento: Mapped[str | None] = mapped_column(String(255))  # descrição mais completa do XLSX/PDF

    conta: Mapped[ContaFinanceira] = relationship()
    categoria: Mapped[Categoria | None] = relationship()
    contraparte: Mapped[Contraparte | None] = relationship()


class Importacao(Base):
    __tablename__ = "importacao"

    id: Mapped[int] = mapped_column(primary_key=True)
    conta_id: Mapped[int] = mapped_column(ForeignKey("conta_financeira.id", ondelete="CASCADE"), index=True)
    arquivo: Mapped[str] = mapped_column(String(255))
    origem: Mapped[OrigemTransacao] = mapped_column(_enum(OrigemTransacao))
    total_lidas: Mapped[int] = mapped_column(default=0)
    total_novas: Mapped[int] = mapped_column(default=0)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Titulo(Base):
    __tablename__ = "titulo"

    id: Mapped[int] = mapped_column(primary_key=True)
    entidade_id: Mapped[int] = mapped_column(ForeignKey("entidade.id", ondelete="CASCADE"), index=True)
    tipo: Mapped[TipoTitulo] = mapped_column(_enum(TipoTitulo), index=True)
    descricao: Mapped[str] = mapped_column(String(255))
    contraparte_id: Mapped[int | None] = mapped_column(ForeignKey("contraparte.id", ondelete="SET NULL"))
    categoria_id: Mapped[int | None] = mapped_column(ForeignKey("categoria.id", ondelete="SET NULL"))
    centro_custo_id: Mapped[int | None] = mapped_column(ForeignKey("centro_custo.id", ondelete="SET NULL"))
    competencia: Mapped[date] = mapped_column(Date)  # primeiro dia do mês de competência
    vencimento: Mapped[date] = mapped_column(Date, index=True)
    valor: Mapped[Decimal] = mapped_column(Dinheiro)  # sempre positivo
    status: Mapped[StatusTitulo] = mapped_column(_enum(StatusTitulo), default=StatusTitulo.ABERTO, index=True)
    parcela: Mapped[int] = mapped_column(default=1)
    total_parcelas: Mapped[int] = mapped_column(default=1)
    grupo_parcelas: Mapped[str | None] = mapped_column(String(36))
    observacao: Mapped[str | None] = mapped_column(Text)

    baixas: Mapped[list["Baixa"]] = relationship(back_populates="titulo", cascade="all, delete-orphan")

    @property
    def valor_baixado(self) -> Decimal:
        return sum((b.valor for b in self.baixas), Decimal("0"))

    @property
    def saldo(self) -> Decimal:
        return self.valor - self.valor_baixado


class Baixa(Base):
    __tablename__ = "baixa"

    id: Mapped[int] = mapped_column(primary_key=True)
    titulo_id: Mapped[int] = mapped_column(ForeignKey("titulo.id", ondelete="CASCADE"), index=True)
    transacao_id: Mapped[int | None] = mapped_column(ForeignKey("transacao.id", ondelete="SET NULL"))
    data: Mapped[date] = mapped_column(Date)
    valor: Mapped[Decimal] = mapped_column(Dinheiro)

    titulo: Mapped[Titulo] = relationship(back_populates="baixas")


class RegraCategorizacao(Base):
    __tablename__ = "regra_categorizacao"

    id: Mapped[int] = mapped_column(primary_key=True)
    entidade_id: Mapped[int] = mapped_column(ForeignKey("entidade.id", ondelete="CASCADE"), index=True)
    padrao: Mapped[str | None] = mapped_column(String(160))  # trecho da descrição (case-insensitive)
    # Regra por quem pagou/recebeu: mais confiável que texto (ex.: todo Pix para o CNPJ X é "Contabilidade")
    contraparte_id: Mapped[int | None] = mapped_column(ForeignKey("contraparte.id", ondelete="CASCADE"), index=True)
    categoria_id: Mapped[int] = mapped_column(ForeignKey("categoria.id", ondelete="CASCADE"))
    prioridade: Mapped[int] = mapped_column(default=100)  # menor = avaliada primeiro
