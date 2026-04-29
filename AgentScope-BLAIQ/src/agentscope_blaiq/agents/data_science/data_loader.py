"""Data loader — Load and parse data from various sources."""

from __future__ import annotations

import json
import logging
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class DataLoader:
    """Load data from CSV, Excel, JSON, and database sources.

    Usage:
        loader = DataLoader()
        df_dict = loader.load_csv("file.csv")
        df_dict = loader.load_excel("file.xlsx")
    """

    def load_csv(self, file_path: str | Path) -> dict[str, Any]:
        """Load CSV file into dictionary representation.

        Args:
            file_path: Path to CSV file

        Returns:
            Dict with 'columns', 'data', 'row_count' keys
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"CSV file not found: {file_path}")

        try:
            import pandas as pd
            df = pd.read_csv(file_path)
            return self._df_to_dict(df)
        except ImportError:
            # Fallback without pandas
            return self._load_csv_basic(file_path)

    def load_excel(self, file_path: str | Path, sheet: str | int = 0) -> dict[str, Any]:
        """Load Excel file into dictionary representation.

        Args:
            file_path: Path to Excel file
            sheet: Sheet name or index (default: first sheet)

        Returns:
            Dict with 'columns', 'data', 'row_count' keys
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Excel file not found: {file_path}")

        try:
            import pandas as pd
            df = pd.read_excel(file_path, sheet_name=sheet)
            return self._df_to_dict(df)
        except ImportError:
            logger.warning("pandas not available, Excel loading limited")
            raise NotImplementedError("Excel loading requires pandas")

    def load_json(self, file_path: str | Path) -> dict[str, Any]:
        """Load JSON file into dictionary representation.

        Args:
            file_path: Path to JSON file

        Returns:
            Dict with 'columns', 'data', 'row_count' keys
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"JSON file not found: {file_path}")

        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)

        # Handle list of dicts
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return self._records_to_dict(data)

        # Handle single dict
        if isinstance(data, dict):
            return self._records_to_dict([data])

        raise ValueError("JSON must be a list of records or a single object")

    def load_from_bytes(self, content: bytes, file_type: str) -> dict[str, Any]:
        """Load data from bytes content.

        Args:
            content: Raw bytes content
            file_type: 'csv', 'excel', or 'json'

        Returns:
            Dict with 'columns', 'data', 'row_count' keys
        """
        try:
            import pandas as pd

            if file_type == "csv":
                df = pd.read_csv(BytesIO(content))
            elif file_type == "excel":
                df = pd.read_excel(BytesIO(content))
            elif file_type == "json":
                data = json.loads(content.decode())
                if isinstance(data, list):
                    return self._records_to_dict(data)
                return self._records_to_dict([data])
            else:
                raise ValueError(f"Unsupported file type: {file_type}")

            return self._df_to_dict(df)

        except ImportError:
            if file_type == "csv":
                return self._load_csv_basic_bytes(content)
            raise

    def _df_to_dict(self, df) -> dict[str, Any]:
        """Convert pandas DataFrame to dictionary representation."""
        return {
            "columns": list(df.columns),
            "data": df.to_dict(orient="records"),
            "row_count": len(df),
            "column_count": len(df.columns),
            "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
        }

    def _records_to_dict(self, records: list[dict]) -> dict[str, Any]:
        """Convert list of dicts to dictionary representation."""
        if not records:
            return {"columns": [], "data": [], "row_count": 0, "column_count": 0}

        columns = list(records[0].keys())
        return {
            "columns": columns,
            "data": records,
            "row_count": len(records),
            "column_count": len(columns),
        }

    def _load_csv_basic(self, file_path: Path) -> dict[str, Any]:
        """Load CSV without pandas (basic implementation)."""
        rows = []
        with open(file_path, encoding="utf-8") as f:
            lines = f.readlines()

        if not lines:
            return {"columns": [], "data": [], "row_count": 0}

        # Parse header
        header = lines[0].strip().split(",")

        # Parse data rows
        for line in lines[1:]:
            if line.strip():
                values = line.strip().split(",")
                if len(values) == len(header):
                    rows.append(dict(zip(header, values)))

        return self._records_to_dict(rows)

    def _load_csv_basic_bytes(self, content: bytes) -> dict[str, Any]:
        """Load CSV from bytes without pandas."""
        import io

        rows = []
        content_io = io.StringIO(content.decode("utf-8"))
        lines = content_io.readlines()

        if not lines:
            return {"columns": [], "data": [], "row_count": 0}

        header = lines[0].strip().split(",")

        for line in lines[1:]:
            if line.strip():
                values = line.strip().split(",")
                if len(values) == len(header):
                    rows.append(dict(zip(header, values)))

        return self._records_to_dict(rows)

    def infer_schema(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Infer schema from loaded data.

        Args:
            data: Dict from load_* methods

        Returns:
            List of column schema dicts
        """
        if not data.get("data"):
            return []

        columns = data.get("columns", [])
        rows = data.get("data", [])
        dtypes = data.get("dtypes", {})

        schema = []

        for col in columns:
            values = [row.get(col) for row in rows if row.get(col) is not None]

            # Infer data type
            if col in dtypes:
                dtype_str = dtypes[col].lower()
                if "int" in dtype_str or "float" in dtype_str:
                    data_type = "numeric"
                elif "datetime" in dtype_str:
                    data_type = "datetime"
                else:
                    data_type = "categorical"
            else:
                # Infer from values
                data_type = self._infer_type(values)

            # Compute statistics for numeric columns
            statistics = None
            if data_type == "numeric" and values:
                try:
                    numeric_values = [float(v) for v in values if v is not None]
                    if numeric_values:
                        statistics = {
                            "min": min(numeric_values),
                            "max": max(numeric_values),
                            "mean": sum(numeric_values) / len(numeric_values),
                        }
                except (ValueError, TypeError):
                    pass

            schema.append({
                "column_name": col,
                "data_type": data_type,
                "nullable": any(row.get(col) is None for row in rows),
                "unique_count": len(set(values)),
                "sample_values": [str(v) for v in values[:3]],
                "statistics": statistics,
            })

        return schema

    def _infer_type(self, values: list) -> str:
        """Infer data type from sample values."""
        if not values:
            return "text"

        # Check if numeric
        numeric_count = 0
        for v in values[:10]:
            try:
                float(v)
                numeric_count += 1
            except (ValueError, TypeError):
                pass

        if numeric_count > len(values[:10]) * 0.8:
            return "numeric"

        # Check if datetime
        datetime_count = 0
        for v in values[:10]:
            if isinstance(v, str) and len(v) > 8:
                # Basic date pattern check
                if any(p in str(v) for p in ["-", "/", "T", ":"]):
                    datetime_count += 1

        if datetime_count > len(values[:10]) * 0.8:
            return "datetime"

        # Check cardinality for categorical
        unique_ratio = len(set(str(v) for v in values[:100])) / min(len(values[:100]), 1)
        if unique_ratio < 0.1:
            return "categorical"

        return "text"
