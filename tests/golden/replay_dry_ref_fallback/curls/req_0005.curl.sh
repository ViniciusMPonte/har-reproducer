#!/bin/bash
curl -X GET \
     http://127.0.0.1:<PORT>/plain \
     -H 'Accept: text/html'
