# flux_bot.py

import logging
import os
import uuid
import asyncio
import glob
from datetime import datetime
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

COMFYUI_PATH = "/home/duxon/Tools/ComfyUI"
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

# --- New Helper Functions ---

def cleanup_workspace():
    """Removes leftover image files from previous runs at startup."""
    logger.info("Cleaning up workspace from previous runs...")
    input_files = glob.glob("input_*.png")
    output_files = glob.glob("flux_output.png")
    
    for f_path in input_files + output_files:
        try:
            os.remove(f_path)
            logger.info(f"Removed leftover file: {f_path}")
        except OSError as e:
            logger.error(f"Error removing file {f_path}: {e}")

def log_generation():
    """Appends a timestamp to the generation log file."""
    log_message = f"Image generated at: {datetime.now().isoformat()}\n"
    try:
        with open("generation_log.txt", "a") as log_file:
            log_file.write(log_message)
    except IOError as e:
        logger.error(f"Failed to write to generation_log.txt: {e}")

# --- Core Bot Logic ---

async def run_generation_process(context: ContextTypes.DEFAULT_TYPE, chat_id: int, prompt: str, image_path: str):
    """The central function to run the ComfyUI workflow, protected by a lock and run in a separate thread."""
    async with generation_lock:
        try:
            await context.bot.send_message(chat_id, "✅ Your turn! Starting generation process... This will take around 5 minutes.")
            
            output_image_path = await asyncio.to_thread(
                manager.run_workflow,
                input_image_path=image_path,
                positive_prompt=prompt
            )

            if output_image_path and os.path.exists(output_image_path):
                log_generation()
                await context.bot.send_message(chat_id, "Generation complete! Sending your image...")
                await context.bot.send_photo(chat_id, photo=open(output_image_path, 'rb'))
            else:
                # This 'else' block will now be reached if the process was killed
                # and didn't produce an output, so no extra message is needed here.
                pass

        except Exception as e:
            logger.error(f"An error occurred during generation for chat {chat_id}: {e}")
            await context.bot.send_message(chat_id, f"An error occurred: {e}")
        
        finally:
            logger.info(f"Cleaning up files for chat {chat_id}.")
            if os.path.exists(image_path):
                os.remove(image_path)
            if 'output_image_path' in locals() and os.path.exists(output_image_path):
                os.remove(output_image_path)
            
            # This is a safer way to remove the user from the dict
            user_data.pop(chat_id, None)


# --- Telegram Handlers ---

async def kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kills the running ComfyUI process and clears the queue."""
    chat_id = update.message.chat_id
    logger.warning(f"Kill command issued by user {chat_id}.")
    
    # Check if a process is actually running
    if not generation_lock.locked():
        await update.message.reply_text("No generation process is currently running.")
        return

    # Create a copy of user data before clearing it
    queued_users = dict(user_data)
    user_data.clear()

    # Kill the server process
    manager.kill_server()

    await update.message.reply_text("🚨 The generation process has been... terminated. The queue is cleared.")

    # Notify all users who were in the queue
    for user_id, data in queued_users.items():
        # Clean up the input file for the queued user
        if "image_path" in data and os.path.exists(data["image_path"]):
            os.remove(data["image_path"])
        
        # Send a funny message
        try:
            await context.bot.send_message(
                user_id,
                "Looks like the admin tripped over the power cord. 🔌\n\n"
                "The generation process has been abruptly stopped. Please submit your request again."
            )
        except Exception as e:
            logger.error(f"Failed to send kill notification to {user_id}: {e}")


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

    # Add the new /kill command handler
    application.add_handler(CommandHandler("kill", kill))
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))

    print("Bot is running... Press Ctrl-C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    cleanup_workspace()
    main()
