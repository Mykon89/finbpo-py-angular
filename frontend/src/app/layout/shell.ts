import { Component, OnInit, inject } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { Auth } from '../core/auth';
import { EntidadeAtual } from '../core/entidade-atual';
import { SEGMENTOS } from '../core/models';

@Component({
  selector: 'app-shell',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  template: `
    <aside class="lateral">
      <div class="marca">FinBPO</div>
      <label class="rotulo" for="sel-entidade">Entidade</label>
      <select id="sel-entidade" [value]="ent.id() ?? ''" (change)="trocar($event)">
        @for (e of ent.lista(); track e.id) {
          <option [value]="e.id">{{ e.nome }}</option>
        } @empty {
          <option value="">Nenhuma cadastrada</option>
        }
      </select>
      @if (ent.atual(); as a) {
        <span class="selo">{{ segmentos[a.segmento] }}</span>
      }
      <nav>
        <a routerLink="/painel" routerLinkActive="ativo">Painel</a>
        <a routerLink="/titulos/pagar" routerLinkActive="ativo">Contas a pagar</a>
        <a routerLink="/titulos/receber" routerLinkActive="ativo">Contas a receber</a>
        <a routerLink="/importar" routerLinkActive="ativo">Contas e extratos</a>
        <a routerLink="/lancamentos" routerLinkActive="ativo">Lançamentos</a>
        <a routerLink="/conciliacao" routerLinkActive="ativo">Conciliação</a>
        <a routerLink="/entidades" routerLinkActive="ativo">Entidades</a>
      </nav>
      <button class="sair" type="button" (click)="auth.sair()">Sair</button>
    </aside>
    <main class="conteudo">
      <router-outlet />
    </main>
  `,
  styles: `
    :host {
      display: grid;
      grid-template-columns: 240px 1fr;
      min-height: 100vh;
    }
    .lateral {
      background: var(--lateral);
      color: var(--lateral-texto);
      padding: 20px 16px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .marca {
      font-size: 1.4rem;
      font-weight: 700;
      margin-bottom: 16px;
    }
    .rotulo {
      font-size: 0.75rem;
      text-transform: uppercase;
      opacity: 0.7;
    }
    .selo {
      font-size: 0.75rem;
      opacity: 0.8;
    }
    nav {
      display: flex;
      flex-direction: column;
      margin-top: 16px;
      gap: 2px;
    }
    nav a {
      color: inherit;
      text-decoration: none;
      padding: 8px 10px;
      border-radius: 6px;
    }
    nav a:hover,
    nav a.ativo {
      background: rgba(255, 255, 255, 0.12);
    }
    .sair {
      margin-top: auto;
    }
    .conteudo {
      padding: 24px;
      overflow-x: auto;
    }
    @media (max-width: 760px) {
      :host {
        grid-template-columns: 1fr;
      }
      .lateral {
        padding: 12px 16px;
      }
      nav {
        flex-direction: row;
        flex-wrap: wrap;
        margin-top: 8px;
      }
      .sair {
        margin-top: 8px;
      }
      .conteudo {
        padding: 16px;
      }
    }
  `,
})
export class Shell implements OnInit {
  protected ent = inject(EntidadeAtual);
  protected auth = inject(Auth);
  protected segmentos = SEGMENTOS;

  ngOnInit() {
    this.ent.carregar();
  }

  trocar(ev: Event) {
    this.ent.selecionar(Number((ev.target as HTMLSelectElement).value) || null);
  }
}
