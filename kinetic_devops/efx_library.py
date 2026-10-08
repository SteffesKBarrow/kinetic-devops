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
import re
import sys
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

if __package__:
    from .base_client import KineticBaseClient
    from .artifact_validation import normalize_artifact_rows, DEFAULT_IGNORE_FIELDS
else:
    from kinetic_devops.base_client import KineticBaseClient
    from kinetic_devops.artifact_validation import normalize_artifact_rows, DEFAULT_IGNORE_FIELDS


SERVICE_NAME = "Ice.Lib.EfxLibraryDesignerSvc"


def _safe_path_component(value: str) -> str:
    """Strip path separators and traversal sequences from a server-supplied
    ID before using it as a directory/filename component. The original,
    unmodified value should still be used for API calls -- this is only
    for constructing local output paths safely."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    cleaned = cleaned.strip(".") or "library"
    return cleaned


def _resolve_contained_path(out_dir: str, *parts: str) -> str:
    """Join parts under out_dir and verify the result doesn't escape it."""
    out_dir_abs = os.path.abspath(out_dir)
    candidate = os.path.abspath(os.path.join(out_dir_abs, *parts))
    if candidate != out_dir_abs and not candidate.startswith(out_dir_abs + os.sep):
        raise ValueError(f"Resolved path '{candidate}' escapes output directory '{out_dir_abs}'.")
    return candidate


def _local_tag(tag: str) -> str:
    """Strip the XML namespace off an ElementTree tag ('{ns}Name' -> 'Name')."""
    return tag.rsplit("}", 1)[-1]


def _xml_parent_map(root: ET.Element) -> Dict[ET.Element, ET.Element]:
    return {child: parent for parent in root.iter() for child in parent}


def _iter_custom_code_actions(root: ET.Element):
    """Yield (directive_step_or_None, action_element) for every
    CustomCodeAction node in a function Body XML tree, regardless of
    namespace prefix or nesting depth (conditions/branches can nest
    DirectiveSteps inside each other)."""
    parent_map = _xml_parent_map(root)
    for action in root.iter():
        if _local_tag(action.tag) != "CustomCodeAction":
            continue
        step = None
        node = action
        while node in parent_map:
            node = parent_map[node]
            if _local_tag(node.tag) == "DirectiveStep":
                step = node
                break
        yield step, action


def _dotnet_xml_attribute_escape(text: str) -> str:
    """Match .NET's XmlWriter attribute-value escaping exactly (observed in
    live Body XML): <, >, &, " are entity-escaped, and \\n/\\r/\\t become
    numeric character references so whitespace survives attribute-value
    normalization. Used instead of a generic XML library so a push-back
    edit only ever touches the one attribute value being changed."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    text = text.replace("\r\n", "\n")
    text = text.replace("\n", "&#xA;").replace("\r", "&#xD;").replace("\t", "&#x9;")
    return text


def _replace_code_attribute_for_step(body: str, step_id: str, new_code: str) -> str:
    """Replace the Code="..." attribute inside the DirectiveStep whose Id
    matches step_id, via targeted string surgery on the raw Body text --
    NOT a parse-then-reserialize round-trip. Body is .NET XAML
    serialization (DirectiveDefinition2); verified live that reserializing
    the whole tree via a generic XML library (even just parsing and
    writing it back unchanged) breaks the server's XAML deserializer
    ('Unable to read function definition' / DeserializeBody) because it
    rewrites namespace prefixes and formatting the deserializer is
    sensitive to. Editing only the one attribute's text in place keeps
    everything else byte-identical to what the server produced."""
    step_pattern = re.compile(r'<DirectiveStep\b[^>]*\bId="' + re.escape(step_id) + r'"[^>]*>')
    match = step_pattern.search(body)
    if not match:
        raise ValueError(f"DirectiveStep with Id '{step_id}' not found in Body.")
    start = match.start()
    # (?=[\s>/]) excludes XAML property-element tags like <DirectiveStep.Action>
    # and <DirectiveStep.VisualProperties>, which aren't sibling step boundaries.
    next_step = re.compile(r"<DirectiveStep(?=[\s>/])").search(body, match.end())
    end = next_step.start() if next_step else len(body)
    segment = body[start:end]

    code_pattern = re.compile(r'(Code=")([^"]*)(")')
    if not code_pattern.search(segment):
        raise ValueError(f"No Code attribute found for DirectiveStep '{step_id}'.")
    new_segment = code_pattern.sub(
        lambda m: m.group(1) + _dotnet_xml_attribute_escape(new_code) + m.group(3),
        segment,
        count=1,
    )
    return body[:start] + new_segment + body[end:]


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

    def extract_function_source(
        self,
        library_id: str,
        function_id: str,
        out_dir: str,
        company: str = "",
        tableset: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Pull one function's Body and split its embedded
        CustomCodeAction.Code fragments into individual .cs files under
        out_dir/<LibraryID>/<FunctionID>/, plus a _body.xml sidecar (the
        untouched original Body, used to reconstruct everything else about
        the function on push-back) and a _meta.json (row metadata with
        Body and volatile fields like SysRevID/SysRowID/BitFlag stripped,
        for human review/diffing only -- push-back always re-fetches fresh
        metadata rather than trusting this file).

        Only the XML Body wire format is handled here -- that's what
        GetLibraries returns live (verified against Third). The service
        also accepts a JSON wire format on write (seen in a captured
        ApplyChangesWithDiagnostics trace), but a live GetLibraries read
        returning that JSON form hasn't been observed, so round-tripping it
        isn't implemented.
        """
        if tableset is None:
            tableset = self.get_libraries([library_id], company=company)
        functions = tableset.get("EfxFunction") or []
        row = next(
            (f for f in functions if f.get("FunctionID") == function_id and f.get("LibraryID") == library_id),
            None,
        )
        if row is None:
            raise ValueError(f"Function '{function_id}' not found in library '{library_id}'.")

        body = row.get("Body") or ""
        safe_lib = _safe_path_component(library_id)
        safe_fn = _safe_path_component(function_id)
        func_dir = _resolve_contained_path(out_dir, safe_lib, safe_fn)
        os.makedirs(func_dir, exist_ok=True)

        written_files: List[str] = []
        if body.lstrip().startswith("<"):
            root = ET.fromstring(body)
            for index, (step, action) in enumerate(_iter_custom_code_actions(root)):
                code = action.get("Code") or ""
                node_id = (step.get("Id") if step is not None else "") or f"node{index}"
                display_name = (step.get("DisplayName") if step is not None else "") or f"CustomCode{index}"
                file_name = f"{_safe_path_component(node_id)}__{_safe_path_component(display_name)}.cs"
                file_path = _resolve_contained_path(func_dir, file_name)
                with open(file_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(code)
                written_files.append(file_path)

            body_sidecar = _resolve_contained_path(func_dir, "_body.xml")
            with open(body_sidecar, "w", encoding="utf-8", newline="\n") as f:
                f.write(body)
        else:
            body_sidecar = _resolve_contained_path(func_dir, "_body.json")
            with open(body_sidecar, "w", encoding="utf-8", newline="\n") as f:
                f.write(body)

        ignore_fields = DEFAULT_IGNORE_FIELDS | {"Body"}
        meta_rows = normalize_artifact_rows([row], ignore_fields=ignore_fields)
        meta_path = _resolve_contained_path(func_dir, "_meta.json")
        with open(meta_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(meta_rows[0] if meta_rows else {}, f, indent=2, sort_keys=True)
            f.write("\n")

        return {
            "library_id": library_id,
            "function_id": function_id,
            "function_dir": func_dir,
            "code_files": written_files,
            "body_sidecar": body_sidecar,
            "meta_file": meta_path,
        }

    def export_library_source(self, library_id: str, out_dir: str, company: str = "") -> List[Dict[str, Any]]:
        """Extract every function in a library to
        out_dir/<LibraryID>/<FunctionID>/. One failing function doesn't
        abort the rest."""
        tableset = self.get_libraries([library_id], company=company)
        results: List[Dict[str, Any]] = []
        for row in tableset.get("EfxFunction") or []:
            function_id = row.get("FunctionID")
            if not function_id:
                continue
            try:
                result = self.extract_function_source(
                    library_id, function_id, out_dir, company=company, tableset=tableset
                )
                result["success"] = True
            except Exception as exc:
                result = {
                    "library_id": library_id,
                    "function_id": function_id,
                    "success": False,
                    "error": str(exc),
                }
            results.append(result)
        return results

    def push_function_source(
        self, library_id: str, function_id: str, out_dir: str, company: str = ""
    ) -> Dict[str, Any]:
        """Re-inject edited .cs file(s) from
        out_dir/<LibraryID>/<FunctionID>/ back into a freshly-fetched copy
        of the function's Body XML (not the locally cached _body.xml
        sidecar, so concurrent server-side changes to nodes this didn't
        touch aren't clobbered), then submit via ApplyChangesWithDiagnostics
        (ApplyChanges is deprecated in the live swagger spec; this uses the
        non-deprecated method). Raises if the server reports diagnostics.

        Verified live: ApplyChangesWithDiagnostics returns
        {"parameters": {"libraryTableset": ..., "diagnostics": [...]}} --
        not the usual {"returnObj": ...} shape most other BO/Lib methods
        use. No Lock/Release/Regenerate call is made here: none appeared in
        the captured save trace this was built from, so adding one would be
        guessing rather than verifying.
        """
        safe_lib = _safe_path_component(library_id)
        safe_fn = _safe_path_component(function_id)
        func_dir = _resolve_contained_path(out_dir, safe_lib, safe_fn)

        tableset = self.get_libraries([library_id], company=company)
        functions = tableset.get("EfxFunction") or []
        row = next(
            (f for f in functions if f.get("FunctionID") == function_id and f.get("LibraryID") == library_id),
            None,
        )
        if row is None:
            raise ValueError(f"Function '{function_id}' not found in library '{library_id}'.")

        body = row.get("Body") or ""
        if not body.lstrip().startswith("<"):
            raise ValueError(
                f"Function '{function_id}' Body is not in the XML wire format; "
                "push-back for the JSON wire format isn't implemented."
            )
        root = ET.fromstring(body)

        changed = False
        new_body = body
        for step, action in _iter_custom_code_actions(root):
            if step is None:
                continue
            node_id = step.get("Id") or ""
            display_name = step.get("DisplayName") or ""
            file_name = f"{_safe_path_component(node_id)}__{_safe_path_component(display_name)}.cs"
            file_path = os.path.join(func_dir, file_name)
            if not os.path.isfile(file_path):
                continue
            with open(file_path, "r", encoding="utf-8") as f:
                new_code = f.read()
            if new_code != (action.get("Code") or ""):
                new_body = _replace_code_attribute_for_step(new_body, node_id, new_code)
                changed = True

        if not changed:
            return {"library_id": library_id, "function_id": function_id, "changed": False}

        updated_row = dict(row)
        updated_row["Body"] = new_body
        updated_row["RowMod"] = "U"

        tableset_payload = {
            "EfxLibrary": [],
            "EfxFunction": [updated_row],
            "EfxFunctionSignature": [],
            "EfxLibraryMapping": [],
            "EfxRefAssembly": [],
            "EfxRefLibrary": [],
            "EfxRefService": [],
            "EfxRefTable": [],
        }
        response = self._call(
            "ApplyChangesWithDiagnostics",
            {"libraryTableset": tableset_payload},
            company=company,
        )
        result = response.get("parameters") or {}
        diagnostics = result.get("diagnostics") or []
        if diagnostics:
            raise RuntimeError(f"ApplyChangesWithDiagnostics reported diagnostics: {diagnostics}")

        return {
            "library_id": library_id,
            "function_id": function_id,
            "changed": True,
            "diagnostics": diagnostics,
        }

    def test_function_in_pilot(
        self, library_id: str, function_id: str, params: Optional[Dict[str, Any]] = None, company: str = ""
    ) -> Dict[str, Any]:
        """Actually EXECUTE a saved function via the EFx staging endpoint --
        this runs its real C# code, side effects included (the function
        this was reverse-engineered from calls Db.SaveChanges()). Hard
        restrictions, not configurable:
          - Only runs if the resolved environment nickname is 'Pilot'.
          - Refuses to run unless both stdin and stdout are a real tty
            (never unattended/scripted/CI).
          - Requires typing the function id back as a confirmation prompt.

        Verified live (captured trace): immediately after a successful
        ApplyChangesWithDiagnostics save, the EFx Studio UI issued
        POST {instance}/api/v2/efx/staging/{company}/{libraryId} and the
        response's callertrace header decoded to an op record showing the
        function was actually invoked. NOT verified: the exact URL shape
        for naming which function and for passing parameters -- the
        captured function took no arguments (empty request body), so this
        guesses {instance}/api/v2/efx/staging/{company}/{libraryId}/{functionId}
        with params as the JSON body. Treat the first real use of this
        against a parameterized function as the verification step, not as
        already-confirmed behavior.
        """
        nickname = str(self.config.get("nickname") or "")
        if nickname.lower() != "pilot":
            raise RuntimeError(
                f"Refusing to invoke a live EFx function outside Pilot (resolved environment: '{nickname}')."
            )
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise RuntimeError(
                "Refusing to invoke a live EFx function in a non-interactive session. "
                "This executes real code with real side effects and must be run attended."
            )

        print(f"\n⚠️  About to EXECUTE '{function_id}' in library '{library_id}' on Pilot.")
        print("    This runs the function's actual C# code against real Pilot data -- not a dry run.")
        confirmation = input(f"    Type the function id ('{function_id}') to confirm, or anything else to abort: ")
        if confirmation != function_id:
            raise RuntimeError("Confirmation did not match the function id; aborted.")

        target_co = company or self.config["company"]
        url = f"{self.config['url'].rstrip('/')}/api/v2/efx/staging/{target_co}/{library_id}/{function_id}"
        return self.execute_request("POST", url, payload=params or {}, company=target_co)

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
        resolved = self.resolve_output_path(out_path)
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
            safe_id = _safe_path_component(library_id)
            try:
                out_path = _resolve_contained_path(out_dir, safe_id, f"{safe_id}.efxlib")
            except ValueError as exc:
                results.append({"library_id": library_id, "success": False, "error": str(exc)})
                continue
            try:
                # The real, unmodified library_id is still used for the API
                # call -- only the local output path is sanitized.
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

    pull_source_p = subparsers.add_parser(
        "pull-source", help="Extract a library's functions into editable .cs files under out_dir/<LibraryID>/<FunctionID>/"
    )
    pull_source_p.add_argument("library_id")
    pull_source_p.add_argument("--out-dir", required=True)

    push_source_p = subparsers.add_parser(
        "push-source", help="Push edited .cs file(s) for one function back via ApplyChangesWithDiagnostics"
    )
    push_source_p.add_argument("library_id")
    push_source_p.add_argument("function_id")
    push_source_p.add_argument("--out-dir", required=True)

    test_pilot_p = subparsers.add_parser(
        "test-pilot", help="Actually execute a saved function on Pilot (interactive confirmation required, Pilot only)"
    )
    test_pilot_p.add_argument("library_id")
    test_pilot_p.add_argument("function_id")
    test_pilot_p.add_argument("--params", help="JSON object of parameters to pass", default=None)

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
            failed = [r for r in results if not r.get("success") and not r.get("skipped")]
            print(f"✅ Exported {ok}/{len(results)} libraries to {args.out_dir}")
            for r in failed:
                print(f"  ❌ {r['library_id']}: {r.get('error')}")
            if failed:
                sys.exit(1)
        elif args.command == "import":
            result = service.import_library_from_file(args.file_path, new_library_id=args.new_library_id, overwrite_mode=args.overwrite_mode)
            errors = result.get("BOUpdError") or []
            if errors:
                print(f"⚠️  Import completed with {len(errors)} error(s): {errors}")
                sys.exit(1)
            else:
                print("✅ Import completed with no errors.")
        elif args.command == "pull-source":
            results = service.export_library_source(args.library_id, args.out_dir)
            ok = sum(1 for r in results if r.get("success"))
            failed = [r for r in results if not r.get("success")]
            print(f"✅ Pulled source for {ok}/{len(results)} function(s) to {args.out_dir}")
            for r in failed:
                print(f"  ❌ {r['function_id']}: {r.get('error')}")
            if failed:
                sys.exit(1)
        elif args.command == "push-source":
            result = service.push_function_source(args.library_id, args.function_id, args.out_dir)
            if not result.get("changed"):
                print("= No changes detected; nothing pushed.")
            else:
                print(f"✅ Pushed changes to {args.function_id}; diagnostics: {result.get('diagnostics')}")
        elif args.command == "test-pilot":
            params = json.loads(args.params) if args.params else {}
            result = service.test_function_in_pilot(args.library_id, args.function_id, params=params)
            print(f"✅ Executed. Response: {result}")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
