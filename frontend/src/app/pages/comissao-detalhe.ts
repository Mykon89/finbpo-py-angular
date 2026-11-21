import { Component, computed, input } from '@angular/core';
import { BrlPipe } from '../core/formato';
import { ApuracaoComissao, HistoricoComissao } from '../core/models';

/** Painel + apuração de uma produtora (usado na tela do admin e em "Minha comissão"). */
@Component({
  selector: 'app-comissao-detalhe',
  imports: [BrlPipe],
  template: `
    @if (a(); as x) {
      <section class="grade-kpi">
        <div class="cartao kpi">
          <span>PL para a meta</span><strong>{{ x.patrimonial.pl | brl }}</strong>
        </div>
        <div class="cartao kpi">
          <span>Nível</span><strong>{{ x.patrimonial.nivel }}</strong>
          <small>{{ +x.patrimonial.pct * 100 }}%</small>
        </div>
        <div class="cartao kpi">
          <span>Falta para a próxima faixa</span
          ><strong>{{ x.patrimonial.falta !== null ? (x.patrimonial.falta | brl) : '—' }}</strong>
        </div>
        @if (x.pl_projetado) {
          <div class="cartao kpi">
            <span>Projeção do mês ({{ x.dias_passados }}/{{ x.dias_mes }} dias)</span
            ><strong>{{ x.pl_projetado | brl }}</strong
            ><small>{{ x.nivel_projetado }}</small>
          </div>
        }
        <div class="cartao kpi">
          <span>Total {{ x.rotulo }}</span
          ><strong class="pos">{{ x.a_pagar | brl }}</strong>
        </div>
      </section>
      @if (x.meta_pendente) {
        <p class="aviso">
          Meta de {{ x.rotulo }} ainda não cadastrada: o valor final sai quando a meta for
          informada.
        </p>
      }
      @if (x.patrimonial.faixas; as f) {
        <section class="cartao">
          <h2>Faixas da meta</h2>
          <div class="faixas">
            @for (n of nomes; track n; let i = $index) {
              <div class="faixa" [class.atual]="x.patrimonial.nivel_idx === i">
                <strong>{{ n }}</strong><span
                  >{{ i === 0 ? 'até' : 'acima de' }}
                  {{ (i === 0 ? f[0] : f[i === 1 ? 0 : i]) | brl }}</span
                >
              </div>
            }
          </div>
          <div class="barra"><div [style.width.%]="progresso()"></div></div>
        </section>
      }
      <section class="cartao">
        <h2>Composição</h2>
        <table>
          <thead>
            <tr>
              <th>Item</th>
              <th class="num">Base</th>
              <th class="num">%</th>
              <th class="num">Valor</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                Comissão do extrato (estornos já abatidos: {{ x.patrimonial.estornos | brl }})
              </td>
              <td class="num">{{ x.patrimonial.base | brl }}</td>
              <td class="num">{{ +x.patrimonial.pct * 100 }}%</td>
              <td class="num">{{ x.patrimonial.valor | brl }}</td>
            </tr>
            @if (+x.indicacoes.bruto) {
              <tr>
                <td>Indicações pessoais ({{ x.indicacoes.linhas.length }}) — bruto − 18%</td>
                <td class="num">{{ x.indicacoes.base | brl }}</td>
                <td class="num">{{ +x.indicacoes.pct * 100 }}%</td>
                <td class="num">{{ x.indicacoes.valor | brl }}</td>
              </tr>
            }
            @if (x.saude; as s) {
              @for (i of s.itens; track i.item) {
                <tr>
                  <td>Saúde ({{ s.nivel }}): {{ i.item }}</td>
                  <td class="num">{{ i.base | brl }}</td>
                  <td class="num">{{ +i.pct * 100 }}%</td>
                  <td class="num">{{ i.valor | brl }}</td>
                </tr>
              }
            }
            @if (+x.saldo_anterior) {
              <tr>
                <td>Saldo negativo do mês anterior</td>
                <td></td>
                <td></td>
                <td class="num neg">{{ x.saldo_anterior | brl }}</td>
              </tr>
            }
            @if (+x.cartao_informativo) {
              <tr class="sutil">
                <td>Cartão (informativo, fora do cálculo)</td>
                <td class="num">{{ x.cartao_informativo | brl }}</td>
                <td></td>
                <td></td>
              </tr>
            }
            <tr>
              <td><strong>Total a receber</strong></td>
              <td></td>
              <td></td>
              <td class="num">
                <strong>{{ x.a_pagar | brl }}</strong>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
      <section class="cartao sem-padding">
        <h2>Lançamentos do mês ({{ x.linhas.length }})</h2>
        <table>
          <thead>
            <tr>
              <th>Data</th>
              <th>Seguradora</th>
              <th>Ramo</th>
              <th>Cliente</th>
              <th>Parcela</th>
              <th class="num">Bruta</th>
            </tr>
          </thead>
          <tbody>
            @for (l of x.linhas; track $index) {
              <tr>
                <td>{{ l.data.slice(8, 10) }}/{{ l.data.slice(5, 7) }}</td>
                <td>{{ l.seguradora }}</td>
                <td>{{ l.ramo }}</td>
                <td>{{ l.cliente }}</td>
                <td>{{ l.parcela }}</td>
                <td class="num" [class.neg]="+l.bruta < 0">{{ l.bruta | brl }}</td>
              </tr>
            }
          </tbody>
        </table>
      </section>
    }
    @if (historico().length) {
      <section class="cartao sem-padding">
        <h2>Histórico do ano</h2>
        <table>
          <thead>
            <tr>
              <th>Mês</th>
              <th class="num">PL</th>
              <th>Nível</th>
              <th class="num">Base</th>
              <th class="num">Indicações</th>
              <th class="num">Saúde</th>
              <th class="num">Total</th>
            </tr>
          </thead>
          <tbody>
            @for (h of historico(); track h.mes) {
              @if (+h.base || +h.total) {
                <tr>
                  <td>{{ h.rotulo }}</td>
                  <td class="num">{{ h.pl | brl }}</td>
                  <td>{{ h.nivel }}</td>
                  <td class="num">{{ h.base | brl }}</td>
                  <td class="num">{{ h.indicacoes | brl }}</td>
                  <td class="num">{{ h.saude !== null ? (h.saude | brl) : '—' }}</td>
                  <td class="num">{{ h.total | brl }}</td>
                </tr>
              }
            }
          </tbody>
        </table>
      </section>
    }
  `,
  styles: `
    .faixas {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
      gap: 8px;
    }
    .faixa {
      border: 1px solid var(--borda, #ddd);
      border-radius: 8px;
      padding: 8px;
      display: flex;
      flex-direction: column;
      font-size: 13px;
    }
    .faixa.atual {
      border-color: #1f4e79;
      background: #eef2f8;
    }
    .barra {
      margin-top: 10px;
      height: 8px;
      border-radius: 4px;
      background: #e5e7eb;
      overflow: hidden;
    }
    .barra div {
      height: 100%;
      background: #1f4e79;
    }
    .aviso {
      background: #fff7d6;
      padding: 8px 12px;
      border-radius: 6px;
    }
    .num {
      text-align: right;
    }
    .neg {
      color: #b91c1c;
    }
    .pos {
      color: #15803d;
    }
  `,
})
export class ComissaoDetalhe {
  a = input<ApuracaoComissao | null>(null);
  historico = input<HistoricoComissao[]>([]);
  nomes = ['SEM META', 'BRONZE', 'PRATA', 'OURO', 'DIAMANTE'];
  progresso = computed(() => {
    const x = this.a();
    const f = x?.patrimonial.faixas;
    if (!x || !f) return 0;
    return Math.min(100, (Number(x.patrimonial.pl) / Number(f[4] || 1)) * 100);
  });
}
