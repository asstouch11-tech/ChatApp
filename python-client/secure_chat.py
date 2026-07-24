import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import asyncio
import websockets
import json
import threading
import queue
import time
import hashlib
import hmac
import base64
import secrets
import os
import sys
import ctypes
import subprocess
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import win32gui
import win32con
import win32api
import win32process
from pathlib import Path

CONFIG_FILE = Path.home() / ".secure_chat_config.json"
DEFAULT_SERVER = "wss://your-render-app.onrender.com"
RECONNECT_DELAY = 5
MAX_RECONNECT_ATTEMPTS = 10
NOTIFICATION_DURATION = 3000
MESSAGE_TTL_HOURS = 1

class StealthNotification:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        self.root.attributes('-alpha', 0.0)
        self.root.attributes('-toolwindow', True)
        
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        self.notification_width = 360
        self.notification_height = 85
        x = screen_width - self.notification_width - 20
        y = screen_height - self.notification_height - 80
        
        self.root.geometry(f"{self.notification_width}x{self.notification_height}+{x}+{y}")
        
        self.frame = tk.Frame(self.root, bg='#1a1a2e', bd=0, highlightthickness=0)
        self.frame.pack(fill=tk.BOTH, expand=True)
        
        self.icon_label = tk.Label(self.frame, text="🔒", bg='#1a1a2e', fg='#60a5fa', font=('Segoe UI', 24))
        self.icon_label.pack(side=tk.LEFT, padx=(15, 10), pady=10)
        
        self.text_frame = tk.Frame(self.frame, bg='#1a1a2e')
        self.text_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=10)
        
        self.title_label = tk.Label(self.text_frame, text="Secure Chat", bg='#1a1a2e', fg='#ffffff', font=('Segoe UI', 9, 'bold'), anchor='w')
        self.title_label.pack(fill=tk.X)
        
        self.message_label = tk.Label(self.text_frame, text="", bg='#1a1a2e', fg='#b0b0b0', font=('Segoe UI', 8), anchor='w', wraplength=290, justify='left')
        self.message_label.pack(fill=tk.X)
        
        self.progress = tk.Frame(self.frame, bg='#2563eb', width=0, height=3)
        self.progress.place(x=0, y=self.notification_height-3, width=0, height=3)
        
        self.hwnd = self.root.winfo_id()
        self._make_click_through()
        
        self.message_queue = queue.Queue()
        self.current_notification = None
        self.root.after(100, self._process_queue)
        
    def _make_click_through(self):
        try:
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x80000
            WS_EX_TRANSPARENT = 0x20
            WS_EX_TOOLWINDOW = 0x80
            WS_EX_NOACTIVATE = 0x08000000
            
            style = ctypes.windll.user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
            style |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
            ctypes.windll.user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE, style)
            
            ctypes.windll.user32.SetLayeredWindowAttributes(self.hwnd, 0, 230, 0x2)
        except Exception as e:
            pass

    def _process_queue(self):
        try:
            while True:
                msg = self.message_queue.get_nowait()
                self._show_notification(msg['title'], msg['message'], msg.get('encrypted', False))
        except queue.Empty:
            pass
        self.root.after(100, self._process_queue)

    def _show_notification(self, title, message, encrypted=False):
        if self.current_notification:
            self._hide_notification()
        
        self.title_label.config(text=title)
        if encrypted:
            self.message_label.config(text=f"🔒 {message}")
            self.icon_label.config(text="🔐", fg='#f87171')
        else:
            self.message_label.config(text=message)
            self.icon_label.config(text="🔒", fg='#60a5fa')
        
        self.current_notification = {'title': title, 'message': message}
        self._animate_in()

    def _animate_in(self):
        self.root.deiconify()
        self.root.attributes('-alpha', 0.0)
        self._fade_in(0)

    def _fade_in(self, alpha):
        if alpha < 0.9:
            alpha += 0.15
            self.root.attributes('-alpha', alpha)
            self.root.after(16, lambda: self._fade_in(alpha))
        else:
            self.root.attributes('-alpha', 0.9)
            self._start_progress_bar()

    def _start_progress_bar(self):
        self.progress_width = 0
        self._animate_progress()

    def _animate_progress(self):
        if self.progress_width < self.notification_width:
            self.progress_width += self.notification_width / (NOTIFICATION_DURATION / 16)
            self.progress.place(width=self.progress_width)
            self.root.after(16, self._animate_progress)
        else:
            self._animate_out()

    def _animate_out(self):
        self._fade_out(0.9)

    def _fade_out(self, alpha):
        if alpha > 0:
            alpha -= 0.1
            self.root.attributes('-alpha', alpha)
            self.root.after(16, lambda: self._fade_out(alpha))
        else:
            self._hide_notification()

    def _hide_notification(self):
        self.root.withdraw()
        self.root.attributes('-alpha', 0.0)
        self.progress.place(width=0)
        self.current_notification = None

    def show(self, title, message, encrypted=False):
        self.message_queue.put({'title': title, 'message': message, 'encrypted': encrypted})

    def run(self):
        self.root.mainloop()


class SecureChatClient:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.ws = None
        self.ws_thread = None
        self.running = False
        self.message_queue = queue.Queue()
        self.current_room = None
        self.current_username = None
        self.encryption_password = None
        self.encryption_enabled = False
        self.fernet = None
        self.notification = None
        self.notification_thread = None
        self.reconnect_attempts = 0
        self.server_url = DEFAULT_SERVER
        self.master_password = None
        self.config = self.load_config()
        
        if self.config.get('server_url'):
            self.server_url = self.config['server_url']

    def load_config(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {}

    def save_config(self):
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self.config, f)
        except:
            pass

    def derive_key(self, password):
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'secure-chat-salt',
            iterations=100000,
        )
        return base64.urlsafe_b64encode(kdf.derive(password.encode()))

    def encrypt_message(self, message):
        if not self.fernet:
            self.fernet = Fernet(self.derive_key(self.encryption_password))
        return self.fernet.encrypt(message.encode()).decode()

    def decrypt_message(self, encrypted):
        if not self.fernet:
            self.fernet = Fernet(self.derive_key(self.encryption_password))
        try:
            return self.fernet.decrypt(encrypted.encode()).decode()
        except:
            return "[Decryption failed]"

    def start_notification_system(self):
        self.notification = StealthNotification()
        self.notification_thread = threading.Thread(target=self.notification.run, daemon=True)
        self.notification_thread.start()

    def show_notification(self, title, message, encrypted=False):
        if self.notification:
            self.notification.show(title, message, encrypted)

    def authenticate(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("🔒 Secure Chat - Authentication")
        dialog.geometry("420x340")
        dialog.resizable(False, False)
        dialog.configure(bg='#0a0a0f')
        dialog.transient(self.root)
        dialog.grab_set()
        
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - 210
        y = (dialog.winfo_screenheight() // 2) - 170
        dialog.geometry(f"+{x}+{y}")

        tk.Label(dialog, text="🔒 Secure Chat", bg='#0a0a0f', fg='#ffffff', font=('Segoe UI', 18, 'bold')).pack(pady=(30, 10))
        tk.Label(dialog, text="Enter your master password", bg='#0a0a0f', fg='#888', font=('Segoe UI', 10)).pack(pady=(0, 20))

        password_var = tk.StringVar()
        password_entry = tk.Entry(dialog, textvariable=password_var, show='●', font=('Segoe UI', 12), bg='#1e1e2a', fg='#fff', bd=0, highlightthickness=1, highlightbackground='#2a2a3a', highlightcolor='#2563eb', insertbackground='white', width=30)
        password_entry.pack(pady=10, ipady=8, padx=40)
        password_entry.focus()

        server_frame = tk.Frame(dialog, bg='#0a0a0f')
        server_frame.pack(pady=10, padx=40, fill=tk.X)
        tk.Label(server_frame, text="Server URL:", bg='#0a0a0f', fg='#888', font=('Segoe UI', 9)).pack(anchor='w')
        server_var = tk.StringVar(value=self.server_url)
        server_entry = tk.Entry(server_frame, textvariable=server_var, font=('Segoe UI', 10), bg='#1e1e2a', fg='#fff', bd=0, highlightthickness=1, highlightbackground='#2a2a3a', highlightcolor='#2563eb', insertbackground='white')
        server_entry.pack(fill=tk.X, pady=5, ipady=5)

        save_var = tk.BooleanVar(value=True)
        tk.Checkbutton(dialog, text="Remember server", variable=save_var, bg='#0a0a0f', fg='#888', selectcolor='#1e1e2a', activebackground='#0a0a0f', activeforeground='#fff').pack(pady=5)

        result = {'password': None, 'server': None, 'save': False}

        def on_ok():
            if password_var.get():
                result['password'] = password_var.get()
                result['server'] = server_var.get()
                result['save'] = save_var.get()
                dialog.destroy()
            else:
                messagebox.showerror("Error", "Password required", parent=dialog)

        def on_cancel():
            dialog.destroy()
            self.root.quit()

        btn_frame = tk.Frame(dialog, bg='#0a0a0f')
        btn_frame.pack(pady=20)
        tk.Button(btn_frame, text="Connect", command=on_ok, bg='#2563eb', fg='white', bd=0, font=('Segoe UI', 10, 'bold'), padx=30, pady=8, cursor='hand2').pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Cancel", command=on_cancel, bg='#374151', fg='white', bd=0, font=('Segoe UI', 10), padx=30, pady=8, cursor='hand2').pack(side=tk.LEFT, padx=10)

        dialog.bind('<Return>', lambda e: on_ok())
        dialog.bind('<Escape>', lambda e: on_cancel())
        dialog.wait_window()

        if result['password']:
            self.master_password = result['password']
            self.server_url = result['server']
            if result['save']:
                self.config['server_url'] = self.server_url
                self.save_config()
            return True
        return False

    def setup_main_window(self):
        self.root.deiconify()
        self.root.title("🔒 Secure Chat")
        self.root.geometry("950x650")
        self.root.minsize(750, 550)
        self.root.configure(bg='#0a0a0f')
        
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - 475
        y = (self.root.winfo_screenheight() // 2) - 325
        self.root.geometry(f"+{x}+{y}")

        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TNotebook', background='#0a0a0f', borderwidth=0)
        style.configure('TNotebook.Tab', background='#1a1a2e', foreground='#888', padding=[15, 8], font=('Segoe UI', 9))
        style.map('TNotebook.Tab', background=[('selected', '#2563eb')], foreground=[('selected', '#fff')])
        style.configure('TFrame', background='#0a0a0f')

        main_frame = tk.Frame(self.root, bg='#0a0a0f')
        main_frame.pack(fill=tk.BOTH, expand=True)

        sidebar = tk.Frame(main_frame, bg='#12121a', width=280)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)

        sidebar_header = tk.Frame(sidebar, bg='#12121a')
        sidebar_header.pack(fill=tk.X, padx=16, pady=16)
        tk.Label(sidebar_header, text="ROOMS", bg='#12121a', fg='#888', font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT)
        tk.Button(sidebar_header, text="+", command=self.show_create_room, bg='#2563eb', fg='white', bd=0, font=('Segoe UI', 12, 'bold'), width=2, cursor='hand2').pack(side=tk.RIGHT)

        self.room_list_frame = tk.Frame(sidebar, bg='#12121a')
        self.room_list_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        chat_area = tk.Frame(main_frame, bg='#0a0a0f')
        chat_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.chat_header = tk.Frame(chat_area, bg='#12121a', height=60)
        self.chat_header.pack(fill=tk.X)
        self.chat_header.pack_propagate(False)

        self.chat_title = tk.Label(self.chat_header, text="Select a room", bg='#12121a', fg='#fff', font=('Segoe UI', 12, 'bold'))
        self.chat_title.pack(side=tk.LEFT, padx=24, pady=16)
        
        self.chat_meta = tk.Label(self.chat_header, text="Messages auto-delete after 1 hour", bg='#12121a', fg='#888', font=('Segoe UI', 8))
        self.chat_meta.pack(side=tk.LEFT, padx=24, pady=16)

        self.leave_btn = tk.Button(self.chat_header, text="Leave Room", command=self.leave_room, bg='#dc2626', fg='white', bd=0, font=('Segoe UI', 8), padx=16, pady=4, cursor='hand2')
        self.leave_btn.pack(side=tk.RIGHT, padx=24)
        self.leave_btn.pack_forget()

        self.messages_frame = tk.Frame(chat_area, bg='#0a0a0f')
        self.messages_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        self.canvas = tk.Canvas(self.messages_frame, bg='#0a0a0f', highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self.messages_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas, bg='#0a0a0f')
        
        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        self.empty_label = tk.Label(self.scrollable_frame, text="Select or create a room to start chatting", bg='#0a0a0f', fg='#555', font=('Segoe UI', 11))
        self.empty_label.pack(expand=True, pady=100)

        self.input_frame = tk.Frame(chat_area, bg='#12121a', height=80)
        self.input_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self.input_frame.pack_propagate(False)
        self.input_frame.pack_forget()

        input_container = tk.Frame(self.input_frame, bg='#12121a')
        input_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=12)

        self.message_var = tk.StringVar()
        self.message_entry = tk.Entry(input_container, textvariable=self.message_var, font=('Segoe UI', 11), bg='#1e1e2a', fg='#fff', bd=0, highlightthickness=1, highlightbackground='#2a2a3a', highlightcolor='#2563eb', insertbackground='white')
        self.message_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=10, padx=(0, 10))
        self.message_entry.bind('<Return>', lambda e: self.send_message())

        self.encrypt_var = tk.BooleanVar()
        self.encrypt_btn = tk.Checkbutton(input_container, text="🔒 Encrypt", variable=self.encrypt_var, command=self.toggle_encryption, bg='#12121a', fg='#888', selectcolor='#1e1e2a', activebackground='#12121a', activeforeground='#60a5fa', font=('Segoe UI', 9), cursor='hand2')
        self.encrypt_btn.pack(side=tk.LEFT, padx=10)

        self.send_btn = tk.Button(input_container, text="Send", command=self.send_message, bg='#2563eb', fg='white', bd=0, font=('Segoe UI', 10, 'bold'), padx=24, pady=8, cursor='hand2')
        self.send_btn.pack(side=tk.LEFT)

        self.refresh_rooms()

    def refresh_rooms(self):
        asyncio.run_coroutine_threadsafe(self.fetch_rooms(), self.loop)

    async def fetch_rooms(self):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.server_url.replace('ws', 'http')}/api/rooms") as resp:
                    if resp.status == 200:
                        rooms = await resp.json()
                        self.root.after(0, lambda: self.render_rooms(rooms))
        except Exception as e:
            pass

    def render_rooms(self, rooms):
        for widget in self.room_list_frame.winfo_children():
            widget.destroy()
        
        if not rooms:
            tk.Label(self.room_list_frame, text="No rooms yet. Create one to start.", bg='#12121a', fg='#555', font=('Segoe UI', 9)).pack(pady=20)
            return
        
        for room in rooms:
            frame = tk.Frame(self.room_list_frame, bg='#1a1a2e' if room['name'] == self.current_room else '#12121a', cursor='hand2')
            frame.pack(fill=tk.X, pady=2)
            frame.bind("<Button-1>", lambda e, r=room['name']: self.join_room(r))
            
            name_frame = tk.Frame(frame, bg=frame['bg'])
            name_frame.pack(fill=tk.X, padx=12, pady=10)
            
            icon = "🔒 " if room.get('password_protected') else ""
            tk.Label(name_frame, text=f"{icon}{room['name']}", bg=name_frame['bg'], fg='#fff', font=('Segoe UI', 9, 'bold')).pack(side=tk.LEFT)
            
            meta = tk.Frame(name_frame, bg=name_frame['bg'])
            meta.pack(side=tk.RIGHT)
            tk.Label(meta, text=f"{room.get('message_count', 0)} msgs", bg=meta['bg'], fg='#666', font=('Segoe UI', 7)).pack(side=tk.LEFT, padx=4)
            tk.Label(meta, text=f"{room.get('client_count', 0)} users", bg=meta['bg'], fg='#666', font=('Segoe UI', 7)).pack(side=tk.LEFT, padx=4)
            
            for child in [name_frame, meta]:
                child.bind("<Button-1>", lambda e, r=room['name']: self.join_room(r))

    def join_room(self, room_name):
        room = next((r for r in self.rooms if r['name'] == room_name), None)
        if not room:
            return
        
        self.current_room = room_name
        
        dialog = tk.Toplevel(self.root)
        dialog.title("Join Room" if not room.get('password_protected') else "Enter Password")
        dialog.geometry("350x250")
        dialog.resizable(False, False)
        dialog.configure(bg='#0a0a0f')
        dialog.transient(self.root)
        dialog.grab_set()
        
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - 175
        y = (dialog.winfo_screenheight() // 2) - 125
        dialog.geometry(f"+{x}+{y}")

        tk.Label(dialog, text="Enter username", bg='#0a0a0f', fg='#fff', font=('Segoe UI', 11, 'bold')).pack(pady=(20, 10))
        username_var = tk.StringVar()
        username_entry = tk.Entry(dialog, textvariable=username_var, font=('Segoe UI', 11), bg='#1e1e2a', fg='#fff', bd=0, highlightthickness=1, highlightbackground='#2a2a3a', highlightcolor='#2563eb', insertbackground='white', width=25)
        username_entry.pack(pady=5, ipady=6, padx=30)
        username_entry.focus()

        password_var = tk.StringVar()
        password_entry = None
        if room.get('password_protected'):
            tk.Label(dialog, text="Room password", bg='#0a0a0f', fg='#888', font=('Segoe UI', 9)).pack(pady=(15, 5))
            password_entry = tk.Entry(dialog, textvariable=password_var, show='●', font=('Segoe UI', 11), bg='#1e1e2a', fg='#fff', bd=0, highlightthickness=1, highlightbackground='#2a2a3a', highlightcolor='#2563eb', insertbackground='white', width=25)
            password_entry.pack(pady=5, ipady=6, padx=30)

        def on_join():
            username = username_var.get().strip()
            if not username:
                messagebox.showerror("Error", "Username required", parent=dialog)
                return
            if len(username) > 32:
                messagebox.showerror("Error", "Username too long (max 32)", parent=dialog)
                return
            
            password = password_var.get() if room.get('password_protected') else ""
            dialog.destroy()
            asyncio.run_coroutine_threadsafe(self.connect_websocket(room_name, username, password), self.loop)

        btn_frame = tk.Frame(dialog, bg='#0a0a0f')
        btn_frame.pack(pady=20)
        tk.Button(btn_frame, text="Join", command=on_join, bg='#2563eb', fg='white', bd=0, font=('Segoe UI', 10, 'bold'), padx=30, pady=8, cursor='hand2').pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Cancel", command=dialog.destroy, bg='#374151', fg='white', bd=0, font=('Segoe UI', 10), padx=30, pady=8, cursor='hand2').pack(side=tk.LEFT, padx=10)

        dialog.bind('<Return>', lambda e: on_join())

    async def connect_websocket(self, room, username, password):
        try:
            url = f"{self.server_url}/ws/{room}/{username}"
            self.ws = await websockets.connect(url)
            self.running = True
            self.current_username = username
            self.current_room = room
            self.reconnect_attempts = 0
            
            self.root.after(0, self.on_connected)
            
            async for message in self.ws:
                data = json.loads(message)
                self.handle_ws_message(data)
                
        except Exception as e:
            self.root.after(0, lambda: self.on_disconnected(str(e)))

    def on_connected(self):
        self.chat_title.config(text=self.current_room)
        self.chat_meta.config(text=f"Connected as {self.current_username} • Messages auto-delete after 1 hour")
        self.leave_btn.pack(side=tk.RIGHT, padx=24)
        self.input_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self.empty_label.destroy()
        self.render_rooms(self.rooms)

    def on_disconnected(self, error=""):
        self.running = False
        if self.reconnect_attempts < MAX_RECONNECT_ATTEMPTS and self.current_room and self.current_username:
            self.reconnect_attempts += 1
            self.root.after(RECONNECT_DELAY * 1000 * self.reconnect_attempts, 
                lambda: asyncio.run_coroutine_threadsafe(self.connect_websocket(self.current_room, self.current_username, ""), self.loop))
        else:
            self.leave_room()

    def handle_ws_message(self, data):
        msg_type = data.get('type')
        if msg_type == 'message':
            msg = data['message']
            is_own = msg['username'] == self.current_username
            self.root.after(0, lambda: self.add_message(msg, is_own))
            if not is_own and not self.root.focus_get():
                self.show_notification("New Message", msg['content'] if not msg['encrypted'] else "[Encrypted]", msg['encrypted'])
        elif msg_type == 'user_joined':
            self.root.after(0, lambda: self.add_system_message(f"{data['username']} joined"))
        elif msg_type == 'user_left':
            self.root.after(0, lambda: self.add_system_message(f"{data['username']} left"))

    def add_message(self, message, is_own=False):
        frame = tk.Frame(self.scrollable_frame, bg='#0a0a0f')
        frame.pack(fill=tk.X, pady=6, padx=4)
        
        if is_own:
            frame.pack(anchor='e')
        
        header = tk.Frame(frame, bg='#0a0a0f')
        header.pack(fill=tk.X, anchor='e' if is_own else 'w')
        
        username_color = '#60a5fa' if is_own else '#fff'
        tk.Label(header, text=f"{message['username']}{' (you)' if is_own else ''}", bg='#0a0a0f', fg=username_color, font=('Segoe UI', 8, 'bold')).pack(side=tk.LEFT if not is_own else tk.RIGHT)
        
        time_str = time.strftime('%H:%M', time.localtime(message['timestamp']))
        expires_in = max(0, int(message['expires_at'] - time.time()))
        hrs, rem = divmod(expires_in, 3600)
        mins, secs = divmod(rem, 60)
        timer_text = f"{hrs}h {mins}m" if hrs > 0 else f"{mins}m {secs}s"
        timer_color = '#f87171' if expires_in < 300 else '#fbbf24' if expires_in < 600 else '#888'
        tk.Label(header, text=f"{time_str}  •  {timer_text}", bg='#0a0a0f', fg=timer_color, font=('Consolas', 7)).pack(side=tk.LEFT if not is_own else tk.RIGHT, padx=8)
        
        if message['encrypted']:
            badge = tk.Frame(frame, bg='#1e3a5f')
            badge.pack(fill=tk.X, pady=(2, 4))
            tk.Label(badge, text="🔒 Encrypted", bg='#1e3a5f', fg='#60a5fa', font=('Segoe UI', 7)).pack(padx=8, pady=2)
        
        content_bg = '#2563eb' if is_own else '#1e1e2a'
        content_fg = '#fff' if is_own else '#e0e0e0'
        if message['encrypted']:
            content_bg = '#1e3a5f'
            content_fg = '#93c5fd'
        
        content = tk.Label(frame, text=message['content'], bg=content_bg, fg=content_fg, font=('Segoe UI', 9), wraplength=500, justify='left' if not is_own else 'right', padx=14, pady=8)
        content.pack(anchor='e' if is_own else 'w')
        
        if not message['encrypted'] or (message['encrypted'] and self.encryption_enabled and self.encryption_password):
            display_text = message['content']
            if message['encrypted'] and self.encryption_enabled:
                display_text = self.decrypt_message(message['content'])
            content.config(text=display_text)
        
        self.canvas.yview_moveto(1.0)

    def add_system_message(self, text):
        frame = tk.Frame(self.scrollable_frame, bg='#0a0a0f')
        frame.pack(fill=tk.X, pady=4)
        tk.Label(frame, text=text, bg='#0a0a0f', fg='#666', font=('Segoe UI', 8)).pack()
        self.canvas.yview_moveto(1.0)

    def send_message(self):
        content = self.message_var.get().strip()
        if not content or not self.ws or not self.running:
            return
        
        final_content = content
        if self.encryption_enabled and self.encryption_password:
            final_content = self.encrypt_message(content)
        
        msg = {
            'type': 'message',
            'content': final_content,
            'encrypted': self.encryption_enabled
        }
        
        asyncio.run_coroutine_threadsafe(self.ws.send(json.dumps(msg)), self.loop)
        self.message_var.set('')

    def toggle_encryption(self):
        if self.encrypt_var.get():
            if not self.encryption_password:
                dialog = tk.Toplevel(self.root)
                dialog.title("Encryption Password")
                dialog.geometry("350x200")
                dialog.resizable(False, False)
                dialog.configure(bg='#0a0a0f')
                dialog.transient(self.root)
                dialog.grab_set()
                
                dialog.update_idletasks()
                x = (dialog.winfo_screenwidth() // 2) - 175
                y = (dialog.winfo_screenheight() // 2) - 100
                dialog.geometry(f"+{x}+{y}")
                
                tk.Label(dialog, text="Enter encryption password", bg='#0a0a0f', fg='#fff', font=('Segoe UI', 11, 'bold')).pack(pady=(20, 10))
                pw_var = tk.StringVar()
                pw_entry = tk.Entry(dialog, textvariable=pw_var, show='●', font=('Segoe UI', 11), bg='#1e1e2a', fg='#fff', bd=0, highlightthickness=1, highlightbackground='#2a2a3a', highlightcolor='#2563eb', insertbackground='white', width=25)
                pw_entry.pack(pady=10, ipady=6, padx=30)
                pw_entry.focus()
                
                def on_ok():
                    if pw_var.get():
                        self.encryption_password = pw_var.get()
                        self.encryption_enabled = True
                        self.fernet = Fernet(self.derive_key(self.encryption_password))
                        dialog.destroy()
                    else:
                        messagebox.showerror("Error", "Password required", parent=dialog)
                
                btn_frame = tk.Frame(dialog, bg='#0a0a0f')
                btn_frame.pack(pady=15)
                tk.Button(btn_frame, text="Set Password", command=on_ok, bg='#2563eb', fg='white', bd=0, font=('Segoe UI', 10, 'bold'), padx=20, pady=6, cursor='hand2').pack(side=tk.LEFT, padx=10)
                tk.Button(btn_frame, text="Cancel", command=lambda: [self.encrypt_var.set(False), dialog.destroy()], bg='#374151', fg='white', bd=0, font=('Segoe UI', 10), padx=20, pady=6, cursor='hand2').pack(side=tk.LEFT, padx=10)
                
                dialog.bind('<Return>', lambda e: on_ok())
        else:
            self.encryption_enabled = False
            self.encryption_password = None
            self.fernet = None

    def show_create_room(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Create Room")
        dialog.geometry("380x300")
        dialog.resizable(False, False)
        dialog.configure(bg='#0a0a0f')
        dialog.transient(self.root)
        dialog.grab_set()
        
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - 190
        y = (dialog.winfo_screenheight() // 2) - 150
        dialog.geometry(f"+{x}+{y}")

        tk.Label(dialog, text="Create New Room", bg='#0a0a0f', fg='#fff', font=('Segoe UI', 12, 'bold')).pack(pady=(20, 20))

        tk.Label(dialog, text="Room name", bg='#0a0a0f', fg='#ccc', font=('Segoe UI', 9)).pack(anchor='w', padx=30)
        name_var = tk.StringVar()
        tk.Entry(dialog, textvariable=name_var, font=('Segoe UI', 11), bg='#1e1e2a', fg='#fff', bd=0, highlightthickness=1, highlightbackground='#2a2a3a', highlightcolor='#2563eb', insertbackground='white', width=30).pack(pady=5, ipady=6, padx=30)

        tk.Label(dialog, text="Password (optional)", bg='#0a0a0f', fg='#ccc', font=('Segoe UI', 9)).pack(anchor='w', padx=30, pady=(15, 0))
        pw_var = tk.StringVar()
        tk.Entry(dialog, textvariable=pw_var, show='●', font=('Segoe UI', 11), bg='#1e1e2a', fg='#fff', bd=0, highlightthickness=1, highlightbackground='#2a2a3a', highlightcolor='#2563eb', insertbackground='white', width=30).pack(pady=5, ipady=6, padx=30)

        tk.Label(dialog, text="Max messages (100-10000)", bg='#0a0a0f', fg='#ccc', font=('Segoe UI', 9)).pack(anchor='w', padx=30, pady=(15, 0))
        max_var = tk.StringVar(value="1000")
        tk.Entry(dialog, textvariable=max_var, font=('Segoe UI', 11), bg='#1e1e2a', fg='#fff', bd=0, highlightthickness=1, highlightbackground='#2a2a3a', highlightcolor='#2563eb', insertbackground='white', width=30).pack(pady=5, ipady=6, padx=30)

        def on_create():
            name = name_var.get().strip()
            if not name:
                messagebox.showerror("Error", "Room name required", parent=dialog)
                return
            if len(name) > 32:
                messagebox.showerror("Error", "Name too long (max 32)", parent=dialog)
                return
            
            asyncio.run_coroutine_threadsafe(self.create_room(name, pw_var.get(), int(max_var.get())), self.loop)
            dialog.destroy()

        btn_frame = tk.Frame(dialog, bg='#0a0a0f')
        btn_frame.pack(pady=20)
        tk.Button(btn_frame, text="Create", command=on_create, bg='#2563eb', fg='white', bd=0, font=('Segoe UI', 10, 'bold'), padx=30, pady=8, cursor='hand2').pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Cancel", command=dialog.destroy, bg='#374151', fg='white', bd=0, font=('Segoe UI', 10), padx=30, pady=8, cursor='hand2').pack(side=tk.LEFT, padx=10)

    async def create_room(self, name, password, max_messages):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.server_url.replace('ws', 'http')}/api/rooms", json={
                    'name': name, 'password': password, 'max_messages': max_messages
                }) as resp:
                    if resp.status == 200:
                        self.root.after(0, lambda: messagebox.showinfo("Success", "Room created"))
                        self.refresh_rooms()
                    else:
                        err = await resp.json()
                        self.root.after(0, lambda: messagebox.showerror("Error", err.get('detail', 'Failed to create room')))
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", str(e)))

    def leave_room(self):
        if self.ws:
            self.running = False
            asyncio.run_coroutine_threadsafe(self.ws.close(), self.loop)
            self.ws = None
        
        self.current_room = None
        self.current_username = None
        self.encryption_password = None
        self.encryption_enabled = False
        self.fernet = None
        self.encrypt_var.set(False)
        
        self.chat_title.config(text="Select a room")
        self.chat_meta.config(text="Messages auto-delete after 1 hour")
        self.leave_btn.pack_forget()
        self.input_frame.pack_forget()
        
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        
        self.empty_label = tk.Label(self.scrollable_frame, text="Select or create a room to start chatting", bg='#0a0a0f', fg='#555', font=('Segoe UI', 11))
        self.empty_label.pack(expand=True, pady=100)
        
        self.render_rooms(self.rooms)

    def run(self):
        if not self.authenticate():
            return
        
        self.start_notification_system()
        self.loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.loop_thread.start()
        
        self.setup_main_window()
        self.root.mainloop()

def main():
    client = SecureChatClient()
    client.run()

if __name__ == "__main__":
    main()