# Totoloto Analyzer

Aplicação local em Python/Flask para importar resultados, explorar estatísticas, gerar combinações, testar cobertura e executar backtesting walk-forward. O projeto foi desenhado para separar evidência matemática, padrão histórico e heurística.

> **Aviso:** frequência, atraso, IA, score e histórico não aumentam a probabilidade de ganhar num sorteio aleatório. O sistema não prevê concursos nem garante prémios.

## O que demonstra

- Flask com páginas para resultados, estatísticas, wheeling e backtesting;
- MySQL opcional para histórico e configurações, com variáveis `MYSQL_*`;
- importação de CSV/Excel/PDF e validação de concursos com seis números distintos;
- expansão de múltiplas em linhas simples e cálculo de prémios por linha;
- walk-forward sem usar concursos futuros e comparação com baseline aleatório;
- testes Python e integrações MySQL opt-in.

## Evidência e linguagem

- **FATO MATEMÁTICO:** enumeração, combinações, cobertura, custos e protocolo nulo.
- **PADRÃO HISTÓRICO:** descrição do que aconteceu em dados passados.
- **HEURÍSTICA:** regra de seleção ou ranking que não altera a aleatoriedade do próximo concurso.

O ROI fica indisponível sem quinhões oficiais por concurso e categoria. Estatísticas agregadas não substituem o histórico bruto necessário para backtesting.

## Executar localmente

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:MYSQL_HOST='localhost'
$env:MYSQL_PORT='3306'
$env:MYSQL_USER='root'
$env:MYSQL_PASSWORD=''
$env:MYSQL_DATABASE='totoloto_analyzer'
python criar_banco.py
python app.py
```

Abra `http://127.0.0.1:5000`. Para validar sem base de dados:

```powershell
python -m unittest discover -s tests -v
```

Os testes MySQL são opcionais e só devem ser ativados conscientemente. Nunca guarde credenciais, bases locais, uploads ou relatórios privados no repositório.

## English

Local Python/Flask application for importing lottery results, exploring statistics, generating combinations, checking coverage and running walk-forward backtests. It explicitly separates mathematical facts, historical patterns and heuristics.

Frequency, delay, AI, scores and past history do not increase the odds of a future random draw. The application does not predict draws or guarantee prizes. MySQL is optional and configured through `MYSQL_*` environment variables. Run the Python unittest suite without a database; opt-in integration tests require a deliberately configured local MySQL instance.

## License

MIT — see [LICENSE](LICENSE).
