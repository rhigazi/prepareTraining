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

## V2: Verhältnis-Features & Multi-Ticker-OOT

Der KO-State enthält zusätzlich explizite **Verhältnisgrößen**:

* `fee_burden` = kumulierte Gebühren / Startkapital,
* `trade_count_norm` = Anzahl Trades / 50,
* `pnl_to_fee` = unrealisierter PnL / 10-$-Gebühr,
* `atr_value_fees` = USD-Wert einer 1-ATR-Bewegung / 10-$-Gebühr,
* `mid_room_fees` = potenzieller USD-Weg zur Mitte / 10-$-Gebühr,
* `sma_room_fees` = potenzieller USD-Weg bis zum SMA-Spread / 10-$-Gebühr.

Damit kann der Agent abschätzen, ob der Restweg zum Ziel die Ordergebühr
überhaupt rechtfertigt. Der OOT-Holdout ist über `--oot-tickers` frei wählbar:

```bash
--oot-tickers AAPL,NVDA
```

`eval_rl.py` schreibt zusätzlich `by_ticker_<split>.csv` und zeigt im Report
eine OOT-Tabelle pro Ticker (z. B. AAPL vs. NVDA) sowie weiterhin die
Timeframe-Tabelle (1Hour vs. 15Min).

### V2-Ergebnisse (OOT: AAPL + NVDA)

Die finalen V2-Läufe nutzen `--bc-anchor 0.5`: eine kleine BC-Kreuzentropie
während der PPO-Updates verhindert den wiederholten Flat-Kollaps bei 10 $
Gebühren, ohne die Politik vollständig auf die Regel zu fixieren.

| Run | Split | Return | MaxDD | Trades | Win | Ø Hold | KOs | KO-Rate | Fees $ | Gross $ | Net $ | Fee/Gross | Schein-Verteilung |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `v2_ml4t_final` | Test | +0.15 % | 1.7 % | 41 | 51.2 % | 13.0 | 3 | 7.3 % | 790 | 1.000 | 210 | 0.79 | 30x:35 / 60x:6 |
| `v2_ml4t_final` | OOT | **+5.37 %** | 4.0 % | 66 | 59.1 % | 13.0 | 4 | 6.1 % | 1.280 | 3.428 | **2.148** | 0.37 | 30x:62 / 60x:4 |
| `v2_all3_final` | Test | −0.42 % | 3.6 % | 181 | 48.1 % | 10.3 | 9 | 5.0 % | 3.530 | 2.944 | −586 | 1.20 | 22x:4 / 30x:89 / 80x:88 |
| `v2_all3_final` | OOT | −4.54 % | 10.3 % | 321 | 53.6 % | 10.3 | 26 | 8.1 % | 6.160 | 4.345 | −1.815 | 1.42 | 22x:17 / 30x:179 / 80x:125 |

**OOT nach Ticker:**

| Run | Ticker | Return | MaxDD | Trades | Win | Ø Hold | KOs | Fees $ | Net $ |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `v2_ml4t_final` | AAPL | +5.44 % | 2.5 % | 26 | 61.5 % | 11.3 | 1 | 510 | 1.088 |
| `v2_ml4t_final` | NVDA | +5.30 % | 5.4 % | 40 | 57.5 % | 14.1 | 3 | 770 | 1.060 |
| `v2_all3_final` | AAPL | −3.05 % | 7.2 % | 156 | 53.2 % | 10.5 | 7 | 3.050 | −609 |
| `v2_all3_final` | NVDA | −6.03 % | 13.4 % | 165 | 53.9 % | 10.1 | 19 | 3.110 | −1.206 |

**OOT nach Timeframe:**

| Run | TF | Return | MaxDD | Trades | Win | Ø Hold | KOs | Fees $ | Net $ |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `v2_ml4t_final` | 1Hour | **+12.42 %** | 4.8 % | 41 | 70.7 % | 13.3 | 4 | 780 | 2.483 |
| `v2_ml4t_final` | 15Min | −1.67 % | 3.1 % | 25 | 40.0 % | 12.4 | 0 | 500 | −335 |
| `v2_all3_final` | 1Hour | −9.26 % | 14.0 % | 166 | 50.6 % | 10.2 | 18 | 3.140 | −1.853 |
| `v2_all3_final` | 15Min | +0.19 % | 6.6 % | 155 | 56.8 % | 10.3 | 8 | 3.020 | +38 |

**Exit-Diagnostik (OOT):**

| Run | Close | KO | SMA-Cross | Mean-Rev | Max-Hold | Ø Hold Close | Ø Hold KO | Ø Hold Ziel |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `v2_ml4t_final` | 2 | 4 | 14 | 34 | 12 | 9.5 | 11.0 | 13.2 |
| `v2_all3_final` | 45 | 26 | 48 | 186 | 15 | 7.9 | 13.8 | 10.4 |

**BC-Sweep (ml4t, 50 Iterationen):** BC 0 und 5.000 kollabieren auf flat
(0 Trades); 10.000 ist das minimale Warmstart-Niveau, 20.000 handelt aktiver
(65 OOT-Trades, +4.66 % OOT) und nutzt mehr 60x/80x. Die finalen Läufe nutzen
10k (ml4t) bzw. 20k (all3) plus BC-Anker.

Hinweis zur Datenherkunft: `AAPL` war sowohl für die Signalgeber als auch für
den RL-Agenten vollständig OOT. `NVDA` war für die Signalgeber im Training,
aber **nicht** für den RL-Agenten; der NVDA-Test prüft also die RL-Politik auf
einem für sie unbekannten Ticker, nicht die Signalgeber.

## V3: Max-Edge & Kostenfilter

Der V3-Lauf ergänzt die Verhältnis-Features um **Round-Trip-Kosten**
(`--fee-basis 2.0`, also 20 $ bei 10 $/Order) und optionale harte
Einstiegsfilter:

```bash
--min-edge-ratio 4.0      # Zielweg (Mitte/SMA) muss >= 4x Round-Trip-Fee sein
--min-ko-buffer-atr 1.5   # initialer KO-Abstand muss >= 1.5 ATR sein
```

Blockierte Einstiege werden als `filtered_entries` gezählt. OOT umfasst hier
**AAPL, NVDA und MSFT**.

| Run | TF | Test Ret | Test DD | Test Trades | Test KOs | OOT Ret | OOT DD | OOT Trades | OOT KOs | OOT Fees $ | OOT Net $ | Fee/Gross | filtered |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `v3_max_edge_1h` | 1Hour | **+0.79 %** | 0.5 % | 5 | 0 | +0.99 % | 4.3 % | 24 | 3 | 450 | 298 | 0.60 | 0 |
| `v3_max_edge_1h15m` | 1h+15m | +0.18 % | 0.9 % | 16 | 0 | −0.06 % | 3.6 % | 58 | 4 | 1.120 | −37 | 1.03 | 4 |
| `v3_max_edge_1h15m_strict` | 1h+15m | −0.36 % | 0.7 % | 9 | 0 | −0.32 % | 2.2 % | 29 | 3 | 550 | −193 | 1.54 | 16 |

**OOT nach Ticker (`v3_max_edge_1h`):**

| Ticker | Return | MaxDD | Trades | Win | Ø Hold | KOs | Fees $ | Net $ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| AAPL | +3.93 % | 0.7 % | 3 | 100.0 % | 8.7 | 0 | 60 | 393 |
| NVDA | +0.37 % | 7.3 % | 13 | 61.5 % | 11.5 | 2 | 240 | 37 |
| MSFT | −1.31 % | 4.9 % | 8 | 50.0 % | 10.5 | 1 | 150 | −131 |

**OOT nach Timeframe (1h+15m-Varianten):**

| Run | TF | Return | Trades | KOs | Fees $ | Net $ |
|---|---|---:|---:|---:|---:|---:|
| `v3_max_edge_1h15m` | 1Hour | −0.28 % | 41 | 4 | 780 | −83 |
| `v3_max_edge_1h15m` | 15Min | +0.16 % | 17 | 0 | 340 | +47 |
| `v3_max_edge_1h15m_strict` | 1Hour | −0.96 % | 23 | 3 | 430 | −289 |
| `v3_max_edge_1h15m_strict` | 15Min | +0.32 % | 6 | 0 | 120 | +96 |

**Fazit:** Der 1Hour-Fokus mit Kostenfilter liefert die beste
Risiko-/Kosteneffizienz (Test +0.79 %, 0 KOs, OOT +0.99 %, Fee/Gross 0.60),
bleibt aber unter dem Netto-Return von `v2_ml4t_final` (+5.37 % OOT). Der
zusätzliche 15Min-Zweig und noch strengere Filter heben den Testsplit nicht
nachhaltig und erhöhen die Streuung. Nächster sinnvoller Schritt: 1Hour-only
mit weniger strengem Filter (2–3x Fee) und mehr 1Hour-Trainingsdaten; 15Min
zunächst deprioritizieren.

## V4: Mean-Reversion only & 2:1 Mid/KO

V4 deaktiviert SMA-Cross als Ziel vollständig (`--mr-only`). Der Agent handelt
nur noch Mean-Reversion gegen die Mitte. Beim Einstieg wird für jeden Schein
das Verhältnis **Distanz zur Mitte / Distanz zum KO** berechnet und im State
bereitgestellt; `--min-mr-ko-ratio 2.0` erzwingt das ≥ 2:1-Verhältnis.
`--mr-ratio-bonus` belohnt größere Verhältnisse, wenn an der Mitte mit
Netto-Gewinn nach 20 $ Round-Trip geschlossen wird.

| Run | Ratio-Filter | Test Ret | Test Trades | Test KOs | OOT Ret | OOT Trades | OOT KOs | OOT Fees $ | OOT Net $ | Ø MR/KO | Schein-Verteilung |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `v4_mr_only_1h` | 2.0 | 0.00 % | 0 | 0 | 0.00 % | 0 | 0 | 0 | 0 | – | – |
| `v4_mr_only_1h_r1p5` | 1.5 | 0.00 % | 0 | 0 | 0.00 % | 0 | 0 | 0 | 0 | – | – |
| `v4_mr_only_1h_r1p0` | 1.0 (Kontrolle) | −0.00 % | 13 | 3 | −1.16 % | 50 | 11 | 890 | −347 | 1.78 | 80x: 50/50 |

**Baseline mit 2:1-Filter (Regel, kein RL):**

| Methode | Test Ret | Test Trades | OOT Ret | OOT Trades | OOT KOs |
|---|---:|---:|---:|---:|---:|
| `blind` | −0.08 % | 1 | −0.60 % | 2 | 1 |
| `high_conf` | −0.08 % | 1 | +0.10 % | 1 | 0 |

**Fazit:** Das 2:1-Verhältnis ist auf 1Hour mit diesen Signalen **zu streng**:
Der Agent bleibt rational flat (0 Trades), weil die wenigen validen Setups die
20 $ Round-Trip-Kosten und das KO-Risiko nicht tragen. Lockert man auf 1.0,
handelt der Agent fast ausschließlich 80x – und läuft mit 11 KOs auf 50
OOT-Trades in die Knock-out-Falle; nach 890 $ Gebühren bleibt −1.16 % OOT.
Das 2:1-Verhältnis ist ein **Reward/Risk-Filter, kein Wahrscheinlichkeits-
Filter**: Ein weit entferntes Mean-Reversion-Ziel bei sehr nahem KO bedeutet
häufig, dass der KO vor der Mitte erreicht wird. Für eine reine MR-Strategie
wäre eher ein Ziel **näher als der KO** (Ratio < 1) oder ein Teilziel/Time-Stop
sinnvoll; 2:1-R/R braucht eine deutlich höhere Trefferquote.

## V5: Adaptive Ratio & Partial Target (A/B)

V5 vergleicht zwei Varianten auf derselben Basis (1Hour, ml4t, OOT AAPL/NVDA/MSFT,
nur Mean-Reversion, `--mr-only`):

* **`v5_adaptive_1h`:** hebelabhängige Ratio-Schwellen
  `--mr-ko-ratios 0.8,1.0,1.5,2.0` (22x/30x/60x/80x) plus
  `--mr-ratio-vol-scaling 0.25` (höhere Hürde bei hoher ATR).
* **`v5_partial_1h`:** gleiche Schwellen plus **Teilziel**:
  50 % bei 1× initialer KO-Distanz realisieren, Rest zur Mitte/time-stop.
  BC-Entry-Oversampling (`--bc-entry-frac 0.3`) verhindert den Flat-Kollaps
  durch die seltenen validen Setups.

| Run | Test Ret | Test DD | Test Trades | Test KOs | OOT Ret | OOT DD | OOT Trades | OOT KOs | OOT Partials | OOT Fees $ | OOT Net $ | Fee/Gross | Ø MR/KO | Schein |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `v5_adaptive_1h` | +0.55 % | 0.4 % | 3 | 2 | 0.00 % | 2.1 % | 9 | 4 | 0 | 140 | 0 | 1.00 | 4.02 | 60x:4 / 80x:5 |
| `v5_partial_1h` | +0.35 % | 0.3 % | 2 | 1 | **+0.18 %** | 2.7 % | 9 | 4 | 4 | 180 | 53 | 0.77 | 4.10 | 60x:2 / 80x:7 |

**OOT nach Ticker:**

| Run | Ticker | Return | MaxDD | Trades | Win | KOs | Ø MR/KO | Net $ |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `v5_adaptive_1h` | AAPL | −1.27 % | 2.9 % | 6 | 50.0 % | 2 | 3.40 | −127 |
| `v5_adaptive_1h` | MSFT | +1.27 % | 3.4 % | 3 | 33.3 % | 2 | 5.28 | +127 |
| `v5_adaptive_1h` | NVDA | 0.00 % | 0.0 % | 0 | – | 0 | – | 0 |
| `v5_partial_1h` | AAPL | +0.13 % | 3.0 % | 4 | 50.0 % | 1 | 3.82 | +13 |
| `v5_partial_1h` | MSFT | +0.04 % | 2.8 % | 4 | 50.0 % | 3 | 4.60 | +4 |
| `v5_partial_1h` | NVDA | +0.37 % | 2.2 % | 1 | 100.0 % | 0 | 3.25 | +37 |

**Fazit:** Das Teilziel ist die bessere der beiden V5-Varianten: OOT +0.18 %
statt 0.00 %, alle drei OOT-Ticker leicht positiv, 4 von 9 Trades mit
Teilgewinn. Aber beide Varianten bleiben weit unter `v2_ml4t_final`
(+5.37 % OOT). Die adaptiven Schwellen erzeugen sehr wenige Trades (9 OOT)
mit hoher KO-Rate (44 %), weil das durchschnittliche MR/KO-Verhältnis mit
~4.0 sehr hoch ist: Die Mitte ist weit entfernt, der KO oft näher. Das
Teilziel federt das ab, löst aber das Grundproblem nicht. Nächster Schritt
wäre ein **niedrigeres Ratio-Ziel für 60x/80x** oder ein **volatilitäts-
abhängiger Teilziel-Multiple**; die Stichprobe ist für belastbare Aussagen
noch zu klein.

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
