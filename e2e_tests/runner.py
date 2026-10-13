"""
AeroPulse Tactical Test Runner (`e2e_tests/runner.py`)

Unified CLI test runner with tactical styling, tier filtering, JSON report generation,
and deterministic exit codes.
"""

import sys
import os
import time
import json
import argparse
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
E2E_DIR = PROJECT_ROOT / "e2e_tests"

# Tactical ANSI styling
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_banner():
    banner = f"""{CYAN}{BOLD}
+----------------------------------------------------------------------------+
|     A E R O P U L S E   |   E 2 E   T E S T   R U N N E R                  |
|     Requirement-Driven, Opaque-Box Automated Verification Track            |
+----------------------------------------------------------------------------+{RESET}"""
    print(banner)


class AeroPulseTestCollector:
    """Custom pytest plugin to capture structured test execution metrics."""
    
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.errors = 0
        self.tests = []
        self.start_time = None
        self.end_time = None

    def pytest_sessionstart(self, session):
        self.start_time = time.time()

    def pytest_sessionfinish(self, session, exitstatus):
        self.end_time = time.time()

    def pytest_runtest_logreport(self, report):
        if report.when == "call":
            if report.passed:
                self.passed += 1
                status = "PASSED"
            elif report.failed:
                self.failed += 1
                status = "FAILED"
            elif report.skipped:
                self.skipped += 1
                status = "SKIPPED"
            else:
                status = "UNKNOWN"
                
            self.tests.append({
                "nodeid": report.nodeid,
                "duration": report.duration,
                "status": status,
                "error": str(report.longrepr) if report.failed else None
            })
        elif report.when in ["setup", "teardown"] and report.failed:
            self.errors += 1
            self.tests.append({
                "nodeid": report.nodeid,
                "duration": report.duration,
                "status": "ERROR",
                "error": str(report.longrepr)
            })
        elif report.when == "setup" and report.skipped:
            self.skipped += 1
            self.tests.append({
                "nodeid": report.nodeid,
                "duration": report.duration,
                "status": "SKIPPED",
                "error": str(report.longrepr)
            })


def run_tests(args) -> int:
    print_banner()
    
    pytest_args = []
    
    if args.verbose:
        pytest_args.append("-v")
    else:
        pytest_args.append("--tb=short")
        
    if args.filter:
        pytest_args.extend(["-k", args.filter])
        
    # Determine target test files based on tier selection
    if args.tier == "1":
        target = str(E2E_DIR / "test_tier1_features.py")
        tier_label = "Tier 1 (Feature Isolation)"
    elif args.tier == "2":
        target = str(E2E_DIR / "test_tier2_boundaries.py")
        tier_label = "Tier 2 (Boundaries, Corner Cases, SLA Benchmark)"
    elif args.tier == "3":
        target = str(E2E_DIR / "test_tier3_pairwise.py")
        tier_label = "Tier 3 (Pairwise Cross-Feature Interactions)"
    elif args.tier == "4":
        target = str(E2E_DIR / "test_tier4_workloads.py")
        tier_label = "Tier 4 (End-to-End Workloads & Realistic Scenarios)"
    else:
        target = str(E2E_DIR)
        tier_label = "All Tiers (1 through 4)"
        
    pytest_args.append(target)
    
    print(f"[*] Target Scope: {BOLD}{tier_label}{RESET}")
    print(f"[*] Working Directory: {PROJECT_ROOT}")
    print(f"[*] Pytest Invocation: pytest {' '.join(pytest_args)}\n")
    
    collector = AeroPulseTestCollector()
    exit_code = pytest.main(pytest_args, plugins=[collector])
    
    duration = (collector.end_time - collector.start_time) if (collector.end_time and collector.start_time) else 0.0
    
    # Summary report
    print("\n" + "=" * 76)
    print(f"{BOLD}AEROPULSE E2E VERIFICATION SUMMARY{RESET}")
    print("=" * 76)
    print(f"Total Tests Executed: {len(collector.tests)}")
    print(f"{GREEN}Passed:  {collector.passed}{RESET}")
    print(f"{YELLOW}Skipped: {collector.skipped} (Progression signal for pending milestones){RESET}")
    print(f"{RED}Failed:  {collector.failed}{RESET}")
    print(f"{RED}Errors:  {collector.errors}{RESET}")
    print(f"Execution Duration:  {duration:.2f}s")
    print("=" * 76)
    
    if collector.failed == 0 and collector.errors == 0:
        print(f"\n{GREEN}{BOLD}[STATUS: PASSED] All executed verification contracts satisfied.{RESET}\n")
    else:
        print(f"\n{RED}{BOLD}[STATUS: FAILED] Verification defects detected. Check logs above.{RESET}\n")
        
    # Optional JSON export
    if args.json_report:
        report_data = {
            "timestamp": time.time(),
            "tier": args.tier,
            "duration_seconds": duration,
            "summary": {
                "total": len(collector.tests),
                "passed": collector.passed,
                "skipped": collector.skipped,
                "failed": collector.failed,
                "errors": collector.errors
            },
            "tests": collector.tests
        }
        with open(args.json_report, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)
        print(f"[+] Exported JSON report to: {args.json_report}")
        
    return exit_code


def main():
    parser = argparse.ArgumentParser(description="AeroPulse Tactical E2E Test Runner")
    parser.add_argument("--tier", choices=["1", "2", "3", "4", "all"], default="all",
                        help="Target test tier to execute (default: all)")
    parser.add_argument("--all", action="store_true", help="Run all test tiers")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose test output")
    parser.add_argument("-k", "--filter", type=str, default="", help="Pytest keyword expression filter")
    parser.add_argument("--json-report", type=str, default=None, help="File path to write JSON execution summary")
    
    args = parser.parse_args()
    if args.all:
        args.tier = "all"
        
    sys.exit(run_tests(args))


if __name__ == "__main__":
    main()
