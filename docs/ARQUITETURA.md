# FinBPO: proposta de arquitetura

Sistema multiempresa e multicliente para:
- 2 corretoras de seguros (saúde e ramos elementares)
- 1 clínica de estética
- carteira de clientes pessoa física (BPO financeiro pessoal)

---

## 1. Módulos

| Módulo | Escopo |
|---|---|
| **Núcleo** | Entidades (PJ/PF), usuários, permissões, plano de contas por segmento, centros de custo, contas bancárias e cartões |
| **Contas a Pagar** | Lançamento manual ou via boleto/NF (código de barras, PDF, e-mail), recorrências, aprovação, agenda de vencimentos, baixa automática pela conciliação |
| **Contas a Receber** | Títulos, parcelas, previsão de recebíveis, inadimplência, cobrança |
| **Importação** | Leitura de OFX (vários bancos), PDF de fatura de cartão, CSV/XLSX e Open Finance |
| **Conciliação** | Casamento automático entre extrato e títulos (valor, data ± n dias, descrição) e regras de categorização |
| **Corretora** | Apólices e propostas, seguradoras, ramos, produtores, comissões previstas e realizadas, estornos e repasses |
| **Clínica** | Procedimentos, pacotes pré-pagos (receita diferida), comissão de profissionais, maquininhas (MDR, antecipação, D+30/parcelado) e custo de insumos |
| **Pessoa Física** | Orçamento, categorização, cartões, metas, patrimônio e apoio ao IRPF, com **nível de dados** por cliente (ver §5) |
| **Relatórios** | DRE gerencial, fluxo de caixa realizado e projetado, aging de AP/AR, margem por linha de negócio, consolidado do grupo |
| **Fechamento** | Checklist do mês, travamento do período e **PDF automático de análise mensal** (ver §6) |

---

## 2. Stack

| Camada | Escolha |
|---|---|
| Backend | Python 3.12, **FastAPI**, SQLAlchemy 2, Alembic, Pydantic |
| Banco de dados | **PostgreSQL** (multi-tenant por `entidade_id`, com Row-Level Security) |
| Jobs | Celery ou **Dramatiq** + Redis (importações, sincronização com Open Finance, fechamento) |
| Frontend | **Angular** (standalone components, Angular Material ou PrimeNG, ngx-charts/ECharts) |
| PDF | Template HTML (Jinja2) → **WeasyPrint**; gráficos com matplotlib (SVG) |
| Inteligência artificial | Claude API: categorização assistida, extração de faturas fora do padrão e texto da análise mensal |
| Armazenamento de arquivos | S3 ou MinIO (OFX, PDFs e relatórios gerados) |
| Autenticação | JWT + 2FA; perfis Admin / Operador / Cliente PF (só leitura) |

---

## 3. Importação de extratos e faturas

### OFX
- Biblioteca: `ofxtools`, com `ofxparse` como fallback.
- Pré-normalização obrigatória: os bancos brasileiros geram **OFX 1.x em SGML**, com encoding latin-1/cp1252, tags sem fechamento e datas com fuso `[-3:BRT]`.
- Deduplicação por `(conta, FITID)`, com fallback por hash de `(data, valor, memo)`, porque alguns bancos repetem FITID.
- Um adaptador por banco para corrigir particularidades (Itaú, Bradesco, BB, Santander, Caixa, Inter, Nubank, Sicoob, Sicredi, C6).

### Fatura de cartão (PDF)
- Pipeline: `pikepdf` (remove a senha, que geralmente são dígitos do CPF) → `pdfplumber`/`PyMuPDF` → **parser por emissor** (regex e layout).
- Cada parser trata: parcelas `03/10`, compras internacionais (valor em USD, cotação e IOF), estornos, encargos, anuidade e cartões adicionais.
- **Fallback com IA**: quando nenhum parser reconhece o PDF, a extração é feita pelo Claude com saída estruturada (JSON validado por Pydantic) e marcada como "revisar".
- Projeção automática das parcelas futuras em Contas a Pagar.

---

## 4. Integrações bancárias e Open Finance

| Via | Uso | Viabilidade |
|---|---|---|
| **Agregador Open Finance** (Pluggy, Belvo, Klavi) | Leitura de saldo, extrato e cartão de PF e PJ com consentimento do titular | ✅ Melhor caminho. Acesso direto ao Open Finance exige ser instituição autorizada pelo Banco Central, por isso o agregador é obrigatório |
| **APIs bancárias PJ** (Inter Empresas, Itaú, Bradesco, BB, Santander, Sicoob, Cora) | Extrato, boletos, Pix e pagamentos | ✅ Inter e Cora são simples (certificado mTLS). Os grandes bancos exigem convênio com o gerente |
| **Gateway de cobrança** (Asaas, Iugu, Inter) | Emissão de boletos/Pix com baixa automática via webhook | ✅ Recomendado para Contas a Receber da clínica e das corretoras |
| **Adquirentes** (Stone, Cielo, Rede, Getnet, PagBank) | Conciliação de vendas no cartão e de recebíveis da clínica | ⚠️ APIs disponíveis conforme o adquirente; alternativa: importar arquivo EDI/CSV |
| **CNAB 240/400** | Remessa e retorno de boletos e pagamentos em lote | ✅ Opção sem API, aceita por todos os bancos |
| **Iniciação de pagamento (Pix via Open Finance)** | Pagar contas pelo sistema | ⚠️ Fase futura; envolve custo e homologação |

Abstração no código: interface `FonteBancaria` (`sincronizar_contas`, `sincronizar_transacoes`) com implementações `OfxFonte`, `PluggyFonte`, `InterApiFonte` etc. A conciliação fica igual para todas as fontes.

Custos: os agregadores cobram por conexão ativa por mês. Vale validar o plano e o uso pessoal ou de desenvolvimento antes de fechar.

---

## 5. Pessoa física: níveis de dados

O sistema funciona com o que o cliente consegue enviar e mostra o nível de cada um:

| Nível | Dados disponíveis | O que o sistema entrega |
|---|---|---|
| 0 | Planilha, prints ou lançamentos manuais | Orçamento e categorias básicas |
| 1 | OFX da conta corrente | Fluxo realizado, categorização automática e recorrências |
| 2 | OFX + PDF das faturas | Visão completa de gastos, parcelas futuras e comprometimento de renda |
| 3 | Open Finance (consentimento) | Atualização automática, saldos e investimentos |

- Dados mínimos de cadastro: nome e e-mail. CPF opcional, necessário apenas para Open Finance ou para a senha do PDF.
- LGPD: termo de consentimento registrado, finalidade declarada, exportação e exclusão dos dados sob pedido, e criptografia dos campos sensíveis.
- Regras de categorização aprendidas por cliente (descrição → categoria), com a IA apenas sugerindo.

---

## 6. Fechamento mensal e PDF

Job agendado para o dia 1 (ou disparo manual) para cada entidade e para o consolidado:
1. Verifica pendências: itens não conciliados, títulos sem categoria e faturas não importadas. Se houver pendência, o fechamento fica em rascunho.
2. Calcula os indicadores: DRE, fluxo de caixa, aging, margem e variações contra o mês anterior, o mesmo mês do ano anterior e o orçamento.
3. Indicadores específicos por segmento:
   - **Corretora**: comissão por seguradora e por ramo, carteira ativa, estornos, cancelamentos e ticket médio.
   - **Clínica**: faturamento por procedimento, saldo de pacotes, taxa efetiva de cartão, CMV de insumos e comissão por profissional.
   - **Pessoa física**: gasto por categoria, comprometimento de renda, parcelas futuras e evolução patrimonial.
4. A IA redige a análise (destaques, alertas e recomendações) **somente a partir dos números calculados**, sem inventar dados.
5. Gera o PDF (WeasyPrint), arquiva, envia por e-mail e trava o período.

---

## 7. Agentes, skills, conectores e plugins

### Agentes por área

| Agente | Responsabilidade | Skills existentes | Skills a criar |
|---|---|---|---|
| **Contas a Pagar** | Capturar boletos e NFs do e-mail, lançar e agendar | `small-business:ap-processor`, `small-business:pay-the-bills`, `finance:journal-entry` | `leitura-boleto` |
| **Contas a Receber** | Cobrança, aging e previsão | `small-business:invoice-chase`, `small-business:cash-flow-snapshot` | — |
| **Conciliação** | Importar OFX e faturas, casar transações, tratar exceções | `finance:reconciliation`, `anthropic-skills:pdf` | `leitura-ofx`, `leitura-fatura-cartao` |
| **Corretora** | Extratos de comissão das seguradoras, estornos e repasses | `anthropic-skills:comissoes-trust` (já existe) | `comissoes-seguradoras` (genérica, uma regra por seguradora) |
| **Clínica** | Maquininhas, pacotes, comissões e insumos | `small-business:inventory-planner`, `small-business:restock` | `conciliacao-maquininha`, `pacotes-estetica` |
| **Pessoa Física** | Categorização, orçamento e IRPF | `small-business:tax-season-organizer` | `financas-pf` |
| **Fechamento e Relatórios** | Checklist, DRE, variações e PDF | `finance:close-management`, `small-business:close-month`, `small-business:month-end-prep`, `finance:financial-statements`, `finance:variance-analysis`, `small-business:report-pack` | `relatorio-mensal-pdf` |
| **Orquestrador** | Rotear pedidos para o agente certo e montar o resumo semanal | `small-business:smb-router`, `small-business:monday-brief`, `small-business:business-pulse` | — |

Para criar as skills novas: `anthropic-skills:skill-creator`. Recomendação: empacotar tudo em um plugin próprio (**finbpo**).

### Conectores

| Conector | Uso |
|---|---|
| **MCP próprio do FinBPO** (criar com `small-business:build-connector`) | ⭐ Essencial: dá aos agentes acesso de leitura e escrita aos títulos, à conciliação e aos relatórios do sistema |
| Gmail | Captura de boletos, NFs, faturas e extratos de comissão; envio do PDF mensal |
| Google Drive | Repositório de documentos e PDFs por cliente e por mês |
| Google Calendar | Vencimentos e datas de fechamento |
| Slack ou WhatsApp (via Zapier) | Alertas de vencimento e de pendências |
| Claude Docs | Notas de fechamento e procedimentos |

Não recomendados por não se aplicarem ao Brasil: QuickBooks, Xero, Gusto, Ramp e Expensify. Para contabilidade, a saída é exportar no layout do sistema contábil do contador (Domínio, Alterdata ou Contmatic).

---

## 8. Modelo de dados (núcleo)

```
entidade(id, tipo[PJ|PF], segmento[corretora|clinica|pf], nome, documento?)
conta_financeira(id, entidade_id, tipo[corrente|cartao|caixa|maquininha], banco, ...)
transacao(id, conta_id, data, valor, descricao, fitid, origem[ofx|pdf|api|manual], hash, conciliada)
titulo(id, entidade_id, tipo[pagar|receber], contraparte_id, categoria_id, centro_custo_id,
       vencimento, valor, status, recorrencia_id?)
baixa(id, titulo_id, transacao_id, valor, data)
categoria(id, entidade_id?, segmento, nome, grupo_dre)
regra_categorizacao(id, entidade_id, padrao, categoria_id, prioridade)
fechamento(id, entidade_id, competencia, status, pdf_url, snapshot_json)
-- corretora
seguradora, apolice(ramo, produtor_id, premio, pct_comissao), comissao(prevista|recebida|estornada)
-- clínica
procedimento, pacote(saldo_sessoes, receita_diferida), venda_cartao(adquirente, mdr, parcelas)
```

---

## 9. Roadmap

| Fase | Entrega |
|---|---|
| 1 | Núcleo, Contas a Pagar e a Receber, importação de OFX, conciliação e DRE simples |
| 2 | Parser de faturas de cartão, módulo Pessoa Física (níveis 0 a 2) e PDF do fechamento |
| 3 | Módulos Corretora (comissões) e Clínica (maquininha e pacotes) |
| 4 | Open Finance (agregador), API do Inter/Cora e gateway de cobrança |
| 5 | MCP do FinBPO, plugin de agentes e skills, análise mensal por IA |

---

## 10. Decisões pendentes

1. Bancos usados por cada empresa e cartões dos clientes PF (define a ordem dos parsers).
2. Seguradoras parceiras e o formato dos extratos de comissão (PDF, XLSX ou portal).
3. Maquininha e sistema de agenda da clínica.
4. Regime tributário de cada empresa (Simples ou Presumido) e sistema contábil do contador.
5. Quantidade prevista de clientes PF (define o custo do Open Finance).
6. Hospedagem: VPS (Docker) ou nuvem gerenciada.
