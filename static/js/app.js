function formatCVE(valor) {
  const inteiro = Math.round(Number(valor || 0));
  return inteiro.toLocaleString('pt-PT').replace(/,/g, '.') + ' CVE';
}

function atualizarCusto() {
  const qtd = parseInt(document.querySelector('[name="qtd_numeros"]')?.value || '6');
  const joker = document.querySelector('[name="incluir_joker"]')?.checked || false;
  const mapa = {6: 1, 7: 7, 8: 28, 9: 84, 10: 210};
  const apostas = mapa[qtd] || 1;
  const el = document.getElementById('preview-custo');
  const precoAposta = parseFloat(el?.dataset.precoAposta || '30');
  const precoJoker = parseFloat(el?.dataset.precoJoker || '70');
  const custo = apostas * precoAposta + (joker ? precoJoker : 0);
  if (el) el.textContent = formatCVE(custo);
}

function atualizarLimiteBacktesting() {
  const form = document.querySelector('form[data-backtesting]');
  if (!form) return;
  const qtd = parseInt(form.querySelector('[name="qtd_numeros"]')?.value || '6');
  const linhas = {6: 1, 7: 7, 8: 28, 9: 84, 10: 210}[qtd] || 1;
  const limite = Math.min(20, Math.max(1, Math.floor(420 / linhas)));
  const input = form.querySelector('[name="quantidade_jogos"]');
  if (input) {
    input.max = String(limite);
    if (Number(input.value) > limite) input.value = String(limite);
  }
}

function aplicarMascaraDataBR(input) {
  input.addEventListener('input', () => {
    let v = input.value.replace(/\D/g, '').slice(0, 8);
    if (v.length >= 5) v = v.slice(0, 2) + '/' + v.slice(2, 4) + '/' + v.slice(4);
    else if (v.length >= 3) v = v.slice(0, 2) + '/' + v.slice(2);
    input.value = v;
  });
}

document.addEventListener('change', () => {
  atualizarCusto();
  atualizarLimiteBacktesting();
});
document.addEventListener('DOMContentLoaded', () => {
  atualizarCusto();
  atualizarLimiteBacktesting();
  document.querySelectorAll('.date-br').forEach(aplicarMascaraDataBR);
  configurarProtocolo();
});

function configurarProtocolo() {
  const form = document.getElementById('protocolo-form');
  if (!form) return;
  const parametros = document.querySelector('form[data-backtesting]');
  const saida = document.getElementById('protocolo-estado');
  const confirmar = document.getElementById('protocolo-confirmar');
  let token = null;
  let timer = null;
  const mostrar = texto => { saida.textContent = texto; };
  const invalidar = () => { token = null; confirmar.hidden = true; };
  [form, parametros].forEach(f => f.addEventListener('input', invalidar));
  async function post(url, data) {
    const resposta = await fetch(url, {method: 'POST', body: data});
    const json = await resposta.json();
    if (!resposta.ok) throw new Error(json.mensagem || 'Não foi possível concluir o pedido.');
    return json;
  }
  async function acompanhar(url) {
    clearTimeout(timer);
    try {
      const resposta = await fetch(url);
      const estado = await resposta.json();
      if (!resposta.ok) throw new Error(estado.mensagem || 'Estado indisponível.');
      let texto = `FATO MATEMÁTICO — ${estado.estado}\nProtocolo: ${estado.id}\n` +
        `Simulações completas: ${estado.simulacoes_concluidas}/${estado.n_sinteticos}\n` +
        `Tempo: ${estado.tempo_decorrido} s / prazo ${estado.timeout_global} s\n`;
      if (estado.progresso) texto += `Concursos por avaliação (−1 = real): ${JSON.stringify(estado.progresso)}\n`;
      if (estado.mensagem) texto += estado.mensagem + '\n';
      if (estado.motivo) texto += `Motivo: ${estado.motivo}\n`;
      if (estado.erro_id) texto += `Consulte o registo com o ID ${estado.erro_id}.\n`;
      if (estado.estado === 'completo') {
        texto += `PADRÃO HISTÓRICO — diferença observada: ${estado.metrica_observada}\n` +
          `p-valor empírico (cauda superior): ${estado.p_valor_empirico}\n` +
          `Intervalo nulo descritivo: ${estado.intervalo_nulo.join(' a ')}\nNão garante desempenho futuro.`;
      } else texto += 'Sem p-valor final.';
      mostrar(texto);
      if (['pendente', 'em_execucao'].includes(estado.estado)) timer = setTimeout(() => acompanhar(url), 2000);
    } catch (erro) {
      mostrar(`Estado indeterminado: ${erro.message} A execução não foi declarada completa. Nova consulta em 5 segundos.`);
      timer = setTimeout(() => acompanhar(url), 5000);
    }
  }
  form.addEventListener('submit', async evento => {
    evento.preventDefault(); invalidar();
    const data = new FormData(form);
    const gerais = new FormData(parametros);
    ['estrategia', 'quantidade_jogos', 'qtd_numeros', 'incluir_joker', 'limite_concursos'].forEach(k => {
      if (gerais.has(k)) data.set(k, gerais.get(k));
    });
    try {
      const resposta = await post(form.action, data);
      token = resposta.token; confirmar.hidden = false;
      mostrar(`${resposta.mensagem}\nÂmbito: ${resposta.ambito}; corte: ${resposta.corte}; alvos: ${resposta.alvos}.\n` +
        `Duração estimada: ${resposta.estimativa.inferior_segundos}–${resposta.estimativa.superior_segundos} s. Prazo: ${resposta.timeout_global} s.\n` +
        resposta.estimativa.aviso);
    } catch (erro) { mostrar(erro.message); }
  });
  confirmar.addEventListener('click', async () => {
    if (!token) return;
    confirmar.disabled = true;
    try {
      const data = new FormData();
      data.set('token', token); data.set('confirmar', '1');
      data.set('csrf_token', form.querySelector('[name="csrf_token"]').value);
      const resposta = await post('/backtesting/protocolo/iniciar', data);
      invalidar(); localStorage.setItem('totoloto-protocolo-poll', resposta.poll);
      acompanhar(resposta.poll);
    } catch (erro) { mostrar(erro.message); }
    finally { confirmar.disabled = false; }
  });
  const anterior = localStorage.getItem('totoloto-protocolo-poll');
  if (anterior && /^\/backtesting\/protocolo\/[a-f0-9]{32}$/.test(anterior)) acompanhar(anterior);
}
