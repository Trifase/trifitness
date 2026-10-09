import sys

# 1. Update cron_jobs.py
with open('/home/luca/emily/cron_jobs.py', 'r', encoding='utf-8') as f:
    cron_content = f.read()

if 'post_daily_fitness' not in cron_content:
    cron_addition = """

async def post_daily_fitness(context: ContextTypes.DEFAULT_TYPE) -> bool:
    import subprocess
    print(f"{get_now()} [AUTO] Eseguo lo script dei passi e invio la scheda sul canale fitness")
    channel_id = -1004324070335
    fitness_dir = "/home/luca/scripts/fitness_card"
    output_image = os.path.join(fitness_dir, "today_card.png")

    uv_path = "/home/luca/.local/bin/uv"
    if not os.path.exists(uv_path):
        uv_path = "uv"

    cmd = [uv_path, "run", "--directory", fitness_dir, "generate_card.py"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"{get_now()} [ERROR] Errore esecuzione fitness card: {proc.stderr}")
        raise RuntimeError(f"Errore generazione fitness card: {proc.stderr}")

    if not os.path.exists(output_image):
        print(f"{get_now()} [ERROR] Immagine fitness non trovata in {output_image}")
        raise FileNotFoundError(f"Immagine non trovata: {output_image}")

    with open(output_image, "rb") as photo_file:
        await context.bot.send_photo(chat_id=channel_id, photo=photo_file)

    print(f"{get_now()} [AUTO] Scheda fitness inviata con successo su {channel_id}")
    return True
"""
    with open('/home/luca/emily/cron_jobs.py', 'w', encoding='utf-8') as f:
        f.write(cron_content + cron_addition)
    print("cron_jobs.py updated successfully.")
else:
    print("post_daily_fitness already in cron_jobs.py.")

# 2. Update admin.py
with open('/home/luca/emily/admin.py', 'r', encoding='utf-8') as f:
    admin_content = f.read()

if 'posta_passi' not in admin_content:
    admin_addition = """

async def posta_passi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in config.ADMINS:
        return
    await printlog(update, "posta manualmente la scheda dei passi nel canale")
    status_msg = await update.message.reply_html("⏳ Generazione e invio scheda passi in corso...")
    try:
        from cron_jobs import post_daily_fitness
        await post_daily_fitness(context)
        await status_msg.edit_text("✅ Scheda passi inviata con successo sul canale!")
    except Exception as e:
        await status_msg.edit_text(f"❌ Errore durante l'invio:\\n{e}")
"""
    with open('/home/luca/emily/admin.py', 'w', encoding='utf-8') as f:
        f.write(admin_content + admin_addition)
    print("admin.py updated successfully.")
else:
    print("posta_passi already in admin.py.")

# 3. Update handlers.py
with open('/home/luca/emily/handlers.py', 'r', encoding='utf-8') as f:
    handlers_content = f.read()

if 'posta_passi' not in handlers_content:
    # Add import
    target_imp = "from admin import ("
    replacement_imp = "from admin import (\n    posta_passi,"
    handlers_content = handlers_content.replace(target_imp, replacement_imp, 1)

    # Add handler
    target_handler = "# admin.py"
    handler_code = """# admin.py
    h[-10] = [
        CommandHandler(
            ["posta_passi", "postapassi"],
            posta_passi,
            filters=~filters.UpdateType.EDITED & filters.User(config.ID_TRIF),
        )
    ]"""
    handlers_content = handlers_content.replace(target_handler, handler_code, 1)

    with open('/home/luca/emily/handlers.py', 'w', encoding='utf-8') as f:
        f.write(handlers_content)
    print("handlers.py updated successfully.")
else:
    print("posta_passi already in handlers.py.")

# 4. Update main.py
with open('/home/luca/emily/main.py', 'r', encoding='utf-8') as f:
    main_content = f.read()

if 'post_daily_fitness' not in main_content:
    # Add import
    target_main_imp = "from cron_jobs import ("
    replacement_main_imp = "from cron_jobs import (\n    post_daily_fitness,"
    main_content = main_content.replace(target_main_imp, replacement_main_imp, 1)

    # Add job
    target_job = "j.run_daily(check_compleanni, datetime.time(hour=0, minute=0, tzinfo=pytz.timezone(\"Europe/Rome\")), data=None)"
    job_code = """j.run_daily(post_daily_fitness, datetime.time(hour=23, minute=45, tzinfo=pytz.timezone("Europe/Rome")), data=None)
    j.run_daily(check_compleanni, datetime.time(hour=0, minute=0, tzinfo=pytz.timezone("Europe/Rome")), data=None)"""
    main_content = main_content.replace(target_job, job_code, 1)

    with open('/home/luca/emily/main.py', 'w', encoding='utf-8') as f:
        f.write(main_content)
    print("main.py updated successfully.")
else:
    print("post_daily_fitness already in main.py.")
