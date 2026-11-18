# Planilha EXTRATOS_SEGURADORAS → FinBPO

## Como migrar
1. No Google Sheets: **Arquivo → Fazer download → Microsoft Excel (.xlsx)**.
2. No FinBPO, escolha a entidade (corretora) → **Comissões → Importar planilha (.xlsx)**.
3. Confira o grupo da DRE das categorias novas em **Plano de contas**.

Pode reimportar a qualquer momento: o que já existe não é duplicado (PAGAR pelo ID, BASE por linha).

## O que vai para onde
| Aba / função da planilha | No FinBPO | Situação |
|---|---|---|
| PAGAR | Contas a pagar (com desconto, juros, natureza fixa/variável) | ✅ |
| RECORRÊNCIAS (mensal, semanal, quinzenal, anual, única, parcelada, nº dia útil, antecipar/postergar, reajuste, `{COMP}`/`{MES}`) | Recorrências → "Gerar contas" | ✅ |
| Feriados bancários (fixos + Páscoa) | Ajuste de vencimento | ✅ |
| REGRAS_BANCO | Regras de categorização (CNPJ vira regra por contraparte) | ✅ |
| PAINEL (vence hoje, atrasado, 7 dias, até o fim do mês, pago no mês) | Painel | ✅ |
| BASE | Comissões (linhas) | ✅ |
| RECEBER / Conferência | Comissões → Extratos do mês | ✅ |
| VISÃO MENSAL / COMPARATIVO (ramo, seguradora, novos negócios) | Comissões | ✅ |
| Vínculo ORIGEM/PRODUTOR/PARCEIRO | Edição na linha + filtro "sem produtor/parceiro" | ✅ manual |
| Importadores de extrato por seguradora (Porto, Bradesco, Tokio, Allianz…) | — | próxima fase |
| Conciliação RECEBER × banco (1→N, N→1, tolerância R$ 0,05, Bradesco por fatura) | — | próxima fase |
| Conciliação PAGAR × débitos do banco (6 passes) e aprendizado | parcial (conciliação atual por valor/data) | próxima fase |
| Vínculo automático pelo histórico / FECHAMENTO DE PROPOSTAS / Gmail Trust | — | próxima fase |
| Comissões Giovanna/Fabi (metas, níveis, PL) | — | próxima fase |
| Exportação Conta Azul, OCR de boletos/holerites/DARF, 13º, virada de ano | — | a definir |
