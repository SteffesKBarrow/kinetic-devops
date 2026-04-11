"""Shared CLI entrypoint matrix for regression tests."""

CLI_MODULES = [
    {"module": "auth", "script": "auth.py", "router": "auth"},
    {"module": "baq", "script": "baq.py", "router": "baq"},
    {"module": "boreader", "script": "boreader.py", "router": None},
    {"module": "efx", "script": "efx.py", "router": "efx"},
    {"module": "export_all", "script": "export_all.py", "router": "export"},
    {"module": "file_service", "script": "file_service.py", "router": None},
    {"module": "find_sensitive_data", "script": "find_sensitive_data.py", "router": "find"},
    {"module": "metafx", "script": "metafx.py", "router": "meta"},
    {"module": "report_service", "script": "report_service.py", "router": "report"},
    {"module": "repo_maker", "script": "repo_maker.py", "router": None},
    {"module": "solutions", "script": "solutions.py", "router": "solutions"},
    {"module": "zdatatable", "script": "zdatatable.py", "router": "zdatatable"},
]

ROUTER_TOOLS = [item for item in CLI_MODULES if item["router"]]
