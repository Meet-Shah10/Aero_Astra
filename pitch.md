# AERO-ASTRA — Pitch

---

## 1. The Problem

In 2023, ESA's OPS-SAT — a satellite the size of a shoebox, orbiting 500km above Earth — developed a subtle sensor fault. A magnetometer flatlined. It took the ground team **four contact windows, nearly 16 hours**, to notice it, work out what was wrong, and upload a fix. For those 16 hours the satellite kept flying, logging telemetry nobody was watching.

That's not a one-off. It's how satellite operations work almost everywhere:

A satellite in Low Earth Orbit moves at roughly 7.5 km/s and completes an orbit every ~90 minutes. It's only in radio contact with a ground station for **8–12 minutes per pass, a handful of passes a day** — meaning for **most of every day it is completely on its own**, unwatched and uncommandable.

When contact does happen, the satellite dumps hours of backlogged telemetry, and a human operator has to:
1. Scan the dump for anything abnormal (20–40 minutes)
2. Figure out which subsystem is at fault
3. Pull in a subject-matter expert to confirm
4. Debate the root cause
5. Design and validate a fix on a ground test bench
6. Wait for the *next* contact window to upload it
7. Confirm it worked on the pass after that

**End to end: anywhere from 2 to 48 hours from fault to confirmed fix.** In that window, a thermal runaway can permanently degrade solar panels, a reaction wheel fault can tumble the spacecraft out of control, and a power cascade can drain the battery bus in under four hours and kill the mission outright.

**We set out to build the thing that turns that 16-hour window into under 10 seconds.**

---

## 2. What We First Thought We'd Build

The obvious first idea: pull live telemetry from a real operational satellite, train an anomaly detector directly on its actual fault history, and build the whole pipeline around real, present-day mission data.

That idea didn't survive contact with reality.

---

## 3. The Wall We Hit — There Is No Open Dataset

Operational satellites don't publish their telemetry. Commercial operators (Starlink, Kuiper, national defense constellations) treat live telemetry and fault logs as proprietary and often classified — for competitive reasons, and because a public feed of exactly how and when your satellite fails is itself a security liability. Even where academic papers claim to work with "satellite anomaly data," most of it turns out to be synthetic or hand-labeled from simulators, not a real spacecraft's actual failure history.

We spent real time on this before pivoting: reaching out to see what was available, checking every public dataset we could find, and confirming the same thing each time — nobody who operates a satellite in orbit today is going to hand you their raw fault telemetry.

So the question became: is there *any* real satellite, anywhere, that publishes its own telemetry and fault labels openly?

---

## 4. The Pivot — OPS-SAT

There is exactly one good answer: **ESA's OPS-SAT**, launched in 2019 specifically as an open experimentation platform — the first ESA satellite built to let outside researchers run software on real flight hardware and see real results. ESA also published **OPSSAT-AD**, a labeled anomaly dataset from that actual satellite's telemetry (Zenodo, DOI: 10.5281/zenodo.10624588).

This mattered because it meant we weren't training on synthetic fault curves we made up ourselves — we were training on how a real satellite's sensors actually behave when something real goes wrong. We built our anomaly detector (SENTINEL's Engine A) directly on this dataset, and used the behavioral signatures in it to calibrate the physics constants in our own simulation engine, so the fault dynamics we simulate for scenarios OPS-SAT never had (thermal runaway, thruster faults, power cascades) still resemble how a real spacecraft actually degrades, not just a textbook curve.

Where OPSSAT-AD didn't cover a fault type we needed, we built a physics-based digital twin instead — coupled differential equations for each subsystem (power, thermal, attitude), the same modeling approach real spacecraft AOCS simulators use — and validated its behavior against the OPS-SAT data we did have, rather than inventing fault curves from scratch.

That's the honest version of where our data comes from: one real, open satellite's real anomaly history, plus a physics model calibrated against it — not a live feed from an operational constellation, because no such feed exists publicly, and we're not pretending otherwise anywhere in the product.

---

## 5. What We Built

AERO-ASTRA is a closed-loop pipeline that takes a satellite from "something's wrong" to "here's the fix, executed or awaiting approval" in seconds instead of hours. It runs on the ground (not onboard the spacecraft — more on why below) and moves through six stages:

1. **Detect** — continuously score subsystem health and catch anomalies as they emerge, using both a model trained on real satellite data and physics-based checks that catch failure patterns no single-channel detector would notice.
2. **Diagnose** — figure out the root cause, constrained so the reasoning can never point at a subsystem that isn't physically capable of causing the observed fault.
3. **Simulate** — run every candidate fix through a physics digital twin, a hundred times each with randomized initial conditions, to get real empirical success rates instead of a guess.
4. **Plan** — turn the winning simulation result into a clear, human-readable recovery procedure.
5. **Gate** — decide whether the fix executes automatically or needs a human's sign-off first, based on how severe and how reversible the situation is.
6. **Log** — record everything that happened and why, in a form that can be audited afterward.

The one deliberate design choice underneath all of this: **we only use an LLM where actual language-level reasoning is needed** (working out a causal story, writing a procedure in plain English). Anything that can be computed — health scores, simulation outcomes, safety thresholds — is computed deterministically, not asked of a language model. A model can sound confident about a made-up success rate; a Monte Carlo simulation can't. That split is what makes autonomous execution safe to allow at all.

### Why run this on the ground, not onboard the satellite?

Because the hardware makes that decision for you. Real flight computers use radiation-hardened processors running at a few hundred MHz — they can't run an LLM, and they don't need to. The dangerous window isn't the seconds after a fault starts; most real subsystem failures take 30–90 minutes to become unrecoverable, not seconds. A ground-based pipeline that finishes in under 10 seconds (measured end to end, detection through GUARDIAN's gate decision) is still enormously faster than that window, and it's how real mission control systems are actually built today — we're just making the human analysis step automatic. Truly instantaneous events (a cosmic-ray bit flip, a micro-meteoroid strike) are already handled by hardwired onboard safe-mode logic on every satellite; we don't touch that layer.

---

## 6. Live Demo Walkthrough

**Landing page** — a real-time 3D scene (Three.js / React Three Fiber), not a video or a static background: a rotating Earth, an orbiting satellite model, a live orbital readout.

**Mission Control dashboard** — everything on screen updates live over WebSocket from the FastAPI backend: subsystem health gauges, the anomaly feed, the diagnosis panel, the event log, the safety-gate status.

**Inject an anomaly** — pick one of five fault scenarios (thermal runaway, signal dropout, thruster fault, power cascade failure, sensor fusion failure) and a severity. Watch the pipeline fire end to end: detection, diagnosis, simulation, recovery plan, and the safety gate deciding whether it executes automatically or waits for a human click.

**Historical case study** — one of the five scenarios, sensor fusion failure, replays the real failure pattern behind JAXA's *Hitomi* satellite loss in 2016: a faulty inertial sensor disagreed with the star tracker, the control system trusted the wrong one, and the spacecraft spun itself apart correcting an error that didn't exist. Our detector is built to catch exactly that kind of two-channel disagreement — not just "one number crossed a threshold," but "two things that should agree, don't." It's the clearest demonstration of why the system needs to exist at all: the data to catch that failure was there in the real telemetry, nobody built the thing that was watching for it correctly.

---

## 7. Closing

We set out to answer one question: *can a system manage a satellite anomaly better than the ground team that exists today?*

The honest answer is yes, but only if you're disciplined about where you use AI and where you don't. Use real data where real data exists. Use physics simulation where it doesn't. Use language models for reasoning, not for arithmetic. And always leave a human able to stop the machine before anything irreversible happens.

The OPS-SAT anomaly that took 16 hours to resolve — this pipeline handles the equivalent in under 10 seconds, measured end to end on our own test runs.

---

## 8. Questions & Answers

**Q: Why not train on real, current satellite telemetry?**
A: Because it isn't public. No operator of a live constellation publishes their fault history — it's proprietary and often treated as a security concern. OPS-SAT is the one satellite that publishes real, labeled anomaly data openly, so that's what we trained on, and we say so directly rather than implying we had access to something we didn't.

**Q: Why not just use one big LLM for the whole pipeline?**
A: Because a language model can't be trusted to compute a safety probability — it will produce a plausible-sounding number, not a measured one. We use LLMs only for the parts that genuinely need language reasoning (why did this happen, how do I explain the fix). Anything that's actually a calculation — health scores, simulation outcomes, thresholds — is deterministic code, not a model output.

**Q: How is this different from existing fault-detection systems?**
A: Traditional systems are rule-based lookup tables — no learning, no reasoning about causes, no simulated comparison of fix options. This pipeline adds a detector trained on real satellite data, causal reasoning that's physically constrained so it can't blame an impossible subsystem, simulated (not guessed) recovery outcomes, and a graded decision on when a human needs to approve versus when the system can act on its own.

**Q: What happens with no internet or API access at the ground station?**
A: The reasoning stages fall back to a precomputed offline response and the system keeps running — detection, simulation, and the safety gate don't depend on a live API. You lose the natural-language explanation layer, not the actual fault handling.

**Q: How confident are you the physics model is realistic?**
A: We calibrated it against the real OPS-SAT dataset rather than inventing constants from scratch, and it produces zero false positives across repeated nominal-telemetry test runs. It's a best-effort physics approximation, not a claim of certified flight-grade fidelity — that distinction matters and we don't blur it.

**Q: What stops the system from executing a bad fix?**
A: Every candidate fix is simulated before anything executes, and any option with a meaningfully high chance of making things worse is automatically routed to require human approval, regardless of how urgent the situation looks. Nothing irreversible happens without a person clicking approve.

---

*— AERO-ASTRA*
