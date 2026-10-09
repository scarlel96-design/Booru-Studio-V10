# ADR 0003 — Worker per active Job

Status: Accepted

At most one V10 Worker process executes a given active Job at a time. A Worker may run bounded internal transfer concurrency and engine subprocesses. Worker replacement occurs through a new run/generation rather than two workers concurrently owning the same Job.
