"""Exploração inicial dos dados da StatsBomb: a final da Euro 2024.

Mostra a estrutura dos jogos e dos eventos e conta os cruzamentos (e quantos deram certo)
de cada seleção na final.  Uso:  python explorar.py
"""
import warnings

warnings.filterwarnings("ignore", category=UserWarning)  # aviso de "sem credenciais" da API aberta
from statsbombpy import sb

# Euro 2024 = competition_id 55, season_id 282
jogos = sb.matches(competition_id=55, season_id=282)
print(len(jogos), "jogos")
print(jogos.columns.tolist())

# A final: filtra pela fase da competição e pega o match_id
final = jogos[jogos["competition_stage"] == "Final"]
print(final[["match_id", "home_team", "away_team", "match_date"]])
match_id_final = final["match_id"].iloc[0]

# Eventos: uma linha por ação do jogo (passe, chute, pressão...)
eventos = sb.events(match_id=match_id_final)
print(len(eventos), "eventos")
print(eventos["type"].value_counts())

# Cruzamentos: pass_cross == True. Na StatsBomb, pass_outcome vazio = passe certo.
passes = eventos[eventos["type"] == "Pass"]
cruzamentos = passes[passes["pass_cross"] == True]
certos = cruzamentos[cruzamentos["pass_outcome"].isna()]
print(len(certos), "cruzamentos certos de", len(cruzamentos))

print(cruzamentos.groupby("team")["pass_outcome"].agg(
    cruzamentos="size",
    certos=lambda s: s.isna().sum(),
))
