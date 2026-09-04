# Contributing to ClashFlag

Thanks for considering a contribution — clash coordination tooling for Revit benefits from
more eyes on it, not fewer.

## Ways to contribute

- **Bug reports**: open an issue with your Revit version, pyRevit version, and (if possible)
  the exact console error text ClashFlag prints.
- **Feature ideas**: open an issue describing the workflow problem, not just the feature —
  it's easier to design the right solution when the underlying need is clear.
- **Code**: fork, branch, and open a pull request. See below for how this project works.

## How this project is organized

ClashFlag was built using a ticket-based workflow — see [`tickets/`](tickets/) for the full
history of every design decision and [`specs/`](specs/) for the user-story spec that ticket
work traces back to. New features should ideally follow the same shape:

1. A spec update (or a new user story) describing *why*, not just *what*.
2. One or more tickets, each independently reviewable.
3. A PR per ticket where practical, rather than one giant PR.

This isn't a strict requirement for small fixes (typos, obvious bugs) — use judgment.

## Code style

- Python targets pyRevit's IronPython 2.7 engine unless a function is explicitly CPython3-only
  — avoid Python 3-only syntax in `script.py`.
- Every Revit-API-touching call must be wrapped in a `Transaction` and handle exceptions —
  don't let a failed API call leave a half-applied change in the model.
- If you're calling a Revit API method whose behavior you're not 100% sure of, verify it (API
  docs, a real test) rather than guessing — this project has a documented history (see the
  tickets) of bugs that came from unverified API assumptions.

## Testing

There's no automated test suite for the Revit-API-touching code (it needs a live Revit
session to exercise meaningfully). Please describe how you tested your change (Revit
version, model type, what you clicked) in your PR description.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By participating, you
agree to abide by it.
