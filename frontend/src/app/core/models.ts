export type Segmento = 'corretora' | 'clinica' | 'pf';
export type TipoTitulo = 'pagar' | 'receber';
export type StatusTitulo = 'aberto' | 'parcial' | 'pago' | 'cancelado';
export type TipoConta = 'corrente' | 'poupanca' | 'cartao' | 'caixa' | 'maquininha';

export interface CNAE {
  codigo: string;
  descricao: string;
}

export interface DadosCadastrais {
  documento: string | null;
  email: string | null;
  telefone: string | null;
  razao_social: string | null;
  nome_fantasia: string | null;
  situacao_cadastral: string | null;
  data_abertura: string | null;
  natureza_juridica: string | null;
  porte: string | null;
  cnae_principal: string | null;
  cnae_descricao: string | null;
  cnaes_secundarios: CNAE[] | null;
  optante_simples: boolean | null;
  mei: boolean | null;
  cep: string | null;
  logradouro: string | null;
  numero: string | null;
  complemento: string | null;
  bairro: string | null;
  municipio: string | null;
  uf: string | null;
}

export interface Entidade extends DadosCadastrais {
  id: number;
  tipo: 'PJ' | 'PF';
  segmento: Segmento;
  nome: string;
  ativo: boolean;
  dados_atualizados_em: string | null;
}

export interface DadosCNPJ extends Omit<DadosCadastrais, 'documento'> {
  cnpj: string;
  segmento_sugerido: Segmento | null;
  fonte: string;
}

export interface Categoria {
  id: number;
  entidade_id: number;
  nome: string;
  grupo_dre: string;
}

export interface Conta {
  id: number;
  entidade_id: number;
  tipo: TipoConta;
  nome: string;
  banco_codigo: string | null;
  agencia: string | null;
  numero: string | null;
  saldo_inicial: string;
  saldo_atual: string;
  ativo: boolean;
}

export interface Baixa {
  id: number;
  transacao_id: number | null;
  data: string;
  valor: string;
}

export interface Titulo {
  id: number;
  entidade_id: number;
  tipo: TipoTitulo;
  descricao: string;
  contraparte_id: number | null;
  categoria_id: number | null;
  centro_custo_id: number | null;
  competencia: string;
  vencimento: string;
  valor: string;
  saldo: string;
  status: StatusTitulo;
  parcela: number;
  total_parcelas: number;
  observacao: string | null;
  baixas: Baixa[];
}

export interface Transacao {
  id: number;
  conta_id: number;
  data: string;
  valor: string;
  descricao: string;
  fitid: string | null;
  origem: string;
  categoria_id: number | null;
  conciliada: boolean;
  contraparte_id: number | null;
  contraparte_nome: string | null;
  contraparte_documento: string | null;
  complemento: string | null;
}

export interface ComplementoResultado {
  arquivos: string[];
  linhas_lidas: number;
  enriquecidas: number;
  sem_correspondencia: number;
  contrapartes_criadas: number;
  erros: string[];
}

export interface ImportacaoResultado {
  importacao_id: number;
  conta_id: number;
  conta_nome: string;
  conta_criada: boolean;
  total_lidas: number;
  total_novas: number;
  duplicadas: number;
  categorizadas: number;
  conciliadas: number;
  saldo_extrato: string | null;
  com_documento_no_ofx: number;
  complemento: ComplementoResultado | null;
}

export interface AnaliseOFX {
  banco_codigo: string | null;
  banco_nome: string | null;
  agencia: string | null;
  numero: string | null;
  tipo: TipoConta;
  inicio: string | null;
  fim: string | null;
  total_transacoes: number;
  saldo_extrato: string | null;
  data_saldo: string | null;
  conta_existente: Omit<Conta, 'saldo_atual'> | null;
  outra_entidade: string | null;
  sugestao_nome: string;
  sugestao_saldo_inicial: string;
}

export interface LinhaDRE {
  grupo: string | null;
  rotulo: string;
  valor: string;
  detalhe: { categoria: string; valor: string }[];
}

export interface DRE {
  entidade_id: number;
  competencia: string;
  linhas: LinhaDRE[];
  resultado_liquido: string;
  margem_liquida_pct: number | null;
  nao_operacional: string;
  sem_categoria: string;
}

export interface Aging {
  tipo: TipoTitulo;
  data_base: string;
  faixas: { faixa: string; quantidade: number; valor: string }[];
}

export const SEGMENTOS: Record<Segmento, string> = {
  corretora: 'Corretora de seguros',
  clinica: 'Clínica de estética',
  pf: 'Pessoa física',
};
