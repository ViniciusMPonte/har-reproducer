# Data Model: Record Curl Requests

## Entities

### RecordedRequest
Represents a captured HTTP interaction for reproduction.
- `step_index`: int (The index of the step in the flow)
- `url`: str
- `method`: str
- `headers`: dict[str, str]
- `cookies`: dict[str, str]
- `body`: Optional[str]
- `token_traces`: list[TokenTrace]

### TokenTrace
Maps a specific value in the request to its source.
- `token_id`: str (The ID of the dynamic token)
- `value`: str (The actual value inserted)
- `origin_step`: int (The index of the response that provided this value)
- `location`: TokenLocation (Header, Cookie, or Body)
- `key`: str (The header name or cookie name where the token was used)
