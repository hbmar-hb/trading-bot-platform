"""Re-export PortfolioManager from canonical location in app.services.

This file remains for backward compatibility; new code should import from
app.services.portfolio_manager directly.
"""
from app.services.portfolio_manager import PortfolioManager, PortfolioCheckResult

__all__ = ["PortfolioManager", "PortfolioCheckResult"]
