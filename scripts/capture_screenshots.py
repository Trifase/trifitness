import os
import sys
import time
import threading
import subprocess
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
DOCS_DIR = BASE_DIR / "docs" / "screenshots"
DOCS_DIR.mkdir(parents=True, exist_ok=True)

import uvicorn
from main import app

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
]

browser_exe = None
for p in CHROME_PATHS:
    if os.path.exists(p):
        browser_exe = p
        break

if not browser_exe:
    print("Browser executable not found!")
    sys.exit(1)

# Start FastAPI server on port 9998
server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=9998, log_level="warning"))
server_thread = threading.Thread(target=server.run, daemon=True)
server_thread.start()
time.sleep(2)

print(f"FastAPI server running on http://127.0.0.1:9998 using {browser_exe}")

SHOTS = [
    {
        "filename": "01-calendario-pasti.png",
        "url": "http://127.0.0.1:9998/?tab=calendar",
        "size": "1440,900",
        "budget": "4000",
        "desc": "Calendario Pasti Settimanale"
    },
    {
        "filename": "02-lista-spesa.png",
        "url": "http://127.0.0.1:9998/?tab=shopping",
        "size": "1440,960",
        "budget": "4000",
        "desc": "Lista della Spesa per Reparti"
    },
    {
        "filename": "03-ricettario.png",
        "url": "http://127.0.0.1:9998/?tab=recipes",
        "size": "1440,920",
        "budget": "4000",
        "desc": "Ricettario Anti-Insulino-Resistenza"
    },
    {
        "filename": "04-scheda-ricetta-porzioni.png",
        "url": "http://127.0.0.1:9998/?tab=recipes&recipe=insalata-riso-venere",
        "size": "1440,900",
        "budget": "4000",
        "desc": "Scheda Ricetta con Porzioni Dinamiche"
    },
    {
        "filename": "05-meal-prep.png",
        "url": "http://127.0.0.1:9998/?tab=mealprep",
        "size": "1440,900",
        "budget": "4000",
        "desc": "Meal Prep Domenicale & Freezer"
    },
    {
        "filename": "06-monitoraggio-peso.png",
        "url": "http://127.0.0.1:9998/?tab=weight",
        "size": "1440,920",
        "budget": "4000",
        "desc": "Monitoraggio Peso & Grafico Media Mobile"
    },
    {
        "filename": "07-attivita-fisica.png",
        "url": "http://127.0.0.1:9998/?tab=activities",
        "size": "1440,920",
        "budget": "4000",
        "desc": "Registro Attività Fisica & Tapis Roulant"
    },
    {
        "filename": "08-cucina-tablet-today.png",
        "url": "http://127.0.0.1:9998/kitchen?view=today",
        "size": "1280,800",
        "budget": "4000",
        "desc": "Vista Cucina / Tablet Kiosk - Oggi"
    },
    {
        "filename": "09-cucina-tablet-week.png",
        "url": "http://127.0.0.1:9998/kitchen?view=w1",
        "size": "1280,820",
        "budget": "4000",
        "desc": "Vista Cucina / Tablet Kiosk - Settimana"
    }
]

for item in SHOTS:
    dest = str(DOCS_DIR / item["filename"])
    print(f"Catturo {item['desc']} -> {item['filename']} ...")
    cmd = [
        browser_exe,
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        f"--window-size={item['size']}",
        f"--virtual-time-budget={item['budget']}",
        f"--screenshot={dest}",
        item["url"]
    ]
    res = subprocess.run(cmd, capture_output=True)
    if os.path.exists(dest):
        size_kb = os.path.getsize(dest) // 1024
        print(f"  OK: {item['filename']} ({size_kb} KB)")
    else:
        print(f"  ERRORE su {item['filename']}: {res.stderr.decode('utf-8', errors='ignore')}")

server.should_exit = True
print("Completato!")
