#!/usr/bin/env python3
"""
Chat App - Quick Start Script
Run this to start the backend server locally
"""

import os
import sys
import subprocess
from pathlib import Path

def generate_key():
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode()

def main():
    project_root = Path(__file__).parent
    backend_dir = project_root / "backend"
    
    if not backend_dir.exists():
        print("Error: backend directory not found")
        sys.exit(1)
    
    # Check for .env
    env_file = project_root / ".env"
    if not env_file.exists():
        print("Creating .env from example...")
        example = project_root / ".env.example"
        if example.exists():
            import shutil
            shutil.copy(example, env_file)
        else:
            key = generate_key()
            with open(env_file, "w") as f:
                f.write(f"ENCRYPTION_KEY={key}\nPORT=8000\n")
            print(f"Generated ENCRYPTION_KEY: {key}")
    
    # Check for local key file (for persistence across restarts)
    key_file = project_root / ".encryption_key"
    if not key_file.exists():
        key = generate_key()
        key_file.write_text(key)
        print(f"Generated local encryption key: {key}")
        print("  (Saved to .encryption_key for persistence)")
    
    # Load key into env if not already set
    if not os.environ.get("ENCRYPTION_KEY"):
        os.environ["ENCRYPTION_KEY"] = key_file.read_text().strip()
    
    # Install dependencies
    print("Installing dependencies...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", "backend/requirements.txt"], check=True)
    
    # Start server
    print("\nStarting Chat App server...")
    print("Web interface: http://localhost:8000")
    print("WebSocket: ws://localhost:8000/ws/{room}/{user}")
    print("Health check: http://localhost:8000/health")
    print("\nPress Ctrl+C to stop\n")
    
    os.chdir(backend_dir)
    os.execvpe(sys.executable, [sys.executable, "main.py"], os.environ)

if __name__ == "__main__":
    main()