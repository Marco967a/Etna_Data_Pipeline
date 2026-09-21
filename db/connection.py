"""
Helper di connessione al database PostgreSQL.
"""
import psycopg2
from config import DB_CONFIG


def get_connection():
    """Ritorna una nuova connessione psycopg2 usando le credenziali da .env."""
    return psycopg2.connect(**DB_CONFIG)
