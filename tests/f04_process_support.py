"""Fixtures F-04: processos Flask reais e lock simulado ou MySQL real.

Só usado pelos testes. Não altera configuração, dados ou chave de produção.
O runner mantém o coordenador vivo sem executar simulações estatísticas longas.
"""
import argparse
from contextlib import ExitStack
import json
from multiprocessing.managers import BaseManager
import os
from pathlib import Path
import threading
import time
from unittest.mock import patch


class ServidorLocks:
    def __init__(self):
        self.mutex = threading.Lock()
        self.sequencia = 0
        self.locks = {}

    def abrir(self):
        with self.mutex:
            self.sequencia += 1
            return self.sequencia

    def executar(self, sessao, sql, params):
        with self.mutex:
            if "CONNECTION_ID" in sql:
                return sessao
            chave = params[0]
            if "GET_LOCK" in sql:
                if self.locks.get(chave) not in (None, sessao):
                    return 0
                self.locks[chave] = sessao
                return 1
            if "IS_USED_LOCK" in sql:
                return self.locks.get(chave)
            if "RELEASE_LOCK" in sql:
                if self.locks.get(chave) != sessao:
                    return 0
                del self.locks[chave]
                return 1
            raise AssertionError("SQL inesperado na fixture")

    def fechar(self, sessao):
        with self.mutex:
            for chave in list(self.locks):
                if self.locks[chave] == sessao:
                    del self.locks[chave]


_SERVIDOR = ServidorLocks()


def servidor_partilhado():
    return _SERVIDOR


class GestorLocks(BaseManager):
    pass


GestorLocks.register("servidor", callable=servidor_partilhado)


class LigacaoSimulada:
    def __init__(self, servidor):
        self.servidor = servidor
        self.sessao = servidor.abrir()
        self.autocommit = True

    def cursor(self):
        return CursorSimulado(self)

    def rollback(self):
        pass

    def close(self):
        self.servidor.fechar(self.sessao)


class CursorSimulado:
    def __init__(self, con):
        self.con = con

    def execute(self, sql, params=()):
        self.valor = self.con.servidor.executar(self.con.sessao, sql, params)

    def fetchone(self):
        return (self.valor,)

    def close(self):
        pass


def ligar_mysql():
    """Duas sessões reais; credenciais apenas do ambiente, sem selecionar schema."""
    import mysql.connector
    from config import Config
    return mysql.connector.connect(
        host=Config.MYSQL_HOST, port=Config.MYSQL_PORT, user=Config.MYSQL_USER,
        password=Config.MYSQL_PASSWORD, connection_timeout=3,
        read_timeout=5, write_timeout=5, autocommit=True)


def ligar(backend):
    if backend["tipo"] == "mysql":
        return ligar_mysql()
    gestor = GestorLocks(address=(backend["host"], backend["porta"]),
                         authkey=bytes.fromhex(backend["authkey"]))
    gestor.connect()
    con = LigacaoSimulada(gestor.servidor())
    con.gestor = gestor
    return con


def consulta(con, sql, params=()):
    cur = None
    try:
        cur = con.cursor()
        cur.execute(sql, params)
        return cur.fetchone()[0]
    except BaseException:
        con.rollback()
        raise
    finally:
        if cur is not None:
            cur.close()


def dono(backend, chave):
    con = ligar(backend)
    try:
        return consulta(con, "SELECT IS_USED_LOCK(%s)", (chave,))
    finally:
        con.close()


def plano_fixture():
    from modules.protocolo_backtesting import gerar_historico_sintetico, preparar_protocolo
    modelo = [{"concurso": str(i + 1), "data_sorteio": None} for i in range(20)]
    return preparar_protocolo(gerar_historico_sintetico(modelo, 71), quantidade_jogos=1,
                              n_sinteticos=1, workers=1, holdout_inedito=True)


def servir_flask(canal, pasta, chave, backend):
    """Flask HTTP real; adapta só a fixture do subprocesso, dados e pasta de testes."""
    import app as web
    from database import protocolo_lock
    from modules import coordenador_backtesting as coord
    from werkzeug.serving import make_server, WSGIRequestHandler

    class PedidosDeTeste(WSGIRequestHandler):
        def log_request(self, code="-", size="-"):
            pass  # Evita ruído de polling na saída unittest; erros continuam visíveis.

    plano = plano_fixture()
    popen_real = coord.subprocess.Popen

    def arrancar_fixture(args, **kwargs):
        args = list(args)
        assert args[1:3] == ["-m", "modules.coordenador_backtesting"]
        args[2] = "tests.f04_process_support"
        args += ["--chave", chave, "--backend", json.dumps(backend)]
        processo = popen_real(args, **kwargs)
        # O launcher .venv no Windows pode ter PID diferente do intérprete.
        # O ID do protocolo identifica inequivocamente a fixture a aguardar.
        with (Path(pasta).parent / "filhos.txt").open("a", encoding="ascii") as f:
            f.write(args[args.index("--job") + 1] + "\n")
        return processo

    with ExitStack() as stack:
        stack.enter_context(patch.object(protocolo_lock, "CHAVE_PROTOCOLO", chave))
        stack.enter_context(patch.object(protocolo_lock, "get_connection", lambda: ligar(backend)))
        stack.enter_context(patch.object(coord.subprocess, "Popen", arrancar_fixture))
        stack.enter_context(patch.object(web, "iniciar_protocolo", lambda p: coord.iniciar(p, pasta)))
        stack.enter_context(patch.object(web, "consultar_protocolo", lambda i: coord.consultar(i, pasta)))
        stack.enter_context(patch.object(web, "fetch_all", return_value=plano.historico))
        stack.enter_context(patch.object(web, "get_configuracao", return_value={}))
        # CSRF continua ativo; o cliente obtém o token da página como o navegador.
        web.app.config.update(TESTING=False)
        servidor = make_server("127.0.0.1", 0, web.app, request_handler=PedidosDeTeste)
        try:
            canal.send({"url": f"http://127.0.0.1:{servidor.server_port}", "pid": os.getpid()})
            canal.close()
            servidor.serve_forever()
        finally:
            servidor.server_close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    parser.add_argument("--pasta", required=True)
    parser.add_argument("--chave", required=True)
    parser.add_argument("--backend", required=True)
    args = parser.parse_args()
    from database import protocolo_lock
    from modules import coordenador_backtesting as coord
    backend = json.loads(args.backend)
    controle = Path(args.pasta).parent

    def manter_vivo(plano, reg, lock, pasta):
        limite = time.monotonic() + 45
        while not (controle / "parar").exists() and time.monotonic() < limite:
            lock.verificar()
            time.sleep(.05)
        coord.guardar(coord.interromper(reg, "fim_fixture_de_integracao"), pasta)

    try:
        with patch.object(protocolo_lock, "CHAVE_PROTOCOLO", args.chave), \
                patch.object(protocolo_lock, "get_connection", lambda: ligar(backend)):
            coord.coordenar(args.job, args.pasta, runner=manter_vivo)
    finally:
        (controle / f"terminou-{args.job}").touch()


if __name__ == "__main__":
    main()
