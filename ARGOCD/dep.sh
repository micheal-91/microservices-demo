#!/bin/bash
/root/git_local/git_script.sh

kubectl apply -f argocd-app.yaml 
echo "applied after sync with remote repo"
