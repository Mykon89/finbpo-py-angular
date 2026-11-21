# Comissões das produtoras

Tela **Comissões das produtoras** (admin/diretoria, área `comissao_produtoras`) e **Minha comissão** (área `minha_comissao`, a produtora vê só a dela).

## Regras (iguais ao script da planilha)
- **PL da meta** = prêmio líquido no FECHAMENTO (mesmo produtor) dos clientes com comissão positiva no mês. Fora: DÉBITO, SALDO, BONIFICAÇÃO, CARTÃO e os ramos excluídos do plano (Fabi: SAÚDE/ODONTO).
- **Nível** (5 faixas por mês): até F1 = SEM META; acima de F1 = BRONZE; acima de F3 = PRATA; de F4 = OURO; de F5 = DIAMANTE.
  Patrimonial 6/8/10/12/15%; saúde 10/30/32/34/36% (editável por plano).
- **Base** = comissão bruta do mês da produtora (estornos abatidos no mês em que aparecem). Cartão só informativo.
- **Indicação pessoal** = (bruto − 18%) × 20%. Conta quando a BASE traz ela como parceira **ou** o FECHAMENTO diz que a indicação é dela (parceiro/origem).
- **Saúde (Fabi)**: planilha própria (abas JANEIRO..DEZEMBRO). Fatura × 12 = PL saúde; 1ª parcela PME/PF × % nível; demais até a 3ª × 10%; adesão × % nível.
- **Saldo negativo** do mês vai para o seguinte.
- **Sem meta cadastrada**: não calcula nem gera conta; o e-mail diário avisa "pegue com a Kette".

## Conta a pagar (automática)
- Rotina diária cria/atualiza `COMISSÃO {PRODUTORA} MM/AAAA` da competência anterior, até ser paga.
- Paga no mês seguinte (configurável), **1 dia antes do primeiro imposto** (DAS/INSS/FGTS/IRRF) do mês; sem imposto lançado, dia 19.
- Reaproveita e corrige a cópia da recorrência já lançada no mês (ex.: "09/2026" em novembro vira "10/2026").

## Outros
- Ajuste do PL: excluir clientes e somar/abater valor manual.
- Simulador: "se eu fechar mais R$ X de prêmio".
- Demonstrativo PDF por produtora/mês.
- Primeiro uso: botão "Criar Giovanna e Fabiana" (regras e metas 2026 do script).
- Para a produtora ver a dela: grupo com a área "Minha comissão" + usuário ligado ao plano (Configuração).
