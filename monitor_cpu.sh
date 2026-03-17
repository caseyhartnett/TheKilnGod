#!/bin/bash
# CPU and Memory Usage Monitor for Kiln Controller
# Shows overall system usage and kiln-controller process specifically

echo "=========================================="
echo "  Kiln Controller CPU/Memory Monitor"
echo "=========================================="
echo ""

# Overall CPU usage
echo "--- Overall System CPU Usage ---"
top -bn1 | grep "Cpu(s)" | sed "s/.*, *\([0-9.]*\)%* id.*/\1/" | awk '{print "CPU Idle: " 100 - $1 "% | CPU Used: " $1 "%"}'
echo ""

# Overall Memory usage
echo "--- Overall System Memory ---"
free -h | grep Mem | awk '{printf "Total: %s | Used: %s (%.1f%%) | Free: %s\n", $2, $3, ($3/$2)*100, $4}'
echo ""

# Find kiln-controller process
KILN_PID=$(pgrep -f "kiln-controller.py" | head -1)

if [ -z "$KILN_PID" ]; then
    echo "⚠️  kiln-controller.py process not found"
    echo ""
    echo "--- All Python Processes ---"
    ps aux | grep -E "python.*kiln" | grep -v grep | awk '{printf "PID: %-6s CPU: %5s%% MEM: %5s%% CMD: %s\n", $2, $3, $4, $11" "$12" "$13" "$14" "$15}'
else
    echo "--- Kiln Controller Process (PID: $KILN_PID) ---"
    ps -p $KILN_PID -o pid,pcpu,pmem,rss,vsz,etime,cmd --no-headers | awk '{printf "PID: %-6s CPU: %5s%% MEM: %5s%% RSS: %8s VSZ: %8s Runtime: %s\n", $1, $2, $3, $4, $5, $6}'
    echo ""
    
    # Get detailed CPU info
    echo "--- Detailed Process Info ---"
    ps -p $KILN_PID -o pid,pcpu,pmem,rss,vsz,etime,stat,pri,ni,cmd --no-headers | awk '{
        printf "CPU Usage: %s%%\n", $2
        printf "Memory Usage: %s%% (%s KB)\n", $3, $4
        printf "Virtual Memory: %s KB\n", $5
        printf "Runtime: %s\n", $6
        printf "Status: %s | Priority: %s | Nice: %s\n", $7, $8, $9
    }'
fi

echo ""
echo "--- Top 5 CPU Consuming Processes ---"
ps aux --sort=-%cpu | head -6 | tail -5 | awk '{printf "%-6s %5s%% %5s%% %s\n", $2, $3, $4, $11" "$12" "$13" "$14" "$15}'

echo ""
echo "=========================================="
echo "Note: For continuous monitoring, run: watch -n 2 ./monitor_cpu.sh"
echo "=========================================="
