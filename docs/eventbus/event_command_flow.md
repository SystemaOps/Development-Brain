# Event → Command Flow

## Core Idea

Use this separation:

```text
Webhook
   ↓
Canonical Event
   ↓
Event Processor / Event Handlers
   ↓
Decide what should happen
   ↓
Command(s), if needed
   ↓
Command Queue
   ↓
Worker
   ↓
Workflow
```

## Responsibility

### Event
Describes something that already happened.

Examples:

```text
WorkItemAssigned
RepositoryRevisionChanged
HumanFeedbackReceived
VerificationCompleted
```

### Command
Requests the system to do something.

Examples:

```text
RunWorkItemCommand
IngestRepositoryCommand
ResumeWorkItemCommand
VerifyExecutionCommand
CreatePullRequestCommand
```

## Recommended Assignment Flow

```text
OpenProject Webhook
        ↓
OpenProject Adapter
        ↓
WorkItemAssigned
        ↓
IncomingEventProcessor
        ↓
EventBus
        ↓
WorkItemAssignedHandler
        ↓
RunWorkItemCommand
        ↓
enqueue_command(...)
        ↓
RedisCommandQueue
        ↓
WorkerLoop
        ↓
CommandDispatcher
        ↓
WorkflowEngine
```

The webhook should only report the fact:

```python
await incoming_event_processor.process(
    WorkItemAssigned(...)
)
```

The event handler decides the consequence:

```python
class WorkItemAssignedHandler:

    async def handle(self, event):
        await enqueue_command(
            CommandType.RUN_WORK_ITEM,
            project_id=event.project_id,
            work_item_id=event.work_item_id,
        )
```

## Important Rule

```text
Webhook produces facts.
Event handlers decide consequences.
Commands request work.
Workers perform the work.
```

Not every event must create a command.

For example:

```text
RepositoryRevisionChanged
       │
       ├── update revision state
       ├── update projections
       └── enqueue ingestion command
```

while another event may only update state:

```text
PullRequestCreated
       ↓
store PR relationship
```

## Recommended Responsibilities

```text
IncomingEventProcessor
    - deduplication
    - event log
    - dispatch events

Event Handlers
    - react to events
    - update projections
    - create commands when needed

Command Queue
    - store requested asynchronous work

Worker
    - execute commands
```
