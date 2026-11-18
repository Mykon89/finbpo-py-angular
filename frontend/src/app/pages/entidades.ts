import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../core/api';
import { mensagemErro } from '../core/auth';
import { EntidadeAtual } from '../core/entidade-atual';
import { SEGMENTOS, Segmento } from '../core/models';

@Component({
  selector: 'app-entidades',
  imports: [FormsModule],
  template: `
    <header class="cabecalho"><h1>Entidades</h1></header>
    <form class="cartao formulario" (ngSubmit)="salvar()">
      <label>Nome <input name="nome" [(ngModel)]="nome" required /></label>
      <label
        >Segmento
        <select name="segmento" [(ngModel)]="segmento">
          @for (s of segmentosLista; track s[0]) {
            <option [ngValue]="s[0]">{{ s[1] }}</option>
          }
        </select>
      </label>
      <label
        >{{ segmento === 'pf' ? 'CPF (opcional)' : 'CNPJ' }}
        <input name="documento" [(ngModel)]="documento"
      /></label>
      <label>E-mail <input name="email" type="email" [(ngModel)]="email" /></label>
      @if (erro()) {
        <p class="erro">{{ erro() }}</p>
      }
      <div><button class="primario" type="submit">Cadastrar</button></div>
    </form>
    <p class="sutil">Cada entidade recebe um plano de contas padrão do segmento.</p>

    <div class="cartao sem-padding">
      <table>
        <thead>
          <tr>
            <th>Nome</th>
            <th>Segmento</th>
            <th>Documento</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          @for (e of ent.lista(); track e.id) {
            <tr>
              <td>{{ e.nome }}</td>
              <td>{{ segmentos[e.segmento] }}</td>
              <td>{{ e.documento ?? '—' }}</td>
              <td class="num">
                @if (ent.id() === e.id) {
                  <strong>selecionada</strong>
                } @else {
                  <button type="button" (click)="ent.selecionar(e.id)">Selecionar</button>
                }
              </td>
            </tr>
          }
        </tbody>
      </table>
    </div>
  `,
  styles: `
    .formulario {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 12px;
      align-items: end;
    }
  `,
})
export class Entidades {
  private api = inject(Api);
  protected ent = inject(EntidadeAtual);
  segmentos = SEGMENTOS;
  segmentosLista = Object.entries(SEGMENTOS) as [Segmento, string][];
  nome = '';
  segmento: Segmento = 'corretora';
  documento = '';
  email = '';
  erro = signal('');

  salvar() {
    this.erro.set('');
    this.api
      .criarEntidade({
        nome: this.nome,
        segmento: this.segmento,
        tipo: this.segmento === 'pf' ? 'PF' : 'PJ',
        documento: this.documento || null,
        email: this.email || null,
      })
      .subscribe({
        next: (e) => {
          this.nome = this.documento = this.email = '';
          this.ent.carregar();
          this.ent.selecionar(e.id);
        },
        error: (err) => this.erro.set(mensagemErro(err)),
      });
  }
}
