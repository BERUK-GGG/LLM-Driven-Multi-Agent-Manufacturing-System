# Fully Autonomous Factory — Multi-Agent System

A factory automation system where independent AI agents communicate through a shared event bus and make their own decisions. The only human input is typing `start factory` at launch.

## How to Run

Start the JavaFX simulation first:
```bash
java --module-path /usr/share/openjfx/lib --add-modules javafx.controls,javafx.fxml \
  -jar ../CraneSimulation/simulation.jar
```

Then start the agents:
```bash
python main.py
# > start factory
```

## Architecture

```
                        ┌─────────────────────────────────────────┐
                        │             Message Bus                  │
                        │  (async pub/sub — asyncio.Queue per      │
                        │   subscriber, typed event routing)       │
                        └──────┬──────┬──────────┬────────────────┘
                               │      │          │
          ┌────────────────────┘      │          └──────────────────┐
          │                           │                             │
   ┌──────▼──────┐           ┌────────▼────────┐           ┌───────▼──────┐
   │ SensorAgent │           │   CraneAgent    │           │ ProcessAgent │
   │             │           │                 │           │              │
   │ Polls Modbus│           │ asyncio.Lock    │           │ asyncio.Task │
   │ every 2s    │           │ (one move at    │           │ per machine  │
   │             │           │  a time)        │           │              │
   │ Publishes:  │           │ Publishes:      │           │ Publishes:   │
   │ PartDetected│           │ WorkOrder       │           │ ProcessCompl-│
   │ SensorUpdate│           │   Complete      │           │   ete        │
   └─────────────┘           └─────────────────┘           └──────────────┘
                                      ▲                           ▲
                                      │ WorkOrder                 │ StartProcess
                                      │                           │
                        ┌─────────────┴───────────────────────────┴────────┐
                        │              OversightAgent  (LLM brain)         │
                        │                                                  │
                        │  Subscribes to: ALL events                       │
                        │  Maintains:     FactoryState                     │
                        │  Calls:         GPT-4.1-mini on significant      │
                        │                 events (crane free only)         │
                        │                                                  │
                        │  Decides: pick_to_process / pick_to_output / wait│
                        └──────────────────────────────────────────────────┘
```

## The Four Agents

### SensorAgent
Polls hardware sensors every 2 seconds. Uses **rising-edge detection** — only publishes a `PartDetected` event on the 0→1 transition so the OversightAgent is not flooded with repeated signals while a part sits at a station.

### CraneAgent
Pure hardware executor — no LLM. Waits for `WorkOrder` messages, acquires an `asyncio.Lock`, then performs the pick-and-place sequence:

```
move to pick_x at Y=82 → vacuum ON → move to place_x at Y=82 → vacuum OFF → park at Y=200
```

The lock serialises all physical crane operations. Because `hardware.safe_move()` uses `asyncio.sleep`, the event loop is not blocked during crane movement — other agents (ProcessAgent, SensorAgent) continue running concurrently.

### ProcessAgent
Spawns an independent `asyncio.Task` for each `StartProcess` command. Both machines can run simultaneously because they hold no crane lock. Each task: start machine (Modbus write) → sleep `PROCESS_TIME` seconds → stop machine → publish `ProcessComplete`.

### OversightAgent — the LLM brain
Receives **every event** on the bus. Maintains a `FactoryState` in memory (no hardware polling). Calls GPT-4.1-mini when the crane is free and something actionable happened. The full factory state is sent as JSON; the LLM responds with exactly one JSON action:

```json
{"action": "pick_to_process", "part_id": 2, "part_type": 2, "pick_x": 158, "place_x": 650}
{"action": "pick_to_output",  "part_id": 1, "part_type": 1, "pick_x": 450}
{"action": "wait"}
```

**Decision rules given to the LLM:**
- While a machine is running → use the crane to pick waiting source parts (opportunistic)
- When a machine is done and a source part is also waiting → prefer `pick_to_output` first
- One crane operation at a time (physical constraint)

## Concurrency: How Two Things Happen at Once

The key insight is that `asyncio.sleep` yields control back to the event loop. While the crane is sleeping between moves, `ProcessAgent._run_machine` is also sleeping for its machine cycle. Both run within a single thread, interleaved by the event loop.

**Example timeline with both sources active:**

```
T+0   SensorAgent: source1 detected → PartDetected
      OversightAgent LLM → pick_to_process(part1, source1 → process1)
      CraneAgent: acquires lock, starts moving to X=55

T+12  Crane delivers part1 to X=450 → WorkOrderComplete
      OversightAgent: publishes StartProcess(machine1) ← machine starts AFTER part arrives
      Machine1 running for 12s (until T+24)
      crane_busy=False → LLM called

      LLM sees: machine1 running, source2 has a part waiting
      → pick_to_process(part2, source2 → process2)   ← crane picks source2 WHILE machine1 runs

T+12  Crane starts moving toward source2 (X=158)

T+24  Crane delivers part2 to X=650       ← concurrent with machine1 finishing
      Machine1 finishes → ProcessComplete
      Machine2 starts for part2

      OversightAgent LLM → pick_to_output(part1, X=450 → output)

T+36  Part1 delivered to output
      LLM → pick_to_output(part2, X=650 → output)
```

The log evidence of concurrency: `[MODBUS] reg[4] ← 1` (machine start) appears while crane move lines are still printing, and `Machine 1 done` prints before the secondary crane WorkOrder completes.

## Safety

**`hardware.safe_move(target_x, target_y)`** always executes three steps, enforced in Python — the LLM cannot bypass this:
1. Rise to Y=200 if not already at travel height
2. Move horizontally to target_x
3. Lower to target_y

On startup, `hardware.initialize()` forces the crane to Y=200 to establish a known safe state.

## File Structure

```
fully-autonomous/
├── main.py           # entry point — "start factory" prompt, wires everything
├── config.py         # positions, timings, AsyncOpenAI client
├── hardware.py       # async Modbus layer, safe_move()
├── messages.py       # event dataclasses (PartDetected, WorkOrder, etc.)
├── bus.py            # async pub/sub message bus
└── agents/
    ├── base.py       # BaseAgent ABC
    ├── sensor.py     # polls sensors, rising-edge PartDetected
    ├── crane.py      # asyncio.Lock executor
    ├── process.py    # per-machine asyncio.Task runner
    └── oversight.py  # LLM brain (GPT-4.1-mini via AsyncOpenAI)
```

## Tuning

| Parameter | File | Default | Effect |
|---|---|---|---|
| `PROCESS_TIME` | `config.py` | 12s | How long a machine runs. Must be > 2×MOVE_DELAY for concurrency to be visible |
| `MOVE_DELAY` | `config.py` | 3s | Seconds per crane move segment (rise / horizontal / lower) |
| `SENSOR_POLL` | `config.py` | 2s | How often SensorAgent reads hardware |
| `MODEL` | `config.py` | `gpt-4.1-mini` | LLM used by OversightAgent |

## Differences from Semi-Autonomous Version

| | `main.py` (semi-autonomous) | `fully-autonomous/main.py` |
|---|---|---|
| Concurrency | Sequential: one operation at a time | True concurrent: crane + process machines run simultaneously |
| Decision maker | Hardcoded Python orchestrator | GPT-4.1-mini via AsyncOpenAI on each event |
| Agent communication | Function calls through orchestrator | Pub/sub event bus — agents are peers |
| LLM calls | `plan_run()` — JSON plan, 1 call per task | `AsyncOpenAI` — 1 call per significant event |
| Hardware timing | `time.sleep` (blocks everything) | `asyncio.sleep` (yields to event loop) |
