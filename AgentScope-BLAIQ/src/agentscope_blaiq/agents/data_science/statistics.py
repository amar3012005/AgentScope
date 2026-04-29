"""Statistics engine — Statistical analysis utilities."""

from __future__ import annotations

import logging
from typing import Any

from agentscope_blaiq.contracts.evidence import StatisticalResult

logger = logging.getLogger(__name__)


class StatisticsEngine:
    """Statistical analysis engine for data science workflows.

    Provides descriptive statistics, correlation analysis, and hypothesis testing.
    """

    def compute_descriptive(self, data: dict[str, Any]) -> list[StatisticalResult]:
        """Compute descriptive statistics for numeric columns.

        Args:
            data: Dict with 'columns' and 'data' keys

        Returns:
            List of StatisticalResult objects
        """
        if not data.get("data"):
            return []

        results = []
        columns = data.get("columns", [])
        rows = data.get("data", [])

        for col in columns:
            values = self._extract_numeric_values(rows, col)

            if not values:
                continue

            try:
                n = len(values)
                mean = sum(values) / n
                variance = sum((x - mean) ** 2 for x in values) / (n - 1) if n > 1 else 0
                std = variance ** 0.5
                sorted_values = sorted(values)
                median = sorted_values[n // 2] if n % 2 else (sorted_values[n // 2 - 1] + sorted_values[n // 2]) / 2

                results.append(StatisticalResult(
                    stat_type="descriptive",
                    test_name=f"Descriptive Statistics: {col}",
                    result_dict={
                        "count": n,
                        "mean": round(mean, 4),
                        "std": round(std, 4),
                        "min": round(min(values), 4),
                        "max": round(max(values), 4),
                        "median": round(median, 4),
                    },
                    interpretation=f"{col}: mean={mean:.2f}, std={std:.2f}, median={median:.2f}",
                ))
            except Exception as exc:
                logger.warning("Failed to compute descriptive stats for %s: %s", col, exc)

        return results

    def compute_correlation(self, data: dict[str, Any]) -> list[StatisticalResult]:
        """Compute correlation matrix for numeric columns.

        Args:
            data: Dict with 'columns' and 'data' keys

        Returns:
            List of StatisticalResult objects with correlation coefficients
        """
        if not data.get("data"):
            return []

        results = []
        columns = data.get("columns", [])
        rows = data.get("data", [])

        # Extract numeric columns
        numeric_cols = {}
        for col in columns:
            values = self._extract_numeric_values(rows, col)
            if len(values) >= 3:
                numeric_cols[col] = values

        # Compute pairwise correlations
        col_names = list(numeric_cols.keys())
        for i, col1 in enumerate(col_names):
            for col2 in col_names[i+1:]:
                values1 = numeric_cols[col1]
                values2 = numeric_cols[col2]

                # Align lengths
                min_len = min(len(values1), len(values2))
                values1 = values1[:min_len]
                values2 = values2[:min_len]

                try:
                    # Pearson correlation
                    mean1, mean2 = sum(values1) / len(values1), sum(values2) / len(values2)
                    numerator = sum((v1 - mean1) * (v2 - mean2) for v1, v2 in zip(values1, values2))
                    denom1 = sum((v1 - mean1) ** 2 for v1 in values1) ** 0.5
                    denom2 = sum((v2 - mean2) ** 2 for v2 in values2) ** 0.5

                    if denom1 > 0 and denom2 > 0:
                        r = numerator / (denom1 * denom2)

                        # Approximate p-value (for large n)
                        t_stat = r * ((len(values1) - 2) / (1 - r ** 2 + 1e-10)) ** 0.5
                        p_value = 2 * (1 - min(abs(t_stat) / 10, 1))  # Rough approximation

                        results.append(StatisticalResult(
                            stat_type="correlation",
                            test_name=f"Pearson Correlation: {col1} vs {col2}",
                            result_dict={
                                "r": round(r, 4),
                                "p_value": round(p_value, 4),
                                "n": len(values1),
                            },
                            interpretation=f"Correlation between {col1} and {col2}: r={r:.3f}, p={p_value:.3f}",
                            effect_size=abs(r),
                        ))
                except Exception as exc:
                    logger.warning("Failed to compute correlation: %s", exc)

        return results

    def perform_t_test(
        self,
        group1: list[float],
        group2: list[float],
        group1_name: str = "Group 1",
        group2_name: str = "Group 2",
    ) -> StatisticalResult:
        """Perform independent samples t-test.

        Args:
            group1: Values for group 1
            group2: Values for group 2
            group1_name: Label for group 1
            group2_name: Label for group 2

        Returns:
            StatisticalResult with t-statistic and p-value
        """
        n1, n2 = len(group1), len(group2)

        if n1 < 2 or n2 < 2:
            return StatisticalResult(
                stat_type="inferential",
                test_name="Independent t-test",
                result_dict={"error": "Insufficient sample size"},
                interpretation="T-test requires at least 2 samples per group",
            )

        mean1 = sum(group1) / n1
        mean2 = sum(group2) / n2

        var1 = sum((x - mean1) ** 2 for x in group1) / (n1 - 1)
        var2 = sum((x - mean2) ** 2 for x in group2) / (n2 - 1)

        # Pooled standard error
        se = ((var1 / n1) + (var2 / n2)) ** 0.5

        if se > 0:
            t_stat = (mean1 - mean2) / se
            # Approximate p-value
            df = n1 + n2 - 2
            p_value = 2 * (1 - min(abs(t_stat) / 5, 1))  # Rough approximation
        else:
            t_stat = 0
            p_value = 1.0

        return StatisticalResult(
            stat_type="inferential",
            test_name=f"Independent t-test: {group1_name} vs {group2_name}",
            result_dict={
                "t": round(t_stat, 4),
                "p_value": round(p_value, 4),
                "df": df,
                "mean1": round(mean1, 4),
                "mean2": round(mean2, 4),
            },
            interpretation=f"Mean difference: {mean1 - mean2:.3f}, t({df})={t_stat:.2f}, p={p_value:.3f}",
            effect_size=abs(t_stat) / (df ** 0.5) if df > 0 else 0,
        )

    def _extract_numeric_values(self, rows: list[dict], column: str) -> list[float]:
        """Extract numeric values from a column."""
        values = []
        for row in rows:
            val = row.get(column)
            if val is not None:
                try:
                    values.append(float(val))
                except (ValueError, TypeError):
                    pass
        return values
