# Views
Views form the user interface layer of the MVC Architecture, consisting of PySide6-based widgets for protocol design. Each target group (MEA, TIP, SOURCE, JIG) is provided as an interactive grid widget that allows the user to visually select wells, tubes, and chambers, and all group widgets share a common interface so the Controller can handle them uniformly.

**jig_group_widget.py**

Implements the `JIGGroupWidget` for the JIG target group, which manages auxiliary holding positions used to temporarily store MEAs during multi-step protocols. It uses an 8 rows × 2 cols grid structure for compatibility with MEA chambers, enabling MEAs to be moved between JIG and MEA positions through gripper Pick/Place actions.

**mea_group_widget.py**

Implements the `MEAGroupWidget` for the MEA (Microelectrode Array) target group. It provides stack count management for each MEA chamber (MEA1, MEA2, MEA3, MEA-Measure), real-time validation against the `max_counts` defined in `robot_constants_config.json`, a 90° rotation to align with the physical chamber orientation, and automatic gripper Z-offset calculation through integration with the `MEAStackManager`.

**source_group_widget.py**

Implements the `SourceGroupWidget` for the SOURCE target group, arranging three source grids (SOURCE1, SOURCE2, SOURCE3) vertically, with each grid using a 3 rows × 1 col structure to represent a column of source tubes. It is a thin specialization intended for cases where a simple non-YAML instantiation is required. The heavier logic, such as Source Description mapping and volume tracking, is delegated to `UnifiedGroupWidget`.

**tip_group_widget.py**

Implements the `TIPGroupWidget` for the TIP target group, managing three pipette tip boxes (TIP1, TIP2, TIP3), each with a standard 8 rows × 12 cols layout matching a 96-position tip rack. The user can either explicitly designate which tip to use during the `Equip` action, or let the converter automatically allocate tip from unused positions when no selection is made.


**unified_group_widget.py**

Implements the `UnifiedGroupWidget` that dynamically constructs groups based on YAML configuration. It reads grid definitions, positions, and rotation parameters from YAML to assemble the UI at runtime, supporting three layout modes (horizontal, vertical, grid), 180° rotation with vertical mirroring, separate editing of Source ID and Source Description, volume tracking via `TubeInterface`, and a workflow arrow overlay for the TIP group. The `GroupWidgetFactory` instantiates the specialized `MEAGroupWidget` for the MEA group and `UnifiedGroupWidget` for the rest.
