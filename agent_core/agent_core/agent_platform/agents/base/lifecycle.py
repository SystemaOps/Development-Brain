from __future__ import annotations

from agent_core.agent_platform.agents.base.agent import BaseAgent
from agent_core.agent_platform.agents.base.contracts import AgentRequest, AgentResult
from agent_core.agent_platform.runtime.execution_context import AgentExecutionContext


async def execute_agent_lifecycle(
    agent: BaseAgent,
    *,
    request: AgentRequest,
    context: AgentExecutionContext,
) -> AgentResult:
    await agent.initialize()
    try:
        await agent.validate_request(request)
        return await agent.execute(request, context)
    finally:
        await agent.shutdown()
