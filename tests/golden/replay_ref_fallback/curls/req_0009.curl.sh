#!/bin/bash
# [Static 1] header:Content-Type←0003
# [Unresolved 1] url
curl -X POST \
     http://127.0.0.1:<PORT>/submit \
     -H 'Accept: text/html' \
     -H 'Content-Type: application/json' \
     --data-binary '{"a": 1}'
