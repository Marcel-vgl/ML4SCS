# SwingStream (Watch + iPhone)

Apple-Watch- und iPhone-Apps für Tennis-Aufnahmen: Label-Modus speichert
verlustfreie Watch-CSV plus iPhone-Video, Predict-Modus streamt Motion-/IMU-Daten
live an das Mac-Dashboard (`ML4SCS/tools/swingstream_dashboard.py`).

```text
Label:   Apple Watch CSV  ->  iPhone-Dateien-App
         iPhone Kamera    ->  MOV + Sync-JSON

Predict: Apple Watch      ->  iPhone Bridge  ->  Mac Dashboard
          (CoreMotion)        (WatchConnectivity)   (HTTP /api/ingest)
```

## Projekt erzeugen / öffnen

Das Xcode-Projekt wird mit [XcodeGen](https://github.com/yonaskolb/XcodeGen) aus
`project.yml` erzeugt (XcodeGen ist via Homebrew installiert):

```bash
cd ML4SCS/SwingStream
xcodegen generate
open SwingStream.xcodeproj
```

## In Xcode einrichten

1. Target **SwingStream** → *Signing & Capabilities* → eigenes **Team** wählen.
   Das Watch-Target **SwingStream Watch App** übernimmt das Team automatisch.
2. iPhone als Run-Ziel wählen → **Run**. Die Watch-App wird mitinstalliert.
3. Beim ersten Start:
   - iPhone fragt nach **lokalem Netzwerk** → erlauben.
   - iPhone fragt nach **Kamera/Mikrofon** → erlauben.
   - Watch fragt nach **Bewegungsdaten** → erlauben.

## Benutzung

**Label:** Watch-App öffnen → iPhone: Modus „Label", Session-Name setzen,
iPhone auf den Platz ausrichten → „Aufnahme starten" → „Stop". Danach liegen
`<session>.csv`, `<session>.mov` und `<session>_video_metadata.json` in
„Aufnahmen" / Dateien-App.

**Predict:** Mac: `ML4SCS/tools/start_swingstream.command` starten → iPhone:
Modus „Predict", Mac-IP + Port 8788 eintragen → „Vorhersage starten".

## Struktur

```text
project.yml                         XcodeGen-Spec (iOS-App + Watch-App)
SwingStream.xcodeproj/              generiertes Xcode-Projekt
build/                              lokale Xcode-Build-Ausgaben
Shared/SensorModels.swift           gemeinsames Sample-/Batch-Modell (beide Targets)
docs/                               Status, Implementierungsplan, Onboarding
SwingStream/                        iPhone-Bridge
  SwingStreamApp.swift
  ContentView.swift                 UI: Modus, Kamera, Mac-IP/Port, Status
  PhoneWatchBridge.swift            WCSession-Empfang + Weiterleitung
  LabelVideoRecorder.swift          iPhone-Kameraaufnahme + Sync-Metadaten
  MacHTTPClient.swift               HTTP POST an das Mac-Dashboard
SwingStream Watch App/              watchOS-App
  SwingStreamWatchApp.swift
  WatchContentView.swift            UI: Start/Stop, Rate
  WatchMotionSampler.swift          CoreMotion 100 Hz, Batching
  WatchConnectivitySender.swift     WCSession-Versand ans iPhone
```

## Hinweise

- **Transport:** HTTP POST (kein WebSocket) – passt zum stdlib-Mac-Dashboard und
  braucht auf iOS nur `URLSession`.
- **CSV-Kompatibilität:** Das Mac-Dashboard mappt die kompakten JSON-Felder auf
  die kanonischen Apple-Watch-Spalten, sodass Aufnahmen direkt durch die
  bestehende ML4SCS-Pipeline (`src/stroke_model.py`, `src/predict.py`,
  Modell `v_r_v1.pkl`) laufen.
- Watch und iPhone müssen im selben WLAN wie der Mac sein.
- Aktueller Projektstand: `docs/SwingStream_STATUS.md`.
