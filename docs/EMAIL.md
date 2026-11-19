# E-mails automáticos (alerta diário e fechamento do mês)

O FinBPO manda, sozinho:
- **todo dia** (a partir de `ALERTAS_HORA`, padrão 7h): contas em atraso, que vencem hoje e nos próximos 3 dias,
  comissões sem crédito no banco há mais de 10 dias, parcelas de comissão que não chegaram e perguntas abertas
  na Central de decisões. Se não houver nada, não manda (ou mande sempre com `ALERTAS_SEMPRE=true`);
- **no dia `FECHAMENTO_DIA`** (padrão 5): o PDF do fechamento do mês anterior de cada empresa, com as sugestões de economia.

Cada e-mail sai uma vez só (fica registrado). Os e-mails não levam CPF nem nome de cliente pessoa física.

## Configurar com Gmail (grátis)
1. Na conta Google que vai enviar, ative a **verificação em duas etapas**.
2. Acesse https://myaccount.google.com/apppasswords, crie uma senha de app chamada `FinBPO` e copie as 16 letras.
3. No `.env`:
   ```
   SMTP_HOST=smtp.gmail.com
   SMTP_PORTA=587
   SMTP_USUARIO=seu-email@gmail.com
   SMTP_SENHA=as16letrasdasenhadeapp
   ALERTAS_DESTINATARIOS=seu-email@gmail.com
   ```
4. `docker compose up --build` e, em **Fechamento do mês**, clique em **Enviar alerta agora** para testar.

O computador com o Docker precisa estar ligado no horário (o envio acontece na primeira volta depois da hora marcada).

## Análise do Claude no fechamento (sem custo de API)
No Claude com o conector finbpo, peça: *"faça a análise do fechamento de outubro da Atual Prev e salve"*.
Ele lê os números (`dados_fechamento`), escreve o diagnóstico com sugestões de corte e grava (`salvar_analise_fechamento`);
o PDF passa a ter a seção **Análise do Claude**. Fornecedores pessoa física vão para o Claude só com as iniciais.
