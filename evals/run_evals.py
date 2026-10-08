"""
Evaluation script for document intake system.
Runs the system against the golden dataset and reports results.

Usage:
    python evals/run_evals.py                    # Run all test cases
    python evals/run_evals.py --case 01          # Run specific case
    python evals/run_evals.py --category "Normal Use"  # Run category
    python evals/run_evals.py --severity critical # Run only critical tests
    python evals/run_evals.py --verbose          # Show detailed output
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import defaultdict

# Add parent directory to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from backend.llm import Gateway, GroqProvider, Settings
from backend.engine import Intake
from backend.observability import CallLog, tracer


# ============================================================================
# Test Case Loading
# ============================================================================

def load_golden_dataset(path: Path) -> tuple[dict, List[dict]]:
    """Load golden dataset from JSONL file."""
    with open(path, encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]
    
    meta = lines[0] if lines and "_meta" in lines[0] else {}
    cases = [line for line in lines[1:] if "_meta" not in line]
    
    return meta, cases


# ============================================================================
# Comparators
# ============================================================================

def normalize_text(text: str) -> str:
    """Normalize text for comparison."""
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def tokens_from_text(text: str) -> set:
    """Extract tokens from text."""
    return set(re.findall(r"[\w'-]+", text.lower()))


def address_f1_score(actual: str, expected: str) -> float:
    """Calculate token F1 score for addresses."""
    actual_tokens = tokens_from_text(actual)
    expected_tokens = tokens_from_text(expected)
    
    if not actual_tokens and not expected_tokens:
        return 1.0
    if not actual_tokens or not expected_tokens:
        return 0.0
    
    intersection = len(actual_tokens & expected_tokens)
    precision = intersection / len(actual_tokens) if actual_tokens else 0
    recall = intersection / len(expected_tokens) if expected_tokens else 0
    
    if precision + recall == 0:
        return 0.0
    
    return 2 * (precision * recall) / (precision + recall)


def compare_values(actual: Any, expected: Any, field: str) -> tuple[bool, str]:
    """
    Compare actual vs expected values with field-specific rules.
    Returns: (passed, reason)
    """
    # Handle None/empty
    if expected is None or expected == "" or expected == []:
        if actual is None or actual == "" or actual == []:
            return True, "Both empty"
        return False, f"Expected empty, got {actual}"
    
    # Handle any_of comparator
    if isinstance(expected, dict) and "any_of" in expected:
        for option in expected["any_of"]:
            passed, _ = compare_values(actual, option, field)
            if passed:
                return True, f"Matched option: {option}"
        return False, f"None of {expected['any_of']} matched {actual}"
    
    # Handle must_not_contain
    if isinstance(expected, dict) and "must_not_contain" in expected:
        forbidden = expected["must_not_contain"]
        actual_str = str(actual).lower()
        for substring in forbidden:
            if substring.lower() in actual_str:
                return False, f"Contains forbidden substring: {substring}"
        
        # Check value if present
        if "value" in expected:
            return compare_values(actual, expected["value"], field)
        return True, "No forbidden substrings"
    
    # Booleans: exact match
    if isinstance(expected, bool):
        if actual == expected:
            return True, "Boolean match"
        return False, f"Expected {expected}, got {actual}"
    
    # Home address: token F1 >= 0.80
    if field == "home_address":
        if not isinstance(actual, str) or not isinstance(expected, str):
            return False, f"Address must be string"
        
        f1 = address_f1_score(actual, expected)
        if f1 >= 0.80:
            return True, f"Address F1={f1:.2f}"
        return False, f"Address F1={f1:.2f} < 0.80"
    
    # Names and relationships: case-folded exact match
    if field in ("full_name", "executor.name", "executor.relationship"):
        if normalize_text(str(actual)) == normalize_text(str(expected)):
            return True, "Text match"
        return False, f"Expected '{expected}', got '{actual}'"
    
    # Children names: set equality
    if field == "children_names":
        if not isinstance(actual, list) or not isinstance(expected, list):
            return False, "Must be lists"
        
        actual_norm = set(normalize_text(name) for name in actual)
        expected_norm = set(normalize_text(name) for name in expected)
        
        if actual_norm == expected_norm:
            return True, "Children set match"
        return False, f"Expected {expected_norm}, got {actual_norm}"
    
    # Default: exact match
    if actual == expected:
        return True, "Exact match"
    return False, f"Expected {expected}, got {actual}"


# ============================================================================
# State Comparison
# ============================================================================

def get_nested_value(state: dict, path: str) -> Any:
    """Get value from nested dict using dot notation."""
    parts = path.split(".")
    value = state
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def check_state_delta(actual_state: dict, expected_delta: dict) -> tuple[bool, List[str]]:
    """
    Check if actual state contains expected delta.
    Returns: (all_passed, list of failures)
    """
    failures = []
    
    for field, expected_value in expected_delta.items():
        actual_value = get_nested_value(actual_state, field)
        
        passed, reason = compare_values(actual_value, expected_value, field)
        
        if not passed:
            failures.append(f"{field}: {reason}")
    
    return len(failures) == 0, failures


# ============================================================================
# Test Runner
# ============================================================================

class TestResult:
    def __init__(self, case_id: str, category: str, severity: str):
        self.case_id = case_id
        self.category = category
        self.severity = severity
        self.passed = False
        self.turn_results = []
        self.total_turns = 0
        self.passed_turns = 0
        self.errors = []
        self.duration_ms = 0


def run_test_case(case: dict, verbose: bool = False) -> TestResult:
    """Run a single test case."""
    result = TestResult(case["id"], case["category"], case["severity"])
    result.total_turns = len(case["turns"])
    
    if verbose:
        print(f"\n{'='*60}")
        print(f"Case {case['id']}: {case['subcategory']}")
        print(f"{'='*60}")
    
    # Initialize intake
    try:
        settings = Settings.from_env()
        log = CallLog()
        provider = GroqProvider(settings.api_keys, settings.timeout)
        gateway = Gateway(provider, settings, log=log, tracer=tracer)
        intake = Intake(gateway, log=log, tracer=tracer)
    except Exception as e:
        result.errors.append(f"Setup failed: {e}")
        return result
    
    # Start conversation
    try:
        start_time = time.time()
        intake.start()
        
        # Run each turn
        for turn_idx, turn in enumerate(case["turns"]):
            user_msg = turn["user"]
            expected = turn["expect"]
            
            if verbose:
                print(f"\nTurn {turn_idx + 1}:")
                print(f"  User: {user_msg}")
            
            try:
                # Send message
                reply = intake.handle(user_msg)
                
                if verbose:
                    print(f"  Bot: {reply}")
                
                # Check expected state delta
                if "state" in expected:
                    passed, failures = check_state_delta(intake.state, expected["state"])
                    
                    if passed:
                        result.passed_turns += 1
                        if verbose:
                            print(f"  ✓ State check passed")
                    else:
                        if verbose:
                            print(f"  ✗ State check failed:")
                            for failure in failures:
                                print(f"      {failure}")
                        result.errors.extend(failures)
                
                # Check next field
                if "next" in expected:
                    expected_next = expected["next"]
                    actual_next = intake.sess.target({})
                    
                    # Handle any_of for next
                    if isinstance(expected_next, dict) and "any_of" in expected_next:
                        if actual_next in expected_next["any_of"]:
                            if verbose:
                                print(f"  ✓ Next field: {actual_next}")
                        else:
                            error = f"Next field: expected one of {expected_next['any_of']}, got {actual_next}"
                            result.errors.append(error)
                            if verbose:
                                print(f"  ✗ {error}")
                    else:
                        if actual_next == expected_next:
                            if verbose:
                                print(f"  ✓ Next field: {actual_next}")
                        else:
                            error = f"Next field: expected {expected_next}, got {actual_next}"
                            result.errors.append(error)
                            if verbose:
                                print(f"  ✗ {error}")
                
                # Store turn result
                result.turn_results.append({
                    "turn": turn_idx + 1,
                    "user": user_msg,
                    "reply": reply,
                    "state": dict(intake.state),
                    "passed": passed if "state" in expected else None
                })
                
            except Exception as e:
                error = f"Turn {turn_idx + 1} failed: {str(e)}"
                result.errors.append(error)
                if verbose:
                    print(f"  ✗ {error}")
        
        result.duration_ms = int((time.time() - start_time) * 1000)
        
        # Check final state
        if "final" in case:
            final = case["final"]
            if "state" in final:
                passed, failures = check_state_delta(intake.state, final["state"])
                if not passed:
                    result.errors.extend([f"Final: {f}" for f in failures])
            
            if "done" in final:
                if intake.done() != final["done"]:
                    result.errors.append(f"Final: done={intake.done()}, expected {final['done']}")
        
        # Overall pass if no errors
        result.passed = len(result.errors) == 0
        
    except Exception as e:
        result.errors.append(f"Test execution failed: {e}")
    
    return result


# ============================================================================
# Reporting
# ============================================================================

def print_summary(results: List[TestResult], meta: dict):
    """Print test results summary."""
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    
    # By severity
    by_severity = defaultdict(lambda: {"total": 0, "passed": 0})
    for r in results:
        by_severity[r.severity]["total"] += 1
        if r.passed:
            by_severity[r.severity]["passed"] += 1
    
    # By category
    by_category = defaultdict(lambda: {"total": 0, "passed": 0})
    for r in results:
        by_category[r.category]["total"] += 1
        if r.passed:
            by_category[r.category]["passed"] += 1
    
    print("\n" + "="*60)
    print("EVALUATION RESULTS")
    print("="*60)
    print(f"\nOverall: {passed}/{total} passed ({passed/total*100:.1f}%)")
    print(f"Failed: {failed}")
    
    print("\n" + "-"*60)
    print("By Severity:")
    print("-"*60)
    for severity in ["critical", "major", "minor"]:
        if severity in by_severity:
            s = by_severity[severity]
            pct = s["passed"]/s["total"]*100 if s["total"] > 0 else 0
            status = "✓" if s["passed"] == s["total"] else "✗"
            print(f"  {status} {severity.upper():10s}: {s['passed']}/{s['total']} ({pct:.1f}%)")
    
    print("\n" + "-"*60)
    print("By Category:")
    print("-"*60)
    for cat, stats in sorted(by_category.items()):
        pct = stats["passed"]/stats["total"]*100 if stats["total"] > 0 else 0
        status = "✓" if stats["passed"] == stats["total"] else "✗"
        print(f"  {status} {cat:30s}: {stats['passed']}/{stats['total']} ({pct:.1f}%)")
    
    # Failed cases
    if failed > 0:
        print("\n" + "-"*60)
        print("Failed Cases:")
        print("-"*60)
        for r in results:
            if not r.passed:
                print(f"  ✗ {r.case_id} ({r.severity}): {r.category}")
                for error in r.errors[:3]:  # Show first 3 errors
                    print(f"      - {error}")
                if len(r.errors) > 3:
                    print(f"      ... and {len(r.errors) - 3} more errors")
    
    print("\n" + "="*60)


def save_results(results: List[TestResult], output_file: Path):
    """Save detailed results to JSON file."""
    output = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(results),
        "passed": sum(1 for r in results if r.passed),
        "failed": sum(1 for r in results if not r.passed),
        "results": [
            {
                "case_id": r.case_id,
                "category": r.category,
                "severity": r.severity,
                "passed": r.passed,
                "duration_ms": r.duration_ms,
                "turns": r.total_turns,
                "passed_turns": r.passed_turns,
                "errors": r.errors,
                "turn_results": r.turn_results
            }
            for r in results
        ]
    }
    
    with open(output_file, "w") as f:
        json.dump(output, f, indent=2)
    
    print(f"\nDetailed results saved to: {output_file}")


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Run document intake evaluations")
    parser.add_argument("--case", help="Run specific case ID")
    parser.add_argument("--category", help="Run specific category")
    parser.add_argument("--severity", help="Run only tests of this severity", choices=["critical", "major", "minor"])
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    parser.add_argument("--output", "-o", help="Save results to JSON file")
    
    args = parser.parse_args()
    
    # Load dataset
    dataset_path = ROOT / "evals" / "document-intake-golden-set-v3.1.jsonl"
    if not dataset_path.exists():
        print(f"Error: Dataset not found at {dataset_path}")
        sys.exit(1)
    
    meta, all_cases = load_golden_dataset(dataset_path)
    
    print(f"Loaded {len(all_cases)} test cases from golden dataset")
    print(f"Dataset version: {meta.get('_meta', {}).get('version', 'unknown')}")
    
    # Filter cases
    cases = all_cases
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            print(f"Error: Case {args.case} not found")
            sys.exit(1)
    
    if args.category:
        cases = [c for c in cases if c["category"] == args.category]
        if not cases:
            print(f"Error: No cases found for category '{args.category}'")
            sys.exit(1)
    
    if args.severity:
        cases = [c for c in cases if c["severity"] == args.severity]
    
    print(f"Running {len(cases)} test case(s)...\n")
    
    # Run tests
    results = []
    for i, case in enumerate(cases, 1):
        if not args.verbose:
            print(f"[{i}/{len(cases)}] Running case {case['id']}: {case['subcategory']}...", end=" ")
        
        result = run_test_case(case, verbose=args.verbose)
        results.append(result)
        
        if not args.verbose:
            status = "✓" if result.passed else "✗"
            print(f"{status}")
    
    # Print summary
    print_summary(results, meta)
    
    # Save results if requested
    if args.output:
        save_results(results, Path(args.output))
    
    # Exit code
    sys.exit(0 if all(r.passed for r in results) else 1)


if __name__ == "__main__":
    main()
