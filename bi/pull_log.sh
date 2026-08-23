#!/bin/sh
sshpass -p 'R0ss@2026' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8 root@10.21.63.187 'docker logs --tail 200 superset 2>&1 | grep -iE "traceback|error|exception|sqlalchemy|invalid|column|relation" | grep -viE "error_type|GET|POST" | tail -30'
