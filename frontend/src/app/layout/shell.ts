import { Component, OnInit, effect, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { Api } from '../core/api';
import { Auth } from '../core/auth';
import { Perfil } from '../core/perfil';
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
          <option [value]="e.id" [selected]="e.id === ent.id()">{{ e.nome }}</option>
        } @empty {
          <option value="">Nenhuma cadastrada</option>
        }
      </select>
      @if (ent.atual(); as a) {
        <span class="selo">{{ segmentos[a.segmento] }}</span>
      }
      @if (perfil.leitor()) {
        <span class="consulta">Modo consulta · {{ perfil.eu()?.grupo }}</span>
      }
      <nav>
        @for (m of menu; track m.link) {
          @if (perfil.pode(m.area)) {
            <a [routerLink]="m.link" routerLinkActive="ativo"
              >{{ m.rotulo }}
              @if (m.area === 'decisoes' && abertas()) {
                <span class="contador">{{ abertas() }}</span>
              }
            </a>
          }
        }
        @if (perfil.admin()) {
          <span class="secao">Administração</span>
          <a routerLink="/acessos" routerLinkActive="ativo">Usuários e acessos</a>
          <a routerLink="/auditoria" routerLinkActive="ativo">Auditoria</a>
          <a routerLink="/privacidade" routerLinkActive="ativo">Privacidade (LGPD)</a>
        }
      </nav>
      <button class="sair" type="button" (click)="auth.sair()">Sair</button>
    </aside>
    <main class="conteudo" [class.somente-leitura]="perfil.leitor()">
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
    .consulta {
      font-size: 0.75rem;
      background: rgba(255, 255, 255, 0.12);
      border-radius: 6px;
      padding: 4px 8px;
    }
    .secao {
      margin-top: 14px;
      font-size: 0.7rem;
      text-transform: uppercase;
      opacity: 0.6;
      padding: 0 10px;
    }
    .contador {
      background: #ef4444;
      color: #fff;
      border-radius: 10px;
      padding: 0 7px;
      font-size: 0.72rem;
      margin-left: 6px;
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
  protected perfil = inject(Perfil);
  private api = inject(Api);
  protected segmentos = SEGMENTOS;
  protected abertas = signal(0);
  protected readonly menu = [
    { link: '/painel', rotulo: 'Painel', area: 'painel' },
    { link: '/decisoes', rotulo: 'Central de decisões', area: 'decisoes' },
    { link: '/titulos/pagar', rotulo: 'Contas a pagar', area: 'pagar' },
    { link: '/titulos/receber', rotulo: 'Contas a receber', area: 'receber' },
    { link: '/recorrencias', rotulo: 'Recorrências', area: 'recorrencias' },
    { link: '/comissoes', rotulo: 'Comissões', area: 'comissoes' },
    { link: '/previsao', rotulo: 'Previsão de recebimentos', area: 'previsao' },
    { link: '/importar', rotulo: 'Contas e extratos', area: 'lancamentos' },
    { link: '/lancamentos', rotulo: 'Lançamentos', area: 'lancamentos' },
    { link: '/conciliacao', rotulo: 'Conciliação', area: 'conciliacao' },
    { link: '/plano-contas', rotulo: 'Plano de contas', area: 'plano_contas' },
    { link: '/aprendizado', rotulo: 'O que o sistema aprendeu', area: 'aprendizado' },
    { link: '/entidades', rotulo: 'Entidades', area: 'entidades' },
  ];

  constructor() {
    this.auth.aoSair.push(() => this.perfil.limpar());
    effect(() => {
      const eid = this.ent.id();
      if (!eid || !this.perfil.pode('decisoes')) return;
      this.api.resumoPendencias(eid).subscribe((r) => this.abertas.set(r.abertas));
    });
  }

  ngOnInit() {
    this.ent.carregar();
    if (!this.perfil.eu()) this.perfil.carregar().subscribe();
  }

  trocar(ev: Event) {
    this.ent.selecionar(Number((ev.target as HTMLSelectElement).value) || null);
  }
}
