# File vuoto: la sua presenza nella root fa aggiungere la root a sys.path da pytest,
# così i test possono importare `config`, `db` e `ingestion`.
