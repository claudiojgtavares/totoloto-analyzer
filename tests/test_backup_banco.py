import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import backup_banco
from config import Config


class BackupBancoTests(unittest.TestCase):
    def _config(self):
        return patch.multiple(
            Config,
            MYSQL_HOST="localhost",
            MYSQL_PORT=3306,
            MYSQL_USER="root",
            MYSQL_PASSWORD="segredo-de-teste",
            MYSQL_DATABASE="totoloto_analyzer",
            MYSQLDUMP_PATH="",
        )

    def test_comando_usa_configuracao_e_password_so_no_ambiente(self):
        with tempfile.TemporaryDirectory() as pasta, self._config(), \
             patch("backup_banco.shutil.which", return_value="mysqldump.exe"), \
             patch("backup_banco.subprocess.run") as executar:
            def simular(comando, **kwargs):
                caminho = next(arg.split("=", 1)[1] for arg in comando if arg.startswith("--result-file="))
                Path(caminho).write_text("-- dump válido\n", encoding="utf-8")
                return SimpleNamespace(returncode=0, stderr="")
            executar.side_effect = simular

            resultado = backup_banco.criar_backup(pasta, datetime(2026, 9, 17, 14, 30, 15, 123456))

            self.assertTrue(Path(resultado).exists())
            comando = executar.call_args.args[0]
            ambiente = executar.call_args.kwargs["env"]
            self.assertIn("--host=localhost", comando)
            self.assertIn("--port=3306", comando)
            self.assertIn("--user=root", comando)
            self.assertIn("totoloto_analyzer", comando)
            self.assertNotIn("--password=segredo-de-teste", comando)
            self.assertEqual(ambiente["MYSQL_PWD"], "segredo-de-teste")
            self.assertIn("20260917_143015_123456.sql", resultado)

    def test_mysql_dump_inexistente_e_reportado(self):
        with self._config(), patch("backup_banco.shutil.which", return_value=None):
            with self.assertRaisesRegex(backup_banco.ErroBackup, "mysqldump não foi encontrado"):
                backup_banco.localizar_mysqldump()

    def test_path_configurado_tem_precedencia_e_falha_clara(self):
        with patch.object(Config, "MYSQLDUMP_PATH", r"C:\nao-existe\mysqldump.exe"), \
             patch("backup_banco.shutil.which", return_value=None):
            with self.assertRaisesRegex(backup_banco.ErroBackup, "MYSQLDUMP_PATH"):
                backup_banco.localizar_mysqldump()

    def test_codigo_de_saida_nao_publica_dump_incompleto(self):
        with tempfile.TemporaryDirectory() as pasta, self._config(), \
             patch("backup_banco.shutil.which", return_value="mysqldump.exe"), \
             patch("backup_banco.subprocess.run", return_value=SimpleNamespace(returncode=2, stderr="falhou")):
            with self.assertRaisesRegex(backup_banco.ErroBackup, "código 2"):
                backup_banco.criar_backup(pasta, datetime(2026, 9, 17, 14, 30, 15))
            self.assertEqual(list(Path(pasta).iterdir()), [])

    def test_dump_vazio_nao_e_considerado_valido(self):
        with tempfile.TemporaryDirectory() as pasta, self._config(), \
             patch("backup_banco.shutil.which", return_value="mysqldump.exe"), \
             patch("backup_banco.subprocess.run") as executar:
            def vazio(comando, **kwargs):
                caminho = next(arg.split("=", 1)[1] for arg in comando if arg.startswith("--result-file="))
                Path(caminho).touch()
                return SimpleNamespace(returncode=0, stderr="")
            executar.side_effect = vazio
            with self.assertRaisesRegex(backup_banco.ErroBackup, "sem produzir"):
                backup_banco.criar_backup(pasta)
            self.assertEqual(list(Path(pasta).iterdir()), [])

    def test_retencao_propria_remove_antigos_e_excedentes(self):
        with tempfile.TemporaryDirectory() as pasta:
            antigo = Path(pasta) / "antigo.sql"
            recente = Path(pasta) / "recente.sql"
            antigo.write_text("x", encoding="utf-8")
            recente.write_text("x", encoding="utf-8")
            os.utime(antigo, (0, 0))
            os.utime(recente, (100, 100))
            removidos = backup_banco.limpar_backups(pasta, dias=1, max_ficheiros=1, agora=100 + 86400)
            self.assertEqual(removidos, 1)
            self.assertTrue(recente.exists())
            self.assertFalse(antigo.exists())


if __name__ == "__main__":
    unittest.main()
