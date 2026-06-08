# SwingStream Implementierungsplan

> **Überarbeitet** für die Integration in das bestehende ML4SCS-Repo. Wesentliche
> Korrekturen gegenüber der ersten Fassung:
>
> 1. **CSV-Format = kanonisches Apple-Watch-Format** (`motionUserAccelerationX(G)`,
>    `motionRotationRateX(rad/s)`, `motionTimestamp_sinceReboot(s)` …), damit die
>    aufgezeichneten Streams **direkt** vom bestehenden Code (`src/stroke_model.py`,
>    `src/predict.py`, Offline-Labeler, Modell `models/v_r_v1.pkl`) gelesen werden
>    können. Kein paralleles `acc_x_g`/`gyro_x_rad_s`-Format mehr.
> 2. **Keine neuen Python-Abhängigkeiten.** Das vorhandene Dashboard
>    (`tools/prediction_dashboard.py`) nutzt ausschließlich die Standardbibliothek
>    (`http.server`). SwingStream übernimmt dieses Muster: **HTTP-POST-Ingest +
>    Browser-Polling** statt `websockets`/`aiohttp`. Für 50 Hz über LAN ist das mehr
>    als ausreichend und auf der Swift-Seite (`URLSession`) deutlich einfacher.
> 3. **Simulator-first.** Die Mac-Seite wird zuerst gebaut und mit einem
>    Stream-Simulator (`tools/swingstream_sim.py`) end-to-end getestet – ohne dass
>    Xcode, iPhone oder Watch nötig sind.
> 4. **Ausführung über `.venv_vr`**, dasselbe venv, in dem Modell/Prediction laufen,
>    damit die optionale Live-Schlagerkennung das bestehende Modell wiederverwenden
>    kann.

## Ziel

SwingStream streamt Apple-Watch-Sensordaten live mit mindestens `50 Hz` auf ein
Mac-Dashboard. Das iPhone dient als Bridge zwischen Apple Watch und Mac.

```text
Apple Watch  ->  iPhone Bridge  ->  Mac Dashboard
 (CoreMotion)     (WatchConnectivity)   (HTTP, Browser-UI)
```

Das Tool visualisiert live, zeigt Verbindungs-/Qualitätsstatus und speichert die
eingehenden Sensordaten als CSV im **ML4SCS-kompatiblen Format**, sodass jede
Aufnahme sofort durch Offline-Labeler und Schlagmodell laufen kann.

## Integration in ML4SCS (Leitprinzip)

SwingStream ist kein isoliertes Projekt, sondern der **Live-/Online-Pfad** zur
bestehenden Offline-Pipeline:

| Bestehend (offline)                         | SwingStream (online)                           |
| ------------------------------------------- | ---------------------------------------------- |
| CSV-Upload in `tools/prediction_dashboard.py` | Live-Stream in `tools/swingstream_dashboard.py` |
| `uploads/…_Apple_Watch.csv`                 | `recordings/swingstream_…csv` (gleiche Spalten) |
| `src/stroke_model.load_sensor_table()`      | identisch wiederverwendbar                     |
| `detect_energy_peaks()` + `predict_one()` | identisch für Live-Klassifikation              |
| Modell `models/v_r_v1.pkl`                  | dasselbe Modell, optional live                 |

**Konsequenz:** Die aufgezeichneten CSVs müssen exakt die Spalten enthalten, die
`load_sensor_table()` erwartet. Minimal benötigt das Modell:

```text
motionTimestamp_sinceReboot(s)
motionUserAccelerationX(G), motionUserAccelerationY(G), motionUserAccelerationZ(G)
motionRotationRateX(rad/s), motionRotationRateY(rad/s), motionRotationRateZ(rad/s)
```

Wir schreiben darüber hinaus die volle Attitude/Gravity/Quaternion, um zur
vorhandenen Spaltenstruktur (`Daten/`, `uploads/`) kompatibel zu bleiben.

## Zielarchitektur

1. **SwingStream Watch App** (watchOS)
   - liest Motion-/IMU-Daten über `CoreMotion`
   - sammelt Samples in einem Ringbuffer, vergibt fortlaufende `sequence`
   - sendet in kleinen Batches an das iPhone über `WatchConnectivity`

2. **SwingStream iPhone Bridge** (iOS)
   - empfängt Watch-Batches über `WCSession`
   - puffert kurz, ergänzt Bridge-Metadaten
   - sendet Batches per **HTTP POST** an das Mac-Dashboard
   - Reconnect/Retry mit lokaler Queue

3. **SwingStream Mac Dashboard** (`tools/swingstream_dashboard.py`)
   - stdlib-HTTP-Server, nimmt Batches entgegen
   - Live-Status, Sample-Rate, Gap-/Drop-Erkennung
   - Live-Plot im Browser (Canvas, Polling)
   - Recording in ML4SCS-kompatibles CSV
   - optional: Live-Schlagerkennung über `v_r_v1.pkl`

## Technische Entscheidungen

### Watch → iPhone: WatchConnectivity

`WCSession.default.sendMessageData(...)` für Live-Batches (kein FileTransfer, kein
Bluetooth-Sonderweg). Batches statt Einzelmessages, damit `WCSession` nicht
überlastet wird.

```text
Sampling:       50 Hz (CoreMotion deviceMotionUpdateInterval = 1/50)
Batch-Größe:    5 bis 10 Samples
Sendefrequenz:  ca. 5–10 Hz (alle 0.1–0.2 s ein Batch)
```

Damit bleibt die effektive Messrate ≥ `50 Hz`.

### iPhone → Mac: HTTP POST (statt WebSocket)

**MVP-Transport ist HTTP POST** auf einen stdlib-Server:

```text
POST http://<mac-ip>:8788/api/ingest
Content-Type: application/json
Body: { "type": "sensor_batch", ... }   (siehe Datenprotokoll)
```

Begründung gegenüber WebSocket:

- **Keine neuen Abhängigkeiten** – passt zum bestehenden `http.server`-Dashboard.
- Auf der Swift-Seite nur `URLSession` nötig (kein WS-Framework).
- Bei 5–10 Batches/s über LAN ist die Latenz unkritisch.
- Verbindungsverlust ist trivial behandelbar (Request schlägt fehl → Queue/Retry).

WebSocket bleibt eine **optionale spätere Optimierung**, falls bidirektionale
Steuerkommandos (Mac → iPhone Start/Stop) oder geringere Latenz nötig werden.

Das Browser-Dashboard holt sich neue Daten per **Polling** (`GET /api/live`, ca.
alle 100–200 ms). Das ist robust und kommt ohne Server-Push aus. (Server-Sent
Events wären stdlib-fähig, sind aber für den MVP nicht nötig.)

## CSV-Datenformat (ML4SCS-kompatibel)

Aufgezeichnete Dateien verwenden die **kanonischen Apple-Watch-Spaltennamen**.
Mindestens (und in dieser Reihenfolge):

```csv
loggingTime(txt),motionTimestamp_sinceReboot(s),accelerometerTimestamp_sinceReboot(s),accelerometerAccelerationX(G),accelerometerAccelerationY(G),accelerometerAccelerationZ(G),motionUserAccelerationX(G),motionUserAccelerationY(G),motionUserAccelerationZ(G),motionRotationRateX(rad/s),motionRotationRateY(rad/s),motionRotationRateZ(rad/s),motionGravityX(G),motionGravityY(G),motionGravityZ(G),motionRoll(rad),motionPitch(rad),motionYaw(rad),motionQuaternionX(R),motionQuaternionY(R),motionQuaternionZ(R),motionQuaternionW(R),sequence,label
```

Anforderungen:

- `motionTimestamp_sinceReboot(s)` ist die **Zeitbasis** (so wie es
  `load_sensor_table()` bevorzugt). Sie wird aus `watch_uptime_s` der Watch
  befüllt – monoton und driftarm.
- `loggingTime(txt)` als ISO-Zeitstempel (aus `timestamp_unix_s` abgeleitet), nur
  als absolute Referenz.
- `sequence` ist fortlaufend und startet pro Session bei `0` (zur Gap-Erkennung).
- `label` wird mit `0` vorbelegt (kompatibel zu vorhandenen CSVs; Labeling
  passiert weiterhin offline im Labeler).
- Fehlende Werte werden als `0.0` geschrieben.
- Gespeicherte Dateien liegen unter `recordings/swingstream_YYYYMMDD_HHMMSS.csv`.

### Mapping Stream-JSON → CSV-Spalte

| JSON-Feld (Sample)   | CSV-Spalte                          |
| -------------------- | ----------------------------------- |
| `watch_uptime_s`     | `motionTimestamp_sinceReboot(s)`, `accelerometerTimestamp_sinceReboot(s)` |
| `timestamp_unix_s`   | `loggingTime(txt)` (ISO, vom Mac abgeleitet) |
| `user_acc_{x,y,z}_g` | `motionUserAcceleration{X,Y,Z}(G)`  |
| `gyro_{x,y,z}_rad_s` | `motionRotationRate{X,Y,Z}(rad/s)`  |
| `acc_{x,y,z}_g`      | `accelerometerAcceleration{X,Y,Z}(G)` |
| `gravity_{x,y,z}_g`  | `motionGravity{X,Y,Z}(G)`           |
| `roll/pitch/yaw_rad` | `motionRoll/Pitch/Yaw(rad)`         |
| `quat_{x,y,z,w}`     | `motionQuaternion{X,Y,Z,W}(R)`      |
| `sequence`           | `sequence`                          |

> Die kurzen JSON-Keys halten die Watch→iPhone→Mac-Nachrichten kompakt; das
> Mapping auf die kanonischen Spalten passiert **einmalig beim CSV-Schreiben auf
> dem Mac**. So bleibt das Netzwerkformat schlank und die Datei modellkompatibel.

## Datenprotokoll

### Watch → iPhone Batch

```json
{
  "type": "sensor_batch",
  "session_id": "20260607_132500",
  "samples": [
    {
      "sequence": 120,
      "timestamp_unix_s": 1780838700.123,
      "watch_uptime_s": 42.120,
      "user_acc_x_g": 0.02, "user_acc_y_g": 0.01, "user_acc_z_g": -0.04,
      "gyro_x_rad_s": 0.12, "gyro_y_rad_s": -0.08, "gyro_z_rad_s": 0.03,
      "acc_x_g": 0.01, "acc_y_g": -0.03, "acc_z_g": 0.05,
      "gravity_x_g": 0.0, "gravity_y_g": -1.0, "gravity_z_g": 0.0,
      "roll_rad": 0.1, "pitch_rad": -0.2, "yaw_rad": 1.3,
      "quat_x": 0.0, "quat_y": 0.0, "quat_z": 0.0, "quat_w": 1.0
    }
  ]
}
```

### iPhone → Mac (`POST /api/ingest`)

Gleiches Batch-Format, ergänzt um Bridge-Metadaten:

```json
{
  "type": "sensor_batch",
  "source": "iphone_bridge",
  "session_id": "20260607_132500",
  "bridge_received_unix_s": 1780838700.155,
  "samples": []
}
```

Antwort des Mac: `{"ok": true, "received": <n>, "recording": <bool>}`.

### Steuerkommandos (später, optional)

Nur relevant, wenn von HTTP-POST auf WebSocket umgestellt wird:
`{ "type": "start_stream" }`, `{ "type": "stop_stream" }`, `{ "type": "ping" }`.
Im MVP wird Start/Stop direkt auf Watch und iPhone bedient.

## Mac-Dashboard Design

### Server (`tools/swingstream_dashboard.py`)

Aufbau analog zu `tools/prediction_dashboard.py` (gleicher Stil, gleiche
stdlib-Bausteine `BaseHTTPRequestHandler`/`HTTPServer`):

- **ein** HTTP-Server, Default `0.0.0.0:8788` (im LAN erreichbar fürs iPhone)
- Endpunkte:
  - `GET  /` – Dashboard-HTML (Canvas-Plot, Status, Recording-Buttons)
  - `POST /api/ingest` – nimmt Batches entgegen, schreibt in Ringbuffer/CSV
  - `GET  /api/live` – aktuelle Stats + jüngste Samples (für Polling)
  - `POST /api/record/start` – startet CSV-Recording (neue Datei in `recordings/`)
  - `POST /api/record/stop` – schließt CSV sauber
- thread-sicherer Ringbuffer (`ThreadingHTTPServer`, da POST + Polling parallel)
- Gap-Erkennung über `sequence`, effektive Rate über `watch_uptime_s`,
  Latenzschätzung über `bridge_received_unix_s` vs. Mac-Empfangszeit

### Dashboard-UI

- Verbindungsstatus (letzter Batch vor … s)
- aktuelle Sample-Rate (Hz), empfangene Samples gesamt
- Gap-/Drop-Count (fehlende `sequence`)
- Latenzschätzung
- Live-Plot: User-Acceleration-Magnitude und Rotation-Magnitude (Score wie im
  bestehenden Dashboard: `acc + 0.12 * gyro`)
- Recording-Bereich: Start/Stop, Pfad zur aktuellen CSV, Zeilenzahl

### Optional: Live-Schlagerkennung

Wiederverwendung des bestehenden Codes ohne Neuentwicklung:

- rollierender Puffer der letzten ~3 s als `SensorTable`
  (`src/stroke_model.py` Datenstrukturen)
- `detect_energy_peaks()` auf dem Puffer → Peak-Zeiten
- pro neuem Peak `predict_one(load_model(), table, t)` → `Vorhand`/`Rueckhand`
- Ergebnis als Marker im Live-Plot (Farben wie im Prediction-Dashboard)

Dies konkretisiert die frühere offene Frage „Schlagmodell live anwenden?" – es ist
mit der vorhandenen API direkt möglich, sobald `.venv_vr` genutzt wird.

## Performance-Anforderungen

### Muss
- ≥ `50 Samples/s` vom Watch-Sampler
- sichtbare Live-Updates im Dashboard
- CSV-Aufzeichnung ohne Lücken bei stabiler Verbindung
- Reconnect/Retry nach Verbindungsverlust (iPhone-Queue)

### Soll
- Sample-Gap-Erkennung über `sequence`
- Anzeige effektiver Empfangsrate und Latenz
- Batch-Größe konfigurierbar

### Akzeptanzkriterien
1. Watch streamt bei `50 Hz` für ≥ `60 s`.
2. Mac-Dashboard zeigt durchgehend eingehende Daten und plausible Rate (~50 Hz).
3. Gespeicherte CSV enthält ≥ `3000` Samples nach `60 s`.
4. `sequence` ohne große Lücken (Gap-Count klein).
5. **Die CSV lässt sich ohne Fehler durch `src/stroke_model.load_sensor_table()`
   laden** und durch `src/predict.py --scan` verarbeiten.
6. Live-Plot reagiert sichtbar auf Handbewegungen.
7. Nach Stop wird die CSV sauber geschlossen.

## Implementierungsschritte

> Reihenfolge bewusst **Mac-zuerst**: Die Mac-Seite ist ohne Hardware baubar und
> testbar (Simulator). Erst danach Swift/Xcode.

### Phase 0: Mac-Dashboard + Simulator (zuerst, ohne Hardware)
1. `tools/swingstream_dashboard.py` bauen (Server, Endpunkte, Ringbuffer).
2. CSV-Writer mit kanonischen Spalten implementieren.
3. `tools/swingstream_sim.py` bauen: erzeugt 50-Hz-Batches mit synthetischer
   Bewegung und POSTet sie an `/api/ingest`.
4. End-to-End testen: Simulator → Dashboard → Recording.
5. Aufgezeichnete CSV mit `load_sensor_table()` + `predict.py --scan` prüfen.
6. `tools/start_swingstream.command` Launcher anlegen (analog `start_labeler.command`).

### Phase 1: Xcode-Projekt
1. Xcode-Projekt `SwingStream` (iOS App + Watch App Target).
2. Bundle IDs: `com.florianschneider.SwingStream`,
   `com.florianschneider.SwingStream.watchkitapp`.
3. Signing Team setzen, Testlauf auf iPhone und Watch.

### Phase 2: Gemeinsames Sample-Modell
1. `SensorSample.swift` (Codable) in iOS- und Watch-Target.
2. `SensorBatch` definieren, JSON-Encoding/Decoding testen
   (gegen das oben definierte Protokoll).

### Phase 3: Watch-Sampler
1. `WatchMotionSampler` mit `CMMotionManager`, `50 Hz`.
2. fortlaufende `sequence`, Ringbuffer, Batch-Buffer.
3. Watch-UI mit Start/Stop und Status (`samples/s`).

### Phase 4: WatchConnectivity
1. `WatchConnectivitySender` (Watch) + `PhoneWatchBridge` (iPhone).
2. Batches Watch → iPhone, empfangene Rate auf iPhone anzeigen.
3. Fehlerfälle loggen (iPhone unreachable, Session inaktiv, Send-Fehler).

### Phase 5: iPhone → Mac (HTTP)
1. `MacHTTPClient` (`URLSession`), Mac-IP + Port konfigurierbar (Default `8788`).
2. Watch-Batches an `/api/ingest` POSTen, Bridge-Metadaten ergänzen.
3. Lokale Queue + Retry/Backoff bei Verbindungsfehlern.
4. Bridge-Status anzeigen (Mac reachable, samples/s, dropped).

### Phase 6: Live-Dashboard-Ausbau
1. Canvas-Plot, Rate/Status/Gap/Latenz.
2. Recording Start/Stop, CSV-Pfad/Zeilenzahl.

### Phase 7: Optional Live-Schlagerkennung
1. rollierenden `SensorTable`-Puffer aufbauen.
2. `detect_energy_peaks()` + `predict_one()` einbinden.
3. Schlag-Marker im Live-Plot.

### Phase 8: Integrationstest
1. Dashboard auf Mac starten, iPhone mit Mac-IP verbinden.
2. Watch-Stream 60 s laufen lassen.
3. CSV prüfen: Zeilenzahl, Frequenz, `sequence`-Lücken, Spaltenformat,
   Ladbarkeit via `load_sensor_table()`.
4. Live-Plot mit echten Bewegungen validieren.

## Risiken und Gegenmaßnahmen

| Risiko | Gegenmaßnahme |
| ------ | ------------- |
| WatchConnectivity nicht für High-Throughput | Batches (5–10 Samples), JSON ggf. später durch kompaktes Binärformat ersetzen |
| Watch geht in Energiespar-/Hintergrundmodus | zunächst nur aktive Foreground-Session; später `HKWorkoutSession` für längeres Streaming prüfen |
| WLAN iPhone → Mac instabil | HTTP-Retry + lokale iPhone-Queue, Gap-Erkennung im Dashboard |
| Zeitstempel nicht exakt synchron | primär `sequence` + `watch_uptime_s` (→ `motionTimestamp_sinceReboot`), `timestamp_unix_s` nur als Referenz, Latenz separat |
| CSV nicht modellkompatibel | **kanonische Spaltennamen** + Akzeptanzkriterium 5 (Ladbarkeit) |

## Minimal Viable Product

1. **Mac:** `swingstream_dashboard.py` empfängt Batches per HTTP, plottet live,
   schreibt ML4SCS-kompatibles CSV. Verifiziert mit `swingstream_sim.py`.
2. **Watch:** sammelt `userAcceleration` + `rotationRate` bei `50 Hz`, sendet
   Batches an iPhone.
3. **iPhone:** leitet Batches per HTTP-POST an den Mac weiter.

Alles andere (Binärprotokoll, WebSocket, Bonjour, Hintergrund-Streaming, Live-
Modell) ist sekundär.

## Empfohlene Ordnerstruktur

```text
ML4SCS/
  tools/
    swingstream_dashboard.py     # Mac-Empfänger + Browser-Dashboard (stdlib)
    swingstream_sim.py           # Stream-Simulator zum Testen ohne Hardware
    start_swingstream.command    # Launcher (venv wählen + Safari öffnen)
  recordings/
    swingstream_YYYYMMDD_HHMMSS.csv

SwingStream/                     # Xcode-Projekt im Repo (mit xcodegen aus project.yml)
  project.yml                    # XcodeGen-Spec
  SwingStream.xcodeproj
  Shared/
    SensorModels.swift           # gemeinsames Sample-/Batch-Modell (beide Targets)
  SwingStream/                   # iPhone-Bridge
    SwingStreamApp.swift
    iPhoneBridgeView.swift
    PhoneWatchBridge.swift
    MacHTTPClient.swift
    SensorSample.swift
    StreamStats.swift
  SwingStream Watch App/
    SwingStreamWatchApp.swift
    WatchStreamView.swift
    WatchMotionSampler.swift
    WatchConnectivitySender.swift
    SensorSample.swift
```

## Ausführung

```bash
# Mac-Dashboard starten (im Repo-Root)
.venv_vr/bin/python tools/swingstream_dashboard.py        # http://127.0.0.1:8788

# In zweitem Terminal: Stream simulieren (60 s bei 50 Hz)
.venv_vr/bin/python tools/swingstream_sim.py --duration 60 --rate 50
```

`.venv_vr` wird genutzt, damit die optionale Live-Schlagerkennung dasselbe
`numpy/scikit-learn/joblib` wie die Offline-Pipeline verwenden kann. Das reine
Empfangen/Recorden funktioniert auch mit System-Python (nur stdlib).

Die Watch-/iPhone-Apps liegen unter `SwingStream/` und werden mit XcodeGen erzeugt:

```bash
cd SwingStream && xcodegen generate && open SwingStream.xcodeproj
# In Xcode: Signing-Team setzen, iPhone als Ziel wählen, Run (Watch-App wird mitinstalliert)
```

## Offene Entscheidungen

- Mac-Dashboard mittelfristig in `prediction_dashboard.py` integrieren (ein
  Tool für Upload **und** Live)?
- iPhone automatisch Mac-IP per Bonjour entdecken?
- Watch langfristig im Hintergrund streamen (Workout-Session)?
- Live-Modell standardmäßig an oder nur auf Knopfdruck?

## Empfehlung

Zuerst Phase 0 (Mac-Dashboard + Simulator) fertigstellen und gegen die
Akzeptanzkriterien testen – insbesondere die CSV-Kompatibilität. Danach die
Swift-Apps bauen und gegen den bereits getesteten Mac-Empfänger streamen. Sobald
`50 Hz` stabil laufen, Live-Schlagerkennung über das vorhandene Modell ergänzen.
