#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

FREQUENCY=$(python3 -c "import json; print(json.load(open('data.json')).get('backup_frequency', '1d'))" 2>/dev/null)
if [ -z "$FREQUENCY" ]; then
    echo "ERROR: Cannot read backup_frequency from data.json"
    exit 1
fi

# Convert frequency to systemd format
case $FREQUENCY in
    *m) SYSTEMD_INTERVAL="${FREQUENCY%m}min" ;;
    *h) SYSTEMD_INTERVAL="${FREQUENCY%h}h" ;;
    *d) SYSTEMD_INTERVAL="${FREQUENCY%d}d" ;;
    *w) SYSTEMD_INTERVAL="${FREQUENCY%w}w" ;;
    *) SYSTEMD_INTERVAL="1d" ;;
esac

SERVICE_USER=$(whoami)

# Create service file
cat > ptaf_backuper.service << EOF
[Unit]
Description=PT AF Configuration Backup
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=$SCRIPT_DIR/start.sh
WorkingDirectory=$SCRIPT_DIR
User=$SERVICE_USER
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Create timer file
cat > ptaf_backuper.timer << EOF
[Unit]
Description=PT AF Backup Timer
Requires=ptaf_backuper.service

[Timer]
OnUnitActiveSec=$SYSTEMD_INTERVAL
OnBootSec=5min
Unit=ptaf_backuper.service
Persistent=true

[Install]
WantedBy=timers.target
EOF

echo "Installing to systemd..."
cp ptaf_backuper.service /etc/systemd/system/
cp ptaf_backuper.timer /etc/systemd/system/

echo "Reloading systemd..."
systemctl daemon-reload

echo "Enabling and starting timer..."
systemctl enable --now ptaf_backuper.timer

echo ""
echo "Installation complete"
echo ""
echo "Status:"
systemctl status ptaf_backuper.timer --no-pager
echo ""
echo "Logs:"
echo "  journalctl -u ptaf_backuper.service -f"
echo "  tail -f $SCRIPT_DIR/backup.log"
