# Architecture decision: Session-centric parking (2026-10-31)

## Decision

VLN-AVP autonomous parking uses **one Agent-Kernel Session** as the only task
lifecycle.

The Session owns Context, revisions, Planner exchanges, Workflow/Task
execution, authorization, execution feedback and termination. VLN-AVP owns
parking-domain skills, validators, target evidence and stage constraints. The
parking-domain progress snapshot is stored in the Session Context under
`domain.parking` and updated through the existing planner/execution exchanges
and `session.context.update`.

## Superseded design

The CAP-08A `src/vln/mission` core (MissionContext, MissionOrchestrator,
MissionPlanner, MissionStatus, Mission state machine and the CAP-08C-01 Mission
wrapper draft) is **deprecated and removed from the effective source tree**. It
is archived only as historical material under
`docs/evidence/cap-08a-01-superseded-mission/`; nothing there is importable or
part of the build.

The CAP-08A historical result/baseline documents still describe the design that
existed at that time. They are historical records, not current development
guidance.

## Consequences

- No Mission ID, Mission status, Mission object, Mission runtime, Mission
  manager/controller or Session↔Mission synchronisation may be reintroduced.
- Stage transitions are validated by existing parking domain validators and
  recorded in the Agent-Kernel Context, not in a second lifecycle store.
- Taichu decisions remain candidates; only Kernel authorization and the
  existing parking validators/gate can authorise motion or completion.
- The current driver is `scripts/carla_cap08c01_session_parking.py`; it is a
  session driver that sequences existing skills, not a task runtime.
