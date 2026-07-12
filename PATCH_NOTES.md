# SpyEngine M11.6 — GUI cliente in italiano + Wizard AI cliente

Patch UX/client-only sopra M11.5.

## Cambiamenti

- La lingua principale della GUI cliente resta italiana anche per:
  - colonne delle tabelle;
  - stati verifica/pulizia;
  - categorie prodotto.
- Le chiavi tecniche del DB (`technology_laptop`, `vehicle_car_part`, ecc.) restano nel DB, ma non sono più il testo principale nella vista cliente.
- I filtri categoria mostrano etichette italiane ordinate alfabeticamente.
- Il Wizard AI è spostato nella navigazione cliente: non è più dentro la sezione sviluppatore.
- Home e sidebar hanno il pulsante “Crea ricerca AI”.
- La tab Opportunità applica un filtro prudente client-side per non mostrare in shortlist casi noti di categoria/titolo in conflitto.
- L’export cliente (`scripts/export_marketplace_client_view.py`) usa intestazioni e valori principali in italiano.

## Nota

La patch non cambia il database e non modifica la pipeline. È una patch di presentazione/UX.
