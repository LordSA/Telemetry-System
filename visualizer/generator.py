import pymongo
from pymongo import MongoClient
import matplotlib.pyplot as plt
import numpy as np
from scipy import ndimage
from scipy.stats import gaussian_kde
import os
import argparse
import sys

# Import shared configuration from the project root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import var

OUTPUT_DIR = var.VISUALIZER_OUTPUT_DIR

# MongoDB Configuration from common var.py
MONGO_URI = var.MONGO_URI
DB_NAME = var.DB_NAME

_client = None
_db = None


def connect_db():
    """Connect to the MongoDB database."""
    global _client, _db
    try:
        if _client is None:
            _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
            _client.admin.command('ping')
            _db = _client[DB_NAME]
            print(f"[INFO] Connected to MongoDB: {DB_NAME}")
        return _db
    except Exception as e:
        print(f"[ERROR] Connecting to MongoDB: {e}")
        return None


def fetch_deaths(area_code=None, session_id=None):
    """Fetch death coordinates, optionally filtered by area or session."""
    db = connect_db()
    if db is None:
        return []

    try:
        query = {}
        if area_code is not None:
            query['area_code'] = int(area_code)
        if session_id is not None:
            query['session_id'] = int(session_id)

        deaths = db.deaths.find(query, {'x': 1, 'y': 1, '_id': 0})
        data = [(float(d['x']), float(d['y'])) for d in deaths if d.get('x') is not None and d.get('y') is not None]
        return data
    except Exception as e:
        print(f"[ERROR] Fetching deaths: {e}")
        return []


def fetch_death_causes(area_code=None):
    """Fetch death cause distribution."""
    db = connect_db()
    if db is None:
        return []

    try:
        match_stage = {}
        if area_code is not None:
            match_stage['area_code'] = int(area_code)

        pipeline = []
        if match_stage:
            pipeline.append({'$match': match_stage})
        pipeline.extend([
            {'$group': {'_id': '$cause', 'count': {'$sum': 1}}},
            {'$sort': {'count': -1}}
        ])

        results = list(db.deaths.aggregate(pipeline))
        return [(r['_id'], r['count']) for r in results if r['_id'] is not None]
    except Exception as e:
        print(f"[ERROR] Fetching death causes: {e}")
        return []


def fetch_mapzones():
    """Fetch all map zones for overlay context."""
    db = connect_db()
    if db is None:
        return []

    try:
        zones = list(db.mapzones.find({}, {'_id': 0}))
        for z in zones:
            for key in ('x_min', 'y_min', 'x_max', 'y_max'):
                if key in z:
                    z[key] = float(z[key])
        return zones
    except Exception as e:
        print(f"[ERROR] Fetching map zones: {e}")
        return []


def generate_kde_heatmap(coords, map_size=(1000, 1000), output_name=None, title='Deaths', cmap='Reds'):
    """
    Generate a Kernel Density Estimation heatmap.
    
    Uses Gaussian KDE to create smooth density gradients from point data.
    Output is a transparent PNG that can be overlaid on level maps.
    """
    if not coords or len(coords) < 2:
        print(f"[WARNING] Not enough data points ({len(coords)} points)")
        return None
    
    x = np.array([c[0] for c in coords])
    y = np.array([c[1] for c in coords])
    
    print(f"[INFO] Generating KDE heatmap for {title} ({len(coords)} points)")
    
    # Create figure with transparent background
    fig, ax = plt.subplots(figsize=(12, 12))
    fig.patch.set_alpha(0)
    ax.patch.set_alpha(0)
    
    try:
        # Kernel Density Estimation
        xy = np.vstack([x, y])
        kde = gaussian_kde(xy)
        
        # Create grid for evaluation
        xmin, xmax = 0, map_size[0]
        ymin, ymax = 0, map_size[1]
        
        # Auto-adjust if data is outside default bounds
        if x.max() > xmax or y.max() > ymax:
            xmax = max(xmax, x.max() * 1.1)
            ymax = max(ymax, y.max() * 1.1)
        
        xi, yi = np.mgrid[xmin:xmax:200j, ymin:ymax:200j]
        zi = kde(np.vstack([xi.flatten(), yi.flatten()]))
        zi = zi.reshape(xi.shape)
        
        # Apply Gaussian blur for smoother gradients
        zi = ndimage.gaussian_filter(zi, sigma=2)
        
        # Plot the KDE heatmap
        im = ax.pcolormesh(xi, yi, zi, shading='gouraud', cmap=cmap, alpha=0.7)
        
        # Also scatter the actual points (semi-transparent)
        ax.scatter(x, y, c='white', s=20, alpha=0.3, edgecolors='none')
        
    except np.linalg.LinAlgError:
        # Fallback to histogram if KDE fails (e.g., colinear points)
        print(f"[WARNING] KDE failed, falling back to histogram")
        ax.hist2d(x, y, bins=30, cmap=cmap, alpha=0.7)
    
    # Style the plot
    ax.set_xlim(0, map_size[0])
    ax.set_ylim(0, map_size[1])
    ax.set_aspect('equal')
    ax.axis('off')  # No axes for clean overlay
    
    # Save with transparency
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    if output_name:
        filename = f"{output_name}.png"
    else:
        filename = "heatmap_deaths.png"
    
    output_path = os.path.join(OUTPUT_DIR, filename)
    plt.savefig(output_path, transparent=True, bbox_inches='tight', pad_inches=0, dpi=150)
    plt.close()
    
    print(f"[SUCCESS] Heatmap saved to {output_path}")
    return output_path


def generate_zone_heatmaps(map_size=(1000, 1000)):
    """Generate per-zone death heatmaps."""
    zones = fetch_mapzones()
    if not zones:
        print("[WARNING] No map zones found in database")
        return

    for zone in zones:
        area_code = zone.get('area_code')
        area_name = zone.get('zone_name') or zone.get('area_name') or f'zone_{area_code}'
        coords = fetch_deaths(area_code=area_code)
        if coords and len(coords) >= 2:
            zone_size = (zone['x_max'] - zone['x_min'], zone['y_max'] - zone['y_min'])
            # Normalize coordinates relative to zone bounds
            normalized = [(c[0] - zone['x_min'], c[1] - zone['y_min']) for c in coords]
            generate_kde_heatmap(
                normalized,
                map_size=zone_size,
                output_name=f"heatmap_zone_{area_code}_{area_name.lower().replace(' ', '_')}",
                title=f"Deaths in {area_name}"
            )
        else:
            print(f"[INFO] No death data for zone {area_name} (code={area_code})")


def generate_death_cause_chart(area_code=None):
    """Generate a bar chart of death causes."""
    causes = fetch_death_causes(area_code=area_code)
    if not causes:
        print("[WARNING] No death cause data found")
        return None
    
    labels = [c[0] for c in causes]
    counts = [c[1] for c in causes]
    
    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.barh(labels, counts, color='crimson', alpha=0.8)
    ax.set_xlabel('Count')
    ax.set_title('Death Causes' + (f' (Zone {area_code})' if area_code else ''))
    ax.invert_yaxis()
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    suffix = f"_zone_{area_code}" if area_code else ""
    output_path = os.path.join(OUTPUT_DIR, f"death_causes{suffix}.png")
    plt.savefig(output_path, bbox_inches='tight', dpi=150)
    plt.close()
    
    print(f"[SUCCESS] Death cause chart saved to {output_path}")
    return output_path


def fetch_events(event_type=None, area_code=None, session_id=None):
    """Fetch player event coordinates, optionally filtered."""
    db = connect_db()
    if db is None:
        return []

    try:
        query = {'x': {'$ne': None}, 'y': {'$ne': None}}
        if event_type is not None:
            query['event_type'] = event_type
        if area_code is not None:
            query['area_code'] = int(area_code)
        if session_id is not None:
            query['session_id'] = int(session_id)

        events = db.events.find(query, {'x': 1, 'y': 1, '_id': 0})
        data = [(float(e['x']), float(e['y'])) for e in events if e.get('x') is not None and e.get('y') is not None]
        return data
    except Exception as e:
        print(f"[ERROR] Fetching events: {e}")
        return []


def fetch_event_types():
    """Fetch distinct event types from player events."""
    db = connect_db()
    if db is None:
        return []

    try:
        types = db.events.distinct('event_type')
        return sorted([t for t in types if t is not None])
    except Exception as e:
        print(f"[ERROR] Fetching event types: {e}")
        return []


def get_stats():
    """Print statistics about collected data."""
    db = connect_db()
    if db is None:
        return

    try:
        print("\n" + "=" * 50)
        print("  TELEMETRY STATISTICS")
        print("=" * 50)

        # Total deaths
        total_deaths = db.deaths.count_documents({})
        print(f"Total Deaths: {total_deaths}")

        # Deaths by cause
        cause_pipeline = [
            {'$group': {'_id': '$cause', 'count': {'$sum': 1}}},
            {'$sort': {'count': -1}}
        ]
        causes = list(db.deaths.aggregate(cause_pipeline))
        print("\nDeaths by Cause:")
        for c in causes:
            cause_name = c['_id'] if c['_id'] else 'Unknown'
            print(f"  {cause_name}: {c['count']}")

        # Deaths by zone (area_code)
        zone_pipeline = [
            {'$group': {'_id': '$area_code', 'count': {'$sum': 1}}},
            {'$sort': {'count': -1}}
        ]
        zones = list(db.deaths.aggregate(zone_pipeline))
        print("\nDeaths by Zone:")
        for z in zones:
            zone_name = f"Zone {z['_id']}" if z['_id'] is not None else 'Unknown'
            zone_doc = db.mapzones.find_one({'area_code': z['_id']})
            if zone_doc:
                zone_name = zone_doc.get('zone_name', zone_name)
            print(f"  {zone_name}: {z['count']}")

        # Total player events
        total_events = db.events.count_documents({})
        print(f"\nTotal Player Events: {total_events}")

        # Events by type
        event_pipeline = [
            {'$group': {'_id': '$event_type', 'count': {'$sum': 1}}},
            {'$sort': {'count': -1}}
        ]
        event_types = list(db.events.aggregate(event_pipeline))
        print("\nEvents by Type:")
        for et in event_types:
            print(f"  {et['_id']}: {et['count']}")

        # Sessions
        total_sessions = db.sessions.count_documents({})
        print(f"\nTotal Sessions: {total_sessions}")

        # Players
        total_players = db.players.count_documents({})
        print(f"Total Players: {total_players}")

        print("=" * 50 + "\n")

    except Exception as e:
        print(f"[ERROR] Getting stats: {e}")


def main():
    parser = argparse.ArgumentParser(description='Generate telemetry heatmaps')
    parser.add_argument('--all', '-a', action='store_true', help='Generate all heatmaps (deaths + events + per-zone)')
    parser.add_argument('--zone', '-z', type=int, help='Generate heatmap for a specific zone (area_code)')
    parser.add_argument('--zones', action='store_true', help='Generate per-zone death heatmaps')
    parser.add_argument('--causes', '-c', action='store_true', help='Generate death cause chart')
    parser.add_argument('--event', '-e', type=str, help='Generate heatmap for a specific event type from playerevent')
    parser.add_argument('--events', action='store_true', help='Generate heatmaps for all event types')
    parser.add_argument('--stats', '-s', action='store_true', help='Show statistics')
    parser.add_argument('--width', type=int, default=1000, help='Map width')
    parser.add_argument('--height', type=int, default=1000, help='Map height')
    
    args = parser.parse_args()
    map_size = (args.width, args.height)
    
    print("\n" + "=" * 50)
    print("  HEATMAP GENERATOR - Visualizing Telemetry")
    print("=" * 50 + "\n")
    
    if args.stats:
        get_stats()
        return
    
    if args.causes:
        generate_death_cause_chart(area_code=args.zone)
        return
    
    if args.event:
        coords = fetch_events(event_type=args.event)
        generate_kde_heatmap(coords, map_size,
                             output_name=f"heatmap_event_{args.event.lower()}",
                             title=f"Event: {args.event}", cmap='Blues')
        return
    
    if args.events:
        event_types = fetch_event_types()
        if not event_types:
            print("[INFO] No player events found.")
        for et in event_types:
            coords = fetch_events(event_type=et)
            if coords and len(coords) >= 2:
                generate_kde_heatmap(coords, map_size,
                                     output_name=f"heatmap_event_{et.lower()}",
                                     title=f"Event: {et}", cmap='Blues')
        return
    
    if args.zone is not None:
        coords = fetch_deaths(area_code=args.zone)
        generate_kde_heatmap(coords, map_size, output_name=f"heatmap_zone_{args.zone}",
                             title=f"Deaths in Zone {args.zone}")
        return
    
    if args.zones:
        generate_zone_heatmaps(map_size)
        return
    
    if args.all:
        # Global death heatmap
        coords = fetch_deaths()
        if coords:
            generate_kde_heatmap(coords, map_size)
        # Per-zone heatmaps
        generate_zone_heatmaps(map_size)
        # Death cause chart
        generate_death_cause_chart()
        # All event type heatmaps
        event_types = fetch_event_types()
        for et in event_types:
            coords = fetch_events(event_type=et)
            if coords and len(coords) >= 2:
                generate_kde_heatmap(coords, map_size,
                                     output_name=f"heatmap_event_{et.lower()}",
                                     title=f"Event: {et}", cmap='Blues')
        return
    
    # Default: Generate global death heatmap
    print("Generating death heatmap (use --help for more options)...")
    coords = fetch_deaths()
    if coords:
        generate_kde_heatmap(coords, map_size)
    else:
        print("[INFO] No death events found. Play the game first!")


if __name__ == "__main__":
    main()
