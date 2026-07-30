import json
import time
import os

from openai import OpenAI
from google.cloud import storage
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------------- CONFIG ----------------

TELEGRAM_BOT_TOKEN = os.getenv("BOT_TOKEN")
AIPIPE_TOKEN = os.getenv("PIPE_TOKEN")

BUCKET_NAME = "devjoshi-telegram-logs"
LOG_OBJECT = "run.jsonl"

LOG_URL = f"https://storage.googleapis.com/{BUCKET_NAME}/{LOG_OBJECT}"

# ----------------------------------------

client = OpenAI(
    base_url="https://aipipe.org/openai/v1",
    api_key=AIPIPE_TOKEN,
)

storage_client = storage.Client()
bucket = storage_client.bucket(BUCKET_NAME)
blob = bucket.blob(LOG_OBJECT)

conversation_history = {}


def log_event(event: dict):
    """Append a JSON object to run.jsonl stored in Google Cloud Storage."""
    event["timestamp"] = time.time()

    try:
        existing = blob.download_as_text()
    except Exception:
        existing = ""

    new_line = json.dumps(event)

    if existing.strip():
        updated = existing.rstrip() + "\n" + new_line
    else:
        updated = new_line

    blob.upload_from_string(
        updated,
        content_type="application/json",
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text

    log_event(
        {
            "type": "incoming",
            "chat_id": chat_id,
            "text": user_text,
        }
    )

    history = conversation_history.setdefault(chat_id, [])
    history.append(
        {
            "role": "user",
            "content": user_text,
        }
    )

    system_prompt = (
        "You are a careful data analyst. "
        "The user's LAST message asks a data-analysis question and tells you "
        "exactly what JSON shape to reply with. "
        "Work out the real answer. "
        "Reply with ONLY the JSON object requested. "
        "Do not include explanations, markdown or code fences."
    )

    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {
                "role": "system",
                "content": system_prompt,
            }
        ]
        + history[-6:],
    )

    reply_text = response.choices[0].message.content.strip()

    history.append(
        {
            "role": "assistant",
            "content": reply_text,
        }
    )

    try:
        parsed = json.loads(reply_text)
    except json.JSONDecodeError:
        start = reply_text.find("{")
        end = reply_text.rfind("}")

        if start == -1 or end == -1:
            parsed = {"answer": reply_text}
        else:
            parsed = json.loads(reply_text[start : end + 1])

    parsed["log_url"] = LOG_URL

    final_reply = json.dumps(parsed)

    log_event(
        {
            "type": "outgoing",
            "chat_id": chat_id,
            "text": final_reply,
        }
    )

    await update.message.reply_text(final_reply)


app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message,
    )
)

print("Bot is running...")

app.run_polling()