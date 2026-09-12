# -*- coding: utf-8 -*-
import os
import json
import time
import threading
import webbrowser
import base64
import re
import tkinter as tk
from tkinter import filedialog, messagebox
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
import requests

APP_NAME = "AgnesClient"
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".agnes_client")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    "api_base": "https://apihub.agnes-ai.com/v1",
    "api_key": "",
    "models": {
        "text": "agnes-3.0-flash",
        "image": "agnes-image-2.5-flash",
        "video": "agnes-video-2.5-flash"
    },
    "video_poll_interval": 2,
    "video_poll_timeout": 600,
    "remote_config_url": ""
}

def load_config():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
            cfg.setdefault("models", {})
            for k, v in DEFAULT_CONFIG["models"].items():
                cfg["models"].setdefault(k, v)
            return cfg
        except Exception:
            pass
    return json.loads(json.dumps(DEFAULT_CONFIG))

def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def file_to_base64(file_path):
    """将本地图片转换为 Base64 字符串"""
    try:
        with open(file_path, "rb") as f:
            data = f.read()
            ext = os.path.splitext(file_path)[1].lower()
            mime = "image/jpeg"
            if ext == ".png": mime = "image/png"
            elif ext == ".gif": mime = "image/gif"
            elif ext == ".webp": mime = "image/webp"
            return f"data:{mime};base64,{base64.b64encode(data).decode('utf-8')}"
    except Exception as e:
        return None

class AgnesClient:
    def __init__(self, config):
        self.config = config

    @property
    def base(self):
        return self.config["api_base"].rstrip("/")

    @property
    def headers(self):
        return {
            "Authorization": f"Bearer {self.config['api_key']}",
            "Content-Type": "application/json"
        }

    def _url(self, path):
        return self.base + path

    def refresh_remote_config(self):
        url = self.config.get("remote_config_url", "").strip()
        if not url:
            return False
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        remote = r.json()
        if "models" in remote:
            self.config["models"].update(remote["models"])
        for key in ("api_base", "video_poll_interval", "video_poll_timeout"):
            if key in remote:
                self.config[key] = remote[key]
        save_config(self.config)
        return True

    def text_chat(self, messages, temperature=0.7, max_tokens=4096):
        url = self._url("/chat/completions")
        payload = {
            "model": self.config["models"]["text"],
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False
        }
        r = requests.post(url, headers=self.headers, json=payload, timeout=180)
        r.raise_for_status()
        return r.json()

    def generate_image(self, prompt, size="2K", ratio="1:1", image_data_list=None, return_base64=False):
        url = self._url("/images/generations")
        payload = {
            "model": self.config["models"]["image"],
            "prompt": prompt,
            "size": size,
            "ratio": ratio,
            "return_base64": return_base64
        }
        if image_data_list:
            payload["image"] = image_data_list  # 根据 Agnes 接口文档，接受图片数组
        r = requests.post(url, headers=self.headers, json=payload, timeout=600)
        r.raise_for_status()
        return r.json()

    def create_video_task(self, prompt, mode="text", size="720P", aspect_ratio="16:9", seconds="5", image_data_list=None, **extra):
        url = self._url("/videos")
        payload = {
            "model": self.config["models"]["video"],
            "prompt": prompt,
            "mode": mode,
            "size": size,
            "aspect_ratio": aspect_ratio,
            "seconds": seconds
        }
        if image_data_list:
            payload["images"] = image_data_list  # 视频多图参考
        payload.update(extra)
        r = requests.post(url, headers=self.headers, json=payload, timeout=120)
        r.raise_for_status()
        return r.json()

    def query_video_task(self, video_id):
        url = self._url("/agnesapi")
        params = {
            "video_id": video_id,
            "model_name": self.config["models"]["video"]
        }
        r = requests.get(url, headers=self.headers, params=params, timeout=60)
        r.raise_for_status()
        return r.json()

    def wait_for_video(self, video_id, on_progress=None, cancel_event=None):
        start = time.time()
        timeout = float(self.config.get("video_poll_timeout", 600))
        interval = float(self.config.get("video_poll_interval", 2))
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("已取消")
            if time.time() - start > timeout:
                raise TimeoutError("视频生成超时")
            result = self.query_video_task(video_id)
            status = result.get("status") or result.get("state") or "unknown"
            if on_progress:
                on_progress(status, result)
            if status in ("completed", "succeeded", "success"):
                return result
            if status in ("failed", "error", "canceled", "cancelled"):
                raise RuntimeError("视频生成失败：" + json.dumps(result, ensure_ascii=False))
            time.sleep(interval)

class AgnesApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Agnes AI 全能客户端")
        self.root.geometry("1100x850")
        self.config = load_config()
        self.client = AgnesClient(self.config)
        self.video_cancel = None
        
        # 素材仓库
        self.img_assets = []  # 存 (名称, base64/url) 的元组
        self.vid_assets = []
        
        self._build_ui()
        self._load_config_to_ui()
        self.root.after(600, self._try_refresh_remote)

    def _build_ui(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=BOTH, expand=True, padx=10, pady=10)
        self._build_settings_tab()
        self._build_text_tab()
        self._build_image_tab()
        self._build_video_tab()
        self.status = tk.StringVar(value="就绪")
        ttk.Label(self.root, textvariable=self.status, anchor="w", bootstyle="secondary").pack(fill=X, side=BOTTOM, padx=10, pady=5)

    def _build_settings_tab(self):
        f = ttk.Frame(self.notebook)
        self.notebook.add(f, text="设置")
        row = 0
        ttk.Label(f, text="API Base：").grid(row=row, column=0, sticky="e", padx=6, pady=6)
        self.var_api_base = tk.StringVar()
        ttk.Entry(f, textvariable=self.var_api_base, width=80).grid(row=row, column=1, sticky="we", padx=6, pady=6)
        row += 1
        ttk.Label(f, text="API Key：").grid(row=row, column=0, sticky="e", padx=6, pady=6)
        self.var_api_key = tk.StringVar()
        ttk.Entry(f, textvariable=self.var_api_key, width=80, show="*").grid(row=row, column=1, sticky="we", padx=6, pady=6)
        row += 1
        ttk.Label(f, text="文本模型：").grid(row=row, column=0, sticky="e", padx=6, pady=6)
        self.var_model_text = tk.StringVar()
        ttk.Entry(f, textvariable=self.var_model_text, width=50).grid(row=row, column=1, sticky="w", padx=6, pady=6)
        row += 1
        ttk.Label(f, text="图片模型：").grid(row=row, column=0, sticky="e", padx=6, pady=6)
        self.var_model_image = tk.StringVar()
        ttk.Entry(f, textvariable=self.var_model_image, width=50).grid(row=row, column=1, sticky="w", padx=6, pady=6)
        row += 1
        ttk.Label(f, text="视频模型：").grid(row=row, column=0, sticky="e", padx=6, pady=6)
        self.var_model_video = tk.StringVar()
        ttk.Entry(f, textvariable=self.var_model_video, width=50).grid(row=row, column=1, sticky="w", padx=6, pady=6)
        row += 1
        ttk.Label(f, text="远端配置 URL（可选）：").grid(row=row, column=0, sticky="e", padx=6, pady=6)
        self.var_remote = tk.StringVar()
        ttk.Entry(f, textvariable=self.var_remote, width=80).grid(row=row, column=1, sticky="we", padx=6, pady=6)
        row += 1
        btns = ttk.Frame(f)
        btns.grid(row=row, column=1, sticky="w", padx=6, pady=12)
        ttk.Button(btns, text="保存设置", command=self.save_settings, bootstyle="success").pack(side="left", padx=4)
        ttk.Button(btns, text="测试文本接口", command=self.test_text, bootstyle="info").pack(side="left", padx=4)
        ttk.Button(btns, text="从远端刷新模型", command=self.refresh_remote, bootstyle="warning").pack(side="left", padx=4)
        f.columnconfigure(1, weight=1)

    def _load_config_to_ui(self):
        self.var_api_base.set(self.config.get("api_base", ""))
        self.var_api_key.set(self.config.get("api_key", ""))
        self.var_model_text.set(self.config["models"]["text"])
        self.var_model_image.set(self.config["models"]["image"])
        self.var_model_video.set(self.config["models"]["video"])
        self.var_remote.set(self.config.get("remote_config_url", ""))

    def _apply_ui_to_config(self):
        self.config["api_base"] = self.var_api_base.get().strip()
        self.config["api_key"] = self.var_api_key.get().strip()
        self.config["models"]["text"] = self.var_model_text.get().strip()
        self.config["models"]["image"] = self.var_model_image.get().strip()
        self.config["models"]["video"] = self.var_model_video.get().strip()
        self.config["remote_config_url"] = self.var_remote.get().strip()
        self.client.config = self.config

    def save_settings(self):
        self._apply_ui_to_config()
        save_config(self.config)
        self.status.set("设置已保存")
        messagebox.showinfo("提示", "设置已保存")

    def test_text(self):
        self._apply_ui_to_config()
        def run():
            try:
                res = self.client.text_chat([{"role": "user", "content": "你好，请回复：连接成功"}], max_tokens=50)
                content = res.get("choices", [{}])[0].get("message", {}).get("content", "")
                self.root.after(0, lambda c=content: messagebox.showinfo("测试成功", c or "接口有响应"))
            except Exception as e:
                err = str(e)
                self.root.after(0, lambda err=err: messagebox.showerror("测试失败", err))
        threading.Thread(target=run, daemon=True).start()

    def refresh_remote(self):
        self._apply_ui_to_config()
        def run():
            try:
                ok = self.client.refresh_remote_config()
                self.root.after(0, self._load_config_to_ui)
                self.root.after(0, lambda ok=ok: messagebox.showinfo("提示", "远端配置已刷新" if ok else "未填写远端配置 URL"))
            except Exception as e:
                err = str(e)
                self.root.after(0, lambda err=err: messagebox.showerror("刷新失败", err))
        threading.Thread(target=run, daemon=True).start()

    def _try_refresh_remote(self):
        if self.config.get("remote_config_url", "").strip():
            self.refresh_remote()

    # ================= 文本对话 =================
    def _build_text_tab(self):
        f = ttk.Frame(self.notebook)
        self.notebook.add(f, text="文本对话")
        top = ttk.Frame(f)
        top.pack(fill=X, padx=6, pady=6)
        ttk.Label(top, text="温度").pack(side="left")
        self.var_temp = tk.StringVar(value="0.7")
        ttk.Entry(top, textvariable=self.var_temp, width=6).pack(side="left", padx=4)
        ttk.Label(top, text="最大输出").pack(side="left", padx=(12, 0))
        self.var_max_tokens = tk.StringVar(value="4096")
        ttk.Entry(top, textvariable=self.var_max_tokens, width=8).pack(side="left", padx=4)

        ttk.Label(f, text="输入：").pack(anchor="w", padx=6)
        self.text_input = ttk.Text(f, height=6)
        self.text_input.pack(fill=X, padx=6)
        btns = ttk.Frame(f)
        btns.pack(fill=X, padx=6, pady=4)
        ttk.Button(btns, text="发送", command=self.send_text, bootstyle="primary").pack(side="left")
        ttk.Button(btns, text="清空对话", command=self.clear_text, bootstyle="secondary").pack(side="left", padx=4)
        ttk.Label(f, text="回复：").pack(anchor="w", padx=6)
        self.text_output = ttk.Text(f, state="disabled")
        self.text_output.pack(fill=BOTH, expand=True, padx=6, pady=6)

    def clear_text(self):
        self.text_input.delete("1.0", "end")
        self.text_output.config(state="normal")
        self.text_output.delete("1.0", "end")
        self.text_output.config(state="disabled")

    def send_text(self):
        self._apply_ui_to_config()
        text = self.text_input.get("1.0", "end").strip()
        if not text:
            return
        try:
            temp = float(self.var_temp.get())
            max_tokens = int(self.var_max_tokens.get())
        except ValueError:
            messagebox.showerror("参数错误", "温度和最大输出必须是数字")
            return
        self._append_text("你：" + text)
        self.text_input.delete("1.0", "end")
        self.status.set("正在请求文本模型...")
        def run():
            try:
                res = self.client.text_chat([{"role": "user", "content": text}], temperature=temp, max_tokens=max_tokens)
                content = res.get("choices", [{}])[0].get("message", {}).get("content", "")
                self.root.after(0, lambda c=content: self._append_text("Agnes：" + c))
                self.root.after(0, lambda: self.status.set("完成"))
            except Exception as e:
                err = str(e)
                self.root.after(0, lambda err=err: self._append_text("错误：" + err))
                self.root.after(0, lambda: self.status.set("失败"))
        threading.Thread(target=run, daemon=True).start()

    def _append_text(self, s):
        self.text_output.config(state="normal")
        self.text_output.insert("end", s + "\n\n")
        self.text_output.config(state="disabled")
        self.text_output.see("end")

    # ================= 图片生成 =================
    def _build_image_tab(self):
        f = ttk.Frame(self.notebook)
        self.notebook.add(f, text="图片生成")
        
        ttk.Label(f, text="提示词（输入 @ 可引用上方素材）：").pack(anchor="w", padx=6, pady=(6, 0))
        self.img_prompt = ttk.Text(f, height=5)
        self.img_prompt.pack(fill=X, padx=6)
        self.img_prompt.bind("<KeyRelease>", lambda e: self._check_at_symbol(e, self.img_prompt, self.img_assets, "图片"))
        
        # 素材上传区
        asset_frame = ttk.LabelFrame(f, text="已上传素材 (点击上传，在输入框打 @ 引用)")
        asset_frame.pack(fill=X, padx=6, pady=6)
        self.img_asset_listbox = tk.Listbox(asset_frame, height=3)
        self.img_asset_listbox.pack(side="left", fill=X, expand=True, padx=6, pady=6)
        ttk.Button(asset_frame, text="上传素材", command=self.upload_img_asset, bootstyle="info").pack(side="right", padx=6)

        opts = ttk.Frame(f)
        opts.pack(fill=X, padx=6, pady=6)
        ttk.Label(opts, text="尺寸").pack(side="left")
        self.var_img_size = tk.StringVar(value="2K")
        ttk.Combobox(opts, textvariable=self.var_img_size, values=["1K", "2K", "3K", "4K"], width=6, state="readonly").pack(side="left", padx=4)
        ttk.Label(opts, text="比例").pack(side="left", padx=(12, 0))
        self.var_img_ratio = tk.StringVar(value="1:1")
        ttk.Combobox(opts, textvariable=self.var_img_ratio, values=["1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3"], width=8, state="readonly").pack(side="left", padx=4)
        
        btns = ttk.Frame(f)
        btns.pack(fill=X, padx=6)
        ttk.Button(btns, text="生成图片", command=self.gen_image, bootstyle="primary").pack(side="left")
        ttk.Button(btns, text="打开结果链接", command=self.open_image_link, bootstyle="secondary").pack(side="left", padx=4)
        ttk.Label(f, text="结果：").pack(anchor="w", padx=6, pady=(8, 0))
        self.img_result_url = tk.StringVar()
        ttk.Entry(f, textvariable=self.img_result_url).pack(fill=X, padx=6)
        self.img_result_text = ttk.Text(f, height=8)
        self.img_result_text.pack(fill=BOTH, expand=True, padx=6, pady=6)

    def upload_img_asset(self):
        file_path = filedialog.askopenfilename(filetypes=[("Image files", "*.jpg *.jpeg *.png *.webp")])
        if not file_path: return
        b64 = file_to_base64(file_path)
        if not b64:
            messagebox.showerror("错误", "读取图片失败")
            return
        name = os.path.basename(file_path)
        self.img_assets.append((name, b64))
        self.img_asset_listbox.insert(tk.END, name)

    def _check_at_symbol(self, event, text_widget, asset_list, asset_type):
        if event.char == '@':
            if not asset_list:
                return
            # 弹出选择器
            popup = ttk.Toplevel(self.root)
            popup.title(f"选择{asset_type}素材")
            popup.geometry("300x200")
            popup.transient(self.root)
            popup.grab_set()
            listbox = tk.Listbox(popup)
            listbox.pack(fill=BOTH, expand=True, padx=10, pady=10)
            for idx, (name, _) in enumerate(asset_list):
                listbox.insert(tk.END, f"{idx+1}. {name}")
            
            def on_select(evt=None):
                sel = listbox.curselection()
                if sel:
                    idx = sel[0]
                    text_widget.insert(tk.INSERT, f"{asset_type}{idx+1} ")
                    popup.destroy()
            listbox.bind("<Double-Button-1>", on_select)
            ttk.Button(popup, text="确认选择", command=on_select, bootstyle="primary").pack(pady=5)

    def _resolve_prompt(self, prompt_text, asset_list, asset_type):
        """解析文本中的 @图片1 / @视频1，替换为对应数据"""
        pattern = rf"@{asset_type}(\d+)"
        def repl(match):
            idx = int(match.group(1)) - 1
            if 0 <= idx < len(asset_list):
                return asset_list[idx][1]  # 返回 base64 或 url
            return match.group(0)
        
        # 提取所有被引用的素材数据
        referenced_data = []
        for match in re.finditer(pattern, prompt_text):
            idx = int(match.group(1)) - 1
            if 0 <= idx < len(asset_list):
                referenced_data.append(asset_list[idx][1])
                
        cleaned_prompt = re.sub(pattern, "", prompt_text).strip()
        return cleaned_prompt, referenced_data

    def open_image_link(self):
        url = self.img_result_url.get()
        if url:
            webbrowser.open(url)

    def gen_image(self):
        self._apply_ui_to_config()
        raw_prompt = self.img_prompt.get("1.0", "end").strip()
        if not raw_prompt:
            messagebox.showwarning("提示", "请输入提示词")
            return
        
        prompt, refs = self._resolve_prompt(raw_prompt, self.img_assets, "图片")
        self.status.set("正在生成图片...")
        def run():
            try:
                res = self.client.generate_image(prompt, size=self.var_img_size.get(), ratio=self.var_img_ratio.get(), image_data_list=refs or None)
                text = json.dumps(res, ensure_ascii=False, indent=2)
                url = ""
                data = res.get("data") or []
                if data:
                    url = data[0].get("url") or data[0].get("b64_json") or ""
                self.root.after(0, lambda t=text: self._set_image_text(t))
                if url:
                    self.root.after(0, lambda u=url: self.img_result_url.set(u))
                self.root.after(0, lambda: self.status.set("完成"))
            except Exception as e:
                err = str(e)
                self.root.after(0, lambda err=err: self._set_image_text("错误：" + err))
                self.root.after(0, lambda: self.status.set("失败"))
        threading.Thread(target=run, daemon=True).start()

    def _set_image_text(self, text):
        self.img_result_text.delete("1.0", "end")
        self.img_result_text.insert("end", text)

    # ================= 视频生成 =================
    def _build_video_tab(self):
        f = ttk.Frame(self.notebook)
        self.notebook.add(f, text="视频生成")
        ttk.Label(f, text="视频描述（输入 @ 引用素材）：").pack(anchor="w", padx=6, pady=(6, 0))
        self.vid_prompt = ttk.Text(f, height=5)
        self.vid_prompt.pack(fill=X, padx=6)
        self.vid_prompt.bind("<KeyRelease>", lambda e: self._check_at_symbol(e, self.vid_prompt, self.vid_assets, "视频"))

        # 素材上传区
        asset_frame = ttk.LabelFrame(f, text="视频参考素材 (图生视频支持上传图片，打 @ 引用)")
        asset_frame.pack(fill=X, padx=6, pady=6)
        self.vid_asset_listbox = tk.Listbox(asset_frame, height=3)
        self.vid_asset_listbox.pack(side="left", fill=X, expand=True, padx=6, pady=6)
        ttk.Button(asset_frame, text="上传图片素材", command=self.upload_vid_asset, bootstyle="info").pack(side="right", padx=6)

        opts = ttk.Frame(f)
        opts.pack(fill=X, padx=6, pady=6)
        ttk.Label(opts, text="模式").pack(side="left")
        self.var_vid_mode = tk.StringVar(value="text")
        ttk.Combobox(opts, textvariable=self.var_vid_mode, values=["text", "image"], width=8, state="readonly").pack(side="left", padx=4)
        ttk.Label(opts, text="尺寸").pack(side="left", padx=(12, 0))
        self.var_vid_size = tk.StringVar(value="720P")
        ttk.Combobox(opts, textvariable=self.var_vid_size, values=["720P"], width=8, state="readonly").pack(side="left", padx=4)
        ttk.Label(opts, text="比例").pack(side="left", padx=(12, 0))
        self.var_vid_ratio = tk.StringVar(value="16:9")
        ttk.Combobox(opts, textvariable=self.var_vid_ratio, values=["16:9", "9:16", "1:1"], width=8, state="readonly").pack(side="left", padx=4)
        ttk.Label(opts, text="时长秒").pack(side="left", padx=(12, 0))
        self.var_vid_seconds = tk.StringVar(value="5")
        ttk.Combobox(opts, textvariable=self.var_vid_seconds, values=["5", "10"], width=5, state="readonly").pack(side="left", padx=4)
        
        btns = ttk.Frame(f)
        btns.pack(fill=X, padx=6)
        ttk.Button(btns, text="创建视频任务", command=self.gen_video, bootstyle="primary").pack(side="left")
        ttk.Button(btns, text="取消轮询", command=self.cancel_video, bootstyle="danger").pack(side="left", padx=4)
        ttk.Button(btns, text="打开视频链接", command=self.open_video_link, bootstyle="secondary").pack(side="left", padx=4)
        self.vid_status = tk.StringVar(value="等待中...")
        ttk.Label(f, textvariable=self.vid_status, bootstyle="info").pack(anchor="w", padx=6, pady=6)
        ttk.Label(f, text="结果：").pack(anchor="w", padx=6)
        self.vid_result_url = tk.StringVar()
        ttk.Entry(f, textvariable=self.vid_result_url).pack(fill=X, padx=6)
        self.vid_result_text = ttk.Text(f, height=8)
        self.vid_result_text.pack(fill=BOTH, expand=True, padx=6, pady=6)

    def upload_vid_asset(self):
        file_path = filedialog.askopenfilename(filetypes=[("Image files", "*.jpg *.jpeg *.png *.webp")])
        if not file_path: return
        b64 = file_to_base64(file_path)
        if not b64:
            messagebox.showerror("错误", "读取图片失败")
            return
        name = os.path.basename(file_path)
        self.vid_assets.append((name, b64))
        self.vid_asset_listbox.insert(tk.END, name)

    def open_video_link(self):
        url = self.vid_result_url.get()
        if url:
            webbrowser.open(url)

    def gen_video(self):
        self._apply_ui_to_config()
        raw_prompt = self.vid_prompt.get("1.0", "end").strip()
        if not raw_prompt:
            messagebox.showwarning("提示", "请输入视频描述")
            return
        
        prompt, refs = self._resolve_prompt(raw_prompt, self.vid_assets, "视频")
        self.video_cancel = threading.Event()
        self.status.set("正在创建视频任务...")
        def run():
            try:
                task = self.client.create_video_task(
                    prompt,
                    mode=self.var_vid_mode.get(),
                    size=self.var_vid_size.get(),
                    aspect_ratio=self.var_vid_ratio.get(),
                    seconds=self.var_vid_seconds.get(),
                    image_data_list=refs or None
                )
                self.root.after(0, lambda t=task: self._reset_video_text("创建响应：\n" + json.dumps(t, ensure_ascii=False, indent=2) + "\n"))
                video_id = task.get("video_id") or task.get("id") or task.get("task_id")
                if not video_id:
                    raise RuntimeError("未找到 video_id：" + json.dumps(task, ensure_ascii=False))
                self.root.after(0, lambda vid=video_id: self.vid_status.set(f"任务 {vid} 已创建，轮询中..."))
                def on_progress(status, result):
                    self.root.after(0, lambda s=status: self.vid_status.set(f"状态：{s}"))
                    self.root.after(0, lambda s=status: self._append_video_text(f"状态：{s}\n"))
                result = self.client.wait_for_video(video_id, on_progress=on_progress, cancel_event=self.video_cancel)
                text = json.dumps(result, ensure_ascii=False, indent=2)
                self.root.after(0, lambda t=text: self._append_video_text("完成：\n" + t + "\n"))
                url = result.get("url") or result.get("video_url")
                if not url and isinstance(result.get("output"), dict):
                    url = result["output"].get("url")
                if url:
                    self.root.after(0, lambda u=url: self.vid_result_url.set(u))
                self.root.after(0, lambda: self.vid_status.set("完成"))
                self.root.after(0, lambda: self.status.set("完成"))
            except Exception as e:
                err = str(e)
                self.root.after(0, lambda: self.vid_status.set("失败"))
                self.root.after(0, lambda err=err: self._append_video_text("错误：" + err + "\n"))
                self.root.after(0, lambda: self.status.set("失败"))
        threading.Thread(target=run, daemon=True).start()

    def cancel_video(self):
        if self.video_cancel:
            self.video_cancel.set()
            self.vid_status.set("已请求取消")

    def _reset_video_text(self, text):
        self.vid_result_text.delete("1.0", "end")
        self.vid_result_text.insert("end", text)

    def _append_video_text(self, text):
        self.vid_result_text.insert("end", text)
        self.vid_result_text.see("end")

if __name__ == "__main__":
    root = ttk.Window(themename="darkly")  # 使用 ttkbootstrap 的暗黑主题美化界面
    app = AgnesApp(root)
    root.mainloop()
