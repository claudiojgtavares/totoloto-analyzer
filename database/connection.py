from contextlib import contextmanager

import mysql.connector
from mysql.connector import Error
from config import Config


def get_connection(use_database=True):
    """Abre conexão com o MySQL local do XAMPP."""
    params = {
        "host": Config.MYSQL_HOST,
        "user": Config.MYSQL_USER,
        "password": Config.MYSQL_PASSWORD,
        "port": Config.MYSQL_PORT,
        "autocommit": False,
    }
    if use_database:
        params["database"] = Config.MYSQL_DATABASE
    try:
        return mysql.connector.connect(**params)
    except Error as exc:
        raise RuntimeError(f"Erro ao conectar no MySQL: {exc}") from exc


@contextmanager
def connection_scope(use_database=True):
    """Gere rollback em erro e fecha sempre a ligação MySQL."""
    conexao = get_connection(use_database=use_database)
    try:
        yield conexao
    except Exception:
        try:
            conexao.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conexao.close()
        except Exception:
            pass


@contextmanager
def transaction_scope(use_database=True):
    """Executa uma unidade de escrita com commit/rollback atómicos."""
    conexao = get_connection(use_database=use_database)
    try:
        yield conexao
        conexao.commit()
    except Exception:
        try:
            conexao.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conexao.close()
        except Exception:
            pass
