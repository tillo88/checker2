# SpyEngine Product Knowledge

La knowledge base prodotti e separata dalla vita breve degli annunci. Il catalogo
mantiene famiglie, varianti, alias, identificatori, specifiche, evidenze e
relazioni; gli annunci forniscono esempi rumorosi e segnali di verifica.

## Stato e copertura

```bash
./.venv/bin/python scripts/catalog_knowledge_status.py \
  --db data/marketplace_cache/marketplace.sqlite
```

Il report evidenzia famiglie senza varianti, alias, identificatori o specifiche e
alias condivisi da famiglie diverse.

## Resolver locale titolo + descrizione

```bash
./.venv/bin/python scripts/resolve_product_from_catalog.py \
  "OTTIMA OFFERTA!!1! IPHONE TELEFONO NUOVO RICONDIZIATO PRO MAX 16" \
  --description "Codice modello A3296, 256GB, display 6.9 pollici"
```

L'output contiene candidato selezionato, alternative, confidenza, condizione ed
evidenze. Un identificatore esatto puo risolvere un conflitto presente nel solo
titolo. In assenza di margine sufficiente lo stato resta `ambiguous`.

La stessa funzione e disponibile nella GUI cliente in:

`Prodotti -> Risolvi annuncio`

## Migrazione e indice

Dry-run su copia temporanea:

```bash
./.venv/bin/python scripts/migrate_product_knowledge.py
```

Applicazione reale con backup automatico:

```bash
./.venv/bin/python scripts/migrate_product_knowledge.py --apply
```

## Qualita alias

Gli alias originali non vengono cancellati. L'audit crea review separate e
ricostruisce l'indice escludendo solo gli alias marcati `reject`.

```bash
./.venv/bin/python scripts/audit_product_alias_quality.py
./.venv/bin/python scripts/audit_product_alias_quality.py --apply
```

## Coda enrichment lunga e riprendibile

Creazione idempotente dei task mancanti:

```bash
./.venv/bin/python scripts/catalog_enrichment_queue.py seed
```

Stato:

```bash
./.venv/bin/python scripts/catalog_enrichment_queue.py status
```

Ripristino di lease scaduti dopo crash o riavvio:

```bash
./.venv/bin/python scripts/catalog_enrichment_queue.py release-stale
```

Le priorita correnti sono: identificatori, specifiche, varianti, alias. I task
sono persistenti, hanno tentativi massimi e lease; un worker puo quindi lavorare
per giorni o settimane e riprendere senza ricominciare.

## Import strutturato da crawler/fonti

Il file di input segue `configs/product_knowledge_import_example.json`.

Dry-run:

```bash
./.venv/bin/python scripts/import_product_knowledge.py \
  configs/product_knowledge_import_example.json
```

Apply con backup:

```bash
./.venv/bin/python scripts/import_product_knowledge.py \
  configs/product_knowledge_import_example.json --apply
```

Ogni fatto conserva fonte e confidenza. Identificatori e specifiche non devono
essere promossi da un singolo snippet debole: il crawler deve fornire evidenze
ufficiali o consenso fra fonti indipendenti.

### Relazioni e compatibilita

Le relazioni sono dichiarate nella chiave top-level `relations` del payload e
usano `family_key`/`variant_key`, mai gli ID interni SQLite. Esempio:

```json
{
  "subject": {"family_key": "apple_iphone_16_pro_max"},
  "type": "compatible_with",
  "object": {"family_key": "apple_usb_c_20w_power_adapter"},
  "confidence": 0.98
}
```

I tipi ammessi comprendono `compatible_with`, `incompatible_with`,
`accessory_for`, `requires`, `replacement_for`, `successor_of`,
`predecessor_of` e `often_bundled_with`. Gli import sono idempotenti e ogni
arco conserva fonte e confidenza. Quando il resolver seleziona un prodotto,
restituisce anche le relazioni in entrata e in uscita.

## Modalita dry-run del bot

```bash
# Nessuna persistenza e nessuna notifica reale
./.venv/bin/python scripts/run_manager.py --dry-run

# Memoria/report normali, Telegram simulato
./.venv/bin/python scripts/run_manager.py --notification-dry-run
```

I due flag sono mutuamente esclusivi. Senza flag il manager persiste e invia le
notifiche configurate normalmente.

## Opportunity score e card

La pagina `Opportunita` mostra card con prezzo, score, scarto dal riferimento e
pulsante `Apri annuncio`. Lo score commerciale e distinto dalla confidenza di
classificazione:

- usa soltanto gruppi con almeno tre annunci dello stesso modello o titolo risolto;
- `50` indica un prezzo vicino alla mediana del gruppo;
- valori maggiori indicano un prezzo inferiore al riferimento;
- ribassi oltre il 65% sono marcati `Prezzo anomalo: verificare` e declassati;
- senza comparabili specifici lo score resta vuoto.

L'export JSON include `opportunity_score`, `opportunity_status`,
`reference_price`, `discount_percent`, `reference_scope`,
`reference_sample_size` e `reference_confidence`, oltre alla confidenza prodotto
originale nel campo `confidence`.


## GUI cliente ottimizzata

Il launcher apre subito Streamlit senza attendere llama-server. L'AI resta
disponibile dai controlli sviluppatore o impostando
`SPYENGINE_GUI_AUTOSTART_LLAMA=1`. Le query cliente usano cache brevi, le tabelle
mostrano solo le colonne operative e gli export conservano tutti i campi tecnici.
La sidebar cliente contiene stato sintetico e una sola navigazione; i controlli
avanzati restano nascosti finche non viene attivata la modalita sviluppatore.

## Batch sugli annunci esistenti

```bash
./.venv/bin/python scripts/resolve_catalog_listings.py --limit 5000
```

Per default usa soltanto annunci `verified` e `clean=accept` e non scrive review.
L'opzione `--apply` persiste le risoluzioni nella tabella dedicata senza cambiare
annunci, cleaning o verifiche originali.

