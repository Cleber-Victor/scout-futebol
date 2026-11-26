"""Baixa todos os jogos da Euro 2024 (StatsBomb Open Data) e salva em data/.

Gera três arquivos Parquet:
  data/jogos.parquet       - um jogo por linha
  data/eventos.parquet     - todos os eventos de todos os jogos, com a coluna match_id
  data/escalacoes.parquet  - cada trecho em que um jogador ocupou uma posição

Uso:  python baixar.py   (leva alguns minutos)
"""
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore", category=UserWarning)  # aviso de "sem credenciais" da API aberta
from statsbombpy import sb

PASTA = Path("data")
PASTA.mkdir(exist_ok=True)

# Euro 2024 = competition_id 55, season_id 282
jogos = sb.matches(competition_id=55, season_id=282)
jogos.to_parquet(PASTA / "jogos.parquet")

todos_eventos, todas_escalacoes = [], []
for match_id in jogos["match_id"]:
    print("baixando", match_id)

    ev = sb.events(match_id=match_id)
    ev["match_id"] = match_id
    todos_eventos.append(ev)

    escalacoes = sb.lineups(match_id=match_id)  # dict: {seleção: DataFrame}
    for time, df in escalacoes.items():
        for _, jogador in df.iterrows():
            # um jogador pode ter várias posições no mesmo jogo -> uma linha por posição
            for pos in jogador["positions"]:
                todas_escalacoes.append({
                    "match_id": match_id,
                    "time": time,
                    "player_id": jogador["player_id"],
                    "player_name": jogador["player_name"],
                    "position": pos["position"],
                    "from": pos["from"],
                    "to": pos["to"],  # None = ficou até o fim
                    "from_period": pos["from_period"],
                    "to_period": pos["to_period"],
                })

eventos = pd.concat(todos_eventos, ignore_index=True)
eventos.to_parquet(PASTA / "eventos.parquet")

escalacoes_df = pd.DataFrame(todas_escalacoes)
escalacoes_df.to_parquet(PASTA / "escalacoes.parquet")

print(len(eventos), "eventos e", len(escalacoes_df), "linhas de escalação salvos em", PASTA)
