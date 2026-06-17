#!/bin/bash
curl -X POST \
     'https://api.example.com/test' \
     -H 'Authorization: Bearer secret_abc' \
     # Token session_id comes from response of step 1 \
     --cookie 'JSESSIONID=sess_123' \
     # Token auth_token comes from response of step 0 \
     --data-binary '{"token": "secret_abc"}'
