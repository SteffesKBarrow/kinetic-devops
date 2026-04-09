"""
kinetic_devops/solutions.py

Solution Workbench backup and recreation support using Ice.BO.ExportPackageSvc.

Goal:
- Back up a solution definition from one environment
- Recreate the solution definition in another environment
- Build it there later, without installing a package artifact
"""

import argparse
import base64
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

if __package__:
    from .base_client import KineticBaseClient
else:
    from kinetic_devops.base_client import KineticBaseClient


SKIP_RECREATE_TABLES = {
    "EPHistory",
    "EPSolutionDetailDisplay",
    "EPSolutionTracker",
    "EPSolutionTrackerDetail",
}

# Default targeted hydration scope for high-value migration elements.
DEFAULT_HYDRATE_TABLES = [
    "BPDirective",
    "BPDirectiveGroup",
    "MethodDirective",
    "DataDirective",
    "Menu",
    "XXXDef",
    "MetaUI",
]

BUILD_SERVER_ARTIFACT_FIELDS = [
    ("solutionFileNameServer", "solutionFileName", "package"),
    ("solutionBuildLogFileNameServer", "solutionBuildLogFileName", "build_log"),
    ("solutionHashFileNameServer", "solutionHashFileName", "hash"),
]

FAIL_PATTERNS = [
    re.compile(r"\berror\b", re.IGNORECASE),
    re.compile(r"\bexception\b", re.IGNORECASE),
    re.compile(r"\bfailed\b", re.IGNORECASE),
    re.compile(r"\bfatal\b", re.IGNORECASE),
]

WARN_PATTERNS = [
    re.compile(r"\bwarning\b", re.IGNORECASE),
]

INSTALL_FAIL_PATTERNS = [
    re.compile(r"\berror\b", re.IGNORECASE),
    re.compile(r"\bfailed\b", re.IGNORECASE),
    re.compile(r"\bexception\b", re.IGNORECASE),
]

INSTALL_WARN_PATTERNS = [
    re.compile(r"\bwarning\b", re.IGNORECASE),
    re.compile(r"\bcancel(ed)?\b", re.IGNORECASE),
    re.compile(r"\balready exists\b", re.IGNORECASE),
    re.compile(r"\bregenerate data model\b", re.IGNORECASE),
    re.compile(r"\bmay need\b", re.IGNORECASE),
]

MESSAGE_KEYS = {"message", "validationmsg", "logrecords"}

IGNORE_LINE_PATTERNS = [
    re.compile(r"\b0\s+errors?\b", re.IGNORECASE),
]


def _export_package_url(base_url: str, company: str, method_name: str) -> str:
    return f"{base_url.rstrip('/')}/api/v2/odata/{company}/Ice.BO.ExportPackageSvc/{method_name}"


def _replace_solution_ids(value: Any, source_id: str, target_id: str) -> Any:
    if isinstance(value, dict):
        return {key: _replace_solution_ids(item, source_id, target_id) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_solution_ids(item, source_id, target_id) for item in value]
    if isinstance(value, str) and value == source_id:
        return target_id
    return value


def _sanitize_row(row: Dict[str, Any], source_id: str, target_id: str, row_mod: str = "A") -> Dict[str, Any]:
    cleaned = {
        key: value
        for key, value in row.items()
        if key not in {"SysRowID", "SysRevID", "BitFlag"}
    }
    cleaned = _replace_solution_ids(cleaned, source_id, target_id)
    cleaned["RowMod"] = row_mod
    return cleaned


def _sanitize_tableset_for_recreate(
    source_tableset: Dict[str, Any],
    source_solution_id: str,
    target_solution_id: str,
) -> Dict[str, Any]:
    sanitized: Dict[str, Any] = {}

    for table_name, rows in source_tableset.items():
        if table_name in SKIP_RECREATE_TABLES:
            sanitized[table_name] = []
            continue
        if not isinstance(rows, list):
            continue

        if table_name == "ExportPackage":
            sanitized[table_name] = [
                _sanitize_row(row, source_solution_id, target_solution_id, row_mod="A")
                for row in rows[:1]
            ]
            continue

        sanitized[table_name] = [
            _sanitize_row(row, source_solution_id, target_solution_id, row_mod="A")
            for row in rows
        ]

    return sanitized


def _extract_solution_table_names(tableset: Dict[str, Any]) -> List[str]:
    table_names: Set[str] = set()
    for detail_table in ("EPSolutionDetail", "EPSolutionPackage"):
        for row in tableset.get(detail_table, []) or []:
            table_name = str(row.get("TableName", "")).strip()
            if not table_name or table_name.lower() == "undefined":
                continue
            table_names.add(table_name)
    return sorted(table_names)


def _normalize_table_name(name: str) -> str:
    clean = str(name or "").strip()
    if clean.lower().startswith("ice."):
        clean = clean[4:]
    return clean.lower()


def _resolve_hydrate_tables(available_table_names: List[str], requested_tables: List[str]) -> List[str]:
    requested_normalized = {_normalize_table_name(item) for item in requested_tables if str(item).strip()}
    resolved: List[str] = []
    for table_name in available_table_names:
        if _normalize_table_name(table_name) in requested_normalized:
            resolved.append(table_name)
    return sorted(set(resolved))


def _extract_dynamic_rows_payload(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, dict):
        return payload.get("returnObj") if isinstance(payload.get("returnObj"), dict) else payload
    return {}


def _sanitize_dynamic_payload_for_add(
    payload: Dict[str, Any],
    source_solution_id: str,
    target_solution_id: str,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for table_name, rows in payload.items():
        if not isinstance(rows, list):
            continue
        result[table_name] = [
            _sanitize_row(row, source_solution_id, target_solution_id, row_mod="A")
            for row in rows
        ]
    return result


def _line_has_pattern(line: str, patterns: List[re.Pattern]) -> bool:
    return any(pattern.search(line) for pattern in patterns)


def _collect_text_findings(path: str) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    if not path or not os.path.isfile(path):
        return findings

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for idx, line in enumerate(f, start=1):
            text = line.strip()
            if not text:
                continue
            if _line_has_pattern(text, IGNORE_LINE_PATTERNS):
                continue
            if _line_has_pattern(text, FAIL_PATTERNS):
                findings.append({"severity": "error", "file": path, "line": idx, "text": text})
                continue
            if _line_has_pattern(text, WARN_PATTERNS):
                findings.append({"severity": "warning", "file": path, "line": idx, "text": text})
    return findings


def _extract_named_messages(payload: Any) -> List[str]:
    messages: List[str] = []

    def _walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).strip().lower() in MESSAGE_KEYS:
                    if isinstance(item, str) and item.strip():
                        messages.append(item.strip())
                    elif isinstance(item, (list, dict)):
                        _walk(item)
                else:
                    _walk(item)
            return

        if isinstance(value, list):
            for item in value:
                _walk(item)

    _walk(payload)

    # Stable de-dup preserving first appearance order.
    deduped: List[str] = []
    seen = set()
    for message in messages:
        if message in seen:
            continue
        seen.add(message)
        deduped.append(message)
    return deduped


def _classify_install_message(message: str) -> str:
    text = str(message or "")
    if _line_has_pattern(text, INSTALL_FAIL_PATTERNS):
        return "failure"
    if _line_has_pattern(text, INSTALL_WARN_PATTERNS):
        return "warning"
    return "info"


def _build_high_vis_summary(payload: Any) -> Dict[str, Any]:
    extracted = _extract_named_messages(payload)
    classified = [
        {"severity": _classify_install_message(msg), "message": msg}
        for msg in extracted
    ]
    warnings = [item for item in classified if item["severity"] == "warning"]
    failures = [item for item in classified if item["severity"] == "failure"]
    info = [item for item in classified if item["severity"] == "info"]
    return {
        "count": len(classified),
        "failures": failures,
        "warnings": warnings,
        "info": info,
        "messages": classified,
    }


def _apply_install_flags(
    settings: Dict[str, Any],
    replace: bool = False,
    overwrite_duplicate_file: bool = False,
    overwrite_duplicate_data: bool = False,
    delete_previous_install: bool = False,
    override_directives: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, bool]]:
    rows = settings.get("MainInstallSettings") or []

    # Replace mode is a convenience profile for common promotion behavior.
    eff_file = overwrite_duplicate_file or replace
    eff_data = overwrite_duplicate_data or replace
    eff_delete_prev = delete_previous_install or replace
    eff_override_dir = override_directives or replace

    for row in rows:
        row["AutoOverwriteDuplicateFile"] = bool(eff_file)
        row["AutoOverwriteDuplicateData"] = bool(eff_data)
        row["DeletePreviousInstall"] = bool(eff_delete_prev)
        row["OverrideDirectives"] = bool(eff_override_dir)

    return settings, {
        "replace": bool(replace),
        "AutoOverwriteDuplicateFile": bool(eff_file),
        "AutoOverwriteDuplicateData": bool(eff_data),
        "DeletePreviousInstall": bool(eff_delete_prev),
        "OverrideDirectives": bool(eff_override_dir),
    }


class KineticSolutionService(KineticBaseClient):
    """Backup and recreate solutions from Solution Workbench."""

    def _call(self, method_name: str, body: Optional[Dict[str, Any]] = None, company: str = "") -> Dict[str, Any]:
        target_co = company if company else self.config["company"]
        url = _export_package_url(self.config["url"], target_co, method_name)
        return self.execute_request("POST", url, payload=body or {})

    def _call_file_transfer(self, method_name: str, body: Optional[Dict[str, Any]] = None, company: str = "") -> Dict[str, Any]:
        target_co = company if company else self.config["company"]
        url = f"{self.config['url'].rstrip('/')}/api/v2/odata/{target_co}/Ice.Lib.FileTransferSvc/{method_name}"
        return self.execute_request("POST", url, payload=body or {})

    def _empty_tableset_from(self, tableset: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not tableset:
            return {"ExportPackage": []}
        return {key: [] for key, value in tableset.items() if isinstance(value, list)}

    def list_solutions(self, company: str = "", page_size: int = 200, absolute_page: int = 1) -> Dict[str, Any]:
        return self._call(
            "GetList",
            {
                "whereClause": "",
                "pageSize": page_size,
                "absolutePage": absolute_page,
            },
            company=company,
        )

    def get_solution(self, solution_id: str, company: str = "") -> Dict[str, Any]:
        return self._call("GetByID", {"packageID": solution_id}, company=company)

    def solution_exists(self, solution_id: str, company: str = "") -> bool:
        data = self.get_solution(solution_id, company=company)
        tableset = data.get("returnObj") or {}
        for key in ("ExportPackage", "EPSolutionHeader", "EPSolutionDetail", "EPSolutionPackage"):
            rows = tableset.get(key) or []
            if rows:
                return True
        return False

    def get_solution_items_dynamic(self, solution_id: str, table_name: str, company: str = "") -> Dict[str, Any]:
        return self._call(
            "GetSolutionItemsAsDynamicDataSet",
            {"tableName": table_name, "solutionId": solution_id},
            company=company,
        )

    def get_tracked_items_dynamic(self, solution_id: str, table_name: str, company: str = "") -> Dict[str, Any]:
        return self._call(
            "GetTrackedItemsAsDynamicDataSet",
            {"tableName": table_name, "solutionId": solution_id},
            company=company,
        )

    def get_new_export_package(self, template_tableset: Optional[Dict[str, Any]] = None, company: str = "") -> Dict[str, Any]:
        empty_ds = self._empty_tableset_from(template_tableset)
        response = self._call("GetNewExportPackage", {"ds": empty_ds}, company=company)
        return (response.get("parameters") or {}).get("ds") or empty_ds

    def update_solution_tableset(self, tableset: Dict[str, Any], company: str = "") -> Dict[str, Any]:
        response = self._call("Update", {"ds": tableset}, company=company)
        return (response.get("parameters") or {}).get("ds") or {}

    def delete_solution(self, solution_id: str, company: str = "") -> None:
        self._call("DeleteByID", {"solutionID": solution_id}, company=company)

    def add_items_to_solution_and_save(
        self,
        solution_id: str,
        ds_to_add: Dict[str, Any],
        records_to_delete: Optional[Dict[str, Any]] = None,
        company: str = "",
    ) -> Dict[str, Any]:
        return self._call(
            "AddItemsToSolutionAndSave",
            {
                "solutionId": solution_id,
                "dsToAdd": ds_to_add,
                "recordsToDelete": records_to_delete if records_to_delete is not None else {"ELEMENT": []},
            },
            company=company,
        )

    def get_build_settings(self, solution_id: str, company: str = "") -> Dict[str, Any]:
        response = self._call("GetBuildSettings", {"solutionID": solution_id}, company=company)
        return response.get("returnObj") or {}

    def build_solution(self, solution_id: str, company: str = "") -> Dict[str, Any]:
        settings = self.get_build_settings(solution_id, company=company)
        response = self._call("BuildSolution", {"settings": settings}, company=company)
        result = {
            "solution_id": solution_id,
            "settings": settings,
            "result": response,
        }
        return result

    def download_server_file(self, server_path: str, folder: int = 4, company: str = "") -> bytes:
        response = self._call_file_transfer(
            "DownloadFile",
            {"folder": int(folder), "serverPath": server_path},
            company=company,
        )
        b64_data = response.get("returnObj")
        if not isinstance(b64_data, str) or not b64_data:
            raise ValueError(f"No file data returned for server path: {server_path}")
        return base64.b64decode(b64_data)

    def validate_build_artifacts(
        self,
        package_file: str,
        build_log_file: str = "",
        validation_file: str = "",
    ) -> Dict[str, Any]:
        summary: Dict[str, Any] = {
            "package_file": package_file,
            "package_exists": False,
            "package_is_zip": False,
            "package_entries": 0,
            "errors": [],
            "warnings": [],
            "pre_install_ready": False,
        }

        if not package_file or not os.path.isfile(package_file):
            summary["errors"].append("Package file is missing")
            return summary

        summary["package_exists"] = True
        if not zipfile.is_zipfile(package_file):
            summary["errors"].append("Package is not a valid zip file")
            return summary

        summary["package_is_zip"] = True
        with zipfile.ZipFile(package_file, "r") as zf:
            names = zf.namelist()
            summary["package_entries"] = len(names)
            if not names:
                summary["errors"].append("Package zip contains no entries")

        findings: List[Dict[str, Any]] = []
        findings.extend(_collect_text_findings(build_log_file))
        findings.extend(_collect_text_findings(validation_file))

        summary["warnings"] = [f for f in findings if f.get("severity") == "warning"]
        summary["errors"].extend([f for f in findings if f.get("severity") == "error"])
        summary["pre_install_ready"] = bool(summary["package_is_zip"] and not summary["errors"])
        return summary

    def build_and_download(
        self,
        solution_id: str,
        out_dir: str,
        company: str = "",
        folder: int = 4,
    ) -> Dict[str, Any]:
        build_result = self.build_solution(solution_id, company=company)
        params = ((build_result.get("result") or {}).get("parameters") or {})
        os.makedirs(out_dir, exist_ok=True)

        downloaded_artifacts: List[Dict[str, Any]] = []
        server_dirs: List[str] = []
        for server_key, local_key, role in BUILD_SERVER_ARTIFACT_FIELDS:
            server_path = str(params.get(server_key) or "").strip()
            if not server_path:
                continue

            server_dir = os.path.dirname(server_path)
            if server_dir and server_dir not in server_dirs:
                server_dirs.append(server_dir)

            payload = self.download_server_file(server_path, folder=folder, company=company)
            local_name = str(params.get(local_key) or "").strip()
            output_name = os.path.basename(local_name or server_path)
            if not output_name:
                output_name = f"{solution_id}_{role}.bin"

            output_path = os.path.join(out_dir, output_name)
            output_path = self.resolve_output_path(output_path, conflict_resolution="timestamp")
            with open(output_path, "wb") as f:
                f.write(payload)

            downloaded_artifacts.append(
                {
                    "role": role,
                    "server_field": server_key,
                    "server_path": server_path,
                    "local_file": output_path,
                }
            )

        if not downloaded_artifacts:
            raise ValueError("Build did not return downloadable server artifact file names")

        # Preserve compatibility for callers expecting single artifact keys.
        package_artifact = next((a for a in downloaded_artifacts if a["role"] == "package"), None)
        if package_artifact:
            build_result["artifact_file"] = package_artifact["local_file"]
            build_result["artifact_server_path"] = package_artifact["server_path"]

        # Try to download server-side Validation.txt from the same folder as build artifacts.
        validation_downloaded = False
        for server_dir in server_dirs:
            for validation_name in ("Validation.txt", "validation.txt"):
                validation_server_path = f"{server_dir.rstrip('/\\')}/{validation_name}"
                try:
                    payload = self.download_server_file(validation_server_path, folder=folder, company=company)
                except Exception:
                    continue

                validation_local_path = os.path.join(out_dir, "Validation.txt")
                validation_local_path = self.resolve_output_path(validation_local_path, conflict_resolution="timestamp")
                with open(validation_local_path, "wb") as f:
                    f.write(payload)

                downloaded_artifacts.append(
                    {
                        "role": "validation_server",
                        "server_field": "derived_validation_path",
                        "server_path": validation_server_path,
                        "local_file": validation_local_path,
                    }
                )
                build_result["validation_file"] = validation_local_path
                build_result["validation_server_path"] = validation_server_path
                validation_downloaded = True
                break
            if validation_downloaded:
                break

        log_records = str(params.get("logRecords") or "").strip()
        if log_records and not validation_downloaded:
            validation_path = os.path.join(out_dir, "Validation.txt")
            validation_path = self.resolve_output_path(validation_path, conflict_resolution="timestamp")
            with open(validation_path, "w", encoding="utf-8") as f:
                f.write(log_records)
            build_result["validation_file"] = validation_path
            build_result["validation_source"] = "logRecords"
        elif validation_downloaded:
            build_result["validation_source"] = "server_file"

        build_log_file = ""
        build_log_artifact = next((a for a in downloaded_artifacts if a.get("role") == "build_log"), None)
        if build_log_artifact:
            build_log_file = str(build_log_artifact.get("local_file") or "")

        validation_file = str(build_result.get("validation_file") or "")
        package_file = str(build_result.get("artifact_file") or "")
        build_result["post_build_validation"] = self.validate_build_artifacts(
            package_file=package_file,
            build_log_file=build_log_file,
            validation_file=validation_file,
        )
        build_result["pre_install_ready"] = bool(build_result["post_build_validation"].get("pre_install_ready"))

        build_result["downloaded_artifacts"] = downloaded_artifacts
        build_result["artifact_folder"] = int(folder)
        return build_result

    def save_build_result(self, solution_id: str, build_result: Dict[str, Any], out_dir: str) -> str:
        os.makedirs(out_dir, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_solution = solution_id.replace("/", "_").replace("\\", "_")
        output_path = os.path.join(out_dir, f"solution_build_{safe_solution}_{timestamp}.json")
        output_path = self.resolve_output_path(output_path, conflict_resolution="error")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(build_result, f, indent=2, ensure_ascii=False)
        return output_path

    def get_install_settings(self, cab_data: str, solution_file: str, company: str = "") -> Dict[str, Any]:
        response = self._call(
            "GetInstallSettings",
            {"cabData": cab_data, "solutionFile": solution_file},
            company=company,
        )
        return response.get("returnObj") or {}

    def install_solution_cab(
        self,
        cab_file: str,
        solution_file: str = "",
        company: str = "",
        skip_preflight: bool = False,
        replace: bool = False,
        overwrite_duplicate_file: bool = False,
        overwrite_duplicate_data: bool = False,
        delete_previous_install: bool = False,
        override_directives: bool = False,
    ) -> Dict[str, Any]:
        if not os.path.isfile(cab_file):
            raise FileNotFoundError(f"CAB file not found: {cab_file}")

        if not skip_preflight:
            base = cab_file
            build_log_path = f"{base}_Build.log"
            validation_path = f"{base}_Validation.txt"
            if not os.path.isfile(validation_path):
                alt_validation = os.path.join(os.path.dirname(base), "Validation.txt")
                validation_path = alt_validation if os.path.isfile(alt_validation) else ""

            preflight = self.validate_build_artifacts(
                package_file=cab_file,
                build_log_file=build_log_path if os.path.isfile(build_log_path) else "",
                validation_file=validation_path,
            )
            if not preflight.get("pre_install_ready"):
                raise ValueError("Pre-install validation failed. Use --skip-preflight to bypass.")

        cab_data = self.file_to_base64(cab_file)
        solution_file_name = solution_file.strip() or os.path.basename(cab_file)
        settings = self.get_install_settings(cab_data, solution_file_name, company=company)
        settings, install_flags = _apply_install_flags(
            settings,
            replace=replace,
            overwrite_duplicate_file=overwrite_duplicate_file,
            overwrite_duplicate_data=overwrite_duplicate_data,
            delete_previous_install=delete_previous_install,
            override_directives=override_directives,
        )
        response = self._call(
            "Install",
            {"cabData": cab_data, "settings": settings},
            company=company,
        )

        high_vis = _build_high_vis_summary(response)
        return {
            "cab_file": cab_file,
            "solution_file": solution_file_name,
            "preflight": preflight if not skip_preflight else {"skipped": True},
            "install_flags": install_flags,
            "settings": settings,
            "result": response,
            "high_vis": high_vis,
        }

    def backup_solution(
        self,
        solution_id: str,
        out_dir: str,
        company: str = "",
        include_dynamic: bool = True,
        include_tracked: bool = True,
    ) -> Dict[str, Any]:
        os.makedirs(out_dir, exist_ok=True)
        tableset = (self.get_solution(solution_id, company=company).get("returnObj") or {})
        table_names = _extract_solution_table_names(tableset)

        dynamic_items: Dict[str, Any] = {}
        tracked_items: Dict[str, Any] = {}

        if include_dynamic:
            for table_name in table_names:
                dynamic_items[table_name] = self.get_solution_items_dynamic(solution_id, table_name, company=company)

        if include_tracked:
            for table_name in table_names:
                tracked_items[table_name] = self.get_tracked_items_dynamic(solution_id, table_name, company=company)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_solution = solution_id.replace("/", "_").replace("\\", "_")
        output_path = os.path.join(out_dir, f"solution_backup_{safe_solution}_{timestamp}.json")
        output_path = self.resolve_output_path(output_path, conflict_resolution="error")

        backup = {
            "metadata": {
                "solution_id": solution_id,
                "environment": self.config.get("nickname", ""),
                "company": company or self.config.get("company", ""),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "table_names": table_names,
            },
            "tableset": tableset,
            "dynamic_items": dynamic_items,
            "tracked_items": tracked_items,
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(backup, f, indent=2, ensure_ascii=False)

        return {
            "success": True,
            "solution_id": solution_id,
            "output_file": output_path,
            "table_names": table_names,
        }

    def recreate_solution_from_backup(
        self,
        backup_path: str,
        company: str = "",
        target_solution_id: str = "",
        overwrite: bool = False,
        hydrate_items: bool = False,
        hydrate_tables: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        with open(backup_path, "r", encoding="utf-8") as f:
            backup = json.load(f)

        source_tableset = backup.get("tableset") or {}
        source_dynamic = backup.get("dynamic_items") or {}
        source_tracked = backup.get("tracked_items") or {}
        metadata = backup.get("metadata") or {}
        source_solution_id = str(metadata.get("solution_id", "")).strip()
        if not source_solution_id:
            raise ValueError("Backup file is missing metadata.solution_id")

        final_solution_id = target_solution_id.strip() or source_solution_id

        if overwrite and self.solution_exists(final_solution_id, company=company):
            self.delete_solution(final_solution_id, company=company)
        elif self.solution_exists(final_solution_id, company=company):
            raise ValueError(f"Solution already exists in target environment: {final_solution_id}")

        base_ds = self.get_new_export_package(template_tableset=source_tableset, company=company)
        recreated_ds = _sanitize_tableset_for_recreate(source_tableset, source_solution_id, final_solution_id)

        for key, value in recreated_ds.items():
            if isinstance(value, list):
                base_ds[key] = value

        saved_ds = self.update_solution_tableset(base_ds, company=company)

        hydrated_tables: List[str] = []
        hydrate_errors: Dict[str, str] = {}

        if hydrate_items:
            available_names = metadata.get("table_names") or _extract_solution_table_names(source_tableset)
            requested = hydrate_tables or DEFAULT_HYDRATE_TABLES
            selected_tables = _resolve_hydrate_tables(available_names, requested)

            for table_name in selected_tables:
                raw_payload = source_dynamic.get(table_name) or source_tracked.get(table_name)
                if not raw_payload:
                    continue
                ds_obj = _extract_dynamic_rows_payload(raw_payload)
                if not ds_obj:
                    continue
                ds_to_add = _sanitize_dynamic_payload_for_add(ds_obj, source_solution_id, final_solution_id)
                if not ds_to_add:
                    continue
                try:
                    self.add_items_to_solution_and_save(
                        final_solution_id,
                        ds_to_add=ds_to_add,
                        records_to_delete={"ELEMENT": []},
                        company=company,
                    )
                    hydrated_tables.append(table_name)
                except Exception as exc:
                    hydrate_errors[table_name] = str(exc)

        return {
            "success": True,
            "source_solution_id": source_solution_id,
            "target_solution_id": final_solution_id,
            "company": company or self.config.get("company", ""),
            "tables_saved": sorted([key for key, value in base_ds.items() if isinstance(value, list) and value]),
            "hydrated_tables": sorted(hydrated_tables),
            "hydrate_errors": hydrate_errors,
            "saved_tableset": saved_ds,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Backup, recreate, build, and install Solution Workbench solutions")
    parser.add_argument("--env", help="Environment nickname")
    parser.add_argument("--user", help="User ID for session")
    parser.add_argument("--company", help="Company override", default="")

    subparsers = parser.add_subparsers(dest="command")

    list_parser = subparsers.add_parser("list", help="List solutions")
    list_parser.add_argument("--page-size", type=int, default=200)
    list_parser.add_argument("--page", type=int, default=1)

    backup_parser = subparsers.add_parser("backup", help="Backup one solution definition")
    backup_parser.add_argument("solution_id")
    backup_parser.add_argument("--out-dir", default=os.path.join("exports", "solutions"))
    backup_parser.add_argument("--no-dynamic", action="store_true")
    backup_parser.add_argument("--no-tracked", action="store_true")

    recreate_parser = subparsers.add_parser("recreate", help="Recreate a solution from backup JSON")
    recreate_parser.add_argument("backup_file")
    recreate_parser.add_argument("--target-solution-id", default="")
    recreate_parser.add_argument("--overwrite", action="store_true")
    recreate_parser.add_argument(
        "--hydrate-items",
        action="store_true",
        help="Attempt AddItemsToSolutionAndSave for targeted element tables (BPDirective, Menu, XXXDef, MetaUI)",
    )
    recreate_parser.add_argument(
        "--hydrate-table",
        action="append",
        default=[],
        help="Table name to hydrate (repeatable). Defaults to BPDirective/Menu/XXXDef/MetaUI set when --hydrate-items is used.",
    )

    build_parser = subparsers.add_parser("build", help="Build a solution package on the server")
    build_parser.add_argument("solution_id")
    build_parser.add_argument(
        "--out-dir",
        default="",
        help="Optional directory to download the built package and save build result JSON.",
    )
    build_parser.add_argument(
        "--file-folder",
        type=int,
        default=4,
        help="FileTransferSvc folder enum for downloading server file (default: 4).",
    )

    install_parser = subparsers.add_parser("install", help="Install a solution CAB package")
    install_parser.add_argument("cab_file")
    install_parser.add_argument(
        "--solution-file",
        default="",
        help="Solution file name passed to GetInstallSettings (defaults to CAB filename).",
    )
    install_parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip pre-install validation checks on package/log/validation files.",
    )
    install_parser.add_argument(
        "--replace",
        action="store_true",
        help="Enable replace profile: overwrite duplicate file/data, delete previous install, override directives.",
    )
    install_parser.add_argument(
        "--overwrite-duplicate-file",
        action="store_true",
        help="Set MainInstallSettings.AutoOverwriteDuplicateFile=true.",
    )
    install_parser.add_argument(
        "--overwrite-duplicate-data",
        action="store_true",
        help="Set MainInstallSettings.AutoOverwriteDuplicateData=true.",
    )
    install_parser.add_argument(
        "--delete-previous-install",
        action="store_true",
        help="Set MainInstallSettings.DeletePreviousInstall=true.",
    )
    install_parser.add_argument(
        "--override-directives",
        action="store_true",
        help="Set MainInstallSettings.OverrideDirectives=true.",
    )
    KineticBaseClient.add_file_resolution_args(parser)

    args = parser.parse_args()

    service = KineticSolutionService(args.env, args.user, company_id=args.company or None)
    service.configure_file_resolution_from_args(args)

    if args.command == "list":
        result = service.list_solutions(company=args.company, page_size=args.page_size, absolute_page=args.page)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if args.command == "backup":
        result = service.backup_solution(
            args.solution_id,
            out_dir=args.out_dir,
            company=args.company,
            include_dynamic=not args.no_dynamic,
            include_tracked=not args.no_tracked,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if args.command == "recreate":
        result = service.recreate_solution_from_backup(
            args.backup_file,
            company=args.company,
            target_solution_id=args.target_solution_id,
            overwrite=args.overwrite,
            hydrate_items=args.hydrate_items,
            hydrate_tables=args.hydrate_table,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if args.command == "build":
        if args.out_dir:
            result = service.build_and_download(
                args.solution_id,
                out_dir=args.out_dir,
                company=args.company,
                folder=args.file_folder,
            )
        else:
            result = service.build_solution(args.solution_id, company=args.company)
        if args.out_dir:
            result["output_file"] = service.save_build_result(args.solution_id, result, args.out_dir)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if args.command == "install":
        result = service.install_solution_cab(
            args.cab_file,
            solution_file=args.solution_file,
            company=args.company,
            skip_preflight=args.skip_preflight,
            replace=args.replace,
            overwrite_duplicate_file=args.overwrite_duplicate_file,
            overwrite_duplicate_data=args.overwrite_duplicate_data,
            delete_previous_install=args.delete_previous_install,
            override_directives=args.override_directives,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))

        # High-visibility summary at the end for operators.
        high_vis = result.get("high_vis") or {}
        warnings = high_vis.get("warnings") or []
        failures = high_vis.get("failures") or []
        if warnings or failures:
            print("\n" + "=" * 80, file=sys.stderr)
            print("POST-INSTALL HIGHLIGHTS", file=sys.stderr)
            print("=" * 80, file=sys.stderr)
            for item in failures:
                print(f"[FAILURE] {item.get('message', '')}", file=sys.stderr)
            for item in warnings:
                print(f"[WARNING] {item.get('message', '')}", file=sys.stderr)
            print("=" * 80, file=sys.stderr)
        return

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
