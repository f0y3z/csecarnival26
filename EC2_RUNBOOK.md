# EC2 Deployment Runbook

This is the simple non-Docker deployment path for the hackathon API.

## 1. Launch EC2

Use Ubuntu on a small instance. Open inbound TCP port `8000` in the security group.

## 2. Install System Packages

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip git
```

## 3. Get The Code

```bash
git clone YOUR_REPOSITORY_URL csecarnival26
cd csecarnival26
```

If the code is already uploaded, just `cd` into the project directory.

## 4. Install Python Dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 5. Configure Environment

Replace `YOUR_EC2_PUBLIC_IP` with the actual public IPv4 address.

```bash
export DJANGO_SECRET_KEY='replace-with-any-long-random-string'
export DJANGO_DEBUG=false
export DJANGO_ALLOWED_HOSTS='YOUR_EC2_PUBLIC_IP,localhost,127.0.0.1'
```

## 6. Verify Django

```bash
cd backend
python manage.py check
python manage.py test
```

## 7. Start The API With Gunicorn

```bash
gunicorn support_copilot.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 30
```

Submission base URL:

```text
http://YOUR_EC2_PUBLIC_IP:8000
```

Judge endpoints:

```text
http://YOUR_EC2_PUBLIC_IP:8000/health
http://YOUR_EC2_PUBLIC_IP:8000/analyze-ticket
```

## 8. Keep It Running With systemd

Copy `deploy/questorm.service.example` to `/etc/systemd/system/questorm.service`, then edit:

- `User`
- `WorkingDirectory`
- `Environment`
- `ExecStart`

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable questorm
sudo systemctl start questorm
sudo systemctl status questorm
```

View logs:

```bash
sudo journalctl -u questorm -f
```

## Quick Smoke Test

```bash
curl http://YOUR_EC2_PUBLIC_IP:8000/health
```

Expected:

```json
{"status":"ok"}
```
