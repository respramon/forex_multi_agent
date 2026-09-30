"""Stateless forex specialists, scheduled through explicit assessment messages."""

from .contracts import AgentAssessment, AnalysisContext, SpecialistAgent
from .data import DataValidationAgent
from .fundamental import CurrencySentimentAgent, FundamentalAgent
from .market import MarketConditionsAgent
from .portfolio import PortfolioAgent
from .risk import RiskAgent
from .strategy import StrategyAgent
from .technical import TechnicalAgent
from ..models import PAIRS

AGENT_TYPES = (DataValidationAgent, TechnicalAgent, FundamentalAgent,
               MarketConditionsAgent, PortfolioAgent, StrategyAgent,
               CurrencySentimentAgent, RiskAgent)


def agent_manifest() -> dict:
    return {"architecture": "forex_multi_agent", "coordinator": "ForexCoordinator",
            "decision_policy": "mandatory_veto", "agent_count": len(AGENT_TYPES),
            "forex_only": True, "pairs": list(PAIRS), "execution_enabled": False,
            "agents": [agent.describe() for agent in AGENT_TYPES]}


__all__ = ["AgentAssessment", "AnalysisContext", "SpecialistAgent", "DataValidationAgent",
           "TechnicalAgent", "FundamentalAgent", "MarketConditionsAgent", "PortfolioAgent",
           "StrategyAgent", "CurrencySentimentAgent", "RiskAgent", "AGENT_TYPES", "agent_manifest"]
