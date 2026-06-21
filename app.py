from flask import Flask, render_template, request, jsonify
from database import init_db, list_scenarios, load_scenario, save_scenario, delete_scenario
from calculations import calculate_pension_plan

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/scenarios", methods=["GET"])
def api_list_scenarios():
    return jsonify(list_scenarios())


@app.route("/api/scenarios", methods=["POST"])
def api_create_scenario():
    data = request.json
    sid = save_scenario(data["name"], data["params"])
    return jsonify({"id": sid})


@app.route("/api/scenarios/<int:sid>", methods=["GET"])
def api_get_scenario(sid):
    s = load_scenario(sid)
    if not s:
        return jsonify({"error": "not found"}), 404
    return jsonify(s)


@app.route("/api/scenarios/<int:sid>", methods=["PUT"])
def api_update_scenario(sid):
    data = request.json
    save_scenario(data["name"], data["params"], scenario_id=sid)
    return jsonify({"ok": True})


@app.route("/api/scenarios/<int:sid>", methods=["DELETE"])
def api_delete_scenario(sid):
    delete_scenario(sid)
    return jsonify({"ok": True})


@app.route("/api/calculate", methods=["POST"])
def api_calculate():
    params = request.json
    result = calculate_pension_plan(params)
    return jsonify(result)


@app.route("/api/compare", methods=["POST"])
def api_compare():
    ids = request.json.get("ids", [])
    results = []
    for sid in ids[:2]:
        s = load_scenario(int(sid))
        if s:
            r = calculate_pension_plan(s["params"])
            r["name"] = s["name"]
            r["id"] = s["id"]
            results.append(r)
    return jsonify(results)


if __name__ == "__main__":
    init_db()
    print("Rentensimulation läuft auf http://localhost:5000")
    app.run(debug=True, port=5000)
