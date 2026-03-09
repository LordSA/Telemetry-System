import http.server
import socketserver
import json
import pymongo
from pymongo import MongoClient
import time
from datetime import datetime
import os
import sys
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
    global db_client, db
    try:
        db_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        db_client.server_info()
        db = db_client[DB_NAME]
        
        db.players.create_index('username', unique=True)
        db.players.create_index('player_id', unique=True)
        db.savefiles.create_index([('player_id', 1), ('slot_number', 1)], unique=True)
        db.sessions.create_index('session_id', unique=True)
        db.sessions.create_index('player_id')
        db.events.create_index('session_id')
        db.events.create_index('event_type')
        db.events.create_index('area_code')
        db.events.create_index('event_time')
        db.deaths.create_index('session_id')
        db.deaths.create_index('area_code')
        db.mapzones.create_index('area_code', unique=True)
        
        print(f'[OVERSEER] Connected to MongoDB at {MONGO_URI}')
        return True
    except Exception as e:
        print(f'[OVERSEER] Error initializing MongoDB: {e}')
        return False

class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True

class TelemetryHandler(http.server.BaseHTTPRequestHandler):
    def send_json_response(self, status_code, data):
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode('utf-8'))
    
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
        elif self.path == '/death/batch': self.handle_death_event_batch(data)
        elif self.path == '/event': self.handle_player_event(data)
        elif self.path == '/event/batch': self.handle_player_event_batch(data)
        elif self.path == '/save/upload': self.handle_save_upload(data)
        elif self.path == '/mapzone': self.handle_mapzone_create(data)
        else: self.send_json_response(404, {'error': 'Not found'})

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/health': self.send_json_response(200, {'status': 'alive', 'db': db is not None})
        elif parsed.path == '/deaths': self.handle_get_deaths()
        elif parsed.path == '/events': self.handle_get_events()
        elif parsed.path == '/mapzones': self.handle_get_mapzones()
        elif parsed.path.startswith('/leaderboard'): self.handle_get_leaderboard()
        else: self.send_json_response(404, {'error': 'Not found'})

    def handle_player_register(self, data):
        u, p = data.get('username'), data.get('password')
        if not u or not p: return self.send_json_response(400, {'error': 'Missing fields'})
        try:
            res = db.players.find_one({'username': u})
            if res: return self.send_json_response(200, {'status': 'exists', 'player_id': res['player_id']})
            max_p = db.players.find_one(sort=[('player_id', -1)])
            pid = (max_p['player_id'] + 1) if max_p else 1
            db.players.insert_one({'player_id': pid, 'username': u, 'password': p, 'created_at': datetime.now()})
            self.send_json_response(200, {'status': 'registered', 'player_id': pid})
        except Exception as e: self.send_json_response(500, {'error': str(e)})

    def handle_session_start(self, data):
        pid, sid_req = data.get('player_id'), data.get('save_id')
        if not pid: return self.send_json_response(400, {'error': 'player_id required'})
        try:
            max_s = db.sessions.find_one(sort=[('session_id', -1)])
            sid = (max_s['session_id'] + 1) if max_s else 1
            db.sessions.insert_one({'session_id': sid, 'player_id': pid, 'save_id': sid_req, 'start_time': datetime.now()})
            self.send_json_response(200, {'status': 'session_started', 'session_id': sid})
        except Exception as e: self.send_json_response(500, {'error': str(e)})

    def handle_session_end(self, data):
        sid = data.get('session_id')
        if not sid: return self.send_json_response(400, {'error': 'session_id required'})
        try:
            db.sessions.update_one({'session_id': int(sid)}, {'': {'end_time': datetime.now()}})
            self.send_json_response(200, {'status': 'session_ended'})
        except Exception as e: self.send_json_response(500, {'error': str(e)})

    def handle_save_upload(self, data):
        pid, slot, pct = data.get('player_id'), data.get('slot_number', 1), data.get('completion_pct', 0.0)
        if not pid: return self.send_json_response(400, {'error': 'player_id required'})
        try:
            db.savefiles.update_one({'player_id': pid, 'slot_number': slot}, {'': {'completion_pct': pct, 'last_updated': datetime.now()}}, upsert=True)
            self.send_json_response(200, {'status': 'save_synced'})
        except Exception as e: self.send_json_response(500, {'error': str(e)})

    def handle_death_event(self, data):
        sid = data.get('session_id')
        if not sid: return self.send_json_response(400, {'error': 'session_id required'})
        try:
            db.deaths.insert_one({
                'session_id': int(sid), 'area_code': data.get('area_code'), 'death_x': float(data.get('death_x',0)),
                'death_y': float(data.get('death_y',0)), 'death_cause': data.get('death_cause','unknown'), 'recorded_at': datetime.now()
            })
            self.send_json_response(200, {'status': 'death_recorded'})
        except Exception as e: self.send_json_response(500, {'error': str(e)})

    def handle_death_event_batch(self, data):
        if not isinstance(data, list): return self.send_json_response(400, {'error': 'Expected array'})
        try:
            recs = [{'session_id': int(e['session_id']), 'area_code': e.get('area_code'),
                     'death_x': float(e.get('death_x',0)), 'death_y': float(e.get('death_y',0)),
                     'death_cause': e.get('death_cause','unknown'), 'recorded_at': datetime.now()} for e in data if e.get('session_id')]
            if recs: db.deaths.insert_many(recs)
            self.send_json_response(200, {'status': 'batch_recorded', 'count': len(recs)})
        except Exception as e: self.send_json_response(500, {'error': str(e)})

    def handle_mapzone_create(self, data):
        ac, name = data.get('area_code'), data.get('area_name')
        if ac is None or not name: return self.send_json_response(400, {'error': 'Missing fields'})
        try:
            db.mapzones.update_one({'area_code': ac}, {'': {
                'area_name': name, 'x_min': float(data.get('x_min',0)), 'y_min': float(data.get('y_min',0)),
                'x_max': float(data.get('x_max',0)), 'y_max': float(data.get('y_max',0))
            }}, upsert=True)
            self.send_json_response(200, {'status': 'mapzone_saved', 'area_code': ac})
        except Exception as e: self.send_json_response(500, {'error': str(e)})

    def handle_player_event(self, data):
        sid, et = data.get('session_id'), data.get('event_type')
        if not sid or not et: return self.send_json_response(400, {'error': 'Missing fields'})
        try:
            db.events.insert_one({'session_id': int(sid), 'event_type': et, 'area_code': data.get('area_code'),
                                  'event_x': float(data['event_x']) if data.get('event_x') else None,
                                  'event_y': float(data['event_y']) if data.get('event_y') else None,
                                  'event_value': data.get('event_value'), 'event_time': datetime.now()})
            self.send_json_response(200, {'status': 'event_recorded'})
        except Exception as e: self.send_json_response(500, {'error': str(e)})

    def handle_player_event_batch(self, data):
        if not isinstance(data, list): return self.send_json_response(400, {'error': 'Expected array'})
        try:
            recs = [{'session_id': int(e['session_id']), 'event_type': e['event_type'], 'area_code': e.get('area_code'),
                     'event_x': float(e['event_x']) if e.get('event_x') else None, 'event_y': float(e['event_y']) if e.get('event_y') else None,
                     'event_value': e.get('event_value'), 'event_time': datetime.now()} for e in data if e.get('session_id') and e.get('event_type')]
            if recs: db.events.insert_many(recs)
            self.send_json_response(200, {'status': 'batch_recorded', 'count': len(recs)})
        except Exception as e: self.send_json_response(500, {'error': str(e)})

    def handle_get_events(self):
        try:
            cursor = db.events.find({}).sort('event_time', -1).limit(100)
            events = list(cursor)
            for ev in events: del ev['_id']
            self.send_json_response(200, {'events': events})
        except Exception as e: self.send_json_response(500, {'error': str(e)})

    def handle_get_deaths(self):
        try:
            cursor = db.deaths.find({}).sort('recorded_at', -1).limit(100)
            recs = list(cursor)
            for r in recs: del r['_id']
            self.send_json_response(200, {'deaths': recs})
        except Exception as e: self.send_json_response(500, {'error': str(e)})

    def handle_get_mapzones(self):
        try:
            zones = list(db.mapzones.find({}))
            for z in zones: del z['_id']
            self.send_json_response(200, {'mapzones': zones})
        except Exception as e: self.send_json_response(500, {'error': str(e)})

    def handle_get_leaderboard(self):
        try:
            pipe = [{'': {'from': 'sessions', 'localField': 'player_id', 'foreignField': 'player_id', 'as': 's'}},
                    {'': ''}, {'': {'from': 'deaths', 'localField': 's.session_id', 'foreignField': 'session_id', 'as': 'd'}},
                    {'': {'username': 1, 'player_id': 1, 'dc': {'': ''}}},
                    {'': {'_id': '', 'username': {'': ''}, 'dc': {'': ''}}},
                    {'': {'dc': 1}}, {'': 20}]
            res = list(db.players.aggregate(pipe))
            for p in res: p['player_id'] = p['_id']; del p['_id']
            self.send_json_response(200, {'leaderboard': res})
        except Exception as e: self.send_json_response(500, {'error': str(e)})

if __name__ == '__main__':
    if initialize_database():
        with ThreadingTCPServer(('', PORT), TelemetryHandler) as httpd:
            print(f'[OVERSEER] Listening on {PORT}'); httpd.serve_forever()
