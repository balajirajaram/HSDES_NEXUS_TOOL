# Knowledge-Base Entry Schema

Each learned case stored via `codesign-debug-store-memory` should follow this shape.
The KB lives in the memory server, **not** in Git — this schema is documentation so
entries stay consistent and reviewable.

```jsonc
{
  "signature": {
    "family": "GNR | SRF | CWF",
    "stepping": "e.g. A0, B0, C0",
    "unit": "e.g. RDT, UPI",
    "bucket": "failure bucket / cluster name",
    "mce_bank": "MCE bank number, if applicable",
    "rip": "instruction pointer, if applicable",
    "signal": "key RTL/SV signal name(s)",
    "error_string": "verbatim error text / bucket string",
    "key_terms": ["normalized", "search", "terms"]
  },
  "similar_hsds": [
    { "id": "HSD-xxxxxxxx", "why_matched": "reason for similarity" }
  ],
  "root_cause": {
    "text": "confirmed or likely root cause",
    "confidence": "confirmed | hypothesis"
  },
  "debug_steps": [
    "ordered step with the exact PythonSV command that was useful"
  ],
  "resolution": {
    "text": "final fix / workaround",
    "source_hsd": "HSD-xxxxxxxx"
  },
  "provenance": {
    "source": "KB | HSDES",
    "timestamp": "ISO-8601",
    "confidence_tag": "High | Medium | Low"
  }
}
```

## Rules
- Store only what was actually found or confirmed — never fabricate.
- Tag `root_cause.confidence` as `confirmed` (backed by data/HSDES) or `hypothesis`.
- On conflict with HSDES, overwrite and note the correction in `provenance`.
- One entry per normalized signature; **update** rather than duplicate.
- Keep every entry family- and stepping-scoped.
