# Resultados CVCV — Totoloto e Joker 2026

Documento de apoio ao **Totoloto Analyzer**. Os dados abaixo devem ser
confirmados na fonte oficial antes de serem usados para análises definitivas.

## Fonte consultada

- [Jogos Cruz Vermelha de Cabo Verde — últimos resultados](https://www.jogoscruzvermelha.cv/games/lotaria/results/u6304em0j6r46nt)
- Consulta realizada em 17/09/2026.

## Resultados confirmados

| Concurso | Data | N1 | N2 | N3 | N4 | N5 | N6 | Joker |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 24/2026 | 13/06/2026 | 15 | 25 | 26 | 29 | 32 | 44 | 669278 |

### Ordem apresentada pela fonte

- Totoloto: **15 – 25 – 26 – 29 – 32 – 44**
- Joker: **6 6 9 2 7 8** (registado neste documento como `669278`)

## Formato para registo manual

No Totoloto Analyzer, usar estes valores em **Registar Sorteio**:

```text
Concurso: 24
Data do sorteio: 13/06/2026
Números: 15, 25, 26, 29, 32, 44
```

O Joker deve ser registado na página **Joker**, associado ao concurso
`24/2026`, com o número `669278`.

## CSV mínimo para testes locais

Este bloco serve apenas para preparar uma fixture de teste. Não substitui a
validação do formulário nem a confirmação da fonte oficial.

```csv
concurso,data_sorteio,n1,n2,n3,n4,n5,n6,joker
24,13/06/2026,15,25,26,29,32,44,669278
```

## Estado do levantamento anual

O site consultado expôs publicamente o concurso 24/2026, mas a consulta
automatizada não devolveu uma listagem completa dos concursos 1–23 nem dos
concursos posteriores. Por isso, este ficheiro **não afirma que o ano esteja
completo**. Os concursos em falta devem ser adicionados apenas depois de
confirmados no portal oficial ou através de boletins oficiais.

## Testes recomendados no sistema

1. Registar o concurso acima e confirmar que os seis números são aceites como
   únicos e entre 1 e 45.
2. Gerar jogos em **modo análise**, sem consumir o orçamento semanal.
3. Executar o backtesting apenas se existirem concursos históricos suficientes;
   indicar o limite usado e não interpretar o resultado como previsão.
4. Quando forem adicionados mais concursos, verificar duplicados, datas fora
   de ordem e números repetidos antes de recalcular as estatísticas.

> Frequência, atraso, score e backtesting descrevem padrões históricos. Não
> permitem prever o próximo sorteio, que é um evento independente.
