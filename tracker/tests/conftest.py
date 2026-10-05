import os
import sys
import warnings
from dataclasses import replace
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.environ["RASTRO_PASTA_DADOS"] = str(RAIZ / ".pytest_cache" / "dados-nao-usar")
os.environ["RASTRO_SINCRONIZAR"] = "0"
warnings.filterwarnings("ignore", message=".*httpx2.*")

from fastapi.testclient import TestClient  # noqa: E402

from rastro.app import criar_app  # noqa: E402
from rastro.config import carregar  # noqa: E402
from rastro.db import Banco  # noqa: E402


@pytest.fixture
def banco(tmp_path):
    # Por padrão, SQLite. Para testar no PostgreSQL: RASTRO_TESTE_DATABASE_URL=postgresql://... pytest
    url = os.getenv("RASTRO_TESTE_DATABASE_URL")
    if url:
        from rastro import modelos  # noqa: F401
        from rastro.db import Base
        banco = Banco(url)
        Base.metadata.drop_all(banco.engine)
    else:
        banco = Banco(f"sqlite:///{tmp_path / 'teste.db'}")
    banco.criar_tabelas()
    yield banco
    banco.engine.dispose()


@pytest.fixture
def app(tmp_path, banco):
    cfg = replace(carregar(), pasta_dados=tmp_path, chave_secreta="segredo-de-teste", sincronizar_ativo=False,
                  url_publica="https://rastro.exemplo.com")
    return criar_app(cfg, banco)


@pytest.fixture
def cliente(app):
    with TestClient(app, base_url="https://testserver") as cliente:
        cliente.headers["X-Rastro"] = "1"
        yield cliente


@pytest.fixture
def logado(cliente):
    resposta = cliente.post("/api/configurar", json={"nome_conta": "Minha Operação", "nome": "Ana",
                                                     "email": "ana@exemplo.com", "senha": "senha-forte-123"})
    assert resposta.status_code == 200, resposta.text
    return cliente
