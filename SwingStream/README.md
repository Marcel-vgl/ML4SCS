# SwingStream (Watch + iPhone)

Apple-Watch- und iPhone-Apps, die Motion-/IMU-Daten live an das Mac-Dashboard
(`ML4SCS/tools/swingstream_dashboard.py`) streamen.

```text
Apple Watch  ->  iPhone Bridge  ->  Mac Dashboard
 (CoreMotion)     (WatchConnectivity)   (HTTP /api/ingest)
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
   - Watch fragt nach **Bewegungsdaten** → erlauben.

## Benutzung

1. Mac: `ML4SCS/tools/start_swingstream.command` starten (zeigt die Mac-IP an).
2. iPhone-App: die angezeigte **Mac-IP** und **Port 8788** eintragen,
   „Verbindung testen".
3. Watch-App: **Start** drücken → der Stream läuft mit 50 Hz.
4. Mac-Dashboard: „Recording starten" → schreibt eine ML4SCS-kompatible CSV nach
   `ML4SCS/recordings/`.

## Struktur

```text
project.yml                         XcodeGen-Spec (iOS-App + Watch-App)
Shared/SensorModels.swift           gemeinsames Sample-/Batch-Modell (beide Targets)
SwingStream/                        iPhone-Bridge
  SwingStreamApp.swift
  ContentView.swift                 UI: Mac-IP/Port, Status
  PhoneWatchBridge.swift            WCSession-Empfang + Weiterleitung
  MacHTTPClient.swift               HTTP POST an das Mac-Dashboard
SwingStream Watch App/              watchOS-App
  SwingStreamWatchApp.swift
  WatchContentView.swift            UI: Start/Stop, Rate
  WatchMotionSampler.swift          CoreMotion 50 Hz, Batching
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
