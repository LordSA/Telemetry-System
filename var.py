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
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
DB_NAME = os.getenv('DB_NAME', 'telemetry_db')

# Legacy SQL settings (can be removed later)
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')

DB_CONFIG = {
    'host': DB_HOST,
    'database': DB_NAME,
    'user': DB_USER,
    'password': DB_PASSWORD
}

# Config without database for initial setup
DB_CONFIG_NO_DB = {
    'host': DB_HOST,
    'user': DB_USER,
    'password': DB_PASSWORD
}

# ============================================================================
# SERVER SETTINGS
# ============================================================================
SERVER_PORT = int(os.getenv('SERVER_PORT', 8090))

# ============================================================================
# VISUALIZER SETTINGS
# ============================================================================
VISUALIZER_OUTPUT_DIR = os.getenv('VISUALIZER_OUTPUT_DIR', 'output')
VISUALIZER_DEFAULT_EVENT = os.getenv('VISUALIZER_DEFAULT_EVENT', 'PLAYER_DEATH')
