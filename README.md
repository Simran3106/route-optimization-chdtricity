# Data-Driven Route Optimization for Chandigarh CTU Local Bus Network

BTech Computer Science / Data Science Minor Project

This project aims to develop a data-driven route recommendation and optimization system for the Chandigarh Transport Undertaking (CTU) local bus network.

The system will model the CTU bus network using geographic, route and timetable data and eventually compare conventional shortest-path algorithms such as Dijkstra and A* with a multi-criteria routing approach.

---

## Current Project Scope

The current scope is limited to:

- Chandigarh Transport Undertaking (CTU) local city buses
- CTU bus stops
- CTU routes
- Route-stop sequences
- Timetable / frequency information
- Geographic coordinates
- OpenStreetMap geographic data
- Graph-based routing
- Multi-criteria route recommendation

### Not currently included

- PUNBUS
- PRTC
- Interstate buses
- Fleet scheduling
- Driver scheduling
- Depot optimization
- Full timetable optimization
- Reinforcement learning
- Deep learning
- Complex genetic algorithms

These may be considered as future extensions.

---

# Project Structure

```text
route-optimization-chdtricity/
│
├── data/
│   ├── raw/
│   └── processed/
│
├── docs/
│   └── data_sources.md
│
├── notebooks/
│   └── exploration.ipynb
│
├── outputs/
│   ├── figures/
│   ├── maps/
│   └── results/
│
├── src/
│   ├── data_collection/
│   ├── preprocessing/
│   ├── routing/
│   └── visualisation/
│
├── .gitignore
├── README.md
└── requirements.txt