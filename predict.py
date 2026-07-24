"""
Brasileirão Série A - Predictor automático
Consume la API de football-data.org (v4), calcula probabilidades con un
modelo de Poisson (fuerza de ataque/defensa) para los próximos partidos,
y guarda el resultado en data/predictions.json.

Requiere la variable de entorno FOOTBALL_DATA_API_KEY (se pasa como
GitHub Secret en el workflow, o localmente via export).
"""

import os
import json
import math
import sys
from datetime import datetime, timedelta, timezone
import urllib.request
import urllib.error

API_BASE = "https://api.football-data.org/v4"
COMPETITION = "BSA"  # Brasileirão Série A
HOME_ADV = 1.15
MAX_GOALS = 8
DAYS_AHEAD = 10  # ventana para "próximos partidos"

API_KEY = os.environ.get("FOOTBALL_DATA_API_KEY")


def api_get(path):
    url = f"{API_BASE}{path}"
    req = urllib.request.Request(url, headers={"X-Auth-Token": API_KEY})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"Error HTTP {e.code} llamando {url}: {body}", file=sys.stderr)
        sys.exit(1)


def get_standings():
    """Devuelve dict {team_name: {pj, gf, gc}} desde la tabla de posiciones."""
    data = api_get(f"/competitions/{COMPETITION}/standings")
    stats = {}
    for table_group in data.get("standings", []):
        if table_group.get("type") != "TOTAL":
            continue
        for row in table_group.get("table", []):
            team = row["team"]["name"]
            stats[team] = {
                "pj": row["playedGames"],
                "gf": row["goalsFor"],
                "gc": row["goalsAgainst"],
            }
    return stats


def get_upcoming_matches():
    date_from = datetime.now(timezone.utc).date().isoformat()
    date_to = (datetime.now(timezone.utc).date() + timedelta(days=DAYS_AHEAD)).isoformat()
    data = api_get(
        f"/competitions/{COMPETITION}/matches?status=SCHEDULED&dateFrom={date_from}&dateTo={date_to}"
    )
    matches = []
    for m in data.get("matches", []):
        matches.append(
            {
                "id": m["id"],
                "utcDate": m["utcDate"],
                "home": m["homeTeam"]["name"],
                "away": m["awayTeam"]["name"],
                "matchday": m.get("matchday"),
            }
        )
    return matches


def poisson_p(lam, k):
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def league_avg_goals(stats):
    total_goals = sum(s["gf"] for s in stats.values())
    total_matches = sum(s["pj"] for s in stats.values())
    if total_matches == 0:
        return 1.3
    return total_goals / total_matches


def predict_match(home, away, stats, league_avg):
    h = stats.get(home, {"pj": 0, "gf": 0, "gc": 0})
    a = stats.get(away, {"pj": 0, "gf": 0, "gc": 0})

    def safe(n, d):
        return (n / d) if d > 0 else league_avg

    home_attack = safe(h["gf"], h["pj"]) / league_avg
    home_defense = safe(h["gc"], h["pj"]) / league_avg
    away_attack = safe(a["gf"], a["pj"]) / league_avg
    away_defense = safe(a["gc"], a["pj"]) / league_avg

    xg_home = league_avg * home_attack * away_defense * HOME_ADV
    xg_away = league_avg * away_attack * home_defense / HOME_ADV

    p_home = p_draw = p_away = 0.0
    best = {"h": 0, "a": 0, "p": -1}
    for hg in range(MAX_GOALS + 1):
        for ag in range(MAX_GOALS + 1):
            p = poisson_p(xg_home, hg) * poisson_p(xg_away, ag)
            if hg > ag:
                p_home += p
            elif hg == ag:
                p_draw += p
            else:
                p_away += p
            if p > best["p"]:
                best = {"h": hg, "a": ag, "p": p}

    return {
        "xgHome": round(xg_home, 2),
        "xgAway": round(xg_away, 2),
        "probHome": round(p_home * 100, 1),
        "probDraw": round(p_draw * 100, 1),
        "probAway": round(p_away * 100, 1),
        "likelyScore": f"{best['h']}-{best['a']}",
    }


def main():
    if not API_KEY:
        print("Falta la variable de entorno FOOTBALL_DATA_API_KEY", file=sys.stderr)
        sys.exit(1)

    stats = get_standings()
    league_avg = league_avg_goals(stats)
    matches = get_upcoming_matches()

    results = []
    for m in matches:
        pred = predict_match(m["home"], m["away"], stats, league_avg)
        results.append({**m, "prediction": pred})

    output = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "competition": "Brasileirão Série A",
        "leagueAvgGoals": round(league_avg, 2),
        "matches": results,
    }

    os.makedirs("data", exist_ok=True)
    with open("data/predictions.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Guardado data/predictions.json con {len(results)} partidos.")


if __name__ == "__main__":
    main()
