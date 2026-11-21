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

export type GrupoDRE =
  | 'receita_bruta'
  | 'deducoes'
  | 'custos'
  | 'despesas_pessoal'
  | 'despesas_adm'
  | 'despesas_comerciais'
  | 'receitas_fin'
  | 'despesas_fin'
  | 'impostos_lucro'
  | 'nao_operacional';

/** Grupos da DRE, na ordem em que aparecem no relatório. */
export const GRUPOS_DRE: { valor: GrupoDRE; rotulo: string; ajuda: string }[] = [
  {
    valor: 'receita_bruta',
    rotulo: 'Receita bruta',
    ajuda: 'Faturamento: comissões, procedimentos, vendas, salário (PF)',
  },
  {
    valor: 'deducoes',
    rotulo: 'Deduções da receita',
    ajuda: 'Impostos sobre a venda (DAS, ISS), estornos, taxas de cartão',
  },
  {
    valor: 'custos',
    rotulo: 'Custos',
    ajuda: 'Gasto direto para gerar a receita: repasses, insumos, comissões',
  },
  {
    valor: 'despesas_pessoal',
    rotulo: 'Despesas com pessoal',
    ajuda: 'Salários, encargos, benefícios, pró-labore',
  },
  {
    valor: 'despesas_adm',
    rotulo: 'Despesas administrativas',
    ajuda: 'Aluguel, energia, contabilidade, sistemas, seguros, limpeza',
  },
  {
    valor: 'despesas_comerciais',
    rotulo: 'Despesas comerciais',
    ajuda: 'Marketing, anúncios, brindes',
  },
  {
    valor: 'receitas_fin',
    rotulo: 'Receitas financeiras',
    ajuda: 'Rendimentos de aplicações, juros recebidos',
  },
  {
    valor: 'despesas_fin',
    rotulo: 'Despesas financeiras',
    ajuda: 'Tarifas bancárias, juros, multas, IOF',
  },
  {
    valor: 'impostos_lucro',
    rotulo: 'IRPJ / CSLL',
    ajuda: 'Impostos sobre o lucro (Lucro Presumido/Real)',
  },
  {
    valor: 'nao_operacional',
    rotulo: 'Fora do resultado',
    ajuda: 'Não entra na DRE: transferências entre contas, aportes, distribuição de lucros',
  },
];

export interface Categoria {
  id: number;
  entidade_id: number;
  nome: string;
  grupo_dre: GrupoDRE;
  ativo: boolean;
  qtd_lancamentos: number;
  qtd_titulos: number;
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
  desconto?: string;
  natureza?: 'fixa' | 'variavel' | null;
  recorrencia_id?: number | null;
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
  categoria_origem: 'manual' | 'regra' | 'sugestao' | 'ia' | null;
}

export interface Sugestao {
  transacao_id: number;
  categoria_id: number;
  categoria: string;
  confianca: number;
  motivo: string;
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

export type Frequencia = 'mensal' | 'semanal' | 'quinzenal' | 'anual' | 'unica' | 'parcelada';
export type AjusteDiaUtil = 'nenhum' | 'antecipar' | 'postergar';

export interface Recorrencia {
  id: number;
  codigo: string | null;
  ativa: boolean;
  tipo: TipoTitulo;
  descricao: string;
  valor: string;
  frequencia: Frequencia;
  inicio: string;
  fim: string | null;
  dia: number | null;
  dia_util: number | null;
  ajuste: AjusteDiaUtil;
  parcelas: number | null;
  reajuste_pct: string | null;
  mes_reajuste: number | null;
  contraparte_id: number | null;
  categoria_id: number | null;
  centro_custo_id: number | null;
  natureza: 'fixa' | 'variavel' | null;
  proximo_vencimento: string | null;
  contraparte_nome: string | null;
}

export interface ImportacaoPlanilha {
  abas: string[];
  contas_pagar: number;
  contas_pagas: number;
  recorrencias: number;
  regras: number;
  extratos: number;
  comissoes: number;
  categorias_criadas: string[];
  fornecedores_criados: number;
  ignoradas: number;
}

export interface Comissao {
  id: number;
  extrato_id: number | null;
  data: string;
  apolice: string | null;
  seguradora: string;
  ramo: string | null;
  cliente: string | null;
  bruta: string;
  imposto: string;
  liquida: string;
  origem: string | null;
  produtor: string | null;
  parceiro: string | null;
  observacao: string | null;
  parcela: number | null;
  parcela_texto: string | null;
  novo_negocio?: boolean | null;
}

export interface ExtratoComissao {
  id: number;
  codigo: string;
  seguradora: string;
  data: string;
  documento: string | null;
  bruto: string;
  iss: string;
  liquido: string;
  debitos: string;
  recebido_valor: string | null;
  recebido_em: string | null;
  linhas: number;
  situacao: 'A RECEBER' | 'RECEBIDO' | 'DIVERGENTE';
}

export interface LinhaComparativo {
  chave: string;
  anterior: string;
  atual: string;
  variacao: string;
  variacao_pct: number | null;
  qtd: number;
}

export interface Comparativo {
  mes: string;
  anterior: string;
  por_ramo: LinhaComparativo[];
  por_seguradora: LinhaComparativo[];
  total_anterior: string;
  total_atual: string;
  imposto_atual: string;
  liquido_atual: string;
  novos_qtd: number;
  novos_valor: string;
  sem_vinculo: number;
}

export interface PainelPagar {
  vence_hoje: string;
  atrasado: string;
  proximos_dias: string;
  aberto_ate_fim_mes: string;
  pago_no_mes: string;
  dias: number;
  titulos: Titulo[];
}

export interface ExtratoImportado {
  arquivo: string;
  codigo: string | null;
  seguradora: string | null;
  data: string | null;
  bruto: string;
  iss: string;
  liquido: string;
  linhas: number;
  gravadas: number;
  ja_importado: boolean;
  sem_vinculo: string[];
  divergencias: string[];
  avisos: string[];
  erro: string | null;
}

export interface FechamentoStatus {
  planilha_id: string | null;
  sincronizado_em: string | null;
  propostas: number;
  conta_servico: boolean;
  abas: string[];
  avisos: string[];
  novos_negocios: number | null;
}

export interface ItemPrevisao {
  tipo: 'parcela' | 'recorrente' | 'proposta';
  mes: string;
  seguradora: string;
  cliente: string;
  apolice: string | null;
  ramo: string | null;
  valor: string;
  detalhe: string;
}

export interface MesPrevisao {
  mes: string;
  total: string;
  parcelas: string;
  recorrentes: string;
  propostas: string;
  por_seguradora: Record<string, string>;
}

export interface Previsao {
  meses: MesPrevisao[];
  itens: ItemPrevisao[];
  atrasados: ItemPrevisao[];
}

export interface ArquivoMonitorado {
  id: number;
  nome: string;
  situacao: 'importado' | 'ja_importado' | 'ignorado' | 'erro';
  mensagem: string | null;
  extratos: string | null;
  processado_em: string;
}

export interface PastaStatus {
  configurada: boolean;
  intervalo_segundos: number;
  entidade_padrao: number | null;
  arquivos: ArquivoMonitorado[];
}

export interface UsuarioEu {
  id: number;
  nome: string;
  email: string;
  papel: 'admin' | 'leitor';
  areas: string[];
  somente_leitura: boolean;
  grupo: string | null;
}

export interface OpcaoPendencia {
  id: string;
  rotulo: string;
  campos?: string[];
}

export interface Pendencia {
  id: number;
  tipo: string;
  tipo_rotulo: string;
  titulo: string;
  descricao: string | null;
  opcoes: OpcaoPendencia[];
  sugestao: string | null;
  status: string;
  ocorrencias: number;
  criada_em: string;
  resolvida_em: string | null;
  resposta: { opcao: string; sempre: boolean } | null;
}

export interface ResumoPendencias {
  abertas: number;
  por_tipo: Record<string, number>;
  resolvidas_sozinho_no_mes: number;
  perguntas_no_mes: number;
  automatico_pct: number | null;
}

export interface Aprendido {
  id: string;
  tipo: string;
  descricao: string;
  ativa: boolean;
  vezes_aplicada: number | null;
  criada_em: string | null;
}

export interface Area {
  codigo: string;
  rotulo: string;
}

export interface GrupoAcesso {
  id?: number;
  nome: string;
  descricao: string | null;
  areas: string[];
  todas_entidades: boolean;
  entidades: number[];
  usuarios?: number;
}

export interface UsuarioAdmin {
  id: number;
  nome: string;
  email: string;
  papel: 'admin' | 'leitor';
  grupo_id: number | null;
  ativo: boolean;
  criado_em: string;
}

export interface EventoAuditoria {
  id: number;
  quando: string;
  usuario: string | null;
  acao: string;
  metodo: string | null;
  caminho: string;
  entidade_id: number | null;
  status: number | null;
  ip: string | null;
}

export interface Sugestao2 {
  titulo: string;
  texto: string;
  economia: string;
}

export interface FechamentoDados {
  entidade: string;
  rotulo: string;
  receita: string;
  despesas_total: string;
  dre: { resultado_liquido: string; margem_liquida_pct: number | null };
  resultado_anteriores: string[];
  despesas: { categoria: string; valor: string; media_3m: string; variacao_pct: number | null }[];
  atrasadas: { descricao: string; vencimento: string; saldo: string; dias: number }[];
  proximos_30: string;
  proximos_30_qtd: number;
  descontos_obtidos: string;
  comissoes: { bruta: string; anterior: string; novos_qtd: number; novos_valor: string } | null;
  pendencias_abertas: number;
  sugestoes: Sugestao2[];
  analise_ia: string | null;
}

// comissão das produtoras
export interface NivelComissao {
  nome: string;
  pct: number;
  pct_saude: number;
}
export interface PlanoComissao {
  id?: number;
  produtor: string;
  nome: string;
  ativo: boolean;
  niveis: NivelComissao[];
  regras: Record<string, number>;
  aliases_indicacao: string[];
  excluir_ramos: string[];
  usa_planilha_saude: boolean;
  planilha_saude_id: string | null;
  meses_para_pagar: number;
  contraparte_id: number | null;
  categoria_id: number | null;
  usuario_id: number | null;
}
export interface ItemComissao {
  item: string;
  base: string;
  pct: string;
  valor: string;
}
export interface ClientePL {
  chave: string;
  cliente: string;
  seguradora: string;
  ramo: string | null;
  pl: string;
  fonte: string;
  incluido: boolean;
}
export interface ApuracaoComissao {
  plano_id: number;
  produtor: string;
  nome: string;
  ano: number;
  mes: number;
  rotulo: string;
  patrimonial: {
    pl_clientes: string;
    ajuste: string;
    pl: string;
    faixas: string[] | null;
    nivel: string;
    nivel_idx: number | null;
    pct: string;
    proxima: string | null;
    falta: string | null;
    base: string;
    estornos: string;
    valor: string;
    meta_cadastrada: boolean;
  };
  indicacoes: {
    bruto: string;
    imposto: string;
    base: string;
    pct: string;
    valor: string;
    linhas: { data: string; seguradora: string; cliente: string; bruta: string }[];
  };
  saude: {
    linhas: number;
    fatura: string;
    pl: string;
    nivel: string;
    pct: string;
    proxima: string | null;
    itens: ItemComissao[];
    subtotal: string;
    meta_cadastrada: boolean;
  } | null;
  cartao_informativo: string;
  saldo_anterior: string;
  total: string;
  a_pagar: string;
  meta_pendente: boolean;
  clientes_pl: ClientePL[];
  linhas: {
    data: string;
    seguradora: string;
    ramo: string;
    cliente: string;
    bruta: string;
    parcela: string;
  }[];
  dias_passados?: number;
  dias_mes?: number;
  pl_projetado?: string;
  nivel_projetado?: string;
}
export interface HistoricoComissao {
  mes: number;
  rotulo: string;
  pl: string;
  nivel: string;
  base: string;
  pct: string;
  indicacoes: string;
  saude: string | null;
  total: string;
}
export interface SimulacaoComissao {
  atual: { nivel: string; total: string };
  simulado: {
    nivel: string;
    pct: string;
    total: string;
    pl: string;
    proxima: string | null;
    falta: string | null;
  };
  ganho: string;
}
export interface MetaMes {
  mes: number;
  tipo: 'patrimonial' | 'saude';
  faixas: number[];
}
