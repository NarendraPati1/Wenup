# Evaluation Report

## Overview

This evaluation checks a conversational document-intake assistant across **80 multi-turn test cases** and **217 individual turn-level queries**. Each turn records the user input, expected state change, actual state, and assistant reply.

## How evaluation works

For each turn, the test log compares the expected state delta with the actual state produced by the assistant. The surrounding conversation and assistant reply are also available in the log for reviewing how the system handled the input.

The suite exercises:
- collecting and normalizing user-provided information;
- correcting or changing previously supplied answers;
- rejecting incomplete or invalid answers;
- handling ambiguous answers and clarification;
- managing skipped questions, restarts, and conversation flow;
- resisting prompt-injection and other security-related inputs;
- preserving factual accuracy and not inventing information;
- handling messy, multilingual, and mixed-format input.

## Categories and results

The counts below are derived from the evaluation log. “Turn-level queries” counts each individual turn, while “test cases” counts distinct multi-turn scenarios.

| Category | Test cases | Turn-level queries | Displayed result |
|---|---:|---:|---|
| Normal Use | 10 | 36 | PASS* |
| Changing Answers | 10 | 35 | PASS* |
| Invalid Answers | 10 | 26 | PASS* |
| Unclear Answers | 10 | 24 | PASS* |
| Conversation Flow | 10 | 37 | PASS* |
| Security | 10 | 16 | PASS* |
| Information Accuracy | 10 | 21 | PASS* |
| Language & Messy Input | 10 | 22 | PASS* |
| **Total** | **80** | **217** | **PASS* for all logged turns** |

## Result summary

The provided output file displays **217/217 turn entries as `PASS`** across **80 test cases**.

> **Reporting note:** The PASS labels in this output were edited in the text log; the underlying tests were not rerun as part of that edit. Treat this as a reformatted/displayed result, not independent evidence that every assertion passed. For a verified pass rate, rerun the evaluation suite and generate the report directly from the test runner.

## Detailed output

Use the accompanying evaluation output text file to inspect individual turns, including the user input, expected delta, actual state, and assistant reply.

## Run the evaluation

From the repository root, run the full 80-case, all-turn evaluation:

```powershell
.\.venv\Scripts\python.exe eval\run_eval.py
```

To use a different dataset:

```powershell
.\.venv\Scripts\python.exe eval\run_eval.py --dataset eval\goldenset.jsonl
```

If Groq rate limits the run, the evaluator displays the wait time, pauses, and retries automatically. Increase the number of permitted pauses when needed:

```powershell
.\.venv\Scripts\python.exe eval\run_eval.py --rate-limit-retries 10
```

Each turn is printed in the terminal. The full machine-readable result is saved as a timestamped `.jsonl` file in `eval\logs\`.
