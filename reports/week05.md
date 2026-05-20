# Week 05 Report — Machine Learning for Smart and Connected Systems (ML4SCS)

## Weekly Goal
Weekly Goal for next Week is to further develop the dashboard integration for live sensor streaming and labelling the already recorded data


## Work Done This Week

### 0. Project setup
- The project question was refined to focus on recognizing and classifying tennis movements using smartwatch sensor data.


### 1. Data Work
-  We continued working on labeling the previously recorded sensor datasets, but have not yet found a fully functional solution for our synchronization and labeling workflow.

### 2. Analysis / Modeling Work
- Initial work was done on integrating a dashboard to capture and visualize live sensor data streams. Dashboard is still currently work in progress

### 3. Repository / Documentation Work
- Github repository was updated: 
    - Added Section
    - Added main research question


## Challenges

### Labeling and Video Synchronization
- One of the main challenges remains the labelling process.
- Currently, we haven't found a suitable tool that fully supports synchronized video playback together with `.csv` files for our use case.
- The videos recorded so far are partly very large, which means common annotation tools fail to reliably load or process them, making it difficult to align video footage with sensor data and apply consistent labels.
- The dashboard integration and synchronization are still unfinished and require further development.

### WatchStreamer App Installation on the Apple Watch
The WatchStreamer app could not be installed on the real Apple Watch this week. Initially, the Watch app on the iPhone showed a trust warning ("App is not from a trusted developer"), even though the developer profile was already marked as trusted under `Settings > General > VPN & Device Management`. After resolving that, a new error appeared: `This app could not be installed at this time.`

Several root causes were found and fixed during debugging:

- **Xcode on external drive:** Xcode was located at `/Volumes/KINGSTON/Xcode/Xcode.app`, which caused problems for real-device deployment. Xcode was moved locally to `/Applications/Xcode.app`.
- **Insufficient internal storage:** The internal drive had only ~8.6 GiB free. Ollama models and other large files were moved to the Kingston drive, freeing ~28–32 GiB.
- **DerivedData path pointed to Kingston:** Xcode was still using `/Volumes/KINGSTON/Xcode/Dependencies/DerivedData`, causing `database is locked` build errors. The path was reset to the default `/Users/florianschneider/Library/Developer/Xcode/DerivedData`.
- **iOS and watchOS components missing:** After removing simulator runtimes, Xcode reported `iOS 26.5 is not installed` and `watchOS 26.5 is not installed`. Both components were reinstalled.

**Current status:** The build of the iPhone app including the embedded Watch app works again. However, the Apple Watch still does not appear as a development device in Xcode (`Window > Devices and Simulators`), so the app cannot yet be deployed directly to the real watch. The issue is likely a missing Developer Mode pairing between Mac, iPhone, and Apple Watch.

## Key Insights
- What did you learn this week?

## Plan for Next Week
- Continue on dashboard integration with live data visualization
- Continue labeling the collected dataset

## Contributions
- Member 1:
- Member 2:
- Member 3:
