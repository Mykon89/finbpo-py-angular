import { Component, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';
import { Api } from '../core/api';
import { EntidadeAtual } from '../core/entidade-atual';
import { BrlPipe } from '../core/formato';
import { Aging, Conta, DRE } from '../core/models';

@Component({
  selector: 'app-painel',
  imports: [FormsModule, BrlPipe],
  template: `
    <header class="cabecalho">
      <h1>Painel</h1>
      <input
        type="month"
        [ngModel]="competencia()"
        (ngModelChange)="competencia.set($event)"
        aria-label="Competência"
      />
    </header>

    @if (!ent.id()) {
      <p class="sutil">Cadastre uma entidade em <strong>Entidades</strong> para começar.</p>
    } @else {
      <section class="grade-kpi">
        <div class="cartao kpi">
          <span>Saldo em contas</span><strong>{{ saldoTotal() | brl }}</strong>
        </div>
        <div class="cartao kpi">
          <span>Resultado do mês</span
          ><strong [class.neg]="+(dre()?.resultado_liquido ?? 0) < 0">{{
            dre()?.resultado_liquido | brl
          }}</strong>
        </div>
        <div class="cartao kpi">
          <span>Margem líquida</span
          ><strong
            >{{ dre()?.margem_liquida_pct ?? '—'
            }}{{ dre()?.margem_liquida_pct != null ? '%' : '' }}</strong
          >
        </div>
        <div class="cartao kpi">
          <span>Sem categoria</span><strong>{{ dre()?.sem_categoria | brl }}</strong>
        </div>
      </section>

      <div class="duas-colunas">
        <section class="cartao">
          <h2>DRE gerencial (caixa)</h2>
          @if (dre(); as d) {
            <table>
              <tbody>
                @for (l of d.linhas; track l.rotulo) {
                  <tr [class.subtotal]="!l.grupo">
                    <td>{{ l.rotulo }}</td>
                    <td class="num" [class.neg]="+l.valor < 0">{{ l.valor | brl }}</td>
                  </tr>
                }
                <tr class="total">
                  <td>= Resultado líquido</td>
                  <td class="num">{{ d.resultado_liquido | brl }}</td>
                </tr>
              </tbody>
            </table>
            <p class="sutil">
              Movimentos não operacionais (transferências, aportes, retiradas):
              {{ d.nao_operacional | brl }}
            </p>
          }
        </section>

        <div class="pilha">
          <section class="cartao">
            <h2>Contas</h2>
            <table>
              <tbody>
                @for (c of contas(); track c.id) {
                  <tr>
                    <td>{{ c.nome }}</td>
                    <td class="num" [class.neg]="+c.saldo_atual < 0">{{ c.saldo_atual | brl }}</td>
                  </tr>
                } @empty {
                  <tr>
                    <td class="sutil">Nenhuma conta cadastrada</td>
                  </tr>
                }
              </tbody>
            </table>
          </section>
          @for (a of agings(); track a.tipo) {
            <section class="cartao">
              <h2>{{ a.tipo === 'pagar' ? 'A pagar' : 'A receber' }} por vencimento</h2>
              <table>
                <tbody>
                  @for (f of a.faixas; track f.faixa) {
                    <tr>
                      <td>{{ f.faixa }} ({{ f.quantidade }})</td>
                      <td class="num">{{ f.valor | brl }}</td>
                    </tr>
                  }
                </tbody>
              </table>
            </section>
          }
        </div>
      </div>
    }
  `,
  styles: `
    .grade-kpi {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }
    .kpi {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .kpi span {
      font-size: 0.8rem;
      color: var(--texto-sutil);
    }
    .kpi strong {
      font-size: 1.35rem;
      font-variant-numeric: tabular-nums;
    }
    .duas-colunas {
      display: grid;
      grid-template-columns: 3fr 2fr;
      gap: 16px;
      align-items: start;
    }
    .pilha {
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    .subtotal td {
      font-weight: 600;
      background: var(--fundo-sutil);
    }
    .total td {
      font-weight: 700;
      border-top: 2px solid var(--borda);
    }
    @media (max-width: 900px) {
      .duas-colunas {
        grid-template-columns: 1fr;
      }
    }
  `,
})
export class Painel {
  private api = inject(Api);
  protected ent = inject(EntidadeAtual);
  competencia = signal(new Date().toISOString().slice(0, 7));
  dre = signal<DRE | null>(null);
  contas = signal<Conta[]>([]);
  agings = signal<Aging[]>([]);
  saldoTotal = signal(0);

  constructor() {
    effect(() => {
      const eid = this.ent.id();
      const [ano, mes] = this.competencia().split('-').map(Number);
      if (!eid || !ano) return;
      forkJoin({
        dre: this.api.dre(eid, ano, mes),
        contas: this.api.contas(eid),
        pagar: this.api.aging(eid, 'pagar'),
        receber: this.api.aging(eid, 'receber'),
      }).subscribe((r) => {
        this.dre.set(r.dre);
        this.contas.set(r.contas);
        this.saldoTotal.set(
          r.contas
            .filter((c) => c.tipo !== 'cartao')
            .reduce((s, c) => s + Number(c.saldo_atual), 0),
        );
        this.agings.set([r.pagar, r.receber]);
      });
    });
  }
}
