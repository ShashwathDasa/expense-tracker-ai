import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from telegram import Update

from app import create_bot
from config import Config

telegram_bot = create_bot()
application = telegram_bot.build_application()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await application.initialize()
    await application.start()
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    if render_url:
        webhook_url = f"{render_url}/telegram/webhook"
        await application.bot.set_webhook(webhook_url, secret_token=Config.TELEGRAM_WEBHOOK_SECRET)
    yield
    if render_url:
        await application.bot.delete_webhook()
    await application.stop()
    await application.shutdown()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret != Config.TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=403)
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return {"ok": True}
