import re
import unittest
from unittest.mock import patch

from app import app


class ErrorMessageTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def test_rota_nao_expoe_excecao_crua_e_mostra_id(self):
        original = "SEGREDO-EXCECAO-123"
        with patch("app.fetch_all", side_effect=RuntimeError(original)), \
             patch.object(app.logger, "error") as log_error:
            resposta = self.client.get("/dashboard")

        self.assertEqual(resposta.status_code, 200)
        corpo = resposta.data.decode("utf-8")
        self.assertNotIn(original, corpo)
        self.assertRegex(corpo, r"ID [0-9a-f]{8}")
        log_error.assert_called_once()
        self.assertIn("Erro interno", str(log_error.call_args))


if __name__ == "__main__":
    unittest.main()
