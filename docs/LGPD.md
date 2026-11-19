# FinBPO e a LGPD (Lei 13.709/2018)

O que o sistema já faz e o que fica com você (controlador dos dados).

## Medidas técnicas no sistema
| Exigência | Como o FinBPO atende |
|---|---|
| Segurança (art. 46) | CPF guardado **cifrado** no banco (AES-SIV); senhas com Argon2; sessão expira; HTTPS recomendado se publicar fora do seu PC |
| Acesso mínimo necessário | **Grupos de acesso**: diretoria/colaboradores são *leitores* — veem só as áreas e empresas liberadas e não alteram nada. Parceiros não têm acesso |
| Rastreabilidade (art. 37) | **Auditoria**: logins, falhas de login, todas as alterações e as consultas dos leitores (quem, quando, rota, IP) — sem o conteúdo dos dados. Guardada por 5 anos |
| Minimização (art. 6º, III) | Só o necessário: do Petlove não se guarda e-mail/telefone do tutor; arquivos da pasta monitorada são apagados 90 dias depois de importados (`RETENCAO_ARQUIVOS_DIAS`) |
| Compartilhamento com terceiros | Conector do Claude recebe **CPF e nome de pessoa física mascarados** (`MCP_MASCARAR_PF=true`); BrasilAPI/CNPJá só recebem CNPJ (dado público de empresa), nunca CPF |
| Direitos do titular (art. 18) | Tela **Privacidade (LGPD)**: buscar por CPF/nome, exportar cópia (JSON) e anonimizar |

## Configuração
- `SECRET_KEY`: **não troque** depois de usar — a chave dos CPFs é derivada dela. Para uma chave própria, defina
  `DADOS_CHAVE` (64 bytes em base64) **antes** do primeiro uso; gerar: `python -c "import os,base64;print(base64.b64encode(os.urandom(64)).decode())"`.
- Guarde o `.env` e os backups do banco em local protegido (BitLocker no Windows).
- Troque o `MCP_TOKEN` se ele já apareceu em conversas ou prints.

## O que fica com você (organizacional)
1. **Registro das operações de tratamento** (art. 37) — modelo abaixo.
2. **Encarregado/canal do titular** (art. 41): agentes de pequeno porte podem ser dispensados de indicar encarregado
   (Resolução CD/ANPD nº 2/2022), mas precisam de um canal para o titular (ex.: e-mail de privacidade no site).
3. **Política de privacidade** para clientes (site / propostas).
4. **Contratos com operadores**: seguradoras, contabilidade, Google (planilha FECHAMENTO), Anthropic (Claude),
   e no futuro o agregador bancário — cláusula de proteção de dados.
5. **Incidente de segurança** (vazamento): avaliar risco e, se relevante, comunicar a ANPD e os titulares
   (Resolução CD/ANPD nº 15/2024: em até 3 dias úteis). A auditoria ajuda a saber o que foi acessado.

### Modelo de registro das operações (preencha)
| Dado | Titular | Finalidade | Base legal | Onde fica | Quem acessa | Retenção |
|---|---|---|---|---|---|---|
| Nome do segurado, apólice, comissão | Clientes | Apurar e conferir comissões | Execução de contrato (art. 7º, V) / legítimo interesse (IX) | FinBPO (Postgres) | Admin; leitores do grupo com "Comissões" | 5 anos (fiscal) |
| Nome/CPF de quem paga ou recebe no banco | Clientes, fornecedores | Contas a pagar/receber, conciliação | Obrigação legal (II) / execução de contrato | FinBPO | Admin; grupos com "Lançamentos" | 5 anos |
| Propostas (FECHAMENTO) | Clientes | Vínculo do produtor, novos negócios | Legítimo interesse | Google Sheets + FinBPO | Admin; grupos com "Comissões" | enquanto vigente + 5 anos |
| Usuários do sistema | Equipe | Controle de acesso e auditoria | Legítimo interesse / obrigação legal | FinBPO | Admin | enquanto ativo + 5 anos |
