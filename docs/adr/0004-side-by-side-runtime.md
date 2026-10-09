# ADR 0004 — Side-by-side immutable application runtime

Status: Accepted

Production V10 uses versioned onedir application capsules. Running application files are not updated in place. Bootstrap, application runtime and Engine Pack lifecycles remain separable so failed activation can return to a known-good version.
