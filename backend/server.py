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
        elif self.path == '/death/batch': self.handle_death_batch(data)
        elif self.path == '/event': self.handle_player_event(data)
        elif self.path == '/event/batch': self.handle_event_batch(data)
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
        u, p = data.get('username'), data.get('password', '')
        if not u: return self.send_json_response(400, {'error': 'Missing username'})
        try:
            player = db.players.find_one({'username': u})
            if player:
                print(f"[DEBUG] [players] Player already exists: id={player['player_id']}, username='{u}'")
                return self.send_json_response(200, {'status': 'exists', 'player_id': player['player_id']})
            max_p = db.players.find_one(sort=[('player_id', -1)])
            pid = (max_p['player_id'] + 1) if max_p else 1
            db.players.insert_one({'player_id': pid, 'username': u, 'password': p, 'created_at': datetime.now()})
            print(f"[DEBUG] [players] Registered new player: id={pid}, username='{u}'")
            self.send_json_response(200, {'status': 'registered', 'player_id': pid})
        except Exception as e: self.send_json_response(500, {'error': str(e)})

    def handle_session_start(self, data):
        pid = data.get('player_id') or data.get('user_id')
        if not pid: return self.send_json_response(400, {'error': 'player_id required'})
        try:
            max_s = db.sessions.find_one(sort=[('session_id', -1)])
            sid = (max_s['session_id'] + 1) if max_s else 1
            session_doc = {
                'session_id': sid,
                'player_id': pid,
                'start_time': datetime.now()
            }
            # Include save_id if the game client provides it
            save_id = data.get('save_id')
            if save_id is not None:
                session_doc['save_id'] = int(save_id)
            db.sessions.insert_one(session_doc)
            print(f"[DEBUG] [sessions] Session started: session_id={sid}, player_id={pid}, save_id={save_id}")
            self.send_json_response(200, {'status': 'session_started', 'session_id': sid})
        except Exception as e: self.send_json_response(500, {'error': str(e)})

    def handle_session_end(self, data):
        sid = data.get('session_id')
        if not sid: return self.send_json_response(400, {'error': 'session_id required'})
        try:
            db.sessions.update_one({'session_id': int(sid)}, {'$set': {'end_time': datetime.now()}})
            print(f"[DEBUG] [sessions] Session ended: session_id={sid}")
            self.send_json_response(200, {'status': 'session_ended'})
        except Exception as e: self.send_json_response(500, {'error': str(e)})

    def handle_save_upload(self, data):
        pid = data.get('player_id')
        if not pid: return self.send_json_response(400, {'error': 'player_id required'})
        try:
            slot_number = data.get('slot_number', 0)
            completion_pct = data.get('completion_pct', 0.0)
            
            # Upsert by player_id + slot_number
            result = db.savefiles.find_one_and_update(
                {'player_id': int(pid), 'slot_number': int(slot_number)},
                {'$set': {
                    'completion_pct': float(completion_pct),
                    'save_data': data.get('save_data'),
                    'last_updated': datetime.now()
                }},
                upsert=True,
                return_document=pymongo.ReturnDocument.AFTER
            )
            
            # Generate a save_id for the game client
            # Use the existing save_id if present, otherwise assign one
            if 'save_id' not in result:
                max_save = db.savefiles.find_one(sort=[('save_id', -1)])
                new_save_id = (max_save['save_id'] + 1) if (max_save and 'save_id' in max_save) else 1
                db.savefiles.update_one({'_id': result['_id']}, {'$set': {'save_id': new_save_id}})
                save_id = new_save_id
            else:
                save_id = result['save_id']
            
            print(f"[DEBUG] [savefiles] Save synced: player_id={pid}, slot={slot_number}, completion={completion_pct}%, save_id={save_id}")
            self.send_json_response(200, {'status': 'save_synced', 'save_id': save_id})
        except Exception as e: self.send_json_response(500, {'error': str(e)})

    def handle_death_event(self, data):
        sid = data.get('session_id')
        if not sid: return self.send_json_response(400, {'error': 'session_id required'})
        try:
            death_doc = {
                'session_id': int(sid),
                'x': data.get('death_x') or data.get('x'),
                'y': data.get('death_y') or data.get('y'),
                'cause': data.get('death_cause') or data.get('cause'),
                'time': datetime.now()
            }
            # Include area_code if provided by the game client
            area_code = data.get('area_code')
            if area_code is not None:
                death_doc['area_code'] = int(area_code)
            db.deaths.insert_one(death_doc)
            print(f"[DEBUG] [deaths] Death recorded: session_id={sid}, cause={death_doc.get('cause')}, pos=({death_doc.get('x')}, {death_doc.get('y')}), area_code={death_doc.get('area_code', 'N/A')}")
            self.send_json_response(200, {'status': 'death_recorded'})
        except Exception as e: self.send_json_response(500, {'error': str(e)})

    def handle_death_batch(self, data):
        if not isinstance(data, list): return self.send_json_response(400, {'error': 'List expected'})
        try:
            for item in data:
                sid = item.get('session_id')
                if sid:
                    death_doc = {
                        'session_id': int(sid),
                        'x': item.get('death_x') or item.get('x'),
                        'y': item.get('death_y') or item.get('y'),
                        'cause': item.get('death_cause') or item.get('cause'),
                        'time': datetime.now()
                    }
                    area_code = item.get('area_code')
                    if area_code is not None:
                        death_doc['area_code'] = int(area_code)
                    db.deaths.insert_one(death_doc)
                    print(f"[DEBUG] [deaths] Batch death: session_id={sid}, cause={death_doc.get('cause')}, pos=({death_doc.get('x')}, {death_doc.get('y')}), area_code={death_doc.get('area_code', 'N/A')}")
            print(f"[DEBUG] [deaths] Batch complete: {len(data)} death(s) processed")
            self.send_json_response(200, {'status': 'batch_deaths_recorded'})
        except Exception as e: self.send_json_response(500, {'error': str(e)})

    def handle_player_event(self, data):
        sid, et = data.get('session_id'), data.get('event_type')
        if not sid or not et: return self.send_json_response(400, {'error': 'Missing fields'})
        try:
            event_doc = {
                'session_id': int(sid),
                'event_type': et,
                'x': data.get('event_x'),
                'y': data.get('event_y'),
                'value': data.get('event_value'),
                'area_code': data.get('area_code'),
                'event_time': datetime.now()
            }
            db.events.insert_one(event_doc)
            print(f"[DEBUG] [events] Event recorded: session_id={sid}, type={et}, pos=({event_doc.get('x')}, {event_doc.get('y')}), value={event_doc.get('value')}, area_code={event_doc.get('area_code', 'N/A')}")
            self.send_json_response(200, {'status': 'event_recorded'})
        except Exception as e: self.send_json_response(500, {'error': str(e)})

    def handle_event_batch(self, data):
        if not isinstance(data, list): return self.send_json_response(400, {'error': 'List expected'})
        try:
            for item in data:
                sid, et = item.get('session_id'), item.get('event_type')
                if sid and et:
                    event_doc = {
                        'session_id': int(sid),
                        'event_type': et,
                        'x': item.get('event_x'),
                        'y': item.get('event_y'),
                        'value': item.get('event_value'),
                        'area_code': item.get('area_code'),
                        'event_time': datetime.now()
                    }
                    db.events.insert_one(event_doc)
                    print(f"[DEBUG] [events] Batch event: session_id={sid}, type={et}, pos=({event_doc.get('x')}, {event_doc.get('y')}), value={event_doc.get('value')}")
            print(f"[DEBUG] [events] Batch complete: {len(data)} event(s) processed")
            self.send_json_response(200, {'status': 'batch_events_recorded'})
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
