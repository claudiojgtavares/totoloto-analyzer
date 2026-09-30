import math
import random
import unittest

from modules.backtesting import executar_backtesting, max_bilhetes_backtesting
from modules.gerador import calcular_custo, gerar_jogos_estatisticos
from modules.totoloto import (
    avaliar_aposta,
    expandir_aposta,
    metricas_cobertura,
    probabilidade_acertos,
)


class RegrasTotolotoTests(unittest.TestCase):
    def test_quantidade_de_linhas_oficiais(self):
        esperadas = {5: 40, 6: 1, 7: 7, 8: 28, 9: 84, 10: 210}
        for quantidade, linhas in esperadas.items():
            with self.subTest(quantidade=quantidade):
                self.assertEqual(len(expandir_aposta(range(1, quantidade + 1))), linhas)
                self.assertEqual(calcular_custo(quantidade)["apostas_simples"], linhas)

    def test_cinco_fixos_seguem_tabela_regulamentar(self):
        cinco_acertos = avaliar_aposta([1, 2, 3, 4, 5], [1, 2, 3, 4, 5, 6])
        self.assertEqual(cinco_acertos["premios"], {
            "primeiro": 1, "segundo": 39, "terceiro": 0, "quarto": 0,
        })

        quatro_acertos = avaliar_aposta([1, 2, 3, 4, 20], [1, 2, 3, 4, 5, 6])
        self.assertEqual(quatro_acertos["premios"], {
            "primeiro": 0, "segundo": 2, "terceiro": 38, "quarto": 0,
        })

    def test_multiplas_seguem_tabela_regulamentar(self):
        sete = avaliar_aposta(range(1, 8), range(1, 7))
        self.assertEqual(sete["premios"], {
            "primeiro": 1, "segundo": 6, "terceiro": 0, "quarto": 0,
        })

        oito = avaliar_aposta(range(1, 9), range(1, 7))
        self.assertEqual(oito["premios"], {
            "primeiro": 1, "segundo": 12, "terceiro": 15, "quarto": 0,
        })

    def test_multiplas_todos_tamanhos_e_acertos(self):
        for tamanho in range(6, 11):
            pool = list(range(1, tamanho + 1))
            for acertos_pool in range(0, 7):
                if acertos_pool > tamanho or 6 - acertos_pool > 45 - tamanho:
                    continue
                resultado = pool[:acertos_pool] + list(
                    range(tamanho + 1, tamanho + 1 + (6 - acertos_pool))
                )
                avaliacao = avaliar_aposta(pool, resultado)
                for acertos_linha in range(7):
                    esperado = (
                        math.comb(acertos_pool, acertos_linha)
                        * math.comb(tamanho - acertos_pool, 6 - acertos_linha)
                        if acertos_linha <= acertos_pool
                        and 0 <= 6 - acertos_linha <= tamanho - acertos_pool
                        else 0
                    )
                    self.assertEqual(
                        avaliacao["distribuicao_acertos"][acertos_linha], esperado,
                        (tamanho, acertos_pool, acertos_linha),
                    )

    def test_custo_joker_e_entradas_invalidas(self):
        self.assertEqual(calcular_custo(10, incluir_joker=True)["custo_final"], 6370)
        with self.assertRaises(ValueError):
            expandir_aposta([1, 1, 2, 3, 4, 5])
        with self.assertRaises(ValueError):
            expandir_aposta([0, 1, 2, 3, 4, 5])

    def test_distribuicao_teorica_fecha_em_um(self):
        probabilidades = [probabilidade_acertos(k) for k in range(7)]
        self.assertAlmostEqual(sum(probabilidades), 1.0, places=12)
        self.assertAlmostEqual(sum(k * p for k, p in enumerate(probabilidades)), 0.8, places=12)
        self.assertEqual(math.comb(45, 6), 8_145_060)


class GeracaoECoberturaTests(unittest.TestCase):
    def test_gerador_entrega_carteira_com_score_de_cobertura(self):
        jogos = gerar_jogos_estatisticos([], quantidade_jogos=5, qtd_numeros=6, seed=2026)
        self.assertEqual(len(jogos), 5)
        self.assertEqual(len({tuple(jogo["numeros"]) for jogo in jogos}), 5)
        self.assertTrue(all("score_cobertura" in jogo for jogo in jogos))
        self.assertTrue(all(jogo["linhas_aprovadas_filtros"] == 1 for jogo in jogos))
        cobertura = metricas_cobertura(jogos)
        self.assertEqual(cobertura["linhas"], 5)
        self.assertEqual(cobertura["linhas_duplicadas"], 0)
        self.assertGreaterEqual(cobertura["numeros_unicos"], 20)


class BacktestingExatoTests(unittest.TestCase):
    @staticmethod
    def _historico(quantidade=15):
        rng = random.Random(91)
        sorteios = []
        for concurso in range(1, quantidade + 1):
            numeros = sorted(rng.sample(range(1, 46), 6))
            sorteios.append({
                "concurso": concurso,
                "data_sorteio": None,
                **{f"n{i + 1}": numero for i, numero in enumerate(numeros)},
            })
        return sorteios

    def test_multipla_e_avaliada_por_linha_e_com_baseline(self):
        resumo = executar_backtesting(
            self._historico(),
            quantidade_jogos=1,
            qtd_numeros=7,
            min_historico=10,
        )
        self.assertEqual(resumo["concursos_testados"], 5)
        self.assertEqual(resumo["bilhetes_testados"], 5)
        self.assertEqual(resumo["linhas_testadas"], 35)
        self.assertEqual(resumo["baseline"]["linhas"], 35)
        self.assertEqual(resumo["custo_simulado"], 5 * 7 * 30)
        self.assertIsNone(resumo["retorno_simulado"])
        self.assertIsNone(resumo["lucro_prejuizo"])
        self.assertTrue(all(item["linhas_testadas"] == 7 for item in resumo["detalhes"]))
        self.assertEqual(resumo["baseline_repeticoes"], 20)
        self.assertEqual(len(resumo["diferenca_baseline_ic_95"]), 2)

    def test_limite_de_carga_das_multiplas(self):
        self.assertEqual(max_bilhetes_backtesting(10), 2)
        with self.assertRaises(ValueError):
            executar_backtesting(
                self._historico(), quantidade_jogos=3, qtd_numeros=10, min_historico=10
            )

    def test_limite_de_concursos_mantem_historico_e_reduz_alvos(self):
        resumo = executar_backtesting(
            self._historico(20), quantidade_jogos=1, qtd_numeros=6,
            min_historico=10, limite_concursos=3,
        )
        self.assertEqual(resumo["concursos_testados"], 3)
        self.assertEqual(resumo["limite_concursos"], 3)
        self.assertFalse(resumo["incompleto"])


if __name__ == "__main__":
    unittest.main()
