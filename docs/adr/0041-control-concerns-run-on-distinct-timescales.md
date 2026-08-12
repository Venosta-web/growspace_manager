# Control concerns run on distinct timescales

Agronomic crop-steering decisions remain minute-scale, actuator and flow verification react to events or second-scale observations, and analytics and optimization run from multi-minute through daily horizons. These paths share Requested Shot and Execution Ledger semantics but not one universal polling loop. The separation adds orchestration boundaries, but avoids making biological control noisy merely to detect hydraulic failures promptly.
