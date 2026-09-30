import unittest
from contextlib import contextmanager
from unittest.mock import patch

from app import app


class FakeCursor:
    def __init__(self):
        self.closed = False
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def close(self):
        self.closed = True


class FakeTransactionConnection:
    def __init__(self):
        self.cursor_obj = FakeCursor()
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self, **kwargs):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def transaction_scope_fake(connection):
    @contextmanager
    def scope():
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    return scope


class TransactionRouteTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def test_registo_sorteio_so_faz_commit_depois_do_recalculo(self):
        connection = FakeTransactionConnection()
        with patch("app.transaction_scope", transaction_scope_fake(connection)), \
             patch("app.recalcular_estatisticas") as recalcular, \
             patch("app.fetch_all", return_value=[]):
            resposta = self.client.post("/cadastrar-sorteio", data={
                "concurso": "101",
                "data_sorteio": "17/09/2026",
                "n1": "1", "n2": "8", "n3": "17",
                "n4": "26", "n5": "35", "n6": "44",
            })

        self.assertEqual(resposta.status_code, 302)
        recalcular.assert_called_once_with(connection)
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)
        self.assertTrue(connection.cursor_obj.closed)
        self.assertTrue(connection.closed)

    def test_registo_joker_so_faz_commit_depois_do_recalculo(self):
        connection = FakeTransactionConnection()
        with patch("app.transaction_scope", transaction_scope_fake(connection)), \
             patch("app.recalcular_estatisticas_joker") as recalcular:
            resposta = self.client.post("/joker", data={
                "acao": "registar",
                "concurso": "01/2026",
                "data_sorteio": "17/09/2026",
                "numero_joker": "056708",
                "premio": "1.º Prémio",
            })

        self.assertEqual(resposta.status_code, 302)
        recalcular.assert_called_once_with(connection)
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)
        self.assertTrue(connection.cursor_obj.closed)
        self.assertTrue(connection.closed)


if __name__ == "__main__":
    unittest.main()
