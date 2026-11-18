# Categorização com o Claude (sem custo de API)

O FinBPO tem um **conector MCP** que o Claude do seu computador usa para ler e categorizar
lançamentos. O consumo entra na sua assinatura do Claude (Pro/Max), não em cobrança de API.

> No Windows, use sempre `127.0.0.1` em vez de `localhost`: com Docker + WSL, `localhost` pode
> tentar IPv6 e falhar.

## 1. Ligar o conector no FinBPO

1. Gere um token no PowerShell:
   ```powershell
   -join ((1..32) | % { '{0:x2}' -f (Get-Random -Max 256) })
   ```
2. No arquivo `.env` do projeto, adicione:
   ```
   MCP_TOKEN=cole-o-token-aqui
   ```
3. Reinicie: `docker compose up --build`.

O conector fica em `http://127.0.0.1:8000/mcp` e só responde com o token. Para testar:
```powershell
$t = "SEU_TOKEN"
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/mcp -Headers @{Authorization="Bearer $t"; Accept="application/json, text/event-stream"} -ContentType "application/json" -Body '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"listar_entidades","arguments":{}}}'
```
A resposta deve trazer `jsonrpc 2.0` e `isError=False`.

## 2. Conectar o Claude

### Claude Desktop (Windows)
Requer o [Node.js](https://nodejs.org) (LTS) instalado.

1. Feche o Claude por completo (confira no Gerenciador de Tarefas).
2. Abra o `claude_desktop_config.json`:
   - Instalação normal: `%APPDATA%\Claude\claude_desktop_config.json`
   - Instalação pela Microsoft Store: `%LOCALAPPDATA%\Claude-Data\claude_<id>\claude_desktop_config.json`

   Para localizar:
   ```powershell
   Get-ChildItem -Path $env:APPDATA, $env:LOCALAPPDATA -Filter "claude_desktop_config.json" -Recurse -ErrorAction SilentlyContinue
   ```
3. Logo depois do primeiro `{`, acrescente o bloco abaixo (sem apagar o resto do arquivo):
   ```json
     "mcpServers": {
       "finbpo": {
         "command": "cmd",
         "args": ["/c", "npx", "-y", "mcp-remote", "http://127.0.0.1:8000/mcp", "--header", "Authorization:${FINBPO_AUTH}"],
         "env": { "FINBPO_AUTH": "Bearer SEU_TOKEN" }
       }
     },
   ```
4. Salve, abra o Claude e procure **finbpo** em **+ → Plugins**.

O conector funciona nas conversas de chat. Nas sessões de código (Claude Code), use o comando abaixo.

### Claude Code (terminal)
```bash
claude mcp add --transport http finbpo http://127.0.0.1:8000/mcp --header "Authorization: Bearer SEU_TOKEN"
```

> O claude.ai no navegador não alcança o seu computador; para usá-lo, o FinBPO precisa estar
> publicado num servidor com HTTPS.

## 3. Usar

Com o Docker rodando, peça ao Claude, por exemplo:

- "Use o finbpo e categorize os lançamentos pendentes da Corretora X de novembro."
- "Categorize os pendentes de todas as empresas; crie regra para os fornecedores recorrentes."
- "Faça uma análise do resultado de outubro da clínica."

| Ferramenta | O que faz |
|---|---|
| `listar_entidades` | Empresas e pessoas físicas cadastradas |
| `listar_categorias` | Plano de contas da entidade |
| `lancamentos_sem_categoria` | Pendentes, com descrição, quem pagou/recebeu e a sugestão do aprendizado interno |
| `categorizar_lancamentos` | Grava as categorias (marcadas "por Claude" para revisão) e, se pedido, cria regras |
| `resumo_do_mes` | DRE do mês e totais a pagar/receber |

Tudo que o Claude categoriza aparece como **"por Claude"** nas telas de Lançamentos e Conciliação.

## Problemas comuns

| Sintoma | Causa provável |
|---|---|
| finbpo não aparece em Plugins | Claude não foi fechado por completo antes de salvar, ou JSON com vírgula/aspa faltando |
| "A conexão subjacente estava fechada" | Endereço com `localhost`; troque por `127.0.0.1` |
| Erro 401 | Token diferente entre `.env` e a configuração do Claude, ou backend não reiniciado |
| Erro de conexão | Docker parado: rode `docker compose up` |

## Aprendizado interno (sem Claude)

- **Regra por CPF/CNPJ**: ao categorizar com "criar regra", os próximos lançamentos da mesma contraparte são categorizados sozinhos.
- **Sugestões**: lançamentos de quem você já categorizou, ou com descrição parecida, recebem sugestão na Conciliação ("aceitar" ou "Aceitar N sugestões").
