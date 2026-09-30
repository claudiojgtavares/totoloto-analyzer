"""Reinício real dos processos Flask; backend simulado partilhado entre processos."""
from http.cookiejar import CookieJar
import json
import multiprocessing
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import time
import unittest
from urllib.request import build_opener, HTTPCookieProcessor, Request
import uuid

from tests.f04_process_support import GestorLocks, dono, servir_flask


def esperar(condicao, segundos=15):
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        valor = condicao()
        if valor:
            return valor
        time.sleep(.05)
    raise AssertionError("A condição esperada não ocorreu dentro do prazo do teste.")


def parar_processo(processo):
    if processo.is_alive():
        processo.terminate()
    processo.join(5)
    if processo.is_alive():
        processo.kill()
        processo.join(5)
    if processo.is_alive():
        raise AssertionError("O processo Flask de teste não terminou.")


def verificar_reinicio(test, backend):
    """Reusa as rotas HTTP e coordenador de produção, com runner de espera da fixture."""
    contexto = multiprocessing.get_context("spawn")
    chave = "totoloto:test:f04:" + uuid.uuid4().hex
    processos = []
    with TemporaryDirectory(prefix="totoloto-f04-") as temporario:
        controle = Path(temporario)
        pasta = controle / "estados"
        pasta.mkdir()

        def novo_flask():
            receber, enviar = contexto.Pipe(duplex=False)
            processo = contexto.Process(target=servir_flask, args=(enviar, str(pasta), chave, backend))
            processos.append(processo)
            processo.start()
            enviar.close()
            try:
                test.assertTrue(receber.poll(15), "O novo processo Flask não arrancou.")
                info = receber.recv()
            finally:
                receber.close()
            cliente = build_opener(HTTPCookieProcessor(CookieJar()))
            with cliente.open(info["url"] + "/backtesting", timeout=5) as resposta:
                pagina = resposta.read().decode("utf-8")
            token = re.search(r'name="csrf_token" value="([^"]+)"', pagina).group(1)
            return processo, info, cliente, token

        def pedido(cliente, url, dados=None, csrf=None):
            req = Request(url, data=json.dumps(dados).encode() if dados is not None else None,
                          headers={"Content-Type": "application/json", "X-CSRFToken": csrf or ""})
            with cliente.open(req, timeout=5) as resposta:
                return resposta.status, json.loads(resposta.read())

        def iniciar(info, cliente, csrf):
            status, preparado = pedido(cliente, info["url"] + "/backtesting/protocolo/preparar",
                                        {"n_sinteticos": 1, "workers": 1, "quantidade_jogos": 1,
                                         "holdout_inedito": True}, csrf)
            test.assertEqual(status, 200)
            status, job = pedido(cliente, info["url"] + "/backtesting/protocolo/iniciar",
                                {"token": preparado["token"], "confirmar": True}, csrf)
            test.assertEqual(status, 202)
            return job

        try:
            primeiro, info1, cliente1, csrf1 = novo_flask()
            job1 = iniciar(info1, cliente1, csrf1)
            def estado1():
                r = pedido(cliente1, info1["url"] + job1["poll"])[1]
                test.assertIn(r["estado"], ("pendente", "em_execucao"), r)
                return r if r["estado"] == "em_execucao" else None
            esperar(estado1)
            owner = dono(backend, chave)
            test.assertIsNotNone(owner)
            parar_processo(primeiro)  # termina mesmo o processo Flask, não apenas um cliente HTTP
            test.assertIsNotNone(primeiro.exitcode)
            test.assertEqual(dono(backend, chave), owner)

            segundo, info2, cliente2, csrf2 = novo_flask()
            test.assertNotEqual(info1["pid"], info2["pid"])
            test.assertEqual(dono(backend, chave), owner)
            anterior = pedido(cliente2, info2["url"] + job1["poll"])[1]
            test.assertEqual(anterior["estado"], "em_execucao")

            job2 = iniciar(info2, cliente2, csrf2)
            def recusado():
                r = pedido(cliente2, info2["url"] + job2["poll"])[1]
                return r if r["estado"] != "pendente" else None
            r = esperar(recusado)
            test.assertEqual(r["estado"], "recusado")
            test.assertEqual(r["motivo"], "protocolo_ativo")
            test.assertEqual(dono(backend, chave), owner)
            reg2 = json.loads((pasta / f"{job2['id']}.json").read_text(encoding="utf-8"))
            test.assertFalse(reg2["avaliacao_iniciada"])
        finally:
            (controle / "parar").touch()
            for processo in processos:
                if processo.pid is not None:
                    parar_processo(processo)
            ficheiro_jobs = controle / "filhos.txt"
            jobs = ficheiro_jobs.read_text(encoding="ascii").splitlines() if ficheiro_jobs.exists() else []
            # Só se limpam os ficheiros após todos os coordenadores criados pelo teste terminarem.
            esperar(lambda: all((controle / f"terminou-{job}").exists() for job in jobs), segundos=50)
            esperar(lambda: dono(backend, chave) is None)


class ReinicioFlaskTests(unittest.TestCase):
    def test_reinicio_flask_preserva_coordenador_e_recusa_segundo_protocolo(self):
        contexto = multiprocessing.get_context("spawn")
        authkey = os.urandom(16)
        gestor = GestorLocks(address=("127.0.0.1", 0), authkey=authkey, ctx=contexto)
        gestor.start()
        try:
            verificar_reinicio(self, {"tipo": "simulado", "host": gestor.address[0],
                                     "porta": gestor.address[1], "authkey": authkey.hex()})
        finally:
            gestor.shutdown()


if __name__ == "__main__":
    unittest.main()
