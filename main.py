# main.py
import os
import sys
import webview
import requests
import json

# 解决 PyInstaller 打包后找不到 html 文件的问题
def get_resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".agnes_canvas")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
DEFAULT_CONFIG = {
    "api_base": "https://apihub.agnes-ai.com/v1",
    "api_key": "",
    "model_image": "agnes-image-2.5-flash",
    "model_video": "agnes-video-2.5-flash"
}

def load_config():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

config = load_config()

class Api:
    def generate_image(self, prompt):
        if not config.get("api_key"):
            return {"status": "error", "message": "请先设置 API Key"}
        
        url = config["api_base"].rstrip("/") + "/images/generations"
        headers = {
            "Authorization": f"Bearer {config['api_key']}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": config.get("model_image", "agnes-image-2.5-flash"),
            "prompt": prompt,
            "size": "2K",
            "ratio": "1:1"
        }
        
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=300)
            r.raise_for_status()
            res = r.json()
            data = res.get("data", [])
            if data:
                img_url = data[0].get("url") or data[0].get("b64_json", "")
                return {"status": "success", "url": img_url}
            return {"status": "error", "message": "接口未返回图片数据"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def save_api_key(self, key):
        config["api_key"] = key
        save_config(config)
        return {"status": "success"}

if __name__ == '__main__':
    api = Api()
    html_path = get_resource_path('index.html')
    window = webview.create_window('Agnes AI 画布', html_path, js_api=api, width=1200, height=800)
    webview.start()
