"""
Configurazione centrale del progetto.
Carica le variabili d'ambiente da .env e definisce le costanti geografiche
condivise da tutti gli script di ingestion.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# --- Database ---
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME", "etna_data"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
}

# --- NASA FIRMS ---
FIRMS_MAP_KEY = os.getenv("FIRMS_MAP_KEY", "")

# --- NASA Earthdata Login ---
# earthaccess legge da solo queste variabili (login "environment"); qui servono
# solo per dare un errore chiaro se mancano. In alternativa al username/password
# si può usare un token (EARTHDATA_TOKEN).
EARTHDATA_USERNAME = os.getenv("EARTHDATA_USERNAME", "")
EARTHDATA_PASSWORD = os.getenv("EARTHDATA_PASSWORD", "")
EARTHDATA_TOKEN = os.getenv("EARTHDATA_TOKEN", "")

# --- Area geografica di interesse (bounding box Etna) ---
# Copre l'edificio vulcanico e l'area di sismicità vulcano-tettonica associata.
# Puoi restringerlo in seguito se noti troppo "rumore" da eventi tettonici regionali
# non direttamente legati alla dinamica del vulcano.
ETNA_BBOX = {
    "min_lat": 37.60,
    "max_lat": 37.90,
    "min_lon": 14.90,
    "max_lon": 15.15,
}

# Formato richiesto da FIRMS Area API: "west,south,east,north"
FIRMS_AREA_STRING = (
    f"{ETNA_BBOX['min_lon']},{ETNA_BBOX['min_lat']},"
    f"{ETNA_BBOX['max_lon']},{ETNA_BBOX['max_lat']}"
)
