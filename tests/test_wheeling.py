import unittest
from decimal import Decimal
from itertools import chain, combinations, repeat
from unittest.mock import patch

from modules.wheeling import construir_wheel, verificar_cobertura, FATO_MATEMATICO
from modules.wheeling import (
    planear_wheel, planear_wheel_orcamento, interpretar_orcamento_cve, formatar_cve_exato,
)


class WheelingTests(unittest.TestCase):
    def test_verificador_detecta_cobertura_completa(self):
        linhas = [(1, 2, 3), (1, 2, 4), (1, 3, 4), (2, 3, 4)]
        resultado = verificar_cobertura(linhas, range(1, 5), t=2)
        self.assertEqual(resultado["rotulo"], FATO_MATEMATICO)
        self.assertEqual(resultado["descobertos"], 0)

    def test_construtor_respeita_numero_de_linhas_e_verifica(self):
        linhas = construir_wheel(range(1, 7), 2, tamanho_linha=4, t=2)
        self.assertLessEqual(len(linhas), 2)
        resultado = verificar_cobertura(linhas, range(1, 7), t=2)
        self.assertGreater(resultado["cobertura"], 0)

    def test_verificador_rejeita_linha_com_numero_fora_do_pool(self):
        with self.assertRaises(ValueError):
            verificar_cobertura([(1, 2, 3, 4, 5, 45)], range(1, 7), t=3)

    def test_verificador_rejeita_repeticao_dentro_da_linha(self):
        with self.assertRaises(ValueError):
            verificar_cobertura([(1, 2, 3, 4, 5, 5)], range(1, 7), t=3)

    def test_verificador_rejeita_nivel_impossivel(self):
        with self.assertRaises(ValueError):
            verificar_cobertura([], range(1, 7), t=7)

    def test_linha_vazia_tamanhos_inconsistentes_e_pool_invalido(self):
        for linhas, pool in (([()], range(1, 7)),
                             ([(1, 2, 3), (1, 2, 3, 4)], range(1, 7)),
                             ([], [1, 2, 3, 4, 5, 5]),
                             ([], [0, 1, 2, 3, 4, 5]),
                             ([], [True, 2, 3, 4, 5, 6]),
                             ([], [1.0, 2, 3, 4, 5, 6])):
            with self.subTest(linhas=linhas, pool=pool), self.assertRaises(ValueError):
                verificar_cobertura(linhas, pool, t=3)

    def test_cobertura_parcial_exata_sem_garantia(self):
        r = planear_wheel(range(1, 8), 1, t=3, preco_aposta="30.50")
        self.assertEqual(r["certificado"]["subconjuntos_totais"], 35)
        self.assertEqual(r["certificado"]["cobertos"], 20)
        self.assertEqual(r["certificado"]["descobertos"], 15)
        self.assertIsNone(r["garantia"])
        self.assertFalse(r["incompleto"])
        self.assertEqual(r["motivo"], "limite_linhas")
        self.assertEqual(r["custo_simulado"], Decimal("30.50"))

    def test_certificado_completo_garante_trinca_por_enumeracao(self):
        r = planear_wheel(range(1, 9), 50, t=3)
        self.assertTrue(r["certificado"]["cobertura_completa"])
        self.assertIn("pelo menos 3 acertos", r["garantia"])
        self.assertEqual(r["motivo"], "cobertura_completa")
        self.assertLess(len(r["linhas"]), 50)
        for trinca in combinations(range(1, 9), 3):
            # Resultado com exatamente estes três números dentro do conjunto.
            sorteio = set(trinca) | {43, 44, 45}
            self.assertGreaterEqual(max(len(set(l) & sorteio) for l in r["linhas"]), 3)

    def test_linhas_duplicadas_nao_aumentam_cobertura(self):
        linha = (1, 2, 3, 4, 5, 6)
        r = verificar_cobertura([linha, linha], range(1, 8), t=3)
        self.assertEqual(r["cobertos"], 20)
        self.assertEqual(r["linhas_duplicadas"], 1)

    def test_mesma_entrada_reproduz_carteira_e_hash(self):
        a = planear_wheel(range(1, 10), 10)
        b = planear_wheel(range(9, 0, -1), 10)
        self.assertEqual(a["linhas"], b["linhas"])
        self.assertEqual(a["certificado"]["hash_sha256"], b["certificado"]["hash_sha256"])
        self.assertEqual(len(set(a["linhas"])), len(a["linhas"]))
        c = verificar_cobertura(list(reversed(a["linhas"])), range(1, 10), 3, 6)
        self.assertEqual(c["hash_sha256"], a["certificado"]["hash_sha256"])

    def test_timeout_devolve_parcial_verificado_e_custo_das_linhas_concluidas(self):
        # 1 leitura inicial, 7 candidatos e 7 comparações; interrompe a 2.ª linha.
        with patch("modules.wheeling.monotonic", side_effect=chain(repeat(0, 15), repeat(11))):
            r = planear_wheel(range(1, 8), 10)
        self.assertTrue(r["incompleto"])
        self.assertEqual(r["motivo"], "timeout")
        self.assertEqual(len(r["linhas"]), 1)
        self.assertEqual(r["custo_simulado"], Decimal(30))
        self.assertEqual(r["certificado"]["cobertos"], 20)
        self.assertEqual(r["tempo_segundos"], 11)
        self.assertIsNone(r["garantia"])

    def test_timeout_na_preparacao_nao_inventa_cobertura(self):
        with patch("modules.wheeling.monotonic", side_effect=[0, 11, 11]):
            r = planear_wheel(range(1, 8), 10)
        self.assertTrue(r["incompleto"])
        self.assertEqual(r["certificado"]["cobertura"], 0)
        self.assertEqual(r["custo_simulado"], 0)

    def test_limites_de_execucao_e_valores_invalidos(self):
        for kwargs in ({"quantidade_linhas": 421}, {"quantidade_linhas": 0},
                       {"pool": range(1, 14)}, {"pool": range(1, 6)},
                       {"t": 4}, {"timeout_segundos": float("nan")},
                       {"timeout_segundos": 11}, {"preco_aposta": "NaN"},
                       {"preco_aposta": -30}):
            argumentos = {"pool": range(1, 8), "quantidade_linhas": 10, **kwargs}
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                planear_wheel(**argumentos)

    def test_limite_superior_produz_linhas_validas_6_45(self):
        r = planear_wheel(range(1, 13), 420)
        self.assertFalse(r["incompleto"])
        self.assertTrue(r["certificado"]["cobertura_completa"])
        self.assertLessEqual(len(r["linhas"]), 420)
        for linha in r["linhas"]:
            self.assertEqual(len(set(linha)), 6)
            self.assertTrue(set(linha) <= set(range(1, 13)))


class WheelingOrcamentoTests(unittest.TestCase):
    def test_formatos_pt_preservam_milhar_e_centavos(self):
        for entrada, esperado in (("1.000", "1000"), ("1.000,50", "1000.50"),
                                  ("1000,50", "1000.50"), ("30.50", "30.50"),
                                  ("0,10", "0.10"), (Decimal("1200.50"), "1200.50")):
            with self.subTest(entrada=entrada):
                valor = interpretar_orcamento_cve(entrada)
                self.assertIsInstance(valor, Decimal)
                self.assertEqual(valor, Decimal(esperado))

    def test_rejeita_orcamento_invalido_sem_construir(self):
        for valor in ("", "-10", "NaN", "Infinity", "1.00,50", "1,234", "1e5",
                      "9999999999", "0", True, float("inf"), Decimal("0.001")):
            with self.subTest(valor=valor), patch("modules.wheeling._construir") as construir:
                with self.assertRaises(ValueError):
                    planear_wheel_orcamento(range(1, 8), valor)
                construir.assert_not_called()

    def test_orcamento_inferior_ao_preco_mostra_montantes_exatos(self):
        with self.assertRaisesRegex(ValueError, r"30,49 CVE.*30,50 CVE"):
            planear_wheel_orcamento(range(1, 8), "30,49", preco_aposta=Decimal("30.50"))

    def test_divisao_decimal_exata_e_limite_sem_arredondar_para_cima(self):
        for montante, preco, linhas, saldo in (("0,30", "0.10", 3, "0"),
                                             ("61,00", "30.50", 2, "0"),
                                             ("60,99", "30.50", 1, "30.49")):
            with self.subTest(montante=montante):
                r = planear_wheel_orcamento(range(1, 8), montante, preco_aposta=preco)
                self.assertEqual(len(r["linhas"]), linhas)
                self.assertEqual(r["saldo_nao_utilizado"], Decimal(saldo))
                self.assertLessEqual(r["custo_simulado"], r["orcamento"])
                self.assertEqual(r["motivo"], "limite_orcamento")

    def test_para_na_cobertura_completa_e_devolve_saldo(self):
        r = planear_wheel_orcamento(range(1, 9), "1.000,50")
        self.assertEqual(r["max_linhas"], 33)
        self.assertEqual(r["motivo"], "cobertura_completa")
        self.assertLess(len(r["linhas"]), 33)
        self.assertGreater(r["saldo_nao_utilizado"], 0)
        self.assertEqual(r["saldo_nao_utilizado"] + r["custo_simulado"], Decimal("1000.50"))

    def test_teto_420_e_identificado_sem_consumir_excedente(self):
        r = planear_wheel_orcamento(range(1, 13), "15.000")
        self.assertEqual(r["linhas_financiaveis"], 500)
        self.assertEqual(r["max_linhas"], 420)
        self.assertTrue(r["limitado_por_teto"])
        self.assertLessEqual(len(r["linhas"]), 420)
        self.assertLessEqual(r["custo_simulado"], Decimal(15000))

    def test_timeout_preserva_saldo_e_cobertura_das_linhas_concluidas(self):
        with patch("modules.wheeling.monotonic", side_effect=chain(repeat(0, 15), repeat(11))):
            r = planear_wheel_orcamento(range(1, 8), "300")
        self.assertEqual(r["motivo"], "timeout")
        self.assertTrue(r["incompleto"])
        self.assertEqual(r["custo_simulado"], Decimal(30))
        self.assertEqual(r["saldo_nao_utilizado"], Decimal(270))
        self.assertEqual(r["cobertura_por_cve"], Decimal(20) / 30)
        self.assertIsNone(r["garantia"])

    def test_timeout_sem_linhas_nao_divide_por_zero(self):
        with patch("modules.wheeling.monotonic", side_effect=[0, 11, 11]):
            r = planear_wheel_orcamento(range(1, 8), "300")
        self.assertIsNone(r["cobertura_por_cve"])
        self.assertEqual(r["saldo_nao_utilizado"], Decimal(300))

    def test_orcamento_e_max_linhas_equivalentes_geram_mesma_carteira(self):
        a = planear_wheel_orcamento(range(1, 11), "90")
        b = planear_wheel(range(1, 11), 3)
        self.assertEqual(a["certificado"], b["certificado"])
        self.assertEqual(a["linhas"], b["linhas"])

    def test_precos_invalidos_sao_rejeitados(self):
        for preco in (0, -30, "NaN", "Infinity", "0.001", None):
            with self.subTest(preco=preco), self.assertRaises(ValueError):
                planear_wheel_orcamento(range(1, 8), "1000", preco_aposta=preco)

    def test_formatacao_nao_oculta_centavos(self):
        self.assertEqual(formatar_cve_exato(Decimal("1000.50")), "1.000,50 CVE")
        self.assertEqual(formatar_cve_exato(Decimal("30")), "30 CVE")
        self.assertEqual(formatar_cve_exato(Decimal("0.01")), "0,01 CVE")


if __name__ == "__main__":
    unittest.main()
