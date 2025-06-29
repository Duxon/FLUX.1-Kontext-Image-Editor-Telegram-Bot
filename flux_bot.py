# flux_bot.py

import logging
import os
import uuid
import asyncio
import glob
import re
import subprocess
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
GENERATION_TIME_MINUTES = 5
VRAM_THRESHOLD_PERCENT = 20
VRAM_POLL_INTERVAL_SECONDS = 300 # 5 minutes

manager = ComfyAPIManager(SERVER_ADDRESS, CONDA_ENV, COMFYUI_PATH, WORKFLOW_PATH, NODE_IDS)
user_data = {}
job_queue = asyncio.Queue()

# --- Helper Functions ---

def cleanup_workspace():
    # (No changes to this function)
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
    # (No changes to this function)
    log_message = f"Image generated at: {datetime.now().isoformat()}\n"
    try:
        with open("generation_log.txt", "a") as log_file:
            log_file.write(log_message)
    except IOError as e:
        logger.error(f"Failed to write to generation_log.txt: {e}")
        
async def check_vram():
    # (No changes to this function)
    """Checks if VRAM usage is below the threshold using nvidia-smi in a non-blocking way."""
    try:
        command = "nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits"
        result = await asyncio.to_thread(
            subprocess.check_output, command, shell=True, text=True
        )
        used, total = map(int, re.split(r',\s*', result.strip()))
        usage_percent = (used / total) * 100
        logger.info(f"Current VRAM usage: {usage_percent:.2f}% ({used}/{total} MiB)")
        return usage_percent < VRAM_THRESHOLD_PERCENT
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.warning("nvidia-smi command not found or failed. Assuming VRAM is available.")
        return True
    except Exception as e:
        logger.error(f"An error occurred checking VRAM: {e}")
        return True

# --- Core Bot Logic ---

async def worker():
    """The single consumer that processes jobs from the queue one by one."""
    while True:
        job = await job_queue.get()
        chat_id = job["chat_id"]
        prompt = job["prompt"]
        image_path = job["image_path"]
        context = job["context"]
        prompt_message_id = job["prompt_message_id"]

        try:
            # --- MODIFIED LOGIC: VRAM CHECK ---
            # First, check if the server is already running from a previous job.
            server_was_running = await asyncio.to_thread(manager.is_server_running)

            # Only perform the VRAM check if the server is starting from a cold state.
            if not server_was_running:
                wait_message = None
                while not await check_vram():
                    message_text = f"High VRAM usage detected. Your job is paused. Will check again in {VRAM_POLL_INTERVAL_SECONDS // 60} minutes."
                    if wait_message:
                        await context.bot.edit_message_text(chat_id=chat_id, message_id=wait_message.message_id, text=message_text + f"\n(Last checked: {datetime.now().strftime('%H:%M:%S')})")
                    else:
                        wait_message = await context.bot.send_message(chat_id, message_text, reply_to_message_id=prompt_message_id)
                    await asyncio.sleep(VRAM_POLL_INTERVAL_SECONDS)
                
                if wait_message:
                     await context.bot.edit_message_text(chat_id=chat_id, message_id=wait_message.message_id, text="✅ VRAM is now available. Starting your job...")
            
            # --- END MODIFIED LOGIC ---

            # Start server (this is a no-op if it was already running)
            await asyncio.to_thread(manager.start_server)

            await context.bot.send_message(chat_id, f"✅ Your turn! Starting generation process... This will take around {GENERATION_TIME_MINUTES} minutes.", reply_to_message_id=prompt_message_id)
            
            output_image_path = await asyncio.to_thread(
                manager.run_workflow,
                input_image_path=image_path,
                positive_prompt=prompt
            )

            if output_image_path and os.path.exists(output_image_path):
                log_generation()
                await context.bot.send_message(chat_id, "Generation complete! Sending your image...", reply_to_message_id=prompt_message_id)
                await context.bot.send_photo(chat_id, photo=open(output_image_path, 'rb'), reply_to_message_id=prompt_message_id)
            else:
                await context.bot.send_message(chat_id, "Sorry, the generation failed to produce an image.", reply_to_message_id=prompt_message_id)

        except Exception as e:
            logger.error(f"An error occurred during generation for chat {chat_id}: {e}")
            await context.bot.send_message(chat_id, f"An error occurred: {e}", reply_to_message_id=prompt_message_id)
        
        finally:
            logger.info(f"Cleaning up files for chat {chat_id}.")
            if os.path.exists(image_path):
                os.remove(image_path)
            if 'output_image_path' in locals() and os.path.exists(output_image_path):
                os.remove(output_image_path)
            
            # Conditional server shutdown
            job_queue.task_done()
            if job_queue.empty():
                logger.info("Job queue is empty. Shutting down ComfyUI server.")
                await asyncio.to_thread(manager.stop_server)

# --- Telegram Handlers (No changes below this line) ---
async def log_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"/log command issued by user {update.effective_user.id}")
    log_file_path = "generation_log.txt"
    num_lines = 20

    try:
        if not os.path.exists(log_file_path):
            await update.message.reply_text("No log file found yet.")
            return

        with open(log_file_path, "r") as f:
            lines = f.readlines()

        if not lines:
            await update.message.reply_text("The log file is empty.")
            return

        recent_lines = lines[-num_lines:]
        log_content = "".join(recent_lines)
        
        message = f"Here are the last {len(recent_lines)} log entries:\n```\n{log_content}```"
        await update.message.reply_text(message, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error reading log file: {e}")
        await update.message.reply_text("Sorry, there was an error reading the log file.")

async def kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    logger.warning(f"Kill command issued by user {chat_id}.")
    
    jobs_cleared = 0
    waiting_jobs = []
    while not job_queue.empty():
        try:
            waiting_jobs.append(job_queue.get_nowait())
            jobs_cleared += 1
        except asyncio.QueueEmpty:
            break
    
    manager.kill_server()
    await update.message.reply_text(f"🚨 Server process killed. {jobs_cleared} job(s) in the queue were cleared.")

    for job in waiting_jobs:
        user_id_to_notify = job["chat_id"]
        image_to_delete = job["image_path"]
        if os.path.exists(image_to_delete):
            os.remove(image_to_delete)
        
        try:
            await context.bot.send_message(
                user_id_to_notify,
                "Looks like the admin tripped over the power cord. 🔌\n\n"
                "The generation process has been abruptly stopped. Please submit your request again."
            )
        except Exception as e:
            logger.error(f"Failed to send kill notification to {user_id_to_notify}: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_html(
        f"Hi {user.first_name}!\n\n"
        "I am a bot that can reimagine an image based on your text prompt. "
        "If I am busy, your request will be added to a queue and you'll be notified of your position. "
        "\n\nBy the way, I am deleting all data after processing each image. You can find my source code here: https://github.com/Duxon/FLUX.1-Kontext-Image-Editor-Telegram-Bot"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(
        "<b>How to use this bot:</b>\n\n"
        "1. **Easiest way:** Send an image and type your prompt in the caption.\n"
        "2. **Alternate ways:** Send an image or a prompt first, and I will ask for the other piece.\n\n"
        "Your request will be processed in the order it was received."
    )

async def handle_request(context: ContextTypes.DEFAULT_TYPE, update: Update, prompt: str, image_path: str, prompt_message_id: int):
    """Adds a job to the queue and notifies the user of their position."""
    chat_id = update.message.chat_id
    
    position = job_queue.qsize() + 1
    wait_time = (position - 1) * GENERATION_TIME_MINUTES

    if wait_time > 0:
        await context.bot.send_message(chat_id, f"Got it! You are number **{position}** in the queue.\nEstimated wait time is ~{wait_time} minutes.", parse_mode='Markdown', reply_to_message_id=prompt_message_id)
    else:
        await context.bot.send_message(chat_id, "Got it! Your request is next in line.", reply_to_message_id=prompt_message_id)
    
    job = {"chat_id": chat_id, "prompt": prompt, "image_path": image_path, "context": context, "prompt_message_id": prompt_message_id}
    await job_queue.put(job)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    prompt = update.message.text
    prompt_message_id = update.message.message_id

    if chat_id in user_data and user_data[chat_id]["state"] == "awaiting_prompt":
        image_path = user_data[chat_id]["image_path"]
        user_data.pop(chat_id, None)
        await handle_request(context, update, prompt, image_path, prompt_message_id)
    else:
        user_data[chat_id] = {"state": "awaiting_image", "prompt": prompt, "prompt_message_id": prompt_message_id}
        await update.message.reply_text("Got your prompt! Now, please send me the image.")

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    image_message_id = update.message.message_id
    
    file = await context.bot.get_file(update.message.photo[-1].file_id)
    image_path = f"input_{uuid.uuid4()}.png"
    await file.download_to_drive(image_path)
    
    prompt = update.message.caption

    if prompt:
        await handle_request(context, update, prompt, image_path, image_message_id)
    elif chat_id in user_data and user_data[chat_id]["state"] == "awaiting_image":
        saved_prompt = user_data[chat_id]["prompt"]
        prompt_message_id = user_data[chat_id]["prompt_message_id"]
        user_data.pop(chat_id, None)
        await handle_request(context, update, saved_prompt, image_path, prompt_message_id)
    else:
        user_data[chat_id] = {"state": "awaiting_prompt", "image_path": image_path}
        await update.message.reply_text("Got your image! Now, please send me a text prompt for it.")

async def post_init(application: Application):
    logger.info("Application initialized. Starting background worker.")
    asyncio.create_task(worker())

def main():
    application = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("log", log_command))
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
