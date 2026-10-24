from flask import Flask, jsonify, request, send_from_directory
import requests

import metrolinkClient as api

app = Flask(__name__, static_folder="static")


def call_api(func, *args):
    """Run an API call and turn failures into clean JSON errors.

    requests' own error messages include the full URL (and so the API key),
    so we log only the error type and never send it to the browser.
    """
    try:
        return jsonify(func(*args))
    except api.MetrolinxError as e:
        app.logger.warning("Metrolinx API error: %s", e)
        return jsonify({"error": f"Transit API error: {e}"}), 502
    except requests.RequestException as e:
        app.logger.warning("Request to transit API failed: %s", type(e).__name__)
        return jsonify({"error": "Could not reach the transit API."}), 502


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/stops")
def stops():
    return call_api(api.get_stops)


@app.route("/api/stops/<stop_code>/destinations")
def destinations(stop_code):
    return call_api(api.get_destinations, stop_code)


@app.route("/api/stops/<stop_code>/departures")
def departures(stop_code):
    # Optional ?to=<destination id> limits results to trains heading there
    return call_api(api.get_departures, stop_code, request.args.get("to") or None)


@app.route("/api/stops/<stop_code>/details")
def details(stop_code):
    return call_api(api.get_stop_details, stop_code)


if __name__ == "__main__":
    app.run(debug=True)