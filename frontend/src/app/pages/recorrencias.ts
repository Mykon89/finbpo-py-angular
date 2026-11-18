import { Component, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../core/api';
import { mensagemErro } from '../core/auth';
import { EntidadeAtual } from '../core/entidade-atual';
import { BrlPipe, DataBrPipe, hojeIso } from '../core/formato';
import { AjusteDiaUtil, Categoria, Frequencia, Recorrencia, Titulo } from '../core/models';

const FREQUENCIAS: { valor: Frequencia; rotulo: string }[] = [
  { valor: 'mensal', rotulo: 'Mensal' },
  { valor: 'semanal', rotulo: 'Semanal' },
  { valor: 'quinzenal', rotulo: 'Quinzenal' },
  { valor: 'anual', rotulo: 'Anual' },
  { valor: 'parcelada', rotulo: 'Parcelada (mensal, n vezes)' },
  { valor: 'unica', rotulo: 'Única' },
];

@Component({
  selector: 'app-recorrencias',
  imports: [FormsModule, BrlPipe, DataBrPipe],
  template: `
    <header class="cabecalho">
      <h1>Recorrências</h1>
      <div class="gerar">
        <label
          >Gerar contas até
          <input type="date" [(ngModel)]="ate" aria-label="Gerar contas até" />
        </label>
        <button type="button" class="primario" (click)="gerar()">Gerar contas</button>
      </div>
    </header>
    <p class="sutil">
      Contas que se repetem (aluguel, pró-labore, DAS, parcelas). "Gerar contas" cria no Contas a
      pagar/receber o que falta até a data, sem duplicar. Use <code>{{ '{' }}COMP{{ '}' }}</code> na
      descrição para o mês de competência (mês anterior) e <code>{{ '{' }}MES{{ '}' }}</code> para o
      mês do vencimento.
    </p>

    @if (erro()) {
      <p class="erro">{{ erro() }}</p>
    }
    @if (gerados(); as g) {
      <p class="cartao aviso">
        @if (g.length) {
          {{ g.length }} contas criadas:
          @for (t of g.slice(0, 8); track t.id) {
            <span class="item">{{ t.descricao }} ({{ t.vencimento | dataBr }})</span>
          }
          @if (g.length > 8) {
            e mais {{ g.length - 8 }}.
          }
        } @else {
          Nada a gerar: as contas até essa data já existem.
        }
      </p>
    }

    <form class="cartao formulario" (ngSubmit)="criar()">
      <label
        >Fornecedor / cliente
        <input name="cp" [(ngModel)]="novo.contraparte_nome" placeholder="Ex.: CONHECER CONTABIL" />
      </label>
      <label class="largo"
        >Descrição
        <input name="desc" [(ngModel)]="novo.descricao" required placeholder="HONORÁRIOS {COMP}" />
      </label>
      <label
        >Tipo
        <select name="tipo" [(ngModel)]="novo.tipo">
          <option value="pagar">A pagar</option>
          <option value="receber">A receber</option>
        </select>
      </label>
      <label
        >Valor
        <input
          name="valor"
          type="number"
          step="0.01"
          min="0.01"
          [(ngModel)]="novo.valor"
          required
        />
      </label>
      <label
        >Frequência
        <select name="freq" [(ngModel)]="novo.frequencia">
          @for (f of frequencias; track f.valor) {
            <option [value]="f.valor">{{ f.rotulo }}</option>
          }
        </select>
      </label>
      <label
        >Início
        <input name="inicio" type="date" [(ngModel)]="novo.inicio" required />
      </label>
      <label
        >Dia do mês
        <input
          name="dia"
          type="number"
          min="1"
          max="31"
          [(ngModel)]="novo.dia"
          placeholder="do início"
        />
      </label>
      <label
        >ou nº dia útil
        <input
          name="du"
          type="number"
          min="1"
          max="23"
          [(ngModel)]="novo.dia_util"
          placeholder="ex.: 5"
        />
      </label>
      <label
        >Se cair em fim de semana/feriado
        <select name="ajuste" [(ngModel)]="novo.ajuste">
          <option value="nenhum">Manter a data</option>
          <option value="antecipar">Antecipar</option>
          <option value="postergar">Postergar</option>
        </select>
      </label>
      @if (novo.frequencia === 'parcelada') {
        <label
          >Parcelas
          <input name="parc" type="number" min="1" [(ngModel)]="novo.parcelas" />
        </label>
      }
      <label
        >Fim (opcional)
        <input name="fim" type="date" [(ngModel)]="novo.fim" />
      </label>
      <label
        >Categoria
        <select name="cat" [(ngModel)]="novo.categoria_id">
          <option [ngValue]="null">—</option>
          @for (c of categoriasAtivas(); track c.id) {
            <option [ngValue]="c.id">{{ c.nome }}</option>
          }
        </select>
      </label>
      <label
        >Natureza
        <select name="nat" [(ngModel)]="novo.natureza">
          <option [ngValue]="null">—</option>
          <option value="fixa">Fixa</option>
          <option value="variavel">Variável</option>
        </select>
      </label>
      <label
        >Reajuste % ao ano
        <input name="reaj" type="number" step="0.01" [(ngModel)]="novo.reajuste_pct" />
      </label>
      <button class="primario" type="submit" [disabled]="!novo.descricao || !novo.valor">
        Adicionar
      </button>
    </form>

    <section class="cartao sem-padding">
      <table>
        <thead>
          <tr>
            <th>Código</th>
            <th>Fornecedor / descrição</th>
            <th>Frequência</th>
            <th class="num">Valor</th>
            <th>Próximo</th>
            <th>Categoria</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          @for (r of lista(); track r.id) {
            <tr [class.inativa]="!r.ativa">
              <td>{{ r.codigo }}</td>
              <td>
                <strong>{{ r.contraparte_nome ?? '—' }}</strong>
                <div class="sutil">{{ r.descricao }}</div>
              </td>
              <td>
                {{ rotuloFreq(r.frequencia) }}
                <div class="sutil pequeno">{{ quando(r) }}</div>
              </td>
              <td class="num">{{ r.valor | brl }}</td>
              <td>{{ r.proximo_vencimento | dataBr }}</td>
              <td>{{ nomeCategoria(r.categoria_id) }}</td>
              <td class="acoes">
                <button type="button" class="link" (click)="gerarUma(r)" [disabled]="!r.ativa">
                  Gerar
                </button>
                <button type="button" class="link" (click)="alternar(r)">
                  {{ r.ativa ? 'Pausar' : 'Reativar' }}
                </button>
                <button type="button" class="link perigo" (click)="remover(r)">Excluir</button>
              </td>
            </tr>
          } @empty {
            <tr>
              <td colspan="7" class="sutil">Nenhuma recorrência cadastrada.</td>
            </tr>
          }
        </tbody>
      </table>
    </section>
  `,
  styles: `
    .gerar {
      display: flex;
      gap: 8px;
      align-items: end;
    }
    .aviso {
      margin-bottom: 16px;
    }
    .item {
      display: inline-block;
      margin-right: 8px;
    }
    .formulario {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 12px;
      align-items: end;
      margin-bottom: 16px;
    }
    .largo {
      grid-column: span 2;
    }
    .acoes {
      text-align: right;
      white-space: nowrap;
    }
    .inativa td {
      opacity: 0.55;
    }
    .perigo {
      color: var(--negativo);
    }
    .pequeno {
      font-size: 0.78rem;
    }
    section.cartao {
      overflow-x: auto;
    }
    @media (max-width: 700px) {
      .largo {
        grid-column: auto;
      }
    }
  `,
})
export class Recorrencias {
  private api = inject(Api);
  private ent = inject(EntidadeAtual);
  frequencias = FREQUENCIAS;
  lista = signal<Recorrencia[]>([]);
  categorias = signal<Categoria[]>([]);
  categoriasAtivas = computed(() => this.categorias().filter((c) => c.ativo));
  gerados = signal<Titulo[] | null>(null);
  erro = signal('');
  ate = fimDoProximoMes();
  novo = this.vazio();

  constructor() {
    effect(() => this.carregar());
  }

  private vazio() {
    return {
      contraparte_nome: '',
      descricao: '',
      tipo: 'pagar' as 'pagar' | 'receber',
      valor: null as number | null,
      frequencia: 'mensal' as Frequencia,
      inicio: hojeIso(),
      fim: null as string | null,
      dia: null as number | null,
      dia_util: null as number | null,
      ajuste: 'nenhum' as AjusteDiaUtil,
      parcelas: null as number | null,
      categoria_id: null as number | null,
      natureza: null as 'fixa' | 'variavel' | null,
      reajuste_pct: null as number | null,
    };
  }

  carregar() {
    const eid = this.ent.id();
    if (!eid) return;
    this.api.recorrencias(eid).subscribe((l) => this.lista.set(l));
    this.api.categorias(eid).subscribe((c) => this.categorias.set(c));
  }

  private eid() {
    return this.ent.id();
  }

  private falha = (e: unknown) => this.erro.set(mensagemErro(e));

  criar() {
    const eid = this.eid();
    if (!eid) return;
    this.erro.set('');
    const dados = Object.fromEntries(
      Object.entries(this.novo).filter(([, v]) => v !== null && v !== ''),
    ) as unknown as Partial<Recorrencia>;
    this.api.criarRecorrencia(eid, dados).subscribe({
      next: () => {
        this.novo = this.vazio();
        this.carregar();
      },
      error: this.falha,
    });
  }

  gerar() {
    const eid = this.eid();
    if (!eid) return;
    this.api.gerarRecorrencias(eid, this.ate).subscribe({
      next: (g) => this.gerados.set(g),
      error: this.falha,
    });
  }

  gerarUma(r: Recorrencia) {
    const eid = this.eid();
    if (!eid) return;
    this.api.gerarRecorrencias(eid, this.ate, r.id).subscribe({
      next: (g) => this.gerados.set(g),
      error: this.falha,
    });
  }

  alternar(r: Recorrencia) {
    const eid = this.eid();
    if (!eid) return;
    this.api.atualizarRecorrencia(eid, r.id, { ativa: !r.ativa }).subscribe({
      next: () => this.carregar(),
      error: this.falha,
    });
  }

  remover(r: Recorrencia) {
    const eid = this.eid();
    if (!eid || !confirm(`Excluir a recorrência "${r.descricao}"? As contas já geradas ficam.`))
      return;
    this.api
      .removerRecorrencia(eid, r.id)
      .subscribe({ next: () => this.carregar(), error: this.falha });
  }

  rotuloFreq(f: Frequencia) {
    return FREQUENCIAS.find((x) => x.valor === f)?.rotulo.split(' (')[0] ?? f;
  }

  quando(r: Recorrencia) {
    const partes: string[] = [];
    if (r.dia_util) partes.push(`${r.dia_util}º dia útil`);
    else if (r.dia && r.frequencia !== 'semanal' && r.frequencia !== 'quinzenal')
      partes.push(`dia ${r.dia}`);
    if (r.ajuste !== 'nenhum') partes.push(r.ajuste === 'antecipar' ? 'antecipa' : 'posterga');
    if (r.parcelas) partes.push(`${r.parcelas}x`);
    if (r.reajuste_pct) partes.push(`reajuste ${r.reajuste_pct}%`);
    return partes.join(' · ');
  }

  nomeCategoria(id: number | null) {
    return this.categorias().find((c) => c.id === id)?.nome ?? '—';
  }
}

function fimDoProximoMes(): string {
  const d = new Date();
  const fim = new Date(d.getFullYear(), d.getMonth() + 2, 0);
  return `${fim.getFullYear()}-${String(fim.getMonth() + 1).padStart(2, '0')}-${String(fim.getDate()).padStart(2, '0')}`;
}
