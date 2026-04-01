"""
kinetic_devops/export_all.py

Core export orchestration for Kinetic DevOps workflows.

Supports:
- EFx library export mode (ExportAllTheThings-compatible)
- Native endpoint export mode (no ExportAllTheThings dependency)
- Auto mode (prefer EFx export library; fall back to native)
"""

import argparse
import base64
import binascii
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qsl

import requests

from .efx import KineticEFxService
from .base_client import KineticBaseClient

DEFAULT_EATT_LIBRARY = "ExportAllTheThings"
DEFAULT_EXPORT_FUNCTIONS = [
    "ExportAllCustomBAQs",
    "ExportAllFunctionLibraries",
    "ExportAllUDCodes",
    "ExportDataDirectivesByTable",
    "ExportDirectivesByGroups",
    "ExportMethodDirectivesByService",
    "ExportAllKineticCustomLayers",
    "ExportAllKineticSystemLayers",
]

DEFAULT_NATIVE_EXPORT_PLAN = [
    {
        "id": "baq_list",
        "method": "POST",
        "endpoint": "/api/v2/odata/{company}/Ice.BO.BAQDesignerSvc/GetList",
        "body": {
            "whereClause": "SystemFlag=false",
            "pageSize": 0,
            "absolutePage": 0,
        },
        "output": "baq_list.json",
    },
    {
        "id": "efx_library_list",
        "method": "POST",
        "endpoint": "/api/v2/odata/{company}/Ice.BO.EfxLibraryDesignerSvc/GetLibraryList",
        "body": {
            "searchOptions": {
                "kind": 1,
                "startsWith": "",
                "rollOutMode": 2,
                "status": 2,
            }
        },
        "output": "efx_library_list.json",
    },
    {
        "id": "ud_codes",
        "method": "POST",
        "endpoint": "/api/v2/odata/{company}/Ice.BO.UserCodesSvc/GetRows",
        "body": {
            "whereClauseUDCodeType": "",
            "whereClauseUDCodes": "",
            "pageSize": 0,
            "absolutePage": 0,
        },
        "output": "ud_codes.json",
    },
    {
        "id": "method_directives",
        "method": "POST",
        "endpoint": "/api/v2/odata/{company}/Ice.BO.BpMethodSvc/GetList",
        "body": {
            "whereClause": "Source = 'BO' AND ObjectNS <> ''",
            "pageSize": 0,
            "absolutePage": 0,
        },
        "output": "method_directives.json",
    },
    {
        "id": "data_directives",
        "method": "POST",
        "endpoint": "/api/v2/odata/{company}/Ice.BO.BpMethodSvc/GetList",
        "body": {
            "whereClause": "Source = 'DB'",
            "pageSize": 0,
            "absolutePage": 0,
        },
        "output": "data_directives.json",
    },
    {
        "id": "directive_groups",
        "method": "POST",
        "endpoint": "/api/v2/odata/{company}/Ice.BO.BpMethodSvc/GetDirectiveGroups",
        "body": {
            "source": "BO,DB"
        },
        "output": "directive_groups.json",
    },
    {
        "id": "metafx_applications",
        "method": "POST",
        "endpoint": "/api/v2/odata/{company}/Ice.LIB.MetaFXSvc/GetApplications",
        "body": {
            "request": {
                "Type": "view",
                "SubType": "",
                "SearchText": "",
                "IncludeAllLayers": True,
                "IncludePersLayers": False,
            }
        },
        "output": "metafx_applications.json",
    },
]


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned or "artifact"


def _walk_values(node: Any) -> Iterable[Any]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, value
            yield from _walk_values(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_values(item)


def _collect_function_ids_from_payload(payload: Any) -> List[str]:
    discovered: List[str] = []
    seen = set()

    for key, value in _walk_values(payload):
        if isinstance(key, str) and key.lower() == "functionid" and isinstance(value, str):
            function_id = value.strip()
            if function_id and function_id not in seen:
                seen.add(function_id)
                discovered.append(function_id)

    return discovered


def _is_probable_base64(value: str) -> bool:
    sample = value.strip()
    if not sample or len(sample) < 8:
        return False
    if len(sample) % 4 != 0:
        return False
    return re.fullmatch(r"[A-Za-z0-9+/=\\r\\n]+", sample) is not None


def _extract_file_payload(result: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[bytes], Optional[str]]:
    """
    Return (payload_key, payload_type, payload_bytes, payload_text).

    payload_type is one of: base64, text
    """
    priority_keys = ["ZipBase64", "File", "Content"]

    # First pass: direct keys with original case
    for key in priority_keys:
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            if key == "ZipBase64" or _is_probable_base64(value):
                try:
                    return key, "base64", base64.b64decode(value), None
                except (binascii.Error, ValueError):
                    pass
            return key, "text", None, value

    # Second pass: recursive key search (case-insensitive)
    for key, value in _walk_values(result):
        if not isinstance(key, str):
            continue
        if key.lower() not in {"zipbase64", "file", "content"}:
            continue
        if not isinstance(value, str) or not value.strip():
            continue

        if key.lower() == "zipbase64" or _is_probable_base64(value):
            try:
                return key, "base64", base64.b64decode(value), None
            except (binascii.Error, ValueError):
                pass

        return key, "text", None, value

    return None, None, None, None


def _deep_template(value: Any, mapping: Dict[str, str]) -> Any:
    if isinstance(value, str):
        out = value
        for key, replacement in mapping.items():
            out = out.replace("{" + key + "}", replacement)
        return out
    if isinstance(value, list):
        return [_deep_template(item, mapping) for item in value]
    if isinstance(value, dict):
        return {k: _deep_template(v, mapping) for k, v in value.items()}
    return value


def _parse_query_params(raw: str) -> Dict[str, str]:
    text = (raw or "").lstrip("?").strip()
    if not text:
        return {}
    return {k: v for k, v in parse_qsl(text, keep_blank_values=True)}


class KineticExportAllService(KineticEFxService):
    """Service that discovers and executes ExportAllTheThings export functions."""

    def discover_export_functions(
        self,
        library: str = DEFAULT_EATT_LIBRARY,
        company: str = "",
        fallback_to_defaults: bool = True,
    ) -> List[str]:
        target_co = company if company else self.config["company"]
        endpoint = (
            f"{self.config['url'].rstrip('/')}/api/v2/odata/{target_co}/"
            "Ice.BO.EfxLibraryDesignerSvc/GetLibrary"
        )

        headers = self.mgr.get_auth_headers(self.config)
        payload = {"libraryID": library}

        try:
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=120)
            if not resp.ok:
                self.log_wire("POST", endpoint, headers, body=payload, resp=resp)
                resp.raise_for_status()
            data = resp.json() or {}
            discovered = [fn for fn in _collect_function_ids_from_payload(data) if fn.startswith("Export")]
            if discovered:
                return sorted(set(discovered))
        except Exception:
            # Fall back to known defaults for resilient CLI behavior.
            pass

        return list(DEFAULT_EXPORT_FUNCTIONS) if fallback_to_defaults else []

    def _request_native(
        self,
        method: str,
        endpoint: str,
        params: str = "",
        body: Optional[Dict[str, Any]] = None,
        company: str = "",
    ) -> requests.Response:
        target_co = company if company else self.config["company"]
        mapping = {
            "company": target_co,
            "base_url": self.config["url"].rstrip("/"),
        }
        rendered_endpoint = _deep_template(endpoint, mapping)
        if rendered_endpoint.startswith("http://") or rendered_endpoint.startswith("https://"):
            url = rendered_endpoint
        else:
            url = f"{self.config['url'].rstrip('/')}/{rendered_endpoint.lstrip('/')}"

        headers = self.mgr.get_auth_headers(self.config)
        query = _parse_query_params(params)
        payload = _deep_template(body or {}, mapping)

        response = requests.request(
            method=method.upper(),
            url=url,
            params=query,
            json=payload if method.upper() != "GET" else None,
            headers=headers,
            timeout=180,
        )

        if not response.ok:
            self.log_wire(method.upper(), url, headers, body=payload, resp=response)
            response.raise_for_status()

        return response

    def export_native_one(
        self,
        out_dir: str,
        endpoint: str,
        method: str = "GET",
        params: str = "",
        body: Optional[Dict[str, Any]] = None,
        company: str = "",
        output_name: str = "native_export",
    ) -> Dict[str, Any]:
        os.makedirs(out_dir, exist_ok=True)
        response = self._request_native(
            method=method,
            endpoint=endpoint,
            params=params,
            body=body,
            company=company,
        )

        content_type = (response.headers.get("content-type") or "").lower()
        base_name = _safe_name(output_name)
        output_file = ""

        if "application/json" in content_type:
            payload = response.json()
            output_file = os.path.join(out_dir, f"{base_name}.json")
            output_file = self.resolve_output_path(output_file, conflict_resolution="timestamp")
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            payload_type = "json"
        else:
            text_preview = None
            payload_type = "binary"
            try:
                text_preview = response.text
                if text_preview and not response.content.startswith(b"PK"):
                    output_file = os.path.join(out_dir, f"{base_name}.txt")
                    output_file = self.resolve_output_path(output_file, conflict_resolution="timestamp")
                    with open(output_file, "w", encoding="utf-8") as f:
                        f.write(text_preview)
                    payload_type = "text"
                else:
                    output_file = os.path.join(out_dir, f"{base_name}.bin")
                    output_file = self.resolve_output_path(output_file, conflict_resolution="timestamp")
                    with open(output_file, "wb") as f:
                        f.write(response.content)
            except Exception:
                output_file = os.path.join(out_dir, f"{base_name}.bin")
                output_file = self.resolve_output_path(output_file, conflict_resolution="timestamp")
                with open(output_file, "wb") as f:
                    f.write(response.content)

        return {
            "id": output_name,
            "success": True,
            "method": method.upper(),
            "endpoint": endpoint,
            "output_file": output_file,
            "payload_type": payload_type,
            "status_code": response.status_code,
        }

    def export_native_all(
        self,
        out_dir: str,
        plan: List[Dict[str, Any]],
        company: str = "",
        continue_on_error: bool = True,
    ) -> Dict[str, Any]:
        os.makedirs(out_dir, exist_ok=True)
        results: List[Dict[str, Any]] = []
        failures = 0

        for item in plan:
            item_id = str(item.get("id", "native_item"))
            try:
                result = self.export_native_one(
                    out_dir=out_dir,
                    endpoint=str(item.get("endpoint", "")),
                    method=str(item.get("method", "GET")),
                    params=str(item.get("params", "")),
                    body=item.get("body") if isinstance(item.get("body"), dict) else {},
                    company=company,
                    output_name=str(item.get("output", item_id)).rsplit(".", 1)[0],
                )
                results.append(result)
            except Exception as exc:
                failures += 1
                results.append(
                    {
                        "id": item_id,
                        "success": False,
                        "method": str(item.get("method", "GET")).upper(),
                        "endpoint": str(item.get("endpoint", "")),
                        "output_file": "",
                        "error": str(exc),
                    }
                )
                if not continue_on_error:
                    break

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        manifest_path = os.path.join(out_dir, f"native_export_manifest_{timestamp}.json")
        manifest = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": "native",
            "company": company or self.config.get("company", ""),
            "total_items": len(plan),
            "failed_items": failures,
            "successful_items": len(results) - failures,
            "results": results,
        }

        manifest_path = self.resolve_output_path(manifest_path, conflict_resolution="timestamp")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        return {
            "success": failures == 0,
            "manifest": manifest_path,
            "results": results,
            "summary": manifest,
        }

    def export_one(
        self,
        function_id: str,
        out_dir: str,
        library: str = DEFAULT_EATT_LIBRARY,
        company: str = "",
        input_data: Optional[Dict[str, Any]] = None,
        extension: str = "zip",
    ) -> Dict[str, Any]:
        os.makedirs(out_dir, exist_ok=True)

        result = self.run_function(
            library=library,
            function=function_id,
            input_data=input_data or {},
            company=company,
        )

        payload_key, payload_type, payload_bytes, payload_text = _extract_file_payload(result)
        if not payload_key:
            return {
                "function_id": function_id,
                "success": False,
                "output_file": "",
                "payload_key": "",
                "error": "No file-like payload found in EFx response.",
                "response": result,
            }

        out_name = f"{_safe_name(function_id)}.{extension if payload_type == 'base64' else 'txt'}"
        output_path = os.path.join(out_dir, out_name)
        output_path = self.resolve_output_path(output_path, conflict_resolution="timestamp")

        if payload_type == "base64" and payload_bytes is not None:
            with open(output_path, "wb") as f:
                f.write(payload_bytes)
        else:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(payload_text or "")

        return {
            "function_id": function_id,
            "success": True,
            "output_file": output_path,
            "payload_key": payload_key,
            "payload_type": payload_type,
            "response": result,
        }

    def export_all(
        self,
        out_dir: str,
        library: str = DEFAULT_EATT_LIBRARY,
        company: str = "",
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
        input_data: Optional[Dict[str, Any]] = None,
        continue_on_error: bool = True,
        extension: str = "zip",
    ) -> Dict[str, Any]:
        functions = self.discover_export_functions(library=library, company=company)

        if include:
            allowed = {name.strip() for name in include if name.strip()}
            functions = [fn for fn in functions if fn in allowed]

        if exclude:
            denied = {name.strip() for name in exclude if name.strip()}
            functions = [fn for fn in functions if fn not in denied]

        results: List[Dict[str, Any]] = []
        failures = 0

        for function_id in functions:
            try:
                item = self.export_one(
                    function_id=function_id,
                    out_dir=out_dir,
                    library=library,
                    company=company,
                    input_data=input_data,
                    extension=extension,
                )
                if not item.get("success", False):
                    failures += 1
                    if not continue_on_error:
                        results.append(item)
                        break
                results.append(item)
            except Exception as exc:
                failures += 1
                error_item = {
                    "function_id": function_id,
                    "success": False,
                    "output_file": "",
                    "error": str(exc),
                }
                results.append(error_item)
                if not continue_on_error:
                    break

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        manifest_path = os.path.join(out_dir, f"export_manifest_{timestamp}.json")
        manifest = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "library": library,
            "company": company or self.config.get("company", ""),
            "total_functions": len(functions),
            "failed_functions": failures,
            "successful_functions": len(results) - failures,
            "results": [
                {
                    "function_id": item.get("function_id", ""),
                    "success": item.get("success", False),
                    "output_file": item.get("output_file", ""),
                    "payload_key": item.get("payload_key", ""),
                    "payload_type": item.get("payload_type", ""),
                    "error": item.get("error", ""),
                }
                for item in results
            ],
        }

        os.makedirs(out_dir, exist_ok=True)
        manifest_path = self.resolve_output_path(manifest_path, conflict_resolution="timestamp")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        return {
            "success": failures == 0,
            "manifest": manifest_path,
            "results": results,
            "summary": manifest,
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export everything from Kinetic (with or without ExportAllTheThings)"
    )
    parser.add_argument("--mode", choices=["auto", "eatt", "native"], default="auto")
    parser.add_argument("--env", help="Environment nickname")
    parser.add_argument("--user", help="User ID for session")
    parser.add_argument("--co", help="Company override", default="")
    parser.add_argument("--library", default=DEFAULT_EATT_LIBRARY, help="EFx library name")
    parser.add_argument("--out-dir", default=os.path.join("exports", "ExportAllTheThings"), help="Output directory")
    parser.add_argument("--list", action="store_true", help="List discovered export functions only")
    parser.add_argument("--function", default="", help="Run only one export function")
    parser.add_argument("--include", nargs="*", help="Optional include list for bulk export")
    parser.add_argument("--exclude", nargs="*", help="Optional exclude list for bulk export")
    parser.add_argument("--input", default="{}", help="JSON payload passed to export functions")
    parser.add_argument("--extension", default="zip", help="Artifact extension for base64 payloads")
    parser.add_argument("--stop-on-error", action="store_true", help="Stop bulk export on first error")
    parser.add_argument("--native-plan", default="", help="Path to JSON file containing native endpoint plan list")
    parser.add_argument("--native-endpoint", default="", help="Single native endpoint to export (relative or absolute URL)")
    parser.add_argument("--native-method", default="GET", help="HTTP method for --native-endpoint")
    parser.add_argument("--native-params", default="", help="Query string for --native-endpoint")
    parser.add_argument("--native-body", default="{}", help="JSON body for --native-endpoint")
    parser.add_argument("--native-name", default="native_export", help="Output base name for --native-endpoint")
    KineticBaseClient.add_file_resolution_args(parser)

    args = parser.parse_args()

    try:
        input_data = json.loads(args.input)
        if not isinstance(input_data, dict):
            raise ValueError("--input must parse to a JSON object")
    except Exception as exc:
        print(f"Error: invalid --input JSON: {exc}")
        sys.exit(2)

    try:
        native_body = json.loads(args.native_body)
        if not isinstance(native_body, dict):
            raise ValueError("--native-body must parse to a JSON object")
    except Exception as exc:
        print(f"Error: invalid --native-body JSON: {exc}")
        sys.exit(2)

    service = KineticExportAllService(args.env, args.user, debug=False)
    service.configure_file_resolution_from_args(args)

    effective_mode = args.mode
    discovered_functions: List[str] = []
    if args.mode in {"auto", "eatt"}:
        discovered_functions = service.discover_export_functions(
            library=args.library,
            company=args.co,
            fallback_to_defaults=(args.mode == "eatt"),
        )
        if args.mode == "auto":
            effective_mode = "eatt" if discovered_functions else "native"

    if effective_mode == "eatt":
        if args.list:
            print(json.dumps({"mode": "eatt", "library": args.library, "functions": discovered_functions}, indent=2))
            return

        if args.function:
            result = service.export_one(
                function_id=args.function,
                out_dir=args.out_dir,
                library=args.library,
                company=args.co,
                input_data=input_data,
                extension=args.extension,
            )
            print(json.dumps(result, indent=2, ensure_ascii=False))
            sys.exit(0 if result.get("success") else 1)

        outcome = service.export_all(
            out_dir=args.out_dir,
            library=args.library,
            company=args.co,
            include=args.include,
            exclude=args.exclude,
            input_data=input_data,
            continue_on_error=not args.stop_on_error,
            extension=args.extension,
        )
    else:
        if args.list:
            print(json.dumps({
                "mode": "native",
                "default_plan_ids": [item.get("id", "") for item in DEFAULT_NATIVE_EXPORT_PLAN],
            }, indent=2))
            return

        if args.native_endpoint:
            single = service.export_native_one(
                out_dir=args.out_dir,
                endpoint=args.native_endpoint,
                method=args.native_method,
                params=args.native_params,
                body=native_body,
                company=args.co,
                output_name=args.native_name,
            )
            print(json.dumps(single, indent=2, ensure_ascii=False))
            sys.exit(0 if single.get("success") else 1)

        if args.native_plan:
            with open(args.native_plan, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, list):
                print("Error: --native-plan JSON must be a list of request objects")
                sys.exit(2)
            plan = loaded
        else:
            plan = DEFAULT_NATIVE_EXPORT_PLAN

        outcome = service.export_native_all(
            out_dir=args.out_dir,
            plan=plan,
            company=args.co,
            continue_on_error=not args.stop_on_error,
        )

    print(json.dumps({
        "mode": effective_mode,
        "success": outcome.get("success", False),
        "manifest": outcome.get("manifest", ""),
        "summary": outcome.get("summary", {}),
    }, indent=2, ensure_ascii=False))
    sys.exit(0 if outcome.get("success", False) else 1)


if __name__ == "__main__":
    main()
