# ML4SCS Tennis Stroke Classification

## Project Overview

This repository contains a semester project for **Machine Learning for Smart and Connected Systems**.

The project investigates whether smartwatch sensor data can be used to recognize and classify tennis movements. The focus is on motion and IMU data recorded with an Apple Watch during tennis practice.

The repository documents the full project workflow from data collection and labeling to preprocessing, feature engineering, model training, and evaluation.

## Research Question

Can movement and IMU data from a smartwatch be used to automatically detect and classify tennis strokes such as forehand, backhand, serve, and slice?

## Goal

The goal is to build a machine learning pipeline that can distinguish between different tennis movements based on Apple Watch sensor data.

At this stage, the main target classes are:

- Forehand
- Backhand
- Serve
- Slice
- No stroke / other movement

The classification setup may be extended later if the dataset supports more stroke types.

## Data

The data consists mainly of Apple Watch sensor recordings and matching video material from tennis sessions.

The smartwatch data includes motion-related signals such as acceleration, rotation rate, attitude, and other sensor values. Video recordings are used as reference material to assign labels to the sensor data.

The raw and collected data is stored in the `Daten/` directory.

## Repository Structure

```text
Daten/       Raw collected data and video material
docs/        Project documentation, grouped by topic
labels/      Event-based labels for recorded sessions
notebooks/   Exploratory notebooks
reports/     Weekly project reports
src/         Project source code for preprocessing, training, and evaluation
SwingStream/ Watch/iPhone Xcode project and SwingStream documentation
tools/       Helper tools used during the project
```

Important documentation:

- `docs/ml-pipeline/` - modeling, labeler, and CSV graph notes
- `SwingStream/docs/` - SwingStream implementation plan and current status
- `reports/` - weekly project reports

## Current Status

The project is currently in the data preparation phase. Initial sensor recordings and video material have been collected, and the first labels have been created.

The next steps are to collect more data, transform the labeled events into usable training samples, extract features from the sensor windows, and train baseline classification models.

## Team

- Florian Schneider
- Marcel Vogeler
- Metehan Tetik
