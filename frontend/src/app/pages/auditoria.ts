import { Component, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../core/api';
import { EventoAuditoria } from '../core/models';

@Component({
  selector: 'app-auditoria',
  imports: [FormsModule],
  template: `
    <header class="cabecalho">
      <h1>Auditoria</h1>
      <div class="filtros">
        <select [ngModel]="acao()" (ngModelChange)="acao.set($event)" aria-label="Ação">
          <option value="">Todas as ações</option>
          @for (a of acoes; track a) {
            <option [value]="a">{{ a }}</option>
          }
        </select>
        <input type="date" [ngModel]="de()" (ngModelChange)="de.set($event)" aria-label="De" />
      </div>
    </header>
    <p class="sutil">
      Logins, todas as alterações e as consultas dos leitores. Guardado por 5 anos, sem o conteúdo
      dos dados.
    </p>
    <section class="cartao sem-padding">
      <table>
        <thead>
          <tr>
            <th>Quando</th>
            <th>Quem</th>
            <th>Ação</th>
            <th>Rota</th>
            <th class="num">Status</th>
            <th>IP</th>
          </tr>
        </thead>
        <tbody>
          @for (e of eventos(); track e.id) {
            <tr [class.neg]="(e.status ?? 0) >= 400">
              <td>{{ quando(e.quando) }}</td>
              <td>{{ e.usuario ?? '—' }}</td>
              <td>{{ e.acao }}</td>
              <td class="pequeno">{{ e.metodo }} {{ e.caminho }}</td>
              <td class="num">{{ e.status }}</td>
              <td class="sutil pequeno">{{ e.ip }}</td>
            </tr>
          }
        </tbody>
      </table>
    </section>
  `,
  styles: `
    .filtros {
      display: flex;
      gap: 8px;
    }
    .pequeno {
      font-size: 0.78rem;
    }
    .neg td {
      color: var(--negativo);
    }
    section {
      overflow-x: auto;
    }
  `,
})
export class AuditoriaPage {
  private api = inject(Api);
  acoes = ['login', 'login_falhou', 'leitura', 'criacao', 'alteracao', 'exclusao', 'exportacao'];
  acao = signal('');
  de = signal('');
  eventos = signal<EventoAuditoria[]>([]);

  constructor() {
    effect(() =>
      this.api
        .auditoria({ acao: this.acao(), de: this.de() })
        .subscribe((e) => this.eventos.set(e)),
    );
  }

  quando(iso: string) {
    return new Date(iso).toLocaleString('pt-BR');
  }
}
