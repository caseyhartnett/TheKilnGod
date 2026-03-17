#!/bin/bash
# Diagnostic script to check command execution environment
# Run this manually: bash diagnose_commands.sh

echo "=== Command Execution Diagnostic ==="
echo "Date: $(date)"
echo ""

echo "1. Basic command test:"
echo "   pwd: $(pwd)"
echo "   whoami: $(whoami)"
echo "   hostname: $(hostname)"
echo ""

echo "2. Shell information:"
echo "   SHELL: $SHELL"
echo "   BASH_VERSION: $BASH_VERSION"
echo "   PATH: $PATH"
echo ""

echo "3. Environment check:"
echo "   HOME: $HOME"
echo "   USER: $USER"
echo "   PWD: $PWD"
echo ""

echo "4. File system access:"
if [ -d "/home/bigred/TheKilnGod" ]; then
    echo "   ✓ Workspace directory exists"
    ls -ld /home/bigred/TheKilnGod 2>&1
else
    echo "   ✗ Workspace directory NOT found"
fi
echo ""

echo "5. Permission check:"
touch /home/bigred/TheKilnGod/.test_write 2>&1
if [ -f "/home/bigred/TheKilnGod/.test_write" ]; then
    echo "   ✓ Write permission OK"
    rm -f /home/bigred/TheKilnGod/.test_write
else
    echo "   ✗ Write permission FAILED"
fi
echo ""

echo "6. Command execution test:"
test_cmd="echo 'Command execution works'"
if eval "$test_cmd" > /dev/null 2>&1; then
    echo "   ✓ Command execution works"
else
    echo "   ✗ Command execution FAILED"
fi
echo ""

echo "7. Python availability:"
if command -v python3 &> /dev/null; then
    echo "   ✓ python3 found: $(which python3)"
    python3 --version 2>&1
else
    echo "   ✗ python3 NOT found"
fi
echo ""

echo "8. System information:"
echo "   OS: $(uname -a 2>&1)"
echo "   Kernel: $(uname -r 2>&1)"
echo ""

echo "9. Process information:"
echo "   PID: $$"
echo "   PPID: $PPID"
ps -p $$ -o pid,ppid,cmd 2>&1 || echo "   ps command failed"
echo ""

echo "10. Exit code test:"
exit 0


