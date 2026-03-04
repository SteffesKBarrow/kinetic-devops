# kinetic_devops/__init__.py
try:
    import keyring
except ImportError:
    print("Error: The 'keyring' module is not installed. Please activate the virtual environment and install the required packages.")
    print("To activate the virtual environment, run: .\\venv\\Scripts\\activate")
    print("To install the required packages, run: pip install -r requirements.txt")
    exit(1)

from .auth import KineticConfigManager
from .base_client import KineticBaseClient
from .metafx import KineticMetafetcher
from .baq import KineticBAQService
from .boreader import KineticBOReaderService
from .file_service import KineticFileService
from .report_service import KineticReportService
from . import find_sensitive_data

__all__ = [
    "KineticConfigManager",
    "KineticBaseClient",
    "KineticMetafetcher",
    "KineticBAQService",
    "KineticBOReaderService",
    "KineticFileService",
    "KineticReportService",
    "find_sensitive_data",
]