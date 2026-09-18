Here's the full digestion picture for both paths, with exact references.
1. Command path — enqueue_command(...) → digested by the worker
Producer (webhook route)
brain/api/routes/webhooks.py (assignment branch) calls enqueue_command():
brain/api/commands.py:24-43 — builds a CommandEnvelope via make_command(...) and pushes it onto the queue:
queue = container.services["command_queue"]      # line 33
await queue.enqueue(envelope)                    # line 41
The queue (where the command waits)
brain/bootstrap/providers.py:371-388 — build_command_queue():
- BRAIN_REDIS_PROVIDER=redis → RedisCommandQueue (production)
- default → InMemoryCommandQueue (tests/dev)
brain/adapters/queue/redis.py:
- enqueue (line 32) → rpush envelope JSON onto {queue}:pending
- consume (line 35) → blpop (blocking pop) → moves envelope to {queue}:inflight hash
- acknowledge (line 44) → removes from inflight
- dead_letter (line 55) → pushes to {queue}:dead with reason
The digester — the worker process
brain/workers/main.py — python -m brain.workers.main creates the container, grabs services["command_dispatcher"] and services["command_queue"], and runs WorkerLoop.
brain/workers/loop.py:98-131 — WorkerLoop.run():
loop:
  command = queue.consume()          # blpop from Redis
  process_command(dispatcher, ...)   # line 115
  success → queue.acknowledge()      # line 129
  failure → retry (max 3) → dead_letter  # lines 113-126
brain/workers/loop.py:38-72 — process_command():
- await dispatcher.dispatch(command) (line 51)
- on exception → classify_failure() (line 26, maps exception → CommandFailureCategory + retry eligibility) → persists a CommandFailure → re-raises
The dispatcher → the actual handler
brain/application/command_dispatcher.py:40-44 — dispatch() routes by command.command_type to the registered handler.
brain/application/command_handlers.py:60-73 — _register() installs the mapping, e.g.:
self._dispatcher.register(CommandType.RUN_WORK_ITEM, self._run_work_item)   # line 69
command_handlers.py:194-213 — _run_work_item() loads the work item + project, then:
state = await self._container.workflow.start(project=project, work_item=work_item, ...)
→ WorkflowEngine.start() (brain/application/workflow_engine.py:53) — context build, execution, verification.
Wired at brain/bootstrap/container.py:253,278 — install_command_handlers(container=container_instance).
2. Event path — container.event_bus.publish(envelope) → nothing digests it (currently)
The bus implementation
brain/adapters/in_memory/event_bus.py:27-32 — InMemoryEventBus.publish():
self.published.append(event)                       # test-inspection log
handlers = self._handlers.get(event.event_type.value, [])
for handler in handlers:
    await handler.handle(event)                    # synchronous fan-out
The intended digesters (exist, but NOT wired)
brain/application/events.py:34-59 — IncomingEventProcessor.process() is the documented "single choke point":
if idempotency.is_processed(key): return SKIPPED   # dedup
await self._bus.publish(envelope)                  # dispatch to handlers
await self._event_log.append(envelope)             # trace log
await idempotency.mark_processed(key)              # exactly-once
Two EventHandler implementations exist:
- brain/application/projections.py:39-70 — CanonicalStateProjection.handle(): upserts project/repository/work item/requirement/document/execution into canonical state
- brain/application/revisions.py:37-69 — IncrementalRevisionHandler.handle(): RepositoryRevisionChanged → changed files → RepositoryChangeSet → advances current_revision
But: a grep across brain/ for subscribe finds only the port (ports/event_bus.py:23), the adapter (in_memory/event_bus.py:17), and tests. IncomingEventProcessor is never instantiated in create_brain_container(), and neither projection is subscribed to the bus.
So today's event flow from the webhook is:
webhook → event_bus.publish(envelope)   (webhooks.py:60)
        → self.published.append(...)    ← only side effect
        → no handlers → dead end
Why the system still works (the real mechanism)
The webhook route doesn't rely on the bus for behavior — it calls side-effect services directly:
- comments → HumanFeedbackService.receive() directly (webhooks.py → _normalize_human_comment), which itself persists feedback and enqueues resume
- assignment → enqueue_command(...) → command path above → worker → workflow
The event bus is the "what happened" record; the command queue is the "what to do next" mechanism.
Summary table
Path	Who digests
enqueue_command → queue	worker (WorkerLoop.run)
→ dispatcher	CommandDispatcher.dispatch
→ real work	CommandHandlers._run_work_item → WorkflowEngine.start
event_bus.publish	no one (unwired)
If you want the event bus to actually do something, the fix is wiring IncomingEventProcessor + CanonicalStateProjection/IncrementalRevisionHandler as subscribers in create_brain_container() — happy to implement that.