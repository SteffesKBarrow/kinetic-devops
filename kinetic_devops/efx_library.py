"""EFx Function Library management via Ice.Lib.EfxLibraryDesignerSvc.

Method names and payload shapes below are verified against captured browser
traces of the EFx Studio UI (Export Library / Import Library actions), not
guessed from documentation -- Ice.Lib.EfxLibraryDesignerSvc isn't documented
consistently across Epicor instances. Only the methods actually exercised in
a trace are implemented; Promote/Demote/Assign Companies/Delete/References
are intentionally not included yet -- they need their own captured trace
before being wrapped, to avoid shipping invented payload shapes.
"""

import argparse
import base64
import json
import os
import sys
from typing import Any, Dict, List, Optional

if __package__:
    from .base_client import KineticBaseClient
else:
    from kinetic_devops.base_client import KineticBaseClient


SERVICE_NAME = "Ice.Lib.EfxLibraryDesignerSvc"


class KineticEfxLibraryService(KineticBaseClient):
    """Export/import/list Epicor EFx Function Libraries."""

    def _service_url(self, method_name: str, company: str = "") -> str:
        target_co = company or self.config["company"]
        return f"{self.config['url'].rstrip('/')}/api/v2/odata/{target_co}/{SERVICE_NAME}/{method_name}"

    def _call(
        self,
        method_name: str,
        payload: Optional[Dict[str, Any]] = None,
        company: str = "",
        http_method: str = "POST",
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        target_co = company or self.config["company"]
        return self.execute_request(
            http_method,
            self._service_url(method_name, company=target_co),
            payload=payload if http_method != "GET" else None,
            params=params,
            company=target_co,
        )

    def get_library_list(
        self,
        kind: str = "1",
        starts_with: str = "",
        roll_out_mode: str = "2",
        status: str = "2",
        company: str = "",
    ) -> List[Dict[str, Any]]:
        """List libraries visible to the current user.

        Live-tested against Third on 2026-10-07: Ice.Lib.EfxLibraryDesignerSvc
        /GetLibraryList2 with kind/startsWith/rollOutMode/status as strings,
        startsWith required (can be empty). export_all.py separately calls
        Ice.BO.EfxLibraryDesignerSvc/GetLibraryList with an int-wrapped
        "searchOptions" payload -- a different method name, not yet tested
        one way or the other here.
        """
        response = self._call(
            "GetLibraryList2",
            {
                "kind": str(kind),
                "startsWith": starts_with,
                "rollOutMode": str(roll_out_mode),
                "status": str(status),
            },
            company=company,
        )
        rows = (response.get("returnObj") or {}).get("EfxLibraryList") or []
        return [row for row in rows if isinstance(row, dict)]

    def get_libraries(self, library_ids: List[str], company: str = "") -> Dict[str, Any]:
        """Fetch the full tableset for one or more libraries: EfxLibrary,
        EfxFunction (with raw directive Body), EfxLibraryMapping (company
        assignments), EfxRefService, EfxRefTable, etc."""
        response = self._call("GetLibraries", {"libraryIds": list(library_ids)}, company=company)
        return response.get("returnObj") or {}

    def get_kinetic_function(self, library_id: str, function_id: str, company: str = "") -> Dict[str, Any]:
        """Fetch a single function's node graph. The service returns this
        as a JSON-encoded string, not an object -- parsed here for
        convenience."""
        response = self._call(
            "GetKineticFunction",
            http_method="GET",
            params={"libraryId": library_id, "functionId": function_id},
            company=company,
        )
        raw = response.get("returnObj")
        if isinstance(raw, str) and raw.strip():
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"_raw": raw}
        return raw or {}

    def export_library(
        self,
        library_id: str,
        mode: int = 0,
        export_format: int = 1,
        package: Optional[str] = None,
        package_version: Optional[str] = None,
        publisher: Optional[str] = None,
        install_as_hidden: bool = False,
        company: str = "",
    ) -> str:
        """Export a library. Returns the raw base64 payload (not a zip --
        it decodes directly to XML/text); use export_library_to_file to
        decode and save it."""
        response = self._call(
            "ExportLibrary",
            {
                "libraryID": library_id,
                "options": {
                    "Mode": mode,
                    "Format": export_format,
                    "Package": package or library_id,
                    "PackageVersion": package_version,
                    "Publisher": publisher,
                    "InstallAsHidden": bool(install_as_hidden),
                },
            },
            company=company,
        )
        return response.get("returnObj") or ""

    def export_library_to_file(self, library_id: str, out_path: str, company: str = "", **export_kwargs) -> str:
        """Export a library and decode+save it to out_path. Returns the
        resolved output path (conflict-resolved via resolve_output_path)."""
        b64_data = self.export_library(library_id, company=company, **export_kwargs)
        if not b64_data:
            raise ValueError(f"No export payload returned for library '{library_id}'.")
        resolved = self.resolve_output_path(out_path, conflict_resolution="timestamp")
        os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
        with open(resolved, "wb") as f:
            f.write(base64.b64decode(b64_data))
        return resolved

    def import_library(
        self,
        library_package_b64: str,
        new_library_id: Optional[str] = None,
        overwrite_mode: int = 0,
        company: str = "",
    ) -> Dict[str, Any]:
        """Import a library from the base64 payload produced by
        export_library/ExportLibrary. Returns the raw response (check
        BOUpdError for row-level failures -- a 200 doesn't guarantee a
        clean import)."""
        response = self._call(
            "ImportLibrary",
            {
                "libraryPackage": library_package_b64,
                "options": {
                    "NewLibraryId": new_library_id,
                    "OverwriteMode": int(overwrite_mode),
                },
            },
            company=company,
        )
        return response.get("returnObj") or {}

    def import_library_from_file(
        self,
        file_path: str,
        new_library_id: Optional[str] = None,
        overwrite_mode: int = 0,
        company: str = "",
    ) -> Dict[str, Any]:
        with open(file_path, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("ascii")
        return self.import_library(b64_data, new_library_id=new_library_id, overwrite_mode=overwrite_mode, company=company)

    def export_all_libraries(self, out_dir: str, company: str = "", skip_disabled: bool = True) -> List[Dict[str, Any]]:
        """Export every library visible to the current user, one file per
        library under out_dir/<LibraryID>/<LibraryID>.efxlib. Returns a
        per-library result list (success/error) instead of raising on the
        first failure, so one broken library doesn't abort the rest."""
        results: List[Dict[str, Any]] = []
        for lib in self.get_library_list(company=company):
            library_id = lib.get("LibraryID")
            if not library_id:
                continue
            if skip_disabled and lib.get("Disabled"):
                results.append({"library_id": library_id, "skipped": "disabled"})
                continue
            lib_dir = os.path.join(out_dir, library_id)
            out_path = os.path.join(lib_dir, f"{library_id}.efxlib")
            try:
                resolved = self.export_library_to_file(library_id, out_path, company=company)
                results.append({"library_id": library_id, "output_file": resolved, "success": True})
            except Exception as exc:
                results.append({"library_id": library_id, "success": False, "error": str(exc)})
        return results


def main() -> None:
    parser = argparse.ArgumentParser(description="EFx Function Library export/import")
    parser.add_argument("-e", "--env")
    parser.add_argument("-u", "--user")
    parser.add_argument("--company")
    KineticBaseClient.add_file_resolution_args(parser)

    subparsers = parser.add_subparsers(dest="command")

    list_p = subparsers.add_parser("list", help="List visible libraries")

    export_p = subparsers.add_parser("export", help="Export a single library")
    export_p.add_argument("library_id")
    export_p.add_argument("--out", required=True)

    export_all_p = subparsers.add_parser("export-all", help="Export every visible library into out_dir/<LibraryID>/")
    export_all_p.add_argument("--out-dir", required=True)

    import_p = subparsers.add_parser("import", help="Import a library from a previously exported file")
    import_p.add_argument("file_path")
    import_p.add_argument("--new-library-id")
    import_p.add_argument("--overwrite-mode", type=int, default=0)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    service = KineticEfxLibraryService(args.env, args.user, company_id=args.company)
    service.configure_file_resolution_from_args(args)

    try:
        if args.command == "list":
            for lib in service.get_library_list():
                print(f"{lib.get('LibraryID')}\t{'disabled' if lib.get('Disabled') else 'enabled'}\t{lib.get('Description') or ''}")
        elif args.command == "export":
            resolved = service.export_library_to_file(args.library_id, args.out)
            print(f"✅ Exported {args.library_id} -> {resolved}")
        elif args.command == "export-all":
            results = service.export_all_libraries(args.out_dir)
            ok = sum(1 for r in results if r.get("success"))
            print(f"✅ Exported {ok}/{len(results)} libraries to {args.out_dir}")
            for r in results:
                if not r.get("success") and not r.get("skipped"):
                    print(f"  ❌ {r['library_id']}: {r.get('error')}")
        elif args.command == "import":
            result = service.import_library_from_file(args.file_path, new_library_id=args.new_library_id, overwrite_mode=args.overwrite_mode)
            errors = result.get("BOUpdError") or []
            if errors:
                print(f"⚠️  Import completed with {len(errors)} error(s): {errors}")
            else:
                print("✅ Import completed with no errors.")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
