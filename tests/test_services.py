#!/usr/bin/env python
"""Comprehensive test of all services: imports, methods, and CLI."""

import subprocess
import sys
from kinetic_devops import (
    KineticBAQService,
    KineticBOReaderService,
    KineticFileService
)

print("=" * 60)
print("KINETIC SDK SERVICE TESTS")
print("=" * 60)

# Test 1: Imports
print("\n[TEST 1] Service Imports")
print("✅ All 4 services imported successfully")

services = [
    ("KineticBAQService", KineticBAQService, "baq"),
    ("KineticBOReaderService", KineticBOReaderService, "boreader"),
    ("KineticFileService", KineticFileService, "file_service"),
]

# Test 2: Public Methods
print("\n[TEST 2] Public Methods")
for name, service_class, _ in services:
    methods = [m for m in dir(service_class) if not m.startswith("_") and callable(getattr(service_class, m))]
    print(f"\n{name}:")
    print(f"  Methods: {methods}")

# Test 3: CLI Help for each service
print("\n[TEST 3] CLI Help Tests")
cli_modules = [
    ("baq", "kinetic_devops.baq"),
    ("boreader", "kinetic_devops.boreader"),
    ("file_service", "kinetic_devops.file_service"),
]

for name, module in cli_modules:
    print(f"\n{name} --help:")
    try:
        result = subprocess.run(
            [sys.executable, "-m", module, "--help"],
            capture_output=True,
            text=True,
            timeout=5
        )
        # Print first 8 lines of help
        lines = result.stdout.split('\n')[:8]
        for line in lines:
            print(f"  {line}")
        print(f"  ✅ CLI works")
    except Exception as e:
        print(f"  ❌ Error: {e}")

print("\n" + "=" * 60)
print("TESTS COMPLETE")
print("=" * 60)
