# Change request: GigSim platform policy update (2 Nov 2026)

**Simulated.** The instructor's change-request text was not available to the author, so a plausible update was defined
and implemented in GigSim as policy v2 (`gigsim/app.py`, `POLICIES[2]`):

1. **New rule:** proposals must not contain external links or URLs. GigSim rejects them at submit with HTTP 422.
2. **New cost:** premium jobs (Expert level or fixed budget ≥ $1,000) cost 4 extra Connects.

## What had to change in BidPilot

| Item | Change | Lines |
|---|---|---|
| `agent/config.yaml` | `marketplace.policy_version: 1` → `2` (enables the `policy.v2_rules` link rule in the Compliance Guard) | 1 |
| `data/policy_pack/marketplace_policy.md` | Added the two v2 rules for documentation | +4 |
| Agent code | None. Pricing already uses the per-job `connects_cost` returned by the marketplace, so the surcharge flows into the Connects EV check and the dry-run preview automatically. | 0 |

See the commit "Change request: GigSim policy v2" (`git show` on it for the diff). Time taken: under 10 minutes,
including verifying that GigSim returns 422 for a proposal with a link.

**Why it was cheap:** compliance rules, thresholds, budgets and model routing were in configuration from the start.
**What would not be cheap:** a rule that needs new logic, such as a weekly cap on proposals per category, would need code
in `decide`.
