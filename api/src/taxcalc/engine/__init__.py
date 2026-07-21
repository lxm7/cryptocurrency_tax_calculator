"""Section 104 disposal-matching engine.

PURE, zero I/O. No database session, no HTTP, no clock. Transactions in,
disposals out. Built test-first against committed fixtures — never wired to a
live datasource. This constraint is load-bearing for the CI eval gate and the
week-8 numeric reconciliation step.
"""
