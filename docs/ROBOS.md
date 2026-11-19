# Baixar os extratos das seguradoras sem esforço

Os dois caminhos salvam os arquivos numa **pasta monitorada**; o FinBPO importa sozinho (a cada minuto),
reconhece a seguradora pelo conteúdo e não duplica. O resultado aparece em **Comissões → Pasta monitorada**.

## 1. Ligar a pasta monitorada (uma vez)
1. Crie a pasta, ex.: `C:\FinBPO\extratos`.
2. No `.env` do FinBPO:
   ```
   EXTRATOS_PASTA_HOST=C:/FinBPO/extratos
   EXTRATOS_ENTIDADE_ID=1
   ```
   (`1` = id da corretora no FinBPO. Para outra empresa, use uma subpasta com o id ou o CNPJ: `C:\FinBPO\extratos\2\`.)
3. `docker compose up --build`.

Dica: o arquivo pode ter qualquer nome. Se o nome não tiver a data (`dd-mm-aaaa`), vale o dia do download para
os formatos que precisam dela (Tokio XLSX, Petlove).

## 2. Claude in Chrome — para portais com token (supervisionado)
1. Instale a extensão **Claude in Chrome** e entre com a sua conta Claude.
2. Crie um **perfil do Chrome só para as seguradoras** e, nas configurações desse perfil, mude
   **Downloads → Local** para `C:\FinBPO\extratos`. Entre uma vez em cada portal e salve a senha nesse perfil.
3. Peça ao Claude (no painel da extensão), por exemplo:

   > Entre nos portais abaixo, no menu de extratos/demonstrativos de comissão, e baixe todos os extratos
   > **pagos desde 01/11/2026** que ainda não estão na pasta de downloads. Prefira o formato da lista
   > (PDF, TXT, CSV ou XLSX). Se pedir token, me avise e espere eu digitar.
   > - Porto: <endereço do portal do corretor> → Comissões → Analítico de pagamentos (.do)
   > - Tokio: <endereço> → Extrato do corretor (XLSX)
   > - Allianz: <endereço> → Extrato de comissões pagas por SUSEP (PDF)
   > - …

   Ajuste a lista (URL e caminho do menu) uma vez e guarde o texto: depois é só trocar a data.

## 3. Robô Playwright — para portais com usuário e senha (sozinho)
Roda no seu computador (Node.js já instalado):
```powershell
cd C:\caminho\finbpo-py-angular\robos
npm install
npx playwright install chromium
copy config.exemplo.json config.json   # ajuste "pasta" e a lista de seguradoras
npm run baixar -- porto                # 1ª vez: faça o login na janela; depois ele lembra
```
- Cada seguradora tem um perfil de navegador próprio em `robos\perfis\` (sessão e "lembrar dispositivo" ficam salvos lá;
  o FinBPO não guarda senha). Se a sessão expirar, a janela abre e espera você entrar (até 5 min) e o robô continua.
- Baixa só o que é novo (registro em `robos\perfis\baixados.json`) e salva como `PORTO_EXTRATO_17-11-2026_<nº>.ext`.
- Erro em um portal: print da tela em `robos\perfis\<seguradora>-erro.png`.

### Rodar todo dia sozinho
Agendador de Tarefas do Windows → Criar tarefa básica → Diariamente às 8h → Programa: `robos\baixar-extratos.bat`.
(Precisa do computador ligado e com o usuário logado, porque o navegador abre na tela.)

### Criar o robô de uma seguradora
Eu não tenho acesso aos portais, então o caminho de cada um é gravado por você, uma vez:
```powershell
npm run gravar -- https://endereco-do-portal-da-seguradora
```
Faça login e o caminho até **baixar um extrato**; o Playwright escreve o código numa janela ao lado.
Copie esse código e me envie (pode apagar senhas que aparecerem nele) que eu transformo em `robos\portais\<seguradora>.mjs`
no formato de `portais\_modelo.mjs` (vários extratos, filtro por data, sem repetir).

## Qual usar em cada portal
| Portal pede | Melhor opção |
|---|---|
| Só usuário e senha (ou "lembrar dispositivo" que dura semanas) | Robô (roda sozinho, agendado) |
| Token por SMS/app a cada acesso, ou captcha | Claude in Chrome (você digita o token, ele faz o resto) |
