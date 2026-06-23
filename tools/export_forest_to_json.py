#!/usr/bin/env python3
"""Exportiert das trainierte RandomForest-Schlagmodell (v_r_v1.pkl) in eine
kompakte JSON-Datei, die die iPhone-App on-device auswertet.

Format pro Baum: flache Arrays f/t/l/r/v
  f[i] = Feature-Index (>=0) an Knoten i, oder -1 wenn Blatt
  t[i] = Schwellwert (X[f] <= t -> links, sonst rechts)
  l[i] = Index linkes Kind, r[i] = Index rechtes Kind
  v[i] = Wahrscheinlichkeit fuer Klasse 'Vorhand' am Blatt (sonst 0)

Der Forest-Score fuer 'Vorhand' = Mittelwert der Blatt-Wahrscheinlichkeiten ueber
alle Baeume (soft voting, identisch zu sklearn predict_proba bei 2 Klassen).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = REPO_ROOT / "models" / "v_r_v1.pkl"
OUT_PATH = REPO_ROOT / "TennisTracker" / "TennisTracker" / "StrokeForest.json"

STATS = ["mean", "std", "min", "max", "ptp", "median", "energy"]


def main() -> None:
    payload = joblib.load(MODEL_PATH)
    forest = payload["model"]
    classes = [str(c) for c in payload["classes"]]
    assert classes == ["Rueckhand", "Vorhand"], f"unexpected classes: {classes}"
    vorhand_idx = classes.index("Vorhand")

    trees_json = []
    for est in forest.estimators_:
        tr = est.tree_
        n = tr.node_count
        f = [int(tr.feature[i]) for i in range(n)]
        t = [float(tr.threshold[i]) for i in range(n)]
        l = [int(tr.children_left[i]) for i in range(n)]
        r = [int(tr.children_right[i]) for i in range(n)]
        v = [0.0] * n
        for i in range(n):
            if l[i] == -1:  # Blatt
                counts = tr.value[i][0]
                total = float(counts.sum())
                v[i] = float(counts[vorhand_idx] / total) if total > 0 else 0.0
                f[i] = -1
        trees_json.append({"f": f, "t": t, "l": l, "r": r, "v": [round(x, 6) for x in v]})

    out = {
        "classes": classes,
        "signal_names": list(payload["signal_names"]),
        "stats": STATS,
        "window_before_s": float(payload["window_before_s"]),
        "window_after_s": float(payload["window_after_s"]),
        "n_features": int(forest.n_features_in_),
        "trees": trees_json,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, separators=(",", ":")))
    print(f"wrote {OUT_PATH} ({OUT_PATH.stat().st_size/1024:.1f} KB, {len(trees_json)} trees)")

    # --- Verifikation: pure-python Eval gegen sklearn predict_proba ---
    def eval_tree(tree, x):
        i = 0
        while tree["f"][i] != -1:
            i = tree["l"][i] if x[tree["f"][i]] <= tree["t"][i] else tree["r"][i]
        return tree["v"][i]

    def eval_forest(x):
        s = sum(eval_tree(tr, x) for tr in trees_json) / len(trees_json)
        return s  # P(Vorhand)

    rng = np.random.default_rng(0)
    n_feat = forest.n_features_in_
    max_err = 0.0
    mism = 0
    N = 500
    X = rng.normal(0, 1.5, size=(N, n_feat))
    sk = forest.predict_proba(X)[:, vorhand_idx]
    for k in range(N):
        ours = eval_forest(X[k])
        max_err = max(max_err, abs(ours - sk[k]))
        if (ours >= 0.5) != (sk[k] >= 0.5):
            mism += 1
    print(f"verify: max P(Vorhand) abs error = {max_err:.2e}, label mismatches = {mism}/{N}")
    if max_err > 1e-6 or mism > 0:
        print("FEHLER: Export stimmt nicht mit sklearn ueberein!", file=sys.stderr)
        sys.exit(1)
    print("OK: JSON-Forest identisch zu sklearn.")


if __name__ == "__main__":
    main()
