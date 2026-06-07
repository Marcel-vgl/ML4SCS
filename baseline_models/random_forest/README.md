# Random-Forest Baseline

Dieser Ordner enthaelt eine erste, bewusst einfache Baseline fuer eure Schlagklassifikation auf Basis der bereits gelabelten CSV-Dateien in `Daten/Daten_Labeled`.

## Idee

Das Modell arbeitet **ereignisbasiert**:

1. Jede gelabelte Zeile wird als Event interpretiert.
2. Um jedes Event wird ein Zeitfenster gebildet.
3. Aus allen Sensorwerten im Fenster werden kompakte Statistik-Features berechnet.
4. Diese Features werden mit einem `RandomForestClassifier` klassifiziert.

Die aktuelle Baseline nutzt standardmaessig:

- `0.5` Sekunden vor dem Event
- `0.5` Sekunden nach dem Event
- die Labels `Vorhand`, `Rueckhand`, `Schlaeger drehen`, `Aufschlag von unten` und `Kein Schlag / Other`

## Warum dieser Aufbau?

- Die Labels in euren CSVs liegen punktuell auf einzelnen Event-Zeitpunkten vor.
- Eure Daten sind mit ca. `100 Hz` aufgenommen, daher ergeben Fenster um Events gut nutzbare Kurzsequenzen.
- Random Forest ist robust, schnell trainierbar und eignet sich gut als erste Vergleichsbasis fuer spaetere Modelle.

## Anpassung

Die wichtigsten Einstellungen stehen in [config.json](/Users/marcel/Desktop/ML4SCS/baseline_models/random_forest/config.json):

- `window_before_s` und `window_after_s`: Fenstergroesse vor/nach dem Event
- `labels`: explizite Label-Auswahl
- `min_samples_per_label` und `min_sessions_per_label`: automatische Filter, falls `labels` auf `null` gesetzt wird
- `n_estimators`, `max_depth`, `min_samples_leaf`: Random-Forest-Hyperparameter

## Ausfuehren

Evaluation mit Precision/Recall/F1 und Confusion Matrix:

```bash
python3 -m src.random_forest_baseline.evaluate
```

Training eines finalen Modells auf allen aktuell ausgewaehlten Events:

```bash
python3 -m src.random_forest_baseline.train
```

## Ausgaben

Die Evaluationsskripte schreiben ihre Ergebnisse nach `baseline_models/random_forest/output/`:

- `metrics.json`
- `classification_report.csv`
- `confusion_matrix.csv`
- `confusion_matrix.png`
- `fold_metrics.csv`
- `predictions.csv`
- `label_summary.csv`

Zusatz fuer das Training:

- `random_forest_model.pkl`
- `feature_importances.csv`

## Wichtige Annahmen

- Die vorhandenen gelabelten Dateien enthalten punktuelle Events, keine bereits segmentierten Schlagfenster.
- Die Label-Spalten sind im Projekt nicht komplett einheitlich (`Label_name`/`label_name`, `Labels`/`label`). Der Loader gleicht das automatisch aus.
- Sehr seltene Labels solltet ihr vorerst nur gezielt zuschalten, weil die Baseline sonst schnell instabil wird.
