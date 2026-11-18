import { Component, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../core/api';
import { mensagemErro } from '../core/auth';
import { EntidadeAtual } from '../core/entidade-atual';
import { BrlPipe } from '../core/formato';
import { Conta, ImportacaoResultado, TipoConta } from '../core/models';

@Component({
  selector: 'app-importar',
  imports: [FormsModule, BrlPipe],
  template: `
    <header class="cabecalho"><h1>Contas e extratos</h1></header>

    <div class="duas-colunas">
      <section class="cartao">
        <h2>Importar OFX</h2>
        <label
          >Conta
          <select [(ngModel)]="contaId" name="conta">
            @for (c of contas(); track c.id) {
              <option [ngValue]="c.id">{{ c.nome }}</option>
            }
          </select>
        </label>
        <label
          class="soltar"
          [class.sobre]="arrastando()"
          (dragover)="$event.preventDefault(); arrastando.set(true)"
          (dragleave)="arrastando.set(false)"
          (drop)="soltar($event)"
        >
          <input type="file" accept=".ofx,.OFX" (change)="escolher($event)" hidden />
          {{ arquivo()?.name ?? 'Arraste o arquivo .ofx aqui ou clique para escolher' }}
        </label>
        <button
          class="primario"
          type="button"
          [disabled]="!arquivo() || !contaId || enviando()"
          (click)="enviar()"
        >
          {{ enviando() ? 'Importando…' : 'Importar' }}
        </button>
        @if (erro()) {
          <p class="erro">{{ erro() }}</p>
        }
        @if (resultado(); as r) {
          <ul class="resultado">
            <li>
              Lidas: <strong>{{ r.total_lidas }}</strong>
            </li>
            <li>
              Novas: <strong>{{ r.total_novas }}</strong> · Duplicadas ignoradas: {{ r.duplicadas }}
            </li>
            <li>Categorizadas por regra: {{ r.categorizadas }}</li>
            <li>Conciliadas automaticamente: {{ r.conciliadas }}</li>
            @if (r.saldo_extrato) {
              <li>Saldo informado no extrato: {{ r.saldo_extrato | brl }}</li>
            }
          </ul>
        }
      </section>

      <section class="cartao">
        <h2>Nova conta</h2>
        <form class="formulario" (ngSubmit)="criarConta()">
          <label
            >Nome <input name="nome" [(ngModel)]="nova.nome" required placeholder="Ex.: Itaú PJ"
          /></label>
          <label
            >Tipo
            <select name="tipo" [(ngModel)]="nova.tipo">
              @for (t of tipos; track t[0]) {
                <option [ngValue]="t[0]">{{ t[1] }}</option>
              }
            </select>
          </label>
          <label
            >Banco (código) <input name="banco" [(ngModel)]="nova.banco_codigo" placeholder="341"
          /></label>
          <label>Agência <input name="agencia" [(ngModel)]="nova.agencia" /></label>
          <label
            >Conta
            <input name="numero" [(ngModel)]="nova.numero" placeholder="Igual ao ACCTID do OFX"
          /></label>
          <label
            >Saldo inicial
            <input name="saldo" type="number" step="0.01" [(ngModel)]="nova.saldo_inicial"
          /></label>
          <button class="primario" type="submit">Adicionar</button>
        </form>
      </section>
    </div>

    <section class="cartao sem-padding">
      <table>
        <thead>
          <tr>
            <th>Conta</th>
            <th>Tipo</th>
            <th>Banco</th>
            <th>Número</th>
            <th class="num">Saldo</th>
          </tr>
        </thead>
        <tbody>
          @for (c of contas(); track c.id) {
            <tr>
              <td>{{ c.nome }}</td>
              <td>{{ c.tipo }}</td>
              <td>{{ c.banco_codigo ?? '—' }}</td>
              <td>{{ c.numero ?? '—' }}</td>
              <td class="num">{{ c.saldo_atual | brl }}</td>
            </tr>
          } @empty {
            <tr>
              <td colspan="5" class="sutil">Nenhuma conta</td>
            </tr>
          }
        </tbody>
      </table>
    </section>
  `,
  styles: `
    .duas-colunas {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      margin-bottom: 16px;
      align-items: start;
    }
    .cartao {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .formulario {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }
    .soltar {
      border: 2px dashed var(--borda);
      border-radius: 8px;
      padding: 28px 16px;
      text-align: center;
      cursor: pointer;
      color: var(--texto-sutil);
    }
    .soltar.sobre {
      border-color: var(--primaria);
      color: var(--texto);
    }
    .resultado {
      margin: 0;
      padding-left: 18px;
    }
    @media (max-width: 900px) {
      .duas-colunas,
      .formulario {
        grid-template-columns: 1fr;
      }
    }
  `,
})
export class Importar {
  private api = inject(Api);
  private ent = inject(EntidadeAtual);
  contas = signal<Conta[]>([]);
  arquivo = signal<File | null>(null);
  arrastando = signal(false);
  enviando = signal(false);
  resultado = signal<ImportacaoResultado | null>(null);
  erro = signal('');
  contaId: number | null = null;
  tipos: [TipoConta, string][] = [
    ['corrente', 'Conta corrente'],
    ['poupanca', 'Poupança'],
    ['cartao', 'Cartão de crédito'],
    ['caixa', 'Caixa'],
    ['maquininha', 'Maquininha'],
  ];
  nova = this.vazia();

  constructor() {
    effect(() => this.carregar());
  }

  carregar() {
    const eid = this.ent.id();
    if (!eid) return;
    this.api.contas(eid).subscribe((c) => {
      this.contas.set(c);
      if (!c.some((x) => x.id === this.contaId)) this.contaId = c[0]?.id ?? null;
    });
  }

  escolher(ev: Event) {
    this.arquivo.set((ev.target as HTMLInputElement).files?.[0] ?? null);
    this.resultado.set(null);
  }

  soltar(ev: DragEvent) {
    ev.preventDefault();
    this.arrastando.set(false);
    this.arquivo.set(ev.dataTransfer?.files?.[0] ?? null);
    this.resultado.set(null);
  }

  enviar() {
    const eid = this.ent.id();
    const f = this.arquivo();
    if (!eid || !f || !this.contaId) return;
    this.erro.set('');
    this.enviando.set(true);
    this.api.importarOfx(eid, this.contaId, f).subscribe({
      next: (r) => {
        this.resultado.set(r);
        this.arquivo.set(null);
        this.enviando.set(false);
        this.carregar();
      },
      error: (e) => {
        this.erro.set(mensagemErro(e));
        this.enviando.set(false);
      },
    });
  }

  criarConta() {
    const eid = this.ent.id();
    if (!eid) return;
    const dados = Object.fromEntries(
      Object.entries(this.nova).filter(([, v]) => v !== '' && v !== null),
    );
    this.api.criarConta(eid, dados).subscribe({
      next: () => {
        this.nova = this.vazia();
        this.carregar();
      },
      error: (e) => this.erro.set(mensagemErro(e)),
    });
  }

  private vazia() {
    return {
      nome: '',
      tipo: 'corrente' as TipoConta,
      banco_codigo: '',
      agencia: '',
      numero: '',
      saldo_inicial: 0 as unknown as string,
    };
  }
}
