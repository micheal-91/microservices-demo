#!/bin/bash

skaffold build --default-repo=ghcr.io/micheal-91     
skaffold render --default-repo=ghcr.io/micheal-91 --output=hydrated.yaml

echo "build & render Done"
