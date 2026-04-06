#!/usr/bin/env python3
"""
scripts/doctor.py

Diagnose environment issues, check dependencies, and fix common configuration problems.
Usage: python scripts/doctor.py
"""
import sys
import os
import shutil
import importlib.util
from pathlib import Path

# Force UTF-8 encoding for Windows console
if sys.platform == 'win32':
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    if sys.stdout is not None:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

def check_venv():
    print("=" * 60)
    print("ENVIRONMENT DIAGNOSTIC TOOL")
    print("=" * 60)
    
    # 1. Check Python Version
    print(f"Python Executable: {sys.executable}")
    print(f"Python Version:    {sys.version.split()[0]}")
    
    # 2. Check Virtual Environment
    in_venv = (sys.prefix != sys.base_prefix) or hasattr(sys, 'real_prefix')
    venv_env_var = os.environ.get("VIRTUAL_ENV")
    
    print(f"In Venv (sys):     {in_venv}")
    print(f"VIRTUAL_ENV Var:   {venv_env_var}")
    
    if venv_env_var:
        # Normalize paths for comparison (Windows case insensitivity)
        running_python = os.path.abspath(sys.executable).lower()
        venv_path = os.path.abspath(venv_env_var).lower()
        
        if not running_python.startswith(venv_path):
            print("\n⚠️  CRITICAL WARNING: PYTHON MISMATCH")
            print("   You are running a Python executable OUTSIDE your active virtual environment.")
            print(f"   Current: {sys.executable}")
            print(f"   Expected inside: {venv_env_var}")
            print("\n   ROOT CAUSE: On Windows, 'python3' often points to the global installation.")
            print("   FIX: Use 'python' instead of 'python3' when the venv is active.")
            return False
        
        # Windows-specific check: venv usually only has python.exe, not python3.exe
        if sys.platform == 'win32':
            scripts_dir = Path(venv_env_var) / 'Scripts'
            if not (scripts_dir / 'python3.exe').exists():
                print("\nℹ️  TIP: 'python3' command may not target this venv on Windows.")
                print("   Use 'python' (without the 3) to ensure you use the active virtual environment.")

    elif not in_venv:
        print("\n⚠️  WARNING: Not running inside a virtual environment.")
        
    return True

def fix_requirements_encoding():
    print("\n--- Checking requirements.txt ---")
    req_path = Path("requirements.txt")
    if not req_path.exists():
        # Try looking one level up if run from scripts/
        if Path("../requirements.txt").exists():
            req_path = Path("../requirements.txt")
        else:
            print("❌ requirements.txt not found.")
            return

    try:
        # Try reading as UTF-8 first
        with open(req_path, 'r', encoding='utf-8') as f:
            content = f.read()
        # Check for null bytes which indicate binary/UTF-16 read as UTF-8
        if '\0' in content:
            raise UnicodeError("Null bytes found")
        print("✅ requirements.txt is valid UTF-8.")
    except (UnicodeError, UnicodeDecodeError):
        print("⚠️  requirements.txt appears to be UTF-16/Binary. Converting to UTF-8...")
        try:
            with open(req_path, 'rb') as f:
                raw = f.read()
            # Decode UTF-16 (handle BOM)
            decoded = raw.decode('utf-16').replace('\r\n', '\n')
            with open(req_path, 'w', encoding='utf-8') as f:
                f.write(decoded)
            print("✅ Fixed requirements.txt encoding.")
        except Exception as e:
            print(f"❌ Failed to convert requirements.txt: {e}")

def check_dependencies():
    print("\n--- Checking Dependencies ---")
    required = ['keyring', 'requests']
    missing = []
    
    for pkg in required:
        spec = importlib.util.find_spec(pkg)
        if spec is None:
            print(f"❌ Missing: {pkg}")
            missing.append(pkg)
        else:
            print(f"✅ Found:   {pkg}")
            
    if missing:
        print(f"\n⚠️  Missing packages detected. Run: pip install -r requirements.txt")

def clean_artifacts():
    print("\n--- Cleaning Artifacts ---")
    root = Path(".")
    # Handle running from scripts/ subdir
    if root.resolve().name == 'scripts':
        root = root.parent
        
    patterns = ["__pycache__", "*.pyc", "*.pyo", ".git_commit_msg.tmp", "env_vars_tmp.bat", "env_vars_tmp.ps1"]
    count = 0
    
    for pattern in patterns:
        for p in root.rglob(pattern):
            try:
                if p.is_dir():
                    shutil.rmtree(p)
                    print(f"   Deleted dir:  {p}")
                else:
                    p.unlink()
                    print(f"   Deleted file: {p}")
                count += 1
            except Exception as e:
                print(f"   Failed to delete {p}: {e}")
    print(f"Removed {count} temporary files/directories.")

def main():
    check_venv()
    fix_requirements_encoding()
    check_dependencies()
    clean_artifacts()
    print("\nDiagnostic complete.")

if __name__ == "__main__":
    main()
