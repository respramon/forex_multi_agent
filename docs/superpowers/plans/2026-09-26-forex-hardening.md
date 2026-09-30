# Forex Agent Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Apply the highest-impact safety, data-integrity, replay-determinism, API, and CI improvements without enabling broker order execution.

**Architecture:** Keep the deterministic analysis and risk engine as the authority. Share transaction geometry and candle cadence validators across journal, reconciliation, snapshot, and replay paths. Make same-timestamp replay phases explicit, while keeping the paper ledger separate from any future execution adapter.

**Tech Stack:** Python 3.11+, standard library, SQLite, unittest, GitHub Actions, Docker.

**Spec:** The approved repository review in the conversation, with the explicit requirement to apply the recommendations now.

## Global Constraints

- Broker adapters remain read-only; no live order endpoint is added.
- Existing CLI/API behavior and synthetic fixtures remain backward compatible unless a previously unsafe input is rejected.
- New behavior is introduced with a failing regression test before production code changes.
- Signals and risk calculations remain deterministic and fail closed on invalid or incomplete data.

## Review Focus

- A BUY/SELL journal amendment with a stop on the wrong side must be rejected.
- A missing candle outside the most recent ten bars must be rejected or explicitly identified as a permitted session gap.
- Same-timestamp exits and fills must not depend on lexical pair order.
- A retried journal-open request must not silently create duplicate records.
- API and CI changes must preserve the existing 64-test suite and offline smoke commands.

## Tasks

1. Add shared transaction and account invariants with journal/reconciliation regressions.
2. Enforce full candle cadence and common snapshot timing in all input adapters.
3. Separate replay open exits from fills and make execution prices side-aware.
4. Harden local API/file writes and add idempotency and operational safeguards.
5. Add CI quality gates and reproducibility metadata without adding mandatory runtime dependencies.
6. Run the full suite, smoke commands, and a targeted security/packaging review.
