import os
import json
import asyncio
import asyncio.tasks
import secrets
import hashlib
import hmac
import time
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional
from dataclasses import dataclass, field, asdict
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

KEY_FILE = Path("/app/.encryption_key")

def load_or_generate_key() -> bytes:
    env_key = os.environ.get("ENCRYPTION_KEY")
    if env_key:
        return env_key.encode() if isinstance(env_key, str) else env_key
    
    if KEY_FILE.exists():
        try:
            key = KEY_FILE.read_bytes().strip()
            logger.info("Loaded encryption key from file")
            return key
        except Exception as e:
            logger.warning(f"Failed to load key file: {e}")
    
    key = Fernet.generate_key()
    try:
        KEY_FILE.write_bytes(key)
        logger.info(f"Generated new encryption key: {key.decode()}")
        logger.info("IMPORTANT: Save this key as ENCRYPTION_KEY environment variable for persistence across restarts")
    except Exception as e:
        logger.warning(f"Could not save key file: {e}")
    return key

ENCRYPTION_KEY = load_or_generate_key()
fernet = Fernet(ENCRYPTION_KEY)

ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH")
ADMIN_PASSWORD_SALT = os.environ.get("ADMIN_PASSWORD_SALT", secrets.token_hex(16))

MESSAGE_TTL_HOURS = 1
CLEANUP_INTERVAL_SECONDS = 300
MAX_MESSAGE_LENGTH = 4096
MAX_MESSAGES_PER_ROOM = 1000
MAX_USERNAME_LENGTH = 32
MAX_ROOM_NAME_LENGTH = 32

@dataclass
class Message:
    id: str
    room: str
    username: str
    content: str
    encrypted: bool
    timestamp: float
    expires_at: float
    message_id: str = field(default_factory=lambda: secrets.token_urlsafe(16))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "room": self.room,
            "username": self.username,
            "content": self.content,
            "encrypted": self.encrypted,
            "timestamp": self.timestamp,
            "expires_at": self.expires_at,
            "message_id": self.message_id
        }

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def to_encrypted_dict(self, key: bytes) -> dict:
        f = Fernet(key)
        encrypted_content = f.encrypt(self.content.encode()).decode()
        return {
            "id": self.id,
            "room": self.room,
            "username": self.username,
            "content": encrypted_content,
            "encrypted": True,
            "timestamp": self.timestamp,
            "expires_at": self.expires_at,
            "message_id": self.message_id
        }

@dataclass
class Room:
    name: str
    password_hash: Optional[str] = None
    password_salt: Optional[str] = None
    messages: List[Message] = field(default_factory=list)
    clients: Set[WebSocket] = field(default_factory=set)
    created_at: float = field(default_factory=time.time)
    max_messages: int = MAX_MESSAGES_PER_ROOM

    def verify_password(self, password: str) -> bool:
        if not self.password_hash or not self.password_salt:
            return True
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=bytes.fromhex(self.password_salt),
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        f = Fernet(key)
        try:
            f.decrypt(self.password_hash.encode())
            return True
        except:
            return False

    def set_password(self, password: str):
        self.password_salt = secrets.token_hex(16)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=bytes.fromhex(self.password_salt),
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        f = Fernet(key)
        self.password_hash = f.encrypt(b"verified").decode()

    def add_message(self, message: Message):
        self.messages.append(message)
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]

    def get_valid_messages(self) -> List[Message]:
        now = time.time()
        self.messages = [m for m in self.messages if not m.is_expired()]
        return self.messages

    def cleanup_expired(self) -> int:
        before = len(self.messages)
        self.messages = [m for m in self.messages if not m.is_expired()]
        return before - len(self.messages)

rooms: Dict[str, Room] = {}
cleanup_task: Optional[asyncio.Task] = None

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[WebSocket, dict] = {}

    async def connect(self, websocket: WebSocket, room: str, username: str):
        await websocket.accept()
        if room not in rooms:
            rooms[room] = Room(name=room)
        rooms[room].clients.add(websocket)
        self.active_connections[websocket] = {"room": room, "username": username}
        await self.broadcast_to_room(room, {
            "type": "user_joined",
            "username": username,
            "timestamp": time.time()
        }, exclude=websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            info = self.active_connections[websocket]
            room_name = info["room"]
            username = info["username"]
            if room_name in rooms:
                rooms[room_name].clients.discard(websocket)
                if not rooms[room_name].clients:
                    pass
            del self.active_connections[websocket]

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        try:
            await websocket.send_json(message)
        except:
            pass

    async def broadcast_to_room(self, room: str, message: dict, exclude: WebSocket = None):
        if room in rooms:
            for client in rooms[room].clients.copy():
                if client != exclude:
                    try:
                        await client.send_json(message)
                    except:
                        rooms[room].clients.discard(client)

manager = ConnectionManager()

class CreateRoomRequest(BaseModel):
    name: str
    password: str = ""
    max_messages: int = MAX_MESSAGES_PER_ROOM

class JoinRoomRequest(BaseModel):
    name: str
    password: str = ""
    username: str

class SendMessageRequest(BaseModel):
    room: str
    username: str
    content: str
    encrypted: bool = False

class EncryptionKeyRequest(BaseModel):
    password: str

def encrypt_message(content: str, password: str) -> str:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"secure-chat-salt",
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    f = Fernet(key)
    return f.encrypt(content.encode()).decode()

def decrypt_message(encrypted: str, password: str) -> str:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"secure-chat-salt",
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    f = Fernet(key)
    return f.decrypt(encrypted.encode()).decode()

async def cleanup_expired_messages():
    while True:
        try:
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
            total_removed = 0
            empty_rooms = []
            for room_name, room in rooms.items():
                removed = room.cleanup_expired()
                total_removed += removed
                if not room.clients and not room.messages:
                    empty_rooms.append(room_name)
            for room_name in empty_rooms:
                del rooms[room_name]
            if total_removed > 0:
                logger.info(f"Cleaned up {total_removed} expired messages, removed {len(empty_rooms)} empty rooms")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    global cleanup_task
    cleanup_task = asyncio.create_task(cleanup_expired_messages())
    yield
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="Secure Chat", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="../frontend"), name="static")

@app.get("/", response_class=HTMLResponse)
async def root():
    with open("../frontend/index.html", "r") as f:
        return HTMLResponse(f.read())

@app.get("/health")
async def health():
    return {"status": "ok", "rooms": len(rooms), "messages": sum(len(r.messages) for r in rooms.values())}

@app.post("/api/rooms")
async def create_room(request: CreateRoomRequest):
    if len(request.name) > MAX_ROOM_NAME_LENGTH:
        raise HTTPException(400, "Room name too long")
    if request.name in rooms:
        raise HTTPException(400, "Room already exists")
    room = Room(name=request.name, max_messages=request.max_messages)
    if request.password:
        room.set_password(request.password)
    rooms[request.name] = room
    return {"name": room.name, "created": room.created_at, "password_protected": bool(request.password)}

@app.post("/api/rooms/join")
async def join_room(request: JoinRoomRequest):
    if len(request.username) > MAX_USERNAME_LENGTH:
        raise HTTPException(400, "Username too long")
    if request.name not in rooms:
        raise HTTPException(404, "Room not found")
    room = rooms[request.name]
    if not room.verify_password(request.password):
        raise HTTPException(401, "Invalid password")
    return {"room": room.name, "messages": [m.to_dict() for m in room.get_valid_messages()]}

@app.post("/api/messages")
async def send_message(request: SendMessageRequest):
    if request.room not in rooms:
        raise HTTPException(404, "Room not found")
    if len(request.content) > MAX_MESSAGE_LENGTH:
        raise HTTPException(400, "Message too long")
    room = rooms[request.room]
    expires_at = time.time() + (MESSAGE_TTL_HOURS * 3600)
    message = Message(
        id=secrets.token_urlsafe(16),
        room=request.room,
        username=request.username,
        content=request.content,
        encrypted=request.encrypted,
        timestamp=time.time(),
        expires_at=expires_at
    )
    room.add_message(message)
    await manager.broadcast_to_room(request.room, {
        "type": "message",
        "message": message.to_dict()
    })
    return {"status": "sent", "message_id": message.id, "expires_at": expires_at}

@app.get("/api/rooms/{room_name}/messages")
async def get_messages(room_name: str):
    if room_name not in rooms:
        raise HTTPException(404, "Room not found")
    room = rooms[room_name]
    return {"messages": [m.to_dict() for m in room.get_valid_messages()]}

@app.post("/api/encryption-key")
async def get_encryption_key(request: EncryptionKeyRequest):
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"secure-chat-salt",
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(request.password.encode()))
    return {"key": key.decode()}

@app.websocket("/ws/{room_name}/{username}")
async def websocket_endpoint(websocket: WebSocket, room_name: str, username: str):
    if room_name not in rooms:
        await websocket.close(code=4004, reason="Room not found")
        return
    if len(username) > MAX_USERNAME_LENGTH:
        await websocket.close(code=4001, reason="Username too long")
        return
    await manager.connect(websocket, room_name, username)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "message":
                content = data.get("content", "")
                encrypted = data.get("encrypted", False)
                if len(content) > MAX_MESSAGE_LENGTH:
                    continue
                room = rooms[room_name]
                expires_at = time.time() + (MESSAGE_TTL_HOURS * 3600)
                message = Message(
                    id=secrets.token_urlsafe(16),
                    room=room_name,
                    username=username,
                    content=content,
                    encrypted=encrypted,
                    timestamp=time.time(),
                    expires_at=expires_at
                )
                room.add_message(message)
                await manager.broadcast_to_room(room_name, {
                    "type": "message",
                    "message": message.to_dict()
                })
            elif data.get("type") == "ping":
                await websocket.send_json({"type": "pong", "timestamp": time.time()})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await manager.broadcast_to_room(room_name, {
            "type": "user_left",
            "username": username,
            "timestamp": time.time()
        })
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)