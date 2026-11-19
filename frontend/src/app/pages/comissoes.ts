import { Component, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../core/api';
import { mensagemErro } from '../core/auth';
import { EntidadeAtual } from '../core/entidade-atual';
import { BrlPipe, DataBrPipe } from '../core/formato';
import {
  Comissao,
  Comparativo,
  ExtratoComissao,
  ExtratoImportado,
  FechamentoStatus,
  ImportacaoPlanilha,
  PastaStatus,
} from '../core/models';

@Component({
  selector: 'app-comissoes',
  imports: [FormsModule, BrlPipe, DataBrPipe],
  template: `
    <header class="cabecalho">
      <h1>Comissões</h1>
      <div class="acoes-topo">
        <input
          type="month"
          [ngModel]="mes()"
          (ngModelChange)="mes.set($event)"
          aria-label="Mês do extrato"
        />
        <label class="botao">
          {{ importandoExt() ? 'Lendo extratos…' : 'Importar extratos das seguradoras' }}
          <input type="file" multiple hidden (change)="importarExtratos($event)" />
        </label>
        <label class="botao secundario">
          {{ importando() ? 'Importando…' : 'Importar planilha (.xlsx)' }}
          <input type="file" accept=".xlsx,.xlsm" hidden (change)="importar($event)" />
        </label>
      </div>
    </header>

    @if (erro()) {
      <p class="erro">{{ erro() }}</p>
    }

    <details class="cartao fech so-admin" [open]="!fech()?.propostas">
      <summary>
        <strong>FECHAMENTO DE PROPOSTAS</strong>
        @if (fech(); as f) {
          <span class="sutil">
            @if (f.propostas) {
              · {{ f.propostas }} propostas · sincronizado {{ f.sincronizado_em | dataBr }}
            } @else {
              · não ligado: o vínculo e o "novo negócio" ficam só pela BASE
            }
          </span>
        }
      </summary>
      <div class="fech-form">
        <label class="largo"
          >Link da planilha no Google Sheets
          <input
            [(ngModel)]="linkFech"
            placeholder="https://docs.google.com/spreadsheets/d/.../edit"
            aria-label="Link da planilha FECHAMENTO"
        /></label>
        <button type="button" class="link" (click)="salvarFech()">Salvar link</button>
        <button
          type="button"
          class="primario"
          (click)="sincronizarFech()"
          [disabled]="sincronizando() || !fech()?.planilha_id"
        >
          {{ sincronizando() ? 'Sincronizando…' : 'Sincronizar agora' }}
        </button>
        <label class="link arquivo"
          >ou subir o .xlsx
          <input type="file" accept=".xlsx" hidden (change)="subirFech($event)" />
        </label>
      </div>
      @if (fech(); as f) {
        <p class="sutil pequeno">
          @if (f.conta_servico) {
            Acesso pela conta de serviço do Google (compartilhe a planilha com o e-mail dela, como
            leitor).
          } @else {
            Sem conta de serviço configurada: a planilha precisa estar com "qualquer pessoa com o
            link pode ver". Veja docs/FECHAMENTO.md para o acesso privado (recomendado).
          }
          @if (f.abas.length) {
            Abas lidas: {{ f.abas.join(', ') }}.
          }
          @if (f.novos_negocios !== null) {
            {{ f.novos_negocios }} comissões marcadas como novo negócio.
          }
        </p>
        @for (a of f.avisos; track a) {
          <p class="neg pequeno">{{ a }}</p>
        }
      }
    </details>

    @if (pasta(); as pst) {
      <details class="cartao fech so-admin">
        <summary>
          <strong>Pasta monitorada</strong>
          <span class="sutil">
            @if (pst.configurada) {
              · lida a cada {{ pst.intervalo_segundos }}s · {{ pst.arquivos.length }} arquivo(s)
              recentes
            } @else {
              · desligada (robôs e Claude in Chrome salvam nela; ver docs/ROBOS.md)
            }
          </span>
        </summary>
        @if (pst.configurada) {
          <div class="fech-form">
            <button type="button" class="primario" (click)="lerPasta()">Ler a pasta agora</button>
          </div>
          <table>
            <tbody>
              @for (a of pst.arquivos; track a.id) {
                <tr>
                  <td>{{ a.processado_em | dataBr }}</td>
                  <td>{{ a.nome }}</td>
                  <td>
                    <span class="status" [attr.data-s]="cssArquivo(a.situacao)">{{
                      a.situacao.replace('_', ' ')
                    }}</span>
                  </td>
                  <td class="sutil pequeno">{{ a.extratos }} {{ a.mensagem }}</td>
                </tr>
              } @empty {
                <tr>
                  <td class="sutil">Nenhum arquivo ainda.</td>
                </tr>
              }
            </tbody>
          </table>
        }
      </details>
    }

    @if (extratosImportados().length) {
      <section class="cartao sem-padding aviso">
        <h2>
          Extratos lidos
          <button type="button" class="link" (click)="extratosImportados.set([])">fechar</button>
        </h2>
        <table>
          <tbody>
            @for (x of extratosImportados(); track $index) {
              <tr>
                <td>
                  <strong>{{ x.codigo ?? x.arquivo }}</strong>
                  <div class="sutil pequeno">{{ x.arquivo }}</div>
                </td>
                @if (x.erro) {
                  <td colspan="4" class="neg">{{ x.erro }}</td>
                } @else {
                  <td>{{ x.data | dataBr }}</td>
                  <td class="num">bruto {{ x.bruto | brl }} · líquido {{ x.liquido | brl }}</td>
                  <td>
                    @if (x.ja_importado) {
                      <span class="status" data-s="pago">já importado</span>
                    } @else {
                      {{ x.gravadas }} lançamentos
                    }
                  </td>
                  <td>
                    @for (d of x.divergencias; track d) {
                      <div class="neg">⚠ {{ d }}</div>
                    }
                    @if (x.sem_vinculo.length) {
                      <div class="neg">
                        {{ x.sem_vinculo.length }} sem vínculo:
                        {{ x.sem_vinculo.slice(0, 4).join('; ')
                        }}{{
                          x.sem_vinculo.length > 4
                            ? ' e mais ' +
                              (x.sem_vinculo.length - 4) +
                              ' (filtro "sem produtor/parceiro")'
                            : ''
                        }}
                      </div>
                    }
                    @for (a of x.avisos; track a) {
                      <div class="sutil pequeno">{{ a }}</div>
                    }
                  </td>
                }
              </tr>
            }
          </tbody>
        </table>
      </section>
    }
    @if (resultado(); as r) {
      <p class="cartao aviso">
        Planilha importada ({{ r.abas.join(', ') }}): {{ r.contas_pagar }} contas a pagar ({{
          r.contas_pagas
        }}
        já pagas), {{ r.recorrencias }} recorrências, {{ r.regras }} regras,
        {{ r.extratos }} extratos e {{ r.comissoes }} linhas de comissão.
        @if (r.categorias_criadas.length) {
          {{ r.categorias_criadas.length }} categorias novas: confira o grupo da DRE em
          <strong>Plano de contas</strong>.
        }
        @if (!r.contas_pagar && !r.comissoes) {
          Nada novo: tudo já estava importado.
        }
      </p>
    }

    @if (cmp(); as c) {
      <section class="grade-kpi">
        <div class="cartao kpi">
          <span>Comissão bruta</span><strong>{{ c.total_atual | brl }}</strong>
          <small [class.neg]="+c.total_atual < +c.total_anterior"
            >{{ variacao(c.total_anterior, c.total_atual) }} vs {{ rotulo(c.anterior) }}</small
          >
        </div>
        <div class="cartao kpi">
          <span>Impostos</span><strong>{{ c.imposto_atual | brl }}</strong>
        </div>
        <div class="cartao kpi">
          <span>Comissão líquida</span><strong>{{ c.liquido_atual | brl }}</strong>
        </div>
        <div class="cartao kpi">
          <span>Novos negócios</span><strong>{{ c.novos_valor | brl }}</strong>
          <small>{{ c.novos_qtd }} apólices</small>
        </div>
        <button
          type="button"
          class="cartao kpi clicavel"
          [class.alerta]="c.sem_vinculo"
          (click)="filtrarSemVinculo()"
        >
          <span>Sem produtor/parceiro</span><strong>{{ c.sem_vinculo }}</strong>
          <small>clique para ver</small>
        </button>
      </section>

      <div class="duas-colunas">
        @for (bloco of blocos(); track bloco.titulo) {
          <section class="cartao sem-padding">
            <h2>{{ bloco.titulo }}</h2>
            <table>
              <thead>
                <tr>
                  <th></th>
                  <th class="num">{{ rotulo(c.anterior) }}</th>
                  <th class="num">{{ rotulo(c.mes) }}</th>
                  <th class="num">Variação</th>
                </tr>
              </thead>
              <tbody>
                @for (l of bloco.linhas; track l.chave) {
                  <tr>
                    <td>
                      @if (bloco.campo === 'seguradora') {
                        <button
                          type="button"
                          class="link"
                          (click)="filtrar({ seguradora: l.chave })"
                        >
                          {{ l.chave }}
                        </button>
                      } @else {
                        <button type="button" class="link" (click)="filtrar({ ramo: l.chave })">
                          {{ l.chave }}
                        </button>
                      }
                    </td>
                    <td class="num">{{ l.anterior | brl }}</td>
                    <td class="num">{{ l.atual | brl }}</td>
                    <td class="num" [class.neg]="+l.variacao < 0">
                      {{ +l.variacao < 0 ? '▼' : '▲' }}
                      {{ l.variacao_pct === null ? 'novo' : pct(l.variacao_pct) }}
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </section>
        }
      </div>
    }

    <section class="cartao sem-padding">
      <h2>Extratos do mês (conferência)</h2>
      <table>
        <thead>
          <tr>
            <th>Extrato</th>
            <th>Data</th>
            <th class="num">Linhas</th>
            <th class="num">Bruto</th>
            <th class="num">ISS</th>
            <th class="num">Líquido</th>
            <th class="num">Recebido</th>
            <th>Situação</th>
          </tr>
        </thead>
        <tbody>
          @for (e of extratos(); track e.id) {
            <tr [class.selecionado]="filtro().extrato_id === e.id">
              <td>
                <button type="button" class="link" (click)="filtrar({ extrato_id: e.id })">
                  {{ e.codigo }}
                </button>
                <div class="sutil pequeno">{{ e.documento }}</div>
              </td>
              <td>{{ e.data | dataBr }}</td>
              <td class="num">{{ e.linhas }}</td>
              <td class="num">{{ e.bruto | brl }}</td>
              <td class="num">{{ e.iss | brl }}</td>
              <td class="num">{{ e.liquido | brl }}</td>
              <td class="num">
                {{ e.recebido_valor | brl }}
                @if (e.recebido_em) {
                  <div class="sutil pequeno">{{ e.recebido_em | dataBr }}</div>
                }
              </td>
              <td>
                <span class="status" [attr.data-s]="situacaoCss(e.situacao)">{{ e.situacao }}</span>
              </td>
            </tr>
          } @empty {
            <tr>
              <td colspan="8" class="sutil">Nenhum extrato neste mês.</td>
            </tr>
          }
        </tbody>
      </table>
    </section>

    <section class="cartao sem-padding">
      <header class="cabecalho-tabela">
        <h2>
          Lançamentos de comissão
          @if (descricaoFiltro()) {
            <span class="sutil pequeno">· {{ descricaoFiltro() }}</span>
            <button type="button" class="link" (click)="filtrar({})">limpar filtro</button>
          }
        </h2>
        <input
          placeholder="Buscar cliente ou apólice"
          [ngModel]="busca()"
          (ngModelChange)="busca.set($event)"
          aria-label="Buscar cliente ou apólice"
        />
      </header>
      <table>
        <thead>
          <tr>
            <th>Data</th>
            <th>Seguradora / ramo</th>
            <th>Cliente</th>
            <th class="num">Bruta</th>
            <th class="num">Líquida</th>
            <th>Origem</th>
            <th>Produtor</th>
            <th>Parceiro</th>
          </tr>
        </thead>
        <tbody>
          @for (l of linhasVisiveis(); track l.id) {
            <tr [class.alerta]="!l.produtor && !l.parceiro">
              <td>{{ l.data | dataBr }}</td>
              <td>
                {{ l.seguradora }}<span class="sutil"> · {{ l.ramo }}</span>
                @if (l.parcela) {
                  <span class="sutil"> · parc. {{ l.parcela_texto ?? l.parcela }}</span>
                }
              </td>
              <td>
                {{ l.cliente }}
                @if (l.apolice) {
                  <div class="sutil pequeno">{{ l.apolice }}</div>
                }
              </td>
              <td class="num" [class.neg]="+l.bruta < 0">{{ l.bruta | brl }}</td>
              <td class="num">{{ l.liquida | brl }}</td>
              @for (campo of camposVinculo; track campo) {
                <td>
                  <input
                    class="vinculo"
                    [attr.list]="'lista-' + campo"
                    [ngModel]="l[campo]"
                    (change)="salvarVinculo(l, campo, $any($event.target).value)"
                    [attr.aria-label]="campo + ' de ' + l.cliente"
                  />
                </td>
              }
            </tr>
          } @empty {
            <tr>
              <td colspan="8" class="sutil">Nada para mostrar.</td>
            </tr>
          }
        </tbody>
      </table>
      @if (linhasFiltradas().length > linhasVisiveis().length) {
        <p class="sutil rodape">
          Mostrando {{ linhasVisiveis().length }} de {{ linhasFiltradas().length }}.
          <button type="button" class="link" (click)="limite.set(limite() + 200)">
            Mostrar mais
          </button>
        </p>
      }
    </section>

    @for (campo of camposVinculo; track campo) {
      <datalist [id]="'lista-' + campo">
        @for (v of sugestoes()[campo]; track v) {
          <option [value]="v"></option>
        }
      </datalist>
    }
  `,
  styles: `
    .acoes-topo {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }
    .botao {
      cursor: pointer;
      padding: 8px 12px;
      border-radius: 8px;
      background: var(--primaria, #2563eb);
      color: #fff;
      font-weight: 600;
    }
    .aviso {
      margin-bottom: 16px;
    }
    .fech {
      margin-bottom: 16px;
    }
    .fech summary {
      cursor: pointer;
    }
    .fech-form {
      display: flex;
      gap: 12px;
      align-items: end;
      flex-wrap: wrap;
      margin-top: 12px;
    }
    .fech-form .largo {
      flex: 1 1 320px;
    }
    .fech-form .largo input {
      width: 100%;
    }
    .arquivo {
      cursor: pointer;
    }
    .secundario {
      background: transparent;
      color: var(--primaria, #2563eb);
      border: 1px solid currentColor;
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
      text-align: left;
      font: inherit;
      color: inherit;
    }
    .kpi span,
    .kpi small {
      font-size: 0.8rem;
      color: var(--texto-sutil);
    }
    .kpi strong {
      font-size: 1.3rem;
      font-variant-numeric: tabular-nums;
    }
    .clicavel {
      cursor: pointer;
    }
    .duas-colunas {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      align-items: start;
      margin-bottom: 16px;
    }
    section.cartao {
      margin-bottom: 16px;
      overflow-x: auto;
    }
    h2 {
      padding: 12px 12px 0;
      font-size: 0.95rem;
    }
    .cabecalho-tabela {
      display: flex;
      justify-content: space-between;
      align-items: end;
      gap: 12px;
      padding-right: 12px;
      flex-wrap: wrap;
    }
    .neg {
      color: var(--negativo);
    }
    .alerta td,
    .kpi.alerta strong {
      color: var(--negativo);
    }
    .selecionado td {
      background: var(--fundo-sutil);
    }
    .vinculo {
      width: 110px;
      text-transform: uppercase;
    }
    .pequeno {
      font-size: 0.78rem;
      font-weight: normal;
    }
    .rodape {
      padding: 0 12px 12px;
    }
    @media (max-width: 900px) {
      .duas-colunas {
        grid-template-columns: 1fr;
      }
    }
  `,
})
export class Comissoes {
  private api = inject(Api);
  private ent = inject(EntidadeAtual);
  readonly camposVinculo = ['origem', 'produtor', 'parceiro'] as const;

  mes = signal(mesAnterior());
  cmp = signal<Comparativo | null>(null);
  extratos = signal<ExtratoComissao[]>([]);
  linhas = signal<Comissao[]>([]);
  filtro = signal<{
    seguradora?: string;
    ramo?: string;
    extrato_id?: number;
    sem_vinculo?: boolean;
  }>({});
  busca = signal('');
  limite = signal(200);
  erro = signal('');
  importando = signal(false);
  resultado = signal<ImportacaoPlanilha | null>(null);
  importandoExt = signal(false);
  extratosImportados = signal<ExtratoImportado[]>([]);

  blocos = computed(() => {
    const c = this.cmp();
    if (!c) return [];
    return [
      { titulo: 'Por ramo', campo: 'ramo', linhas: c.por_ramo },
      { titulo: 'Por seguradora', campo: 'seguradora', linhas: c.por_seguradora },
    ];
  });

  linhasFiltradas = computed(() => {
    const f = this.filtro();
    const b = this.busca().trim().toUpperCase();
    return this.linhas().filter(
      (l) =>
        (!f.seguradora || l.seguradora === f.seguradora) &&
        (!f.ramo || (l.ramo ?? '—') === f.ramo) &&
        (!f.extrato_id || l.extrato_id === f.extrato_id) &&
        (!f.sem_vinculo || (!l.produtor && !l.parceiro)) &&
        (!b || (l.cliente ?? '').toUpperCase().includes(b) || (l.apolice ?? '').includes(b)),
    );
  });
  linhasVisiveis = computed(() => this.linhasFiltradas().slice(0, this.limite()));

  sugestoes = computed(() => {
    const s: Record<string, string[]> = {};
    for (const campo of this.camposVinculo) {
      s[campo] = [
        ...new Set(
          this.linhas()
            .map((l) => l[campo])
            .filter((v): v is string => !!v),
        ),
      ].sort();
    }
    return s;
  });

  descricaoFiltro = computed(() => {
    const f = this.filtro();
    if (f.extrato_id)
      return this.extratos().find((e) => e.id === f.extrato_id)?.codigo ?? 'extrato';
    if (f.sem_vinculo) return 'sem produtor/parceiro';
    return f.seguradora ?? f.ramo ?? '';
  });

  fech = signal<FechamentoStatus | null>(null);
  pasta = signal<PastaStatus | null>(null);
  sincronizando = signal(false);
  linkFech = '';

  constructor() {
    effect(() => this.carregar());
    effect(() => {
      const eid = this.ent.id();
      if (!eid) return;
      this.api.pasta(eid).subscribe((p) => this.pasta.set(p));
      this.api.fechamento(eid).subscribe((f) => {
        this.fech.set(f);
        this.linkFech = f.planilha_id
          ? `https://docs.google.com/spreadsheets/d/${f.planilha_id}/edit`
          : '';
      });
    });
  }

  private aposFech = {
    next: (f: FechamentoStatus) => {
      this.fech.set(f);
      this.sincronizando.set(false);
      this.carregar();
    },
    error: (e: unknown) => {
      this.erro.set(mensagemErro(e));
      this.sincronizando.set(false);
    },
  };

  lerPasta() {
    const eid = this.ent.id();
    if (!eid) return;
    this.api.varrerPasta(eid).subscribe({
      next: (p) => {
        this.pasta.set(p);
        this.carregar();
      },
      error: (e) => this.erro.set(mensagemErro(e)),
    });
  }

  cssArquivo(s: string) {
    return s === 'importado' ? 'pago' : s === 'erro' ? 'cancelado' : 'aberto';
  }

  salvarFech() {
    const eid = this.ent.id();
    if (!eid) return;
    this.erro.set('');
    this.api.configurarFechamento(eid, this.linkFech.trim() || null).subscribe(this.aposFech);
  }

  sincronizarFech() {
    const eid = this.ent.id();
    if (!eid) return;
    this.erro.set('');
    this.sincronizando.set(true);
    this.api.sincronizarFechamento(eid).subscribe(this.aposFech);
  }

  subirFech(ev: Event) {
    const input = ev.target as HTMLInputElement;
    const arq = input.files?.[0];
    const eid = this.ent.id();
    input.value = '';
    if (!arq || !eid) return;
    this.sincronizando.set(true);
    this.api.importarFechamento(eid, arq).subscribe(this.aposFech);
  }

  carregar() {
    const eid = this.ent.id();
    const mes = this.mes();
    if (!eid || !mes) return;
    this.limite.set(200);
    this.api.comparativo(eid, mes).subscribe({
      next: (c) => this.cmp.set(c),
      error: (e) => this.erro.set(mensagemErro(e)),
    });
    this.api.extratosComissao(eid, mes).subscribe((e) => this.extratos.set(e));
    this.api.comissoes(eid, { mes }).subscribe((l) => this.linhas.set(l));
  }

  filtrar(f: { seguradora?: string; ramo?: string; extrato_id?: number }) {
    this.filtro.set(f);
    this.limite.set(200);
  }

  filtrarSemVinculo() {
    this.filtro.set({ sem_vinculo: true });
  }

  salvarVinculo(l: Comissao, campo: 'origem' | 'produtor' | 'parceiro', valor: string) {
    const eid = this.ent.id();
    if (!eid) return;
    this.api.atualizarComissao(eid, l.id, { [campo]: valor }).subscribe({
      next: (novo) => this.linhas.update((ls) => ls.map((x) => (x.id === novo.id ? novo : x))),
      error: (e) => this.erro.set(mensagemErro(e)),
    });
  }

  importarExtratos(ev: Event) {
    const input = ev.target as HTMLInputElement;
    const arquivos = Array.from(input.files ?? []);
    const eid = this.ent.id();
    input.value = '';
    if (!arquivos.length || !eid) return;
    this.erro.set('');
    this.importandoExt.set(true);
    this.api.importarExtratos(eid, arquivos).subscribe({
      next: (r) => {
        this.extratosImportados.set(r);
        this.importandoExt.set(false);
        const mais = r
          .filter((x) => x.data)
          .map((x) => x.data!.slice(0, 7))
          .sort()
          .pop();
        if (mais && mais !== this.mes()) this.mes.set(mais);
        else this.carregar();
      },
      error: (e) => {
        this.erro.set(mensagemErro(e));
        this.importandoExt.set(false);
      },
    });
  }

  importar(ev: Event) {
    const input = ev.target as HTMLInputElement;
    const arquivo = input.files?.[0];
    const eid = this.ent.id();
    input.value = '';
    if (!arquivo || !eid) return;
    this.erro.set('');
    this.importando.set(true);
    this.api.importarPlanilha(eid, arquivo).subscribe({
      next: (r) => {
        this.resultado.set(r);
        this.importando.set(false);
        this.carregar();
      },
      error: (e) => {
        this.erro.set(mensagemErro(e));
        this.importando.set(false);
      },
    });
  }

  rotulo(mes: string) {
    const [a, m] = mes.split('-');
    return `${MESES[Number(m) - 1]}/${a}`;
  }

  pct(v: number) {
    return `${(v * 100).toFixed(1).replace('.', ',')}%`;
  }

  variacao(anterior: string, atual: string) {
    const a = Number(anterior);
    if (!a) return 'sem base';
    const v = (Number(atual) - a) / Math.abs(a);
    return `${v < 0 ? '▼' : '▲'} ${this.pct(Math.abs(v))}`;
  }

  situacaoCss(s: string) {
    return s === 'RECEBIDO' ? 'pago' : s === 'DIVERGENTE' ? 'parcial' : 'aberto';
  }
}

const MESES = ['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN', 'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ'];

function mesAnterior(): string {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}
