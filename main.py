# main.py
import os, sys, json, uuid, time
import webview
import requests

def get_resource_path(p):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, p)
    return os.path.join(os.path.abspath("."), p)

CFG_DIR = os.path.join(os.path.expanduser("~"), ".agnes_canvas")
CFG_PATH = os.path.join(CFG_DIR, "config.json")
PROJ_PATH = os.path.join(CFG_DIR, "projects.json")

DEFAULT_CFG = {
    "api_base": "https://apihub.agnes-ai.com/v1",
    "api_key": "",
    "model_text": "agnes-3.0-flash",
    "model_image": "agnes-image-2.5-flash",
    "model_video": "agnes-video-2.5-flash"
}

def _load(path, default):
    os.makedirs(CFG_DIR, exist_ok=True)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default

def _save(path, data):
    os.makedirs(CFG_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

config = _load(CFG_PATH, DEFAULT_CFG.copy())
for k, v in DEFAULT_CFG.items():
    config.setdefault(k, v)

def projects():
    return _load(PROJ_PATH, [])

def save_projects(p):
    _save(PROJ_PATH, p)

def _headers():
    return {"Authorization": f"Bearer {config['api_key']}", "Content-Type": "application/json"}

class Api:
    def get_config(self):
        return config

    def save_config(self, cfg):
        for k in ("api_base", "api_key", "model_text", "model_image", "model_video"):
            if k in cfg:
                config[k] = str(cfg[k]).strip()
        _save(CFG_PATH, config)
        return {"status": "success"}

    # ---------- 项目 ----------
    def get_projects(self, module):
        ps = [p for p in projects() if p.get("type") == module]
        ps.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
        return ps

    def create_project(self, module, name):
        ps = projects()
        now = time.time()
        np = {"id": str(uuid.uuid4()), "type": module, "name": name,
              "data": {}, "created_at": now, "updated_at": now}
        ps.append(np)
        save_projects(ps)
        return {"status": "success", "project": np}

    def save_project_data(self, pid, data, name=None):
        ps = projects()
        for p in ps:
            if p["id"] == pid:
                p["data"] = data
                p["updated_at"] = time.time()
                if name:
                    p["name"] = name
                break
        save_projects(ps)
        return {"status": "success"}

    def get_project_data(self, pid):
        for p in projects():
            if p["id"] == pid:
                return {"status": "success", "project": p}
        return {"status": "error", "message": "not found"}

    def delete_project(self, pid):
        save_projects([p for p in projects() if p["id"] != pid])
        return {"status": "success"}

    # ---------- 文本 ----------
    def text_chat(self, messages, temperature=0.7, max_tokens=4096):
        if not config.get("api_key"):
            return {"status": "error", "message": "请先设置 API Key"}
        url = config["api_base"].rstrip("/") + "/chat/completions"
        payload = {
            "model": config["model_text"],
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False
        }
        try:
            r = requests.post(url, headers=_headers(), json=payload, timeout=180)
            r.raise_for_status()
            res = r.json()
            content = res["choices"][0]["message"]["content"]
            return {"status": "success", "content": content}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ---------- 图片 ----------
    def generate_image(self, prompt, size="2K", ratio="1:1", images=None):
        if not config.get("api_key"):
            return {"status": "error", "message": "请先设置 API Key"}
        url = config["api_base"].rstrip("/") + "/images/generations"
        payload = {
            "model": config["model_image"],
            "prompt": prompt,
            "size": size,
            "ratio": ratio
        }
        if images:
            payload["image"] = images
        try:
            r = requests.post(url, headers=_headers(), json=payload, timeout=600)
            r.raise_for_status()
            res = r.json()
            data = res.get("data") or []
            if not data:
                return {"status": "error", "message": "接口未返回图片"}
            item = data[0]
            out = item.get("url")
            b64 = item.get("b64_json")
            if not out and b64:
                out = "data:image/png;base64," + b64
            return {"status": "success", "url": out}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ---------- 视频 ----------
    def create_video_task(self, prompt, mode="text", size="720P",
                          aspect_ratio="16:9", seconds="5", images=None):
        if not config.get("api_key"):
            return {"status": "error", "message": "请先设置 API Key"}
        url = config["api_base"].rstrip("/") + "/videos"
        payload = {
            "model": config["model_video"],
            "prompt": prompt,
            "mode": mode,
            "size": size,
            "aspect_ratio": aspect_ratio,
            "seconds": seconds
        }
        if images:
            payload["images"] = images
        try:
            r = requests.post(url, headers=_headers(), json=payload, timeout=120)
            r.raise_for_status()
            return {"status": "success", "raw": r.json()}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def wait_video(self, video_id):
        url = config["api_base"].rstrip("/") + "/agnesapi"
        params = {"video_id": video_id, "model_name": config["model_video"]}
        start = time.time()
        while time.time() - start < 600:
            try:
                r = requests.get(url, headers=_headers(), params=params, timeout=60)
                r.raise_for_status()
                res = r.json()
                st = res.get("status") or res.get("state") or "unknown"
                if st in ("completed", "succeeded", "success"):
                    out = res.get("url") or res.get("video_url")
                    if not out and isinstance(res.get("output"), dict):
                        out = res["output"].get("url")
                    return {"status": "success", "url": out, "raw": res}
                if st in ("failed", "error", "canceled", "cancelled"):
                    return {"status": "error", "message": json.dumps(res, ensure_ascii=False)}
            except Exception as e:
                return {"status": "error", "message": str(e)}
            time.sleep(2)
        return {"status": "error", "message": "视频生成超时"}

if __name__ == '__main__':
    api = Api()
    webview.create_window('Agnes AI 创作平台', get_resource_path('index.html'),
                          js_api=api, width=1400, height=900)
    webview.start()
