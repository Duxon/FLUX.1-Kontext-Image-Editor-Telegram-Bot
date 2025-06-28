# flux_bot.py (Skeleton for next step)

from comfy_api_manager import ComfyAPIManager
import os
import uuid

# This would be the main logic for your Telegram bot

# --- Configuration for the manager ---
# All settings are now cleanly separated from the bot logic
COMFYUI_PATH = "/home/duxon/Tools/ComfyUI" # Absolute path
CONDA_ENV = "comfyui"
WORKFLOW_PATH = "FLUX-Kontext-Python.json"
SERVER_ADDRESS = "127.0.0.1:8188"
NODE_IDS = {
    "load_image": "41",
    "clip_text": "6"
}

# 1. Instantiate the manager once when the bot starts
manager = ComfyAPIManager(SERVER_ADDRESS, CONDA_ENV, COMFYUI_PATH, WORKFLOW_PATH, NODE_IDS)

def handle_telegram_request(user_image_path, user_prompt):
    """
    This function represents the core logic that will be triggered
    by a user sending an image and prompt to the bot.
    """
    print(f"Received request. Image: {user_image_path}, Prompt: '{user_prompt}'")
    
    # Each request triggers a full start-run-stop cycle
    output_image = manager.run_workflow(
        input_image_path=user_image_path,
        positive_prompt=user_prompt,
        output_filename=f"result_{uuid.uuid4()}.png" # Unique filename for each result
    )

    if output_image:
        print(f"Workflow complete. Result saved to: {output_image}")
        # In a real bot, you would send this image file back to the user
        # send_image_to_telegram_user(output_image)
        # os.remove(output_image) # Clean up the file after sending
    else:
        print("Workflow failed to produce an image.")
        # send_error_message_to_user()


if __name__ == '__main__':
    # This is a simple test to show how to use the manager
    # In the real bot, this logic will be inside your Telegram message handlers
    print("--- Running a test of the ComfyAPIManager ---")
    
    test_image = "./image.png" # Make sure you have a test image here
    test_prompt = 'a man plays the piano'
    
    if os.path.exists(test_image):
        handle_telegram_request(test_image, test_prompt)
    else:
        print(f"Error: Test image not found at '{test_image}'")
    
    print("\n--- Test finished ---")
