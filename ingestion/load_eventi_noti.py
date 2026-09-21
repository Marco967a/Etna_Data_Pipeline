"""
Carica in PostgreSQL il CSV compilato manualmente in data_seed/eventi_noti_template.csv
(o un altro percorso passato come argomento).

Questi eventi vanno compilati a mano consultando lo storico eruttivo del
Global Volcanism Program (Smithsonian) per l'Etna:
https://volcano.si.edu/volcano.cfm?vn=211060

Esecuzione:
    python -m ingestion.load_eventi_noti data_seed/eventi_noti_template.csv
"""
import csv
import sys

from db.connection import get_connection

INSERT_SQL = """
    INSERT INTO eventi_noti (event_date, event_type, description, source)
    VALUES (%(event_date)s, %(event_type)s, %(description)s, %(source)s);
"""


def run(csv_path: str) -> None:
    conn = get_connection()
    n = 0
    try:
        with open(csv_path, newline="", encoding="utf-8") as f, conn.cursor() as cur:
            reader = csv.DictReader(f)
            for row in reader:
                cur.execute(INSERT_SQL, row)
                n += 1
        conn.commit()
    finally:
        conn.close()
    print(f"Caricati {n} eventi noti da {csv_path}")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "data_seed/eventi_noti_template.csv"
    run(path)
