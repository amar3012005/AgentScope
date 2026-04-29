"""Financial data MCP client interface.

Provides an abstract base class and concrete implementations for accessing
financial data sources via MCP (Model Context Protocol). Designed to be
extensible with additional providers (tdx-mcp, qieman-mcp, etc.).

Usage:
    # Register financial data clients
    from agentscope_blaiq.runtime.hivemind_mcp import HivemindMCPClient
    from agentscope_blaiq.agents.deep_research.finance_data import FinancialDataClient

    # Primary: HIVE-MIND for internal knowledge
    hivemind = HivemindMCPClient(...)

    # Optional: Specialized financial data (tdx-mcp for stock data)
    # tdx = TdxFinancialClient(...)  # Future extension

    # Use in FinanceDeepResearchAgent
    agent = FinanceDeepResearchAgent(hivemind=hivemind)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FinancialDataPoint:
    """A single financial data point.

    Attributes:
        symbol: Stock ticker or company identifier
        metric: The metric name (e.g., "revenue", "net_income", "pe_ratio")
        value: Numeric value
        currency: Currency code (e.g., "USD", "CNY")
        period: Time period (e.g., "2024-Q4", "2024-Annual")
        source: Data source name
        timestamp: ISO timestamp of data retrieval
    """
    symbol: str
    metric: str
    value: float
    currency: str
    period: str
    source: str
    timestamp: str


@dataclass
class FinancialDocument:
    """A financial document (filing, report, etc.).

    Attributes:
        doc_id: Unique identifier
        doc_type: Type (e.g., "10-K", "10-Q", "earnings_call")
        company: Company name or symbol
        filing_date: Date of filing
        url: URL or path to document
        summary: Brief summary
    """
    doc_id: str
    doc_type: str
    company: str
    filing_date: str
    url: str
    summary: str


class FinancialDataClientBase(ABC):
    """Abstract base class for financial data MCP clients.

    Implement this class for each financial data source (tdx-mcp, qieman-mcp, etc.).
    """

    @abstractmethod
    async def get_metric(self, symbol: str, metric: str, period: str | None = None) -> FinancialDataPoint | None:
        """Fetch a specific financial metric.

        Args:
            symbol: Stock ticker or company identifier
            metric: Metric name (e.g., "revenue", "net_income")
            period: Optional time period (latest if None)

        Returns:
            FinancialDataPoint if found, None otherwise
        """
        pass

    @abstractmethod
    async def get_company_profile(self, symbol: str) -> dict[str, Any] | None:
        """Get company profile and key information.

        Args:
            symbol: Stock ticker or company identifier

        Returns:
            Dictionary with company info, or None if not found
        """
        pass

    @abstractmethod
    async def search_filings(self, query: str, company: str | None = None) -> list[FinancialDocument]:
        """Search financial filings and reports.

        Args:
            query: Search query
            company: Optional company filter

        Returns:
            List of matching financial documents
        """
        pass

    @abstractmethod
    async def get_peer_comparison(self, symbol: str, metrics: list[str]) -> dict[str, Any]:
        """Get comparative metrics across peer companies.

        Args:
            symbol: Primary company symbol
            metrics: List of metrics to compare

        Returns:
            Dictionary with peer comparison data
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the name of this data source."""
        pass


class HivemindFinancialClient(FinancialDataClientBase):
    """Financial data client using HIVE-MIND MCP.

    Routes financial queries through HIVE-MIND which aggregates:
    - Internal enterprise knowledge (past analyses, stored reports)
    - Web search via Tavily for current market data
    - Document retrieval for uploaded financial filings
    """

    def __init__(self, hivemind_client: Any) -> None:
        """Initialize with HIVE-MIND MCP client.

        Args:
            hivemind_client: Configured HivemindMCPClient instance
        """
        self.hivemind = hivemind_client

    @property
    def name(self) -> str:
        return "HIVE-MIND Financial"

    async def get_metric(self, symbol: str, metric: str, period: str | None = None) -> FinancialDataPoint | None:
        """Fetch financial metric via HIVE-MIND recall."""
        query = f"{symbol} {metric}"
        if period:
            query += f" {period}"

        try:
            result = await self.hivemind.recall(query=query, limit=5, mode="quick")
            # Parse result for metric value
            # This is a simplified implementation - would need NLP extraction
            logger.info("HIVE-MIND metric query '%s' returned result", query)
            return None  # Placeholder - HIVE-MIND returns unstructured text
        except Exception as exc:
            logger.warning("HIVE-MIND metric fetch failed for %s %s: %s", symbol, metric, exc)
            return None

    async def get_company_profile(self, symbol: str) -> dict[str, Any] | None:
        """Get company profile via HIVE-MIND."""
        query = f"{symbol} company profile overview"

        try:
            result = await self.hivemind.recall(query=query, limit=10, mode="insight")
            # Return as unstructured profile
            return {"symbol": symbol, "source": self.name, "query": query}
        except Exception as exc:
            logger.warning("HIVE-MIND company profile failed for %s: %s", symbol, exc)
            return None

    async def search_filings(self, query: str, company: str | None = None) -> list[FinancialDocument]:
        """Search filings via HIVE-MIND document retrieval."""
        if company:
            query = f"{company} {query}"

        try:
            result = await self.hivemind.recall(query=query, limit=10, mode="panorama")
            # Parse for document references
            return []  # Placeholder - would extract doc references from memories
        except Exception as exc:
            logger.warning("HIVE-MIND filing search failed for '%s': %s", query, exc)
            return []

    async def get_peer_comparison(self, symbol: str, metrics: list[str]) -> dict[str, Any]:
        """Get peer comparison via HIVE-MIND research."""
        query = f"{symbol} competitors comparison {' '.join(metrics)}"

        try:
            result = await self.hivemind.recall(query=query, limit=15, mode="insight")
            return {"symbol": symbol, "metrics": metrics, "source": self.name}
        except Exception as exc:
            logger.warning("HIVE-MIND peer comparison failed for %s: %s", symbol, exc)
            return {}


# Future: TDX Financial Client (Chinese stock market data)
# class TdxFinancialClient(FinancialDataClientBase):
#     """TDX MCP client for Chinese A-share market data.
#
#     Connects to tdx-mcp server for:
#     - Real-time stock prices (SHA/SZSE)
#     - Financial statements (Chinese GAAP)
#     - Technical indicators
#     """
#
#     def __init__(self, rpc_url: str, api_key: str | None = None):
#         self.rpc_url = rpc_url
#         self.api_key = api_key
#         self._client = None
#
#     @property
#     def name(self) -> str:
#         return "TDX Financial"
#
#     async def _ensure_connected(self):
#         if not self._client:
#             # Initialize MCP client connection
#             pass
#
#     async def get_metric(self, symbol: str, metric: str, period: str | None = None) -> FinancialDataPoint | None:
#         await self._ensure_connected()
#         # Call tdx-mcp get_stock_indicator or get_financial_indicator
#         pass
#
#     # ... implement other methods


# Future: Qieman MCP Client (financial research reports)
# class QiemanFinancialClient(FinancialDataClientBase):
#     """Qieman MCP client for financial research reports.
#
#     Connects to qieman-mcp for:
#     - Analyst research reports
#     - Industry analysis
#     - Investment theses
#     """
#
#     def __init__(self, rpc_url: str, api_key: str | None = None):
#         self.rpc_url = rpc_url
#         self.api_key = api_key
#         self._client = None
#
#     @property
#     def name(self) -> str:
#         return "Qieman Research"
#
#     async def _ensure_connected(self):
#         if not self._client:
#             pass
#
#     async def search_filings(self, query: str, company: str | None = None) -> list[FinancialDocument]:
#         await self._ensure_connected()
#         # Call qieman-mcp search_reports
#         pass
#
#     # ... implement other methods


def create_financial_client(
    hivemind_client: Any,
    provider: str = "hivemind",
    **kwargs: Any,
) -> FinancialDataClientBase:
    """Factory function to create financial data client.

    Args:
        hivemind_client: HIVE-MIND MCP client instance
        provider: "hivemind" (default), or future: "tdx", "qieman"
        **kwargs: Provider-specific configuration

    Returns:
        FinancialDataClientBase instance

    Example:
        hivemind = HivemindMCPClient(...)
        client = create_financial_client(hivemind, provider="hivemind")

        # Future:
        # tdx_client = create_financial_client(hivemind, provider="tdx", rpc_url="...")
    """
    providers = {
        "hivemind": HivemindFinancialClient,
        # "tdx": TdxFinancialClient,  # Future
        # "qieman": QiemanFinancialClient,  # Future
    }

    if provider not in providers:
        raise ValueError(f"Unknown financial data provider: {provider}. Available: {list(providers.keys())}")

    if provider == "hivemind":
        return providers["hivemind"](hivemind_client)

    return providers[provider](**kwargs)
