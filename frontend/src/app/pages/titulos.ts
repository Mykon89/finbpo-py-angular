import { Component, computed, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../core/api';
import { mensagemErro } from '../core/auth';
import { EntidadeAtual } from '../core/entidade-atual';
import { BrlPipe, DataBrPipe, hojeIso } from '../core/formato';
import { Categoria, StatusTitulo, TipoTitulo, Titulo } from '../core/models';

@Component({
  selector: 'app-titulos',
  imports: [FormsModule, BrlPipe, DataBrPipe],
  template: `
    <header class="cabecalho">
      <h1>{{ tipo() === 'pagar' ? 'Contas a pagar' : 'Contas a receber' }}</h1>
      <button class="primario" type="button" (click)="formAberto.set(!formAberto())">
        {{ formAberto() ? 'Fechar' : 'Novo título' }}
      </button>
    </header>

    @if (formAberto()) {
      <form class="cartao formulario" (ngSubmit)="salvar()">
        <label class="largo"
          >Descrição <input name="descricao" [(ngModel)]="novo.descricao" required
        /></label>
        <label
          >Valor (por parcela)
          <input
            name="valor"
            type="number"
            step="0.01"
            min="0.01"
            [(ngModel)]="novo.valor"
            required
        /></label>
        <label
          >1º vencimento
          <input name="vencimento" type="date" [(ngModel)]="novo.vencimento" required
        /></label>
        <label
          >Parcelas
          <input name="parcelas" type="number" min="1" max="360" [(ngModel)]="novo.parcelas"
        /></label>
        <label
          >Categoria
          <select name="categoria" [(ngModel)]="novo.categoria_id">
            <option [ngValue]="null">—</option>
            @for (c of categorias(); track c.id) {
              @if (c.ativo) {
                <option [ngValue]="c.id">{{ c.nome }}</option>
              }
            }
          </select>
        </label>
        <label class="largo"
          >Observação <input name="observacao" [(ngModel)]="novo.observacao"
        /></label>
        @if (erro()) {
          <p class="erro largo">{{ erro() }}</p>
        }
        <div class="largo"><button class="primario" type="submit">Salvar</button></div>
      </form>
    }

    <div class="filtros">
      @for (s of opcoesStatus; track s.valor) {
        <label class="chip"
          ><input
            type="checkbox"
            [checked]="status().includes(s.valor)"
            (change)="alternar(s.valor)"
          />
          {{ s.rotulo }}</label
        >
      }
      <span class="sutil"
        >Total em aberto: <strong>{{ totalAberto() | brl }}</strong></span
      >
    </div>

    <div class="cartao sem-padding">
      <table>
        <thead>
          <tr>
            <th>Vencimento</th>
            <th>Descrição</th>
            <th>Categoria</th>
            <th class="num">Valor</th>
            <th class="num">Saldo</th>
            <th>Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          @for (t of titulos(); track t.id) {
            <tr [class.atrasado]="atrasado(t)">
              <td>{{ t.vencimento | dataBr }}</td>
              <td>{{ t.descricao }}</td>
              <td>{{ nomeCategoria(t.categoria_id) }}</td>
              <td class="num">{{ t.valor | brl }}</td>
              <td class="num">{{ t.saldo | brl }}</td>
              <td>
                <span class="status" [attr.data-s]="t.status">{{ t.status }}</span>
              </td>
              <td class="acoes">
                @if (t.status === 'aberto' || t.status === 'parcial') {
                  <button type="button" (click)="baixar(t)">Baixar</button>
                  @if (!t.baixas.length) {
                    <button type="button" class="link" (click)="cancelar(t)">Cancelar</button>
                  }
                }
              </td>
            </tr>
          } @empty {
            <tr>
              <td colspan="7" class="sutil">Nenhum título</td>
            </tr>
          }
        </tbody>
      </table>
    </div>
  `,
  styles: `
    .formulario {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }
    .largo {
      grid-column: 1 / -1;
    }
    .filtros {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      margin-bottom: 12px;
    }
    .chip {
      display: inline-flex;
      flex-direction: row;
      gap: 4px;
      align-items: center;
      padding: 4px 10px;
      border: 1px solid var(--borda);
      border-radius: 999px;
    }
    .atrasado td:first-child {
      color: var(--negativo);
      font-weight: 600;
    }
    .acoes {
      white-space: nowrap;
      text-align: right;
    }
  `,
})
export class Titulos {
  private api = inject(Api);
  private ent = inject(EntidadeAtual);
  readonly tipo = input.required<TipoTitulo>();

  titulos = signal<Titulo[]>([]);
  categorias = signal<Categoria[]>([]);
  status = signal<StatusTitulo[]>(['aberto', 'parcial']);
  formAberto = signal(false);
  erro = signal('');
  hoje = hojeIso();
  opcoesStatus: { valor: StatusTitulo; rotulo: string }[] = [
    { valor: 'aberto', rotulo: 'Em aberto' },
    { valor: 'parcial', rotulo: 'Parcial' },
    { valor: 'pago', rotulo: 'Pago' },
    { valor: 'cancelado', rotulo: 'Cancelado' },
  ];
  novo = this.vazio();
  totalAberto = computed(() =>
    this.titulos()
      .filter((t) => t.status === 'aberto' || t.status === 'parcial')
      .reduce((s, t) => s + Number(t.saldo), 0),
  );

  constructor() {
    effect(() => {
      const eid = this.ent.id();
      if (!eid) return;
      this.api.categorias(eid).subscribe((c) => this.categorias.set(c));
    });
    effect(() => this.carregar());
  }

  carregar() {
    const eid = this.ent.id();
    if (!eid) return;
    this.api
      .titulos(eid, { tipo: this.tipo(), status: this.status() })
      .subscribe((t) => this.titulos.set(t));
  }

  alternar(s: StatusTitulo) {
    this.status.update((l) => (l.includes(s) ? l.filter((x) => x !== s) : [...l, s]));
  }

  nomeCategoria(id: number | null) {
    return this.categorias().find((c) => c.id === id)?.nome ?? '—';
  }

  atrasado(t: Titulo) {
    return (t.status === 'aberto' || t.status === 'parcial') && t.vencimento < this.hoje;
  }

  salvar() {
    const eid = this.ent.id();
    if (!eid) return;
    this.erro.set('');
    this.api.criarTitulo(eid, { ...this.novo, tipo: this.tipo() }).subscribe({
      next: () => {
        this.novo = this.vazio();
        this.formAberto.set(false);
        this.carregar();
      },
      error: (e) => this.erro.set(mensagemErro(e)),
    });
  }

  baixar(t: Titulo) {
    const data = prompt('Data da baixa (AAAA-MM-DD)', this.hoje);
    if (!data) return;
    this.api.baixarTitulo(t.entidade_id, t.id, data).subscribe({
      next: () => this.carregar(),
      error: (e) => alert(mensagemErro(e)),
    });
  }

  cancelar(t: Titulo) {
    if (!confirm(`Cancelar "${t.descricao}"?`)) return;
    this.api.cancelarTitulo(t.entidade_id, t.id).subscribe(() => this.carregar());
  }

  private vazio() {
    return {
      descricao: '',
      valor: null as number | null,
      vencimento: hojeIso(),
      parcelas: 1,
      categoria_id: null as number | null,
      observacao: '',
    };
  }
}
