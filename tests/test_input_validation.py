import unittest
from unittest.mock import patch

from app import app


CONFIG = {
    "preco_aposta_simples": 30,
    "preco_joker": 70,
    "orcamento_semanal": 1000,
    "moeda": "CVE",
}


class InputValidationTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()

    @patch("app.fetch_all", return_value=[])
    def test_rejeita_concurso_totoloto_nao_positivo(self, _fetch_all):
        resposta = self.client.post("/cadastrar-sorteio", data={"concurso": "0"})
        self.assertEqual(resposta.status_code, 200)
        self.assertIn(b"inteiro", resposta.data)

    @patch("app.fetch_one", return_value=CONFIG)
    def test_rejeita_estrategia_desconhecida_na_geracao(self, _fetch_one):
        with patch("app.fetch_all", return_value=[]), patch("app.get_configuracao", return_value=CONFIG):
            resposta = self.client.post("/gerar-jogos", data={"estrategia": "Inventada"})
        self.assertEqual(resposta.status_code, 200)
        self.assertIn(b"Estrat", resposta.data)

    @patch("app.fetch_one", return_value=CONFIG)
    def test_rejeita_estrategia_desconhecida_no_backtesting(self, _fetch_one):
        with patch("app.fetch_all", return_value=[]), patch("app.get_configuracao", return_value=CONFIG):
            resposta = self.client.post("/backtesting", data={"estrategia": "Inventada"})
        self.assertEqual(resposta.status_code, 200)
        self.assertIn(b"Estrat", resposta.data)

    def test_rejeita_quantidade_joker_acima_do_limite(self):
        with patch("app.fetch_all", return_value=[]), patch(
            "app.fetch_one", side_effect=[{"total": 0}, None, None, None]
        ):
            resposta = self.client.post("/joker", data={"acao": "gerar", "quantidade": "31"})
        self.assertEqual(resposta.status_code, 200)
        self.assertIn(b"30", resposta.data)

    def test_rejeita_concurso_joker_mal_formado(self):
        with patch("app.fetch_all", return_value=[]), patch(
            "app.fetch_one", side_effect=[{"total": 0}, None, None, None]
        ):
            resposta = self.client.post("/joker", data={
                "acao": "registar", "concurso": "2026/01",
                "data_sorteio": "17/09/2026", "numero_joker": "056708",
            })
        self.assertEqual(resposta.status_code, 200)
        self.assertIn(b"Concurso Joker", resposta.data)

    @patch("app.fetch_one", return_value=CONFIG)
    def test_rejeita_preco_negativo_nas_definicoes(self, _fetch_one):
        resposta = self.client.post("/configuracoes", data={
            "preco_aposta_simples": "-1",
            "preco_joker": "70",
            "orcamento_semanal": "1000",
        })
        self.assertEqual(resposta.status_code, 200)
        self.assertIn(b"n", resposta.data)

    @patch("app.fetch_one", return_value={"gasto": 0, "retorno": 0, "saldo": 0})
    @patch("app.fetch_all", return_value=[])
    def test_rejeita_valor_de_banca_negativo(self, _fetch_all, _fetch_one):
        resposta = self.client.post("/controle-banca", data={
            "valor_gasto": "-10", "valor_retorno": "0",
        })
        self.assertEqual(resposta.status_code, 200)
        self.assertIn(b"n", resposta.data)


if __name__ == "__main__":
    unittest.main()
