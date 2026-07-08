# v_r_v1 Evaluation

Dieser Ordner enthaelt die Evaluationsstruktur fuer das bereits trainierte Modell [v_r_v1.pkl](/Users/marcel/Desktop/ML4SCS/models/v_r_v1_eval/output/v_r_v1.pkl).

## Modell

`v_r_v1.pkl` ist ein gespeichertes Vorhand/Rueckhand-Modell, das ueber [stroke_model.py](/Users/marcel/Desktop/ML4SCS/src/stroke_model.py:1) ausgewertet wird.

Das Modell:

- nutzt Zeitfenster von `0.45s` vor und `0.35s` nach dem Zentrum eines Schlags
- richtet Event-Zeitpunkte auf erkannte Bewegungspeaks aus
- sagt nur die Klassen `Vorhand` und `Rueckhand` voraus

## Struktur

- [config.json](/Users/marcel/Desktop/ML4SCS/models/v_r_v1_eval/config.json): Pfade und Evaluationsparameter
- [v_r_v1_evaluation.ipynb](/Users/marcel/Desktop/ML4SCS/models/v_r_v1_eval/v_r_v1_evaluation.ipynb): Notebook fuer Analyse und Vergleich
- `output/`: automatisch erzeugte Kennzahlen, CSVs und Plots

## Ausfuehren

```bash
python3 -m src.vr_model_evaluation.evaluate
```

## Wichtiger Hinweis

Die aktuell verfuegbaren `Vorhand`/`Rueckhand`-Labels in `labels/` summieren sich auf `326` Events. Das entspricht genau den im Modell gespeicherten `training_samples`.

Deshalb gilt:

- die aktuelle Auswertung testet das vorhandene `.pkl` sehr wahrscheinlich auf denselben Beispielen, auf denen es trainiert wurde
- diese Kennzahlen sind gut zum technischen Pruefen des Artefakts
- fuer einen fairen Modellvergleich solltet ihr spaeter unbedingt mit echten Holdout-Sessions oder Leave-One-Session-Out arbeiten

## Ausgaben

Nach dem Lauf liegen in `output/` unter anderem:

- `metrics.json`
- `model_metadata.json`
- `classification_report.csv`
- `confusion_matrix.csv`
- `confusion_matrix.png`
- `session_metrics.csv`
- `predictions.csv`
- `label_summary.csv`
- `feature_importances.csv`
