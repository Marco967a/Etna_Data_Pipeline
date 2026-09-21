"""
Ingestion terremoti — EtnaRCSC (INGV Osservatorio Etneo), dal 1999.

STATO: DA COMPLETARE — a differenza di ISIDe/FDSN e FIRMS, l'export di EtnaRCSC
avviene tramite un form HTML (http://sismoweb.ct.ingv.it/Etna/catalogs/EtnaRCSC/catalogue.php)
di cui non è stato possibile verificare in automatico i parametri esatti della richiesta
("Make file"): il name/id dei campi del form non è visibile dall'HTML renderizzato.

Come completarlo (5 minuti):
1. Apri http://sismoweb.ct.ingv.it/Etna/catalogs/EtnaRCSC/catalogue.php nel browser.
2. Apri gli strumenti sviluppatore -> tab "Network", imposta un intervallo di date breve
   di prova e clicca "Make file".
3. Guarda la richiesta HTTP generata: URL, metodo (GET/POST) e nomi dei parametri
   (es. potrebbero chiamarsi start_date/end_date, o form[...], o altro).
4. Riporta quei parametri nella funzione fetch_chunk() qui sotto, al posto del TODO.

Nel frattempo, il catalogo ISIDe/FDSN (ingest_terremoti.py) copre già l'intera area
etnea dal 1985 ad oggi con buona qualità: il progetto può partire senza bloccarsi
su questo script. EtnaRCSC resta utile come fonte di incrocio/validazione più
specifica sull'area vulcanica stretta, una volta completato.

Riferimento per la citazione (obbligatoria se userai questi dati):
Alparone, S. C. et al. (2020). Mt. Etna Revised and Concise Seismic Catalog from 1999
(EtnaRCSC) [Data set]. INGV. https://doi.org/10.13127/ETNASC/ETNARCSC
"""
import requests

BASE_URL = "http://sismoweb.ct.ingv.it/Etna/catalogs/EtnaRCSC/catalogue.php"


def fetch_chunk(start_date: str, end_date: str) -> str:
    """
    TODO: sostituire con i parametri reali osservati nel tab Network del browser.
    Esempio indicativo (NON verificato) di come potrebbe essere strutturata:

        params = {
            "start_date": start_date,
            "end_date": end_date,
            "output": "csv",
        }
        resp = requests.get(BASE_URL, params=params, timeout=60)
        resp.raise_for_status()
        return resp.text
    """
    raise NotImplementedError(
        "Parametri del form da verificare manualmente — vedi istruzioni nel docstring del modulo."
    )


if __name__ == "__main__":
    print(__doc__)
