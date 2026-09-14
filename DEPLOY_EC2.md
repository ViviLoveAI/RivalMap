# Deploy RivalMap to EC2

This deployment exposes the existing RivalMap application through Nginx:

```text
Internet :80 → Nginx → 127.0.0.1:8000 → Uvicorn/FastAPI → Bedrock + Exa
```

The application entry point is `server:app`. It requires Python 3.11 or newer,
serves the frontend and `/assets` itself, streams progressive events from
`POST /api/v1/runs/stream`, and reports health at `GET /health`.

## 1. Launch the instance

Launch an Ubuntu EC2 instance with an architecture supported by your chosen
instance type. For a short hackathon demo, start with at least 2 vCPU and 4 GiB RAM.

Configure its security group:

- TCP 22 from your IP only.
- TCP 80 from `0.0.0.0/0` and `::/0`.
- Do not expose port 8000.

Attach an EC2 instance role that can invoke the configured Bedrock model. The
current working model ID is the US geographic inference profile
`us.anthropic.claude-haiku-4-5-20251001-v1:0`. Replace `ACCOUNT_ID` below with
your AWS account ID:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InvokeRivalMapInferenceProfile",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": "arn:aws:bedrock:us-west-2:ACCOUNT_ID:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0"
    },
    {
      "Sid": "InvokeRivalMapFoundationModelInProfileRegions",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": "arn:aws:bedrock:us-*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0"
    }
  ]
}
```

Geographic cross-region inference requires permission for both the inference
profile and its foundation model in every possible destination region. The
model-scoped `us-*` ARN covers those US destination regions without granting
access to other models. Also ensure organization SCPs do not deny those regions.
Strands and boto3 use the standard AWS credential chain, so no static AWS keys
belong in the environment file.

## 2. Install RivalMap

SSH to the instance, then run:

```bash
sudo apt-get update
sudo apt-get install -y git nginx python3 python3-venv python3-pip
sudo useradd --system --create-home --home-dir /opt/rivalmap --shell /usr/sbin/nologin rivalmap
sudo git clone https://github.com/ViviLoveAI/RivalMap.git /opt/rivalmap
sudo chown -R rivalmap:rivalmap /opt/rivalmap
sudo -u rivalmap python3 -m venv /opt/rivalmap/.venv
sudo -u rivalmap /opt/rivalmap/.venv/bin/pip install --upgrade pip
sudo -u rivalmap /opt/rivalmap/.venv/bin/pip install /opt/rivalmap
```

## 3. Configure the protected environment

```bash
sudo install -d -m 0750 -o root -g rivalmap /etc/rivalmap
sudo install -m 0640 -o root -g rivalmap \
  /opt/rivalmap/deployment/rivalmap.env.example /etc/rivalmap/rivalmap.env
sudoedit /etc/rivalmap/rivalmap.env
```

Set the real `EXA_API_KEY`, `RIVALMAP_AWS_REGION`, and current working
`RIVALMAP_BEDROCK_MODEL_ID`. Do not add AWS access keys. The existing research
budgets and 60-second new-work deadline plus 20-second drain period remain unchanged.

## 4. Install and start the service

```bash
sudo install -m 0644 /opt/rivalmap/deployment/systemd/rivalmap.service \
  /etc/systemd/system/rivalmap.service
sudo systemctl daemon-reload
sudo systemctl enable --now rivalmap
sudo systemctl status rivalmap --no-pager
curl -fsS http://127.0.0.1:8000/health
```

Follow application logs with:

```bash
sudo journalctl -u rivalmap -f
```

## 5. Install Nginx

```bash
sudo install -m 0644 /opt/rivalmap/deployment/nginx/rivalmap.conf \
  /etc/nginx/sites-available/rivalmap
sudo ln -sfn /etc/nginx/sites-available/rivalmap /etc/nginx/sites-enabled/rivalmap
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl restart nginx
sudo systemctl status nginx --no-pager
curl -fsS http://127.0.0.1/health
```

The SSE locations use HTTP/1.1, disable proxy/request buffering, caching, and
compression, and allow 180 seconds for existing work to finish. Starting new runs
is limited per client IP; static files and continuation traffic are not rate-limited.

## 6. Verify the live demo

Test the stream from the instance:

```bash
curl -N --max-time 100 \
  -H 'Content-Type: application/json' \
  -H 'Accept: text/event-stream' \
  --data '{"idea":"AI interview coaching platform","target_user":"job seekers","problem":"practice interviews and receive feedback"}' \
  http://127.0.0.1/api/v1/runs/stream
```

Find the instance Public IPv4 DNS name in the EC2 console and open:

```text
http://EC2-PUBLIC-DNS/
http://EC2-PUBLIC-DNS/?demo=1
```

Manual smoke checklist:

- Homepage and health endpoint load.
- Run Demo and framing both start a run.
- SSE progressively adds competitors before completion.
- Product detail and evidence links open.
- Compare uses existing profiles without starting new research.
- Presentation Mode and PNG/SVG export work.
- Bedrock succeeds through the EC2 instance role.
- Exa succeeds without exposing its key in browser traffic.
- Browser console contains no application errors.

Useful recovery commands:

```bash
sudo systemctl restart rivalmap
sudo systemctl status rivalmap --no-pager
sudo journalctl -u rivalmap -n 200 --no-pager
sudo nginx -t
sudo systemctl restart nginx
```

Domain and HTTPS are optional follow-up work. They are not required for the first
public demo at `http://EC2-PUBLIC-DNS/`.
