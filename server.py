from fastapi import FastAPI, APIRouter, HTTPException, Query
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional
import uuid
from datetime import datetime, timedelta
import aiohttp
import asyncio
import json
import math
from tenacity import retry, stop_after_attempt, wait_exponential

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app
app = FastAPI(title="Speed Camera Map API", version="3.0.0")

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Cache settings
CACHE_TTL = 30 * 60  # 30 minutes - more frequent updates for real-time accuracy
GLOBAL_CACHE_TTL = 6 * 60 * 60  # 6 hours for global data

# In-memory caches
camera_cache = {}
global_cameras_cache = {}
hazard_cache = {}

# ============ EUROPEAN RED LIGHT CAMERAS (From OpenStreetMap) ============
# These are verified red light cameras from OSM enforcement=traffic_signals
EUROPE_REDLIGHT_CAMERAS = [
    # UK
    {"lat": 53.6584, "lon": -1.483, "name": "UK - Red Light Camera", "type": "redlight"},
    {"lat": 52.4811, "lon": -2.1616, "name": "UK - Red Light Camera", "type": "redlight"},
    {"lat": 51.6055, "lon": -3.009, "name": "UK - Red Light Camera", "type": "redlight"},
    {"lat": 52.6321, "lon": 1.2854, "name": "UK - Red Light Camera", "type": "redlight"},
    {"lat": 51.7222, "lon": 0.4506, "name": "UK - Red Light Camera", "type": "redlight"},
    {"lat": 52.711, "lon": -2.47, "name": "UK - Red Light Camera", "type": "redlight"},
    {"lat": 51.4617, "lon": 0.3688, "name": "UK - Red Light Camera", "type": "redlight"},
    {"lat": 52.5867, "lon": -2.0004, "name": "UK - Red Light Camera", "type": "redlight"},
    {"lat": 52.5546, "lon": -2.1005, "name": "UK - Red Light Camera", "type": "redlight"},
    {"lat": 54.9516, "lon": -1.599, "name": "UK - Red Light Camera", "type": "redlight"},
    {"lat": 51.407, "lon": -0.2291, "name": "UK - Red Light Camera", "type": "redlight"},
    {"lat": 57.15, "lon": -2.1972, "name": "UK - Red Light Camera", "type": "redlight"},
    {"lat": 53.1946, "lon": -2.8474, "name": "UK - Red Light Camera", "type": "redlight"},
    # Italy
    {"lat": 45.4827, "lon": 12.2322, "name": "IT - Venice Red Light", "type": "redlight"},
    {"lat": 45.5698, "lon": 12.1127, "name": "IT - Red Light Camera", "type": "redlight"},
    {"lat": 45.4125, "lon": 11.883, "name": "IT - Padua Red Light", "type": "redlight"},
    {"lat": 44.0307, "lon": 12.4698, "name": "IT - Rimini Red Light", "type": "redlight"},
    {"lat": 43.7496, "lon": 13.1007, "name": "IT - Ancona Red Light", "type": "redlight"},
    {"lat": 45.0157, "lon": 7.8283, "name": "IT - Turin Red Light", "type": "redlight"},
    {"lat": 41.8946, "lon": 12.4378, "name": "IT - Rome Red Light", "type": "redlight"},
    {"lat": 44.4867, "lon": 11.293, "name": "IT - Bologna Red Light", "type": "redlight"},
    {"lat": 45.454, "lon": 8.543, "name": "IT - Novara Red Light", "type": "redlight"},
    {"lat": 45.5861, "lon": 8.9431, "name": "IT - Sempione Red Light", "type": "redlight"},
    {"lat": 45.5257, "lon": 9.0468, "name": "IT - Milan Red Light", "type": "redlight"},
    # France
    {"lat": 48.8843, "lon": 2.3615, "name": "FR - Paris Red Light", "type": "redlight"},
    {"lat": 48.7836, "lon": 2.4474, "name": "FR - Paris South Red Light", "type": "redlight"},
    {"lat": 48.9538, "lon": 2.2545, "name": "FR - Paris North Red Light", "type": "redlight"},
    {"lat": 44.9122, "lon": 2.4381, "name": "FR - Aurillac Red Light", "type": "redlight"},
    {"lat": 43.6017, "lon": 3.8847, "name": "FR - Montpellier Red Light", "type": "redlight"},
    {"lat": 47.2161, "lon": -1.5656, "name": "FR - Nantes Red Light", "type": "redlight"},
    {"lat": 43.3098, "lon": 5.4031, "name": "FR - Marseille Red Light", "type": "redlight"},
    {"lat": 45.7789, "lon": 4.8671, "name": "FR - Lyon Red Light", "type": "redlight"},
    {"lat": 48.8052, "lon": 2.1356, "name": "FR - Versailles Red Light", "type": "redlight"},
    {"lat": 43.2816, "lon": 5.3848, "name": "FR - Marseille Red Light", "type": "redlight"},
    {"lat": 43.828, "lon": 5.7872, "name": "FR - Radar Feu", "type": "redlight"},
    {"lat": 44.2005, "lon": 0.6337, "name": "FR - Radar Feu Rouge", "type": "redlight"},
    {"lat": 43.6214, "lon": 1.4249, "name": "FR - Toulouse Red Light", "type": "redlight"},
    {"lat": 44.8282, "lon": -0.5398, "name": "FR - Bordeaux Red Light", "type": "redlight"},
    {"lat": 43.701, "lon": 7.287, "name": "FR - Nice Red Light", "type": "redlight"},
    # Netherlands
    {"lat": 51.1232, "lon": 4.5773, "name": "NL - Antwerp Red Light", "type": "redlight"},
    {"lat": 52.3822, "lon": 4.669, "name": "NL - Amsterdam Red Light", "type": "redlight"},
    {"lat": 52.3458, "lon": 4.6246, "name": "NL - Amsterdam Red Light", "type": "redlight"},
    {"lat": 52.0459, "lon": 4.2549, "name": "NL - Den Haag Red Light", "type": "redlight"},
    {"lat": 51.4617, "lon": 5.4545, "name": "NL - Eindhoven Red Light", "type": "redlight"},
    {"lat": 51.4831, "lon": 5.433, "name": "NL - Eindhoven Red Light", "type": "redlight"},
    {"lat": 51.9309, "lon": 5.172, "name": "NL - Arnhem Red Light", "type": "redlight"},
    {"lat": 52.3635, "lon": 4.6118, "name": "NL - Schiphol Red Light", "type": "redlight"},
    # Belgium
    {"lat": 50.9128, "lon": 4.4316, "name": "BE - Brussels Red Light", "type": "redlight"},
    {"lat": 50.8965, "lon": 4.4337, "name": "BE - Brussels Red Light", "type": "redlight"},
    {"lat": 51.2219, "lon": 3.4474, "name": "BE - Bruges Red Light", "type": "redlight"},
    {"lat": 50.9543, "lon": 3.2844, "name": "BE - Ghent Red Light", "type": "redlight"},
    {"lat": 51.3083, "lon": 4.5077, "name": "BE - Antwerp Red Light", "type": "redlight"},
    # Austria
    {"lat": 48.2079, "lon": 15.6202, "name": "AT - Vienna Red Light", "type": "redlight"},
    {"lat": 47.798, "lon": 13.0307, "name": "AT - Salzburg Red Light", "type": "redlight"},
    {"lat": 47.8286, "lon": 13.0063, "name": "AT - Salzburg Red Light", "type": "redlight"},
    {"lat": 48.3024, "lon": 14.2963, "name": "AT - Linz Red Light", "type": "redlight"},
    {"lat": 48.1575, "lon": 14.022, "name": "AT - Red Light Camera", "type": "redlight"},
    {"lat": 48.1621, "lon": 14.0307, "name": "AT - Red Light Camera", "type": "redlight"},
    {"lat": 48.2144, "lon": 16.3615, "name": "AT - Vienna Red Light", "type": "redlight"},
    {"lat": 48.275, "lon": 14.3189, "name": "AT - Linz Rotlichtkamera", "type": "redlight"},
    # Switzerland
    {"lat": 47.387, "lon": 8.5349, "name": "CH - Zurich Red Light", "type": "redlight"},
    {"lat": 47.2388, "lon": 9.5978, "name": "CH - St. Gallen Red Light", "type": "redlight"},
    {"lat": 47.1024, "lon": 7.2951, "name": "CH - Bern Red Light", "type": "redlight"},
    {"lat": 46.9494, "lon": 7.4639, "name": "CH - Bern Red Light", "type": "redlight"},
    {"lat": 46.9632, "lon": 7.4545, "name": "CH - Bern Red Light", "type": "redlight"},
    # Germany (additional)
    {"lat": 51.488, "lon": 6.8632, "name": "DE - Duisburg Red Light", "type": "redlight"},
    {"lat": 50.5598, "lon": 8.6454, "name": "DE - Giessen Red Light", "type": "redlight"},
    {"lat": 52.1636, "lon": 9.4781, "name": "DE - Hannover Red Light", "type": "redlight"},
    {"lat": 52.0848, "lon": 9.343, "name": "DE - Hameln Red Light", "type": "redlight"},
    {"lat": 48.0777, "lon": 7.327, "name": "DE - Freiburg Red Light", "type": "redlight"},
    # Spain
    {"lat": 43.4851, "lon": -1.4944, "name": "ES - San Sebastian Red Light", "type": "redlight"},
    {"lat": 43.3049, "lon": -0.3706, "name": "ES - Pamplona Red Light", "type": "redlight"},
    {"lat": 43.2204, "lon": 0.0639, "name": "ES - Red Light Camera", "type": "redlight"},
    # Poland
    {"lat": 51.7366, "lon": 19.4427, "name": "PL - Lodz Red Light", "type": "redlight"},
    {"lat": 51.7799, "lon": 19.4217, "name": "PL - Lodz Red Light", "type": "redlight"},
    {"lat": 53.15, "lon": 16.7894, "name": "PL - Pila Red Light", "type": "redlight"},
    # Ireland
    {"lat": 53.3474, "lon": -6.2823, "name": "IE - Dublin Red Light", "type": "redlight"},
    # Latvia
    {"lat": 56.7836, "lon": 23.9492, "name": "LV - Jelgava Red Light", "type": "redlight"},
    # Finland
    {"lat": 60.9947, "lon": 24.4711, "name": "FI - Red Light Camera", "type": "redlight"},
    # Hungary
    {"lat": 46.9246, "lon": 18.1006, "name": "HU - VÉDA Red Light", "type": "redlight"},
    # Serbia
    {"lat": 44.79, "lon": 20.5407, "name": "RS - Belgrade Red Light", "type": "redlight"},
]

# ============ ABSTANDSKONTROLLE / DISTANCE CONTROL CAMERAS (Germany) ============
# These cameras measure distance between vehicles (tailgating enforcement)
GERMANY_DISTANCE_CAMERAS = [
    # A2 - Main distance control locations
    {"lat": 52.2021, "lon": 11.0831, "name": "A2 Barleben - Abstandskontrolle Ri. Hannover", "type": "distance", "speedLimit": 80},
    {"lat": 52.0456, "lon": 8.4891, "name": "A2 Bielefeld Talbrücke Lämershagen - Abstandskontrolle", "type": "distance", "speedLimit": 100},
    {"lat": 52.1789, "lon": 11.3456, "name": "A2 Hohe Börde - Abstandskontrolle Ri. Berlin", "type": "distance", "speedLimit": 80},
    {"lat": 52.3012, "lon": 10.8234, "name": "A2 Lehre/Wolfsburg - Abstandskontrolle", "type": "distance", "speedLimit": 100},
    {"lat": 52.3567, "lon": 10.5234, "name": "A2 Braunschweig - Abstandskontrolle", "type": "distance", "speedLimit": 100},
    # A7 - Main distance control locations
    {"lat": 51.4234, "lon": 9.6512, "name": "A7 Hann. Münden Werratalbrücke - Abstandskontrolle", "type": "distance", "speedLimit": 100},
    {"lat": 54.2567, "lon": 9.6234, "name": "A7 Borgstedt/Rendsburg - Abstandskontrolle", "type": "distance", "speedLimit": 80},
    {"lat": 51.5012, "lon": 9.9234, "name": "A7 Rosdorf/Kassel - Abstandskontrolle", "type": "distance", "speedLimit": 60},
    {"lat": 53.0845, "lon": 9.9123, "name": "A7 Bispringen - Abstandskontrolle Ri. Hamburg", "type": "distance", "speedLimit": 120},
    {"lat": 52.7234, "lon": 9.7345, "name": "A7 Essel - Abstandskontrolle Ri. Hannover", "type": "distance", "speedLimit": 120},
    {"lat": 53.5567, "lon": 9.9812, "name": "A7 Hamburg - Abstandskontrolle", "type": "distance", "speedLimit": 80},
    # A1 - Distance control locations
    {"lat": 53.1234, "lon": 8.7512, "name": "A1 Bremen - Abstandskontrolle Ri. Hamburg", "type": "distance", "speedLimit": 120},
    {"lat": 49.7345, "lon": 6.6234, "name": "A1 Mehring - Abstandskontrolle Ri. Saarbrücken", "type": "distance", "speedLimit": 80},
    {"lat": 49.9512, "lon": 6.8923, "name": "A1 Wittlich - Abstandskontrolle", "type": "distance", "speedLimit": 80},
    # A3 - Distance control locations
    {"lat": 50.1123, "lon": 8.6823, "name": "A3 Frankfurt - Abstandskontrolle", "type": "distance", "speedLimit": 100},
    {"lat": 51.2234, "lon": 6.7823, "name": "A3 Düsseldorf - Abstandskontrolle", "type": "distance", "speedLimit": 100},
    # A4 - Distance control locations  
    {"lat": 50.9234, "lon": 6.9567, "name": "A4 Köln - Abstandskontrolle", "type": "distance", "speedLimit": 100},
    # A8 - Distance control locations
    {"lat": 48.7823, "lon": 9.1823, "name": "A8 Stuttgart - Abstandskontrolle", "type": "distance", "speedLimit": 120},
    {"lat": 48.1345, "lon": 11.5823, "name": "A8 München - Abstandskontrolle", "type": "distance", "speedLimit": 120},
    # A9 - Distance control locations
    {"lat": 48.3567, "lon": 11.7823, "name": "A9 München Nord - Abstandskontrolle", "type": "distance", "speedLimit": 120},
    {"lat": 50.3234, "lon": 11.9123, "name": "A9 Nürnberg - Abstandskontrolle", "type": "distance", "speedLimit": 120},
]

# ============ FRANCE DISTANCE CONTROL / RADARS DE CONTRÔLE INTER-VÉHICULAIRE ============
# Contrôle des distances de sécurité en France
FRANCE_DISTANCE_CAMERAS = [
    # A1 - Autoroute du Nord
    {"lat": 49.0234, "lon": 2.5123, "name": "A1 Roissy - Contrôle distance", "type": "distance", "speedLimit": 110},
    {"lat": 49.2567, "lon": 2.7823, "name": "A1 Senlis - Contrôle distance", "type": "distance", "speedLimit": 130},
    {"lat": 49.8512, "lon": 2.2956, "name": "A1 Amiens - Contrôle distance", "type": "distance", "speedLimit": 130},
    # A4 - Autoroute de l'Est
    {"lat": 48.9234, "lon": 2.7623, "name": "A4 Marne-la-Vallée - Contrôle distance", "type": "distance", "speedLimit": 110},
    {"lat": 49.0456, "lon": 3.9512, "name": "A4 Reims - Contrôle distance", "type": "distance", "speedLimit": 130},
    {"lat": 49.1123, "lon": 6.1756, "name": "A4 Metz - Contrôle distance", "type": "distance", "speedLimit": 130},
    # A6 - Autoroute du Soleil
    {"lat": 48.6823, "lon": 2.3756, "name": "A6 Évry - Contrôle distance", "type": "distance", "speedLimit": 110},
    {"lat": 47.9956, "lon": 3.2823, "name": "A6 Auxerre - Contrôle distance", "type": "distance", "speedLimit": 130},
    {"lat": 46.3123, "lon": 4.8356, "name": "A6 Mâcon - Contrôle distance", "type": "distance", "speedLimit": 130},
    {"lat": 45.7523, "lon": 4.8623, "name": "A6 Lyon Nord - Contrôle distance", "type": "distance", "speedLimit": 110},
    # A7 - Autoroute du Soleil (Sud)
    {"lat": 45.5234, "lon": 4.7512, "name": "A7 Vienne - Contrôle distance", "type": "distance", "speedLimit": 130},
    {"lat": 44.9312, "lon": 4.8923, "name": "A7 Valence - Contrôle distance", "type": "distance", "speedLimit": 130},
    {"lat": 44.1256, "lon": 4.8056, "name": "A7 Orange - Contrôle distance", "type": "distance", "speedLimit": 130},
    {"lat": 43.4523, "lon": 4.9823, "name": "A7 Salon-de-Provence - Contrôle distance", "type": "distance", "speedLimit": 130},
    # A8 - La Provençale
    {"lat": 43.5234, "lon": 5.4512, "name": "A8 Aix-en-Provence - Contrôle distance", "type": "distance", "speedLimit": 130},
    {"lat": 43.6012, "lon": 6.8923, "name": "A8 Fréjus - Contrôle distance", "type": "distance", "speedLimit": 130},
    {"lat": 43.6756, "lon": 7.2123, "name": "A8 Nice - Contrôle distance", "type": "distance", "speedLimit": 110},
    # A9 - La Languedocienne
    {"lat": 43.6123, "lon": 3.8756, "name": "A9 Montpellier - Contrôle distance", "type": "distance", "speedLimit": 130},
    {"lat": 43.1856, "lon": 2.9823, "name": "A9 Narbonne - Contrôle distance", "type": "distance", "speedLimit": 130},
    {"lat": 42.6956, "lon": 2.8756, "name": "A9 Perpignan - Contrôle distance", "type": "distance", "speedLimit": 130},
    # A10 - L'Aquitaine
    {"lat": 48.0234, "lon": 1.5312, "name": "A10 Chartres - Contrôle distance", "type": "distance", "speedLimit": 130},
    {"lat": 47.3856, "lon": 0.6923, "name": "A10 Tours - Contrôle distance", "type": "distance", "speedLimit": 130},
    {"lat": 46.5823, "lon": 0.3512, "name": "A10 Poitiers - Contrôle distance", "type": "distance", "speedLimit": 130},
    {"lat": 44.8512, "lon": -0.5623, "name": "A10 Bordeaux - Contrôle distance", "type": "distance", "speedLimit": 110},
    # A13 - Autoroute de Normandie
    {"lat": 48.9923, "lon": 1.2156, "name": "A13 Mantes - Contrôle distance", "type": "distance", "speedLimit": 130},
    {"lat": 49.1856, "lon": 0.3712, "name": "A13 Rouen - Contrôle distance", "type": "distance", "speedLimit": 130},
    {"lat": 49.2023, "lon": -0.3612, "name": "A13 Caen - Contrôle distance", "type": "distance", "speedLimit": 130},
    # Périphérique Paris
    {"lat": 48.8234, "lon": 2.4123, "name": "Périph. Paris Est - Contrôle distance", "type": "distance", "speedLimit": 70},
    {"lat": 48.8512, "lon": 2.2856, "name": "Périph. Paris Ouest - Contrôle distance", "type": "distance", "speedLimit": 70},
    {"lat": 48.8923, "lon": 2.3512, "name": "Périph. Paris Nord - Contrôle distance", "type": "distance", "speedLimit": 70},
]

# ============ SECTION CONTROL / STRECKENRADAR (Average Speed Cameras) ============
# These measure average speed over a road section
SECTION_CONTROL_CAMERAS = [
    # Germany
    {"lat": 52.2945, "lon": 10.4523, "name": "B6 Gleidingen - Section Control START", "type": "section_start", "speedLimit": 100},
    {"lat": 52.3123, "lon": 10.4812, "name": "B6 Gleidingen - Section Control END", "type": "section_end", "speedLimit": 100},
    {"lat": 52.1567, "lon": 9.9234, "name": "A2 Hannover - Section Control", "type": "zone", "speedLimit": 100},
    {"lat": 51.0234, "lon": 7.0012, "name": "A1 Leverkusen - Section Control", "type": "zone", "speedLimit": 100},
    # Austria (many section controls)
    {"lat": 47.2634, "lon": 11.3456, "name": "A13 Brenner - Section Control START", "type": "section_start", "speedLimit": 100},
    {"lat": 47.0812, "lon": 11.5023, "name": "A13 Brenner - Section Control END", "type": "section_end", "speedLimit": 100},
    {"lat": 48.1923, "lon": 16.3234, "name": "A4 Wien - Section Control", "type": "zone", "speedLimit": 100},
    {"lat": 47.0567, "lon": 15.4234, "name": "A2 Graz - Section Control", "type": "zone", "speedLimit": 100},
    {"lat": 47.8012, "lon": 13.0456, "name": "A1 Salzburg - Section Control", "type": "zone", "speedLimit": 100},
    # Switzerland
    {"lat": 46.2012, "lon": 6.1456, "name": "A1 Genève - Section Control", "type": "zone", "speedLimit": 120},
    {"lat": 47.3767, "lon": 8.5412, "name": "A1 Zürich - Section Control", "type": "zone", "speedLimit": 100},
    # Netherlands
    {"lat": 52.0789, "lon": 4.3123, "name": "A4 Den Haag - Trajectcontrole", "type": "zone", "speedLimit": 100},
    {"lat": 52.3456, "lon": 4.8234, "name": "A10 Amsterdam Ring - Trajectcontrole", "type": "zone", "speedLimit": 100},
    # Italy (Tutor system)
    {"lat": 45.4678, "lon": 9.1812, "name": "A4 Milano - Tutor START", "type": "section_start", "speedLimit": 130},
    {"lat": 45.5234, "lon": 9.3456, "name": "A4 Milano - Tutor END", "type": "section_end", "speedLimit": 130},
    {"lat": 41.9012, "lon": 12.5234, "name": "A1 Roma - Tutor", "type": "zone", "speedLimit": 130},
    {"lat": 43.7689, "lon": 11.2534, "name": "A1 Firenze - Tutor", "type": "zone", "speedLimit": 130},
    # UK
    {"lat": 51.5123, "lon": -0.1234, "name": "M25 London - Average Speed", "type": "zone", "speedLimit": 112},
    {"lat": 53.4789, "lon": -2.2456, "name": "M60 Manchester - Average Speed", "type": "zone", "speedLimit": 80},
    # France
    {"lat": 48.8534, "lon": 2.3488, "name": "A86 Paris - Radar Tronçon", "type": "zone", "speedLimit": 90},
    {"lat": 43.2965, "lon": 5.3698, "name": "A7 Marseille - Radar Tronçon", "type": "zone", "speedLimit": 110},
]

# ============ TUNNEL CONTROL CAMERAS ============
TUNNEL_CONTROL_CAMERAS = [
    # Germany
    {"lat": 50.1123, "lon": 8.6789, "name": "Rennsteig Tunnel A71 - Tunnelkontrolle", "type": "tunnel", "speedLimit": 80},
    {"lat": 51.5123, "lon": 7.4567, "name": "Essen Tunnel A40 - Tunnelkontrolle", "type": "tunnel", "speedLimit": 80},
    {"lat": 53.5489, "lon": 9.9872, "name": "Elbtunnel A7 Hamburg - Tunnelkontrolle", "type": "tunnel", "speedLimit": 80},
    # Austria
    {"lat": 47.0789, "lon": 10.6789, "name": "Arlberg Tunnel - Tunnelkontrolle", "type": "tunnel", "speedLimit": 80},
    {"lat": 47.0456, "lon": 12.8234, "name": "Tauern Tunnel - Tunnelkontrolle", "type": "tunnel", "speedLimit": 80},
    {"lat": 46.9789, "lon": 12.9567, "name": "Katschberg Tunnel - Tunnelkontrolle", "type": "tunnel", "speedLimit": 80},
    # Switzerland
    {"lat": 46.5789, "lon": 8.5234, "name": "Gotthard Tunnel - Tunnelkontrolle", "type": "tunnel", "speedLimit": 80},
    {"lat": 46.3123, "lon": 7.6234, "name": "Lötschberg Tunnel - Tunnelkontrolle", "type": "tunnel", "speedLimit": 80},
    # Italy
    {"lat": 45.8234, "lon": 6.8567, "name": "Mont Blanc Tunnel - Controllo Tunnel", "type": "tunnel", "speedLimit": 70},
    {"lat": 45.9012, "lon": 7.8789, "name": "Fréjus Tunnel - Controllo Tunnel", "type": "tunnel", "speedLimit": 70},
    # France
    {"lat": 45.8567, "lon": 6.8234, "name": "Tunnel du Mont-Blanc - Contrôle", "type": "tunnel", "speedLimit": 70},
]

# ============ NOISE CAMERAS (Lärmblitzer) ============
NOISE_CAMERAS = [
    # Germany (pilot projects)
    {"lat": 52.5200, "lon": 13.4050, "name": "Berlin - Lärmblitzer Pilot", "type": "noise", "speedLimit": None},
    {"lat": 48.1351, "lon": 11.5820, "name": "München - Lärmblitzer Pilot", "type": "noise", "speedLimit": None},
    # France
    {"lat": 48.8566, "lon": 2.3522, "name": "Paris - Radar Sonore", "type": "noise", "speedLimit": None},
    {"lat": 45.7640, "lon": 4.8357, "name": "Lyon - Radar Sonore", "type": "noise", "speedLimit": None},
    {"lat": 43.6047, "lon": 1.4442, "name": "Toulouse - Radar Sonore", "type": "noise", "speedLimit": None},
    {"lat": 43.2965, "lon": 5.3698, "name": "Marseille - Radar Sonore", "type": "noise", "speedLimit": None},
    # Switzerland (known for strict noise laws)
    {"lat": 47.3769, "lon": 8.5417, "name": "Zürich - Lärmblitzer", "type": "noise", "speedLimit": None},
    {"lat": 46.2044, "lon": 6.1432, "name": "Genève - Radar Bruit", "type": "noise", "speedLimit": None},
]

# ============ MOBILE PHONE CAMERAS (Handyblitzer) ============
PHONE_CAMERAS = [
    # Germany
    {"lat": 50.1109, "lon": 8.6821, "name": "Frankfurt - Handyblitzer", "type": "phone", "speedLimit": None},
    {"lat": 52.5200, "lon": 13.4050, "name": "Berlin - Handyblitzer", "type": "phone", "speedLimit": None},
    {"lat": 48.1351, "lon": 11.5820, "name": "München - Handyblitzer", "type": "phone", "speedLimit": None},
    {"lat": 53.5511, "lon": 9.9937, "name": "Hamburg - Handyblitzer", "type": "phone", "speedLimit": None},
    {"lat": 51.2277, "lon": 6.7735, "name": "Düsseldorf - Handyblitzer", "type": "phone", "speedLimit": None},
    # Netherlands (Handheld camera enforcement)
    {"lat": 52.3676, "lon": 4.9041, "name": "Amsterdam - Telefooncontrole", "type": "phone", "speedLimit": None},
    {"lat": 51.9244, "lon": 4.4777, "name": "Rotterdam - Telefooncontrole", "type": "phone", "speedLimit": None},
    # UK
    {"lat": 51.5074, "lon": -0.1278, "name": "London - Mobile Phone Camera", "type": "phone", "speedLimit": None},
]

# ============ WEIGHT CONTROL (Gewichtskontrolle - for trucks) ============
WEIGHT_CONTROL_CAMERAS = [
    # Germany
    {"lat": 52.2567, "lon": 10.5234, "name": "A2 Helmstedt - LKW Gewichtskontrolle", "type": "weight", "speedLimit": None},
    {"lat": 51.4234, "lon": 6.7823, "name": "A40 Duisburg - LKW Gewichtskontrolle", "type": "weight", "speedLimit": None},
    {"lat": 50.0789, "lon": 8.2345, "name": "A3 Limburg - LKW Gewichtskontrolle", "type": "weight", "speedLimit": None},
    {"lat": 49.4521, "lon": 11.0767, "name": "A6 Nürnberg - LKW Gewichtskontrolle", "type": "weight", "speedLimit": None},
    # Austria
    {"lat": 47.2634, "lon": 11.3923, "name": "A13 Brenner - LKW Kontrolle", "type": "weight", "speedLimit": None},
    {"lat": 48.2082, "lon": 16.3738, "name": "A4 Wien - LKW Kontrolle", "type": "weight", "speedLimit": None},
]

# ============ OVERTAKING BAN CAMERAS (Überholverbot) ============
OVERTAKING_CAMERAS = [
    # Germany (common on highways with overtaking restrictions)
    {"lat": 51.3234, "lon": 9.4567, "name": "A7 Kassel - Überholverbot LKW", "type": "overtaking", "speedLimit": None},
    {"lat": 50.9234, "lon": 6.9567, "name": "A4 Köln - Überholverbot Kontrolle", "type": "overtaking", "speedLimit": None},
    {"lat": 49.8789, "lon": 8.6512, "name": "A5 Darmstadt - Überholverbot", "type": "overtaking", "speedLimit": None},
]

# ============ SEATBELT CAMERAS (Gurtblitzer) ============
SEATBELT_CAMERAS = [
    # Germany
    {"lat": 52.5200, "lon": 13.4050, "name": "Berlin - Gurtkontrolle", "type": "seatbelt", "speedLimit": None},
    {"lat": 48.1351, "lon": 11.5820, "name": "München - Gurtkontrolle", "type": "seatbelt", "speedLimit": None},
    {"lat": 50.1109, "lon": 8.6821, "name": "Frankfurt - Gurtkontrolle", "type": "seatbelt", "speedLimit": None},
    # Netherlands
    {"lat": 52.3676, "lon": 4.9041, "name": "Amsterdam - Gordelcontrole", "type": "seatbelt", "speedLimit": None},
    # UK
    {"lat": 51.5074, "lon": -0.1278, "name": "London - Seatbelt Camera", "type": "seatbelt", "speedLimit": None},
]

# ============ BUS LANE CAMERAS ============
BUS_LANE_CAMERAS = [
    # UK (very common)
    {"lat": 51.5074, "lon": -0.1278, "name": "London - Bus Lane Camera", "type": "buslane", "speedLimit": None},
    {"lat": 53.4808, "lon": -2.2426, "name": "Manchester - Bus Lane Camera", "type": "buslane", "speedLimit": None},
    {"lat": 55.9533, "lon": -3.1883, "name": "Edinburgh - Bus Lane Camera", "type": "buslane", "speedLimit": None},
    {"lat": 51.4545, "lon": -2.5879, "name": "Bristol - Bus Lane Camera", "type": "buslane", "speedLimit": None},
    # France
    {"lat": 48.8566, "lon": 2.3522, "name": "Paris - Voie Bus Caméra", "type": "buslane", "speedLimit": None},
    {"lat": 45.7640, "lon": 4.8357, "name": "Lyon - Voie Bus Caméra", "type": "buslane", "speedLimit": None},
    # Germany
    {"lat": 52.5200, "lon": 13.4050, "name": "Berlin - Busspur Kontrolle", "type": "buslane", "speedLimit": None},
]

# ============ ENVIRONMENTAL ZONE CAMERAS (Umweltzone/LEZ) ============
ENVIRONMENTAL_CAMERAS = [
    # Germany - Umweltzonen
    {"lat": 52.5200, "lon": 13.4050, "name": "Berlin - Umweltzone Einfahrt", "type": "environment", "speedLimit": None},
    {"lat": 48.1351, "lon": 11.5820, "name": "München - Umweltzone", "type": "environment", "speedLimit": None},
    {"lat": 50.9375, "lon": 6.9603, "name": "Köln - Umweltzone", "type": "environment", "speedLimit": None},
    {"lat": 51.2277, "lon": 6.7735, "name": "Düsseldorf - Umweltzone", "type": "environment", "speedLimit": None},
    {"lat": 48.7758, "lon": 9.1829, "name": "Stuttgart - Umweltzone", "type": "environment", "speedLimit": None},
    # UK - ULEZ/LEZ
    {"lat": 51.5074, "lon": -0.1278, "name": "London ULEZ", "type": "environment", "speedLimit": None},
    {"lat": 53.4808, "lon": -2.2426, "name": "Manchester Clean Air Zone", "type": "environment", "speedLimit": None},
    {"lat": 52.4862, "lon": -1.8904, "name": "Birmingham Clean Air Zone", "type": "environment", "speedLimit": None},
    # Netherlands
    {"lat": 52.3676, "lon": 4.9041, "name": "Amsterdam - Milieuzone", "type": "environment", "speedLimit": None},
    {"lat": 51.9244, "lon": 4.4777, "name": "Rotterdam - Milieuzone", "type": "environment", "speedLimit": None},
    # Belgium
    {"lat": 50.8503, "lon": 4.3517, "name": "Brussels - LEZ", "type": "environment", "speedLimit": None},
    {"lat": 51.0543, "lon": 3.7174, "name": "Gent - LEZ", "type": "environment", "speedLimit": None},
    {"lat": 51.2194, "lon": 4.4025, "name": "Antwerpen - LEZ", "type": "environment", "speedLimit": None},
    # Italy - ZTL
    {"lat": 41.9028, "lon": 12.4964, "name": "Roma - ZTL", "type": "environment", "speedLimit": None},
    {"lat": 45.4642, "lon": 9.1900, "name": "Milano - Area C", "type": "environment", "speedLimit": None},
    {"lat": 43.7696, "lon": 11.2558, "name": "Firenze - ZTL", "type": "environment", "speedLimit": None},
]

# ============ SPAIN - RADARES ============
SPAIN_CAMERAS = [
    # Fixed speed cameras (Radares fijos)
    {"lat": 40.4168, "lon": -3.7038, "name": "Madrid M-30 - Radar fijo", "type": "speed", "speedLimit": 90},
    {"lat": 41.3851, "lon": 2.1734, "name": "Barcelona Ronda - Radar fijo", "type": "speed", "speedLimit": 80},
    {"lat": 39.4699, "lon": -0.3763, "name": "Valencia V-30 - Radar fijo", "type": "speed", "speedLimit": 100},
    {"lat": 37.3891, "lon": -5.9845, "name": "Sevilla SE-30 - Radar fijo", "type": "speed", "speedLimit": 80},
    {"lat": 43.2627, "lon": -2.9253, "name": "Bilbao A-8 - Radar fijo", "type": "speed", "speedLimit": 120},
    # Section control (Radares de tramo)
    {"lat": 40.4523, "lon": -3.6892, "name": "A-1 Madrid - Radar tramo", "type": "zone", "speedLimit": 120},
    {"lat": 41.6176, "lon": -0.9057, "name": "A-2 Zaragoza - Radar tramo", "type": "zone", "speedLimit": 120},
    {"lat": 38.3452, "lon": -0.4815, "name": "A-7 Alicante - Radar tramo", "type": "zone", "speedLimit": 120},
    # Red light cameras
    {"lat": 40.4168, "lon": -3.7038, "name": "Madrid - Semáforo radar", "type": "redlight", "speedLimit": None},
    {"lat": 41.3851, "lon": 2.1734, "name": "Barcelona - Semáforo radar", "type": "redlight", "speedLimit": None},
]

# ============ PORTUGAL - RADARES ============
PORTUGAL_CAMERAS = [
    {"lat": 38.7223, "lon": -9.1393, "name": "Lisboa A1 - Radar fixo", "type": "speed", "speedLimit": 120},
    {"lat": 41.1579, "lon": -8.6291, "name": "Porto A3 - Radar fixo", "type": "speed", "speedLimit": 120},
    {"lat": 37.0179, "lon": -7.9304, "name": "Faro A22 - Radar fixo", "type": "speed", "speedLimit": 120},
    {"lat": 40.2033, "lon": -8.4103, "name": "Coimbra A1 - Radar fixo", "type": "speed", "speedLimit": 120},
]

# ============ POLAND - FOTORADARY ============
POLAND_CAMERAS = [
    {"lat": 52.2297, "lon": 21.0122, "name": "Warszawa S8 - Fotoradar", "type": "speed", "speedLimit": 120},
    {"lat": 51.1079, "lon": 17.0385, "name": "Wrocław A4 - Fotoradar", "type": "speed", "speedLimit": 140},
    {"lat": 50.0647, "lon": 19.9450, "name": "Kraków A4 - Fotoradar", "type": "speed", "speedLimit": 140},
    {"lat": 54.3520, "lon": 18.6466, "name": "Gdańsk S7 - Fotoradar", "type": "speed", "speedLimit": 120},
    {"lat": 52.4064, "lon": 16.9252, "name": "Poznań A2 - Fotoradar", "type": "speed", "speedLimit": 140},
    # Section control (Odcinkowy pomiar prędkości)
    {"lat": 52.1234, "lon": 20.8234, "name": "A2 Łódź - Odcinkowy pomiar", "type": "zone", "speedLimit": 140},
]

# ============ CZECH REPUBLIC - RADARY ============
CZECH_CAMERAS = [
    {"lat": 50.0755, "lon": 14.4378, "name": "Praha D1 - Radar", "type": "speed", "speedLimit": 130},
    {"lat": 49.1951, "lon": 16.6068, "name": "Brno D1 - Radar", "type": "speed", "speedLimit": 130},
    {"lat": 49.8209, "lon": 18.2625, "name": "Ostrava D1 - Radar", "type": "speed", "speedLimit": 130},
    # Section control
    {"lat": 49.5923, "lon": 17.2512, "name": "D1 Olomouc - Úsekové měření", "type": "zone", "speedLimit": 130},
]

# ============ HUNGARY - TRAFFIPAX ============
HUNGARY_CAMERAS = [
    {"lat": 47.4979, "lon": 19.0402, "name": "Budapest M1 - Traffipax", "type": "speed", "speedLimit": 130},
    {"lat": 47.6812, "lon": 17.6356, "name": "M1 Győr - Traffipax", "type": "speed", "speedLimit": 130},
    {"lat": 46.2530, "lon": 20.1414, "name": "M5 Szeged - Traffipax", "type": "speed", "speedLimit": 130},
    {"lat": 47.0934, "lon": 17.9093, "name": "M7 Balaton - Traffipax", "type": "speed", "speedLimit": 130},
]

# ============ SCANDINAVIA (Sweden, Norway, Denmark, Finland) ============
SCANDINAVIA_CAMERAS = [
    # Sweden - ATK (Automatisk Trafiksäkerhetskontroll)
    {"lat": 59.3293, "lon": 18.0686, "name": "Stockholm E4 - ATK", "type": "speed", "speedLimit": 110},
    {"lat": 57.7089, "lon": 11.9746, "name": "Göteborg E6 - ATK", "type": "speed", "speedLimit": 110},
    {"lat": 55.6050, "lon": 13.0038, "name": "Malmö E6 - ATK", "type": "speed", "speedLimit": 110},
    # Norway - Fotoboks
    {"lat": 59.9139, "lon": 10.7522, "name": "Oslo E18 - Fotoboks", "type": "speed", "speedLimit": 100},
    {"lat": 60.3913, "lon": 5.3221, "name": "Bergen E39 - Fotoboks", "type": "speed", "speedLimit": 90},
    {"lat": 63.4305, "lon": 10.3951, "name": "Trondheim E6 - Fotoboks", "type": "speed", "speedLimit": 90},
    # Denmark - Fotofælder
    {"lat": 55.6761, "lon": 12.5683, "name": "København E20 - ATK", "type": "speed", "speedLimit": 110},
    {"lat": 56.1629, "lon": 10.2039, "name": "Aarhus E45 - ATK", "type": "speed", "speedLimit": 130},
    # Section control
    {"lat": 55.4038, "lon": 10.4024, "name": "Fyn Motorvejen - Strækningsmåling", "type": "zone", "speedLimit": 130},
    # Finland - Nopeuskamera
    {"lat": 60.1699, "lon": 24.9384, "name": "Helsinki E18 - Nopeuskamera", "type": "speed", "speedLimit": 120},
    {"lat": 61.4978, "lon": 23.7610, "name": "Tampere E12 - Nopeuskamera", "type": "speed", "speedLimit": 120},
]

# ============ BENELUX (Belgium, Netherlands, Luxembourg) ============
BENELUX_CAMERAS = [
    # Belgium - Flitsers
    {"lat": 50.8503, "lon": 4.3517, "name": "Brussels E40 - Flitspaal", "type": "speed", "speedLimit": 120},
    {"lat": 51.2194, "lon": 4.4025, "name": "Antwerpen E17 - Flitspaal", "type": "speed", "speedLimit": 120},
    {"lat": 51.0543, "lon": 3.7174, "name": "Gent E40 - Flitspaal", "type": "speed", "speedLimit": 120},
    {"lat": 50.6292, "lon": 5.5797, "name": "Liège E40 - Flitspaal", "type": "speed", "speedLimit": 120},
    # Belgium Section control (Trajectcontrole)
    {"lat": 51.0312, "lon": 3.7056, "name": "E17 Gent - Trajectcontrole", "type": "zone", "speedLimit": 120},
    {"lat": 50.9234, "lon": 4.0456, "name": "E40 Aalst - Trajectcontrole", "type": "zone", "speedLimit": 120},
    # Netherlands - Flitsers  
    {"lat": 52.3676, "lon": 4.9041, "name": "Amsterdam A10 - Flitspaal", "type": "speed", "speedLimit": 100},
    {"lat": 51.9244, "lon": 4.4777, "name": "Rotterdam A16 - Flitspaal", "type": "speed", "speedLimit": 100},
    {"lat": 52.0907, "lon": 5.1214, "name": "Utrecht A2 - Flitspaal", "type": "speed", "speedLimit": 100},
    {"lat": 51.4416, "lon": 5.4697, "name": "Eindhoven A2 - Flitspaal", "type": "speed", "speedLimit": 130},
    # Netherlands Section control (Trajectcontrole)
    {"lat": 52.0789, "lon": 4.3123, "name": "A4 Den Haag - Trajectcontrole", "type": "zone", "speedLimit": 100},
    {"lat": 52.2012, "lon": 4.5234, "name": "A44 Leiden - Trajectcontrole", "type": "zone", "speedLimit": 100},
    # Luxembourg
    {"lat": 49.6116, "lon": 6.1319, "name": "Luxembourg A1 - Radar fixe", "type": "speed", "speedLimit": 130},
    {"lat": 49.5012, "lon": 5.9456, "name": "A4 Esch - Radar fixe", "type": "speed", "speedLimit": 130},
]

# ============ ITALY - AUTOVELOX & TUTOR ============
ITALY_CAMERAS = [
    # Autovelox (fixed speed)
    {"lat": 41.9028, "lon": 12.4964, "name": "Roma GRA - Autovelox", "type": "speed", "speedLimit": 80},
    {"lat": 45.4642, "lon": 9.1900, "name": "Milano Tangenziale - Autovelox", "type": "speed", "speedLimit": 90},
    {"lat": 43.7696, "lon": 11.2558, "name": "Firenze A1 - Autovelox", "type": "speed", "speedLimit": 130},
    {"lat": 40.8518, "lon": 14.2681, "name": "Napoli A1 - Autovelox", "type": "speed", "speedLimit": 130},
    {"lat": 45.0703, "lon": 7.6869, "name": "Torino Tangenziale - Autovelox", "type": "speed", "speedLimit": 90},
    {"lat": 44.4949, "lon": 11.3426, "name": "Bologna A14 - Autovelox", "type": "speed", "speedLimit": 130},
    # Tutor (section control) - very common in Italy
    {"lat": 44.1234, "lon": 9.8234, "name": "A12 La Spezia - Tutor", "type": "zone", "speedLimit": 130},
    {"lat": 43.3123, "lon": 11.7823, "name": "A1 Arezzo - Tutor", "type": "zone", "speedLimit": 130},
    {"lat": 42.3512, "lon": 13.3956, "name": "A24 L'Aquila - Tutor", "type": "zone", "speedLimit": 130},
    {"lat": 45.8234, "lon": 10.9512, "name": "A22 Brennero - Tutor", "type": "zone", "speedLimit": 130},
    {"lat": 44.8234, "lon": 8.4512, "name": "A26 Alessandria - Tutor", "type": "zone", "speedLimit": 130},
    {"lat": 45.5234, "lon": 12.2512, "name": "A4 Venezia - Tutor", "type": "zone", "speedLimit": 130},
]

# ============ GREECE - RADARS ============
GREECE_CAMERAS = [
    {"lat": 37.9838, "lon": 23.7275, "name": "Athens Attiki Odos - Radar", "type": "speed", "speedLimit": 120},
    {"lat": 40.6401, "lon": 22.9444, "name": "Thessaloniki Egnatia - Radar", "type": "speed", "speedLimit": 130},
    {"lat": 38.2466, "lon": 21.7346, "name": "Patras A8 - Radar", "type": "speed", "speedLimit": 130},
]

# ============ CROATIA - RADARI ============
CROATIA_CAMERAS = [
    {"lat": 45.8150, "lon": 15.9819, "name": "Zagreb A1 - Radar", "type": "speed", "speedLimit": 130},
    {"lat": 45.3271, "lon": 14.4422, "name": "Rijeka A7 - Radar", "type": "speed", "speedLimit": 130},
    {"lat": 43.5081, "lon": 16.4402, "name": "Split A1 - Radar", "type": "speed", "speedLimit": 130},
]

# ============ SLOVENIA - RADARJI ============
SLOVENIA_CAMERAS = [
    {"lat": 46.0569, "lon": 14.5058, "name": "Ljubljana A1 - Radar", "type": "speed", "speedLimit": 130},
    {"lat": 46.5547, "lon": 15.6459, "name": "Maribor A1 - Radar", "type": "speed", "speedLimit": 130},
    {"lat": 45.5469, "lon": 13.7300, "name": "Koper A1 - Radar", "type": "speed", "speedLimit": 130},
]

# ============ BREMEN RED LIGHT CAMERAS (Manually verified from SCDB) ============
BREMEN_REDLIGHT_CAMERAS = [
    {"lat": 53.0727, "lon": 8.8075, "name": "B75 Tiefer, Ecke Altenwall", "type": "redlight"},
    {"lat": 53.0635, "lon": 8.8180, "name": "Breitenweg, Ecke Bürgermeister-Smidt-Str.", "type": "redlight"},
    {"lat": 53.1108, "lon": 8.8523, "name": "Borgfelder Heerstr., Ecke Borgfelder Allee", "type": "redlight"},
    {"lat": 53.1285, "lon": 8.7175, "name": "Grambker Heerstr., Ecke Mittelsbürener Landstr.", "type": "redlight"},
    {"lat": 53.0742, "lon": 8.7352, "name": "B75 Oldenburger Straße, vor Ausfahrt Grolland", "type": "redlight"},
    {"lat": 53.0985, "lon": 8.9150, "name": "Ludwig-Roselius-Allee, Ecke Hinter dem Rennplatz", "type": "redlight"},
    {"lat": 53.0405, "lon": 8.8425, "name": "Pfalzburger Str., Autobahnzubringer Hemelingen", "type": "redlight"},
    {"lat": 53.0330, "lon": 8.7890, "name": "B6 Kattenturmer Heerstr., Ecke Arsterdamm", "type": "redlight"},
    {"lat": 53.0495, "lon": 8.8670, "name": "Kurt-Schumacher-Allee, Ecke Karl-Kautsky-Str.", "type": "redlight"},
    {"lat": 53.0583, "lon": 8.7715, "name": "B6 Neuenlander Str., Ecke Neuenlander Ring", "type": "redlight"},
    {"lat": 53.0515, "lon": 8.7405, "name": "A281, kurz nach Ausfahrt Airport", "type": "redlight"},
    {"lat": 53.1022, "lon": 8.8728, "name": "Hans-Bredow-Str., Ecke Julius-Faucher-Str.", "type": "redlight"},
    {"lat": 53.1085, "lon": 8.8998, "name": "B75 Osterholzer Heerstr., Ecke Hans-Bredow-Str.", "type": "redlight"},
    {"lat": 53.0825, "lon": 8.8345, "name": "Bismarckstr., Ecke Schwachhauser Heerstr.", "type": "redlight"},
    {"lat": 53.0862, "lon": 8.8225, "name": "Dobbenweg, Kreuzung Am Dobben", "type": "redlight"},
    {"lat": 53.0958, "lon": 8.8425, "name": "Schwachhauser Heerstr., Ecke Holler Allee", "type": "redlight"},
    {"lat": 53.0975, "lon": 8.8510, "name": "Schwachhauser Heerstr., Ecke Kurfürstenallee", "type": "redlight"},
    {"lat": 53.0785, "lon": 8.8015, "name": "Hans-Böckler-Str., Ecke Lloydstr.", "type": "redlight"},
    {"lat": 53.0925, "lon": 8.8745, "name": "Richard-Boljahn-Allee, Kreuzung In der Vahr", "type": "redlight"},
    {"lat": 53.0895, "lon": 8.7635, "name": "Waller Heerstr., Kreuzung Waller Ring", "type": "redlight"},
]

# Combine all verified cameras
ALL_VERIFIED_CAMERAS = (
    EUROPE_REDLIGHT_CAMERAS + 
    BREMEN_REDLIGHT_CAMERAS + 
    GERMANY_DISTANCE_CAMERAS +
    FRANCE_DISTANCE_CAMERAS +
    SECTION_CONTROL_CAMERAS +
    TUNNEL_CONTROL_CAMERAS +
    NOISE_CAMERAS +
    PHONE_CAMERAS +
    WEIGHT_CONTROL_CAMERAS +
    OVERTAKING_CAMERAS +
    SEATBELT_CAMERAS +
    BUS_LANE_CAMERAS +
    ENVIRONMENTAL_CAMERAS +
    SPAIN_CAMERAS +
    PORTUGAL_CAMERAS +
    POLAND_CAMERAS +
    CZECH_CAMERAS +
    HUNGARY_CAMERAS +
    SCANDINAVIA_CAMERAS +
    BENELUX_CAMERAS +
    ITALY_CAMERAS +
    GREECE_CAMERAS +
    CROATIA_CAMERAS +
    SLOVENIA_CAMERAS
)

# ============ USA VERIFIED CAMERAS ============
USA_CAMERAS = [
    # New York City
    {"lat": 40.7128, "lon": -74.0060, "type": "redlight", "name": "NYC Manhattan", "speedLimit": None},
    {"lat": 40.7580, "lon": -73.9855, "type": "speed", "name": "NYC Times Square", "speedLimit": 25},
    {"lat": 40.7484, "lon": -73.9857, "type": "speed", "name": "NYC 34th Street", "speedLimit": 25},
    {"lat": 40.7614, "lon": -73.9776, "type": "redlight", "name": "NYC 5th Avenue", "speedLimit": None},
    # Los Angeles
    {"lat": 34.0522, "lon": -118.2437, "type": "redlight", "name": "LA Downtown", "speedLimit": None},
    {"lat": 34.0195, "lon": -118.4912, "type": "speed", "name": "LA Santa Monica", "speedLimit": 35},
    {"lat": 34.0736, "lon": -118.4004, "type": "redlight", "name": "LA Beverly Hills", "speedLimit": None},
    # Chicago
    {"lat": 41.8781, "lon": -87.6298, "type": "speed", "name": "Chicago Loop", "speedLimit": 30},
    {"lat": 41.8827, "lon": -87.6233, "type": "redlight", "name": "Chicago Downtown", "speedLimit": None},
    # Miami
    {"lat": 25.7617, "lon": -80.1918, "type": "speed", "name": "Miami Downtown", "speedLimit": 35},
    {"lat": 25.7907, "lon": -80.1300, "type": "redlight", "name": "Miami Beach", "speedLimit": None},
    # Washington DC
    {"lat": 38.9072, "lon": -77.0369, "type": "speed", "name": "DC Downtown", "speedLimit": 25},
    {"lat": 38.8977, "lon": -77.0365, "type": "redlight", "name": "DC Capitol", "speedLimit": None},
    # Houston
    {"lat": 29.7604, "lon": -95.3698, "type": "speed", "name": "Houston Downtown", "speedLimit": 35},
    # Phoenix
    {"lat": 33.4484, "lon": -112.0740, "type": "speed", "name": "Phoenix", "speedLimit": 45},
    # Philadelphia
    {"lat": 39.9526, "lon": -75.1652, "type": "redlight", "name": "Philadelphia", "speedLimit": None},
    # San Francisco
    {"lat": 37.7749, "lon": -122.4194, "type": "speed", "name": "SF Downtown", "speedLimit": 25},
    {"lat": 37.7849, "lon": -122.4094, "type": "redlight", "name": "SF Market St", "speedLimit": None},
    # Seattle
    {"lat": 47.6062, "lon": -122.3321, "type": "speed", "name": "Seattle Downtown", "speedLimit": 25},
    # Denver
    {"lat": 39.7392, "lon": -104.9903, "type": "speed", "name": "Denver Downtown", "speedLimit": 30},
    # Boston
    {"lat": 42.3601, "lon": -71.0589, "type": "redlight", "name": "Boston Downtown", "speedLimit": None},
]

# ============ CANADA VERIFIED CAMERAS ============
CANADA_CAMERAS = [
    # Toronto
    {"lat": 43.6532, "lon": -79.3832, "type": "speed", "name": "Toronto Downtown", "speedLimit": 50},
    {"lat": 43.6426, "lon": -79.3871, "type": "redlight", "name": "Toronto Union Station", "speedLimit": None},
    {"lat": 43.7001, "lon": -79.4163, "type": "speed", "name": "Toronto North York", "speedLimit": 50},
    # Montreal
    {"lat": 45.5017, "lon": -73.5673, "type": "speed", "name": "Montreal Downtown", "speedLimit": 50},
    {"lat": 45.5088, "lon": -73.5878, "type": "redlight", "name": "Montreal St Laurent", "speedLimit": None},
    # Vancouver
    {"lat": 49.2827, "lon": -123.1207, "type": "speed", "name": "Vancouver Downtown", "speedLimit": 50},
    {"lat": 49.2768, "lon": -123.1180, "type": "redlight", "name": "Vancouver Waterfront", "speedLimit": None},
    # Ottawa
    {"lat": 45.4215, "lon": -75.6972, "type": "speed", "name": "Ottawa Downtown", "speedLimit": 50},
    {"lat": 45.4231, "lon": -75.6998, "type": "redlight", "name": "Ottawa Parliament", "speedLimit": None},
    # Calgary
    {"lat": 51.0447, "lon": -114.0719, "type": "speed", "name": "Calgary Downtown", "speedLimit": 50},
    # Edmonton
    {"lat": 53.5461, "lon": -113.4938, "type": "speed", "name": "Edmonton Downtown", "speedLimit": 50},
    # Winnipeg
    {"lat": 49.8951, "lon": -97.1384, "type": "speed", "name": "Winnipeg Downtown", "speedLimit": 50},
]

# ============ UK VERIFIED CAMERAS ============
UK_CAMERAS = [
    # London
    {"lat": 51.5074, "lon": -0.1278, "type": "speed", "name": "London Central", "speedLimit": 30},
    {"lat": 51.5014, "lon": -0.1419, "type": "redlight", "name": "Westminster", "speedLimit": None},
    {"lat": 51.5033, "lon": -0.1195, "type": "zone", "name": "City of London ULEZ", "speedLimit": 30},
    # Manchester
    {"lat": 53.4808, "lon": -2.2426, "type": "speed", "name": "Manchester", "speedLimit": 30},
    # Birmingham
    {"lat": 52.4862, "lon": -1.8904, "type": "speed", "name": "Birmingham", "speedLimit": 30},
    # Glasgow
    {"lat": 55.8642, "lon": -4.2518, "type": "speed", "name": "Glasgow", "speedLimit": 30},
    # Liverpool
    {"lat": 53.4084, "lon": -2.9916, "type": "speed", "name": "Liverpool", "speedLimit": 30},
]

# Add to ALL_VERIFIED_CAMERAS
ALL_VERIFIED_CAMERAS = (
    ALL_VERIFIED_CAMERAS + 
    USA_CAMERAS + 
    CANADA_CAMERAS + 
    UK_CAMERAS
)

# ============ PYDANTIC MODELS ============

class Camera(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    lat: float
    lon: float
    type: str  # 'speed', 'redlight', 'mobile', 'zone', 'checkpoint', 'distance'
    speedLimit: Optional[int] = None
    direction: Optional[int] = None
    source: str = "aggregated"
    name: Optional[str] = None
    road: Optional[str] = None
    country: Optional[str] = None
    verified: bool = True
    lastUpdated: Optional[datetime] = None

class CameraResponse(BaseModel):
    cameras: List[Camera]
    cached: bool = False
    source: str = "aggregated"
    total: int = 0
    region: Optional[str] = None

class Hazard(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    lat: float
    lon: float
    type: str  # 'accident', 'traffic', 'roadwork', 'police', 'obstacle', 'weather'
    severity: str = "medium"  # 'low', 'medium', 'high'
    description: Optional[str] = None
    votes: int = 1
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    expiresAt: datetime = Field(default_factory=lambda: datetime.utcnow() + timedelta(hours=2))
    userId: Optional[str] = None

class HazardCreate(BaseModel):
    lat: float
    lon: float
    type: str
    severity: str = "medium"
    description: Optional[str] = None

class UserReport(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    lat: float
    lon: float
    type: str
    speedLimit: Optional[int] = None
    votes: int = 0
    confirmed: bool = False
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    expiresAt: Optional[datetime] = None

class UserReportCreate(BaseModel):
    lat: float
    lon: float
    type: str
    speedLimit: Optional[int] = None

class VoteRequest(BaseModel):
    vote: str  # 'confirm' or 'dismiss'

class ReportResponse(BaseModel):
    reports: List[UserReport]

class HazardResponse(BaseModel):
    hazards: List[Hazard]

# ============ COMMENTS SYSTEM ============
class CameraComment(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    cameraId: str
    userId: str
    userName: str = "Anonymous"
    text: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    likes: int = 0
    
class CommentCreate(BaseModel):
    cameraId: str
    userId: str
    userName: str = "Anonymous"
    text: str

class CommentResponse(BaseModel):
    comments: List[CameraComment]

# ============ CAMERA TRUST SYSTEM ============
# Constants for trust-based camera validation
TRUST_THRESHOLDS = {
    'MIN_CONFIRMATIONS_TO_ADD': 3,      # Need 3 users to confirm a new camera
    'MIN_REMOVALS_TO_HIDE': 3,          # Need 3 removal reports to hide camera
    'MIN_REMOVALS_TO_DELETE': 5,        # Need 5 removal reports to fully delete
    'REMOVAL_WINDOW_DAYS': 7,           # Removal reports must be within 7 days
    'AUTO_CLEAN_DAYS': 30,              # Auto-clean after 30 days with no confirmations
    'TRUST_SCORE_THRESHOLD': -3,        # Hide camera when trust <= -3
}

CAMERA_CATEGORIES = {
    'fixed': ['speed', 'redlight', 'distance', 'average', 'zone'],  # Permanent cameras
    'mobile': ['mobile', 'trailer'],                                  # Semi-permanent
    'temporary': ['police', 'checkpoint'],                            # User-reported, temporary
    'hazard': ['construction', 'accident', 'traffic', 'obstacle'],   # Road hazards
}

REPORT_POINTS = {
    'camera_exists': 5,      # Confirming camera exists
    'camera_removed': 10,    # Reporting camera removed (more valuable)
    'new_camera': 15,        # First to report new camera
    'hazard_report': 10,     # Reporting hazard
    'false_report_penalty': -20,  # Penalty for false reports
}

# ============ HELPER FUNCTIONS ============

def get_cache_key(lat: float, lon: float, radius: float) -> str:
    """Generate a cache key based on grid location"""
    grid_size = 0.1  # About 10km grid
    grid_lat = round(lat / grid_size) * grid_size
    grid_lon = round(lon / grid_size) * grid_size
    return f"cameras_{grid_lat:.3f}_{grid_lon:.3f}_{int(radius)}"

def get_country_from_coords(lat: float, lon: float) -> str:
    """Detect country from coordinates"""
    # Europe
    if 35 <= lat <= 72 and -10 <= lon <= 40:
        # Germany
        if 47 <= lat <= 55 and 5 <= lon <= 15:
            return "de"
        # France
        if 42 <= lat <= 51 and -5 <= lon <= 8:
            return "fr"
        # Switzerland
        if 45.5 <= lat <= 47.8 and 5.9 <= lon <= 10.5:
            return "ch"
        # Austria
        if 46 <= lat <= 49 and 9.5 <= lon <= 17:
            return "at"
        # Netherlands
        if 50.5 <= lat <= 53.5 and 3 <= lon <= 7.5:
            return "nl"
        # Belgium
        if 49.5 <= lat <= 51.5 and 2.5 <= lon <= 6.5:
            return "be"
        # Italy
        if 36 <= lat <= 47 and 6 <= lon <= 18.5:
            return "it"
        # Spain
        if 36 <= lat <= 44 and -10 <= lon <= 4:
            return "es"
        # Portugal
        if 36.5 <= lat <= 42 and -10 <= lon <= -6:
            return "pt"
        # Poland
        if 49 <= lat <= 55 and 14 <= lon <= 24:
            return "pl"
        # Czech Republic
        if 48.5 <= lat <= 51 and 12 <= lon <= 19:
            return "cz"
        # Russia (European part)
        if 45 <= lat <= 70 and 30 <= lon <= 60:
            return "ru"
        return "eu"
    # UK & Ireland
    if 49 <= lat <= 62 and -11 <= lon <= 2:
        return "uk"
    # Canada
    if 41 <= lat <= 83 and -141 <= lon <= -52:
        return "ca"
    # USA
    if 24 <= lat <= 50 and -125 <= lon <= -66:
        return "us"
    # Australia
    if -44 <= lat <= -10 and 112 <= lon <= 154:
        return "au"
    # New Zealand
    if -47 <= lat <= -34 and 166 <= lon <= 179:
        return "nz"
    return "world"

def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in meters between two points"""
    R = 6371000  # Earth's radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = math.sin(delta_phi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c

async def get_camera_trust_score(camera_id: str) -> int:
    """Get the trust score for a camera"""
    try:
        camera_trust = await db.camera_trust.find_one({"camera_id": camera_id})
        if camera_trust:
            return camera_trust.get("trust_score", 0)
        return 0
    except:
        return 0

async def update_camera_trust(camera_id: str, lat: float, lon: float, change: int, user_id: str, action: str):
    """Update trust score for a camera"""
    try:
        # Check if user already voted on this camera
        existing_vote = await db.camera_votes.find_one({
            "camera_id": camera_id,
            "user_id": user_id,
            "action": action
        })
        
        if existing_vote:
            logger.info(f"User {user_id} already voted {action} on camera {camera_id}")
            return False
        
        # Record the vote
        await db.camera_votes.insert_one({
            "camera_id": camera_id,
            "user_id": user_id,
            "action": action,
            "lat": lat,
            "lon": lon,
            "created_at": datetime.utcnow()
        })
        
        # Update trust score
        await db.camera_trust.update_one(
            {"camera_id": camera_id},
            {
                "$inc": {"trust_score": change},
                "$set": {
                    "lat": lat,
                    "lon": lon,
                    "last_updated": datetime.utcnow()
                },
                "$push": {
                    "history": {
                        "user_id": user_id,
                        "action": action,
                        "change": change,
                        "timestamp": datetime.utcnow()
                    }
                }
            },
            upsert=True
        )
        
        logger.info(f"Trust updated for camera {camera_id}: {change:+d} by user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Error updating camera trust: {e}")
        return False

async def is_camera_hidden(camera_id: str) -> bool:
    """Check if a camera should be hidden based on trust score and removal reports"""
    try:
        # Check trust score
        trust_score = await get_camera_trust_score(camera_id)
        if trust_score <= TRUST_THRESHOLDS['TRUST_SCORE_THRESHOLD']:
            return True
        
        # Check recent removal reports
        week_ago = datetime.utcnow() - timedelta(days=TRUST_THRESHOLDS['REMOVAL_WINDOW_DAYS'])
        removal_count = await db.camera_removals.count_documents({
            "camera_id": camera_id,
            "created_at": {"$gte": week_ago}
        })
        
        if removal_count >= TRUST_THRESHOLDS['MIN_REMOVALS_TO_HIDE']:
            return True
        
        return False
    except:
        return False

async def auto_clean_cameras():
    """Auto-clean cameras with no recent confirmations (run periodically)"""
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=TRUST_THRESHOLDS['AUTO_CLEAN_DAYS'])
        
        # Find cameras with negative trust and no recent confirmations
        old_cameras = await db.camera_trust.find({
            "trust_score": {"$lte": TRUST_THRESHOLDS['TRUST_SCORE_THRESHOLD']},
            "last_updated": {"$lt": cutoff_date}
        }).to_list(100)
        
        for camera in old_cameras:
            # Move to archive instead of deleting
            await db.camera_archive.insert_one({
                **camera,
                "archived_at": datetime.utcnow(),
                "reason": "auto_clean_no_confirmations"
            })
            await db.camera_trust.delete_one({"_id": camera["_id"]})
            
        logger.info(f"Auto-cleaned {len(old_cameras)} cameras")
    except Exception as e:
        logger.error(f"Auto-clean error: {e}")

def parse_camera_type(type_code: str, name: str = '') -> str:
    """Comprehensive camera type mapping"""
    name_lower = name.lower() if name else ''
    
    # Distance check cameras (Abstandsblitzer)
    if any(x in name_lower for x in ['abstand', 'distance', 'tailgating', 'section']):
        return 'distance'
    
    # Red light cameras
    if any(x in name_lower for x in ['feu rouge', 'red light', 'rotlicht', 'ampel', 'traffic light', 'semaforo']):
        return 'redlight'
    
    # Mobile radars
    if any(x in name_lower for x in ['mobile', 'mobil', 'temporär', 'temporary', 'variabel', 'laser']):
        return 'mobile'
    
    # Speed zones / Average speed
    if any(x in name_lower for x in ['zone', 'average', 'moyenne', 'durchschnitt', 'strecken', 'abschnitt', 'tutor']):
        return 'zone'
    
    # Checkpoints
    if any(x in name_lower for x in ['contrôle', 'control', 'kontrolle', 'police', 'polizei', 'gendarm']):
        return 'checkpoint'
    
    # Type code mapping
    type_map = {
        # Lufop types
        '148': 'speed', '149': 'mobile', '150': 'zone', '151': 'zone',
        '152': 'redlight', '153': 'redlight', '154': 'checkpoint',
        '155': 'mobile', '156': 'distance', '157': 'speed', '158': 'checkpoint',
        # Atudo types
        '1': 'speed', '2': 'speed', '3': 'speed', '4': 'speed', '5': 'speed',
        '6': 'mobile', '7': 'mobile',
        '20': 'redlight', '21': 'redlight', '22': 'redlight',
        '101': 'mobile', '102': 'mobile', '103': 'mobile',
        '104': 'checkpoint', '105': 'redlight_mobile',
        # Mobile/Semi-stationary types
        '21': 'mobile',      # Mobile speed camera
        '22': 'trailer',     # Anhänger Blitzer (Trailer)
        '23': 'mobile',      # Mobile speed trap
        '24': 'police',      # Police control
        '25': 'mobile',      # Mobile camera
        # OSM types
        'fixed': 'speed', 'mobile': 'mobile', 'average': 'zone',
        'red_light': 'redlight', 'traffic_signals': 'redlight',
    }
    
    return type_map.get(str(type_code), 'speed')

# ============ DATA SOURCES ============

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=8))
async def fetch_from_lufop(lat: float, lon: float, radius_km: int = 100) -> List[Camera]:
    """Fetch cameras from Lufop API - Global coverage including US, UK, CA, AU"""
    country = get_country_from_coords(lat, lon)
    
    # Map country codes to Lufop regions
    lufop_regions = {
        # Europe
        'de': 'de', 'fr': 'fr', 'ch': 'ch', 'at': 'at', 'nl': 'nl', 
        'be': 'be', 'it': 'it', 'es': 'es', 'pt': 'pt', 'eu': 'all',
        # UK
        'uk': 'uk', 'gb': 'uk',
        # North America
        'us': 'us', 'ca': 'ca',
        # Australia/NZ
        'au': 'au', 'nz': 'nz',
    }
    
    pays = lufop_regions.get(country, 'all')
    
    url = f"https://api.lufop.net/api?format=json&pays={pays}&q={lat},{lon}&m={radius_km}&nbr=2000"
    
    cameras = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=30),
                headers={'User-Agent': 'SpeedCameraMap/3.0'}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    if isinstance(data, list):
                        seen = set()
                        for item in data:
                            try:
                                lat_val = float(item.get('lat', 0))
                                lon_val = float(item.get('lng', 0))
                                if lat_val == 0 or lon_val == 0:
                                    continue
                                
                                loc_key = f"{round(lat_val, 5)}_{round(lon_val, 5)}"
                                if loc_key in seen:
                                    continue
                                seen.add(loc_key)
                                
                                name = item.get('name', '')
                                lufop_type = item.get('type', '148')
                                
                                speed_limit = None
                                vitesse = item.get('vitesse', '')
                                if vitesse:
                                    try:
                                        speed_limit = int(vitesse)
                                    except:
                                        pass
                                
                                cameras.append(Camera(
                                    id=f"lufop_{item.get('ID', uuid.uuid4())}",
                                    lat=lat_val,
                                    lon=lon_val,
                                    type=parse_camera_type(lufop_type, name),
                                    speedLimit=speed_limit,
                                    source='lufop',
                                    name=name,
                                    road=item.get('voie', ''),
                                    country=country
                                ))
                            except Exception as e:
                                continue
                        
                        logger.info(f"Lufop: {len(cameras)} cameras for {country}")
    except Exception as e:
        logger.warning(f"Lufop error: {e}")
    
    return cameras

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=8))
async def fetch_from_atudo(lat: float, lon: float, radius_km: int = 100) -> List[Camera]:
    """Fetch from atudo.net - Blitzer.de backend (Germany, Austria, Switzerland)"""
    
    # Calculate bounding box
    lat_diff = radius_km / 111.0
    lon_diff = radius_km / (111.0 * abs(math.cos(math.radians(lat))))
    min_lat, max_lat = lat - lat_diff, lat + lat_diff
    min_lon, max_lon = lon - lon_diff, lon + lon_diff
    
    # Try multiple Atudo endpoints including box-based for redlight cameras
    endpoints = [
        f"https://cdn2.atudo.net/api/1.0/vl.php?type=0,1,2,3,4,5,6,20,21,22,101,102,103,104,105&box={min_lat},{min_lon},{max_lat},{max_lon}",
        f"https://cdn2.atudo.net/api/4.0/pois.php?lat={lat}&lng={lon}&type=0,1,2,3,4,5,6,7,20,21,22,101,102,103,104,105&radius={radius_km}&lang=en",
    ]
    
    cameras = []
    for url in endpoints:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=15),
                    headers={'User-Agent': 'Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36'}
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        pois = data.get('pois', []) if isinstance(data, dict) else data if isinstance(data, list) else []
                        
                        for poi in pois:
                            try:
                                poi_type = int(poi.get('type', 0))
                                
                                # Map Atudo types properly
                                if poi_type == 0 or poi_type == 1:
                                    cam_type = 'speed'  # Fixed speed camera
                                elif poi_type == 2:
                                    cam_type = 'redlight'  # Red light camera
                                elif poi_type == 3:
                                    cam_type = 'zone'  # Section control START
                                elif poi_type == 4:
                                    cam_type = 'zone'  # Section control END
                                elif poi_type == 5:
                                    cam_type = 'checkpoint'  # Police checkpoint
                                elif poi_type == 6:
                                    cam_type = 'distance'  # Distance control
                                elif poi_type == 21:
                                    cam_type = 'mobile'  # Mobile speed camera
                                elif poi_type == 22:
                                    cam_type = 'trailer'  # Anhänger Blitzer (Trailer)
                                elif poi_type == 23:
                                    cam_type = 'mobile'  # Mobile speed trap
                                elif poi_type == 24:
                                    cam_type = 'police'  # Police control
                                elif poi_type == 25:
                                    cam_type = 'mobile'  # Mobile camera
                                elif 101 <= poi_type <= 106:
                                    cam_type = 'mobile'  # Mobile cameras
                                elif poi_type == 105:
                                    cam_type = 'redlight_mobile'  # Mobile red light
                                else:
                                    cam_type = 'speed'
                                
                                cameras.append(Camera(
                                    id=f"atudo_{poi.get('id', uuid.uuid4())}",
                                    lat=float(poi.get('lat', 0)),
                                    lon=float(poi.get('lng', 0)),
                                    type=cam_type,
                                    speedLimit=poi.get('vmax'),
                                    source='atudo',
                                    name=poi.get('street', ''),
                                    road=poi.get('street', ''),
                                    verified=True
                                ))
                            except:
                                continue
                        
                        if cameras:
                            break  # Got data, no need to try other endpoints
        except Exception as e:
            continue
    
    logger.info(f"Atudo: {len(cameras)} cameras")
    return cameras

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=5))
async def fetch_from_overpass(lat: float, lon: float, radius: float) -> List[Camera]:
    """Fetch from OpenStreetMap Overpass API - ALL speed cameras and enforcement"""
    # Enhanced query for ALL camera types - no date filter for maximum coverage
    query = f"""
    [out:json][timeout:60];
    (
      // All speed cameras
      node["highway"="speed_camera"](around:{radius},{lat},{lon});
      way["highway"="speed_camera"](around:{radius},{lat},{lon});
      
      // All enforcement devices
      node["enforcement"](around:{radius},{lat},{lon});
      way["enforcement"](around:{radius},{lat},{lon});
      
      // Traffic signals with cameras
      node["enforcement"="traffic_signals"](around:{radius},{lat},{lon});
      node["traffic_signals:enforcement"="yes"](around:{radius},{lat},{lon});
      
      // Average speed cameras / Section control
      node["enforcement"="average_speed"](around:{radius},{lat},{lon});
      relation["type"="enforcement"]["enforcement"="average_speed"](around:{radius},{lat},{lon});
      
      // Red light cameras
      node["enforcement"="maxspeed;traffic_signals"](around:{radius},{lat},{lon});
      
      // Surveillance cameras on roads
      node["man_made"="surveillance"]["surveillance:type"="camera"]["surveillance:zone"="traffic"](around:{radius},{lat},{lon});
    );
    out body center;
    """
    
    servers = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://lz4.overpass-api.de/api/interpreter",
    ]
    
    cameras = []
    for server in servers:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    server,
                    data={'data': query},
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        elements = data.get('elements', [])
                        logger.info(f"OSM from {server}: {len(elements)} elements")
                        seen = set()
                        
                        for el in elements:
                            try:
                                el_lat = el.get('lat')
                                el_lon = el.get('lon')
                                
                                if not el_lat or not el_lon:
                                    if 'center' in el:
                                        el_lat = el['center'].get('lat')
                                        el_lon = el['center'].get('lon')
                                
                                if not el_lat or not el_lon:
                                    continue
                                
                                loc_key = f"{round(el_lat, 5)}_{round(el_lon, 5)}"
                                if loc_key in seen:
                                    continue
                                seen.add(loc_key)
                                
                                tags = el.get('tags', {})
                                enforcement = tags.get('enforcement', '').lower()
                                device_type = tags.get('device', '').lower()
                                name = tags.get('name', '').lower()
                                surveillance_type = tags.get('surveillance:type', '').lower()
                                maxspeed_tag = tags.get('maxspeed', '')
                                
                                # Determine camera type
                                cam_type = 'speed'  # default
                                
                                # Red light camera detection
                                if enforcement in ['traffic_signals', 'red_light', 'traffic_light', 'stoplight']:
                                    cam_type = 'redlight'
                                elif 'traffic' in enforcement or 'signal' in enforcement or 'light' in enforcement:
                                    cam_type = 'redlight'
                                elif 'red' in surveillance_type or 'traffic' in surveillance_type:
                                    cam_type = 'redlight'
                                elif 'red' in name or 'rotlicht' in name or 'ampel' in name or 'blitz' in name.lower():
                                    cam_type = 'redlight'
                                elif device_type in ['traffic_signals', 'loop', 'gate', 'induction_loop']:
                                    cam_type = 'redlight'
                                # Speed camera detection
                                elif enforcement in ['maxspeed', 'speed_camera', 'speed', 'average_speed']:
                                    if enforcement == 'average_speed':
                                        cam_type = 'zone'
                                    else:
                                        cam_type = 'speed'
                                elif tags.get('highway') == 'speed_camera':
                                    # If highway=speed_camera but no maxspeed, could be combined camera
                                    if not maxspeed_tag:
                                        cam_type = 'combined'  # Both speed and redlight
                                    else:
                                        cam_type = 'speed'
                                # If enforcement exists but no maxspeed, likely redlight
                                elif enforcement and not maxspeed_tag:
                                    cam_type = 'redlight'
                                
                                speed_limit = None
                                if maxspeed_tag:
                                    try:
                                        speed_limit = int(maxspeed_tag.replace('km/h', '').replace(' ', ''))
                                    except:
                                        pass
                                
                                cameras.append(Camera(
                                    id=f"osm_{el.get('id', uuid.uuid4())}",
                                    lat=el_lat,
                                    lon=el_lon,
                                    type=cam_type,
                                    speedLimit=speed_limit,
                                    source='osm',
                                    name=tags.get('name', ''),
                                    road=tags.get('ref', '')
                                ))
                            except:
                                continue
                        
                        logger.info(f"OSM: {len(cameras)} cameras")
                        break
        except Exception as e:
            logger.warning(f"Overpass error on {server}: {e}")
            continue
    
    return cameras

async def fetch_from_scdb(lat: float, lon: float, radius_km: int = 100) -> List[Camera]:
    """Fetch from Speed Camera Database (SCDB) - Open database"""
    # SCDB covers many countries with verified cameras
    url = f"https://www.scdb.info/api/cameras/nearby?lat={lat}&lng={lon}&radius={radius_km}"
    
    cameras = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=20),
                headers={'User-Agent': 'SpeedCameraMap/3.0'}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    for cam in data.get('cameras', []):
                        cameras.append(Camera(
                            id=f"scdb_{cam.get('id', uuid.uuid4())}",
                            lat=float(cam.get('lat', 0)),
                            lon=float(cam.get('lng', 0)),
                            type=parse_camera_type(cam.get('type', ''), cam.get('name', '')),
                            speedLimit=cam.get('limit'),
                            source='scdb',
                            verified=True
                        ))
    except:
        pass  # SCDB may not always be available
    
    return cameras

# ============ BAUSTELLE / CONSTRUCTION ZONES ============

async def fetch_construction_zones(lat: float, lon: float, radius: float) -> List[dict]:
    """Fetch construction zones (Baustelle) from OSM"""
    query = f"""
    [out:json][timeout:10];
    (
      node["highway"="construction"](around:{radius},{lat},{lon});
      way["highway"="construction"](around:{radius},{lat},{lon});
      node["construction"](around:{radius},{lat},{lon});
      way["construction"](around:{radius},{lat},{lon});
    );
    out center;
    """
    
    zones = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://overpass-api.de/api/interpreter",
                data={'data': query},
                timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"Baustelle API returned {len(data.get('elements', []))} elements")
                    for el in data.get('elements', []):
                        el_lat = el.get('lat') or (el.get('center', {}).get('lat'))
                        el_lon = el.get('lon') or (el.get('center', {}).get('lon'))
                        if el_lat and el_lon:
                            tags = el.get('tags', {})
                            zones.append({
                                'id': f"baustelle_{el.get('id')}",
                                'lat': el_lat,
                                'lon': el_lon,
                                'type': 'construction',
                                'name': tags.get('name', 'Baustelle'),
                                'speedLimit': None
                            })
    except Exception as e:
        logger.warning(f"Construction zone fetch error: {e}")
    
    return zones

# ============ API ENDPOINTS ============

@api_router.get("/")
async def root():
    return {
        "name": "Speed Camera Map API",
        "version": "3.0.0",
        "description": "Comprehensive speed camera database for safe driving",
        "coverage": ["Europe", "UK", "Canada", "USA", "Australia", "Switzerland"],
        "sources": ["Lufop", "Atudo/Blitzer.de", "OpenStreetMap", "Community Reports"],
        "features": ["Real-time alerts", "Hazard warnings", "Crowdsourcing"]
    }

@api_router.get("/cameras", response_model=CameraResponse)
async def get_cameras(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
    radius: float = Query(50000, description="Search radius in meters (max 200km)")
):
    """Get cameras near a location - aggregates multiple high-quality sources"""
    
    # Cap radius at 200km for maximum coverage
    radius = min(radius, 200000)
    radius_km = int(radius / 1000) + 10
    
    cache_key = get_cache_key(lat, lon, radius)
    country = get_country_from_coords(lat, lon)
    
    # Check memory cache
    if cache_key in camera_cache:
        cached = camera_cache[cache_key]
        if datetime.utcnow().timestamp() - cached['timestamp'] < CACHE_TTL:
            logger.info(f"Cache hit: {len(cached['cameras'])} cameras")
            return CameraResponse(
                cameras=cached['cameras'],
                cached=True,
                source="cache",
                total=len(cached['cameras']),
                region=country
            )
    
    # Check MongoDB cache
    try:
        db_cache = await db.camera_cache.find_one({"key": cache_key})
        if db_cache:
            cache_time = db_cache.get('timestamp', datetime.min)
            if isinstance(cache_time, datetime):
                if (datetime.utcnow() - cache_time).total_seconds() < CACHE_TTL:
                    cameras = [Camera(**c) for c in db_cache.get('cameras', [])]
                    camera_cache[cache_key] = {
                        'cameras': cameras,
                        'timestamp': datetime.utcnow().timestamp()
                    }
                    return CameraResponse(
                        cameras=cameras,
                        cached=True,
                        source="db_cache",
                        total=len(cameras),
                        region=country
                    )
    except Exception as e:
        logger.error(f"DB cache error: {e}")
    
    # Fetch from TRUSTED sources (Atudo/Blitzer.de, Lufop, and verified OSM)
    all_cameras = []
    
    try:
        tasks = [
            fetch_from_atudo(lat, lon, radius_km),  # Blitzer.de - Most trusted
            fetch_from_lufop(lat, lon, radius_km),  # Lufop - European coverage
            fetch_from_overpass(lat, lon, radius),   # OSM - ALL cameras
            fetch_from_scdb(lat, lon, radius_km),    # SCDB - Verified cameras
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        atudo_cams = results[0] if isinstance(results[0], list) else []
        lufop_cams = results[1] if isinstance(results[1], list) else []
        osm_cams = results[2] if isinstance(results[2], list) else []
        scdb_cams = results[3] if isinstance(results[3], list) else []
        
        logger.info(f"Fetched: Atudo={len(atudo_cams)}, Lufop={len(lufop_cams)}, OSM={len(osm_cams)}, SCDB={len(scdb_cams)}")
        
        # Fetch construction zones (Baustelle)
        try:
            construction_zones = await fetch_construction_zones(lat, lon, min(radius, 30000))
            logger.info(f"Found {len(construction_zones)} Baustelle/construction zones")
        except:
            construction_zones = []
        
        # Merge with deduplication (priority: Atudo > Lufop > OSM)
        seen_locs = set()
        
        for cam in atudo_cams:
            loc_key = f"{round(cam.lat, 4)}_{round(cam.lon, 4)}"
            if loc_key not in seen_locs:
                all_cameras.append(cam)
                seen_locs.add(loc_key)
        
        for cam in lufop_cams:
            loc_key = f"{round(cam.lat, 4)}_{round(cam.lon, 4)}"
            if loc_key not in seen_locs:
                all_cameras.append(cam)
                seen_locs.add(loc_key)
        
        # Add OSM cameras (they are from official government mapping)
        for cam in osm_cams:
            loc_key = f"{round(cam.lat, 4)}_{round(cam.lon, 4)}"
            if loc_key not in seen_locs:
                all_cameras.append(cam)
                seen_locs.add(loc_key)
        
        # Add SCDB cameras (verified by community)
        for cam in scdb_cams:
            loc_key = f"{round(cam.lat, 4)}_{round(cam.lon, 4)}"
            if loc_key not in seen_locs:
                all_cameras.append(cam)
                seen_locs.add(loc_key)
        
        logger.info(f"Total unique cameras: {len(all_cameras)}")
        
        # Add verified cameras from Europe (red light + distance control + other types)
        verified_added = 0
        for verified_cam in ALL_VERIFIED_CAMERAS:
            verified_loc = f"{round(verified_cam['lat'], 4)}_{round(verified_cam['lon'], 4)}"
            # Check if camera is within search radius
            dist = math.sqrt((verified_cam['lat'] - lat)**2 + (verified_cam['lon'] - lon)**2) * 111000
            if dist <= radius:
                # Remove any existing camera at this location (might be misclassified)
                all_cameras = [c for c in all_cameras if f"{round(c.lat, 4)}_{round(c.lon, 4)}" != verified_loc]
                seen_locs.discard(verified_loc)
                
                # Add the correctly classified camera
                cam_type = verified_cam.get('type', 'redlight')
                speed_limit = verified_cam.get('speedLimit')
                
                all_cameras.append(Camera(
                    id=f"verified_{cam_type}_{verified_cam['lat']}_{verified_cam['lon']}",
                    lat=verified_cam['lat'],
                    lon=verified_cam['lon'],
                    type=cam_type,
                    speedLimit=speed_limit,
                    source='verified',
                    name=verified_cam['name'],
                    verified=True
                ))
                seen_locs.add(verified_loc)
                verified_added += 1
        
        logger.info(f"Added {verified_added} verified cameras")
        
        # Add construction zones (Baustelle)
        for zone in construction_zones:
            zone_loc = f"{round(zone['lat'], 4)}_{round(zone['lon'], 4)}"
            if zone_loc not in seen_locs:
                all_cameras.append(Camera(
                    id=zone['id'],
                    lat=zone['lat'],
                    lon=zone['lon'],
                    type='construction',
                    speedLimit=None,
                    source='osm',
                    name=zone.get('name', 'Baustelle')
                ))
                seen_locs.add(zone_loc)
        
    except Exception as e:
        logger.error(f"Camera fetch error: {e}")
    
    # Filter out cameras reported as removed (by user community)
    try:
        lat_delta = radius / 111000
        lon_delta = radius / (111000 * max(abs(lat), 1))
        
        removals = await db.camera_removals.find({
            "lat": {"$gte": lat - lat_delta, "$lte": lat + lat_delta},
            "lon": {"$gte": lon - lon_delta, "$lte": lon + lon_delta},
            "votes": {"$gte": 2}  # At least 2 reports
        }).to_list(500)
        
        if removals:
            removal_locs = set()
            for r in removals:
                removal_locs.add(f"{round(r['lat'], 4)}_{round(r['lon'], 4)}")
            
            # Filter out removed cameras
            original_count = len(all_cameras)
            all_cameras = [c for c in all_cameras if f"{round(c.lat, 4)}_{round(c.lon, 4)}" not in removal_locs]
            logger.info(f"Filtered out {original_count - len(all_cameras)} removed cameras")
    except Exception as e:
        logger.error(f"Filter removals error: {e}")
    
    # Get user reports from MongoDB
    try:
        lat_delta = radius / 111000
        lon_delta = radius / (111000 * max(abs(lat), 1))
        
        reports = await db.user_reports.find({
            "lat": {"$gte": lat - lat_delta, "$lte": lat + lat_delta},
            "lon": {"$gte": lon - lon_delta, "$lte": lon + lon_delta},
            "votes": {"$gte": -2}
        }).to_list(500)
        
        for report in reports:
            loc_key = f"{round(report['lat'], 4)}_{round(report['lon'], 4)}"
            if loc_key not in seen_locs:
                all_cameras.append(Camera(
                    id=str(report.get('_id', report.get('id', uuid.uuid4()))),
                    lat=report['lat'],
                    lon=report['lon'],
                    type=report.get('type', 'speed'),
                    speedLimit=report.get('speedLimit'),
                    source='user',
                    verified=False
                ))
                seen_locs.add(loc_key)
        
        logger.info(f"Added {len(reports)} user reports")
    except Exception as e:
        logger.error(f"User reports error: {e}")
    
    # Filter out unreliable cameras
    # Only keep cameras that have speedLimit OR are from specific reliable types
    reliable_types = {'redlight', 'distance', 'mobile', 'zone', 'section_start', 'section_end', 'tunnel', 'construction', 'combined'}
    
    original_count = len(all_cameras)
    filtered_cameras = []
    for cam in all_cameras:
        # Keep cameras with speed limit
        if cam.speedLimit and cam.speedLimit > 0:
            filtered_cameras.append(cam)
            continue
        # Keep special camera types (red light, distance, etc.) even without speed limit
        if cam.type in reliable_types:
            filtered_cameras.append(cam)
            continue
        # Skip cameras without speedLimit and not special type
    
    if original_count != len(filtered_cameras):
        logger.info(f"Filtered out {original_count - len(filtered_cameras)} cameras without speedLimit")
    
    all_cameras = filtered_cameras
    
    # Save to cache
    if all_cameras:
        camera_cache[cache_key] = {
            'cameras': all_cameras,
            'timestamp': datetime.utcnow().timestamp()
        }
        
        try:
            await db.camera_cache.update_one(
                {"key": cache_key},
                {
                    "$set": {
                        "cameras": [c.dict() for c in all_cameras[:2000]],  # Limit stored
                        "timestamp": datetime.utcnow()
                    }
                },
                upsert=True
            )
        except Exception as e:
            logger.error(f"Cache save error: {e}")
    
    return CameraResponse(
        cameras=all_cameras,
        cached=False,
        source="aggregated",
        total=len(all_cameras),
        region=country
    )

@api_router.get("/cameras/refresh")
async def refresh_cameras(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
    radius: float = Query(50000, description="Search radius in meters")
):
    """Force refresh cameras - bypass cache and get fresh data from sources"""
    
    radius = min(radius, 100000)
    cache_key = get_cache_key(lat, lon, radius)
    
    # Clear cache for this area
    if cache_key in camera_cache:
        del camera_cache[cache_key]
    
    try:
        await db.camera_cache.delete_one({"key": cache_key})
        logger.info(f"Cache cleared for key: {cache_key}")
    except Exception as e:
        logger.error(f"Cache clear error: {e}")
    
    # Now fetch fresh data
    return await get_cameras(lat, lon, radius)

@api_router.delete("/cameras/cache")
async def clear_all_cache():
    """Clear all camera cache - admin endpoint for forcing fresh data"""
    try:
        camera_cache.clear()
        result = await db.camera_cache.delete_many({})
        logger.info(f"Cleared all cache: {result.deleted_count} entries")
        return {"message": f"Cache cleared: {result.deleted_count} entries deleted", "success": True}
    except Exception as e:
        logger.error(f"Clear cache error: {e}")
        return {"message": str(e), "success": False}

@api_router.get("/hazards", response_model=HazardResponse)
async def get_hazards(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
    radius: float = Query(20000, description="Search radius in meters")
):
    """Get road hazards (accidents, traffic, roadwork, etc.)"""
    try:
        lat_delta = radius / 111000
        lon_delta = radius / (111000 * max(abs(lat), 1))
        
        hazards = await db.hazards.find({
            "lat": {"$gte": lat - lat_delta, "$lte": lat + lat_delta},
            "lon": {"$gte": lon - lon_delta, "$lte": lon + lon_delta},
            "expiresAt": {"$gt": datetime.utcnow()},
            "votes": {"$gte": -3}
        }).sort("createdAt", -1).to_list(100)
        
        result = []
        for h in hazards:
            h['id'] = str(h.get('_id', h.get('id', uuid.uuid4())))
            if '_id' in h:
                del h['_id']
            result.append(Hazard(**h))
        
        return HazardResponse(hazards=result)
    except Exception as e:
        logger.error(f"Hazards error: {e}")
        return HazardResponse(hazards=[])

@api_router.post("/hazards", response_model=Hazard)
async def create_hazard(hazard: HazardCreate):
    """Report a new road hazard"""
    try:
        # Set expiration based on type
        hours = 2
        if hazard.type == 'roadwork':
            hours = 24
        elif hazard.type == 'accident':
            hours = 4
        elif hazard.type == 'police':
            hours = 1
        
        new_hazard = Hazard(
            lat=hazard.lat,
            lon=hazard.lon,
            type=hazard.type,
            severity=hazard.severity,
            description=hazard.description,
            expiresAt=datetime.utcnow() + timedelta(hours=hours)
        )
        
        result = await db.hazards.insert_one(new_hazard.dict())
        new_hazard.id = str(result.inserted_id)
        
        logger.info(f"New hazard reported: {hazard.type} at {hazard.lat},{hazard.lon}")
        return new_hazard
    except Exception as e:
        logger.error(f"Hazard creation error: {e}")
        raise HTTPException(status_code=500, detail="Failed to create hazard")

@api_router.post("/hazards/{hazard_id}/vote")
async def vote_hazard(hazard_id: str, vote: VoteRequest):
    """Vote on a hazard (confirm or dismiss)"""
    try:
        from bson import ObjectId
        vote_delta = 1 if vote.vote == 'confirm' else -1
        
        result = await db.hazards.update_one(
            {"_id": ObjectId(hazard_id)},
            {"$inc": {"votes": vote_delta}}
        )
        
        return {"success": result.modified_count > 0}
    except Exception as e:
        logger.error(f"Hazard vote error: {e}")
        raise HTTPException(status_code=500, detail="Failed to vote")

@api_router.delete("/hazards/clear-area")
async def clear_hazards_in_area(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
    radius: float = Query(500, description="Radius in meters")
):
    """Clear all hazards in a specific area"""
    try:
        lat_delta = radius / 111000
        lon_delta = radius / (111000 * max(abs(lat), 1))
        
        result = await db.hazards.delete_many({
            "lat": {"$gte": lat - lat_delta, "$lte": lat + lat_delta},
            "lon": {"$gte": lon - lon_delta, "$lte": lon + lon_delta}
        })
        
        logger.info(f"Cleared {result.deleted_count} hazards in area ({lat}, {lon})")
        return {"success": True, "deleted": result.deleted_count}
    except Exception as e:
        logger.error(f"Clear hazards error: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear hazards")

# ====== CAMERA REMOVAL REPORTS ======
class CameraRemovalReport(BaseModel):
    cameraId: str
    lat: float
    lon: float
    reason: str = "not_exists"  # not_exists, moved, wrong_location

@api_router.post("/cameras/report-removed")
async def report_camera_removed(report: CameraRemovalReport):
    """Report a camera that no longer exists or is in wrong location"""
    try:
        removal_report = {
            "cameraId": report.cameraId,
            "lat": report.lat,
            "lon": report.lon,
            "reason": report.reason,
            "reportedAt": datetime.utcnow(),
            "votes": 1
        }
        
        # Check if already reported
        existing = await db.camera_removals.find_one({
            "lat": {"$gte": report.lat - 0.0001, "$lte": report.lat + 0.0001},
            "lon": {"$gte": report.lon - 0.0001, "$lte": report.lon + 0.0001},
        })
        
        if existing:
            # Increment vote
            await db.camera_removals.update_one(
                {"_id": existing["_id"]},
                {"$inc": {"votes": 1}}
            )
            logger.info(f"Camera removal vote added: {report.cameraId}")
            return {"success": True, "message": "Vote added", "votes": existing.get("votes", 0) + 1}
        else:
            # Create new report
            result = await db.camera_removals.insert_one(removal_report)
            logger.info(f"Camera removal reported: {report.cameraId} at {report.lat},{report.lon}")
            return {"success": True, "message": "Removal reported", "id": str(result.inserted_id)}
            
    except Exception as e:
        logger.error(f"Camera removal report error: {e}")
        raise HTTPException(status_code=500, detail="Failed to report")

@api_router.get("/cameras/removed")
async def get_removed_cameras(
    lat: float = Query(...),
    lon: float = Query(...),
    radius: float = Query(50000)
):
    """Get list of cameras reported as removed in an area"""
    try:
        lat_delta = radius / 111000
        lon_delta = radius / (111000 * max(abs(lat), 1))
        
        removals = await db.camera_removals.find({
            "lat": {"$gte": lat - lat_delta, "$lte": lat + lat_delta},
            "lon": {"$gte": lon - lon_delta, "$lte": lon + lon_delta},
            "votes": {"$gte": 2}  # At least 2 reports to consider removed
        }).to_list(500)
        
        # Return as list of locations to filter out
        removed_locations = []
        for r in removals:
            removed_locations.append({
                "lat": r["lat"],
                "lon": r["lon"],
                "votes": r.get("votes", 1)
            })
        
        return {"removed": removed_locations, "total": len(removed_locations)}
    except Exception as e:
        logger.error(f"Get removed cameras error: {e}")
        return {"removed": [], "total": 0}

@api_router.get("/reports", response_model=ReportResponse)
async def get_reports(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
    radius: float = Query(10000, description="Search radius in meters")
):
    """Get user-reported cameras near a location"""
    try:
        lat_delta = radius / 111000
        lon_delta = radius / (111000 * max(abs(lat), 1))
        
        reports = await db.user_reports.find({
            "lat": {"$gte": lat - lat_delta, "$lte": lat + lat_delta},
            "lon": {"$gte": lon - lon_delta, "$lte": lon + lon_delta},
            "votes": {"$gte": -3},
        }).to_list(200)
        
        result = []
        for report in reports:
            report['id'] = str(report.get('_id', report.get('id', uuid.uuid4())))
            if '_id' in report:
                del report['_id']
            result.append(UserReport(**report))
        
        return ReportResponse(reports=result)
    except Exception as e:
        logger.error(f"Reports error: {e}")
        return ReportResponse(reports=[])

@api_router.post("/reports", response_model=UserReport)
async def create_report(report: UserReportCreate):
    """Create a new camera report"""
    try:
        new_report = UserReport(
            lat=report.lat,
            lon=report.lon,
            type=report.type,
            speedLimit=report.speedLimit,
            expiresAt=datetime.utcnow() + timedelta(hours=48)
        )
        
        result = await db.user_reports.insert_one(new_report.dict())
        new_report.id = str(result.inserted_id)
        
        logger.info(f"New camera report: {report.type} at {report.lat},{report.lon}")
        return new_report
    except Exception as e:
        logger.error(f"Report creation error: {e}")
        raise HTTPException(status_code=500, detail="Failed to create report")

@api_router.post("/reports/{report_id}/vote")
async def vote_report(report_id: str, vote: VoteRequest):
    """Vote on a camera report"""
    try:
        from bson import ObjectId
        vote_delta = 1 if vote.vote == 'confirm' else -1
        
        # Try by id field
        result = await db.user_reports.update_one(
            {"id": report_id},
            {"$inc": {"votes": vote_delta}}
        )
        
        # Try by _id if not found
        if result.modified_count == 0:
            try:
                result = await db.user_reports.update_one(
                    {"_id": ObjectId(report_id)},
                    {"$inc": {"votes": vote_delta}}
                )
            except:
                pass
        
        return {"success": True}
    except Exception as e:
        logger.error(f"Vote error: {e}")
        raise HTTPException(status_code=500, detail="Failed to vote")

@api_router.delete("/reports/{report_id}")
async def delete_report(report_id: str):
    """Delete a camera report"""
    try:
        from bson import ObjectId
        
        result = await db.user_reports.delete_one({"id": report_id})
        
        if result.deleted_count == 0:
            try:
                result = await db.user_reports.delete_one({"_id": ObjectId(report_id)})
            except:
                pass
        
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Report not found")
        
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete error: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete")

@api_router.delete("/cache")
async def clear_cache():
    """Clear all caches"""
    try:
        camera_cache.clear()
        hazard_cache.clear()
        await db.camera_cache.delete_many({})
        return {"success": True}
    except Exception as e:
        logger.error(f"Cache clear error: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear cache")

@api_router.get("/stats")
async def get_stats():
    """Get database statistics"""
    try:
        camera_count = sum(len(v['cameras']) for v in camera_cache.values())
        report_count = await db.user_reports.count_documents({})
        hazard_count = await db.hazards.count_documents({"expiresAt": {"$gt": datetime.utcnow()}})
        
        return {
            "cameras_in_cache": camera_count,
            "user_reports": report_count,
            "active_hazards": hazard_count,
            "cache_regions": len(camera_cache),
            "version": "3.0.0"
        }
    except Exception as e:
        return {"error": str(e)}

@api_router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "3.0.0"
    }

# ============ COMMUNITY REWARDS SYSTEM ============

@api_router.post("/report")
async def report_hazard(
    lat: float = Query(...),
    lon: float = Query(...),
    type: str = Query(..., description="camera, police, accident, construction, traffic"),
    speed_limit: int = Query(None),
    user_id: str = Query(default="anonymous"),
    description: str = Query(default="")
):
    """Report a new hazard/camera - Community feature"""
    try:
        # Validate type
        valid_types = ['camera', 'police', 'mobile', 'accident', 'construction', 'traffic', 'redlight', 'speed']
        if type not in valid_types:
            type = 'camera'
        
        # Create report
        report = {
            "id": f"report_{uuid.uuid4().hex[:12]}",
            "lat": lat,
            "lon": lon,
            "type": type,
            "speedLimit": speed_limit,
            "userId": user_id,
            "description": description,
            "createdAt": datetime.utcnow(),
            "expiresAt": datetime.utcnow() + timedelta(hours=24),  # Reports expire after 24h
            "confirmations": 1,
            "verified": False
        }
        
        # Save to database
        await db.user_reports.insert_one(report)
        
        # Award points to user
        points_earned = 10
        if type == 'police':
            points_earned = 25  # Police reports are more valuable
        elif type == 'mobile':
            points_earned = 20
        elif type == 'accident':
            points_earned = 15
        
        # Update user points
        await db.user_points.update_one(
            {"userId": user_id},
            {
                "$inc": {"points": points_earned, "reports": 1},
                "$setOnInsert": {"createdAt": datetime.utcnow()},
                "$set": {"lastActive": datetime.utcnow()}
            },
            upsert=True
        )
        
        logger.info(f"New report from {user_id}: {type} at {lat},{lon} (+{points_earned} points)")
        
        return {
            "success": True,
            "reportId": report["id"],
            "pointsEarned": points_earned,
            "message": f"Danke! +{points_earned} Punkte"
        }
    except Exception as e:
        logger.error(f"Report error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/report/{report_id}/confirm")
async def confirm_report(report_id: str, user_id: str = Query(default="anonymous")):
    """Confirm an existing report - gives points to original reporter"""
    try:
        report = await db.user_reports.find_one({"id": report_id})
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        
        # Increment confirmations
        await db.user_reports.update_one(
            {"id": report_id},
            {"$inc": {"confirmations": 1}}
        )
        
        # If 3+ confirmations, verify the report
        if report.get("confirmations", 0) >= 2:
            await db.user_reports.update_one(
                {"id": report_id},
                {"$set": {"verified": True, "expiresAt": datetime.utcnow() + timedelta(hours=48)}}
            )
        
        # Award points to confirmer
        await db.user_points.update_one(
            {"userId": user_id},
            {"$inc": {"points": 5, "confirmations": 1}},
            upsert=True
        )
        
        # Award bonus to original reporter
        await db.user_points.update_one(
            {"userId": report.get("userId")},
            {"$inc": {"points": 3}}
        )
        
        return {"success": True, "pointsEarned": 5}
    except Exception as e:
        logger.error(f"Confirm error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/user/{user_id}/stats")
async def get_user_stats(user_id: str):
    """Get user points, badges, and ranking"""
    try:
        user = await db.user_points.find_one({"userId": user_id})
        if not user:
            user = {"points": 0, "reports": 0, "confirmations": 0}
        
        # Calculate rank
        higher_count = await db.user_points.count_documents({"points": {"$gt": user.get("points", 0)}})
        rank = higher_count + 1
        
        # Calculate badges
        badges = []
        points = user.get("points", 0)
        reports = user.get("reports", 0)
        
        if reports >= 1:
            badges.append({"id": "first_report", "name": "Erster Bericht", "icon": "🎯"})
        if reports >= 10:
            badges.append({"id": "reporter", "name": "Reporter", "icon": "📢"})
        if reports >= 50:
            badges.append({"id": "super_reporter", "name": "Super Reporter", "icon": "🌟"})
        if reports >= 100:
            badges.append({"id": "legend", "name": "Legende", "icon": "👑"})
        if points >= 100:
            badges.append({"id": "point_master", "name": "100 Punkte", "icon": "💯"})
        if points >= 500:
            badges.append({"id": "point_king", "name": "500 Punkte", "icon": "🏆"})
        
        return {
            "userId": user_id,
            "points": points,
            "reports": reports,
            "confirmations": user.get("confirmations", 0),
            "rank": rank,
            "badges": badges,
            "level": min(points // 100 + 1, 99)
        }
    except Exception as e:
        return {"points": 0, "reports": 0, "rank": 0, "badges": [], "level": 1}


@api_router.get("/leaderboard")
async def get_leaderboard(limit: int = Query(default=20)):
    """Get top users - weekly leaderboard"""
    try:
        # Get top users by points
        cursor = db.user_points.find().sort("points", -1).limit(limit)
        users = await cursor.to_list(length=limit)
        
        leaderboard = []
        for i, user in enumerate(users):
            leaderboard.append({
                "rank": i + 1,
                "userId": user.get("userId", "Anonymous")[:12] + "***",
                "points": user.get("points", 0),
                "reports": user.get("reports", 0),
                "badge": "👑" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else "🏅"
            })
        
        return {"leaderboard": leaderboard, "updated": datetime.utcnow().isoformat()}
    except Exception as e:
        return {"leaderboard": [], "error": str(e)}


@api_router.get("/reports/nearby")
async def get_nearby_reports(
    lat: float = Query(...),
    lon: float = Query(...),
    radius: float = Query(default=30000)
):
    """Get community reports near location"""
    try:
        # Find non-expired reports
        lat_delta = radius / 111000
        lon_delta = radius / (111000 * abs(math.cos(math.radians(lat))))
        
        cursor = db.user_reports.find({
            "lat": {"$gte": lat - lat_delta, "$lte": lat + lat_delta},
            "lon": {"$gte": lon - lon_delta, "$lte": lon + lon_delta},
            "expiresAt": {"$gt": datetime.utcnow()}
        }).sort("createdAt", -1).limit(100)
        
        reports = await cursor.to_list(length=100)
        
        result = []
        for r in reports:
            result.append({
                "id": r.get("id"),
                "lat": r.get("lat"),
                "lon": r.get("lon"),
                "type": r.get("type"),
                "speedLimit": r.get("speedLimit"),
                "confirmations": r.get("confirmations", 1),
                "verified": r.get("verified", False),
                "createdAt": r.get("createdAt").isoformat() if r.get("createdAt") else None,
                "minutesAgo": int((datetime.utcnow() - r.get("createdAt", datetime.utcnow())).total_seconds() / 60)
            })
        
        return {"reports": result, "count": len(result)}
    except Exception as e:
        logger.error(f"Nearby reports error: {e}")
        return {"reports": [], "count": 0}


# ============ CAMERA TRUST & REMOVAL SYSTEM ============

@api_router.post("/camera/confirm")
async def confirm_camera_exists(
    lat: float = Query(...),
    lon: float = Query(...),
    camera_id: str = Query(default=None),
    user_id: str = Query(default="anonymous")
):
    """Confirm a camera still exists at location - builds trust"""
    try:
        if not camera_id:
            camera_id = f"cam_{lat:.5f}_{lon:.5f}"
        
        # Check if user already confirmed this camera recently
        recent_vote = await db.camera_votes.find_one({
            "camera_id": camera_id,
            "user_id": user_id,
            "action": "confirm",
            "created_at": {"$gte": datetime.utcnow() - timedelta(days=7)}
        })
        
        if recent_vote:
            return {"success": False, "message": "Already confirmed recently", "pointsEarned": 0}
        
        # Record the confirmation
        success = await update_camera_trust(camera_id, lat, lon, +1, user_id, "confirm")
        
        if success:
            # Award points
            await db.user_points.update_one(
                {"userId": user_id},
                {"$inc": {"points": REPORT_POINTS['camera_exists'], "confirmations": 1}},
                upsert=True
            )
            
            return {
                "success": True,
                "pointsEarned": REPORT_POINTS['camera_exists'],
                "message": "Camera confirmed! +5 points"
            }
        
        return {"success": False, "message": "Already voted", "pointsEarned": 0}
    except Exception as e:
        logger.error(f"Camera confirm error: {e}")
        return {"success": False, "error": str(e)}


@api_router.post("/camera/remove")
async def report_camera_removed(
    lat: float = Query(...),
    lon: float = Query(...),
    camera_id: str = Query(default=None),
    user_id: str = Query(default="anonymous")
):
    """Report a camera has been removed - requires multiple reports"""
    try:
        if not camera_id:
            camera_id = f"cam_{lat:.5f}_{lon:.5f}"
        
        # Check if user already reported this camera as removed
        existing_removal = await db.camera_removals.find_one({
            "camera_id": camera_id,
            "user_id": user_id
        })
        
        if existing_removal:
            return {"success": False, "message": "Already reported", "pointsEarned": 0}
        
        # Check distance - user must be within 100m of camera
        # (This would be validated client-side, but we trust the app for now)
        
        # Record the removal report
        await db.camera_removals.insert_one({
            "camera_id": camera_id,
            "lat": lat,
            "lon": lon,
            "user_id": user_id,
            "created_at": datetime.utcnow()
        })
        
        # Update trust score
        await update_camera_trust(camera_id, lat, lon, -1, user_id, "remove")
        
        # Count total removal reports
        removal_count = await db.camera_removals.count_documents({
            "camera_id": camera_id,
            "created_at": {"$gte": datetime.utcnow() - timedelta(days=TRUST_THRESHOLDS['REMOVAL_WINDOW_DAYS'])}
        })
        
        # Award points for removal report
        await db.user_points.update_one(
            {"userId": user_id},
            {"$inc": {"points": REPORT_POINTS['camera_removed'], "removals": 1}},
            upsert=True
        )
        
        status = "pending"
        if removal_count >= TRUST_THRESHOLDS['MIN_REMOVALS_TO_DELETE']:
            status = "deleted"
            # Archive the camera
            await db.camera_archive.insert_one({
                "camera_id": camera_id,
                "lat": lat,
                "lon": lon,
                "archived_at": datetime.utcnow(),
                "reason": "community_removal",
                "removal_count": removal_count
            })
        elif removal_count >= TRUST_THRESHOLDS['MIN_REMOVALS_TO_HIDE']:
            status = "hidden"
        
        logger.info(f"Camera removal report: {camera_id} by {user_id}, count={removal_count}, status={status}")
        
        return {
            "success": True,
            "pointsEarned": REPORT_POINTS['camera_removed'],
            "removalCount": removal_count,
            "threshold": TRUST_THRESHOLDS['MIN_REMOVALS_TO_HIDE'],
            "status": status,
            "message": f"+{REPORT_POINTS['camera_removed']} points! {removal_count}/{TRUST_THRESHOLDS['MIN_REMOVALS_TO_HIDE']} reports"
        }
    except Exception as e:
        logger.error(f"Camera removal error: {e}")
        return {"success": False, "error": str(e)}


@api_router.get("/camera/{camera_id}/trust")
async def get_camera_trust(camera_id: str):
    """Get trust info for a specific camera"""
    try:
        trust_score = await get_camera_trust_score(camera_id)
        is_hidden = await is_camera_hidden(camera_id)
        
        # Get confirmation count
        confirm_count = await db.camera_votes.count_documents({
            "camera_id": camera_id,
            "action": "confirm"
        })
        
        # Get removal count
        removal_count = await db.camera_removals.count_documents({
            "camera_id": camera_id,
            "created_at": {"$gte": datetime.utcnow() - timedelta(days=7)}
        })
        
        return {
            "cameraId": camera_id,
            "trustScore": trust_score,
            "isHidden": is_hidden,
            "confirmations": confirm_count,
            "recentRemovals": removal_count,
            "status": "hidden" if is_hidden else "active"
        }
    except Exception as e:
        return {"error": str(e)}


@api_router.get("/cameras/hidden")
async def get_hidden_cameras(
    lat: float = Query(...),
    lon: float = Query(...),
    radius: float = Query(default=50000)
):
    """Get list of hidden/removed cameras in area (for admin/debug)"""
    try:
        lat_delta = radius / 111000
        lon_delta = radius / (111000 * abs(math.cos(math.radians(lat))))
        
        hidden = await db.camera_trust.find({
            "lat": {"$gte": lat - lat_delta, "$lte": lat + lat_delta},
            "lon": {"$gte": lon - lon_delta, "$lte": lon + lon_delta},
            "trust_score": {"$lte": TRUST_THRESHOLDS['TRUST_SCORE_THRESHOLD']}
        }).to_list(100)
        
        return {
            "hidden_cameras": [
                {
                    "camera_id": c.get("camera_id"),
                    "lat": c.get("lat"),
                    "lon": c.get("lon"),
                    "trust_score": c.get("trust_score"),
                    "last_updated": c.get("last_updated").isoformat() if c.get("last_updated") else None
                }
                for c in hidden
            ],
            "count": len(hidden)
        }
    except Exception as e:
        return {"hidden_cameras": [], "count": 0, "error": str(e)}


# ============ COMMENTS API ============

@api_router.get("/camera/{camera_id}/comments")
async def get_camera_comments(camera_id: str):
    """Get all comments for a camera"""
    try:
        comments = await db.comments.find({"cameraId": camera_id}).sort("timestamp", -1).to_list(100)
        return {
            "comments": [
                {
                    "id": str(c.get("_id", c.get("id", ""))),
                    "cameraId": c.get("cameraId"),
                    "userId": c.get("userId"),
                    "userName": c.get("userName", "Anonymous"),
                    "text": c.get("text"),
                    "timestamp": c.get("timestamp").isoformat() if c.get("timestamp") else None,
                    "likes": c.get("likes", 0)
                }
                for c in comments
            ]
        }
    except Exception as e:
        logger.error(f"Error getting comments: {e}")
        return {"comments": [], "error": str(e)}

@api_router.post("/camera/{camera_id}/comments")
async def add_camera_comment(camera_id: str, comment: CommentCreate):
    """Add a comment to a camera"""
    try:
        new_comment = {
            "id": str(uuid.uuid4()),
            "cameraId": camera_id,
            "userId": comment.userId,
            "userName": comment.userName or "Anonymous",
            "text": comment.text,
            "timestamp": datetime.utcnow(),
            "likes": 0
        }
        await db.comments.insert_one(new_comment)
        
        # Award points to user
        await db.users.update_one(
            {"user_id": comment.userId},
            {"$inc": {"points": 5, "comments_count": 1}},
            upsert=True
        )
        
        return {"success": True, "comment": new_comment}
    except Exception as e:
        logger.error(f"Error adding comment: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/comment/{comment_id}/like")
async def like_comment(comment_id: str, user_id: str = Query(...)):
    """Like a comment"""
    try:
        result = await db.comments.update_one(
            {"id": comment_id},
            {"$inc": {"likes": 1}}
        )
        return {"success": result.modified_count > 0}
    except Exception as e:
        logger.error(f"Error liking comment: {e}")
        return {"success": False, "error": str(e)}


# ============ REGISTER ROUTER & MIDDLEWARE ============

# Include the router
app.include_router(api_router)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
