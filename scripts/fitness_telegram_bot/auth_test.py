import os
import sys
import datetime
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/fitness.activity.read',
    'https://www.googleapis.com/auth/fitness.location.read'
]

BASE_DIR = Path(__file__).resolve().parent
CREDENTIALS_FILE = BASE_DIR / 'credentials.json'
TOKEN_FILE = BASE_DIR / 'token.json'

def get_credentials():
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
            f.write(creds.to_json())
    return creds

def fetch_today_stats(creds):
    service = build('fitness', 'v1', credentials=creds)
    
    # Calculate start and end of today in nanoseconds
    now = datetime.datetime.now()
    start_of_day = datetime.datetime(now.year, now.month, now.day, 0, 0, 0)
    
    start_ns = int(start_of_day.timestamp() * 1e9)
    end_ns = int(now.timestamp() * 1e9)
    
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
                        
    return {
        "steps": steps,
        "calories": round(calories),
        "distance_km": round(distance_m / 1000, 2)
    }

if __name__ == '__main__':
    print("Avvio autenticazione Google Fitness...")
    creds = get_credentials()
    print("Token salvato con successo!")
    print("Interrogo i dati di oggi...")
    stats = fetch_today_stats(creds)
    print("DATI ESTRATTI DA GOOGLE FIT:")
    print(f"  Passi: {stats['steps']}")
    print(f"  Calorie: {stats['calories']} kcal")
    print(f"  Distanza: {stats['distance_km']} km")
