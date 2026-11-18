import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app


@pytest.fixture
def client():
    # TEST_DATABASE_URL=postgresql+psycopg://... roda contra Postgres (o banco é recriado)
    url = os.getenv("TEST_DATABASE_URL")
    if url:
        engine = create_engine(url)
        Base.metadata.drop_all(engine)
    else:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        event.listen(engine, "connect", lambda c, _: c.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    Sessao = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _db():
        with Sessao() as s:
            yield s

    app.dependency_overrides[get_db] = _db
    with TestClient(app) as c:
        c.post("/api/auth/primeiro-acesso", json={"nome": "Admin", "email": "admin@finbpo.dev", "senha": "senha-forte"})
        token = c.post("/api/auth/login", data={"username": "admin@finbpo.dev", "password": "senha-forte"}).json()
        c.headers["Authorization"] = f"Bearer {token['access_token']}"
        yield c
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def corretora(client):
    return client.post(
        "/api/entidades", json={"tipo": "PJ", "segmento": "corretora", "nome": "Corretora A"}
    ).json()
