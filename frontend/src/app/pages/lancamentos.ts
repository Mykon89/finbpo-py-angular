import { Component, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../core/api';
import { EntidadeAtual } from '../core/entidade-atual';
import { BrlPipe, DataBrPipe, DocumentoPipe } from '../core/formato';
import { Categoria, Conta, Transacao } from '../core/models';

function primeiroDiaMes(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`;
}

@Component({
  selector: 'app-lancamentos',
  imports: [FormsModule, BrlPipe, DataBrPipe, DocumentoPipe],
  template: `
    <header class="cabecalho"><h1>Lançamentos</h1></header>

    <div class="filtros cartao">
      <label
        >Conta
        <select [ngModel]="contaId()" (ngModelChange)="contaId.set($event)">
          <option [ngValue]="null">Todas</option>
          @for (c of contas(); track c.id) {
            <option [ngValue]="c.id">{{ c.nome }}</option>
          }
        </select>
      </label>
      <label>De <input type="date" [ngModel]="de()" (ngModelChange)="de.set($event)" /></label>
      <label>Até <input type="date" [ngModel]="ate()" (ngModelChange)="ate.set($event)" /></label>
      <label class="busca"
        >Buscar
        <input
          type="search"
          placeholder="Descrição, nome ou CPF/CNPJ"
          [ngModel]="busca()"
          (ngModelChange)="busca.set($event)"
      /></label>
    </div>

    <div class="resumo">
      <span
        >Entradas <strong class="pos">{{ totais().entradas | brl }}</strong></span
      >
      <span
        >Saídas <strong class="neg">{{ totais().saidas | brl }}</strong></span
      >
      <span
        >{{ filtradas().length }} lançamentos · {{ totais().comContraparte }} com pagador/recebedor
        identificado</span
      >
    </div>

    <div class="cartao sem-padding">
      <table>
        <thead>
          <tr>
            <th>Data</th>
            <th>Descrição</th>
            <th>Quem pagou / recebeu</th>
            <th>Categoria</th>
            <th class="num">Valor</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          @for (t of filtradas(); track t.id) {
            <tr>
              <td>{{ t.data | dataBr }}</td>
              <td>
                {{ t.descricao }}
                @if (t.complemento) {
                  <div class="sutil pequeno">{{ t.complemento }}</div>
                }
              </td>
              <td>
                @if (t.contraparte_nome || t.contraparte_documento) {
                  {{ t.contraparte_nome ?? '—' }}
                  @if (t.contraparte_documento) {
                    <div class="sutil pequeno">{{ t.contraparte_documento | documento }}</div>
                  }
                } @else {
                  <span class="sutil">—</span>
                }
              </td>
              <td>
                {{ nomeCategoria(t.categoria_id) }}
                @if (t.categoria_id && t.categoria_origem && t.categoria_origem !== 'manual') {
                  <div class="sutil pequeno">
                    {{
                      { ia: 'por Claude', regra: 'por regra', sugestao: 'sugestão aceita' }[
                        t.categoria_origem
                      ]
                    }}
                  </div>
                }
              </td>
              <td class="num" [class.neg]="+t.valor < 0">{{ t.valor | brl }}</td>
              <td>
                <span class="status" [attr.data-s]="t.conciliada ? 'pago' : 'aberto'">{{
                  t.conciliada ? 'conciliado' : 'pendente'
                }}</span>
              </td>
            </tr>
          } @empty {
            <tr>
              <td colspan="6" class="sutil">Nenhum lançamento no período.</td>
            </tr>
          }
        </tbody>
      </table>
    </div>
  `,
  styles: `
    .filtros {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px;
      margin-bottom: 12px;
    }
    .busca {
      grid-column: span 2;
    }
    .resumo {
      display: flex;
      flex-wrap: wrap;
      gap: 8px 24px;
      margin-bottom: 12px;
      color: var(--texto-sutil);
    }
    .resumo strong {
      font-variant-numeric: tabular-nums;
    }
    .pos {
      color: var(--texto);
    }
    .pequeno {
      font-size: 0.75rem;
    }
    @media (max-width: 600px) {
      .busca {
        grid-column: 1 / -1;
      }
    }
  `,
})
export class Lancamentos {
  private api = inject(Api);
  private ent = inject(EntidadeAtual);
  contas = signal<Conta[]>([]);
  categorias = signal<Categoria[]>([]);
  transacoes = signal<Transacao[]>([]);
  contaId = signal<number | null>(null);
  de = signal(primeiroDiaMes());
  ate = signal('');
  busca = signal('');

  filtradas = computed(() => {
    const q = this.busca().trim().toLowerCase();
    const qDig = q.replace(/\D/g, '');
    if (!q) return this.transacoes();
    return this.transacoes().filter(
      (t) =>
        `${t.descricao} ${t.complemento ?? ''} ${t.contraparte_nome ?? ''}`
          .toLowerCase()
          .includes(q) ||
        (qDig.length >= 3 && (t.contraparte_documento ?? '').includes(qDig)),
    );
  });

  totais = computed(() => {
    let entradas = 0;
    let saidas = 0;
    let comContraparte = 0;
    for (const t of this.filtradas()) {
      const v = Number(t.valor);
      if (v >= 0) entradas += v;
      else saidas += v;
      if (t.contraparte_documento || t.contraparte_nome) comContraparte++;
    }
    return { entradas, saidas, comContraparte };
  });

  constructor() {
    effect(() => {
      const eid = this.ent.id();
      if (!eid) return;
      this.api.contas(eid).subscribe((c) => this.contas.set(c));
      this.api.categorias(eid).subscribe((c) => this.categorias.set(c));
    });
    effect(() => {
      const eid = this.ent.id();
      if (!eid) return;
      this.api
        .transacoes(eid, {
          conta_id: this.contaId(),
          data_de: this.de() || undefined,
          data_ate: this.ate() || undefined,
        })
        .subscribe((t) => this.transacoes.set(t));
    });
  }

  nomeCategoria(id: number | null) {
    return this.categorias().find((c) => c.id === id)?.nome ?? '—';
  }
}
