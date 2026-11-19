import { Component, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../core/api';
import { EntidadeAtual } from '../core/entidade-atual';
import { DataBrPipe } from '../core/formato';
import { Aprendido } from '../core/models';

@Component({
  selector: 'app-aprendizado',
  imports: [FormsModule, DataBrPipe],
  template: `
    <header class="cabecalho">
      <h1>O que o sistema aprendeu</h1>
      <input
        placeholder="Buscar"
        [ngModel]="busca()"
        (ngModelChange)="busca.set($event)"
        aria-label="Buscar"
      />
    </header>
    <p class="sutil">
      Cada resposta com "Sempre fazer assim" vira uma regra. Desligue ou exclua a que não servir
      mais.
    </p>
    <section class="cartao sem-padding">
      <table>
        <thead>
          <tr>
            <th>Tipo</th>
            <th>Regra</th>
            <th class="num">Usada</th>
            <th>Desde</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          @for (r of filtradas(); track r.id) {
            <tr [class.inativa]="!r.ativa">
              <td class="sutil">{{ r.tipo }}</td>
              <td>{{ r.descricao }}</td>
              <td class="num">{{ r.vezes_aplicada ?? '—' }}</td>
              <td>{{ r.criada_em | dataBr }}</td>
              <td class="acoes">
                @if (r.id.startsWith('a:')) {
                  <button type="button" class="link so-admin" (click)="alternar(r)">
                    {{ r.ativa ? 'Desligar' : 'Ligar' }}
                  </button>
                }
                <button type="button" class="link perigo" (click)="excluir(r)">Excluir</button>
              </td>
            </tr>
          } @empty {
            <tr>
              <td colspan="5" class="sutil">Ainda nada aprendido.</td>
            </tr>
          }
        </tbody>
      </table>
    </section>
  `,
  styles: `
    .inativa td {
      opacity: 0.5;
    }
    .acoes {
      text-align: right;
      white-space: nowrap;
    }
    .perigo {
      color: var(--negativo);
    }
    section {
      overflow-x: auto;
    }
  `,
})
export class Aprendizado {
  private api = inject(Api);
  private ent = inject(EntidadeAtual);
  lista = signal<Aprendido[]>([]);
  busca = signal('');
  filtradas = computed(() => {
    const b = this.busca().toUpperCase();
    return this.lista().filter(
      (r) => !b || r.descricao.toUpperCase().includes(b) || r.tipo.toUpperCase().includes(b),
    );
  });

  constructor() {
    effect(() => this.carregar());
  }

  carregar() {
    const eid = this.ent.id();
    if (eid) this.api.aprendizado(eid).subscribe((l) => this.lista.set(l));
  }

  alternar(r: Aprendido) {
    const eid = this.ent.id();
    if (eid) this.api.alterarAprendido(eid, r.id, !r.ativa).subscribe(() => this.carregar());
  }

  excluir(r: Aprendido) {
    const eid = this.ent.id();
    if (eid && confirm(`Excluir a regra "${r.descricao}"?`))
      this.api.excluirAprendido(eid, r.id).subscribe(() => this.carregar());
  }
}
