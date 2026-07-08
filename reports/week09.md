# Week 09 Report — Machine Learning for Smart and Connected Systems (ML4SCS)

## Weekly Goal
The goal for this week was to expand the dataset, improve the modeling pipeline, and begin development of a custom app for data collection and live stroke evaluation.

## Work Done This Week

### 0. Project setup
- The project structure was updated to include new datasets and models.
- Work began on a custom app to replace SensorLog for data collection and live stroke evaluation. This is necessary because one of our Apple Watches and the borrowed Watch no longer support the watchOS version required for SensorLog.

### 1. Data Work
- Additional tennis sessions were recorded and added to the repository under `Daten/`. These recordings include both sensor data and corresponding video files.
- The new datasets still need to be labeled. The offline labeling tool will be used to annotate these sessions.

### 2. Analysis / Modeling Work
- Additional models were added to the repository to explore different approaches for stroke classification.
- The new models are being evaluated to determine their performance compared to the existing Random-Forest baseline.
- Work continues on integrating the models into the live prediction pipeline.

### 3. App Development
- Development of a custom app for the Apple Watch and iPhone has started. The app will:
  - Record training data directly from the Apple Watch.
  - Include the trained model for live stroke evaluation.
- The app is being designed to replace SensorLog and streamline the data collection process.
- The app will support both data recording and live prediction modes.

## Experiments Conducted

| Experiment | Change Made | Result | Interpretation |
|-----------|-------------|--------|----------------|
| New datasets | Recorded additional tennis sessions | Data added to `Daten/` | These recordings will expand the dataset and improve model training. |
| Additional models | Added new models to the repository | Evaluation in progress | The new models aim to improve classification performance. |

## Results
- New datasets were recorded and added to the repository.
- Additional models were implemented and are being evaluated.

## Challenges
- One of our Apple Watches and the borrowed Watch no longer support the watchOS version required for SensorLog. This necessitated the development of a custom app for data collection.
- The new datasets still need to be labeled, which is time-consuming.

## Key Insights
- Developing a custom app will provide more control over the data collection process and allow for live stroke evaluation directly on the Apple Watch.
- Expanding the dataset is critical for improving model performance, especially for underrepresented classes.

## Plan for Next Week
- Label the newly recorded datasets using the offline labeling tool.
- Continue development of the custom app, focusing on data recording functionality.
- Integrate the trained model into the app for live stroke evaluation.
- Evaluate the new models and compare their performance to the Random-Forest baseline.

## Contributions
- Florian Schneider:
- Marcel Vogeler:
- Metehan Tetik:
