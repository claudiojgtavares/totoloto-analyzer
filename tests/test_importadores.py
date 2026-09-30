import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.importador import carregar_registros_estatistica, importar_arquivo_estatistica
from modules.joker import _registos_de_texto, _registos_de_dataframe
import pandas as pd


class ImportadoresTests(unittest.TestCase):
    def _csv_estatistica(self, quantidade=45):
        ficheiro = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, newline="", mode="w", encoding="utf-8")
        self.addCleanup(lambda: Path(ficheiro.name).unlink(missing_ok=True))
        escritor = csv.writer(ficheiro)
        escritor.writerow(["numero", "numero_saidas", "percentual", "ultimo sorteio", "data", "ausencias"])
        for numero in range(1, quantidade + 1):
            escritor.writerow([numero, 10, "13,33", "1/2026", "17/09/2026", 0])
        ficheiro.close()
        return ficheiro.name

    def test_csv_estatistica_exige_45_numeros_unicos(self):
        registos = carregar_registros_estatistica(self._csv_estatistica())
        self.assertEqual(len(registos), 45)
        self.assertEqual(registos[0]["numero"], 1)
        with self.assertRaisesRegex(ValueError, "45 números únicos"):
            carregar_registros_estatistica(self._csv_estatistica(44))

    def test_xls_sem_xlrd_tem_mensagem_explicita(self):
        with patch("modules.importador.pd.read_excel", side_effect=ImportError("xlrd ausente")):
            with self.assertRaisesRegex(ValueError, "xlrd"):
                from modules.importador import _ler_excel
                _ler_excel("historico.xls")

    def test_joker_texto_colado_e_dataframe_csv(self):
        texto = "Concurso 49/2025 Sábado, 06 DEZ 2025 1.º Prémio 9 8 9 6 8 2"
        registos_texto = _registos_de_texto(texto)
        self.assertEqual(len(registos_texto), 1)
        self.assertEqual(registos_texto[0]["numero_joker"], "989682")

        df = pd.DataFrame({
            "Concurso": ["49/2025"],
            "Data": ["06/12/2025"],
            "Joker": ["989682"],
        })
        registos_df = _registos_de_dataframe(df)
        self.assertEqual(registos_df[0]["concurso"], "49/2025")

    def test_joker_rejeita_ficheiro_sem_linhas_validas(self):
        df = pd.DataFrame({"Concurso": [""], "Data": [""], "Joker": [""]})
        with self.assertRaises(ValueError):
            _registos_de_dataframe(df)

    def test_importador_nao_faz_commit_interno(self):
        class Cursor:
            def execute(self, *args):
                pass
            def close(self):
                pass
        class Connection:
            commits = 0
            def cursor(self):
                return Cursor()
            def commit(self):
                self.commits += 1
        importar_arquivo_estatistica(self._csv_estatistica(), Connection())
        self.assertEqual(Connection.commits, 0)


if __name__ == "__main__":
    unittest.main()
