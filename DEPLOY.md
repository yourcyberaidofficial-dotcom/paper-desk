# Deployment

Not deployed. No public URL.

Inside the container the app listens on 0.0.0.0:8080. Compose forces DESK_BIND.
On the host, Compose publishes only 127.0.0.1:8080. Port 8080 is not open to the internet.

Access from your laptop:

    ssh -L 8080:127.0.0.1:8080 user@your-vps

Then open http://127.0.0.1:8080 on your laptop.

HTTPS later: Caddy or nginx on the VPS proxies to 127.0.0.1:8080. Do not change the Compose mapping to 0.0.0.0:8080.

Required in .env on the server only:
- DESK_API_TOKEN at least 24 characters. Shorter or empty disables private routes (503).
- TELEGRAM_BOT_TOKEN optional.
- TELEGRAM_CHAT_ID optional.

Do not set DESK_BIND in .env.

Hetzner CX23 is about 5.99 EUR/month. Render free is unsuitable.
