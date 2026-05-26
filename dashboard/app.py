"""Dash example for parkron data. Replace with Dash, Streamlit, etc."""
import dash
from dash import html

app = dash.Dash(__name__)

app.layout = html.Div([
    html.H1("Parkron Dashboard"),
    html.P("Replace this with your reporting framework.")
])

if __name__ == "__main__":
    app.run(debug=True)
