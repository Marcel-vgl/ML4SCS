# Machine Learning for smart and connected systems — Group Project

## Project Overview
This repository contains our semester-long group project for **Machine Learning for Quantified Self**.

The goal of this repository is to document the full project workflow over the semester:
- problem definition
- data understanding
- preprocessing
- feature engineering
- modeling
- evaluation
- iteration
- final conclusions

---

## Team Members
- Florian Schneider
- Marcel Vogeler
- Metehan Tetik

---

## Project Question

Inwiefern lassen sich Bewegungs- und IMU-Daten einer Smartwatch (Apple Watch SensorLog) nutzen, um Tennisbewegungen wie Vorhand, Rückhand und Topspin mittels Machine Learning automatisch zu erkennen und zu klassifizieren?

Ziel: Ein Klassifizierungsmodell, das verschiedene Tennisbewegungen anhand von Sensordaten unterscheidet zwischen:

* Klasse 1: Vorhand
* Klasse 2: Rückhand
* Klasse 3: Keine Schlagbewegung

---

## Dataset
- **Dataset name:**  
- **Source:**  
- **Type of data:**  
- **Target variable:**  
- **Important features:**  

---

## Offline Labeling

For the KINGSTON test recording with video and Apple Watch SensorLog CSV:

```bash
python3 tools/offline_label_tool.py
```

Then open:

```text
http://127.0.0.1:8765
```

The tool uses the clap-based sync offset:

```text
CSV time = video time + 14.078 seconds
```

Keyboard shortcuts:

- `1`: Vorhand
- `2`: Rueckhand
- `3`: Kein Schlag / Other
- `n`: next IMU peak
- `p`: previous IMU peak
- arrow left/right: one frame backward/forward
- space: play/pause

Labels are saved as event annotations:

```text
labels/H_2_050526_events.csv
```
