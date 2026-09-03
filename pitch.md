# AERO-ASTRA — Hackathon Pitch Guide

> This is not a technical doc. This is how you talk to judges who may not be engineers.
> Every section has a "what to say" and a "what not to say."

---

## The One-Line Hook (Open Every Pitch With This)

> *"Every day, satellites worth hundreds of millions of dollars have problems in orbit — and right now, engineers sit in a room staring at spreadsheets, trying to figure out what went wrong. We built an AI system that does that in seconds, automatically, and with a full paper trail."*

That's it. Start there. Watch the room lean in.

---

## The Problem (Explain It Like They're 12)

**What to say:**

*"There are thousands of satellites in orbit right now. Each one is constantly sending data — temperature, battery level, signal strength, CPU usage — back to Earth. When something goes wrong — and things do go wrong — an engineer has to look at all this data, figure out what's causing the problem, decide how to fix it, and execute the fix. That whole process can take hours. And during those hours, a satellite might be losing power, overheating, or drifting out of position."*

*"As satellite constellations scale to hundreds or thousands of units — like SpaceX Starlink, Amazon Kuiper, or ISRO's future constellations — you can't hire enough people to monitor all of them manually. The current approach doesn't scale."*

**What NOT to say:**
- Don't say "anomaly detection ML pipeline" to a non-technical judge
- Don't say "multi-agent LLM orchestration framework"
- Don't mention F1 scores in the first 2 minutes

---

## The Solution (Explain What We Built)

**What to say:**

*"AERO-ASTRA is an autonomous mission operations system. Think of it as a team of AI specialists, each with a different job, working together in real-time."*

Then walk through the agents one at a time — **always in plain English**:

| Agent | What to call it in a pitch | One-sentence plain English explanation |
|---|---|---|
| **SENTINEL** | "The Early Warning System" | "It watches all the telemetry data 24/7 and knows when something starts to look wrong — before a human would notice." |
| **SHERLOCK** | "The Detective" | "When SENTINEL raises an alarm, SHERLOCK figures out *why*. It traces the problem back to its root cause — like diagnosing whether a fever is caused by a cold or a bacterial infection." |
| **ORACLE** | "The Simulator" | "Before we do anything, ORACLE runs 100 different simulations of what will happen if we try each fix. It gives us the odds — like a weather forecast for the satellite." |
| **ATHENA** | "The Strategist" | "Using ORACLE's simulations, ATHENA picks the best recovery plan and writes out every step, in order, with its reasoning." |
| **GUARDIAN** | "The Safety Gate" | "For high-risk situations, nothing executes without a human pressing approve. It also formally verifies that the plan can't make things worse." |
| **QUARTERMASTER** | "The Logistics Manager" | "It coordinates with ground stations and, if needed, shifts load to other satellites in the fleet." |
| **SCRIBE** | "The Accountant" | "Every decision, every step, every agent's reasoning — all of it gets written into an audit trail automatically. Regulators and mission controllers get a complete record." |
| **CHRONICLE** | "The Live Log" | "A running event log of everything happening, in real-time, as it happens." |

**What NOT to say:**
- Don't list agents as bullet points and move on. Tell a story.
- Don't say "we use Claude Sonnet 4.5 via OpenRouter"

---

## The Demo Script (What to Show, In Order)

### Step 1 — Open on calm state
*"This is the dashboard. Everything is green. The satellite is nominal. Battery healthy, communications stable, all systems go."*

### Step 2 — Trigger the fault
Click "Trigger Fault Scenario."

*"I'm going to inject a power system fault — the kind of thing that actually happens on orbit. Watch what happens."*

Narrate as it unfolds:
- *"SENTINEL just detected an anomaly on the power bus. That's the early warning."*
- *"SHERLOCK is now building a causal chain — tracing the problem from the EPS through to the thermal system..."*

### Step 3 — Point at the causal graph
*"Here's what SHERLOCK found. The battery degradation is causing the thermal system to overheat, which is stressing the on-board computer. That's a cascade failure — and SHERLOCK found it in 2 seconds."*

*"The key differentiator here: SHERLOCK can ONLY propose root causes that are physically connected in our satellite dependency graph. It can't hallucinate a random explanation. It's constrained to what's physically possible."*

### Step 4 — Show ORACLE's Monte Carlo bars
*"Before we do anything, ORACLE runs 100 independent simulations of each possible fix. Look at these probability bars. Plan A — shedding non-essential load — gives an 87% chance of full recovery. Doing nothing gives us a 43% chance of mission loss. This is the equivalent of a doctor running a clinical trial before prescribing a treatment."*

### Step 5 — Show ATHENA's reasoning
*"ATHENA took ORACLE's results and wrote a step-by-step recovery procedure. You can see its chain of thought — why it chose this plan, why it ordered the steps this way."*

### Step 6 — Click the GUARDIAN toggle yourself
Don't let it auto-execute. Flip the toggle on camera.

*"For HIGH urgency situations, nothing happens without a human in the loop. I just approved the procedure. The system logged my approval with a timestamp."*

### Step 7 — Show SCRIBE runbook
*"And here's the complete audit trail — every agent's decision, every step of the procedure, the ORACLE simulation results, timestamps on everything. This is what mission controllers and regulators would keep on file. It took zero manual effort to produce."*

### Step 8 — Close with the data line
*"The anomaly detection model was trained on 67,000 rows of real ESA satellite telemetry from the OPSSAT-AD dataset — not synthetic data. The physics simulator that powers ORACLE models all 6 satellite subsystems with realistic orbital dynamics. We're being honest about what's real and what's simulated for the hackathon — the architecture is designed to slot in production data at any point."*

---

## Q&A Cheat Sheet

**"How is this different from existing satellite monitoring tools?"**
> "Existing tools alert you that something is wrong — they're dashboards, not decision-makers. AERO-ASTRA diagnoses the cause, simulates fixes, generates the procedure, and produces the audit trail. The human is in the loop for approval, not for the heavy cognitive lifting."

**"Isn't an LLM dangerous to use for satellite operations?"**
> "Great question — that's exactly why SHERLOCK is graph-constrained. Claude can only select root causes from a physically-validated causal dependency graph. It cannot propose a fix that violates physics. GUARDIAN also formally verifies safety constraints before anything executes."

**"What's the dataset?"**
> "SENTINEL is trained on the OPSSAT-AD dataset — real ESA telemetry from the OPS-SAT experimental satellite. Everything after SENTINEL runs on our physics simulator, which models all 6 subsystems — power, thermal, attitude control, on-board computer, communications, and propulsion — with realistic fault injection and orbital dynamics."

**"What would it take to deploy this for a real satellite?"**
> "Three things: connect SENTINEL's input to live telemetry feeds instead of simulated data, connect GUARDIAN's approval gate to actual command uplink systems, and get the satellite operator's domain experts to validate the causal graph and recovery catalog. The architecture is designed for exactly this path."

**"How much compute does this need?"**
> "The detection and diagnosis happen in under 5 seconds on a standard server. The Monte Carlo simulation runs 100 physics simulations in about 2 seconds on CPU — no GPU needed. It's deployable on a standard cloud instance."

---

## Pitch Structure (2 minutes / 5 minutes / 10 minutes)

### 2-minute version (elevator pitch):
1. Open with the one-liner (20 seconds)
2. The problem — manual triage doesn't scale (30 seconds)
3. Our solution — 8 AI agents, each with a job (40 seconds)
4. The differentiator — graph-constrained, formally verified, auditable (20 seconds)
5. Close — "real ESA data, real physics, fully auditable" (10 seconds)

### 5-minute version:
Same as 2-min but expand Step 3 (demo clip) and Step 4 (ORACLE bars). Add one Q&A.

### 10-minute version:
Full demo walkthrough (Steps 1–8) + 2 minutes of Q&A.

---

## Language Rules

**Always say:**
- "autonomous" not "automated"
- "diagnoses the root cause" not "runs anomaly detection"
- "100 physics simulations" not "Monte Carlo"
- "audit trail" not "log file"
- "human in the loop" — say this phrase explicitly
- "real ESA telemetry" — say this every time you mention SENTINEL

**Never say:**
- "we fine-tuned a model" (we didn't)
- "100% accurate" (nothing is)
- "AI-powered" as a standalone phrase (everyone says this)
- "LLM-based" without immediately explaining what the LLM's job is

---

## The Honest Differentiator Line

If a judge pushes on credibility, use this:

*"We made a deliberate choice to be honest about what's real vs simulated. SENTINEL's detection uses real ESA data. The physics simulator is built on real orbital mechanics equations. Everything else in the pipeline uses that simulator as ground truth — and we label it 'synthetic' on our slides. We think that honesty is itself a differentiator, because judges who've seen real satellite ops can tell the difference between a system built on real constraints and a dashboard with fake numbers."*

---

## The Emotional Close

End every pitch with something that lands emotionally, not technically:

> *"Satellites are infrastructure now — they're not just science experiments. They power GPS, communications, weather forecasting. When one fails unexpectedly and the team is scrambling, every minute matters. AERO-ASTRA is what happens when you take the best of human expertise — the causal reasoning of a diagnosis, the rigor of a formal safety check, the completeness of an audit trail — and make it happen in seconds instead of hours. That's the mission."*
