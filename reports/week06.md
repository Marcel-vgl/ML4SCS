# Week 06 Report — Machine Learning for Smart and Connected Systems (ML4SCS)

## Weekly Goal
Weekly goal for this week was to improve the workflow for labeling already recorded Apple Watch sensor data and to continue the dashboard integration for live data collection.


## Work Done This Week

### 0. Project setup
- The project question was refined to focus on recognizing and classifying tennis movements using smartwatch sensor data.


### 1. Data Work
- We analyzed the recorded test session `H_2_050526.csv` together with the corresponding video `Hannes_2_050526.mp4`.
- The video contains three clap events at the beginning, which were used as synchronization markers between the video and the Apple Watch sensor stream.
- The claps were detected in the video audio at approximately `0.395s`, `0.970s`, and `1.500s`.
- The corresponding IMU peaks in the sensor CSV were detected at approximately `14.472s`, `15.047s`, and `15.580s`.
- This gives a stable synchronization offset of:

```text
CSV time = video time + 14.078 seconds
```

- We started labeling tennis strokes as event annotations. The current event label file is:

```text
labels/H_2_050526_events.csv
```

- Current labeled events in this file: 21 total events
  - 16 Vorhand
  - 5 Rueckhand

### 2. Analysis / Modeling Work
- Initial work was done on integrating a dashboard to capture and visualize live sensor data streams. The dashboard is still currently work in progress.
- In addition, we implemented a separate offline labeling workflow for the already recorded video and CSV files.
- The offline tool shows video playback, IMU signal plots, and automatically detected peak candidates in one interface.
- Labels are stored as timestamped event annotations instead of directly overwriting the raw sensor CSV. This preserves the raw data and allows flexible window generation later during preprocessing.

### 3. Repository / Documentation Work
- Github repository was updated: 
    - Added Section
    - Added main research question
- Added an offline labeling tool:

```text
tools/offline_label_tool.py
```

- Added README documentation for the offline labeling workflow and keyboard shortcuts.
- Added the first event label file:

```text
labels/H_2_050526_events.csv
```


## Challenges

### Labeling and Video Synchronization
- One of the main challenges was the labelling process for already recorded data.
- Common annotation tools did not fit our use case well, because we need synchronized video playback together with Apple Watch `.csv` sensor data.
- The recorded videos are large, and direct manual editing of the sensor CSV would be error-prone.
- We addressed this by building a lightweight local offline labeling tool.
- The tool does not modify the original raw CSV. Instead, it saves event labels with `video_time_s`, `csv_time_s`, `label`, and `label_name`.
- A remaining challenge is converting these event annotations into training windows, for example using windows of `+/-0.5s` around each labeled stroke.

### WatchStreamer App Installation on the Apple Watch
We used the WatchStreamer app from the group "BurkMachtBock" to stream Apple Watch sensor data. The dashboard and the iPhone app are working. However, installing the Watch app on the real Apple Watch failed. Initially, the Watch app on the iPhone showed a trust warning ("App is not from a trusted developer"), even though the developer profile was already marked as trusted under `Settings > General > VPN & Device Management`. After resolving that, a new error appeared: `This app could not be installed at this time.`

One root cause was found and fixed during debugging:

- **DerivedData path misconfigured:** Xcode was using an incorrect DerivedData path, causing `database is locked` build errors. The path was reset to the default, after which the build succeeded.

**Current status:** The build including the embedded Watch app works. The dashboard and iPhone app function correctly. The Apple Watch however still does not appear as a development device in Xcode (`Window > Devices and Simulators`), so the Watch app cannot yet be deployed to the real device. The issue is likely a missing Developer Mode pairing between Mac, iPhone, and Apple Watch.

## Key Insights
- Clap markers are a reliable way to synchronize video and sensor recordings when both audio and IMU signals capture the same event.
- For this session, the video and sensor streams are aligned with an offset of approximately `14.078s`.
- Event-based labeling is safer than writing directly into the raw sensor CSV, because it preserves the original measurements and keeps preprocessing decisions reproducible.
- IMU peak detection is useful for quickly jumping to likely stroke moments, but final labels still need visual confirmation from the video.

## Plan for Next Week
- Continue labeling the collected dataset with the offline labeling tool.
- Implement preprocessing that converts event labels into fixed-size sensor windows.
- Generate a first feature table from the labeled windows.
- Continue dashboard integration with live data visualization.

## Contributions
- Member 1:
- Member 2:
- Member 3:
