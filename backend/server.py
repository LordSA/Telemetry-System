import http.server
import socketserver
import json
import mysql.connector
from mysql.connector import Error, pooling
import time
from datetime import datetime
import os
import sys
from urllib.parse import urlparse, parse_qs

# Import shared configuration from the project root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import var

PORT = var.SERVER_PORT

# Database Configuration from common var.py
DB_CONFIG = {
    'host': var.DB_HOST,
    'database': var.DB_NAME,
    'user': var.DB_USER,
    'password': var.DB_PASSWORD,
    'pool_name': 'telemetry_pool',
    'pool_size': 5
}

# Config without database for initial setup
DB_CONFIG_NO_DB = var.DB_CONFIG_NO_DB

db_pool = None

def initialize_database():
    """Forge the database and tables if they don't exist."""
    conn = None
    try:
        # Connect without specifying database first
        conn = mysql.connector.connect(**DB_CONFIG_NO_DB)
        cursor = conn.cursor()
        
        # Create database
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_CONFIG['database']}")
        cursor.execute(f"USE {DB_CONFIG['database']}")
        
        # Create player table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS player (
                player_id INT PRIMARY KEY AUTO_INCREMENT,
                username VARCHAR(50) UNIQUE NOT NULL,
                password VARCHAR(100) NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create savefile table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS savefile (
                save_id INT PRIMARY KEY AUTO_INCREMENT,
                player_id INT,
                slot_number INT,
                completion_pct DECIMAL(5,2),
                last_updated TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (player_id) REFERENCES player(player_id)
            )
        """)

        # Create mapzone table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mapzone (
                area_code INT PRIMARY KEY,
                area_name VARCHAR(100) NOT NULL,
                x_min DECIMAL(10,2) NOT NULL,
                y_min DECIMAL(10,2) NOT NULL,
                x_max DECIMAL(10,2) NOT NULL,
                y_max DECIMAL(10,2) NOT NULL
            )
        """)

        # Create playersession table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS playersession (
                session_id INT PRIMARY KEY AUTO_INCREMENT,
                player_id INT,
                save_id INT,
                start_time DATETIME NOT NULL,
                end_time DATETIME,
                FOREIGN KEY (player_id) REFERENCES player(player_id),
                FOREIGN KEY (save_id) REFERENCES savefile(save_id)
            )
        """)
        
        # Create deathevent table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deathevent (
                death_id BIGINT PRIMARY KEY AUTO_INCREMENT,
                session_id INT,
                area_code INT,
                death_x DECIMAL(10,2) NOT NULL,
                death_y DECIMAL(10,2) NOT NULL,
                death_cause VARCHAR(80) NOT NULL,
                FOREIGN KEY (session_id) REFERENCES playersession(session_id),
                FOREIGN KEY (area_code) REFERENCES mapzone(area_code)
            )
        """)

        # Create playerevent table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS playerevent (
                event_id BIGINT PRIMARY KEY AUTO_INCREMENT,
                session_id INT NOT NULL,
                area_code INT,
                event_type VARCHAR(50) NOT NULL,
                event_x DECIMAL(10,2),
                event_y DECIMAL(10,2),
                event_value INT,
                event_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES playersession(session_id),
                FOREIGN KEY (area_code) REFERENCES mapzone(area_code)
            )
        """)

        # Create indexes (ignore if they already exist)
        for idx_sql in [
            "CREATE INDEX idx_session_death ON deathevent(session_id)",
            "CREATE INDEX idx_area_death ON deathevent(area_code)",
            "CREATE INDEX idx_session_event ON playerevent(session_id)",
            "CREATE INDEX idx_area_event ON playerevent(area_code)",
            "CREATE INDEX idx_event_type ON playerevent(event_type)",
        ]:
            try:
                cursor.execute(idx_sql)
            except Error:
                pass  # Index already exists
        
        conn.commit()
        cursor.close()
        print("[OVERSEER] Database forged successfully.")
        return True
        
    except Error as e:
        print(f"[OVERSEER] Error initializing database: {e}")
        return False
    finally:
        if conn and conn.is_connected():
            conn.close()

def create_connection_pool():
    """Create the connection pool after DB is initialized."""
    global db_pool
    try:
        db_pool = mysql.connector.pooling.MySQLConnectionPool(**DB_CONFIG)
        print("[OVERSEER] Connection pool created.")
        return True
    except Error as e:
        print(f"[OVERSEER] Error creating connection pool: {e}")
        return False


class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True


class TelemetryHandler(http.server.BaseHTTPRequestHandler):
    
    def log_message(self, format, *args):
        """Custom logging format."""
        print(f"[{time.strftime('%H:%M:%S')}] {args[0]}")
    
    def send_json_response(self, status_code, data):
        """Helper to send JSON responses."""
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode('utf-8'))
    
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            data = json.loads(post_data) if post_data else {}
        except json.JSONDecodeError:
            self.send_json_response(400, {"error": "Invalid JSON"})
            return
        
        # Route to appropriate handler
        if self.path == '/player/register':
            self.handle_player_register(data)
        elif self.path == '/session/start':
            self.handle_session_start(data)
        elif self.path == '/session/end':
            self.handle_session_end(data)
        elif self.path == '/death':
            self.handle_death_event(data)
        elif self.path == '/death/batch':
            self.handle_death_event_batch(data)
        elif self.path == '/event':
            self.handle_player_event(data)
        elif self.path == '/event/batch':
            self.handle_player_event_batch(data)
        elif self.path == '/save/upload':
            self.handle_save_upload(data)
        elif self.path == '/mapzone':
            self.handle_mapzone_create(data)
        else:
            self.send_json_response(404, {"error": "Endpoint not found"})
    
    def do_GET(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        if path == '/health':
            self.send_json_response(200, {"status": "alive", "pool": db_pool is not None})
        elif path == '/deaths':
            self.handle_get_deaths()
        elif path == '/events':
            self.handle_get_events()
        elif path == '/mapzones':
            self.handle_get_mapzones()
        elif path.startswith('/leaderboard'):
            self.handle_get_leaderboard()
        else:
            self.send_json_response(404, {"error": "Endpoint not found"})
    
    def handle_player_register(self, data):
        """Register a new player."""
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            self.send_json_response(400, {"error": "username and password required"})
            return
        
        conn = None
        try:
            conn = db_pool.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO player (username, password)
                VALUES (%s, %s)
            """, (username, password))
            
            player_id = cursor.lastrowid
            conn.commit()
            cursor.close()
            
            print(f"[OVERSEER] Player registered: {username} (id={player_id})")
            self.send_json_response(200, {"status": "registered", "player_id": player_id})
            
        except Error as e:
            if e.errno == 1062:  # Duplicate entry
                # Return existing player_id
                try:
                    cursor = conn.cursor()
                    cursor.execute("SELECT player_id FROM player WHERE username = %s", (username,))
                    row = cursor.fetchone()
                    cursor.close()
                    if row:
                        self.send_json_response(200, {"status": "exists", "player_id": row[0]})
                    else:
                        self.send_json_response(500, {"error": str(e)})
                except Error as e2:
                    self.send_json_response(500, {"error": str(e2)})
            else:
                print(f"[OVERSEER] DB Error: {e}")
                self.send_json_response(500, {"error": str(e)})
        finally:
            if conn and conn.is_connected():
                conn.close()
    
    def handle_session_start(self, data):
        """Initialize a new telemetry session."""
        player_id = data.get('player_id')
        save_id = data.get('save_id')
        
        if not player_id:
            self.send_json_response(400, {"error": "player_id required"})
            return
        
        conn = None
        try:
            conn = db_pool.get_connection()
            cursor = conn.cursor()
            
            # Create session
            cursor.execute("""
                INSERT INTO playersession (player_id, save_id, start_time)
                VALUES (%s, %s, NOW())
            """, (player_id, save_id))
            
            session_id = cursor.lastrowid
            conn.commit()
            cursor.close()
            
            print(f"[OVERSEER] Session started: {session_id} for player {player_id}")
            self.send_json_response(200, {"status": "session_started", "session_id": session_id})
            
        except Error as e:
            print(f"[OVERSEER] DB Error: {e}")
            self.send_json_response(500, {"error": str(e)})
        finally:
            if conn and conn.is_connected():
                conn.close()
    
    def handle_session_end(self, data):
        """End the current session."""
        session_id = data.get('session_id')
        
        if not session_id:
            self.send_json_response(400, {"error": "session_id required"})
            return
        
        conn = None
        try:
            conn = db_pool.get_connection()
            cursor = conn.cursor()
            
            # Update session with end time
            cursor.execute("""
                UPDATE playersession SET end_time = NOW() WHERE session_id = %s
            """, (session_id,))
            
            conn.commit()
            cursor.close()
            
            print(f"[OVERSEER] Session ended: {session_id}")
            self.send_json_response(200, {"status": "session_ended"})
            
        except Error as e:
            print(f"[OVERSEER] DB Error: {e}")
            self.send_json_response(500, {"error": str(e)})
        finally:
            if conn and conn.is_connected():
                conn.close()

    def handle_save_upload(self, data):
        """Create or update a save file."""
        player_id = data.get('player_id')
        slot_number = data.get('slot_number', 1)
        completion_pct = data.get('completion_pct', 0.0)
        
        if not player_id:
            self.send_json_response(400, {"error": "player_id required"})
            return
        
        conn = None
        try:
            conn = db_pool.get_connection()
            cursor = conn.cursor()
            
            # Check if save slot already exists for this player
            cursor.execute("""
                SELECT save_id FROM savefile WHERE player_id = %s AND slot_number = %s
            """, (player_id, slot_number))
            existing = cursor.fetchone()
            
            if existing:
                # Update existing save
                cursor.execute("""
                    UPDATE savefile SET completion_pct = %s, last_updated = CURRENT_TIMESTAMP
                    WHERE save_id = %s
                """, (completion_pct, existing[0]))
                save_id = existing[0]
            else:
                # Create new save
                cursor.execute("""
                    INSERT INTO savefile (player_id, slot_number, completion_pct)
                    VALUES (%s, %s, %s)
                """, (player_id, slot_number, completion_pct))
                save_id = cursor.lastrowid
            
            conn.commit()
            cursor.close()
            
            print(f"[OVERSEER] Save synced for player {player_id}, slot {slot_number}")
            self.send_json_response(200, {"status": "save_synced", "save_id": save_id})
            
        except Error as e:
            print(f"[OVERSEER] DB Error: {e}")
            self.send_json_response(500, {"error": str(e)})
        finally:
            if conn and conn.is_connected():
                conn.close()
    
    def handle_death_event(self, data):
        """Record a death event."""
        session_id = data.get('session_id')
        area_code = data.get('area_code')
        death_x = data.get('death_x', 0.0)
        death_y = data.get('death_y', 0.0)
        death_cause = data.get('death_cause', 'unknown')
        
        if not session_id:
            self.send_json_response(400, {"error": "session_id required"})
            return
        
        conn = None
        try:
            conn = db_pool.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO deathevent (session_id, area_code, death_x, death_y, death_cause)
                VALUES (%s, %s, %s, %s, %s)
            """, (session_id, area_code, float(death_x), float(death_y), death_cause))
            
            conn.commit()
            cursor.close()
            
            print(f"[OVERSEER] Death recorded: '{death_cause}' at ({death_x}, {death_y})")
            self.send_json_response(200, {"status": "death_recorded"})
            
        except Error as e:
            print(f"[OVERSEER] DB Error: {e}")
            self.send_json_response(500, {"error": str(e)})
        finally:
            if conn and conn.is_connected():
                conn.close()

    def handle_death_event_batch(self, data):
        """Record multiple death events in a single request."""
        if not isinstance(data, list):
            self.send_json_response(400, {"error": "Expected a JSON array of death events"})
            return

        conn = None
        try:
            conn = db_pool.get_connection()
            cursor = conn.cursor()

            for event in data:
                session_id = event.get('session_id')
                area_code = event.get('area_code')
                death_x = event.get('death_x', 0.0)
                death_y = event.get('death_y', 0.0)
                death_cause = event.get('death_cause', 'unknown')

                if not session_id:
                    continue

                cursor.execute("""
                    INSERT INTO deathevent (session_id, area_code, death_x, death_y, death_cause)
                    VALUES (%s, %s, %s, %s, %s)
                """, (session_id, area_code, float(death_x), float(death_y), death_cause))

            conn.commit()
            cursor.close()

            print(f"[OVERSEER] Batch recorded: {len(data)} death events")
            self.send_json_response(200, {"status": "batch_recorded", "count": len(data)})

        except Error as e:
            print(f"[OVERSEER] DB Error: {e}")
            self.send_json_response(500, {"error": str(e)})
        finally:
            if conn and conn.is_connected():
                conn.close()

    def handle_mapzone_create(self, data):
        """Create or update a map zone."""
        area_code = data.get('area_code')
        area_name = data.get('area_name')
        x_min = data.get('x_min', 0.0)
        y_min = data.get('y_min', 0.0)
        x_max = data.get('x_max', 0.0)
        y_max = data.get('y_max', 0.0)

        if area_code is None or not area_name:
            self.send_json_response(400, {"error": "area_code and area_name required"})
            return

        conn = None
        try:
            conn = db_pool.get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO mapzone (area_code, area_name, x_min, y_min, x_max, y_max)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE area_name=%s, x_min=%s, y_min=%s, x_max=%s, y_max=%s
            """, (area_code, area_name, x_min, y_min, x_max, y_max,
                  area_name, x_min, y_min, x_max, y_max))

            conn.commit()
            cursor.close()

            print(f"[OVERSEER] Map zone saved: {area_name} (code={area_code})")
            self.send_json_response(200, {"status": "mapzone_saved", "area_code": area_code})

        except Error as e:
            print(f"[OVERSEER] DB Error: {e}")
            self.send_json_response(500, {"error": str(e)})
        finally:
            if conn and conn.is_connected():
                conn.close()
    
    def handle_player_event(self, data):
        """Record a generic player event."""
        session_id = data.get('session_id')
        event_type = data.get('event_type')
        area_code = data.get('area_code')
        event_x = data.get('event_x')
        event_y = data.get('event_y')
        event_value = data.get('event_value')

        if not session_id or not event_type:
            self.send_json_response(400, {"error": "session_id and event_type required"})
            return

        conn = None
        try:
            conn = db_pool.get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO playerevent (session_id, area_code, event_type, event_x, event_y, event_value)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (session_id, area_code, event_type, event_x, event_y, event_value))

            conn.commit()
            cursor.close()

            print(f"[OVERSEER] Event recorded: {event_type} at ({event_x}, {event_y})")
            self.send_json_response(200, {"status": "event_recorded"})

        except Error as e:
            print(f"[OVERSEER] DB Error: {e}")
            self.send_json_response(500, {"error": str(e)})
        finally:
            if conn and conn.is_connected():
                conn.close()

    def handle_player_event_batch(self, data):
        """Record multiple player events in a single request."""
        if not isinstance(data, list):
            self.send_json_response(400, {"error": "Expected a JSON array of events"})
            return

        conn = None
        try:
            conn = db_pool.get_connection()
            cursor = conn.cursor()

            for event in data:
                session_id = event.get('session_id')
                event_type = event.get('event_type')
                area_code = event.get('area_code')
                event_x = event.get('event_x')
                event_y = event.get('event_y')
                event_value = event.get('event_value')

                if not session_id or not event_type:
                    continue

                cursor.execute("""
                    INSERT INTO playerevent (session_id, area_code, event_type, event_x, event_y, event_value)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (session_id, area_code, event_type, event_x, event_y, event_value))

            conn.commit()
            cursor.close()

            print(f"[OVERSEER] Batch recorded: {len(data)} player events")
            self.send_json_response(200, {"status": "batch_recorded", "count": len(data)})

        except Error as e:
            print(f"[OVERSEER] DB Error: {e}")
            self.send_json_response(500, {"error": str(e)})
        finally:
            if conn and conn.is_connected():
                conn.close()

    def handle_get_events(self):
        """Fetch recent player events."""
        parsed_url = urlparse(self.path)
        params = parse_qs(parsed_url.query)
        event_type = params.get('event_type', [None])[0]
        area_code = params.get('area_code', [None])[0]

        conn = None
        try:
            conn = db_pool.get_connection()
            cursor = conn.cursor(dictionary=True)

            query = """
                SELECT e.event_id, e.session_id, e.area_code, m.area_name,
                       e.event_type, e.event_x, e.event_y, e.event_value, e.event_time
                FROM playerevent e
                LEFT JOIN mapzone m ON e.area_code = m.area_code
                WHERE 1=1
            """
            query_params = []

            if event_type:
                query += " AND e.event_type = %s"
                query_params.append(event_type)
            if area_code:
                query += " AND e.area_code = %s"
                query_params.append(area_code)

            query += " ORDER BY e.event_id DESC LIMIT 100"

            cursor.execute(query, tuple(query_params))
            events = cursor.fetchall()
            for ev in events:
                if ev.get('event_x') is not None:
                    ev['event_x'] = float(ev['event_x'])
                if ev.get('event_y') is not None:
                    ev['event_y'] = float(ev['event_y'])
            cursor.close()

            self.send_json_response(200, {"events": events})

        except Error as e:
            self.send_json_response(500, {"error": str(e)})
        finally:
            if conn and conn.is_connected():
                conn.close()

    def handle_get_deaths(self):
        """Fetch recent death events."""
        parsed_url = urlparse(self.path)
        params = parse_qs(parsed_url.query)
        area_code = params.get('area_code', [None])[0]

        conn = None
        try:
            conn = db_pool.get_connection()
            cursor = conn.cursor(dictionary=True)
            
            if area_code:
                cursor.execute("""
                    SELECT d.death_id, d.session_id, d.area_code, m.area_name,
                           d.death_x, d.death_y, d.death_cause
                    FROM deathevent d
                    LEFT JOIN mapzone m ON d.area_code = m.area_code
                    WHERE d.area_code = %s
                    ORDER BY d.death_id DESC LIMIT 100
                """, (area_code,))
            else:
                cursor.execute("""
                    SELECT d.death_id, d.session_id, d.area_code, m.area_name,
                           d.death_x, d.death_y, d.death_cause
                    FROM deathevent d
                    LEFT JOIN mapzone m ON d.area_code = m.area_code
                    ORDER BY d.death_id DESC LIMIT 100
                """)

            deaths = cursor.fetchall()
            # Convert Decimal to float for JSON serialization
            for death in deaths:
                if death.get('death_x') is not None:
                    death['death_x'] = float(death['death_x'])
                if death.get('death_y') is not None:
                    death['death_y'] = float(death['death_y'])
            cursor.close()
            
            self.send_json_response(200, {"deaths": deaths})
            
        except Error as e:
            self.send_json_response(500, {"error": str(e)})
        finally:
            if conn and conn.is_connected():
                conn.close()

    def handle_get_mapzones(self):
        """Fetch all map zones."""
        conn = None
        try:
            conn = db_pool.get_connection()
            cursor = conn.cursor(dictionary=True)

            cursor.execute("SELECT * FROM mapzone ORDER BY area_code")
            zones = cursor.fetchall()
            # Convert Decimal to float for JSON serialization
            for zone in zones:
                for key in ('x_min', 'y_min', 'x_max', 'y_max'):
                    if zone.get(key) is not None:
                        zone[key] = float(zone[key])
            cursor.close()

            self.send_json_response(200, {"mapzones": zones})

        except Error as e:
            self.send_json_response(500, {"error": str(e)})
        finally:
            if conn and conn.is_connected():
                conn.close()

    def handle_get_leaderboard(self):
        """Fetch leaderboard - players ranked by death count (fewest = best)."""
        conn = None
        try:
            conn = db_pool.get_connection()
            cursor = conn.cursor(dictionary=True)
            
            cursor.execute("""
                SELECT p.player_id, p.username, COUNT(d.death_id) AS death_count
                FROM player p
                LEFT JOIN playersession ps ON p.player_id = ps.player_id
                LEFT JOIN deathevent d ON ps.session_id = d.session_id
                GROUP BY p.player_id, p.username
                ORDER BY death_count ASC
                LIMIT 20
            """)
            leaderboard = cursor.fetchall()
            cursor.close()
            self.send_json_response(200, {"leaderboard": leaderboard})
            
        except Error as e:
            print(f"[OVERSEER] DB Error: {e}")
            self.send_json_response(500, {"error": str(e)})
        finally:
            if conn and conn.is_connected():
                conn.close()


if __name__ == "__main__":
    print("=" * 50)
    print("  THE OVERSEER - Telemetry Collection Server")
    print("=" * 50)
    
    # Phase 1: Forge the database
    if not initialize_database():
        print("[OVERSEER] Failed to initialize database. Exiting.")
        sys.exit(1)
    
    # Create connection pool
    if not create_connection_pool():
        print("[OVERSEER] Failed to create connection pool. Exiting.")
        sys.exit(1)
    
    # Start the server
    with ThreadingTCPServer(("", PORT), TelemetryHandler) as httpd:
        print(f"[OVERSEER] Listening on port {PORT}")
        print(f"[OVERSEER] Connected to MySQL at {DB_CONFIG['host']}")
        print("-" * 50)
        print("Endpoints:")
        print("  POST /player/register - Register a player")
        print("  POST /session/start   - Start a new session")
        print("  POST /session/end     - End a session")
        print("  POST /death           - Record a death event")
        print("  POST /death/batch     - Record death events in batch")
        print("  POST /event           - Record a player event")
        print("  POST /event/batch     - Record player events in batch")
        print("  POST /save/upload     - Upload/update save file")
        print("  POST /mapzone         - Create/update map zone")
        print("  GET  /health          - Health check")
        print("  GET  /deaths          - Fetch recent deaths")
        print("  GET  /events          - Fetch recent player events")
        print("  GET  /mapzones        - Fetch all map zones")
        print("  GET  /leaderboard     - Player leaderboard")
        print("-" * 50)
        print("Waiting for victims...")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[OVERSEER] Shutting down...")
            httpd.shutdown()
