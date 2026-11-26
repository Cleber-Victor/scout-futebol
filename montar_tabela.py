"""Transforma os eventos da Euro 2024 numa tabela de jogadores (uma linha por jogador) no DuckDB.

Rode depois do baixar.py:  python montar_tabela.py
Gera o arquivo scout.duckdb com as tabelas: minutos, estatisticas, jogadores.
"""
import duckdb

con = duckdb.connect("scout.duckdb")

# 1) Minutos jogados e posição principal ("cartão de ponto": última saída - primeira entrada, por jogo)
con.sql("""
CREATE OR REPLACE TABLE minutos AS
WITH fim AS (
    SELECT match_id, max(minute + second / 60.0) AS fim
    FROM 'data/eventos.parquet'
    WHERE period < 5                      -- ignora a disputa de pênaltis
    GROUP BY match_id
),
trechos AS (
    SELECT e.match_id, e.player_id, e.player_name, e.time, e.position,
           split_part("from", ':', 1)::INT + split_part("from", ':', 2)::INT / 60.0 AS ini,
           coalesce(split_part("to", ':', 1)::INT + split_part("to", ':', 2)::INT / 60.0, f.fim) AS ate
    FROM 'data/escalacoes.parquet' e
    JOIN fim f USING (match_id)
),
por_jogo AS (
    SELECT match_id, player_id,
           any_value(player_name) AS nome,
           any_value(time) AS selecao,
           max(ate) - min(ini) AS minutos
    FROM trechos
    GROUP BY match_id, player_id
),
posicao AS (
    SELECT player_id, arg_max(position, tempo) AS posicao_principal
    FROM (SELECT player_id, position, sum(ate - ini) AS tempo
          FROM trechos GROUP BY player_id, position)
    GROUP BY player_id
)
SELECT p.player_id,
       any_value(p.nome) AS nome,
       any_value(p.selecao) AS selecao,
       count(*) AS jogos,
       round(sum(p.minutos)) AS minutos,
       any_value(pos.posicao_principal) AS posicao_principal
FROM por_jogo p
JOIN posicao pos USING (player_id)
GROUP BY p.player_id
""")

# 2) Contagens por jogador. Lembrete: no StatsBomb, pass_outcome vazio = passe completo.
con.sql("""
CREATE OR REPLACE TABLE estatisticas AS
SELECT player_id::BIGINT AS player_id,
       count(*) FILTER (WHERE type = 'Pass')                                       AS passes,
       count(*) FILTER (WHERE type = 'Pass' AND pass_outcome IS NULL)              AS passes_certos,
       count(*) FILTER (WHERE type = 'Pass' AND pass_cross)                        AS cruzamentos,
       count(*) FILTER (WHERE type = 'Pass' AND pass_cross AND pass_outcome IS NULL) AS cruzamentos_certos,
       count(*) FILTER (WHERE type = 'Pass' AND pass_goal_assist)                  AS assistencias,
       count(*) FILTER (WHERE type = 'Shot')                                       AS chutes,
       count(*) FILTER (WHERE type = 'Shot' AND shot_outcome = 'Goal')             AS gols,
       count(*) FILTER (WHERE type = 'Dribble' AND dribble_outcome = 'Complete')   AS dribles_certos
FROM 'data/eventos.parquet'
WHERE player_id IS NOT NULL
  AND period < 5                          -- pênaltis da disputa não contam como gol
GROUP BY player_id
""")

# 3) Tabela final: minutos + estatísticas + métricas por 90 minutos e taxas de acerto.
#    É ESTA tabela que o LLM vai consultar na etapa 4, por isso os nomes são claros e em português.
con.sql("""
CREATE OR REPLACE TABLE jogadores AS
SELECT m.player_id, m.nome, m.selecao, m.posicao_principal, m.jogos, m.minutos,
       coalesce(e.passes, 0)             AS passes,
       coalesce(e.cruzamentos, 0)        AS cruzamentos,
       coalesce(e.cruzamentos_certos, 0) AS cruzamentos_certos,
       coalesce(e.assistencias, 0)       AS assistencias,
       coalesce(e.chutes, 0)             AS chutes,
       coalesce(e.gols, 0)               AS gols,
       coalesce(e.dribles_certos, 0)     AS dribles_certos,
       -- por 90 minutos: compara quem jogou muito com quem jogou pouco
       round(coalesce(e.cruzamentos, 0)        * 90 / m.minutos, 2) AS cruzamentos_p90,
       round(coalesce(e.cruzamentos_certos, 0) * 90 / m.minutos, 2) AS cruzamentos_certos_p90,
       round(coalesce(e.chutes, 0)             * 90 / m.minutos, 2) AS chutes_p90,
       round(coalesce(e.dribles_certos, 0)     * 90 / m.minutos, 2) AS dribles_certos_p90,
       -- taxas: NULL quando não houve tentativa (evita divisão por zero)
       round(e.passes_certos      / nullif(e.passes, 0), 3)      AS taxa_acerto_passe,
       round(e.cruzamentos_certos / nullif(e.cruzamentos, 0), 3) AS taxa_acerto_cruzamento
FROM minutos m
LEFT JOIN estatisticas e USING (player_id)
WHERE m.minutos > 0
""")

print(con.sql("SELECT count(*) AS jogadores FROM jogadores"))
print(con.sql("""
    SELECT nome, selecao, posicao_principal, minutos, cruzamentos, cruzamentos_certos,
           cruzamentos_p90, taxa_acerto_cruzamento
    FROM jogadores
    WHERE minutos >= 270
    ORDER BY cruzamentos_certos_p90 DESC
    LIMIT 10
"""))
