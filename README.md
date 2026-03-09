# The Overseer: Telemetry System

The Overseer is a standalone, engine-agnostic telemetry suite designed to collect, archive, and visualize data from game clients silently and efficiently.

## 🚀 Key Features

*   **Engine-Agnostic**: Simple HTTP API for Java, Godot, Unity, and more.
*   **Persistent Tracking**: Automated tracking of career playtime and session durations.
*   **Cloud Persistence**: Handles game save uploads with stat synchronization.
*   **Playtime Leaderboards**: Integrated leaderboard endpoint for engagement tracking.
*   **Heatmap Visualization**: Generate detailed spatial activity maps (Heatmaps) from stored event data.

---

## 📂 Repository Structure

```text
/
├── .env                # Global configuration (Single Source of Truth)
├── var.py              # Shared configuration module for Python components
├── backend/            # Python telemetry server (Overseer)
├── clients/
│   └── java/           # Maven-compliant Java client implementation
├── database/           # MongoDB initialization and storage logic
├── visualizer/         # Spatial data analysis and heatmap generator
└── requirements.txt    # Common Python dependencies
```

---

## ⚙️ Configuration Variables

Centralize your settings in the root `.env` file. These variables are managed by `var.py` and used by both the backend and visualizer.

| Variable | Description | Default |
| :--- | :--- | :--- |
| `MONGO_URI` | Connection string for MongoDB (Local or Atlas) | `mongodb+srv://...` |
| `DB_NAME` | Name of the telemetry database | `telemetry_db` |
| `SERVER_PORT` | Port the Overseer listens on | `8090` |
| `VISUALIZER_OUTPUT_DIR` | Output directory for generated PNGs | `output` |
| `VISUALIZER_DEFAULT_EVENT`| Default event type for visualization | `PLAYER_DEATH` |

---

## 🛠️ Getting Started

### 1. Environment Setup (The "venv" Thing)
It is highly recommended to use a Python virtual environment to keep your global packages clean.

**Window Setup:**
```powershell
# Create the environment
python -m venv venv

# Activate the environment (DO THIS EVERY TIME YOU START WORKING)
.\venv\Scripts\activate

# Install all necessary libraries
pip install -r requirements.txt
```

### 2. Configuration
Copy the template and fill in your MongoDB connection string in `.env`:
```powershell
cp .env.example .env
```

### 3. Database Initialization
Ensure MongoDB is running (locally or on Atlas) and initialize collections/indexes:
```powershell
python database/init_mongodb.py
```

### 4. Running the Backend
Overseer will initialize tables and start listening for data:
```powershell
cd backend
python server.py
```

### 5. Running the Visualizer
Generate heatmaps of player deaths or stealth breakage:
```powershell
cd visualizer
python generator.py --event PLAYER_DEATH
```

### 6. Java Client Integration
Build the standard library for your project:
```bash
cd clients/java
mvn clean install
```
