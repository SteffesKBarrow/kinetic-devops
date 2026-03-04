#!/usr/bin/env python
"""
scripts/validate.py - Quick environment and SDK validation for developers.

Usage:
    python scripts/validate.py
"""
import sys
from pathlib import Path

# Add repo root to path
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))


def main():
    """Quick validation checks."""
    print("=" * 70)
    print("KINETIC SDK QUICK VALIDATION")
    print("=" * 70)
    print()
    
    checks_passed = 0
    checks_failed = 0
    
    # 1. Python version
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    if sys.version_info >= (3, 8):
        print(f"[OK] Python {py_version}")
        checks_passed += 1
    else:
        print(f"[FAIL] Python {py_version} (requires 3.8+)")
        checks_failed += 1
    
    # 2. Import kinetic_devops
    try:
        import kinetic_devops
        print(f"[OK] kinetic_devops imports successfully")
        checks_passed += 1
    except Exception as e:
        print(f"[FAIL] Cannot import kinetic_devops: {e}")
        checks_failed += 1
        return 1
    
    # 3. Import all services
    services = [
        'KineticBAQService',
        'KineticBOReaderService',
        'KineticFileService',
    ]
    
    try:
        from kinetic_devops import (
            KineticBAQService,
            KineticBOReaderService,
            KineticFileService,
        )
        print(f"[OK] All 4 services import successfully")
        checks_passed += 1
    except Exception as e:
        print(f"[FAIL] Cannot import services: {e}")
        checks_failed += 1
        return 1
    
    # 4. Check method availability
    expected_methods = {
        'KineticBAQService': ['get_baq_results'],
        'KineticBOReaderService': ['get_list'],
        'KineticFileService': [
            'get_dms_storage_types',
            'update_dms_storage_type',
            'update_dms_storage_types',
            'set_default_storage_type',
            'get_file_service_status',
        ],
    }
    
    all_methods_ok = True
    for service_name, methods in expected_methods.items():
        service_class = getattr(kinetic_devops, service_name)
        for method in methods:
            if hasattr(service_class, method):
                pass
            else:
                print(f"[FAIL] {service_name} missing method: {method}")
                all_methods_ok = False
                checks_failed += 1
    
    if all_methods_ok:
        print(f"[OK] All service methods present")
        checks_passed += 1
    
    # 5. Check dependencies
    try:
        import requests
        print(f"[OK] requests module available")
        checks_passed += 1
    except ImportError:
        print(f"[WARN] requests module not available (may be needed at runtime)")
        # Don't fail on this, it's a runtime dependency
    
    # Summary
    print()
    print("=" * 70)
    print(f"Checks Passed: {checks_passed}")
    print(f"Checks Failed: {checks_failed}")
    print("=" * 70)
    
    if checks_failed > 0:
        print()
        print("To fix environment issues:")
        print("  1. Ensure Python 3.8+ is installed")
        print("  2. Install dependencies: pip install -r requirements.txt")
        print("  3. Verify kinetic_devops files are in the kinetic_devops/ directory")
        return 1
    
    print()
    print("Environment is ready! You can run tests with:")
    print("  python -m tests.test_runner")
    return 0


if __name__ == '__main__':
    sys.exit(main())
