# main.py
import os
import sys
import webview
import requests
import json
import uuid
import time

def get_resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

# 全局配置与项目存储目录
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".agnes_canvas")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
PROJECTS_PATH = os.path.join(CONFIG_DIR, "projects.json")

DEFAULT_CONFIG = {
    "api_base": "https://apihub.agnes-ai.com/v1",
    "api_key": "",
    "model_image": "agnes-image-2.5-flash",
    "model_video": "agnes-video-2.5-flash"
}

def load_config():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def load_projects():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if os.path.exists(PROJECTS_PATH):
        try:
            with open(PROJECTS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_projects(projects):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(PROJECTS_PATH, "w", encoding="utf-8") as f:
        json.dump(projects, f, ensure_ascii=False, indent=2)

config = load_config()

class Api:
    def get_config(self):
        return config

    def save_api_key(self, key):
        config["api_key"] = key
        save_config(config)
        return {"status": "success"}

    # ===== 项目管理 API =====
    def get_projects(self, module_type):
        """获取指定模块的项目列表（如 canvas, chat, image, video）"""
        projects = load_projects()
        # 过滤出该模块的项目，并按时间倒序
        filtered = [p for p in projects if p.get("type") == module_type]
        filtered.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
        return filtered

    def create_project(self, module_type, name):
        """新建项目，返回项目ID"""
        projects = load_projects()
        project_id = str(uuid.uuid4())
        now = time.time()
        new_project = {
            "id": project_id,
            "type": module_type,
            "name": name,
            "data": {},  # 存放节点、消息等状态
            "created_at": now,
            "updated_at": now
        }
        projects.append(new_project)
        save_projects(projects)
        return {"status": "success", "project": new_project}

    def save_project_data(self, project_id, data):
        """保存项目状态（节点位置、图片、对话记录）"""
        projects = load_projects()
        for p in projects:
            if p["id"] == project_id:
                p["data"] = data
                p["updated_at"] = time.time()
                break
        save_projects(projects)
        return {"status": "success"}

    def get_project_data(self, project_id):
        """读取项目状态"""
        projects = load_projects()
        for p in projects:
            if p["id"] == project_id:
                return {"status": "success", "project": p}
        return {"status": "error", "message": "项目不存在"}

    def delete_project(self, project_id):
        """删除项目"""
        projects = load_projects()
        projects = [p for p in projects if p["id"] != project_id]
        save_projects(projects)
        return {"status": "success"}

    # ===== 图片生成 API =====
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

if __name__ == '__main__':
    api = Api()
    html_path = get_resource_path('index.html')
    window = webview.create_window('Agnes AI 创作平台', html_path, js_api=api, width=1400, height=900)
    webview.start()
