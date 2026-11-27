"""Etapa 4: agente text-to-SQL. Pergunta em português -> SQL -> DuckDB -> resposta.

Fluxo:
    pergunta ──► LLM gera JSON {sql, explicacao} ──► Pydantic valida ──► DuckDB executa
                     ▲                                     │                   │
                     └──── erro volta para o LLM ◄─────────┴───────────────────┘
                           (no máximo MAX_TENTATIVAS vezes)

Uso:  python agente.py                      (modo interativo)
      python agente.py "quem fez mais gols?"
"""
import json
import sys

import duckdb
import pandas as pd
from pydantic import BaseModel, ValidationError, field_validator

from llm import conversar

MAX_TENTATIVAS = 3   # quantas vezes o LLM pode corrigir o próprio erro antes de desistir
LIMITE_LINHAS = 50   # teto de linhas devolvidas, aconteça o que acontecer com o SQL
TABELA = "jogadores_completo"


# ---------------------------------------------------------------------------
# 1. Conexão segura
# ---------------------------------------------------------------------------
def abrir_conexao() -> duckdb.DuckDBPyConnection:
    """Defesa em camadas: mesmo que um SQL malicioso passe pela validação do Pydantic,
    o banco não deixa fazer estrago.
      - read_only=True: bloqueia DROP, INSERT, UPDATE, CREATE...
      - enable_external_access=False: bloqueia ler arquivos do disco ou da internet
        (sem isso, "SELECT * FROM '/etc/passwd'" funcionaria).
    """
    return duckdb.connect("scout.duckdb", read_only=True,
                          config={"enable_external_access": False})


# ---------------------------------------------------------------------------
# 2. O que o LLM precisa saber sobre os dados
# ---------------------------------------------------------------------------
def descrever_schema(con: duckdb.DuckDBPyConnection) -> str:
    """Texto com as colunas da tabela e os valores possíveis de posicao_principal.

    Por que gerar a partir do banco (e não escrever à mão): se uma coluna mudar no
    montar_tabela.py, o prompt acompanha sozinho.
    """
    # DESCRIBE devolve uma linha por coluna: (nome, tipo, null, key, default, extra).
    colunas = con.sql(f"DESCRIBE {TABELA}").fetchall()
    linhas = [f"- {nome} ({tipo})" for nome, tipo, *_ in colunas]

    # As posições estão em inglês ("Left Back"). Sem ver os valores reais, o LLM
    # inventa um WHERE posicao_principal = 'Lateral' e volta vazio.
    posicoes = [p for (p,) in con.sql(
        f"SELECT DISTINCT posicao_principal FROM {TABELA} ORDER BY 1").fetchall()]
    linhas.append("\nValores possíveis de posicao_principal: " + ", ".join(posicoes))
    return "\n".join(linhas)


# REGRAS: conhecimento de domínio que o LLM não tem como adivinhar (vem das "Armadilhas já
# descobertas" do CLAUDE.md). Cada corte numérico foi escolhido olhando os dados:
#   - minutos >= 180: 2 jogos inteiros; mediana do torneio = 192 min; sobram 263 de 493.
#   - cruzamentos >= 5 / passes >= 50: sem mínimo, a maior taxa de cruzamento é 1 de 1 (100%).
#   - "barato" sem número NÃO vira teto: qualquer teto seria arbitrário (a mediana é 11 mi).

# Vocabulário de posições: termo em português -> valores de posicao_principal.
# Por que listar os valores exatos (e não deixar o LLM usar LIKE '%Back'): os zagueiros
# também terminam em "Back" (Left Center Back). Com IN (...) não há como misturar.
# Termos gerais incluem os específicos de propósito: "lateral" já cobre os alas.
# A posição é a que o jogador MAIS ocupou na Euro 2024, não a de origem
# (Trippier, lateral-direito de origem, aparece como Left Back).
POSICOES = {
    "goleiro":                    ["Goalkeeper"],
    "zagueiro / defensor central": ["Center Back", "Left Center Back", "Right Center Back"],
    "lateral":                    ["Left Back", "Right Back", "Left Wing Back", "Right Wing Back"],
    "lateral esquerdo":           ["Left Back", "Left Wing Back"],
    "lateral direito":            ["Right Back", "Right Wing Back"],
    "ala (lateral num esquema com 3 zagueiros)": ["Left Wing Back", "Right Wing Back"],
    "volante":                    ["Center Defensive Midfield", "Left Defensive Midfield",
                                   "Right Defensive Midfield"],
    "meio-campista central":      ["Left Center Midfield", "Right Center Midfield"],
    "meia ofensivo / meia armador / camisa 10": ["Center Attacking Midfield",
                                   "Left Attacking Midfield", "Right Attacking Midfield"],
    "meia aberto (pelos lados)":  ["Left Midfield", "Right Midfield"],
    "meio-campista / meia (geral)": ["Center Defensive Midfield", "Left Defensive Midfield",
                                   "Right Defensive Midfield", "Left Center Midfield",
                                   "Right Center Midfield", "Center Attacking Midfield",
                                   "Left Attacking Midfield", "Right Attacking Midfield",
                                   "Left Midfield", "Right Midfield"],
    "ponta / extremo":            ["Left Wing", "Right Wing"],
    "centroavante / camisa 9":    ["Center Forward"],
    "atacante (geral)":           ["Center Forward", "Left Center Forward", "Right Center Forward"],
    "defensor (geral)":           ["Center Back", "Left Center Back", "Right Center Back",
                                   "Left Back", "Right Back", "Left Wing Back", "Right Wing Back"],
}


def vocabulario_posicoes() -> str:
    """Transforma POSICOES em linhas de regra: - "lateral" = posicao_principal IN (...)"""
    return "\n".join(
        f'- "{termo}" = posicao_principal IN ({", ".join(repr(p) for p in valores)})'
        for termo, valores in POSICOES.items()
    )


REGRAS = """
- Use somente a tabela {tabela}. Escreva SQL do DuckDB.
- Responda SOMENTE com um JSON no formato {{"sql": "...", "explicacao": "..."}}.
- "explicacao" diz em uma frase, em português, como a consulta responde à pergunta.

Posições (use SEMPRE a lista exata com IN, nunca LIKE). A posição é a que o jogador mais
ocupou na Euro 2024. Se a pergunta citar um lado ("lateral esquerdo"), use o termo do lado:
""" + vocabulario_posicoes() + """

Vocabulário:
- "sub-N" = idade < N   (idade na abertura da Euro 2024)
- Nomes estão completos, como na StatsBomb ("Daniel Olmo Carvajal", "Kléper Laveran Lima
  Ferreira" = Pepe). Para achar um jogador, use nome ILIKE '%sobrenome%', nunca nome = '...'.
- Seleções estão em inglês: 'Spain', 'England', 'Netherlands', 'Turkey', 'Czech Republic'...

Métricas:
- Contagens (gols, chutes, cruzamentos...) são o TOTAL no torneio. Para "quem fez mais X",
  use o total.
- Para qualidade ("cruza bem", "chuta muito", "bom driblador"), use a coluna X_p90 (por 90
  minutos) e exija minutos >= 180. Sem esse mínimo, quem jogou 10 minutos e cruzou uma vez
  lidera o ranking.
- Taxas (taxa_acerto_passe, taxa_acerto_cruzamento) vão de 0 a 1 (0.5 = 50%) e são NULL
  quando o jogador não tentou. Ao ordenar por taxa, exija um mínimo de tentativas:
  cruzamentos >= 5 para taxa_acerto_cruzamento e passes >= 50 para taxa_acerto_passe.
  Sem isso, quem acertou 1 de 1 aparece com 100%.
- "Cruzamento certo" = cruzamentos_certos. Gols contra não contam para ninguém.

Valor de mercado:
- valor_mercado_eur está em euros, medido em junho de 2024. "10 milhões" = 10000000.
- "Barato" / "custa pouco" SEM número: não invente um teto. Ordene primeiro pelo desempenho
  pedido (DESC) e inclua valor_mercado_eur no resultado para o usuário comparar os preços.
  Se a pergunta for só sobre preço ("os mais baratos"), ordene por valor_mercado_eur ASC.
- Com número ("até 5 milhões"), filtre: valor_mercado_eur <= 5000000.
- valor_mercado_eur é NULL para 9 jogadores sem avaliação. Ao filtrar ou ordenar por valor,
  esses ficam de fora ou no fim (NULLS LAST).

Resultado:
- Sempre inclua nome, selecao e posicao_principal, mais toda coluna usada em WHERE ou ORDER BY
  (assim o usuário confere por que cada jogador apareceu). Inclua minutos quando filtrar por eles.
- Em todo ORDER BY, escreva NULLS LAST.
- Para "quem é o maior/melhor/mais...", NÃO use LIMIT 1: pode haver empate no topo, e
  LIMIT 1 esconderia os outros empatados. Use LIMIT 10 ou WHERE X = (SELECT max(X) FROM {tabela}).
- Sem quantidade pedida, use LIMIT 10. Para perguntas de contagem ("quantos..."), devolva
  count(*).
"""

PROMPT_SISTEMA = """Você é um analista de scout de futebol. Os dados são da Euro 2024.
Transforme a pergunta do usuário numa consulta SQL.

Tabela {tabela}:
{schema}

Regras:
{regras}"""


# ---------------------------------------------------------------------------
# 3. A saída do LLM, validada
# ---------------------------------------------------------------------------
class ConsultaSQL(BaseModel):
    """O formato que exigimos do LLM. Se ele devolver outra coisa, o Pydantic recusa
    e a mensagem de erro volta para o LLM corrigir."""
    sql: str
    explicacao: str

    @field_validator("sql")
    @classmethod
    def so_select(cls, sql: str) -> str:
        # Por que validar, se a conexão já é read_only: a mensagem daqui é clara para o LLM
        # corrigir ("só SELECT"), enquanto o erro do DuckDB seria genérico. E uma camada a mais
        # de defesa não custa nada.
        sql = sql.strip().rstrip(";").strip()  # o ";" final é inofensivo: só tiramos
        if not sql.lower().startswith(("select", "with")):
            raise ValueError("a consulta deve começar com SELECT ou WITH (só leitura é permitida)")
        if ";" in sql:
            # Um ";" no meio separa duas instruções ("SELECT ...; DROP TABLE ..."). Efeito
            # colateral aceito: um ';' dentro de um texto ('%;%') também é recusado. Em
            # perguntas de scout isso não acontece, e a regra fica simples de explicar.
            raise ValueError("envie uma única instrução SQL, sem ';' no meio")
        return sql


def extrair_json(texto: str) -> str:
    """LLMs costumam embrulhar o JSON em ```json ... ```. Devolve só o JSON."""
    # Do primeiro "{" ao último "}": funciona com ou sem ```, e também quando o LLM escreve
    # uma frase antes ("Claro! Aqui está: {...}").
    inicio, fim = texto.find("{"), texto.rfind("}")
    if inicio == -1 or fim < inicio:
        # Sem JSON: devolve o texto como veio. O Pydantic vai recusar com uma mensagem que
        # volta para o LLM, e ele tenta de novo. Não é papel desta função decidir isso.
        return texto
    return texto[inicio:fim + 1]


# ---------------------------------------------------------------------------
# 4. Execução
# ---------------------------------------------------------------------------
def executar(con: duckdb.DuckDBPyConnection, sql: str) -> pd.DataFrame:
    """Roda o SQL e devolve no máximo LIMITE_LINHAS linhas, mesmo que o LLM esqueça o LIMIT.

    Por que fetchmany em vez de embrulhar em "SELECT * FROM (<sql>) LIMIT n":
      - o SQL padrão não garante que a ordem do ORDER BY de dentro sobreviva ao SELECT
        de fora, e num ranking a ordem É a resposta;
      - um comentário "-- ..." no fim do SQL do LLM engoliria o ")" do embrulho.
    fetchmany pede ao banco só as primeiras n linhas do resultado, na ordem em que vieram.
    """
    cursor = con.execute(sql)
    colunas = [descricao[0] for descricao in cursor.description]
    return pd.DataFrame(cursor.fetchmany(LIMITE_LINHAS), columns=colunas)


# ---------------------------------------------------------------------------
# 5. O laço do agente: gerar -> validar -> executar -> (corrigir)
# ---------------------------------------------------------------------------
def responder(pergunta: str, con: duckdb.DuckDBPyConnection) -> tuple[ConsultaSQL, pd.DataFrame]:
    """Devolve a consulta usada e o resultado. Levanta RuntimeError se não conseguir."""
    sistema = PROMPT_SISTEMA.format(tabela=TABELA, schema=descrever_schema(con),
                                    regras=REGRAS.format(tabela=TABELA))
    mensagens = [{"role": "system", "content": sistema},
                 {"role": "user", "content": pergunta}]

    # Por que devolver o erro ao LLM em vez de só tentar de novo: ele vê "coluna 'idade_anos'
    # não existe, candidatas: idade" e acerta na segunda. Tentar de novo às cegas repetiria o
    # mesmo erro (com temperatura 0, literalmente o mesmo SQL).
    ultimo_erro = None
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        texto = conversar(mensagens)
        try:
            consulta = ConsultaSQL.model_validate_json(extrair_json(texto))
            resultado = executar(con, consulta.sql)
            return consulta, resultado
        except (ValidationError, duckdb.Error) as erro:
            # Só erros que o LLM pode corrigir voltam para ele. Erro de rede/API (em llm.py)
            # sobe direto: reescrever o SQL não resolve servidor fora do ar.
            ultimo_erro = erro
            print(f"  [tentativa {tentativa}/{MAX_TENTATIVAS} falhou] {type(erro).__name__}: "
                  f"{str(erro).splitlines()[0][:150]}")
            mensagens += [
                {"role": "assistant", "content": texto},
                {"role": "user", "content": f"Erro: {erro}\nCorrija e responda só o JSON."},
            ]
    raise RuntimeError(f"{MAX_TENTATIVAS} tentativas falharam. Último erro: {ultimo_erro}")


# TODO 9 (opcional, depois que o resto funcionar): uma segunda chamada ao LLM que recebe a
#   pergunta + a tabela de resultado (resultado.to_markdown() ou to_string()) e escreve uma
#   resposta curta em português, como um scout falaria. Regra no prompt: usar SÓ os números
#   da tabela (para o LLM não inventar dados que não vieram do banco).


# ---------------------------------------------------------------------------
# 6. Interface de linha de comando
# ---------------------------------------------------------------------------
def main() -> None:
    con = abrir_conexao()
    perguntas = [" ".join(sys.argv[1:])] if len(sys.argv) > 1 else None
    while True:
        pergunta = perguntas.pop() if perguntas else input("\nPergunta (Enter para sair): ").strip()
        if not pergunta:
            break
        try:
            consulta, resultado = responder(pergunta, con)
        except RuntimeError as erro:
            print("Não consegui responder:", erro)
        else:
            print("\nSQL:", consulta.sql)
            print("Como:", consulta.explicacao)
            print(resultado.to_string(index=False) if len(resultado) else "(nenhum jogador encontrado)")
        if len(sys.argv) > 1:
            break


# Casos de resposta conhecida para conferir à mão (a etapa 5 vai automatizar isso):
#   "quem fez mais gols?"                   -> 6 empatados com 3: Kane, Musiala, Gakpo, Olmo,
#                                              Schranz, Mikautadze (a chuteira de ouro foi dividida)
#   "quantos laterais sub-23 jogaram?"      -> 9
#   "quem é o jogador mais novo?"           -> Lamine Yamal, 16 anos
#   "me ache um lateral sub-23 que cruza bem e custa pouco"
#                                           -> Nicola Zalewski deve aparecer no topo (ver README)

if __name__ == "__main__":
    main()
