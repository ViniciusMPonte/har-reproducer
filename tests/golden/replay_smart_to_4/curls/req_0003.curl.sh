#!/bin/bash
# [Token 47ee3e04bc14c64ddd36aae983d6cb84 comes from response of step 0000]
# [Token d6005770b2f716bfe1c9cde542280f68 comes from response of step 0000]
# [Token b3defec11e606afd97c5430602861f32 comes from response of step 0000]
# [Unresolved 2] url; header:Content-Type
curl -X POST \
     http://127.0.0.1:<PORT>/api/do \
     -H 'Accept: text/html' \
     -H 'Content-Type: application/json' \
     -H 'X-Csrf: {{extractor:47ee3e04bc14c64ddd36aae983d6cb84}}' \
     -H 'X-Api-Header: {{extractor:d6005770b2f716bfe1c9cde542280f68}}' \
     --cookie 'SESSIONID={{extractor:b3defec11e606afd97c5430602861f32}}' \
     --data-binary '{"csrf": "{{extractor:47ee3e04bc14c64ddd36aae983d6cb84}}"}'
