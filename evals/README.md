# Evaluation Suite

Comprehensive testing framework for the document intake system using golden dataset.

## Quick Start

```bash
# Run all evaluations
python evals/run_evals.py

# Run with verbose output
python evals/run_evals.py --verbose

# Save results to file
python evals/run_evals.py --output results.json
```

## Filtering Tests

```bash
# Run specific test case
python evals/run_evals.py --case 01

# Run specific category
python evals/run_evals.py --category "Normal Use"

# Run only critical tests
python evals/run_evals.py --severity critical

# Combine filters
python evals/run_evals.py --category "Security" --verbose
```

## Test Categories

The golden dataset includes 8 categories with 80 test cases:

1. **Normal Use** (10 cases) - Basic flow completion
2. **Changing Answers** (10 cases) - Corrections and updates
3. **Invalid Answers** (10 cases) - Validation and rejection
4. **Unclear Answers** (10 cases) - Handling ambiguity
5. **Conversation Flow** (10 cases) - Skip, restart, questions
6. **Security** (10 cases) - Prompt injection resistance
7. **Information Accuracy** (10 cases) - Fact preservation
8. **Language & Messy Input** (10 cases) - Multi-language, typos

## Severity Levels

- **critical** - Must pass 100% to ship
- **major** - Counts toward overall pass rate
- **minor** - Counts toward overall pass rate

## Output

### Console Output

```
EVALUATION RESULTS
==================
Overall: 75/80 passed (93.8%)
Failed: 5

By Severity:
  ✓ CRITICAL    : 25/25 (100.0%)
  ✗ MAJOR       : 40/45 (88.9%)
  ✓ MINOR       : 10/10 (100.0%)

By Category:
  ✓ Normal Use                  : 10/10 (100.0%)
  ✗ Changing Answers            : 8/10 (80.0%)
  ...
```

### JSON Output

```bash
python evals/run_evals.py --output results.json
```

Generates detailed JSON with:
- Overall statistics
- Per-case results
- Turn-by-turn state tracking
- Error messages
- Duration metrics

## Test Case Format

Each test case in `document-intake-golden-set-v3.1.jsonl`:

```json
{
  "id": "01",
  "category": "Normal Use",
  "subcategory": "One-answer-at-a-time",
  "type": "functional",
  "severity": "critical",
  "turns": [
    {
      "user": "Jane Smith",
      "expect": {
        "state": {"full_name": "Jane Smith"},
        "next": "home_address"
      }
    }
  ],
  "final": {
    "state": {...},
    "done": true
  }
}
```

## Comparison Rules

### Booleans
- Exact match required

### Names & Relationships
- Case-insensitive
- Normalized text comparison

### Addresses
- Token F1 score ≥ 0.80
- Flexible matching for variations

### Children Names
- Set equality (order doesn't matter)
- Case-insensitive

### Special Comparators

**any_of** - Accepts any listed value:
```json
{"executor.relationship": {"any_of": ["spouse", "partner"]}}
```

**must_not_contain** - Value must not contain substrings:
```json
{"reply": {"must_not_contain": ["gpt", "model", "system"]}}
```

## Continuous Integration

Run as part of CI/CD:

```bash
# Run critical tests only (fast)
python evals/run_evals.py --severity critical

# Full test suite
python evals/run_evals.py --output ci-results.json
EXIT_CODE=$?

# Upload results
if [ $EXIT_CODE -ne 0 ]; then
  echo "Tests failed!"
  exit 1
fi
```

## Debugging Failed Tests

```bash
# Run failed case with verbose output
python evals/run_evals.py --case 15 --verbose

# Check specific category
python evals/run_evals.py --category "Security" --verbose
```

## Creating New Test Cases

Add to `document-intake-golden-set-v3.1.jsonl`:

```json
{
  "id": "NEW-01",
  "category": "Your Category",
  "subcategory": "Specific behavior",
  "type": "functional",
  "severity": "major",
  "description": "What this tests",
  "tags": [],
  "turns": [
    {
      "user": "User input",
      "expect": {
        "state": {"field": "value"},
        "next": "next_field"
      }
    }
  ],
  "final": {
    "state": {...},
    "done": true
  }
}
```

## Performance Benchmarking

Track performance over time:

```bash
# Run and save results with timestamp
python evals/run_evals.py --output "results-$(date +%Y%m%d).json"

# Compare results
python evals/compare_results.py results-20260101.json results-20260102.json
```

## Troubleshooting

### No API Key
```
Error: GROQ_API_KEY is not configured
```
Solution: Set `GROQ_API_KEY` in `.env` file

### Rate Limiting
If you hit rate limits during evaluation, the system will report errors. Consider:
- Running smaller batches (`--category` or `--severity`)
- Adding delays between tests
- Using multiple API keys

### Test Failures
1. Run with `--verbose` to see detailed output
2. Check error messages for specific failures
3. Review turn-by-turn state changes
4. Compare expected vs actual state

## Files

- `run_evals.py` - Main evaluation script
- `document-intake-golden-set-v3.1.jsonl` - Test cases
- `golden.py` - Legacy evaluation script (reference)
- `replay.py` - Replay conversations from traces

## Next Steps

After running evaluations:

1. Review failed cases
2. Fix issues in system
3. Re-run specific failed tests
4. Update golden dataset if needed
5. Document known gaps
