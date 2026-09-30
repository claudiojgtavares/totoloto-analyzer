import unittest
from unittest.mock import patch

from app import app
from modules.wheeling import planear_wheel


class WheelingRotasTests(unittest.TestCase):
    def setUp(self):
        self.config = patch.dict(app.config, {"TESTING": True})
        self.config.start()
        self.addCleanup(self.config.stop)
        self.client = app.test_client()
        self.dados = {"pool": "1,2,3,4,5,6,7", "quantidade_linhas": "10", "nivel": "3"}

    def test_get_renderiza_acentos_csrf_e_avisos_sem_mysql(self):
        with patch("app.get_configuracao") as config:
            r = self.client.get("/wheeling")
        config.assert_not_called()
        texto = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 200)
        for esperado in ("Análise combinatória", "FATO MATEMÁTICO", "HEURÍSTICA",
                         'name="csrf_token"', "Cobrir pares não garante prémio",
                         "Orçamento comprometido", "Gasto real em apostas compradas"):
            self.assertIn(esperado, texto)

    @patch("app.get_configuracao", return_value={"preco_aposta_simples": 40})
    def test_post_certifica_e_nao_grava_jogos_ou_orcamento(self, _config):
        with patch("app._guardar_geracao_com_orcamento") as guardar, \
             patch("app.transaction_scope") as transacao:
            r = self.client.post("/wheeling", data=self.dados)
        guardar.assert_not_called()
        transacao.assert_not_called()
        self.assertEqual(r.status_code, 200)
        texto = r.get_data(as_text=True)
        self.assertIn("Cobertura completa verificada", texto)
        self.assertIn("40 CVE por linha", texto)
        self.assertIn("pelo menos 3 acertos", texto)
        self.assertIn("SHA-256", texto)

    @patch("app.get_configuracao", return_value={"preco_aposta_simples": 30})
    def test_limite_de_linhas_mostra_parcial_sem_garantia(self, _config):
        r = self.client.post("/wheeling", data={**self.dados, "quantidade_linhas": "1"})
        texto = r.get_data(as_text=True)
        self.assertIn("Cobertura parcial", texto)
        self.assertIn("20 / 35", texto)
        self.assertIn("30 CVE", texto)
        self.assertNotIn("pelo menos 3 acertos", texto)

    def test_validacao_rejeita_entradas_antes_de_consultar_mysql(self):
        for dados in ({"pool": "1,2,3,4,5,5"}, {"pool": "1,2,3,4,5,46"},
                      {"pool": "1,2,3,4,5,6<script>"}, {"pool": "1,2,3"},
                      {"pool": ", ; "}, {"nivel": "4"}, {"quantidade_linhas": "421"},
                      {"quantidade_linhas": "1.5"}):
            with self.subTest(dados=dados), patch("app.get_configuracao") as config:
                r = self.client.post("/wheeling", data={**self.dados, **dados})
                self.assertEqual(r.status_code, 400)
                config.assert_not_called()
                if "<script>" in dados.get("pool", ""):
                    self.assertNotIn(dados["pool"], r.get_data(as_text=True))
                    self.assertIn("1,2,3,4,5,6&lt;script&gt;", r.get_data(as_text=True))

    def test_csrf_ativo_rejeita_post_sem_token_e_aceita_token_da_pagina(self):
        with patch.dict(app.config, {"TESTING": False}), \
             patch("app.get_configuracao", return_value={"preco_aposta_simples": 30}):
            self.assertEqual(self.client.post("/wheeling", data=self.dados).status_code, 400)
            self.client.get("/wheeling")
            with self.client.session_transaction() as sessao:
                token = sessao["_csrf_token"]
            r = self.client.post("/wheeling", data={**self.dados, "csrf_token": token})
            self.assertEqual(r.status_code, 200)

    @patch("app.get_configuracao", return_value={"preco_aposta_simples": 30})
    def test_timeout_e_apresentado_como_incompleto(self, _config):
        with patch("modules.wheeling.monotonic", side_effect=[0, 11, 11]):
            parcial = planear_wheel(range(1, 8), 10)
        with patch("app.planear_wheel", return_value=parcial):
            r = self.client.post("/wheeling", data=self.dados)
        self.assertIn("Resultado incompleto", r.get_data(as_text=True))
        self.assertNotIn("Cobertura completa verificada", r.get_data(as_text=True))

    def test_erro_interno_nao_expoe_excecao(self):
        with patch("app.get_configuracao", side_effect=RuntimeError("segredo-mysql")), \
             patch.object(app.logger, "error") as log:
            r = self.client.post("/wheeling", data=self.dados)
        self.assertEqual(r.status_code, 500)
        self.assertNotIn("segredo-mysql", r.get_data(as_text=True))
        self.assertIn("ID", r.get_data(as_text=True))
        log.assert_called_once()

    @patch("app.get_configuracao", return_value={"preco_aposta_simples": 30})
    def test_orcamento_30_limita_carteira_a_uma_linha(self, _config):
        r = self.client.post("/wheeling", data={**self.dados,
                             "modo_limite": "orcamento", "orcamento": "30"})
        texto = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn("Linhas simples: 1 / 1 permitidas", texto)
        self.assertIn("Cobertura parcial", texto)

    @patch("app.get_configuracao", return_value={"preco_aposta_simples": "30.50"})
    def test_modo_orcamento_preserva_centavos_e_nao_escreve_na_banca(self, _config):
        with patch("app._guardar_geracao_com_orcamento") as guardar, \
             patch("app.transaction_scope") as transacao:
            r = self.client.post("/wheeling", data={**self.dados, "quantidade_linhas": "",
                                 "modo_limite": "orcamento", "orcamento": "60,99"})
        self.assertEqual(r.status_code, 200)
        texto = r.get_data(as_text=True)
        for esperado in ("60,99 CVE", "30,50 CVE", "30,49 CVE", "Limite do orçamento atingido",
                         "subconjuntos cobertos por CVE", "Orçamento comprometido",
                         "Gasto real em apostas compradas"):
            self.assertIn(esperado, texto)
        guardar.assert_not_called()
        transacao.assert_not_called()

    def test_orcamento_malformado_e_modo_invalido_nao_consultam_mysql(self):
        for dados in ({"orcamento": "1,234"}, {"orcamento": "NaN"}, {"orcamento": ""},
                      {"modo_limite": "invalido"}, {"orcamento": "-30"}):
            with self.subTest(dados=dados), patch("app.get_configuracao") as config:
                r = self.client.post("/wheeling", data={**self.dados,
                                     "modo_limite": "orcamento", "orcamento": "1000", **dados})
                self.assertEqual(r.status_code, 400)
                config.assert_not_called()

    @patch("app.get_configuracao", return_value={"preco_aposta_simples": 30})
    def test_orcamento_pt_exibe_limite_saldo_e_nao_altera_certificado(self, _config):
        for montante in ("1.000", "1.000,50"):
            with self.subTest(montante=montante):
                r = self.client.post("/wheeling", data={**self.dados,
                                     "modo_limite": "orcamento", "orcamento": montante})
                texto = r.get_data(as_text=True)
                self.assertEqual(r.status_code, 200)
                self.assertIn("4 / 33 permitidas", texto)
                self.assertIn("Cobertura completa verificada", texto)
                self.assertIn("880,50 CVE" if montante.endswith(",50") else "880 CVE", texto)

    @patch("app.get_configuracao", return_value={"preco_aposta_simples": 30})
    def test_modo_linhas_ignora_orcamento_inativo(self, _config):
        r = self.client.post("/wheeling", data={**self.dados, "modo_limite": "linhas",
                             "orcamento": "invalido"})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("Orçamento indicado:", r.get_data(as_text=True))

    @patch("app.get_configuracao", return_value={"preco_aposta_simples": 30})
    def test_orcamento_insuficiente_mostra_preco_sem_resultado(self, _config):
        r = self.client.post("/wheeling", data={**self.dados,
                             "modo_limite": "orcamento", "orcamento": "29,99"})
        self.assertEqual(r.status_code, 400)
        texto = r.get_data(as_text=True)
        self.assertIn("29,99 CVE", texto)
        self.assertIn("não permite uma linha de 30 CVE", texto)
        self.assertNotIn("Certificado de cobertura", texto)


if __name__ == "__main__":
    unittest.main()
