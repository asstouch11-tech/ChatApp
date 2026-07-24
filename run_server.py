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
    backend_dir = Path(__file__).parent / "backend"
    
    if not backend_dir.exists():
        print("Error: backend directory not found")
        sys.exit(1)
    
    # Check for .env
    env_file = Path(__file__).parent / ".env"
    if not env_file.exists():
        print("Creating .env from example...")
        example = Path(__file__).parent / ".env.example"
        if example.exists():
            import shutil
            shutil.copy(example, env_file)
        else:
            key = generate_key()
            with open(env_file, "w") as f:
                f.write(f"ENCRYPTION_KEY={key}\nPORT=8000\n")
            print(f"Generated ENCRYPTION_KEY: {key}")
    
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