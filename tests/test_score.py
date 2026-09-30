import random
import unittest

from modules.score import calcular_score, normalizar_score_tecnico
from modules.joker import calcular_score_joker


class ScoreTecnicoTests(unittest.TestCase):
    def test_score_e_normalizado_e_nao_satura_todas_as_linhas_em_cem(self):
        rng = random.Random(2026)
        valores = [calcular_score(rng.sample(range(1, 46), 6), []) for _ in range(100)]
        self.assertTrue(all(0 <= valor <= 100 for valor in valores))
        self.assertGreater(len(set(valores)), 1)
        self.assertLess(sum(valor == 100 for valor in valores), len(valores))

    def test_normalizacao_e_joker_usam_escala_percentual_tecnica(self):
        self.assertEqual(normalizar_score_tecnico(0), 0.0)
        self.assertEqual(normalizar_score_tecnico(135), 100.0)
        self.assertEqual(normalizar_score_tecnico(200), 100.0)
        joker = calcular_score_joker("123456", [], "Equilibrada")
        self.assertTrue(0 <= joker <= 100)


if __name__ == "__main__":
    unittest.main()
