"""Unit tests for Solution Workbench backup/recreate helpers."""

import os
import tempfile
import unittest
import zipfile

from kinetic_devops.solutions import (
    _apply_install_flags,
    _build_high_vis_summary,
    _classify_install_message,
    _extract_named_messages,
    _collect_text_findings,
    _extract_layer_conflicts,
    _extract_solution_table_names,
    _extract_dynamic_rows_payload,
    _resolve_hydrate_tables,
    _sanitize_tableset_for_recreate,
    _sanitize_dynamic_payload_for_add,
    KineticSolutionService,
)


class TestSolutionHelpers(unittest.TestCase):
    def test_extract_layer_conflicts_identifier_format(self):
        messages = [
            "Import cancelled or failed for 'Erp.UI.NonConfEntry~2026-03-27-NonConfEntry-FTT~KNTCCustLayer'.",
            "Layer with identifier Erp.UI.NonConfEntry~2026-03-27-NonConfEntry-FTT~KNTCCustLayer already exists in another company",
        ]
        conflicts = _extract_layer_conflicts(messages)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["application_id"], "Erp.UI.NonConfEntry")
        self.assertEqual(conflicts[0]["layer_name"], "2026-03-27-NonConfEntry-FTT")
        self.assertEqual(conflicts[0]["layer_type"], "KNTCCustLayer")

    def test_extract_layer_conflicts_alt_warning_format(self):
        messages = [
            "Cannot override all companies customization for application layer 2023-10_AssignedDept Erp.UI.NonConfEntry as the layer already exists in another company.",
            "Cannot override all companies customization for application layer 2026-03-27-NonConfEntry-FTT Erp.UI.NonConfEntry as the layer already exists in another company.",
        ]
        conflicts = _extract_layer_conflicts(messages)
        self.assertEqual(len(conflicts), 2)
        self.assertEqual(conflicts[0]["layer_type"], "KNTCCustLayer")
        self.assertEqual(conflicts[0]["application_id"], "Erp.UI.NonConfEntry")
        self.assertEqual(conflicts[0]["layer_name"], "2023-10_AssignedDept")

    def test_extract_solution_table_names_skips_undefined(self):
        tableset = {
            "EPSolutionDetail": [
                {"TableName": "QueryHdr"},
                {"TableName": "undefined"},
                {"TableName": " Menu "},
            ],
            "EPSolutionPackage": [
                {"TableName": "XXXDef"},
                {"TableName": ""},
            ],
        }

        result = _extract_solution_table_names(tableset)
        self.assertEqual(result, ["Menu", "QueryHdr", "XXXDef"])

    def test_sanitize_tableset_replaces_ids_and_system_fields(self):
        source = {
            "ExportPackage": [
                {
                    "PackageID": "SRC_SOL",
                    "SolutionID": "SRC_SOL",
                    "Description": "Source",
                    "SysRowID": "abc",
                    "SysRevID": 1,
                }
            ],
            "EPSolutionDetail": [
                {
                    "SolutionID": "SRC_SOL",
                    "TableName": "QueryHdr",
                    "Key1": "MyBAQ",
                    "ForeignSysRowID": "foreign-id",
                    "BitFlag": 0,
                }
            ],
            "EPHistory": [
                {"SolutionID": "SRC_SOL", "Something": "skip"}
            ],
        }

        result = _sanitize_tableset_for_recreate(source, "SRC_SOL", "TGT_SOL")

        self.assertEqual(result["ExportPackage"][0]["PackageID"], "TGT_SOL")
        self.assertEqual(result["ExportPackage"][0]["SolutionID"], "TGT_SOL")
        self.assertNotIn("SysRowID", result["ExportPackage"][0])
        self.assertNotIn("SysRevID", result["ExportPackage"][0])
        self.assertEqual(result["ExportPackage"][0]["RowMod"], "A")

        self.assertEqual(result["EPSolutionDetail"][0]["SolutionID"], "TGT_SOL")
        self.assertEqual(result["EPSolutionDetail"][0]["ForeignSysRowID"], "foreign-id")
        self.assertEqual(result["EPHistory"], [])

    def test_resolve_hydrate_tables_handles_ice_prefix(self):
        available = ["QueryHdr", "Ice.Menu", "XXXDef", "BpDirectiveGroup"]
        requested = ["menu", "bpdirectivegroup", "MetaUI"]
        result = _resolve_hydrate_tables(available, requested)
        self.assertEqual(result, ["BpDirectiveGroup", "Ice.Menu"])

    def test_extract_and_sanitize_dynamic_payload(self):
        raw = {
            "returnObj": {
                "DynamicTable": [
                    {
                        "SolutionID": "SRC_SOL",
                        "TableName": "Menu",
                        "Key1": "Main",
                        "SysRowID": "x",
                        "SysRevID": 9,
                    }
                ]
            }
        }

        extracted = _extract_dynamic_rows_payload(raw)
        self.assertIn("DynamicTable", extracted)
        sanitized = _sanitize_dynamic_payload_for_add(extracted, "SRC_SOL", "TGT_SOL")
        self.assertEqual(sanitized["DynamicTable"][0]["SolutionID"], "TGT_SOL")
        self.assertEqual(sanitized["DynamicTable"][0]["RowMod"], "A")
        self.assertNotIn("SysRowID", sanitized["DynamicTable"][0])

    def test_collect_text_findings_ignores_zero_errors(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "Validation.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write("0 errors found\n")
                f.write("WARNING: something optional\n")
                f.write("Fatal: bad state\n")
            findings = _collect_text_findings(path)
            severities = [item["severity"] for item in findings]
            self.assertIn("warning", severities)
            self.assertIn("error", severities)

    def test_validate_build_artifacts_pre_install_ready(self):
        with tempfile.TemporaryDirectory() as td:
            package = os.path.join(td, "pkg.zip")
            with zipfile.ZipFile(package, "w") as zf:
                zf.writestr("manifest.xml", "<m />")

            log_path = os.path.join(td, "pkg.zip_Build.log")
            with open(log_path, "w", encoding="utf-8") as f:
                f.write("Build complete\n")

            svc = object.__new__(KineticSolutionService)
            summary = svc.validate_build_artifacts(package, build_log_file=log_path, validation_file="")
            self.assertTrue(summary["pre_install_ready"])

            validation_path = os.path.join(td, "Validation.txt")
            with open(validation_path, "w", encoding="utf-8") as f:
                f.write("ERROR: failure happened\n")
            summary2 = svc.validate_build_artifacts(package, build_log_file=log_path, validation_file=validation_path)
            self.assertFalse(summary2["pre_install_ready"])

    def test_extract_named_messages_and_classification(self):
        payload = {
            "returnObj": {
                "Message": "Import canceled. Record already exists.",
                "Inner": [
                    {"validationMsg": "Changes may need Regenerate Data Model."},
                    {"Message": "A hard error happened."},
                ],
            }
        }
        msgs = _extract_named_messages(payload)
        self.assertEqual(len(msgs), 3)
        self.assertEqual(_classify_install_message(msgs[0]), "warning")
        self.assertEqual(_classify_install_message(msgs[1]), "warning")
        self.assertEqual(_classify_install_message(msgs[2]), "failure")

    def test_build_high_vis_summary(self):
        payload = {
            "Message": "Import canceled. Record already exists.",
            "logRecords": "ERROR: failed to load item",
        }
        summary = _build_high_vis_summary(payload)
        self.assertEqual(summary["count"], 2)
        self.assertEqual(len(summary["warnings"]), 1)
        self.assertEqual(len(summary["failures"]), 1)

    def test_apply_install_flags_replace_profile(self):
        settings = {
            "MainInstallSettings": [
                {
                    "AutoOverwriteDuplicateFile": False,
                    "AutoOverwriteDuplicateData": False,
                    "DeletePreviousInstall": False,
                    "OverrideDirectives": False,
                }
            ]
        }
        updated, flags = _apply_install_flags(settings, replace=True)
        row = updated["MainInstallSettings"][0]
        self.assertTrue(row["AutoOverwriteDuplicateFile"])
        self.assertTrue(row["AutoOverwriteDuplicateData"])
        self.assertTrue(row["DeletePreviousInstall"])
        self.assertTrue(row["OverrideDirectives"])
        self.assertTrue(flags["replace"])


if __name__ == "__main__":
    unittest.main()