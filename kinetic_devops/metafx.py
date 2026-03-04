"""
kinetic_devops/metafx.py

Metafetcher - Query Epicor Kinetic metadata and system information.

Provides methods to:
- Fetch metadata about Business Objects and services
- Query system configuration
- Retrieve customization information
- Inspect BO structures and fields
"""

# kinetic_devops/metafx.py
import os
import sys
import json
import requests
import argparse
from typing import Optional, Dict
from urllib.parse import quote
 
from .auth import KineticConfigManager

# File: kinetic_devops/metafx.py

class KineticMetafetcher:
    def __init__(self, env_nickname: Optional[str] = None, user_id: Optional[str] = None):
        self.mgr = KineticConfigManager()
        
        # 1. FIX: Unpack 3 values instead of 2
        if not env_nickname:
            self.env_name, self.user_id, self.active_co = self.mgr.prompt_for_env()
        else:
            self.env_name = env_nickname
            self.user_id = user_id
            self.active_co = None

        # 2. FIX: Use the standardized "Triple" context and singular 'company' field
        config_data = self.mgr.get_active_config(
            (self.env_name, self.user_id, self.active_co), 
            fields=("url", "token", "api_key", "company")
        )
        
        if not config_data[0]:
            sys.exit(1)

        self.config = {
            "url": config_data[0],
            "token": config_data[1],
            "api_key": config_data[2],
            "company": config_data[3]
        }

    def fetch_ui_metadata(self, app_id: str, menu_id: str):
        """Fetches UI Metadata via Ice.LIB.MetaFXSvc/GetApp."""
        base_url = self.config['url'].rstrip('/')
        service = "Ice.LIB.MetaFXSvc"
        
        # Construct the specialized MetaFX request object
        request_obj = {
            "id": app_id,
            "properties": {
                "deviceType": "Desktop",
                "layers": [],
                "applicationType": "view",
                "additionalContext": {
                    "menuId": menu_id
                }
            }
        }
        
        # Stringify and URL-encode the request parameter
        request_json = json.dumps(request_obj)
        url = f"{base_url}/api/v2/odata/{self.config['company']}/{service}/GetApp?request={quote(request_json)}"
        
        headers = self.mgr.get_auth_headers(self.config)
        # MetaFX often requires these specific serialization headers found in your UX trace
        headers.update({
            "x-epi-extension-serialization": "full-metadata",
            "Accept": "application/json"
        })

        print(f"\n--- Requesting MetaFX UI Layout ---")
        print(f"App ID: {app_id}")
        
        try:
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code != 200:
                print(f"❌ Error {response.status_code}: {response.text}")
                return

            filename = f"ui_{app_id}_{menu_id}.json"
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(response.json(), f, indent=4)
                
            print(f"✅ UI Metadata saved to: {filename}")

        except Exception as e:
            print(f"Connection Error: {e}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-e", "--env")
    parser.add_argument("-u", "--user")
    parser.add_argument("-a", "--app")
    parser.add_argument("-m", "--menu")
    args = parser.parse_args()

    fetcher = KineticMetafetcher(env_nickname=args.env, user_id=args.user)

    app_id = args.app or input("Enter App ID (e.g. Erp.UI.CustShipEntry): ").strip()
    menu_id = args.menu or input("Enter Menu ID: ").strip()

    fetcher.fetch_ui_metadata(app_id, menu_id)

if __name__ == "__main__":
    main()