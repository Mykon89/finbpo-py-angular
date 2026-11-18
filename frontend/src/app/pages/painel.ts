import { Component, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';
import { Api } from '../core/api';
import { EntidadeAtual } from '../core/entidade-atual';
import { BrlPipe, DataBrPipe } from '../core/formato';
import { Aging, Conta, DRE, PainelPagar } from '../core/models';

@Component({
  selector: 'app-painel',
  imports: [FormsModule, BrlPipe, DataBrPipe],
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

      @if (pagar(); as p) {
        <section class="grade-kpi">
          <div class="cartao kpi">
            <span>Vence hoje</span><strong>{{ p.vence_hoje | brl }}</strong>
          </div>
          <div class="cartao kpi">
            <span>Atrasado</span
            ><strong [class.neg]="+p.atrasado > 0">{{ p.atrasado | brl }}</strong>
          </div>
          <div class="cartao kpi">
            <span>Próximos 7 dias</span><strong>{{ p.proximos_dias | brl }}</strong>
          </div>
          <div class="cartao kpi">
            <span>Aberto até o fim do mês</span><strong>{{ p.aberto_ate_fim_mes | brl }}</strong>
          </div>
          <div class="cartao kpi">
            <span>Pago no mês</span><strong>{{ p.pago_no_mes | brl }}</strong>
          </div>
        </section>
        <section class="cartao sem-padding agenda">
          <header class="cabecalho-agenda">
            <h2>Contas a pagar em aberto</h2>
            <label
              >até daqui a
              <input
                type="number"
                min="0"
                class="dias"
                [ngModel]="dias()"
                (ngModelChange)="dias.set(+$event || 0)"
                aria-label="Dias à frente"
              />
              dias</label
            >
          </header>
          <table>
            <tbody>
              @for (t of p.titulos; track t.id) {
                <tr [class.neg]="t.vencimento < hoje">
                  <td>{{ t.vencimento | dataBr }}</td>
                  <td>{{ t.descricao }}</td>
                  <td class="num">{{ t.saldo | brl }}</td>
                </tr>
              } @empty {
                <tr>
                  <td class="sutil">Nada em aberto no período.</td>
                </tr>
              }
            </tbody>
          </table>
        </section>
      }

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
    .agenda {
      margin-bottom: 16px;
      max-height: 360px;
      overflow: auto;
    }
    .cabecalho-agenda {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 0 12px;
    }
    .cabecalho-agenda label {
      flex-direction: row;
      align-items: center;
      gap: 6px;
    }
    .dias {
      width: 70px;
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
  pagar = signal<PainelPagar | null>(null);
  dias = signal(7);
  hoje = new Date().toISOString().slice(0, 10);

  constructor() {
    effect(() => {
      const eid = this.ent.id();
      if (eid) this.api.painelPagar(eid, this.dias()).subscribe((p) => this.pagar.set(p));
    });
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
