import unittest

from modules.analise_rigor import (
    FATO_MATEMATICO, corrigir_bh, corrigir_holm, suavizar_frequencias,
    teste_ajuste_uniforme, controlo_sintetico,
)


class AnaliseRigorTests(unittest.TestCase):
    def test_prior_beta_6_45_evita_probabilidade_zero(self):
        resultado = suavizar_frequencias({1: 6, **{n: 0 for n in range(2, 46)}}, kappa=45)
        self.assertGreater(resultado[2], 0)
        self.assertLess(resultado[1], 1)
        self.assertAlmostEqual(suavizar_frequencias({n: 0 for n in range(1, 46)}, kappa=45)[1], 6 / 45, places=6)

    def test_qui_quadrado_e_controle_tem_rotulo_e_p(self):
        resultado = teste_ajuste_uniforme({n: 6 for n in range(1, 46)}, simulacoes=20)
        self.assertEqual(resultado["rotulo"], FATO_MATEMATICO)
        self.assertGreaterEqual(resultado["p_valor_empirico"], 0)
        self.assertLessEqual(resultado["p_valor_empirico"], 1)
        controlo = controlo_sintetico([0.2, 0.4], [0.0, 0.1, 0.2])
        self.assertEqual(controlo["rotulo"], FATO_MATEMATICO)

    def test_benjamini_hochberg_corrige_multiplos_testes(self):
        resultado = corrigir_bh([0.001, 0.04, 0.9])
        self.assertEqual(resultado["rotulo"], FATO_MATEMATICO)
        self.assertEqual(resultado["metodo"], "Benjamini-Hochberg")
        self.assertEqual(resultado["significativos"], [0])

    def test_holm_bonferroni_corrige_e_identifica_metodo(self):
        resultado = corrigir_holm([0.001, 0.04, 0.9])
        self.assertEqual(resultado["rotulo"], FATO_MATEMATICO)
        self.assertEqual(resultado["metodo"], "Holm-Bonferroni")
        self.assertEqual(resultado["significativos"], [0])


if __name__ == "__main__":
    unittest.main()

