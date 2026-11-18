import { Component, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../core/api';
import { mensagemErro } from '../core/auth';
import { EntidadeAtual } from '../core/entidade-atual';
import { BrlPipe } from '../core/formato';
import { ItemPrevisao, Previsao } from '../core/models';

const MESES = ['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN', 'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ'];
const TIPOS: Record<string, string> = {
  parcela: 'Parcela restante',
  recorrente: 'Recorrente',
  proposta: 'Proposta fechada',
};

@Component({
  selector: 'app-previsao',
  imports: [FormsModule, BrlPipe],
  template: `
    <header class="cabecalho">
      <h1>Previsão de recebimentos</h1>
      <label class="linha"
        >Meses
        <select [ngModel]="meses()" (ngModelChange)="meses.set(+$event)" aria-label="Meses">
          @for (n of [3, 6, 12]; track n) {
            <option [ngValue]="n">{{ n }}</option>
          }
        </select>
      </label>
    </header>
    <p class="sutil">
      Comissões esperadas por mês: <strong>parcelas restantes</strong> (apólices pagas em n/total,
      pelo valor da última), <strong>recorrentes</strong> (saúde, odonto e vida que pagam todo mês,
      inclusive SulAmérica: média dos últimos 3 meses) e <strong>propostas fechadas</strong> no
      FECHAMENTO que ainda não tiveram comissão.
    </p>
    @if (erro()) {
      <p class="erro">{{ erro() }}</p>
    }

    @if (prev(); as p) {
      <section class="cartao sem-padding">
        <table>
          <thead>
            <tr>
              <th>Mês</th>
              <th class="num">Parcelas</th>
              <th class="num">Recorrentes</th>
              <th class="num">Propostas</th>
              <th class="num">Total</th>
              <th>Principais seguradoras</th>
            </tr>
          </thead>
          <tbody>
            @for (m of p.meses; track m.mes) {
              <tr
                [class.selecionado]="mesSel() === m.mes"
                (click)="mesSel.set(m.mes)"
                class="clicavel"
              >
                <td>
                  <strong>{{ rotulo(m.mes) }}</strong>
                </td>
                <td class="num">{{ m.parcelas | brl }}</td>
                <td class="num">{{ m.recorrentes | brl }}</td>
                <td class="num">{{ m.propostas | brl }}</td>
                <td class="num">
                  <strong>{{ m.total | brl }}</strong>
                </td>
                <td class="sutil pequeno">{{ topSeg(m.por_seguradora) }}</td>
              </tr>
            }
          </tbody>
        </table>
      </section>

      @if (p.atrasados.length) {
        <section class="cartao sem-padding">
          <h2 class="neg">Parcelas que não chegaram ({{ p.atrasados.length }})</h2>
          <table>
            <tbody>
              @for (a of p.atrasados; track $index) {
                <tr>
                  <td>{{ a.seguradora }}</td>
                  <td>{{ a.cliente }}</td>
                  <td class="sutil">{{ a.apolice }}</td>
                  <td class="num">{{ a.valor | brl }}</td>
                  <td class="sutil pequeno">{{ a.detalhe }}</td>
                </tr>
              }
            </tbody>
          </table>
        </section>
      }

      <section class="cartao sem-padding">
        <header class="cabecalho-tabela">
          <h2>Detalhe de {{ rotulo(mesSel()) }}</h2>
          <div class="filtros">
            <select [ngModel]="tipo()" (ngModelChange)="tipo.set($event)" aria-label="Tipo">
              <option value="">Todos os tipos</option>
              @for (t of tipos; track t[0]) {
                <option [value]="t[0]">{{ t[1] }}</option>
              }
            </select>
            <input
              placeholder="Seguradora ou cliente"
              [ngModel]="busca()"
              (ngModelChange)="busca.set($event)"
              aria-label="Buscar"
            />
          </div>
        </header>
        <table>
          <thead>
            <tr>
              <th>Tipo</th>
              <th>Seguradora</th>
              <th>Cliente</th>
              <th>Ramo</th>
              <th class="num">Valor</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            @for (i of detalhe(); track $index) {
              <tr>
                <td>
                  <span class="status" [attr.data-s]="css(i)">{{ rotuloTipo(i.tipo) }}</span>
                </td>
                <td>{{ i.seguradora }}</td>
                <td>
                  {{ i.cliente }}
                  @if (i.apolice) {
                    <div class="sutil pequeno">{{ i.apolice }}</div>
                  }
                </td>
                <td>{{ i.ramo }}</td>
                <td class="num">{{ i.valor | brl }}</td>
                <td class="sutil pequeno">{{ i.detalhe }}</td>
              </tr>
            } @empty {
              <tr>
                <td colspan="6" class="sutil">Nada previsto.</td>
              </tr>
            }
          </tbody>
        </table>
      </section>
    }
  `,
  styles: `
    .linha {
      flex-direction: row;
      align-items: center;
      gap: 8px;
    }
    section.cartao {
      margin-bottom: 16px;
      overflow-x: auto;
    }
    h2 {
      padding: 12px 12px 0;
      font-size: 0.95rem;
    }
    .cabecalho-tabela {
      display: flex;
      justify-content: space-between;
      align-items: end;
      gap: 12px;
      padding-right: 12px;
      flex-wrap: wrap;
    }
    .filtros {
      display: flex;
      gap: 8px;
    }
    .clicavel {
      cursor: pointer;
    }
    .selecionado td {
      background: var(--fundo-sutil);
    }
    .neg {
      color: var(--negativo);
    }
    .pequeno {
      font-size: 0.78rem;
    }
  `,
})
export class PrevisaoRecebimentos {
  private api = inject(Api);
  private ent = inject(EntidadeAtual);
  tipos = Object.entries(TIPOS);
  meses = signal(6);
  prev = signal<Previsao | null>(null);
  mesSel = signal('');
  tipo = signal('');
  busca = signal('');
  erro = signal('');

  detalhe = computed(() => {
    const b = this.busca().trim().toUpperCase();
    return (this.prev()?.itens ?? []).filter(
      (i) =>
        i.mes === this.mesSel() &&
        (!this.tipo() || i.tipo === this.tipo()) &&
        (!b || i.seguradora.includes(b) || i.cliente.toUpperCase().includes(b)),
    );
  });

  constructor() {
    effect(() => {
      const eid = this.ent.id();
      const n = this.meses();
      if (!eid) return;
      this.api.previsao(eid, n).subscribe({
        next: (p) => {
          this.prev.set(p);
          if (!p.meses.some((m) => m.mes === this.mesSel())) this.mesSel.set(p.meses[0]?.mes ?? '');
        },
        error: (e) => this.erro.set(mensagemErro(e)),
      });
    });
  }

  rotulo(mes: string) {
    if (!mes) return '';
    const [a, m] = mes.split('-');
    return `${MESES[Number(m) - 1]}/${a}`;
  }

  rotuloTipo(t: string) {
    return TIPOS[t] ?? t;
  }

  css(i: ItemPrevisao) {
    return i.tipo === 'proposta' ? 'parcial' : i.tipo === 'recorrente' ? 'pago' : 'aberto';
  }

  topSeg(por: Record<string, string>) {
    return Object.entries(por)
      .slice(0, 4)
      .map(([s, v]) => `${s} ${Number(v).toLocaleString('pt-BR', { maximumFractionDigits: 0 })}`)
      .join(' · ');
  }
}
