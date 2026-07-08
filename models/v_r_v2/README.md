# v_r_v2

Dieser Ordner enthaelt das Modell `v_r_v2` mit derselben Mehrklassen-Labelauswahl wie die Random-Forest-Baseline.

## Labels

`v_r_v2` nutzt aktuell dieselben Klassen wie [baseline_models/random_forest/config.json](/Users/marcel/Desktop/ML4SCS/baseline_models/random_forest/config.json:1):

- `Vorhand`
- `Rueckhand`
- `Schlaeger drehen`
- `Aufschlag von unten`
- `Kein Schlag / Other`

## Aufbau

Technisch basiert `v_r_v2` auf derselben Event-Fenster-Pipeline wie eure Baseline:

1. Gelabelte Events werden aus `Daten/Daten_Labeled` geladen.
2. Um jedes Event wird ein Fenster gebildet.
3. Daraus werden Statistik-Features berechnet.
4. Ein `RandomForestClassifier` lernt die Schlagklassen.

Der Unterschied ist hier vor allem die saubere Ablage als eigenes Modell unter `models/v_r_v2/`.

## Struktur

- [config.json](/Users/marcel/Desktop/ML4SCS/models/v_r_v2/config.json): Modell- und Evaluationskonfiguration
- [v_r_v2_evaluation.ipynb](/Users/marcel/Desktop/ML4SCS/models/v_r_v2/v_r_v2_evaluation.ipynb): Notebook fuer Metriken und grafische Auswertung
- `output/`: Modellartefakte und Kennzahlen

## Ausfuehren

Evaluation:

```bash
python3 -m src.vr_v2_model.evaluate
```

Training:

```bash
python3 -m src.vr_v2_model.train
```

## Grafische Auswertung

Wie bei der Baseline wird eine Confusion Matrix als PNG erzeugt und im Notebook direkt dargestellt.

## Ausgaben

Nach dem Lauf liegen in `output/` unter anderem:

- `v_r_v2.pkl`
- `metrics.json`
- `classification_report.csv`
- `confusion_matrix.csv`
- `confusion_matrix.png`
- `fold_metrics.csv`
- `predictions.csv`
- `label_summary.csv`
- `feature_importances.csv`
