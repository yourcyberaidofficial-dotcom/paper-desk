"""Paper order routes. The book stays on the desk-users volume."""

import time

from flask import Blueprint, jsonify, request

bp = Blueprint("paper_api", __name__)


@bp.get("/api/paper/book")
def paper_book():
    from ops.app import _csrf, _gate, _safe_next, _session_user, _worker_public
    user_id, _user = _session_user()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    from ops.paperbook import summary
    return jsonify(summary(user_id))


@bp.post("/api/paper/orders")
def paper_open():
    from ops.app import _csrf, _gate, _safe_next, _session_user, _worker_public
    user_id, user = _session_user()
    if not user_id or not user:
        return jsonify({"error": "unauthorized"}), 401
    from ops.paperbook import open_order, opportunity_row
    body = request.json or {}
    row = opportunity_row(user_id, body.get("opportunity_id"))
    if not row:
        return jsonify({"ok": False, "reason": "missing_opportunity"}), 404
    user["id"] = user_id
    result = open_order(user, row, int(time.time() * 1000))
    if not result.get("ok"):
        try:
            from ops.activity import record
            record(
                "risk_rejected",
                account_id=user_id,
                entity=body.get("opportunity_id"),
                component="paper",
                detail={"note": "The paper order was refused. No observation was deleted.", "reason": str(result.get("reason") or "")[:80]},
                now_ms=int(time.time() * 1000),
            )
        except Exception:
            pass
    return jsonify(result), (200 if result.get("ok") else 409)


@bp.post("/api/paper/close")
def paper_close():
    from ops.app import _csrf, _gate, _safe_next, _session_user, _worker_public
    user_id, _user = _session_user()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    from ops.paperbook import close_order
    body = request.json or {}
    result = close_order(user_id, body.get("order_id"), body.get("exit_price"), int(time.time() * 1000))
    return jsonify(result), (200 if result.get("ok") else 409)
