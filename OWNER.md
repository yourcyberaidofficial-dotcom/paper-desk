# Owner access

There is one owner. There is no public registration and no default password.

The owner secret is `DESK_API_TOKEN` in the server `.env`. It is not in Git.

To rotate it:
1. Generate a new token of at least 24 characters.
2. Put it in `/opt/aureon/.env` as `DESK_API_TOKEN`.
3. Restart the container.
4. Unlock the dashboard with the new token.

Sessions expire after 12 hours. Logout clears the session. Private APIs require the session or a Bearer token.
