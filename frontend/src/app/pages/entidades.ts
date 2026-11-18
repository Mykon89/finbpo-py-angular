import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../core/api';
import { mensagemErro } from '../core/auth';
import { EntidadeAtual } from '../core/entidade-atual';
import { DataBrPipe, DocumentoPipe, documentoFormatado, soDigitos } from '../core/formato';
import { DadosCNPJ, Entidade, SEGMENTOS, Segmento } from '../core/models';

type Formulario = Partial<Omit<Entidade, 'id'>> & {
  tipo: 'PJ' | 'PF';
  segmento: Segmento;
  nome: string;
};

function cnpjValido(v: string): boolean {
  const c = soDigitos(v);
  if (c.length !== 14 || /^(\d)\1+$/.test(c)) return false;
  const dv = (base: string) => {
    const pesos = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2].slice(-base.length);
    const r = [...base].reduce((s, d, i) => s + Number(d) * pesos[i], 0) % 11;
    return r < 2 ? '0' : String(11 - r);
  };
  return c[12] === dv(c.slice(0, 12)) && c[13] === dv(c.slice(0, 13));
}

const CAMPOS_RECEITA = [
  'razao_social',
  'nome_fantasia',
  'situacao_cadastral',
  'data_abertura',
  'natureza_juridica',
  'porte',
  'cnae_principal',
  'cnae_descricao',
  'cnaes_secundarios',
  'optante_simples',
  'mei',
  'cep',
  'logradouro',
  'numero',
  'complemento',
  'bairro',
  'municipio',
  'uf',
  'telefone',
  'email',
] as const;

@Component({
  selector: 'app-entidades',
  imports: [FormsModule, DocumentoPipe, DataBrPipe],
  template: `
    <header class="cabecalho">
      <h1>Entidades</h1>
      @if (!aberto()) {
        <button class="primario" type="button" (click)="novo()">Nova entidade</button>
      }
    </header>

    @if (aberto()) {
      <form class="cartao formulario" (ngSubmit)="salvar()">
        <div class="topo">
          <h2>{{ editandoId() ? 'Editar entidade' : 'Nova entidade' }}</h2>
          <div class="alternador" role="radiogroup" aria-label="Tipo de entidade">
            <button
              type="button"
              [class.ativo]="f.tipo === 'PJ'"
              [disabled]="!!editandoId()"
              (click)="mudarTipo('PJ')"
            >
              Pessoa jurídica
            </button>
            <button
              type="button"
              [class.ativo]="f.tipo === 'PF'"
              [disabled]="!!editandoId()"
              (click)="mudarTipo('PF')"
            >
              Pessoa física
            </button>
          </div>
        </div>

        <fieldset>
          <legend>Identificação</legend>
          <div class="grade">
            @if (f.tipo === 'PJ') {
              <label class="cnpj">
                CNPJ
                <div class="com-botao">
                  <input
                    name="documento"
                    inputmode="numeric"
                    placeholder="00.000.000/0000-00"
                    autocomplete="off"
                    [ngModel]="f.documento"
                    (ngModelChange)="digitouCnpj($event)"
                  />
                  <button type="button" [disabled]="buscando() || !cnpjOk()" (click)="buscar()">
                    {{ buscando() ? 'Buscando…' : 'Buscar' }}
                  </button>
                </div>
              </label>
            } @else {
              <label
                >CPF (opcional)
                <input
                  name="documento"
                  inputmode="numeric"
                  [(ngModel)]="f.documento"
                  placeholder="000.000.000-00"
              /></label>
            }
            <label>
              Segmento
              <select
                name="segmento"
                [(ngModel)]="f.segmento"
                [disabled]="f.tipo === 'PF' || !!editandoId()"
              >
                @for (s of segmentosPJ; track s[0]) {
                  <option [ngValue]="s[0]">{{ s[1] }}</option>
                }
                @if (f.tipo === 'PF') {
                  <option ngValue="pf">Pessoa física</option>
                }
              </select>
            </label>
            <label class="largo">
              Nome de exibição
              <input
                name="nome"
                [(ngModel)]="f.nome"
                required
                placeholder="Como aparece no menu e nos relatórios"
              />
            </label>
          </div>

          @if (aviso(); as a) {
            <p class="aviso" [class.erro]="a.erro">{{ a.texto }}</p>
          }
          @if (f.situacao_cadastral && f.situacao_cadastral.toUpperCase() !== 'ATIVA') {
            <p class="aviso erro">
              Situação cadastral na Receita: <strong>{{ f.situacao_cadastral }}</strong>
            </p>
          }
        </fieldset>

        @if (f.tipo === 'PJ') {
          <fieldset>
            <legend>Dados da Receita Federal</legend>
            <div class="grade">
              <label class="largo"
                >Razão social <input name="razao_social" [(ngModel)]="f.razao_social"
              /></label>
              <label class="largo"
                >Nome fantasia <input name="nome_fantasia" [(ngModel)]="f.nome_fantasia"
              /></label>
              <label>Situação <input name="situacao" [(ngModel)]="f.situacao_cadastral" /></label>
              <label
                >Abertura <input name="abertura" type="date" [(ngModel)]="f.data_abertura"
              /></label>
              <label
                >Natureza jurídica <input name="natureza" [(ngModel)]="f.natureza_juridica"
              /></label>
              <label>Porte <input name="porte" [(ngModel)]="f.porte" /></label>
              <label
                >Simples Nacional
                <select name="simples" [(ngModel)]="f.optante_simples">
                  <option [ngValue]="null">—</option>
                  <option [ngValue]="true">Optante</option>
                  <option [ngValue]="false">Não optante</option>
                </select>
              </label>
              <label
                >MEI
                <select name="mei" [(ngModel)]="f.mei">
                  <option [ngValue]="null">—</option>
                  <option [ngValue]="true">Sim</option>
                  <option [ngValue]="false">Não</option>
                </select>
              </label>
              <label class="largo">
                CNAE principal
                <input name="cnae" [ngModel]="cnaeTexto()" readonly />
              </label>
            </div>
            @if (f.cnaes_secundarios?.length) {
              <details>
                <summary>{{ f.cnaes_secundarios!.length }} CNAE(s) secundário(s)</summary>
                <ul>
                  @for (c of f.cnaes_secundarios; track c.codigo) {
                    <li>{{ c.codigo }} · {{ c.descricao }}</li>
                  }
                </ul>
              </details>
            }
          </fieldset>
        }

        <fieldset>
          <legend>Endereço e contato</legend>
          <div class="grade">
            <label>CEP <input name="cep" inputmode="numeric" [(ngModel)]="f.cep" /></label>
            <label class="largo"
              >Logradouro <input name="logradouro" [(ngModel)]="f.logradouro"
            /></label>
            <label>Número <input name="numero" [(ngModel)]="f.numero" /></label>
            <label>Complemento <input name="complemento" [(ngModel)]="f.complemento" /></label>
            <label>Bairro <input name="bairro" [(ngModel)]="f.bairro" /></label>
            <label>Município <input name="municipio" [(ngModel)]="f.municipio" /></label>
            <label>UF <input name="uf" maxlength="2" [(ngModel)]="f.uf" /></label>
            <label>E-mail <input name="email" type="email" [(ngModel)]="f.email" /></label>
            <label
              >Telefone <input name="telefone" inputmode="tel" [(ngModel)]="f.telefone"
            /></label>
          </div>
        </fieldset>

        @if (erro()) {
          <p class="erro">{{ erro() }}</p>
        }
        <div class="acoes-form">
          <button class="primario" type="submit" [disabled]="salvando()">
            {{ editandoId() ? 'Salvar alterações' : 'Cadastrar' }}
          </button>
          <button type="button" class="link" (click)="fechar()">Cancelar</button>
          @if (!editandoId()) {
            <span class="sutil">Cada entidade recebe um plano de contas padrão do segmento.</span>
          }
        </div>
      </form>
    }

    <div class="cartao sem-padding">
      <table>
        <thead>
          <tr>
            <th>Nome</th>
            <th>Segmento</th>
            <th>Documento</th>
            <th>Cidade</th>
            <th>Situação</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          @for (e of ent.lista(); track e.id) {
            <tr>
              <td>
                {{ e.nome }}
                @if (e.razao_social && e.razao_social !== e.nome) {
                  <div class="sutil pequeno">{{ e.razao_social }}</div>
                }
              </td>
              <td>{{ segmentos[e.segmento] }}</td>
              <td>{{ e.documento | documento }}</td>
              <td>{{ e.municipio ? e.municipio + '/' + e.uf : '—' }}</td>
              <td>
                @if (e.situacao_cadastral) {
                  <span
                    class="status"
                    [attr.data-s]="
                      e.situacao_cadastral.toUpperCase() === 'ATIVA' ? 'pago' : 'parcial'
                    "
                    >{{ e.situacao_cadastral }}</span
                  >
                  @if (e.dados_atualizados_em) {
                    <div class="sutil pequeno">em {{ e.dados_atualizados_em | dataBr }}</div>
                  }
                } @else {
                  —
                }
              </td>
              <td class="acoes">
                <button type="button" class="link" (click)="editar(e)">Editar</button>
                @if (ent.id() === e.id) {
                  <strong>selecionada</strong>
                } @else {
                  <button type="button" (click)="ent.selecionar(e.id)">Selecionar</button>
                }
              </td>
            </tr>
          } @empty {
            <tr>
              <td colspan="6" class="sutil">
                Nenhuma entidade. Clique em "Nova entidade" e digite o CNPJ.
              </td>
            </tr>
          }
        </tbody>
      </table>
    </div>
  `,
  styles: `
    .formulario {
      display: flex;
      flex-direction: column;
      gap: 16px;
      margin-bottom: 16px;
    }
    .topo {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }
    .topo h2 {
      margin: 0;
    }
    fieldset {
      border: 1px solid var(--borda);
      border-radius: 8px;
      padding: 12px 14px 14px;
      margin: 0;
    }
    legend {
      font-weight: 600;
      padding: 0 6px;
      font-size: 0.85rem;
    }
    .grade {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 12px;
    }
    .largo {
      grid-column: span 2;
    }
    .cnpj {
      grid-column: span 2;
    }
    .com-botao {
      display: flex;
      gap: 6px;
    }
    .com-botao input {
      flex: 1;
      min-width: 0;
      font-size: 1rem;
      letter-spacing: 0.02em;
    }
    .alternador {
      display: inline-flex;
      border: 1px solid var(--borda);
      border-radius: 8px;
      overflow: hidden;
    }
    .alternador button {
      border: none;
      border-radius: 0;
      background: transparent;
    }
    .alternador button.ativo {
      background: var(--primaria);
      color: var(--primaria-texto);
    }
    .aviso {
      margin: 10px 0 0;
      padding: 8px 12px;
      border-radius: 6px;
      background: var(--fundo-sutil);
    }
    .aviso.erro {
      color: var(--negativo);
    }
    details {
      margin-top: 10px;
      font-size: 0.85rem;
    }
    details ul {
      margin: 6px 0 0;
      padding-left: 18px;
    }
    .acoes-form {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }
    .acoes {
      white-space: nowrap;
      text-align: right;
    }
    .pequeno {
      font-size: 0.75rem;
    }
    input[readonly] {
      background: var(--fundo-sutil);
    }
    @media (max-width: 600px) {
      .largo,
      .cnpj {
        grid-column: 1 / -1;
      }
    }
  `,
})
export class Entidades {
  private api = inject(Api);
  protected ent = inject(EntidadeAtual);
  segmentos = SEGMENTOS;
  segmentosPJ = (Object.entries(SEGMENTOS) as [Segmento, string][]).filter(([s]) => s !== 'pf');

  aberto = signal(false);
  editandoId = signal<number | null>(null);
  buscando = signal(false);
  salvando = signal(false);
  cnpjOk = signal(false);
  aviso = signal<{ texto: string; erro: boolean } | null>(null);
  erro = signal('');
  f: Formulario = this.vazio('PJ');
  private ultimoBuscado = '';

  novo() {
    this.f = this.vazio('PJ');
    this.editandoId.set(null);
    this.limparMensagens();
    this.cnpjOk.set(false);
    this.ultimoBuscado = '';
    this.aberto.set(true);
  }

  editar(e: Entidade) {
    const { id, ...resto } = e;
    this.f = { ...resto, documento: documentoFormatado(e.documento) };
    this.editandoId.set(id);
    this.limparMensagens();
    this.cnpjOk.set(cnpjValido(e.documento ?? ''));
    this.ultimoBuscado = soDigitos(e.documento);
    this.aberto.set(true);
  }

  fechar() {
    this.aberto.set(false);
    this.editandoId.set(null);
  }

  mudarTipo(tipo: 'PJ' | 'PF') {
    if (this.f.tipo === tipo) return;
    this.f = this.vazio(tipo);
    this.limparMensagens();
  }

  digitouCnpj(valor: string) {
    const d = soDigitos(valor).slice(0, 14);
    this.f.documento = d.length === 14 ? documentoFormatado(d) : valor;
    const ok = cnpjValido(d);
    this.cnpjOk.set(ok);
    if (d.length === 14 && !ok)
      this.aviso.set({ texto: 'CNPJ inválido: confira os dígitos.', erro: true });
    else if (ok && d !== this.ultimoBuscado) this.buscar();
    else if (d.length < 14) this.aviso.set(null);
  }

  buscar() {
    const cnpj = soDigitos(this.f.documento);
    if (!cnpjValido(cnpj)) return;
    this.ultimoBuscado = cnpj;
    this.buscando.set(true);
    this.aviso.set({ texto: 'Consultando a Receita Federal…', erro: false });
    this.api.consultarCnpj(cnpj).subscribe({
      next: (d) => {
        this.aplicar(d);
        this.buscando.set(false);
        this.aviso.set({
          texto: `Dados preenchidos a partir da Receita Federal (fonte: ${d.fonte}). Confira e ajuste se precisar.`,
          erro: false,
        });
      },
      error: (e) => {
        this.buscando.set(false);
        this.aviso.set({
          texto: `${mensagemErro(e)} Você pode preencher os dados manualmente.`,
          erro: true,
        });
      },
    });
  }

  salvar() {
    this.erro.set('');
    this.salvando.set(true);
    const dados = this.paraEnvio();
    const id = this.editandoId();
    const req = id ? this.api.atualizarEntidade(id, dados) : this.api.criarEntidade(dados);
    req.subscribe({
      next: (e) => {
        this.salvando.set(false);
        this.fechar();
        this.ent.carregar();
        if (!id) this.ent.selecionar(e.id);
      },
      error: (err) => {
        this.salvando.set(false);
        this.erro.set(mensagemErro(err));
      },
    });
  }

  cnaeTexto() {
    return this.f.cnae_principal
      ? `${this.f.cnae_principal.replace(/^(\d{4})(\d)(\d{2})$/, '$1-$2/$3')} · ${this.f.cnae_descricao ?? ''}`
      : '';
  }

  private aplicar(d: DadosCNPJ) {
    for (const campo of CAMPOS_RECEITA) {
      const valor = d[campo];
      if (valor !== null && valor !== undefined && valor !== '')
        (this.f as Record<string, unknown>)[campo] = valor;
    }
    if (!this.f.nome || !this.editandoId()) this.f.nome = this.nomeSugerido(d);
    if (d.segmento_sugerido && d.segmento_sugerido !== 'pf' && !this.editandoId())
      this.f.segmento = d.segmento_sugerido;
  }

  private nomeSugerido(d: DadosCNPJ): string {
    const fantasia = d.nome_fantasia?.trim();
    const nome = fantasia && fantasia.length > 2 ? fantasia : (d.razao_social ?? '');
    // Receita devolve em MAIÚSCULAS; deixa mais legível
    if (nome !== nome.toUpperCase()) return nome;
    const minusculas = new Set(['de', 'da', 'do', 'das', 'dos', 'e']);
    return nome
      .toLowerCase()
      .split(' ')
      .map((p, i) =>
        i > 0 && minusculas.has(p)
          ? p
          : /^(ltda|me|epp|sa|s\/a|eireli)$/.test(p)
            ? p.toUpperCase()
            : p.charAt(0).toUpperCase() + p.slice(1),
      )
      .join(' ');
  }

  private paraEnvio(): Partial<Entidade> {
    const dados: Record<string, unknown> = {
      ...this.f,
      documento: soDigitos(this.f.documento) || null,
    };
    for (const [k, v] of Object.entries(dados)) if (v === '') dados[k] = null;
    delete dados['ativo'];
    delete dados['dados_atualizados_em'];
    if (this.editandoId()) {
      delete dados['tipo'];
      delete dados['segmento'];
    }
    return dados as Partial<Entidade>;
  }

  private limparMensagens() {
    this.aviso.set(null);
    this.erro.set('');
  }

  private vazio(tipo: 'PJ' | 'PF'): Formulario {
    return {
      tipo,
      segmento: tipo === 'PF' ? 'pf' : 'corretora',
      nome: '',
      documento: '',
      cnaes_secundarios: null,
    };
  }
}
