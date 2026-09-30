import unittest

from mysql.connector import errors as mysql_errors
from criar_banco import normalizar_coluna_ultimo_sorteio, garantir_coluna


class CriarBancoTests(unittest.TestCase):
    def test_ignora_apenas_programming_error_1060(self):
        class Cursor:
            def execute(self, sql):
                erro = mysql_errors.ProgrammingError("Duplicate column name")
                erro.errno = 1060
                raise erro
        normalizar_coluna_ultimo_sorteio(Cursor())

    def test_propaga_outros_erros_mysql(self):
        class Cursor:
            def execute(self, sql):
                erro = mysql_errors.ProgrammingError("syntax error")
                erro.errno = 1064
                raise erro
        with self.assertRaises(mysql_errors.ProgrammingError):
            normalizar_coluna_ultimo_sorteio(Cursor())

    def test_migracao_comprado_usa_default_falso(self):
        class Cursor:
            def __init__(self):
                self.sql = []
            def execute(self, sql, params=None):
                self.sql.append((sql, params))
            def fetchone(self):
                return None
        cursor = Cursor()
        garantir_coluna(cursor, "jogos_gerados", "comprado", "BOOLEAN NOT NULL DEFAULT FALSE")
        self.assertIn("ALTER TABLE jogos_gerados ADD COLUMN comprado BOOLEAN NOT NULL DEFAULT FALSE", cursor.sql[-1][0])


if __name__ == "__main__":
    unittest.main()
