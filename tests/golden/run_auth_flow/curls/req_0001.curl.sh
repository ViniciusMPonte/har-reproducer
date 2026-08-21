#!/bin/bash
# [Token cd1ab83b0d6eaa4602386d811ffa16bb comes from response of step 0000]
# [Unresolved 1] url
curl -X GET \
     http://127.0.0.1:<PORT>/protected \
     -H 'Accept: application/json' \
     -H 'Authorization: Bearer {{extractor:cd1ab83b0d6eaa4602386d811ffa16bb}}'
