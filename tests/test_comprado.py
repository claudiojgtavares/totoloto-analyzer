import unittest
from contextlib import contextmanager
from unittest.mock import patch

from app import app


class CursorComprado:
    def __init__(self, row):
        self.row = row
        self.executed = []
        self.closed = False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self.row

    def close(self):
        self.closed = True


class ConnectionComprado:
    def __init__(self, row):
        self.cursor_obj = CursorComprado(row)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, **_kwargs):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def scope_for(connection):
    @contextmanager
    def scope():
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return scope


class CompradoTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)

    def test_marcar_e_desmarcar_jogo_sao_transacionais(self):
        for valor in ("1", "0"):
            connection = ConnectionComprado({"id": 7})
            with patch("app.transaction_scope", scope_for(connection)):
                resposta = app.test_client().post(f"/jogos/7/comprado", data={"comprado": valor})
            self.assertEqual(resposta.status_code, 302)
            self.assertEqual(connection.commits, 1)
            self.assertTrue(any("UPDATE jogos_gerados SET comprado" in sql for sql, _ in connection.cursor_obj.executed))
            self.assertEqual(connection.cursor_obj.executed[-1][1], (valor == "1", 7))

    def test_jogo_inexistente_e_rejeitado_sem_commit(self):
        connection = ConnectionComprado(None)
        with patch("app.transaction_scope", scope_for(connection)):
            resposta = app.test_client().post("/jogos/999/comprado", data={"comprado": "1"})
        self.assertEqual(resposta.status_code, 404)
        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)

    def test_banca_mostra_orcamento_comprometido_e_gasto_real_comprado_separados(self):
        with patch("app.fetch_all", return_value=[]), patch(
            "app.fetch_one",
            side_effect=[
                {"gasto": 999, "retorno": 40, "saldo": -959},
                {"total": 120},
                {"total": 30},
            ],
        ) as fetch:
            resposta = app.test_client().get("/controle-banca")
        texto = resposta.get_data(as_text=True)
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Orçamento comprometido", texto)
        self.assertIn("Gasto real em apostas compradas", texto)
        self.assertIn("30", texto)
        sqls = [chamada.args[0] for chamada in fetch.call_args_list]
        self.assertTrue(any("geracoes_semanais" in sql for sql in sqls))
        self.assertTrue(any("comprado = TRUE" in sql for sql in sqls))


if __name__ == "__main__":
    unittest.main()
