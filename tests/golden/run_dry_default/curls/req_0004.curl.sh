#!/bin/bash
# Token ade6a53080262635799eb7ec66e824e8 comes from response of step 3
# Token f04743b512e6241375b3226e7f7c69d3 comes from response of step 0
curl -X GET \
     'http://127.0.0.1:<PORT>/item/{{extractor:ade6a53080262635799eb7ec66e824e8}}' \
     -H 'Accept: text/html' \
     -H 'X-Trace: {{extractor:ade6a53080262635799eb7ec66e824e8}}' \
     -H 'nonce: {{extractor:f04743b512e6241375b3226e7f7c69d3}}'
