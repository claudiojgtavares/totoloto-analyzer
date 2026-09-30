"""Opt-in: F04_MYSQL_TESTS=1. MySQL/MariaDB real, sem escrever em tabelas.

Quando solicitado, indisponibilidade do servidor é ERRO, não skip silencioso.
Cada teste usa chave exclusiva, sem interferir com o protocolo de produção.
"""
from concurrent.futures import ThreadPoolExecutor
import os
import threading
import unittest
from unittest.mock import patch
import uuid

from database import protocolo_lock
from tests.f04_process_support import consulta, ligar_mysql
from tests.test_protocolo_processos import verificar_reinicio


@unittest.skipUnless(os.environ.get("F04_MYSQL_TESTS") == "1",
                     "Integração MySQL opt-in: definir F04_MYSQL_TESTS=1 e MYSQL_*.")
class MySQLRealTests(unittest.TestCase):
    def test_duas_ligacoes_mysql_disputam_get_lock_ao_mesmo_tempo(self):
        chave = "totoloto:test:f04:" + uuid.uuid4().hex
        prontas = threading.Barrier(2, timeout=10)
        tentaram = threading.Barrier(2, timeout=10)

        def conectar():
            con = ligar_mysql()
            try:
                prontas.wait()  # ambas as sessões abertas antes das tentativas GET_LOCK
            except BaseException:
                try:
                    con.rollback()
                finally:
                    con.close()
                raise
            return con

        def disputar():
            try:
                with protocolo_lock.LockProtocolo(connect=conectar) as lock:
                    tentaram.wait()  # quem ganhou mantém o lock até a outra sessão tentar
                    if lock.obtido:
                        lock.verificar()
                    return lock.owner, lock.obtido
            except BaseException:
                prontas.abort()
                tentaram.abort()
                raise

        with patch.object(protocolo_lock, "CHAVE_PROTOCOLO", chave):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futuros = [pool.submit(disputar) for _ in range(2)]
                resultados = [f.result(timeout=20) for f in futuros]
            self.assertNotEqual(resultados[0][0], resultados[1][0])
            self.assertEqual(sorted(obtido for _, obtido in resultados), [False, True])
            con = ligar_mysql()
            try:
                self.assertIsNone(consulta(con, "SELECT IS_USED_LOCK(%s)", (chave,)))
            finally:
                con.close()
            # O lock ficou efetivamente livre depois do fecho das sessões.
            with protocolo_lock.LockProtocolo(connect=ligar_mysql) as novo:
                self.assertTrue(novo.obtido)
                novo.verificar()

    def test_reinicio_flask_mantem_lock_mysql_real_e_recusa_segundo_arranque(self):
        # Falhar cedo se credenciais/servidor indisponíveis; não confundir com teste aprovado.
        con = ligar_mysql()
        con.close()
        verificar_reinicio(self, {"tipo": "mysql"})


if __name__ == "__main__":
    unittest.main()
