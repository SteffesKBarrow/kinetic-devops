#!/usr/bin/env python
"""Find all orphaned token slots (exist in keyring but not in sessions list)."""
import keyring, json, hashlib

SERVICE_SERVERS = "epicor-kinetic-servers"

# Get all known environments
raw = keyring.get_password(SERVICE_SERVERS, "config")
servers = json.loads(raw) if raw else {}

print("\n=== SCANNING FOR ORPHANED TOKEN SLOTS ===\n")

orphaned = []

# For each environment, try to compute all possible slots that SHOULD exist
# and cross-reference with what's in the sessions list
for env_name, cfg in servers.items():
    api_key = cfg.get("api_key", "")
    sessions = cfg.get("sessions", [])
    
    print(f"Env: {env_name}")
    print(f"  Sessions list: {sessions}")
    
    # Try some common usernames to see if tokens exist for users NOT in sessions list
    # This is a heuristic scan since keyring doesn't support prefix listing
    common_users = ["admin", "api", "user", "svc", "kinetic", "epicor"]
    
    # Also try to find slots by checking for any slot that matches pattern
    # Since we can't list keyring entries, we need the user to provide hints
    # OR we can try educated guesses based on pattern
    
    # Better approach: have user provide a hint or manually delete
    print(f"  Registered sessions: {len(sessions)}")
    print(f"  (Use: python -m kinetic_devops.auth validate --find-all)")
    print()

print("\n🔍 TO FIND ORPHANED SLOTS:")
print("  The kinetic_devops.auth validate command should have caught these.")
print("  If tokens still exist after validate, they're under unregistered slots.")
print("\n💡 NUCLEAR OPTION: Delete all token slots for an environment manually.")
print("  Step 1: Get list of all possible slots")
print("  Step 2: For each slot, check if it has a 'current_token' entry")
print("  Step 3: Delete any that aren't in the sessions list\n")

# Brute-force scanner: try to read from slots we know might exist
# This requires knowing the pattern and making educated guesses
print("=== ATTEMPTING COMMON PATTERNS ===\n")

for env_name, cfg in servers.items():
    api_key = cfg.get("api_key", "")
    sessions = cfg.get("sessions", [])
    
    # Common username patterns
    test_users = ["admin", "kuser", "apiuser", "service", "svc", "test"]
    
    for test_user in test_users:
        secret = f"{api_key}{test_user.lower()}"
        key_hash = hashlib.sha256(secret.encode()).hexdigest()[:12]
        slot = f"{env_name}-{test_user.lower()}-{key_hash}"
        
        token_raw = keyring.get_password(slot, "current_token")
        if token_raw:
            is_registered = test_user.lower() in [u.lower() for u in sessions]
            status = "✅ REGISTERED" if is_registered else "❌ ORPHANED"
            print(f"{status}: {env_name} / {test_user}")
            print(f"  Slot: {slot}")
            if not is_registered:
                orphaned.append((env_name, test_user, slot))

if orphaned:
    print(f"\n🚨 Found {len(orphaned)} orphaned token slot(s)!\n")
    for env, user, slot in orphaned:
        print(f"  {env}/{user}: {slot}")
    print("\n💡 DELETE these slots:")
    for env, user, slot in orphaned:
        print(f'  keyring.delete_password("{slot}", "current_token")')
else:
    print("\n✅ No orphaned tokens found in common patterns.")
    print("   If tokens still exist, they're under unusual usernames.")
