"""
kinetic_devops/tax_service.py

TaxService - Manage Epicor Kinetic tax configurations.

Provides high-level methods to:
- Fetch tax service configurations
- Update tax configurations
- Clear/delete tax records
- List inactive tax configurations
"""

import json
from typing import List, Dict, Any, Optional
import requests

from .KineticCore import KineticCore


class TaxService(KineticCore):
    """
    Service for managing Epicor Kinetic tax configurations.
    
    Responsibilities:
    - Fetch and parse tax service configurations
    - Build and execute UpdateExt calls for deletions/updates
    - Handle company-scoped operations
    """
    
    def __init__(self, base_url: str, token: str, api_key: str, debug: bool = False):
        """
        Initialize TaxService.
        
        Args:
            base_url: Base URL of Kinetic instance (e.g., https://example.epicorsaas.com/SaaS681/)
            token: Bearer token for authentication
            api_key: Scoped API key
            debug: Enable debug logging
        """
        super().__init__(debug=debug)
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.api_key = api_key
    
    def _build_headers(self, company: str = "") -> Dict[str, str]:
        """Build standard headers for tax service API calls."""
        headers = self.build_headers(self.token, self.api_key, company)
        headers['accept'] = 'application/json'
        return headers
    
    def get_tax_configs(self, company: str) -> Optional[List[Dict[str, Any]]]:
        """
        Fetch all tax service configurations for a company.
        
        Args:
            company: Company ID (e.g., "ACME-LABS")
        
        Returns:
            List of tax config records, or None on failure
        """
        try:
            url = f"{self.base_url}/api/v2/odata/{company}/Erp.BO.TaxSvcConfigSvc/TaxSvcConfigs"
            headers = self._build_headers(company)
            
            self.log_wire("GET", url, headers)
            
            resp = requests.get(url, headers=headers, timeout=20)
            resp.raise_for_status()
            
            data = resp.json()
            self.log_wire("GET", url, headers, resp=resp)
            
            records = data.get('value', [])
            self.debug_log(f"Fetched {len(records)} tax config record(s) for {company}")
            
            return records
        
        except requests.exceptions.RequestException as e:
            self.debug_log(f"Failed to fetch tax configs for {company}: {e}")
            return None
        except Exception as e:
            self.debug_log(f"Unexpected error fetching tax configs: {e}")
            return None
    
    def get_inactive_configs(self, company: str) -> Optional[List[Dict[str, Any]]]:
        """
        Fetch only inactive (TaxConnectEnabled=false) tax configurations.
        
        Args:
            company: Company ID
        
        Returns:
            List of inactive tax config records, or None on failure
        """
        records = self.get_tax_configs(company)
        
        if records is None:
            return None
        
        # Filter for inactive records
        inactive = [
            r for r in records
            if not r.get('TaxConnectEnabled', False)
        ]
        
        self.debug_log(f"Found {len(inactive)} inactive tax config(s) for {company}")
        
        return inactive
    
    def delete_configs(
        self, 
        company: str, 
        records: List[Dict[str, Any]],
        continue_on_error: bool = True,
        rollback_on_child_error: bool = True
    ) -> bool:
        """
        Delete tax configuration records via UpdateExt.
        
        Args:
            company: Company ID
            records: List of records to delete (will set RowMod="D" for each)
            continue_on_error: Continue processing if errors occur
            rollback_on_child_error: Rollback parent on child errors
        
        Returns:
            True if successful, False otherwise
        """
        if not records:
            self.debug_log(f"No records to delete for {company}")
            return True
        
        try:
            # Mark all records for deletion
            deletion_records = [
                {**record, "RowMod": "D"}
                for record in records
            ]
            
            url = f"{self.base_url}/api/v2/odata/{company}/Erp.BO.TaxSvcConfigSvc/UpdateExt"
            headers = self._build_headers(company)
            headers['Content-Type'] = 'application/json'
            
            payload = {
                "ds": {
                    "TaxSvcConfig": deletion_records
                },
                "continueProcessingOnError": continue_on_error,
                "rollbackParentOnChildError": rollback_on_child_error
            }
            
            self.log_wire("POST", url, headers, json.dumps(payload)[:200])
            
            resp = requests.post(url, headers=headers, json=payload, timeout=20)
            resp.raise_for_status()
            
            data = resp.json()
            self.log_wire("POST", url, headers, resp=resp)
            
            if data.get('errorsOccurred'):
                self.debug_log(f"UpdateExt returned errors for {company}: {data}")
                return False
            
            self.debug_log(f"Successfully deleted {len(deletion_records)} record(s) for {company}")
            return True
        
        except requests.exceptions.RequestException as e:
            self.debug_log(f"UpdateExt request failed for {company}: {e}")
            return False
        except Exception as e:
            self.debug_log(f"Unexpected error in delete_configs: {e}")
            return False
    
    def clear_all_configs(self, company: str) -> bool:
        """
        Fetch all tax configs and delete them.
        
        Args:
            company: Company ID
        
        Returns:
            True if successful, False otherwise
        """
        records = self.get_tax_configs(company)
        
        if records is None:
            return False
        
        if not records:
            self.debug_log(f"No tax configs to clear for {company}")
            return True
        
        return self.delete_configs(company, records)
    
    def clear_inactive_configs(self, company: str) -> bool:
        """
        Fetch inactive tax configs and delete them.
        
        Args:
            company: Company ID
        
        Returns:
            True if successful, False otherwise
        """
        records = self.get_inactive_configs(company)
        
        if records is None:
            return False
        
        if not records:
            self.debug_log(f"No inactive tax configs to clear for {company}")
            return True
        
        return self.delete_configs(company, records)
