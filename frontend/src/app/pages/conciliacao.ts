import { Component, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../core/api';
import { mensagemErro } from '../core/auth';
import { EntidadeAtual } from '../core/entidade-atual';
import { BrlPipe, DataBrPipe, DocumentoPipe } from '../core/formato';
import { Categoria, Conta, Sugestao, Titulo, Transacao } from '../core/models';

@Component({
  selector: 'app-conciliacao',
  imports: [FormsModule, BrlPipe, DataBrPipe, DocumentoPipe],
  template: `
    <header class="cabecalho">
      <h1>Conciliação</h1>
      <div class="botoes">
        @if (pendentesComSugestao().length) {
          <button type="button" (click)="aceitarTodas()">
            Aceitar {{ pendentesComSugestao().length }} sugestões de categoria
          </button>
        }
        <button class="primario" type="button" (click)="automatica()">
          Conciliar automaticamente
        </button>
      </div>
    </header>
    @if (aviso()) {
      <p class="aviso">{{ aviso() }}</p>
    }
    <p class="sutil">
      {{ pendentes().length }} lançamentos do extrato sem título vinculado. Vincule a um título,
      categorize (e salve como regra) ou marque como "sem título" (tarifas, transferências).
    </p>

    <div class="cartao sem-padding">
      <table>
        <thead>
          <tr>
            <th>Data</th>
            <th>Conta</th>
            <th>Descrição</th>
            <th class="num">Valor</th>
            <th>Categoria</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          @for (t of pendentes(); track t.id) {
            <tr>
              <td>{{ t.data | dataBr }}</td>
              <td>{{ nomeConta(t.conta_id) }}</td>
              <td>
                {{ t.descricao }}
                @if (t.contraparte_nome || t.contraparte_documento) {
                  <div class="sutil pequeno">
                    {{ t.contraparte_nome }} {{ t.contraparte_documento | documento }}
                  </div>
                }
              </td>
              <td class="num" [class.neg]="+t.valor < 0">{{ t.valor | brl }}</td>
              <td>
                <select
                  [ngModel]="t.categoria_id"
                  (ngModelChange)="categorizar(t, $event)"
                  [attr.aria-label]="'Categoria de ' + t.descricao"
                >
                  <option [ngValue]="null">—</option>
                  @for (c of categorias(); track c.id) {
                    @if (c.ativo || c.id === t.categoria_id) {
                      <option [ngValue]="c.id">{{ c.nome }}</option>
                    }
                  }
                </select>
                @if (!t.categoria_id && sugestoes().get(t.id); as s) {
                  <button type="button" class="sugestao" [title]="s.motivo" (click)="aceitar(t, s)">
                    Sugestão: {{ s.categoria }} ({{ pct(s.confianca) }}%) · aceitar
                  </button>
                }
                @if (t.categoria_origem === 'ia' || t.categoria_origem === 'regra') {
                  <div class="sutil pequeno">
                    por {{ t.categoria_origem === 'ia' ? 'Claude' : 'regra' }}
                  </div>
                }
              </td>
              <td class="acoes">
                <button type="button" (click)="verCandidatos(t)">Títulos</button>
                <button type="button" class="link" (click)="ignorar(t)">Sem título</button>
              </td>
            </tr>
            @if (abertaId() === t.id) {
              <tr class="candidatos">
                <td colspan="6">
                  @for (c of candidatos(); track c.id) {
                    <div class="candidato">
                      <span
                        >{{ c.vencimento | dataBr }} · {{ c.descricao }} · saldo
                        {{ c.saldo | brl }}</span
                      >
                      <button type="button" class="primario" (click)="vincular(t, c)">
                        Vincular
                      </button>
                    </div>
                  } @empty {
                    <span class="sutil">Nenhum título em aberto com o mesmo valor (±15 dias).</span>
                  }
                </td>
              </tr>
            }
          } @empty {
            <tr>
              <td colspan="6" class="sutil">Tudo conciliado 🎉</td>
            </tr>
          }
        </tbody>
      </table>
    </div>
    <label class="regra"
      ><input type="checkbox" [(ngModel)]="salvarRegra" /> Ao categorizar, criar regra (pelo
      CPF/CNPJ de quem pagou/recebeu; sem ele, pela descrição)</label
    >
  `,
  styles: `
    .acoes {
      white-space: nowrap;
      text-align: right;
    }
    .candidatos td {
      background: var(--fundo-sutil);
    }
    .candidato {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      padding: 4px 0;
    }
    .aviso {
      background: var(--fundo-sutil);
      padding: 8px 12px;
      border-radius: 6px;
    }
    .botoes {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .sugestao {
      display: block;
      margin-top: 4px;
      font-size: 0.75rem;
      padding: 3px 8px;
      border-style: dashed;
      color: var(--primaria);
      background: transparent;
      text-align: left;
    }
    .regra {
      flex-direction: row;
      gap: 6px;
      margin-top: 12px;
      align-items: center;
    }
  `,
})
export class Conciliacao {
  private api = inject(Api);
  private ent = inject(EntidadeAtual);
  transacoes = signal<Transacao[]>([]);
  categorias = signal<Categoria[]>([]);
  contas = signal<Conta[]>([]);
  candidatos = signal<Titulo[]>([]);
  abertaId = signal<number | null>(null);
  aviso = signal('');
  salvarRegra = true;
  pendentes = computed(() => this.transacoes().filter((t) => !t.conciliada));
  sugestoes = signal(new Map<number, Sugestao>());
  pendentesComSugestao = computed(() =>
    this.pendentes().filter((t) => !t.categoria_id && this.sugestoes().has(t.id)),
  );

  constructor() {
    effect(() => {
      const eid = this.ent.id();
      if (!eid) return;
      this.api.categorias(eid).subscribe((c) => this.categorias.set(c));
      this.api.contas(eid).subscribe((c) => this.contas.set(c));
      this.carregar();
    });
  }

  carregar() {
    const eid = this.ent.id();
    if (!eid) return;
    this.api.transacoes(eid, { conciliada: false }).subscribe((t) => this.transacoes.set(t));
    this.api
      .sugestoes(eid)
      .subscribe((l) => this.sugestoes.set(new Map(l.map((s) => [s.transacao_id, s]))));
  }

  nomeConta(id: number) {
    return this.contas().find((c) => c.id === id)?.nome ?? '';
  }

  automatica() {
    const eid = this.ent.id();
    if (!eid) return;
    this.api.conciliarAutomatico(eid).subscribe((r) => {
      this.aviso.set(
        `${r.conciliadas} conciliadas · ${r.ambiguas} com mais de um título possível · ${r.sem_candidato} sem título correspondente`,
      );
      this.carregar();
    });
  }

  categorizar(t: Transacao, categoriaId: number | null) {
    this.api
      .categorizar(this.ent.id()!, t.id, categoriaId, this.salvarRegra && !!categoriaId)
      .subscribe({
        next: () => this.carregar(),
        error: (e) => this.aviso.set(mensagemErro(e)),
      });
  }

  pct(v: number) {
    return Math.round(v * 100);
  }

  aceitar(t: Transacao, s: Sugestao) {
    this.categorizar(t, s.categoria_id);
  }

  aceitarTodas() {
    const eid = this.ent.id();
    if (!eid) return;
    const itens = this.pendentesComSugestao().map((t) => ({
      transacao_id: t.id,
      categoria_id: this.sugestoes().get(t.id)!.categoria_id,
    }));
    this.api.aplicarCategorias(eid, itens).subscribe((r) => {
      this.aviso.set(`${r.alteradas} lançamentos categorizados pelas sugestões.`);
      this.carregar();
    });
  }

  verCandidatos(t: Transacao) {
    if (this.abertaId() === t.id) return this.abertaId.set(null);
    this.abertaId.set(t.id);
    this.candidatos.set([]);
    this.api.candidatos(this.ent.id()!, t.id).subscribe((c) => this.candidatos.set(c));
  }

  vincular(t: Transacao, titulo: Titulo) {
    this.api.vincular(this.ent.id()!, t.id, titulo.id).subscribe({
      next: () => {
        this.abertaId.set(null);
        this.carregar();
      },
      error: (e) => this.aviso.set(mensagemErro(e)),
    });
  }

  ignorar(t: Transacao) {
    this.api.ignorar(this.ent.id()!, t.id).subscribe(() => this.carregar());
  }
}
