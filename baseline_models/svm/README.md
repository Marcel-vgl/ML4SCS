# SVM Baseline

Dieser Ordner enthaelt eine zweite klassische Baseline fuer eure Schlagklassifikation, diesmal auf Basis eines Support Vector Machines (SVM) Modells.

## Idee

Das Modell nutzt dieselbe Event-Fenster-Logik wie eure Random-Forest-Baseline:

1. Jede gelabelte Zeile wird als Event interpretiert.
2. Um jedes Event wird ein Zeitfenster gebildet.
3. Aus allen Sensorwerten im Fenster werden Statistik-Features berechnet.
4. Die Features werden mit einem `SVC` klassifiziert.

Der wichtigste Unterschied: Vor dem SVM werden die Features skaliert, weil SVMs empfindlich auf unterschiedliche Merkmalsgroessen reagieren.

## Standard-Konfiguration

Die Default-Version arbeitet mit:

- `kernel = linear`
- `C = 0.5`
- `gamma = scale`
- `class_weight = balanced`

und nutzt dieselben Klassen wie die Random-Forest-Baseline:

- `Vorhand`
- `Rueckhand`
- `Schlaeger drehen`
- `Aufschlag von unten`
- `Kein Schlag / Other`

## Anpassung

Die wichtigsten Einstellungen stehen in [config.json](/Users/marcel/Desktop/ML4SCS/baseline_models/svm/config.json):

- `window_before_s` und `window_after_s`: Fenstergroesse vor/nach dem Event
- `labels`: explizite Label-Auswahl
- `kernel`, `c_value`, `gamma`, `degree`, `coef0`: SVM-Hyperparameter
- `class_weight`: Ausgleich fuer unbalancierte Klassen

## Ausfuehren

Evaluation:

```bash
python3 -m src.svm_baseline.evaluate
```

Training:

```bash
python3 -m src.svm_baseline.train
```

## Ausgaben

Die Evaluationsskripte schreiben ihre Ergebnisse nach `baseline_models/svm/output/`:

- `metrics.json`
- `classification_report.csv`
- `confusion_matrix.csv`
- `confusion_matrix.png`
- `fold_metrics.csv`
- `predictions.csv`
- `label_summary.csv`

Zusatz fuer das Training:

- `svm_model.pkl`
- `model_metadata.json`
