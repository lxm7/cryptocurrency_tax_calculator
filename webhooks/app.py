"""Flask webhook receiver. Health check only for now; Stripe webhook lands week 10."""

from __future__ import annotations

from flask import Flask, Response, jsonify

app = Flask(__name__)


@app.get("/health")
def health() -> Response:
    return jsonify(status="ok")
