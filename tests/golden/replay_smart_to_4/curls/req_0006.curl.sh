#!/bin/bash
# [Token 19ca0711b31b0813fdab80694bdc28b1 comes from response of step 0005] origin location undetermined — using literal captured value
# [Unresolved 1] url
curl -X GET \
     http://127.0.0.1:<PORT>/use-plain \
     -H 'Accept: text/html' \
     -H 'X-Plain: {{extractor:19ca0711b31b0813fdab80694bdc28b1}}'
