with open('/home/luca/emily/main.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace(
    '    j.run_daily(post_daily_fitness,\n    sync_zepp_wellness, datetime.time(hour=23, minute=45, tzinfo=pytz.timezone("Europe/Rome")), data=None)',
    '    j.run_daily(post_daily_fitness, datetime.time(hour=23, minute=45, tzinfo=pytz.timezone("Europe/Rome")), data=None)'
)

with open('/home/luca/emily/main.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("main.py fixed successfully.")
