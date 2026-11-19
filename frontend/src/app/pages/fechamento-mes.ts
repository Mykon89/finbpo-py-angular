import { Component, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { Api } from '../core/api';
import { mensagemErro } from '../core/auth';
import { EntidadeAtual } from '../core/entidade-atual';
import { BrlPipe } from '../core/formato';
import { FechamentoDados } from '../core/models';
import { Perfil } from '../core/perfil';

@Component({
  selector: 'app-fechamento-mes',
  imports: [FormsModule, BrlPipe],
  template: `
    <header class="cabecalho">
      <h1>Fechamento do mês</h1>
      <div class="acoes">
        <input type="month" [ngModel]="mes()" (ngModelChange)="mes.set($event)" aria-label="Mês" />
        <button type="button" class="primario-visivel" (click)="baixar()">Baixar PDF</button>
      </div>
    </header>
    @if (erro()) {
      <p class="erro">{{ erro() }}</p>
    }
    @if (d(); as f) {
      <section class="grade-kpi">
        <div class="cartao kpi">
          <span>Receita</span><strong>{{ f.receita | brl }}</strong>
        </div>
        <div class="cartao kpi">
          <span>Despesas</span><strong>{{ f.despesas_total | brl }}</strong>
        </div>
        <div class="cartao kpi">
          <span>Resultado</span
          ><strong [class.neg]="+f.dre.resultado_liquido < 0">{{
            f.dre.resultado_liquido | brl
          }}</strong>
        </div>
        <div class="cartao kpi">
          <span>Economia possível</span><strong class="pos">{{ economia() | brl }}/mês</strong>
        </div>
        <div class="cartao kpi">
          <span>Contas em atraso</span
          ><strong [class.neg]="f.atrasadas.length">{{ f.atrasadas.length }}</strong>
        </div>
      </section>

      <section class="cartao">
        <h2>Onde dá para economizar</h2>
        @for (s of f.sugestoes; track s.titulo) {
          <div class="sug">
            <strong>{{ s.titulo }}</strong>
            @if (+s.economia > 0) {
              <span class="pos"> · até {{ s.economia | brl }}/mês</span>
            }
            <p class="sutil">{{ s.texto }}</p>
          </div>
        } @empty {
          <p class="sutil">Nenhum ponto de atenção pelas regras automáticas.</p>
        }
      </section>

      <section class="cartao">
        <h2>Análise do Claude</h2>
        @if (perfil.admin()) {
          <p class="sutil pequeno">
            Sem custo extra: no Claude (conector finbpo), peça "faça a análise do fechamento de
            {{ f.rotulo }} da {{ f.entidade }} e salve". Ou escreva/edite aqui.
          </p>
          <textarea rows="8" [(ngModel)]="texto" aria-label="Análise"></textarea>
          <div class="botoes">
            <button type="button" class="primario" (click)="salvar()">Salvar análise</button>
          </div>
        } @else {
          <p class="analise">{{ f.analise_ia || 'Ainda sem análise para este mês.' }}</p>
        }
      </section>

      <section class="cartao sem-padding">
        <h2>Despesas por categoria</h2>
        <table>
          <thead>
            <tr>
              <th>Categoria</th>
              <th class="num">No mês</th>
              <th class="num">Média 3 meses</th>
              <th class="num">Variação</th>
            </tr>
          </thead>
          <tbody>
            @for (x of f.despesas; track x.categoria) {
              <tr>
                <td>{{ x.categoria }}</td>
                <td class="num">{{ x.valor | brl }}</td>
                <td class="num">{{ x.media_3m | brl }}</td>
                <td class="num" [class.neg]="(x.variacao_pct ?? 0) >= 20">
                  {{
                    x.variacao_pct === null
                      ? '—'
                      : (x.variacao_pct > 0 ? '+' : '') + x.variacao_pct.toFixed(0) + '%'
                  }}
                </td>
              </tr>
            }
          </tbody>
        </table>
      </section>
    }

    @if (perfil.admin() && email(); as e) {
      <section class="cartao">
        <h2>E-mails automáticos</h2>
        @if (e.configurado) {
          <p class="sutil">
            Alerta diário a partir das {{ e.hora }}h e fechamento do mês anterior no dia
            {{ e.dia_fechamento }}, para {{ e.destinatarios.join(', ') }}.
          </p>
        } @else {
          <p class="sutil">Desligados: configure o e-mail no .env (veja docs/EMAIL.md).</p>
        }
        <div class="botoes">
          <button type="button" class="link" (click)="verPrevia()">Ver o e-mail de hoje</button>
          @if (e.configurado) {
            <button type="button" class="link" (click)="testar()">Enviar alerta agora</button>
            <button type="button" class="link" (click)="enviarFechamento()">
              Enviar este fechamento por e-mail
            </button>
          }
        </div>
        @if (msg()) {
          <p class="sutil">{{ msg() }}</p>
        }
        @if (previa(); as p) {
          <div class="previa" [innerHTML]="p"></div>
        }
      </section>
    }
  `,
  styles: `
    .acoes {
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .primario-visivel {
      background: var(--primaria, #2563eb);
      color: #fff;
      border: 0;
      border-radius: 8px;
      padding: 8px 12px;
      cursor: pointer;
    }
    .grade-kpi {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
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
      font-size: 1.25rem;
    }
    section.cartao {
      margin-bottom: 16px;
      overflow-x: auto;
    }
    .sem-padding h2 {
      padding: 12px 12px 0;
    }
    h2 {
      font-size: 1rem;
    }
    .sug {
      margin-bottom: 10px;
    }
    .sug p {
      margin: 2px 0 0;
    }
    .neg {
      color: var(--negativo);
    }
    .pos {
      color: #15803d;
    }
    textarea {
      width: 100%;
      font: inherit;
    }
    .botoes {
      display: flex;
      gap: 16px;
      justify-content: flex-end;
      margin-top: 8px;
      flex-wrap: wrap;
    }
    .analise {
      white-space: pre-wrap;
    }
    .pequeno {
      font-size: 0.8rem;
    }
    .previa {
      border: 1px solid var(--borda);
      border-radius: 8px;
      padding: 12px;
      margin-top: 12px;
      background: #fff;
      color: #111;
    }
  `,
})
export class FechamentoMes {
  private api = inject(Api);
  private ent = inject(EntidadeAtual);
  private san = inject(DomSanitizer);
  protected perfil = inject(Perfil);
  mes = signal(mesAnterior());
  d = signal<FechamentoDados | null>(null);
  email = signal<{
    configurado: boolean;
    destinatarios: string[];
    hora: number;
    dia_fechamento: number;
  } | null>(null);
  previa = signal<SafeHtml | null>(null);
  erro = signal('');
  msg = signal('');
  texto = '';
  economia = computed(() =>
    (this.d()?.sugestoes ?? []).reduce((s, x) => s + Number(x.economia), 0),
  );

  constructor() {
    effect(() => {
      const eid = this.ent.id();
      const [a, m] = this.mes().split('-').map(Number);
      if (!eid || !a) return;
      this.erro.set('');
      this.api.fechamentoMensal(eid, a, m).subscribe({
        next: (d) => {
          this.d.set(d);
          this.texto = d.analise_ia ?? '';
        },
        error: (e) => this.erro.set(mensagemErro(e)),
      });
    });
    effect(() => {
      if (this.perfil.admin()) this.api.statusEmail().subscribe((e) => this.email.set(e));
    });
  }

  private am(): [number, number] {
    const [a, m] = this.mes().split('-').map(Number);
    return [a, m];
  }

  baixar() {
    const eid = this.ent.id();
    if (!eid) return;
    const [a, m] = this.am();
    this.api.fechamentoPdf(eid, a, m).subscribe((b) => {
      const url = URL.createObjectURL(b);
      const l = document.createElement('a');
      l.href = url;
      l.download = `fechamento-${a}-${String(m).padStart(2, '0')}.pdf`;
      l.click();
      URL.revokeObjectURL(url);
    });
  }

  salvar() {
    const eid = this.ent.id();
    if (!eid) return;
    const [a, m] = this.am();
    this.api
      .salvarAnalise(eid, a, m, this.texto)
      .subscribe({
        next: () => this.msg.set('Análise salva.'),
        error: (e) => this.erro.set(mensagemErro(e)),
      });
  }

  verPrevia() {
    this.api.previaAlerta().subscribe((h) => this.previa.set(this.san.bypassSecurityTrustHtml(h)));
  }

  testar() {
    this.api
      .testarAlerta()
      .subscribe({
        next: (r) => this.msg.set(`Alerta: ${r.resultado}.`),
        error: (e) => this.erro.set(mensagemErro(e)),
      });
  }

  enviarFechamento() {
    const [a, m] = this.am();
    this.api
      .enviarFechamento(a, m)
      .subscribe({
        next: (r) => this.msg.set(`Fechamento: ${r.resultado}.`),
        error: (e) => this.erro.set(mensagemErro(e)),
      });
  }
}

function mesAnterior() {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}
