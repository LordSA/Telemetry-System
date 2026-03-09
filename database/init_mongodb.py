import pymongo
from pymongo import MongoClient
import os
import sys
from pathlib import Path

# Add parent dir to path for var.py
sys.path.append(str(Path(__file__).resolve().parent.parent))
import var

def migrate_to_mongodb():
    print("=" * 50)
    print("  MONGODB INITIALIZATION & MIGRATION SCRIPT")
    print("=" * 50)
    
    try:
        client = MongoClient(var.MONGO_URI, serverSelectionTimeoutMS=5000)
        client.server_info()
        db = client[var.DB_NAME]
        
        print(f"Connected to MongoDB at {var.MONGO_URI}")
        
        # 1. Setup Collections and Indexes
        print("Setting up collections and indexes...")
        
        # Players
        db.players.create_index("username", unique=True)
        db.players.create_index("player_id", unique=True)
        
        # Savefiles
        db.savefiles.create_index([("player_id", 1), ("slot_number", 1)], unique=True)
        
        # Sessions
        db.sessions.create_index("session_id", unique=True)
        db.sessions.create_index("player_id")
        
        # Events
        db.events.create_index("session_id")
        db.events.create_index("event_type")
        db.events.create_index("area_code")
        db.events.create_index("event_time")
        
        # Deaths
        db.deaths.create_index("session_id")
        db.deaths.create_index("area_code")
        
        # Mapzones
        db.mapzones.create_index("area_code", unique=True)
        
        print(f"Database '{var.DB_NAME}' initialization complete.")
        return True
        
    except Exception as e:
        print(f"Error during migration initialization: {e}")
        return False

if __name__ == "__main__":
    migrate_to_mongodb()
