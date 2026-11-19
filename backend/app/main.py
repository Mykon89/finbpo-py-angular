import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import admin, auth, decisoes, cnpj, corretagem, entidades, relatorios, titulos, transacoes
from app.mcp_server import app_mcp, ciclo_de_vida
from app.acesso import autorizar
from app.services.auditoria import Auditoria


@asynccontextmanager
async def lifespan(_: FastAPI):
    from app.services.pasta_monitorada import vigiar

    tarefa = asyncio.create_task(vigiar()) if settings.tarefas_automaticas else None  # pasta + tarefas diárias
    async with ciclo_de_vida():
        yield
    if tarefa:
        tarefa.cancel()
        with suppress(asyncio.CancelledError):
            await tarefa


app = FastAPI(title="FinBPO", version="0.1.0", lifespan=lifespan)
app.add_middleware(Auditoria)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api = APIRouter(prefix="/api")
api.include_router(auth.router)
api.include_router(admin.router)
protegido = [Depends(autorizar)]
for r in (cnpj.router, entidades.router, titulos.router, transacoes.router, relatorios.router, corretagem.router, decisoes.router):
    api.include_router(r, dependencies=protegido)
app.include_router(api)


@app.get("/api/saude", tags=["infra"])
def saude():
    return {"status": "ok"}


# Conector MCP para o Claude em /mcp (montado por último: as rotas da API têm prioridade)
app.mount("/", app_mcp)
