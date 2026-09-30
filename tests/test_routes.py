import unittest
from io import BytesIO
from unittest.mock import patch

from app import app


CONFIG_PADRAO = {
    "preco_aposta_simples": 30,
    "preco_joker": 70,
    "orcamento_semanal": 1000,
    "moeda": "CVE",
}


def fetch_one_falso(sql, params=None):
    texto = " ".join(sql.lower().split())
    if "sum(valor_gasto)" in texto:
        return {"gasto": 0, "retorno": 0, "saldo": 0}
    if "count(*) total" in texto:
        return {"total": 0}
    if "from configuracoes" in texto:
        return dict(CONFIG_PADRAO)
    return None


class RotasGetTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()

    @patch("app.get_configuracao", return_value=CONFIG_PADRAO)
    @patch("app.fetch_one", side_effect=fetch_one_falso)
    @patch("app.fetch_all", return_value=[])
    def test_paginas_get_renderizam_sem_base_real(self, _fetch_all, _fetch_one, _config):
        rotas = (
            "/dashboard",
            "/estatisticas",
            "/importar-estatistica",
            "/cadastrar-sorteio",
            "/gerar-jogos",
            "/joker",
            "/estrategias",
            "/backtesting",
            "/controle-banca",
            "/relatorios",
            "/configuracoes",
        )
        for rota in rotas:
            with self.subTest(rota=rota):
                resposta = self.client.get(rota)
                self.assertEqual(resposta.status_code, 200)
                self.assertIn("text/html", resposta.content_type)

    def test_raiz_redireciona_para_dashboard(self):
        resposta = self.client.get("/")
        self.assertEqual(resposta.status_code, 302)
        self.assertTrue(resposta.headers["Location"].endswith("/dashboard"))

    def test_modelo_joker_e_csv_valido(self):
        resposta = self.client.get("/joker/modelo-importacao")
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("text/csv", resposta.content_type)
        self.assertIn(b"Concurso;Data;Joker;Categoria", resposta.data)

    def test_estado_backtesting_inexistente_devolve_404(self):
        resposta = self.client.get("/backtesting/jobs/inexistente")
        self.assertEqual(resposta.status_code, 404)
        self.assertEqual(resposta.json["estado"], "nao_encontrado")

    def test_upload_estatistica_rejeita_extensao_executavel(self):
        resposta = self.client.post(
            "/importar-estatistica",
            data={"arquivo": (BytesIO(b"nao executar"), "dados.exe")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertIn(b"Formato de estat", resposta.data)

    def test_upload_estatistica_rejeita_xls_sem_xlrd(self):
        resposta = self.client.post(
            "/importar-estatistica",
            data={"arquivo": (BytesIO(b"xls indisponivel"), "dados.xls")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertIn(b"Use CSV, XLSX ou PDF", resposta.data)


if __name__ == "__main__":
    unittest.main()
