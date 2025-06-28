# TeleFlux 🚀 -- A Telegram bot that serves a FLUX.1 ComfyUI Workflow for convenient self-hosting

A Python-based Telegram bot for on-demand execution of ComfyUI FLUX workflows, featuring a robust job queue and automatic server lifecycle management. Ideal for running heavy AI models on a personal machine without leaving the server running 24/7.

This bot listens for image and prompt submissions on Telegram, spins up the ComfyUI server to handle the job, returns the generated image, and then shuts the server down, saving system resources.

---

### ✨ Features

* **On-Demand Server Lifecycle**: Automatically starts the ComfyUI server when the first job enters the queue and shuts it down after processing, minimizing resource usage.
* **Robust Job Queue**: Handles multiple concurrent users gracefully. Requests are processed one at a time, and users are notified of their position in the queue and the estimated wait time.
* **Stateful Conversation**: Remembers if a user has sent an image but not a prompt (or vice-versa) and prompts them for the missing piece.
* **Background Processing**: Uses `asyncio` correctly to run heavy generation tasks in a separate thread, keeping the bot fully responsive to new users and commands while a job is running.
* **Admin Commands**: Includes undocumented `/kill` and `/log` commands for easy administration and monitoring.
* **Automatic Cleanup**: Clears temporary input/output files on startup to keep the workspace tidy.
* **Secure Configuration**: Uses a `.env` file for secure handling of your Telegram API token.
* **Systemd Service Ready**: Comes with a `flux_bot.service` file for easy deployment as a persistent background service on Linux.

---

### 📂 Project Structure

```
.
├── comfy_api_manager.py        # Library for interfacing with the ComfyUI API
├── flux_bot.py                 # The main Telegram bot application
├── FLUX-Kontext-Python.json    # Your ComfyUI workflow in API format
├── .env.example                # Example environment file
├── .gitignore                  # Git ignore file for security and cleanliness
├── flux_bot.service            # Systemd service unit file for deployment
└── generation_log.txt          # (auto-generated) Log of successful generations
```

---

### 🛠️ Setup and Installation

Follow these steps to get your own instance of TeleFlux running.

**1. Clone the Repository**
```bash
git clone [<your-repository-url>](https://github.com/Duxon/FLUX.1-Kontext-Image-Editor-Telegram-Bot.git)
cd FLUX.1-Kontext-Image-Editor-Telegram-Bot
```

**2. Set Up the Conda Environment**

The bot is designed to run within a specific conda environment where `comfyui` and its dependencies are installed. Ensure your `comfyui` environment is ready. Then, install the bot's Python dependencies into it:

```bash
conda activate comfyui
pip install python-telegram-bot python-dotenv websocket-client requests
```

**3. Configure Your Bot**

* **API Token:** Rename the `.env.example` file to `.env`:
    ```bash
    mv .env.example .env
    ```
    Now, edit the `.env` file and paste your Telegram Bot API token.

* **Paths:** Open `flux_bot.py` and review the configuration section. You **must** update these two paths to match your system:
    ```python
    COMFYUI_PATH = "/home/duxon/Tools/ComfyUI" # <-- Set this to your ComfyUI path
    CONDA_ENV = "comfyui"                     # <-- The name of your conda environment
    ```

---

### 🚀 Running the Bot

You can run the bot in two ways:

**A) Directly from the Terminal (for testing)**

```bash
# Make sure you are in the correct environment
conda activate comfyui

# Run the bot
python flux_bot.py
```

**B) As a Systemd Service (for production)**

This will make the bot run automatically in the background and restart on boot.

1.  **Edit the service file:** Make sure the paths in `flux_bot.service` are correct for your system (they should be if you followed the setup above).

2.  **Install and start the service:**
    ```bash
    # Copy the service file to the systemd directory
    sudo cp flux_bot.service /etc/systemd/system/flux_bot.service

    # Reload systemd to recognize the new service
    sudo systemctl daemon-reload

    # Enable the service to start on boot
    sudo systemctl enable flux_bot.service

    # Start the service now
    sudo systemctl start flux_bot.service
    ```

3.  **Check the status and logs:**
    ```bash
    # Check if it's running correctly
    sudo systemctl status flux_bot.service

    # View live logs
    sudo journalctl -u flux_bot.service -f
    ```

---

### 🤖 Usage

Interact with your bot on Telegram:

* **/start**: Displays the welcome message.
* **/help**: Shows usage instructions.
* **Sending an Image**: Send an image with your prompt in the caption for the quickest result. You can also send them separately.

**Admin Commands**

* **/kill**: Forcefully stops any running ComfyUI server and clears all jobs from the queue. It will notify waiting users that their job was cancelled.
* **/log**: Displays the last 20 entries from the `generation_log.txt` file.

---

### 📜 License

This project is licensed under the MIT License. See the `LICENSE` file for details.
