# SpyEngine Marketplace — M11.6

M11.6 rifinisce la GUI cliente introdotta con M11.5.

## Obiettivo

La GUI cliente deve sembrare un software professionale per uso operativo, non un dump tecnico.

## Regole UI

- Italiano come lingua principale.
- Categorie tecniche mantenute internamente, visualizzate come etichette italiane.
- Wizard AI accessibile al cliente perché serve a preparare le configurazioni di ricerca.
- Strumenti lunghi/debug restano in modalità sviluppatore.

## Test consigliati

```bash
cd ~/price_check_bot
cp spy_gui_v3.py spy_gui_v3.py.bak_m116
unzip -o SpyEngine_patch_M11_06_italian_client_wizard.zip -d .
./.venv/bin/python scripts/spyengine_client_doctor.py
./.venv/bin/python scripts/export_marketplace_client_view.py --db data/marketplace_cache/marketplace.sqlite --out logs/client_view_it.json
./launch_spyengine_client.sh
```
