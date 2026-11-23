#!/bin/bash
# Starts the required services and then idles. The referee plants the flag
# AFTER the container is up (see referee/referee.py plant_flag), so there is no
# flag token baked into the image.
set -e

# anonymous-FTP config (planted vuln: anon login + writable dir)
cat >/etc/vsftpd.conf <<'EOF'
listen=YES
anonymous_enable=YES
anon_root=/srv/ftp
anon_upload_enable=YES
anon_mkdir_write_enable=YES
write_enable=YES
no_anon_password=YES
EOF
mkdir -p /srv/ftp/upload && chmod 0777 /srv/ftp/upload

service ssh start
service vsftpd start
service cron start

# the web app runs as the unprivileged agent user
su agent -c 'python /opt/webapp/app.py &'

echo "host up: $(hostname)"
# keep container alive; the referee and agents drive everything via docker exec
tail -f /dev/null
