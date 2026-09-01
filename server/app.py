"""
Task 1: Server

A minimal HTTP web server exposing:
  GET /home       -> identifies itself with a unique SERVER_ID
  GET /heartbeat  -> used by the load balancer to detect failures

The server identifier is read from the SERVER_ID environment variable so
that every replicated container can be told apart (see the assignment
hint: "Server ID can be set as an env variable while running a container
instance from the docker image of the server.").
"""
import os
from flask import Flask, jsonify

app = Flask(__name__)

SERVER_ID = os.environ.get("SERVER_ID", "unknown")


@app.route("/home", methods=["GET"])
def home():
    return jsonify({
        "message": f"Hello from Server: {SERVER_ID}",
        "status": "successful",
    }), 200


@app.route("/heartbeat", methods=["GET"])
def heartbeat():
    return "", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # waitress is a production-grade WSGI server with a real thread pool,
    # which matters since the load balancer forwards many concurrent
    # requests to each replica (see analysis/ Task 4 load tests).
    from waitress import serve
    serve(app, host="0.0.0.0", port=port, threads=32, connection_limit=500)
