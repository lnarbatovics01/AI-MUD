import random
import time
import threading
import sqlite3
import json
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from collections import Counter

app = Flask(__name__)
app.config['SECRET_KEY'] = 'incarnadine_secret'
socketio = SocketIO(app)

DB_PATH = "players.db"


# --- 1. DATABASE UPDATES ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Added password_hash column
    c.execute('''CREATE TABLE IF NOT EXISTS players
                 (username TEXT PRIMARY KEY, password_hash TEXT, location TEXT, 
                  level INTEGER, xp INTEGER, gold INTEGER, attunement INTEGER, 
                  hardiness INTEGER, wit INTEGER, current_hp INTEGER, equipped TEXT, inventory TEXT)''')
    conn.commit()
    conn.close()


def save_player(p, password=None):
    """
    Saves player. If a password is provided (on creation), it hashes it.
    Otherwise, it keeps the existing hash.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    inv_json = json.dumps(p['inventory'])

    if password:
        p['password_hash'] = generate_password_hash(password)

    c.execute('''INSERT OR REPLACE INTO players VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
              (p['name'], p['password_hash'], p['location'], p['level'], p['xp'], p['gold'],
               p['stats']['Attunement'], p['stats']['Hardiness'], p['stats']['Wit'],
               p['current_hp'], p['equipped'], inv_json))
    conn.commit()
    conn.close()


def load_player_data(username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM players WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "name": row[0], "password_hash": row[1], "location": row[2],
            "level": row[3], "xp": row[4], "gold": row[5],
            "stats": {"Attunement": row[6], "Hardiness": row[7], "Wit": row[8]},
            "current_hp": row[9], "equipped": row[10], "inventory": json.loads(row[11]), "is_in_combat": False
        }
    return None

def get_leaderboard(limit=10):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Sort by XP descending so the highest earners are at the top
    c.execute("SELECT username, level, xp, gold FROM players ORDER BY xp DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows


init_db()

# --- 1. DATABASES ---
ITEMS = {
    # --- CONSUMABLES ---
    "potion": {"name": "Red Potion", "type": "potion", "price": 20, "effect": "heal", "value": 30, "desc": "A bubbling crimson liquid. Heals 30 HP."},
    "elixir": {"name": "Luminous Elixir", "type": "potion", "price": 50, "effect": "heal", "value": 100, "desc": "Smells like ozone. Heals 100 HP."},
    "stale_bread": {"name": "Stale Bread", "type": "food", "price": 2, "effect": "heal", "value": 5, "desc": "Hard enough to use as a weapon, but edible. Heals 5 HP."},

    # --- WEAPONS / GEAR ---
    "ladle": {"name": "Plastic Ladle", "type": "weapon", "damage": 1, "weight": 1, "price": 5, "value": 1,
              "desc": "How could this get worse as a weapon?"},
    "spoon": {"name": "Wooden Spoon", "type": "weapon", "damage": 2, "weight": 1, "price": 10, "value": 2,
                    "desc": "What are you going to stir me to death?"},
    "rusty_sword": {"name": "Rusty Sword", "type": "weapon", "damage": 3, "weight": 4, "price": 15, "value": 5, "desc": "Better than your fists, barely."},
    "sword": {"name": "Iron Longsword", "type": "weapon", "damage": 15, "weight": 5, "price": 50, "value": 10, "desc": "Its a crappy iron sword"},
    "broadsword": {"name": "Heavy Broadsword", "type": "weapon", "damage": 25, "weight": 8, "price": 150, "value": 75, "desc": "A double-edged blade with a leather-wrapped hilt."},

    # --- MATERIALS & QUEST ITEMS ---
    "iron_ingot": {"name": "Iron Ingot", "type": "material", "price": 40, "effect": None, "value": 20, "desc": "A heavy block of metal. Could be used for crafting."},
    "iron_key": {"name": "Iron Key", "type": "quest", "price": 0, "effect": "unlock", "value": 0, "desc": "A heavy, skeleton-style key from the Foyer."},
    "the_crown": {"name": "The Diamond Crown", "type": "quest", "price": 10000, "effect": "win", "value": 0, "desc": "The ultimate symbol of the Castle's master."},

    # --- ATTUNEMENT ITEMS ---
    "crystal": {"name": "Prismatic Crystal", "type": "potion", "price": 100, "effect": "boost", "value": 2, "desc": "Used to increase your magical attunement (+2)."},
    "chronoshard": {"name": "Chronoshard", "type": "potion", "price": 500, "effect": "boost", "value": 10, "desc": "A fragment of a broken timeline. +10 Attunement."},

    # --- FLAVOR / TRASH ---
    "ever-ice": {"name": "Ever-Ice brand drink", "type": "flavor", "price": 10, "effect": None,
                      "value": 2,
                      "desc": "Ever-Ice, Deep Freeze Cool in every bottle. BEWARE: Do not drink unless your a Snowclaw."},
    "eternal_watch": {"name": "The Time Piece for fit for an Eternal", "type": "flavor", "price": 1000, "effect": None, "value": 250,
                      "desc": "Pretty awesome watch, to bad you cant do anything with it but I bet its worth alot of money!!"},
    "broken_bottle": {"name": "Broken brown beer bottle", "type": "flavor", "price": 2, "effect": None, "value": 0,
                     "desc": "Dont look to hard you'll poke your eye out."},
    "lump_of_coal": {"name": "Lump of Coal", "type": "flavor", "price": 2, "effect": None, "value": 0,
                      "desc": "Really no value unless your cold, probably just put it back."},
    "porcelain_cup": {"name": "Victorian era cup", "type": "flavor", "price": 2, "effect": None, "value": 0,
                    "desc": "Just and old cup, its empty."},
    "sheet_music": {"name": "Old page of sheet music", "type": "flavor", "price": 2, "effect": None, "value": 0,
                  "desc": "It contains half a poem, I thought I saw the first half somewhere."},
    "old_map": {"name": "Old Map", "type": "flavor", "price": 5, "effect": None, "value": 0, "desc": "Smudged and unreadable."},
    "parchment": {"name": "Scrap of Parchment", "type": "flavor", "price": 2, "effect": None, "value": 0, "desc": "It contains half a poem."},
    "game_token": {"name": "Arcade Token", "type": "flavor", "price": 5, "effect": None, "value": 0, "desc": "Good for one game of Galaga... if the power was on."},
    "void_dust": {"name": "Void Dust", "type": "flavor", "price": 25, "effect": None, "value": 0, "desc": "It slips through your fingers."},
    "empty_vial": {"name": "Empty Vial", "type": "flavor", "price": 5, "effect": None, "value": 0,
                  "desc": "Just a useless piece of glass."}

}

SPELLS = {
    "fireball": {"cost": 10, "dmg_mult": 2.5, "desc": "High damage attack (10 HP)."},
    "mend": {"cost": 15, "heal": 35, "desc": "Heal mid-battle (15 HP)."},
    "blur": {"cost": 8, "buff": "wit", "value": 15, "desc": "Boost escape chance (8 HP)."}
}



# --- 2. THE EXPANDED WORLD (144,000-ish Doors) ---
WORLD = {
    # --- REGION 1: THE CORE CASTLE ---
    "1": {
        "name": "The Grand Foyer",
        "desc": "The heart of the Castle. Phil sits at his card table outside his shop.",
        "portals": {
            "2": {"name": "The Library", "min_attunement": 0},
            "3": {"name": "The Kitchen", "min_attunement": 0},
            "4": {"name": "The Battlements", "min_attunement": 0},
            "8": {"name": "The Lab", "min_attunement": 0},
            "12": {"name": "The Music Room", "min_attunement": 0},
            "15": {"name": "The Armory", "min_attunement": 0}
        },
        "has_shop": True,
        "is_safe": True,
        "items": [],
        "monsters": [
            {"name": "Castle Guard", "hp": 60, "max_hp": 60, "atk": 10, "xp": 40, "gold": 15, "loot": "iron_key", "is_aggro": False, "is_roaming": True, "dead_until": 0}
        ]
    },
    "2": {
        "name": "The Library of Whispers",
        "desc": "Infinite shelves of gossip. Ozone fills the air.",
        "portals": {
            "1": {"name": "The Foyer", "min_attunement": 0},
            "16": {"name": "Restricted Section", "min_attunement": 5},
            "666": {"name": "The Void", "min_attunement": 20}
        },
        "items": ["parchment"],
        "monsters": [
            {"name": "Paper Golem", "hp": 50, "max_hp": 50, "atk": 8, "xp": 60, "gold": 15, "loot": "potion", "is_aggro": False, "is_roaming": False, "dead_until": 0},
            {"name": "Ink Sprite", "hp": 20, "max_hp": 20, "atk": 5, "xp": 25, "gold": 5, "loot": "void_dust", "is_aggro": True, "is_roaming": True, "dead_until": 0}
        ]
    },
    "3": {
        "name": "The Great Kitchens",
        "desc": "Gnomes and steam-powered spits. Smells like roasted phoenix.",
        "portals": {
            "1": {"name": "The Foyer", "min_attunement": 0},
            "20": {"name": "The Cellar", "min_attunement": 0}
        },
        "items": ["ladle"],
        "monsters": [
            {"name": "Kitchen Scullion", "hp": 40, "max_hp": 40, "atk": 7, "xp": 40, "gold": 10, "loot": "potion", "is_aggro": True, "is_roaming": False, "dead_until": 0}
        ]
    },
    "4": {
        "name": "The Outer Battlements",
        "desc": "Cold wind and a view of 144,000 horizons.",
        "portals": {
            "1": {"name": "The Foyer", "min_attunement": 0},
            "7": {"name": "Primeval World", "min_attunement": 10},
            "21": {"name": "Clockwork Tower", "min_attunement": 5}
        },
        "items": [],
        "monsters": [
            {"name": "Castle Gargoyle", "hp": 90, "max_hp": 90, "atk": 18, "xp": 150, "gold": 45, "loot": "crystal", "is_aggro": True, "is_roaming": False, "dead_until": 0},
            {"name": "Castle Guard", "hp": 60, "max_hp": 60, "atk": 10, "xp": 40, "gold": 15, "loot": "iron_key", "is_aggro": False, "is_roaming": True, "dead_until": 0}
        ]
    },

    # --- REGION 2: THE ARCANE WING ---
    "8": {
        "name": "The Alchemical Laboratory",
        "desc": "Beakers bubble without heat. Smells of cloves.",
        "portals": {
            "1": {"name": "The Foyer", "min_attunement": 0},
            "9": {"name": "Crystal Garden", "min_attunement": 2},
            "22": {"name": "Hall of Mirrors", "min_attunement": 5}
        },
        "items": ["empty_vial"],
        "monsters": [
            {"name": "Homunculus", "hp": 70, "max_hp": 70, "atk": 12, "xp": 90, "gold": 30, "loot": "elixir", "is_aggro": False, "is_roaming": False, "dead_until": 0}
        ]
    },
    "9": {
        "name": "The Crystal Garden",
        "desc": "Flora made of prismatic glass.",
        "portals": {
            "8": {"name": "The Lab", "min_attunement": 0},
            "23": {"name": "Gravity Well", "min_attunement": 15}
        },
        "items": [],
        "monsters": [
            {"name": "Glass Spider", "hp": 110, "max_hp": 110, "atk": 22, "xp": 180, "gold": 60, "loot": "crystal", "is_aggro": True, "is_roaming": False, "dead_until": 0}
        ]
    },
    "15": {
        "name": "The Armory of Ages",
        "desc": "Suits of armor stand in silent vigil.",
        "portals": {
            "1": {"name": "The Foyer", "min_attunement": 0},
            "24": {"name": "The Observatory", "min_attunement": 8}
        },
        "items": ["rusty_sword"],
        "monsters": [
            {"name": "Animated Plate", "hp": 120, "max_hp": 120, "atk": 25, "xp": 200, "gold": 50, "loot": "potion", "is_aggro": True, "is_roaming": False, "dead_until": 0}
        ]
    },
    "16": {
        "name": "The Restricted Section",
        "desc": "Books here are chained to the walls because they bite.",
        "portals": {
            "2": {"name": "The Library", "min_attunement": 0},
        },
        "items": [],
        "monsters": [
            {"name": "Book Wyrm", "hp": 60, "max_hp": 60, "atk": 14, "xp": 100, "gold": 25, "loot": "potion",
             "is_aggro": True, "is_roaming": False, "dead_until": 0}
        ]
    },

# --- REGION 3: EARTH ECHOES (Low Magic, High Nostalgia) ---
    "12": {
        "name": "The Music Room",
        "desc": "A piano plays itself. The notes are visible sparks.",
        "portals": {
            "1": {"name": "The Foyer", "min_attunement": 0},
            "13": {"name": "Victorian Parlour", "min_attunement": 0},
            "1984": {"name": "The Arcade", "min_attunement": 0}
        },
        "items": ["sheet_music"],
        "monsters": []
    },
    "13": {
        "name": "The Victorian Parlor",
        "desc": "Dusty tea sets and velvet chairs. A grandfather clock ticks backward.",
        "portals": {
            "12": {"name": "The Music Room", "min_attunement": 0},
            "14": {"name": "The Fog of London", "min_attunement": 0}
        },
        "items": ["porcelain_cup"],
        "monsters": []
    },
    "14": {
        "name": "London - 1888",
        "desc": "Fog so thick you can taste the coal smoke. A gaslight flickers.",
        "portals": {
            "13": {"name": "The Parlor", "min_attunement": 0}
        },
        "items": ["lump_of_coal"],
        "monsters": [
            {
                "name": "Street Urchin",
                "hp": 25, "max_hp": 25, "atk": 5,
                "xp": 20, "gold": 2, "loot": "potion",
                "is_aggro": False,
                "is_roaming": True, # Urchins wander around!
                "dead_until": 0
            }
        ]
    },
    "1984": {
        "name": "The Neon Arcade",
        "desc": "Smells like stale popcorn and ozone. Pac-man beeps eternally.",
        "portals": {
            "12": {"name": "The Music Room", "min_attunement": 0},
            "25": {"name": "Dive Bar", "min_attunement": 0}
        },
        "items": ["game_token"],
        "monsters": [],
        "can_rest": True
    },
    "25": {
        "name": "New York - The Dive Bar",
        "desc": "The Rusty Anchor. A jukebox plays 'True' by Spandau Ballet.",
        "portals": {
            "1984": {"name": "The Arcade", "min_attunement": 0}
        },
        "items": ["broken_bottle"],
        "monsters": [
            {
                "name": "Drunk Brawler",
                "hp": 55, "max_hp": 55, "atk": 10,
                "xp": 70, "gold": 12, "loot": "potion",
                "is_aggro": True,
                "is_roaming": False, # Brawlers usually stay at the bar
                "dead_until": 0
            }
        ]
    },

"7": {
        "name": "The Primeval World",
        "desc": "Portal 7 leads to a humid jungle. Dinosaurs rule here.",
        "portals": {
            "4": {"name": "The Outer Battlements", "min_attunement": 0},
            "26": {"name": "Tar Pits", "min_attunement": 0}
        },
        "items": [],
        "monsters": [
            {
                "name": "Allosaurus", "hp": 300, "max_hp": 300, "atk": 45,
                "xp": 700, "gold": 200, "loot": "crystal",
                "is_aggro": True, "is_roaming": True, "dead_until": 0
            }
        ]
    },
    "26": {
        "name": "The Tar Pits",
        "desc": "A sticky, bubbling landscape. Skeletal remains poke out of the black goo.",
        "portals": {"7": {"name": "Primeval World", "min_attunement": 0}},
        "items": [],
        "monsters": [
            {
                "name": "Tar Elemental", "hp": 150, "max_hp": 150, "atk": 20,
                "xp": 250, "gold": 40, "loot": "elixir",
                "is_aggro": True, "is_roaming": False, "dead_until": 0
            }
        ]
    },
    "20": {
        "name": "The Wine Cellar",
        "desc": "Vast tuns of wine that could drown a giant. Deeply dark.",
        "portals": {
            "3": {"name": "The Kitchen", "min_attunement": 0},
            "27": {"name": "Dark Catacombs", "min_attunement": 0}
        },
        "items": [],
        "monsters": [
            {
                "name": "Giant Spider", "hp": 45, "max_hp": 45, "atk": 9,
                "xp": 50, "gold": 5, "loot": "potion",
                "is_aggro": True, "is_roaming": False, "dead_until": 0
            }
        ]
    },
    "27": {
        "name": "The Catacombs",
        "desc": "The bones of former Guests form the architecture here.",
        "portals": {
            "20": {"name": "The Cellar", "min_attunement": 0},
            "28": {"name": "Frozen Waste", "min_attunement": 0}
        },
        "items": [],
        "monsters": [
            {
                "name": "Skeletal Guest", "hp": 80, "max_hp": 80, "atk": 15,
                "xp": 120, "gold": 30, "loot": "crystal",
                "is_aggro": True, "is_roaming": True, "dead_until": 0
            }
        ]
    },

    # --- REGION 5: THE OUTER REALMS (Extreme Difficulty) ---
    "666": {
        "name": "The Void",
        "desc": "Gravity is a suggestion.",
        "portals": {
            "2": {"name": "The Library", "min_attunement": 0},
            "667": {"name": "Edge of Forever", "min_attunement": 50}
        },
        "items": [],
        "monsters": [
            {"name": "Chaos Beast", "hp": 250, "max_hp": 250, "atk": 35, "xp": 500, "gold": 120, "loot": "crystal", "is_aggro": True, "is_roaming": True, "dead_until": 0}
        ]
    },
    "667": {
        "name": "The Edge of Forever",
        "desc": "A platform of white light overlooking the end of time. The silence is deafening.",
        "portals": {
            "666": {"name": "The Void", "min_attunement": 0},
            "999": {"name": "The Throne Room", "min_attunement": 75}
        },
        "items": ["void_dust", "chronoshard"],
        "monsters": [
            {
                "name": "Time Warden",
                "hp": 400, "max_hp": 400, "atk": 55,
                "xp": 1000, "gold": 500,
                "loot": "eternal_watch",
                "is_aggro": True,
                "is_roaming": False, # Wardens guard the gate
                "dead_until": 0
            }
        ]
    },
    "999": {
        "name": "The Throne Room",
        "desc": "A massive seat carved from a single diamond.",
        "portals": {
            "667": {"name": "Edge of Forever", "min_attunement": 0}
        },
        "items": ["the_crown"],
        "monsters": [
            {"name": "Incarnadine Avatar", "hp": 1000, "max_hp": 1000, "atk": 80, "xp": 5000, "gold": 2000, "loot": "crystal", "is_aggro": False, "is_roaming": False, "dead_until": 0}
        ]
    },

    # --- ADDITIONAL ODDITIES ---
    "21": {
        "name": "The Clockwork Tower",
        "desc": "Gears the size of houses grind against each other.",
        "portals": {"4": {"name": "Outer Battlements", "min_attunement": 0}},
        "items": [],
        "monsters": [
            {"name": "Clockwork Soldier", "hp": 100, "max_hp": 100, "atk": 20, "xp": 180, "gold": 40, "loot": "potion", "is_aggro": True, "is_roaming": False, "dead_until": 0}
        ]
    },
    "22": {
        "name": "The Hall of Mirrors",
        "desc": "Every reflection shows a different version of you.",
        "portals": {"8": {"name": "The Lab", "min_attunement": 0}},
        "items": [],
        "monsters": [
            {"name": "Mirror Doppelganger", "hp": 90, "max_hp": 90, "atk": 18, "xp": 160, "gold": 35, "loot": "elixir", "is_aggro": True, "is_roaming": False, "dead_until": 0}
        ]
    },
    "23": {
        "name": "The Gravity Well",
        "desc": "You walk on the walls. The floor is the ceiling.",
        "portals": {"9": {"name": "Crystal Garden", "min_attunement": 0}},
        "items": [],
        "monsters": [
            {"name": "Void Manta", "hp": 130, "max_hp": 130, "atk": 28, "xp": 220, "gold": 70, "loot": "crystal", "is_aggro": True, "is_roaming": True, "dead_until": 0}
        ]
    },
    "24": {
        "name": "The Solar Observatory",
        "desc": "A lens focuses the light of a distant supernova onto a map.",
        "portals": {"15": {"name": "The Armory", "min_attunement": 0}},
        "items": [],
        "monsters": [
            {"name": "Solar Flare", "hp": 140, "max_hp": 140, "atk": 30, "xp": 240, "gold": 80, "loot": "crystal", "is_aggro": True, "is_roaming": False, "dead_until": 0}
        ]
    },
    "28": {
        "name": "The Frozen Waste",
        "desc": "An eternal blizzard. The air freezes in your lungs.",
        "portals": {"27": {"name": "Dark Catacombs", "min_attunement": 0}},
        "items": ["ever-ice"],
        "monsters": [
            {"name": "Frost Giant", "hp": 200, "max_hp": 200, "atk": 38, "xp": 350, "gold": 90, "loot": "potion", "is_aggro": True, "is_roaming": False, "dead_until": 0}
        ]
    }
}

players = {}


# --- 3. ENGINES (Combat, Leveling, Respawn) ---
def monster_respawn_tick():
    while True:
        time.sleep(5)
        now = time.time()
        for rid, data in WORLD.items():
            if data.get('dead_until') and now > data['dead_until']:
                data['dead_until'] = 0
                if data['monster']: data['monster']['hp'] = data['monster']['max_hp']

threading.Thread(target=monster_respawn_tick, daemon=True).start()

def move_monsters():
    while True:
        time.sleep(60)  # Wandering happens every 30 seconds

        # We iterate over a list of IDs to avoid "dictionary changed size during iteration"
        for rid in list(WORLD.keys()):
            room = WORLD[rid]

            if 'monsters' not in room or not room['monsters']:
                continue

            # Iterate backwards through the list so we can safely remove items while looping
            for i in range(len(room['monsters']) - 1, -1, -1):
                random_number = random.randint(1, 100)
                mob = room['monsters'][i]

                # --- 1. VALIDATION CHECKS ---
                # Is it a roamer?
                if not mob.get('is_roaming'):
                    continue

                if random_number < 90:
                    continue

                # Is it currently dead/respawning?
                if mob.get('dead_until', 0) > time.time():
                    continue

                # Is anyone currently fighting THIS specific monster?
                # We check if any player in the room has this monster's index as their target
                is_engaged = any(
                    p.get('combat_target') == i and p['location'] == rid
                    for p in players.values()
                )

                if is_engaged:
                    continue

                # --- 2. MOVEMENT LOGIC ---
                possible_destinations = list(room.get('portals', {}).keys())
                if not possible_destinations:
                    continue

                dest_id = random.choice(possible_destinations)
                dest_room = WORLD.get(dest_id)

                if not dest_room:
                    continue

                # Notify players in the current room
                socketio.emit('status', {'msg': f"🐾 <i>The {mob['name']} wanders away.</i>"}, room=rid)

                # Remove from current room, add to destination room list
                moving_mob = room['monsters'].pop(i)
                dest_room.setdefault('monsters', []).append(moving_mob)

                # Notify players in the new room
                socketio.emit('status', {'msg': f"🐾 <i>A {mob['name']} wanders in.</i>"}, room=dest_id)


# Start the thread at the bottom of your file (before socketio.run)
threading.Thread(target=move_monsters, daemon=True).start()

def combat_tick(sid):
    # Ensure the player still exists and has a target index
    while sid in players and players[sid].get('combat_target') is not None:
        p = players[sid]
        room = WORLD.get(p['location'])

        # 1. Get the specific monster from the room list
        target_idx = p['combat_target']
        monsters = room.get('monsters', [])

        # Validate target exists and is alive
        if target_idx >= len(monsters) or monsters[target_idx].get('dead_until', 0) > 0:
            p['combat_target'] = None
            break

        m = monsters[target_idx]

        # 2. Player's Turn: Calculate Damage
        # Math: Base (8-15) + Attunement scaling
        p_dmg = random.randint(8, 15) + (p['stats'].get('Attunement', 0) // 2)

        # Check equipped item for bonus damage
        if p.get('equipped') and p['equipped'] in ITEMS:
            p_dmg += ITEMS[p['equipped']].get('damage', 0)

        m['hp'] -= p_dmg
        socketio.emit('status', {
            'msg': f"⚔️ <b>Round:</b> Hit {m['name']} for {p_dmg}. (Foe HP: {max(0, m['hp'])})"
        }, room=sid)

        # 3. Check Monster Death
        if m['hp'] <= 0:
            m['dead_until'] = time.time() + m.get('respawn_delay', 30)
            m['hp'] = m['max_hp']  # Reset for next respawn

            p['xp'] += m['xp']
            p['gold'] += m['gold']

            # Add loot to room floor (new behavior) or direct to inventory
            room.setdefault('items', []).append(m['loot'])

            p['combat_target'] = None  # End combat

            socketio.emit('status', {
                'msg': f"<b style='color:#0f0;'>DEFEATED!</b> {m['name']} dropped {m['loot']} and {m['gold']} gold."
            }, room=sid)

            check_level_up(sid)
            break

        # 4. Monster's Turn: Retaliation
        # Math: Monster ATK - (Wit / 4) for damage mitigation
        m_dmg = max(2, m['atk'] - (p['stats'].get('Wit', 0) // 4))
        p['current_hp'] -= m_dmg

        socketio.emit('status', {
            'msg': f"💢 {m['name']} hits for {m_dmg}! (HP: {max(0, p['current_hp'])})"
        }, room=sid)

        # 5. Check Player Death
        if p['current_hp'] <= 0:
            p['combat_target'] = None
            p['location'] = "1"  # Respawn point
            p['current_hp'] = p['stats'].get('Hardiness', 100)
            socketio.emit('status', {
                'msg': "<h1 style='color:red;'>DE-MATERIALIZED!</h1> Respawned in Foyer."
            }, room=sid)
            send_room_desc(sid)  # Refresh the room view
            break

        time.sleep(3)  # Faster pace than 5s feels better for MUDs


def check_level_up(sid):
    p = players[sid]
    if p['xp'] >= p['level'] * 100:
        p['xp'] -= p['level'] * 100;
        p['level'] += 1
        p['stats']['Attunement'] += 5;
        p['stats']['Hardiness'] += 20;
        p['stats']['Wit'] += 3
        p['current_hp'] = p['stats']['Hardiness']
        socketio.emit('status', {'msg': "<h2 style='color:gold;'>★ LEVEL UP! ★</h2>"}, room=sid)


def send_room_desc(sid):
    p = players[sid]
    room_id = p['location']
    room = WORLD[room_id]

    # --- 1. Header & Description ---
    msg = f"<div style='border-bottom: 1px solid #444; margin-bottom: 8px;'>"
    msg += f"<b style='font-size: 1.25em; color: #FFD700;'>{room['name']}</b></div>"
    msg += f"<p style='color: #CCCCCC; line-height: 1.4;'>{room['desc']}</p>"

    # --- 2. Portals (Exits) ---
    if room.get("portals"):
        exit_list = []
        for target_id, info in room["portals"].items():
            # Check player attunement against portal requirement
            if p['stats']['Attunement'] >= info.get('min_attunement', 0):
                color = "#00BFFF"
                exit_list.append(f"<span style='color: {color};'>[{target_id}] {info['name']}</span>")
            else:
                exit_list.append(f"<span style='color: #555555;'>[Locked] ???</span>")
        msg += f"<p><b>Visible Exits:</b> {', '.join(exit_list)}</p>"

    # --- 3. Items on the Floor ---
    if room.get("items") and room.get("items") != [None]:
        readable_items = [i.replace('_', ' ').title() for i in room['items']]
        item_list = ", ".join([f"<span style='color: #00FF7F;'>{item}</span>" for item in readable_items])
        msg += f"<p style='margin: 10px 0;'><b>You see:</b> {item_list}</p>"

    # --- 4. Monsters & Aggro Check ---
    aggro_target_idx = None

    if room.get("monsters"):
        msg += "<div style='margin-top: 10px;'><b>Creatures:</b><ul style='margin-top: 5px; list-style-type: square;'>"

        for i, m in enumerate(room["monsters"]):
            # Only process living monsters
            if m.get("dead_until", 0) <= time.time():
                is_aggro = m.get("is_aggro", False)
                color = "#FF4500" if is_aggro else "#87CEEB"
                roam_text = " <small><i>(Roaming)</i></small>" if m.get("is_roaming") else ""
                msg += f"<li style='color: {color};'><b>{m['name']}</b>{roam_text}</li>"

                # AGGRO LOGIC: If the monster is aggro and we don't have a target yet
                if is_aggro and aggro_target_idx is None:
                    aggro_target_idx = i

        msg += "</ul></div>"

    # --- 5. Room Flags ---
    if room.get("has_shop"):
        msg += "<p style='color: #DAA520; font-weight: bold;'>[SHOP] Phil is here, ready to trade.</p>"

    # Send the room description first
    emit('status', {'msg': msg}, room=sid)

    # --- 6. Trigger Combat if Aggroed ---
    # We only auto-attack if the player isn't already in combat
    random_number = random.randint(1, 100)
    if aggro_target_idx is not None and p.get('combat_target') is None and not "Guest_" in p["name"] and not room.get("is_safe", None) and random_number > 50:
        p['combat_target'] = aggro_target_idx
        monster_name = room["monsters"][aggro_target_idx]['name']
        emit('status', {'msg': f"<b style='color: #FF0000;'>⚠️ The {monster_name} notices you and lunges at you!</b>"}, room=sid)
        socketio.start_background_task(combat_tick, sid)


# --- 4. SOCKETS ---
@app.route('/')
def index(): return render_template('index.html')


@socketio.on('connect')
def handle_connect():
    sid = request.sid
    players[sid] = {
        "name": f"Guest_{sid[:4]}", "location": "1", "level": 1, "xp": 0, "gold": 50,
        "stats": {"Attunement": 0, "Hardiness": 60, "Wit": 12},
        "current_hp": 60, "equipped": None, "inventory": [], "is_in_combat": False
    }
    emit('status', {'msg': "<b>Welcome, Guest.</b> The 144,000 doors await. Type 'help' for all commands."})
    send_room_desc(sid)


# @socketio.on('command')
# def handle_command(data):
#     sid = request.sid;
#     raw = data.get('msg', '').lower().strip();
#     cmd = raw.split()
#     if not cmd or sid not in players: return
#     p = players[sid];
#     room = WORLD[p['location']]
@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in players:
        p = players[sid]

        # 1. Save progress to DB one last time
        if "Guest_" not in p['name']:
            save_player(p)

        # 2. Notify others in the room
        departure_msg = f"<i>{p['name']} has faded into the mists of time (Logged out).</i>"
        emit('status', {'msg': departure_msg}, room=p['location'], include_self=False)

        # 3. Remove from active memory
        del players[sid]
        print(f"DEBUG: {p['name']} disconnected and saved.")


@socketio.on('command')
def handle_command(data):
    sid = request.sid
    raw = data.get('msg', '').strip()
    cmd = raw.split()
    p = players[sid]
    room = WORLD[p['location']]
    if not cmd: return

    # --- REWORKED LOGIN: login [name] [password] ---
    if cmd[0].lower() == "login":
        if len(cmd) < 3:
            emit('status', {'msg': "⚠️ Usage: <b>login [name] [password]</b>"})
            return

        name, password = cmd[1], cmd[2]
        existing_p = load_player_data(name)

        if existing_p:
            # Check if the password is correct
            if check_password_hash(existing_p['password_hash'], password):
                players[sid] = existing_p
                emit('status', {'msg': f"✅ Authenticated. Welcome back, <b>{name}</b>!"})
                send_room_desc(sid)
                p = players[sid];
                room = WORLD[p['location']]
            else:
                emit('status', {'msg': "❌ <span style='color:red;'>Incorrect password for this Guest.</span>"})
        elif "Guest_" in name:
            emit('status', {'msg': "❌ <span style='color:red;'>'Guest_' is not allowed in a registered username.</span>"})
        else:
            # Create new player
            new_p = {
                "name": name, "location": "1", "level": 1, "xp": 0, "gold": 50,
                "stats": {"Attunement": 0, "Hardiness": 60, "Wit": 12},
                "current_hp": 60, "equipped": None, "inventory": [], "is_in_combat": False
            }
            save_player(new_p, password=password)  # Hashes the password here
            players[sid] = load_player_data(name)  # Reload to get the hash into memory
            emit('status', {'msg': f"🌟 New Guest <b>{name}</b> registered and logged in!"})
            send_room_desc(sid)
            p = players[sid];
            room = WORLD[p['location']]
        return

    elif cmd[0] in ["quit", "exit"]:
        if p.get('is_in_combat'):
            emit('status', {'msg': "❌ You cannot quit while in combat! Fight or flee first!"})
            return
        else:
            sid = request.sid
            if sid in players:
                p = players[sid]
                emit('status', {'msg': f"<i>{p['name']} has phased out of existence.</i>"},
                     room=p['location'], include_self=False)
                del players[sid]



    elif cmd[0] == "help":
        help_msg = (
            "<div style='border: 1px dashed #d4af37; padding: 10px; margin: 10px 0;'>"
            "<b style='color: #d4af37;'>--- COMMANDS ---</b><br>"
            "<b>login [username] [password]:</b> Login to your hero.<br>"
            "<b>quit:</b> Leave these realms. <br>"
            "<b>look:</b> Scan the room.<br><b>stats:</b> View status.<br>"
            "<b>go [number]:</b> Enter a portal.<br><b>attack:</b> Fight monster.<br>"
            "<b>inv:</b> View items.<br><b>use [item]:</b> Use an item.<br>"
            "<b>attack:</b> attack the monster that might be near you.<br>"
            "<b>retreat:</b> I guess if your a coward you can do that.<br>"
            "<b>cast [spell]:</b> Cast a spell, current spells available are fireball/mend/blur.<br>"
            "<b>list:</b> List the items in a nearby shop.<br>"
            "<b>buy [item]:</b> Buy an item from the nearby shop.<br>"
            "<b>use [item}:</b> Use an item from your inventory.<br>"
            "<b>say [text]:</b> Chat with others in the room.<br>"
            "<b>shout [text]:</b> Chat with others in the server.<br>"
            "<b>who:</b> List others in the server.<br>"
            "<b>where [player name]:</b> Where is another player?.<br>"
            "<b>top:</b> List the top players on the server.<br>"
            "<b>wield [weapon]:</b> Wield your weapon.<br>"
            "<b>unwield:</b> Sheath your weapon.<br>"
            "<b>probe [item]:</b> What is this thing?.<br>"
            "<b>drop [item]:</b> Drop an item your inventory.<br>"
            "<b>pickup [item]:</b> Pickup an item from a room.<br>"
            "<b>give [player] [item]:</b> Give an item to another player."
            "</div>"
        )
        emit('status', {'msg': help_msg})
    # Restrict all other commands until logged in
    if "Guest_" in p["name"]:
        emit('status', {'msg': "Identify yourself. Use: <b>login [name] [password]</b>"})
        return
    else:

        if cmd[0] == "look":
            send_room_desc(sid)
        elif cmd[0].lower() == "who":
            # Start the header
            who_list = ["<br>--- <b>Current Guests in the Realm</b> ---"]

            # Iterate through all active player sessions
            for sid, other_p in players.items():
                room_name = WORLD.get(other_p['location'], {}).get('name', 'Unknown Void')

                # Format: [Level] Name - Location
                entry = (f"• <span style='color:#00d4ff;'>Lvl {other_p['level']}</span> "
                         f"<b>{other_p['name']}</b> - <i>{room_name}</i>")
                who_list.append(entry)

            # Add a footer with the total count
            who_list.append(f"--- <b>Total: {len(players)}</b> ---<br>")

            # Send only to the player who typed it
            emit('status', {'msg': "<br>".join(who_list)})
        elif cmd[0] in ["stats","whoami"]:
            emit('status',
                 {'msg': f"Name: {p['name']} | LVL: {p['level']} | HP: {p['current_hp']} | ATN: {p['stats']['Attunement']} | Gold: {p['gold']} | XP: {p['xp']} | Equipped: {p['equipped']}"})
        elif cmd[0] == "inv":
            msg = f"Inventory:"
            inv_items = p['inventory']
            if inv_items:
                counts = Counter(ITEMS[i]['name'] for i in inv_items)
                formatted = []
                for name, count in counts.items():
                    if count > 1:
                        formatted.append(f"{name} (x{count})")
                    else:
                        formatted.append(name)
                msg += f"<br>📦 <b>You see:</b> {', '.join(formatted)}<br>"
            emit('status', {'msg': msg})
        elif cmd[0] == "list":
            if room.get('has_shop'):
                emit('status', {'msg': "Phil's Items: potion (20g), crystal (100g), elixir (50), sword(50g), broadsword(150g), spoon(5g)"})
        elif cmd[0] == "buy" and len(cmd) > 1:
            item = cmd[1]
            if room.get('has_shop') and item in ITEMS and p['gold'] >= ITEMS[item]['price']:
                p['gold'] -= ITEMS[item]['price'];
                p['inventory'].append(item)
                emit('status', {'msg': f"Bought {item}."})
            else:
                emit('status', {'msg': f"Check your wallet, also are you sure there is a shop here?."})
        elif cmd[0] == "cast" and len(cmd) > 1:
            s = cmd[1]
            if s in SPELLS and p['current_hp'] > SPELLS[s]['cost']:
                p['current_hp'] -= SPELLS[s]['cost']
                if s == "fireball" and p['is_in_combat']:
                    dmg = int(p['stats']['Attunement'] * 2.5)
                    room['monster']['hp'] -= dmg
                    emit('status', {'msg': f"🔥 Fireball deals {dmg} damage!"})
                elif s == "mend":
                    p['current_hp'] = min(p['stats']['Hardiness'], p['current_hp'] + 35)
                    emit('status', {'msg': "✨ Mended wounds."})
        elif cmd[0] in ["go", "enter"]:
            if p['is_in_combat']:
                emit('status', {'msg': "You can't walk away while being attacked!"})
                return

            target = cmd[1] if len(cmd) > 1 else ""
            if target in room['portals']:
                gate = room['portals'][target]
                if p['stats']['Attunement'] >= gate['min_attunement']:
                    # Notify old room
                    emit('status', {'msg': f"<i>{p['name']} vanished through a portal.</i>"},
                         room=p['location'], include_self=False)
                    leave_room(p['location'])

                    # Move player
                    p['location'] = target
                    join_room(target)
                    save_player(p)

                    # Notify new room
                    emit('status', {'msg': f"<i>{p['name']} stepped out of the shadows.</i>"},
                         room=target, include_self=False)

                    send_room_desc(sid)
                else:
                    emit('status', {'msg': "The portal remains solid. You need more Attunement."})
            else:
                emit('status', {'msg': "Invalid portal number."})
        elif cmd[0] == "attack":
            room = WORLD[p['location']]
            monsters = room.get('monsters', [])

            # 1. Identify which monster to hit (optional name matching)
            target_query = " ".join(cmd[1:]).lower() if len(cmd) > 1 else None

            # Filter for monsters that are currently alive
            active_mobs = [(i, m) for i, m in enumerate(monsters) if m.get('dead_until', 0) == 0]

            if room.get("is_safe", None):
                emit('status', {'msg': "This is a safe area, no one is allowed to fight."}, room=sid)
                return

            if not active_mobs:
                emit('status', {'msg': "There is nothing here to attack."}, room=sid)
                return

            # 2. Selection Logic
            chosen_idx = None
            if target_query:
                for idx, m in active_mobs:
                    if target_query in m['name'].lower():
                        chosen_idx = idx
                        break
                if chosen_idx is None:
                    emit('status', {'msg': f"You don't see a '{target_query}' here."}, room=sid)
                    return
            else:
                # Default to the first living monster in the list
                chosen_idx = active_mobs[0][0]

            # 3. Check if the player is already fighting
            if p.get('combat_target') is not None:
                # If they are already fighting, we just update the target
                p['combat_target'] = chosen_idx
                emit('status', {'msg': f"You shift your focus to the <b>{monsters[chosen_idx]['name']}</b>!"},
                     room=sid)
            else:
                # Start a new combat thread
                p['combat_target'] = chosen_idx
                emit('status', {'msg': f"<b>You engage the {monsters[chosen_idx]['name']}!</b>"}, room=sid)
                socketio.start_background_task(combat_tick, sid)
        elif cmd[0] == "retreat":
            if p['is_in_combat']:
                # Success chance = 40% + Wit
                if random.randint(1, 100) <= (40 + p['stats']['Wit']):
                    p['is_in_combat'] = False
                    p['location'] = "1"
                    emit('status', {'msg': "<b style='color: #00ffff;'>You successfully escaped to the Foyer!</b>"})
                else:
                    m = room['monster']
                    p['current_hp'] -= m['atk']
                    emit('status', {
                        'msg': f"<b style='color: #ffaa00;'>Retreat failed!</b> {m['name']} catches you for {m['atk']} damage!"})
            else:
                emit('status', {'msg': "You aren't in combat."})
        elif cmd[0].lower() == "say":
            if len(cmd) < 2:
                emit('status', {'msg': "<i>Say what?</i>"})
                return

            # Extract everything after the word 'say' to keep spaces intact
            # raw is the full string from the user input
            message_content = raw.split(' ', 1)[1]

            # Format the message for the chat
            chat_msg = f"<b>{p['name']}</b> says: <span style='color:#f1c40f;'>\"{message_content}\"</span>"

            # Emit to everyone in the same location room
            emit('status', {'msg': chat_msg}, room=p['location'])
        elif cmd[0].lower() == "shout":
            if len(cmd) < 2:
                emit('status', {'msg': "<i>Your voice echoes, but you said nothing.</i>"})
                return

            message_content = raw.split(' ', 1)[1]
            shout_msg = f"📢 <b>{p['name']} shouts:</b> <span style='color:#e74c3c;'>{message_content.upper()}!!</span>"

            # Leaving out 'room' emits to every connected socket globally
            emit('status', {'msg': shout_msg}, broadcast=True)
        elif cmd[0] == "use" and len(cmd) > 1:
            item_id = cmd[1].lower()

            if item_id in p['inventory']:
                item_data = ITEMS.get(item_id)

                # 1. Handle Potions and Consumables
                if item_data["type"] == "potion" or item_data["type"] == "food":
                    effect = item_data.get("effect")
                    val = item_data.get("value", 0)

                    if effect == "heal":
                        # Uses 'Hardiness' as the max HP cap
                        p['current_hp'] = min(p['stats']['Hardiness'], p['current_hp'] + val)
                        emit('status', {'msg': f"🥤 You drink the {item_data['name']}. Healed for {val} HP!"}, room=sid)

                    elif effect == "boost":
                        p['stats']['Attunement'] += val
                        emit('status', {'msg': f"✨ The {item_data['name']} shatters! Attunement increased by {val}."},
                             room=sid)

                    elif effect == "wit_boost":
                        p['stats']['Wit'] += val
                        emit('status', {'msg': f"🧠 You drink the {item_data['name']}. Wit increased by {val}."},
                             room=sid)

                    # Remove item after successful use
                    p['inventory'].remove(item_id)

                # 2. Handle Weapons (Prevent "using" them like potions)
                elif item_data["type"] == "weapon":
                    emit('status', {'msg': "<i>You can't eat that. Try 'equip' instead!</i>"}, room=sid)

                # 3. Handle Quest/Flavor Items
                else:
                    emit('status', {'msg': f"You fiddle with the {item_data['name']}, but nothing happens."}, room=sid)
            else:
                emit('status', {'msg': "You aren't carrying that."}, room=sid)
        elif cmd[0].lower() == "where":
            if len(cmd) < 2:
                emit('status', {'msg': "<i>Usage: where [name]</i>"})
                return

            target_name = cmd[1].lower()
            found = False

            for sid, other_p in players.items():
                if other_p['name'].lower() == target_name:
                    room_name = WORLD[other_p['location']]['name']
                    emit('status', {'msg': f"📍 <b>{other_p['name']}</b> is currently in: <i>{room_name}</i>"})
                    found = True
                    break

            if not found:
                emit('status', {'msg': f"❌ Guest '{cmd[1]}' is not currently in this reality."})

        elif cmd[0].lower() in ["leaderboard", "top"]:

            top_players = get_leaderboard()

            if not top_players:
                emit('status', {'msg': "The history books are currently empty."})

                return

            # Build the entire message in one variable


            output = "🏆 --- <b>LEGENDS OF THE REALM</b> ---<br>"

            for i, (name, level, xp, gold) in enumerate(top_players, 1):
                medal = "🥇 " if i == 1 else "🥈 " if i == 2 else "🥉 " if i == 3 else f"{i}. "

                output += f"{medal}<b>{name}</b> - <span style='color:#f1c40f;'>Lvl {level}</span> ({xp} XP) | 💰 {gold}g<br>"

            output += "--------------------------------"

            # Send exactly once

            emit('status', {'msg': output})
        elif cmd[0].lower() == "clear":
            # We emit a special 'clear' event instead of a 'status' message
            emit('clear_screen')
        elif cmd[0].lower() in ["wield", "equip"]:
            if len(cmd) < 2:
                emit('status', {'msg': "<i>Wield what?</i>"})
                return

            item_name = " ".join(cmd[1:]).lower()

            # 1. Find the item in inventory
            item_to_wield = next((i for i in p['inventory'] if i.lower() == item_name), None)

            if not item_to_wield:
                emit('status', {'msg': f"You aren't carrying a '{item_name}'."})
                return

            if ITEMS[item_to_wield].get('type') != 'weapon':
                emit('status', {'msg': f"You can't effectively wield a {item_name} as a weapon."})
                return

            # 2. Equip the item
            p['equipped'] = item_to_wield
            save_player(p)

            emit('status', {
                'msg': f"⚔️ You are now wielding: <b>{ITEMS[item_to_wield]['name']}</b> (Bonus: +{ITEMS[item_to_wield]['damage']} dmg)"})
            emit('status', {'msg': f"<i>{p['name']} draws a {ITEMS[item_to_wield]['name']}.</i>"}, room=p['location'],
                 include_self=False)
        elif cmd[0].lower() == "unwield":
            p['equipped'] = None
            emit('status', {'msg': "You sheath your weapon and prepare to use your fists."})

        elif cmd[0].lower() in ["inspect", "probe", "examine"]:
            if len(cmd) < 2:
                emit('status', {'msg': "<i>What do you want to inspect?</i>"})
                return

            item_name = " ".join(cmd[1:]).lower()
            room = WORLD[p['location']]

            # 1. Search Inventory first, then the room
            target_item = next((i for i in p['inventory'] if i.lower() == item_name), None)

            # Check if targeting a player instead of an item
            target_player = next((other for sid, other in players.items()
                                  if other['name'].lower() == item_name), None)

            if target_player:
                desc = f"👤 <b>{target_player['name']}</b> (Lvl {target_player['level']})<br>"
                desc += f"Status: {'In Combat' if target_player['is_in_combat'] else 'Idle'}"
                emit('status', {'msg': desc})
                return

            location_label = "Inventory"
            if not target_item:
                target_item = next((i for i in room.get('items', []) if i.lower() == item_name), None)
                location_label = "Room"
                target_item = ITEMS[target_item]
            else:
                target_item = ITEMS[target_item]

            if not target_item:
                emit('status', {'msg': f"You don't see a '{item_name}' here or in your pack."})
                return

            # 2. Build the inspection report
            res = [f"<br>🔎 <b>Inspecting: {target_item['name']}</b> ({location_label})"]
            res.append(f"<i>{target_item.get('desc', 'A mysterious object with no visible markings.')}</i>")
            res.append("----------------------------")

            # Dynamically show stats based on item type
            if 'damage' in target_item:
                res.append(f"⚔️ <b>Damage:</b> {target_item['damage']}")
            if 'armor' in target_item:
                res.append(f"🛡️ <b>Protection:</b> {target_item['armor']}")
            if 'weight' in target_item:
                res.append(f"⚖️ <b>Weight:</b> {target_item['weight']} lbs")
            if 'value' in target_item:
                res.append(f"💰 <b>Market Value:</b> {target_item['value']} gold")


            res.append("----------------------------<br>")

            emit('status', {'msg': "<br>".join(res)})

        elif cmd[0].lower() in ["get", "take", "pickup"]:
            if len(cmd) < 2:
                emit('status', {'msg': "<i>Take what?</i>"})
                return

            item_name = " ".join(cmd[1:]).lower()
            room = WORLD[p['location']]

            # 1. Find the item on the floor
            # We use a list comprehension to find the index so we can pop it out
            item_index = next((index for (index, d) in enumerate(room.get('items', []))
                               if d.lower() == item_name), None)

            if item_index is not None:
                # 2. Transfer item: Room -> Player
                item = room['items'].pop(item_index)
                p['inventory'].append(item)

                save_player(p)  # Save inventory state

                emit('status', {'msg': f"You picked up: <b>{item}</b>"})
                emit('status', {'msg': f"<i>{p['name']} picks up a {item}.</i>"},
                     room=p['location'], include_self=False)
            else:
                emit('status', {'msg': f"There is no '{item_name}' here."})
        elif cmd[0].lower() == "drop":
            if len(cmd) < 2:
                emit('status', {'msg': "<i>Drop what?</i>"})
                return

            item_name = " ".join(cmd[1:]).lower()

            # 1. Find item in player inventory
            item_index = next((index for (index, d) in enumerate(p['inventory'])
                               if d.lower() == item_name), None)

            if item_index is not None:
                # 2. Transfer item: Player -> Room
                item = p['inventory'].pop(item_index)

                # Ensure the room has an items list
                if 'items' not in WORLD[p['location']]:
                    WORLD[p['location']]['items'] = []

                WORLD[p['location']]['items'].append(item)

                # 3. Handle 'equipped' safety (If they drop what they are wielding)
                if p.get('equipped') and p['equipped'] == item_name:
                    p['equipped'] = None
                    emit('status', {'msg': "<i>(You unequipped the item before dropping it.)</i>"})

                save_player(p)

                emit('status', {'msg': f"You dropped: <b>{item}</b>"})
                emit('status', {'msg': f"<i>{p['name']} dropped a {item} on the floor.</i>"},
                     room=p['location'], include_self=False)
            else:
                emit('status', {'msg': f"You aren't carrying a '{item_name}'."})
        elif cmd[0].lower() == "give":
            if len(cmd) < 3:
                emit('status', {'msg': "<i>Usage: give [item] [player_name]</i>"})
                return

            # The last word is the target player name
            target_name = cmd[-1].lower()
            # Everything between 'give' and the target name is the item
            item_name = " ".join(cmd[1:-1]).lower()

            # 1. Find the target player in the current room
            target_sid = None
            target_p = None
            for sid, other_p in players.items():
                if other_p['name'].lower() == target_name and other_p['location'] == p['location']:
                    target_sid = sid
                    target_p = other_p
                    break

            if not target_p:
                emit('status', {'msg': f"❌ You don't see anyone named '{target_name}' here."})
                return

            # 2. Find the item in your inventory
            item_index = next((index for (index, d) in enumerate(p['inventory'])
                               if d.lower() == item_name), None)

            if item_index is None:
                emit('status', {'msg': f"You aren't carrying a '{item_name}'."})
                return

            # 3. Perform the transfer
            item = p['inventory'].pop(item_index)
            target_p['inventory'].append(item)

            # 4. Safety: If you were wielding it, unequip it
            if p.get('equipped') and p['equipped'] == ITEMS[item]['name']:
                p['equipped'] = None

            # 5. Save both players
            save_player(p)
            save_player(target_p)

            # 6. Notifications
            # To the Giver
            emit('status', {'msg': f"🎁 You gave the <b>{item['name']}</b> to <b>{target_p['name']}</b>."})

            # To the Receiver
            emit('status', {'msg': f"🎁 <b>{p['name']}</b> handed you a <b>{item['name']}</b>!"}, room=target_sid)

            # To the Room (Observers)
            emit('status', {'msg': f"<i>{p['name']} hands something to {target_p['name']}.</i>"},
                 room=p['location'], skip_sid=[request.sid, target_sid])
        elif cmd[0].lower() == "drop":
            if len(cmd) < 2:
                emit('status', {'msg': "<i>Drop what?</i>"})
                return

            item_name = " ".join(cmd[1:]).lower()

            # 1. Find item in player inventory
            item_index = next((index for (index, d) in enumerate(p['inventory'])
                               if d.lower() == item_name), None)

            if item_index is not None:
                # 2. Transfer item: Player -> Room
                item = p['inventory'].pop(item_index)

                # Ensure the room has an items list
                if 'items' not in WORLD[p['location']]:
                    WORLD[p['location']]['items'] = []

                WORLD[p['location']]['items'].append(item)

                # 3. Handle 'equipped' safety (If they drop what they are wielding)
                if p.get('equipped') and p['equipped'] == item_name:
                    p['equipped'] = None
                    emit('status', {'msg': "<i>(You unequipped the item before dropping it.)</i>"})

                save_player(p)

                emit('status', {'msg': f"You dropped: <b>{item}</b>"})
                emit('status', {'msg': f"<i>{p['name']} dropped a {item} on the floor.</i>"},
                     room=p['location'], include_self=False)
            else:
                emit('status', {'msg': f"You aren't carrying a '{item_name}'."})
        elif cmd[0].lower() == "junk":
            if len(cmd) < 2:
                emit('status', {'msg': "<i>Usage: junk [item]</i>"})
                return

            # Everything between 'junk' and the target name is the item
            item_name = " ".join(cmd[1:]).lower()

            # 2. Find the item in your inventory
            item_index = next((index for (index, d) in enumerate(p['inventory'])
                               if d.lower() == item_name), None)

            if item_index is None:
                emit('status', {'msg': f"You aren't carrying a '{item_name}'."})
                return

            # 3. Perform the transfer
            item = p['inventory'].pop(item_index)

            # 4. Safety: If you were wielding it, unequip it
            if p.get('equipped') and p['equipped'] == ITEMS[item]['name']:
                p['equipped'] = None

            # 5. Save the players
            save_player(p)

            # 6. Notifications
            # To the Giver
            emit('status', {'msg': f"🎁 You junk the <b>{ITEMS[item]['name']}</b>."})

            # To the Room (Observers)
            emit('status', {'msg': f"<i>{p['name']} tosses {ITEMS[item]['name']} into the trash.</i>"},
                 room=p['location'])
        else:
            emit('status', {'msg': "The command '{}' is not available at this time.".format(cmd[0])})

if __name__ == '__main__':
    socketio.run(app, debug=True, allow_unsafe_werkzeug=True, port=8000, host='0.0.0.0')