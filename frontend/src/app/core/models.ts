export type Segmento = 'corretora' | 'clinica' | 'pf';
export type TipoTitulo = 'pagar' | 'receber';
export type StatusTitulo = 'aberto' | 'parcial' | 'pago' | 'cancelado';
export type TipoConta = 'corrente' | 'poupanca' | 'cartao' | 'caixa' | 'maquininha';

export interface Entidade {
  id: number;
  tipo: 'PJ' | 'PF';
  segmento: Segmento;
  nome: string;
  documento: string | null;
  email: string | null;
  ativo: boolean;
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
}

export interface ImportacaoResultado {
  importacao_id: number;
  total_lidas: number;
  total_novas: number;
  duplicadas: number;
  categorizadas: number;
  conciliadas: number;
  saldo_extrato: string | null;
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
