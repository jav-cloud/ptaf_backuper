#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

SCHEDULE=$(python3 -c "import json; print(json.load(open('data.json')).get('backup_schedule', ''))" 2>/dev/null)

if [ -n "$SCHEDULE" ]; then
    SYSTEMD_TIMER_ONCALENDAR="$SCHEDULE"
    SYSTEMD_TIMER_ONBOOT="5min"          # Таймер после загрузки можно увеличить если птаф долго просыпается
    SYSTEMD_TIMER_PERSISTENT="true"
else
    FREQUENCY=$(python3 -c "import json; print(json.load(open('data.json')).get('backup_frequency', '1d'))" 2>/dev/null)
    if [ -z "$FREQUENCY" ]; then
        echo "ERROR: Cannot read backup_frequency from data.json"
        exit 1
    fi
    case $FREQUENCY in
        *m) SYSTEMD_INTERVAL="${FREQUENCY%m}min" ;;
        *h) SYSTEMD_INTERVAL="${FREQUENCY%h}h" ;;
        *d) SYSTEMD_INTERVAL="${FREQUENCY%d}d" ;;
        *w) SYSTEMD_INTERVAL="${FREQUENCY%w}w" ;;
        *) SYSTEMD_INTERVAL="1d" ;;
    esac
    SYSTEMD_TIMER_ONCALENDAR=""
    SYSTEMD_TIMER_ONBOOT="5min"     # Таймер после загрузки можно увеличить если птаф долго просыпается
    SYSTEMD_TIMER_PERSISTENT="true"
fi

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

cat > ptaf_backuper.timer << EOF
[Unit]
Description=PT AF Backup Timer
Requires=ptaf_backuper.service

[Timer]
OnBootSec=$SYSTEMD_TIMER_ONBOOT
EOF

if [ -n "$SYSTEMD_TIMER_ONCALENDAR" ]; then
    echo "OnCalendar=$SYSTEMD_TIMER_ONCALENDAR" >> ptaf_backuper.timer
else
    echo "OnUnitActiveSec=$SYSTEMD_INTERVAL" >> ptaf_backuper.timer
fi

cat >> ptaf_backuper.timer << EOF
Persistent=$SYSTEMD_TIMER_PERSISTENT
Unit=ptaf_backuper.service

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
