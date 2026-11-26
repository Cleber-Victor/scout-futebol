# Scout de Futebol: Euro 2024

Pipeline de dados que transforma os eventos da **Euro 2024**, que a StatsBomb disponibiliza abertamente, numa tabela de scout com **uma linha por jogador**. A tabela traz minutos jogados, posição principal, contagens (passes, cruzamentos, chutes, gols, dribles), métricas por 90 minutos e taxas de acerto, e fica num banco DuckDB pronto para consultas em SQL.

```
StatsBomb Open Data ──► baixar.py ──► data/*.parquet ──► montar_tabela.py ──► scout.duckdb
     (API aberta)                     (jogos, eventos,                         (minutos,
                                       escalações)                              estatisticas,
                                                                                jogadores)
```

## Exemplo de resultado

Os 5 jogadores com mais cruzamentos certos por 90 minutos (mínimo de 270 minutos em campo):

| Jogador | Seleção | Posição | Minutos | Cruz. certos /90 | Acerto |
|---|---|---|---:|---:|---:|
| Cody Gakpo | Holanda | Ponta esquerda | 547 | 1,81 | 47,8% |
| Federico Chiesa | Itália | Ponta direita | 274 | 1,64 | 38,5% |
| Ousmane Dembélé | França | Ponta direita | 362 | 1,49 | 22,2% |
| Maximilian Mittelstädt | Alemanha | Lateral esquerdo | 317 | 1,42 | 25,0% |
| Bukayo Saka | Inglaterra | Ponta direita | 643 | 1,26 | 40,9% |

## Como rodar

Precisa de Python 3.12 ou mais novo.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python baixar.py          # baixa os 51 jogos para data/ (alguns minutos)
python montar_tabela.py   # cria scout.duckdb e mostra um top 10 de cruzamentos
```

Depois disso, dá para consultar o banco direto:

```python
import duckdb
con = duckdb.connect("scout.duckdb", read_only=True)
con.sql("SELECT nome, selecao, gols, chutes_p90 FROM jogadores ORDER BY gols DESC LIMIT 10").show()
```

## Arquivos

| Arquivo | O que faz |
|---|---|
| [`explorar.py`](explorar.py) | Primeiro contato com os dados: estrutura dos jogos e dos eventos, e os cruzamentos da final |
| [`baixar.py`](baixar.py) | Baixa jogos, eventos e escalações de toda a competição e salva em Parquet |
| [`montar_tabela.py`](montar_tabela.py) | Usa SQL no DuckDB para montar a tabela de jogadores |

Os dados (`data/` e `scout.duckdb`) não vão para o repositório. Para recriá-los, rode os scripts.

## A tabela `jogadores`

| Coluna | Descrição |
|---|---|
| `player_id`, `nome`, `selecao` | Identificação do jogador |
| `posicao_principal` | Posição em que o jogador passou mais tempo no torneio |
| `jogos`, `minutos` | Jogos disputados e minutos em campo |
| `passes`, `cruzamentos`, `cruzamentos_certos`, `assistencias`, `chutes`, `gols`, `dribles_certos` | Contagens no torneio |
| `*_p90` | A mesma métrica por 90 minutos, para comparar quem jogou muito com quem jogou pouco |
| `taxa_acerto_passe`, `taxa_acerto_cruzamento` | Fração de acertos (`NULL` quando o jogador não tentou nenhum) |

### Decisões de modelagem

- **Minutos jogados:** em cada jogo, conta do primeiro momento em que o jogador entra em qualquer posição até a última saída. Quem fica até o fim recebe o minuto do último evento da partida, incluindo acréscimos e prorrogação.
- **Disputa de pênaltis** (`period = 5`): fica fora dos minutos e dos gols.
- **Passe certo:** na StatsBomb, `pass_outcome` vazio quer dizer passe completo. Quando o passe erra, o campo traz o motivo, como `Incomplete` ou `Out`.
- **Cruzamento:** passe com `pass_cross = True`.

## Fonte dos dados

[StatsBomb Open Data](https://github.com/statsbomb/open-data), acessada com o [statsbombpy](https://github.com/statsbomb/statsbombpy). O uso dos dados segue os [termos da StatsBomb](https://github.com/statsbomb/open-data/blob/master/LICENSE.pdf). Se publicar algo com eles, cite a StatsBomb como fonte.
