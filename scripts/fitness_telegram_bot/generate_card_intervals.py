import os
import io
import sys
import argparse
import urllib.request
import datetime
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import requests

BASE_DIR = Path(__file__).resolve().parent

ATHLETE_ID = "i745424"
API_KEY = "6pdys6s3sc6br1wbtuqex26g1"
AUTH = ("API_KEY", API_KEY)

def fetch_intervals_metrics(target_date=None):
    if target_date is None:
        now = datetime.datetime.now()
        if now.hour < 7:
            target_date = now.date() - datetime.timedelta(days=1)
        else:
            target_date = now.date()
    elif isinstance(target_date, str):
        target_date = datetime.datetime.strptime(target_date, "%Y-%m-%d").date()
    elif isinstance(target_date, datetime.datetime):
        target_date = target_date.date()

    date_str = target_date.strftime("%Y-%m-%d")

    # 1. Fetch wellness data for daily steps and resting HR
    wellness_url = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/wellness/{date_str}"
    wellness_steps = 0
    resting_hr = None
    try:
        r_w = requests.get(wellness_url, auth=AUTH, timeout=10)
        if r_w.status_code == 200:
            w_data = r_w.json()
            wellness_steps = w_data.get("steps") or 0
            resting_hr = w_data.get("restingHR")
    except Exception as e:
        print(f"Errore recupero wellness: {e}")

    # 2. Fetch activities for the target date
    act_url = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/activities"
    params = {"oldest": date_str, "newest": date_str}
    
    total_distance_m = 0.0
    total_moving_time_s = 0
    total_calories = 0
    total_z2_z3_s = 0
    activity_steps = 0
    hr_weighted_sum = 0.0
    hr_time_sum = 0

    try:
        r_act = requests.get(act_url, auth=AUTH, params=params, timeout=10)
        if r_act.status_code == 200:
            acts = r_act.json()
            for a in acts:
                # We can fetch detailed activity if needed, or use fields directly
                act_id = a.get("id")
                # Single activity details have icu_hr_zone_times
                r_single = requests.get(f"https://intervals.icu/api/v1/activity/{act_id}", auth=AUTH, timeout=10)
                if r_single.status_code == 200:
                    d = r_single.json()
                else:
                    d = a

                dist = d.get("distance") or 0.0
                moving_s = d.get("moving_time") or 0
                cals = d.get("calories") or 0
                avg_hr = d.get("average_heartrate")
                zone_times = d.get("icu_hr_zone_times") or []

                total_distance_m += dist
                total_moving_time_s += moving_s
                total_calories += cals

                if avg_hr and moving_s > 0:
                    hr_weighted_sum += avg_hr * moving_s
                    hr_time_sum += moving_s

                # In 5-zone model:
                # index 0: Z1 (<114)
                # index 1: Z2 (115-123)
                # index 2: Z3 (124-132)
                if len(zone_times) >= 3:
                    total_z2_z3_s += (zone_times[1] or 0) + (zone_times[2] or 0)
                elif len(zone_times) == 2:
                    total_z2_z3_s += (zone_times[1] or 0)

                # Estimate activity steps from cadence if available
                cadence = d.get("average_cadence")
                if cadence and moving_s > 0:
                    # RPM (strides/min) * 2 = SPM
                    act_steps = round(cadence * 2 * (moving_s / 60))
                    activity_steps += act_steps
    except Exception as e:
        print(f"Errore recupero attività: {e}")

    final_steps = max(wellness_steps, activity_steps)
    dist_km = round(total_distance_m / 1000.0, 2)
    avg_hr_final = round(hr_weighted_sum / hr_time_sum) if hr_time_sum > 0 else (resting_hr or 0)
    
    total_min = round(total_moving_time_s / 60)
    z2_z3_min = round(total_z2_z3_s / 60)

    # Format moving time nicely (e.g., 35 min or 1h 15m)
    if total_min >= 60:
        h = total_min // 60
        m = total_min % 60
        time_str = f"{h}h {m}m" if m > 0 else f"{h}h"
    else:
        time_str = f"{total_min} min"

    return {
        "date": target_date,
        "steps": final_steps,
        "calories": total_calories,
        "distance_km": dist_km,
        "z2_z3_min": z2_z3_min,
        "avg_hr": avg_hr_final,
        "total_time_str": time_str,
        "total_time_min": total_min
    }

def create_intervals_card(metrics, output_path="intervals_daily_card.png"):
    target_date = metrics["date"]
    steps = metrics["steps"]
    calories = metrics["calories"]
    dist_km = metrics["distance_km"]
    z2_z3_min = metrics["z2_z3_min"]
    avg_hr = metrics["avg_hr"]
    total_time_str = metrics["total_time_str"]

    width, height = 860, 620

    # 1. Download aesthetic background or use solid dark gradient
    bg_data = None
    try:
        req = urllib.request.Request(
            f"https://picsum.photos/{width}/{height}",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            bg_data = resp.read()
        img = Image.open(io.BytesIO(bg_data)).convert("RGBA")
        bg_blurred = img.filter(ImageFilter.GaussianBlur(radius=5))
    except Exception:
        # Fallback background
        bg_blurred = Image.new("RGBA", (width, height), (15, 23, 42, 255))

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Dark background tint over photo
    draw.rectangle([0, 0, width, height], fill=(10, 15, 29, 140))

    # Glassmorphism Card Container
    card_bounds = [50, 45, width - 50, height - 45]
    draw.rounded_rectangle(
        card_bounds,
        radius=28,
        fill=(15, 23, 42, 225),
        outline=(255, 255, 255, 38),
        width=2
    )

    # Fonts
    fonts_dir = BASE_DIR / 'fonts'
    reg_font_path = str(fonts_dir / 'segoeui.ttf') if (fonts_dir / 'segoeui.ttf').exists() else 'C:/Windows/Fonts/segoeui.ttf'
    bold_font_path = str(fonts_dir / 'segoeuib.ttf') if (fonts_dir / 'segoeuib.ttf').exists() else 'C:/Windows/Fonts/segoeuib.ttf'

    try:
        font_date = ImageFont.truetype(reg_font_path, 22)
        font_main_val = ImageFont.truetype(bold_font_path, 52)
        font_main_lbl = ImageFont.truetype(bold_font_path, 18)
        font_cardio_val = ImageFont.truetype(bold_font_path, 42)
        font_cardio_lbl = ImageFont.truetype(reg_font_path, 18)
        font_tag = ImageFont.truetype(bold_font_path, 13)
    except Exception:
        font_date = font_main_val = font_main_lbl = font_cardio_val = font_cardio_lbl = font_tag = ImageFont.load_default()

    # Italian Date Formatting
    date_str = target_date.strftime('%A, %d %B %Y').upper()
    it_days = {'MONDAY': 'LUNEDÌ', 'TUESDAY': 'MARTEDÌ', 'WEDNESDAY': 'MERCOLEDÌ', 'THURSDAY': 'GIOVEDÌ', 'FRIDAY': 'VENERDÌ', 'SATURDAY': 'SABATO', 'SUNDAY': 'DOMENICA'}
    it_months = {'OCTOBER': 'OTTOBRE', 'NOVEMBER': 'NOVEMBRE', 'DECEMBER': 'DICEMBRE', 'JANUARY': 'GENNAIO', 'FEBRUARY': 'FEBBRAIO', 'MARCH': 'MARZO', 'APRIL': 'APRILE', 'MAY': 'MAGGIO', 'JUNE': 'GIUGNO', 'JULY': 'LUGLIO', 'AUGUST': 'AGOSTO', 'SEPTEMBER': 'SETTEMBRE'}
    for en, it in it_days.items(): date_str = date_str.replace(en, it)
    for en, it in it_months.items(): date_str = date_str.replace(en, it)

    # 1. Header Date
    draw.text((width // 2, 95), date_str, fill=(148, 163, 184, 255), font=font_date, anchor='mm')

    # 2. RIGA SUPERIORE (3 Colonne: Passi, Calorie, Distanza)
    # Centers at X: 190, 430, 670
    col_xs_top = [190, 430, 670]
    y_val_top = 195
    y_lbl_top = 245

    # Badge 1: Passi
    steps_formatted = f"{steps:,}".replace(",", ".")
    draw.text((col_xs_top[0], y_val_top), steps_formatted, fill=(255, 255, 255, 255), font=font_main_val, anchor='mm')
    draw.text((col_xs_top[0], y_lbl_top), "PASSI", fill=(56, 189, 248, 255), font=font_main_lbl, anchor='mm')

    # Badge 2: Calorie
    draw.text((col_xs_top[1], y_val_top), f"{calories} kcal", fill=(249, 115, 22, 255), font=font_main_val, anchor='mm')
    draw.text((col_xs_top[1], y_lbl_top), "CALORIE", fill=(251, 146, 60, 255), font=font_main_lbl, anchor='mm')

    # Badge 3: Distanza
    draw.text((col_xs_top[2], y_val_top), f"{dist_km:.2f} km", fill=(52, 211, 153, 255), font=font_main_val, anchor='mm')
    draw.text((col_xs_top[2], y_lbl_top), "DISTANZA", fill=(74, 222, 128, 255), font=font_main_lbl, anchor='mm')

    # Sottile linea divisoria con sfumatura
    draw.line([(90, 295), (width - 90, 295)], fill=(255, 255, 255, 30), width=2)

    # 3. RIGA INFERIORE (3 Box per Metriche Cardio / Qualità)
    box_w = 220
    box_h = 175
    box_y = 330
    box_xs = [85, 320, 555]

    # Box 1: Zona 2 + 3 (Focus Metabolico)
    bx1 = box_xs[0]
    draw.rounded_rectangle([bx1, box_y, bx1 + box_w, box_y + box_h], radius=18, fill=(30, 41, 59, 180), outline=(234, 179, 8, 80), width=1)
    # Tag piccolo
    draw.rounded_rectangle([bx1 + 18, box_y + 16, bx1 + 92, box_y + 36], radius=6, fill=(234, 179, 8, 40))
    draw.text((bx1 + 55, box_y + 26), "CARDIO", fill=(253, 224, 71, 255), font=font_tag, anchor='mm')
    # Valore
    draw.text((bx1 + box_w // 2, box_y + 85), f"{z2_z3_min} min", fill=(250, 204, 21, 255), font=font_cardio_val, anchor='mm')
    draw.text((bx1 + box_w // 2, box_y + 135), "Tempo Z2+Z3", fill=(203, 213, 225, 255), font=font_cardio_lbl, anchor='mm')

    # Box 2: Frequenza Media
    bx2 = box_xs[1]
    draw.rounded_rectangle([bx2, box_y, bx2 + box_w, box_y + box_h], radius=18, fill=(30, 41, 59, 180), outline=(244, 63, 94, 80), width=1)
    draw.rounded_rectangle([bx2 + 18, box_y + 16, bx2 + 92, box_y + 36], radius=6, fill=(244, 63, 94, 40))
    draw.text((bx2 + 55, box_y + 26), "BATTITI", fill=(253, 164, 175, 255), font=font_tag, anchor='mm')
    draw.text((bx2 + box_w // 2, box_y + 85), f"{avg_hr} bpm", fill=(251, 113, 133, 255), font=font_cardio_val, anchor='mm')
    draw.text((bx2 + box_w // 2, box_y + 135), "Frequenza media", fill=(203, 213, 225, 255), font=font_cardio_lbl, anchor='mm')

    # Box 3: Durata Allenamento
    bx3 = box_xs[2]
    draw.rounded_rectangle([bx3, box_y, bx3 + box_w, box_y + box_h], radius=18, fill=(30, 41, 59, 180), outline=(129, 140, 248, 80), width=1)
    draw.rounded_rectangle([bx3 + 18, box_y + 16, bx3 + 115, box_y + 36], radius=6, fill=(129, 140, 248, 40))
    draw.text((bx3 + 66, box_y + 26), "MOVIMENTO", fill=(199, 210, 254, 255), font=font_tag, anchor='mm')
    draw.text((bx3 + box_w // 2, box_y + 85), total_time_str, fill=(165, 180, 252, 255), font=font_cardio_val, anchor='mm')
    draw.text((bx3 + box_w // 2, box_y + 135), "Durata allenamento", fill=(203, 213, 225, 255), font=font_cardio_lbl, anchor='mm')

    final_img = Image.alpha_composite(bg_blurred, overlay).convert('RGB')
    final_img.save(output_path)
    return output_path

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Genera la scheda fitness tramite Intervals.icu")
    parser.add_argument('--date', type=str, default=None, help="Data nel formato YYYY-MM-DD")
    parser.add_argument('--yesterday', action='store_true', help="Usa il giorno di ieri")
    parser.add_argument('--output', type=str, default="intervals_today_card.png", help="Nome file immagine di output")
    args = parser.parse_args()

    target_d = None
    if args.yesterday:
        target_d = datetime.date.today() - datetime.timedelta(days=1)
    elif args.date:
        target_d = args.date

    metrics = fetch_intervals_metrics(target_d)
    print("Metriche estratte da Intervals.icu:", metrics)
    out = create_intervals_card(metrics, args.output)
    print(f"Immagine generata con successo: {out}")
