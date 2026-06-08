# SwingStream – Status & nächste Schritte

Stand: 2026-06-07 · Branch: `SwingStream-implementierung`

SwingStream = Apple-Watch-/iPhone-Apps + Mac-Dashboard, um Tennis-Schläge mit der
Apple Watch aufzuzeichnen und (live oder offline) auszuwerten. Teil des
ML4SCS-Projekts (gleiche CSV-Spalten, gleiches Modell `models/v_r_v1.pkl`).

## Zwei Modi (im iPhone-App-Picker wählbar)

- **Label Modus** (Platz, **ohne WLAN**): Uhr nimmt Sensordaten **verlustfrei mit
  100 Hz** lokal auf, das iPhone nimmt parallel Video auf. Am Ende überträgt die
  Uhr die CSV per Bluetooth ans iPhone. Später am Mac labeln.
- **Predict Modus** (zu Hause, **WLAN**): Uhr streamt live → iPhone leitet an das
  Mac-Dashboard weiter, das **live die Schlagart erkennt** (Vorhand/Rückhand).

## Architektur / Datenfluss

```text
Label:    Apple Watch ──(CoreMotion 100 Hz)──► lokale CSV-Datei (verlustfrei)
                          │ Live-Vorschau (transferUserInfo, Bluetooth)
                          ▼
                       iPhone ──(am Ende: transferFile)──► CSV in Dateien-App
                          + iPhone-Video + Sync-JSON

Predict:  Apple Watch ──(transferUserInfo)──► iPhone ──(HTTP /api/ingest, WLAN)──►
                       Mac-Dashboard ──► Peak-Erkennung + Modell ──► Live-Schlagart
```

**Schlüsselentscheidung:** Die **Uhr-Datei ist die Quelle der Wahrheit** (lokale
Schreibzugriffe, unabhängig von Funk). Der Live-Stream ist nur Vorschau/Predict.
100 Hz sollen ohne Lücken aufgezeichnet werden; dafür muss der CoreMotion-Callback
leicht bleiben und die Watch-App per Workout-Background-Mode weiterlaufen.

## Was funktioniert (verifiziert)

- ✅ **Signing & Build** beider Targets (freier „Personal Team", inkl. HealthKit).
- ✅ Installation auf iPhone (13 Pro) + Apple Watch (Series 7, watchOS 26.5).
- ✅ **100-Hz-Aufnahme** per CoreMotion (`deviceMotionUpdateInterval = 1/100`),
  CSV-Zeitachse jetzt stabil aus `CMDeviceMotion.timestamp` statt aus
  Callback-Wallclock-Zeit.
- ✅ **Hintergrundbetrieb** via `HKWorkoutSession` + `HKLiveWorkoutBuilder` +
  `beginCollection` und seit dieser Session zusätzlichem Watch-Info.plist-Key
  `WKBackgroundModes = workout-processing`.
- ✅ **Transfer der CSV** Uhr→iPhone (`transferFile`), Datei in „Dateien"-App
  sichtbar + ShareLink-Export.
- ✅ **Session-Name** beim Start auf dem iPhone → `name_YYYYMMDD_HHMMSS.csv`.
- ✅ **Videoaufnahme im Label-Modus implementiert und auf Gerät getestet**:
  iPhone speichert `name_YYYYMMDD_HHMMSS.mov` plus
  `name_YYYYMMDD_HHMMSS_video_metadata.json`; CSV, Video und JSON werden unter
  „Aufnahmen" gebündelt angezeigt.
- ✅ **Gemeinsamer Sync-Anker**: iPhone startet zuerst Video, plant dann
  `session_anchor_unix_s` ca. 1,25 s in die Zukunft und schickt ihn an die Watch.
  Neue SwingStream-Aufnahmen sollen im Labeler ohne manuellen Offset laufen
  (`offset = 0`).
- ✅ **Offline-Labeler angepasst**: `tools/offline_label_tool.py` erkennt passende
  `*_video_metadata.json` automatisch. Ohne Metadaten bleibt die alte
  Audio-/Peak-basierte Offset-Schätzung als Fallback aktiv.
- ✅ **Querformatmodus iPhone**: App erlaubt Landscape Left/Right; im Label-Modus
  gibt es in Landscape eine große 16:9-Kameravorschau links und Controls rechts.
  Videos werden mit aktueller Orientation statt hart mit 90° geschrieben.
- ✅ **Predict-Modus**: Live-Erkennung im Dashboard, Ergebnisse **identisch** zur
  Offline-Pipeline (`predict.py --scan`) – gleiche Schläge, Klassen, Konfidenzen.

## Stand nach Session 2026-06-07

Implementiert und geprüft am 2026-06-07:

- Neue iPhone-Komponente `LabelVideoRecorder.swift` mit `AVCaptureSession`,
  wählbarer Kamera (Rückkamera, Frontkamera, Ultraweitwinkel, Tele), wählbarer
  Qualität (720p, 1080p, Hoch, Mittel), optionalem Mikrofon, Live-Preview und
  `.mov`-Aufzeichnung.
- Label-Start/Stop ist gekoppelt: `PhoneWatchBridge.start(session:)` startet im
  Label-Modus zuerst die iPhone-Videoaufnahme. Erst wenn AVCapture
  `didStartRecordingTo` meldet, plant die App `session_anchor_unix_s` und schickt
  den Startbefehl an die Watch; `stop()` beendet Video und Watch-Aufnahme.
- Pro Label-Session entstehen im iPhone-Dokumentenordner `recordings/`:
  - `name_YYYYMMDD_HHMMSS.csv` (Watch, verlustfreie Sensordaten)
  - `name_YYYYMMDD_HHMMSS.mov` (iPhone-Video)
  - `name_YYYYMMDD_HHMMSS_video_metadata.json` (Sync-Metadaten)
- Die Sync-JSON enthält jetzt u. a. `video_start_unix_s`,
  `session_anchor_unix_s`, `video_anchor_time_s`, `video_stop_unix_s`,
  `video_duration_s`, `video_orientation`, `video_rotation_angle_degrees` und die
  Formel
  `video_time_s = sample.timestamp_unix_s - video_start_unix_s; session_time_s = sample.timestamp_unix_s - session_anchor_unix_s`.
- Die iPhone-UI hat einen separaten Screen „Aufnahmen": CSV/MOV/JSON werden nach
  Session gebündelt, nach Datum/Uhrzeit sortiert, löschbar und gemeinsam per
  ShareLink/AirDrop teilbar.
- Detailansicht einer Aufnahme zeigt das Video in der App per `VideoPlayer`,
  listet zugehörige Dateien und zeigt Zeitinformationen.
- Querformat & Vorschau: iPhone-App erlaubt Landscape; im Label-Modus wird in Landscape eine große Vorschau angezeigt. Die Preview nutzt nun `resizeAspectFill`, um den kompletten Platz vollflächig ohne schwarze Ränder auszufüllen.
- AppIcons für beide Apps implementiert: Das Bildschirmfoto `/Users/florianschneider/screenshots/Bildschirmfoto 2026-06-07 um 18.33.21.png` wurde quadratisch zugeschnitten und in alle benötigten Auflösungen für iOS und watchOS exportiert.
- Beide Asset-Kataloge (`Assets.xcassets/AppIcon.appiconset`) wurden in den Projektverzeichnissen angelegt und die Compiler-Einstellung `ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon` in `project.yml` eingetragen.
- **Fix für Querformat-Freeze & Vorschau-Rotation:** Alle Aufrufe von UIKit und `UIDevice` zur Ermittlung der Displayausrichtung werden nun strikt auf dem Main Thread ausgeführt (mittels `DispatchQueue.main.async` in `refreshVideoOrientation()` und vorab aufgelösten Parametern beim Starten/Vorbereiten der Aufnahme). Zudem wurde eine Race Condition behoben, bei der das Setzen des `videoRotationAngle` auf der Preview-Verbindung fehlschlug, weil die Kamera-Session beim Erstellen der SwiftUI-View noch nicht aktiv war. Die Rotation wird nun dynamisch in `layoutSubviews()` der Preview-View angewendet, was sicherstellt, dass das Livebild immer korrekt ausgerichtet (nicht seitlich gedreht) dargestellt wird.
- Build- und Install-Status dieser Session:
  - `xcodebuild -project SwingStream.xcodeproj -target "SwingStream" -destination 'generic/platform=iOS' -allowProvisioningUpdates build` → **BUILD SUCCEEDED**
  - iPhone installiert: `com.florianschneider.SwingStream`
  - Watch installiert: `com.florianschneider.SwingStream.watchkitapp`

## Analyse wichtiger Testdateien aus dieser Session

### `session_20260607_170556.csv`

Pfad: `/Users/florianschneider/Downloads/session_20260607_170556.csv`

- Im Offline-Labeler waren zunächst keine Ausschläge sichtbar.
- Die Datei enthielt aber starke Signale (`score` max ca. 10, User-Acceleration
  max ca. 8,39 G, Gyro max ca. 27,16 rad/s); das Problem war also nicht
  „keine Bewegung".
- Ursache: `loggingTime(txt)` hatte viele doppelte Zeiten und große Sprünge
  (2135 von 3177 Zeilen mit doppeltem Logging-Zeitstempel, max. Logging-Gap ca.
  14,736 s). Der Labeler nutzte diese Wallclock-Zeitachse.
- Fix:
  - `tools/offline_label_tool.py` nutzt jetzt bevorzugt
    `motionTimestamp_sinceReboot(s)` als relative Sensorzeitachse.
  - `WatchMotionSampler.swift` schreibt `timestamp_unix_s` stabil aus
    `CMDeviceMotion.timestamp` + fixem Unix-Offset statt pro Callback `Date()`.

### `video_test1_20260607_173658.*`

Pfade:
- `/Users/florianschneider/Downloads/video_test1_20260607_173658_video_metadata.json`
- `/Users/florianschneider/Downloads/video_test1_20260607_173658.mov`
- `/Users/florianschneider/Downloads/video_test1_20260607_173658.csv`

Gemessen:
- `video_start_unix_s = 1780846618.62143`
- CSV-Start aus `locationTimestamp_since1970(s) = 1780846618.773933`
- CSV startet also `+0.152503 s` nach Video-Start.
- Für die alte Labeler-Konvention `csv_time = video_time + offset` wäre das
  manuell etwa `offset = -0.153 s`.
- Video-Dauer per ffprobe ca. `43.435 s`; CSV-Dauer ca. `56.057 s`; CSV lief also
  nach Video-Stop weiter.
- Echte Sensorlücken in der CSV:
  - Zeilen `1869 -> 1870`: `4.060216 s`
  - Zeilen `3079 -> 3080`: `8.543541 s`
- Die Sprünge stehen in `motionTimestamp_sinceReboot(s)` und
  `locationTimestamp_since1970(s)`, also sind es echte Watch-Sampling-Lücken,
  keine UI-/Parsing-Artefakte.
- Fix danach: `WatchSessionController.swift` entkoppelt CoreMotion von CSV-I/O und
  WatchConnectivity. Der CoreMotion-Callback legt nur noch Batches ab; Schreiben
  und `transferUserInfo` laufen seriell auf `watchOutput`.

### `Videotest2_20260607_175714.*`

Pfade:
- `/Users/florianschneider/Downloads/Videotest2_20260607_175714.mov`
- `/Users/florianschneider/Downloads/Videotest2_20260607_175714_video_metadata.json`
- `/Users/florianschneider/Downloads/Videotest2_20260607_175714.csv`

Gemessen:
- `video_start_unix_s = 1780847834.727748`
- `session_anchor_unix_s = 1780847835.977931`
- `video_anchor_time_s = 1.25018310546875`
- CSV erste Probe: `1780847835.977931`
- `CSV-Start - session_anchor_unix_s = 0.0 s`

Ergebnis: Der neue Sync-Anker funktioniert am Start exakt. Das verbleibende
Problem war eine echte Watch-Datenlücke:

- Zeile `1354 -> 1355`
- Sprung von `15:57:29.599Z` auf `15:57:40.923Z`
- Gap in `motionTimestamp_sinceReboot(s)`: `11.324129 s`

Wahrscheinliche Ursache: Watch-App wurde beim Display-Senken/Background trotz
Workout-Session zeitweise suspendiert. Gefundener Unterschied zu SensorLog:
`SwingStream Watch App/Info.plist` hatte zwar HealthKit-Usage/Entitlement, aber
keinen `WKBackgroundModes`-Eintrag. Fix: `WKBackgroundModes` mit
`workout-processing` ergänzt und Watch-App neu installiert. Dieser Fix muss mit
einer neuen Testaufnahme validiert werden.

## Komponenten / Dateien

```text
ML4SCS/
  SwingStream/                         Xcode-Projekt (via XcodeGen)
    project.yml                        XcodeGen-Spec (Team DEFYR9944A, HealthKit, Infos)
    SwingStream.xcodeproj/             generiertes Xcode-Projekt
    build/                             lokale Xcode-Build-Ausgaben
    docs/
      SwingStream_IMPLEMENTATION_PLAN.md Gesamtplan
      SwingStream_STATUS.md              dieses Dokument
    Shared/
      SensorModels.swift               SensorSample / SensorBatch (Codable)
      CanonicalCSV.swift               kanonisches CSV-Format (Uhr + iPhone)
    SwingStream Watch App/
      Info.plist                       Watch-Background: WKBackgroundModes/workout-processing
      SwingStreamWatch.entitlements    HealthKit-Entitlement
      WatchSessionController.swift      koordiniert Sampler+Workout+Datei+Link
      WatchMotionSampler.swift         CoreMotion 100 Hz, Batching
      WatchLocalRecorder.swift         verlustfreie lokale CSV
      WatchWorkoutKeeper.swift         HKWorkoutSession (Hintergrund)
      WatchConnectivitySender.swift    Befehle empfangen, transferUserInfo, transferFile
      WatchContentView.swift           Watch-UI
    SwingStream/                       iPhone-Bridge
      ContentView.swift                Moduswahl, Session-Name, Start/Stop, Aufnahmen
      PhoneWatchBridge.swift           Steuerung Uhr + Empfang (UserInfo/File) + Predict-Forward
      LabelVideoRecorder.swift         iPhone-Kameraaufnahme + Sync-Metadaten
      RecordingStore.swift             empfangene Dateien verwalten/teilen
      MacHTTPClient.swift              POST ans Mac-Dashboard (Predict)
  tools/
    swingstream_dashboard.py           Empfänger + Live-Plot + Recording + Predict-Engine
    swingstream_sim.py                 Simulator (synthetisch) + --replay (echte CSV)
    offline_label_tool.py              Offline-Video/CSV-Labeler, erkennt Sync-JSON
    start_swingstream.command          Launcher (.venv_vr, zeigt LAN-IP)
  docs/
    ml-pipeline/                       Modell-/Labeler-/CSV-Dokumentation
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
- Watch-Background ist zweiteilig:
  - `SwingStreamWatch.entitlements`: `com.apple.developer.healthkit = true`
  - `SwingStream Watch App/Info.plist`: `WKBackgroundModes = workout-processing`
  Beides ist nötig, damit `HKWorkoutSession` auch bei gesenktem Arm zuverlässig
  Background-Runtime bekommt.

## Benutzung

**Label (aufnehmen):** Watch-App öffnen → auf der Watch muss `Hintergrund: aktiv`
während der Aufnahme erscheinen → iPhone: Modus „Label", Session-Name, Kamera/Mikro
erlauben, iPhone auf den Platz ausrichten → „Aufnahme starten" → Uhr startet über
den geplanten `session_anchor_unix_s` mit → „Stop" → CSV, MOV und Sync-JSON
erscheinen unter „Aufnahmen" / Dateien-App.

**Querformat aufnehmen:** iPhone-Ausrichtungssperre ausschalten, iPhone vor Start
quer halten. Im Label-Modus wechselt die App in das Landscape-Layout mit großer
16:9-Preview. Für größtmöglichen Platz-Ausschnitt ggf. Ultraweitwinkel + 720p/1080p
wählen.

**Offline labeln:** `tools/offline_label_tool.py` mit CSV + Video starten/öffnen.
Wenn neben CSV/Video eine passende `*_video_metadata.json` liegt, wird sie
automatisch genutzt und der Sensor-Offset auf `0.0` gesetzt. Bei fremden
Video/CSV-Paaren ohne Metadaten bleibt die Audio-/Peak-basierte Offset-Schätzung
aktiv.

**Predict (live):** Mac `start_swingstream.command` → iPhone: Modus „Predict",
Mac-IP + Port 8788, „Vorhersage starten" → Watch starten → Dashboard zeigt Schläge.

**Testen ohne Geräte:**
```bash
.venv_vr/bin/python tools/swingstream_dashboard.py
.venv_vr/bin/python tools/swingstream_sim.py --replay recordings/<datei>.csv --speed 5
```

## Nächste Schritte

1. **Neue Background-Testaufnahme nach `WKBackgroundModes`-Fix:** iPhone quer/hoch
   nach Bedarf, Watch-App offen, `Hintergrund: aktiv`; danach CSV prüfen:
   `motionTimestamp_sinceReboot(s)` darf keine Gaps > ca. 0,03 s haben.
2. **Querformat auf Gerät prüfen:** App muss drehen, Preview muss den kompletten
   Platz zeigen, `.mov` muss korrekt orientiert sein; Metadaten müssen
   `video_orientation` und `video_rotation_angle_degrees` enthalten.
3. **Export/Übertragung zum Mac komfortabler** (z. B. Sammel-Export, oder
   Upload-Button ins Mac-Dashboard bei WLAN).
4. **Label-Workflow am Mac**: aufgenommene CSV + Video in den vorhandenen
   Offline-Labeler einspeisen (Video als Referenz, Events → `labels/`).
5. **Robustheit**: iPhone-gesteuerter Start erreicht die Uhr nur, wenn die Watch-App
   offen ist; ggf. Hinweis/Fallback verbessern. Watch-Datei nach erfolgreichem
   Transfer optional aufräumen.
6. **Optional**: Predict-Modus-Latenz reduzieren (kleinere Batches/`sendMessage`
   wenn erreichbar); Bonjour-Discovery der Mac-IP.

## Offene Fragen

- Soll der Predict-Modus auch eine **Aufnahme** mitschreiben (für spätere
  Re-Analyse), oder rein live?
- Sollen Label-Aufnahmen automatisch ins ML4SCS-`recordings/` am Mac wandern?

---

# Onboarding für einen anderen Agenten

Alles, was nötig ist, um hier ohne Vorwissen weiterzuarbeiten.

## Umgebung (dieser Mac)

- Arbeitsverzeichnis: `/Users/florianschneider` · Repo: `/Users/florianschneider/ML4SCS` (Git).
- macOS (darwin), Apple Silicon, Shell zsh, Homebrew unter `/opt/homebrew`.
- **Xcode 26.5** installiert (`xcode-select -p` → `/Applications/Xcode.app/...`).
- **XcodeGen**: `/opt/homebrew/bin/xcodegen` (erzeugt `.xcodeproj` aus `project.yml`).
- Python-venvs im Repo (gitignored):
  - **`.venv_vr/bin/python`** ← für Dashboard/Modell (numpy 2.4, scikit-learn 1.9,
    joblib, pandas, scipy). **Immer dieses venv für `tools/*.py` und `src/*.py`.**
  - `.venv311` ← Jupyter/Notebooks.
- Datumskontext der Entwicklung: 2026-06-07.

## ML4SCS-Kontext (die bestehende Pipeline, die SwingStream bedient)

- **Forschung**: Tennis-Schlagklassifikation aus Apple-Watch-IMU-Daten.
- **CSV-Format**: „SensorLog"-Stil mit Spalten wie `motionUserAccelerationX(G)`,
  `motionRotationRateX(rad/s)`, `motionTimestamp_sinceReboot(s)`, `loggingTime(txt)` …
  (siehe `Daten/`, `uploads/`). SwingStream schreibt **exakt** dieses Format
  (`Shared/CanonicalCSV.swift` ↔ `tools/swingstream_dashboard.py CSV_COLUMNS`).
  Nicht direkt aufgezeichnete Sensorgruppen (Location, Magnetometer, Pedometer,
  Altimeter) werden mit stabilen Platzhaltern geschrieben, damit die Spaltenstruktur
  zu `Daten/fritz_*.csv` passt.
- **Kerncode** in `src/`:
  - `stroke_model.py`: `load_sensor_table(csv)→SensorTable`,
    `detect_energy_peaks(table)`, `predict_one(model, table, t)`,
    `load_model(path)`, `extract_features`, Konstanten `IMU_COLUMNS`.
  - `predict.py`: CLI (`--scan`, `--events-csv`, `--times`).
  - `preprocessing.py`, `train.py`, `evaluate.py`.
- **Modell**: `models/v_r_v1.pkl` (joblib dict). Klassen **`['Rueckhand','Vorhand']`**,
  `window_before_s=0.45`, `window_after_s=0.35`, 15 `signal_names`:
  `accelerometerAcceleration{X,Y,Z}(G)`, `motion{Pitch,Roll,Yaw}(rad)`,
  `motionRotationRate{X,Y,Z}(rad/s)`, `motionUserAcceleration{X,Y,Z}(G)`,
  `rotation_magnitude`, `score`, `user_acc_magnitude`
  (`score = user_acc_mag + 0.12*rotation_mag`).
- Andere Tools: `tools/prediction_dashboard.py` (Offline-Upload-Dashboard, Port 8770),
  `tools/offline_label_tool.py` (Labeler, Port 8765, `start_labeler.command`).
- `.gitignore` ignoriert u. a. `uploads/`, venvs, `*.mp4/*.mov`, `docs/ml-pipeline/csv_graph_modes.md`,
  einige lokale `.md` (NICHT die SwingStream-Docs).

## Netzwerk-/Steuerprotokoll (Watch ↔ iPhone ↔ Mac)

**SensorSample** (kompakte JSON-Keys, `Shared/SensorModels.swift`):
`sequence, timestamp_unix_s, watch_uptime_s, user_acc_{x,y,z}_g, gyro_{x,y,z}_rad_s,
acc_{x,y,z}_g, gravity_{x,y,z}_g, roll_rad, pitch_rad, yaw_rad, quat_{x,y,z,w}`.
Auf der Uhr: `acc_*` = userAcceleration + gravity (Rohbeschleunigung in G),
`watch_uptime_s` = `CMDeviceMotion.timestamp` (→ `motionTimestamp_sinceReboot`).

**SensorBatch**: `{type:"sensor_batch", source, session_id, bridge_received_unix_s, samples:[…]}`.

- **Watch→iPhone Live**: `WCSession.transferUserInfo(["batch": <JSON-Data von SensorBatch>])`
  (hintergrundfähig, Bluetooth, verlustfrei-queued; **kein** `sendMessageData`, weil
  das im Hintergrund die Erreichbarkeit braucht).
- **Watch→iPhone Datei (am Ende)**: `transferFile(csvURL, metadata:["session": name])`.
  iPhone empfängt in `session(_:didReceive:WCSessionFile)` → Datei **synchron** im
  Delegate kopieren (URL ist danach ungültig).
- **iPhone→Watch Steuerung**: `["command":"start"/"stop", "session":name, "mode":"label"/"predict"]`
  plus im Label-Modus `start_at_unix_s`/`session_anchor_unix_s` via `sendMessage`
  (wenn erreichbar) **und** `updateApplicationContext` (Fallback).
  ⚠️ Die **Watch-App muss geöffnet sein**, damit sie den Start empfängt und die
  Workout-Session starten kann (vom iPhone aus lässt sich die Watch-App nicht starten).
- **Sync-Konvention Label-Modus**:
  - iPhone startet Video wirklich.
  - iPhone setzt `session_anchor_unix_s = Date.now + 1.25 s`.
  - Watch wartet bis zu diesem Unix-Zeitpunkt und startet dann CoreMotion.
  - CSV-Zeitstempel sind absolut (`locationTimestamp_since1970(s)`) und relativ
    (`motionTimestamp_sinceReboot(s)`) konsistent.
  - Offline-Labeler nutzt bei vorhandener Sync-JSON die Video-Zeitachse direkt:
    `video_t = locationTimestamp_since1970(s) - video_start_unix_s`, `offset = 0`.
- **iPhone→Mac (Predict)**: `POST http://<mac-ip>:8788/api/ingest` mit dem Batch-JSON.
- **Mac-Dashboard-Endpunkte**: `GET /` (UI), `POST /api/ingest`, `GET /api/live`
  (Polling: Stats + Punkte + `prediction`), `POST /api/record/{start,stop}`.

## Signing & Geräte

- **Team**: `DEFYR9944A` (Florian Schneider, *Personal Team*, Apple-ID
  `florianschneider2003@gmail.com`). **Kostenlos → Apps laufen 7 Tage**, dann neu
  installieren. Team steht in `project.yml` (`DEVELOPMENT_TEAM`), Style Automatic.
- HealthKit-Entitlement funktioniert mit diesem Free-Account
  (`SwingStream Watch App/SwingStreamWatch.entitlements`, von XcodeGen erzeugt).
- Geräte (Developer Mode an, Zertifikat vertraut):
  - iPhone 13 Pro, iOS 26.5 — devicectl-ID `F013C954-F9D6-590E-A12C-703C89287258`
  - Apple Watch Series 7, watchOS 26.5 — devicectl-ID `11713F8F-7D75-50B9-8FE9-06372EB4B9E3`
- Bundle-IDs: `com.florianschneider.SwingStream` (iOS),
  `com.florianschneider.SwingStream.watchkitapp` (watchOS,
  `WKCompanionAppBundleIdentifier` = iOS-ID).
- iOS-Orientierungen: Portrait, Landscape Left, Landscape Right; iPad zusätzlich
  Portrait Upside Down.
- Watch-Background-Keys:
  - `SwingStream Watch App/SwingStreamWatch.entitlements`:
    `com.apple.developer.healthkit = true`
  - `SwingStream Watch App/Info.plist`: `WKBackgroundModes = workout-processing`

## Xcode-/Build-Nutzung (Details & Fallen)

- **Bauen immer mit `-destination 'generic/platform=iOS'` bzw. `watchOS`**, NICHT mit
  `-sdk iphoneos`: Letzteres zwingt die eingebettete Watch-App aufs iOS-SDK →
  „does not conform to WCSessionDelegate" u. ä.
- **Keine Schemes** nach `xcodegen generate` → mit `-target "<Name>"` bauen (Xcode legt
  Schemes nur beim Öffnen der App an). `-derivedDataPath` braucht `-scheme`, daher
  weglassen; `-target` schreibt nach `./build/Debug-<sdk>/`.
- `-allowProvisioningUpdates` mitgeben (Profil/HealthKit automatisch).
- **`xcodegen generate` überschreibt die `.pbxproj`** → alle dauerhaften Einstellungen
  (Team, Entitlements, Info-Keys, Capabilities) gehören in `project.yml`.
- **Watch-Installation: `devicectl`, nicht Xcode-„Run".** Xcode-Run auf die Uhr hängt
  am „Copying shared cache symbols" (Apple liefert watchOS-26.5-Symbole mit HTTP 403,
  Device-Copy dauert ~40 min). `devicectl install` umgeht das komplett.
- **Watch-Funk schläft ein** → `devicectl`-Tunnel-Timeouts; Uhr wach/entsperrt/nah
  halten, mehrfach versuchen (Retry-Schleife im Build-Abschnitt oben).
- Build-Reihenfolge nach Codeänderung: ggf. `xcodegen generate` → `xcodebuild` (beide
  Targets) → `devicectl install` (beide). iPhone-Build erzeugt die eingebettete
  Watch-App mit; die standalone Watch-App liegt in `build/Debug-watchos/`.

## Computer-Use-Hinweise (falls die GUI bedient werden muss)

- **Xcode ist Tier „click"**: nur Linksklick, **kein Tippen/Tastenkürzel/Rechtsklick/
  Drag**. Für Shell → Bash-Tool. Texteingaben (Apple-ID, Felder) muss der Nutzer machen.
- Die App **„Alcove"** (Notch-Tool) überlagert die obere Leiste → Klicks dort werden
  geblockt („would land on Alcove"). Toolbar-/Tab-Klicks ggf. vom Nutzer ausführen
  lassen oder über das **Product-Menü** gehen.
- Vor Computer-Use `request_access` für „Xcode" aufrufen.
- Signing-Schritte (Apple-ID, Team) macht der Nutzer; das Installieren läuft per
  Bash/`devicectl`.

## Testen ohne Geräte

```bash
cd /Users/florianschneider/ML4SCS
.venv_vr/bin/python tools/swingstream_dashboard.py            # http://127.0.0.1:8788
# echte Aufnahme abspielen (Predict-Engine triggern):
.venv_vr/bin/python tools/swingstream_sim.py --replay recordings/<datei>.csv --speed 5
# synthetischer Stream:
.venv_vr/bin/python tools/swingstream_sim.py --duration 30 --rate 100
```
CSV-Lücken prüfen: `dt` aus `motionTimestamp_sinceReboot(s)` (10 ms ⇒ 100 Hz).
Nach aktueller Spaltenangleichung gibt es keine `sequence`-Spalte mehr in der CSV;
`sequence` bleibt nur im Live-JSON. Gaps > ca. 0,03 s sind echte Watch-Sampling-
Lücken und müssen untersucht werden. Live-Erkennung gegen `src/predict.py --scan
<csv>` gegenprüfen (muss identisch sein).

## Git

- Branch **`SwingStream-implementierung`** (von `main` abgezweigt; `main` unberührt,
  nichts gepusht). Enthält neben SwingStream auch ältere, vorher offene Repo-Änderungen
  (mit committet auf Wunsch des Nutzers).
- Commit-Trailer: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Nur committen/pushen, wenn der Nutzer es verlangt.

## Wichtigste Designprinzipien (nicht brechen)

1. **CSV bleibt im kanonischen ML4SCS-Format** (sonst funktioniert das Modell nicht).
   Keine zusätzlichen Spalten für SwingStream-Metadaten einfügen; Sync gehört in
   die JSON-Datei.
2. **Uhr-Datei = Quelle der Wahrheit**; Stream ist nur Vorschau/Predict.
3. **Hintergrundbetrieb hängt an der `HKWorkoutSession`** (mit LiveWorkoutBuilder +
   `beginCollection`) **und** `WKBackgroundModes = workout-processing`. Ohne diese
   Kombination stoppt/suspendiert CoreMotion bei Display-aus.
4. Keine unnötigen Python-Abhängigkeiten im Dashboard (stdlib + optional das Modell).
5. CoreMotion-Callback niemals mit Datei-I/O oder WatchConnectivity blockieren;
   Batches auf eine separate serielle Queue geben.
