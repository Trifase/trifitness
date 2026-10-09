import os
import sys
import json
import datetime
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

BASE_DIR = Path(__file__).resolve().parent
CREDENTIALS_FILE = BASE_DIR / 'credentials.json'
TOKEN_FILE = BASE_DIR / 'token.json'

SCOPES = [
    'https://www.googleapis.com/auth/fitness.activity.read',
    'https://www.googleapis.com/auth/fitness.location.read'
]

flow = InstalledAppFlow.from_client_secrets_file(
    str(CREDENTIALS_FILE),
    scopes=SCOPES,
    redirect_uri='http://localhost:8088/'
)

auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')

print("="*60, flush=True)
print("CLICCA SU QUESTO LINK PER AUTORIZZARE GOOGLE FIT:", flush=True)
print(auth_url, flush=True)
print("="*60, flush=True)

# Also try opening directly via Windows
try:
    os.startfile(auth_url)
except Exception:
    pass

auth_code = None

class OAuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        
        if 'code' in params:
            auth_code = params['code'][0]
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write("<h1>Autorizzazione completata con successo!</h1><p>Puoi chiudere questa scheda del browser e tornare alla chat.</p>".encode('utf-8'))
        else:
            self.send_response(400)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write("<h1>Errore nell'autorizzazione</h1>".encode('utf-8'))

    def log_message(self, format, *args):
        pass

server = HTTPServer(('localhost', 8088), OAuthHandler)
print("In attesa della conferma nel browser...", flush=True)

while auth_code is None:
    server.handle_request()

print("Codice ricevuto! Scambio con il token...", flush=True)
flow.fetch_token(code=auth_code)
creds = flow.credentials

with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
    f.write(creds.to_json())

print("Token salvato con successo in token.json!", flush=True)

# Fetch stats to verify
service = build('fitness', 'v1', credentials=creds)
now = datetime.datetime.now()
start_of_day = datetime.datetime(now.year, now.month, now.day, 0, 0, 0)

start_ms = int(start_of_day.timestamp() * 1000)
end_ms = int(now.timestamp() * 1000)

body = {
    "aggregateBy": [
        {
            "dataTypeName": "com.google.step_count.delta",
            "dataSourceId": "derived:com.google.step_count.delta:com.google.android.gms:estimated_steps"
        },
        {
            "dataTypeName": "com.google.calories.expended",
            "dataSourceId": "derived:com.google.calories.expended:com.google.android.gms:merge_calories_expended"
        },
        {
            "dataTypeName": "com.google.distance.delta",
            "dataSourceId": "derived:com.google.distance.delta:com.google.android.gms:merge_distance_delta"
        }
    ],
    "bucketByTime": { "durationMillis": 86400000 },
    "startTimeMillis": start_ms,
    "endTimeMillis": end_ms
}

response = service.users().dataset().aggregate(userId="me", body=body).execute()

steps = 0
calories = 0.0
distance_m = 0.0

buckets = response.get('bucket', [])
if buckets:
    for dataset in buckets[0].get('dataset', []):
        name = dataset.get('dataSourceId', '')
        for point in dataset.get('point', []):
            for val in point.get('value', []):
                if 'step_count' in name:
                    steps += val.get('intVal', 0)
                elif 'calories' in name:
                    calories += val.get('fpVal', 0.0)
                elif 'distance' in name:
                    distance_m += val.get('fpVal', 0.0)

print("="*60, flush=True)
print("DATI ESTRATTI CON SUCCESSO DA GOOGLE FIT:", flush=True)
print(f"Passi: {steps}", flush=True)
print(f"Calorie: {round(calories)} kcal", flush=True)
print(f"Distanza: {round(distance_m / 1000, 2)} km", flush=True)
print("="*60, flush=True)
