import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import {
  AnaliseOFX,
  Aging,
  Categoria,
  ComplementoResultado,
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
