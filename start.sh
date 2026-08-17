#!/bin/bash
set -e

# Configure default provider and model to Gemini 3.1 Flash Lite if not already set or fix old config
mkdir -p /opt/data
cat << 'EOF' > /opt/data/config.yaml
provider: gemini
model: gemini-3.1-flash-lite
api_key: ${GEMINI_API_KEY}
EOF

hermes gateway run
exec sleep infinity
