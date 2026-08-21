#!/bin/bash
# [Token cd0419ee5764374946a627cd3912b819 comes from response of step 0007]
# [Unresolved 1] url
curl -X GET \
     http://127.0.0.1:<PORT>/use-prefs \
     -H 'Accept: text/html' \
     --cookie 'PREFS={{extractor:cd0419ee5764374946a627cd3912b819}}'
