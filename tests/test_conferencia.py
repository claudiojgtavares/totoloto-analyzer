import unittest
from contextlib import contextmanager
from unittest.mock import patch

from app import app
from modules.conferencia import conferir_jogos


class _Cursor:
    def execute(self, *_args):
        pass
    def close(self):
        pass


class _Connection:
    def __init__(self):
        self.commits = 0
    def cursor(self, **_kwargs):
        return _Cursor()
    def commit(self):
        self.commits += 1
    def rollback(self):
        pass
    def close(self):
        pass


class ConferenciaTests(unittest.TestCase):
    def test_calcula_categorias_e_isola_jogo_malformado(self):
        jogos = [
            {"id": 1, "concurso": 10, "numeros": "1,2,3,4,5,6"},
            {"id": 2, "concurso": 10, "numeros": "1,2,3,4,5,99"},
            {"id": 3, "concurso": 10, "numeros": "1,2,3,4,9,10"},
            {"id": 4, "concurso": 10, "numeros": "1,2,3,4,5,9"},
            {"id": 5, "concurso": 10, "numeros": "1,2,3,9,10,11"},
        ]
        conferido = conferir_jogos(jogos, [1, 2, 3, 4, 5, 6])
        self.assertEqual(conferido["jogos_conferidos"], 4)
        self.assertEqual(conferido["premios_por_categoria"]["primeiro"], 1)
        self.assertEqual(conferido["premios_por_categoria"]["segundo"], 1)
        self.assertEqual(conferido["premios_por_categoria"]["terceiro"], 1)
        self.assertEqual(conferido["premios_por_categoria"]["quarto"], 1)
        self.assertEqual([e["id"] for e in conferido["erros"]], [2])

    def test_sem_jogos_e_concurso_diferente_nao_produzem_resultado(self):
        self.assertEqual(conferir_jogos([], [1, 2, 3, 4, 5, 6])["jogos_premiados"], [])
        jogos = [{"id": 8, "concurso": 99, "numeros": "1,2,3,4,5,6"}]
        selecionados = [j for j in jogos if j["concurso"] == 10]
        self.assertEqual(conferir_jogos(selecionados, [1, 2, 3, 4, 5, 6])["jogos_conferidos"], 0)

    def test_rota_regista_sorteio_e_confere_depois_do_commit(self):
        connection = _Connection()

        @contextmanager
        def scope():
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

        jogos = [{"id": 17, "concurso": 55, "numeros": "1,2,3,4,5,6"}]
        app.config.update(TESTING=True)
        with patch("app.transaction_scope", scope), \
             patch("app.recalcular_estatisticas"), \
             patch("app.fetch_all", side_effect=[jogos, [], []]):
            resposta = app.test_client().post("/cadastrar-sorteio", data={
                "concurso": "55", "data_sorteio": "17/09/2026",
                "n1": "1", "n2": "2", "n3": "3", "n4": "4", "n5": "5", "n6": "6",
            }, follow_redirects=True)

        self.assertEqual(connection.commits, 1)
        self.assertIn("Confer", resposta.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
