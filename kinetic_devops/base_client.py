"""
kinetic_devops/base_client.py

KineticBaseClient - Session management and authenticated API requests.

Inherits security infrastructure and wire logging from KineticCore.
Provides:
- Interactive environment/user selection
- Automatic token management via keyring
- Header generation with API key and company context
- Generic request execution for custom endpoints
"""

# File: kinetic_devops/base_client.py
import requests
import sys
from typing import Optional, Dict, Any
from urllib.parse import urlparse
from .auth import KineticConfigManager
from .KineticCore import KineticCore  # Import your new centralized brain [cite: 2]

class KineticBaseClient(KineticCore):
    """
    The General Infrastructure Layer.
    Inherits Header Generation and Wire Logging from KineticCore. [cite: 2]
    """
    def __init__(self, env_nickname: Optional[str] = None, user_id: Optional[str] = None, company_id: Optional[str] = None, debug: bool = False):
        # Initialize the Core with debug preference [cite: 2]
        super().__init__(debug=debug)
        self.mgr = KineticConfigManager()
        
        # Standardized environment/user selection 
        if not env_nickname:
            self.env_name, self.user_id, self.active_co = self.mgr.prompt_for_env()
        else:
            self.env_name = env_nickname
            self.user_id = user_id
            self.active_co = company_id

        # Authenticate and get the full config [cite: 121]
        # We pass self.active_co to ensure we don't lose the selection from prompt_for_env
        config_data = self.mgr.get_active_config((self.env_name, self.user_id, self.active_co),
                                                fields=("url", "token", "api_key", "company", "nickname", "user_id"))
        
        if not config_data[0]: # Check if URL exists [cite: 121]
            print(f"❌ Failed to initialize session for {self.user_id}@{self.env_name}")
            sys.exit(1)
            
        self.config = {
            "url": config_data[0],
            "token": config_data[1],
            "api_key": config_data[2],
            "company": config_data[3],
            "nickname": config_data[4],
            "user_id": config_data[5],
        }

    def _build_runtime_substitutions(self, plant: str = "") -> Dict[str, str]:
        """Build runtime substitutions for redacted/template dump placeholders."""
        parsed = urlparse(self.config["url"])
        instance = parsed.path.strip("/")
        mapping = {
            "HOSTNAME": parsed.hostname or "",
            "hostname": parsed.hostname or "",
            "INSTANCE": instance,
            "COMPANY": self.config.get("company", ""),
            "Company": self.config.get("company", ""),
            "COMPANYID": self.config.get("company", ""),
            "USER_ID": self.config.get("user_id", ""),
            "USERID": self.config.get("user_id", ""),
            "PLANT": plant,
        }
        return mapping

    def execute_request(self, method: str, url: str, payload: Any = None, 
                        params: Optional[str] = None, extra_headers: Optional[Dict] = None) -> Dict:
        # Use centralized header builder from KineticCore
        headers = self.build_headers(
            token=self.config['token'],
            api_key=self.config['api_key'],
            company=self.config['company']
        )
        
        if extra_headers:
            headers.update(extra_headers)
        
        try:
            response = requests.request(
                method, url, json=payload, params=params, headers=headers, timeout=60
            )
            
            # Use centralized wire logger from KineticCore [cite: 6, 7]
            # This replaces the old _log_wire_details [cite: 121]
            self.log_wire(method, url, headers, body=payload, resp=response)
            
            # Update session 'last used' timestamp [cite: 28, 126]
            if response.status_code not in (401, 403, 500, 503):
                self.mgr.touch_from_headers(response.request.headers)

            response.raise_for_status()
            return response.json()

        except Exception:
            # Re-raise to let specific tool (BAQ/Meta) handle it [cite: 128]
            raise
