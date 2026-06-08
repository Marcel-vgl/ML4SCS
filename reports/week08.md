# Week 08 Report - Machine Learning for Smart and Connected Systems (ML4SCS)

## Weekly Goal
The goal for this week was to move the project from offline labeling and first
experiments toward a more complete end-to-end workflow: labeled data,
baseline modeling, live prediction, and a dedicated Apple Watch/iPhone app for
collecting new tennis sessions.

## Work Done This Week

### 0. Project setup
- The project structure was extended from a pure Python/data repository to a
  combined ML and mobile-app project.
- The Apple Watch/iPhone app was renamed and cleaned up as **TennisTracker**.
- The main repository README was updated with a clearer project description,
  research question, component overview, team section, and project photo.
- Temporary test label files were removed so that the repository contains only
  useful label artifacts.

### 1. Data Work
- Additional labeled tennis data was added in `Daten/Daten_Labeled/`.
- Event label files were added for several sessions:

```text
labels/Jule_1_events.csv
labels/fritz_1_events.csv
labels/fritz_2_events.csv
labels/fritz_3_events.csv
labels/hannes_1_events.csv
```

- The labeled Fritz sessions are now used as the first structured training set
  for the Random-Forest baseline.
- The offline labeling workflow was improved so that new TennisTracker sessions
  can be synchronized more reliably with video metadata.
- The labeler now prefers stable sensor timestamps such as
  `motionTimestamp_sinceReboot(s)` instead of relying on unstable logging-time
  values.

### 2. Analysis / Modeling Work
- A Random-Forest baseline was implemented for stroke classification.
- The model uses event-based windows around labeled strokes:
  - `0.5s` before the event
  - `0.5s` after the event
- Statistical features are extracted from the sensor values in each window.
- The selected target classes are:
  - Vorhand
  - Rueckhand
  - Schlaeger drehen
  - Aufschlag von unten
  - Kein Schlag / Other
- A reusable training and evaluation package was added under:

```text
src/random_forest_baseline/
```

- Additional prediction code was added for live and offline inference:

```text
src/stroke_model.py
src/train.py
src/predict.py
```

- In addition to the multi-class Random-Forest baseline, a second, narrower
  model was trained only for the two main stroke classes `Vorhand` and
  `Rueckhand`.
- This binary model is used by the prediction scripts and the TennisTracker
  live dashboard because it focuses on the currently most reliable classes.
- The trained Vorhand/Rueckhand model artifact was added:

```text
models/v_r_v1.pkl
```

### 3. TennisTracker App Work
- A dedicated iPhone and Apple Watch app was implemented in:

```text
TennisTracker/
```

- The app supports two main modes:
  - **Label mode:** Apple Watch records lossless 100 Hz motion data locally,
    while the iPhone records a synchronized video.
  - **Predict mode:** Apple Watch streams motion data through the iPhone to the
    Mac dashboard for live stroke prediction.
- The Watch app now records CoreMotion data at 100 Hz and writes a local CSV as
  the source of truth.
- The iPhone app receives Watch files, manages recordings, and forwards live
  data to the Mac dashboard.
- Video recording was added on the iPhone with `.mov` output and a corresponding
  sync metadata JSON file.
- A shared sync anchor (`session_anchor_unix_s`) was introduced so that new
  video and sensor recordings can be aligned without manual clap-based offset
  estimation.
- Landscape recording support was added for better tennis-court video framing.
- App icons and Xcode project configuration were added for both iOS and watchOS.

### 4. Dashboard / Tooling Work
- A TennisTracker dashboard was added:

```text
tools/tennistracker_dashboard.py
```

- The dashboard receives live data from the iPhone, visualizes the sensor stream,
  records incoming samples, detects likely stroke peaks, and runs the prediction
  model.
- A simulator was added for testing the dashboard without the real Watch/iPhone
  app:

```text
tools/tennistracker_sim.py
```

- A launcher script was added:

```text
tools/start_tennistracker.command
```

- The live dashboard prediction path was aligned with the offline prediction
  path so that the same model logic is used in both cases.

### 5. Repository / Documentation Work
- Documentation was added for the TennisTracker app:

```text
TennisTracker/README.md
TennisTracker/docs/TennisTracker_IMPLEMENTATION_PLAN.md
TennisTracker/docs/TennisTracker_STATUS.md
```

- The repository README was updated to describe:
  - project goal
  - data collection and labeling workflow
  - modeling pipeline
  - TennisTracker app
  - dashboards and helper tools
  - team members
- A team photo was added under:

```text
docs/assets/team.jpg
```

## Experiments Conducted

| Experiment | Change Made | Result | Interpretation |
|-----------|-------------|--------|----------------|
| Random-Forest baseline | Built event windows around labeled strokes and extracted statistical features | Accuracy: `0.886`, weighted F1: `0.887`, macro F1: `0.737` | The baseline works well for frequent classes, but weaker classes still need more data |
| Vorhand/Rueckhand model | Trained a separate model filtered to only `Vorhand` and `Rueckhand` | Saved as `models/v_r_v1.pkl` and connected to `src/predict.py` plus the live dashboard | A binary model is more practical for the current live demo because these two classes have the strongest label base |

## Results
- A first complete baseline model was created using 377 labeled events and 164
  extracted features.
- Overall Random-Forest evaluation results:

```text
accuracy:          0.886
balanced accuracy: 0.741
macro F1:          0.737
weighted F1:       0.887
```

- Class-level performance was strongest for frequent or clearly separable
  classes:
  - Vorhand F1: `0.976`
  - Rueckhand F1: `0.934`
  - Aufschlag von unten F1: `0.973`
- `Kein Schlag / Other` was not recognized well yet, most likely because this
  class is less consistent and underrepresented.
- A separate Vorhand/Rueckhand model (`models/v_r_v1.pkl`) was added for the
  live prediction workflow. It only predicts `Vorhand` and `Rueckhand`, which
  makes it better suited for the current app/dashboard demonstration than the
  broader multi-class baseline.
- The project now has a working path from data recording to labeling, feature
  extraction, model training, offline prediction, and live dashboard prediction.

## Challenges

### Data and Label Quality
- The labels are still not evenly distributed across all classes.
- Some classes, especially `Kein Schlag / Other`, need more examples and clearer
  annotation rules.
- Existing datasets use slightly different label column names and formats, so
  the loader has to normalize them.

### Synchronization
- Older recordings still require manual or clap-based synchronization.
- New TennisTracker recordings use sync metadata, but this workflow still needs
  more validation with longer real tennis sessions.

### Live Prediction
- Live prediction works technically, but model quality is still limited by the
  current dataset size and label balance.
- The current live model focuses only on `Vorhand` and `Rueckhand`; additional
  stroke types will require more labeled training data before they can be added
  reliably.

## Key Insights
- A simple Random-Forest model is already a useful baseline for tennis stroke
  classification from smartwatch IMU data.
- A narrower binary model can be useful for the live demo even while the
  multi-class baseline remains important for evaluation and future expansion.
- Event-based labeling plus fixed windows is a practical first modeling approach
  because the labels mark specific stroke moments.
- For new recordings, storing CSV, video, and sync metadata together is much more
  reliable than trying to reconstruct synchronization later.
- The Apple Watch CSV should be treated as the source of truth because live
  streaming can drop data, while local recording can preserve the full signal.

## Plan for Next Week
- Collect new TennisTracker sessions on the tennis court with CSV, video, and
  sync metadata.
- Validate that Watch background recording remains stable during longer real
  sessions.
- Label more sessions, especially underrepresented classes and non-stroke
  movement.
- Retrain and evaluate the baseline with the expanded dataset.
- Improve the live prediction dashboard based on real court tests.
- Decide whether additional features or a sequence model should be tested after
  the Random-Forest baseline.

## Contributions
- Florian Schneider:
- Marcel Vogeler:
- Metehan Tetik:
