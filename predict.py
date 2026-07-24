"""
Brasileirão Série A - Predictor automático (v2)
Modelo mejorado: splits local/visitante, forma reciente ponderada,
y ajuste por historial head-to-head directo entre los dos equipos.
 
Requiere la variable de entorno FOOTBALL_DATA_API_KEY.
"""
 
import os
import json
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import urllib.request
import urllib.error
 
API_BASE = "https://api.football-data.org/v4"
COMPETITION = "BSA"
MAX_GOALS = 8
DAYS_AHEAD = 10
RECENT_N = 6            # cuántos partidos recientes cuentan como "forma"
W_SEASON = 0.6           # peso del promedio de temporada (local/visitante)
W_FORM = 0.4             # peso de la forma reciente
H2H_MIN_MATCHES = 3      # mínimo de enfrentamientos directos para aplicar ajuste
H2H_MAX_ADJUST = 0.08    # ajuste máximo (+/-8%) por head-to-head
REQUEST_DELAY = 6.5      # segundos entre llamadas para respetar 10 req/min
 
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
 
 
def get_finished_matches():
    data = api_get(f"/competitions/{COMPETITION}/matches?status=FINISHED")
    matches = []
    for m in data.get("matches", []):
        if m["score"]["fullTime"]["home"] is None:
            continue
        matches.append({
            "utcDate": m["utcDate"],
            "home": m["homeTeam"]["name"],
            "away": m["awayTeam"]["name"],
            "homeGoals": m["score"]["fullTime"]["home"],
            "awayGoals": m["score"]["fullTime"]["away"],
        })
    matches.sort(key=lambda m: m["utcDate"])
    return matches
 
 
def get_upcoming_matches():
    date_from = datetime.now(timezone.utc).date().isoformat()
    date_to = (datetime.now(timezone.utc).date() + timedelta(days=DAYS_AHEAD)).isoformat()
    data = api_get(
        f"/competitions/{COMPETITION}/matches?status=SCHEDULED&dateFrom={date_from}&dateTo={date_to}"
    )
    matches = []
    for m in data.get("matches", []):
        matches.append({
            "id": m["id"],
            "utcDate": m["utcDate"],
            "home": m["homeTeam"]["name"],
            "away": m["awayTeam"]["name"],
            "matchday": m.get("matchday"),
        })
    return matches
 
 
def get_head2head(match_id):
    time.sleep(REQUEST_DELAY)
    try:
        data = api_get(f"/matches/{match_id}/head2head?limit=10")
    except SystemExit:
        # si falla por lo que sea, seguimos sin ajuste de h2h en vez de tronar todo el run
        return None
    return data.get("aggregates")
 
 
def build_team_stats(finished_matches):
    """
    Devuelve, por equipo:
      home: {gp, gf, gc}   -> jugando de local
      away: {gp, gf, gc}   -> jugando de visitante
      recent: lista de los últimos partidos (dict con gf/gc desde la
              perspectiva del equipo), más reciente primero
    """
    stats = defaultdict(lambda: {
        "home": {"gp": 0, "gf": 0, "gc": 0},
        "away": {"gp": 0, "gf": 0, "gc": 0},
        "all_matches": [],  # cronológico, para sacar forma reciente
    })
 
    for m in finished_matches:
        h, a = m["home"], m["away"]
        hg, ag = m["homeGoals"], m["awayGoals"]
 
        stats[h]["home"]["gp"] += 1
        stats[h]["home"]["gf"] += hg
        stats[h]["home"]["gc"] += ag
        stats[h]["all_matches"].append({"gf": hg, "gc": ag})
 
        stats[a]["away"]["gp"] += 1
        stats[a]["away"]["gf"] += ag
        stats[a]["away"]["gc"] += hg
        stats[a]["all_matches"].append({"gf": ag, "gc": hg})
 
    return stats
 
 
def league_home_away_avg(finished_matches):
    total_home_games = len(finished_matches)
    total_away_games = len(finished_matches)  # mismo número, cada partido tiene 1 local y 1 visitante
    if total_home_games == 0:
        return 1.45, 1.15  # fallback razonable (promedios típicos de local/visitante en fútbol)
    total_home_goals = sum(m["homeGoals"] for m in finished_matches)
    total_away_goals = sum(m["awayGoals"] for m in finished_matches)
    return (total_home_goals / total_home_games), (total_away_goals / total_away_games)
 
 
def recent_form_rate(team_stats, n, league_avg_generic):
    """Promedio de gf/gc de los últimos n partidos del equipo (cualquier venue),
    expresado como ratio contra el promedio genérico de la liga."""
    recent = team_stats["all_matches"][-n:]
    if not recent:
        return 1.0, 1.0
    avg_gf = sum(x["gf"] for x in recent) / len(recent)
    avg_gc = sum(x["gc"] for x in recent) / len(recent)
    return (avg_gf / league_avg_generic), (avg_gc / league_avg_generic)
 
 
def poisson_p(lam, k):
    return math.exp(-lam) * (lam ** k) / math.factorial(k)
 
 
def h2h_adjustment(aggregates, home_name, away_name):
    """Devuelve (factor_home, factor_away) basado en historial directo.
    Conservador: solo ajusta si hay suficientes enfrentamientos previos."""
    if not aggregates:
        return 1.0, 1.0
    n = aggregates.get("numberOfMatches", 0)
    if n < H2H_MIN_MATCHES:
        return 1.0, 1.0
 
    home_wins = aggregates.get("homeTeam", {}).get("wins", 0)
    away_wins = aggregates.get("awayTeam", {}).get("wins", 0)
    draws = aggregates.get("homeTeam", {}).get("draws", 0) or (n - home_wins - away_wins)
 
    home_rate = home_wins / n
    away_rate = away_wins / n
 
    # dominancia neta entre -1 (visitante domina) y +1 (local domina)
    dominance = home_rate - away_rate
    adjust = dominance * H2H_MAX_ADJUST  # escala a un +/-8% máximo
 
    return (1 + adjust), (1 - adjust)
 
 
def predict_match(home, away, team_stats, league_home_avg, league_away_avg, league_generic_avg, h2h_agg):
    h = team_stats.get(home)
    a = team_stats.get(away)
 
    def safe_ratio(gf, gp, league_avg):
        return (gf / gp) / league_avg if gp > 0 else 1.0
 
    # --- splits local/visitante (temporada completa) ---
    home_attack_season = safe_ratio(h["home"]["gf"], h["home"]["gp"], league_home_avg) if h else 1.0
    home_defense_season = safe_ratio(h["home"]["gc"], h["home"]["gp"], league_away_avg) if h else 1.0
    away_attack_season = safe_ratio(a["away"]["gf"], a["away"]["gp"], league_away_avg) if a else 1.0
    away_defense_season = safe_ratio(a["away"]["gc"], a["away"]["gp"], league_home_avg) if a else 1.0
 
    # --- forma reciente (últimos N partidos, cualquier venue) ---
    home_form_attack, home_form_defense = recent_form_rate(h, RECENT_N, league_generic_avg) if h else (1.0, 1.0)
    away_form_attack, away_form_defense = recent_form_rate(a, RECENT_N, league_generic_avg) if a else (1.0, 1.0)
 
    # --- blend season + forma ---
    home_attack = W_SEASON * home_attack_season + W_FORM * home_form_attack
    home_defense = W_SEASON * home_defense_season + W_FORM * home_form_defense
    away_attack = W_SEASON * away_attack_season + W_FORM * away_form_attack
    away_defense = W_SEASON * away_defense_season + W_FORM * away_form_defense
 
    xg_home = league_home_avg * home_attack * away_defense
    xg_away = league_away_avg * away_attack * home_defense
 
    # --- ajuste head-to-head ---
    f_home, f_away = h2h_adjustment(h2h_agg, home, away)
    xg_home *= f_home
    xg_away *= f_away
 
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
        "h2hMatchesConsidered": (h2h_agg or {}).get("numberOfMatches", 0),
    }
 
 
def main():
    if not API_KEY:
        print("Falta la variable de entorno FOOTBALL_DATA_API_KEY", file=sys.stderr)
        sys.exit(1)
 
    finished = get_finished_matches()
    team_stats = build_team_stats(finished)
    league_home_avg, league_away_avg = league_home_away_avg(finished)
    league_generic_avg = (league_home_avg + league_away_avg) / 2
 
    upcoming = get_upcoming_matches()
 
    results = []
    for m in upcoming:
        h2h_agg = get_head2head(m["id"])
        pred = predict_match(
            m["home"], m["away"], team_stats,
            league_home_avg, league_away_avg, league_generic_avg,
            h2h_agg,
        )
        results.append({**m, "prediction": pred})
 
    output = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "competition": "Brasileirão Série A",
        "model": "poisson-v2-home_away_splits-recent_form-h2h",
        "leagueAvgGoals": round(league_generic_avg, 2),
        "leagueAvgHomeGoals": round(league_home_avg, 2),
        "leagueAvgAwayGoals": round(league_away_avg, 2),
        "matches": results,
    }
 
    os.makedirs("data", exist_ok=True)
    with open("data/predictions.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
 
    print(f"Guardado data/predictions.json con {len(results)} partidos (modelo v2).")
 
 
if __name__ == "__main__":
    main()
