# Auditoria técnica — Totoloto Analyzer

**Data:** 17/09/2026  
**Âmbito:** app.py, config.py, criar_banco.py, database/, modules/, templates/, static/, tests/, configuração e artefactos.  
**Estado desta fase:** diagnóstico e propostas apenas. Não foi alterada qualquer regra matemática, estatística ou rota funcional.

## Resumo executivo

O motor do Totoloto está bem separado nas partes sensíveis: uma múltipla é expandida em linhas simples oficiais, a avaliação conta prémios por linha e o backtesting é walk-forward com baseline uniforme. Não encontrei motivo para alterar modules/totoloto.py, score.py ou filtros.py nesta fase. Os 13 testes existentes passam.

Os problemas prioritários estão na camada de integração, não no motor:

1. O orçamento semanal limita cada pedido isolado; várias gerações podem excedê-lo.
2. Ligações/cursors MySQL podem ficar abertos em exceções, e há escritas não atómicas com recálculo de estatísticas.
3. O backtesting pesado bloqueia o pedido Flask sem progresso, cancelamento ou timeout.
4. Importadores são a zona com menos cobertura; .xls é anunciado, mas xlrd não está instalado.
5. A configuração local ainda tem riscos: debug ativo, chave de sessão previsível, sem CSRF, uploads pouco isolados e sem Git/.gitignore.

Toda melhoria analítica deve ter um rótulo explícito:

- **FATO MATEMÁTICO:** probabilidades, cobertura, garantias condicionais, testes e respetivos limites.
- **PADRÃO HISTÓRICO:** medida calculada a partir dos concursos carregados.
- **HEURÍSTICA:** regra de seleção, nunca evidência de que a próxima combinação tenha maior probabilidade.

A separação segue a secção 51 de Lotaria_Analyzer_Tecnicas_de_Lotaria.md.

## Método e evidência

Foi revisto todo o código Python, HTML, CSS e JavaScript, as consultas SQL, esquema MySQL, uploads, exportações e testes. O grafo existente confirma que app.py é o hub entre Flask, MySQL, importação, Joker, geração, relatórios e backtesting; é o ponto de maior acoplamento.

| Verificação | Resultado |
|---|---|
| python -m unittest discover -s tests -v | 13 testes passaram em 0,325 s |
| python -m compileall -q app.py config.py criar_banco.py database modules tests | passou |
| python -m pip check | sem dependências quebradas |
| parse_decimal_br("1.200") | devolve 1.2; defeito confirmado |
| Estatistica Totoloto.xlsx / .pdf | ambos lidos como 45 registos, percentagens 5,71–20,95 |
| PDF Joker em uploads/ | parser extrai dois registos; não serve de cobertura representativa |
| Dados locais, só leitura | 0 sorteios, 0 Joker e 45 apostas geradas |
| Pesquisa a NumPy nos fontes da aplicação | nenhuma importação/uso direto |
| Git | não existe diretoria .git |

Os tempos comunicados para 300 concursos — 62,8 s com 6 números/20 bilhetes e 30,9 s com 10 números/2 bilhetes — são coerentes com o fluxo atual. Para cada concurso-alvo, o programa recalcula o histórico acumulado, gera candidatos e executa 20 baselines.

## Validação dos pontos indicados

| Ponto | Resultado |
|---|---|
| Backtesting síncrono/lento | Confirmado em app.py, backtesting.py e gerador.py |
| Ligações MySQL sem finally | Confirmado em fetch_all, rotas de escrita e importadores |
| Sem testes de importação | Confirmado: tests/ só cobre motor, templates e GETs |
| Dependências soltas / NumPy | Confirmado: sem versões e sem uso direto de NumPy |
| Imports Joker a meio do módulo | Confirmado nas linhas 276–281 de modules/joker.py |
| Decimal PT | Confirmado e atingível por Definições e POST à Banca |
| Sem Git/.gitignore | Confirmado |

# Crítico

## C-01 — O orçamento semanal não é realmente semanal

**Local:** rota gerar_jogos em app.py.

A validação compara custo_unitario × quantidade apenas com orcamento_semanal no pedido atual. Não consulta gerações já guardadas. Dois ou mais pedidos podem cada um atingir o teto e, juntos, ultrapassar o orçamento. Pedidos concorrentes agravam a situação.

**Impacto:** a interface afirma respeitar o orçamento semanal, mas a garantia não existe.

**Correção proposta:** numa transação, somar geracoes_semanais.custo_total da semana definida, reservar/verificar o novo custo e inserir apenas se gasto_existente + custo_novo não exceder o orçamento. Mostrar gasto da semana, disponível e custo desta geração.

**Decisão necessária:** definir “semana”: segunda–domingo local, semana ISO ou concurso. Recomenda-se semana ISO local, apresentada na interface. Criar teste que submete duas gerações e prova que a segunda é ajustada ou recusada.

## C-02 — Quantidade Joker sem limite no servidor

**Local:** ação gerar da rota Joker e gerar_combinacoes_joker.

O HTML limita a 30, mas o servidor aceita qualquer inteiro. Um POST direto muito grande faz o ciclo tentar até quantidade × 500 vezes e pode imobilizar Flask.

**Correção proposta:** validar no servidor 1 <= quantidade <= 30 e validar a estratégia contra ESTRATEGIAS_JOKER. Criar teste unitário e de rota.

## C-03 — Importação mistura fontes estatísticas e permite sucesso parcial

**Local:** importação de estatísticas, importação Joker e tabelas estatisticas_numeros/sorteios.

A importação agregada escreve na mesma tabela que o recálculo de sorteios. É útil para visualização, mas não equivale a histórico bruto; o próximo recálculo pode substituir o importado. A documentação explica a diferença, mas a base não guarda proveniência.

CSV/Excel de estatística podem ser aceites com menos de 45 números; o parser PDF exige 45. O importador Joker ignora erros de algumas linhas se pelo menos uma linha for válida, sem relatório ao utilizador.

**Correção proposta:**

- sorteios deve ser a única fonte de estatísticas calculadas e de backtesting;
- importação agregada deve guardar lote, fonte, hash/nome, aceites, rejeitados e avisos;
- uma substituição completa deve exigir 45 números únicos; importação parcial só deve existir como pré-visualização marcada;
- escrita do lote e recálculo devem ser transacionais, com rollback.

# Robustez

## R-01 — Fecho de ligação/cursor não é garantido

**Locais:** fetch_all/fetch_one, importar_estatistica, cadastrar_sorteio, gerar_jogos, joker, controle_banca, configuracoes, criar_banco.py, estatistica.py, importador.py e joker.py.

O padrão atual fecha cursor/ligação só depois de execute e fetchall. Se uma chamada lançar exceção, o close não é atingido. O problema existe em leitura e escrita.

**Correção proposta:** helper em database/connection.py para gerir ligação e cursor. Deve abrir recursos, fazer rollback na exceção de escrita, fechar sempre em finally e só fazer commit no fim da unidade lógica. Aplicar primeiro a fetch_all/fetch_one e depois uma rota de cada vez. Testar com cursor falso que falha em execute e confirmar rollback/close.

## R-02 — Escrita e recálculo não são atómicos; risco de corrida

**Local:** registo de sorteio/Joker e recalcular_estatisticas/recalcular_estatisticas_joker.

As rotas fazem commit do resultado e só depois recalculam. Se o recálculo falhar, o resultado fica guardado e as estatísticas ficam desatualizadas. Em pedidos simultâneos, dois recálculos podem ler visões diferentes, e o último a escrever pode gravar uma visão antiga.

**Correção proposta:** uma transação curta por registo/importação: insert/upsert, recálculo e commit no fim. Serializar recálculos com GET_LOCK MySQL ou tabela de lock, sempre libertada em finally. O histórico é pequeno, por isso priorizar correção sobre paralelismo.

## R-03 — Validação do servidor é incompleta

**Locais:** formulários em templates/ e rotas em app.py.

Atributos HTML não protegem POSTs diretos. Casos encontrados:

- cadastrar_sorteio aceita concurso zero/negativo por pedido construído;
- preços e orçamento aceitam valores negativos e sem limite;
- gerar_jogos/backtesting aceitam estratégias fora da lista ativa; o gerador pode usar Equilibrada mas guardar/mostrar o nome recebido;
- quantidade Joker não tem limite de servidor;
- observação e prémio não têm limite de domínio, ficando dependentes da coluna MySQL.

**Correção proposta:** validadores centrais com mensagens PT-PT. Preços/orçamento >= 0. Decidir se concurso é inteiro global ou texto NN/AAAA e aplicar uma única regra. Cobrir todos os limites em testes de rota.

## R-04 — parse_decimal_br interpreta milhares como decimais

**Local:** modules/date_utils.py e formulários de Definições/Banca.

Comportamento confirmado:

    "1.200"    -> 1,2        incorreto em PT
    "1.200,50" -> 1200,5     correto
    "1200,50"  -> 1200,5     correto

É atingível diretamente pelos três campos textuais de Definições e por POST à Banca.

**Correção proposta:** usar Decimal e regra sem ambiguidade:

- com vírgula: ponto é milhar e vírgula é decimal;
- sem vírgula: ponto seguido de três dígitos é milhar;
- sem vírgula: ponto decimal só é permitido com um ou dois dígitos após ele;
- formatos ambíguos/mal formados são rejeitados, não adivinhados.

Testar milhares, vírgula, negativas onde aprovadas e entradas inválidas.

## R-05 — Backtesting bloqueia o servidor

**Local:** app.py:backtesting, modules/backtesting.py e modules/gerador.py.

O pedido POST executa no processo Flask:

1. estatísticas de todo o prefixo histórico em cada alvo;
2. geração de candidatos, pelo menos max(200, quantidade × 40);
3. expansão/avaliação de linhas;
4. 20 baselines uniformes por concurso;
5. métricas de cobertura.

O limite de 420 linhas por concurso não limita o produto número de concursos × geração × baselines. Não há progresso, cancelamento, limite de concursos, limite de tempo ou resultado parcial marcado.

### Opções concretas

| Opção | Benefício | Limite |
|---|---|---|
| Limitar concursos-alvo | redução imediata; últimos 25/50/100 | manter todo o passado de cada alvo para não haver leakage |
| Perfil rápido de candidatos | reduzir de 40 para, por exemplo, 15 candidatos/bilhete | altera a estratégia testada; guardar o perfil |
| Baselines configuráveis | 5/20/100 | menos repetições aumentam ruído Monte Carlo |
| Estatísticas incrementais | elimina recomputação repetida | só após testes fortes de equivalência |
| Job assíncrono com polling | não bloqueia HTTP; permite progresso/cancelamento | requer estado persistente e worker separado |

### Roteiro recomendado

**Fase 1 — proteção:** campo limite_concursos (25/50/100/todos), perfil Rápido/Standard e timeout cooperativo. Se parar, mostrar estado incompleto, total concluído e razão; nunca chamar-lhe backtesting completo.

**Fase 2 — job local:** tabela backtesting_jobs com configuração, estado, percentagem, mensagem, início/fim, resultado JSON e erro seguro. Um processo worker recebe dados serializáveis, nunca uma ligação MySQL. A rota cria job e static/js/app.js faz polling. Persistir estado, pois debug/reloader e reinícios invalidam memória de processo.

**Fase 3 — otimização:** antes de estatísticas incrementais, testar equivalência com a versão atual para mesmo histórico/seed; só então perfilar e documentar seed, parâmetros e hardware.

## R-06 — Importadores frágeis e .xls prometido sem suporte

**Locais:** modules/importador.py e modules/joker.py.

- A interface aceita .xls, mas pandas precisa normalmente de xlrd para esse formato binário; xlrd não está instalado.
- PDF só funciona com texto extraível/formato esperado; não há OCR.
- Joker suprime exceções por linha na leitura de texto.
- CSV não define política de encoding nem relatório de rejeições.
- CSV/Excel podem aceitar estatísticas parciais.

**Correção proposta:** remover .xls da interface ou adicionar xlrd pinado e fixture .xls. Criar objeto de resultado de importação: aceites, rejeitados, avisos e origem. Fazer pré-visualização antes da gravação.

## R-07 — Caminhos dependem da diretoria de arranque

**Local:** config.py e criação de pastas em app.py.

uploads e exports são caminhos relativos. O BAT usa a diretoria correta, mas outro arranque pode criar artefactos noutro sítio.

**Correção proposta:** definir BASE_DIR a partir do caminho de config.py e construir caminhos absolutos. Testar com diretoria atual diferente.

# Qualidade e manutenção

## Q-01 — Cobertura de testes insuficiente nas fronteiras de dados

tests/test_totoloto.py protege bem expansão oficial, prémios, custos, cobertura e backtesting básico. test_routes.py faz smoke tests GET e test_templates.py verifica interface. É uma boa proteção do núcleo.

Falta cobertura para parsers, transações, POSTs inválidos, orçamento acumulado, parse_decimal_br, jobs, progresso e novas métricas.

### Plano de fixtures

| Fixture pequena | Testes |
|---|---|
| estatisticas_validas.csv com 45 linhas | cabeçalhos PT, ;, datas PT e normalização |
| estatisticas_cabecalho_deslocado.xlsx | cabeçalho e serial Excel |
| estatisticas_incompletas.csv | erro/aviso para 44 números |
| linhas PDF como texto | parser puro, formato inválido e erro com contexto |
| joker_valido.csv | zero à esquerda, concurso e categoria |
| texto Joker com linha inválida | aceites e rejeições, sem silêncio |
| fake connection/cursor | rollback, close e ausência de commit parcial |

Não usar uploads reais do utilizador como fixtures canónicas. Para XLSX, gerar em setUp com openpyxl ou versionar folha mínima. Para PDF, testar primeiro a extração textual e manter apenas um PDF mínimo de integração.

## Q-02 — Regras repetidas em Python e JavaScript

static/js/app.js repete a tabela 6→1, 7→7, 8→28, 9→84, 10→210 e o limite 420 que existem no Python. Hoje coincidem; uma alteração futura pode deixar pré-visualização diferente da validação real.

**Correção proposta:** renderizar o mapa/limite como dados vindos de Flask; Python permanece fonte de verdade e continua a validar.

## Q-03 — Dependências não reprodutíveis

requirements.txt não fixa versões. O ambiente atual tem Flask 3.1.3, mysql-connector-python 9.7.0, pandas 3.0.3, openpyxl 3.1.5, pypdf 6.12.2 e reportlab 4.5.1, mas nova instalação pode resolver versões diferentes.

NumPy não é usado diretamente por código do projeto. Contudo, é dependência transitiva normal de pandas; retirar a linha direta de requirements não significa desinstalá-lo do ambiente.

**Correção proposta:**

1. manter requirements.in apenas com dependências diretas, removendo NumPy direto;
2. gerar requirements.txt bloqueado/hashed em ambiente limpo com ferramenta de lock aprovada;
3. testar importadores e suite nesse ambiente;
4. manter pip check na validação.

Não fixar simplesmente o freeze atual sem uma instalação limpa validada.

## Q-04 — Organização e migrações

- app.py concentra dados, validação, rotas, orquestração e exportação.
- modules/joker.py tem imports a meio do ficheiro; refactor de baixo risco.
- criar_banco.py tem migração com except Exception: pass, podendo esconder falha real.
- recálculos fazem muitos execute em vez de executemany; é pequeno, mas melhorável após cobertura.
- sorteios.concurso é INT, embora módulos aceitem NN/AAAA. Confirmar a regra oficial antes de migrar, para não criar colisões.

Refactor futuro: serviços para geração/backtesting/importação, repositórios para SQL, rotas finas em blueprints. Não mover o motor matemático sem testes de equivalência.

## Q-05 — Artefactos e exportação

Uploads e cada PDF/XLSX exportado são guardados sem retenção. Exportações carregam todos os jogos em memória. Texto de observação pode iniciar por =, +, - ou @ e converter-se em fórmula ao abrir Excel.

**Correção proposta:** nome único por job, paginação/intervalo de exportação, retenção configurável e neutralização de fórmula em colunas textuais.

## Q-06 — Git e higiene

Não há Git. .venv, dados locais, logs, exports, graphify-out e podcli-clips não devem viajar com o código.

Sugestão de .gitignore:

    # Python
    .venv/
    __pycache__/
    *.py[cod]
    .pytest_cache/
    .mypy_cache/

    # Segredos
    .env
    .env.*
    !.env.example

    # Estado local
    uploads/*
    !uploads/.gitkeep
    exports/pdf/*.pdf
    exports/excel/*.xlsx
    flask-server*.log
    *.log

    # Ferramentas
    graphify-out/
    podcli-clips/
    .vscode/
    .idea/

PDFs de regulamento/técnicas e fixtures pequenas podem ser versionados se houver direitos e valor documental. Uploads reais e exports não. Depois de aprovação: rever ficheiros, criar .gitignore, git init, primeiro commit de código/testes/documentação e remoto privado. Nunca guardar password MySQL.

# Segurança

## S-01 — debug ativo e chave previsível

**Local:** app.py usa debug=True; config.py traz SECRET_KEY fixa por defeito.

127.0.0.1 reduz a exposição de rede, mas não elimina risco local. Debugger não deve ser padrão permanente, e chave previsível permite forjar cookies de sessão caso a aplicação seja exposta.

**Correção proposta:** DEBUG controlado por ambiente e falso por defeito; exigir SECRET_KEY de ambiente fora de desenvolvimento. O BAT pode definir modo local sem guardar segredo no projeto.

## S-02 — POSTs sem CSRF

Todas as rotas mutáveis aceitam POST sem token. Uma página maliciosa aberta no mesmo navegador pode tentar submeter pedidos a localhost.

**Correção proposta:** Flask-WTF/CSRFProtect, token em formulários e testes que rejeitem POST sem token. É alteração transversal; fazer depois da camada transacional.

## S-03 — Upload só protegido pelo nome

secure_filename impede traversal no nome, mas não valida extensão real, MIME, assinatura, páginas/folhas ou colisões. O mesmo nome substitui upload anterior. O limite global de 16 MB é positivo, mas PDF/XLSX complexo pode ainda consumir recursos.

**Correção proposta:** whitelist no servidor, nome aleatório por lote, pasta temporária, limites de páginas/linhas e remoção segura após importar. Mostrar erro sem caminho interno.

## S-04 — Erros internos expostos

Várias rotas fazem flash(str(exc)). Isto pode mostrar detalhes de MySQL, caminhos e SQL.

**Correção proposta:** registar tecnicamente e mostrar mensagem curta em PT-PT com identificador de erro; usar logs em desenvolvimento.

## S-05 — Resultado da procura por SQL injection e XSS

Não foi encontrada interpolação de input HTTP em SQL: as rotas usam parâmetros %s. SQL dinâmico no schema usa identificadores internos, mas o nome de base vindo do ambiente deve ser validado.

Não foram encontrados filtros Jinja safe, Markup, innerHTML, eval ou templates construídos por input; autoescape protege a HTML normal. Isto não cobre injeção de fórmula em XLSX, tratada em Q-05.

# Funcionalidades e rigor analítico propostos

## F-01 — Suavização Bayesiana

**Classificação:** fórmula/posterior/intervalos = **FATO MATEMÁTICO**; contagem observada = **PADRÃO HISTÓRICO**; usar para selecionar aposta = **HEURÍSTICA**.

Para cada número, em T concursos, a presença marginal é Bernoulli com referência p0 = 6/45. Laplace Beta(1,1) centra em 50%, logo não é a referência correta do Totoloto.

Recomendação: prior Beta centrado no nulo, com força κ, por exemplo 20 concursos:

    α = κ × 6/45
    β = κ × 39/45
    p_posterior = (saídas + α) / (T + α + β)

Para Joker, por posição, usar Dirichlet simétrico nos dez dígitos:

    p_posterior(dígito d) = (contagem_d + κ/10) / (T + κ)

Guardar contagem e percentagem brutas. Mostrar estimativa suavizada, κ e intervalo credível. Um índice “quente” deve tornar-se “desvio histórico suavizado”, não probabilidade do próximo concurso.

Ausência é padrão histórico. Sob independência, a ausência passada não muda a probabilidade teórica seguinte; esta mensagem deve combater a gambler's fallacy, não alimentar previsão.

Referência: [Stan User's Guide — Beta-Binomial](https://mc-stan.org/docs/2_19/stan-users-guide-2_19.pdf).

## F-02 — Qualidade de ajuste qui-quadrado

**Classificação:** teste/p-value/simulação = **FATO MATEMÁTICO**; resultado no histórico = **PADRÃO HISTÓRICO**; seleção por ele = **HEURÍSTICA**.

Proposta:

1. calcular O_n e E = T × 6/45;
2. calcular X² = soma de (O_n - E)² / E;
3. não usar cegamente χ² com 44 graus de liberdade: os seis números de um concurso são escolhidos sem reposição e têm correlação negativa;
4. simular, com seed guardada, 10 000 históricos nulos via random.sample(1..45, 6);
5. p = (1 + número de X²_sim >= X²_obs) / (B + 1).

O [NIST](https://itl.nist.gov/div898/handbook/eda/section3/eda35f.htm) descreve a comparação qui-quadrado entre contagens observadas e esperadas e alerta para contagens esperadas pequenas. A simulação do mecanismo 6/45 preserva a dependência do jogo e é mais honesta que uma aproximação multinomial automática.

Texto de interface:

> Este teste avalia se este histórico é invulgar sob modelo uniforme 6/45. P baixo sugere investigar qualidade dos dados, mudanças de equipamento ou outras causas; não identifica causa mecânica, não prova viés e não prevê o próximo sorteio. P não baixo não prova justiça perfeita.

Nunca escrever “bolas de peso diferente” a partir destes dados sem auditoria física/operacional independente.

## F-03 — Múltiplas comparações

**Classificação:** correção = **FATO MATEMÁTICO**; lista de extremos = **PADRÃO HISTÓRICO**; aposta baseada nela = **HEURÍSTICA**.

Testar 45 números individualmente garante que alguns parecem extremos por acaso. Para cada número, teste binomial bilateral exato contra 6/45; depois:

- padrão público: Holm-Bonferroni a α=0,05;
- exploratório: Benjamini-Hochberg FDR, com ressalva de dependência entre números do mesmo concurso;
- mostrar p bruto, p ajustado, método e “não significativo após correção”.

O [NIST](https://itl.nist.gov/div898/handbook/prc/section4/prc473.htm) documenta Bonferroni. O artigo de [Benjamini e Hochberg (1995)](https://doi.org/10.1111/j.2517-6161.1995.tb02031.x) define controlo FDR nas condições declaradas.

## F-04 — Overfitting no backtesting

**Classificação:** protocolo e controlo nulo = **FATO MATEMÁTICO**; desempenho passado = **PADRÃO HISTÓRICO**; escolher parâmetros depois de olhar = **HEURÍSTICA**.

O IC atual é uma boa base, mas não certifica estratégia. Proposta:

1. guardar diferença emparelhada por concurso: média estratégia menos média baseline;
2. gerar B históricos sintéticos 6/45 de igual comprimento e correr exatamente o mesmo walk-forward, estratégia, limites e baselines;
3. comparar métrica observada com distribuição sintética e calcular p empírico;
4. reservar holdout cronológico, por exemplo últimos 20%, antes de escolher parâmetros; congelar configuração e avaliar uma vez.

Teste de permutação emparelhado é válido em muitos casos ([SciPy](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.permutation_test.html)), mas o controlo sintético completo é preferível porque replica treino walk-forward e dependência por históricos sobrepostos.

Guardar n_sinteticos, seed, métrica, p empírico, intervalo nulo e configuração. Executar no job assíncrono.

## F-05 — Wheeling/covering designs verificáveis

**Classificação:** design, certificado e garantia condicional = **FATO MATEMÁTICO**; pool escolhido por passado = **PADRÃO HISTÓRICO** ou **HEURÍSTICA**; wheel não torna o pool mais provável.

Um covering design (v,k,t) é coleção de blocos k em universo v em que cada subconjunto t cabe em algum bloco. A definição e tabelas estão no [La Jolla Covering Repository](https://ljcr.dmgordon.org/cover.html).

Fluxo proposto:

1. utilizador fornece pool v, linhas k=6, nível t e orçamento;
2. sistema constrói/seleciona blocos;
3. verificador independente enumera C(v,t) subconjuntos e confirma cobertura;
4. interface mostra cobertura, descobertos, sobreposição, custo e hash das linhas.

Frase correta:

> Este design cobre 100% das trincas do pool. Se uma trinca vencedora estiver dentro do pool, existe linha que a contém. É garantia condicional de cobertura, não previsão de que a trinca estará no resultado.

Começar pelo verificador e relatório, depois designs pré-calculados. Para otimizar, greedy deve dizer “aproximado”; CP-SAT/ILP deve comunicar OPTIMAL/FEASIBLE/timeout. [OR-Tools CP-SAT](https://developers.google.com/optimization/cp/cp_solver) é opção, mas é dependência nova sujeita a aprovação.

## F-06 — Otimização por orçamento

**Classificação:** máximo para objetivo/restrições declarados = **FATO MATEMÁTICO**; pesos históricos = **PADRÃO HISTÓRICO**; seleção com esses pesos = **HEURÍSTICA**.

Não otimizar “probabilidade de sair”: cada linha distinta de seis números tem a mesma probabilidade teórica. Definir cobertura explicitamente:

    Dados: pool v, linhas candidatas, orçamento B e custo.
    Variável: x_l = 1 quando linha l é comprada.
    Restrição: soma(custo_l × x_l) <= B.
    Objetivo factual: maximizar pares/trincas distintos cobertos
                       e reduzir duplicação/sobreposição.

Para cada subconjunto s, y_s só vale 1 se alguma linha o cobre; maximizar soma(y_s) é máxima cobertura. Pesos todos 1 produzem melhoria estrutural verificável. Pesos por frequência/atraso produzem heurística e devem aparecer em modo separado.

Relatório obrigatório: orçamento, custo, linhas, cobertura absoluta/percentual, cobertura por CVE, sobreposição e status do solver. Timeout nunca pode aparecer como “ótimo”.

# Ordem de correções proposta

Após a aprovação, uma alteração por vez, sempre seguida por python -m unittest discover -s tests -v:

1. Testes e correção de parse_decimal_br com Decimal.
2. Helper de conexão/rollback/close; migrar fetch_all/fetch_one.
3. Transações atómicas para sorteios e Joker, com testes.
4. Validação servidor: Joker, preços/orçamento, concursos e estratégias.
5. Orçamento semanal acumulado, depois de decidir a definição de semana.
6. Fixtures/testes de importação; decisão .xls/xlrd, completude e erros por linha.
7. Limite de concursos, perfil rápido e timeout cooperativo no backtesting.
8. Jobs assíncronos/polling.
9. Proveniência separada de estatística agregada e histórico bruto.
10. Suavização, testes de ajuste/múltiplas comparações/controlo sintético como módulos novos e opt-in.
11. Verificador wheel, depois construtor e otimizador.
12. Debug/secret/CSRF/uploads/exportações, lock de dependências e Git aprovado.

## Critérios de aceitação

Uma alteração só fica concluída quando:

- mantém os 13 testes atuais a passar;
- inclui teste de regressão que falhava antes;
- preserva PT-PT e CVE;
- não apresenta score, frequência, atraso, smoothing ou backtesting como previsão;
- documenta fórmula, unidade, fonte, seed/configuração e rótulo FATO/PADRÃO/HEURÍSTICA quando cria métrica;
- fecha recursos e faz rollback verificável em exceção;
- expõe limites/progresso/estado incompleto com honestidade em operações lentas.

## Itens a preservar nesta fase

- expansão oficial 6–10 e suporte histórico a cinco fixos;
- contagem de prémios por linha;
- limite atual de 420 linhas simples por concurso;
- retorno/ROI indisponível sem quinhões oficiais;
- avisos de que score, frequência e atraso não são garantia.

Estas partes estão coerentes com os testes atuais e com a honestidade estatística definida pelo projeto.

