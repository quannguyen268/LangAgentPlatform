"""LangAgent Platform core — streaming events, cost tracking, and utilities.

NOTE (AD-14): The agent graph is now built by DeepAgents' create_deep_agent()
with LangChain middleware. The custom StateGraph (graph.py, nodes.py) is kept
as a fallback/reference but is not used in the primary agent construction.
The primary code path is in src/agent.py using create_deep_agent().
"""
