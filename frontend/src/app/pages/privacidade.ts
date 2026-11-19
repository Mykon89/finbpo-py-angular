import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../core/api';
import { mensagemErro } from '../core/auth';

@Component({
  selector: 'app-privacidade',
  imports: [FormsModule],
  template: `
    <header class="cabecalho"><h1>Privacidade (LGPD)</h1></header>
    <p class="sutil">
      Atenda os pedidos de titulares (art. 18): ver onde estão os dados de uma pessoa, entregar uma
      cópia ou anonimizar. Guia completo em docs/LGPD.md.
    </p>
    <form class="cartao busca" (ngSubmit)="buscar()">
      <label class="largo"
        >CPF ou nome completo <input name="b" [(ngModel)]="busca" required
      /></label>
      <button type="submit" class="primario">Buscar</button>
    </form>
    @if (erro()) {
      <p class="erro">{{ erro() }}</p>
    }
    @if (achado(); as a) {
      <section class="cartao">
        <h2>Onde aparece</h2>
        <ul>
          @for (k of chaves(a.ocorrencias); track k) {
            <li>
              {{ k }}: <strong>{{ a.ocorrencias[k] }}</strong>
            </li>
          }
        </ul>
        <div class="botoes">
          <button type="button" class="link" (click)="exportar()">Exportar cópia (JSON)</button>
          <button type="button" class="link perigo" (click)="anonimizar()">Anonimizar</button>
        </div>
        @if (msg()) {
          <p class="sutil">{{ msg() }}</p>
        }
      </section>
    }
  `,
  styles: `
    .busca {
      display: flex;
      gap: 12px;
      align-items: end;
      margin-bottom: 16px;
    }
    .largo {
      flex: 1;
    }
    .botoes {
      display: flex;
      gap: 16px;
    }
    .perigo {
      color: var(--negativo);
    }
  `,
})
export class Privacidade {
  private api = inject(Api);
  busca = '';
  achado = signal<{ ocorrencias: Record<string, number> } | null>(null);
  erro = signal('');
  msg = signal('');

  chaves(o: Record<string, number>) {
    return Object.keys(o);
  }

  buscar() {
    this.erro.set('');
    this.msg.set('');
    this.api
      .titular(this.busca)
      .subscribe({ next: (a) => this.achado.set(a), error: (e) => this.erro.set(mensagemErro(e)) });
  }

  exportar() {
    this.api.exportarTitular(this.busca).subscribe((d) => {
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(d, null, 2)], { type: 'application/json' }),
      );
      const a = document.createElement('a');
      a.href = url;
      a.download = 'dados-do-titular.json';
      a.click();
      URL.revokeObjectURL(url);
    });
  }

  anonimizar() {
    if (
      !confirm(
        'Anonimizar troca nome e CPF por um marcador em todos os registros e não pode ser desfeito. Continuar?',
      )
    )
      return;
    this.api.anonimizarTitular(this.busca).subscribe({
      next: (r) => (
        this.msg.set(`${r.registros_anonimizados} registro(s) anonimizado(s).`),
        this.buscar()
      ),
      error: (e) => this.erro.set(mensagemErro(e)),
    });
  }
}
