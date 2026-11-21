import { Component, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../core/api';
import { mensagemErro } from '../core/auth';
import { EntidadeAtual } from '../core/entidade-atual';
import { ApuracaoComissao, HistoricoComissao } from '../core/models';
import { salvarBlob } from './baixar';
import { ComissaoDetalhe } from './comissao-detalhe';
import { SimuladorComissao } from './simulador-comissao';

const hoje = new Date();
const mesAtual = `${hoje.getFullYear()}-${String(hoje.getMonth() + 1).padStart(2, '0')}`;

@Component({
  selector: 'app-minha-comissao',
  imports: [FormsModule, ComissaoDetalhe, SimuladorComissao],
  template: `
    <header class="cabecalho">
      <h1>Minha comissão</h1>
      <div class="acoes">
        <input type="month" [ngModel]="mes()" (ngModelChange)="mes.set($event)" aria-label="Mês" />
        <button type="button" class="primario-visivel" (click)="pdf()">Baixar demonstrativo</button>
      </div>
    </header>
    @if (erro()) {
      <p class="erro">{{ erro() }}</p>
    }
    @if (eid(); as e) {
      <app-comissao-detalhe [a]="a()" [historico]="hist()" />
      <app-simulador-comissao [eid]="e" [ano]="am()[0]" [mes]="am()[1]" />
    }
  `,
})
export class MinhaComissao {
  private api = inject(Api);
  private ent = inject(EntidadeAtual);
  eid = this.ent.id;
  mes = signal(mesAtual);
  a = signal<ApuracaoComissao | null>(null);
  hist = signal<HistoricoComissao[]>([]);
  erro = signal('');

  constructor() {
    effect(() => {
      const eid = this.ent.id();
      const [a, m] = this.am();
      if (!eid || !a) return;
      this.api.minhaComissao(eid, a, m).subscribe({
        next: (r) => {
          this.erro.set('');
          this.a.set(this.mes() === mesAtual ? r.painel : r.apuracao);
          this.hist.set(r.historico);
        },
        error: (e) => this.erro.set(mensagemErro(e)),
      });
    });
  }

  am(): [number, number] {
    const [a, m] = this.mes().split('-').map(Number);
    return [a, m];
  }

  pdf() {
    const eid = this.ent.id();
    const [a, m] = this.am();
    if (eid)
      this.api
        .demonstrativoComissao(eid, null, a, m)
        .subscribe((b) => salvarBlob(b, `minha-comissao-${this.mes()}.pdf`));
  }
}
