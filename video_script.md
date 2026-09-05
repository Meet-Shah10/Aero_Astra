# AERO-ASTRA — Demo Video Script (Voiceover)

Target length: 3.5–4.5 minutes. Format below is `[ON SCREEN]` / `VOICEOVER:` — read the voiceover lines aloud while performing the on-screen action. Timestamps are suggested pacing, not hard cuts — adjust to how fast you naturally talk.

Flow, in order: **hook → problem/research → why existing approaches fail → our solution → live demo → results → close.** This matches how `pitch.md` is structured, compressed for video instead of a live Q&A format — no audience questions to pause for, so the pacing is tighter and there's no separate "literature survey" slide-read, that gets folded into one spoken beat.

Record the demo screen capture *after* writing this script, not before — knowing your exact talking points first means you record fewer, cleaner takes instead of over-shooting footage and cutting a script to match it.

---

## 0:00–0:15 — Cold Open (Hook)

`[ON SCREEN]` Black screen, then fade into the AERO-ASTRA landing page (rotating Earth, orbiting satellite).

**VOICEOVER:**
"In 2023, ESA's OPS-SAT — a satellite the size of a shoebox — developed a subtle sensor fault. It took the ground team sixteen hours to notice, diagnose, and fix it. During those sixteen hours, the satellite kept flying, blind.

This is AERO-ASTRA. It does the same job in under ten seconds."

*(Pause half a beat after "ten seconds" — let that number land before moving on.)*

---

## 0:15–0:55 — The Problem (Research)

`[ON SCREEN]` Cut to a simple diagram or the Problem Understanding slide — orbit path, ground station contact window.

**VOICEOVER:**
"Here's why this is hard. A satellite in low Earth orbit is in radio contact with the ground for maybe ten minutes out of every ninety. For most of the day, it's completely on its own — no commands in, no one watching the telemetry.

When contact does happen, a human operator has to scan hours of backlogged data, figure out what subsystem failed, call in an expert, agree on a fix, and wait for the next contact window to upload it. End to end, that's anywhere from two to forty-eight hours.

In that window, a thermal fault can permanently damage solar panels. A reaction wheel fault can tumble the spacecraft out of control. A power cascade can drain the battery and end the mission — all before a human ever gets a chance to respond."

`[ON SCREEN]` Quick cut: the cascading-subsystem diagram (EPS → TCS → ADCS → TT&C arrows).

**VOICEOVER (continuing):**
"And it's not isolated — a fault in one subsystem drags down the others. That's the problem we set out to solve."

---

## 0:55–1:25 — The Research: Why the Data Story Matters

`[ON SCREEN]` A simple graphic or text card: "No public satellite telemetry" → arrow → "ESA OPS-SAT" logo/mention.

**VOICEOVER:**
"Our first idea was obvious: train on real telemetry from an operational satellite. That idea didn't survive contact with reality — no operator publishes live fault data. It's proprietary, and for good reason: telling the world exactly how your satellite fails is a security risk.

So we went looking for the one exception. ESA's OPS-SAT is a satellite built specifically to let outside researchers use real flight data. Its OPSSAT-AD dataset is real, labeled anomaly data from an actual spacecraft — not synthetic, not simulated. That's what our anomaly detector is trained on. Where that dataset didn't cover a fault type we needed, we built a physics-based digital twin instead, calibrated against the real data we did have."

*(This beat matters — it's the difference between "we made up training data" and "here's exactly where our data is real and where it's a physics model, and why." Say it plainly, don't rush it.)*

---

## 1:25–1:55 — The Solution (Architecture, high level)

`[ON SCREEN]` The 8-agent pipeline diagram, or a simple animated flow if you have one: SENTINEL → SHERLOCK → ORACLE → ATHENA → GUARDIAN → SCRIBE.

**VOICEOVER:**
"AERO-ASTRA is a pipeline of agents, each with exactly one job. SENTINEL watches telemetry continuously and flags anomalies using three detection methods working together. SHERLOCK diagnoses the root cause — but it's constrained by an actual physics graph of the satellite, so it can't invent a cause that isn't physically possible. ORACLE simulates every candidate fix a hundred times against a physics model before anything is trusted. ATHENA turns the winning simulation into a plain-English recovery plan, grounded in a real spacecraft fault-handling handbook, not just a language model's guess. And GUARDIAN — the safety gate — is plain deterministic code, not AI. It decides whether the fix executes automatically or waits for a human to approve it.

The one rule underneath all of it: the AI reasons about *why* something happened and *how* to explain the fix. It never gets to invent a safety number. Every number that matters is computed, not guessed."

---

## 1:55–3:15 — Live Demo

`[ON SCREEN]` Screen recording, mission control dashboard, nominal state.

**VOICEOVER:**
"Let's see it work. This is Mission Control — live telemetry, subsystem health, all running over a real WebSocket connection to the backend."

`[ACTION]` Click **Inject Anomaly** → select **Sensor Fusion Failure** (the Hitomi case study) → set severity → **Launch Scenario**.

**VOICEOVER:**
"I'm injecting a fault scenario modeled on a real spacecraft loss — JAXA's Hitomi satellite in 2016. Its inertial sensor disagreed with its star tracker, the control system trusted the wrong one, and the spacecraft spun itself apart correcting a rotation that never happened. This scenario replays that exact failure signature."

`[ON SCREEN]` Anomaly detected — red overlay, callout labels pop on the satellite model (ADCS / SENSOR DISAGREEMENT / ANOMALY DETECTED).

**VOICEOVER:**
"SENTINEL catches it — not because one number crossed a threshold, but because two things that should agree with each other, don't. That's a detection pattern most systems structurally can't see."

`[ACTION]` Click into the SHERLOCK agent tab, show the causal graph.

**VOICEOVER:**
"SHERLOCK diagnoses the cause. Here's the causal graph — the flagged subsystem in red, every physically possible cause in amber, and the confirmed chain in green. The model can only pick from what's amber. It's not free to guess."

`[ACTION]` Click into ORACLE, show the ranked recovery options and outcome distribution.

**VOICEOVER:**
"ORACLE has already run a hundred simulations per candidate fix against our physics digital twin. These aren't estimates — they're measured outcome distributions."

`[ACTION]` Show ATHENA's recommended plan, then GUARDIAN's MANUAL_INTERLOCK gate.

**VOICEOVER:**
"ATHENA turns the winning option into a plan. And because this fault is severe, GUARDIAN won't execute it alone — it's waiting for a human to click approve. Nothing irreversible happens without that click."

`[ACTION]` Click Approve → Execute Runbook.

**VOICEOVER:**
"Once approved, the fix executes, and SCRIBE writes out a complete audit record — every agent's decision, timestamped, downloadable as a real file."

`[ON SCREEN]` Show the downloaded `.txt` runbook briefly (open it, scroll).

**VOICEOVER:**
"This is the actual audit trail from the run you just watched — not a mockup."

---

## 3:15–3:45 — Results

`[ON SCREEN]` Simple text/number cards, one at a time: "Under 10 seconds end-to-end" / "100% of diagnoses physics-validated" / "False positives cut from ~550/day to under 5/day".

**VOICEOVER:**
"Measured, not projected: the full pipeline — detection through the safety gate's decision — runs in under ten seconds. Every diagnosis is physics-validated before it's accepted. And our detection engine cut false positives from around five hundred a day down to fewer than five, on real satellite data."

---

## 3:45–4:15 — Close

`[ON SCREEN]` Return to the landing page or a clean title card.

**VOICEOVER:**
"We built AERO-ASTRA on one principle: use real data where real data exists, use physics where it doesn't, and never let a language model invent a number that matters. The OPS-SAT anomaly that took sixteen hours to resolve — this pipeline handles the equivalent in under ten seconds.

That's AERO-ASTRA."

`[ON SCREEN]` Team name / logo card, fade out.

---

## Notes for recording

- **Record screen and voiceover separately** if you can — a clean screen capture with no talking-over-clicking audio artifacts, narrated afterward against the footage, looks far more polished than a single live take.
- **Don't narrate every click.** The script above already tells you what to say during each action — resist the urge to describe what's visually obvious ("now I'm clicking here").
- **The Hitomi scenario is the strongest demo beat.** If you're short on time and need to cut, cut from the results section, not the demo — a judge remembers what they watched happen, not a number on a card.
- **Test the full record-to-resolution flow once, off-camera, before your real take** — confirm the anomaly resolves within your expected window (GUARDIAN's MANUAL_INTERLOCK waits indefinitely for your click, so don't record the approval step until you're ready to click).
- Keep the Gemini API quota in mind (20 requests/day on the free tier) — don't burn it on multiple full dry runs the same day you're recording the real take.
