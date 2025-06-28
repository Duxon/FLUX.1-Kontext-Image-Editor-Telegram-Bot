# flux_bot.py

import logging
import os
import uuid
import asyncio
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from comfy_api_manager import ComfyAPIManager

# --- Setup ---
load_dotenv()
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- Configuration ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN not found in .env file. Please create it and add your token.")

COMFYUI_PATH = "/home/duxon/Tools/ComfyUI" # Absolute path
CONDA_ENV = "comfyui"
WORKFLOW_PATH = "FLUX-Kontext-Python.json"
SERVER_ADDRESS = "127.0.0.1:8188"
NODE_IDS = {
    "load_image": "41",
    "clip_text": "6",
    "seed": "25"
}

manager = ComfyAPIManager(SERVER_ADDRESS, CONDA_ENV, COMFYUI_PATH, WORKFLOW_PATH, NODE_IDS)
user_data = {}
generation_lock = asyncio.Lock()

# --- Core Bot Logic ---

async def run_generation_process(context: ContextTypes.DEFAULT_TYPE, chat_id: int, prompt: str, image_path: str):
    """The central function to run the ComfyUI workflow, protected by a lock and run in a separate thread."""
    async with generation_lock:
        try:
            # Use the user's preferred message string
            await context.bot.send_message(chat_id, "✅ Your turn! Starting generation process... This will take around 5 minutes.")
            
            # --- This is the critical fix ---
            # Run the synchronous, blocking function in a separate thread
            # This frees up the main event loop to handle other messages.
            output_image_path = await asyncio.to_thread(
                manager.run_workflow,
                input_image_path=image_path,
                positive_prompt=prompt
            )

            if output_image_path and os.path.exists(output_image_path):
                await context.bot.send_message(chat_id, "Generation complete! Sending your image...")
                await context.bot.send_photo(chat_id, photo=open(output_image_path, 'rb'))
            else:
                await context.bot.send_message(chat_id, "Sorry, something went wrong during generation and no image was produced.")

        except Exception as e:
            logger.error(f"An error occurred during generation for chat {chat_id}: {e}")
            await context.bot.send_message(chat_id, f"An error occurred: {e}")
        
        finally:
            logger.info("Cleaning up image files.")
            if os.path.exists(image_path):
                os.remove(image_path)
            if 'output_image_path' in locals() and os.path.exists(output_image_path):
                os.remove(output_image_path)
            
            if chat_id in user_data:
                del user_data[chat_id]

# --- Telegram Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_message = (
        f"Hi {user.first_name}!\n\n"
        "I am a bot that can reimagine an image based on your text prompt, using a FLUX workflow.\n\n"
        "To get started, please send me an image with your prompt written in the caption. "
        "If I am busy with another request, yours will be added to a queue."
    )
    await update.message.reply_html(welcome_message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "How to use this bot:\n\n"
        "1. **Easiest way:** Send an image and type your creative prompt in the image caption.\n\n"
        "2. **Alternate way:** Send an image first, and I will ask for a prompt. Then, send the prompt in a separate message.\n\n"
        "3. **Another way:** Send a text prompt first, and I will ask for an image. Then, send the image in a separate message.\n\n"
        "Your request will be processed in the order it was received."
    )
    await update.message.reply_html(help_text)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    prompt = update.message.text

    if chat_id in user_data and user_data[chat_id]["state"] == "awaiting_prompt":
        image_path = user_data[chat_id]["image_path"]
        await update.message.reply_text("Got it! Your request has been added to the queue.")
        # We don't await the full process here, just schedule it
        asyncio.create_task(run_generation_process(context, chat_id, prompt, image_path))
    else:
        user_data[chat_id] = {"state": "awaiting_image", "prompt": prompt}
        await update.message.reply_text("Got your prompt! Now, please send me the image you want me to work on.")

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    
    file = await context.bot.get_file(update.message.photo[-1].file_id)
    image_path = f"input_{uuid.uuid4()}.png"
    await file.download_to_drive(image_path)
    
    prompt = update.message.caption

    if prompt:
        await update.message.reply_text("Got it! Your request has been added to the queue.")
        asyncio.create_task(run_generation_process(context, chat_id, prompt, image_path))
    elif chat_id in user_data and user_data[chat_id]["state"] == "awaiting_image":
        saved_prompt = user_data[chat_id]["prompt"]
        await update.message.reply_text("Got it! Your request has been added to the queue.")
        asyncio.create_task(run_generation_process(context, chat_id, saved_prompt, image_path))
    else:
        user_data[chat_id] = {"state": "awaiting_prompt", "image_path": image_path}
        await update.message.reply_text("Got your image! Now, please send me a text prompt for it.")

def main():
    """Start the bot."""
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))

    print("Bot is running... Press Ctrl-C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
