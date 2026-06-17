# Quickstart: Recording Curl Requests

## Overview
The token-tracker now records every actual HTTP request made during reproduction as a `curl` command, including traceability comments for dynamic tokens.

## How to Use
Recorded requests are automatically generated during the reproduction flow.

### Viewing Recorded Requests
Curls are saved in the `curls/` directory in the following format:
`curls/req_0001.curl.sh`
`curls/req_0002.curl.sh`

Each file contains:
1. The `curl` command.
2. Shell comments (`#`) indicating which tokens were dynamic and where they came from.

Example:
```bash
# Token auth_token comes from response of step 0
curl -X POST "https://api.example.com/data" \
     -H "Authorization: Bearer ABC-123" \
     -d '{"id": "user_1"}'
```

## Verification
To verify a recorded request, you can run it directly in your terminal:
`bash curls/req_0001.curl.sh`
