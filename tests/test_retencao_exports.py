import os
import tempfile
import time
import unittest
from pathlib import Path

from modules.relatorios import exportar_excel_jogos, limpar_exports


class RetencaoExportsTests(unittest.TestCase):
    def _ficheiro(self, pasta, nome, idade=0, conteudo="x"):
        caminho = Path(pasta) / nome
        caminho.write_text(conteudo, encoding="utf-8")
        instante = time.time() - idade * 86400
        os.utime(caminho, (instante, instante))
        return caminho

    def test_remove_por_idade_preserva_gitkeep_e_extensoes_desconhecidas(self):
        with tempfile.TemporaryDirectory() as pasta:
            self._ficheiro(pasta, "antigo.pdf", idade=31)
            recente = self._ficheiro(pasta, "recente.pdf")
            gitkeep = self._ficheiro(pasta, ".gitkeep", idade=90)
            outro = self._ficheiro(pasta, "notas.txt", idade=90)

            removidos = limpar_exports(pasta, dias=30, max_ficheiros=0)

            self.assertEqual(removidos, 1)
            self.assertFalse((Path(pasta) / "antigo.pdf").exists())
            self.assertTrue(recente.exists())
            self.assertTrue(gitkeep.exists())
            self.assertTrue(outro.exists())

    def test_limite_de_ficheiros_mantem_os_mais_recentes(self):
        with tempfile.TemporaryDirectory() as pasta:
            antigos = [self._ficheiro(pasta, f"r{i}.pdf", idade=3 - i) for i in range(3)]
            removidos = limpar_exports(pasta, dias=0, max_ficheiros=2)

            self.assertEqual(removidos, 1)
            self.assertFalse(antigos[0].exists())
            self.assertTrue(antigos[1].exists())
            self.assertTrue(antigos[2].exists())

    def test_limites_invalidos_sao_normalizados_para_zero(self):
        with tempfile.TemporaryDirectory() as pasta:
            ficheiro = self._ficheiro(pasta, "relatorio.pdf", idade=100)

            removidos = limpar_exports(pasta, dias=-1, max_ficheiros=-1)

            self.assertEqual(removidos, 0)
            self.assertTrue(ficheiro.exists())

    def test_exportacao_excel_neutraliza_formula_em_observacao(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = exportar_excel_jogos(
                [{"observacao": "=SOMA(A1:A2)", "custo_final": 30}],
                pasta=pasta,
            )
            import pandas as pd
            dados = pd.read_excel(caminho, engine="openpyxl")

            self.assertEqual(dados.loc[0, "observacao"], "'=SOMA(A1:A2)")


if __name__ == "__main__":
    unittest.main()
