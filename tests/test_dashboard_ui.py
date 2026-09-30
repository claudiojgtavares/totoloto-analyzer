import unittest
from datetime import datetime
from unittest.mock import patch

from app import app, pct_br_filter


class DashboardUiTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def test_dashboard_populado_mostra_carteira_e_dois_conceitos_financeiros(self):
        resumo = [
            {"total": 12}, {"total": 4}, {"total": 45},
            {"total": 8}, {"total": 240},
            {"total": 90}, {"total": 60},
            {"concurso": 321, "n1": 1, "n2": 2, "n3": 3, "n4": 4, "n5": 5, "n6": 6},
        ]
        destaques = [
            {"numero": 7, "numero_saidas": 14, "ausencias": 2, "indice_quente": 3.1},
            {"numero": 22, "numero_saidas": 0, "ausencias": 9, "indice_quente": 0.2},
        ]
        jogos = [
            {"id": 10, "created_at": datetime(2026, 9, 17), "numeros": "1,2,3,4,5,6",
             "tipo_aposta": "Simples", "estrategia": "Equilibrada", "score": 84.44,
             "custo_final": 30, "comprado": True},
            {"id": 9, "created_at": datetime(2026, 9, 16), "numeros": "7,8,9,10,11,12",
             "tipo_aposta": "Simples", "estrategia": "Histórica", "score": 71.0,
             "custo_final": 30, "comprado": False},
        ]
        with patch("app.fetch_one", side_effect=resumo), patch(
            "app.fetch_all", side_effect=[destaques, jogos, []]
        ), patch("app.conferir_jogos", return_value=None):
            resposta = self.client.get("/dashboard")

        self.assertEqual(resposta.status_code, 200)
        html = resposta.get_data(as_text=True)
        self.assertIn("Orçamento comprometido", html)
        self.assertIn("Gasto real em apostas compradas", html)
        self.assertIn("90 CVE", html)
        self.assertIn("60 CVE", html)
        self.assertIn("Apenas gerado", html)
        self.assertIn("Marcar como comprado o jogo 9", html)
        self.assertIn("Desmarcar compra do jogo 10", html)
        self.assertIn('action="/jogos/9/comprado"', html)
        self.assertIn('action="/jogos/10/comprado"', html)
        self.assertIn('name="csrf_token"', html)
        self.assertIn('style="width: 0.0%', html)

    def test_dashboard_vazio_apresenta_fluxo_de_primeiro_passo_sem_estado_falso(self):
        with patch("app.fetch_one", side_effect=[
            {"total": 0}, {"total": 0}, {"total": 0}, {"total": 0}, {"total": 0},
            {"total": 0}, {"total": 0}, None,
        ]), patch("app.fetch_all", side_effect=[[], []]):
            resposta = self.client.get("/dashboard")

        self.assertEqual(resposta.status_code, 200)
        html = resposta.get_data(as_text=True)
        self.assertIn("A análise começa pelo histórico", html)
        self.assertIn("A sua carteira ainda está vazia", html)
        self.assertNotIn("Base de dados ligada", html)
        self.assertNotIn("Motor online", html)

    def test_percentagens_sem_zeros_desnecessarios(self):
        self.assertEqual(pct_br_filter(100), "100%")
        self.assertEqual(pct_br_filter(45.23), "45,23%")
        self.assertEqual(pct_br_filter(45.2), "45,2%")
        self.assertEqual(pct_br_filter(0), "0%")


if __name__ == "__main__":
    unittest.main()
