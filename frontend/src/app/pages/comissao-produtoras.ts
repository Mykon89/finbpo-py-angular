import { Component, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../core/api';
import { mensagemErro } from '../core/auth';
import { EntidadeAtual } from '../core/entidade-atual';
import { BrlPipe } from '../core/formato';
import {
  ApuracaoComissao,
  Categoria,
  HistoricoComissao,
  PlanoComissao,
  UsuarioAdmin,
} from '../core/models';
import { Perfil } from '../core/perfil';
import { salvarBlob } from './baixar';
import { ComissaoDetalhe } from './comissao-detalhe';
import { SimuladorComissao } from './simulador-comissao';

const h = new Date();
const mesAtual = `${h.getFullYear()}-${String(h.getMonth() + 1).padStart(2, '0')}`;
const NOMES_MES = [
  'Jan',
  'Fev',
  'Mar',
  'Abr',
  'Mai',
  'Jun',
  'Jul',
  'Ago',
  'Set',
  'Out',
  'Nov',
  'Dez',
];

@Component({
  selector: 'app-comissao-produtoras',
  imports: [FormsModule, BrlPipe, ComissaoDetalhe, SimuladorComissao],
  template: `
    <header class="cabecalho">
      <h1>Comissões das produtoras</h1>
      <div class="acoes">
        <input type="month" [ngModel]="mes()" (ngModelChange)="mes.set($event)" aria-label="Mês" />
        @if (plano(); as p) {
          <button type="button" class="primario-visivel" (click)="pdf(p)">Demonstrativo PDF</button>
          <button type="button" class="primario" (click)="gerar(p)">
            Gerar/atualizar conta a pagar
          </button>
          @if (p.usa_planilha_saude) {
            <button type="button" class="botao" (click)="syncSaude(p)">
              Sincronizar planilha de saúde
            </button>
            <label class="botao"
              >Enviar xlsx
              <input type="file" accept=".xlsx" hidden (change)="enviarSaude(p, $event)"
            /></label>
          }
        }
      </div>
    </header>
    @if (msg()) {
      <p class="ok">{{ msg() }}</p>
    }
    @if (erro()) {
      <p class="erro">{{ erro() }}</p>
    }
    @if (!planos().length) {
      <section class="cartao">
        <p>Nenhum plano cadastrado.</p>
        <button type="button" class="primario" (click)="modelo()">
          Criar Giovanna e Fabiana com as regras da planilha
        </button>
      </section>
    }
    <nav class="abas">
      @for (p of planos(); track p.id) {
        <button type="button" [class.ativa]="p.id === sel()" (click)="sel.set(p.id!)">
          {{ p.produtor }}
        </button>
      }
      @for (t of abas; track t) {
        <button type="button" class="aba-sec" [class.ativa]="aba() === t" (click)="aba.set(t)">
          {{ t }}
        </button>
      }
    </nav>

    @if (plano(); as p) {
      @switch (aba()) {
        @case ('Apuração') {
          <app-comissao-detalhe [a]="a()" [historico]="hist()" />
          <app-simulador-comissao [eid]="eid()!" [plano]="p.id!" [ano]="am()[0]" [mes]="am()[1]" />
        }
        @case ('Metas') {
          <section class="cartao">
            <h2>Metas de {{ am()[0] }} (Kette passa todo início de mês)</h2>
            <p class="sutil pequeno">
              5 faixas: até a 1ª = SEM META; acima da 1ª = BRONZE; acima da 3ª = PRATA; da 4ª =
              OURO; da 5ª = DIAMANTE.
            </p>
            <table>
              <thead>
                <tr>
                  <th>Mês</th>
                  <th>Tipo</th>
                  @for (i of [1, 2, 3, 4, 5]; track i) {
                    <th>Faixa {{ i }}</th>
                  }
                  <th></th>
                </tr>
              </thead>
              <tbody>
                @for (m of grade(); track m.chave) {
                  <tr>
                    <td>{{ nomesMes[m.mes - 1] }}</td>
                    <td>{{ m.tipo }}</td>
                    @for (i of [0, 1, 2, 3, 4]; track i) {
                      <td><input type="number" class="curto" [(ngModel)]="m.faixas[i]" /></td>
                    }
                    <td>
                      <button type="button" class="primario" (click)="salvarMeta(p, m)">
                        Salvar
                      </button>
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </section>
        }
        @case ('PL dos clientes') {
          @if (a(); as x) {
            <section class="cartao sem-padding">
              <h2>Clientes que entram no PL de {{ x.rotulo }}</h2>
              <table>
                <thead>
                  <tr>
                    <th>Entra</th>
                    <th>Cliente</th>
                    <th>Seguradora</th>
                    <th>Ramo</th>
                    <th class="num">PL</th>
                    <th>Fonte</th>
                  </tr>
                </thead>
                <tbody>
                  @for (c of x.clientes_pl; track c.chave) {
                    <tr [class.sutil]="!c.incluido">
                      <td>
                        <input
                          type="checkbox"
                          [checked]="c.incluido"
                          (change)="alternar(c.chave)"
                        />
                      </td>
                      <td>{{ c.cliente }}</td>
                      <td>{{ c.seguradora }}</td>
                      <td>{{ c.ramo }}</td>
                      <td class="num">{{ c.pl | brl }}</td>
                      <td class="pequeno">{{ c.fonte }}</td>
                    </tr>
                  }
                </tbody>
              </table>
              <div class="linha">
                <label>Ajuste manual do PL <input type="number" [(ngModel)]="ajuste" /></label>
                <button type="button" class="primario" (click)="salvarAjuste(p)">
                  Salvar exclusões e ajuste
                </button>
              </div>
            </section>
          }
        }
        @case ('Configuração') {
          <section class="cartao form">
            <h2>Plano de {{ p.produtor }}</h2>
            <label>Nome completo <input [(ngModel)]="p.nome" /></label>
            <label>Produtor (como aparece no extrato) <input [(ngModel)]="p.produtor" /></label>
            <label
              >Nomes que contam como indicação dela (vírgula)
              <input
                [ngModel]="p.aliases_indicacao.join(', ')"
                (ngModelChange)="p.aliases_indicacao = lista($event)"
            /></label>
            <label
              >Ramos fora da comissão patrimonial (vírgula)
              <input
                [ngModel]="p.excluir_ramos.join(', ')"
                (ngModelChange)="p.excluir_ramos = lista($event)"
            /></label>
            <label
              ><input type="checkbox" [(ngModel)]="p.usa_planilha_saude" /> Usa planilha de saúde
              própria</label
            >
            @if (p.usa_planilha_saude) {
              <label
                >Planilha de saúde (link ou ID) <input [(ngModel)]="p.planilha_saude_id"
              /></label>
            }
            <label
              >Paga quantos meses depois da competência
              <input type="number" min="0" max="3" [(ngModel)]="p.meses_para_pagar"
            /></label>
            <label
              >Categoria no contas a pagar
              <select [(ngModel)]="p.categoria_id">
                <option [ngValue]="null">—</option>
                @for (c of categorias(); track c.id) {
                  <option [ngValue]="c.id">{{ c.nome }}</option>
                }
              </select>
            </label>
            <label
              >Usuário que vê "Minha comissão"
              <select [(ngModel)]="p.usuario_id">
                <option [ngValue]="null">ninguém</option>
                @for (u of usuarios(); track u.id) {
                  <option [ngValue]="u.id">{{ u.nome }} ({{ u.email }})</option>
                }
              </select>
            </label>
            <h3>Níveis</h3>
            <table>
              <thead>
                <tr>
                  <th>Nível</th>
                  <th>% patrimonial</th>
                  <th>% saúde</th>
                </tr>
              </thead>
              <tbody>
                @for (n of p.niveis; track n.nome) {
                  <tr>
                    <td>{{ n.nome }}</td>
                    <td><input type="number" step="0.01" class="curto" [(ngModel)]="n.pct" /></td>
                    <td>
                      <input type="number" step="0.01" class="curto" [(ngModel)]="n.pct_saude" />
                    </td>
                  </tr>
                }
              </tbody>
            </table>
            <label><input type="checkbox" [(ngModel)]="p.ativo" /> Ativo</label>
            <div class="botoes">
              <button type="button" class="primario" (click)="salvarPlano(p)">Salvar plano</button>
            </div>
            <p class="sutil pequeno">
              Vencimento da conta: sempre 1 dia antes do primeiro imposto (DAS/INSS/FGTS) do mês de
              pagamento.
            </p>
          </section>
        }
      }
    }
  `,
  styles: `
    .abas {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      margin: 8px 0 12px;
    }
    .abas button {
      border: 1px solid #ccd;
      background: #fff;
      border-radius: 16px;
      padding: 4px 12px;
      cursor: pointer;
    }
    .abas .ativa {
      background: #1f4e79;
      color: #fff;
    }
    .aba-sec:first-of-type {
      margin-left: 16px;
    }
    .curto {
      width: 100px;
    }
    .num {
      text-align: right;
    }
    .linha {
      display: flex;
      gap: 12px;
      align-items: end;
      padding: 12px;
    }
    .form label {
      display: flex;
      flex-direction: column;
      gap: 4px;
      margin-bottom: 10px;
    }
    .ok {
      color: #15803d;
    }
  `,
})
export class ComissaoProdutoras {
  private api = inject(Api);
  private ent = inject(EntidadeAtual);
  protected perfil = inject(Perfil);
  eid = this.ent.id;
  nomesMes = NOMES_MES;
  abas = ['Apuração', 'Metas', 'PL dos clientes', 'Configuração'];
  aba = signal('Apuração');
  mes = signal(mesAtual);
  planos = signal<PlanoComissao[]>([]);
  sel = signal<number | null>(null);
  plano = computed(() => this.planos().find((p) => p.id === this.sel()) ?? null);
  a = signal<ApuracaoComissao | null>(null);
  hist = signal<HistoricoComissao[]>([]);
  grade = signal<{ chave: string; mes: number; tipo: 'patrimonial' | 'saude'; faixas: number[] }[]>(
    [],
  );
  categorias = signal<Categoria[]>([]);
  usuarios = signal<UsuarioAdmin[]>([]);
  excluidos = new Set<string>();
  ajuste = 0;
  msg = signal('');
  erro = signal('');
  private versao = signal(0);

  constructor() {
    effect(() => {
      const eid = this.ent.id();
      if (!eid) return;
      this.carregarPlanos(eid);
      this.api.categorias(eid).subscribe((c) => this.categorias.set(c));
      if (this.perfil.admin()) this.api.usuarios().subscribe((u) => this.usuarios.set(u));
    });
    effect(() => {
      const eid = this.ent.id();
      const id = this.sel();
      const [a, m] = this.am();
      this.versao();
      if (!eid || !id || !a) return;
      const req =
        this.mes() === mesAtual
          ? this.api.painelComissao(eid, id)
          : this.api.apuracaoComissao(eid, id, a, m);
      req.subscribe({
        next: (x) => {
          this.a.set(x);
          this.excluidos = new Set(x.clientes_pl.filter((c) => !c.incluido).map((c) => c.chave));
          this.ajuste = Number(x.patrimonial.ajuste);
        },
        error: (e) => this.erro.set(mensagemErro(e)),
      });
      this.api.historicoComissao(eid, id, a).subscribe((hs) => this.hist.set(hs));
      this.api.metasComissao(eid, id, a).subscribe((ms) => {
        const p = this.plano();
        const tipos: ('patrimonial' | 'saude')[] = p?.usa_planilha_saude
          ? ['patrimonial', 'saude']
          : ['patrimonial'];
        const linhas = [];
        for (let mes = 1; mes <= 12; mes++)
          for (const tipo of tipos) {
            const f = ms.find((x) => x.mes === mes && x.tipo === tipo)?.faixas ?? [0, 0, 0, 0, 0];
            linhas.push({ chave: `${mes}${tipo}`, mes, tipo, faixas: f.map(Number) });
          }
        this.grade.set(linhas);
      });
    });
  }

  am(): [number, number] {
    const [a, m] = this.mes().split('-').map(Number);
    return [a, m];
  }

  private carregarPlanos(eid: number) {
    this.api.planosComissao(eid).subscribe((ps) => {
      this.planos.set(ps);
      if (ps.length && !ps.some((p) => p.id === this.sel())) this.sel.set(ps[0].id!);
    });
  }

  private ok(t: string) {
    this.erro.set('');
    this.msg.set(t);
    this.versao.update((v) => v + 1);
  }

  private falha = (e: unknown) => {
    this.msg.set('');
    this.erro.set(mensagemErro(e));
  };

  lista(t: string) {
    return t
      .split(',')
      .map((x) => x.trim().toUpperCase())
      .filter(Boolean);
  }

  modelo() {
    const eid = this.eid()!;
    this.api
      .criarPlanosModelo(eid)
      .subscribe({ next: () => this.carregarPlanos(eid), error: this.falha });
  }

  salvarPlano(p: PlanoComissao) {
    this.api
      .salvarPlano(this.eid()!, p)
      .subscribe({ next: () => this.ok('Plano salvo.'), error: this.falha });
  }

  salvarMeta(
    p: PlanoComissao,
    m: { mes: number; tipo: 'patrimonial' | 'saude'; faixas: number[] },
  ) {
    this.api
      .salvarMeta(this.eid()!, p.id!, {
        ano: this.am()[0],
        mes: m.mes,
        tipo: m.tipo,
        faixas: m.faixas,
      })
      .subscribe({
        next: () => this.ok(`Meta de ${NOMES_MES[m.mes - 1]} salva.`),
        error: this.falha,
      });
  }

  alternar(chave: string) {
    if (this.excluidos.has(chave)) this.excluidos.delete(chave);
    else this.excluidos.add(chave);
  }

  salvarAjuste(p: PlanoComissao) {
    const [ano, mes] = this.am();
    this.api
      .ajustarPL(this.eid()!, p.id!, {
        ano,
        mes,
        valor: this.ajuste || 0,
        excluidos: [...this.excluidos],
      })
      .subscribe({ next: () => this.ok('PL ajustado.'), error: this.falha });
  }

  gerar(p: PlanoComissao) {
    const [ano, mes] = this.am();
    this.api.gerarContaComissao(this.eid()!, p.id!, ano, mes).subscribe({
      next: (r) =>
        this.ok(
          `Conta ${r.situacao}${r.vencimento ? ' · vence ' + r.vencimento.split('-').reverse().join('/') : ''}.`,
        ),
      error: this.falha,
    });
  }

  pdf(p: PlanoComissao) {
    const [ano, mes] = this.am();
    this.api
      .demonstrativoComissao(this.eid()!, p.id!, ano, mes)
      .subscribe((b) => salvarBlob(b, `comissao-${p.produtor.toLowerCase()}-${this.mes()}.pdf`));
  }

  syncSaude(p: PlanoComissao) {
    this.api
      .sincronizarSaude(this.eid()!, p.id!)
      .subscribe({ next: (r) => this.ok(`${r.linhas} linhas de saúde lidas.`), error: this.falha });
  }

  enviarSaude(p: PlanoComissao, ev: Event) {
    const f = (ev.target as HTMLInputElement).files?.[0];
    if (f)
      this.api
        .importarSaude(this.eid()!, p.id!, f)
        .subscribe({
          next: (r) => this.ok(`${r.linhas} linhas de saúde lidas.`),
          error: this.falha,
        });
  }
}
