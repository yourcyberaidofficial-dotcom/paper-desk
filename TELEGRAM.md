# Telegram setup

Status: NOT VERIFIED.

1. Message @BotFather, /newbot, copy the token. Do not commit it.
2. /start the bot, then open https://api.telegram.org/bot<TOKEN>/getUpdates and copy chat.id.
3. Put TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env on the host.
4. POST /api/alert-test with Authorization Bearer DESK_API_TOKEN.
5. First message is SYSTEM TEST, not a trade signal.
A Telegram ok is not proof you read the message. A failed send never creates a paper trade.
