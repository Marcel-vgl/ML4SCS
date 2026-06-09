# Random-Forest Baseline v2

Dieser Ordner enthaelt eine leicht optimierte zweite Version der Random-Forest-Baseline. Sie basiert auf derselben Event-Fenster-Pipeline wie `baseline_models/random_forest`, nutzt aber Parameter aus einer kleinen gruppenbasierten Randomized Search.

## Idee

Wie bei der ersten Baseline:

1. Jede gelabelte Zeile wird als Event gelesen.
2. Um jedes Event wird ein Zeitfenster gebaut.
3. Daraus werden Statistik-Features pro Sensorsignal erzeugt.
4. Ein `RandomForestClassifier` klassifiziert die Events.

## Labels

`random_forest_v2` nutzt dieselben Klassen wie die erste Baseline:

- `Vorhand`
- `Rueckhand`
- `Schlaeger drehen`
- `Aufschlag von unten`
- `Kein Schlag / Other`

## Gefundene Parameter

Die kleine Search ueber `16` Kandidaten hat fuer den aktuellen Datensatz diese Kombination bevorzugt:

- `n_estimators = 600`
- `max_depth = 12`
- `min_samples_split = 6`
- `min_samples_leaf = 2`
- `max_features = 0.5`
- `criterion = entropy`
- `class_weight = balanced`

## Vergleich zur ersten Baseline

Auf demselben Leave-One-Session-Out-Setup lag `v2` leicht vor `v1`:

- `Accuracy`: `0.891` statt `0.886`
- `Balanced Accuracy`: `0.763` statt `0.741`
- `Macro F1`: `0.752` statt `0.737`
- `Weighted F1`: `0.889` statt `0.887`

Der Gewinn ist also nicht riesig, aber messbar und vor allem auf den unausgeglichenen Klassen etwas besser.

## Ausfuehren

Hyperparameter-Suche:

```bash
python3 -m src.random_forest_baseline.search
```

Evaluation:

```bash
python3 -m src.random_forest_baseline_v2.evaluate
```

Training:

```bash
python3 -m src.random_forest_baseline_v2.train
```

## Notebook

Das Notebook [random_forest_baseline_v2.ipynb](/Users/marcel/Desktop/ML4SCS/baseline_models/random_forest_v2/random_forest_baseline_v2.ipynb) zeigt:

- Labelverteilung
- Gesamtmetriken
- Fold-Metriken
- grafische Confusion Matrix
- die Search-Ergebnisse und die besten Kandidaten

## Ausgaben

In `output/` liegen unter anderem:

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
