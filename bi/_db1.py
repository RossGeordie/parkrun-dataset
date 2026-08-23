import json
from superset import create_app
app = create_app()
with app.app_context():
    from superset.models.core import Dashboard
    d = Dashboard.query.get(1)
    print("TITLE", d.dashboard_title)
    print("PUB", d.published)
    print("CHARTS", [(c.id, c.slice_name) for c in d.charts])
    p = json.loads(d.position_json or "{}")
    print("POSK", list(p.keys()))
    print("POS", json.dumps(p)[:800])
