# SwingStream – Status & nächste Schritte

Stand: 2026-06-07 · Branch: `SwingStream-implementierung`

SwingStream = Apple-Watch-/iPhone-Apps + Mac-Dashboard, um Tennis-Schläge mit der
Apple Watch aufzuzeichnen und (live oder offline) auszuwerten. Teil des
ML4SCS-Projekts (gleiche CSV-Spalten, gleiches Modell `models/v_r_v1.pkl`).

## Zwei Modi (im iPhone-App-Picker wählbar)

- **Label Modus** (Platz, **ohne WLAN**): Uhr nimmt Sensordaten **verlustfrei mit
  100 Hz** lokal auf, überträgt die CSV am Ende per Bluetooth ans iPhone. Später am
  Mac labeln. *(Video parallel: siehe „Nächste Schritte".)*
- **Predict Modus** (zu Hause, **WLAN**): Uhr streamt live → iPhone leitet an das
  Mac-Dashboard weiter, das **live die Schlagart erkennt** (Vorhand/Rückhand).

## Architektur / Datenfluss

```text
Label:    Apple Watch ──(CoreMotion 100 Hz)──► lokale CSV-Datei (verlustfrei)
                          │ Live-Vorschau (transferUserInfo, Bluetooth)
                          ▼
                       iPhone ──(am Ende: transferFile)──► CSV in Dateien-App
                          + iPhone-Video (geplant), zeitgesynct

Predict:  Apple Watch ──(transferUserInfo)──► iPhone ──(HTTP /api/ingest, WLAN)──►
                       Mac-Dashboard ──► Peak-Erkennung + Modell ──► Live-Schlagart
```

**Schlüsselentscheidung:** Die **Uhr-Datei ist die verlustfreie Quelle der
Wahrheit** (lokale Schreibzugriffe, unabhängig von Funk). Der Live-Stream ist nur
Vorschau/Predict. So sind 100 Hz am Platz garantiert lückenlos.

## Was funktioniert (verifiziert)

- ✅ **Signing & Build** beider Targets (freier „Personal Team", inkl. HealthKit).
- ✅ Installation auf iPhone (13 Pro) + Apple Watch (Series 7, watchOS 26.5).
- ✅ **Verlustfreie 100-Hz-Aufnahme im Hintergrund** (Display aus): Testaufnahme
  2542 Zeilen, sequence 0–2541, **0 Lücken**, 99,3 Hz, keine Hänger.
- ✅ **Echter Hintergrundbetrieb** via vollständiger `HKWorkoutSession`
  (`HKLiveWorkoutBuilder` + `beginCollection`).
- ✅ **Transfer der CSV** Uhr→iPhone (`transferFile`), Datei in „Dateien"-App
  sichtbar + ShareLink-Export.
- ✅ **Session-Name** beim Start auf dem iPhone → `name_YYYYMMDD_HHMMSS.csv`.
- ✅ **Predict-Modus**: Live-Erkennung im Dashboard, Ergebnisse **identisch** zur
  Offline-Pipeline (`predict.py --scan`) – gleiche Schläge, Klassen, Konfidenzen.

## Komponenten / Dateien

```text
ML4SCS/
  SwingStream/                         Xcode-Projekt (via XcodeGen)
    project.yml                        XcodeGen-Spec (Team DEFYR9944A, HealthKit, Infos)
    Shared/
      SensorModels.swift               SensorSample / SensorBatch (Codable)
      CanonicalCSV.swift               kanonisches CSV-Format (Uhr + iPhone)
    SwingStream Watch App/
      WatchSessionController.swift      koordiniert Sampler+Workout+Datei+Link
      WatchMotionSampler.swift         CoreMotion 100 Hz, Batching
      WatchLocalRecorder.swift         verlustfreie lokale CSV
      WatchWorkoutKeeper.swift         HKWorkoutSession (Hintergrund)
      WatchConnectivitySender.swift    Befehle empfangen, transferUserInfo, transferFile
      WatchContentView.swift           Watch-UI
    SwingStream/                       iPhone-Bridge
      ContentView.swift                Moduswahl, Session-Name, Start/Stop, Aufnahmen
      PhoneWatchBridge.swift           Steuerung Uhr + Empfang (UserInfo/File) + Predict-Forward
      RecordingStore.swift             empfangene Dateien verwalten/teilen
      MacHTTPClient.swift              POST ans Mac-Dashboard (Predict)
  tools/
    swingstream_dashboard.py           Empfänger + Live-Plot + Recording + Predict-Engine
    swingstream_sim.py                 Simulator (synthetisch) + --replay (echte CSV)
    start_swingstream.command          Launcher (.venv_vr, zeigt LAN-IP)
  docs/
    SwingStream_IMPLEMENTATION_PLAN.md Gesamtplan
    SwingStream_STATUS.md              dieses Dokument
  recordings/                          aufgenommene/empfangene CSVs
```

## Build & Installieren (Entwickler-Workflow)

Geräte-IDs:
- iPhone von Floriann: `F013C954-F9D6-590E-A12C-703C89287258`
- Apple Watch von Florian: `11713F8F-7D75-50B9-8FE9-06372EB4B9E3`

```bash
cd ML4SCS/SwingStream
xcodegen generate            # nur nach project.yml-Änderungen nötig

# Bauen (jeweils -destination, NICHT -sdk, sonst bricht die Watch-Abhängigkeit)
xcodebuild -project SwingStream.xcodeproj -target "SwingStream" \
  -destination 'generic/platform=iOS' -allowProvisioningUpdates build
xcodebuild -project SwingStream.xcodeproj -target "SwingStream Watch App" \
  -destination 'generic/platform=watchOS' -allowProvisioningUpdates build

# Installieren (Uhr muss wach/entsperrt/nah sein)
xcrun devicectl device install app --device <iPhone-ID> build/Debug-iphoneos/SwingStream.app
xcrun devicectl device install app --device <Watch-ID>  "build/Debug-watchos/SwingStream Watch App.app"
```

**Wichtige Lehren / Stolpersteine:**
- Watch-Direktinstallation über Xcode-„Run" hängt am **Symbol-Kopieren** (Apple
  liefert für watchOS 26.5 die Symbole mit HTTP 403; Device-Copy ist sehr langsam).
  → Stattdessen **`devicectl install`** (umgeht das Symbol-Kopieren).
- Die **Watch-Funkverbindung** schläft schnell ein → `devicectl`-Timeouts;
  Uhr wach + entsperrt + nah am Mac halten, ggf. mehrfach versuchen.
- `xcodegen generate` überschreibt das Team → steht in `project.yml`
  (`DEVELOPMENT_TEAM: DEFYR9944A`).
- HealthKit funktioniert mit dem **kostenlosen** Account (App läuft 7 Tage, dann neu
  installieren).

## Benutzung

**Label (aufnehmen):** Watch-App öffnen → iPhone: Modus „Label", Session-Name,
„Aufnahme starten" → Uhr startet mit (Workout aktiv) → Arm/Display egal → „Stop" →
CSV erscheint unter „Aufnahmen" / Dateien-App.

**Predict (live):** Mac `start_swingstream.command` → iPhone: Modus „Predict",
Mac-IP + Port 8788, „Vorhersage starten" → Watch starten → Dashboard zeigt Schläge.

**Testen ohne Geräte:**
```bash
.venv_vr/bin/python tools/swingstream_dashboard.py
.venv_vr/bin/python tools/swingstream_sim.py --replay recordings/<datei>.csv --speed 5
```

## Nächste Schritte

1. **Video im Label-Modus (offen, als Nächstes):** iPhone-Kamera nimmt parallel
   auf; `name_datum.mov` neben `name_datum.csv`. **Zeit-Sync** über gemeinsamen
   Unix-Zeitstempel (Video-Startzeit ↔ `timestamp_unix_s` der Samples) +
   Metadaten-JSON; Labeling später: `video_time = sample_unix − video_start_unix`.
   Braucht Kamera-/Mikrofon-Berechtigung (Usage-Strings sind schon im Info.plist).
   → Geräte-Tests nötig.
2. **Export/Übertragung zum Mac komfortabler** (z. B. Sammel-Export, oder
   Upload-Button ins Mac-Dashboard bei WLAN).
3. **Label-Workflow am Mac**: aufgenommene CSV + Video in den vorhandenen
   Offline-Labeler einspeisen (Video als Referenz, Events → `labels/`).
4. **Robustheit**: iPhone-gesteuerter Start erreicht die Uhr nur, wenn die Watch-App
   offen ist; ggf. Hinweis/Fallback verbessern. Watch-Datei nach erfolgreichem
   Transfer optional aufräumen.
5. **Optional**: Predict-Modus-Latenz reduzieren (kleinere Batches/`sendMessage`
   wenn erreichbar); Bonjour-Discovery der Mac-IP.

## Offene Fragen

- Soll der Predict-Modus auch eine **Aufnahme** mitschreiben (für spätere
  Re-Analyse), oder rein live?
- Sollen Label-Aufnahmen automatisch ins ML4SCS-`recordings/` am Mac wandern?
