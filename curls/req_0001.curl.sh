#!/bin/bash
curl -X POST \
     'https://api.example.com/test' \
     -H 'Content-Type: application/json' \
     -H 'X-Test: Value' \
     --cookie 'session=123' \
     --data-binary '{"key": "value"}'
