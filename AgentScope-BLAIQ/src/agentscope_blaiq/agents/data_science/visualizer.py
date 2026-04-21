"""Visualizer — Chart and plot generation for data analysis."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from io import BytesIO
from pathlib import Path
from typing import Any

from agentscope_blaiq.contracts.evidence import Visualization

logger = logging.getLogger(__name__)


class Visualizer:
    """Generate visualizations from data analysis results.

    Supports multiple output formats: PNG, SVG, HTML (interactive)
    """

    def __init__(self, output_dir: str | None = None):
        """Initialize visualizer.

        Args:
            output_dir: Directory for saving visualization files
        """
        self.output_dir = Path(output_dir) if output_dir else None
        if self.output_dir:
            self.output_dir.mkdir(parents=True, exist_ok=True)

    def create_summary_chart(
        self,
        data: dict[str, Any],
        title: str = "Data Summary",
    ) -> Visualization:
        """Create a summary visualization of the dataset.

        Args:
            data: Dict with 'columns' and 'data' keys
            title: Chart title

        Returns:
            Visualization object
        """
        viz_id = f"viz_summary_{hashlib.md5(title.encode()).hexdigest()[:8]}"

        # Generate plotly JSON for interactive rendering
        plotly_json = self._generate_summary_plotly(data, title)

        # Create visualization metadata
        viz = Visualization(
            viz_id=viz_id,
            viz_type="summary",
            title=title,
            description=f"Overview of dataset with {data.get('row_count', 0)} rows and {data.get('column_count', 0)} columns",
            file_path=str(self.output_dir / f"{viz_id}.html") if self.output_dir else f"/tmp/{viz_id}.html",
            file_type="html",
            data_summary=f"Dataset summary: {data.get('row_count', 0)} rows",
            plotly_json=plotly_json,
        )

        return viz

    def create_bar_chart(
        self,
        categories: list[str],
        values: list[float],
        title: str = "Bar Chart",
        x_label: str = "Category",
        y_label: str = "Value",
    ) -> Visualization:
        """Create a bar chart visualization.

        Args:
            categories: List of category labels
            values: List of corresponding values
            title: Chart title
            x_label: X-axis label
            y_label: Y-axis label

        Returns:
            Visualization object
        """
        viz_id = f"viz_bar_{hashlib.md5(title.encode()).hexdigest()[:8]}"

        plotly_json = {
            "data": [
                {
                    "type": "bar",
                    "x": categories,
                    "y": values,
                    "marker": {"color": "#4F46E5"},
                }
            ],
            "layout": {
                "title": {"text": title},
                "xaxis": {"title": x_label},
                "yaxis": {"title": y_label},
                "template": "plotly_white",
            },
        }

        viz = Visualization(
            viz_id=viz_id,
            viz_type="bar",
            title=title,
            description=f"Bar chart comparing {len(categories)} categories",
            file_path=str(self.output_dir / f"{viz_id}.html") if self.output_dir else f"/tmp/{viz_id}.html",
            file_type="html",
            data_summary=f"Categories: {len(categories)}, Value range: {min(values):.2f} - {max(values):.2f}",
            plotly_json=plotly_json,
        )

        return viz

    def create_line_chart(
        self,
        x_values: list[str | float],
        y_values: list[float],
        title: str = "Line Chart",
        x_label: str = "X",
        y_label: str = "Y",
    ) -> Visualization:
        """Create a line chart visualization.

        Args:
            x_values: X-axis values
            y_values: Y-axis values
            title: Chart title
            x_label: X-axis label
            y_label: Y-axis label

        Returns:
            Visualization object
        """
        viz_id = f"viz_line_{hashlib.md5(title.encode()).hexdigest()[:8]}"

        plotly_json = {
            "data": [
                {
                    "type": "scatter",
                    "x": x_values,
                    "y": y_values,
                    "mode": "lines+markers",
                    "line": {"color": "#4F46E5", "width": 2},
                }
            ],
            "layout": {
                "title": {"text": title},
                "xaxis": {"title": x_label},
                "yaxis": {"title": y_label},
                "template": "plotly_white",
            },
        }

        viz = Visualization(
            viz_id=viz_id,
            viz_type="line",
            title=title,
            description=f"Line chart showing trend across {len(x_values)} points",
            file_path=str(self.output_dir / f"{viz_id}.html") if self.output_dir else f"/tmp/{viz_id}.html",
            file_type="html",
            data_summary=f"Data points: {len(x_values)}, Y range: {min(y_values):.2f} - {max(y_values):.2f}",
            plotly_json=plotly_json,
        )

        return viz

    def create_scatter_plot(
        self,
        x_values: list[float],
        y_values: list[float],
        title: str = "Scatter Plot",
        x_label: str = "X",
        y_label: str = "Y",
    ) -> Visualization:
        """Create a scatter plot visualization.

        Args:
            x_values: X-axis values
            y_values: Y-axis values
            title: Chart title
            x_label: X-axis label
            y_label: Y-axis label

        Returns:
            Visualization object
        """
        viz_id = f"viz_scatter_{hashlib.md5(title.encode()).hexdigest()[:8]}"

        plotly_json = {
            "data": [
                {
                    "type": "scatter",
                    "x": x_values,
                    "y": y_values,
                    "mode": "markers",
                    "marker": {"color": "#4F46E5", "size": 8, "opacity": 0.6},
                }
            ],
            "layout": {
                "title": {"text": title},
                "xaxis": {"title": x_label},
                "yaxis": {"title": y_label},
                "template": "plotly_white",
            },
        }

        viz = Visualization(
            viz_id=viz_id,
            viz_type="scatter",
            title=title,
            description=f"Scatter plot with {len(x_values)} points",
            file_path=str(self.output_dir / f"{viz_id}.html") if self.output_dir else f"/tmp/{viz_id}.html",
            file_type="html",
            data_summary=f"Points: {len(x_values)}, X range: {min(x_values):.2f} - {max(x_values):.2f}",
            plotly_json=plotly_json,
        )

        return viz

    def create_histogram(
        self,
        values: list[float],
        title: str = "Histogram",
        x_label: str = "Value",
        bins: int = 20,
    ) -> Visualization:
        """Create a histogram visualization.

        Args:
            values: Data values
            title: Chart title
            x_label: X-axis label
            bins: Number of bins

        Returns:
            Visualization object
        """
        viz_id = f"viz_hist_{hashlib.md5(title.encode()).hexdigest()[:8]}"

        plotly_json = {
            "data": [
                {
                    "type": "histogram",
                    "x": values,
                    "nbinsx": bins,
                    "marker": {"color": "#4F46E5"},
                }
            ],
            "layout": {
                "title": {"text": title},
                "xaxis": {"title": x_label},
                "yaxis": {"title": "Frequency"},
                "template": "plotly_white",
            },
        }

        viz = Visualization(
            viz_id=viz_id,
            viz_type="histogram",
            title=title,
            description=f"Histogram distribution with {bins} bins",
            file_path=str(self.output_dir / f"{viz_id}.html") if self.output_dir else f"/tmp/{viz_id}.html",
            file_type="html",
            data_summary=f"Values: {len(values)}, Range: {min(values):.2f} - {max(values):.2f}",
            plotly_json=plotly_json,
        )

        return viz

    def create_correlation_heatmap(
        self,
        correlation_matrix: dict[str, dict[str, float]],
        title: str = "Correlation Matrix",
    ) -> Visualization:
        """Create a correlation heatmap visualization.

        Args:
            correlation_matrix: Nested dict of correlations
            title: Chart title

        Returns:
            Visualization object
        """
        viz_id = f"viz_corr_{hashlib.md5(title.encode()).hexdigest()[:8]}"

        columns = list(correlation_matrix.keys())
        z_values = [[correlation_matrix.get(c1, {}).get(c2, 0) for c2 in columns] for c1 in columns]

        plotly_json = {
            "data": [
                {
                    "type": "heatmap",
                    "z": z_values,
                    "x": columns,
                    "y": columns,
                    "colorscale": "RdBu",
                    "zmid": 0,
                }
            ],
            "layout": {
                "title": {"text": title},
                "xaxis": {"title": ""},
                "yaxis": {"title": ""},
                "template": "plotly_white",
            },
        }

        viz = Visualization(
            viz_id=viz_id,
            viz_type="heatmap",
            title=title,
            description=f"Correlation heatmap for {len(columns)} variables",
            file_path=str(self.output_dir / f"{viz_id}.html") if self.output_dir else f"/tmp/{viz_id}.html",
            file_type="html",
            data_summary=f"Variables: {len(columns)}, Correlation matrix {len(columns)}x{len(columns)}",
            plotly_json=plotly_json,
        )

        return viz

    def _generate_summary_plotly(self, data: dict[str, Any], title: str) -> dict:
        """Generate a summary plotly visualization."""
        columns = data.get("columns", [])
        row_count = data.get("row_count", 0)

        # Create a simple bar chart of column count
        return {
            "data": [
                {
                    "type": "indicator",
                    "mode": "number+gauge",
                    "value": row_count,
                    "title": {"text": "Total Rows"},
                    "gauge": {"shape": "bullet"},
                }
            ],
            "layout": {
                "title": {"text": title},
                "template": "plotly_white",
            },
        }

    def render_to_html(self, viz: Visualization) -> str:
        """Render visualization to full HTML string.

        Args:
            viz: Visualization object with plotly_json

        Returns:
            Complete HTML string
        """
        if not viz.plotly_json:
            return f"<div>No plotly data for {viz.viz_id}</div>"

        plotly_html = json.dumps(viz.plotly_json)

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>{viz.title}</title>
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
    <style>
        body {{ font-family: system-ui, sans-serif; margin: 20px; }}
        #chart {{ max-width: 1000px; margin: 0 auto; }}
        h2 {{ color: #1f2937; }}
        .description {{ color: #6b7280; margin-bottom: 20px; }}
    </style>
</head>
<body>
    <h2>{viz.title}</h2>
    <p class="description">{viz.description}</p>
    <div id="chart"></div>
    <script>
        var data = {plotly_html};
        Plotly.newPlot('chart', data.data, data.layout);
    </script>
</body>
</html>
"""
        return html
