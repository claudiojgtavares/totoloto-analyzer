"""Mesma exclusão MySQL GET_LOCK/RELEASE_LOCK usada no orçamento; chave distinta."""
from database.connection import get_connection

CHAVE_PROTOCOLO = "totoloto:controlo-sintetico"


class LockProtocolo:
    def __init__(self, connect=None):
        self.connect = connect or get_connection
        self.con = None
        self.obtido = False
        self.owner = None

    def query(self, sql, params=()):
        cur = None
        try:
            cur = self.con.cursor()
            cur.execute(sql, params)
            row = cur.fetchone()
            return row[0] if row else None
        except Exception:
            self.con.rollback()
            raise
        finally:
            if cur is not None:
                cur.close()

    def __enter__(self):
        self.con = self.connect()
        try:
            # Sem transação aberta durante horas; o lock pertence à sessão, não ao commit.
            self.con.autocommit = True
            self.owner = self.query("SELECT CONNECTION_ID()")
            resposta = self.query("SELECT GET_LOCK(%s, 0)", (CHAVE_PROTOCOLO,))
            if resposta is None:
                raise RuntimeError("Não foi possível obter o lock MySQL do protocolo.")
            self.obtido = resposta == 1
            return self
        except BaseException:
            try:
                self.con.rollback()
            finally:
                self.con.close()
            raise

    def verificar(self):
        # Não usar reconnect=True: uma sessão nova perdeu a propriedade.
        if not self.obtido or self.query("SELECT IS_USED_LOCK(%s)", (CHAVE_PROTOCOLO,)) != self.owner:
            raise RuntimeError("A ligação deixou de ser proprietária do lock do protocolo.")

    def __exit__(self, tipo, exc, tb):
        try:
            if tipo is not None:
                self.con.rollback()
        finally:
            try:
                if self.obtido:
                    self.query("SELECT RELEASE_LOCK(%s)", (CHAVE_PROTOCOLO,))
            finally:
                self.con.close()
