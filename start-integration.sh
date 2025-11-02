#!/bin/bash

# Start LG WebOS Integration for Remote Two
# This script sets the correct network interface for mDNS discovery

# Get the LAN IP address automatically (192.168.x.x or 10.x.x.x)
LAN_IP=$(ifconfig | grep "inet " | grep -v "127.0.0.1" | grep -E "192\.168\.|10\." | awk '{print $2}' | head -1)

if [ -z "$LAN_IP" ]; then
    echo "❌ Error: Could not find LAN IP address"
    echo "Please check your network connection"
    exit 1
fi

echo "🌐 Using network interface: $LAN_IP"

# Check for and kill any existing driver processes
if pgrep -f "driver.py" > /dev/null; then
    echo "⚠️  Stopping existing driver processes..."
    pkill -9 -f "driver.py"
    sleep 2
fi

echo "🚀 Starting LG WebOS integration..."
echo ""

# Navigate to integration directory
cd "$(dirname "$0")" || exit 1

# Export environment variables and start the driver
export UC_EXTERNAL=true
export UC_INTEGRATION_INTERFACE=$LAN_IP

# Start the integration
uv run python ./src/driver.py

