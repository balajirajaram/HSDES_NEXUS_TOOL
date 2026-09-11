# Shared VM Operations Guide

Planning artifact only; no production operations are authorized.

- Start/stop the service through a controlled process manager.
- Verify Kerberos/HSDES connectivity before analysis jobs.
- Back up KB, RCA graph, audit log, and report artifacts.
- Rotate credentials through the approved secret store.
- Review failed jobs and authentication errors daily.
- Keep AutoHSD commands in recommendation-only mode.
- Require approval for HSDES write-back and Golden Case promotion.
- Test restore and rollback on a scheduled cadence.
