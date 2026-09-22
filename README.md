# Etna Volcanic Data — pipeline di ingestion

Pipeline Python per popolare un database PostgreSQL con i dati necessari
all'analisi dei pattern pre-eruttivi sull'Etna (terremoti, hotspot termici,
eventi noti). Struttura ispirata a NewBoxofficeProject.

## Setup

```bash
git clone https://github.com/Marco967a/Etna_Data_Pipeline.git
cd Etna_Data_Pipeline

python -m venv venv
source venv/bin/activate        # su Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # poi compila DB_* e FIRMS_MAP_KEY
psql -U <user> -d etna_data -f db/schema.sql
```

FIRMS_MAP_KEY gratuita: https://firms.modaps.eosdis.nasa.gov/api/map_key/

### NASA Earthdata

L'account Earthdata (https://urs.earthdata.nasa.gov/) è **distinto** dalla
`FIRMS_MAP_KEY`: FIRMS usa solo la chiave, mentre il login Earthdata serve per
scaricare gli altri dataset NASA (es. temperatura superficiale MODIS, SO₂).
Compila `EARTHDATA_USERNAME` e `EARTHDATA_PASSWORD` (oppure `EARTHDATA_TOKEN`)
nel `.env`, poi verifica:

```bash
python -m ingestion.earthdata_check              # login + ricerca di prova sull'Etna
python -m ingestion.earthdata_check --download   # scarica anche un granulo (prova reale del login)
```

### Test

```bash
pip install -r requirements-dev.txt
pytest                                           # test offline dei parser, senza rete né DB
```

## Stato delle fonti

| Fonte | Script | Stato | Copertura |
|---|---|---|---|
| ISIDe / FDSN-event (INGV) | `ingestion/ingest_terremoti.py` | ✅ Verificato, pronto all'uso | dal 1985 |
| NASA FIRMS (hotspot) | `ingestion/ingest_hotspot.py` | ✅ Verificato — da confermare solo la direzione del parametro DATE al primo run (vedi commenti nel file) | MODIS dal 2000, VIIRS dal 2012-01-19 |
| Eventi noti (GVP Smithsonian) | `ingestion/load_eventi_noti.py` + `data_seed/eventi_noti_template.csv` | ⚠️ Compilazione manuale del CSV richiesta | da definire in base al periodo scelto |
| EtnaRCSC (INGV-OE) | `ingestion/ingest_etnarcsc.py` | 🔧 Da completare — meccanismo di export del form da verificare manualmente (istruzioni nel file) | dal 1999 |
| NASA Earthdata (earthaccess) | `ingestion/earthdata_check.py` | 🔧 Solo autenticazione + ricerca di prova; dataset da scegliere (es. MOD11A1, SO₂ OMI/OMPS) | dipende dal prodotto |
| Tremore vulcanico | `ingestion/ingest_tremore.py` | ✅ Verificato, pronto all'uso — RMS grezzo per stazione, non confrontabile tra stazioni diverse (vedi commenti nel file) | dipende dalla copertura delle stazioni IV attive |

## Esecuzione

```bash
# Terremoti, area Etna, dal 1999 a oggi (~1 richiesta per anno)
python -m ingestion.ingest_terremoti --from-year 1999

# Hotspot termici, un mese di prova prima del backfill completo
python -m ingestion.ingest_hotspot --from-date 2012-01-19 --to-date 2012-02-19

# Eventi noti (dopo aver compilato il CSV)
python -m ingestion.load_eventi_noti data_seed/eventi_noti_template.csv

# Tremore vulcanico, un giorno di prova prima del backfill completo
python -m ingestion.ingest_tremore --from-date 2024-06-01 --to-date 2024-06-01
```

## Note importanti

- **Rispetta i servizi pubblici**: gli script includono una pausa tra le
  richieste (`time.sleep`). Non ridurla per velocizzare il backfill.
- **FIRMS**: prima di lanciare il backfill storico completo, esegui un chunk
  di prova e controlla nell'output il range di `acq_date` effettivamente
  ricevuto, per confermare in che direzione si muove il parametro `DATE`.
- **Citazioni**: se pubblichi il progetto, cita le fonti come richiesto —
  in particolare EtnaRCSC (DOI: 10.13127/ETNASC/ETNARCSC) e GVP Smithsonian.
- **Bounding box**: `config.py` definisce l'area geografica (`ETNA_BBOX`).
  Restringila se nell'EDA noti troppi eventi tettonici regionali non
  pertinenti alla dinamica vulcanica.

## Prossimi step

1. Completare `ingest_etnarcsc.py` (vedi istruzioni nel file).
2. Compilare `eventi_noti_template.csv` con lo storico da
   https://volcano.si.edu/volcano.cfm?vn=211060 per il periodo di interesse.
3. Passare alla fase di feature engineering (finestre pre-evento) ed EDA.
