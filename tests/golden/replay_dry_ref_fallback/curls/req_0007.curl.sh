#!/bin/bash
curl -X GET \
     http://127.0.0.1:<PORT>/prefs \
     -H 'Accept: text/html'
