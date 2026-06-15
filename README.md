# SCARA-ROBOT

> Automated MEA biosensor protocol server for SCARA robotic arms, integrating MVC-based protocol design, end-to-end command execution, and electrochemical measurement (CV/EIS).

# Overview

SCARA-ROBOT is the server architecture developed for our SCARA robotic arm-based MEA biosensor automation system. It translates declarative experimental protocols designed through a visual interface into sequential robot motion commands and executes them using a SCARA robotic arm, liquid handling pump, gripper, and electrochemical measurement system. The system supports the fully automated execution of surface functionalization, bacterial sample handling, PBS washing, CV/EIS measurements, and other related experimental procedures without human intervention.

What distinguishes this system is not the automation itself but the abstraction layer that decouples what the experiment intends from how the robot executes. Researchers express protocols through twelve composable actions (Equip, Eject, Pick, Place, Take, Apply, Mix, Measure, Open, Close, Wait, and Dispose), and the system automatically expands them into the full sequence of low-level motion commands while preserving complete execution traceability.

# Key Features

**Declarative Protocol Abstraction.** Researchers design experiments by visually selecting wells, tubes, and chambers, and the system translates these declarative selections into sequential robot motion commands. Twelve composable action primitives serve as the building blocks of any experimental workflow, eliminating the need for low-level robot programming.

**Hardware-Independent Configuration.** All motion parameters and spatial coordinates are externalized to **[`robot_constants_config.json/`](Config/)** and **[`table.yaml/`](Config/)**. This separation allows the same codebase to be applied to different hardware setups or workbench layouts without modifying the source code, directly supporting experimental reproducibility.

**MVC-Based Separation of Concerns.** The protocol design layer is structured around the Model-View-Controller pattern, ensuring that protocol state is managed in a single, consistent location. This separation enables independent evolution of data structures, user interfaces, and coordination logic, making the system extensible to new experimental workflows.

**End-to-End Automated Workflow.** Surface functionalization, sample handling, washing, and electrochemical measurement (CV/EIS) are executed as a single uninterrupted pipeline, producing complete experimental results rather than isolated action demonstrations.

**Accessibility for Domain Scientists.** Biologists without robotics programming experience can design complex automation protocols by visually selecting wells and tubes through the GUI. Internal identifiers (e.g., Source IDs) are decoupled from user-defined descriptions (e.g., Source Descriptions), allowing meaningful labeling without affecting protocol data stability.

**Complete Execution Traceability.** Every protocol is stored as a machine-readable command specification (cmd_list.json) that records each movement, parameter, and hardware interface call. This intermediate file enables experiment reproduction, debugging, and post-hoc analysis by preserving the full execution history of the automated workflow.


# Architecture

The system follows a three-stage pipeline. The MVC-based protocol design layer captures user intent. The protocol-to-command converter translates this intent into a machine-readable command specification. The execution layer drives the actual hardware in synchronized order.

```
SCARA-ROBOT/
├── README.md                          
├── LICENSE                            ← MIT License
├── protocol_to_command_converter.py   ← Protocol to cmd_list.json 
├── cmd_list.json                      ← Example output specification
├── MVC_Architecture/                  ← Protocol design layer
│   ├── Controller/
│   ├── Model/
│   └── View/
├── Config/                            ← Hardware configuration
│   ├── robot_constants_config.json
│   └── table.yaml
└── Execution/                         ← Hardware execution engine
    └── action_commander.py
```

**[`MVC_Architecture/`](MVC_Architecture/)** holds the protocol design layer, structured around the Model-View-Controller pattern. The **[`Model/`](MVC_Architecture/Model/)** directory manages the protocol data, the **[`View/`](MVC_Architecture/View/)** directory provides the visual interface for selecting targets such as MEA, TIP, SOURCE, and JIG, and the **[`Controller/`](MVC_Architecture/Controller/)** directory coordinates the two and synchronizes protocol state.

**[`Config/`](Config/)** holds the hardware configuration files that decouple environment-dependent values from the source code. It defines the robot's motion parameters and the spatial coordinates of the workspace, allowing the same codebase to be adapted to different hardware setups without code changes.

**[`Execution/`](Execution/)** holds the hardware execution engine. It reads the cmd_list.json command specification and drives the actual hardware in synchronized order, including the SCARA robotic arm, liquid handling pump, servo motor, gripper, electrochemical measurement system, and JIG fixture. It also incorporates safety mechanisms such as surface detection and return-to-home behavior.


# Protocol to Command Converter

protocol_to_command_converter.py converts user-designed protocols into a machine-executable command list (cmd_list.json). It parses each Process and Order sequentially, translates twelve action types into robot commands, calculates actual XYZ coordinates from grid positions, applies adaptive speed selection based on movement distance and axis combinations, and tracks tip usage and liquid volumes throughout the experiment.


# cmd_list.json

cmd_list.json is the output file generated by protocol_to_command_converter.py. The user-designed protocol is converted into machine-readable commands, each mapped directly to a robot interface function (ScaraInterface, ServoInterface, DAKENInterface, MeasurementInterface). The execution layer reads this file sequentially to perform the actual physical operations, and the file itself serves as a complete, machine-readable specification of the experiment.


# License

This work is released under the MIT License. See the [LICENSE](LICENSE) file for the full text. The MIT License permits unrestricted use, modification, and distribution, including for commercial purposes, provided that the original copyright notice and license text are preserved.

Copyright (c) 2026 iMEBS Lab
