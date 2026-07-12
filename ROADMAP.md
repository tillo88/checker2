# SpyEngine product knowledge roadmap

## Stato implementazione - 2026-07-11

Completato e verificato:

- Fondamenta Git, `.gitignore`, launcher anti-UNC, config esempio e doctor esteso.
- Vista cliente condivisa, shortlist/export prudenti e filtri prima del limite.
- Full dry-run senza scritture e notification dry-run con persistenza normale.
- Schema knowledge, indice token, evidence ledger e proposte validate.
- Relazioni validate/idempotenti con import, query bidirezionale e output resolver.
- Resolver titolo + descrizione con candidati, confidenza, condizione ed evidenze.
- Audit alias non distruttivo e guardrail anti-contaminazione.
- Coda persistente con lease, retry, resume, run id e heartbeat.
- Worker discovery, source policy, import strutturato e validazione GTIN multi-fonte.
- GUI cliente con resolver e controlli daemon nel Job Center.
- GUI cliente ottimizzata: AI lazy, cache brevi, tabelle compatte e sidebar pulita.
- Opportunity score prudente, card commerciali e pulsante Apri annuncio.
- Suite completa e doctor verdi.

Restano evoluzioni di prodotto, non blocchi delle fondamenta:

- ampliare alias multilingue e forme OCR tramite i worker;
- popolare su larga scala compatibilita e relazioni da fonti ufficiali;


## Visione

SpyEngine deve costruire una knowledge base locale e incrementale dei prodotti.
Gli annunci sono evidenze storiche e operative; il valore permanente e composto da
categorie, brand, famiglie, modelli, varianti, alias, identificatori, specifiche,
compatibilita e provenienza delle informazioni.

Il resolver deve usare prima regole e catalogo locale, poi la descrizione
dell'annuncio, quindi ricerca online e AI/Vision soltanto per i casi ambigui.

## Principi non negoziabili

- Non cancellare o sovrascrivere gli annunci originali.
- Conservare fonte, timestamp e confidenza di ogni fatto appreso.
- Titolo e descrizione sono evidenze separate: il titolo identifica il prodotto,
  la descrizione risolve dettagli e conflitti con peso inferiore.
- Un resolver puo restituire piu candidati; non deve indovinare a tutti i costi.
- Ogni processo lungo deve essere riprendibile tramite checkpoint.
- Dry-run completamente non distruttivo prima di ogni applicazione reale.
- Backup e controllo integrita prima delle migrazioni del catalogo.
- Raccolta ampia; viste cliente prudenti.

## Fase 0 - Fondamenta

- [x] `.gitignore` per segreti, database, modelli e file runtime.
- [x] Configurazione esempio e dipendenze di test riproducibili.
- [x] Launcher Windows canonico indipendente dalla directory UNC corrente.
- [ ] Inizializzare Git e creare il primo snapshot del solo codice.
- [ ] Estendere doctor con import, test, SQLite integrity/FK e launcher checks.

## Fase 1 - Contratto dati cliente

- [ ] Creare una vista/query risolta condivisa da GUI ed export.
- [ ] Definire esplicitamente la precedenza fra cleaning, AI Edge, research e raw.
- [ ] Shortlist: verified + clean accept + prezzo/URL validi + categoria supportata.
- [ ] Applicare filtri prima del LIMIT.
- [ ] Riparare i riferimenti catalogo orfani con backup e report.

## Fase 2 - Dry-run e operazioni sicure

- [ ] Rendere read-only il dry-run del bot: niente seen/history/report persistenti.
- [ ] Separare notification dry-run da full dry-run.
- [ ] Aggiungere lock, run id, checkpoint e resume ai job lunghi.
- [ ] Rendere idempotenti le promozioni nel catalogo.

## Fase 3 - Knowledge base prodotti

- [ ] Estendere schema per brand, famiglie, modelli, varianti e relazioni.
- [ ] Alias multilingue, abbreviazioni, errori comuni e forme OCR.
- [ ] Identificatori EAN/UPC/GTIN/MPN/SKU e codici modello.
- [ ] Specifiche tipizzate con unita normalizzate e provenienza.
- [ ] Compatibilita, accessori, successori/predecessori e falsi amici.
- [ ] Evidence ledger append-only con fonte, estratto, timestamp e confidenza.

## Fase 4 - Resolver titolo + descrizione

- [ ] Normalizzazione robusta e rimozione del rumore commerciale.
- [ ] Candidate generation da alias, identificatori, brand e token distintivi.
- [ ] Ranking spiegabile con evidenze positive e negative.
- [ ] Descrizione usata per capacita, condizione, codice modello e conflitti.
- [ ] Output con candidato principale, alternative, confidenza e motivazione.
- [ ] Escalation online/AI/Vision solo sotto soglie configurabili.

## Fase 5 - Arricchimento massivo

- [ ] Source registry con affidabilita e policy per tipo di dato.
- [ ] Import/crawl paginato, rate limited, riprendibile e multi-lingua.
- [ ] Queue separate per discovery, enrichment, resolution e verification.
- [ ] Apprendimento dagli annunci verificati con guardrail anti-contaminazione.
- [ ] Metriche di copertura per categoria, brand, famiglia e fonte.
- [ ] Report di conflitti, lacune e identificatori mancanti.

## Fase 6 - Prodotto cliente

- [ ] Schede prodotto leggibili e pulsante Apri annuncio.
- [ ] Ricerca istantanea nella knowledge base e negli annunci correnti.
- [ ] Opportunity score separato dalla confidenza di classificazione.
- [ ] Profili di ricerca, notifiche ed export CSV/JSON.
- [ ] Modularizzare la GUI separando pagine, query, resolver e job service.

## Criterio di completamento

Un titolo rumoroso deve essere risolto localmente quando il catalogo contiene
evidenza sufficiente. Il sistema deve mostrare perche ha scelto un prodotto,
mantenere alternative in caso di ambiguita e imparare nuove conoscenze soltanto
da evidenze verificabili senza degradare quelle gia affidabili.
