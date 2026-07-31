from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import AsyncContextManager, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.agent_platform.orchestration import (
    AgentExecutionRequest,
    AgentFlowStore,
    PersistedAgentFlow,
)
from agent_core.persistence.agent_flows import SqlAlchemyAgentFlowStore
from agent_core.services.agent_execution_codec import (
    AgentExecutionRequestCodec,
    create_default_agent_execution_codec,
)
from agent_core.services.agent_platform_service import AgentPlatformService

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AsyncContextManager[AsyncSession]]


class AgentPlatformServiceBuilder(Protocol):
    def __call__(self, db: AsyncSession) -> AgentPlatformService: ...


class AgentFlowStoreFactory(Protocol):
    def __call__(self, db: AsyncSession) -> AgentFlowStore: ...


class AgentFlowWorker:
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        service_builder: AgentPlatformServiceBuilder,
        worker_id: str,
        lease_seconds: int,
        heartbeat_seconds: float,
        poll_seconds: float = 2.0,
        recovery_enabled: bool = True,
        max_recovery_attempts: int = 3,
        codec: AgentExecutionRequestCodec | None = None,
        flow_store_factory: AgentFlowStoreFactory = SqlAlchemyAgentFlowStore,
    ) -> None:
        if heartbeat_seconds <= 0 or heartbeat_seconds >= lease_seconds:
            raise ValueError("heartbeat_seconds must be positive and less than lease_seconds")
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        if max_recovery_attempts < 0:
            raise ValueError("max_recovery_attempts cannot be negative")
        self.session_factory = session_factory
        self.service_builder = service_builder
        self.flow_store_factory = flow_store_factory
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.poll_seconds = poll_seconds
        self.recovery_enabled = recovery_enabled
        self.max_recovery_attempts = max_recovery_attempts
        self.codec = codec or create_default_agent_execution_codec()

    async def run_once(self) -> PersistedAgentFlow | None:
        claim = await self._claim_next()
        if claim is None:
            return None
        if claim.pending_execution_payload is None:
            raise RuntimeError(f"Claimed flow has no execution payload: {claim.flow_id}")
        execution = self.codec.decode(claim.pending_execution_payload)
        return await self._execute_with_heartbeat(claim, execution)

    async def run_forever(self, *, concurrency: int = 1) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        await asyncio.gather(*[self._worker_loop(slot=slot) for slot in range(1, concurrency + 1)])

    async def _worker_loop(self, *, slot: int) -> None:
        logger.info(
            "agent flow worker slot started",
            extra={"worker_id": self.worker_id, "slot": slot},
        )
        while True:
            try:
                result = await self.run_once()
                if result is None:
                    await asyncio.sleep(self.poll_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "agent flow worker execution failed",
                    extra={"worker_id": self.worker_id, "slot": slot},
                )
                await asyncio.sleep(self.poll_seconds)

    async def _claim_next(self) -> PersistedAgentFlow | None:
        async with self.session_factory() as session:
            return await self.flow_store_factory(session).claim_next(
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
                recover_expired=self.recovery_enabled,
                max_recovery_attempts=self.max_recovery_attempts,
            )

    async def _execute_with_heartbeat(
        self,
        claim: PersistedAgentFlow,
        execution: AgentExecutionRequest,
    ) -> PersistedAgentFlow:
        stop = asyncio.Event()
        execution_task = asyncio.create_task(self._execute_claim(claim, execution))
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(claim, stop=stop))
        done, _ = await asyncio.wait(
            {execution_task, heartbeat_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        if execution_task in done:
            stop.set()
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
            return execution_task.result()

        heartbeat_error = heartbeat_task.exception()
        execution_task.cancel()
        await asyncio.gather(execution_task, return_exceptions=True)
        if heartbeat_error is not None:
            raise heartbeat_error
        raise RuntimeError("Agent flow heartbeat stopped before execution completed")

    async def _execute_claim(
        self,
        claim: PersistedAgentFlow,
        execution: AgentExecutionRequest,
    ) -> PersistedAgentFlow:
        async with self.session_factory() as session:
            service = self.service_builder(session)
            return await service.execute_claimed_flow(
                claim=claim,
                request=execution,
                max_steps=claim.execution_options.max_steps,
            )

    async def _heartbeat_loop(
        self,
        claim: PersistedAgentFlow,
        *,
        stop: asyncio.Event,
    ) -> None:
        if claim.lease is None:
            raise RuntimeError(f"Claimed flow has no lease: {claim.flow_id}")
        while True:
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=self.heartbeat_seconds,
                )
                return
            except TimeoutError:
                await self._heartbeat(
                    flow_id=claim.flow_id,
                    lease_id=claim.lease.lease_id,
                    expected_version=claim.version,
                )

    async def _heartbeat(
        self,
        *,
        flow_id: UUID,
        lease_id: UUID,
        expected_version: int,
    ) -> None:
        async with self.session_factory() as session:
            await self.flow_store_factory(session).renew_lease(
                flow_id=flow_id,
                lease_id=lease_id,
                expected_version=expected_version,
                lease_seconds=self.lease_seconds,
            )


async def async_main() -> None:
    from agent_core.agent_platform.config import (
        load_agent_platform_config,
    )
    from agent_core.config import settings
    from agent_core.db import SessionFactory
    from agent_core.services.agent_platform_composition import (
        create_agent_platform_service_for_db,
    )

    flow_config = load_agent_platform_config().flow_runtime
    worker = AgentFlowWorker(
        session_factory=SessionFactory,
        service_builder=create_agent_platform_service_for_db,
        worker_id=settings.flow_worker_id,
        lease_seconds=flow_config.lease_seconds,
        heartbeat_seconds=flow_config.heartbeat_seconds,
        poll_seconds=flow_config.worker_poll_seconds,
        recovery_enabled=flow_config.recovery_enabled,
        max_recovery_attempts=flow_config.max_recovery_attempts,
    )
    await worker.run_forever(concurrency=settings.worker_concurrency)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
