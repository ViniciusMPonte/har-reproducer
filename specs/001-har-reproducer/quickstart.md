# Quickstart: HAR Flow Reproducer

The HAR Flow Reproducer helps you reproduce authenticated browser sessions from a HAR file by automatically tracking dynamic tokens.

## Prerequisites

- Python 3.11+
- `uv` package manager
- `ANTHROPIC_API_KEY` environment variable set

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd token-tracker

# Initialize environment with uv
uv sync
```

## Basic Usage

### 1. Parse the HAR
First, decompose your HAR file (captured in an anonymous window) into individual steps.

```bash
uv run har-reproducer parse --har capture.har --output ./steps
```

### 2. Run the Reproduction
Execute the flow against the server. The tool will automatically detect dynamic tokens and generate extractors.

```bash
uv run har-reproducer run --har capture.har --config criteria.json
```

### 3. Analyze without executing (Dry-Run)
Simulate the process to see which tokens are dynamic and if their origins can be found.

```bash
uv run har-reproducer run --har capture.har --dry-run
```

### 4. Diagnose Failures
If a step fails, use the diagnose command to get a proposed fix from the LLM agent.

```bash
uv run har-reproducer diagnose --steps ./steps --real-responses ./real_responses
```

## Configuration (criteria.json)

Example of a composite success criterion:

```json
{
  "criteria": {
    "type": "composite",
    "conditions": [
      { "type": "status_code", "value": 200 },
      { "type": "body_contains", "value": "Welcome back, User!" },
      { "type": "html_element_present", "value": "#dashboard-main" }
    ]
  }
}
```
