"""Conexão com o banco: SQLite por padrão (arquivo em dados/), PostgreSQL se DATABASE_URL estiver definida."""

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TypeVar

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def normalizar_url(url: str) -> str:
    # Railway, Render e Heroku entregam "postgres://"; o SQLAlchemy usa o driver psycopg 3.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def criar_engine(url: str) -> Engine:
    url = normalizar_url(url)
    if url.startswith("sqlite"):
        caminho = url.split("///", 1)[-1]
        if caminho and caminho != ":memory:":
            from pathlib import Path
            Path(caminho).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(engine, "connect")
        def _ao_conectar(conexao, _):
            # O SQLAlchemy controla as transações (senão o pysqlite quebra os SAVEPOINTs).
            conexao.isolation_level = None
            cursor = conexao.cursor()
            # WAL deixa o painel ler enquanto webhooks e a sincronização escrevem.
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        @event.listens_for(engine, "begin")
        def _ao_iniciar(conexao):
            # IMMEDIATE pega a trava de escrita já no início: transações simultâneas esperam a vez (até o
            # timeout) em vez de falhar com "database is locked" ao passar de leitura para escrita.
            # Por isso nenhuma transação fica aberta durante chamadas à API do Meta.
            conexao.exec_driver_sql("BEGIN IMMEDIATE")

        return engine
    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=20)


class Banco:
    def __init__(self, url: str):
        self.engine = criar_engine(url)
        self.fabrica = sessionmaker(self.engine, expire_on_commit=False)

    def criar_tabelas(self) -> None:
        from rastro import modelos  # noqa: F401  (registra as tabelas no Base)
        Base.metadata.create_all(self.engine)

    @contextmanager
    def sessao(self) -> Iterator[Session]:
        sessao = self.fabrica()
        try:
            yield sessao
            sessao.commit()
        except Exception:
            sessao.rollback()
            raise
        finally:
            sessao.close()


T = TypeVar("T")


def repetir_em_conflito(funcao: Callable[..., T], *args, tentativas: int = 4) -> T:
    """Repete uma transação inteira quando outra gravou a mesma linha ao mesmo tempo.

    Ex.: a Hotmart manda "aprovada" e "completa" da mesma venda no mesmo segundo (chave única no PostgreSQL),
    ou duas gravações disputam o arquivo no SQLite ("database is locked").
    """
    for tentativa in range(tentativas):
        try:
            return funcao(*args)
        except (IntegrityError, OperationalError):
            if tentativa == tentativas - 1:
                raise
            time.sleep(0.05 * (tentativa + 1))
    raise AssertionError("inalcançável")
