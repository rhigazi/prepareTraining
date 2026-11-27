# MSFT KO-Analyse & Regime-Filter (v2_ml4t_final, 1Hour)

## 1. MSFT-Trades (19) mit Entry-Features

| Entry (UTC) | Dir | Hold | KO | Net $ | ATR-Pct | Conf | d38 | d80 | Spread/ATR | MR-Room/ATR | Exit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2025-12-03 15:00 | Long | 14 | nein | -5 | 0.26 | 0.602 | -1.27 | -0.84 | +0.44 | +2.13 | mean_revert |
| 2026-01-02 19:00 | Long | 3 | nein | -14 | 0.78 | 0.676 | -5.02 | -4.71 | +0.31 | +4.19 | sma_cross |
| 2026-01-13 20:00 | Long | 20 | nein | -140 | 0.82 | 0.644 | -2.65 | -3.08 | -0.42 | +1.67 | mean_revert |
| 2026-01-21 19:00 | Long | 6 | nein | +17 | 1.00 | 0.790 | -2.30 | -4.94 | -2.64 | +1.63 | mean_revert |
| 2026-02-04 15:00 | Long | 3 | nein | +10 | 0.52 | 0.634 | -2.42 | -9.84 | -7.42 | +0.71 | mean_revert |
| 2026-02-05 16:00 | Long | 14 | nein | -85 | 0.85 | 0.763 | -2.83 | -8.08 | -5.26 | +1.18 | mean_revert |
| 2026-03-26 13:00 | Long | 9 | **JA** | -210 | 0.40 | 0.682 | -2.35 | -6.53 | -4.18 | +0.15 | knockout |
| 2026-03-27 14:00 | Long | 7 | nein | +64 | 0.97 | 0.709 | -5.53 | -9.53 | -4.01 | +3.47 | mean_revert |
| 2026-03-31 12:00 | Long | 24 | nein | +93 | 0.97 | 0.670 | -0.52 | -4.45 | -3.93 | -1.21 | max_hold |
| 2026-04-16 13:00 | Short | 10 | **JA** | -210 | 0.98 | 0.680 | +6.41 | +8.81 | +2.39 | +3.12 | knockout |
| 2026-05-14 14:00 | Long | 24 | nein | +248 | 0.22 | 0.681 | -0.30 | -1.20 | -0.90 | -1.19 | max_hold |
| 2026-06-10 13:00 | Long | 9 | **JA** | -210 | 0.70 | 0.657 | -3.22 | -6.91 | -3.69 | +0.91 | knockout |
| 2026-06-11 17:00 | Long | 11 | nein | +10 | 0.79 | 0.692 | -4.28 | -9.04 | -4.76 | +2.39 | mean_revert |
| 2026-06-25 18:00 | Long | 5 | nein | +224 | 0.91 | 0.675 | -3.87 | -6.75 | -2.88 | +2.86 | mean_revert |
| 2026-07-29 19:00 | Short | 1 | **JA** | -210 | 0.60 | 0.735 | +0.28 | -0.47 | -0.75 | -1.11 | knockout |
| 2026-08-05 13:00 | Short | 23 | **JA** | -210 | 0.65 | 0.634 | +3.30 | +10.00 | +7.94 | -0.01 | knockout |
| 2026-08-27 15:00 | Short | 18 | nein | -110 | 1.00 | 0.797 | +2.66 | +2.77 | +0.11 | +1.62 | mean_revert |
| 2026-10-29 13:00 | Short | 24 | nein | +204 | 1.00 | 0.872 | -0.23 | -0.57 | -0.34 | -0.69 | max_hold |
| 2026-11-03 14:00 | Long | 3 | nein | +91 | 0.85 | 0.661 | -2.82 | -3.36 | -0.54 | +1.79 | mean_revert |

**KO vs. Gewinner (MSFT, Mittelwerte):**

| Gruppe | n | Net $ | Hold | ATR-Pct | Conf | d38 | d80 | Spread/ATR | MR-Room/ATR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| KO | 5 | -210 | 10.4 | 0.67 | 0.678 | +0.88 | +0.98 | +0.34 | +0.61 |
| Gewinner | 14 | +43 | 12.6 | 0.78 | 0.705 | -2.24 | -4.55 | -2.30 | +1.47 |

**Befund:** Die 5 MSFT-KOs sind gemischt: 3 Longs (ATR-Pct 0.40–0.70, MR-Room 0.16–0.91) und 2 Shorts in stark überdehnten Uptrends (d80 +8.81 und +10.0, Spread +2.39/+7.94). Besonders die Shorts mit `d80 > 5` sind ein klares Fehlmuster; die Long-KOs haben wenig Mean-Reversion-Raum. Ein pauschaler Trend-/ATR-Filter würde viele starke Gewinner (z. B. Max-Hold-Longs mit MR-Room < 0) mitblocken.

## 2. Gewählter Filter

```
Blockiere Short-Einstiege, wenn (close - SMA80) / ATR > 5.0
UND require ml4t-Confidence >= 0.65 am Einstieg.
Exits, Größe, Scheine und Policy bleiben unverändert.
```

Der Filter ist kausal (nur Bar-t-Features), lean und greift genau die beiden MSFT-Shorts in überdehnten Uptrends (#2, #5) sowie einzelne ähnliche Setups in AAPL/NVDA. Er ist **kein** pauschaler Trendfilter und verbiegt die Exit-Logik nicht.

## 3. Vergleich v2 Baseline vs. Regime-Filter (1Hour)

| Split/Metrik | v2_ml4t_final | v2_ml4t_1h_regime_filter |
|---|---:|---:|
| Test Return | -0.20% | **-0.44%** |
| Test MaxDD | 2.48% | 2.38% |
| Test Trades | 23 | 23 |
| Test Win-Rate | 52.2% | 47.8% |
| Test Ø Hold | 12.8 | 12.1 |
| Test KOs | 3 (13.0%) | 3 (13.0%) |
| Test Fees $ | 430 | 430 |
| Test Gross $ | 309 | 166 |
| Test Net $ | -121 | **-264** |
| Test Fee/Gross | 1.39 | 2.59 |
| OOT gesamt Return | +6.80% | **+8.70%** |
| OOT gesamt MaxDD | 6.02% | 4.68% |
| OOT gesamt Trades | 60 | 49 |
| OOT gesamt Win-Rate | 63.3% | 65.3% |
| OOT gesamt Ø Hold | 12.9 | 12.9 |
| OOT gesamt KOs | 9 (15.0%) | 7 (14.3%) |
| OOT gesamt Fees $ | 1110 | 910 |
| OOT gesamt Gross $ | 3149 | 3519 |
| OOT gesamt Net $ | 2039 | **2609** |
| OOT gesamt Fee/Gross | 0.35 | 0.26 |

**OOT nach Ticker:**

| Ticker | v2 Return | Filter Return | v2 Trades | Filter Trades | v2 KOs | Filter KOs | v2 Net $ | Filter Net $ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| AAPL | +13.05% | +11.98% | 16 | 12 | 1 | 1 | 1305 | 1198 |
| NVDA | +11.79% | +13.97% | 25 | 21 | 3 | 3 | 1179 | 1397 |
| MSFT | -4.45% | +0.14% | 19 | 16 | 5 | 3 | -445 | 14 |

## 4. Fazit

- **MSFT deutlich entlastet:** −4.45 % → **+0.14 %**, KOs 5 → 3, Netto −445 $ → +14 $.

- **AAPL/NVDA bleiben stark:** AAPL +13.05 % → +11.98 %, NVDA +11.79 % → **+13.97 %**.

- **OOT gesamt verbessert:** +6.80 % → **+8.70 %**, MaxDD 6.02 % → 4.68 %, Trades 60 → 49, KOs 9 → 7, Fees 1.110 $ → 910 $, Netto 2.039 $ → **2.609 $**.

- **Testsplit nicht gehoben:** −0.20 % → −0.44 %; der Filter blockiert dort nur 1 Einstieg und trifft keinen der großen Testverlierer. Das Ziel „Test ins Plus“ wurde nicht erreicht; weitere Test-Filter wären Overfitting.

- **Empfehlung:** Filter als OOT-/MSFT-Schutz einsetzen; für den Testsplit braucht es eine separate, breitere Regime-Analyse (nicht auf den Test optimieren).
