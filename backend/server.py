import http.server
import socketserver
import json
import pymongo
from pymongo import MongoClient
import time
from datetime import datetime
import os
import sys
import select
from urllib.parse import urlparse, parse_qs

# Import shared configuration from the project root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import var

PORT = var.SERVER_PORT

# MongoDB Configuration from common var.py
MONGO_URI = var.MONGO_URI
DB_NAME = var.DB_NAME

db_client = None
db = None

def initialize_database():
    """Forge the MongoDB connection and collections."""
    global db_client, db
    try:
        db_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        # Force a connection check
        db_client.admin.command('ping')
        db = db_client[DB_NAME]
        
        # Create indexes for performance
        db.players.create_index('username', unique=True)
        db.players.create_index('player_id', unique=True)
        db.savefiles.create_index([('player_id', 1), ('slot_number', 1)], unique=True)
        db.sessions.create_index('session_id', unique=True)
        db.sessions.create_index('player_id')
        db.events.create_index('session_id')
        db.events.create_index('event_time')
        db.deaths.create_index('session_id')
        
        print(f'[OVERSEER] Connected to MongoDB Atlas: {DB_NAME}')
        return True
    except Exception as e:
        print(f'[OVERSEER] Critical Connection Error: {e}')
        return False

# Custom server to handle Windows-specific socket issues if they arise
class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    
    def service_actions(self):
        """Called by the serve_forever loop. We can use this to prevent tight loops."""
        super().service_actions()
        time.sleep(0.01)

class TelemetryHandler(http.server.BaseHTTPRequestHandler):
    def send_json_response(self, status_code, data):
        try:
            self.send_response(status_code)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(data, default=str).encode('utf-8'))
        except (ConnectionAbortedError, ConnectionResetError):
            print("[OVERSEER] Client disconnected prematurely")

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        try:
            data = json.loads(post_data) if post_data else {}
        except:
            self.send_json_response(400, {'error': 'Invalid JSON'})
            return
        
        if self.path == '/player/register': self.handle_player_register(data)
        elif self.path == '/session/start': self.handle_session_start(data)
        elif self.path == '/session/end': self.handle_session_end(data)
        elif self.path == '/death': self.handle_death_event(data)
        elif self.path == '/event': self.handle_player_event(data)
        elif self.path == '/save/upload': self.handle_save_upload(data)
        else: self.send_json_response(404, {'error': 'Not found'})

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/health': self.send_json_response(200, {'status': 'alive'})
        elif parsed.path == '/users/list': self.handle_get_users_list()
        elif parsed.path.startswith('/leaderboard'): self.handle_get_leaderboard()
        else: self.send_json_response(404, {'error': 'Not found'})

    def handle_get_users_list(self):
        try:
            users = list(db.players.find({}, {'password': 0, '_id': 0}))
            self.send_json_response(200, {'users': users})
        except Exception as e: self.send_json_response(500, {'error': str(e)})

    def handle_player_register(self, data):
        u, p = data.get('username'), data.get('password')
        if not u or not p: return self.send_json_response(400, {'error': 'Missing fields'})
        try:
            player = db.players.find_one({'username': u})
            if player: return self.send_json_response(200, {'status': 'exists', 'player_id': player['player_id']})
            max_p = db.players.find_one(sort=[('player_id', -1)])
            pid = (max_p['player_id'] + 1) if max_p else 1
            db.players.insert_one({'player_id': pid, 'username': u, 'password': p, 'created_at': datetime.now()})
            self.send_json_response(200, {'status': 'registered', 'player_id': pid})
        except Exception as e: self.send_json_response(500, {'error': str(e)})

    def handle_session_start(self, data):
        pid = data.get('player_id') or data.get('user_id')
        if not pid: return self.send_json_response(400, {'error': 'player_id required'})
        try:
            max_s = db.sessions.find_one(sort=[('session_id', -1)])
            sid = (max_s['session_id'] + 1) if max_s else 1
            db.sessions.insert_one({'session_id': sid, 'player_id': pid, 'start_time': datetime.now()})
            self.send_json_response(200, {'status': 'session_started', 'session_id': sid})
        except Exception as e: self.send_json_response(500, {'error': str(e)})

    def handle_session_end(self, data):
        sid = data.get('session_id')
        if not sid: return self.send_json_response(400, {'error': 'session_id required'})
        try:
            db.sessions.update_one({'session_id': int(sid)}, {'$set': {'end_time': datetime.now()}})
            self.send_json_response(200, {'status': 'session_ended'})
        except Exception as e: self.send_json_response(500, {'error': str(e)})

    def handle_save_upload(self, data):
        pid = data.get('player_id')
        if not pid: return self.send_json_response(400, {'error': 'player_id required'})
        try:
            db.savefiles.update_one({'player_id': pid}, {'$set': {'data': data.get('save_data'), 'last_updated': datetime.now()}}, upsert=True)
            self.send_json_response(200, {'status': 'save_synced'})
        except Exception as e: self.send_json_response(500, {'error': str(e)})

    def handle_death_event(self, data):
        sid = data.get('session_id')
        if not sid: return self.send_json_response(400, {'error': 'session_id required'})
        try:
            db.deaths.insert_one({'session_id': int(sid), 'x': data.get('x'), 'y': data.get('y'), 'cause': data.get('cause'), 'time': datetime.now()})
            self.send_json_response(200, {'status': 'death_recorded'})
        except Exception as e: self.send_json_response(500, {'error': str(e)})

    def handle_player_event(self, data):
        sid, et = data.get('session_id'), data.get('event_type')
        if not sid or not et: return self.send_json_response(400, {'error': 'Missing fields'})
        try:
            db.events.insert_one({'session_id': int(sid), 'event_type': et, 'event_time': datetime.now()})
            self.send_json_response(200, {'status': 'event_recorded'})
        except Exception as e: self.send_json_response(500, {'error': str(e)})

    def handle_get_leaderboard(self):
        try:
            # Aggregate deaths per player
            # 1. Join players with sessions
            # 2. Join sessions with deaths
            # 3. Group by player and sum the number of death records
            pipe = [
                {
                    '$lookup': {
                        'from': 'sessions',
                        'localField': 'player_id',
                        'foreignField': 'player_id',
                        'as': 'player_sessions'
                    }
                },
                {'$unwind': {'path': '$player_sessions', 'preserveNullAndEmptyArrays': True}},
                {
                    '$lookup': {
                        'from': 'deaths',
                        'localField': 'player_sessions.session_id',
                        'foreignField': 'session_id',
                        'as': 'session_deaths'
                    }
                },
                {
                    '$group': {
                        '_id': '$player_id',
                        'username': {'$first': '$username'},
                        'death_count': {'$sum': {'$size': {'$ifNull': ['$session_deaths', []]}}}
                    }
                },
                {'$sort': {'death_count': -1}}, # Highest deaths first for a "Leaderboard"
                {'$limit': 10}
            ]
            res = list(db.players.aggregate(pipe))
            # Clean up MongoDB _id and format for response
            for p in res:
                p['player_id'] = p['_id']
                del p['_id']
            
            self.send_json_response(200, {'leaderboard': res})
        except Exception as e:
            print(f"[OVERSEER] Leaderboard Error: {e}")
            self.send_json_response(500, {'error': str(e)})

if __name__ == '__main__':
    if initialize_database():
        with ThreadingTCPServer(('', PORT), TelemetryHandler) as httpd:
            print(f'[OVERSEER] Listening on {PORT}')
            httpd.serve_forever()
