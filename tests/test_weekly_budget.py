import unittest
from contextlib import contextmanager
from datetime import date, datetime
from unittest.mock import patch

from app import _guardar_geracao_com_orcamento, _limites_semana_iso


class BudgetCursor:
    def __init__(self, respostas):
        self.respostas = iter(respostas)
        self.closed = False
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return next(self.respostas)

    def close(self):
        self.closed = True


class BudgetConnection:
    def __init__(self, respostas):
        self.cursor_obj = BudgetCursor(respostas)
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def scope_for(connection):
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


class WeeklyBudgetTests(unittest.TestCase):
    def test_semana_iso_comeca_na_segunda_e_termina_na_segunda_seguinte(self):
        inicio, fim = _limites_semana_iso(date(2026, 9, 17))
        self.assertEqual(inicio, datetime(2026, 9, 14))
        self.assertEqual(fim, datetime(2026, 9, 21))

    def test_rejeita_geracao_que_ultrapassa_gasto_acumulado(self):
        connection = BudgetConnection([(1,), (950,)])
        jogo = {
            "custo_final": 100,
            "tipo_aposta": "simples",
            "estrategia": "Equilibrada",
            "numeros": [1, 2, 3, 4, 5, 6],
            "apostas_simples": 1,
            "score": 0,
            "custo_total": 100,
            "incluir_joker": False,
            "custo_joker": 0,
        }
        with patch("app.transaction_scope", scope_for(connection)):
            with self.assertRaises(ValueError):
                _guardar_geracao_com_orcamento(
                    [jogo], 10, "Equilibrada", 1000,
                    datetime(2026, 9, 14), datetime(2026, 9, 21),
                )
        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)
        self.assertTrue(connection.cursor_obj.closed)
        self.assertTrue(connection.closed)
        self.assertTrue(any("GET_LOCK" in sql for sql, _ in connection.cursor_obj.executed))
        self.assertTrue(any("RELEASE_LOCK" in sql for sql, _ in connection.cursor_obj.executed))
        self.assertTrue(any("geracoes_semanais" in sql for sql, _ in connection.cursor_obj.executed))
        self.assertFalse(any("comprado" in sql.lower() for sql, _ in connection.cursor_obj.executed))

    def test_modo_analise_guarda_numeros_sem_consumir_orcamento(self):
        connection = BudgetConnection([])
        jogo = {
            "custo_final": 30, "tipo_aposta": "simples", "estrategia": "Equilibrada",
            "numeros": [1, 2, 3, 4, 5, 6], "apostas_simples": 1, "score": 0,
            "custo_total": 30, "incluir_joker": False, "custo_joker": 0,
        }
        with patch("app.transaction_scope", scope_for(connection)):
            _guardar_geracao_com_orcamento(
                [jogo], 11, "Equilibrada", 1000,
                datetime(2026, 9, 14), datetime(2026, 9, 21),
                consumir_orcamento=False,
            )
        self.assertEqual(connection.commits, 1)
        self.assertFalse(any("GET_LOCK" in sql for sql, _ in connection.cursor_obj.executed))
        self.assertFalse(any("geracoes_semanais" in sql for sql, _ in connection.cursor_obj.executed))


if __name__ == "__main__":
    unittest.main()
