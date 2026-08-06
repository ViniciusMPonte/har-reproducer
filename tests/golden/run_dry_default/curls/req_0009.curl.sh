#!/bin/bash
# Token 3a2dd5b363bd0701c13a2da19b03abc9 comes from response of step 3
curl -X POST \
     http://127.0.0.1:<PORT>/submit \
     -H 'Accept: text/html' \
     -H 'Content-Type: {{extractor:3a2dd5b363bd0701c13a2da19b03abc9}}' \
     --data-binary '{"a": 1}'
