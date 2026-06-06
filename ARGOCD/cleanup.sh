#!/bin/bash

kubectl delete -f argocd-app.yaml 
kubectl delete deployments,services,pods --all -n default
echo "All removed!"
