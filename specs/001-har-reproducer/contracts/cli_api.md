# Interface Contract: CLI API

The HAR Flow Reproducer exposes three primary subcommands.

## 1. `parse`
**Purpose**: Decomposes a HAR file into a sequence of step files.

**Command**: `har-reproducer parse --har <path_to_har> --output <output_dir>`

**Inputs**:
- `--har`: Path to a valid `.har` file.
- `--output`: Directory where `req_NNNN.json` and `res_NNNN.json` will be stored.

**Outputs**:
- A directory containing indexed JSON files.
- Stdout: `Parsed HAR into N steps.`

---

## 2. `run`
**Purpose**: Reproduces the HTTP flow and validates success.

**Command**: `har-reproducer run --har <path_to_har> [--dry-run] [--config <criteria_file>]`

**Inputs**:
- `--har`: Path to the original `.har` file.
- `--dry-run`: Optional. If present, simulates token tracking using HAR responses without network calls.
- `--config`: Optional. Path to JSON/YAML file defining `SuccessCriteria`.

**Outputs**:
- `real_responses/` directory with live results.
- `curls/` directory with rendered shell scripts.
- `extractors/` directory with Python extractor functions.
- Stdout: Progress of each step and final success/failure status.

---

## 3. `diagnose`
**Purpose**: Analyzes a failed step and proposes a fix.

**Command**: `har-reproducer diagnose --steps <steps_dir> --real-responses <responses_dir>`

**Inputs**:
- `--steps`: Path to the decomposed steps directory.
- `--real-responses`: Path to the live responses directory.

**Outputs**:
- Stdout: A proposed `Patch` (fix for extractor or manual value injection) and its rationale.

---

## Internal Contract: Extractor Signature

All generated extractors MUST implement the following interface:

```python
def extract_<token_id>(response: dict) -> str:
    """
    Args:
        response: A dictionary containing:
            - 'headers': dict[str, str]
            - 'cookies': dict[str, str]
            - 'body': str
            - 'body_mime': str
            - 'redirect_url': str | None
    Returns:
        The extracted token value as a string.
    Raises:
        ExtractorError: If the value cannot be found in the response.
    """
```
