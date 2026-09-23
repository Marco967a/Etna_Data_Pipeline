# Analisi esplorativa dei pattern pre-eruttivi — primi risultati

Riproducibile con `python -m analysis.eda_preeruptive` (seed fisso). Dati: terremoti EtnaRCSC
2021-01-01 → 2026-02-28 (Mc = 1.5), 14 fasi eruttive indipendenti (eruzioni separate da > 30 giorni;
elenco degli onset nell'output dello script) e 67 giorni eruttivi totali.

## 1. Epoch sovrapposte (14 onset vs date di controllo casuali, test di permutazione)

- Grezzo: il **numero di eventi totali** nei 14 e 30 giorni prima dell'onset è ~1.6x quello dei
  controlli (p_Holm = 0.007). Sembra un precursore.
- **Non lo è:** normalizzando per la media mobile annuale (`n_all_rel`) l'effetto sparisce
  (p = 0.26). L'eccesso è compatibile con un livello più alto di conteggi nel 2021 (attività o cambi di rete/rilevabilità: non verificato quale), non
  un aumento locale prima degli onset. Il conteggio con M ≥ Mc (catalogo completo) non mostra
  nulla di significativo in nessuna finestra.
- Energia, deformazione di Benioff e magnitudo massima: tendenza positiva nei 14-30 giorni prima
  (percentili 92-99 del null) ma **non significativa dopo correzione per test multipli** (p_Holm ≥ 0.13).
- Solo 2 test su 35 restano significativi dopo Holm, entrambi il conteggio grezzo (confondente).

## 2. Modelli (validazione a blocchi da 120 giorni, null da permutazione intra-blocco)

| Modello | AUC logistica | AUC random forest | AUC null (permutazione) |
|---|---|---|---|
| A: eruzione entro 24h (67 positivi) | 0.91 | 0.93 | 0.88-0.89 |
| B: 7 giorni prima di un onset (98 positivi) | 0.56 | 0.69 | 0.50-0.61 |

- L'AUC alta del modello A è quasi tutta **struttura temporale**: permutando le etichette dentro ai
  blocchi l'AUC resta 0.88. I modelli riconoscono "siamo nel 2021, periodo ad alta attività", non il
  giorno prima di un parossismo. Il guadagno reale sopra il null è di ~0.03-0.04 (p ≈ 0.003, ma con
  poche unità indipendenti).
- Modello B (più pulito perché indipendente dalle serie fitte): random forest 0.69 contro un null di
  0.61, guadagno modesto e da non sovra-interpretare con 14 onset.
- AUC univariate del modello B: le più alte sono i conteggi su 90 giorni (0.80), cioè ancora il
  livello lento di attività, non un segnale a breve termine. b-value, energia a 7 giorni e rapporto
  7/30 giorni sono intorno a 0.5.

## 3. Conclusioni prudenti

1. Con solo catalogo sismico EtnaRCSC e queste feature **non emerge un precursore a breve termine
   (24h-7gg) robusto**. Emerge un legame con il regime di attività su scala di mesi.
2. Il campione indipendente è piccolo (14 fasi): potenza statistica bassa; un risultato nullo non
   dimostra l'assenza di precursori.
3. I confondenti principali sono la non stazionarietà del catalogo (rete) e il raggruppamento delle
   eruzioni nel 2021.

## 4. Limiti e prossimi passi possibili

- Eventi noti con sola data (nessuna ora); alcuni episodi 2021-2023 da compilazione secondaria.
- Catalogo EtnaRCSC fermo a fine febbraio 2026: le eruzioni giugno-agosto 2026 non sono analizzabili.
- Da provare: feature che non dipendono dal tasso (profondità, migrazione spaziale, rapporto
  eventi profondi/superficiali, b-value con Mc locale), tremore su 1-2 stazioni, hotspot FIRMS
  (rilevano l'attività effusiva, non i parossismi brevi).

## 5. Feature non legate al tasso (`python -m analysis.eda_nonrate`)

Feature: profondità (mediana, IQR, quota > 10 km), distanza e dispersione rispetto ai crateri
sommitali, magnitudo media/dev. std, coefficiente di variazione dei tempi tra eventi, migrazione
(centroide e profondità ultimi 7 gg vs giorni 8-37), b-value con Mc locale. Test sul giorno prima
dell'onset, in versione grezza e detrendata (meno la mediana mobile annuale): 54 test.

- **Nessun test significativo dopo Holm** (miglior p_Holm = 0.36).
- Segnali nominali (p grezzo < 0.05, ipotesi da rivalutare, non risultati): profondità mediana a 7 gg
  più bassa (-1.2 km detrendata), spostamento verso eventi più superficiali (-2 km rispetto al mese
  precedente) e magnitudo media più bassa (più piccoli eventi). Direzione coerente tra versione
  grezza e detrendata. Controllo di coerenza sui singoli onset: profondità 7 gg sotto la norma in
  10 onset su 13 (sign test p = 0.09), spostamento in 9 su 13 (p = 0.27).
- **Modelli:** le sole feature non legate al tasso non superano il caso (AUC 0.43-0.57, in un caso
  0.18 cioè instabile tra blocchi: nessun segnale che generalizza). Combinarle con le feature di tasso
  non migliora rispetto al solo tasso (guadagno sul null 0.015-0.057, in linea con la sezione 2).

**Lettura:** la debole tendenza a sismicità più superficiale prima degli onset è fisicamente
plausibile ma, con 14 fasi e 54 test, non è distinguibile dal caso. Per confermarla servirebbero
più onset (altri anni, altri cataloghi) o un test mirato su una sola ipotesi decisa a priori.
