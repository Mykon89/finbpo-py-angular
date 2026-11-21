import { Component, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../core/api';
import { mensagemErro } from '../core/auth';
import { BrlPipe } from '../core/formato';
import { SimulacaoComissao } from '../core/models';

@Component({
  selector: 'app-simulador-comissao',
  imports: [FormsModule, BrlPipe],
  template: `
    <section class="cartao">
      <h2>Simulador: "se eu fechar mais…"</h2>
      <div class="linha">
        <label>Prêmio líquido a mais <input type="number" [(ngModel)]="pl" min="0" /></label>
        <label>Comissão a mais <input type="number" [(ngModel)]="com" min="0" /></label>
        <button type="button" class="primario-visivel" (click)="simular()">Simular</button>
      </div>
      @if (r(); as s) {
        <p>
          Hoje: <strong>{{ s.atual.nivel }}</strong> · {{ s.atual.total | brl }} → Simulado:
          <strong>{{ s.simulado.nivel }}</strong> ({{ +s.simulado.pct * 100 }}%) ·
          {{ s.simulado.total | brl }}
          <span class="pos">(+{{ s.ganho | brl }})</span>
        </p>
      }
      @if (erro()) {
        <p class="erro">{{ erro() }}</p>
      }
    </section>
  `,
  styles: `
    .linha {
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      align-items: end;
    }
    .pos {
      color: #15803d;
    }
  `,
})
export class SimuladorComissao {
  private api = inject(Api);
  eid = input.required<number>();
  plano = input<number | null>(null);
  ano = input.required<number>();
  mes = input.required<number>();
  pl = 0;
  com = 0;
  r = signal<SimulacaoComissao | null>(null);
  erro = signal('');

  simular() {
    this.api
      .simularComissao(
        this.eid(),
        this.plano(),
        this.ano(),
        this.mes(),
        this.pl || 0,
        this.com || 0,
      )
      .subscribe({
        next: (r) => this.r.set(r),
        error: (e) => this.erro.set(mensagemErro(e)),
      });
  }
}
