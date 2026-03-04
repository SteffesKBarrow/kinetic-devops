#!/usr/bin/env python
"""Export all keyring contents for debugging (no redaction)."""
import keyring, json, hashlib

SERVICE_SERVERS = "epicor-kinetic-servers"

# Export servers config
raw = keyring.get_password(SERVICE_SERVERS, "config")
servers = json.loads(raw) if raw else {}

print("=== SERVERS CONFIG ===")
print(json.dumps(servers, indent=2))

# Export global pointer
last_ptr = keyring.get_password("KineticSDK", "LAST_GLOBAL_SESSION")
print(f"\n=== GLOBAL POINTER ===\nLAST_GLOBAL_SESSION: {last_ptr}")

if last_ptr:
    meta_raw = keyring.get_password(last_ptr, "current_token")
    print(f"\nMetadata at slot {last_ptr}:")
    if meta_raw:
        meta = json.loads(meta_raw)
        print(json.dumps(meta, indent=2))
    else:
        print("<no metadata found>")

# Export all Third environment token slots
print("\n=== THIRD ENVIRONMENT TOKEN SLOTS ===")
cfg = servers.get("Third")
if cfg:
    api_key = cfg.get("api_key")
    sessions = cfg.get("sessions") or []
    print(f"Sessions list in config: {sessions}")
    
    for user in sessions:
        secret = f"{api_key}{user.lower()}"
        key_hash = hashlib.sha256(secret.encode()).hexdigest()[:12]
        slot = f"Third-{user.lower()}-{key_hash}"
        meta_raw = keyring.get_password(slot, "current_token")
        print(f"\nSlot: {slot}")
        if meta_raw:
            meta = json.loads(meta_raw)
            print(json.dumps(meta, indent=2))
        else:
            print("<no token>")
else:
    print("No Third environment config found")
