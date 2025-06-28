# comfy_api_manager.py

import websocket
import uuid
import json
import urllib.request
import urllib.parse
import os
import requests
import subprocess
import time
import socket
import signal

class ComfyAPIManager:
    """A class to manage the ComfyUI server and workflow execution."""

    def __init__(self, server_address, conda_env, comfyui_path, workflow_path, node_ids):
        self.server_address = server_address
        self.client_id = str(uuid.uuid4())
        self.server_process = None
        
        self.conda_env_name = conda_env
        self.comfyui_path = comfyui_path
        self.workflow_api_json_path = workflow_path
        
        self.load_image_node_id = node_ids["load_image"]
        self.clip_text_node_id = node_ids["clip_text"]
        self.seed_node_id = node_ids["seed"]

    def _is_server_running(self):
        host, port = self.server_address.split(':')
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.settimeout(1)
                s.connect((host, int(port)))
                return True
            except (ConnectionRefusedError, socket.timeout):
                return False

    def _start_server(self):
        if self._is_server_running():
            print("Server is already running.")
            return

        print("Starting ComfyUI server...")
        command = [
            "conda", "run", "-n", self.conda_env_name,
            "python", "main.py", "--lowvram", "--listen", "0.0.0.0"
        ]
        
        self.server_process = subprocess.Popen(
            command, 
            cwd=self.comfyui_path,
            start_new_session=True
        )
        
        print("Waiting for server to start...", end="", flush=True)
        for _ in range(60):
            time.sleep(1)
            print(".", end="", flush=True)
            if self._is_server_running():
                print("\nServer started successfully.")
                return
        
        print("\nError: Server did not start in time.")
        self._stop_server()
        raise RuntimeError("Server failed to start.")

    def _stop_server(self):
        if self.server_process:
            print("Shutting down ComfyUI server process group...")
            try:
                pgid = os.getpgid(self.server_process.pid)
                os.killpg(pgid, signal.SIGTERM)
                time.sleep(3)
                os.killpg(pgid, signal.SIGKILL)
                print("Server process group terminated.")
            except ProcessLookupError:
                print("Server process was already shut down.")
            except Exception as e:
                print(f"An error occurred during server shutdown: {e}")
            finally:
                self.server_process = None
    
    def kill_server(self):
        """Public method to safely stop the server."""
        self._stop_server()

    def _upload_image(self, filepath):
        filename = os.path.basename(filepath)
        with open(filepath, 'rb') as f:
            files = {'image': (filename, f.read(), 'image/png')}
        data = {'overwrite': 'true'}
        resp = requests.post(f"http://{self.server_address}/upload/image", files=files, data=data)
        resp.raise_for_status()
        return resp.json()['name']

    def _queue_prompt(self, prompt_workflow):
        p = {"prompt": prompt_workflow, "client_id": self.client_id}
        data = json.dumps(p).encode('utf-8')
        req = urllib.request.Request(f"http://{self.server_address}/prompt", data=data)
        return json.loads(urllib.request.urlopen(req).read())

    def _get_image(self, filename, subfolder, folder_type):
        data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        with urllib.request.urlopen(f"http://{self.server_address}/view?{urllib.parse.urlencode(data)}") as response:
            return response.read()

    def _get_history(self, prompt_id):
        with urllib.request.urlopen(f"http://{self.server_address}/history/{prompt_id}") as response:
            return json.loads(response.read())

    def run_workflow(self, input_image_path, positive_prompt, output_filename="flux_output.png"):
        """
        Starts the server, runs the workflow with a random seed, and stops the server.
        Returns the path to the generated output image.
        """
        try:
            self._start_server()

            uploaded_filename = self._upload_image(input_image_path)
            with open(self.workflow_api_json_path, 'r', encoding='utf-8') as f:
                prompt = json.load(f)

            print("Setting seed node to randomize for this run.")
            prompt[self.seed_node_id]["inputs"]["control_after_generate"] = "randomize"

            prompt[self.load_image_node_id]["inputs"]["image"] = uploaded_filename
            prompt[self.clip_text_node_id]["inputs"]["text"] = positive_prompt

            ws = websocket.WebSocket()
            ws.connect(f"ws://{self.server_address}/ws?clientId={self.client_id}")
            prompt_id = self._queue_prompt(prompt)['prompt_id']
            
            print("Workflow queued. Waiting for execution to finish...")
            try:
                while True:
                    out = ws.recv()
                    if isinstance(out, str):
                        message = json.loads(out)
                        if message['type'] == 'executing' and message['data']['node'] is None and message['data']['prompt_id'] == prompt_id:
                            break
            finally:
                ws.close()
            print("Execution finished.")

            history = self._get_history(prompt_id)[prompt_id]
            for node_id in history['outputs']:
                if 'images' in history['outputs'][node_id]:
                    image_data = history['outputs'][node_id]['images'][0]
                    image_bytes = self._get_image(image_data['filename'], image_data['subfolder'], image_data['type'])
                    with open(output_filename, 'wb') as f:
                        f.write(image_bytes)
                    print(f"Saved output image to '{output_filename}'")
                    return output_filename
        
        finally:
            self._stop_server()

        return None
