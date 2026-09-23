# Part 2 — Production Issue Case Study
## Contract Document Processing Platform

### Executive Summary

The reported production symptoms point to a combination of **throughput bottlenecks, unreliable job lifecycle handling, extraction-provider saturation, database contention, and non-atomic batch/finding state transitions**.

The remediation should be staged:

1. **Stabilize:** timeouts, bounded retries, provider concurrency limits, stale-job recovery.
2. **Correctness:** explicit document state machine, idempotent processing, unique finding constraints.
3. **Reduce load:** optimize database writes/queries and batch progress calculation.
4. **Scale:** autoscaling, backpressure, distributed workers, provider-aware throttling.
5. **Govern:** versioned findings, optimistic locking, audit events, reconciliation jobs.

The key architectural principle is: **the document is the unit of work; the batch is an aggregate of document outcomes.**

---

## 1. Current Processing Model

```text
User
  |
  v
API Service
  |
  +--> Object Storage
  |
  +--> PostgreSQL
  |
  v
Queue
  |
  v
Document Workers
  |
  v
Extraction Service
  |
  v
Findings DB
  |
  v
Human Review
```

Important invariants:

- Every document has one authoritative processing state.
- Every processing attempt has a unique identity.
- Findings are unique per document + variable + extraction version.
- Every document eventually reaches `COMPLETED` or `FAILED`.
- A batch becomes terminal only after all documents are terminal.
- Retries never create duplicate findings.
- Reviewed findings are never silently overwritten.

---

# 2. Issue: Large Batches Are Taking Much Longer

## Possible causes

### A. Insufficient worker concurrency

The number of documents may have increased while worker capacity stayed constant.

### B. Extraction service is the bottleneck

Increasing worker count does not help if the downstream provider has a concurrency/rate limit.

### C. Uneven document processing times

Large or complex documents can occupy workers for much longer than normal documents.

### D. Database overhead

Each document may cause many queries:

```text
SELECT document
INSERT job
INSERT findings × N
UPDATE document
UPDATE batch
SELECT batch documents
```

### E. Repeated batch scans

If every completed document executes a full:

```sql
SELECT * FROM documents WHERE batch_id = ?
```

the DB work grows rapidly.

### Investigation

Measure:

- Queue depth and queue wait time
- Documents/minute
- Worker utilization
- Extraction p50/p95/p99 latency
- Extraction timeout rate
- DB CPU and connections
- Slow queries
- Lock waits
- API polling rate

The key question is:

```text
arrival rate > processing rate?
```

If yes, backlog will grow continuously.

### Immediate mitigation

- Increase workers carefully.
- Cap extraction concurrency.
- Reduce unnecessary DB queries.
- Batch finding inserts.
- Reduce aggressive frontend polling.
- Prioritize recovery of stuck jobs.

### Permanent remediation

Use autoscaling based on queue depth and processing latency.

Introduce provider-specific concurrency:

```text
Provider A -> 20 concurrent requests
Provider B -> 10
Provider C -> 5
```

Use adaptive concurrency when provider latency/error rates change.

### Risks

- More workers can overload the extraction service.
- Higher concurrency can increase rate-limit errors.
- Autoscaling increases infrastructure cost.
- Aggressive parallelism increases DB connection pressure.

---

# 3. Issue: Documents Remain in Processing Indefinitely

## Possible causes

- Worker crashes after setting `PROCESSING`.
- Extraction request hangs.
- No HTTP timeout exists.
- Queue acknowledgement happens before persistence.
- Kubernetes/VM termination kills the worker.
- There is no lease/heartbeat mechanism.

Typical failure:

```text
DB: PROCESSING
       |
       X Worker crashes
       |
       X No state transition
```

### Investigation

Find stale jobs:

```sql
SELECT id, processing_started_at
FROM documents
WHERE status = 'PROCESSING'
  AND processing_started_at < NOW() - INTERVAL '15 minutes';
```

Correlate with:

- Worker logs
- Pod restarts
- OOM events
- Deployment events
- Extraction request traces
- Queue message IDs

### Immediate mitigation

Add:

- Extraction timeouts
- A stale-job watchdog
- Bounded retries
- Dead-letter handling

Example:

```text
PROCESSING > timeout
       |
       v
mark attempt stale
       |
       v
retry
```

### Permanent remediation

Use an explicit state machine:

```text
PENDING
   |
   v
PROCESSING
   |
   +----> COMPLETED
   |
   +----> RETRY_WAIT
              |
              v
          PROCESSING
              |
              v
           FAILED
```

Store:

```text
attempt_id
worker_id
started_at
heartbeat_at
lease_expiry
```

A worker renews its lease while processing. Expired leases can be reclaimed.

### Risks

- Watchdogs may reclaim legitimate long-running jobs.
- Reclaiming jobs can cause duplicate provider calls.
- Short leases increase duplicate work.
- Long leases delay recovery.

Therefore lease recovery must be combined with idempotency.

---

# 4. Issue: Extraction Service Has Increased Timeouts

## Possible causes

- Excessive application concurrency
- Provider rate limiting
- Larger documents
- Network latency
- Provider-side degradation
- Retry storms

A dangerous feedback loop is:

```text
Provider slows
    ↓
Requests timeout
    ↓
Workers retry
    ↓
Traffic increases
    ↓
Provider slows further
```

### Investigation

Track:

```text
request rate
success rate
timeout rate
429 rate
5xx rate
p50/p95/p99 latency
concurrency
document size
```

Correlate timeout rate with concurrency and document size.

### Immediate mitigation

- Reduce concurrency.
- Add exponential backoff.
- Add jitter.
- Respect `Retry-After`.
- Implement a circuit breaker.
- Stop retrying permanent errors.
- Use a dead-letter queue after maximum attempts.

Example:

```text
1st retry -> 1 sec
2nd       -> 5 sec
3rd       -> 30 sec
4th       -> 2 min
```

### Permanent remediation

Introduce an Extraction Gateway:

```text
                 Extraction Gateway
                         |
             +-----------+-----------+
             |           |           |
         Timeout      Rate Limit   Circuit
                                    Breaker
                         |
                  Concurrency Pool
                         |
                  Provider Router
```

The gateway handles:

- Timeouts
- Retries
- Rate limits
- Provider health
- Fallback
- Concurrency

### Risks

- Lower concurrency increases processing time.
- Circuit breakers temporarily stop processing.
- Multiple providers may have different extraction behavior.
- Provider fallback can increase cost.

---

# 5. Issue: Database Load Has Increased

## Possible causes

### N+1 queries

One document can generate many database operations.

### Batch progress scans

Repeatedly calculating progress from all documents is expensive.

### Missing indexes

Important indexes include:

```text
documents(batch_id)
documents(status)
findings(document_id)
findings(document_id, variable_name)
extraction_jobs(document_id)
```

### Excessive frontend polling

Review dashboards can repeatedly hit batch/document endpoints.

### Investigation

Use:

```sql
EXPLAIN ANALYZE
```

and inspect:

- Query execution time
- Calls per query
- Rows scanned
- Index usage
- Lock waits
- Connection pool usage
- CPU/IOPS

### Immediate mitigation

- Add missing indexes.
- Reduce UI polling.
- Batch finding inserts.
- Avoid repeated full-batch scans.
- Reduce transaction scope.

### Permanent remediation

Maintain atomic counters:

```text
total
processed
successful
failed
```

For higher scale, publish:

```text
DocumentCompleted
DocumentFailed
```

events and maintain batch progress asynchronously.

Use read replicas for read-heavy review APIs if required.

Archive old batches and partition very large tables when justified.

### Risks

- Counter-based progress can become inconsistent after failures.
- Event-driven progress is eventually consistent.
- Read replicas introduce replication lag.
- Additional indexes increase write/storage cost.

Add a reconciliation job to repair aggregate state.

---

# 6. Issue: Batch Status Does Not Match Document Status

This indicates a **state consistency problem**.

## Possible causes

### A. Non-atomic updates

```text
Document -> COMPLETED
       |
       X
Batch update fails
```

### B. Race condition

```text
Worker A reads processed = 10
Worker B reads processed = 10

A writes 11
B writes 11

Actual = 12
Stored = 11
```

### C. Stale cache

### D. Retry logic incorrectly updates counters

### Investigation

Recalculate actual batch state:

```sql
SELECT
  COUNT(*) AS total
FROM documents
WHERE batch_id = :batch_id;
```

Then compare counts for:

```text
COMPLETED
FAILED
PROCESSING
PENDING
```

against the stored batch aggregate.

### Immediate mitigation

Run a reconciliation job periodically:

```text
Read document states
       ↓
Calculate expected batch state
       ↓
Repair batch counters/status
```

### Permanent remediation

Two good approaches exist.

#### Option A — Transactional counters

Update document and batch aggregate in the same transaction.

#### Option B — Derived batch state

Treat document state as the source of truth:

```text
All COMPLETED
    -> COMPLETED

Some FAILED, no active documents
    -> PARTIALLY_COMPLETED

Any PENDING/PROCESSING
    -> PROCESSING

All FAILED
    -> FAILED
```

At scale, maintain an aggregate for fast reads but periodically reconcile it.

### Risks

- Derived state can be expensive to calculate.
- Event-driven aggregates are eventually consistent.
- Transactional counters are more complex under concurrent retries.

---

# 7. Issue: Missing, Duplicate, or Inconsistent Findings

This is the most critical correctness problem.

## Possible causes

### Duplicate findings

A worker successfully writes findings and then crashes before acknowledging the queue. The same job is retried.

### Missing findings

Only part of the finding set is committed.

Example:

```text
effective_date -> inserted
expiry_date -> inserted
governing_law -> DB error
termination_clause -> never inserted
```

### Concurrent workers

Two workers process the same document.

### Non-deterministic extraction

A retry produces a different result.

### Reviewer race

A retry overwrites a finding after a reviewer has already accepted it.

### Investigation

Check duplicates:

```sql
SELECT document_id, variable_name, COUNT(*)
FROM findings
GROUP BY document_id, variable_name
HAVING COUNT(*) > 1;
```

Compare:

```text
Requested variables
       vs
Stored findings
```

Inspect job attempts and extraction request IDs.

### Immediate mitigation

- Add a unique DB constraint.
- Make writes idempotent.
- Use transactions for complete finding persistence.
- Do not overwrite reviewed findings.
- Prevent duplicate processing using a processing lease/claim.

### Permanent remediation

Introduce extraction versions:

```text
document_id
extraction_version
variable_name
value
status
```

Unique constraint:

```text
UNIQUE(
    document_id,
    extraction_version,
    variable_name
)
```

Example:

```text
Document 123
  Extraction v1 -> effective_date = 2026-01-01
  Extraction v2 -> effective_date = 2026-01-05
```

The review system explicitly chooses the active version.

Use optimistic locking for reviewer changes:

```text
finding_version
```

or:

```text
updated_at
```

### Risks

- More storage.
- More complex review UI.
- Multiple extraction versions require clear version semantics.
- Different providers can produce different values.

---

# 8. Cause-and-Remediation Table

| Issue | Likely causes | Validation | Immediate mitigation | Permanent remediation | Risks |
|---|---|---|---|---|---|
| Large batches slow | Worker bottleneck, provider bottleneck, DB overhead | Queue depth, throughput, worker utilization, extraction p95 | Carefully scale workers, cap provider concurrency, reduce DB writes | Autoscaling, adaptive concurrency, queue partitioning | Provider overload, cost |
| Documents stuck | Worker crash, hung request, missing timeout | Find stale `PROCESSING`, inspect worker/queue traces | Watchdog, timeout, retry | Lease/heartbeat + state machine | Duplicate processing |
| Extraction timeouts | Excess concurrency, rate limits, provider degradation | p95 latency, 429/5xx, concurrency correlation | Reduce concurrency, backoff, circuit breaker | Extraction gateway + provider routing | Lower throughput |
| DB load high | N+1 queries, polling, scans, missing indexes | Query profiler, `EXPLAIN ANALYZE` | Indexes, reduce polling, batch writes | Aggregate counters/events, read replicas | Eventual consistency |
| Batch mismatch | Non-atomic updates, races, stale cache | Compare batch aggregate to document states | Reconciliation job | Transactional counters or derived state | Concurrency complexity |
| Missing findings | Partial writes, crashes | Requested vs stored variables | Transactional writes | Versioned extraction + completeness checks | Storage overhead |
| Duplicate findings | Retries, concurrent workers | Duplicate query + job logs | Unique constraint + upsert | Idempotency keys + unique versioned findings | Constraint conflicts |
| Inconsistent findings | Provider nondeterminism, retries overwriting review | Compare extraction versions | Freeze reviewed findings | Immutable extraction versions + optimistic locking | More complex UX |

---

# 9. Recommended Target Architecture

```text
                         +------------------+
                         |    Web Client    |
                         +--------+---------+
                                  |
                                  v
                         +------------------+
                         |    API Service   |
                         +----+---------+---+
                              |         |
                   +----------+         +-----------+
                   v                                v
             +-----------+                    +-----------+
             |  Object   |                    | PostgreSQL|
             |  Storage  |                    +-----+-----+
             +-----+-----+                          |
                   |                                |
                   v                                |
             +-----------+                          |
             | Ingestion |                          |
             |  Service  |                          |
             +-----+-----+                          |
                   |                                |
                   v                                |
             +-----------+                          |
             |   Queue   |                          |
             +-----+-----+                          |
                   |                                |
        +----------+----------+                     |
        v          v          v                     |
    +-------+  +-------+  +-------+                 |
    |Worker |  |Worker |  |Worker |                 |
    +---+---+  +---+---+  +---+---+                 |
        |          |          |                      |
        +----------+----------+                      |
                   |                                 |
                   v                                 |
            +--------------+                          |
            | Extraction   |                          |
            | Gateway      |                          |
            |--------------|                          |
            | timeout      |                          |
            | retry        |                          |
            | rate-limit   |                          |
            | circuit      |                          |
            | concurrency  |                          |
            +------+-------+                          |
                   |                                  |
          +--------+--------+                         |
          v        v        v                         |
      Provider A Provider B OCR                       |
                                                     |
                                                     v
                                              +-------------+
                                              |  Findings   |
                                              |   Store     |
                                              +------+------+
                                                     |
                                                     v
                                              +-------------+
                                              | Review UI   |
                                              +-------------+

       +-----------------------------------------------+
       | Watchdog + Reconciliation + Observability     |
       | stale jobs | batch repair | duplicates | SLOs |
       +-----------------------------------------------+
```

---

# 10. Processing State Machine

```text
                 +-----------+
                 |  PENDING  |
                 +-----+-----+
                       |
                       v
                 +-----------+
                 | PROCESSING|
                 +-----+-----+
                    +--+--+
                    |     |
                    v     v
              +---------+ +------------+
              |COMPLETED| | RETRY_WAIT |
              +---------+ +------+-----+
                                  |
                                  v
                            PROCESSING
                                  |
                                  v
                              +-------+
                              |FAILED |
                              +-------+
```

Important invariant:

> No document should remain in `PROCESSING` without a valid active lease or heartbeat.

---

# 11. Idempotency Strategy

Use idempotency at multiple levels.

### Queue/job

```text
job_id = document_id + extraction_version
```

### Extraction request

```text
Idempotency-Key:
document_id:extraction_version
```

### Database

```text
UNIQUE(
    document_id,
    extraction_version,
    variable_name
)
```

### State claim

Use a conditional transition:

```sql
UPDATE documents
SET status = 'PROCESSING'
WHERE id = :id
  AND status = 'PENDING';
```

Only the worker that successfully claims the document owns the processing attempt.

---

# 12. Observability

## Queue metrics

```text
queue_depth
oldest_job_age
processing_rate
retry_rate
failure_rate
```

## Extraction metrics

```text
request_rate
success_rate
timeout_rate
429_rate
5xx_rate
p50/p95/p99_latency
concurrent_requests
```

## Database metrics

```text
CPU
connections
transaction_latency
lock_waits
slow_queries
```

## Processing metrics

```text
active_documents
stale_processing_documents
completed_documents
failed_documents
batch_duration
batch_duration_p95
```

## Correctness metrics

```text
duplicate_findings
missing_findings
batch_document_mismatches
reconciliation_repairs
```

Use correlation IDs across:

```text
batch_id
document_id
job_id
extraction_request_id
trace_id
```

---

# 13. Recommended Rollout Plan

## Phase 1 — Stabilization

Implement immediately:

1. Extraction timeout.
2. Maximum retry count.
3. Exponential backoff + jitter.
4. Provider concurrency limit.
5. Unique finding constraint.
6. Idempotent finding persistence.
7. Stale `PROCESSING` watchdog.
8. Batch reconciliation.
9. Queue/extraction metrics.

## Phase 2 — Correctness

Introduce:

1. Explicit state machine.
2. Job/attempt records.
3. Processing leases.
4. Extraction versions.
5. Optimistic locking for reviewer updates.
6. Transactional finding persistence.
7. Immutable audit events.

## Phase 3 — Scale

Introduce:

1. Horizontal worker autoscaling.
2. Queue partitioning.
3. Extraction gateway.
4. Adaptive concurrency.
5. Provider routing/fallback.
6. Read replicas.
7. Event-driven progress aggregation.
8. Object-storage lifecycle policies.
9. Historical data archival.

---

# 14. Assumptions

- Documents are independently processable.
- Document ordering is not required.
- A batch may partially succeed.
- Extraction providers can be retried for transient failures.
- Findings belong to a document + variable.
- Reviewer decisions must not be silently overwritten.
- Eventual consistency is acceptable for progress dashboards, but final state must be correct.
- PostgreSQL is the source of truth for document and finding state.
- Object storage is the source of truth for document content.

---

# 15. Final Recommendation

The production problem is not one isolated failure. It is the interaction between **unbounded concurrency, unreliable job lifecycle handling, external-service saturation, database contention, and independently maintained aggregate state**.

The most important architectural changes are:

```text
1. Document = unit of work
2. Queue = backpressure mechanism
3. Worker = stateless execution unit
4. Extraction Gateway = controlled external-service access
5. State machine = authoritative document lifecycle
6. Findings = idempotent + versioned
7. Batch = aggregate of document outcomes
8. Watchdog + reconciliation = correctness safety net
9. Metrics + tracing = operational visibility
```

This provides a path from the current 1,000-document workload toward substantially higher volumes while preserving **throughput, correctness, recoverability, and reviewer trust**.
