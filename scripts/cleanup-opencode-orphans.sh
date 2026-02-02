#!/bin/bash
# OpenCode orphan process cleanup script
# Purpose: Clean up OpenCode processes without associated terminals (usually left after closing terminal)

set -e

echo "🔍 OpenCode Process Health Check"
echo "=================================="
echo ""

# Count current processes
total_processes=$(ps aux | grep opencode | grep -v grep | wc -l | xargs)
orphan_count=$(ps aux | grep opencode | grep -v grep | awk '$7 == "??"' | wc -l | xargs)

echo "📊 Current Status:"
echo "   Total processes: $total_processes"
echo "   Active sessions: $((total_processes - orphan_count))"
echo "   Orphan processes: $orphan_count"
echo ""

if [ "$orphan_count" -eq 0 ]; then
    echo "✅ No orphan processes, system healthy!"
    exit 0
fi

echo "⚠️  Found $orphan_count orphan process(es):"
echo ""
ps aux | grep opencode | grep -v grep | awk '$7 == "??" {printf "   PID: %s, CPU: %s%%, MEM: %s%%, Runtime: %s\n", $2, $3, $4, $10}'
echo ""

# Ask whether to clean up
read -p "Clean up these orphan processes? (y/N): " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "🧹 Starting cleanup..."
    ps aux | grep opencode | grep -v grep | awk '$7 == "??" {print $2}' | xargs -r kill 2>/dev/null || true
    sleep 2
    
    # Verify cleanup results
    remaining_orphans=$(ps aux | grep opencode | grep -v grep | awk '$7 == "??"' | wc -l | xargs)
    
    if [ "$remaining_orphans" -eq 0 ]; then
        echo "✅ Cleanup complete! Cleaned $orphan_count orphan process(es)"
    else
        echo "⚠️  Some processes failed to clean, $remaining_orphans orphan(s) remaining"
        echo "Attempting force cleanup..."
        ps aux | grep opencode | grep -v grep | awk '$7 == "??" {print $2}' | xargs -r kill -9 2>/dev/null || true
        sleep 1
        echo "✅ Force cleanup complete"
    fi
    
    echo ""
    echo "📊 Status after cleanup:"
    echo "   Total processes: $(ps aux | grep opencode | grep -v grep | wc -l | xargs)"
else
    echo "❌ Cleanup cancelled"
fi

echo ""
echo "💡 Tip: Run this script regularly to prevent resource leaks"
echo "   Usage: ./scripts/cleanup-opencode-orphans.sh"
