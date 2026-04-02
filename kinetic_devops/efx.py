import argparse
import json
import base64
import sys
import os
import requests
from .base_client import KineticBaseClient

class KineticEFxService(KineticBaseClient):
    """
    Service for executing Epicor Functions (EFx) directly.
    Useful for bypassing UI/App constraints or automating function calls.
    """
    
    def run_function(self, library: str, function: str, input_data: dict = None, company: str = "") -> dict:
        """
        Executes an Epicor Function via REST API.
        """
        target_co = company if company else self.config['company']
        # Construct the EFx endpoint: /api/v2/efx/{company}/{library}/{function}
        url = f"{self.config['url'].rstrip('/')}/api/v2/efx/{target_co}/{library}/{function}"
        
        headers = self.mgr.get_auth_headers(self.config)
        
        # EFx calls are POST requests
        response = requests.post(url, json=input_data or {}, headers=headers, timeout=120)
        
        if not response.ok:
            self.log_wire("POST", url, headers, body=input_data, resp=response)
            response.raise_for_status()
            
        return response.json()

def main():
    parser = argparse.ArgumentParser(description="Execute Epicor Functions (EFx) and handle file outputs.")
    parser.add_argument("library", help="Library ID (e.g., ExportAllTheThings)")
    parser.add_argument("function", help="Function ID (e.g., ExportAllKineticCustomizationLayers)")
    parser.add_argument("--env", help="Environment Nickname")
    parser.add_argument("--user", help="Specific User ID (Session)")
    parser.add_argument("--co", help="Company Override")
    parser.add_argument("--input", help="Input JSON string (optional)", default="{}")
    parser.add_argument("--out", help="Output filename (for file/zip responses)")
    parser.add_argument("--decode", action="store_true", help="Decode the output as Base64 (auto-detected for ZipBase64)")
    parser.add_argument("--debug", action="store_true")
    KineticBaseClient.add_file_resolution_args(parser)
    
    args = parser.parse_args()

    try:
        service = KineticEFxService(args.env, args.user, debug=args.debug)
        service.configure_file_resolution_from_args(args)
        
        try:
            input_data = json.loads(args.input)
        except json.JSONDecodeError:
            print("❌ Error: Invalid JSON provided for --input")
            sys.exit(1)
            
        print(f"🚀 Executing {args.library}.{args.function}...")
        result = service.run_function(args.library, args.function, input_data, args.co)
        
        # Check for common file output keys
        output_content = result.get("ZipBase64") or result.get("File") or result.get("Content")
        
        if args.out and output_content:
            # Auto-decode if it looks like Base64 or if requested
            if args.decode or "ZipBase64" in result:
                file_data = base64.b64decode(output_content)
                mode = "wb"
            else:
                file_data = output_content
                mode = "w"
                
            args.out = service.resolve_output_path(args.out, conflict_resolution="timestamp")
            with open(args.out, mode) as f:
                f.write(file_data)
            print(f"✅ Output saved to {args.out}")
        else:
            print(json.dumps(result, indent=2))

    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()