# brasileirao-alertas

Predictor automático de partidos del **Brasileirão Série A**, usando la API de
[football-data.org](https://www.football-data.org/) y un modelo de Poisson
(fuerza de ataque/defensa + ventaja de local).

Corre solo, todos los días, vía GitHub Actions, y deja el resultado en
`data/predictions.json`.

## Setup (una sola vez)

1. **Crea el repo en GitHub** (por ejemplo `brasileirao-alertas`) y sube estos
   archivos (`predict.py`, `.github/workflows/predict.yml`, este `README.md`).

2. **Consigue tu API key** en https://www.football-data.org/client/register
   (plan gratis, 10 requests/minuto).

3. **Agrega la key como secret del repo:**
   - Ve a tu repo → `Settings` → `Secrets and variables` → `Actions`
   - `New repository secret`
   - Name: `FOOTBALL_DATA_API_KEY`
   - Value: (tu key)

4. **Verifica permisos de Actions:**
   - `Settings` → `Actions` → `General` → `Workflow permissions`
   - Selecciona `Read and write permissions`

5. Listo. El workflow corre automáticamente todos los días a las 09:00 UTC,
   o puedes lanzarlo manual desde la pestaña `Actions` → `Brasileirão
   Predictor` → `Run workflow`.

## ¿Qué hace `predict.py`?

1. Trae la tabla de posiciones actual (goles a favor/en contra, partidos
   jugados) de cada equipo.
2. Trae los partidos programados en los próximos 10 días.
3. Calcula, para cada partido, goles esperados (xG) de local y visitante,
   probabilidad de victoria local / empate / victoria visitante, y el
   marcador más probable.
4. Guarda todo en `data/predictions.json`.

## Formato de salida

```json
{
  "generatedAt": "2026-07-24T09:00:00+00:00",
  "competition": "Brasileirão Série A",
  "leagueAvgGoals": 1.32,
  "matches": [
    {
      "id": 123456,
      "utcDate": "2026-07-27T20:00:00Z",
      "home": "Flamengo",
      "away": "Palmeiras",
      "matchday": 20,
      "prediction": {
        "xgHome": 1.71,
        "xgAway": 1.05,
        "probHome": 48.2,
        "probDraw": 26.1,
        "probAway": 25.7,
        "likelyScore": "2-1"
      }
    }
  ]
}
```

## Notas

- El modelo se pone más confiable a medida que avanza la temporada (más
  partidos jugados = mejores promedios). Al inicio de temporada las
  probabilidades son más ruidosas.
- Si quieres visualizar `predictions.json` con una interfaz bonita, se puede
  armar una página estática simple que lea ese archivo directamente desde
  `raw.githubusercontent.com` — avísame y la armamos.
- Límite del plan gratis de football-data.org: 10 requests/min. Este script
  hace 2 requests por corrida, así que sobra margen incluso si lo corres
  varias veces al día.
