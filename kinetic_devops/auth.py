# kinetic_devops/auth.py
"""
Kinetic Config Manager — Project-Centric, Zero-Knowledge Vault, and CI/CD Orchestration Model

This module is part of a modern, modular Kinetic SDK infrastructure designed for:

1. **Project-Centric Repository Model**
    - Each Kinetic feature (e.g., Project-Daily-Production) is a self-contained Git submodule, including its own MetaUI, Reports, BPM exports, and BAQs.
    - The SDK (this repo) acts as the host, providing API, deployment, and orchestration logic, while project submodules are the payloads.
    - Public/private separation: SDK core remains clean and trackable; business logic and sensitive assets live in private submodules.

2. **Secure Auth Layer (with Optional Zero-Knowledge Vault)**
    - Credentials are stored in the OS keyring (Windows Credential Manager) by default.
    - Optional "Vault" mode: User provides a personal salt/passphrase at runtime.
    - PBKDF2 + AES-256: Credentials are encrypted before storage, ensuring zero-knowledge privacy.
    - Even with full keyring access, secrets are unreadable without the user’s passphrase (in Vault mode).
    - CI/CD compatibility: In automated environments, secrets can be injected via environment variables, bypassing interactive prompts.

3. **Orchestration & CI/CD Workflow**
    - The SDK provides CLI tools to iterate through project submodules, detect changes (via hashing), and push updates to Kinetic environments.
    - Environment switching (Dev/UAT/Prod) is managed by mapping nicknames to encrypted credentials in the vault.
    - The Auth layer checks for passphrase/API keys in environment variables first, supporting both local and CI/CD workflows.
    - Pre-flight validation (JSON schema, RDL linting) is performed before deployment.
    - Deployment scripts automate upload of .erp/.rdl files to Kinetic endpoints (e.g., Ice.BO.BpMethodSvc, System.ReportSvc).

This file is intentionally lightweight and designed for both interactive developer use and automated CI/CD pipelines. It provides secure, modular, and maintainable credential and config management for all Kinetic SDK operations.
"""

import sys
import json
import base64
import getpass
import argparse
import keyring
import requests
import time
import hashlib
import re
import os
from datetime import timedelta

# Ensure UTF-8 encoding for Windows terminals to support emojis
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from typing import Optional, Dict, Tuple

from urllib.parse import urlparse
if __package__:
    from .KineticCore import KineticCore
    from . import crypto
else:
    from kinetic_devops.KineticCore import KineticCore
    from kinetic_devops import crypto

SERVICE_API_KEY = "epicor-kinetic-apikey"
SERVICE_SERVERS = "epicor-kinetic-servers"
DEFAULT_TTL_SEC = 1200

class KineticConfigManager(KineticCore):
    """Manager for Kinetic server configs and token lifecycle stored in keyring.

    Responsibilities:
    - Read/write server config map from keyring
    - Store and retrieve an API key
    - Fetch and cache access tokens from the Kinetic TokenResource endpoint
    - Provide CLI-friendly helpers to print shell-export commands
    """
    def __init__(self, debug: bool = False):
        super().__init__(debug=debug)
        self.os_type = "windows" if sys.platform == "win32" else "unix"
        self.is_interactive = sys.stdout.isatty()

    def _get_config_hash(self) -> str:
        """Required by KineticCore: Detects if the config map has changed."""
        raw = keyring.get_password(SERVICE_SERVERS, "config")
        if not raw: return "empty"
        return hashlib.md5(raw.encode()).hexdigest()

    def _get_server_dict(self) -> Dict:
        """Load the saved servers map from the keyring.

        Returns an empty dict when nothing is stored yet.
        """
        raw = keyring.get_password(SERVICE_SERVERS, "config")
        if not raw:
            return {}

        # If it's an encrypted blob, attempt to decrypt using environment
        # variable `KINETIC_VAULT_PASSPHRASE` or prompt interactively.
        if crypto.is_encrypted_blob(raw):
            passphrase = os.environ.get("KINETIC_VAULT_PASSPHRASE")
            if not passphrase and sys.stdout.isatty():
                try:
                    passphrase = getpass.getpass("Vault passphrase: ")
                except Exception:
                    passphrase = None

            if not passphrase:
                raise RuntimeError("Vault is encrypted. Set KINETIC_VAULT_PASSPHRASE or run in interactive terminal to provide passphrase.")

            try:
                return crypto.decrypt_json(raw, passphrase)
            except Exception as e:
                raise RuntimeError(f"Failed to decrypt vault: {e}")

        # Legacy plain JSON fallback
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def _find_env(self, servers: Dict, name: str) -> Tuple[Optional[str], Optional[Dict]]:
        """Case-insensitive lookup for a saved server configuration.

        Returns the stored key and its config dict, or (None, None) when not found.
        """
        search_name = name.lower()
        for k, v in servers.items():
            if str(k).lower() == search_name:
                return k, v
        return None, None

    def _get_token_key(self, nickname: str, user_id: str, api_key: str) -> str:
        """Generates a unique identifier: Nickname-UserID-Hash(API+User)."""
        # Incorporating the UserID and API Key into the hash ensures total isolation
        secret_context = f"{api_key}{user_id.lower()}"
        key_hash = hashlib.sha256(secret_context.encode()).hexdigest()[:12]
        return f"{nickname}-{user_id.lower()}-{key_hash}"

    def _list_slots_for_env(self, nickname: str) -> list:
        """Generates all possible token slots for a given environment."""
        servers = self._get_server_dict()
        name, cfg = self._find_env(servers, nickname)
        if not cfg:
            return []
        
        # Generate slots for all known sessions in this environment
        slots = []
        for user in cfg.get("sessions", []):
            slot = self._get_token_key(name, user, cfg['api_key'])
            slots.append(slot)
        return slots

    def _get_api_key(self, nickname: str) -> str:
        """Retrieves the API key for a given environment nickname."""
        servers = self._get_server_dict()
        name, cfg = self._find_env(servers, nickname)
        if not cfg:
            return ""
        return cfg.get('api_key', '')

    def _get_token_meta(self, token_slot: str) -> Optional[Dict]:
        """Retrieves metadata using the unique token_slot identifier."""
        raw_data = keyring.get_password(token_slot, "current_token")
        if not raw_data: return None

        # If token slot is encrypted, decrypt it with same passphrase logic
        if crypto.is_encrypted_blob(raw_data):
            passphrase = os.environ.get("KINETIC_VAULT_PASSPHRASE")
            if not passphrase and sys.stdout.isatty():
                try:
                    passphrase = getpass.getpass("Vault passphrase: ")
                except Exception:
                    passphrase = None
            if not passphrase:
                # Can't decrypt non-interactively; treat as missing
                return None
            try:
                data = crypto.decrypt_json(raw_data, passphrase)
            except Exception:
                return None
        else:
            try:
                data = json.loads(raw_data)
            except Exception:
                return None

        try:
            stored_at = data.get("_local_timestamp", 0)
            expires_in = data.get("expires_in") or data.get("ExpiresIn") or DEFAULT_TTL_SEC
            remaining = int(expires_in - (time.time() - stored_at))
            data["_remaining"] = remaining if remaining > 0 else 0
            data["_is_valid"] = remaining > 0
            return data
        except Exception:
            return None

    def get_session_by_bearer(self, token_to_match: str, fields: Tuple[str, ...]) -> Tuple:
        """
        Global reverse lookup. Identifies the session by scanning obscured slots.
        """
        if not token_to_match:
            return tuple(None for _ in fields)

        # Note: Scanning logic here depends on your keyring backend's ability to list.
        # If listing is unavailable, we iterate known environments to generate slot candidates.
        servers = self._get_server_dict()
        for name, cfg in servers.items():
            # Discovery: Find all slots for this environment
            # (Assuming the manager keeps a registry or the backend supports prefix listing)
            potential_slots = self._list_slots_for_env(name) 
            
            for slot in potential_slots:
                data = self._get_token_meta(slot)
                if data:
                    stored_token = data.get('AccessToken') or data.get('access_token')
                    if stored_token == token_to_match:
                        source_map = {
                            "nickname": name,
                            "user_id": data.get("user_id"), # Found in encrypted blob
                            "url": cfg.get("url"),
                            "company": data.get("current_company"),
                            "last_used": data.get("_last_used"),
                            "meta": data
                        }
                        return tuple(source_map.get(f) for f in fields)
        
        return tuple(None for _ in fields)

    def touch_session(self, slot: str, token_meta: Dict, nickname: str = ""):
        """
        Exclusive bottleneck for session state.
        - Accepts complete token metadata (created by _fetch_token_kinetic or context switch).
        - Registers user in sessions list (zero-trust).
        - Persists to keyring.
        - Sets the Global Last-Run Pointer for Quick Connect.
        
        Args:
            slot: Unique token slot identifier (Nickname-UserID-Hash)
            token_meta: Complete token metadata dict with AccessToken, user_id, etc.
            nickname: Environment nickname for user registration
        """
        now = time.time()
        
        # 1. Validation - token_meta must contain the AccessToken
        if not token_meta.get('AccessToken') and not token_meta.get('access_token'):
            return # Cannot touch a session without a token payload

        # 2. Update timestamp
        token_meta['_last_used'] = now
        
        # 3. Persist to Keyring (Obscured Slot)
        keyring.set_password(slot, "current_token", json.dumps(token_meta))
        
        # 4. Register user in sessions list (CENTRALIZED LOGIC)
        if nickname:
            servers = self._get_server_dict()
            name, cfg = self._find_env(servers, nickname)
            if cfg:
                user_id = token_meta.get("user_id", "")
                if user_id:
                    sessions = cfg.get("sessions", [])
                    if user_id.lower() not in [s.lower() for s in sessions]:
                        sessions.append(user_id)
                        cfg["sessions"] = sessions
                        keyring.set_password(SERVICE_SERVERS, "config", json.dumps(servers))
        
        # 5. Promote to Global Last-Run Pointer
        # This is what prompt_for_env looks for first.
        keyring.set_password("KineticSDK", "LAST_GLOBAL_SESSION", slot)

    def touch_from_headers(self, headers: dict):
        """Extracts context from wire headers and updates the session's current company."""
        auth = headers.get('Authorization', '')
        token = auth.replace("Bearer ", "").strip()
        co_id = headers.get('X-Epicor-Company')
        
        if token:
            # Find who this token belongs to
            nickname, user_id = self.get_session_by_bearer(token, ("nickname", "user_id"))
            if nickname and user_id:
                slot = self._get_token_key(nickname, user_id, self._get_api_key(nickname))
                # Retrieve existing metadata and update company
                meta = self._get_token_meta(slot)
                if meta and co_id:
                    meta['current_company'] = co_id
                    self.touch_session(slot, meta, nickname)

    def sync_companies(self, env_name: str, passive: bool = False):
        """Sync authorized companies from server to local config for one environment."""
        env_name = str(env_name or "").strip()
        if not env_name:
            print("❌ Sync Failure: env name is required")
            return tuple()

        servers = self._get_server_dict()
        name, master_cfg = self._find_env(servers, env_name)
        if not master_cfg:
            print(f"❌ Sync Failure: unknown environment '{env_name}'")
            return tuple()

        local_list = sorted([c.strip() for c in str(master_cfg.get('companies', '')).split(',') if c.strip()])

        url, token, api_key, current_co, user_id, nickname = self.get_active_config(
            name,
            fields=("url", "token", "api_key", "company", "user_id", "nickname"),
        )

        if not token or not url:
            print(f"❌ Sync Failure: No valid session or URL for {name}")
            return tuple(local_list)

        env_match, actual_user = self.get_session_by_bearer(token, ("nickname", "user_id"))
        if env_match and env_match.lower() != str(nickname or name).lower():
            print(f"⚠️ Security Alert: Token belongs to {env_match}, but targeting {nickname or name}!")
        if actual_user and user_id and str(actual_user).lower() != str(user_id).lower():
            print(f"⚠️ Security Alert: Token user is {actual_user}, but targeting {user_id}!")

        base_url = str(url).rstrip('/')
        user_id_wc = str(user_id or "").replace("'", "''")
        bo_path = "Erp.BO.UserFileSvc/GetRows"

        candidate_urls = []
        base_lower = base_url.lower()
        if "/api/v2/" in base_lower:
            candidate_urls.append(f"{base_url}/{bo_path}")
            api_v2_root = base_url[:base_lower.index("/api/v2/") + len("/api/v2")]
            candidate_urls.append(f"{api_v2_root}/{bo_path}")
        else:
            candidate_urls.append(f"{base_url}/api/v2/odata/{current_co}/{bo_path}")
            candidate_urls.append(f"{base_url}/api/v2/{bo_path}")

        ordered_urls = []
        seen_urls = set()
        for candidate_url in candidate_urls:
            normalized_url = candidate_url.rstrip('/')
            if normalized_url and normalized_url not in seen_urls:
                ordered_urls.append(normalized_url)
                seen_urls.add(normalized_url)

        params = {
            "whereClauseUserFile": f"DcdUserID = '{user_id_wc}'",
            "whereClauseUserComp": f"DcdUserID = '{user_id_wc}'",
            "whereClauseUserCompExt": "",
            "pageSize": 50,
            "absolutePage": 1,
        }

        headers = self.get_auth_headers({
            "token": token,
            "api_key": api_key,
            "company": current_co,
        })
        headers["X-Company"] = str(current_co or "")

        try:
            response = None
            last_error = None
            did_retry_refresh = False
            slot = self._get_token_key(name, user_id, api_key)

            for api_url in ordered_urls:
                response = requests.get(api_url, headers=headers, params=params, timeout=20)

                if response.status_code == 401 and "invalid api key" in (response.text or "").lower():
                    self.log_wire("GET", api_url, headers, resp=response)
                    print(
                        "❌ Sync Error: Server rejected the API key for this environment/company. "
                        "Update the environment API key or its company scope, then retry."
                    )
                    return tuple(local_list)

                if response.status_code == 401 and not did_retry_refresh:
                    print(f"⚠️ Received 401 from {nickname or name}; attempting one token refresh and retry...")
                    renew_ctx = {
                        "url": base_url,
                        "api_key": api_key,
                        "user_id": user_id,
                        "token_slot": slot,
                        "nickname": name,
                        "company": current_co,
                    }

                    existing_token = headers.get("Authorization", "").replace("Bearer ", "").strip()
                    renewed = self._renew_token_from_existing(renew_ctx, existing_token) if existing_token else None
                    if not renewed and not passive:
                        renewed = self._fetch_token_kinetic(renew_ctx)

                    if renewed:
                        refreshed = self._get_token_meta(slot) or {}
                        fresh_token = str(refreshed.get("AccessToken") or refreshed.get("access_token") or "").strip()
                        if fresh_token:
                            headers = self.get_auth_headers({
                                "token": fresh_token,
                                "api_key": api_key,
                                "company": current_co,
                            })
                            headers["X-Company"] = str(current_co or "")
                            response = requests.get(api_url, headers=headers, params=params, timeout=20)
                    did_retry_refresh = True

                self.log_wire("GET", api_url, headers, resp=response)

                if response.ok:
                    break

                last_error = f"{response.status_code} for {api_url}"

            if not response or not response.ok:
                if response is not None:
                    response.raise_for_status()
                raise RuntimeError(last_error or "no response from sync probe")

            data = response.json() or {}
            server_set = set()
            return_obj = data.get("returnObj") if isinstance(data, dict) else {}
            comps = return_obj.get("UserComp", []) if isinstance(return_obj, dict) else []
            if isinstance(comps, list):
                for item in comps:
                    if not isinstance(item, dict):
                        continue
                    company = str(item.get("Company") or item.get("CompanyID") or "").strip()
                    if company:
                        server_set.add(company)

            server_list = sorted(server_set)
            if not server_list:
                print(f"⚠️ Sync: server returned no companies for {nickname or name}; keeping local list.")
                return tuple(local_list)

            if server_list == local_list:
                print(f"✅ Sync: {nickname or name} company list is up to date.")
                return tuple(local_list)

            print(f"⚠️ Mismatch detected for {nickname or name}!")
            print(f"   Server: {', '.join(server_list)}")
            print(f"   Local:  {', '.join(local_list)}")

            if passive:
                return tuple(local_list)

            choice = input("\nUpdate company list? [Y]es (Overwrite) / [M]erge / [N]o: ").strip().lower()
            if choice in {"", "y", "yes"}:
                final_list = server_list
            elif choice in {"m", "merge"}:
                final_list = sorted(list(set(local_list + server_list)))
            else:
                return tuple(local_list)

            master_cfg["companies"] = ",".join(final_list)
            keyring.set_password(SERVICE_SERVERS, "config", json.dumps(servers))
            print(f"✅ Updated list saved for {nickname or name}.")
            return tuple(final_list)

        except Exception as e:
            print(f"❌ Sync Error: {e}")
            return tuple(local_list)
        
    def _print_env_var(self, key: str, value: str):
        """Print a shell command that sets an environment variable.

        Values are masked when printed to an interactive terminal to avoid
        accidental disclosure. The actual (unmasked) value is not changed or
        re-stored by this helper; callers should use the print output as a
        convenience for users to capture into their shell session if desired.
        """
        display = value or ""
        if self.is_interactive and value:
            # Mask API keys and tokens for display purposes only.
            if "API_KEY" in key and len(value) > 4:
                display = f"{value[:4]}****************"
            elif "TOKEN" in key:
                display = "****************"

        if self.os_type == "windows":
            print(f"SET {key}={display}")
        else:
            print(f"export {key}=\"{display}\"")

    def use(self, context: any = None):
        """CLI ACTION: Selects environment and prints SET/export lines."""
        # 1. If no context (env) provided via CLI, trigger the interactive prompt
        if not context:
            env_name, user_id, co_id = self.prompt_for_env()
            context = (env_name, user_id, co_id)
        
        # 2. Resolve the full config using the standardized "Triple" fields
        # This fixes the TypeError by providing the 'fields' argument
        config_data = self.get_active_config(
            context, 
            fields=("url", "token", "api_key", "company", "nickname")
        )

        if not config_data[0]:
            sys.stderr.write(f"Error: Could not resolve session for context '{context}'.\n")
            return

        # Map results for display
        url, token, api_key, company, nickname = config_data

        # 3. Print environment variables for the shell
        print(f"\n# Active Session: {nickname} (Co: {company})")
        self._print_env_var("KIN_URL", url)
        self._print_env_var("KIN_COMPANY", company)
        self._print_env_var("KIN_API_KEY", api_key)
        self._print_env_var("KIN_TOKEN", token)

    def prompt_for_env(self, passive: bool = False, prompt_reuse: bool = False) -> Tuple[str, str, str]:
        # 1. GLOBAL QUICK-CONNECT: Check the last session touched by ANY tool
        last_slot = keyring.get_password("KineticSDK", "LAST_GLOBAL_SESSION")
        
        if last_slot and not passive:
            # Be defensive: only auto-reuse the pointer when it actually
            # belongs to a currently configured environment and user.
            meta = self._get_token_meta(last_slot)
            if meta and meta.get("_is_valid"):
                env_guess = meta.get("env_name") or str(last_slot).split('-')[0]
                co = meta.get("current_company", "Unknown")

                # Confirm the environment still exists and the api_key matches
                servers = self._get_server_dict()
                name, cfg = self._find_env(servers, env_guess)
                display_id = last_slot[-4:].upper()

                # Validate that the slot actually matches the current env/user/api_key
                user_id = meta.get("user_id")
                slot_valid = False
                if name and cfg and user_id:
                    try:
                        expected = self._get_token_key(name, user_id, cfg.get('api_key', ''))
                        if expected == last_slot:
                            # Ensure the user is recorded in sessions for this env
                            sessions = cfg.get('sessions', []) or []
                            if any(user_id.lower() == s.lower() for s in sessions):
                                slot_valid = True
                    except Exception:
                        slot_valid = False

                # Require that the token metadata already contains a valid
                # current_company before offering to reuse. If the company is
                # missing, prompt the user to select an environment+company
                # instead of silently reusing an incomplete session.
                if slot_valid and meta.get('current_company'):
                    print(f"\n✨ Last active: ID_{display_id} @ {name} (Co: {co})")
                    # Default behavior is to reuse immediately. To restore
                    # interactive confirmation, either pass prompt_reuse=True
                    # or set KIN_PROMPT_REUSE=1.
                    should_prompt_reuse = prompt_reuse or os.getenv("KIN_PROMPT_REUSE", "").strip().lower() in {
                        "1", "true", "yes", "y", "on"
                    }
                    if should_prompt_reuse:
                        if input("Reuse this session? [Y/n]: ").strip().lower() in ('', 'y', 'yes'):
                            return name, user_id, co
                    else:
                        print("Auto-reusing last active session.")
                        return name, user_id, co

        # 3. SELECT ENVIRONMENT
        configs = self._get_server_dict()
        options = list(configs.keys())
        print("\n--- Select Kinetic Environment ---")
        for i, n in enumerate(options, 1):
            print(f"{i}) 🟢 {n:<15} ({configs[n]['url']})")
        
        choice = input(f"\nSelection (1-{len(options)}) [1]: ").strip() or "1"
        selected_env = options[int(choice)-1]
        env_cfg = configs[selected_env]

        if passive: return selected_env, "", ""

        # 4. SELECT SESSION
        sessions = env_cfg.get("sessions", [])
        selected_user = None
        if sessions:
            print(f"\n👤 Sessions for {selected_env}:")
            for i, user in enumerate(sessions, 1):
                print(f"   {i}) {user}")
            u_choice = input(f"Select Session (0-{len(sessions)}) [1]: ").strip() or "1"
            if u_choice != "0":
                selected_user = sessions[int(u_choice)-1]

        # If no session was selected, insist on a non-empty user id input.
        if not selected_user:
            while True:
                entered = input("Enter Epicor User ID: ").strip()
                if entered:
                    selected_user = entered
                    break
                print("User ID cannot be empty. Please enter your Epicor User ID.")

        # 5. SELECT COMPANY (Supports Direct ID or Numeric Selection)
        raw_cos = env_cfg.get('company') or env_cfg.get('companies') or ""
        available_cos = [c.strip() for c in str(raw_cos).split(',') if c.strip()]
        
        if len(available_cos) > 1:
            print(f"\n🏢 Select Company for {selected_env}:")
            for i, co in enumerate(available_cos, 1):
                print(f"  {i}) {co}")
            
            choice = input(f"Selection (1-{len(available_cos)}) or enter ID [1]: ").strip() or "1"
            
            # --- NEW LOGIC: Support Direct ID Input ---
            # 1. Check if the user typed the ID directly (e.g., "ACME")
            if choice.upper() in [c.upper() for c in available_cos]:
                selected_co = next(c for c in available_cos if c.upper() == choice.upper())
            else:
                try:
                    # 2. Otherwise, treat it as a numeric index
                    idx = int(choice) - 1
                    selected_co = available_cos[idx]
                except (ValueError, IndexError):
                    # 3. Fallback to first if input is garbage
                    print(f"⚠️ Invalid selection. Defaulting to {available_cos[0]}")
                    selected_co = available_cos[0]
        else:
            selected_co = available_cos[0] if available_cos else ""

        # Lock choice into metadata
        self.set_current_company(selected_env, selected_user, selected_co)
        return selected_env, selected_user, selected_co

    def logout(self, env_name: str):
        """Clears all session hashes for a parent environment."""
        servers = self._get_server_dict()
        name, cfg = self._find_env(servers, env_name)
        if not cfg: return

        sessions = cfg.get("sessions", [])
        for user in sessions:
            slot = self._get_token_key(name, user, cfg['api_key'])
            try:
                keyring.delete_password(slot, "current_token")
                print(f"🗑️ Cleared session for {user}")
            except: pass
        
        # Clear the session list in config too
        cfg["sessions"] = []
        keyring.set_password(SERVICE_SERVERS, "config", json.dumps(servers))
        print(f"✅ All sessions for {name} have been purged.")

    def inspect(self, env_name: str):
        """Lists all active user sessions and the redacted server configuration."""
        servers = self._get_server_dict()
        name, cfg = self._find_env(servers, env_name)
        if not cfg:
            print(f"No environment named '{env_name}' found.")
            return

        print(f"\n--- Environment Audit: {name} ---")
        
        # --- Redacted Config Section ---
        api_key = cfg.get('api_key', '')
        redacted_key = f"{api_key[:4]}...{api_key[-4:]}" if len(api_key) > 8 else "****"
        
        print(f"URL:       {cfg.get('url')}")
        print(f"API Key:   {redacted_key}")
        print(f"Companies: {cfg.get('companies', 'None')}") 
        
        # --- Session Section ---
        sessions = cfg.get("sessions", [])
        if not sessions:
            print(f"\nNo recorded sessions for {name}. Use 'auth login' to begin.")
            return

        print(f"\n{'User':<15} | {'Status':<10} | {'Remaining':<12} | {'Current Co'}")
        print("-" * 65)
        for user in sessions:
            slot = self._get_token_key(name, user, cfg['api_key'])
            data = self._get_token_meta(slot)
            
            if data:
                rem = data.get("_remaining", 0)
                status = "✅ ACTIVE" if data.get("_is_valid") else "❌ EXPIRED"
                # Pull current company from token metadata
                current_co = data.get("current_company", "---")
                
                print(f"{data.get('user_id', user):<15} | {status:<10} | "
                      f"{str(timedelta(seconds=rem)):<12} | {current_co}")
            else:
                print(f"{user:<15} | ⚠️ NO TOKEN | {'-':<12} | ---")

    def set_current_company(self, nickname: str, user_id: str, company_id: str):
        """Updates the token metadata in the keyring to track the 'active' company."""
        servers = self._get_server_dict()
        name, cfg = self._find_env(servers, nickname)
        if not cfg: return

        slot = self._get_token_key(name, user_id, cfg['api_key'])
        data = self._get_token_meta(slot)
        
        if data:
            data['current_company'] = company_id
            # Re-save the updated JSON blob to the keyring
            keyring.set_password(slot, "current_token", json.dumps(data))

    def get_all_configs(self) -> Dict[str, Dict]:
        """Module API: Returns a dictionary of all stored configs with their current token status."""
        servers = self._get_server_dict()
        results = {}
        for name, cfg in servers.items():
            # We track tokens per user, so we check the 'sessions' list for the first active one.
            sessions = cfg.get("sessions", [])
            active_meta = None
            
            if sessions:
                # Look for the most recently used or first valid session
                for user in sessions:
                    slot = self._get_token_key(name, user, cfg['api_key'])
                    meta = self._get_token_meta(slot)
                    if meta and meta.get("_is_valid"):
                        active_meta = meta
                        break
            
            results[name] = {
                "url": cfg.get('url'),
                "companies": cfg.get('companies'),
                "is_active": active_meta["_is_valid"] if active_meta else False,
                "remaining_sec": active_meta["_remaining"] if active_meta else 0,
                "status_label": "active" if active_meta and active_meta["_is_valid"] else ("expired" if active_meta else "no token")
            }
        return results

    def list(self):
        """CLI ACTION: List saved nicknames with URL, companies, and token status."""
        configs = self.get_all_configs()
        print(f"\n{'Nickname':<12} | {'URL':<40} | {'Companies':<20} | {'Status'}")
        print("-" * 105)
        
        for name, info in configs.items():
            co_list = str(info.get("companies", "None"))
            # Your original truncation logic
            display_co = (co_list[:17] + "..") if len(co_list) > 17 else co_list

            # Redact URL for display
            url_str = info.get('url', '')
            display_url = url_str
            try:
                parsed_url = urlparse(url_str)
                if parsed_url.hostname:
                    redacted_host = self.redact_value(parsed_url.hostname)
                    display_url = parsed_url._replace(netloc=redacted_host).geturl()
            except Exception:
                # Fallback to redacting the whole string if parsing fails
                display_url = self.redact_value(url_str)

            status = ""
            if info["is_active"]:
                rem = info["remaining_sec"]
                # Displaying minutes left as per your original design
                status = f"✅ {rem//60}m left"
            elif info["status_label"] == "expired":
                status = "❌ Expired"
            else:
                status = "Empty"
            
            print(f"{name:<12} | {display_url:<40} | {display_co:<20} | {status}")

    def store(self):
        """Stores environment and initializes an empty session list."""
        name = input("Nickname (e.g., DEV): ").strip()
        url = input("Base URL: ").strip()
        co = input("Company ID: ").strip()
        key = getpass.getpass("API Key (Scoped): ").strip()
        
        if input(f"Save '{name}'? (y/n): ").lower() == 'y':
            servers = self._get_server_dict()
            # Initialize with an empty sessions list if new
            servers[name] = {
                "url": url, 
                "companies": co, 
                "api_key": key, 
                "sessions": servers.get(name, {}).get("sessions", []) 
            }
            keyring.set_password(SERVICE_SERVERS, "config", json.dumps(servers))
            print(f"✅ Stored {name}")


    def _fetch_token_kinetic(self, ctx: Dict) -> Optional[str]:
        """Interactive credential prompt that saves the UserID into the metadata.

        Accepts a single context dict with keys: url, api_key, user_id, token_slot,
        nickname, company. This consolidates the input and makes it easier to
        pass through the selected company from upstream callers.
        """
        url = ctx.get('url', '')
        api_key = ctx.get('api_key', '')
        user_id = ctx.get('user_id', '')
        token_slot = ctx.get('token_slot', '')
        nickname = ctx.get('nickname', '')
        company = ctx.get('company', '')

        # If the caller did not provide a user_id (empty), prompt now.
        if not user_id:
            while True:
                user_id = input("Epicor User ID: ").strip()
                if user_id:
                    break
                print("User ID cannot be empty. Please enter your Epicor User ID.")

        password = getpass.getpass(f"Password for {user_id}: ").strip()
        auth_url = f"{url.rstrip('/')}/TokenResource.svc/"
        basic_auth = base64.b64encode(f"{user_id}:{password}".encode("utf-8")).decode("ascii")
        primary_headers = {
            'Authorization': f'Basic {basic_auth}',
            'X-API-Key': api_key,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        legacy_headers = {
            'userName': user_id,
            'password': password,
            'x-api-key': api_key,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        try:
            resp = requests.post(auth_url, headers=primary_headers, data='', timeout=15)
            if resp.status_code in (400, 401, 403):
                resp = requests.post(auth_url, headers=legacy_headers, data='', timeout=15)
            resp.raise_for_status()
            res = resp.json()

            # --- ADD REQUIRED METADATA ---
            res["_local_timestamp"] = time.time()
            res["_last_used"] = time.time()
            res["user_id"] = user_id.lower()  # Store username so 'inspect' can show it
            res["env_name"] = nickname # Track source env

            # --- DETERMINE & SAVE current_company (so token is usable immediately) ---
            # If caller provided a company (e.g., from prompt_for_env), use it.
            try:
                if company:
                    res['current_company'] = company
                else:
                    servers = self._get_server_dict()
                    name, cfg = self._find_env(servers, nickname)
                    raw_cos = cfg.get('companies') or cfg.get('company') if cfg else ''
                    available_cos = [c.strip() for c in str(raw_cos).split(',') if c.strip()]

                    if available_cos:
                        if len(available_cos) == 1:
                            selected_co = available_cos[0]
                        else:
                            # Prompt user to choose a company for this session
                            print(f"\n🏢 Select Company for {nickname} (for user {user_id}):")
                            for i, co in enumerate(available_cos, 1):
                                print(f"  {i}) {co}")
                            choice = input(f"Selection (1-{len(available_cos)}) or enter ID [1]: ").strip() or "1"
                            if choice.upper() in [c.upper() for c in available_cos]:
                                selected_co = next(c for c in available_cos if c.upper() == choice.upper())
                            else:
                                try:
                                    idx = int(choice) - 1
                                    selected_co = available_cos[idx]
                                except Exception:
                                    selected_co = available_cos[0]
                        if selected_co:
                            res['current_company'] = selected_co
            except Exception:
                # Best-effort only; if something goes wrong we'll leave current_company absent
                pass

            selected_company = str(res.get("current_company") or company or "").strip()
            probe_ok, probe_reason = self._validate_bearer_access(
                url=url,
                api_key=api_key,
                company=selected_company,
                token=str(res.get('AccessToken') or res.get('access_token') or '').strip(),
                user_id=user_id,
            )
            if not probe_ok:
                sys.stderr.write(
                    f"\n❌ Auth Failed for {user_id}: token minted but BO probe failed ({probe_reason}).\n"
                )
                return None

            # --- SAVE & REGISTER VIA CENTRALIZED BOTTLENECK ---
            # touch_session receives complete token data and handles all registration
            self.touch_session(token_slot, res, nickname)

            return res.get('AccessToken') or res.get('access_token')
        except Exception as e:
            sys.stderr.write(f"\n❌ Auth Failed for {user_id}: {e}\n")
            return None

    def migrate(self):
        """Migrate legacy server entries into the current normalized shape.

        This is a non-destructive rewrite of the stored servers map that
        attempts to harmonize older keys (e.g., `company`) into the current
        `companies` field and ensures each entry contains a `display_name`.
        """
        servers = self._get_server_dict()
        new_servers = {k: {"url": v.get("url", ""), "companies": v.get("companies") or v.get("company") or "ACME", "display_name": k} for k, v in servers.items() if isinstance(v, dict)}
        keyring.set_password(SERVICE_SERVERS, "config", json.dumps(new_servers))
        print("✅ Migration complete.")

    def set_api_key(self, env_name: str, value: str = ""):
        """Replace only the API key for an existing environment."""
        env_name = str(env_name or "").strip()
        if not env_name:
            print("❌ Environment name is required.")
            return

        servers = self._get_server_dict()
        name, cfg = self._find_env(servers, env_name)
        if not cfg:
            print(f"❌ No environment named '{env_name}' found.")
            return

        new_key = str(value or "").strip()
        if not new_key:
            new_key = getpass.getpass(f"New API key for {name}: ").strip()
        if not new_key:
            print("❌ API key cannot be empty.")
            return

        old_key = str(cfg.get("api_key") or "").strip()
        if old_key == new_key:
            print(f"✅ API key for {name} is unchanged.")
            return

        deleted_slots = 0
        sessions = cfg.get("sessions", []) or []
        for user in sessions:
            user_id = str(user or "").strip()
            if not user_id:
                continue
            try:
                old_slot = self._get_token_key(name, user_id, old_key)
                keyring.delete_password(old_slot, "current_token")
                deleted_slots += 1
            except Exception:
                pass

        cfg["api_key"] = new_key
        servers[name] = cfg
        keyring.set_password(SERVICE_SERVERS, "config", json.dumps(servers))

        try:
            last_slot = keyring.get_password("KineticSDK", "LAST_GLOBAL_SESSION") or ""
            if last_slot and any(last_slot == self._get_token_key(name, str(user), old_key) for user in sessions if str(user).strip()):
                keyring.delete_password("KineticSDK", "LAST_GLOBAL_SESSION")
        except Exception:
            pass

        print(f"✅ API key updated for {name}.")
        if deleted_slots:
            print(f"Removed {deleted_slots} cached token slot(s) for {name}; renew to create a fresh token.")

    def _renew_token_from_existing(self, ctx: Dict, existing_token: str) -> Optional[str]:
        """Attempt to obtain a fresh JWT using an existing bearer token."""
        url = str(ctx.get("url") or "").strip().rstrip("/")
        api_key = str(ctx.get("api_key") or "").strip()
        user_id = str(ctx.get("user_id") or "").strip().lower()
        token_slot = str(ctx.get("token_slot") or "").strip()
        nickname = str(ctx.get("nickname") or "").strip()
        company = str(ctx.get("company") or "").strip()

        if not url or not api_key or not token_slot or not existing_token:
            return None

        candidates = [
            ("POST", f"{url}/TokenResource.svc/", ""),
            ("POST", f"{url}/TokenResource.svc/RefreshToken", ""),
            ("POST", f"{url}/TokenResource.svc/refresh", ""),
            ("GET", f"{url}/TokenResource.svc/", None),
        ]

        base_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "Authorization": f"Bearer {existing_token}",
        }
        if company:
            base_headers["X-Epicor-Company"] = company

        for method, endpoint, payload in candidates:
            try:
                if method == "POST":
                    resp = requests.post(endpoint, headers=base_headers, data=payload, timeout=15)
                else:
                    resp = requests.get(endpoint, headers=base_headers, timeout=15)
                resp.raise_for_status()
                data = resp.json() if resp.content else {}
                if not isinstance(data, dict):
                    continue

                token = str(data.get("AccessToken") or data.get("access_token") or "").strip()
                if not token:
                    continue

                probe_ok, _ = self._validate_bearer_access(
                    url=url,
                    api_key=api_key,
                    company=company,
                    token=token,
                    user_id=user_id,
                )
                if not probe_ok:
                    continue

                data["_local_timestamp"] = time.time()
                data["_last_used"] = time.time()
                data["user_id"] = user_id
                data["env_name"] = nickname
                if company:
                    data["current_company"] = company

                self.touch_session(token_slot, data, nickname)
                return token
            except Exception:
                continue

        return None

    def _validate_bearer_access(
        self,
        url: str,
        api_key: str,
        company: str,
        token: str,
        user_id: str,
    ) -> Tuple[bool, str]:
        """Validate bearer usability against a real BO endpoint."""
        base_url = str(url or "").strip().rstrip("/")
        api_key = str(api_key or "").strip()
        company = str(company or "").strip()
        token = str(token or "").strip()
        user_id = str(user_id or "").strip()
        if not base_url or not api_key or not company or not token:
            return False, "missing probe inputs"

        user_id_wc = user_id.replace("'", "''")
        where = f"DcdUserID = '{user_id_wc}'" if user_id else ""
        params = {
            "whereClauseUserFile": where,
            "whereClauseUserComp": where,
            "whereClauseUserCompExt": "",
            "pageSize": 1,
            "absolutePage": 1,
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-API-Key": api_key,
            "X-Epicor-Company": company,
            "X-Company": company,
        }

        bo_path = "Erp.BO.UserFileSvc/GetRows"
        candidates = []
        base_lower = base_url.lower()
        if "/api/v2/" in base_lower:
            candidates.append(f"{base_url}/{bo_path}")
            api_v2_root = base_url[:base_lower.index("/api/v2/") + len("/api/v2")]
            candidates.append(f"{api_v2_root}/{bo_path}")
        else:
            candidates.append(f"{base_url}/api/v2/odata/{company}/{bo_path}")
            candidates.append(f"{base_url}/api/v2/{bo_path}")

        seen = set()
        ordered = []
        for item in candidates:
            normalized = item.rstrip("/")
            if normalized and normalized not in seen:
                ordered.append(normalized)
                seen.add(normalized)

        last_status = "no-response"
        for endpoint in ordered:
            try:
                response = requests.get(endpoint, headers=headers, params=params, timeout=15)
                if response.ok:
                    return True, f"{response.status_code} {endpoint}"
                last_status = str(response.status_code)
                body = (response.text or "")[:200].lower()
                if "invalid api key" in body:
                    return False, "api key rejected"
            except Exception as exc:
                last_status = str(exc)

        return False, f"probe failed: {last_status}"

    def renew(
        self,
        env_name: str = "",
        user_id: str = "",
        company_id: str = "",
        from_token: bool = False,
        allow_password_fallback: bool = False,
    ):
        """Force a fresh JWT fetch from TokenResource and persist it to keyring."""
        env_name = str(env_name or "").strip()
        user_id = str(user_id or "").strip()
        company_id = str(company_id or "").strip()

        servers = self._get_server_dict()

        if not env_name or not user_id:
            selected_env, selected_user, selected_co = self.prompt_for_env()
            env_name = env_name or selected_env
            user_id = user_id or selected_user
            company_id = company_id or selected_co

        name, cfg = self._find_env(servers, env_name)
        if not cfg:
            print(f"❌ No environment named '{env_name}' found.")
            return

        if not user_id:
            sessions = cfg.get("sessions", []) or []
            if sessions:
                user_id = str(sessions[0]).strip()

        if not user_id:
            while True:
                entered = input("Epicor User ID: ").strip()
                if entered:
                    user_id = entered
                    break
                print("User ID cannot be empty. Please enter your Epicor User ID.")

        if not company_id:
            try:
                slot_guess = self._get_token_key(name, user_id, cfg.get("api_key", ""))
                meta = self._get_token_meta(slot_guess) or {}
                company_id = str(meta.get("current_company") or "").strip()
            except Exception:
                company_id = ""

        if not company_id:
            companies = [c.strip() for c in str(cfg.get("companies", "")).split(",") if c.strip()]
            company_id = companies[0] if companies else ""

        api_key = cfg.get("api_key", "")
        slot = self._get_token_key(name, user_id, api_key)
        ctx = {
            "url": cfg.get("url", ""),
            "api_key": api_key,
            "user_id": user_id,
            "token_slot": slot,
            "nickname": name,
            "company": company_id,
        }

        if from_token:
            current_meta = self._get_token_meta(slot) or {}
            current_token = str(current_meta.get("AccessToken") or current_meta.get("access_token") or "").strip()
            renewed = self._renew_token_from_existing(ctx, current_token)
            if renewed:
                print(f"\n✅ Token renewed from existing bearer for {name}/{user_id} (Co: {company_id})")
                self.use((name, user_id, company_id))
                return

            print("❌ Token-based renewal failed for this environment.")
            if not allow_password_fallback:
                print("Tip: rerun with --allow-password-fallback to prompt for password-based token re-issue.")
                return

        token = self._fetch_token_kinetic(ctx)
        if not token:
            print("❌ Token renewal failed.")
            return

        print(f"\n✅ Token renewed for {name}/{user_id} (Co: {company_id})")
        self.use((name, user_id, company_id))

    def delete(self, env_name: str):
        """Delete a saved server entry by nickname (case-insensitive).

        The operation updates the stored servers map in the keyring.
        """
        servers = self._get_server_dict()
        name, _ = self._find_env(servers, env_name)
        if name:
            del servers[name]
            keyring.set_password(SERVICE_SERVERS, "config", json.dumps(servers))
            print(f"Deleted '{name}'.")

    def get_base_config(self, env_name: str) -> Optional[Dict]:
        """
        Retrieves stored environment metadata without attempting to 
        authenticate or fetch a token. Useful for legacy shell exports.
        """
        servers = self._get_server_dict()
        name, cfg = self._find_env(servers, env_name)
        if not cfg:
            return None
        
        return {
            "url": cfg.get('url'),
            "companies": cfg.get('companies'),
            "api_key": cfg.get('api_key'),
            "nickname": name
        }

    def get_active_config(self, context: any, fields: Tuple[str, ...]) -> Tuple:
        """
        Accepts context as:
        - "nickname" (Uses last active user/company)
        - ("nickname", "user_id") (Uses last active company)
        - {"env": "...", "user": "...", "co": "..."} (Precise)
        """
        # --- 1. UNPACK CONTEXT ---
        env_name, user_id, company_id = None, None, None
        
        if isinstance(context, str):
            env_name = context
        elif isinstance(context, (tuple, list)):
            env_name = context[0]
            if len(context) > 1: user_id = context[1]
            if len(context) > 2: company_id = context[2]
        elif isinstance(context, dict):
            env_name = context.get('env') or context.get('nickname')
            user_id = context.get('user') or context.get('user_id')
            company_id = context.get('co') or context.get('company')

        # --- 2. RESOLVE MISSING PIECES ---
        servers = self._get_server_dict()
        name, cfg = self._find_env(servers, env_name)
        if not cfg: return tuple(None for _ in fields)

        # Fallback for user: Use first session if not provided
        if not user_id:
            sessions = cfg.get("sessions", [])
            if sessions:
                user_id = sessions[0]
            else:
                # No user provided AND no saved sessions: must prompt interactively
                env_name, user_id, company_id = self.prompt_for_env()
                name, cfg = self._find_env(servers, env_name)
                if not cfg: return tuple(None for _ in fields)
        
        if not user_id: return tuple(None for _ in fields)

        # Resolve token & meta
        api_key = cfg['api_key']
        slot = self._get_token_key(name, user_id, api_key)
        meta = self._get_token_meta(slot)

        # (Insert Auth/Fetch Logic here...)
        # CORRECTED LOGIC:
        token = None
        # Only reuse a cached token when it's valid AND the user_id is
        # recorded in the environment's sessions list. This prevents
        # using orphaned keyring blobs that are not associated with
        # the saved server config.
        if meta and meta.get("_is_valid"):
            sessions = cfg.get('sessions', []) or []
            if user_id and any(user_id.lower() == s.lower() for s in sessions):
                token = meta.get('AccessToken') or meta.get('access_token')
            else:
                # If the cached token exists but the user isn't recorded
                # in the sessions list, force an interactive fetch so the
                # session is created through the centralized touch_session
                ctx = {
                    'url': cfg.get('url'),
                    'api_key': api_key,
                    'user_id': user_id,
                    'token_slot': slot,
                    'nickname': name,
                    'company': company_id
                }
                token = self._fetch_token_kinetic(ctx)
        else:
            # Pass the variables resolved earlier in the method
            ctx = {
                'url': cfg.get('url'),
                'api_key': api_key,
                'user_id': user_id,
                'token_slot': slot,
                'nickname': name,
                'company': company_id
            }
            token = self._fetch_token_kinetic(ctx)

        # If we performed an interactive fetch above, refresh the meta
        # so that subsequent logic (company resolution) sees any fields
        # added during touch_session (e.g., current_company)
        try:
            meta = self._get_token_meta(slot) or meta
        except Exception:
            pass

        # --- 3. THE "CLEAN" RESOLUTION ---
        # If no company provided, check meta, then fallback to first valid ID in sync list
        active_co = company_id or (meta.get('current_company') if meta else None)
        if not active_co or ',' in str(active_co):
            active_co = [c.strip() for c in cfg.get('companies', '').split(',') if c.strip()][0]

        # --- 4. MAP & RETURN ---
        source_map = {
            "nickname": name,
            "user_id": user_id,
            "url": cfg.get("url"),
            "token": token,
            "api_key": api_key,
            "company": active_co,
            "meta": meta
        }
        return tuple(source_map.get(f) for f in fields)

    def get_auth_headers(self, config: Dict, plant_id: str = "") -> Dict:
        """
        Generates standard headers for Epicor V2 OData calls.
        'self' must be the first argument.
        """
        if not config:
            raise ValueError("No configuration provided for header generation.")

        # We pull the values out of the 'config' dictionary passed in
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-Epicor-Company': config.get('company'),
            'X-API-Key': str(config.get('api_key', '')),
        }
        
        if plant_id:
            headers['X-Epicor-Plant'] = str(plant_id)

        token = config.get('token')
        if token:
            headers['Authorization'] = f'Bearer {token}'
            
        return headers

    def redact_json(self, data: Dict) -> Dict:
        """Standardized redactor with Sanity Check error codes."""
        sensitive_keys = {'Authorization': 'Token', 'X-API-Key': 'Key'}
        redact_marker = "[REDACTED]"
        clean_data = json.loads(json.dumps(data))

        def _scan(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k in sensitive_keys:
                        val_str = str(v).strip()
                        if not val_str: raise ValueError(f"ERR_EMPTY_SECRET: {k}")
                        if redact_marker in val_str: raise ValueError(f"ERR_PRE_REDACTED: {k}")
                        # API Key gets a partial mask; Token gets full redaction
                        obj[k] = f"{val_str[:4]}...{val_str[-4:]}" if k == 'X-API-Key' else redact_marker
                    else: _scan(v)
            elif isinstance(obj, list):
                for item in obj: _scan(item)
        _scan(clean_data)
        return clean_data
    
    def get_sensitive_data_patterns(self) -> Dict[str, 're.Pattern']:
        """
        Generates regex patterns for sensitive data stored in the keyring.
        This includes API keys (partial match), hostnames, and a consolidated list of company IDs.
        """
        patterns = {}
        all_companies = set()

        # Use _get_server_dict to get raw config without token status
        servers = self._get_server_dict()
        if not servers:
            return {}

        for name, config in servers.items():
            # Pattern for URL Hostname
            if config.get("url"):
                try:
                    hostname = urlparse(config["url"]).hostname
                    if hostname:
                        patterns[f"URL_HOSTNAME_FOR_{name}"] = re.compile(re.escape(hostname), re.IGNORECASE)
                except Exception:
                    pass  # Ignore if URL parsing fails

            # Pattern for API Key (full and partial match)
            if config.get("api_key"):
                key = config["api_key"]
                if len(key) > 10:
                    first_part = re.escape(key[:5])
                    last_part = re.escape(key[-5:])
                    # Matches base64-like characters in the middle
                    patterns[f"API_KEY_PARTIAL_FOR_{name}"] = re.compile(
                        f'{first_part}[a-zA-Z0-9+/_-]{{10,60}}{last_part}'
                    )
                # Also keep the full key match for exact findings
                patterns[f"API_KEY_FULL_FOR_{name}"] = re.compile(r'\b' + re.escape(key) + r'\b')

            # Collect all company IDs
            companies_str = config.get("companies") or config.get("company") or ""
            if companies_str:
                for company in companies_str.split(','):
                    co = company.strip()
                    if co:
                        all_companies.add(re.escape(co))

        # Create a single, efficient regex for all company IDs
        if all_companies:
            # Sort by length descending to match longer company IDs first
            sorted_companies = sorted(list(all_companies), key=len, reverse=True)
            patterns["ALL_COMPANY_IDS"] = re.compile(r'\b(' + '|'.join(sorted_companies) + r')\b', re.IGNORECASE)

        return patterns

    def panic(self):
        """🚨 Emergency Wipe: Deletes all salts, sentinels, and the cache file."""
        print("🚨 Panic Wipe Initiated...")
        keys_to_purge = ["Sentinel", "Integrity", "SDK_CORE_A", "SDK_CORE_B"]
        for k in keys_to_purge:
            try: keyring.delete_password("KineticSDK", k)
            except: pass
        if os.path.exists(self._cache_file):
            os.remove(self._cache_file)
        print("✅ Security environment purged. Re-run 'store' or 'use' to re-initialize.")

    def clean_sessions(self):
        """Deletes all sessions across all environments (keeps server configs)."""
        print("\n🧹 CLEAN ALL SESSIONS\n")
        print("This will:")
        print("  - Delete all token slots across all environments")
        print("  - Clear the sessions list for all environments")
        print("  - Keep all server configs (URLs, API keys, companies)")
        print("  - Clear the global pointer\n")
        
        if input("Proceed? (y/N): ").strip().lower() != 'y':
            print("Cancelled.")
            return
        
        servers = self._get_server_dict()
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

    def validate(self):
        """
        Validate keyring records against schema and auto-repair invalid entries.
        
        Requirements:
        - Each server config must have: url, api_key, companies, sessions (list)
        - Each token slot must have: AccessToken, user_id, _local_timestamp
        - LAST_GLOBAL_SESSION (if exists) must point to valid, non-expired token
        """
        print("\n🔍 VALIDATING KEYRING RECORDS\n")
        
        servers = self._get_server_dict()
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
                    expires_in = token_data.get("expires_in") or token_data.get("ExpiresIn") or DEFAULT_TTL_SEC
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
                try:
                    keyring.delete_password("KineticSDK", "LAST_GLOBAL_SESSION")
                    fixes_applied.append(f"🔧 Deleted invalid LAST_GLOBAL_SESSION pointer")
                except:
                    pass
            else:
                try:
                    token_data = json.loads(token_raw)
                    stored_at = token_data.get("_local_timestamp", 0)
                    expires_in = token_data.get("expires_in") or token_data.get("ExpiresIn") or DEFAULT_TTL_SEC
                    remaining = int(expires_in - (time.time() - stored_at))
                    if remaining <= 0:
                        issues_found.append(f"⚠️ LAST_GLOBAL_SESSION points to expired token")
                        keyring.delete_password("KineticSDK", "LAST_GLOBAL_SESSION")
                        fixes_applied.append(f"🔧 Deleted expired LAST_GLOBAL_SESSION pointer")
                except json.JSONDecodeError:
                    issues_found.append(f"⚠️ LAST_GLOBAL_SESSION token data corrupted")
                    try:
                        keyring.delete_password("KineticSDK", "LAST_GLOBAL_SESSION")
                        fixes_applied.append(f"🔧 Deleted corrupted LAST_GLOBAL_SESSION pointer")
                    except:
                        pass
        
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
    parser = argparse.ArgumentParser(description="Kinetic Config Manager")
    subparsers = parser.add_subparsers(dest="command")
    
    subparsers.add_parser("store")
    subparsers.add_parser("list")
    subparsers.add_parser("migrate")
    subparsers.add_parser("encrypt-vault")
    subparsers.add_parser("decrypt-vault")
    subparsers.add_parser("panic")
    subparsers.add_parser("validate")
    subparsers.add_parser("clean-sessions")
    set_key_p = subparsers.add_parser("set-api-key")
    set_key_p.add_argument("env")
    set_key_p.add_argument("--value", default="")
    renew_p = subparsers.add_parser("renew")
    renew_p.add_argument("env", nargs="?", default="")
    renew_p.add_argument("--user", default="")
    renew_p.add_argument("--co", default="")
    renew_p.add_argument("--from-token", action="store_true")
    renew_p.add_argument("--allow-password-fallback", action="store_true")
    
    sync_p = subparsers.add_parser("sync-companies")
    sync_p.add_argument("env")

    for cmd in ["inspect", "use", "delete", "logout"]:
        p = subparsers.add_parser(cmd)
        if cmd == "use":
            p.add_argument("env", nargs="?", default=None)
        else:
            p.add_argument("env")

    args = parser.parse_args()
    mgr = KineticConfigManager(debug=True)
    
    try:
        if args.command == "store": mgr.store()
        elif args.command == "list": mgr.list()
        elif args.command == "migrate": mgr.migrate()
        elif args.command == "encrypt-vault":
            # Encrypt servers map and all token slots.
            passphrase = os.environ.get("KINETIC_VAULT_PASSPHRASE")
            if not passphrase and sys.stdout.isatty():
                passphrase = getpass.getpass("New vault passphrase: ")
                confirm = getpass.getpass("Confirm vault passphrase: ")
                if passphrase != confirm:
                    print("Passphrases do not match. Aborting.")
                    sys.exit(1)

            if not passphrase:
                print("Provide KINETIC_VAULT_PASSPHRASE env var or run interactively.")
                sys.exit(1)

            # Encrypt servers map
            raw = keyring.get_password(SERVICE_SERVERS, "config")
            if not raw:
                print("No servers config to encrypt.")
            else:
                if crypto.is_encrypted_blob(raw):
                    print("Vault already encrypted.")
                else:
                    try:
                        servers = json.loads(raw)
                        enc = crypto.encrypt_json(servers, passphrase)
                        keyring.set_password(SERVICE_SERVERS, "config", enc)
                        print("✅ Servers map encrypted.")
                    except Exception as e:
                        print(f"Failed to encrypt servers: {e}")

            # Encrypt token slots
            servers = mgr._get_server_dict()
            for name, cfg in servers.items():
                api_key = cfg.get('api_key', '')
                for user in cfg.get('sessions', []):
                    slot = mgr._get_token_key(name, user, api_key)
                    token_raw = keyring.get_password(slot, 'current_token')
                    if token_raw and not crypto.is_encrypted_blob(token_raw):
                        try:
                            token_data = json.loads(token_raw)
                            enc_token = crypto.encrypt_json(token_data, passphrase)
                            keyring.set_password(slot, 'current_token', enc_token)
                        except Exception:
                            pass
            print("✅ Vault encryption completed.")

        elif args.command == "decrypt-vault":
            passphrase = os.environ.get("KINETIC_VAULT_PASSPHRASE")
            if not passphrase and sys.stdout.isatty():
                passphrase = getpass.getpass("Vault passphrase: ")
            if not passphrase:
                print("Provide KINETIC_VAULT_PASSPHRASE env var or run interactively.")
                sys.exit(1)

            raw = keyring.get_password(SERVICE_SERVERS, "config")
            if not raw:
                print("No servers config found.")
            else:
                if not crypto.is_encrypted_blob(raw):
                    print("Servers map is not encrypted.")
                else:
                    try:
                        dec = crypto.decrypt_json(raw, passphrase)
                        keyring.set_password(SERVICE_SERVERS, "config", json.dumps(dec))
                        print("✅ Servers map decrypted (now stored as plain JSON).")
                    except Exception as e:
                        print(f"Failed to decrypt servers: {e}")

            # Decrypt token slots
            servers = mgr._get_server_dict()
            for name, cfg in servers.items():
                api_key = cfg.get('api_key', '')
                for user in cfg.get('sessions', []):
                    slot = mgr._get_token_key(name, user, api_key)
                    token_raw = keyring.get_password(slot, 'current_token')
                    if token_raw and crypto.is_encrypted_blob(token_raw):
                        try:
                            token_data = crypto.decrypt_json(token_raw, passphrase)
                            keyring.set_password(slot, 'current_token', json.dumps(token_data))
                        except Exception:
                            pass
            print("✅ Vault decryption completed.")

        elif args.command == "panic": mgr.panic()
        elif args.command == "validate": mgr.validate()
        elif args.command == "clean-sessions": mgr.clean_sessions()
        elif args.command == "set-api-key": mgr.set_api_key(args.env, args.value)
        elif args.command == "renew":
            mgr.renew(
                args.env,
                args.user,
                args.co,
                from_token=bool(args.from_token),
                allow_password_fallback=bool(args.allow_password_fallback),
            )
        elif args.command == "sync-companies": mgr.sync_companies(args.env)
        elif args.command == "inspect": mgr.inspect(args.env)
        elif args.command == "use": mgr.use(args.env)
        elif args.command == "delete": mgr.delete(args.env)
        elif args.command == "logout": mgr.logout(args.env)
        else: parser.print_help()
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()