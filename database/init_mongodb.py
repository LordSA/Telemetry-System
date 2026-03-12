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
        client = MongoClient(var.MONGO_URI, serverSelectionTimeoutMS=30000, socketTimeoutMS=30000)
        client.server_info()
        db = client[var.DB_NAME]
        
        print(f"Connected to MongoDB at {var.MONGO_URI}")
        
        # 1. Setup Collections and Indexes
        print("Setting up collections and indexes...")
        
        def safe_create_index(collection, keys, **kwargs):
            """Create an index, ignoring errors if it already exists."""
            try:
                db[collection].create_index(keys, **kwargs)
                print(f"  [OK] {collection}: index on {keys}")
            except Exception as e:
                print(f"  [SKIP] {collection}: index on {keys} — {e}")
        
        # Players
        safe_create_index("players", "username", unique=True)
        safe_create_index("players", "player_id", unique=True)
        
        # Savefiles
        safe_create_index("savefiles", [("player_id", 1), ("slot_number", 1)], unique=True)
        
        # Sessions
        safe_create_index("sessions", "session_id", unique=True)
        safe_create_index("sessions", "player_id")
        
        # Events
        safe_create_index("events", "session_id")
        safe_create_index("events", "event_type")
        safe_create_index("events", "area_code")
        safe_create_index("events", "event_time")
        
        # Deaths
        safe_create_index("deaths", "session_id")
        safe_create_index("deaths", "area_code")
        
        # Mapzones
        safe_create_index("mapzones", "area_code", unique=True)
        
        print(f"Database '{var.DB_NAME}' initialization complete.")
        return True
        
    except Exception as e:
        print(f"Error during migration initialization: {e}")
        return False

if __name__ == "__main__":
    migrate_to_mongodb()
