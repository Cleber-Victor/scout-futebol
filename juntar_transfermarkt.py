"""Etapa 3: junta idade e valor de mercado do Transfermarkt à tabela de jogadores da StatsBomb.

As duas bases não têm um ID em comum, então o casamento é feito pelo NOME (entity resolution).
Rode depois do montar_tabela.py:  python juntar_transfermarkt.py

Entrada:  scout.duckdb (tabela jogadores), data/escalacoes.parquet,
          data/players.csv.gz e data/player_valuations.csv.gz (Transfermarkt)
Saída:    tabelas ponte_tm e jogadores_completo no scout.duckdb
"""
import unicodedata

import duckdb
import pandas as pd
from rapidfuzz import fuzz, process

DATA_TORNEIO = "2024-06-14"  # abertura da Euro 2024: idade e valor são medidos NESTA data
NOTA_MINIMA = 90             # nota mínima (0-100) para aceitar um casamento aproximado

con = duckdb.connect("scout.duckdb")


# ---------------------------------------------------------------------------
# Passo 1: carregar os dois lados
# ---------------------------------------------------------------------------
# Lado StatsBomb: um jogador por linha, com o apelido ("Cody Gakpo") além do nome completo
# ("Cody Mathès Gakpo"). O apelido vem das escalações (salvo pelo baixar.py).
# Atenção: a StatsBomb só preenche o apelido quando ele é diferente do nome completo
# (Laporte não tem apelido). ~80% dos jogadores vêm com apelido NULL.
sb = con.sql("""
    SELECT j.player_id, j.nome, j.selecao,
           any_value(e.player_nickname) AS apelido
    FROM jogadores j
    JOIN 'data/escalacoes.parquet' e USING (player_id)
    GROUP BY ALL
""").df()

# Lado Transfermarkt: só jogadores ATIVOS na época do torneio. Por quê: o TM tem um "Rodri"
# nascido em 1984 e um "Nacho" nascido em 1980, aposentados. Sem esse filtro, o casamento por
# nome escolhe o errado. "Ativo" = jogou temporada >= 2023 numa liga coberta pelo dataset OU
# teve avaliação nos 2 anos antes do torneio (cada critério sozinho perde jogadores: há quem não
# tenha nenhuma avaliação no arquivo, e quem jogue numa liga que o dataset não cobre).
# O TM grafa a Turquia de dois jeitos ("Turkey" e "Türkiye"); unificamos com o nome da StatsBomb.
tm = con.sql(f"""
    SELECT player_id AS tm_id, name AS tm_nome,
           replace(country_of_citizenship, 'Türkiye', 'Turkey') AS pais,
           date_of_birth::DATE AS nascimento
    FROM 'data/players.csv.gz'
    WHERE last_season >= 2023
       OR player_id IN (
           SELECT player_id FROM 'data/player_valuations.csv.gz'
           WHERE date BETWEEN DATE '{DATA_TORNEIO}' - INTERVAL 2 YEAR AND DATE '{DATA_TORNEIO}')
""").df()

# Cauda longa que o casamento automático não resolve, conferida à mão (nascimento e clube):
# {player_id StatsBomb: tm_id}. Sempre preferir corrigir aqui a afrouxar a NOTA_MINIMA.
CORRECOES_MANUAIS = {
    9478: 126600,   # Kenneth McLean      -> Kenny McLean (apelido Kenny)
    8519: 344695,   # Dayotchanculle Upamecano -> Dayot Upamecano
    48335: 548729,  # Mohamed Zeki Amdouni -> Zeki Amdouni
    15896: 320854,  # Timi Elšnik         -> Timi Max Elsnik
    5202: 58884,    # Nacho               -> Nacho Fernández (há 7 "Nacho" espanhóis ativos)
    28272: 345911,  # Ladislav Krejčí     -> o de 1999 (há dois, ambos tchecos e ativos)
    34639: 487469,  # Vitinha             -> o do PSG, de 13/02/2000 (há dois, ambos de 2000)
    16005: 157391,  # Solomon Kverkvelia  -> Solomon Kvirkvelia (liga fora da cobertura)
    7139: 80351,    # Josip Iličić        -> Josip Ilicic (liga fora da cobertura)
    3153: 168088,   # Ádám Lang           -> Ádám Lang (liga fora da cobertura)
    32975: 357153,  # Diogo Costa         -> o goleiro do Porto, de 1999 (há um zagueiro de 2003)
    5603: 413507,   # Nikola Milenković   -> o zagueiro de 1997 (há um meia de 2006)
    # Kwadwo Duah (Suíça) não existe no dataset: fica sem par, de propósito.
}
manuais = pd.DataFrame({"player_id": list(CORRECOES_MANUAIS), "tm_id": list(CORRECOES_MANUAIS.values()),
                        "metodo": "manual", "nota": 100.0})
total_sb = len(sb)
sb = sb[~sb["player_id"].isin(CORRECOES_MANUAIS)]  # o resto do script só lida com os automáticos

print(total_sb, "jogadores StatsBomb |", len(tm), "jogadores Transfermarkt ativos |",
      len(manuais), "correções manuais")


# ---------------------------------------------------------------------------
# Passo 2: normalizar nomes
# ---------------------------------------------------------------------------
# Letras que o NFKD NÃO decompõe em "letra + acento" (são letras próprias, não letras acentuadas).
LETRAS_ESPECIAIS = str.maketrans({"ø": "o", "æ": "ae", "ß": "ss", "ł": "l", "đ": "d", "ı": "i"})


def normalizar(nome) -> str:
    """'Álvaro  Morata' -> 'alvaro morata'. Sem acento, minúsculo, espaços simples."""
    if not isinstance(nome, str):  # None ou NaN
        return ""
    nome = nome.lower().translate(LETRAS_ESPECIAIS)
    nome = unicodedata.normalize("NFKD", nome)  # "á" vira "a" + acento solto
    nome = "".join(c for c in nome if not unicodedata.combining(c))  # descarta os acentos soltos
    nome = nome.replace("-", " ").replace("'", " ")  # "Pierre-Emile" ~ "Pierre Emile"
    return " ".join(nome.split())


assert normalizar("Álvaro  Morata") == "alvaro morata"
assert normalizar("Pierre-Emile Højbjerg") == "pierre emile hojbjerg"
assert normalizar(None) == ""

# Apelido quando existe; senão o nome completo. O Transfermarkt usa o nome "de camisa".
sb["chave"] = sb["apelido"].fillna(sb["nome"]).map(normalizar)
tm["chave"] = tm["tm_nome"].map(normalizar)


def variantes(nome_completo: str) -> list[str]:
    """Formas curtas do nome completo, para o passo 4.

    A StatsBomb usa nomes de registro ("Grant Campbell Hanley", "Alejandro Grimaldo García"),
    e o TM, o nome curto ("Grant Hanley", "Alejandro Grimaldo"). Testamos as duas formas comuns:
    primeiro + último nome (nome do meio) e primeiro + segundo (sobrenome duplo, comum em
    espanhóis e romenos).
    """
    p = normalizar(nome_completo).split()
    formas = [" ".join(p)]
    if len(p) >= 3:
        formas += [f"{p[0]} {p[-1]}", f"{p[0]} {p[1]}"]
    return formas


# ---------------------------------------------------------------------------
# Passo 3: casamento exato (nome normalizado + país)
# ---------------------------------------------------------------------------
# Por que incluir o país: existem vários "Danilo" e "Rodri" no Transfermarkt. Exigir a mesma
# nacionalidade elimina quase todos os homônimos.
pares = sb.merge(tm, left_on=["chave", "selecao"], right_on=["chave", "pais"])

# Ambíguo = um jogador StatsBomb casou com 2+ jogadores TM. Não escolhemos ao acaso:
# esses vão para o passo 4, que olha o nome completo.
qtd = pares.groupby("player_id")["tm_id"].transform("size")
ambiguos = pares.loc[qtd > 1, "player_id"].unique()
exatos = pares.loc[qtd == 1, ["player_id", "tm_id"]].assign(metodo="exato", nota=100.0)
print("exatos:", len(exatos), "| ambíguos:", len(ambiguos))


# ---------------------------------------------------------------------------
# Passo 4: casamento aproximado (fuzzy) para quem sobrou
# ---------------------------------------------------------------------------
# Um jogador TM só pode ser usado uma vez: quem já casou (manual ou exato) sai dos candidatos.
# Sem isso, "Daniel Olmo Carvajal" (variante "daniel carvajal") casava com o Dani Carvajal.
ja_usados = set(manuais["tm_id"]) | set(exatos["tm_id"])
livres = tm[~tm["tm_id"].isin(ja_usados)]
TM_POR_PAIS = {pais: grupo for pais, grupo in livres.groupby("pais")}


def melhor_candidato(chaves: list[str], pais: str) -> tuple[int | None, float, str | None]:
    """Procura o nome mais parecido entre os jogadores TM do mesmo país.

    Testa várias formas do nome e fica com a melhor nota. Se dois jogadores TM DIFERENTES
    empatam no topo, é ambíguo: devolve nota 0 em vez de escolher um ao acaso.
    Devolve (tm_id, nota, tm_nome); (None, 0, None) se não há candidato.
    """
    candidatos = TM_POR_PAIS.get(pais)
    if candidatos is None:
        return None, 0.0, None
    resultados = []  # (nota, rótulo da linha em `candidatos`)
    for chave in chaves:
        for _, nota, idx in process.extract(chave, candidatos["chave"],
                                            scorer=fuzz.token_sort_ratio, limit=2):
            resultados.append((nota, idx))
    if not resultados:
        return None, 0.0, None
    nota_max = max(n for n, _ in resultados)
    no_topo = {idx for n, idx in resultados if n == nota_max}
    idx = next(iter(no_topo))
    tm_id, tm_nome = int(candidatos.at[idx, "tm_id"]), candidatos.at[idx, "tm_nome"]
    if len(no_topo) > 1:
        return tm_id, 0.0, f"AMBÍGUO ({len(no_topo)} candidatos)"
    return tm_id, nota_max, tm_nome


restantes = sb[~sb["player_id"].isin(exatos["player_id"])]
linhas = []
for j in restantes.itertuples():
    tm_id, nota, tm_nome = melhor_candidato([j.chave, *variantes(j.nome)], j.selecao)
    linhas.append({"player_id": j.player_id, "nome": j.nome, "selecao": j.selecao,
                   "tm_id": tm_id, "tm_nome": tm_nome, "nota": nota})
fuzzy = pd.DataFrame(linhas, columns=["player_id", "nome", "selecao", "tm_id", "tm_nome", "nota"])

aceitos = fuzzy[fuzzy["nota"] >= NOTA_MINIMA]
aproximados = aceitos[["player_id", "tm_id", "nota"]].assign(metodo="aproximado")
sem_par = fuzzy[fuzzy["nota"] < NOTA_MINIMA]

# Os casos de nota mais baixa entre os aceitos são onde moram os erros: confira na mão.
print("\naproximados com nota mais baixa (confira):")
print(aceitos.sort_values("nota").head(10)[["nome", "tm_nome", "selecao", "nota"]].to_string(index=False))

ponte = pd.concat([manuais, exatos, aproximados], ignore_index=True)
assert ponte["player_id"].is_unique and ponte["tm_id"].is_unique, "casamento duplicado"
ponte["tm_id"] = ponte["tm_id"].astype("int64")
con.sql("CREATE OR REPLACE TABLE ponte_tm AS SELECT player_id, tm_id, metodo, nota FROM ponte")
print(f"\ncasados: {len(ponte)} de {total_sb} ({len(ponte) / total_sb:.1%})")
print(ponte["metodo"].value_counts().to_string())
print("sem par:", len(sem_par))
if len(sem_par):
    print(sem_par.sort_values("nota", ascending=False)[["nome", "selecao", "tm_nome", "nota"]]
          .to_string(index=False))


# ---------------------------------------------------------------------------
# Passo 5: idade e valor de mercado NA DATA DO TORNEIO
# ---------------------------------------------------------------------------
# Por que não usar market_value_in_eur do players.csv: é o valor ATUAL (2026). Usar esse valor
# para responder "quem era barato na Euro 2024?" é vazamento temporal (olhar o futuro).
#
# Idade: date_SUB conta anos COMPLETOS (respeita o aniversário). date_DIFF contaria só as
#   viradas de ano: Nico Williams (12/07/2002) sairia com 22 anos em 14/06/2024, mas tinha 21.
# Valor: ASOF JOIN pega, para cada jogador, a ÚLTIMA avaliação com data <= data do torneio.
#   valor_data fica na tabela para auditoria: uma avaliação muito antiga indica casamento suspeito.
con.sql(f"""
CREATE OR REPLACE TABLE jogadores_completo AS
WITH tm AS (
    SELECT p.player_id, p.tm_id, t.date_of_birth::DATE AS nascimento,
           DATE '{DATA_TORNEIO}' AS data_ref
    FROM ponte_tm p
    JOIN 'data/players.csv.gz' t ON t.player_id = p.tm_id
),
valor AS (
    -- avaliação com mais de 1 ano antes do torneio não diz quanto ele valia em 2024: vira NULL
    SELECT tm.player_id,
           CASE WHEN v.date >= tm.data_ref - INTERVAL 1 YEAR THEN v.market_value_in_eur END
               AS valor_mercado_eur,
           v.date AS valor_data
    FROM tm
    ASOF LEFT JOIN 'data/player_valuations.csv.gz' v
        ON tm.tm_id = v.player_id AND tm.data_ref >= v.date
)
SELECT j.*,
       tm.tm_id,
       date_sub('year', tm.nascimento, tm.data_ref) AS idade,
       v.valor_mercado_eur,
       v.valor_data
FROM jogadores j
LEFT JOIN tm USING (player_id)      -- quem ficou sem par entra com NULL, não some
LEFT JOIN valor v USING (player_id)
""")


# ---------------------------------------------------------------------------
# Passo 6: conferir com casos de resposta conhecida
# ---------------------------------------------------------------------------
#   - Cody Gakpo (Holanda): nascido em 07/05/1999 -> 25 anos na Euro
#   - Nico Williams (Espanha): nascido em 12/07/2002 -> 21 (fez 22 DURANTE o torneio)
#   - Lamine Yamal (Espanha): nascido em 13/07/2007 -> 16, o mais jovem do torneio
print(con.sql("""
    SELECT nome, selecao, idade, valor_mercado_eur, valor_data
    FROM jogadores_completo
    WHERE nome ILIKE '%Gakpo%' OR nome ILIKE '%Nicholas Williams%' OR nome ILIKE '%Yamal%'
"""))
casos = dict(con.sql("""
    SELECT nome, idade FROM jogadores_completo
    WHERE nome IN ('Cody Mathès Gakpo', 'Nicholas Williams Arthuer', 'Lamine Yamal Nasraoui Ebana')
""").fetchall())
assert casos == {"Cody Mathès Gakpo": 25, "Nicholas Williams Arthuer": 21,
                 "Lamine Yamal Nasraoui Ebana": 16}, casos
assert con.sql("SELECT nome FROM jogadores_completo ORDER BY idade LIMIT 1").fetchall()[0][0] \
    == "Lamine Yamal Nasraoui Ebana"

# Sanidade geral: na Euro 2024, o mais velho era o Pepe (41 anos); ninguém pode passar disso.
print(con.sql("""
    SELECT count(*) AS jogadores, count(idade) AS com_idade, count(valor_mercado_eur) AS com_valor,
           min(idade) AS idade_min, max(idade) AS idade_max,
           arg_max(nome, idade) AS mais_velho
    FROM jogadores_completo
"""))
assert con.sql("SELECT max(idade) FROM jogadores_completo").fetchall()[0][0] == 41

# Avaliações antigas demais sugerem casamento errado (ex.: um homônimo aposentado).
print("valor de mercado mais antigo que 2023 (suspeitos):")
print(con.sql("""
    SELECT nome, selecao, idade, valor_mercado_eur, valor_data
    FROM jogadores_completo WHERE valor_data < DATE '2023-01-01' ORDER BY valor_data
"""))
