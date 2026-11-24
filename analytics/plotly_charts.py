"""Optional Plotly figure builders for reports/exports."""
from __future__ import annotations

from .risk_service import risk_report_rows


def risk_distribution_figure():
    import plotly.graph_objects as go

    rows = risk_report_rows()
    counts = {'low': 0, 'medium': 0, 'high': 0, 'unassessed': 0}
    for row in rows:
        counts[row['risk_level']] = counts.get(row['risk_level'], 0) + 1

    fig = go.Figure(
        data=[
            go.Pie(
                labels=['On track', 'Need attention', 'High risk', 'Unassessed'],
                values=[counts['low'], counts['medium'], counts['high'], counts['unassessed']],
                hole=0.45,
                marker_colors=['#0f6e56', '#b86e00', '#b42318', '#9aa7b5'],
            )
        ]
    )
    fig.update_layout(title='Risk distribution', margin=dict(l=20, r=20, t=50, b=20))
    return fig


def top_risk_bar_figure(limit: int = 10):
    import plotly.express as px
    import pandas as pd

    rows = [r for r in risk_report_rows() if r['failure_risk'] is not None][:limit]
    df = pd.DataFrame(rows)
    if df.empty:
        import plotly.graph_objects as go

        return go.Figure()
    fig = px.bar(
        df,
        x='name',
        y='failure_risk',
        color='risk_level',
        title='Top failure-risk learners',
        labels={'failure_risk': 'Failure risk %', 'name': 'Student'},
        color_discrete_map={'low': '#0f6e56', 'medium': '#b86e00', 'high': '#b42318'},
    )
    fig.update_layout(xaxis_tickangle=-30, margin=dict(l=20, r=20, t=50, b=80))
    return fig
