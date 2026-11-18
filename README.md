# FinBPO

Gestão financeira multiempresa (corretoras de seguros, clínica de estética e clientes PF).
Backend em **Python (FastAPI)** e frontend em **Angular**. A arquitetura completa está em [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md).

## Fase 1 (atual)

- Entidades (PJ/PF) com plano de contas padrão por segmento e **preenchimento automático pelo CNPJ** (BrasilAPI, com CNPJá como reserva)
- Contas financeiras (corrente, cartão, caixa, maquininha) com saldo
- Contas a pagar e a receber, com parcelamento, baixa manual, cancelamento e estorno de baixa
- Importação de **OFX** (SGML 1.x e XML 2.x, cp1252/UTF-8, vírgula decimal), sem duplicar ao reimportar
- Regras de categorização por trecho da descrição
- Conciliação automática (mesmo valor, vencimento ± 5 dias, só quando há um único candidato) e manual
- DRE gerencial (regime de caixa) e aging de contas a pagar e a receber
- Login com JWT

## Rodando com Docker

```bash
cp .env.example .env   # ajuste POSTGRES_PASSWORD e SECRET_KEY
docker compose up --build
```

Acesse http://localhost:8080. A documentação da API fica em http://localhost:8000/docs.
No primeiro acesso, clique em **Primeiro acesso** para criar o usuário administrador.

## Desenvolvimento

Requisitos: Python 3.12+, Node 22+ e PostgreSQL 16 (ou só o `db` do compose: `docker compose up db`).

```bash
# backend
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload            # http://localhost:8000/docs

# frontend (outro terminal)
cd frontend
npm install
npm start                                # http://localhost:4200 (proxy de /api para :8000)
```

### Testes

```bash
cd backend && pytest                     # SQLite em memória
TEST_DATABASE_URL=postgresql+psycopg://finbpo:finbpo@localhost/finbpo_test pytest   # Postgres (recria o banco)
cd frontend && npx ng test --watch=false
```

### Migrações

```bash
cd backend
alembic revision --autogenerate -m "descrição"
alembic upgrade head
```

## Estrutura

```
backend/
  app/
    models.py            modelos SQLAlchemy
    schemas.py           contratos da API (Pydantic)
    routers/             auth, entidades, titulos, transacoes (OFX + conciliação), relatorios
    services/            ofx, conciliacao, categorizacao, dre, plano_contas
  alembic/               migrações
  tests/                 pytest (inclui OFX de exemplo)
frontend/
  src/app/
    core/                API, autenticação, entidade selecionada, formatação
    layout/shell.ts      menu lateral e seletor de entidade
    pages/               painel, titulos, importar, conciliacao, entidades, login
docs/ARQUITETURA.md
```

## Próximas fases

Ver o roadmap em `docs/ARQUITETURA.md` §9: faturas de cartão em PDF, módulo PF, PDF de fechamento mensal, módulos Corretora e Clínica, Open Finance.
