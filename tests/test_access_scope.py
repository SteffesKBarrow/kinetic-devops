"""Tests for access scope migration and validation CLI behavior."""

import argparse
import json
import os
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from kinetic_devops import access_scope, artifact_validation


class TestAccessScopeValidation(unittest.TestCase):
    def test_compare_scope_functional_artifacts_detects_method_gap(self):
        reference = {
            "core": [{"AccessScopeID": "HeadlessMES", "Description": "Headless Kinetic Flow MES"}],
            "entities": [{"EntityID": "ERP.BO.Company"}],
            "bo_methods": [{"EntityID": "ERP.BO.Company", "MethodID": "GetList"}],
        }
        target = {
            "core": [{"AccessScopeID": "HeadlessMES", "Description": "Headless Kinetic Flow MES"}],
            "entities": [{"EntityID": "ERP.BO.Company"}],
            "bo_methods": [],
        }

        result = artifact_validation.compare_artifact_sections(reference, target, ("core", "entities", "bo_methods"))

        self.assertTrue(result["core_identical"])
        self.assertTrue(result["entities_identical"])
        self.assertFalse(result["bo_methods_identical"])
        self.assertEqual(result["bo_methods_reference_only_count"], 1)
        self.assertEqual(result["bo_methods_target_only_count"], 0)
        self.assertFalse(result["functionally_identical"])

    def test_extract_artifact_payload_accepts_nested_pilot(self):
        payload = {
            "scope": "HeadlessMES",
            "pilot": {
                "env": "Pilot",
                "core": [{"AccessScopeID": "HeadlessMES"}],
                "entities": [{"EntityID": "ERP.BO.Company"}],
                "bo_methods": [{"MethodID": "GetList"}],
            },
        }

        result = artifact_validation.extract_artifact_payload(payload, ("core", "entities", "bo_methods"))

        self.assertEqual(result["env"], "Pilot")
        self.assertEqual(result["scope"], "HeadlessMES")
        self.assertEqual(len(result["core"]), 1)

    def test_main_legacy_args_default_to_migrate(self):
        with patch("kinetic_devops.access_scope.run_scope_migration", return_value=0) as migrate, patch(
            "kinetic_devops.access_scope.run_scope_validation", return_value=0
        ) as validate:
            rc = access_scope.main(
                [
                    "--source-env",
                    "Pilot",
                    "--target-env",
                    "Third",
                    "--from-scope",
                    "A",
                    "--to-scope",
                    "B",
                ]
            )

        self.assertEqual(rc, 0)
        self.assertEqual(migrate.call_count, 1)
        self.assertEqual(validate.call_count, 0)

    def test_main_validate_dispatch(self):
        with patch("kinetic_devops.access_scope.run_scope_migration", return_value=0) as migrate, patch(
            "kinetic_devops.access_scope.run_scope_validation", return_value=0
        ) as validate:
            rc = access_scope.main(
                [
                    "validate",
                    "--scope-id",
                    "HeadlessMES",
                    "--reference-env",
                    "Pilot",
                    "--target-env",
                    "Third",
                ]
            )

        self.assertEqual(rc, 0)
        self.assertEqual(validate.call_count, 1)
        self.assertEqual(migrate.call_count, 0)

    def test_main_refresh_import_dispatch(self):
        with patch("kinetic_devops.access_scope.run_scope_migration", return_value=0) as migrate, patch(
            "kinetic_devops.access_scope.run_scope_validation", return_value=0
        ) as validate, patch("kinetic_devops.access_scope.run_scope_refresh_import", return_value=0) as refresh_import:
            rc = access_scope.main(
                [
                    "refresh-import",
                    "--scope-id",
                    "HeadlessMES",
                    "--reference-env",
                    "Pilot",
                    "--target-env",
                    "Third",
                    "--dry-run",
                ]
            )

        self.assertEqual(rc, 0)
        self.assertEqual(refresh_import.call_count, 1)
        self.assertEqual(validate.call_count, 0)
        self.assertEqual(migrate.call_count, 0)

    def test_main_validate_requires_reference_source(self):
        with self.assertRaises(SystemExit) as ctx:
            access_scope.main(
                [
                    "validate",
                    "--scope-id",
                    "HeadlessMES",
                    "--target-env",
                    "Third",
                ]
            )

        self.assertEqual(ctx.exception.code, 2)

    def test_main_refresh_import_requires_reference_source(self):
        with self.assertRaises(SystemExit) as ctx:
            access_scope.main(
                [
                    "refresh-import",
                    "--scope-id",
                    "HeadlessMES",
                    "--target-env",
                    "Third",
                ]
            )

        self.assertEqual(ctx.exception.code, 2)

    def test_main_export_eas_dispatch(self):
        with patch("kinetic_devops.access_scope.run_scope_migration", return_value=0) as migrate, patch(
            "kinetic_devops.access_scope.run_scope_validation", return_value=0
        ) as validate, patch("kinetic_devops.access_scope.run_scope_export_eas", return_value=0) as export_eas:
            rc = access_scope.main(
                [
                    "export-eas",
                    "--scope-id",
                    "HeadlessMES",
                    "--source-env",
                    "Pilot",
                ]
            )

        self.assertEqual(rc, 0)
        self.assertEqual(export_eas.call_count, 1)
        self.assertEqual(validate.call_count, 0)
        self.assertEqual(migrate.call_count, 0)

    def test_load_scope_artifact_from_eas_normalizes_noise_fields(self):
        tableset = {
            "AccessScope": [
                {
                    "Company": "CMP",
                    "AccessScopeID": "HeadlessMES",
                    "Description": "Headless Kinetic Flow MES",
                    "SysRevID": 123,
                    "SysRowID": "abc",
                    "RowMod": "",
                }
            ],
            "AccessScopeEntity": [
                {
                    "Company": "CMP",
                    "AccessScopeID": "HeadlessMES",
                    "EntityType": "Service",
                    "EntityID": "ERP.BO.Company",
                    "EntityDescription": "Company Service",
                    "SysRevID": 1,
                    "SysRowID": "def",
                }
            ],
            "AccessScopeBOMethod": [
                {
                    "Company": "CMP",
                    "AccessScopeID": "HeadlessMES",
                    "EntityType": "Service",
                    "EntityID": "ERP.BO.Company",
                    "MethodID": "GetList",
                    "SysRevID": 2,
                    "SysRowID": "ghi",
                }
            ],
        }

        with tempfile.NamedTemporaryFile(suffix=".eas", delete=False) as tmp:
            eas_path = tmp.name

        try:
            with zipfile.ZipFile(eas_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("Version", "5.2.100.0")
                archive.writestr("AccessScopeTableset", json.dumps(tableset))

            artifact = artifact_validation.load_scope_artifact_from_path(eas_path)
            self.assertEqual(artifact["scope"], "HeadlessMES")
            self.assertEqual(artifact["company"], "CMP")
            self.assertEqual(len(artifact["core"]), 1)
            self.assertEqual(len(artifact["entities"]), 1)
            self.assertEqual(len(artifact["bo_methods"]), 1)

            core_row = artifact["core"][0]
            self.assertIn("AccessScopeID", core_row)
            self.assertNotIn("Company", core_row)
            self.assertNotIn("SysRevID", core_row)
            self.assertNotIn("SysRowID", core_row)
            self.assertNotIn("RowMod", core_row)
        finally:
            if os.path.exists(eas_path):
                os.remove(eas_path)


if __name__ == "__main__":
    unittest.main()