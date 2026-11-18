from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import auth, cnpj, corretagem, entidades, relatorios, titulos, transacoes
from app.mcp_server import app_mcp, ciclo_de_vida
from app.security import usuario_atual


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with ciclo_de_vida():
        yield


app = FastAPI(title="FinBPO", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api = APIRouter(prefix="/api")
api.include_router(auth.router)
protegido = [Depends(usuario_atual)]
for r in (cnpj.router, entidades.router, titulos.router, transacoes.router, relatorios.router, corretagem.router):
    api.include_router(r, dependencies=protegido)
app.include_router(api)


@app.get("/api/saude", tags=["infra"])
def saude():
    return {"status": "ok"}


# Conector MCP para o Claude em /mcp (montado por último: as rotas da API têm prioridade)
app.mount("/", app_mcp)
