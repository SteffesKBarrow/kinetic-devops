# kinetic_devops/report_service.py
"""
Report Service Wrapper

Handles uploading and extracting Report Data Definitions (RDD) and RDLs.
Inherits session management from KineticBaseClient.
"""

import sys
import json
import argparse
import base64
import os
import requests
from typing import Dict, Any, Optional

from .base_client import KineticBaseClient

class KineticReportService(KineticBaseClient):
    """
    Service for managing Epicor Kinetic Reports.
    """

    def upload_file_to_server(self, local_path: str, server_path: str, folder: int = 4) -> bool:
        """
        Uploads a file using Ice.Lib.FileTransferSvc.
        
        Args:
            local_path: Path to the local file.
            server_path: Destination path on the server (e.g., '_TempZip//Reports.zip').
            folder: Epicor SpecialFolder enum value (default 4 = UserData/Temporary).
        """
        if not os.path.exists(local_path):
            print(f"❌ Local file not found: {local_path}")
            return False

        with open(local_path, "rb") as f:
            file_bytes = f.read()
            b64_data = base64.b64encode(file_bytes).decode('utf-8')

        endpoint = f"{self.config['url'].rstrip('/')}/api/v2/odata/{self.config['company']}/Ice.Lib.FileTransferSvc/UploadFile"
        
        payload = {
            "folder": folder,
            "serverPath": server_path,
            "data": b64_data
        }

        # FileTransferSvc often requires specific headers or just standard auth
        headers = self.mgr.get_auth_headers(self.config)

        print(f"Uploading {os.path.basename(local_path)} to {server_path}...")
        resp = requests.post(endpoint, json=payload, headers=headers, timeout=300)

        if not resp.ok:
            self.log_wire("POST", endpoint, headers, payload, resp)
            print(f"❌ Upload failed: {resp.status_code} {resp.text}")
            return False
        
        print("✅ File uploaded successfully.")
        return True

    def extract_and_upload_reports_zip(self, server_path: str, report_id: str) -> bool:
        """
        Calls Ice.BO.ReportSvc/ExtractAndUploadReportsZip using the server file path.
        """
        endpoint = f"{self.config['url'].rstrip('/')}/api/v2/odata/{self.config['company']}/Ice.BO.ReportSvc/ExtractAndUploadReportsZip"
        
        # Payload references the file path on the server (uploaded via FileTransferSvc)
        payload = {
            "printProgram": report_id,
            "data": server_path
        }

        headers = self.mgr.get_auth_headers(self.config)
        
        print(f"Extracting and deploying reports from server path: {server_path}...")
        resp = requests.post(endpoint, json=payload, headers=headers, timeout=600)

        if not resp.ok:
            self.log_wire("POST", endpoint, headers, payload, resp)
            print(f"❌ Extraction failed: {resp.status_code} {resp.text}")
            return False

        print("✅ Reports extracted and uploaded successfully.")
        return True

def main():
    parser = argparse.ArgumentParser(description="Kinetic Report Service CLI")
    parser.add_argument("action", choices=['upload', 'extract', 'deploy'], help="Action to perform")
    parser.add_argument("file", help="Local path to the .zip file")
    parser.add_argument("--server-path", help="Server destination path (for upload action)", default="_TempZip//Reports.zip")
    parser.add_argument("--report-id", help="Report ID (printProgram) e.g. 'Report Path (printProgram) e.g. reports/CustomReports/PackingSlip/PackSlip,reports/CustomReports/ShippingLabels/ShipLabl'")
    parser.add_argument("--env", help="Environment Nickname")
    parser.add_argument("--user", help="Specific User ID")
    parser.add_argument("--debug", action="store_true")
    
    args = parser.parse_args()

    try:
        service = KineticReportService(args.env, args.user, debug=args.debug)

        if args.action == 'upload':
            service.upload_file_to_server(args.file, args.server_path)
        elif args.action == 'extract':
            if not args.report_id:
                print("❌ Error: --report-id is required for extraction.")
                sys.exit(1)
            service.extract_and_upload_reports_zip(args.server_path, args.report_id)
        elif args.action == 'deploy':
            if not args.report_id:
                print("❌ Error: --report-id is required for deployment.")
                sys.exit(1)
            if service.upload_file_to_server(args.file, args.server_path):
                service.extract_and_upload_reports_zip(args.server_path, args.report_id)

    except Exception as e:
        print(f"❌ Error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()