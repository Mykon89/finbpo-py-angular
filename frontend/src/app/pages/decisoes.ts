import { Component, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../core/api';
import { mensagemErro } from '../core/auth';
import { EntidadeAtual } from '../core/entidade-atual';
import { DataBrPipe } from '../core/formato';
import { Categoria, OpcaoPendencia, Pendencia, ResumoPendencias } from '../core/models';
import { Perfil } from '../core/perfil';

@Component({
  selector: 'app-decisoes',
  imports: [FormsModule, DataBrPipe],
  template: `
    <header class="cabecalho">
      <h1>Central de decisões</h1>
      <div class="acoes">
        <select [ngModel]="status()" (ngModelChange)="status.set($event)" aria-label="Situação">
          <option value="aberta">Abertas</option>
          <option value="resolvida">Resolvidas</option>
          <option value="descartada">Descartadas</option>
        </select>
        <button type="button" class="primario" (click)="verificar()">Verificar agora</button>
      </div>
    </header>
    <p class="sutil">
      O que o sistema não soube resolver sozinho. Responda e deixe
      <strong>"Sempre fazer assim"</strong>
      marcado: a próxima situação igual é resolvida sem perguntar.
    </p>
    @if (resumo(); as r) {
      <section class="grade-kpi">
        <div class="cartao kpi">
          <span>Perguntas abertas</span><strong>{{ r.abertas }}</strong>
        </div>
        <div class="cartao kpi">
          <span>Resolvido sozinho no mês</span><strong>{{ r.resolvidas_sozinho_no_mes }}</strong>
        </div>
        <div class="cartao kpi">
          <span>Automático no mês</span
          ><strong>{{ r.automatico_pct === null ? '—' : r.automatico_pct + '%' }}</strong>
        </div>
      </section>
    }
    @if (erro()) {
      <p class="erro">{{ erro() }}</p>
    }
    @for (p of lista(); track p.id) {
      <article class="cartao pergunta">
        <header>
          <span class="status" data-s="parcial">{{ p.tipo_rotulo }}</span>
          <span class="sutil pequeno"
            >{{ p.criada_em | dataBr }} · {{ p.ocorrencias }} caso(s)</span
          >
        </header>
        <h2>{{ p.titulo }}</h2>
        @if (p.descricao) {
          <p class="sutil">{{ p.descricao }}</p>
        }
        @if (p.status === 'aberta' && !perfil.leitor()) {
          <div class="opcoes">
            @for (o of p.opcoes; track o.id) {
              <label class="opcao">
                <input
                  type="radio"
                  [name]="'p' + p.id"
                  [value]="o.id"
                  [(ngModel)]="escolha[p.id]"
                />
                {{ o.rotulo }}
                @if (o.id === p.sugestao) {
                  <span class="sugerida">sugerida</span>
                }
              </label>
              @if (escolha[p.id] === o.id && o.campos?.length) {
                <div class="campos">
                  @for (c of o.campos; track c) {
                    @if (c === 'categoria_id') {
                      <select [(ngModel)]="valores[p.id][c]" aria-label="Categoria">
                        <option [ngValue]="undefined">Escolha a categoria…</option>
                        @for (cat of categorias(); track cat.id) {
                          <option [ngValue]="cat.id">{{ cat.nome }}</option>
                        }
                      </select>
                    } @else {
                      <input
                        [placeholder]="rotuloCampo(c)"
                        [(ngModel)]="valores[p.id][c]"
                        [attr.aria-label]="rotuloCampo(c)"
                      />
                    }
                  }
                </div>
              }
            }
          </div>
          <footer>
            <label class="sempre"
              ><input type="checkbox" [(ngModel)]="sempre[p.id]" /> Sempre fazer assim</label
            >
            <button type="button" class="link perigo" (click)="descartar(p)">Descartar</button>
            <button
              type="button"
              class="primario"
              [disabled]="!escolha[p.id]"
              (click)="responder(p)"
            >
              Responder
            </button>
          </footer>
        } @else if (p.resposta) {
          <p class="pequeno">
            Resposta: <strong>{{ rotuloOpcao(p, p.resposta.opcao) }}</strong>
            {{ p.resposta.sempre ? '· virou regra' : '' }}
          </p>
        }
      </article>
    } @empty {
      <p class="cartao sutil">Nada por aqui. 🎉</p>
    }
  `,
  styles: `
    .acoes {
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .grade-kpi {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }
    .kpi {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .kpi span {
      font-size: 0.8rem;
      color: var(--texto-sutil);
    }
    .kpi strong {
      font-size: 1.3rem;
    }
    .pergunta {
      margin-bottom: 12px;
    }
    .pergunta header {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    h2 {
      font-size: 1rem;
      margin: 8px 0 4px;
    }
    .opcoes {
      display: flex;
      flex-direction: column;
      gap: 6px;
      margin: 10px 0;
    }
    .opcao {
      flex-direction: row;
      align-items: center;
      gap: 8px;
      font-weight: normal;
    }
    .sugerida {
      font-size: 0.72rem;
      background: #dcfce7;
      color: #166534;
      border-radius: 8px;
      padding: 0 6px;
    }
    .campos {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-left: 26px;
    }
    footer {
      display: flex;
      gap: 12px;
      align-items: center;
      justify-content: flex-end;
    }
    .sempre {
      flex-direction: row;
      align-items: center;
      gap: 6px;
      margin-right: auto;
    }
    .pequeno {
      font-size: 0.8rem;
    }
    .perigo {
      color: var(--negativo);
    }
  `,
})
export class Decisoes {
  private api = inject(Api);
  private ent = inject(EntidadeAtual);
  protected perfil = inject(Perfil);
  status = signal('aberta');
  lista = signal<Pendencia[]>([]);
  resumo = signal<ResumoPendencias | null>(null);
  categorias = signal<Categoria[]>([]);
  erro = signal('');
  escolha: Record<number, string> = {};
  sempre: Record<number, boolean> = {};
  valores: Record<number, Record<string, unknown>> = {};

  constructor() {
    effect(() => this.carregar());
  }

  carregar() {
    const eid = this.ent.id();
    const st = this.status();
    if (!eid) return;
    this.api.pendencias(eid, st).subscribe((l) => {
      for (const p of l) {
        this.escolha[p.id] ??= p.sugestao ?? '';
        this.sempre[p.id] ??= true;
        this.valores[p.id] ??= {};
      }
      this.lista.set(l);
    });
    this.api.resumoPendencias(eid).subscribe((r) => this.resumo.set(r));
    if (!this.categorias().length)
      this.api.categorias(eid).subscribe((c) => this.categorias.set(c.filter((x) => x.ativo)));
  }

  responder(p: Pendencia) {
    const eid = this.ent.id();
    if (!eid) return;
    this.erro.set('');
    this.api
      .responderPendencia(eid, p.id, this.escolha[p.id], this.valores[p.id], this.sempre[p.id])
      .subscribe({
        next: () => this.carregar(),
        error: (e) => this.erro.set(mensagemErro(e)),
      });
  }

  descartar(p: Pendencia) {
    const eid = this.ent.id();
    if (eid) this.api.descartarPendencia(eid, p.id).subscribe(() => this.carregar());
  }

  verificar() {
    const eid = this.ent.id();
    if (eid) this.api.verificarPendencias(eid).subscribe(() => this.carregar());
  }

  rotuloCampo(c: string) {
    return (
      { origem: 'Origem (ex.: KETTE)', produtor: 'Produtora', parceiro: 'Parceiro', ramo: 'Ramo' }[
        c
      ] ?? c
    );
  }

  rotuloOpcao(p: Pendencia, id: string) {
    return p.opcoes.find((o: OpcaoPendencia) => o.id === id)?.rotulo ?? id;
  }
}
