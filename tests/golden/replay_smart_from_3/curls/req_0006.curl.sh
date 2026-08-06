#!/bin/bash
# Token 19ca0711b31b0813fdab80694bdc28b1 comes from response of step 5
# Token 19ca0711b31b0813fdab80694bdc28b1 origin location undetermined — using literal captured value
curl -X GET \
     http://127.0.0.1:<PORT>/use-plain \
     -H 'Accept: text/html' \
     -H 'X-Plain: {{extractor:19ca0711b31b0813fdab80694bdc28b1}}'
