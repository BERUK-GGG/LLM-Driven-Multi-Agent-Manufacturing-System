# Legacy — Hardcoded Factory Automation

A pre-LLM baseline: crane movements and machine operations are loaded from `actions.json` and executed as a fixed sequence via Modbus TCP. No AI, no decision-making — useful for verifying raw hardware connectivity and as a reference for the register map.

## How to Run

Start the JavaFX simulation first:
```bash
java --module-path /usr/share/openjfx/lib --add-modules javafx.controls,javafx.fxml \
  -jar ../CraneSimulation/simulation.jar
```

Then run:
```bash
python auto.py
```

## How It Works

`auto.py` reads two action sequences from `actions.json` — one for each part type. For each detected part it:

1. Reads sensors (Modbus registers 17–20) to detect a part at source1 or source2
2. Executes the matching action sequence: move crane, toggle vacuum, start/stop machine
3. Logs each action to `log.csv` with a timestamp

There is no planning, no LLM call, and no dynamic routing. If both sources have parts simultaneously, they are processed one at a time in queue order.

## Files

```
legacy/
├── auto.py       # main loop — sensor poll, action execution, CSV logging
├── Agents.py     # original single-file prototype (superseded)
├── actions.json  # hardcoded pick-place-process sequences per part type
└── log.csv       # execution log (written at runtime)
```

## Differences from LLM Systems

| | Legacy | Semi-autonomous | Fully autonomous |
|---|---|---|---|
| Routing | Hardcoded in JSON | LLM decides per task | LLM decides per event |
| Concurrency | None | None | Crane + machines simultaneously |
| Adaptability | Zero | Medium | High |
| API cost | Zero | ~5 calls/part | ~1 call/event |
