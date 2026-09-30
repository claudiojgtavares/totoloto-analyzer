import unittest
from contextlib import contextmanager
from unittest.mock import patch

from app import fetch_all, fetch_one


class FakeCursor:
    def __init__(self, rows=None, error=None):
        self.rows = rows or []
        self.error = error
        self.closed = False
        self.sql = None
        self.params = None

    def execute(self, sql, params):
        self.sql = sql
        self.params = params
        if self.error:
            raise self.error

    def fetchall(self):
        return self.rows

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self.fake_cursor = cursor
        self.rolled_back = False
        self.closed = False

    def cursor(self, dictionary=False):
        self.dictionary = dictionary
        return self.fake_cursor

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def fake_scope(connection):
    @contextmanager
    def scope():
        try:
            yield connection
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    return scope


class DatabaseLifecycleTests(unittest.TestCase):
    def test_fetch_all_fecha_cursor_e_ligacao_em_sucesso(self):
        cursor = FakeCursor(rows=[{"total": 3}])
        connection = FakeConnection(cursor)
        with patch("app.connection_scope", fake_scope(connection)):
            rows = fetch_all("SELECT %s AS total", (3,))

        self.assertEqual(rows, [{"total": 3}])
        self.assertEqual(cursor.params, (3,))
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)
        self.assertFalse(connection.rolled_back)

    def test_fetch_all_faz_rollback_e_fecha_recursos_em_excecao(self):
        cursor = FakeCursor(error=RuntimeError("falha de query"))
        connection = FakeConnection(cursor)
        with patch("app.connection_scope", fake_scope(connection)):
            with self.assertRaisesRegex(RuntimeError, "falha de query"):
                fetch_all("SELECT falha")

        self.assertTrue(cursor.closed)
        self.assertTrue(connection.rolled_back)
        self.assertTrue(connection.closed)

    @patch("app.fetch_all", return_value=[{"id": 1}])
    def test_fetch_one_devolve_primeira_linha_ou_none(self, fetch_mock):
        self.assertEqual(fetch_one("SELECT 1"), {"id": 1})
        fetch_mock.return_value = []
        self.assertIsNone(fetch_one("SELECT 1"))
        self.assertEqual(fetch_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()
