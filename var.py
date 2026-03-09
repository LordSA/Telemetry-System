import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory for the whole project
BASE_DIR = Path(__file__).resolve().parent

# Load the root .env
load_dotenv(BASE_DIR / ".env")

# ============================================================================
# DATABASE SETTINGS
# ============================================================================
# Connect to MongoDB Atlas or local MongoDB
# Replace with your actual connection string from MongoDB Atlas
MONGO_URI = os.getenv('MONGO_URI', 'mongodb+srv://<username>:<password>@cluster.mongodb.net/?retryWrites=true&w=majority')
DB_NAME = os.getenv('DB_NAME', 'telemetry_db')

# ============================================================================
# SERVER SETTINGS
# ============================================================================
SERVER_PORT = int(os.getenv('SERVER_PORT', 8090))

# ============================================================================
# VISUALIZER SETTINGS
# ============================================================================
VISUALIZER_OUTPUT_DIR = os.getenv('VISUALIZER_OUTPUT_DIR', 'output')
VISUALIZER_DEFAULT_EVENT = os.getenv('VISUALIZER_DEFAULT_EVENT', 'PLAYER_DEATH')
