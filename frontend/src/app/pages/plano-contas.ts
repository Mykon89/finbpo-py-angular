import { Component, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../core/api';
import { mensagemErro } from '../core/auth';
import { EntidadeAtual } from '../core/entidade-atual';
import { Categoria, GRUPOS_DRE, GrupoDRE } from '../core/models';

@Component({
  selector: 'app-plano-contas',
  imports: [FormsModule],
  template: `
    <header class="cabecalho">
      <h1>Plano de contas</h1>
      <label class="chip"
        ><input type="checkbox" [(ngModel)]="mostrarInativas" /> Mostrar desativadas</label
      >
    </header>
    <p class="sutil">
      As categorias classificam os lançamentos e montam a DRE. O grupo define em que linha do
      relatório a categoria entra.
    </p>

    <form class="cartao nova" (ngSubmit)="criar()">
      <label class="largo"
        >Nova categoria
        <input
          name="nome"
          [(ngModel)]="nome"
          required
          minlength="2"
          placeholder="Ex.: Seguros, Limpeza e conservação"
      /></label>
      <label
        >Grupo da DRE
        <select name="grupo" [(ngModel)]="grupo">
          @for (g of grupos; track g.valor) {
            <option [ngValue]="g.valor">{{ g.rotulo }}</option>
          }
        </select>
      </label>
      <button class="primario" type="submit" [disabled]="nome.trim().length < 2">Adicionar</button>
      <p class="sutil pequeno largo">{{ ajuda(grupo) }}</p>
    </form>

    @if (erro()) {
      <p class="erro">{{ erro() }}</p>
    }

    @for (g of porGrupo(); track g.valor) {
      <section class="cartao sem-padding grupo">
        <h2>
          {{ g.rotulo }} <span class="sutil pequeno">· {{ g.ajuda }}</span>
        </h2>
        <table>
          <tbody>
            @for (c of g.categorias; track c.id) {
              <tr [class.inativa]="!c.ativo">
                <td class="nome">
                  @if (editandoId() === c.id) {
                    <input
                      [(ngModel)]="nomeEdicao"
                      (keydown.enter)="salvarNome(c)"
                      (keydown.escape)="editandoId.set(null)"
                      [attr.aria-label]="'Novo nome de ' + c.nome"
                    />
                  } @else {
                    {{ c.nome }}
                    @if (!c.ativo) {
                      <span class="status">desativada</span>
                    }
                  }
                </td>
                <td class="uso sutil">
                  {{ c.qtd_lancamentos }} lanç. · {{ c.qtd_titulos }} títulos
                </td>
                <td>
                  <select
                    [ngModel]="c.grupo_dre"
                    (ngModelChange)="mudarGrupo(c, $event)"
                    [attr.aria-label]="'Grupo de ' + c.nome"
                  >
                    @for (o of grupos; track o.valor) {
                      <option [ngValue]="o.valor">{{ o.rotulo }}</option>
                    }
                  </select>
                </td>
                <td class="acoes">
                  @if (editandoId() === c.id) {
                    <button type="button" class="primario" (click)="salvarNome(c)">Salvar</button>
                    <button type="button" class="link" (click)="editandoId.set(null)">
                      Cancelar
                    </button>
                  } @else {
                    <button type="button" class="link" (click)="editar(c)">Renomear</button>
                    <button type="button" class="link" (click)="alternar(c)">
                      {{ c.ativo ? 'Desativar' : 'Reativar' }}
                    </button>
                    @if (!c.qtd_lancamentos && !c.qtd_titulos) {
                      <button type="button" class="link perigo" (click)="remover(c)">
                        Excluir
                      </button>
                    }
                  }
                </td>
              </tr>
            } @empty {
              <tr>
                <td class="sutil">Nenhuma categoria neste grupo.</td>
              </tr>
            }
          </tbody>
        </table>
      </section>
    }
  `,
  styles: `
    .chip {
      flex-direction: row;
      align-items: center;
      gap: 6px;
    }
    .nova {
      display: grid;
      grid-template-columns: 2fr 1fr auto;
      gap: 12px;
      align-items: end;
      margin-bottom: 16px;
    }
    .largo {
      grid-column: 1 / 2;
    }
    .nova p {
      grid-column: 1 / -1;
      margin: 0;
    }
    .grupo {
      margin-bottom: 12px;
    }
    .grupo h2 {
      padding: 12px 12px 0;
      font-size: 0.95rem;
    }
    .nome {
      width: 40%;
    }
    .nome input {
      width: 100%;
    }
    .uso {
      white-space: nowrap;
      font-size: 0.8rem;
    }
    .acoes {
      text-align: right;
      white-space: nowrap;
    }
    .inativa td {
      opacity: 0.6;
    }
    .perigo {
      color: var(--negativo);
    }
    .pequeno {
      font-size: 0.8rem;
      font-weight: normal;
    }
    @media (max-width: 700px) {
      .nova {
        grid-template-columns: 1fr;
      }
      .uso {
        display: none;
      }
    }
  `,
})
export class PlanoContas {
  private api = inject(Api);
  private ent = inject(EntidadeAtual);
  grupos = GRUPOS_DRE;
  categorias = signal<Categoria[]>([]);
  editandoId = signal<number | null>(null);
  erro = signal('');
  nome = '';
  grupo: GrupoDRE = 'despesas_adm';
  nomeEdicao = '';
  private mostrar = signal(false);

  get mostrarInativas() {
    return this.mostrar();
  }
  set mostrarInativas(v: boolean) {
    this.mostrar.set(v);
  }

  porGrupo = computed(() =>
    GRUPOS_DRE.map((g) => ({
      ...g,
      categorias: this.categorias().filter(
        (c) => c.grupo_dre === g.valor && (c.ativo || this.mostrar()),
      ),
    })),
  );

  constructor() {
    effect(() => this.carregar());
  }

  carregar() {
    const eid = this.ent.id();
    if (!eid) return;
    this.api.categorias(eid).subscribe((c) => this.categorias.set(c));
  }

  ajuda(g: GrupoDRE) {
    return GRUPOS_DRE.find((x) => x.valor === g)?.ajuda ?? '';
  }

  criar() {
    const eid = this.ent.id();
    if (!eid) return;
    this.erro.set('');
    this.api.criarCategoria(eid, { nome: this.nome, grupo_dre: this.grupo }).subscribe({
      next: () => {
        this.nome = '';
        this.carregar();
      },
      error: (e) => this.erro.set(mensagemErro(e)),
    });
  }

  editar(c: Categoria) {
    this.nomeEdicao = c.nome;
    this.editandoId.set(c.id);
  }

  salvarNome(c: Categoria) {
    if (this.nomeEdicao.trim() === c.nome) return this.editandoId.set(null);
    this.atualizar(c, { nome: this.nomeEdicao }, () => this.editandoId.set(null));
  }

  mudarGrupo(c: Categoria, grupo: GrupoDRE) {
    if (grupo === c.grupo_dre) return;
    if (
      c.qtd_lancamentos &&
      !confirm(`Mudar o grupo de "${c.nome}" altera também a DRE dos meses já lançados. Continuar?`)
    ) {
      this.carregar();
      return;
    }
    this.atualizar(c, { grupo_dre: grupo });
  }

  alternar(c: Categoria) {
    this.atualizar(c, { ativo: !c.ativo });
  }

  remover(c: Categoria) {
    const eid = this.ent.id();
    if (!eid || !confirm(`Excluir a categoria "${c.nome}"?`)) return;
    this.api.removerCategoria(eid, c.id).subscribe({
      next: () => this.carregar(),
      error: (e) => this.erro.set(mensagemErro(e)),
    });
  }

  private atualizar(c: Categoria, dados: Partial<Categoria>, depois?: () => void) {
    const eid = this.ent.id();
    if (!eid) return;
    this.erro.set('');
    this.api.atualizarCategoria(eid, c.id, dados).subscribe({
      next: (n) => {
        this.categorias.update((l) => l.map((x) => (x.id === n.id ? n : x)));
        depois?.();
      },
      error: (e) => {
        this.erro.set(mensagemErro(e));
        this.carregar();
      },
    });
  }
}
