# Ligar a planilha FECHAMENTO DE PROPOSTAS

O FinBPO lê a planilha direto do Google Sheets (botão **Comissões → FECHAMENTO DE PROPOSTAS → Sincronizar agora**).
Com ela, o sistema:
- completa ORIGEM/PRODUTOR/PARCEIRO dos clientes novos (que ainda não estão na BASE);
- usa o FECHAMENTO quando ele for mais novo que a BASE e o produtor/parceiro mudou (mesma regra do script);
- marca **novo negócio** pela coluna **Tipo** ("Seguro Novo" x "Renovação"), essencial para a SulAmérica,
  que manda "parcela 1" o ano inteiro;
- entra na **Previsão de recebimentos** com as propostas fechadas que ainda não pagaram comissão.

## Opção A — conta de serviço (recomendada: a planilha continua privada)
Feito uma vez, leva uns 10 minutos:
1. Acesse https://console.cloud.google.com/ com a sua conta Google e crie um projeto (ex.: `finbpo`).
2. Menu **APIs e serviços → Biblioteca** → ative a **Google Drive API**.
3. **APIs e serviços → Credenciais → Criar credenciais → Conta de serviço** (nome: `finbpo`). Não precisa de papel.
4. Abra a conta criada → aba **Chaves → Adicionar chave → JSON**. Baixa um arquivo `.json`.
5. Salve o arquivo como `credenciais/google.json` dentro da pasta do FinBPO (essa pasta não vai para o Git).
6. No `.env`, acrescente:
   ```
   GOOGLE_SERVICE_ACCOUNT_FILE=/app/credenciais/google.json
   ```
7. Na planilha FECHAMENTO, clique em **Compartilhar** e adicione o e-mail da conta de serviço
   (termina em `@...iam.gserviceaccount.com`, está no arquivo JSON) como **Leitor**.
8. `docker compose up --build`, cole o link da planilha em Comissões → FECHAMENTO e clique em **Sincronizar agora**.

## Opção B — link público (mais simples, menos privado)
Na planilha: **Compartilhar → Acesso geral → Qualquer pessoa com o link → Leitor**. Quem tiver o link vê os dados
dos clientes; prefira a opção A.

## Sem internet / sem Google
Ainda dá para **subir o .xlsx** (Arquivo → Fazer download → .xlsx) no mesmo cartão.

## Como as abas são lidas
- Abas `JAN` a `DEZ` (e `JAN27`, `FEV27`… para o ano seguinte); o ano vem do título da aba ("FECHAMENTO DE PROPOSTAS - OUTUBRO 2026").
- Cabeçalho nas 10 primeiras linhas com **Cliente** e **Seguradora**. Colunas usadas: Data de e-mail, Vigência Inicial,
  Tipo, Seguradora, Ramo, Descrição, Cliente, Produtor, Origem, Prêmio Líquido, Com. Bruta, Parceiro(a) (em MAI, a 2ª "Origem"), Emissão, Recebido.
- Seguradoras são normalizadas como no script (AZUL/ITAÚ → PORTO, ALIRO → YELUM, SA SAÚDE → SULAMERICA…).
  Produtor: "Fabiana C." → FABIANA, "Fabianny A." → FABI ANJOS.

## Novo negócio
| Seguradora | Regra |
|---|---|
| SulAmérica | 1ª comissão do contrato (pela apólice ou pelo nome) **e** o FECHAMENTO não diz "Renovação". Nos 2 primeiros meses de histórico, só conta se o FECHAMENTO disser "Seguro Novo". |
| Demais | Positivo com parcela 1, TOTAL ou ÚNICA (regra do comparativo da planilha). |
