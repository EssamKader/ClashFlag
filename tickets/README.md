# Ticket tracker (local, file-based)

Each ticket is one `.md` file in this folder. First line is always:

```
label: <needs-triage|needs-info|ready-for-agent|ready-for-human|wontfix|wayfinder:map>
```

Valid labels for this sandbox:
- `needs-triage` — default state for a new ticket
- `needs-info` — missing a specific detail
- `ready-for-agent` — clear, no open questions, safe to implement
- `ready-for-human` — needs a human decision/action
- `wontfix` — explicitly out of scope
- `wayfinder:map` — root ticket for an ambiguity-resolution pass
