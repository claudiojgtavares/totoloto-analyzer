"""Regressões F-04; núcleo real e simulações pequenas, MySQL simulado explícito."""
from concurrent.futures import Future
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch, Mock
import uuid

from database.protocolo_lock import LockProtocolo, CHAVE_PROTOCOLO
from modules import backtesting as motor
from modules import coordenador_backtesting as coord
from modules.protocolo_backtesting import (
    ErroProtocolo, corte_holdout, executar_avaliacao, gerar_historico_sintetico,
    novo_registo, preparar_protocolo, resultado_completo, seed_simulacao, validar_prazo,
)


def historico(n=20):
    modelo = [{"concurso": str(i + 1), "data_sorteio": None} for i in range(n)]
    return gerar_historico_sintetico(modelo, 71)


def plano(**kwargs):
    opcoes = dict(quantidade_jogos=1, limite_concursos=500, n_sinteticos=3,
                  workers=1, holdout_inedito=True)
    opcoes.update(kwargs)
    return preparar_protocolo(historico(), **opcoes)


class ServidorMysqlFalso:
    """Simula SEMÂNTICA de sessões GET_LOCK; não substitui integração MySQL."""
    def __init__(self):
        self.owner = None
        self.mutex = threading.Lock()
        self.conexoes = []

    def connect(self):
        with self.mutex:
            con = ConexaoFalsa(self, len(self.conexoes) + 1)
            self.conexoes.append(con)
            return con


class ConexaoFalsa:
    def __init__(self, servidor, numero):
        self.servidor, self.numero = servidor, numero
        self.fechada = False
        self.rollbacks = 0
        self.cursors = []

    def cursor(self):
        cur = CursorFalso(self)
        self.cursors.append(cur)
        return cur

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        with self.servidor.mutex:
            if self.servidor.owner == self.numero:
                self.servidor.owner = None
            self.fechada = True


class CursorFalso:
    def __init__(self, con):
        self.con = con
        self.fechado = False

    def execute(self, sql, params):
        servidor = self.con.servidor
        with servidor.mutex:
            if "CONNECTION_ID" in sql:
                self.valor = self.con.numero
            elif "GET_LOCK" in sql:
                assert params == (CHAVE_PROTOCOLO,)
                self.valor = int(servidor.owner in (None, self.con.numero))
                if self.valor:
                    servidor.owner = self.con.numero
            elif "IS_USED_LOCK" in sql:
                self.valor = servidor.owner
            elif "RELEASE_LOCK" in sql:
                self.valor = int(servidor.owner == self.con.numero)
                if self.valor:
                    servidor.owner = None
            else:
                raise AssertionError(sql)

    def fetchone(self):
        return (self.valor,)

    def close(self):
        self.fechado = True


class PoolImediato:
    """Futuros determinísticos para testar supervisão/prazos sem esperar horas."""
    def __init__(self, **kwargs):
        self.terminado = False

    def submit(self, func, p, indice):
        futuro = Future()
        futuro.set_result({"incompleto": False, "concursos_testados": p.alvos,
                           "concursos_ignorados": 0, "baseline_repeticoes": 20,
                           "diferencas_emparelhadas": [0.2 if indice == -1 else indice / 10] * p.alvos})
        return futuro

    def terminate_workers(self):
        self.terminado = True

    def shutdown(self, wait=True):
        pass


class ProtocoloEstatisticoTests(unittest.TestCase):
    def test_seed_reproduz_historico_e_nao_depende_da_ordem_dos_workers(self):
        h = historico()
        a = gerar_historico_sintetico(h, seed_simulacao(7, 2))
        gerar_historico_sintetico(h, seed_simulacao(7, 1))
        self.assertEqual(a, gerar_historico_sintetico(h, seed_simulacao(7, 2)))
        self.assertNotEqual(a, gerar_historico_sintetico(h, seed_simulacao(8, 2)))

    def test_sinteticos_validos_6_45_sem_reposicao_mesmo_comprimento(self):
        h = historico(300)
        sim = gerar_historico_sintetico(h, 123)
        self.assertEqual(len(sim), len(h))
        for original, s in zip(h, sim):
            nums = [s[f"n{i}"] for i in range(1, 7)]
            self.assertEqual(len(set(nums)), 6)
            self.assertTrue(all(1 <= n <= 45 for n in nums))
            self.assertEqual(s["concurso"], original["concurso"])
            self.assertEqual(s["data_sorteio"], original["data_sorteio"])

    def test_corte_80_20_arredonda_holdout_para_cima(self):
        self.assertEqual(corte_holdout(300), 240)
        self.assertEqual(corte_holdout(301), 240)
        p = plano()
        self.assertEqual((p.corte, p.inicio_alvos, p.alvos), (16, 16, 4))

    def test_configuracao_e_historico_congelados_antes_de_avaliar(self):
        h = historico()
        p = preparar_protocolo(h, holdout_inedito=True)
        with self.assertRaises(FrozenInstanceError):
            p.seed = 44
        h[0]["n1"] = 99
        p.historico[0]["n1"] = 88
        p.configuracao["estrategia"] = "Mista"
        self.assertNotIn(p.historico[0]["n1"], (88, 99))
        self.assertEqual(p.configuracao["estrategia"], "Equilibrada")

    def test_holdout_exige_reserva_e_limite_cobre_todos_os_alvos(self):
        with self.assertRaisesRegex(ErroProtocolo, "Confirme"):
            plano(holdout_inedito=False)
        with self.assertRaisesRegex(ErroProtocolo, "4 concursos completos"):
            plano(limite_concursos=3)
        with self.assertRaisesRegex(ErroProtocolo, "insuficiente"):
            preparar_protocolo([], holdout_inedito=True)

    def test_walk_forward_holdout_so_acede_a_prefixos_sem_futuro(self):
        p = plano()
        prefixos = []
        original = motor.calcular_estatisticas_de_sorteios
        def observar(h):
            prefixos.append([s["concurso"] for s in h])
            return original(h)
        with patch.object(motor, "calcular_estatisticas_de_sorteios", side_effect=observar):
            r = executar_avaliacao(p)
        self.assertTrue(resultado_completo(r, p))
        self.assertEqual(prefixos, [[str(i) for i in range(1, alvo)] for alvo in range(17, 21)])

    def test_real_sintetico_usam_mesmo_nucleo_estrategia_baselines_e_limites(self):
        p = plano(estrategia="Mista", qtd_numeros=7)
        with patch("modules.protocolo_backtesting.executar_backtesting", wraps=motor.executar_backtesting) as core:
            real = executar_avaliacao(p)
            nulo = executar_avaliacao(p, 0)
        self.assertEqual(core.call_count, 2)
        self.assertEqual(core.call_args_list[0].kwargs, core.call_args_list[1].kwargs)
        for r in (real, nulo):
            self.assertTrue(resultado_completo(r, p))
            self.assertEqual(r["baseline_repeticoes"], 20)
            self.assertEqual(r["linhas_testadas"], 4 * 7)
            self.assertEqual(r["baseline"]["linhas"], 4 * 7)
        self.assertEqual(motor.MAX_LINHAS_POR_CONCURSO, 420)
        with self.assertRaisesRegex(ErroProtocolo, "420"):
            plano(qtd_numeros=10, quantidade_jogos=3)

    def test_preserva_diferencas_sem_arredondamento_nem_corte_30(self):
        p = preparar_protocolo(historico(165), quantidade_jogos=1, limite_concursos=33,
                              n_sinteticos=1, holdout_inedito=True)
        r = executar_avaliacao(p)
        self.assertEqual(len(r["diferencas_emparelhadas"]), 33)
        self.assertEqual(len(r["detalhes"]), 30)

    def test_comparacao_chama_funcao_existente_e_intervalo_nulo(self):
        with patch.object(motor, "controlo_sintetico", wraps=motor.controlo_sintetico) as comparar:
            r = motor.comparar_historicos_nulos([.2, .4], [-.5, 0, .5])
        comparar.assert_called_once_with([.2, .4], [-.5, 0, .5])
        self.assertEqual(r["p_valor_empirico"], .5)
        self.assertEqual(r["intervalo_nulo"], [-.475, .475])
        self.assertEqual(r["rotulo"], "FATO MATEMÁTICO")

    def test_erros_e_timeout_do_nucleo_nunca_sao_completos(self):
        p = plano()
        with patch.object(motor, "gerar_jogos_estatisticos", side_effect=ValueError("fixture")):
            r = executar_avaliacao(p)
        self.assertTrue(r["incompleto"])
        self.assertFalse(resultado_completo(r, p))
        r = motor.executar_backtesting(historico(), timeout_segundos=0)
        self.assertTrue(r["incompleto"])

    def test_timeout_default_apenas_holdout_exploratorio_exige_prazo(self):
        self.assertEqual(plano().timeout_global, 7200)
        with self.assertRaisesRegex(ErroProtocolo, "prazo explícito"):
            plano(ambito="exploratorio")

    def test_bloqueia_estimativa_superior_ao_prazo_antes_de_criar_processo(self):
        p = preparar_protocolo(historico(300), quantidade_jogos=20, limite_concursos=300,
                              ambito="exploratorio", workers=1, timeout_global=7200)
        with patch.object(coord.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(ErroProtocolo, "Duração estimada:.*Prazo configurado: 7200.*Aumente"):
                coord.iniciar(p)
        spawn.assert_not_called()
        self.assertGreater(json.loads(p.estimativa_json)["superior_segundos"], 14400)
        validar_prazo(replace(p, timeout_global=30000))


class CoordenadorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pasta = Path(self.tmp.name)
        self.servidor = ServidorMysqlFalso()
        self.lock = lambda: LockProtocolo(self.servidor.connect)

    def registo(self, p=None):
        p = p or plano()
        reg = novo_registo(p, uuid.uuid4().hex)
        coord.guardar(reg, self.pasta)
        return reg

    def test_concorrencia_dois_coordenadores_mysql_impede_segundo(self):
        entrou, sair = threading.Event(), threading.Event()
        def runner(p, reg, lock, pasta):
            entrou.set()
            if not sair.wait(10):
                raise RuntimeError("fixture timeout")
            coord.guardar(coord.interromper(reg, "fim_fixture"), pasta)
        a, b = self.registo(), self.registo()
        primeiro = threading.Thread(target=coord.coordenar, args=(a["id"], self.pasta, self.lock, runner))
        primeiro.start()
        try:
            self.assertTrue(entrou.wait(5))
            segundo = Mock()
            coord.coordenar(b["id"], self.pasta, self.lock, segundo)
            segundo.assert_not_called()
            self.assertEqual(coord.ler(b["id"], self.pasta)["motivo"], "protocolo_ativo")
            self.assertIsNotNone(self.servidor.owner)
        finally:
            sair.set()
            primeiro.join(10)
        self.assertIsNone(self.servidor.owner)

    def test_reconciliacao_orfao_sem_lock_interrompe_e_nao_publica_p(self):
        reg = self.registo()
        reg.update(estado="em_execucao", proprietario_mysql=999, avaliacao_iniciada=True)
        coord.guardar(reg, self.pasta)
        with self.lock() as lock:
            coord.reconciliar(lock, self.pasta)
        atual = coord.ler(reg["id"], self.pasta)
        self.assertEqual(atual["estado"], "incompleto")
        self.assertEqual(atual["motivo"], "interrompido_sem_proprietario_ativo")
        self.assertIsNone(atual["p_valor_empirico"])

    def test_estado_em_ficheiro_nao_substitui_lock(self):
        self.registo()
        with self.lock() as lock:
            self.assertTrue(lock.obtido)
            with self.lock() as concorrente:
                self.assertFalse(concorrente.obtido)
                with self.assertRaises(RuntimeError):
                    coord.reconciliar(concorrente, self.pasta)

    def test_holdout_consumido_bloqueia_seed_ou_parametros_novos(self):
        reg = self.registo()
        reg.update(avaliacao_iniciada=True, estado="incompleto")
        coord.guardar(reg, self.pasta)
        for p in (plano(seed=999), plano(estrategia="Mista")):
            with self.assertRaisesRegex(ErroProtocolo, "já usado"):
                coord.verificar_holdout_inedito(p, uuid.uuid4().hex, self.pasta)

    def test_exploracao_que_expoe_holdout_impede_confirmacao(self):
        reg = self.registo(plano(ambito="exploratorio", timeout_global=7200))
        reg.update(avaliacao_iniciada=True, estado="completo")
        coord.guardar(reg, self.pasta)
        with self.assertRaises(ErroProtocolo):
            coord.verificar_holdout_inedito(plano(), uuid.uuid4().hex, self.pasta)

    def test_timeout_global_a_meio_persiste_parcial_sem_p(self):
        p = replace(plano(n_sinteticos=20), timeout_global=1)
        reg = self.registo(p)
        reg["estado"] = "em_execucao"
        tempo = [0]
        def clock():
            tempo[0] += .15
            return tempo[0]
        with self.lock() as lock:
            coord.executar_pool(p, reg, lock, self.pasta, clock=clock, pool_factory=PoolImediato)
        r = coord.ler(reg["id"], self.pasta)
        self.assertEqual(r["estado"], "incompleto")
        self.assertEqual(r["motivo"], "timeout_global")
        self.assertGreaterEqual(r["tempo_decorrido"], 1)
        self.assertGreater(r["simulacoes_concluidas"], 0)
        self.assertLess(r["simulacoes_concluidas"], 20)
        self.assertIsNone(r["p_valor_empirico"])
        self.assertIsNone(r["intervalo_nulo"])

    def test_completo_persiste_seeds_configuracao_e_todas_diferencas(self):
        p = plano()
        reg = self.registo(p)
        with self.lock() as lock:
            coord.executar_pool(p, reg, lock, self.pasta, pool_factory=PoolImediato)
        r = coord.ler(reg["id"], self.pasta)
        self.assertEqual(r["estado"], "completo")
        self.assertEqual(r["simulacoes_concluidas"], 3)
        self.assertEqual(r["p_valor_empirico"], .5)
        self.assertEqual(r["configuracao_usada"], p.configuracao)
        self.assertEqual(len(r["seeds_sinteticas"]), 3)
        self.assertEqual(len(r["nulos"]["0"]["diferencas_emparelhadas"]), p.alvos)
        self.assertEqual(r["rotulo_desempenho"], "PADRÃO HISTÓRICO")

    def test_perda_lock_interrompe_sem_reconectar_ou_publicar(self):
        p, reg = plano(), self.registo()
        with self.lock() as lock:
            self.servidor.owner = None
            with self.assertRaises(RuntimeError):
                coord.executar_pool(p, reg, lock, self.pasta, pool_factory=PoolImediato)
        r = coord.ler(reg["id"], self.pasta)
        self.assertEqual(r["motivo"], "perda_do_lock_mysql")
        self.assertIsNone(r["p_valor_empirico"])
        self.assertEqual(len(self.servidor.conexoes), 1)

    def test_mysql_rollback_e_finally_em_excecao(self):
        with self.assertRaisesRegex(ValueError, "fixture"):
            with self.lock() as lock:
                raise ValueError("fixture")
        con = self.servidor.conexoes[0]
        self.assertTrue(con.fechada)
        self.assertEqual(con.rollbacks, 1)
        self.assertTrue(all(cur.fechado for cur in con.cursors))
        self.assertIsNone(self.servidor.owner)

    def test_publico_nao_expoe_resultados_intermedios_do_holdout(self):
        reg = self.registo()
        reg.update(estado="em_execucao", resultado_real={"segredo": 42}, metrica_observada=.8)
        publico = coord.estado_publico(reg)
        self.assertNotIn("resultado_real", publico)
        self.assertIsNone(publico["metrica_observada"])
        self.assertIsNone(publico["p_valor_empirico"])


class ProtocoloRotasTests(unittest.TestCase):
    def setUp(self):
        from app import app
        self.app = app
        app.config.update(TESTING=True)
        self.client = app.test_client()

    @patch("app.fetch_all", return_value=historico())
    @patch("app.get_configuracao", return_value={"preco_aposta_simples": 30, "preco_joker": 70})
    def test_preparacao_nao_avalia_e_token_congela_configuracao(self, *_):
        with patch("app.executar_backtesting") as motor_mock:
            resposta = self.client.post("/backtesting/protocolo/preparar", data={"holdout_inedito": "1", "n_sinteticos": "3"})
            self.assertEqual(resposta.status_code, 200)
            motor_mock.assert_not_called()
        with patch("app.iniciar_protocolo", return_value="a" * 32) as iniciar:
            r = self.client.post("/backtesting/protocolo/iniciar", data={"token": resposta.json["token"],
                                 "confirmar": "1", "estrategia": "Mista", "seed": "999"})
            self.assertEqual(r.status_code, 202)
            self.assertEqual(iniciar.call_args.args[0].seed, 2026)
            self.assertEqual(iniciar.call_args.args[0].configuracao["estrategia"], "Equilibrada")

    @patch("app.fetch_all", return_value=historico(300))
    @patch("app.get_configuracao", return_value={})
    def test_http_bloqueia_prazo_e_mostra_estimativa(self, *_):
        r = self.client.post("/backtesting/protocolo/preparar", data={"ambito": "exploratorio",
            "timeout_global": "7200", "limite_concursos": "300", "workers": "1", "quantidade_jogos": "20"})
        self.assertEqual(r.status_code, 422)
        self.assertIn("Duração estimada", r.json["mensagem"])
        self.assertIn("Prazo configurado: 7200", r.json["mensagem"])
        self.assertNotIn("token", r.json)

    @patch("app.fetch_all", return_value=[])
    @patch("app.get_configuracao", return_value={})
    def test_get_nao_expoe_holdout_e_post_normal_so_usa_desenvolvimento(self, *_):
        with patch("app.executar_backtesting") as m:
            self.assertEqual(self.client.get("/backtesting").status_code, 200)
            m.assert_not_called()
        with patch("app.fetch_all", side_effect=[[], historico()]), patch("app.executar_backtesting", return_value=motor.resumo_backtesting_demo()) as m:
            self.client.post("/backtesting", data={"limite_concursos": 50})
            self.assertEqual(len(m.call_args.args[0]), 16)

    def test_token_adulterado_e_id_invalido_rejeitados(self):
        self.assertEqual(self.client.post("/backtesting/protocolo/iniciar", data={"token": "falso", "confirmar": "1"}).status_code, 422)
        self.assertEqual(self.client.get("/backtesting/protocolo/invalido").status_code, 404)


if __name__ == "__main__":
    unittest.main()
