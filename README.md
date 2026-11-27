# Scout de Futebol em Linguagem Natural: Euro 2024

O objetivo é um scout que responde a perguntas em português, como *"me ache um lateral sub-23 que cruza bem e custa pouco"*. Um LLM transforma a pergunta numa consulta SQL. Essa consulta roda sobre uma tabela de jogadores montada a partir de dados abertos, e a resposta sai validada.

> 🚧 **Em construção.** A base de dados e o agente text-to-SQL já funcionam. Faltam a avaliação sistemática e a interface ([roadmap](#roadmap)).

### Exemplo

```
$ python agente.py "me ache um lateral sub-23 que cruza bem e custa pouco"
```

O agente (Gemini) gerou este SQL a partir da frase:

```sql
SELECT nome, selecao, posicao_principal, idade, minutos, cruzamentos_certos_p90,
       taxa_acerto_cruzamento, valor_mercado_eur
FROM jogadores_completo
WHERE posicao_principal IN ('Left Back', 'Right Back', 'Left Wing Back', 'Right Wing Back')
  AND idade < 23 AND minutos >= 180
ORDER BY cruzamentos_certos_p90 DESC NULLS LAST
LIMIT 10
```

Ele traduziu "lateral" para as 4 posições exatas, "sub-23" para `idade < 23` e "cruza bem" para cruzamentos certos por 90 minutos, com um mínimo de minutos em campo. "Custa pouco" virou uma coluna de valor para comparar, em vez de um teto inventado.

| Jogador | Seleção | Idade | Minutos | Cruz. certos /90 | Valor (jun/2024) |
|---|---|---:|---:|---:|---:|
| **Nicola Zalewski** | Polônia | 22 | 257 | **0,70** | **€ 12 mi** |
| Joško Gvardiol | Croácia | 22 | 292 | 0,31 | € 75 mi |
| Nuno Mendes | Portugal | 21 | 426 | 0,21 | € 55 mi |
| Mario Mitaj | Albânia | 20 | 288 | 0,00 | € 2 mi |
| Milos Kerkez | Hungria | 20 | 239 | 0,00 | € 20 mi |

O Zalewski acerta mais que o dobro de cruzamentos por 90 minutos do que o segundo colocado e custa 6 vezes menos que o Gvardiol.

## Roadmap

1. ✅ **Exploração** dos eventos da StatsBomb (`explorar.py`)
2. ✅ **Tabela de jogadores** com métricas por 90 minutos no DuckDB (`baixar.py`, `montar_tabela.py`)
3. ✅ **Idade e valor de mercado** do Transfermarkt, medidos na data do torneio e cruzados com a StatsBomb pelo nome dos jogadores (*entity resolution*, `juntar_transfermarkt.py`)
4. ✅ **Agente text-to-SQL:** pergunta → LLM gera o SQL → saída validada com Pydantic → DuckDB executa em modo somente leitura, e os erros voltam para o LLM corrigir (`agente.py`, `llm.py`)
5. ⬜ **Avaliação** com cerca de 20 perguntas de scout de resposta conhecida, medindo a taxa de acerto
6. ⬜ **Interface** simples em Streamlit

## Base de dados (etapas 1 a 3)

O pipeline transforma os eventos da **Euro 2024**, que a StatsBomb disponibiliza abertamente, numa tabela de scout com **uma linha por jogador**. A tabela traz minutos jogados, posição principal, contagens (passes, cruzamentos, chutes, gols, dribles), métricas por 90 minutos e taxas de acerto. Depois, a tabela ganha idade e valor de mercado vindos do Transfermarkt.

```
StatsBomb Open Data ──► baixar.py ──► data/*.parquet ──► montar_tabela.py ──► scout.duckdb
     (API aberta)                     (jogos, eventos,                         (jogadores)
                                       escalações)                                  │
                                                                                    ▼
Transfermarkt ──────► data/*.csv.gz ─────────────────► juntar_transfermarkt.py ──► jogadores_completo
(dataset CC0)         (jogadores, avaliações)            (casamento por nome)
```

## Exemplo de resultado

Os 5 jogadores com mais cruzamentos certos por 90 minutos (mínimo de 270 minutos em campo):

| Jogador | Seleção | Posição | Idade | Minutos | Cruz. certos /90 | Acerto | Valor (jun/2024) |
|---|---|---|---:|---:|---:|---:|---:|
| Cody Gakpo | Holanda | Ponta esquerda | 25 | 547 | 1,81 | 47,8% | € 50 mi |
| Federico Chiesa | Itália | Ponta direita | 26 | 274 | 1,64 | 38,5% | € 35 mi |
| Ousmane Dembélé | França | Ponta direita | 27 | 362 | 1,49 | 22,2% | € 60 mi |
| Maximilian Mittelstädt | Alemanha | Lateral esquerdo | 27 | 317 | 1,42 | 25,0% | € 17 mi |
| Bukayo Saka | Inglaterra | Ponta direita | 22 | 643 | 1,26 | 40,9% | € 140 mi |

## Como rodar

Precisa de Python 3.12 ou mais novo.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python baixar.py          # baixa os 51 jogos para data/ (alguns minutos)
python montar_tabela.py   # cria scout.duckdb e mostra um top 10 de cruzamentos

# dados do Transfermarkt (dataset aberto dcaribou/transfermarkt-datasets)
URL=https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data
curl -L -o data/players.csv.gz "$URL/players.csv.gz"
curl -L -o data/player_valuations.csv.gz "$URL/player_valuations.csv.gz"

python juntar_transfermarkt.py   # casa os jogadores e cria jogadores_completo
```

Para o agente, crie um arquivo `.env` na raiz com a sua chave do Gemini, que é gratuita em [aistudio.google.com/apikey](https://aistudio.google.com/apikey). O `.env` já está no `.gitignore`.

```bash
GEMINI_API_KEY=sua-chave
MODELO_LLM=gemini-3.5-flash
```

```bash
python agente.py                          # modo interativo
python agente.py "quem fez mais gols?"    # uma pergunta só
```

Também dá para consultar o banco direto, sem o agente:

```python
import duckdb
con = duckdb.connect("scout.duckdb", read_only=True)
con.sql("SELECT nome, selecao, idade, gols, valor_mercado_eur FROM jogadores_completo ORDER BY gols DESC LIMIT 10").show()
```

## Arquivos

| Arquivo | O que faz |
|---|---|
| [`explorar.py`](explorar.py) | Primeiro contato com os dados: estrutura dos jogos e dos eventos, e os cruzamentos da final |
| [`baixar.py`](baixar.py) | Baixa jogos, eventos e escalações de toda a competição e salva em Parquet |
| [`montar_tabela.py`](montar_tabela.py) | Usa SQL no DuckDB para montar a tabela de jogadores |
| [`juntar_transfermarkt.py`](juntar_transfermarkt.py) | Casa cada jogador com o seu registro no Transfermarkt e acrescenta idade e valor de mercado |
| [`agente.py`](agente.py) | Agente text-to-SQL: monta o prompt, valida a saída do LLM, executa o SQL com segurança e corrige erros |
| [`llm.py`](llm.py) | Único arquivo que conhece o provedor do LLM. Trocar de provedor é mudar só este arquivo |

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
- **Conferência com um caso conhecido:** o goleiro titular da Inglaterra, Jordan Pickford, jogou todas as partidas inteiras. A tabela registra 7 jogos e 713 minutos para ele: 7 × 90 = 630, mais duas prorrogações (60) e os acréscimos.

## Idade e valor de mercado (etapa 3)

A tabela `jogadores_completo` tem todas as colunas de `jogadores` e mais estas:

| Coluna | Descrição |
|---|---|
| `tm_id` | ID do jogador no Transfermarkt |
| `idade` | Idade em 14/06/2024, dia da abertura da Euro |
| `valor_mercado_eur` | Última avaliação de mercado antes do torneio (`NULL` se a última avaliação tem mais de 1 ano) |
| `valor_data` | Data dessa avaliação, para auditoria |

A tabela `ponte_tm` registra, para cada jogador, com qual registro do Transfermarkt ele foi casado e **como**: `exato`, `aproximado` (com a nota de similaridade) ou `manual`.

### Casando as duas bases pelo nome

As duas bases não têm um ID em comum. Por isso o casamento é feito pelo nome (*entity resolution*), e **492 dos 493 jogadores (99,8%)** foram casados:

| Método | Jogadores | Como funciona |
|---|---:|---|
| Exato | 461 | Nome normalizado (sem acento, minúsculo) **e** mesma nacionalidade |
| Aproximado | 19 | Similaridade de nomes com [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz), nota mínima de 90, dentro da mesma nacionalidade. Os 19 foram conferidos à mão |
| Manual | 12 | Casos que nenhuma regra resolve, conferidos pela data de nascimento e pelo clube |

O único jogador sem par é o Kwadwo Duah, da Suíça, que não está no dataset do Transfermarkt.

Problemas encontrados no caminho e como foram resolvidos:

- **Homônimos aposentados:** o Transfermarkt tem um Rodri nascido em 1984 e um Nacho nascido em 1980. Só entram como candidatos os jogadores ativos na época do torneio.
- **Homônimos ativos:** existem dois Ladislav Krejčí tchecos e dois Vitinha portugueses nascidos em 2000. Quando dois candidatos empatam, o script marca o caso como ambíguo e não escolhe ao acaso. Esses casos vão para a lista manual.
- **Nome de registro × nome usado:** a StatsBomb grava "Grant Campbell Hanley", e o Transfermarkt, "Grant Hanley". O script usa o apelido da StatsBomb quando existe e testa variantes curtas do nome.
- **Um registro do Transfermarkt só pode ser usado uma vez:** sem essa regra, a variante "Daniel Carvajal" do Dani Olmo (Daniel Olmo Carvajal) casava com o Dani Carvajal.
- **Grafias do país:** o Transfermarkt usa tanto "Turkey" quanto "Türkiye".
- **Sem vazamento temporal:** a idade e o valor são os de junho de 2024, não os atuais. A idade conta aniversários completos, e por isso o Nico Williams, que fez 22 anos durante o torneio, aparece com 21. O valor vem de um `ASOF JOIN`, que pega a última avaliação antes da abertura.
- **Conferências automáticas:** o script para com erro se Gakpo, Nico Williams e Yamal não tiverem as idades conhecidas (25, 21 e 16), se o mais velho não tiver 41 anos (Pepe) ou se algum jogador for casado duas vezes.

## Agente text-to-SQL (etapa 4)

```
pergunta ──► LLM gera JSON {sql, explicacao} ──► Pydantic valida ──► DuckDB executa ──► resultado
                 ▲                                      │                  │
                 └──────── o erro volta para o LLM ◄────┴──────────────────┘
                           (até 3 tentativas)
```

### O prompt

O prompt dá ao LLM o que ele não tem como adivinhar sozinho:

- **O schema, lido do próprio banco:** as colunas com seus tipos e as 23 posições que existem nos dados. Se a tabela mudar, o prompt acompanha.
- **O vocabulário de posições:** cada termo em português corresponde a uma lista exata de posições (`"lateral" = posicao_principal IN ('Left Back', ...)`). O `LIKE '%Back'` fica proibido, porque os zagueiros também terminam em "Back".
- **As regras de scout, com cortes escolhidos a partir dos dados:**
  - "Faz X bem" usa a métrica por 90 minutos com `minutos >= 180`, que equivale a 2 jogos inteiros (a mediana do torneio é 192 minutos).
  - Taxas de acerto exigem um mínimo de tentativas, para que 1 cruzamento certo em 1 tentado não apareça como 100%.
  - "Barato" sem número não vira um teto inventado.
  - `LIMIT 1` é proibido, porque esconde empates.
- **Nenhuma resposta de teste no prompt:** as regras não citam as respostas das perguntas de avaliação, para que o acerto meça o agente e não a cola.

### Segurança em camadas

O SQL vem de um modelo e precisa ser tratado como entrada não confiável:

| Camada | O que bloqueia |
|---|---|
| Validação com Pydantic | Qualquer coisa que não comece com `SELECT`/`WITH`, e várias instruções (`SELECT ...; DROP ...`) |
| `read_only=True` no DuckDB | Escrita: `DROP`, `INSERT`, `UPDATE`, `CREATE` |
| `enable_external_access=False` | Leitura de arquivos do disco ou da internet (`SELECT * FROM '/etc/passwd'`) |
| `fetchmany(50)` | Resultados gigantes, mesmo que o LLM esqueça o `LIMIT` |

### Correção automática de erros

Quando o JSON é inválido ou o SQL falha, a mensagem de erro volta para o LLM. Por exemplo, o DuckDB responde `column "idade_anos" not found. Candidate bindings: "idade"`, e o modelo corrige na tentativa seguinte. Tentar de novo sem mostrar o erro, com temperatura 0, repetiria exatamente o mesmo SQL. Erros de rede ou da API não voltam para o LLM, porque reescrever o SQL não resolve um servidor fora do ar.

### Primeiros testes

| Pergunta | Resposta esperada | Agente |
|---|---|---|
| Quem fez mais gols? | 6 empatados com 3 gols (a artilharia foi dividida) | ✅ os 6, com `WHERE gols = (SELECT max(gols) ...)` |
| Quantos laterais sub-23 jogaram? | 9 | ✅ |
| Quem é o jogador mais novo? | Lamine Yamal, 16 anos | ✅ |
| Lateral sub-23 que cruza bem e custa pouco | Zalewski no topo | ✅ o mesmo SQL escrito à mão |

A etapa 5 amplia esses testes para cerca de 20 perguntas e mede a taxa de acerto.

## Fonte dos dados

- [StatsBomb Open Data](https://github.com/statsbomb/open-data), acessada com o [statsbombpy](https://github.com/statsbomb/statsbombpy). O uso dos dados segue os [termos da StatsBomb](https://github.com/statsbomb/open-data/blob/master/LICENSE.pdf). Se publicar algo com eles, cite a StatsBomb como fonte.
- [transfermarkt-datasets](https://github.com/dcaribou/transfermarkt-datasets), um dataset aberto (licença CC0) com dados extraídos do Transfermarkt.
