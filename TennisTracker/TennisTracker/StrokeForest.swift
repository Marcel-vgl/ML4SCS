import Foundation

/// On-device Repräsentation des trainierten RandomForest-Schlagmodells
/// (`v_r_v1.pkl`), exportiert nach `StrokeForest.json` von
/// `tools/export_forest_to_json.py`. Reines Foundation – keine Abhängigkeit von
/// Core ML, damit die Logik 1:1 gegen die Python-Pipeline testbar bleibt.
struct StrokeForest: Decodable {
    /// Ein einzelner Entscheidungsbaum als flache Arrays.
    /// `f[i] == -1` markiert ein Blatt; dann ist `v[i]` die P(Vorhand).
    struct Tree: Decodable {
        let f: [Int]      // Feature-Index je Knoten (-1 = Blatt)
        let t: [Double]   // Schwellwert: x[f] <= t -> links, sonst rechts
        let l: [Int]      // linkes Kind
        let r: [Int]      // rechtes Kind
        let v: [Double]   // P(Vorhand) am Blatt
    }

    let classes: [String]
    let signalNames: [String]
    let stats: [String]
    let windowBeforeS: Double
    let windowAfterS: Double
    let nFeatures: Int
    let trees: [Tree]

    enum CodingKeys: String, CodingKey {
        case classes
        case signalNames = "signal_names"
        case stats
        case windowBeforeS = "window_before_s"
        case windowAfterS = "window_after_s"
        case nFeatures = "n_features"
        case trees
    }

    /// Mittelwert der Blatt-Wahrscheinlichkeiten über alle Bäume (soft voting,
    /// identisch zu `RandomForestClassifier.predict_proba` bei zwei Klassen).
    func probabilityVorhand(_ features: [Double]) -> Double {
        var sum = 0.0
        for tree in trees {
            var i = 0
            while tree.f[i] != -1 {
                i = features[tree.f[i]] <= tree.t[i] ? tree.l[i] : tree.r[i]
            }
            sum += tree.v[i]
        }
        return sum / Double(trees.count)
    }

    /// Klassifiziert einen Feature-Vektor: (Label, Konfidenz, P(Vorhand)).
    func classify(_ features: [Double]) -> (label: String, confidence: Double, pVorhand: Double) {
        let p = probabilityVorhand(features)
        let isVorhand = p >= 0.5
        let label = isVorhand ? "Vorhand" : "Rueckhand"
        return (label, isVorhand ? p : 1.0 - p, p)
    }

    // MARK: - Laden

    static func decode(from data: Data) throws -> StrokeForest {
        try JSONDecoder().decode(StrokeForest.self, from: data)
    }

    /// Lädt das gebündelte Modell aus dem App-Bundle.
    static func loadFromBundle(_ bundle: Bundle = .main, name: String = "StrokeForest") -> StrokeForest? {
        guard let url = bundle.url(forResource: name, withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let forest = try? decode(from: data) else {
            return nil
        }
        return forest
    }
}
