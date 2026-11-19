import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import {
  AnaliseOFX,
  Aprendido,
  Area,
  EventoAuditoria,
  GrupoAcesso,
  Pendencia,
  ResumoPendencias,
  UsuarioAdmin,
  UsuarioEu,
  Aging,
  Categoria,
  Comissao,
  Comparativo,
  ComplementoResultado,
  ExtratoComissao,
  ExtratoImportado,
  FechamentoDados,
  FechamentoStatus,
  PastaStatus,
  Previsao,
  ImportacaoPlanilha,
  PainelPagar,
  Recorrencia,
  Conta,
  DadosCNPJ,
  DRE,
  Entidade,
  ImportacaoResultado,
  StatusTitulo,
  Sugestao,
  TipoTitulo,
  Titulo,
  Transacao,
} from './models';

type Params = Record<string, string | number | boolean | string[] | undefined | null>;

function params(p: Params): HttpParams {
  let hp = new HttpParams();
  for (const [k, v] of Object.entries(p)) {
    if (v === undefined || v === null || v === '') continue;
    if (Array.isArray(v)) v.forEach((x) => (hp = hp.append(k, x)));
    else hp = hp.set(k, String(v));
  }
  return hp;
}

@Injectable({ providedIn: 'root' })
export class Api {
  private http = inject(HttpClient);
  private base = '/api';

  private e(id: number) {
    return `${this.base}/entidades/${id}`;
  }

  // perfil, decisões e aprendizado
  eu() {
    return this.http.get<UsuarioEu>(`${this.base}/auth/eu`);
  }
  pendencias(eid: number, status = 'aberta') {
    return this.http.get<Pendencia[]>(`${this.e(eid)}/pendencias`, { params: params({ status }) });
  }
  resumoPendencias(eid: number) {
    return this.http.get<ResumoPendencias>(`${this.e(eid)}/pendencias/resumo`);
  }
  responderPendencia(eid: number, id: number, opcao: string, valores: object, sempre: boolean) {
    return this.http.post<Pendencia>(`${this.e(eid)}/pendencias/${id}/responder`, {
      opcao,
      valores,
      sempre,
    });
  }
  descartarPendencia(eid: number, id: number) {
    return this.http.post<Pendencia>(`${this.e(eid)}/pendencias/${id}/descartar`, {});
  }
  verificarPendencias(eid: number) {
    return this.http.post<object>(`${this.e(eid)}/pendencias/verificar`, {});
  }
  aprendizado(eid: number) {
    return this.http.get<Aprendido[]>(`${this.e(eid)}/aprendizado`);
  }
  alterarAprendido(eid: number, id: string, ativa: boolean) {
    return this.http.patch(`${this.e(eid)}/aprendizado/${id}`, { ativa });
  }
  excluirAprendido(eid: number, id: string) {
    return this.http.delete<void>(`${this.e(eid)}/aprendizado/${id}`);
  }

  // fechamento mensal e e-mail
  fechamentoMensal(eid: number, ano: number, mes: number) {
    return this.http.get<FechamentoDados>(`${this.e(eid)}/fechamento-mensal`, {
      params: params({ ano, mes }),
    });
  }
  fechamentoPdf(eid: number, ano: number, mes: number) {
    return this.http.get(`${this.e(eid)}/fechamento-mensal/pdf`, {
      params: params({ ano, mes }),
      responseType: 'blob',
    });
  }
  salvarAnalise(eid: number, ano: number, mes: number, texto: string) {
    return this.http.put(`${this.e(eid)}/fechamento-mensal/analise`, { ano, mes, texto });
  }
  statusEmail() {
    return this.http.get<{
      configurado: boolean;
      destinatarios: string[];
      hora: number;
      dia_fechamento: number;
    }>(`${this.base}/admin/email`);
  }
  previaAlerta() {
    return this.http.get(`${this.base}/admin/alertas/previa`, { responseType: 'text' });
  }
  testarAlerta() {
    return this.http.post<{ resultado: string }>(`${this.base}/admin/alertas/testar`, {});
  }
  enviarFechamento(ano: number, mes: number) {
    return this.http.post<{ resultado: string }>(`${this.base}/admin/fechamento/enviar`, null, {
      params: params({ ano, mes }),
    });
  }

  // administração
  areas() {
    return this.http.get<Area[]>(`${this.base}/admin/areas`);
  }
  grupos() {
    return this.http.get<GrupoAcesso[]>(`${this.base}/admin/grupos`);
  }
  salvarGrupo(g: GrupoAcesso) {
    return g.id
      ? this.http.put<GrupoAcesso>(`${this.base}/admin/grupos/${g.id}`, g)
      : this.http.post<GrupoAcesso>(`${this.base}/admin/grupos`, g);
  }
  removerGrupo(id: number) {
    return this.http.delete<void>(`${this.base}/admin/grupos/${id}`);
  }
  usuarios() {
    return this.http.get<UsuarioAdmin[]>(`${this.base}/admin/usuarios`);
  }
  criarUsuario(u: object) {
    return this.http.post<UsuarioAdmin>(`${this.base}/admin/usuarios`, u);
  }
  alterarUsuario(id: number, u: object) {
    return this.http.patch<UsuarioAdmin>(`${this.base}/admin/usuarios/${id}`, u);
  }
  auditoria(filtro: { usuario_id?: number; acao?: string; de?: string; ate?: string }) {
    return this.http.get<EventoAuditoria[]>(`${this.base}/admin/auditoria`, {
      params: params(filtro),
    });
  }
  titular(busca: string) {
    return this.http.get<{
      ocorrencias: Record<string, number>;
      amostra: Record<string, Record<string, string>[]>;
    }>(`${this.base}/admin/privacidade/titular`, { params: params({ busca }) });
  }
  exportarTitular(busca: string) {
    return this.http.get<object>(`${this.base}/admin/privacidade/titular/exportar`, {
      params: params({ busca }),
    });
  }
  anonimizarTitular(busca: string) {
    return this.http.post<{ registros_anonimizados: number }>(
      `${this.base}/admin/privacidade/titular/anonimizar`,
      {
        busca,
        confirmar: true,
      },
    );
  }

  // entidades
  entidades() {
    return this.http.get<Entidade[]>(`${this.base}/entidades`);
  }
  criarEntidade(dados: Partial<Entidade>) {
    return this.http.post<Entidade>(`${this.base}/entidades`, dados);
  }
  atualizarEntidade(id: number, dados: Partial<Entidade>) {
    return this.http.patch<Entidade>(`${this.base}/entidades/${id}`, dados);
  }
  consultarCnpj(cnpj: string) {
    return this.http.get<DadosCNPJ>(`${this.base}/cnpj/${cnpj}`);
  }
  categorias(eid: number) {
    return this.http.get<Categoria[]>(`${this.e(eid)}/categorias`);
  }
  criarCategoria(eid: number, dados: { nome: string; grupo_dre: string }) {
    return this.http.post<Categoria>(`${this.e(eid)}/categorias`, dados);
  }
  atualizarCategoria(
    eid: number,
    id: number,
    dados: Partial<Pick<Categoria, 'nome' | 'grupo_dre' | 'ativo'>>,
  ) {
    return this.http.patch<Categoria>(`${this.e(eid)}/categorias/${id}`, dados);
  }
  removerCategoria(eid: number, id: number) {
    return this.http.delete<void>(`${this.e(eid)}/categorias/${id}`);
  }

  // contas
  contas(eid: number) {
    return this.http.get<Conta[]>(`${this.e(eid)}/contas`);
  }
  criarConta(eid: number, dados: Partial<Conta>) {
    return this.http.post<Conta>(`${this.e(eid)}/contas`, dados);
  }
  importarOfx(eid: number, contaId: number, arquivo: File) {
    const form = new FormData();
    form.append('arquivo', arquivo);
    return this.http.post<ImportacaoResultado>(
      `${this.e(eid)}/contas/${contaId}/importar-ofx`,
      form,
    );
  }

  analisarOfx(eid: number, arquivo: File) {
    const form = new FormData();
    form.append('arquivo', arquivo);
    return this.http.post<AnaliseOFX>(`${this.e(eid)}/ofx/analisar`, form);
  }
  importarOfxAuto(
    eid: number,
    arquivo: File,
    opcoes: { conta_id?: number | null; nome?: string; saldo_inicial?: string | number | null },
    complementos: File[] = [],
  ) {
    const form = new FormData();
    form.append('arquivo', arquivo);
    if (opcoes.conta_id) form.append('conta_id', String(opcoes.conta_id));
    if (opcoes.nome) form.append('nome', opcoes.nome);
    if (
      opcoes.saldo_inicial !== null &&
      opcoes.saldo_inicial !== undefined &&
      opcoes.saldo_inicial !== ''
    )
      form.append('saldo_inicial', String(opcoes.saldo_inicial));
    complementos.forEach((f) => form.append('complementos', f));
    return this.http.post<ImportacaoResultado>(`${this.e(eid)}/ofx/importar`, form);
  }
  complementarConta(eid: number, contaId: number, arquivos: File[]) {
    const form = new FormData();
    arquivos.forEach((f) => form.append('arquivos', f));
    return this.http.post<ComplementoResultado>(
      `${this.e(eid)}/contas/${contaId}/complementar`,
      form,
    );
  }

  // planilha, comissões, recorrências
  importarPlanilha(eid: number, arquivo: File) {
    const form = new FormData();
    form.append('arquivo', arquivo);
    return this.http.post<ImportacaoPlanilha>(`${this.e(eid)}/importar-planilha`, form);
  }
  fechamento(eid: number) {
    return this.http.get<FechamentoStatus>(`${this.e(eid)}/fechamento`);
  }
  configurarFechamento(eid: number, planilha: string | null) {
    return this.http.put<FechamentoStatus>(`${this.e(eid)}/fechamento`, { planilha });
  }
  sincronizarFechamento(eid: number) {
    return this.http.post<FechamentoStatus>(`${this.e(eid)}/fechamento/sincronizar`, {});
  }
  importarFechamento(eid: number, arquivo: File) {
    const form = new FormData();
    form.append('arquivo', arquivo);
    return this.http.post<FechamentoStatus>(`${this.e(eid)}/fechamento/importar`, form);
  }
  pasta(eid: number) {
    return this.http.get<PastaStatus>(`${this.e(eid)}/pasta`);
  }
  varrerPasta(eid: number) {
    return this.http.post<PastaStatus>(`${this.e(eid)}/pasta/varrer`, {});
  }
  previsao(eid: number, meses: number) {
    return this.http.get<Previsao>(`${this.e(eid)}/comissoes/previsao`, {
      params: params({ meses }),
    });
  }
  importarExtratos(eid: number, arquivos: File[]) {
    const form = new FormData();
    arquivos.forEach((f) => form.append('arquivos', f));
    return this.http.post<ExtratoImportado[]>(`${this.e(eid)}/extratos-comissao/importar`, form);
  }
  comissoes(
    eid: number,
    filtro: {
      mes?: string;
      seguradora?: string;
      ramo?: string;
      extrato_id?: number;
      busca?: string;
      sem_vinculo?: boolean;
    },
  ) {
    return this.http.get<Comissao[]>(`${this.e(eid)}/comissoes`, { params: params(filtro) });
  }
  atualizarComissao(eid: number, id: number, dados: Partial<Comissao>) {
    return this.http.patch<Comissao>(`${this.e(eid)}/comissoes/${id}`, dados);
  }
  comparativo(eid: number, mes: string) {
    return this.http.get<Comparativo>(`${this.e(eid)}/comissoes/comparativo`, {
      params: params({ mes }),
    });
  }
  extratosComissao(eid: number, mes?: string) {
    return this.http.get<ExtratoComissao[]>(`${this.e(eid)}/extratos-comissao`, {
      params: params({ mes }),
    });
  }
  recorrencias(eid: number) {
    return this.http.get<Recorrencia[]>(`${this.e(eid)}/recorrencias`);
  }
  criarRecorrencia(eid: number, dados: Partial<Recorrencia>) {
    return this.http.post<Recorrencia>(`${this.e(eid)}/recorrencias`, dados);
  }
  atualizarRecorrencia(eid: number, id: number, dados: Partial<Recorrencia>) {
    return this.http.patch<Recorrencia>(`${this.e(eid)}/recorrencias/${id}`, dados);
  }
  removerRecorrencia(eid: number, id: number) {
    return this.http.delete<void>(`${this.e(eid)}/recorrencias/${id}`);
  }
  gerarRecorrencias(eid: number, ate?: string, recorrencia_id?: number) {
    return this.http.post<Titulo[]>(`${this.e(eid)}/recorrencias/gerar`, null, {
      params: params({ ate, recorrencia_id }),
    });
  }
  painelPagar(eid: number, dias: number) {
    return this.http.get<PainelPagar>(`${this.e(eid)}/painel-pagar`, { params: params({ dias }) });
  }

  // títulos
  titulos(
    eid: number,
    filtro: {
      tipo?: TipoTitulo;
      status?: StatusTitulo[];
      vencimento_de?: string;
      vencimento_ate?: string;
    },
  ) {
    return this.http.get<Titulo[]>(`${this.e(eid)}/titulos`, { params: params(filtro) });
  }
  criarTitulo(eid: number, dados: object) {
    return this.http.post<Titulo[]>(`${this.e(eid)}/titulos`, dados);
  }
  baixarTitulo(eid: number, id: number, data: string) {
    return this.http.post<Titulo>(`${this.e(eid)}/titulos/${id}/baixar`, { data });
  }
  cancelarTitulo(eid: number, id: number) {
    return this.http.post<Titulo>(`${this.e(eid)}/titulos/${id}/cancelar`, {});
  }

  // transações e conciliação
  transacoes(
    eid: number,
    filtro: {
      conciliada?: boolean;
      sem_categoria?: boolean;
      conta_id?: number | null;
      data_de?: string;
      data_ate?: string;
    },
  ) {
    return this.http.get<Transacao[]>(`${this.e(eid)}/transacoes`, { params: params(filtro) });
  }
  categorizar(eid: number, id: number, categoria_id: number | null, criar_regra: boolean) {
    return this.http.patch<Transacao>(`${this.e(eid)}/transacoes/${id}`, {
      categoria_id,
      criar_regra,
    });
  }
  sugestoes(eid: number) {
    return this.http.get<Sugestao[]>(`${this.e(eid)}/categorizacao/sugestoes`);
  }
  aplicarCategorias(eid: number, itens: { transacao_id: number; categoria_id: number }[]) {
    return this.http.post<{ alteradas: number }>(`${this.e(eid)}/categorizacao/aplicar`, {
      itens,
      origem: 'sugestao',
    });
  }
  ignorar(eid: number, id: number) {
    return this.http.post<Transacao>(`${this.e(eid)}/transacoes/${id}/ignorar`, {});
  }
  conciliarAutomatico(eid: number) {
    return this.http.post<{ conciliadas: number; ambiguas: number; sem_candidato: number }>(
      `${this.e(eid)}/conciliacao/automatica`,
      {},
    );
  }
  candidatos(eid: number, transacaoId: number) {
    return this.http.get<Titulo[]>(`${this.e(eid)}/conciliacao/${transacaoId}/candidatos`);
  }
  vincular(eid: number, transacao_id: number, titulo_id: number) {
    return this.http.post<Titulo>(`${this.e(eid)}/conciliacao/vincular`, {
      transacao_id,
      titulo_id,
    });
  }

  // relatórios
  dre(eid: number, ano: number, mes: number) {
    return this.http.get<DRE>(`${this.e(eid)}/relatorios/dre`, { params: params({ ano, mes }) });
  }
  aging(eid: number, tipo: TipoTitulo) {
    return this.http.get<Aging>(`${this.e(eid)}/relatorios/aging`, { params: params({ tipo }) });
  }
}
