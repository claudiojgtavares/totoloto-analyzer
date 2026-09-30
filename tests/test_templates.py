import unittest

from flask import render_template

from app import app
from modules.backtesting import resumo_backtesting_demo


class TemplatesTotolotoTests(unittest.TestCase):
    def test_interfaces_renderizam_e_ocultam_cinco_fixos(self):
        with app.test_request_context("/backtesting"):
            estrategias = [{"nome": "Equilibrada"}]
            selecionado = {
                "estrategia": "Equilibrada",
                "quantidade_jogos": 5,
                "qtd_numeros": 6,
                "incluir_joker": False,
            }
            backtesting = render_template(
                "backtesting.html",
                resumo=resumo_backtesting_demo(),
                estrategias=estrategias,
                selecionado=selecionado,
            )
            geracao = render_template(
                "gerar_jogos.html",
                estrategias=estrategias,
                jogos=[{
                    "numeros": [1, 2, 3, 4, 5, 6],
                    "tipo_aposta": "Simples",
                    "estrategia": "Equilibrada",
                    "apostas_simples": 1,
                    "score": 80,
                    "score_cobertura": 100,
                    "custo_total": 30,
                    "custo_joker": 0,
                    "custo_final": 30,
                }],
                config={
                    "preco_aposta_simples": 30,
                    "preco_joker": 70,
                    "orcamento_semanal": 1000,
                },
            )

        self.assertIn("Baseline uniforme", backtesting)
        self.assertIn("Score cobertura", geracao)
        self.assertNotIn('option value="5"', backtesting)
        self.assertNotIn('option value="5"', geracao)


if __name__ == "__main__":
    unittest.main()
