import { Component, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../core/api';
import { mensagemErro } from '../core/auth';
import { EntidadeAtual } from '../core/entidade-atual';
import { BrlPipe, DataBrPipe } from '../core/formato';
import { AnaliseOFX, Conta, ImportacaoResultado, TipoConta } from '../core/models';

const TIPOS: [TipoConta, string][] = [
  ['corrente', 'Conta corrente'],
  ['poupanca', 'Poupança'],
  ['cartao', 'Cartão de crédito'],
  ['caixa', 'Caixa'],
  ['maquininha', 'Maquininha'],
];

@Component({
  selector: 'app-importar',
  imports: [FormsModule, BrlPipe, DataBrPipe],
  template: `
    <header class="cabecalho"><h1>Contas e extratos</h1></header>

    <section class="cartao bloco">
      <h2>Importar extrato OFX</h2>
      <label
        class="soltar"
        [class.sobre]="arrastando()"
        (dragover)="$event.preventDefault(); arrastando.set(true)"
        (dragleave)="arrastando.set(false)"
        (drop)="soltar($event)"
      >
        <input type="file" accept=".ofx,.OFX" (change)="escolher($event)" hidden />
        @if (arquivo(); as a) {
          <strong>{{ a.name }}</strong> · clique para trocar
        } @else {
          Arraste o arquivo .ofx aqui ou clique para escolher
        }
      </label>
      @if (analisando()) {
        <p class="sutil">Lendo o arquivo…</p>
      }
      @if (erro()) {
        <p class="erro">{{ erro() }}</p>
      }

      @if (analise(); as a) {
        <div class="analise">
          <dl>
            <div>
              <dt>Banco</dt>
              <dd>
                {{ a.banco_nome ?? 'Não identificado'
                }}{{ a.banco_codigo ? ' (' + a.banco_codigo + ')' : '' }}
              </dd>
            </div>
            @if (a.agencia) {
              <div>
                <dt>Agência</dt>
                <dd>{{ a.agencia }}</dd>
              </div>
            }
            <div>
              <dt>{{ a.tipo === 'cartao' ? 'Cartão' : 'Conta' }}</dt>
              <dd>{{ a.numero ?? '—' }}</dd>
            </div>
            <div>
              <dt>Período</dt>
              <dd>{{ a.inicio | dataBr }} a {{ a.fim | dataBr }}</dd>
            </div>
            <div>
              <dt>Lançamentos</dt>
              <dd>{{ a.total_transacoes }}</dd>
            </div>
            @if (a.saldo_extrato !== null) {
              <div>
                <dt>Saldo no extrato</dt>
                <dd>{{ a.saldo_extrato | brl }}</dd>
              </div>
            }
          </dl>

          @if (a.outra_entidade) {
            <p class="aviso erro">
              Esta conta já está cadastrada na entidade <strong>{{ a.outra_entidade }}</strong>.
              Confira se a entidade selecionada no menu é a certa antes de importar.
            </p>
          }

          @if (a.conta_existente && !escolherOutra()) {
            <p class="aviso ok">
              Conta reconhecida: <strong>{{ a.conta_existente.nome }}</strong>. Lançamentos já
              importados antes são ignorados.
            </p>
            <div class="acoes">
              <button class="primario" type="button" [disabled]="importando()" (click)="importar()">
                {{ importando() ? 'Importando…' : 'Importar' }}
              </button>
              <button class="link" type="button" (click)="escolherOutra.set(true)">
                Importar em outra conta
              </button>
            </div>
          } @else {
            <div class="opcoes" role="radiogroup" aria-label="Destino do extrato">
              @if (a.numero) {
                <label class="opcao"
                  ><input type="radio" name="destino" [value]="'nova'" [(ngModel)]="destino" />
                  Criar nova conta com os dados do extrato</label
                >
              }
              @if (contas().length) {
                <label class="opcao"
                  ><input type="radio" name="destino" [value]="'existente'" [(ngModel)]="destino" />
                  Usar uma conta já cadastrada</label
                >
              }
            </div>

            @if (destino === 'nova' && a.numero) {
              <div class="grade">
                <label class="largo"
                  >Nome da conta <input name="nome" [(ngModel)]="nomeNova"
                /></label>
                <label>
                  Saldo inicial
                  <input name="saldoInicial" type="number" step="0.01" [(ngModel)]="saldoNova" />
                </label>
              </div>
              @if (a.saldo_extrato !== null) {
                <p class="sutil pequeno">
                  Saldo inicial calculado para que o saldo no sistema fique igual ao do extrato ({{
                    a.saldo_extrato | brl
                  }}).
                </p>
              }
            } @else if (destino === 'existente') {
              <label
                >Conta
                <select name="conta" [(ngModel)]="contaEscolhida">
                  @for (c of contas(); track c.id) {
                    <option [ngValue]="c.id">{{ c.nome }}</option>
                  }
                </select>
              </label>
            }
            <div class="acoes">
              <button
                class="primario"
                type="button"
                [disabled]="importando() || (destino === 'existente' && !contaEscolhida)"
                (click)="importar()"
              >
                {{
                  importando()
                    ? 'Importando…'
                    : destino === 'nova'
                      ? 'Criar conta e importar'
                      : 'Importar'
                }}
              </button>
              @if (a.conta_existente) {
                <button class="link" type="button" (click)="escolherOutra.set(false)">
                  Voltar
                </button>
              }
            </div>
          }
        </div>
      }

      @if (resultado(); as r) {
        <div class="aviso ok resultado">
          <strong>{{
            r.conta_criada
              ? 'Conta "' + r.conta_nome + '" criada e extrato importado.'
              : 'Extrato importado em "' + r.conta_nome + '".'
          }}</strong>
          <ul>
            <li>
              Novos lançamentos: <strong>{{ r.total_novas }}</strong> de {{ r.total_lidas }} ({{
                r.duplicadas
              }}
              já existiam)
            </li>
            <li>
              Categorizados por regra: {{ r.categorizadas }} · Conciliados automaticamente:
              {{ r.conciliadas }}
            </li>
          </ul>
        </div>
      }
    </section>

    <section class="cartao sem-padding">
      <table>
        <thead>
          <tr>
            <th>Conta</th>
            <th>Tipo</th>
            <th>Banco</th>
            <th>Agência</th>
            <th>Número</th>
            <th class="num">Saldo</th>
          </tr>
        </thead>
        <tbody>
          @for (c of contas(); track c.id) {
            <tr>
              <td>{{ c.nome }}</td>
              <td>{{ rotuloTipo(c.tipo) }}</td>
              <td>{{ c.banco_codigo ?? '—' }}</td>
              <td>{{ c.agencia ?? '—' }}</td>
              <td>{{ c.numero ?? '—' }}</td>
              <td class="num" [class.neg]="+c.saldo_atual < 0">{{ c.saldo_atual | brl }}</td>
            </tr>
          } @empty {
            <tr>
              <td colspan="6" class="sutil">
                Nenhuma conta ainda. Importe o primeiro extrato acima: a conta é criada
                automaticamente.
              </td>
            </tr>
          }
        </tbody>
      </table>
    </section>

    <details class="cartao manual">
      <summary>Cadastrar conta manualmente (caixa, maquininha ou conta sem OFX)</summary>
      <form class="grade" (ngSubmit)="criarConta()">
        <label
          >Nome
          <input name="mnome" [(ngModel)]="nova.nome" required placeholder="Ex.: Caixa da clínica"
        /></label>
        <label
          >Tipo
          <select name="mtipo" [(ngModel)]="nova.tipo">
            @for (t of tipos; track t[0]) {
              <option [ngValue]="t[0]">{{ t[1] }}</option>
            }
          </select>
        </label>
        <label
          >Banco (código) <input name="mbanco" [(ngModel)]="nova.banco_codigo" placeholder="341"
        /></label>
        <label>Agência <input name="magencia" [(ngModel)]="nova.agencia" /></label>
        <label>Conta <input name="mnumero" [(ngModel)]="nova.numero" /></label>
        <label
          >Saldo inicial
          <input name="msaldo" type="number" step="0.01" [(ngModel)]="nova.saldo_inicial"
        /></label>
        <div><button class="primario" type="submit">Adicionar</button></div>
      </form>
    </details>
  `,
  styles: `
    .bloco {
      display: flex;
      flex-direction: column;
      gap: 12px;
      margin-bottom: 16px;
    }
    .bloco h2 {
      margin: 0;
    }
    .soltar {
      border: 2px dashed var(--borda);
      border-radius: 8px;
      padding: 28px 16px;
      text-align: center;
      cursor: pointer;
      color: var(--texto-sutil);
    }
    .soltar.sobre {
      border-color: var(--primaria);
      color: var(--texto);
    }
    .analise {
      display: flex;
      flex-direction: column;
      gap: 12px;
      border-top: 1px solid var(--borda);
      padding-top: 12px;
    }
    dl {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 10px 16px;
      margin: 0;
    }
    dt {
      font-size: 0.75rem;
      color: var(--texto-sutil);
    }
    dd {
      margin: 2px 0 0;
      font-weight: 600;
    }
    .aviso {
      margin: 0;
      padding: 8px 12px;
      border-radius: 6px;
      background: var(--fundo-sutil);
    }
    .aviso.erro {
      color: var(--negativo);
    }
    .aviso.ok {
      border-left: 3px solid var(--primaria);
    }
    .opcoes {
      display: flex;
      flex-wrap: wrap;
      gap: 8px 20px;
    }
    .opcao {
      flex-direction: row;
      align-items: center;
      gap: 6px;
      color: var(--texto);
      font-size: 0.9rem;
    }
    .grade {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 12px;
      align-items: end;
    }
    .largo {
      grid-column: span 2;
    }
    .acoes {
      display: flex;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
    }
    .resultado ul {
      margin: 6px 0 0;
      padding-left: 18px;
    }
    .pequeno {
      font-size: 0.8rem;
      margin: 0;
    }
    .manual {
      margin-top: 16px;
    }
    .manual summary {
      cursor: pointer;
      font-weight: 600;
    }
    .manual form {
      margin-top: 12px;
    }
    @media (max-width: 600px) {
      .largo {
        grid-column: 1 / -1;
      }
    }
  `,
})
export class Importar {
  private api = inject(Api);
  private ent = inject(EntidadeAtual);
  tipos = TIPOS;
  contas = signal<Conta[]>([]);
  arquivo = signal<File | null>(null);
  analise = signal<AnaliseOFX | null>(null);
  resultado = signal<ImportacaoResultado | null>(null);
  arrastando = signal(false);
  analisando = signal(false);
  importando = signal(false);
  escolherOutra = signal(false);
  erro = signal('');
  destino: 'nova' | 'existente' = 'nova';
  nomeNova = '';
  saldoNova: number | null = null;
  contaEscolhida: number | null = null;
  nova = this.vazia();

  constructor() {
    effect(() => {
      this.ent.id();
      this.limpar();
      this.carregar();
    });
  }

  carregar() {
    const eid = this.ent.id();
    if (!eid) return;
    this.api.contas(eid).subscribe((c) => this.contas.set(c));
  }

  rotuloTipo(t: TipoConta) {
    return TIPOS.find((x) => x[0] === t)?.[1] ?? t;
  }

  escolher(ev: Event) {
    const input = ev.target as HTMLInputElement;
    this.selecionar(input.files?.[0] ?? null);
    input.value = '';
  }

  soltar(ev: DragEvent) {
    ev.preventDefault();
    this.arrastando.set(false);
    this.selecionar(ev.dataTransfer?.files?.[0] ?? null);
  }

  private selecionar(f: File | null) {
    const eid = this.ent.id();
    this.limpar();
    this.arquivo.set(f);
    if (!f || !eid) return;
    this.analisando.set(true);
    this.api.analisarOfx(eid, f).subscribe({
      next: (a) => {
        this.analisando.set(false);
        this.analise.set(a);
        this.nomeNova = a.sugestao_nome;
        this.saldoNova = Number(a.sugestao_saldo_inicial);
        this.destino = a.numero ? 'nova' : 'existente';
        this.contaEscolhida = this.contas()[0]?.id ?? null;
      },
      error: (e) => {
        this.analisando.set(false);
        this.erro.set(mensagemErro(e));
      },
    });
  }

  importar() {
    const eid = this.ent.id();
    const f = this.arquivo();
    const a = this.analise();
    if (!eid || !f || !a) return;
    const reconhecida = a.conta_existente && !this.escolherOutra();
    const opcoes = reconhecida
      ? { conta_id: a.conta_existente!.id }
      : this.destino === 'existente'
        ? { conta_id: this.contaEscolhida }
        : { nome: this.nomeNova, saldo_inicial: this.saldoNova };
    this.erro.set('');
    this.importando.set(true);
    this.api.importarOfxAuto(eid, f, opcoes).subscribe({
      next: (r) => {
        this.importando.set(false);
        this.analise.set(null);
        this.arquivo.set(null);
        this.resultado.set(r);
        this.carregar();
      },
      error: (e) => {
        this.importando.set(false);
        this.erro.set(mensagemErro(e));
      },
    });
  }

  criarConta() {
    const eid = this.ent.id();
    if (!eid) return;
    const dados = Object.fromEntries(
      Object.entries(this.nova).filter(([, v]) => v !== '' && v !== null),
    );
    this.api.criarConta(eid, dados).subscribe({
      next: () => {
        this.nova = this.vazia();
        this.carregar();
      },
      error: (e) => this.erro.set(mensagemErro(e)),
    });
  }

  private limpar() {
    this.analise.set(null);
    this.resultado.set(null);
    this.erro.set('');
    this.escolherOutra.set(false);
  }

  private vazia() {
    return {
      nome: '',
      tipo: 'caixa' as TipoConta,
      banco_codigo: '',
      agencia: '',
      numero: '',
      saldo_inicial: 0 as unknown as string,
    };
  }
}
