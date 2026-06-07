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
- **Kerncode** in `src/`:
  - `stroke_model.py`: `load_sensor_table(csv)→SensorTable`,
    `offline_labeler_peaks(table)`, `predict_one(model, table, t)`,
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
- `.gitignore` ignoriert u. a. `uploads/`, venvs, `*.mp4/*.mov`, `docs/csv_graph_modes.md`,
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
  via `sendMessage` (wenn erreichbar) **und** `updateApplicationContext` (Fallback).
  ⚠️ Die **Watch-App muss geöffnet sein**, damit sie den Start empfängt und die
  Workout-Session starten kann (vom iPhone aus lässt sich die Watch-App nicht starten).
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
Verlustfreiheit einer CSV prüfen: Zeilen vs. `sequence`-Bereich, `dt` aus
`motionTimestamp_sinceReboot(s)` (10 ms ⇒ 100 Hz). Live-Erkennung gegen
`src/predict.py --scan <csv>` gegenprüfen (muss identisch sein).

## Git

- Branch **`SwingStream-implementierung`** (von `main` abgezweigt; `main` unberührt,
  nichts gepusht). Enthält neben SwingStream auch ältere, vorher offene Repo-Änderungen
  (mit committet auf Wunsch des Nutzers).
- Commit-Trailer: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Nur committen/pushen, wenn der Nutzer es verlangt.

## Wichtigste Designprinzipien (nicht brechen)

1. **CSV bleibt im kanonischen ML4SCS-Format** (sonst funktioniert das Modell nicht).
2. **Uhr-Datei = verlustfreie Quelle der Wahrheit**; Stream ist nur Vorschau/Predict.
3. **Hintergrundbetrieb hängt an der `HKWorkoutSession`** (mit LiveWorkoutBuilder +
   `beginCollection`). Ohne sie stoppt CoreMotion bei Display-aus.
4. Keine unnötigen Python-Abhängigkeiten im Dashboard (stdlib + optional das Modell).
