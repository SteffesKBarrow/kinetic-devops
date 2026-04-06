#!/usr/bin/env python
"""Clean up stale tokens and corrupted keyring entries."""
import keyring, json, sys, time

SERVICE_SERVERS = "epicor-kinetic-servers"

def list_all_kinetic_entries():
    """List all known Kinetic keyring entries (requires manual enumeration since keyring doesn't support listing)."""
    print("=== Current Kinetic Keyring State ===\n")
    
    # Get servers config
    raw = keyring.get_password(SERVICE_SERVERS, "config")
    servers = json.loads(raw) if raw else {}
    
    print(f"Servers Config: {json.dumps(servers, indent=2)}\n")
    
    # Check global pointer
    last_ptr = keyring.get_password("KineticSDK", "LAST_GLOBAL_SESSION")
    print(f"LAST_GLOBAL_SESSION: {last_ptr}\n")
    
    # List all token slots for each environment
    print("Token Slots:")
    import hashlib
    for env_name, cfg in servers.items():
        api_key = cfg.get("api_key", "")
        sessions = cfg.get("sessions", [])
        if sessions:
            for user in sessions:
                secret = f"{api_key}{user.lower()}"
                key_hash = hashlib.sha256(secret.encode()).hexdigest()[:12]
                slot = f"{env_name}-{user.lower()}-{key_hash}"
                token_raw = keyring.get_password(slot, "current_token")
                status = "EXISTS" if token_raw else "MISSING"
                print(f"  {slot}: {status}")
        else:
            print(f"  (no sessions for {env_name})")

def option_full_wipe():
    """Delete ALL Kinetic keyring entries and start fresh."""
    print("\n🚨 OPTION 4: FULL WIPE (Delete everything)\n")
    print("This will delete:")
    print("  - All server configs (nicknames, URLs, API keys)")
    print("  - All token slots")
    print("  - Global pointer (LAST_GLOBAL_SESSION)")
    print("\nYou will need to re-run: python -m kinetic_devops.auth store\n")
    
    if input("Proceed with full wipe? (y/N): ").strip().lower() == 'y':
        # Delete servers config
        try:
            keyring.delete_password(SERVICE_SERVERS, "config")
            print("✅ Deleted servers config")
        except:
            pass
        
        # Delete global pointer
        try:
            keyring.delete_password("KineticSDK", "LAST_GLOBAL_SESSION")
            print("✅ Deleted LAST_GLOBAL_SESSION pointer")
        except:
            pass
        
        print("✅ Full wipe complete. Run 'python -m kinetic_devops.auth store' to set up again.")
    else:
        print("Cancelled.")

def option_reset_pointer():
    """Delete just the global LAST_GLOBAL_SESSION pointer."""
    print("\n🔄 OPTION 3: RESET GLOBAL POINTER\n")
    print("This will:")
    print("  - Delete LAST_GLOBAL_SESSION (the quick-connect cache)")
    print("  - Keep all tokens and server configs")
    print("  - Next run will show the environment selection menu\n")
    
    if input("Proceed? (y/N): ").strip().lower() == 'y':
        try:
            keyring.delete_password("KineticSDK", "LAST_GLOBAL_SESSION")
            print("✅ Deleted LAST_GLOBAL_SESSION pointer")
        except:
            print("⚠️ No pointer found to delete")
    else:
        print("Cancelled.")

def option_clean_all_sessions():
    """Delete all sessions across all environments (keep server configs)."""
    print("\n🧹 OPTION 2: CLEAN ALL SESSIONS\n")
    print("This will:")
    print("  - Delete all token slots across all environments")
    print("  - Clear the sessions list for all environments")
    print("  - Keep all server configs (URLs, API keys, companies)")
    print("  - Clear the global pointer\n")
    
    if input("Proceed? (y/N): ").strip().lower() == 'y':
        import hashlib
        
        raw = keyring.get_password(SERVICE_SERVERS, "config")
        servers = json.loads(raw) if raw else {}
        
        deleted_count = 0
        
        # For each environment, delete all token slots
        for env_name, cfg in servers.items():
            api_key = cfg.get("api_key", "")
            sessions = cfg.get("sessions", [])
            
            for user in sessions:
                secret = f"{api_key}{user.lower()}"
                key_hash = hashlib.sha256(secret.encode()).hexdigest()[:12]
                slot = f"{env_name}-{user.lower()}-{key_hash}"
                try:
                    keyring.delete_password(slot, "current_token")
                    deleted_count += 1
                except:
                    pass
            
            # Clear sessions list but keep the environment config
            cfg["sessions"] = []
            servers[env_name] = cfg
        
        # Save updated config (with empty sessions lists)
        keyring.set_password(SERVICE_SERVERS, "config", json.dumps(servers))
        print(f"✅ Deleted {deleted_count} token slots across all environments")
        print("✅ Cleared sessions lists for all environments")
        print("✅ Server configs preserved (URLs, API keys, companies)")
        
        # Clear global pointer
        try:
            keyring.delete_password("KineticSDK", "LAST_GLOBAL_SESSION")
            print("✅ Cleared LAST_GLOBAL_SESSION pointer")
        except:
            pass
    else:
        print("Cancelled.")

def validate_and_repair():
    """
    Validate keyring records against current schema and delete/repair non-compliant entries.
    
    Requirements:
    - Each server config must have: url, api_key, companies, sessions (list)
    - Each token slot must have: AccessToken (or access_token), user_id, _local_timestamp
    - Sessions list must only contain valid user IDs
    - LAST_GLOBAL_SESSION (if exists) must point to a valid, non-expired token
    """
    print("\n🔍 VALIDATING KEYRING RECORDS\n")
    
    import hashlib
    
    raw = keyring.get_password(SERVICE_SERVERS, "config")
    servers = json.loads(raw) if raw else {}
    
    issues_found = []
    fixes_applied = []
    
    # Validate each server config
    for env_name, cfg in list(servers.items()):
        # Check required fields
        if not cfg.get("url"):
            issues_found.append(f"⚠️ {env_name}: missing 'url'")
        if not cfg.get("api_key"):
            issues_found.append(f"⚠️ {env_name}: missing 'api_key'")
        if not cfg.get("companies"):
            issues_found.append(f"⚠️ {env_name}: missing 'companies'")
        
        # Ensure sessions is a list
        if "sessions" not in cfg or not isinstance(cfg.get("sessions"), list):
            cfg["sessions"] = []
            fixes_applied.append(f"🔧 {env_name}: reset sessions to empty list")
        
        # Validate each session's token slot
        api_key = cfg.get("api_key", "")
        sessions = cfg.get("sessions", [])
        valid_sessions = []
        
        for user in sessions:
            secret = f"{api_key}{user.lower()}"
            key_hash = hashlib.sha256(secret.encode()).hexdigest()[:12]
            slot = f"{env_name}-{user.lower()}-{key_hash}"
            
            token_raw = keyring.get_password(slot, "current_token")
            if not token_raw:
                issues_found.append(f"⚠️ {env_name}: session '{user}' has no token at slot {slot}")
                # Don't add to valid_sessions; will be pruned below
                continue
            
            try:
                token_data = json.loads(token_raw)
                
                # Check for required token fields
                if not token_data.get("AccessToken") and not token_data.get("access_token"):
                    issues_found.append(f"⚠️ {env_name}/{user}: token missing AccessToken field")
                    continue
                
                if not token_data.get("user_id"):
                    issues_found.append(f"⚠️ {env_name}/{user}: token missing user_id field")
                    continue
                
                if not token_data.get("_local_timestamp"):
                    issues_found.append(f"⚠️ {env_name}/{user}: token missing _local_timestamp")
                    continue
                
                # Check if token is expired
                stored_at = token_data.get("_local_timestamp", 0)
                expires_in = token_data.get("expires_in") or token_data.get("ExpiresIn") or 1200
                remaining = int(expires_in - (time.time() - stored_at))
                
                if remaining <= 0:
                    issues_found.append(f"⚠️ {env_name}/{user}: token expired (will be cleaned on next use)")
                
                # Token is valid; keep it
                valid_sessions.append(user)
                
            except json.JSONDecodeError:
                issues_found.append(f"⚠️ {env_name}/{user}: token data is corrupted JSON")
                continue
        
        # Update sessions list to only include valid ones
        if len(valid_sessions) != len(sessions):
            cfg["sessions"] = valid_sessions
            removed = len(sessions) - len(valid_sessions)
            fixes_applied.append(f"🔧 {env_name}: removed {removed} invalid session(s)")
        
        servers[env_name] = cfg
    
    # Validate LAST_GLOBAL_SESSION pointer
    last_ptr = keyring.get_password("KineticSDK", "LAST_GLOBAL_SESSION")
    if last_ptr:
        token_raw = keyring.get_password(last_ptr, "current_token")
        if not token_raw:
            issues_found.append(f"⚠️ LAST_GLOBAL_SESSION points to slot with no token")
            keyring.delete_password("KineticSDK", "LAST_GLOBAL_SESSION")
            fixes_applied.append(f"🔧 Deleted invalid LAST_GLOBAL_SESSION pointer")
        else:
            try:
                token_data = json.loads(token_raw)
                stored_at = token_data.get("_local_timestamp", 0)
                expires_in = token_data.get("expires_in") or token_data.get("ExpiresIn") or 1200
                remaining = int(expires_in - (time.time() - stored_at))
                if remaining <= 0:
                    issues_found.append(f"⚠️ LAST_GLOBAL_SESSION points to expired token")
                    keyring.delete_password("KineticSDK", "LAST_GLOBAL_SESSION")
                    fixes_applied.append(f"🔧 Deleted expired LAST_GLOBAL_SESSION pointer")
            except json.JSONDecodeError:
                issues_found.append(f"⚠️ LAST_GLOBAL_SESSION token data corrupted")
                keyring.delete_password("KineticSDK", "LAST_GLOBAL_SESSION")
                fixes_applied.append(f"🔧 Deleted corrupted LAST_GLOBAL_SESSION pointer")
    
    # Save repaired config
    if fixes_applied:
        keyring.set_password(SERVICE_SERVERS, "config", json.dumps(servers))
    
    # Print report
    print("=" * 60)
    if issues_found:
        print("\n⚠️ ISSUES FOUND:")
        for issue in issues_found:
            print(f"  {issue}")
    else:
        print("\n✅ No issues found. Keyring is valid.")
    
    if fixes_applied:
        print("\n🔧 REPAIRS APPLIED:")
        for fix in fixes_applied:
            print(f"  {fix}")
    else:
        print("\n✅ No repairs needed.")
    
    print("\n" + "=" * 60)

def main():
    print("\n=== Kinetic Keyring Cleanup Tool ===\n")
    
    list_all_kinetic_entries()
    
    print("\n=== Cleanup Options ===\n")
    print("1) VALIDATE & REPAIR  - Check for schema violations and clean up invalid records")
    print("2) CLEAN ALL SESSIONS - Delete all tokens/sessions (keep server configs)")
    print("3) RESET POINTER      - Delete just the quick-connect cache (LAST_GLOBAL_SESSION)")
    print("4) FULL WIPE          - Delete all Kinetic keyring entries (config + tokens)")
    print("5) EXIT               - Cancel\n")
    
    choice = input("Select option (1-5): ").strip()
    
    if choice == '1':
        validate_and_repair()
    elif choice == '2':
        option_clean_all_sessions()
    elif choice == '3':
        option_reset_pointer()
    elif choice == '4':
        option_full_wipe()
    elif choice == '5':
        print("Cancelled.")
    else:
        print("Invalid choice.")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled by user.")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
