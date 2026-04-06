# scripts/diagnose_keyring_redacted.py
import json, keyring, time, hashlib, urllib.parse
from datetime import timedelta

SERVICE_SERVERS = "epicor-kinetic-servers"
LAST_PTR = ("KineticSDK", "LAST_GLOBAL_SESSION")
DEFAULT_TTL_SEC = 1200


def mask_key(k):
    """Keep only the first 4 characters of the API key and ellipsize."""
    if not k:
        return ""
    return f"{k[:4]}..." if len(k) >= 4 else k


def mask_user(u):
    if not u:
        return ""
    u = str(u)
    if len(u) <= 2:
        return u[0] + "*"
    return u[0:2] + "..." + u[-1]


def short_slot(slot):
    return slot[-4:].upper() if slot else "<none>"


def get_servers():
    raw = keyring.get_password(SERVICE_SERVERS, "config")
    try:
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def compute_slot(nickname, user, api_key):
    secret = f"{api_key}{user.lower()}"
    key_hash = hashlib.sha256(secret.encode()).hexdigest()[:12]
    return f"{nickname}-{user.lower()}-{key_hash}"


def get_meta(slot):
    raw = keyring.get_password(slot, "current_token")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    # compute remaining similarly to codebase
    stored_at = data.get("_local_timestamp", 0)
    expires_in = data.get("expires_in") or data.get("ExpiresIn") or DEFAULT_TTL_SEC
    remaining = int(expires_in - (time.time() - stored_at))
    data["_remaining"] = remaining if remaining > 0 else 0
    data["_is_valid"] = remaining > 0
    return data


def redact_url(u):
    try:
        p = urllib.parse.urlparse(u)
        return p.netloc or u
    except Exception:
        return u


def map_companies_to_codenames(raw_companies: str):
    """Replace real company IDs with CO1, CO2 etc per environment."""
    items = [c.strip() for c in str(raw_companies).split(',') if c.strip()]
    mapping = {}
    out = []
    for i, it in enumerate(items, 1):
        key = f"CO{i}"
        mapping[key] = it
        out.append(key)
    return out, mapping


def main():
    servers = get_servers()
    print("--- SERVERS REDACTED SUMMARY ---\n")
    if not servers:
        print("No servers config found.")
        return

    # Retrieve global pointer once
    last_ptr = keyring.get_password(*LAST_PTR)

    for name, cfg in servers.items():
        host = redact_url(cfg.get("url", ""))
        companies_raw = cfg.get("companies", "") or cfg.get('company', '')
        api_key = cfg.get("api_key", "")
        # Sessions key may vary in case across older data shapes
        sessions = cfg.get("sessions") or cfg.get("Sessions") or cfg.get("session") or []

        # Map companies to CO1/CO2
        co_list, co_map = map_companies_to_codenames(companies_raw)

        print(f"Nickname: {name}")
        # print(f"  Host (redacted): {host}")
        print(f"  Companies: {', '.join(co_list) if co_list else '<none>'}")
        print(f"  API Key: {mask_key(api_key)}")

        known_count = len(sessions)

        # Fallback heuristic: if no recorded sessions, check global pointer if it references this nickname
        inferred_sessions = []
        if known_count == 0 and last_ptr:
            try:
                if str(last_ptr).lower().startswith(str(name).lower() + "-"):
                    meta = get_meta(last_ptr)
                    if meta:
                        inferred_sessions.append(meta.get('user_id') or '<unknown>')
            except Exception:
                pass

        print(f"  Known Sessions: {known_count}{' (inferred via pointer)' if inferred_sessions else ''} -> {[mask_user(u) for u in sessions]}")

        if sessions:
            for u in sessions:
                slot = compute_slot(name, u, api_key)
                meta = get_meta(slot)
                if meta:
                    status = "active" if meta.get("_is_valid") else "expired"
                    rem = meta.get("_remaining", 0)
                    co = meta.get("current_company", "<none>")
                    # redact company to COx using mapping
                    redacted_co = next((k for k, v in co_map.items() if v.upper() == str(co).upper()), co)
                    print(f"    - user: {mask_user(meta.get('user_id') or u)} | slot_end: {short_slot(slot)} | {status} | {rem}s left | co: {redacted_co}")
                else:
                    print(f"    - user: {mask_user(u)} | slot_end: {short_slot(slot)} | NO TOKEN")

        # If we inferred a session via global pointer, print that too
        for u in inferred_sessions:
            # compute short id from pointer
            print(f"    - (pointer) user: {mask_user(u)} | slot_end: {short_slot(last_ptr)} | slot referenced by LAST_GLOBAL_SESSION")

        print("")

    # LAST_GLOBAL_SESSION summary
    print("--- GLOBAL POINTER ---")
    if last_ptr:
        print(f"LAST_GLOBAL_SESSION: slot_end={short_slot(last_ptr)}")
        meta = get_meta(last_ptr)
        if meta:
            print(f"  Pointer token status: {'active' if meta.get('_is_valid') else 'expired'}, remaining={meta.get('_remaining',0)}s, env={meta.get('env_name')}, user={mask_user(meta.get('user_id'))}")
        else:
            print("  Pointer slot exists but no metadata found (or unreadable).")
    else:
        print("No LAST_GLOBAL_SESSION pointer found.")
    print("\nDone.")


if __name__ == '__main__':
    main()