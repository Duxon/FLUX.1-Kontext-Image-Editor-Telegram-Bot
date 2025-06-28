from llama_cpp import Llama
import base64
from PIL import Image
import io
import os

# --- Configuration ---
MODEL_PATH = "./flux1-kontext-dev-Q6_K.gguf"
IMAGE_PATH = "image.png"
OUTPUT_PATH = "edited_image_gguf.png"
PROMPT = "Add a pirate hat to the main subject."

# --- Check for input files ---
if not os.path.exists(MODEL_PATH):
    print(f"Error: Model not found at '{MODEL_PATH}'")
    exit()
if not os.path.exists(IMAGE_PATH):
    print(f"Error: Input image not found at '{IMAGE_PATH}'")
    exit()

# --- Model Loading (Simplified) ---
print("Loading GGUF model... This may take a moment.")
try:
    llm = Llama(
        model_path=MODEL_PATH,
        chat_format="llava-1-5",  # Let Llama handle the handler setup internally
        n_ctx=2048,
        n_gpu_layers=-1, # Offload all possible layers to the GPU
        verbose=True
    )
    print("Model loaded successfully.")
except Exception as e:
    print(f"Failed to load model with new method. Error: {e}")
    exit()


# --- Prepare Image and Prompt ---
def load_image_as_base64(image_path):
    with Image.open(image_path) as img:
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode('utf-8')

image_b64 = load_image_as_base64(IMAGE_PATH)

# --- Inference ---
print(f"Running inference with prompt: '{PROMPT}'")
response = llm.create_chat_completion(
    messages=[
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                {"type": "text", "text": PROMPT}
            ]
        }
    ]
)

# --- Process Result ---
try:
    assistant_message = response['choices'][0]['message']['content']
    saved_image_b64 = None
    for part in assistant_message:
        if part['type'] == 'image_url':
            saved_image_b64 = part['image_url']['url'].split(',', 1)[1]
            break

    if saved_image_b64:
        img_data = base64.b64decode(saved_image_b64)
        with open(OUTPUT_PATH, "wb") as f:
            f.write(img_data)
        print(f"Successfully saved edited image to '{OUTPUT_PATH}'")
    else:
        print("Model did not return an image. Full response:")
        print(response)

except (KeyError, IndexError, TypeError) as e:
    print(f"Could not parse the image from the model's response. Error: {e}")
    print("Full response:")
    print(response)
