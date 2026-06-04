# SCARA-ROBOT
A laboratory workflow automation server utilizing the Hitbot SCARA robotic arm.
Supports protocol design, command translation, robot execution, and automated liquid handling across MEA, TIP, SOURCE, and JIG targets.

# Overview
This repository presents the server architecture for automating MEA (Microelectrode Array) biosensor experiments.
The server translates user-defined experimental protocols into sequential robot motion commands,
enabling fully automated execution of surface functionalization, bacterial sample handling, PBS washing, and electrochemical measurements (CV/EIS).

# Architecture
The server is structured around the MVC (Model-View-Controller) pattern.
```
SCARA-Robot-Automated-MEA-Protocol-Server/
├── protocol_to_command_converter.py         # Protocol → robot command conversion
├── models/
│   └── protocol_model.py                    # Protocol data model
├── controllers/
│   └── protocol_controller.py               # Protocol execution controller
├── services/
│   └── grid_selection_service.py            # Grid coordinate service
├── views/
│   ├── mea_group_widget.py                  # MEA target interface
│   ├── source_group_widget.py               # Source tube interface
│   ├── tip_group_widget.py                  # Tip box interface
│   └── jig_group_widget.py                  # JIG target interface
└── config/
    ├── robot_constants_config.json          # Robot motion parameters
    └── table.yaml                           # Spatial coordinate definitions
```
**Data Flow:**
```
User designs protocol via GUI (views/)
            ↓
protocol_model.py stores protocol as structured data
            ↓
protocol_controller.py sequences execution order
            ↓
protocol_to_command_converter.py converts protocol into robot commands
            ↓
cmd_list.json (command list) → Hitbot SCARA arm executes
```

# Protocol to Command Converter
`protocol_to_command_converter.py` is the core engine of this project, consisting of 3,823 lines and approximately 60 functions.
It converts user-designed protocol JSON files into a machine-executable command list (`cmd_list.json`).

# Command
The server converts protocols into a structured JSON command list (`cmd_list.json`).
Each command maps directly to a robot interface function.

# Config
Robot behavior is defined by two configuration files.
