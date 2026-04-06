# kinetic_devops/__init__.py
try:
    import keyring
except ImportError:
    print("Error: The 'keyring' module is not installed. Please activate the virtual environment and install the required packages.")
    print("To activate the virtual environment, run: .\\venv\\Scripts\\activate")
    print("To install the required packages, run: pip install -r requirements.txt")
    exit(1)

from importlib import import_module


_LAZY_ATTRS = {
    "KineticConfigManager": (".auth", "KineticConfigManager"),
    "KineticBaseClient": (".base_client", "KineticBaseClient"),
    "KineticMetafetcher": (".metafx", "KineticMetafetcher"),
    "KineticBAQService": (".baq", "KineticBAQService"),
    "KineticBOReaderService": (".boreader", "KineticBOReaderService"),
    "KineticFileService": (".file_service", "KineticFileService"),
    "KineticReportService": (".report_service", "KineticReportService"),
    "KineticExportAllService": (".export_all", "KineticExportAllService"),
    "KineticSolutionService": (".solutions", "KineticSolutionService"),
    "KineticZDataTableService": (".zdatatable", "KineticZDataTableService"),
}


def __getattr__(name):
    if name == "find_sensitive_data":
        module = import_module(".find_sensitive_data", __name__)
        globals()[name] = module
        return module

    target = _LAZY_ATTRS.get(name)
    if target is not None:
        module_name, attr_name = target
        module = import_module(module_name, __name__)
        value = getattr(module, attr_name)
        globals()[name] = value
        return value

    raise AttributeError(f"module 'kinetic_devops' has no attribute '{name}'")

__all__ = [
    "KineticConfigManager",
    "KineticBaseClient",
    "KineticMetafetcher",
    "KineticBAQService",
    "KineticBOReaderService",
    "KineticFileService",
    "KineticReportService",
    "KineticExportAllService",
    "KineticSolutionService",
    "KineticZDataTableService",
    "find_sensitive_data",
]