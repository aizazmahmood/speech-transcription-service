# Speech Transcription Service System Design

## Purpose

This document describes the production design for the speech transcription service.

The current repository already implements a synchronous FastAPI transcription endpoint,
audio validation, FFmpeg normalization, adaptive direct-versus-chunked transcription,
timestamp rebasing, overlap-aware chunk merging, structured errors, and automated
tests.

This document focuses on the production architecture needed for:

- concurrent uploads
- durable storage
- long-running transcription jobs
- worker retries
- failure recovery
- API polling
- operational visibility
- safe scaling

The design intentionally separates what is already implemented from what would be
added for a production deployment.

## Current implemented behavior

The current implementation supports two synchronous transcription modes.

| Mode | When used | Behavior |
|---|---|---|
| Direct | Source duration is at or below the configured threshold | The service normalizes the complete file and transcribes it once |
| Chunked | Source duration is above the configured threshold | The service extracts overlapping chunks, transcribes them sequentially, rebases timestamps, removes overlap duplicates, and returns one merged transcript |

The current endpoint remains synchronous. The API request stays open until upload,
inspection, media processing, transcription, merging, response serialization, and
temporary-file cleanup are complete.

This is acceptable for local execution and an assessment demo, but it is not the
final production model for high concurrency or long-running jobs.

## Production goals

The production design should provide:

| Goal | Design response |
|---|---|
| Handle many concurrent uploads | Stream uploads to object storage and return a job ID quickly |
| Avoid blocking API workers during transcription | Move transcription to background workers |
| Support long audio safely | Split audio into deterministic chunks and checkpoint progress |
| Recover from crashes | Persist job state, chunk state, source location, and worker attempts |
| Retry transient failures | Retry failed jobs or chunks with bounded exponential backoff |
| Avoid duplicate processing | Use idempotency keys and deterministic storage keys |
| Provide client visibility | Expose job status and result endpoints |
| Support operations | Add logs, metrics, tracing, and dead-letter queues |
| Protect resources | Enforce size limits, timeouts, authentication, and rate limits |

## High-level production architecture

The production architecture uses five main layers.

| Layer | Responsibility |
|---|---|
| API service | Accept uploads, validate metadata, create jobs, expose status/result APIs |
| Object storage | Store original uploads, normalized files, chunks, and exported outputs |
| Database | Persist users, jobs, chunk records, attempts, statuses, and result metadata |
| Queue | Dispatch transcription work to background workers |
| Worker service | Run FFprobe, FFmpeg, faster-whisper, chunk merging, retries, and exports |

The API service and worker service can use the same domain and application code, but
they should run as separate process types in production.

## Main components

### API service

The API service should:

- authenticate requests
- enforce upload limits
- stream accepted files to object storage
- run inexpensive prechecks
- create a durable transcription job
- enqueue background work
- return a job response quickly
- expose status and result APIs

The API service should not run expensive transcription work during a production
upload request.

### Object storage

Object storage should contain durable binary artifacts.

Examples:

| Artifact | Example key |
|---|---|
| Source upload | tenants/{tenant_id}/jobs/{job_id}/source/original |
| Normalized direct audio | tenants/{tenant_id}/jobs/{job_id}/normalized/audio.wav |
| Chunk audio | tenants/{tenant_id}/jobs/{job_id}/chunks/{chunk_index}.wav |
| JSON result | tenants/{tenant_id}/jobs/{job_id}/results/transcript.json |
| SRT result | tenants/{tenant_id}/jobs/{job_id}/results/transcript.srt |
| WebVTT result | tenants/{tenant_id}/jobs/{job_id}/results/transcript.vtt |

Object storage should use server-side encryption, lifecycle policies, and private
access by default.

### Database

The database should store job metadata and state transitions.

A relational database such as PostgreSQL is a good default because job state,
attempts, users, and chunks have clear relationships and benefit from transactions.

Core tables:

| Table | Purpose |
|---|---|
| transcription_jobs | One row per user transcription request |
| transcription_chunks | One row per planned chunk for long audio |
| transcription_attempts | Records worker attempts, errors, and timing |
| transcription_outputs | Records generated JSON, SRT, WebVTT, or text outputs |
| users or api_clients | Owns requests and permissions |

### Queue

The queue should decouple API requests from transcription work.

Suitable options include Redis Queue, Celery with Redis or RabbitMQ, AWS SQS, Google
Pub/Sub, or a managed cloud queue. For a production cloud deployment, a managed queue
is preferred because it reduces operational burden.

The queue message should be small. It should contain identifiers, not binary audio.

Example queue payload fields:

| Field | Meaning |
|---|---|
| job_id | Durable job identifier |
| tenant_id | Owner or workspace identifier |
| task_type | inspect, direct_transcribe, chunk_transcribe, merge, export |
| chunk_index | Present for chunk transcription tasks |
| attempt | Current attempt number |

### Worker service

Workers should:

- claim queued tasks
- load job metadata from the database
- download source or chunk audio from object storage
- run FFprobe and FFmpeg as needed
- run the transcription engine
- persist partial results
- update job and chunk statuses
- enqueue follow-up tasks
- retry transient failures
- move poison messages to a dead-letter queue

Workers can scale horizontally. For CPU inference, worker concurrency should be
limited based on CPU cores and memory. For GPU inference, workers should be scheduled
according to GPU capacity.

## Job lifecycle

A transcription job should move through explicit states.

| State | Meaning |
|---|---|
| RECEIVED | API accepted the request and started creating records |
| UPLOADED | Source file is durably stored |
| INSPECTING | Worker is validating source media |
| PLANNED | Duration and chunking plan are known |
| QUEUED | Work is waiting for worker capacity |
| PROCESSING | One or more worker tasks are active |
| MERGING | Chunk transcripts are being merged |
| EXPORTING | Output formats are being generated |
| SUCCEEDED | Final transcript and requested outputs are available |
| FAILED | Job failed after retry policy was exhausted |
| CANCELED | User or system canceled the job |
| EXPIRED | Job artifacts passed retention policy and were removed |

The API should expose these states without leaking internal paths or raw worker errors.

## Chunk lifecycle

Long audio should be split into deterministic chunks.

Each chunk should have its own state.

| State | Meaning |
|---|---|
| PLANNED | Chunk boundaries were calculated |
| QUEUED | Chunk is waiting for a worker |
| PROCESSING | Worker is extracting or transcribing the chunk |
| SUCCEEDED | Chunk transcript is persisted |
| FAILED_RETRYABLE | Chunk failed but can be retried |
| FAILED_FINAL | Chunk failed permanently |
| SKIPPED | Chunk is no longer needed because the job was canceled |

Chunk records should store:

- chunk index
- raw start and end seconds
- keep-window start and end seconds
- source storage key
- chunk audio storage key if persisted
- transcript storage key or JSON field
- attempt count
- last error code
- processing duration

## Upload and job creation flow

The production upload flow should be:

1. Client sends audio upload with optional language, output format, and idempotency key.
2. API authenticates the client.
3. API validates filename, content type, and configured size limits.
4. API streams the file directly to object storage.
5. API creates a transcription_jobs row.
6. API stores source metadata and storage key.
7. API enqueues an inspection task.
8. API returns 202 Accepted with job_id and status URL.

The API should not wait for transcription to finish.

## Inspection and planning flow

The inspection worker should:

1. Load the job row.
2. Download or stream the source file from object storage.
3. Run FFprobe.
4. Persist source media metadata.
5. Decide whether the job is direct or chunked.
6. For direct jobs, enqueue a direct transcription task.
7. For long audio, create transcription_chunks rows.
8. Enqueue chunk transcription tasks.
9. Update the job status to QUEUED or PROCESSING.

Invalid media should fail the job with a stable error code such as INVALID_AUDIO.

## Direct transcription flow

For direct jobs, the worker should:

1. Download the source audio.
2. Normalize it to the internal WAV format.
3. Verify the normalized file with FFprobe.
4. Upload normalized audio to object storage if retention is required.
5. Run the transcription engine.
6. Persist the transcript.
7. Generate requested outputs.
8. Mark the job as SUCCEEDED.

Temporary files should be deleted after success or failure.

## Chunked transcription flow

For chunked jobs, workers should process chunks independently.

Each chunk worker should:

1. Load the job and chunk record.
2. Extract the chunk from the original source using FFmpeg.
3. Verify the chunk against the internal audio contract.
4. Run the transcription engine.
5. Persist the chunk transcript.
6. Mark the chunk as SUCCEEDED.
7. Delete temporary files.

After all chunks succeed, the system should enqueue a merge task.

The merge task should:

1. Load all chunk transcripts.
2. Rebase chunk-local timestamps to full-audio timestamps.
3. Apply deterministic keep-window ownership.
4. Remove overlap duplicates.
5. Reindex final segments.
6. Persist the merged transcript.
7. Enqueue export tasks or mark the job as SUCCEEDED.

## Retry policy

Retries should be bounded and error-aware.

| Error type | Retry? | Example |
|---|---|---|
| Invalid user input | No | Unsupported media or invalid audio |
| Missing dependency | No until deployment fixed | FFmpeg unavailable |
| Transient storage issue | Yes | Object storage timeout |
| Transient queue issue | Yes | Queue visibility timeout |
| Worker crash | Yes | Process killed during chunk transcription |
| Model loading failure | Maybe | Retry if caused by network or temporary disk issue |
| Deterministic model error | No after repeated failure | Same chunk fails with same engine error |

Recommended retry behavior:

- maximum attempts per task: 3
- backoff: exponential with jitter
- dead-letter queue after final failure
- persist every failed attempt
- expose stable error codes to API clients

## Crash recovery

The system should recover from worker and API crashes.

API crash during upload:

- incomplete object storage multipart uploads should expire automatically
- no job should be visible until database creation succeeds
- idempotency keys should allow safe retry by the client

Worker crash during processing:

- queue visibility timeout should release the task
- another worker should retry the task
- attempt records should show the abandoned attempt
- stale PROCESSING chunks should be detected by heartbeat or timeout

Crash during merge:

- merge task should be idempotent
- final transcript should be written with a deterministic key
- database update should be transactional
- duplicate merge execution should not create inconsistent results

## Idempotency

The upload API should accept an idempotency key.

The unique constraint should include:

- tenant_id
- idempotency_key

When the same client retries the same request, the API should return the existing
job instead of creating a duplicate.

Storage keys should include the job_id so repeated worker execution overwrites or
reuses deterministic artifacts safely.

## API design

### Create transcription job

POST /api/v1/transcriptions

Production behavior:

- accepts multipart audio upload
- returns 202 Accepted
- returns job_id and status URL
- does not wait for transcription completion

Response fields:

| Field | Meaning |
|---|---|
| job_id | Durable transcription job ID |
| status | Initial job status |
| status_url | API URL for polling |
| result_url | API URL for result retrieval when complete |

### Get job status

GET /api/v1/transcriptions/{job_id}

Returns:

| Field | Meaning |
|---|---|
| job_id | Durable transcription job ID |
| status | Current job state |
| mode | direct or chunked when known |
| progress | Approximate completion percentage |
| chunk_count | Number of chunks when known |
| completed_chunks | Number of successful chunks |
| error | Stable error object when failed |
| created_at | Job creation time |
| updated_at | Last state update time |

### Get transcript result

GET /api/v1/transcriptions/{job_id}/result

Returns the final transcript after success.

For unfinished jobs, the API should return 409 Conflict or 202 Accepted depending on
the preferred client contract.

### Download exports

GET /api/v1/transcriptions/{job_id}/exports/{format}

Supported future formats:

- json
- txt
- srt
- vtt

The API can return the file directly or issue a short-lived signed URL.

## Progress reporting

For direct jobs, progress is coarse:

| Stage | Approximate progress |
|---|---:|
| Uploaded | 10 |
| Inspected | 25 |
| Normalized | 45 |
| Transcribed | 85 |
| Exported | 100 |

For chunked jobs, progress can be based on completed chunks:

progress = completed_chunks / chunk_count

A weighted model can also account for inspection, planning, merging, and export work.

## Storage retention

A production system should define retention policies.

Examples:

| Artifact | Suggested retention |
|---|---|
| Source audio | 7 to 30 days depending on customer settings |
| Chunk audio | Delete after successful chunk transcription unless debugging is enabled |
| Normalized direct audio | Delete after success unless retention is requested |
| JSON transcript | Retain according to customer policy |
| SRT and WebVTT exports | Regenerate or retain according to cost and latency needs |
| Failed job temporary files | Delete after diagnostic retention window |

Retention should be configurable by tenant or deployment environment.

## Security

Production security should include:

- authentication for all transcription APIs
- per-tenant authorization checks
- private object storage buckets
- server-side encryption for stored files
- TLS for all network traffic
- input size limits
- media duration limits
- allowed content-type and extension prechecks
- FFprobe validation as source of truth
- rate limiting
- audit logs for job creation and downloads
- no raw internal paths in API responses
- no raw subprocess stderr in client-facing errors

## Observability

The production deployment should expose:

- structured logs with job_id and chunk_index
- request latency metrics
- upload size metrics
- queue depth metrics
- worker processing duration
- model inference duration
- FFmpeg and FFprobe failure counts
- retry counts
- dead-letter queue counts
- job success and failure rates
- real-time factor distribution
- chunk merge duration

Tracing should connect:

- upload request
- job creation
- queue message
- worker task
- storage operations
- final result request

## Scaling considerations

API services scale horizontally behind a load balancer.

Workers scale independently from the API. Worker count should be controlled by:

- CPU cores
- GPU availability
- model memory requirements
- FFmpeg load
- queue depth
- target job latency

Long audio should not monopolize a single worker for too long if chunk tasks can be
distributed. Chunk-level task distribution improves throughput and recovery, but the
merge task must wait for all required chunk transcripts.

## Database consistency

Important database operations should be transactional.

Examples:

- create job row and mark upload complete
- create all chunk rows for a long job
- mark chunk success and persist transcript reference
- mark final merge success and final transcript reference
- transition job to FAILED after final retry

State transitions should be validated so a completed job is not accidentally moved
back to PROCESSING by a late worker.

## Cost controls

The production design should control cost by:

- enforcing upload size and duration limits
- deleting temporary chunk files after success
- using lifecycle policies for old artifacts
- limiting retries
- using smaller models when acceptable
- routing premium jobs to larger models only when requested
- scaling workers based on queue depth
- avoiding duplicate jobs with idempotency keys

## Current implementation versus production target

| Capability | Current repository | Production target |
|---|---|---|
| Upload handling | Synchronous API upload with temporary local files | Stream to object storage and return job ID |
| Transcription execution | API request path | Background workers |
| Long audio | Sequential synchronous chunking | Distributed chunk tasks with checkpoints |
| Persistence | Temporary local workspace only | Database plus object storage |
| Retry behavior | Request-level failure response | Task-level retry policy and dead-letter queue |
| Status API | Immediate response only | Pollable job status and progress |
| Output formats | JSON transcript response | JSON, TXT, SRT, and WebVTT outputs |
| Recovery | Temporary cleanup on request completion | Durable recovery from worker crashes |
| Scaling | One API process can run local demo | Horizontally scaled API and workers |

## Summary

The current implementation proves the core media and transcription logic in a clean,
testable way. The production design keeps that core logic but moves long-running work
out of the API request path.

The key production changes are:

- stream uploads to object storage
- persist job and chunk state in a database
- execute transcription in background workers
- checkpoint chunk progress
- retry transient failures safely
- expose status and result APIs
- add operational metrics, logs, tracing, and retention policies