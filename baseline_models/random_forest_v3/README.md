# Random-Forest Baseline v3

Dieser Ordner enthaelt die dritte Version der Random-Forest-Baseline. Sie nutzt dieselbe Event-Fenster-Struktur wie `random_forest` und `random_forest_v2`, fasst aber `Schlaeger drehen` und `Kein Schlag / Other` zu einer gemeinsamen Klasse zusammen.

## Labels

`random_forest_v3` nutzt diese Zielklassen:

- `Vorhand`
- `Rueckhand`
- `Aufschlag von unten`
- `Kein Schlag / Schlaeger drehen`

## Aufbau

Wie bei den vorherigen Baselines:

1. Jede gelabelte Zeile wird als Event gelesen.
2. Um jedes Event wird ein Zeitfenster gebaut.
3. Daraus werden Statistik-Features pro Sensorsignal erzeugt.
4. Ein `RandomForestClassifier` klassifiziert die Events.

Der Unterschied zu `v2` ist nur die zusammengelegte Nicht-Schlag-Klasse und die dazugehoerige eigene Auswertungsstruktur unter `baseline_models/random_forest_v3/`.

## Gefundene Parameter

Die gruppenbasierte Search ueber `16` Kandidaten hat fuer `v3` diese Kombination bevorzugt:

- `n_estimators = 600`
- `max_depth = 12`
- `min_samples_split = 10`
- `min_samples_leaf = 3`
- `max_features = log2`
- `criterion = entropy`
- `class_weight = balanced_subsample`

Diese Werte sind bereits in [config.json](/Users/marcel/Desktop/ML4SCS/baseline_models/random_forest_v3/config.json) uebernommen.

## Vergleich zu v1 und v2

Mit der zusammengelegten Klasse steigt die Leave-One-Session-Out-Qualitaet deutlich:

- `Accuracy`: `0.958` statt `0.891` bei `v2`
- `Balanced Accuracy`: `0.952` statt `0.763` bei `v2`
- `Macro F1`: `0.953` statt `0.752` bei `v2`
- `Weighted F1`: `0.958` statt `0.889` bei `v2`

Wichtig: Der Vergleich bleibt hilfreich, ist aber nicht vollstaendig 1:1, weil `v3` durch das Merge eine andere Klassenaufgabe loest als `v1` und `v2`.

## Struktur

- [config.json](/Users/marcel/Desktop/ML4SCS/baseline_models/random_forest_v3/config.json): Modell- und Evaluationskonfiguration
- [random_forest_baseline_v3.ipynb](/Users/marcel/Desktop/ML4SCS/baseline_models/random_forest_v3/random_forest_baseline_v3.ipynb): Notebook fuer Evaluation und Vergleich mit `v1`/`v2`
- `output/`: Modellartefakte und Kennzahlen

## Ausfuehren

Hyperparameter-Suche:

```bash
python3 -m src.random_forest_baseline_v3.search
```

Evaluation:

```bash
python3 -m src.random_forest_baseline_v3.evaluate
```

Training:

```bash
python3 -m src.random_forest_baseline_v3.train
```

## Ausgaben

Nach Search, Evaluation und Training liegen in `output/` unter anderem:

- `search_results.csv`
- `search_summary.json`
- `recommended_config.json`
- `metrics.json`
- `classification_report.csv`
- `confusion_matrix.csv`
- `confusion_matrix.png`
- `fold_metrics.csv`
- `predictions.csv`
- `label_summary.csv`
- `feature_importances.csv`
- `random_forest_model.pkl`
