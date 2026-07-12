SpyEngine GUI Launchers

File aggiunti:
- launch_gui.bat      Windows doppio click, pensato per progetto dentro WSL
- launch_gui.ps1      alternativa PowerShell
- launch_gui.sh       Linux/WSL terminale

Uso consigliato su Windows:
1. Doppio click su launch_gui.bat
2. Aspetta 3-5 secondi
3. Si apre http://localhost:8501

Note:
- Il .bat usa wsl.exe e converte automaticamente il percorso con wslpath.
- Se trova .venv/bin/activate lo attiva automaticamente.
- Chiudere la finestra del launcher ferma Streamlit.
