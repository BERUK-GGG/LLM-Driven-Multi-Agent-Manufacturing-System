# Semi-Autonomous Factory — Multi-Agent System

An LLM-orchestrated crane factory where GPT-4.1-mini plans each task as a JSON action sequence. Three specialized agents handle sensing, crane movement, and process machine control — but a Python orchestrator sequences them and all concurrency decisions remain in code.



## The Three Agents

### SourceAgent
Uses OpenAI function calling to invoke `read_sensors`. Returns a JSON object:
```json
{"source1": true, "source2": false}
```
The orchestrator uses this to decide which parts have arrived.

### CraneAgent — `plan_run()` mode
Receives a task description like `"Pick from source1 X=55. Deliver to process1 X=450."` and returns a complete JSON action plan in a single API call:
```json
{"steps": [
  {"tool": "move_crane",  "args": {"x": 55,  "y": 82}},
  {"tool": "set_vacuum",  "args": {"on": true}},
  {"tool": "move_crane",  "args": {"x": 450, "y": 82}},
  {"tool": "set_vacuum",  "args": {"on": false}},
  {"tool": "move_crane",  "args": {"x": 450, "y": 200}}
]}
```
Python walks the steps and executes each tool call directly — no back-and-forth with the API.

### ProcessAgent — `plan_run()` mode
Same pattern: one prompt → JSON plan with `set_process(on=True)`, sleep, `set_process(on=False)`.

## Why `plan_run()` Instead of `run()`

The iterative `run()` loop makes one API round-trip per tool call — for a full pick-and-place that's ~16 calls. `plan_run()` collapses this into one call that returns the entire sequence upfront. For deterministic, predictable tasks like crane movement this is both faster and cheaper.

`run()` is still used by SourceAgent because sensor reads are interactive — the agent needs the actual sensor value before it can produce its output.

## Safety

`hardware.safe_move(target_x, target_y)` always executes three steps, enforced in Python:
1. Rise to Y=200 (travel height) if not already there
2. Move horizontally to `target_x`
3. Lower to `target_y`

The LLM can pass any X/Y values — `safe_move` ensures the crane never sweeps laterally at pick height. On startup, `hardware.initialize()` forces the crane to Y=200.

## Sequence for One Part (Type 1)

```
Orchestrator senses source1 → part queued

CraneAgent plan_run:
  move X=55,  Y=82   → vacuum ON    (pick from source1)
  move X=450, Y=82   → vacuum OFF   (deliver to process1)
  move X=450, Y=200  (park)

ProcessAgent plan_run:
  set_process(1, ON) → sleep 12s → set_process(1, OFF)

CraneAgent plan_run:
  move X=450, Y=82   → vacuum ON    (pick from process1)
  move X=945, Y=82   → vacuum OFF   (deliver to output)
  move X=450, Y=200  (park)
```

Operations are sequential — the crane finishes before the process starts, and the process finishes before the output pick begins. For true concurrency (crane + machine simultaneously), see the [fully-autonomous system](../fully-autonomous/README.md).

## File Structure

```
semi-autonomous/
├── main.py          # entry point
├── config.py        # OpenAI client, positions, timing constants
├── hardware.py      # sync Modbus layer, safe_move()
├── tools.py         # tool implementations + OpenAI function schema
├── agents.py        # Agent class (run / plan_run) + system prompts
└── orchestrator.py  # Orchestrator: sense loop, part queue, agent calls
```

## Tuning

| Parameter | File | Default | Effect |
|---|---|---|---|
| `MODEL` | `config.py` | `gpt-4.1-mini` | LLM for all agents |
| `MOVE_DELAY` | `config.py` | `3s` | Sleep after each crane move segment |
| `POSITIONS` | `config.py` | see file | X coordinates of each station |
