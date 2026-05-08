# Multi-Agent Factory Automation

A robotic crane factory controlled by LLM-powered agents. The crane picks parts from source conveyors, delivers them to processing machines, then carries finished parts to the output conveyor. Three generations of implementation live side by side — from fully hardcoded to fully autonomous.

## Demo — Model Comparison

### GPT-4.1-mini — correct decisions, true concurrency
![GPT-4.1-mini demo](src/GPT-4.1.mini-demo.gif)

### Llama 3.1 8B — poor decisions, unreliable sequencing
![Llama 8B demo](src/llama-3.1-8B-Demo.gif)

> Llama 3.1 8B frequently misroutes parts, stalls on decisions, or calls tools in the wrong order. GPT-4.1-mini reliably follows all routing rules and exploits the crane opportunistically while machines run.

---

## The Three Systems

| | [Legacy (hardcoded)](#legacy-hardcoded) | [Semi-autonomous](#semi-autonomous) | [Fully autonomous](#fully-autonomous) |
|---|---|---|---|
| **Location** | `legacy/` | `semi-autonomous/` | `fully-autonomous/` |
| **Decision maker** | Pre-scripted JSON actions | LLM per task, Python orchestrator | LLM on every event, agents are peers |
| **Concurrency** | Sequential | Sequential | True async (crane + machines simultaneously) |
| **LLM calls** | None | ~5 per part (plan_run) | 1 per significant event |
| **Human input** | None (auto) | None (auto) |None|

---

## Factory Layout

```
 Source 1   Source 2         Process 1     Process 2       Output
  X=55       X=158             X=450         X=650          X=945
   │           │                 │             │               │
   └───────────┴─────────────────┴─────────────┴───────────────┘
                          Crane rail (Y=82 pick, Y=200 travel)
```

**Part routing:** Source 1 → Process 1 → Output · Source 2 → Process 2 → Output

---

## Start the Simulation

### Linux
```bash
sudo apt install default-jre openjfx #install openjfx runtime if you dont have it
```
since this simulation uses modbus defualt port 502 (which is privilaged port on linuc), you will need to to allow Java to bind low ports without sudo 

```bash
sudo setcap 'cap_net_bind_service=+ep' $(readlink -f $(which java))
```
Run the simulation
```bash
cd CraneSimulation
java --module-path /usr/share/openjfx/lib --add-modules javafx.controls,javafx.fxml \
  -jar CraneSimulation/simulation.jar
```
### Windows
```bash
cd CraneSimulation
.\simulation.exe
```
---

## Legacy (hardcoded)

> `legacy/`

No LLM. Crane movements are loaded from `actions.json` and executed as a fixed sequence via Modbus TCP writes. The orchestration logic (`auto.py`) loops over actions and queues parts manually.

**Run:**
```bash
python legacy/auto.py
```

Good as a baseline and for verifying raw Modbus connectivity with the simulation.

---

## Semi-autonomous

> `semi-autonomous/`

An LLM orchestrator (GPT-4.1-mini) delegates work to three specialized agents. Each agent is called once per task and returns a JSON action plan that Python executes. This cuts API round-trips from ~16 to ~5 per part.

**Run:**
```bash
python semi-autonomous/main.py
```

**How it works:**
- **Orchestrator** polls sensors every 2 seconds via `SourceAgent`, queues detected parts, and calls the other agents in sequence
- **CraneAgent** receives a single prompt → returns `{"steps": [...]}` JSON → Python executes the moves
- **ProcessAgent** same pattern: one prompt → JSON plan → Python starts/stops the machine
- **SourceAgent** calls `read_sensors` via function calling and returns `{"source1": bool, "source2": bool}`

Safety is enforced in `hardware.safe_move()` — the LLM cannot skip the rise-to-travel-height step even if it outputs wrong coordinates.

See [`semi-autonomous/README.md`](semi-autonomous/README.md) for full details.

---

## Fully autonomous

> `fully-autonomous/`

Four independent agents communicate through a typed pub/sub event bus. After a single `start factory` prompt, the LLM (GPT-4.1-mini via AsyncOpenAI) makes every decision — which source to pick first, when to use the crane opportunistically while a machine is running, when to send parts to output.

**Run:**
```bash
python fully-autonomous/main.py
```

**Key capability — true concurrency:**  
While Process Machine 1 is running its 12-second cycle, the crane simultaneously picks from Source 2 and delivers to Process Machine 2. Both operate in the same Python thread via `asyncio`.

See [`fully-autonomous/README.md`](fully-autonomous/README.md) for full architecture, timing diagrams, and tuning parameters.

---

## Hardware / Modbus Register Map

| Register | Direction | Meaning |
|---|---|---|
| 1 | Write | Crane X position |
| 2 | Write | Crane Y position |
| 3 | Write | Vacuum gripper (0/1) |
| 4 | Write | Process machine 1 (0/1) |
| 5 | Write | Process machine 2 (0/1) |
| 17–20 | Read | Sensors (source1, source2, process1, process2) |

Modbus host: `127.0.0.1` (simulation listens on default port 502).

---

## Setup

```bash
pip install -r req.txt
```

API key goes in `.env` at the project root:
```
OPENAI_API_KEY=sk-...
```
