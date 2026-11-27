# rl_trader – Eigenständiger RL-Handelsprototyp

Kausale, framework-freie MDP-Trading-Umgebung mit PPO-Agent (PyTorch). Der Agent
lernt aus den Turning-Point-Signalen der drei Profile (`ml4t`, `baseline`,
`sma_auto`) und den Roh-Kurs-/Volatilitätsdaten.

## Struktur

```text
rl_trader/
├── README.md
├── env.py          # Datensignale + kausale Trading-Umgebung (Gymnasium)
├── train_rl.py     # PPO-Training (eigene Implementierung, kein SB3)
├── eval_rl.py      # Agent vs. Baselines, Test/OOT, Kennzahlen & Charts
└── runs/           # Checkpoints, Logs, Metriken, Plots (gitignored)
```

## Daten & Splits

* Rohdaten im **Data-Root**: `raw_data/*.csv` (27 Ticker/Timeframe-Serien).
  Der Data-Root wird automatisch erkannt (Repo-Root mit `raw_data/` und
  `prepared_data/`) oder per `RL_DATA_ROOT` gesetzt; typischerweise ist das
  das `prepareTraining`-Repo selbst, egal ob `rl_trader/` darin oder daneben
  liegt.
* **Timeframe-Filter:** `--timeframes 1Hour,15Min` (Whitelist) oder
  `--exclude-timeframes 5Min` (Blacklist). Ohne Angabe werden alle drei
  Timeframes genutzt. Der Filter wirkt auf Datensignale, Trainings-/Eval-Pools
  und wird im Checkpoint gespeichert; `eval_rl.py` übernimmt ihn automatisch,
  kann ihn aber per CLI überschreiben.
* Signale: die fertigen Produktionsmodelle unter
  `production_models/<profil>/active` werden auf die vorbereiteten
  Feature-CSVs angewendet:
  * `baseline` → `prepared_data/`
  * `ml4t` → `runs/eval_3ways/_data/ml4t_tol2/`
  * `sma_auto` → `runs/eval_3ways/_data/sma5_tol2/`
* **Chronologischer Split pro Serie:** 70 % Training, 15 % Validation,
  15 % Test (die letzten Bars). Keine Überlappung.
* **Out-of-Ticker-Holdout:** `AAPL` (alle drei Timeframes) wird nie trainiert
  und dient als OOT-Test.
* **Strikte Kausalität:** Zustand bei Bar `t` nutzt nur Bars `<= t`. Die Aktion
  wird zu `close_t` ausgeführt; der Reward entsteht aus dem Return
  `close_t → close_{t+1}`.

## MDP

### State (Beobachtung)

Pro aktivem Profil (8 Werte):

| Wert | Bedeutung |
|---|---|
| `prob_bear` | P(Extrem-Hoch) → Short-Signal |
| `prob_neutral` | P(neutral) |
| `prob_bull` | P(Extrem-Tief) → Long-Signal |
| `raw_pred` | Roh-Signal (−1/0/+1) |
| `filtered_pred` | NMS-gefiltertes Signal (−1/0/+1) |
| `confidence` | max(prob_bear, prob_bull) |
| `bars_since_signal` | Bars seit letztem gefilterten Signal (normiert) |
| `signal_strength` | \|prob_bull − prob_bear\| |

Markt/Volatilität (7): Log-Return 1/5 Bars, normierte Range, normierter ATR(14),
Distanz zu SMA38/SMA80 (in ATR), rollierende Volatilität.

Konto/Position (4): Position (−1/0/+1), unrealisierter PnL, Haltedauer
(normiert), aktueller Drawdown.

### Action (diskret, 4)

| Action | Bedeutung |
|---|---|
| `0` | Hold – Position halten oder flat bleiben (Signale ignorieren) |
| `1` | Long – Zielposition +1 |
| `2` | Short – Zielposition −1 |
| `3` | Close – Zielposition 0 |

### Reward

```text
net      = position * next_return − Kosten(|Δposition|)
equity  *= (1 + net)
reward   = reward_scale * net
           − dd_penalty * reward_scale * max(0, Δdrawdown)
           − trade_penalty * |Δposition|
           + signal_bonus * max(0, confidence − signal_conf_min)
             (nur wenn die Zielposition zum gefilterten Signal passt)
```

Kosten = `(cost_bps + slippage_bps) / 10000` pro Positionswechsel. Standard:
5 bps Kommission + 1 bps Slippage. Die Drawdown-Strafe und die kleine
Reibungsstrafe bremsen Überhandeln. Der optionale `--signal-bonus`
(Default 0.02, mit `--signal-bonus 0` deaktivierbar) ist reines
Explorations-Shaping und wird im Checkpoint gespeichert.

## Training

```bash
# Kompakter Lauf auf einem Profil (empfohlene Demo-Konfiguration)
python rl_trader/train_rl.py --profile ml4t --run-name ml4t_ppo \
  --iterations 100 --n-envs 8 --rollout 128 --lr 1e-4 \
  --bc-samples 20000 --bc-epochs 10 --bc-conf-min 0.6

# Kombiniert über alle drei Profile
python rl_trader/train_rl.py --profile all_3 --run-name all3_ppo \
  --iterations 120 --n-envs 8 --rollout 128 --lr 1e-4 \
  --bc-samples 24000 --bc-epochs 10 --bc-conf-min 0.6
```

Wichtige Optionen: `--timeframes`, `--exclude-timeframes`, `--n-envs`,
`--rollout`, `--episode-len`, `--lr`, `--ent-coef`, `--cost-bps`,
`--slippage-bps`, `--dd-penalty`, `--trade-penalty`, `--signal-bonus`,
`--bc-samples`, `--bc-epochs`, `--bc-conf-min`, `--seed`.

Beispiele mit Timeframe-Fokus:

```bash
# nur 1Hour + 15Min, reduzierter BC-Warmstart
python rl_trader/train_rl.py --profile ml4t --timeframes 1Hour,15Min \
  --run-name ml4t_1h_15m --iterations 100 --lr 1e-4 \
  --bc-samples 5000 --bc-epochs 8 --bc-conf-min 0.6

# 5Min ausschließen
python rl_trader/train_rl.py --profile all_3 --exclude-timeframes 5Min \
  --run-name all3_no5m --dd-penalty 0.2 --trade-penalty 0.05
```

### Optionaler Behaviour-Cloning-Warmstart

Reines PPO aus zufälliger Initialisierung konvergiert bei diesen schwachen
Signalen und 6 bps Kosten schnell auf „flat“ (Null-Trades), weil jede
Explorationsbewegung zunächst Geld kostet. Mit `--bc-samples > 0` wird der
Actor daher vor dem PPO-Feintuning kurz auf eine einfache Regel gebehavior-
clont (nur Signale mit `confidence >= --bc-conf-min` handeln, sonst Position
halten). Das ist optional; `--bc-samples 0` ergibt reines PPO. Der
Warmstart ist im Log (`BC epoch ... acc ...`) dokumentiert.

Artefakte unter `rl_trader/runs/<run-name>/`:
`checkpoint.pt`, `training_run.log`, `learning_curve.csv`,
`learning_curve.png`, `train_meta.json`.

## Voraussetzungen

`torch`, `numpy`, `pandas`, `gymnasium`, `matplotlib`, `joblib`.
**Kein TA-Lib nötig** – die vorbereiteten Feature-CSVs enthalten bereits alle
Modellfeatures; die Signale werden direkt aus den Produktions-Checkpoints
berechnet.

## Leakage-Schutz

* Jede Serie wird **pro Datei chronologisch** in 70/15/15 % geteilt; es wird
  nie über die Zeitgrenze hinweg gemischt.
* `AAPL` ist komplett aus Training/Validation/Test ausgeschlossen und bildet
  den Out-of-Ticker-Holdout.
* Der Zustand bei Bar `t` enthält ausschließlich Signale/Features bis `t`;
  Labels (`label_turn`, `label_max_move_atr`) werden **nie** als Input genutzt.
* Die Aktion wird zu `close_t` ausgeführt, der Reward nutzt erst danach
  `close_{t+1}`.
* Der optionale BC-Warmstart nutzt nur das Signal an Bar `t` und die aktuelle
  Position – keine Zukunftsinformation.
* Die Signalgeber sind die eingefrorenen Produktionsmodelle. `AAPL` war bei
  deren Training vollständig ausgeschlossen, daher ist die OOT-Auswertung
  sauber. Für Nicht-AAPL-Bars kann der Signalgeber Teile des RL-Testsplits
  bereits im eigenen (globalen) Trainingssplit gesehen haben; der RL-Agent
  selbst erhält jedoch ausschließlich Signale/Features bis `t` und nie Labels
  oder zukünftige Kurse.

## Erster Testlauf (Demo)

| Run | Profil | Test mean return | Test max DD | AAPL OOT mean return | OOT max DD |
|---|---|---|---|---|---|
| `ml4t_ppo` | ml4t | −1.57 % | 7.8 % | +5.73 % | 12.5 % |
| `all3_ppo` | alle 3 | −1.34 % | 8.1 % | +3.56 % | 12.3 % |

Beide Läufe handeln aktiv, aber selektiv: `ml4t_ppo` nutzt ca. 65–69 % der
gefilterten Signale und hält Positionen lange (≈94–184 Bars), `all3_ppo` ist
aktiver (≈25 Bars Haltedauer, ca. 82 % Signalnutzung). Auf dem Testsplit ist
keine Methode nach 6 bps Kosten profitabel; auf AAPL (OOT) sind alle
Signalstrategien positiv, wobei der `ml4t`-Agent vor allem vom 1Hour-Chart
profitiert. Details: `runs/<run>/eval/eval_report.md`.

## Timeframe-Vergleichsläufe (1Hour + 15Min)

Diese drei Läufe schließen `5Min` bewusst aus. Alle nutzen
`--timeframes 1Hour,15Min`, 100 PPO-Iterationen, `--lr 1e-4` (all3: `5e-5`)
und 6 bps Gesamtkosten.

| Run | Profil | BC-Samples | Reward-Tuning | Test Ret | Test MaxDD | Test Trades | Test Win | Test Hold | Test SigUse | OOT ges. | OOT 1Hour | OOT 15Min | OOT MaxDD | OOT Trades | OOT Win | OOT Hold | OOT SigUse |
|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `ml4t_1h_15m` | ml4t | 5.000 | dd 0.10 / trade 0.01 | +1.18 % | 9.0 % | 36 | 55.6 % | 125 | 57 % | +23.45 % | +31.27 % | +15.62 % | 10.0 % | 14 | 71.4 % | 259 | 47 % |
| `all3_1h_15m` | all_3 | 20.000 | dd 0.15 / trade 0.02 | +0.61 % | 8.7 % | 292 | 57.2 % | 16 | 89 % | +11.09 % | +19.64 % | +2.53 % | 13.8 % | 245 | 62.9 % | 15 | 90 % |
| `base_1h_15m` | baseline | 5.000 | dd 0.10 / trade 0.01 | +1.94 % | 9.4 % | 16 | 68.8 % | 290 | 50 % | +19.52 % | +24.39 % | +14.64 % | 10.6 % | 8 | 100.0 % | 467 | 48 % |

**BC-Sweep (ml4t, 1Hour+15Min, 40 Iterationen):**

| BC-Samples | Test Ret | OOT Ret | Test Trades | OOT Trades | OOT Win | OOT Hold | OOT SigUse |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 0.00 % | 0.00 % | 0 | 0 | – | – | 0 % |
| 5.000 | +0.23 % | +34.68 % | 16 | 8 | 100 % | 453 | 44 % |
| 10.000 | −1.23 % | −3.33 % | 49 | 13 | 77 % | 286 | 65 % |
| 20.000 | −0.85 % | +31.43 % | 59 | 46 | 70 % | 80 | 79 % |

Fazit: 5.000 BC-Samples reichen, um den Flat-Kollaps zu vermeiden, drücken
den Agenten aber in sehr lange Holds und wenige Trades. Mehr BC (10–20k)
erhöht die Signalnutzung und Trade-Frequenz, kostet aber Rendite bzw. macht
den Agenten stärker von der starren Regel abhängig.

## Knock-out-Simulation (USD)

Zusätzlich zum klassischen `TradingEnv` gibt es `KOTradingEnv` (`--env ko`).
Gehandelt werden simulierte Knock-out-Zertifikate in **USD**:

* Einsatz: `--position-size 200` ($), optional reduziert über
  `--size-fractions 1.0,0.5` (volle 200 $ oder 100 $).
* Scheine: `--cert-leverages 22,30,38` (konservativ ~22x, Standard ~30x,
  aggressiv ~38x). Der KO-Abstand ist `1/Hebel + --ko-buffer` (Default 0.5 %).
* Gebühren: `--trade-fee 10` ($ pro Order, also Entry/Exit/Flip).
* KO: Long wird ausgeknockt, wenn das **Low** eines Folge-Bars das KO-Level
  toucht; Short beim **High**. Ein KO ist der Totalverlust des Einsatzes
  (die 200 $ bzw. 100 $). Danach ist die Position flat.
* Konto: `--initial-cash 10000` ($). Die Equity ist Cash + aktueller
  Zertifikatswert; ein KO setzt den Zertifikatswert auf 0.

**Action space (14):**

| Action | Bedeutung |
|---|---|
| `0` | Hold / kein Einstieg |
| `1` | Close |
| `2..7` | Long mit Schein 0/1/2 und Größe 0/1 |
| `8..13` | Short mit Schein 0/1/2 und Größe 0/1 |

**State-Erweiterung (13 Werte):** Position, Einsatz normiert, Hebel normiert,
aktueller KO-Abstand (normiert und in ATR), KO-Nähe, unrealisierter PnL,
Haltedauer, Drawdown, Equity-Return sowie die initialen KO-Abstände der drei
Scheine. ATR/Volatilität sind bereits in den Marktfeatures enthalten.

**Reward:** `ΔEquity_USD / reward_scale_usd` minus Drawdown-Strafe, minus
KO-Nähe-Strafe pro Bar, minus KO-Event-Strafe, plus optionalem Signal-Shaping.
Die 10 $-Gebühren und der KO-Totalverlust stecken direkt in `ΔEquity_USD`.

Der optionale BC-Warmstart nutzt für KO eine **risikobewusste Regel**:
Close bei KO-Nähe ≥ 0.75, Einstieg nur wenn flat oder das Signal dreht,
konservativer 22x-Schein bei ATR ≥ 1 %, sonst Standard-30x, jeweils mit
voller 200-$-Größe. `--target-leverage 30` dient als Referenz für den
Standard-Schein; die konkreten Scheine kommen aus `--cert-leverages`.

### KO-Trainingsbeispiel

```bash
python rl_trader/train_rl.py --env ko --profile ml4t \
  --timeframes 1Hour,15Min --run-name ko30_ml4t --iterations 100 \
  --position-size 200 --trade-fee 10 --cert-leverages 22,30,38 \
  --size-fractions 1.0,0.5 --ko-penalty 0.1 --ko-event-penalty 0.3 \
  --lr 1e-5 --bc-samples 20000 --bc-epochs 8
```

Die KO-Auswertung (`eval_rl.py`) protokolliert zusätzlich:
**KO-Anzahl und KO-Rate**, **Gebühren $**, **Brutto-/Netto-PnL $**,
**Fee/Gross-Verhältnis**, **Schein-Präferenz** (z. B. `30x:29/22x:2`) und
**Größen-Präferenz** (z. B. `100%:31/50%:0`).

### Erste KO-Ergebnisse (1Hour + 15Min, 200 $, 10 $/Order)

| Run | Split | Mean Ret | MaxDD | Trades | Win | Ø Hold | KOs | KO-Rate | Fees $ | Gross $ | Net $ | Fee/Gross | Schein-Präferenz |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `ko30_ml4t` | Test | −0.45 % | 3.4 % | 31 | 35.5 % | 79 | 10 | 32.3 % | 520 | −204 | −724 | 2.54 | 30x:29 / 22x:2 |
| `ko30_ml4t` | AAPL OOT | +4.41 % | 8.9 % | 15 | 46.7 % | 184 | 3 | 20.0 % | 270 | 1.152 | 882 | 0.23 | 30x:12 / 22x:3 |
| `ko30_all3` | Test | −0.09 % | 4.4 % | 57 | 43.9 % | 69 | 15 | 26.3 % | 990 | 845 | −145 | 1.17 | 30x:54 / 22x:3 |
| `ko30_all3` | AAPL OOT | +3.17 % | 5.6 % | 51 | 51.0 % | 57 | 10 | 19.6 % | 920 | 1.554 | 634 | 0.59 | 30x:50 / 22x:1 |

Beide Agenten bevorzugen den **Standard-Schein (30x)** mit **voller
200-$-Größe**; der konservative 22x-Schein wird nur in volatileren Lagen
genutzt, der aggressive 38x-Schein gar nicht. `ko30_all3` nutzt einen
höheren BC-Confidence-Schwellwert (0.7) und handelt dadurch deutlich
selektiver als `ko30_ml4t`. Beim `ko30_ml4t` sind die 10-$-Gebühren auf Test
(520 $ bei nur 204 $ Brutto-PnL) der dominierende Faktor; auf AAPL OOT bleibt
nach 270 $ Gebühren noch 882 $ Netto-PnL übrig.

## Höhere Hebel (60x/80x) & schnelle Ausstiege

Die Schein-Palette ist jetzt standardmäßig `22,30,60,80`; über
`--cert-leverages` frei konfigurierbar. Der State enthält pro Schein
**Hebel, initialen KO-Abstand in % und in ATR**; für die aktuelle Position
zusätzlich den dynamischen KO-Abstand und die relative KO-Nähe. Dazu kommen
Mean-Reversion- und SMA-Cross-Features:

* `mid` = kausaler gleitender Mittelwert (Default 20 Bars),
* Abstand des Kurses zur Mitte (in ATR), Seite und Annäherungsrichtung,
* SMA(38/80)-Spread (in ATR), Spread-Änderung und Cross-Event-Flag.

**Schnelle Ausstiege** (optional, pro Lauf konfigurierbar):

| Flag | Wirkung |
|---|---|
| `--mean-revert-target` | schließt Long bei Erreichen/Überschreiten der Mitte, Short analog |
| `--exit-on-sma-cross` | schließt beim SMA(38/80)-Cross |
| `--max-hold-bars 24` | schließt nach maximal 24 Bars |

Der Reward enthält zusätzlich `--target-bonus` für profitable
Mean-Reversion-/SMA-Cross-Exits, `--avoid-ko-bonus` für profitables Schließen
nahe am KO sowie `--high-lev-ko-penalty` für Halten von 60x/80x in der
KO-Zone. Die Auswertung schlüsselt zusätzlich nach **Schein**, **Exit-Grund**
(Close / KO / SMA-Cross / Mean-Reversion / Max-Hold) und **Haltedauer bis
Close/KO/Ziel** auf.

### Ergebnisse 60x/80x (1Hour + 15Min, 200 $, 10 $/Order)

```bash
python rl_trader/train_rl.py --env ko --profile ml4t \
  --timeframes 1Hour,15Min --run-name ko60_80_ml4t --iterations 100 \
  --position-size 200 --trade-fee 10 --cert-leverages 22,30,60,80 \
  --size-fractions 1.0,0.5 --ko-penalty 0.1 --ko-event-penalty 0.3 \
  --high-lev-threshold 60 --high-lev-ko-penalty 0.1 \
  --target-bonus 0.2 --avoid-ko-bonus 0.1 \
  --exit-on-sma-cross --mean-revert-target --max-hold-bars 24 \
  --lr 1e-5 --bc-samples 20000 --bc-epochs 8 --bc-conf-min 0.6
```

| Run | Split | Return | MaxDD | Trades | Win | Ø Hold | KOs | KO-Rate | Fees $ | Gross $ | Net $ | Fee/Gross | Schein-Verteilung |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `ko60_80_ml4t` | Test | −0.18 % | 1.3 % | 18 | 38.9 % | 15 | 3 | 16.7 % | 330 | 38 | −292 | 8.78 | 22x:1 / 30x:12 / 60x:5 / 80x:0 |
| `ko60_80_ml4t` | AAPL OOT | **+6.18 %** | 1.7 % | 16 | 62.5 % | 12 | 0 | 0.0 % | 320 | 1.555 | 1.235 | 0.21 | 22x:1 / 30x:13 / 60x:1 / 80x:1 |
| `ko60_80_all3` | Test | −0.27 % | 1.6 % | 61 | 44.3 % | 10 | 2 | 3.3 % | 1.200 | 774 | −426 | 1.55 | 30x:22 / 80x:39 |
| `ko60_80_all3` | AAPL OOT | −1.67 % | 4.7 % | 55 | 54.5 % | 10 | 5 | 9.1 % | 1.050 | 717 | −333 | 1.46 | 30x:18 / 80x:37 |

**AAPL OOT nach Timeframe:**

| Run | TF | Return | Trades | Win | KOs | Fees $ | Net $ |
|---|---|---:|---:|---:|---:|---:|---:|
| `ko60_80_ml4t` | 1Hour | +13.90 % | 12 | 83.3 % | 0 | 240 | 1.390 |
| `ko60_80_ml4t` | 15Min | −1.55 % | 4 | 0.0 % | 0 | 80 | −155 |
| `ko60_80_all3` | 1Hour | −2.17 % | 18 | 61.1 % | 3 | 330 | −217 |
| `ko60_80_all3` | 15Min | −1.16 % | 37 | 51.4 % | 2 | 720 | −116 |

**Exit-Diagnostik (AAPL OOT):**

| Run | Close | KO | SMA-Cross | Mean-Rev | Max-Hold | Ø Hold Close | Ø Hold KO | Ø Hold Ziel |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `ko60_80_ml4t` | 0 | 0 | 6 | 7 | 3 | – | – | 12.2 |
| `ko60_80_all3` | 1 | 5 | 13 | 33 | 3 | 6.0 | 8.6 | 10.1 |

**Einschätzung:** `ko60_80_ml4t` nutzt überwiegend den 30x-Schein, gelegentlich
60x/80x, und schließt schnell über Mean-Reversion/SMA-Cross/Max-Hold. Auf AAPL
OOT erzielt er +6.18 % bei 0 KOs und nur 320 $ Gebühren. `ko60_80_all3`
bevorzugt bei niedriger Volatilität den 80x-Schein mit halber 100-$-Größe
(37 von 55 OOT-Trades), bleibt aber nach 1.050 $ Gebühren leicht negativ
(−1.67 %). Immerhin vermeidet er die drastischen Verluste der Blind-/
High-Confidence-Baselines (OOT −17.82 % / −19.55 %) und hält den Drawdown
mit 4.7 % klein. Die 10-$-Gebühr bleibt der dominierende Kostenfaktor.

## Evaluation

```bash
python rl_trader/eval_rl.py --run-name ml4t_ppo --splits val,test,oot
python rl_trader/eval_rl.py --run-name ko60_80_ml4t --splits val,test,oot
python rl_trader/eval_rl.py --run-name ko30_ml4t --splits val,test,oot
```

`eval_rl.py` erkennt den Umgebungstyp automatisch aus dem Checkpoint
(`env_type`) und nutzt für KO-Runs automatisch die KO-Metriken. `--env ko`
bzw. `--env classic` kann das überschreiben.

Verglichen werden:

1. `rl_agent` – deterministische PPO-Policy
2. `blind` – jedes `filtered_pred`-Signal blind handeln
3. `high_conf` – nur Signale mit `confidence >= --high-conf` (Default 0.60)
4. `flat` – nie handeln

Kennzahlen: Netto-Return nach Kosten, Max-Drawdown, Sharpe, Win-Rate,
Trade-Anzahl, durchschnittliche Haltedauer, genutzte/ignorierte Signale,
Standalone-Trades ohne Signal. „Genutzt“ bedeutet: die Zielposition stimmt am
Signalbalken mit der Signalrichtung überein; „ignoriert“: Signalbalken ohne
passende Position. Ausgabe: `eval_metrics.json`,
`eval_report.md`, `per_series_*.csv`, `by_timeframe_<split>.csv`,
`trades_*.csv` sowie `equity_<split>.png` / `drawdown_<split>.png`.
`by_timeframe_<split>.csv` und der `by_timeframe`-Block in
`eval_metrics.json` schlüsseln jeden Split zusätzlich nach `1Hour`, `15Min`
und `5Min` auf (bei `oot` also AAPL pro Timeframe).
