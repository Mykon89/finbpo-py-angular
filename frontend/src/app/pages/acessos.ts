import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../core/api';
import { mensagemErro } from '../core/auth';
import { EntidadeAtual } from '../core/entidade-atual';
import { Area, GrupoAcesso, UsuarioAdmin } from '../core/models';

@Component({
  selector: 'app-acessos',
  imports: [FormsModule],
  template: `
    <header class="cabecalho"><h1>Usuários e acessos</h1></header>
    <p class="sutil">
      Diretoria e colaboradores entram como <strong>leitor</strong>: só veem as áreas e empresas do
      seu grupo e não alteram nada. Parceiros não recebem acesso.
    </p>
    @if (erro()) {
      <p class="erro">{{ erro() }}</p>
    }

    <section class="cartao">
      <h2>Grupos de acesso</h2>
      <div class="grupos">
        @for (g of grupos(); track g.id) {
          <button type="button" class="chip" [class.sel]="edit()?.id === g.id" (click)="editar(g)">
            {{ g.nome }} <span class="sutil">({{ g.usuarios }})</span>
          </button>
        }
        <button type="button" class="link" (click)="novo()">+ Novo grupo</button>
      </div>
      @if (edit(); as g) {
        <div class="form">
          <label>Nome <input [(ngModel)]="g.nome" aria-label="Nome do grupo" /></label>
          <label class="largo"
            >Descrição <input [(ngModel)]="g.descricao" aria-label="Descrição"
          /></label>
        </div>
        <h3>Áreas que o grupo pode ver</h3>
        <div class="marcas">
          @for (a of areas(); track a.codigo) {
            <label
              ><input
                type="checkbox"
                [checked]="g.areas.includes(a.codigo)"
                (change)="marcar(g.areas, a.codigo)"
              />
              {{ a.rotulo }}</label
            >
          }
        </div>
        <h3>Empresas</h3>
        <label class="linha"
          ><input type="checkbox" [(ngModel)]="g.todas_entidades" /> Todas as empresas</label
        >
        @if (!g.todas_entidades) {
          <div class="marcas">
            @for (e of ent.lista(); track e.id) {
              <label
                ><input
                  type="checkbox"
                  [checked]="g.entidades.includes(e.id)"
                  (change)="marcar(g.entidades, e.id)"
                />
                {{ e.nome }}</label
              >
            }
          </div>
        }
        <div class="botoes">
          @if (g.id) {
            <button type="button" class="link perigo" (click)="removerGrupo(g)">
              Excluir grupo
            </button>
          }
          <button type="button" class="primario" (click)="salvarGrupo(g)">Salvar grupo</button>
        </div>
      }
    </section>

    <section class="cartao sem-padding">
      <h2>Usuários</h2>
      <table>
        <thead>
          <tr>
            <th>Nome</th>
            <th>E-mail</th>
            <th>Papel</th>
            <th>Grupo</th>
            <th>Ativo</th>
          </tr>
        </thead>
        <tbody>
          @for (u of usuarios(); track u.id) {
            <tr>
              <td>{{ u.nome }}</td>
              <td>{{ u.email }}</td>
              <td>
                <select
                  [ngModel]="u.papel"
                  (ngModelChange)="alterar(u, { papel: $event })"
                  aria-label="Papel"
                >
                  <option value="admin">Administrador</option>
                  <option value="leitor">Leitor (só consulta)</option>
                </select>
              </td>
              <td>
                @if (u.papel === 'leitor') {
                  <select
                    [ngModel]="u.grupo_id"
                    (ngModelChange)="alterar(u, { grupo_id: $event })"
                    aria-label="Grupo"
                  >
                    @for (g of grupos(); track g.id) {
                      <option [ngValue]="g.id">{{ g.nome }}</option>
                    }
                  </select>
                }
              </td>
              <td>
                <input
                  type="checkbox"
                  [ngModel]="u.ativo"
                  (ngModelChange)="alterar(u, { ativo: $event })"
                  aria-label="Ativo"
                />
              </td>
            </tr>
          }
        </tbody>
      </table>
      <form class="form novo" (ngSubmit)="criar()">
        <label>Nome <input name="n" [(ngModel)]="nu.nome" required /></label>
        <label>E-mail <input name="e" type="email" [(ngModel)]="nu.email" required /></label>
        <label
          >Senha inicial
          <input
            name="s"
            type="password"
            [(ngModel)]="nu.senha"
            placeholder="10+ caracteres, letras e números"
        /></label>
        <label
          >Grupo
          <select name="g" [(ngModel)]="nu.grupo_id">
            @for (g of grupos(); track g.id) {
              <option [ngValue]="g.id">{{ g.nome }}</option>
            }
          </select>
        </label>
        <button type="submit" class="primario">Adicionar leitor</button>
      </form>
    </section>
  `,
  styles: `
    section {
      margin-bottom: 16px;
      overflow-x: auto;
    }
    h2 {
      font-size: 1rem;
    }
    .sem-padding h2 {
      padding: 12px 12px 0;
    }
    h3 {
      font-size: 0.85rem;
      margin: 14px 0 6px;
    }
    .grupos {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
    }
    .chip {
      border: 1px solid var(--borda);
      background: transparent;
      border-radius: 16px;
      padding: 4px 12px;
      cursor: pointer;
    }
    .chip.sel {
      border-color: var(--primaria, #2563eb);
      font-weight: 600;
    }
    .form {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 12px;
      align-items: end;
      margin-top: 12px;
    }
    .novo {
      padding: 12px;
    }
    .marcas {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 4px;
    }
    .marcas label,
    .linha {
      flex-direction: row;
      align-items: center;
      gap: 6px;
      font-weight: normal;
    }
    .botoes {
      display: flex;
      justify-content: flex-end;
      gap: 12px;
      margin-top: 12px;
    }
    .perigo {
      color: var(--negativo);
    }
  `,
})
export class Acessos {
  private api = inject(Api);
  protected ent = inject(EntidadeAtual);
  areas = signal<Area[]>([]);
  grupos = signal<GrupoAcesso[]>([]);
  usuarios = signal<UsuarioAdmin[]>([]);
  edit = signal<GrupoAcesso | null>(null);
  erro = signal('');
  nu = { nome: '', email: '', senha: '', grupo_id: null as number | null };

  constructor() {
    this.api.areas().subscribe((a) => this.areas.set(a));
    this.carregar();
  }

  private falha = (e: unknown) => this.erro.set(mensagemErro(e));

  carregar() {
    this.api.grupos().subscribe((g) => this.grupos.set(g));
    this.api.usuarios().subscribe((u) => this.usuarios.set(u));
  }

  editar(g: GrupoAcesso) {
    this.edit.set({ ...g, areas: [...g.areas], entidades: [...g.entidades] });
  }

  novo() {
    this.edit.set({ nome: '', descricao: '', areas: [], todas_entidades: false, entidades: [] });
  }

  marcar<T>(lista: T[], v: T) {
    const i = lista.indexOf(v);
    if (i >= 0) lista.splice(i, 1);
    else lista.push(v);
  }

  salvarGrupo(g: GrupoAcesso) {
    this.erro.set('');
    this.api
      .salvarGrupo(g)
      .subscribe({ next: (s) => (this.edit.set(null), this.carregar(), s), error: this.falha });
  }

  removerGrupo(g: GrupoAcesso) {
    if (g.id && confirm(`Excluir o grupo ${g.nome}?`))
      this.api
        .removerGrupo(g.id)
        .subscribe({ next: () => (this.edit.set(null), this.carregar()), error: this.falha });
  }

  alterar(u: UsuarioAdmin, dados: object) {
    this.erro.set('');
    this.api
      .alterarUsuario(u.id, dados)
      .subscribe({ next: () => this.carregar(), error: (e) => (this.falha(e), this.carregar()) });
  }

  criar() {
    this.erro.set('');
    this.api.criarUsuario({ ...this.nu, papel: 'leitor' }).subscribe({
      next: () => {
        this.nu = { nome: '', email: '', senha: '', grupo_id: null };
        this.carregar();
      },
      error: this.falha,
    });
  }
}
