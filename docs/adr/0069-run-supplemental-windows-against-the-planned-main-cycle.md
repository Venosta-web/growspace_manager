# Run supplemental windows against the planned main cycle

Growspace Manager switches Home Assistant lights and switches live to support multiple windows on one output. The managed main light supplies the planned lights-on time and the stage-dependent photoperiod. Both endpoints resolve against the same local cycle, including cycles that cross midnight. Valid windows fit within the main cycle and overlap or touch without an intervening off command. A later schedule change skips individual invalid windows and preserves the valid ones.

The controller applies the state required by the current clock at startup, window boundaries, schedule changes, device reconnection and when a timed Lights Manual Override clears or expires. A delayed controller can run the rest of the current window. A device that loses contact while on can stay on until Home Assistant can command it again.

Each output is assigned to at most one growspace and lighting role. The Growlights editor saves Supplemental Lights directly so it can surface the result of releasing the old output with the edit still open.
