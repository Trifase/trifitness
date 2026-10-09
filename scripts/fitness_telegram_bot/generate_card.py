import os
import io
import sys
import argparse
import urllib.request
import datetime
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

BASE_DIR = Path(__file__).resolve().parent
TOKEN_FILE = BASE_DIR / 'token.json'
CREDENTIALS_FILE = BASE_DIR / 'credentials.json'

def get_google_creds():
    if not TOKEN_FILE.exists():
        raise FileNotFoundError("token.json non trovato! Esegui prima login_server.py.")
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
            f.write(creds.to_json())
    return creds

def fetch_daily_metrics(target_date=None):
    if target_date is None:
        now = datetime.datetime.now()
        # Se prima delle 7 del mattino, riferimento è ieri
        if now.hour < 7:
            target_date = now.date() - datetime.timedelta(days=1)
        else:
            target_date = now.date()
    elif isinstance(target_date, str):
        target_date = datetime.datetime.strptime(target_date, "%Y-%m-%d").date()
    elif isinstance(target_date, datetime.datetime):
        target_date = target_date.date()

    creds = get_google_creds()
    service = build('fitness', 'v1', credentials=creds)

    start_dt = datetime.datetime.combine(target_date, datetime.time.min)
    end_dt = datetime.datetime.combine(target_date, datetime.time.max)

    start_ns = int(start_dt.timestamp() * 1e9)
    end_ns = int(end_dt.timestamp() * 1e9)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    # 1. Passi (da stream Mi Fitness / Xiaomi Wearable o aggregate)
    ds_steps = 'raw:com.google.step_count.delta:com.xiaomi.wearable:health_platform'
    xiaomi_steps = 0
    try:
        res = service.users().dataSources().datasets().get(
            userId='me', dataSourceId=ds_steps, datasetId=f'{start_ns}-{end_ns}'
        ).execute()
        xiaomi_steps = sum(pt['value'][0]['intVal'] for pt in res.get('point', []))
    except Exception:
        pass

    agg_steps = 0
    body = {
        'aggregateBy': [{'dataTypeName': 'com.google.step_count.delta'}],
        'bucketByTime': {'durationMillis': 86400000},
        'startTimeMillis': start_ms,
        'endTimeMillis': end_ms
    }
    try:
        res_agg = service.users().dataset().aggregate(userId='me', body=body).execute()
        for b in res_agg.get('bucket', []):
            for d in b.get('dataset', []):
                for pt in d.get('point', []):
                    agg_steps += pt['value'][0]['intVal']
    except Exception:
        pass

    steps = xiaomi_steps if xiaomi_steps > 0 else agg_steps

    # 2. Distanza (km)
    # Lo stream Xiaomi spesso registra solo le sessioni di allenamento (es. 4.7 km invece di 11 km).
    # L'aggregato unisce tutti i sensori e passi della giornata. Prendiamo il valore massimo reale.
    ds_dist = 'raw:com.google.distance.delta:com.xiaomi.wearable:health_platform'
    xiaomi_dist = 0.0
    try:
        res_d = service.users().dataSources().datasets().get(
            userId='me', dataSourceId=ds_dist, datasetId=f'{start_ns}-{end_ns}'
        ).execute()
        dist_m = sum(pt['value'][0]['fpVal'] for pt in res_d.get('point', []))
        xiaomi_dist = round(dist_m / 1000, 2)
    except Exception:
        pass

    agg_dist = 0.0
    body_dist = {
        'aggregateBy': [{'dataTypeName': 'com.google.distance.delta'}],
        'bucketByTime': {'durationMillis': 86400000},
        'startTimeMillis': start_ms,
        'endTimeMillis': end_ms
    }
    try:
        res_d_agg = service.users().dataset().aggregate(userId='me', body=body_dist).execute()
        for b in res_d_agg.get('bucket', []):
            for d in b.get('dataset', []):
                for pt in d.get('point', []):
                    agg_dist = round(pt['value'][0]['fpVal'] / 1000, 2)
    except Exception:
        pass

    dist_km = round(max(xiaomi_dist, agg_dist), 2)

    # 3. Calorie Attive da Movimento / Esercizi
    exercise_calories = 0.0
    try:
        sess_res = service.users().sessions().list(
            userId='me',
            startTime=start_dt.isoformat() + 'Z',
            endTime=end_dt.isoformat() + 'Z'
        ).execute()
        sessions = sess_res.get('session', [])

        for s in sessions:
            s_start_ms = int(s['startTimeMillis'])
            s_end_ms = int(s['endTimeMillis'])
            dur_min = (s_end_ms - s_start_ms) / 60000
            act_type = s.get('activityType')

            is_exercise = False
            if act_type in [8, 88, 25, 57, 97, 108]:
                is_exercise = True
            elif act_type == 7 and dur_min <= 90:
                is_exercise = True

            if not is_exercise:
                continue

            body_c = {
                'aggregateBy': [{'dataTypeName': 'com.google.calories.expended'}],
                'startTimeMillis': s_start_ms,
                'endTimeMillis': s_end_ms
            }
            res_c = service.users().dataset().aggregate(userId='me', body=body_c).execute()
            sess_cal = 0.0
            for b in res_c.get('bucket', []):
                for ds in b.get('dataset', []):
                    for pt in ds.get('point', []):
                        sess_cal += pt['value'][0].get('fpVal', 0)

            exercise_calories += sess_cal
    except Exception as e:
        print("Errore nel recupero sessioni:", e)

    # Calcolo calorie attive finali:
    # Se le calorie lette dai sensori sono irrealisticamente basse (< dist_km * 35 kcal, es. solo sensore passivo telefono 123 kcal),
    # usiamo la calibrazione esatta di Mi Fitness (60.74 kcal/km, derivata dai 489 kcal per 8.05 km dell'orologio).
    if dist_km > 0:
        mi_fit_cals = round(dist_km * 60.74)
        if exercise_calories < (dist_km * 35):
            active_cals = mi_fit_cals
        else:
            active_cals = round(exercise_calories)
    else:
        active_cals = round(exercise_calories)

    return {
        "date": target_date,
        "steps": steps,
        "active_calories": active_cals,
        "distance_km": dist_km
    }

def create_card_image(metrics, output_path="daily_fitness_card.png"):
    target_date = metrics["date"]
    steps = metrics["steps"]
    active_calories = metrics["active_calories"]
    dist_km = metrics["distance_km"]

    # Download random background image from Picsum
    req = urllib.request.Request('https://picsum.photos/800/600', headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as resp:
        bg_data = resp.read()

    img = Image.open(io.BytesIO(bg_data)).convert('RGBA')
    bg_blurred = img.filter(ImageFilter.GaussianBlur(radius=2))

    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Central dark card
    draw.rounded_rectangle([70, 60, 730, 520], radius=24, fill=(15, 23, 42, 215), outline=(255, 255, 255, 40), width=2)

    fonts_dir = BASE_DIR / 'fonts'
    reg_font_path = str(fonts_dir / 'segoeui.ttf') if (fonts_dir / 'segoeui.ttf').exists() else 'C:/Windows/Fonts/segoeui.ttf'
    bold_font_path = str(fonts_dir / 'segoeuib.ttf') if (fonts_dir / 'segoeuib.ttf').exists() else 'C:/Windows/Fonts/segoeuib.ttf'

    try:
        font_date = ImageFont.truetype(reg_font_path, 24)
        font_steps_num = ImageFont.truetype(bold_font_path, 76)
        font_label = ImageFont.truetype(bold_font_path, 22)
        font_stat_val = ImageFont.truetype(bold_font_path, 36)
        font_stat_lbl = ImageFont.truetype(reg_font_path, 19)
    except Exception:
        font_date = ImageFont.load_default()
        font_steps_num = font_label = font_stat_val = font_stat_lbl = ImageFont.load_default()

    date_str = target_date.strftime('%A, %d %B %Y').upper()
    it_days = {'MONDAY': 'LUNEDÌ', 'TUESDAY': 'MARTEDÌ', 'WEDNESDAY': 'MERCOLEDÌ', 'THURSDAY': 'GIOVEDÌ', 'FRIDAY': 'VENERDÌ', 'SATURDAY': 'SABATO', 'SUNDAY': 'DOMENICA'}
    it_months = {'OCTOBER': 'OTTOBRE', 'NOVEMBER': 'NOVEMBRE', 'DECEMBER': 'DICEMBRE', 'JANUARY': 'GENNAIO', 'FEBRUARY': 'FEBBRAIO', 'MARCH': 'MARZO', 'APRIL': 'APRILE', 'MAY': 'MAGGIO', 'JUNE': 'GIUGNO', 'JULY': 'LUGLIO', 'AUGUST': 'AGOSTO', 'SEPTEMBER': 'SETTEMBRE'}
    for en, it in it_days.items(): date_str = date_str.replace(en, it)
    for en, it in it_months.items(): date_str = date_str.replace(en, it)

    # Date
    draw.text((400, 115), date_str, fill=(148, 163, 184, 255), font=font_date, anchor='mm')

    # Steps
    draw.text((400, 220), f'{steps:,}'.replace(',', '.'), fill=(255, 255, 255, 255), font=font_steps_num, anchor='mm')
    draw.text((400, 280), 'PASSI GIORNALIERI', fill=(56, 189, 248, 255), font=font_label, anchor='mm')

    # Divider
    draw.line([(150, 330), (650, 330)], fill=(255, 255, 255, 30), width=2)

    # Calories consumed by exercises / active movement
    draw.text((260, 405), f'{active_calories} kcal', fill=(249, 115, 22, 255), font=font_stat_val, anchor='mm')
    draw.text((260, 448), 'Calorie Attive', fill=(203, 213, 225, 255), font=font_stat_lbl, anchor='mm')

    # Distance
    draw.text((540, 405), f'{dist_km} km', fill=(52, 211, 153, 255), font=font_stat_val, anchor='mm')
    draw.text((540, 448), 'Distanza Percorsa', fill=(203, 213, 225, 255), font=font_stat_lbl, anchor='mm')

    final_img = Image.alpha_composite(bg_blurred, overlay).convert('RGB')
    final_img.save(output_path)
    return output_path

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Genera la scheda fitness del giorno")
    parser.add_argument('--date', type=str, default=None, help="Data nel formato YYYY-MM-DD")
    parser.add_argument('--yesterday', action='store_true', help="Usa il giorno di ieri")
    parser.add_argument('--output', type=str, default="today_card.png", help="Nome file immagine di output")
    args = parser.parse_args()

    target_d = None
    if args.yesterday:
        target_d = datetime.date.today() - datetime.timedelta(days=1)
    elif args.date:
        target_d = args.date

    metrics = fetch_daily_metrics(target_d)
    print("Metriche estratte:", metrics)
    out = create_card_image(metrics, args.output)
    print("Immagine creata:", out)
