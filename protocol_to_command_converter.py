import json
import os
import sys
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path

# Import config manager (optional)
try:
    from robot_constants_manager import RobotConstantsManager
    HAS_CONFIG_MANAGER = True
except ImportError:
    HAS_CONFIG_MANAGER = False
    print("Cannot import config manager. Using default values.")


class ProtocolToCommandConverter:
    """Class that converts Protocol JSON into a Command List."""
    
    def __init__(self, protocol_dir: str = "./protocol", 
                 table_coords_file: str = "table_coordinates.json",
                 tube_interface=None,
                 stack_manager=None):
        """
        Initialize
        
        Args:
            protocol_dir: Directory containing Protocol JSON files
            table_coords_file: JSON file containing table coordinate info
            tube_interface: Tube interface (optional, for tube status queries)
        """
        # Initialize config manager
        if HAS_CONFIG_MANAGER:
            try:
                self.config_manager = RobotConstantsManager()
            except Exception as e:
                print(f"Config manager initialization failed: {e}. Using default values.")
                self.config_manager = None
        else:
            self.config_manager = None
        
        # Load constant values from config
        self._load_constants_from_config()
        
        self.protocol_dir = Path(protocol_dir)
        self.table_coords_file = table_coords_file
        self.table_coords = self._load_table_coordinates()
        self.tube_interface = tube_interface  # for tube status queries
        
        # State tracking variables
        self.current_tip_position = 0  # Current tip position in use
        self.current_source_volumes = {}  # Remaining volume for each source
        self.equipped_tip = False  # Tip equipped state
        
        # Track tip grid usage state
        self.tip_grid_usage = self._initialize_tip_grid_usage()
        
        # State variables for liquid volume tracking
        self.liquid_tracking = {
            'current_take_amount': 0,      # Total volume taken so far
            'current_apply_amount': 0,     # Total volume applied so far
            'remaining_amount': 0,         # Remaining volume (take - apply)
            'process_started': False       # Whether process has started
        }
        
        # Track previous position (for determining move command speed)
        self._last_position = None     # [x, y, z] or None
        
        # Source Desc mapping (for converting Source Desc -> Source ID)
        self.source_desc_mapping = {}  # Extracted from grid_name_mapping
        self.source_desc_to_id = {}   # Reverse mapping (source_desc -> source_id)
        
        # Initialize calibration manager
        try:
            from utils.calibration_manager import CalibrationManager
            self.calibration_manager = CalibrationManager()
        except ImportError:
            print("Cannot import CalibrationManager. Calibration features will be disabled.")
            self.calibration_manager = None
        
        # Initialize MEA Stack Manager and Height Calculator
        try:
            from models.mea_stack_manager import MEAStackManager
            from utils.mea_height_calculator import MEAHeightCalculator
            # Use externally provided stack_manager if available, otherwise create new
            if stack_manager is not None:
                self.stack_manager = stack_manager
                print(f"[DEBUG] ProtocolToCommandConverter: Using externally provided stack_manager")
            else:
                self.stack_manager = MEAStackManager()
                print(f"[DEBUG] ProtocolToCommandConverter: Creating new stack_manager (separate from GUI)")
            self.height_calculator = MEAHeightCalculator(self.stack_manager)
        except ImportError as e:
            print(f"Unable to import MEA Stack Manager: {e}. MEA stack functionality disabled.")
            self.stack_manager = None
            self.height_calculator = None
    
    def _load_constants_from_config(self):
        """Load constant values from config."""
        if self.config_manager:
            # Speed-related
            self.default_speed = self.config_manager.get("speed", "default_speed") or 100
            self.single_axis_speed = self.config_manager.get("speed", "single_axis_speed") or 5
            self.tip_equip_descent_speed = self.config_manager.get("speed", "tip_equip_descent_speed") or 10
            self.tip_equip_fast_z_axis_speed = self.config_manager.get("speed", "tip_equip_fast_z_axis_speed") or 50
            self.long_distance_z_axis_speed = self.config_manager.get("speed", "long_distance_z_axis_speed") or 50
            self.long_distance_single_axis_speed = self.config_manager.get("speed", "long_distance_single_axis_speed") or 50
            self.multi_axis_intermediate_speed = self.config_manager.get("speed", "multi_axis_intermediate_speed") or 50
            self.initial_position_move_to_top_speed = self.config_manager.get("speed", "initial_position_move_to_top_speed") or 50
            
            # Threshold-related
            self.consecutive_movement_threshold = self.config_manager.get("threshold", "consecutive_movement_threshold") or 0.5
            self.single_axis_movement_threshold = self.config_manager.get("threshold", "single_axis_movement_threshold") or 0.1
            self.short_distance_threshold = self.config_manager.get("threshold", "short_distance_threshold") or 20
            
            # Offset/distance-related
            self.tip_equip_fast_z_offset = self.config_manager.get("offset_distance", "tip_equip_fast_z_offset") or 10
            self.dynamic_surface_offset = self.config_manager.get("offset_distance", "dynamic_surface_offset") or 5.0
            self.mea_apply_z_offset = self.config_manager.get("offset_distance", "mea_apply_z_offset") or 11.5
            self.mea_take_z_offset = self.config_manager.get("offset_distance", "mea_take_z_offset") or 1.0
            self.take_z_offset_after_aspiration = self.config_manager.get("offset_distance", "take_z_offset_after_aspiration") or 0.45
            
            # Grid-related
            default_grid = self.config_manager.get("grid", "default_tip_grid")
            if default_grid:
                self.default_tip_grid_rows = default_grid.get("rows", 8)
                self.default_tip_grid_cols = default_grid.get("cols", 12)
            else:
                self.default_tip_grid_rows = 8
                self.default_tip_grid_cols = 12
            
            mea_grid = self.config_manager.get("grid", "mea_tip_grid")
            if mea_grid:
                self.mea_tip_grid_rows = mea_grid.get("rows", 8)
                self.mea_tip_grid_cols = mea_grid.get("cols", 2)
            else:
                self.mea_tip_grid_rows = 8
                self.mea_tip_grid_cols = 2
            
            # Surface detection-related
            self.post_aspiration_minor_spit_amount = self.config_manager.get("surface_detection", "post_aspiration_minor_spit_amount") or 30
            
            # Wait time-related
            self.spit_minor_amount_pre_wait = self.config_manager.get("wait_time", "spit_minor_amount_pre_wait") or 1.0
            
            # Initial position-related
            initial_pos = self.config_manager.get("position", "initial_position")
            if initial_pos and 'servo' in initial_pos:
                self.initial_servo_angle = initial_pos['servo'].get('angle', 60)
            else:
                self.initial_servo_angle = 60
        else:
            # Default values
            self.default_speed = 100
            self.single_axis_speed = 5
            self.tip_equip_descent_speed = 10
            self.tip_equip_fast_z_axis_speed = 50
            self.long_distance_z_axis_speed = 50
            self.long_distance_single_axis_speed = 50
            self.multi_axis_intermediate_speed = 50
            self.consecutive_movement_threshold = 0.5
            self.single_axis_movement_threshold = 0.1
            self.short_distance_threshold = 20
            self.initial_servo_angle = 60  # Default initial servo angle
            self.tip_equip_fast_z_offset = 10
            self.dynamic_surface_offset = 5.0
            self.mea_apply_z_offset = 11.5
            self.mea_take_z_offset = 1.0
            self.take_z_offset_after_aspiration = 0.45
            self.default_tip_grid_rows = 8
            self.default_tip_grid_cols = 12
            self.mea_tip_grid_rows = 8
            self.mea_tip_grid_cols = 2
            self.post_aspiration_minor_spit_amount = 30
            self.spit_minor_amount_pre_wait = 1.0
        
    def _load_table_coordinates(self) -> Dict[str, Any]:
        """Load table coordinates information"""
        print(f"[DEBUG] Attempting to load table_coordinates.json: {self.table_coords_file}")
        try:
            with open(self.table_coords_file, 'r', encoding='utf-8') as f:
                coords = json.load(f)
                print(f"[DEBUG] table_coordinates.json loaded successfully")
                print(f"[DEBUG] Loaded tools: {list(coords.get('tools', {}).keys())}")
                return coords
        except FileNotFoundError:
            print(f" [DEBUG] Warning: {self.table_coords_file} file not found.")
            return {}
        except json.JSONDecodeError as e:
            print(f"[DEBUG] Warning: {self.table_coords_file} file parsing error: {e}")
            return {}
    
    def convert_protocol_file(self, protocol_file: str) -> List[Dict[str, Any]]:
        """
        Convert Protocol JSON file to Command List
        
        Args:
            protocol_file: Protocol JSON file name
            
        Returns:
            Command List array
        """
        # Add protocol_dir only if it is not an absolute path
        if not os.path.isabs(protocol_file) and not protocol_file.startswith('protocol/'):
            protocol_path = self.protocol_dir / protocol_file
        else:
            protocol_path = Path(protocol_file)
        
        if not protocol_path.exists():
            raise FileNotFoundError(f"Protocol file not found: {protocol_path}")
        
        with open(protocol_path, 'r', encoding='utf-8') as f:
            protocol_data = json.load(f)
        
        # Extract Source Desc mapping (Source Desc -> Source ID conversion)
        self.source_desc_mapping = protocol_data.get('grid_name_mapping', {})
        if self.source_desc_mapping:
            # Extract mapping only for SOURCE group (source_id -> source_desc format)
            source_mapping = {}
            for group_name in ['SOURCE', 'SOURCES']:
                if group_name in self.source_desc_mapping:
                    # Create reverse mapping (source_desc -> source_id)
                    for source_id, source_desc in self.source_desc_mapping[group_name].items():
                        source_mapping[source_desc] = source_id
            self.source_desc_to_id = source_mapping
            print(f"[DEBUG] Source Desc mapping loaded: {self.source_desc_to_id}")
        else:
            self.source_desc_to_id = {}
            print(f"[DEBUG] Source Desc mapping not found")
        
        # Initialize state before conversion (consistency guarantee)
        self.reset_state()
        
        # Debug: Output protocol data read from file
        print(f"\n{'='*80}")
        print(f"[DEBUG] convert_protocol_file - input protocol data")
        print(f"File path: {protocol_path}")
        print(f"{'='*80}")
        print(json.dumps(protocol_data, ensure_ascii=False, indent=2))
        print(f"{'='*80}\n")
        
        return self.convert_protocol_data(protocol_data)
    
    def convert_protocol_data(self, protocol_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Convert Protocol data to Command List
        
        Args:
            protocol_data: Protocol data dictionary
            
        Returns:
            Command List array
        """
        # Extract Source Desc mapping (Source Desc -> Source ID conversion)
        # May have already been processed in convert_protocol_file, but guard for direct calls
        print(f"[DEBUG] convert_protocol_data started - checking grid_name_mapping...")
        if 'grid_name_mapping' in protocol_data:
            self.source_desc_mapping = protocol_data.get('grid_name_mapping', {})
            print(f"[DEBUG] grid_name_mapping found: {self.source_desc_mapping}")
            if self.source_desc_mapping:
                # Extract mapping only for SOURCE group (source_id -> source_desc format)
                source_mapping = {}
                for group_name in ['SOURCE', 'SOURCES']:
                    if group_name in self.source_desc_mapping:
                        print(f"[DEBUG] Group '{group_name}' mapping processing: {self.source_desc_mapping[group_name]}")
                        # Build reverse mapping (source_desc -> source_id)
                        for source_id, source_desc in self.source_desc_mapping[group_name].items():
                            source_mapping[source_desc] = source_id
                            print(f"[DEBUG] Reverse mapping added: '{source_desc}' -> '{source_id}'")
                self.source_desc_to_id = source_mapping
                print(f"[DEBUG] Source Desc mapping loaded (convert_protocol_data): {self.source_desc_to_id}")
            else:
                self.source_desc_to_id = {}
                print(f"[DEBUG] Source Desc mapping not found (convert_protocol_data) - source_desc_mapping is empty")
        else:
            print(f"[DEBUG] grid_name_mapping not found in protocol_data")
            # Keep existing mapping if present, otherwise use empty dict
            if not hasattr(self, 'source_desc_to_id'):
                self.source_desc_to_id = {}
        
        # Guard for cases where convert_protocol_file() was not called
        # (tip_grid_usage must be preserved, so do not reset in reset_state())
        # reset_state() has already been updated to not reset tip_grid_usage
        # Note: reset_state() already called in convert_protocol_file(), skip here
        # But verify for cases where CommandListGenerator.generate() calls directly
        
        # Debug: print current state
        print(f"\n{'='*60}")
        print(f"[DEBUG] Checking current state")
        print(f"Tip grid usage state:")
        for tip_name, usage_list in self.tip_grid_usage.items():
            used_count = sum(usage_list)
            total_count = len(usage_list)
            print(f"  {tip_name}: {used_count}/{total_count} used")
        print(f"equipped_tip: {self.equipped_tip}")
        print(f"current_tip_position: {self.current_tip_position}")
        print(f"{'='*60}\n")
        
        # Debug: print protocol data received from memory
        print(f"\n{'='*80}")
        print(f"[DEBUG] convert_protocol_data - input protocol data")
        print(f"Data source: memory (protocol_dict)")
        print(f"{'='*80}")
        print(json.dumps(protocol_data, ensure_ascii=False, indent=2))
        print(f"{'='*80}\n")
        
        command_list = []
        command_number = 1
        
        # Add protocol description
        if 'description' in protocol_data:
            command_list.append({
                "type": "protocol_info",
                "name": "Protocol_Info",
                "description": protocol_data['description']
            })
        
        # 1. move to top
        command_list.append({
            "type": "initialization",
            "action": "move_to_top",
            "function": "ScaraInterface.move_to_top",
            "parameters": {},
            "description": "Move to top position"
        })
        
        # 2. Move to 420,0,0 (initial position)
        initial_xyz = [420, 0, 0]
        speed = self._calculate_speed_for_position(initial_xyz)
        command_list.append({
            "type": "initialization",
            "action": "move_xy_position",
            "function": "ScaraInterface.move_end_effector",
            "parameters": {
                "end_effector": "gripper",
                "xyz": initial_xyz,
                "tip": False,
                "speed": speed
            },
            "description": "Move to initial position (420, 0, 0)"
        })
        
        # 3. Set end effector to initial position (using initial servo angle from config)
        initial_servo_angle = getattr(self, 'initial_servo_angle', 60)
        command_list.append({
            "type": "initialization",
            "action": "set_end_effector",
            "function": "ServorInterface.move_to_angle",
            "parameters": {"angle": initial_servo_angle},
            "description": f"Set end-effector to initial position (servo angle: {initial_servo_angle}°)"
        })
        
        # Process each process (sorted in same order as Tree Viewer)
        processes_list = protocol_data.get('processes', [])
        # Sort processes by name (same order as Tree Viewer)
        sorted_processes = sorted(processes_list, key=lambda x: x.get('name', ''))
        print(f"[DEBUG] Processing processes: total {len(sorted_processes)} processes found (sorted by name)")
        for idx, process in enumerate(sorted_processes):
            process_name = process.get('name', 'Unknown')
            print(f"[DEBUG] Processing process {idx + 1}/{len(sorted_processes)}: {process_name}")
            process_commands = self._process_orders(process, command_number)
            print(f"[DEBUG] {len(process_commands)} commands generated for process '{process_name}'")
            command_list.extend(process_commands)
            command_number += len(process_commands)
            
            # Process GUI events (prevent blocking) - only if PySide6 is available
            try:
                from PySide6.QtWidgets import QApplication
                QApplication.processEvents()
            except ImportError:
                pass  # Ignored in environments without PySide6
        
        # Applying auto tip positions to all commands
        command_list = self._apply_auto_tip_positions_to_all_commands(command_list)
        
        # Debug: print conversion result
        print(f"\n{'='*80}")
        print(f"[DEBUG] Conversion completed - Command List result")
        print(f"Total command count: {len(command_list)}")
        print(f"{'='*80}")
        for i, cmd in enumerate(command_list, 1):
            print(f"{i:2d}. {cmd.get('type', 'unknown')} - {cmd.get('action', 'unknown')}: {cmd.get('description', '')}")
        print(f"{'='*80}\n")
        
        return command_list
    
    def _process_orders(self, process: Dict[str, Any], start_command_number: int) -> List[Dict[str, Any]]:
        """Convert process orders into command list."""
        commands = []
        command_number = start_command_number
        
        # Start process
        commands.append({
            "type": "process_start",
            "name": process['name'],
            "description": process.get('description', '')
        })
        
        # Initialize liquid tracking state at process start
        self.liquid_tracking = {
            'current_take_amount': 0,
            'current_apply_amount': 0,
            'remaining_amount': 0,
            'process_started': False
        }
        print(f"[DEBUG] Process '{process['name']}' started - initializing liquid tracking state")
        
        # Process each order
        for order_idx, order in enumerate(process.get('orders', [])):
            order_commands = self._convert_order_to_commands(order, command_number, process['name'], order_idx)
            commands.extend(order_commands)
            command_number += len(order_commands)
            
            # Process GUI events (prevent blocking) - only if PySide6 is available
            try:
                from PySide6.QtWidgets import QApplication
                QApplication.processEvents()
            except ImportError:
                pass  # Ignored in environments without PySide6
        
        # End process
        commands.append({
            "type": "process_end",
            "name": process['name']
        })
        
        return commands
    
    def _convert_order_to_commands(self, order: Dict[str, Any], start_command_number: int, process_name: str = None, order_index: int = None) -> List[Dict[str, Any]]:
        """Convert individual order into command list."""
        action = order.get('action', '').lower()
        commands = []
        command_number = start_command_number
        
        # Metadata to include order info in each command
        order_meta = {}
        if process_name is not None:
            order_meta['process_name'] = process_name
        if order_index is not None:
            order_meta['order_index'] = order_index
        
        if action == 'equip':
            order_commands = self._create_equip_commands(order, command_number)
        elif action == 'eject':
            order_commands = self._create_eject_commands(order, command_number)
        elif action == 'pick':
            order_commands = self._create_pick_commands(order, command_number)
        elif action == 'place':
            order_commands = self._create_place_commands(order, command_number)
        elif action == 'take':
            order_commands = self._create_take_commands(order, command_number)
        elif action == 'apply':
            order_commands = self._create_apply_commands(order, command_number)
        elif action == 'dispose':
            order_commands = self._create_dispose_commands(order, command_number)
        elif action == 'wait':
            order_commands = self._create_wait_commands(order, command_number)
        elif action == 'measure':
            order_commands = self._create_measure_commands(order, command_number)
        elif action == 'open':
            order_commands = self._create_open_commands(order, command_number)
        elif action == 'close':
            order_commands = self._create_close_commands(order, command_number)
        elif action == 'mix':
            order_commands = self._create_mix_commands(order, command_number)
        else:
            order_commands = []
        
        # Add order info to each command
        for cmd in order_commands:
            if order_meta:
                cmd.update(order_meta)
        
        commands.extend(order_commands)
        return commands
    
    def _create_equip_commands(self, order: Dict[str, Any], start_command_number: int) -> List[Dict[str, Any]]:
        """Create commands for Equip action."""
        commands = []
        command_number = start_command_number
        
        print(f"\n{'='*60}")
        print(f"[DEBUG] _create_equip_commands started")
        print(f"  equipped_tip: {self.equipped_tip}")
        print(f"  current_tip_position: {self.current_tip_position}")
        print(f"  order: {order}")
        print(f"{'='*60}")
        
        if self.equipped_tip:
            # Skip if tip is already equipped
            print(f"[DEBUG] Tip already equipped - skipping Equip action")
            commands.append({
                "type": "equip",
                "action": "skip_equip",
                "function": "none",
                "parameters": {},
                "description": "Tip already equipped"
            })
            return commands
        
        # Set end-effector to pipette
        commands.append({
            "type": "equip",
            "action": "set_end_effector",
            "function": "ServorInterface.move_to_angle",
            "parameters": {"angle": 60},
            "description": "Set end-effector to pipette"
        })
        
        # Calculate tip position and move
        tip_positions = []  # List to store multiple tip positions
        tip_tool_name = None
        
        # If target is none or missing, auto-calculate unused tip grid position
        target = order.get('target', 'none')
        print(f"[DEBUG] Equip action - target: {target}")
        
        if target == 'none' or target == {}:
            # Auto-calculate unused tip grid position
            print(f"[DEBUG] Calculating auto tip position...")
            tip_data = self._get_next_available_tip_position()
            print(f"[DEBUG] Auto tip position result: {tip_data}")
            if tip_data:
                tip_position, tip_tool_name, tip_grid_index = tip_data
                tip_positions = [tip_position]  # Convert single position to list
                # Store actual grid index for auto-assigned case
                self._auto_tip_grid_index = tip_grid_index
                print(f"[DEBUG] Storing auto-assigned grid index: {tip_grid_index}")
        else:
            # Extract tip position from target
            print(f"[DEBUG] Extracting tip position from target...")
            target_positions = self._extract_target_positions(target)
            print(f"[DEBUG] Extracted target_positions: {target_positions}")
            
            tip_grid_index_from_target = None  # For storing grid_index on manual selection
            
            if target_positions:
                # Collect all TIP positions
                for pos, tool_name, grid_index in target_positions:
                    if 'tip' in tool_name.lower():  # Process only TIP-related tools
                        tip_positions.append(pos)
                        if tip_tool_name is None:  # Store first TIP tool name
                            tip_tool_name = tool_name
                            tip_grid_index_from_target = grid_index  # Store grid_index of first TIP
                        print(f"[DEBUG] Adding TIP position: pos={pos}, tool_name={tool_name}, grid_index={grid_index}")
                
                print(f"[DEBUG] Total {len(tip_positions)}TIP positions found")
            else:
                print(f"[DEBUG] TIP position not found - attempting auto position calculation")
                # Auto-calculate if TIP position not found
                tip_data = self._get_next_available_tip_position()
                if tip_data:
                    tip_position, tip_tool_name, tip_grid_index = tip_data
                    tip_positions = [tip_position]
                    tip_grid_index_from_target = tip_grid_index
        
        print(f"[DEBUG] Final TIP positions: {tip_positions}")
        print(f"[DEBUG] TIP tool name: {tip_tool_name}")
        print(f"[DEBUG] TIP position count: {len(tip_positions)}")
        
        if tip_positions and tip_tool_name:
            # Use first tip position as default (independent per call)
            current_tip_position = tip_positions[0]  # Changed to local variable
            self._current_tip_position = current_tip_position
            self._current_tip_tool_name = tip_tool_name
            
            # Use actual found grid index
            if target == 'none' or target == {}:
                # Auto-assigned: use stored grid index
                if hasattr(self, '_auto_tip_grid_index'):
                    self._current_tip_grid_index = self._auto_tip_grid_index
                    print(f"[DEBUG] Auto-assigned - using stored grid index: {self._auto_tip_grid_index}")
                else:
                    self._current_tip_grid_index = 0
                    print(f"[DEBUG] Auto-assigned - no stored grid index, using 0")
            else:
                # Manual selection: use extracted grid_index
                if tip_grid_index_from_target is not None and tip_grid_index_from_target >= 0:
                    self._current_tip_grid_index = tip_grid_index_from_target
                    print(f"[DEBUG] Manual selection - using extracted grid index: {tip_grid_index_from_target}")
                else:
                    # Set to 0 if grid_index not found (e.g. gripper action)
                    self._current_tip_grid_index = 0
                    print(f"[DEBUG] Manual selection - grid_index not found, using 0")
            
            print(f"[DEBUG] Final tip position set: pos={current_tip_position}, tool={tip_tool_name}, grid_index={self._current_tip_grid_index}")
            print(f"[DEBUG] Total {len(tip_positions)} tip positions found, using first position")
            
            print(f"[DEBUG] Equip command creation start")
            
            # Step 1: Move to top from current position
            print(f"[DEBUG] Step 1: creating move_to_top command")
            commands.append({
                "type": "equip",
                "action": "move_to_top",
                "function": "ScaraInterface.move_to_top",
                "parameters": {
                    "end_effector": "pipette",
                    "xyz": [0, 0, 0],  # Top position from current location
                    "tip": False
                },
                "description": "Move to top from current position"
            })
            
            # Step 2: Move X,Y only (from top) - Use current tip position
            print(f"[DEBUG] Step 2: creating move_xy_position command")
            print(f"[DEBUG] Coordinates to use: {current_tip_position}")
            target_xyz = [current_tip_position[0], current_tip_position[1], 0]
            speed = self._calculate_speed_for_position(target_xyz)
            
            # Check and add calibration data
            calibration_params = {}
            if self.calibration_manager:
                calib_data = self.calibration_manager.get_calibration_angles(tip_tool_name)
                if calib_data:
                    # Calculate row, col from grid_index
                    # tip box: 8 rows x 12 cols -> row = grid_index // 12, col = grid_index % 12
                    grid_index = self._current_tip_grid_index
                    if 'tip' in tip_tool_name:
                        grid_cols = 12
                    elif 'mea' in tip_tool_name:
                        grid_cols = 2
                    else:
                        grid_cols = 12  # Default values
                    
                    grid_row = grid_index // grid_cols
                    grid_col = grid_index % grid_cols
                    
                    calibration_params = {
                        "calibration_angles": {
                            "angle1": calib_data.get('angle1'),
                            "angle2": calib_data.get('angle2'),
                            "end_effector": calib_data.get('end_effector', 'pipette'),
                            "with_tip": calib_data.get('with_tip', False)
                        },
                        "tool_name": tip_tool_name,
                        "grid_row": grid_row,
                        "grid_col": grid_col
                    }
                    print(f"[DEBUG] Adding calibration data: {tip_tool_name}, grid_index={grid_index}, row={grid_row}, col={grid_col}")
            
            command_params = {
                "end_effector": "pipette",
                "xyz": target_xyz,
                "tip": False,
                "speed": speed
            }
            command_params.update(calibration_params)
            
            commands.append({
                "type": "equip",
                "action": "move_xy_position",
                "function": "ScaraInterface.move_end_effector",
                "parameters": command_params,
                "description": f"Move X,Y to tip position: {current_tip_position}"
            })
            
            # Before Step 3: fast move to z_position + 10 (speed=50)
            z_position = self._calculate_z_position(tip_tool_name, "equip")
            fast_z_position = z_position + self.tip_equip_fast_z_offset
            print(f"[DEBUG] Before Step 3: move_z_position (z={fast_z_position}) command created (speed=50)")
            target_xyz_fast = [current_tip_position[0], current_tip_position[1], fast_z_position]
            commands.append({
                "type": "equip",
                "action": "move_z_position",
                "function": "ScaraInterface.move_end_effector",
                "parameters": {
                    "end_effector": "pipette",
                    "xyz": target_xyz_fast,
                    "tip": False,
                    "speed": self.tip_equip_fast_z_axis_speed
                },
                "description": f"Fast Z move to tip position: {fast_z_position}"
            })

            # Step 3: Descend along Z-axis - Use current tip position
            print(f"[DEBUG] Step 3: move_z_position command creation")
            target_xyz = [current_tip_position[0], current_tip_position[1], z_position]
            speed = self.tip_equip_descent_speed
            print(f"[DEBUG] Equip descent speed: {speed} (from config)")
            commands.append({
                "type": "equip",
                "action": "move_z_position",
                "function": "ScaraInterface.move_end_effector",
                "parameters": {
                    "end_effector": "pipette",
                    "xyz": target_xyz,
                    "tip": False,
                    "speed": speed
                },
                "description": f"Z move to tip position: {z_position}"
            })
            
            # Step 4: Integrated tip equip command (with retry logic)
            print(f"[DEBUG] Step 4: tip_equip_with_retry command creation")
            commands.append({
                "type": "equip",
                "action": "tip_equip_with_retry",
                "function": "CommandExecutor._execute_tip_equip_with_retry",
                "parameters": {
                    "max_retries": 3,
                    "retry_delay": 1.0,
                    "z_offset": 7
                },
                "description": "Tip attach (with retry)"
            })
            
            # Step 5: Move to top position - Use current tip position
            print(f"[DEBUG] Step 5: move_to_top command creation")
            commands.append({
                "type": "equip",
                "action": "move_to_top",
                "function": "ScaraInterface.move_to_top",
                "parameters": {
                    "end_effector": "pipette",
                    "xyz": [current_tip_position[0], current_tip_position[1], 0],  # Use current tip position
                    "tip": True
                },
                "description": f"Move to top position: {current_tip_position}"
            })
            
            # Process multiple tip positions
            if len(tip_positions) > 1:
                print(f"[DEBUG] Multiple tip position processing start: {len(tip_positions)}")
                
                # Create additional commands for each tip position
                for i, tip_pos in enumerate(tip_positions[1:], 1):  # First one already processed
                    print(f"[DEBUG] Additional tip position {i+1}/{len(tip_positions)}: {tip_pos}")
                    
                    # Commands to move to additional tip positions
                    commands.append({
                        "type": "equip",
                        "action": "move_to_top",
                        "function": "ScaraInterface.move_to_top",
                        "parameters": {
                            "end_effector": "pipette",
                            "xyz": [0, 0, 0],
                            "tip": True
                        },
                        "description": f"Move to additional tip position {i+1}"
                    })
                    
                    target_xyz = [tip_pos[0], tip_pos[1], 0]
                    speed = self._calculate_speed_for_position(target_xyz)
                    commands.append({
                        "type": "equip",
                        "action": "move_xy_position",
                        "function": "ScaraInterface.move_end_effector",
                        "parameters": {
                            "end_effector": "pipette",
                            "xyz": target_xyz,
                            "tip": True,
                            "speed": speed
                        },
                        "description": f"Move X,Y to additional tip position {i+1}"
                    })
                    
                    # Z-axis move only changes z since x,y is the same
                    z_position = self._calculate_z_position(tip_tool_name, "equip")
                    target_xyz_z = [tip_pos[0], tip_pos[1], z_position]
                    speed_z = self._calculate_speed_for_position(target_xyz_z)
                    commands.append({
                        "type": "equip",
                        "action": "move_z_position",
                        "function": "ScaraInterface.move_end_effector",
                        "parameters": {
                            "end_effector": "pipette",
                            "xyz": target_xyz_z,
                            "tip": True,
                            "speed": speed_z
                        },
                        "description": f"Z move to additional tip position {i+1}"
                    })
                    
                    commands.append({
                        "type": "equip",
                        "action": "tip_equip_with_retry",
                        "function": "CommandExecutor._execute_tip_equip_with_retry",
                        "parameters": {
                            "max_retries": 3,
                            "retry_delay": 1.0,
                            "z_offset": 7
                        },
                        "description": f"Tip {i+1} attach (with retry)"
                    })
                    
                    commands.append({
                        "type": "equip",
                        "action": "move_to_top",
                        "function": "ScaraInterface.move_to_top",
                        "parameters": {
                            "end_effector": "pipette",
                            "xyz": [0, 0, 0],
                            "tip": True
                        },
                        "description": f"Move to top after tip {i+1} attach"
                    })
                
                print(f"[DEBUG] Multiple tip position processing complete: Total {len(tip_positions)} tips processed")
            
            # Mark tip grid positions as used (all tip positions)
            for i, tip_pos in enumerate(tip_positions):
                # Calculate actual grid index: first tip uses _current_tip_grid_index, rest are sequential
                actual_grid_index = self._current_tip_grid_index + i
                self._mark_tip_position_as_used(tip_tool_name, actual_grid_index)
                print(f"[DEBUG] Tip position {i+1} marked as used: {tip_pos} (Grid Index: {actual_grid_index})")
            
            print(f"[DEBUG] Equip complete - state changed:")
            print(f"  equipped_tip: {self.equipped_tip} -> True")
            print(f"  current_tip_position: {self.current_tip_position} -> {self.current_tip_position + len(tip_positions)}")
            
            self.equipped_tip = True
            self.current_tip_position += len(tip_positions)
        else:
            print(f"[DEBUG] Tip position not found: tip_positions={tip_positions}, tip_tool_name={tip_tool_name}")
            print(f"[DEBUG] Skipping Equip action - insufficient tip position info")
        
        print(f"[DEBUG] _create_equip_commands end - commands created: {len(commands)}")
        return commands
    
    def _create_eject_commands(self, order: Dict[str, Any], start_command_number: int) -> List[Dict[str, Any]]:
        """Create commands for Eject action."""
        commands = []
        
        if not self.equipped_tip:
            commands.append({
                "type": "eject",
                "action": "skip_eject",
                "function": "none",
                "parameters": {},
                "description": "No tip equipped"
            })
            return commands
        
        # Set end-effector to pipette
        commands.append({
            "type": "eject",
            "action": "set_end_effector",
            "function": "ServorInterface.move_to_angle",
            "parameters": {"angle": 60},
            "description": "Set end-effector to pipette"
        })
        
        # Move to Tip Trash position (split into 3 steps)
        tip_trash_pos = self._get_tip_trash_position()
        if tip_trash_pos:
            # Calculate trash z position + height
            trash_z_position = self._calculate_trash_z_position("tip-trash")
            
            # Step 1: Move to top from current position
            commands.append({
                "type": "eject",
                "action": "move_to_top",
                "function": "ScaraInterface.move_to_top",
                "parameters": {
                    "end_effector": "pipette",
                    "xyz": [0, 0, 0],  # Top position from current location
                    "tip": True
                },
                "description": "Move to top from current position"
            })
            
            # Step 2: Move X,Y only (from top)
            target_xyz = tip_trash_pos + [0]
            speed = self._calculate_speed_for_position(target_xyz)
            commands.append({
                "type": "eject",
                "action": "move_xy_position",
                "function": "ScaraInterface.move_end_effector",
                "parameters": {
                    "end_effector": "pipette",
                    "xyz": target_xyz,
                    "tip": True,
                    "speed": speed
                },
                "description": "Move X,Y to Tip Trash"
            })
            
            # Step 3: Descend along Z-axis
            target_xyz_z = tip_trash_pos + [trash_z_position]
            speed_z = self._calculate_speed_for_position(target_xyz_z)
            commands.append({
                "type": "eject",
                "action": "move_z_position",
                "function": "ScaraInterface.move_end_effector",
                "parameters": {
                    "end_effector": "pipette",
                    "xyz": target_xyz_z,
                    "tip": True,
                    "speed": speed_z
                },
                "description": "Z move to Tip Trash"
            })
            
            # Remove tip
            commands.append({
                "type": "eject",
                "action": "remove_tip",
                "function": "DakenInterface.eject_tip",
                "parameters": {},
                "description": "Remove tip"
            })
            
            # Move to top position
            commands.append({
                "type": "eject",
                "action": "move_to_top",
                "function": "ScaraInterface.move_to_top",
                "parameters": {
                    "end_effector": "pipette",
                    "xyz": tip_trash_pos + [0],  # z=0 (top position)
                    "tip": False
                },
                "description": "Move to top position"
            })
            
            print(f"[DEBUG] Eject complete - State changed:")
            print(f"  equipped_tip: {self.equipped_tip} -> False")
            self.equipped_tip = False
            
            # Initialize tip position variable (so next Equip can find new position)
            if hasattr(self, '_current_tip_position'):
                print(f"[DEBUG] _current_tip_position Initialize: {self._current_tip_position} -> None")
                self._current_tip_position = None
            if hasattr(self, '_current_tip_tool_name'):
                print(f"[DEBUG] _current_tip_tool_name Initialize: {self._current_tip_tool_name} -> None")
                self._current_tip_tool_name = None
            if hasattr(self, '_current_tip_grid_index'):
                print(f"[DEBUG] _current_tip_grid_index Initialize: {self._current_tip_grid_index} -> None")
                self._current_tip_grid_index = None
        
        # Keep usage state on tip removal (tips are single-use)
        
        return commands
    
    def _create_pick_commands(self, order: Dict[str, Any], start_command_number: int) -> List[Dict[str, Any]]:
        """Create commands for Pick action."""
        commands = []
        
        # 1. Set end-effector to gripper
        commands.append({
            "type": "pick",
            "action": "set_end_effector",
            "function": "ServorInterface.move_to_angle",
            "parameters": {"angle": 240},
            "description": "Set end-effector to gripper"
        })
        
        # Process target positions
        target_positions = self._extract_target_positions(order.get('target', {}), "pick")
        for pos, tool_name, grid_index in target_positions:
            try:
                # Calculate z coordinate (with error handling)
                z_position = self._calculate_z_position(tool_name, "pick")
            except ValueError as e:
                # Add error command on error
                commands.append({
                    "type": "pick",
                    "action": "error",
                    "function": "none",
                    "parameters": {},
                    "description": f"Z coordinate calculation error: {str(e)}"
                })
                continue
            
            # pos is already the MEA center point, use as-is
            # 2. Move to top (z=0 from current x,y)
            commands.append({
                "type": "pick",
                "action": "move_to_top",
                "function": "ScaraInterface.move_to_top",
                "parameters": {},
                "description": "Move to top position"
            })
            
            # Move x,y only (x,y move from top)
            commands.append(self._create_xy_move_command(
                pos, "pick", f"Move to target X,Y position: {pos}", "gripper", tool_name
            ))
            
            # gripper open
            commands.append({
                "type": "pick",
                "action": "gripper_open",
                "function": "ScaraInterface.gripper.open",
                "parameters": {},
                "description": "Gripper open"
            })
            
            # 3. Move z only to destination (arrive at final position)
            commands.append(self._create_z_move_command(
                pos, z_position, "pick", f"Move to target Z position: {z_position}", "gripper", tool_name
            ))
            
            # gripper close
            commands.append({
                "type": "pick",
                "action": "gripper_close",
                "function": "ScaraInterface.gripper.close",
                "parameters": {
                    "action": "pick",
                    "tool_name": tool_name
                },
                "description": "Gripper close (force detection)"
            })
            
            # 4. Move to top position
            commands.append({
                "type": "pick",
                "action": "move_to_top",
                "function": "ScaraInterface.move_to_top",
                "parameters": {
                    "end_effector": "gripper",
                    "xyz": pos + [0],  # z=0 (top position)
                    "tip": False
                },
                "description": "Move to top position"
            })
        
        return commands
    
    def _create_place_commands(self, order: Dict[str, Any], start_command_number: int) -> List[Dict[str, Any]]:
        """Create commands for Place action."""
        commands = []
        
        # 1. Set end-effector to gripper
        commands.append({
            "type": "place",
            "action": "set_end_effector",
            "function": "ServorInterface.move_to_angle",
            "parameters": {"angle": 240},
            "description": "Set end-effector to gripper"
        })
        
        # Process target positions
        target_positions = self._extract_target_positions(order.get('target', {}), "place")
        for pos, tool_name, grid_index in target_positions:
            try:
                # Calculate z coordinate (with error handling)
                z_position = self._calculate_z_position(tool_name, "place")
            except ValueError as e:
                # Add error command on error
                commands.append({
                    "type": "place",
                    "action": "error",
                    "function": "none",
                    "parameters": {},
                    "description": f"Z coordinate calculation error: {str(e)}"
                })
                continue
            
            # pos is already the MEA center point, use as-is
            # 2. Move to top (z=0 from current x,y)
            commands.append({
                "type": "place",
                "action": "move_to_top",
                "function": "ScaraInterface.move_to_top",
                "parameters": {},
                "description": "Move to top position"
            })
            
            # Move x,y only (x,y move from top)
            commands.append(self._create_xy_move_command(
                pos, "place", f"Move to target X,Y position: {pos}", "gripper", tool_name
            ))
            
            # 3. Move z only to destination (arrive at final position)
            commands.append(self._create_z_move_command(
                pos, z_position, "place", f"Move to target Z position: {z_position}", "gripper", tool_name
            ))
            
            # gripper open
            commands.append({
                "type": "place",
                "action": "gripper_open",
                "function": "ScaraInterface.gripper.open",
                "parameters": {
                    "action": "place",
                    "tool_name": tool_name
                },
                "description": "Gripper open"
            })
            
            # 4. Move to top position
            commands.append({
                "type": "place",
                "action": "move_to_top",
                "function": "ScaraInterface.move_to_top",
                "parameters": {
                    "end_effector": "gripper",
                    "xyz": pos + [0],  # z=0 (top position)
                    "tip": False
                },
                "description": "Move to top position"
            })
        
        return commands
    
    def _create_take_commands(self, order: Dict[str, Any], start_command_number: int) -> List[Dict[str, Any]]:
        """Create commands for Take action."""
        commands = []
        amount = order.get('amount', 0)
        
        # Update liquid tracking state
        self.liquid_tracking['current_take_amount'] = amount
        self.liquid_tracking['remaining_amount'] = amount
        self.liquid_tracking['current_apply_amount'] = 0  # apply Initialize
        self.liquid_tracking['process_started'] = True
        
        print(f"[DEBUG] Take volume tracking: {amount}μL aspiration")
        
        if not self.equipped_tip:
            commands.append({
                "type": "take",
                "action": "error_no_tip",
                "function": "none",
                "parameters": {},
                "description": "No tip equipped"
            })
            return commands
        
        # Set end-effector to pipette
        commands.append({
            "type": "take",
            "action": "set_end_effector",
            "function": "ServorInterface.move_to_angle",
            "parameters": {"angle": 60},
            "description": "Set end-effector to pipette"
        })
        
        # Process target positions
        target_positions = self._extract_target_positions(order.get('target', {}), "take")
        
        # Check if consecutive targets
        is_consecutive = self._is_consecutive_targets(target_positions)
        print(f"[DEBUG] take target count: {len(target_positions)}, is_consecutive: {is_consecutive}")
        if len(target_positions) > 1:
            print(f"[DEBUG] First Target: {target_positions[0][0]}")
            print(f"[DEBUG] Second Target: {target_positions[1][0]}")
            axis, offset = self._calculate_offset_between_positions(target_positions[0][0], target_positions[1][0])
            print(f"[DEBUG] First->Second offset: axis={axis}, offset={offset:.2f}")
        
        # Track previous grid Z position in MEA tool (used for next grid move)
        previous_mea_z = None
        
        for i, (pos, tool_name, grid_index) in enumerate(target_positions):
            # Calculate z coordinate
            z_position = self._calculate_z_position(tool_name, "take")
            
            # Extract source_id from Target (before z move command creation)
            source_id = self._extract_source_id_from_target(order.get('target', {}), pos)
            
            # Pre-check next position: verify both current and next positions are MEA tool
            is_current_mea = self._is_mea_tool(tool_name)
            is_next_mea = False
            if i + 1 < len(target_positions):
                next_tool_name = target_positions[i + 1][1]
                is_next_mea = self._is_mea_tool(next_tool_name)
            
            # Check if inter-grid move (grid_index >= 0 and MEA tool case)
            # Take action can also trigger inter-grid move on MEA tool
            is_grid_movement = (grid_index >= 0 and is_current_mea)
            
            # Condition evaluation:
            # 1. First move (i == 0): always use move_xy_position
            # 2. Non-consecutive target case (not is_consecutive): use move_xy_position
            # 3. Inter-grid move case (is_grid_movement): use move_xy_position (angle-based precise move)
            # 4. Consecutive targets that are NOT inter-grid: use move_offset (fast move in end effector coords)
            if i == 0 or not is_consecutive or is_grid_movement:
                # If first move, non-consecutive, or inter-grid: x,y move → z move
                print(f"[DEBUG] take[{i}]: using move_xy_position (is_consecutive={is_consecutive}, is_grid_movement={is_grid_movement}), tool_name={tool_name}")
                
                # If previous grid was MEA tool and current is also MEA: maintain previous Z position
                xy_move_z = previous_mea_z if (previous_mea_z is not None and is_current_mea) else None
                commands.append(self._create_xy_move_command(
                    pos, "take", f"Move x,y to source: {pos}", "pipette", tool_name, z_position=xy_move_z
                ))
                
                # If source_id is None (MEA tool etc.): add z move command
                if source_id is None:
                    # MEA tool etc.: move to z position then aspirate directly
                    print(f"[DEBUG] take[{i}]: source_id=None (MEA tool etc.), adding z move command")
                    commands.append(self._create_z_move_command(
                        pos, z_position, "take", f"Move to target Z: {z_position}"
                    ))
                else:
                    # SOURCE tool case: z move is commented out (processed via surface detection)
                    print(f"[DEBUG] take[{i}]: source_id={source_id} (SOURCE tool), z move processed via surface detection")
                    # Commented out: processing from aspiration command to z-axis move above liquid surface
                    # commands.append(self._create_z_move_command(
                    #     pos, z_position, 'take', f'Move to source z position: {z_position}'
                    # ))
            else:
                # After second of non-consecutive inter-grid target: x,y offset move → z move
                # Note: inter-grid moves use move_xy_position per above condition, so only non-grid cases processed here
                prev_pos = target_positions[i-1][0]
                axis, offset = self._calculate_offset_between_positions(prev_pos, pos)
                print(f"[DEBUG] take[{i}]: using move_offset (not inter-grid move) - axis={axis}, offset={offset:.2f}, is_grid_movement={is_grid_movement}")
                
                commands.append(self._create_move_offset_command(
                    axis=axis,
                    offset=offset,
                    action_type="take",
                    description=f"{axis}-axis move {offset:.1f}mm"
                ))
                
                # If source_id is None (MEA tool etc.): add z move command
                if source_id is None:
                    # MEA tool etc.: move to z position then aspirate directly
                    print(f"[DEBUG] take[{i}]: source_id=None (MEA tool etc.), adding z move command")
                    commands.append(self._create_z_move_command(
                        pos, z_position, "take", f"Move to target Z: {z_position}"
                    ))
                else:
                    # SOURCE tool case: z move is commented out (processed via surface detection)
                    print(f"[DEBUG] take[{i}]: source_id={source_id} (SOURCE tool), z move processed via surface detection")
                    # commands.append(self._create_z_move_command(
                    #     pos, z_position, 'take', f'Move to source z position: {z_position}'
                    # ))
            
            # Liquid aspiration (including source_id)
            commands.append({
                "type": "take",
                "action": "take",
                "function": "DakenInterface.aspirate_liquid",
                "parameters": {
                    "amount": amount,
                    "source_id": source_id  # source3, source1, etc.
                },
                "description": f"Aspirate {amount} (source: {source_id})"
            })
            
            # # SOURCE tool case: move z-axis up from current position then dispense 30uL
            # if source_id is not None:
            #     # Move z-axis up from current position (using offset from config)
            #     print(f"[DEBUG] SOURCE tool ({source_id}): z-axis move from current position")
            #     commands.append(self._create_move_offset_command(
            #         axis="z",
            #         offset=self.take_z_offset_after_aspiration,
            #         action_type="take",
            #         description=f"z-axis +{self.take_z_offset_after_aspiration}mm move"
            #     ))

            #     # Wait before dispense
            #     commands.append({
            #         "type": "take",
            #         "action": "wait",
            #         "function": "time.sleep",
            #         "parameters": {
            #             "seconds": self.spit_minor_amount_pre_wait
            #         },
            #         "description": f"before dispense {self.spit_minor_amount_pre_wait}s wait"
            #     })

            #     # Dispense small amount after aspiration for accuracy
            #     commands.append({
            #         "type": "take",
            #         "action": "spit_minor_amount",
            #         "function": "DakenInterface.spit_liquid",
            #         "parameters": {
            #             "amount": self.post_aspiration_minor_spit_amount,
            #             "source_id": source_id
            #         },
            #         "description": f"{self.post_aspiration_minor_spit_amount}uL dispense (Source: {source_id})"
            #     })
            # else:
            #     # MEA tool etc.: skip dispense
            #     print(f"[DEBUG] take[{i}]: source_id=None (MEA tool etc.), skipping 30uL dispense")
            
            if is_current_mea and is_next_mea:
                # If both current and next positions are MEA tool: move to MEA tool height + 5mm
                # Get MEA tool center Z coordinate
                tool_center_z = self._get_tool_center_z(tool_name)
                if tool_center_z is not None:
                    mea_height_offset = 5.0  # 5mm
                    previous_mea_z = tool_center_z + mea_height_offset
                    print(f"[DEBUG] take[{i}]: MEA tool height + 5mm calculated: tool_center_z={tool_center_z:.2f}mm, previous_mea_z={previous_mea_z:.2f}mm")
                else:
                    previous_mea_z = None
                
                commands.append(self._create_move_to_mea_height_command(
                    pos, tool_name, "take", "Move to MEA tool height + 5mm", "pipette"
                ))
            else:
                # Other cases: Return to top position
                previous_mea_z = None  # Initialize if not MEA tool
                commands.append(self._create_move_to_top_command(
                    pos, "take", "Return to top position", "pipette"
                ))
            

        
        return commands
    
    def _create_mix_commands(self, order: Dict[str, Any], start_command_number: int) -> List[Dict[str, Any]]:
        """Create commands for Mix action (similar to Take but with direct mixing included)."""
        commands = []
        amount = order.get('amount', 0)
        
        # Update liquid tracking state
        self.liquid_tracking['current_take_amount'] = amount
        self.liquid_tracking['remaining_amount'] = amount
        self.liquid_tracking['current_apply_amount'] = 0  # apply Initialize
        self.liquid_tracking['process_started'] = True
        
        print(f"[DEBUG] Mix volume tracking: {amount}μL mix")
        
        if not self.equipped_tip:
            commands.append({
                "type": "mix",
                "action": "error_no_tip",
                "function": "none",
                "parameters": {},
                "description": "No tip equipped"
            })
            return commands
        
        # Set end-effector to pipette
        commands.append({
            "type": "mix",
            "action": "set_end_effector",
            "function": "ServorInterface.move_to_angle",
            "parameters": {"angle": 60},
            "description": "Set end-effector to pipette"
        })
        
        # Process target positions
        target_positions = self._extract_target_positions(order.get('target', {}), "mix")
        
        if len(target_positions) == 0:
            print(f"[DEBUG] Mix: no target positions found.")
            return commands
        
        # Check if consecutive targets
        is_consecutive = self._is_consecutive_targets(target_positions)
        print(f"[DEBUG] mix target count: {len(target_positions)}, is_consecutive: {is_consecutive}")
        
        # Track previous grid Z position in MEA tool (used for next grid move)
        previous_mea_z = None
        
        for i, (pos, tool_name, grid_index) in enumerate(target_positions):
            # Calculate z coordinate
            z_position = self._calculate_z_position(tool_name, "mix")
            
            # Extract source_id from Target (before z move command creation)
            source_id = self._extract_source_id_from_target(order.get('target', {}), pos)
            
            # Pre-check next position: verify both current and next positions are MEA tool
            is_current_mea = self._is_mea_tool(tool_name)
            is_next_mea = False
            if i + 1 < len(target_positions):
                next_tool_name = target_positions[i + 1][1]
                is_next_mea = self._is_mea_tool(next_tool_name)
            
            # Check if inter-grid move (grid_index >= 0 and MEA tool case)
            is_grid_movement = (grid_index >= 0 and is_current_mea)

            # 1. From top state: daken aspiration(aspirate) 10 uL
            # (x,y already moved, aspiration from top z=0)
            # 10uL aspiration from top
            commands.append({
                "type": "mix",
                "action": "aspirate_initial",
                "function": "DakenInterface.aspirate_liquid",
                "parameters": {
                    "amount": 10,
                    "source_id": source_id
                },
                "description": f"Aspirate 10μL from top (source: {source_id})"
            })
            
            # Condition evaluation:
            # 1. First move (i == 0): always use move_xy_position
            # 2. Non-consecutive target case (not is_consecutive): use move_xy_position
            # 3. Inter-grid move case (is_grid_movement): use move_xy_position (angle-based precise move)
            # 4. Consecutive targets that are NOT inter-grid: use move_offset (fast move in end effector coords)
            if i == 0 or not is_consecutive or is_grid_movement:
                # If first move, non-consecutive, or inter-grid: x,y move → z move
                print(f"[DEBUG] mix[{i}]: using move_xy_position (is_consecutive={is_consecutive}, is_grid_movement={is_grid_movement}), tool_name={tool_name}")
                
                # If previous grid was MEA tool and current is also MEA: maintain previous Z position
                xy_move_z = previous_mea_z if (previous_mea_z is not None and is_current_mea) else None
                commands.append(self._create_xy_move_command(
                    pos, "mix", f"mix move to x,y position: {pos}", "pipette", tool_name, z_position=xy_move_z
                ))
                
                # If source_id is None (MEA tool etc.): add z move command
                if source_id is None:
                    # MEA tool etc.: move to z position then aspirate directly
                    print(f"[DEBUG] mix[{i}]: source_id=None (MEA tool etc.), adding z move command")
                    commands.append(self._create_z_move_command(
                        pos, z_position, "mix", f"Move to target Z: {z_position}"
                    ))
                else:
                    # SOURCE tool case: z move is commented out (processed via surface detection)
                    print(f"[DEBUG] mix[{i}]: source_id={source_id} (SOURCE tool), z move processed via surface detection")
            else:
                # After second of non-consecutive inter-grid target: x,y offset move → z move
                prev_pos = target_positions[i-1][0]
                axis, offset = self._calculate_offset_between_positions(prev_pos, pos)
                print(f"[DEBUG] mix[{i}]: using move_offset (not inter-grid move) - axis={axis}, offset={offset:.2f}, is_grid_movement={is_grid_movement}")
                
                commands.append(self._create_move_offset_command(
                    axis=axis,
                    offset=offset,
                    action_type="mix",
                    description=f"{axis}-axis move {offset:.1f}mm"
                ))
                
                # If source_id is None (MEA tool etc.): add z move command
                if source_id is None:
                    # MEA tool etc.: move to z position then aspirate directly
                    print(f"[DEBUG] mix[{i}]: source_id=None (MEA tool etc.), adding z move command")
                    commands.append(self._create_z_move_command(
                        pos, z_position, "mix", f"Move to target Z: {z_position}"
                    ))
                else:
                    # SOURCE tool case: z move is commented out (processed via surface detection)
                    print(f"[DEBUG] mix[{i}]: source_id={source_id} (SOURCE tool), z move processed via surface detection")
            
            
            
            # Move to z position (for mix)
            if source_id is None:
                # MEA tool etc.: move to z position
                commands.append(self._create_z_move_command(
                    pos, z_position, "mix", f"z position for mix: {z_position}"
                ))
            # SOURCE tool case: z move processed via surface detection, so no command added
            
            # 2. Instead of daken aspiration: repeat aspiration(aspirate) + dispense(spit) 3 times for the volume
            for mix_cycle in range(3):
                # aspiration
                commands.append({
                    "type": "mix",
                    "action": "mix_aspirate",
                    "function": "DakenInterface.aspirate_liquid",
                    "parameters": {
                        "amount": amount,
                        "source_id": source_id
                    },
                    "description": f"Mix cycle {mix_cycle + 1}/3: {amount}μL aspirate (source: {source_id})"
                })
                
                # dispense
                commands.append({
                    "type": "mix",
                    "action": "mix_spit",
                    "function": "DakenInterface.spit_liquid",
                    "parameters": {
                        "amount": amount,
                        "source_id": source_id
                    },
                    "description": f"Mix cycle {mix_cycle + 1}/3: {amount}μL spit (source: {source_id})"
                })
            
            # 3. Rise 5mm along z-axis, then spit 10 uL
            commands.append(self._create_move_offset_command(
                axis="z",
                offset=3.0,
                action_type="mix",
                description="3mm z axis ascent"
            ))
            
            commands.append({
                "type": "mix",
                "action": "spit_final",
                "function": "DakenInterface.spit_liquid",
                "parameters": {
                    "amount": 10,
                    "source_id": source_id
                },
                "description": f"10μL spit (source: {source_id})"
            })
            
            # 4. Then move to top
            if is_current_mea and is_next_mea:
                # If both current and next positions are MEA tool: move to MEA tool height + 5mm
                tool_center_z = self._get_tool_center_z(tool_name)
                if tool_center_z is not None:
                    mea_height_offset = 5.0  # 5mm
                    previous_mea_z = tool_center_z + mea_height_offset
                    print(f"[DEBUG] mix[{i}]: MEA tool height + 5mm calculated: tool_center_z={tool_center_z:.2f}mm, previous_mea_z={previous_mea_z:.2f}mm")
                else:
                    previous_mea_z = None
                
                commands.append(self._create_move_to_mea_height_command(
                    pos, tool_name, "mix", "Move to MEA tool height + 5mm", "pipette"
                ))
            else:
                # Other cases: Return to top position
                previous_mea_z = None  # Initialize if not MEA tool
                commands.append(self._create_move_to_top_command(
                    pos, "mix", "Return to top position", "pipette"
                ))
        
        return commands
    
    def _create_apply_commands(self, order: Dict[str, Any], start_command_number: int) -> List[Dict[str, Any]]:
        """Create commands for Apply action."""
        commands = []
        amount = order.get('amount', 0)
        
        # Process target positions
        target_positions = self._extract_target_positions(order.get('target', {}), "apply")
        
        # Calculate total apply volume (applied per grid)
        total_apply_amount = amount * len(target_positions)
        
        # Update liquid tracking state
        self.liquid_tracking['current_apply_amount'] += total_apply_amount
        self.liquid_tracking['remaining_amount'] = (
            self.liquid_tracking['current_take_amount'] - 
            self.liquid_tracking['current_apply_amount']
        )
        
        print(f"[DEBUG] Apply volume tracking: {total_apply_amount}μL applied (remaining volume: {self.liquid_tracking['remaining_amount']}μL)")
        
        if not self.equipped_tip:
            commands.append({
                "type": "apply",
                "action": "error_no_tip",
                "function": "none",
                "parameters": {},
                "description": "No tip equipped"
            })
            return commands
        
        # Set end-effector to pipette
        commands.append({
            "type": "apply",
            "action": "set_end_effector",
            "function": "ServorInterface.move_to_angle",
            "parameters": {"angle": 60},
            "description": "Set end-effector to pipette"
        })
        
        # Check if consecutive targets
        is_consecutive = self._is_consecutive_targets(target_positions)
        print(f"[DEBUG] apply target count: {len(target_positions)}, is_consecutive: {is_consecutive}")
        if len(target_positions) > 1:
            print(f"[DEBUG] First Target: {target_positions[0][0]}")
            print(f"[DEBUG] Second Target: {target_positions[1][0]}")
            axis, offset = self._calculate_offset_between_positions(target_positions[0][0], target_positions[1][0])
            print(f"[DEBUG] First->Second offset: axis={axis}, offset={offset:.2f}")
        
        # Track previous grid Z position in MEA tool (used for next grid move)
        previous_mea_z = None
        # Track current grid position (maintain grid info even when using move_offset)
        current_grid_row = None
        current_grid_col = None
        current_tool_name = None
        
        for i, (pos, tool_name, grid_index) in enumerate(target_positions):
            # Calculate z coordinate
            z_position = self._calculate_z_position(tool_name, "apply")
            
            # Pre-check next position: verify both current and next positions are MEA tool
            is_current_mea = self._is_mea_tool(tool_name)
            is_next_mea = False
            if i + 1 < len(target_positions):
                next_tool_name = target_positions[i + 1][1]
                is_next_mea = self._is_mea_tool(next_tool_name)
            
            # Calculate current grid position (extract row, col from grid_index)
            if grid_index >= 0 and is_current_mea:
                # MEA tool case: grid_indexfrom row, col calculate
                if 'mea' in tool_name.lower():
                    grid_cols = 2  # MEA tool has 2 columns
                    current_grid_row = grid_index // grid_cols
                    current_grid_col = grid_index % grid_cols
                    current_tool_name = tool_name
                    print(f"[DEBUG] apply[{i}]: grid position tracking - grid_index={grid_index} -> row={current_grid_row}, col={current_grid_col}")
                else:
                    # Other tool case
                    current_grid_row = None
                    current_grid_col = None
                    current_tool_name = None
            
            # Check if inter-grid move (grid_index >= 0 and MEA tool case)
            is_grid_movement = (grid_index >= 0 and is_current_mea)
            
            # Condition evaluation:
            # 1. First move (i == 0): always use move_xy_position
            # 2. Non-consecutive target case (not is_consecutive): use move_xy_position
            # 3. Inter-grid move case (is_grid_movement): use move_xy_position (angle-based precise move)
            # 4. Consecutive targets that are NOT inter-grid: use move_offset (fast move in end effector coords)
            if i == 0 or not is_consecutive or is_grid_movement:
                # If first move, non-consecutive, or inter-grid: x,y move → z move
                print(f"[DEBUG] apply[{i}]: using move_xy_position (is_consecutive={is_consecutive}, is_grid_movement={is_grid_movement}), tool_name={tool_name}")
                
                # If previous grid was MEA tool and current is also MEA: maintain previous Z position
                xy_move_z = previous_mea_z if (previous_mea_z is not None and is_current_mea) else None
                commands.append(self._create_xy_move_command(
                    pos, "apply", f"Move x,y to target: {pos}", "pipette", tool_name, z_position=xy_move_z
                ))
                commands.append(self._create_z_move_command(
                    pos, z_position, "apply", f"Move to target Z: {z_position}", 
                    tool_name=tool_name, grid_row=current_grid_row, grid_col=current_grid_col
                ))
            else:
                # After second of non-consecutive inter-grid target: x,y offset move → z move
                # Note: inter-grid moves use move_xy_position per above condition, so only non-grid cases processed here
                prev_pos = target_positions[i-1][0]
                axis, offset = self._calculate_offset_between_positions(prev_pos, pos)
                print(f"[DEBUG] apply[{i}]: using move_offset (not inter-grid move) - axis={axis}, offset={offset:.2f}, is_grid_movement={is_grid_movement}")
                
                # Add grid info to move_offset command (for use in next command)
                move_offset_cmd = self._create_move_offset_command(
                    axis=axis,
                    offset=offset,
                    action_type="apply",
                    description=f"{axis}-axis move {offset:.1f}mm",
                    tool_name=current_tool_name,
                    grid_row=current_grid_row,
                    grid_col=current_grid_col
                )
                commands.append(move_offset_cmd)
                
                # Update grid position after move_offset
                if current_grid_row is not None and current_grid_col is not None and current_tool_name:
                    if axis == 'x' and offset > 0:
                        # Positive x-axis move: increase row (mea2 has 2 cols, so)
                        grid_cols = 2
                        grid_index_after = current_grid_row * grid_cols + current_grid_col
                        # Divide offset by grid spacing (9mm) to calculate row increment
                        row_increment = int(round(offset / 9.0))
                        current_grid_row = current_grid_row + row_increment
                        print(f"[DEBUG] apply[{i}]: grid position updated after move_offset - row={current_grid_row}, col={current_grid_col} (offset={offset:.2f}mm, row_increment={row_increment})")
                    elif axis == 'x' and offset < 0:
                        # Negative x-axis move: decrease row
                        grid_cols = 2
                        row_decrement = int(round(abs(offset) / 9.0))
                        current_grid_row = current_grid_row - row_decrement
                        print(f"[DEBUG] apply[{i}]: grid position updated after move_offset - row={current_grid_row}, col={current_grid_col} (offset={offset:.2f}mm, row_decrement={row_decrement})")
                    elif axis == 'y' and offset > 0:
                        # Positive y-axis move: increase col
                        current_grid_col = current_grid_col + 1
                        print(f"[DEBUG] apply[{i}]: grid position updated after move_offset - row={current_grid_row}, col={current_grid_col} (offset={offset:.2f}mm)")
                    elif axis == 'y' and offset < 0:
                        # Negative y-axis move: decrease col
                        current_grid_col = current_grid_col - 1
                        print(f"[DEBUG] apply[{i}]: grid position updated after move_offset - row={current_grid_row}, col={current_grid_col} (offset={offset:.2f}mm)")
                
                commands.append(self._create_z_move_command(
                    pos, z_position, "apply", f"Move to target Z: {z_position}",
                    tool_name=current_tool_name, grid_row=current_grid_row, grid_col=current_grid_col
                ))
           
            # Liquid apply
            commands.append({
                "type": "apply",
                "action": "perform_apply",
                "function": "DakenInterface.spit_liquid",
                "parameters": {"amount": amount, "tool_name": tool_name},
                "description": f"Apply {amount}"
            })
            
            if is_current_mea and is_next_mea:
                # If both current and next positions are MEA tool: move to MEA tool height + 5mm
                # Get MEA tool center Z coordinate
                tool_center_z = self._get_tool_center_z(tool_name)
                if tool_center_z is not None:
                    mea_height_offset = 5.0  # 5mm
                    previous_mea_z = tool_center_z + mea_height_offset
                    print(f"[DEBUG] apply[{i}]: MEA tool height + 5mm calculated: tool_center_z={tool_center_z:.2f}mm, previous_mea_z={previous_mea_z:.2f}mm")
                else:
                    previous_mea_z = None
                
                commands.append(self._create_move_to_mea_height_command(
                    pos, tool_name, "apply", "Move to MEA tool height + 5mm", "pipette"
                ))
            else:
                # Other cases: Return to top position
                previous_mea_z = None  # Initialize if not MEA tool
                commands.append(self._create_move_to_top_command(
                    pos, "apply", "Return to top position", "pipette"
                ))
        
        return commands
    
    def _create_dispose_commands(self, order: Dict[str, Any], start_command_number: int) -> List[Dict[str, Any]]:
        """Create commands for Dispose action."""
        commands = []
               
        if not self.equipped_tip:
            commands.append({
                "type": "dispose",
                "action": "error_no_tip",
                "function": "none",
                "parameters": {},
                "description": "No tip equipped"
            })
            return commands
        
        # Set end-effector to pipette
        commands.append({
            "type": "dispose",
            "action": "set_end_effector",
            "function": "ServorInterface.move_to_angle",
            "parameters": {"angle": 60},
            "description": "Set end-effector to pipette"
        })
               
        # Move to Liquid Trash and dispense (3-step disconnect)
        liq_trash_pos = self._get_liquid_trash_position()
        if liq_trash_pos:
            # Calculate trash z position + height
            trash_z_position = self._calculate_trash_z_position("liq-trash")
            
            # Step 1: Move to top from current position
            commands.append({
                "type": "dispose",
                "action": "move_to_top",
                "function": "ScaraInterface.move_to_top",
                "parameters": {
                    "end_effector": "pipette",
                    "xyz": [0, 0, 0],  # Top position from current location
                    "tip": True
                },
                "description": "Move to top from current position"
            })
            
            # Step 2: Move X,Y only (from top)
            target_xyz = liq_trash_pos + [0]
            speed = self._calculate_speed_for_position(target_xyz)
            commands.append({
                "type": "dispose",
                "action": "move_xy_position",
                "function": "ScaraInterface.move_end_effector",
                "parameters": {
                    "end_effector": "pipette",
                    "xyz": target_xyz,
                    "tip": True,
                    "speed": speed
                },
                "description": "Move X,Y to Liquid Trash"
            })
            
            # Step 3: Descend along Z-axis
            target_xyz_z = liq_trash_pos + [trash_z_position]
            speed_z = self._calculate_speed_for_position(target_xyz_z)
            commands.append({
                "type": "dispose",
                "action": "move_z_position",
                "function": "ScaraInterface.move_end_effector",
                "parameters": {
                    "end_effector": "pipette",
                    "xyz": target_xyz_z,
                    "tip": True,
                    "speed": speed_z
                },
                "description": "Z move to Liquid Trash"
            })
            
            # Waste dispense
            commands.append({
                "type": "dispose",
                "action": "dispose_waste",
                "function": "DakenInterface.spit_liquid",
                "parameters": {"amount": 0},
                "description": "Dispose waste"
            })
            
            # Return to top position
            commands.append({
                "type": "dispose",
                "action": "move_to_top",
                "function": "ScaraInterface.move_to_top",
                "parameters": {
                    "end_effector": "pipette",
                    "xyz": liq_trash_pos + [0],  # z=0 (top position)
                    "tip": True
                },
                "description": "Return to top position"
            })
        
        return commands
    
    def _create_wait_commands(self, order: Dict[str, Any], start_command_number: int) -> List[Dict[str, Any]]:
        """Create commands for Wait action."""
        # Process both: time field as dict AND direct time_value/time_unit
        if 'time' in order and isinstance(order.get('time'), dict):
            time_value = order.get('time', {}).get('value', 0)
            time_unit = order.get('time', {}).get('unit', 'sec')
        else:
            # Direct time_value/time_unit case (compatibility)
            time_value = order.get('time_value', 0)
            time_unit = order.get('time_unit', 'sec')
        
        # Convert time unit to seconds
        if time_unit == 'sec':
            seconds = time_value
        elif time_unit == 'min':
            seconds = time_value * 60
        elif time_unit == 'hour':
            seconds = time_value * 3600
        else:
            # Unknown unit is assumed to be seconds
            seconds = time_value
        
        return [{
            "type": "wait",
            "action": "wait",
            "function": "time.sleep",
            "parameters": {
                "seconds": seconds
            },
            "description": f"Wait {time_value} {time_unit}"
        }]
    
    def _create_measure_commands(self, order: Dict[str, Any], start_command_number: int) -> List[Dict[str, Any]]:
        """Create commands for Measure action (JIG close → measurement → JIG open)."""
        commands = []
        
        # Debug: print order info
        print(f"[DEBUG] _create_measure_commands - order: {order}")
        
        # 1. JIG close (before measurement)
        commands.append({
            "type": "measure",
            "action": "jig_close",
            "function": "JigController.close",
            "parameters": {
                "wait_for_completion": True
            },
            "description": "Close JIG for measurement"
        })
        
        # 2. Start measurement
        commands.append({
            "type": "measure",
            "action": "start_measurement",
            "function": "MeasurementInterface.start_measurement",
            "parameters": {},
            "description": "Start measurement"
        })
        
        # 3. Wait for measurement completion (time info handling)
        # Use time object or direct time_value/time_unit according to protocol structure
        if 'time' in order and isinstance(order['time'], dict):
            # time object exists case (legacy method)
            time_info = order.get('time', {})
            time_value = time_info.get('value', 0)
            time_unit = time_info.get('unit', 'sec')
        else:
            # Direct time_value/time_unit case (new method)
            time_value = order.get('time_value', 0)
            time_unit = order.get('time_unit', 'sec')
        
        print(f"[DEBUG] Measurement time info: value={time_value}, unit={time_unit}")
        
        # Add wait command if time info exists
        if time_value is not None and time_value > 0:
            seconds = self._convert_time_to_seconds(time_value, time_unit)
            print(f"[DEBUG] Measurement wait time: {seconds} seconds")
            
            commands.append({
                "type": "measure",
                "action": "wait_measurement",
                "function": "time.sleep",
                "parameters": {
                    "seconds": seconds
                },
                "description": f"Wait for measurement ({time_value}{time_unit})"
            })
        elif time_value == 0:
            # Show explicitly even for 0 seconds case
            print(f"[DEBUG] Measurement wait time: 0 seconds")
            commands.append({
                "type": "measure",
                "action": "wait_measurement",
                "function": "time.sleep",
                "parameters": {
                    "seconds": 0
                },
                "description": "Wait for measurement (0s)"
            })
        else:
            print(f"[DEBUG] Measurement wait time not found")
        
        # 4. JIG open (after measurement)
        commands.append({
            "type": "measure",
            "action": "jig_open",
            "function": "JigController.open",
            "parameters": {
                "wait_for_completion": True
            },
            "description": "Open JIG after measurement"
        })
        
        return commands
    
    def _create_open_commands(self, order: Dict[str, Any], start_command_number: int) -> List[Dict[str, Any]]:
        """Create commands for Open action."""
        commands = []
        
        # Set end-effector to gripper
        commands.append({
            "type": "open",
            "action": "set_end_effector",
            "function": "ServorInterface.move_to_angle",
            "parameters": {"angle": 240},
            "description": "Set end-effector to gripper"
        })
        
        # Move to target position
        target_positions = self._extract_target_positions(order.get('target', {}), "open")
        for pos, tool_name, grid_index in target_positions:
            try:
                # Calculate z coordinate (with error handling)
                z_position = self._calculate_z_position(tool_name, "open")
            except ValueError as e:
                # Add error command on error
                commands.append({
                    "type": "open",
                    "action": "error",
                    "function": "none",
                    "parameters": {},
                    "description": f"Z coordinate calculation error: {str(e)}"
                })
                continue
            
            # Move to target position
            target_xyz = pos + [z_position]
            speed = self._calculate_speed_for_position(target_xyz)
            commands.append({
                "type": "open",
                "action": "move_to_position",
                "function": "ScaraInterface.move_end_effector",
                "parameters": {
                    "end_effector": "gripper",
                    "xyz": target_xyz,
                    "tip": False,
                    "speed": speed
                },
                "description": f"Move to target: {target_xyz}"
            })
            
            # Close gripper
            commands.append({
                "type": "open",
                "action": "gripper_close",
                "function": "ScaraInterface.gripper.set_rotation_angle",
                "parameters": {"angle": -360*5},  # closing
                "description": "Gripper close"
            })
            
            # Counter-clockwise rotation and Z-axis move
            commands.append({
                "type": "open",
                "action": "rotate_ccw_and_move",
                "function": "ScaraInterface.gripper.set_rotation_angle",
                "parameters": {"angle": +360*5},  # opening (ccw)
                "description": "Counterclockwise rotation and Z move"
            })
            
            # Move to top position
            commands.append({
                "type": "open",
                "action": "move_to_top",
                "function": "ScaraInterface.move_to_top",
                "parameters": {
                    "end_effector": "gripper",
                    "xyz": pos + [0],  # z=0 (top position)
                    "tip": False
                },
                "description": "Move to top position"
            })
        
        return commands
    
    def _create_close_commands(self, order: Dict[str, Any], start_command_number: int) -> List[Dict[str, Any]]:
        """Create commands for Close action."""
        commands = []
        
        # Set end-effector to gripper
        commands.append({
            "type": "close",
            "action": "set_end_effector",
            "function": "ServorInterface.move_to_angle",
            "parameters": {"angle": 240},
            "description": "Set end-effector to gripper"
        })
        
        # Move to target position
        target_positions = self._extract_target_positions(order.get('target', {}), "close")
        for pos, tool_name, grid_index in target_positions:
            try:
                # Calculate z coordinate (with error handling)
                z_position = self._calculate_z_position(tool_name, "close")
            except ValueError as e:
                # Add error command on error
                commands.append({
                    "type": "close",
                    "action": "error",
                    "function": "none",
                    "parameters": {},
                    "description": f"Z coordinate calculation error: {str(e)}"
                })
                continue
            
            # Move to target position
            target_xyz = pos + [z_position]
            speed = self._calculate_speed_for_position(target_xyz)
            commands.append({
                "type": "close",
                "action": "move_to_position",
                "function": "ScaraInterface.move_end_effector",
                "parameters": {
                    "end_effector": "gripper",
                    "xyz": target_xyz,
                    "tip": False,
                    "speed": speed
                },
                "description": f"Move to target: {target_xyz}"
            })
            
            # Close gripper
            commands.append({
                "type": "close",
                "action": "gripper_close",
                "function": "ScaraInterface.gripper.set_rotation_angle",
                "parameters": {"angle": -360*5},  # closing
                "description": "Gripper close"
            })
            
            # Clockwise rotation and Z-axis move
            commands.append({
                "type": "close",
                "action": "rotate_cw_and_move",
                "function": "ScaraInterface.gripper.set_rotation_angle",
                "parameters": {"angle": -360*5},  # closing (cw)
                "description": "Clockwise rotation and Z move"
            })
            
            # Open gripper
            commands.append({
                "type": "close",
                "action": "gripper_open",
                "function": "ScaraInterface.gripper.set_rotation_angle",
                "parameters": {"angle": +360*5},  # opening
                "description": "Gripper open"
            })
            
            # Move to top position
            commands.append({
                "type": "close",
                "action": "move_to_top",
                "function": "ScaraInterface.move_to_top",
                "parameters": {
                    "end_effector": "gripper",
                    "xyz": pos + [0],  # z=0 (top position)
                    "tip": False
                },
                "description": "Move to top position"
            })
        
        return commands
    
    def _calculate_next_tip_position(self) -> Optional[List[float]]:
        """next Tip position calculate"""
        if not self.table_coords:
            return None
        
        # Find available tip from tip1, tip2, tip3
        for tip_name in ['tip1', 'tip2', 'tip3']:
            if tip_name in self.table_coords.get('tools', {}):
                tip_data = self.table_coords['tools'][tip_name]
                grid_coords = tip_data.get('grid_pattern', {}).get('grid_center_coordinates', [])
                
                if self.current_tip_position < len(grid_coords):
                    coord = grid_coords[self.current_tip_position]
                    return [coord['x'], coord['y']]
        
        return None
    
    def _get_tip_trash_position(self) -> Optional[List[float]]:
        """Return Tip Trash position."""
        if not self.table_coords:
            return None
        
        tip_trash = self.table_coords.get('tools', {}).get('tip-trash', {})
        center_coords = tip_trash.get('center_coordinates', {})
        
        if center_coords:
            return [center_coords['x'], center_coords['y']]
        
        return None
    
    def _get_liquid_trash_position(self) -> Optional[List[float]]:
        """Return Liquid Trash position."""
        if not self.table_coords:
            return None
        
        liq_trash = self.table_coords.get('tools', {}).get('liq-trash', {})
        center_coords = liq_trash.get('center_coordinates', {})
        
        if center_coords:
            return [center_coords['x'], center_coords['y']]
        
        return None
    
    def _get_tool_center_coordinates_direct(self, item_name: str) -> Optional[List[float]]:
        """
        Return tool's center_coordinates directly (grid position independent)
        caution: correction value is applied only in action_commander.py (not at command creation stage)
        
        Args:
            item_name: Item name (e.g. 'MEA3', 'TIP1')
            
        Returns:
            tool's center_coordinates [x, y] (correction value not applied) or None
        """
        if not self.table_coords:
            return None
        
        tool_key = item_name.lower()  # MEA3 -> mea3
        tool_data = self.table_coords.get('tools', {}).get(tool_key, {})
        
        if not tool_data:
            return None
        
        # center_coordinates used directly
        # caution: correction value is applied only in action_commander.py (not at command creation stage)
        center_coords = tool_data.get('center_coordinates', {})
        if center_coords and 'x' in center_coords and 'y' in center_coords:
            x = center_coords['x']
            y = center_coords['y']
            
            return [x, y]
        
        return None

    def _extract_target_positions(self, target: Dict[str, Any], action_type: str = None) -> List[Tuple[List[float], str, int]]:
        """Extract position coordinates, tool name, and grid_index from target"""
        positions = []
        print(f"[DEBUG] _extract_target_positions start - target: {target}, action_type: {action_type}")
        
        for group_name, group_data in target.items():
            print(f"[DEBUG] Group processing: {group_name} -> {group_data}")
            if isinstance(group_data, dict):
                for item_name, item_positions in group_data.items():
                    if isinstance(item_positions, list):
                        for pos in item_positions:
                            # Check if pos is list or tuple
                            if (isinstance(pos, (list, tuple)) and len(pos) >= 2):
                                # Source has no grid, so use direct coordinates
                                if group_name.upper() == 'SOURCE':
                                    # For Source, use center_coordinates directly (correct value)
                                    # item_name may be Source Desc, so convert to Source ID
                                    source_id = self._convert_source_desc_to_id(item_name)
                                    tool_key = source_id.lower()  # source2 -> source2
                                    print(f"[DEBUG] Source processing: item_name='{item_name}' -> source_id='{source_id}' -> tool_key='{tool_key}'")
                                    tool_data = self.table_coords.get('tools', {}).get(tool_key, {})
                                    if tool_data:
                                        center_coords = tool_data.get('center_coordinates', {})
                                        if center_coords:
                                            # Source has no grid_index, so use -1
                                            positions.append(([center_coords['x'], center_coords['y']], tool_key, -1))
                                            print(f"[DEBUG] Source position added: ({[center_coords['x'], center_coords['y']]}, {tool_key}, -1)")
                                    else:
                                        print(f"[DEBUG] Source tool_data not found: tool_key='{tool_key}'")
                                elif group_name.upper() == 'MEA':
                                    # For MEA, convert grid coordinates to actual coordinates
                                    print(f"[DEBUG] MEA grid coordinates conversion: pos={pos}, group={group_name}, item={item_name}")
                                    tool_key = item_name.lower()  # MEA1 -> mea1
                                    
                                    # For gripper action, use tool's center_coordinates directly
                                    if action_type in ['pick', 'place', 'open', 'close']:
                                        actual_pos = self._get_tool_center_coordinates_direct(item_name)
                                        print(f"[DEBUG] MEA center coordinates for gripper: {actual_pos}")
                                        if actual_pos:
                                            # For gripper action, grid_index is not used, so use -1
                                            positions.append((actual_pos, tool_key, -1))
                                            print(f"[DEBUG] MEA positions added: ({actual_pos}, {tool_key}, -1)")
                                    else:
                                        # For pipette action, use existing logic (grid center point)
                                        result = self._convert_grid_to_actual_coordinates(pos, group_name, item_name)
                                        if result:
                                            actual_pos, grid_index = result
                                            print(f"[DEBUG] MEA grid coordinates for pipette: {actual_pos}, grid_index: {grid_index}")
                                            positions.append((actual_pos, tool_key, grid_index))
                                            print(f"[DEBUG] MEA positions added: ({actual_pos}, {tool_key}, {grid_index})")
                                else:
                                    # TIP etc. convert grid coordinates to actual coordinates
                                    print(f"[DEBUG] TIP grid coordinates conversion: pos={pos}, group={group_name}, item={item_name}")
                                    
                                    # Gripper action: use tool center_coordinates directly
                                    if action_type in ['pick', 'place', 'open', 'close']:
                                        actual_pos = self._get_tool_center_coordinates_direct(item_name)
                                        print(f"[DEBUG] TIP center coordinates for gripper: {actual_pos}")
                                        if actual_pos:
                                            # Gripper action has no grid_index, so use -1
                                            tool_key = item_name.lower()  # TIP1 -> tip1
                                            positions.append((actual_pos, tool_key, -1))
                                            print(f"[DEBUG] positions added: ({actual_pos}, {tool_key}, -1)")
                                    else:
                                        # Pipette action: use existing method directly
                                        result = self._convert_grid_to_actual_coordinates(pos, group_name, item_name)
                                        if result:
                                            actual_pos, grid_index = result
                                            tool_key = item_name.lower()  # TIP1 -> tip1
                                            print(f"[DEBUG] TIP grid coordinates for pipette: {actual_pos}, grid_index: {grid_index}")
                                            positions.append((actual_pos, tool_key, grid_index))
                                            print(f"[DEBUG] positions added: ({actual_pos}, {tool_key}, {grid_index})")
        
        # Pipette action for MEA tool and JIG group: sort by grid_index (improve SCARA move efficiency)
        # Sort only within same tool_name (multiple tools may be mixed)
        if action_type not in ['pick', 'place', 'open', 'close']:  # Pipette action case
            # Group by tool_name and sort
            tool_groups = {}
            for pos, tool_name, grid_index in positions:
                if grid_index >= 0:  # Only for cases where grid_index exists (MEA/JIG group)
                    if tool_name not in tool_groups:
                        tool_groups[tool_name] = []
                    tool_groups[tool_name].append((pos, tool_name, grid_index))
                else:
                    # Keep as-is for cases where grid_index is missing (SOURCE etc.)
                    if tool_name not in tool_groups:
                        tool_groups[tool_name] = []
                    tool_groups[tool_name].append((pos, tool_name, grid_index))
            
            # Sort by grid_index per tool, then merge back
            sorted_positions = []
            for tool_name in sorted(tool_groups.keys()):  # Maintain tool_name order
                tool_positions = tool_groups[tool_name]
                # Sort only if grid_index exists, keep original order otherwise
                has_grid = any(idx >= 0 for _, _, idx in tool_positions)
                if has_grid:
                    # grid_index based on sort
                    tool_positions.sort(key=lambda x: x[2] if x[2] >= 0 else float('inf'))
                    print(f"[DEBUG] {tool_name} grid position sort complete (by grid_index)")
                sorted_positions.extend(tool_positions)
            
            if sorted_positions:
                positions = sorted_positions
                print(f"[DEBUG] grid position sort applied: Total {len(positions)} positions")
        
        print(f"[DEBUG] _extract_target_positions Result: {positions}")
        return positions
    
    def _is_consecutive_targets(self, positions: List[Tuple[List[float], str, int]]) -> bool:
        """Check if multiple consecutive target coordinates (2 or more coordinates, move along one axis only)."""
        if len(positions) < 2:
            print(f"[DEBUG] _is_consecutive_targets: positions less than 2 ({len(positions)}) -> False")
            return False
        
        print(f"[DEBUG] _is_consecutive_targets: Total {len(positions)} positions")
        
        # Check move from previous to next position (check consecutive move pattern)
        axis_movements = set()
        threshold = self.consecutive_movement_threshold  # Ignore errors within 0.5mm (consider floating point errors)
        
        for i in range(1, len(positions)):
            prev_pos = positions[i-1][0]  # extract only pos from (pos, tool_name, grid_index)
            curr_pos = positions[i][0]     # extract only pos from (pos, tool_name, grid_index)
            
            dx = curr_pos[0] - prev_pos[0]
            dy = curr_pos[1] - prev_pos[1]
            
            print(f"[DEBUG] _is_consecutive_targets: pos[{i-1}]={prev_pos} -> pos[{i}]={curr_pos}, dx={dx:.6f}mm, dy={dy:.6f}mm")
            
            # Check if moving along one axis only (other axis movement is at or below threshold)
            if abs(dx) > threshold and abs(dy) <= threshold:
                # x-axis only move
                axis_movements.add('x')
                print(f"[DEBUG] _is_consecutive_targets: pos[{i-1}]->[{i}]: x-axis move {dx:.2f}mm (dy={dy:.6f}mm ignored, threshold={threshold}mm)")
            elif abs(dy) > threshold and abs(dx) <= threshold:
                # y-axis only move
                axis_movements.add('y')
                print(f"[DEBUG] _is_consecutive_targets: pos[{i-1}]->[{i}]: y-axis move {dy:.2f}mm (dx={dx:.6f}mm ignored, threshold={threshold}mm)")
            else:
                # Case where both axes move or no movement
                if abs(dx) > threshold or abs(dy) > threshold:
                    print(f"[DEBUG] _is_consecutive_targets: pos[{i-1}]->[{i}]: both axes moving (dx={dx:.2f}mm, dy={dy:.2f}mm) -> False return")
                    # Case where both axes move is not a consecutive target
                    return False
                else:
                    # Both axes at or below threshold (nearly no movement)
                    print(f"[DEBUG] _is_consecutive_targets: pos[{i-1}]->[{i}]: move None (dx={dx:.6f}mm, dy={dy:.6f}mm)")
        
        result = len(axis_movements) <= 1
        print(f"[DEBUG] _is_consecutive_targets: axis_movements={axis_movements}, result={result}")
        # Return True if moving along one axis only
        return result
    
    def _convert_grid_to_actual_coordinates(self, grid_pos, group_name: str, item_name: str) -> Optional[Tuple[List[float], int]]:
        """Convert grid coordinates to actual coordinates and also return grid_index."""
        print(f"[DEBUG] ========================================")
        print(f"[DEBUG] grid coordinates convert start")
        print(f"[DEBUG] ========================================")
        print(f"[DEBUG] Input: grid_pos={grid_pos}, group={group_name}, item={item_name}")
        
        if not self.table_coords:
            print("[DEBUG] table_coords is None")
            return None
        
        tool_key = item_name.lower()  # MEA1 -> mea1, TIP1 -> tip1
        print(f"[DEBUG] tool_key: {tool_key}")
        
        tool_data = self.table_coords.get('tools', {}).get(tool_key, {})
        if not tool_data:
            print(f"[DEBUG] tool_data not found: {tool_key}")
            return None
        
        print(f"[DEBUG] tool_data found: {tool_data.get('table_coordinates', {})}")
        
        grid_pattern = tool_data.get('grid_pattern', {})
        print(f"[DEBUG] grid_pattern: {grid_pattern}")
        
        grid_coords = grid_pattern.get('grid_center_coordinates', [])
        print(f"[DEBUG] grid_coords count: {len(grid_coords)}")
        
        # Check if grid_pos is list or tuple, then convert
        if isinstance(grid_pos, (list, tuple)) and len(grid_pos) >= 2:
            row, col = grid_pos[0], grid_pos[1]
            print(f"[DEBUG] grid coordinates: row={row}, col={col}")
            
            # grid size calculation (varies per tool) - use rows, cols from JSON
            if 'tip' in tool_key:
                # Tip box: 8-row 12-col grid (JSON rows=8, cols=12)
                grid_rows = self.default_tip_grid_rows   # rows from JSON
                grid_cols = self.default_tip_grid_cols  # cols from JSON
                print(f"[DEBUG] TIP grid Size: {grid_rows} rows x {grid_cols} cols")
            elif 'mea' in tool_key:
                # MEA tool: 8-row 2-col grid
                grid_rows = self.mea_tip_grid_rows   # rows from JSON
                grid_cols = self.mea_tip_grid_cols  # cols from JSON
                print(f"[DEBUG] MEA grid Size: {grid_rows} rows x {grid_cols} cols")
            else:
                # Default values
                grid_rows = self.default_tip_grid_rows
                grid_cols = self.default_tip_grid_cols
                print(f"[DEBUG] Default grid size: {grid_rows} rows x {grid_cols} cols")
            
            # Calculate grid index (row * grid_cols + col)
            grid_index = row * grid_cols + col
            print(f"[DEBUG] Calculated grid_index: {grid_index} (row={row} * grid_cols={grid_cols} + col={col})")
            
            # Print grid pattern info
            origin_0 = grid_pattern.get('origin_0', {})
            distance = grid_pattern.get('distance', {})
            print(f"[DEBUG] origin_0: {origin_0}")
            print(f"[DEBUG] distance: {distance}")
            
            if grid_index < len(grid_coords):
                coord = grid_coords[grid_index]
                print(f"[DEBUG] selected coordinates: {coord}")
                
                # Calculate manually to validate
                if origin_0 and distance:
                    manual_x = origin_0.get('x', 0) + col * distance.get('x', 0)
                    manual_y = origin_0.get('y', 0) + row * distance.get('y', 0)
                    print(f"[DEBUG] Manually calculated coordinates: x={manual_x}, y={manual_y}")
                    print(f"[DEBUG] Comparison with actual coordinates: x={coord.get('x', 0)}, y={coord.get('y', 0)}")
                
                # Grid Center Coordinates is valid value, use as-is
                result_coords = [coord['x'], coord['y']]
                print(f"[DEBUG] Final return coordinates: {result_coords}, grid_index: {grid_index}")
                print(f"[DEBUG] ========================================")
                return (result_coords, grid_index)
            else:
                print(f"[DEBUG] grid_index {grid_index}out of range (max: {len(grid_coords)-1})")
        else:
            print(f"[DEBUG] invalid grid_pos format: {grid_pos}")
        
        print(f"[DEBUG] ========================================")
        return None
    
    def _calculate_center_position(self, position: List[float]) -> Optional[List[float]]:
        """Calculate center position (considering size info)."""
        # Pick/Place case: already center point, use as-is
        # Center position calculation only needed for other action cases
        return position
    
    def _get_table_center_z(self) -> float:
        """Return z coordinates of table center."""
        if not self.table_coords:
            return 0.0
        return self.table_coords.get('metadata', {}).get('table_center', {}).get('z', 0.0)
    
    def _get_tool_center_z(self, tool_name: str) -> Optional[float]:
        """Return center z coordinates of a specific tool."""
        if not self.table_coords:
            return None
        
        tool_data = self.table_coords.get('tools', {}).get(tool_name.lower(), {})
        center_coords = tool_data.get('center_coordinates', {})
        return center_coords.get('z')
    
    def _get_tool_size_z(self, tool_name: str) -> Optional[float]:
        """Return size z value of a specific tool."""
        if not self.table_coords:
            return None
        
        tool_data = self.table_coords.get('tools', {}).get(tool_name.lower(), {})
        size = tool_data.get('size', {})
        
        # Return z or height value if size is dict
        if isinstance(size, dict):
            return size.get('z') or size.get('height')
        return None
    
    def _get_source_tool_radius(self, source_id: str) -> Optional[float]:
        """Return radius of Source tool."""
        if not self.table_coords:
            return None
        
        tool_name = source_id.lower()  # source1, source2, etc.
        tool_data = self.table_coords.get('tools', {}).get(tool_name, {})
        size = tool_data.get('size', {})
        
        if not isinstance(size, dict):
            return None
        
        # Circular shape case: if dia (diameter) exists, radius = dia / 2
        if 'dia' in size:
            radius = size.get('dia', 0) / 2.0
            print(f"[DEBUG] {tool_name} radius calculate: dia={size.get('dia')} -> radius={radius}")
            return radius
        
        # Rectangle shape case: use half of x or y as radius
        if 'x' in size:
            radius = size.get('x', 0) / 2.0
            print(f"[DEBUG] {tool_name} radius calculate: x={size.get('x')} -> radius={radius}")
            return radius
        
        # Default value: 10mm (typical source tool size)
        print(f"[DEBUG] {tool_name} radius info not found, using default value 10mm")
        return 10.0
    
    def _get_origin_0_z(self, tool_name: str) -> Optional[float]:
        """Return origin_0 z value of specific tool."""
        if not self.table_coords:
            return None
        
        tool_data = self.table_coords.get('tools', {}).get(tool_name.lower(), {})
        grid_pattern = tool_data.get('grid_pattern', {})
        origin_0 = grid_pattern.get('origin_0', {})
        
        return origin_0.get('z')
    
    def _calculate_z_position(self, tool_name: str, action_type: str, offset: float = 0.0) -> float:
        """
        Calculate appropriate z coordinates according to tool shape and action type
        
        Args:
            tool_name: tool name (e.g., 'tip1', 'mea1', 'source1')
            action_type: action type ('equip', 'take', 'apply', 'dispose', 'pick', 'place', 'open', 'close')
            offset: add offset (mm)
            
        Returns:
            calculated z coordinates
            
        Raises:
            ValueError: tool_center_z is missing for gripper action
        """
        table_center_z = self._get_table_center_z()
        tool_center_z = self._get_tool_center_z(tool_name)
        tool_size_z = self._get_tool_size_z(tool_name)
        origin_0_z = self._get_origin_0_z(tool_name)
        
        # Default value is table center z
        base_z = table_center_z
        
        if tool_center_z is not None:
            # tool shape center zuse if exists
            base_z = tool_center_z
        elif tool_size_z is not None:
            # Subtract from table center if tool size z exists (generally negative)
            base_z = table_center_z + tool_size_z
        
        # Apply z offset according to action type
        if action_type in ['equip', 'eject']:
            # Tip equip/remove: use origin_0 z offset
            z_offset = origin_0_z if origin_0_z is not None else 0.0
        elif action_type in ['take', 'mix']:
            # Take action: process differently according to tool_name
            # MEA tool case: tool_center_z based calculate
            if 'mea' in tool_name.lower():
                # MEA tool: tool_center_z based calculate
                # mea_take_z_offset is applied in action_commander's move_z_position (prevent duplication)
                if tool_center_z is not None:
                    if origin_0_z is not None:
                        return tool_center_z + origin_0_z + offset
                    else:
                        return tool_center_z - 10.0 + offset  # Default values
                else:
                    # tool_center_z is missing default value
                    return -395.0 + offset
            else:
                # SOURCE tool: fixed at -395 (base_z ignored, processed via surface detection)
                return -395.0 + offset
        elif action_type == 'apply':
            # Apply action: use tool_center_z if exists, otherwise use -table_center_z
            if tool_center_z is not None:
                # Source tool case: must dispense inside Source, so config for low position
                if 'source' in tool_name.lower():
                    # Source tool: config position as tool_center_z - 1.0 (inside Source)
                    return tool_center_z - 1.0 + offset
                # Case where tool_center_z exists (mea-measure etc.)
                if tool_size_z is not None and origin_0_z is not None:
                    # MEA tool dispense Position: tool_center_z + origin_0_z
                    # mea_apply_z_offset is applied in action_commander's move_z_position (prevent duplication)
                    return tool_center_z + origin_0_z + offset
                elif tool_size_z is not None:
                    return tool_center_z + tool_size_z/2 + 1.0 + offset
                elif origin_0_z is not None:
                    return tool_center_z + origin_0_z + 1.0 + offset
                else:
                    return tool_center_z - 10.0 + 1.0 + offset  # Default values
            else:
                # tool_center_z is missing (existing method directly)
                if tool_size_z is not None and origin_0_z is not None:
                    return -table_center_z + tool_size_z + origin_0_z + 1.0 + offset
                elif tool_size_z is not None:
                    return -table_center_z + tool_size_z + 1.0 + offset
                elif origin_0_z is not None:
                    return -table_center_z + origin_0_z + 1.0 + offset
                else:
                    return -table_center_z - 10.0 + 1.0 + offset  # Default values
        elif action_type == 'dispose':
            # Dispose Action: work inside tool shape (half of size approximately)
            if tool_size_z is not None:
                z_offset = tool_size_z
            else:
                z_offset = -10.0  # Default values
        elif action_type in ['pick', 'place', 'open', 'close']:
            # Gripper operation: consider stack height when at MEA position
            if 'mea' in tool_name.lower() and self.height_calculator:
                location = tool_name.lower()
                
                if action_type == 'pick':
                    # When Gripper picks up a tool
                    # stack_manager state check
                    if self.stack_manager:
                        stack_count = self.stack_manager.get_stack_count(location)
                        print(f"[Z calculate] {tool_name} {action_type}: stack_manager state check - {location} = {stack_count}")
                    pick_height = self.height_calculator.calculate_pick_height(location)
                    if pick_height is not None:
                        final_z = pick_height + offset
                        print(f"[Z calculate] {tool_name} {action_type}: pick_height={pick_height:.2f}mm, offset={offset:.2f}mm, final_z={final_z:.2f}mm")
                        return final_z
                    # no stacked tools, use default value
                    if tool_center_z is None:
                        raise ValueError(f"Gripper action '{action_type}' for tool '{tool_name}': center_coordinates.z not found. Check center_coordinates info in table_coordinates.json.")
                                       f"Please check center_coordinates info for the tool shape in table_coordinates.json.")
                    fallback_z = tool_center_z - 5.0 + offset
                    print(f"[Z calculate] {tool_name} {action_type}: no stacked tools, fallback z={fallback_z:.2f}mm (tool_center_z={tool_center_z:.2f}mm - 5.0 + offset={offset:.2f}mm)")
                    return fallback_z
                
                elif action_type == 'place':
                    # When Gripper places a tool
                    place_height = self.height_calculator.calculate_place_height(location)
                    if place_height is not None:
                        final_z = place_height + offset
                        print(f"[Z calculate] {tool_name} {action_type}: place_height={place_height:.2f}mm, offset={offset:.2f}mm, final_z={final_z:.2f}mm")
                        return final_z
                    # cannot stack more, use default value
                    if tool_center_z is None:
                        raise ValueError(f"Gripper action '{action_type}' for tool '{tool_name}': center_coordinates.z not found. Check center_coordinates info in table_coordinates.json.")
                                       f"Please check center_coordinates info for the tool shape in table_coordinates.json.")
                    fallback_z = tool_center_z - 5.0 + 2.0 + offset
                    print(f"[Z calculate] {tool_name} {action_type}: cannot stack more, fallback z={fallback_z:.2f}mm (tool_center_z={tool_center_z:.2f}mm - 5.0 + 2.0 + offset={offset:.2f}mm)")
                    return fallback_z
            
            # If not MEA or height_calculator is missing, use existing method directly
            # tool_center_z is required; raise error if missing
            if tool_center_z is None:
                raise ValueError(f"Gripper action '{action_type}' for tool '{tool_name}': center_coordinates.z not found. Check center_coordinates info in table_coordinates.json.")
                               f"Please check center_coordinates info for the tool shape in table_coordinates.json.")
            
            # For place action: add +1mm margin to prevent collision
            if action_type == 'place':
                return tool_center_z - 5.0 + 2.0 + offset
            else:
                return tool_center_z - 5.0 + offset
        else:
            z_offset = 0.0
        
        # Calculate final z coordinates
        final_z = base_z + z_offset + offset
        
        return final_z
    
    def _calculate_trash_z_position(self, trash_name: str) -> float:
        """
        Calculate z coordinates of Trash (3mm below top-center of trash)
        
        Args:
            trash_name: trash name (e.g., 'tip-trash', 'liq-trash')
            
        Returns:
            calculated z coordinates
        """
        if not self.table_coords:
            return 0.0
        
        # trash tool info get
        trash_data = self.table_coords.get('tools', {}).get(trash_name, {})
        
        # Trash z position (center_coordinates.z is already the top-center point)
        center_coords = trash_data.get('center_coordinates', {})
        trash_z = center_coords.get('z', 0.0)
        
        # Final z coordinates = trash top-center point - 2mm
        final_z = trash_z - 2.0
        
        return final_z
    
    def _convert_time_to_seconds(self, time_value: float, time_unit: str) -> float:
        """
        Convert time unit to seconds
        
        Args:
            time_value: time value
            time_unit: time unit ('sec', 'min', 'hour')
            
        Returns:
            time converted to seconds
        """
        if time_unit == 'sec':
            return time_value
        elif time_unit == 'min':
            return time_value * 60
        elif time_unit == 'hour':
            return time_value * 3600
        else:
            # Default value is sto assume
            print(f"[DEBUG] unknown time unit '{time_unit}', sto assume")
            return time_value
    
    def _initialize_tip_grid_usage(self) -> Dict[str, List[bool]]:
        """Initialize tip grid usage state."""
        tip_grid_usage = {}
        
        if not self.table_coords:
            return tip_grid_usage
        
        # tip1, tip2, tip3 usage state of each grid Initialize
        for tip_num in range(1, 4):
            tip_name = f"tip{tip_num}"
            tool_data = self.table_coords.get('tools', {}).get(tip_name, {})
            grid_coords = tool_data.get('grid_pattern', {}).get('grid_center_coordinates', [])
            
            # Initialize each grid in tip box to False (unused)
            tip_grid_usage[tip_name] = [False] * len(grid_coords)
        
        return tip_grid_usage
    
    def _get_next_available_tip_position(self) -> Optional[Tuple[List[float], str, int]]:
        """Return next unused tip grid position."""
        print(f"[DEBUG] ========================================")
        print(f"[DEBUG] _get_next_available_tip_position start")
        print(f"[DEBUG] ========================================")
        
        if not self.table_coords:
            print("[DEBUG] table_coords is None")
            return None
        
        # Print current tip grid usage state
        print(f"[DEBUG] Current tip grid usage state:")
        for tip_name, usage_list in self.tip_grid_usage.items():
            used_count = sum(usage_list)
            total_count = len(usage_list)
            used_indices = [i for i, used in enumerate(usage_list) if used]
            print(f"  {tip_name}: {used_count}/{total_count} used, used indices: {used_indices}")
        
        # tip1, tip2, tip3 orderto unused grid find
        for tip_num in range(1, 4):
            tip_name = f"tip{tip_num}"
            print(f"[DEBUG] {tip_name} check in progress...")
            tool_data = self.table_coords.get('tools', {}).get(tip_name, {})
            grid_coords = tool_data.get('grid_pattern', {}).get('grid_center_coordinates', [])
            
            print(f"[DEBUG] {tip_name} grid count: {len(grid_coords)}")
            
            # unused grid find
            for grid_index, is_used in enumerate(self.tip_grid_usage[tip_name]):
                print(f"[DEBUG] {tip_name} grid {grid_index}: used={is_used}")
                if not is_used:
                    coord = grid_coords[grid_index]
                    result = [coord['x'], coord['y']], tip_name, grid_index
                    print(f"[DEBUG] available Tip position found: {result}")
                    print(f"[DEBUG] ========================================")
                    return result
        
        print(f"[DEBUG] No available tip position found")
        print(f"[DEBUG] ========================================")
        return None
    
    def _mark_tip_position_as_used(self, tip_name: str, grid_index: int):
        """Mark tip grid position as used."""
        print(f"[DEBUG] _mark_tip_position_as_used call: tip_name={tip_name}, grid_index={grid_index}")
        
        if tip_name in self.tip_grid_usage and grid_index < len(self.tip_grid_usage[tip_name]):
            old_value = self.tip_grid_usage[tip_name][grid_index]
            self.tip_grid_usage[tip_name][grid_index] = True
            print(f"[DEBUG] {tip_name} grid {grid_index} marked as used: {old_value} -> True")
            
            # Print updated usage state
            used_count = sum(self.tip_grid_usage[tip_name])
            total_count = len(self.tip_grid_usage[tip_name])
            used_indices = [i for i, used in enumerate(self.tip_grid_usage[tip_name]) if used]
            print(f"[DEBUG] {tip_name} Updated state: {used_count}/{total_count} used, used indices: {used_indices}")
        else:
            print(f"[DEBUG] invalid tip_name or grid_index: tip_name={tip_name}, grid_index={grid_index}")
            if tip_name not in self.tip_grid_usage:
                print(f"[DEBUG] tip_name not found in tip_grid_usage: {list(self.tip_grid_usage.keys())}")
            elif grid_index >= len(self.tip_grid_usage[tip_name]):
                print(f"[DEBUG] grid_indexout of range: {grid_index} >= {len(self.tip_grid_usage[tip_name])}")
    
    def _mark_tip_position_as_unused(self, tip_name: str, grid_index: int):
        """Mark tip grid position as unused."""
        if tip_name in self.tip_grid_usage and grid_index < len(self.tip_grid_usage[tip_name]):
            self.tip_grid_usage[tip_name][grid_index] = False
    
    def _create_move_offset_command(self, axis: str, offset: float, speed: Optional[float] = None, 
                                  action_type: str = "move_offset", description: str = "",
                                  tool_name: Optional[str] = None, grid_row: Optional[int] = None, 
                                  grid_col: Optional[int] = None) -> Dict[str, Any]:
        """move_offset command creation"""
        parameters = {
            "axis": axis,
            "offset": offset
        }
        
        # Add grid info if available (for use in next command)
        if tool_name and grid_row is not None and grid_col is not None:
            parameters["tool_name"] = tool_name
            parameters["grid_row"] = grid_row
            parameters["grid_col"] = grid_col
            print(f"[DEBUG] Adding grid info to move_offset: tool_name={tool_name}, row={grid_row}, col={grid_col}")
        
        # If speed not specified, calculate based on offset
        if speed is None:
            # For offset move on x or y axis with offset <= 20: configure low speed
            if axis in ['x', 'y'] and abs(offset) <= 20:
                speed = self.single_axis_speed
                print(f"[DEBUG] move_offset low speed configured: axis={axis}, offset={offset}, speed={speed}")
            else:
                speed = self.default_speed
                print(f"[DEBUG] move_offset general Speed: axis={axis}, offset={offset}, speed={speed}")
        else:
            print(f"[DEBUG] move_offset explicit speed: axis={axis}, offset={offset}, speed={speed}")
        
        parameters["speed"] = speed
        
        # Update _last_position: calculate expected position after move_offset
        if self._last_position is not None:
            new_position = self._last_position.copy()
            if axis == 'x':
                new_position[0] += offset
            elif axis == 'y':
                new_position[1] += offset
            elif axis == 'z':
                if len(new_position) > 2:
                    new_position[2] += offset
                else:
                    new_position.append(offset)
            
            old_position = self._last_position.copy()
            self._last_position = new_position
            print(f"[DEBUG] Updating _last_position after move_offset: {old_position} -> {self._last_position}")
        else:
            print(f"[DEBUG] move_offset: _last_position is None, skipping update")
        
        return {
            "type": action_type,
            "action": "move_offset",
            "function": "ScaraInterface.move_offset",
            "parameters": parameters,
            "description": description or f"{axis}-axis to {offset}mm move"
        }
    
    def _calculate_offset_between_positions(self, from_pos: List[float], to_pos: List[float]) -> Tuple[str, float]:
        """Calculate offset between two positions (return axis with largest difference)."""
        if len(from_pos) < 2 or len(to_pos) < 2:
            return "x", 0.0
        
        dx = to_pos[0] - from_pos[0]
        dy = to_pos[1] - from_pos[1]
        
        # axis with largest difference return
        if abs(dx) >= abs(dy):
            return "x", dx
        else:
            return "y", dy
    
    def _is_single_axis_movement(self, from_pos: Optional[List[float]], to_pos: List[float], threshold: float = None) -> bool:
        """
        Check if single axis move (x-axis only or y-axis only)
        
        Args:
            from_pos: previous position [x, y, z] or None
            to_pos: current position [x, y, z]
            threshold: fine error tolerance (mm), retrieved from config if None
        
        Returns:
            x-axis only or y-axis only moveif done True, otherwise False
        """
        if threshold is None:
            threshold = self.single_axis_movement_threshold
        
        if from_pos is None or len(from_pos) < 2 or len(to_pos) < 2:
            return False
        
        dx = abs(to_pos[0] - from_pos[0])
        dy = abs(to_pos[1] - from_pos[1])
        dz = abs(to_pos[2] - from_pos[2]) if len(to_pos) > 2 and len(from_pos) > 2 else 0
        
        # x-axis only move (dx > threshold, dy < threshold)
        if dx > threshold and dy < threshold:
            return True
        
        # y-axis only move (dy > threshold, dx < threshold)
        if dy > threshold and dx < threshold:
            return True
        
        return False
    
    def _calculate_speed_for_position(self, target_xyz: List[float], offset: Optional[float] = None, axis: Optional[str] = None) -> int:
        """
        Calculate move speed for target position (called during protocol→JSON conversion)
        
        Args:
            target_xyz: target position [x, y, z]
            offset: offset value for offset move (optional)
            axis: axis info for offset move (optional)
        
        Returns:
            calculated speed (5, 10, 50, or 100)
        """
        print(f"[DEBUG] _calculate_speed_for_position call:")
        print(f"   - target_xyz: {target_xyz}")
        print(f"   - offset: {offset}, axis: {axis}")
        print(f"   - _last_position: {self._last_position}")
        
        # Low speed only for offset move on x/y axis with offset <= 20
        if offset is not None and axis is not None and axis in ['x', 'y'] and abs(offset) <= 20:
            speed = self.single_axis_speed
            print(f"[DEBUG] _calculate_speed_for_position: offset move, axis={axis}, offset={offset}, speed={speed}")
        else:
            # If not offset move: compare with previous position to check single axis
            if self._last_position is not None:
                # Compare previous position with target position
                dx = abs(target_xyz[0] - self._last_position[0])
                dy = abs(target_xyz[1] - self._last_position[1])
                dz = abs(target_xyz[2] - self._last_position[2])
                
                print(f"[DEBUG] Position difference: dx={dx:.2f}mm, dy={dy:.2f}mm, dz={dz:.2f}mm")
                
                # Check if single axis move (threshold from config)
                threshold = self.single_axis_movement_threshold
                is_single_axis_x = dx > threshold and dy < threshold and dz < threshold
                is_single_axis_y = dy > threshold and dx < threshold and dz < threshold
                is_single_axis_z = dz > threshold and dx < threshold and dy < threshold
                
                print(f"[DEBUG] Single axis move evaluation: X={is_single_axis_x}, Y={is_single_axis_y}, Z={is_single_axis_z}")
                
                # move distance calculate
                distance_3d = (dx**2 + dy**2 + dz**2)**0.5  # 3D distance
                distance_2d = (dx**2 + dy**2)**0.5  # X-Y plane distance
                
                # Z-axis only move: use low speed for safety
                if is_single_axis_z:
                    if dz <= self.short_distance_threshold:  # short Z-axis move
                        speed = self.tip_equip_descent_speed
                        print(f"[DEBUG] _calculate_speed_for_position: single Z-axis move (short), dz={dz:.2f}mm, speed={speed}")
                    else:
                        speed = self.long_distance_z_axis_speed  # long Z-axis move speed
                        print(f"[DEBUG] _calculate_speed_for_position: single Z-axis move (long), dz={dz:.2f}mm, speed={speed}")
                # X or Y-axis only move case
                elif is_single_axis_x or is_single_axis_y:
                    if distance_2d <= self.short_distance_threshold:  # short single axis move (by X-Y plane distance)
                        speed = self.single_axis_speed
                        print(f"[DEBUG] _calculate_speed_for_position: single axis move (short), distance_2d={distance_2d:.2f}mm, speed={speed}")
                    else:
                        speed = self.long_distance_single_axis_speed  # long single axis move speed
                        print(f"[DEBUG] _calculate_speed_for_position: single axis move (long), distance_2d={distance_2d:.2f}mm, speed={speed}")
                # Multi-axis move case (includes cases where both X and Y change)
                else:
                    # If X-Y plane move distance <= 20mm, use speed 5
                    if distance_2d <= self.short_distance_threshold:
                        speed = self.single_axis_speed  # 5
                        print(f"[DEBUG] _calculate_speed_for_position: multi-axis move (short X-Y plane distance), distance_2d={distance_2d:.2f}mm, speed={speed}")
                    elif distance_3d <= self.short_distance_threshold:  # 3D distance at or below threshold
                        speed = self.multi_axis_intermediate_speed
                        print(f"[DEBUG] _calculate_speed_for_position: multi-axis move (short 3D distance), distance_3d={distance_3d:.2f}mm, speed={speed}")
                    else:
                        speed = self.default_speed  # default speed for long multi-axis move
                        print(f"[DEBUG] _calculate_speed_for_position: multi-axis move (long), distance_3d={distance_3d:.2f}mm, speed={speed}")
            else:
                # No previous position (first move): use default speed
                speed = self.default_speed
                print(f"[DEBUG] _calculate_speed_for_position: first move (no previous position), speed={speed}")
        
        # Update previous position
        old_position = self._last_position
        self._last_position = target_xyz.copy()
        print(f"[DEBUG] _last_position update: {old_position} -> {self._last_position}")
        print(f"[DEBUG] Final calculated speed: {speed}")
        
        return speed
    
    def _create_xy_move_command(self, pos: List[float], action_type: str, description: str, end_effector: str = "pipette", tool_name: Optional[str] = None, z_position: Optional[float] = None) -> Dict[str, Any]:
        """Create command to move x,y coordinates only (use z_position if specified, otherwise z=0)."""
        # Use z_position if specified, otherwise 0 (default)
        target_z = z_position if z_position is not None else 0
        target_xyz = pos + [target_z]
        
        # Compare with previous position, check single axis, calculate speed
        speed = self._calculate_speed_for_position(target_xyz)
        
        parameters = {
            "end_effector": end_effector,
            "xyz": target_xyz,
            "tip": end_effector == "pipette",
            "speed": speed
        }
        
        # Add tool_name to params if present (needed for coordinate calculation per tool shape)
        # tool_name is needed when accessing mea2, source etc. via pipette
        if tool_name:
            parameters["tool_name"] = tool_name
            
            # Add calibration info (if tool shape supports calibration)
            if self.calibration_manager:
                calib_data = self.calibration_manager.get_calibration_angles(tool_name)
                if calib_data:
                    # Reverse-calculate grid position from actual coordinates
                    grid_row, grid_col = self._calculate_grid_position_from_coordinates(pos, tool_name)
                    if grid_row is not None and grid_col is not None:
                        parameters["calibration_angles"] = {
                            "angle1": calib_data.get('angle1'),
                            "angle2": calib_data.get('angle2'),
                            "end_effector": calib_data.get('end_effector', end_effector),
                            "with_tip": calib_data.get('with_tip', end_effector == "pipette")
                        }
                        parameters["grid_row"] = grid_row
                        parameters["grid_col"] = grid_col
                        print(f"[DEBUG] Adding calibration info: {tool_name}, row={grid_row}, col={grid_col}")
        
        # MEA pick/place action case action add
        if end_effector == "gripper" and tool_name and 'mea' in tool_name.lower():
            parameters["action"] = action_type
        
        return {
            "type": action_type,
            "action": "move_xy_position",
            "function": "ScaraInterface.move_end_effector",
            "parameters": parameters,
            "description": description
        }
    
    def _calculate_grid_position_from_coordinates(self, pos: List[float], tool_name: str) -> Tuple[Optional[int], Optional[int]]:
        """
        Reverse-calculate grid (row, col) from actual coordinates
        
        Args:
            pos: actual coordinates [x, y]
            tool_name: tool name (e.g., 'mea2', 'tip1', 'mea-measure')
        
        Returns:
            Tuple[Optional[int], Optional[int]]: (row, col) or (None, None)
        """
        try:
            if not self.table_coords:
                return None, None
            
            tool_data = self.table_coords.get('tools', {}).get(tool_name)
            if not tool_data:
                return None, None
            
            grid_pattern = tool_data.get('grid_pattern', {})
            grid_center_coords = grid_pattern.get('grid_center_coordinates', [])
            
            if not grid_center_coords:
                return None, None
            
            # Determine grid cols count
            if 'tip' in tool_name:
                grid_cols = 12
            elif 'mea' in tool_name:
                grid_cols = 2
            else:
                grid_cols = 12  # Default values
            
            # Find grid position closest to actual coordinates
            target_x, target_y = pos[0], pos[1]
            min_distance = float('inf')
            best_index = None
            
            for i, grid_coord in enumerate(grid_center_coords):
                grid_x = grid_coord.get('x', 0)
                grid_y = grid_coord.get('y', 0)
                distance = ((target_x - grid_x)**2 + (target_y - grid_y)**2)**0.5
                
                if distance < min_distance:
                    min_distance = distance
                    best_index = i
            
            # Tolerance: within 5mm
            if best_index is not None and min_distance < 5.0:
                row = best_index // grid_cols
                col = best_index % grid_cols
                print(f"[DEBUG] Grid position reverse-calc: coordinates({target_x:.2f}, {target_y:.2f}) -> grid({row}, {col}), distance={min_distance:.2f}mm")
                return row, col
            else:
                print(f"[DEBUG] Grid position reverse-calc failed: min distance={min_distance:.2f}mm (allow error: 5mm)")
                return None, None
                
        except Exception as e:
            print(f"[DEBUG] Grid position reverse-calc error: {e}")
            import traceback
            traceback.print_exc()
            return None, None
    
    def _add_dynamic_surface_calculation_command(self, commands: List[Dict[str, Any]], pos: List[float], 
                                                   source_id: str, amount: float, floor_height: float, 
                                                   tool_center_z: Optional[float] = None, tool_size_z: Optional[float] = None):
        """Add command for dynamic calculation (fallback when tube interface is missing)."""
        commands.append({
            "type": "take",
            "action": "move_z_position",
            "function": "ScaraInterface.move_end_effector",
            "parameters": {
                "end_effector": "pipette",
                "xyz": [pos[0], pos[1], 0],  # z calculated at execution time
                "tip": True,
                "speed": self.default_speed,  # default speed for dynamic calculation
                "calculate_from_surface": True,  # dynamic calculate flag
                "source_id": source_id,  # for tube status queries
                "aspirate_amount": amount,  # aspirated volume (for consumed height calculation)
                "surface_offset": self.dynamic_surface_offset,  # surface height + offset
                "floor_height": floor_height,  # floor height (for z coordinate conversion)
                "tool_center_z": tool_center_z,  # tool center z coordinates (for z calculation)
                "tool_size_z": tool_size_z  # tool size z (tube height, for z calculation)
            },
            "description": f"Move to surface height + 5mm position (dynamic calculation: {source_id})"
        })
    
    def _create_z_move_command(self, pos: List[float], z_position: float, action_type: str, description: str, end_effector: str = "pipette", tool_name: Optional[str] = None, grid_row: Optional[int] = None, grid_col: Optional[int] = None) -> Dict[str, Any]:
        """Create command for z-coordinate only movement"""
        # pos can be [x, y] or [x, y, z] form; z is always newly calculated
        if len(pos) >= 2:
            # Get x, y from pos; use newly calculated z_position for z
            target_xyz = [pos[0], pos[1], z_position]
        else:
            # Use default value if pos is invalid
            target_xyz = [0.0, 0.0, z_position]
        
        # Compare with previous position, check single axis, calculate speed
        speed = self._calculate_speed_for_position(target_xyz)
        
        parameters = {
            "end_effector": end_effector,
            "xyz": target_xyz,
            "tip": end_effector == "pipette",
            "speed": speed
        }
        
        # Add grid info if available (maintain grid info after move_offset)
        if tool_name and grid_row is not None and grid_col is not None:
            parameters["tool_name"] = tool_name
            parameters["grid_row"] = grid_row
            parameters["grid_col"] = grid_col
            # Add calibration info (if tool shape supports calibration)
            if self.calibration_manager:
                calib_data = self.calibration_manager.get_calibration_angles(tool_name)
                if calib_data:
                    parameters["calibration_angles"] = {
                        "angle1": calib_data.get('angle1'),
                        "angle2": calib_data.get('angle2'),
                        "end_effector": calib_data.get('end_effector', end_effector),
                        "with_tip": calib_data.get('with_tip', end_effector == "pipette")
                    }
                    print(f"[DEBUG] Adding grid info to move_z_position: tool_name={tool_name}, row={grid_row}, col={grid_col}")
        
        # MEA pick/place action case action, tool_name, type add
        if end_effector == "gripper" and tool_name and 'mea' in tool_name.lower():
            parameters["action"] = action_type
            parameters["tool_name"] = tool_name
            parameters["type"] = action_type  # pass type for stack_count calculation
        
        return {
            "type": action_type,
            "action": "move_z_position",
            "function": "ScaraInterface.move_end_effector",
            "parameters": parameters,
            "description": description
        }
    
    def _is_mea_tool(self, tool_name: Optional[str]) -> bool:
        """Check if tool_name is an MEA tool."""
        if not tool_name:
            return False
        return 'mea' in tool_name.lower()
    
    def _create_move_to_mea_height_command(self, pos: List[float], tool_name: str, action_type: str, description: str, end_effector: str = "pipette") -> Dict[str, Any]:
        """Create command to move to MEA tool height + 5mm."""
        # Get center Z coordinates of MEA tool
        tool_center_z = self._get_tool_center_z(tool_name)
        if tool_center_z is None:
            # Fallback: use top position
            print(f"[DEBUG] Cannot find tool_center_z for {tool_name}, using top position")
            return self._create_move_to_top_command(pos, action_type, description, end_effector)
        
        # MEA tool height + 5mm calculate
        mea_height_offset = 5.0  # 5mm
        target_z = tool_center_z + mea_height_offset
        target_xyz = [pos[0], pos[1], target_z]
        
        # Calculate speed
        speed = self._calculate_speed_for_position(target_xyz)
        
        return {
            "type": action_type,
            "action": "move_z_position",
            "function": "ScaraInterface.move_end_effector",
            "parameters": {
                "end_effector": end_effector,
                "xyz": target_xyz,
                "tip": end_effector == "pipette",
                "speed": speed
            },
            "description": description
        }
    
    def _create_move_to_top_command(self, pos: List[float], action_type: str, description: str, end_effector: str = "pipette") -> Dict[str, Any]:
        """Create command to move to top position (z=0)."""
        target_xyz = pos + [0]  # z=0 (top position)
        
        # Call _calculate_speed_for_position for _last_position update
        # move_to_top uses initial_position_move_to_top_speed from config
        speed = getattr(self, 'initial_position_move_to_top_speed', 50)
        
        return {
            "type": action_type,
            "action": "move_to_top",
            "function": "ScaraInterface.move_to_top",
            "parameters": {
                "end_effector": end_effector,
                "xyz": target_xyz,
                "tip": end_effector == "pipette",
                "speed": speed  # initial_position_move_to_top_speed configuse value
            },
            "description": description
        }
    
    def _get_auto_tip_position(self) -> Optional[Tuple[List[float], str, int]]:
        """Return next unused tip grid position automatically (used by all tip-related actions)."""
        return self._get_next_available_tip_position()
    
    def _apply_auto_tip_position(self, command: Dict[str, Any]) -> Dict[str, Any]:
        """Apply auto tip position to command."""
        if (command.get('type') == 'equip' and 
            command.get('action') in ['move_xy_position', 'move_z_position', 'move_to_top'] and 
            'parameters' in command and 
            'xyz' in command['parameters']):
            
            
            # Use saved tip position info or auto-calculate next unused tip grid position
            if hasattr(self, '_current_tip_position') and self._current_tip_position:
                tip_position = self._current_tip_position
                tip_tool_name = self._current_tip_tool_name
                tip_grid_index = self._current_tip_grid_index
            else:
                tip_data = self._get_auto_tip_position()
                if tip_data:
                    tip_position, tip_tool_name, tip_grid_index = tip_data
                else:
                    return command
            
            # Calculate z coordinate (origin_0 z offset already included)
            z_position = self._calculate_z_position(tip_tool_name, "equip")
            
            # Update coordinates according to action
            if command.get('action') == 'move_xy_position':
                # Move X, Y only (Z=0)
                target_xyz = tip_position + [0]
                speed = self._calculate_speed_for_position(target_xyz)
                command['parameters']['xyz'] = target_xyz
                command['parameters']['speed'] = speed
                command['description'] = f"Move X,Y to tip position: {tip_position}"
            elif command.get('action') == 'move_z_position':
                # Z move - apply different Z coordinates according to description
                if "Z -7mm" in command.get('description', '') or "for tip attach" in command.get('description', ''):
                    # Z move for tip attach (-7mm)
                    target_xyz = tip_position + [z_position - 7]
                    speed = self._calculate_speed_for_position(target_xyz)
                    command['parameters']['xyz'] = target_xyz
                    command['parameters']['speed'] = speed
                    command['description'] = f"Z move for tip attach (-7mm): {z_position - 7}"
                elif "Z +7mm" in command.get('description', '') or "after tip attach" in command.get('description', ''):
                    # Z move after tip attach (+7mm)
                    target_xyz = tip_position + [z_position]
                    speed = self._calculate_speed_for_position(target_xyz)
                    command['parameters']['xyz'] = target_xyz
                    command['parameters']['speed'] = speed
                    command['description'] = f"Z move after tip attach (+7mm): {z_position}"
                else:
                    # Normal Z move
                    target_xyz = tip_position + [z_position]
                    speed = self._calculate_speed_for_position(target_xyz)
                    command['parameters']['xyz'] = target_xyz
                    command['parameters']['speed'] = speed
                    command['description'] = f"Z move to tip position: {z_position}"
            elif command.get('action') == 'move_to_top':
                # Move to top position (Z=0)
                target_xyz = tip_position + [0]
                speed = self._calculate_speed_for_position(target_xyz)
                command['parameters']['xyz'] = target_xyz
                command['parameters']['speed'] = speed
                command['description'] = f"Move to top position: {tip_position}"
            
            # Mark tip grid position as used
            self._mark_tip_position_as_used(tip_tool_name, tip_grid_index)
        
        return command
    
    def _apply_auto_tip_positions_to_all_commands(self, command_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply auto tip positions to all commands (skip already processed ones)."""
        processed_commands = []
        
        for command in command_list:
            # Apply auto tip position to move_xy_position, move_z_position, move_to_top actions
            # Skip if coordinates already configured (prevent duplicate processing)
            if (command.get('type') == 'equip' and 
                command.get('action') in ['move_xy_position', 'move_z_position', 'move_to_top'] and 
                'parameters' in command and 
                'xyz' in command['parameters']):
                
                # Skip command if actual coordinates already configured
                xyz = command['parameters']['xyz']
                # Skip if real coordinates are configured (not [0,0,0] or default)
                if (xyz != [0, 0, 0] and 
                    not (xyz[0] == 0 and xyz[1] == 0 and xyz[2] == 0) and
                    not (xyz[0] == 420 and xyz[1] == 0 and xyz[2] == 0)):  # Exclude init command
                    print(f"[DEBUG] Skipping command with already-configured coordinates: {command.get('action')} - {xyz}")
                    processed_commands.append(command)
                    continue
                
                # Apply auto tip position
                command = self._apply_auto_tip_position(command)
            
            processed_commands.append(command)
        
        return processed_commands
    
    def save_command_list(self, command_list: List[Dict[str, Any]], output_file: str = "cmd_list.json"):
        """Save Command List to JSON file."""
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(command_list, f, ensure_ascii=False, indent=2)
        
        print(f"Command List saved to {output_file}.")
    
    def reset_state(self):
        """Initialize state + detailed debug"""
        print(f"\n{'='*80}")
        print(f"[DEBUG] reset_state call before state:")
        print(f"  equipped_tip: {self.equipped_tip}")
        print(f"  current_tip_position: {self.current_tip_position}")
        print(f"  current_source_volumes: {self.current_source_volumes}")
        print(f"  tip_grid_usage:")
        for tip_name, usage_list in self.tip_grid_usage.items():
            used_count = sum(usage_list)
            total_count = len(usage_list)
            print(f"    {tip_name}: {used_count}/{total_count} used")
        
        # Check additional state variables
        if hasattr(self, '_current_tip_position'):
            print(f"  _current_tip_position: {getattr(self, '_current_tip_position', 'None')}")
        if hasattr(self, '_current_tip_tool_name'):
            print(f"  _current_tip_tool_name: {getattr(self, '_current_tip_tool_name', 'None')}")
        if hasattr(self, '_current_tip_grid_index'):
            print(f"  _current_tip_grid_index: {getattr(self, '_current_tip_grid_index', 'None')}")
        
        # state Initialize
        self.current_tip_position = 0
        self.current_source_volumes = {}
        self.equipped_tip = False
        # Do not reset tip_grid_usage (tips are single-use; used positions remain unavailable)
        # self.tip_grid_usage = self._initialize_tip_grid_usage()  # commented out (experiment restart) - used tip positions remain unavailable
        
        # Initialize additional state variables
        if hasattr(self, '_current_tip_position'):
            self._current_tip_position = None
        if hasattr(self, '_current_tip_tool_name'):
            self._current_tip_tool_name = None
        if hasattr(self, '_current_tip_grid_index'):
            self._current_tip_grid_index = None
        
        # Initialize previous position
        self._last_position = None
        
        print(f"[DEBUG] reset_state call after state:")
        print(f"  equipped_tip: {self.equipped_tip}")
        print(f"  current_tip_position: {self.current_tip_position}")
        print(f"  current_source_volumes: {self.current_source_volumes}")
        print(f"  tip_grid_usage:")
        for tip_name, usage_list in self.tip_grid_usage.items():
            used_count = sum(usage_list)
            total_count = len(usage_list)
            print(f"    {tip_name}: {used_count}/{total_count} used")
        print(f"{'='*80}\n")
    
    def _get_test_protocol_data(self):
        """Return test protocol data"""
        return {
            "description": "Test protocol",
            "processes": [
                {
                    "name": "Process_001",
                    "description": "Tip attach test",
                    "orders": [
                        {
                            "action": "Equip",
                            "amount": 0,
                            "time": {"value": 0, "unit": "sec"},
                            "target": "none"
                        }
                    ]
                },
                {
                    "name": "Process_002", 
                    "description": "Liquid processing test (consecutive targets)",
                    "orders": [
                        {
                            "action": "Take",
                            "amount": 100,
                            "time": {"value": 0, "unit": "sec"},
                            "target": {
                                "SOURCE": {
                                    "SOURCE1": [[0, 0]]
                                }
                            }
                        },
                        {
                            "action": "Apply",
                            "amount": 50,
                            "time": {"value": 0, "unit": "sec"},
                            "target": {
                                "MEA": {
                                    "MEA1": [[0, 0], [0, 1], [0, 2], [0, 3]]
                                }
                            }
                        },
                        {
                            "action": "Dispose",
                            "amount": 25,
                            "time": {"value": 0, "unit": "sec"},
                            "target": {
                                "MEA": {
                                    "MEA1": [[1, 0], [1, 1], [1, 2]]
                                }
                            }
                        }
                    ]
                }
            ]
        }
    
    
    def _extract_source_id_from_target(self, target, position):
        """Extract source_id from target (convert Source Desc to Source ID)"""
        try:
            source_group = target.get('SOURCE', {})
            
            # Find first source with coordinates
            for source_name, source_positions in source_group.items():
                if source_positions:  # If coordinates exist, try to convert source_name to Source ID
                    # source_name may be Source Desc; attempt to convert to Source ID
                    source_id = self._convert_source_desc_to_id(source_name)
                    print(f"[DEBUG] Source name '{source_name}' -> Source ID '{source_id}'")
                    return source_id
            
            return None
            
        except Exception as e:
            print(f"source_id extract Error: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _convert_source_desc_to_id(self, source_name: str) -> str:
        """Convert Source Desc to Source ID."""
        # If mapping exists, convert Source Desc -> Source ID
        if hasattr(self, 'source_desc_to_id') and self.source_desc_to_id:
            print(f"[DEBUG] _convert_source_desc_to_id: source_name='{source_name}', mapping={self.source_desc_to_id}")
            if source_name in self.source_desc_to_id:
                source_id = self.source_desc_to_id[source_name]
                print(f"Source Desc '{source_name}' -> Source ID '{source_id}' (using mapping)")
                return source_id
            else:
                print(f"[DEBUG] '{source_name}' not found in mapping. mapping keys: {list(self.source_desc_to_id.keys())}")
        else:
            print(f"[DEBUG] source_desc_to_id is missing or empty. hasattr={hasattr(self, 'source_desc_to_id')}, value={getattr(self, 'source_desc_to_id', None)}")
        
        # If mapping not found:
        # 1. Check if already in Source ID format (source1, source2, etc.)
        source_name_lower = source_name.lower()
        if source_name_lower.startswith('source') and source_name_lower[6:].isdigit():
            print(f"'{source_name}' is already in Source ID format")
            return source_name_lower
        
        # 2. Check if in SOURCE1, SOURCE2 format
        if source_name.upper().startswith('SOURCE') and source_name[6:].isdigit():
            print(f"Converting '{source_name}' to Source ID: {source_name_lower}")
            return source_name_lower
        
        # 3. If no mapping, return as-is (but warn)
        print(f"No Source ID mapping found for Source Desc '{source_name}'. Using as-is: {source_name_lower}")
        return source_name_lower


# Test code
if __name__ == "__main__":
    def test_converter(input_file: str = None, output_file: str = None):
        """Basic operation test
        
        Args:
            input_file: input protocol file path (use default test data if None)
            output_file: output command list file path (use "test_cmd_list.json" if None)
        """
        print("=== Protocol to Command Converter Test ===")
        
        # Default values config
        if input_file is None:
            input_file = "protocol/test_protocol.json"
        if output_file is None:
            output_file = "test_cmd_list.json"
        
        try:
            # Initialize converter
            converter = ProtocolToCommandConverter()
            
            # Convert input file
            if input_file and not input_file.startswith("protocol/test_protocol.json"):
                # Convert actual file
                command_list = converter.convert_protocol_file(input_file)
                print(f"File '{input_file}' conversion complete: {len(command_list)} commands created")
            else:
                # Convert test protocol data
                command_list = converter.convert_protocol_data(converter._get_test_protocol_data())
                print(f"Test data conversion complete: {len(command_list)} commands created")
            
            # print result
            for i, cmd in enumerate(command_list, 1):
                print(f"{i:2d}. {cmd.get('type', 'unknown')} - {cmd.get('action', 'unknown')}: {cmd.get('description', '')}")
            
            # Print tip grid usage state
            print("\n=== Tip grid usage state ===")
            for tip_name, usage_list in converter.tip_grid_usage.items():
                used_count = sum(usage_list)
                total_count = len(usage_list)
                print(f"{tip_name}: {used_count}/{total_count} used")
                if used_count > 0:
                    used_indices = [i for i, used in enumerate(usage_list) if used]
                    print(f"  used Grid Index: {used_indices[:10]}{'...' if len(used_indices) > 10 else ''}")
            
            # Save to JSON file
            converter.save_command_list(command_list, output_file)
            print(f"\nCommand List saved to '{output_file}'. ")
            print("Test complete!")
            
        except Exception as e:
            print(f"convert in progress Error occurred: {e}")
            import traceback
            traceback.print_exc()
    
    def _get_test_protocol_data(self):
        """Return test protocol data."""
        return {
            "description": "Test protocol",
            "processes": [
                {
                    "name": "Process_001",
                    "description": "Tip attach test",
                    "orders": [
                        {
                            "action": "Equip",
                            "amount": 0,
                            "time": {"value": 0, "unit": "sec"},
                            "target": "none"
                        }
                    ]
                },
                {
                    "name": "Process_002", 
                    "description": "Liquid processing test (consecutive targets)",
                    "orders": [
                        {
                            "action": "Take",
                            "amount": 100,
                            "time": {"value": 0, "unit": "sec"},
                            "target": {
                                "SOURCE": {
                                    "SOURCE1": [[0, 0]]
                                }
                            }
                        },
                        {
                            "action": "Apply",
                            "amount": 50,
                            "time": {"value": 0, "unit": "sec"},
                            "target": {
                                "MEA": {
                                    "MEA1": [[0, 0], [0, 1], [0, 2], [0, 3]]
                                }
                            }
                        },
                        {
                            "action": "Dispose",
                            "amount": 25,
                            "time": {"value": 0, "unit": "sec"},
                            "target": {
                                "MEA": {
                                    "MEA1": [[1, 0], [1, 1], [1, 2]]
                                }
                            }
                        }
                    ]
                }
            ]
        }
    def test_grid_coordinates():
        """Grid coordinates test mode"""
        print("\n=== Grid coordinate test mode ===")
        
        converter = ProtocolToCommandConverter()
        
        # MEA Tool grid coordinates check
        print("\n--- MEA Tool grid coordinates ---")
        for mea_num in [1, 2, 3]:
            tool_name = f"mea{mea_num}"
            tool_data = converter.table_coords.get('tools', {}).get(tool_name, {})
            
            if tool_data:
                print(f"\n{tool_name.upper()}:")
                print(f"  Center Coordinates: {tool_data.get('center_coordinates', {})}")
                print(f"  Size: {tool_data.get('size', {})}")
                
                grid_coords = tool_data.get('grid_pattern', {}).get('grid_center_coordinates', [])
                table_coords = tool_data.get('grid_pattern', {}).get('grid_table_coordinates', [])
                
                print(f"  Grid Center Coordinates ({len(grid_coords)}):")
                for i, coord in enumerate(grid_coords):
                    row = i // 8  # 8x2 grid
                    col = i % 8
                    print(f"    [{row:2d},{col:2d}] -> Center: [{coord['x']:6.1f}, {coord['y']:6.1f}]")
                
                print(f"  Grid Table Coordinates ({len(table_coords)}):")
                for i, coord in enumerate(table_coords):
                    row = i // 8  # 8x2 grid
                    col = i % 8
                    print(f"    [{row:2d},{col:2d}] -> Table:  [{coord['x']:6.1f}, {coord['y']:6.1f}]")
            else:
                print(f"{tool_name.upper()}: data not found")
        
        # Tip Box grid coordinates check
        print("\n--- Tip Box grid coordinates ---")
        for tip_num in [1, 2, 3]:
            tool_name = f"tip{tip_num}"
            tool_data = converter.table_coords.get('tools', {}).get(tool_name, {})
            
            if tool_data:
                print(f"\n{tool_name.upper()}:")
                print(f"  Center Coordinates: {tool_data.get('center_coordinates', {})}")
                print(f"  Size: {tool_data.get('size', {})}")
                
                grid_coords = tool_data.get('grid_pattern', {}).get('grid_center_coordinates', [])
                table_coords = tool_data.get('grid_pattern', {}).get('grid_table_coordinates', [])
                
                print(f"  Grid Center Coordinates ({len(grid_coords)}, 8x12):")
                for i, coord in enumerate(grid_coords):
                    row = i // 8  # 8x12 grid
                    col = i % 8
                    if i < 20:  # show first 20 only
                        print(f"    [{row:2d},{col:2d}] -> Center: [{coord['x']:6.1f}, {coord['y']:6.1f}]")
                    elif i == 20:
                        print(f"    ... (Total {len(grid_coords)}, showing first 20)")
                
                print(f"  Grid Table Coordinates ({len(table_coords)}, 8x12):")
                for i, coord in enumerate(table_coords):
                    row = i // 8  # 8x12 grid
                    col = i % 8
                    if i < 20:  # show first 20 only
                        print(f"    [{row:2d},{col:2d}] -> Table:  [{coord['x']:6.1f}, {coord['y']:6.1f}]")
                    elif i == 20:
                        print(f"    ... (Total {len(table_coords)}, showing first 20)")
            else:
                print(f"{tool_name.upper()}: data not found")
        
        # Source coordinates check
        print("\n--- Source coordinates ---")
        for source_num in [1, 2, 3]:
            tool_name = f"source{source_num}"
            tool_data = converter.table_coords.get('tools', {}).get(tool_name, {})
            
            if tool_data:
                print(f"{tool_name.upper()}:")
                print(f"  Center Coordinates: {tool_data.get('center_coordinates', {})}")
                print(f"  Table Coordinates: {tool_data.get('table_coordinates', {})}")
                print(f"  Size: {tool_data.get('size', {})}")
            else:
                print(f"{tool_name.upper()}: data not found")
        
        # Coordinates conversion test
        print("\n--- Coordinates conversion test ---")
        test_cases = [
            ("MEA", "MEA1", [0, 0]),
            ("MEA", "MEA1", [0, 1]),
            ("MEA", "MEA2", [0, 0]),
            ("MEA", "MEA2", [1, 0]),
            ("TIP", "TIP1", [0, 0]),
            ("TIP", "TIP1", [0, 1]),
            ("TIP", "TIP2", [0, 0]),
            ("SOURCE", "SOURCE1", [0, 0]),
            ("SOURCE", "SOURCE2", [0, 0]),
        ]
        
        for group, item, grid_pos in test_cases:
            if group == "SOURCE":
                # Source has no grid, use coordinates directly
                tool_key = item.lower()
                tool_data = converter.table_coords.get('tools', {}).get(tool_key, {})
                if tool_data:
                    center_coords = tool_data.get('center_coordinates', {})
                    actual_pos = [center_coords['x'], center_coords['y']] if center_coords else None
                else:
                    actual_pos = None
            else:
                result = converter._convert_grid_to_actual_coordinates(grid_pos, group, item)
                if result:
                    actual_pos, grid_index = result
                else:
                    actual_pos = None
            
            print(f"  {group}{item} {grid_pos} -> {actual_pos}")
    
    def test_protocol_with_coordinates():
        """Test coordinates conversion with actual protocol."""
        print("\n=== Actual protocol coordinates conversion test ===")
        
        converter = ProtocolToCommandConverter()
        
        try:
            # Convert actual protocol
            command_list = converter.convert_protocol_file('prep_bacteria_sensor.json')
            
            print(f"Protocol conversion complete: {len(command_list)} commands created")
            
            # Filter only commands that include coordinates
            coordinate_commands = [cmd for cmd in command_list if 'parameters' in cmd and 'xyz' in cmd.get('parameters', {})]
            
            print(f"\nCommands with coordinates: {len(coordinate_commands)}")
            
            # Group and display by coordinates
            coordinate_groups = {}
            for cmd in coordinate_commands:
                xyz = cmd['parameters']['xyz']
                coord_key = f"[{xyz[0]:.1f}, {xyz[1]:.1f}, {xyz[2]:.1f}]"
                if coord_key not in coordinate_groups:
                    coordinate_groups[coord_key] = []
                coordinate_groups[coord_key].append(cmd)
            
            print(f"\nunique coordinates Position: {len(coordinate_groups)}")
            for coord, cmds in sorted(coordinate_groups.items()):
                print(f"  {coord}: {len(cmds)} command")
                for cmd in cmds[:3]:  # show first 3 only
                    print(f"    - {cmd['type']}.{cmd['action']}")
                if len(cmds) > 3:
                    print(f"    ... (Total {len(cmds)})")
            
        except Exception as e:
            print(f"protocol convert in progress Error occurred: {e}")
            import traceback
            traceback.print_exc()
    
    def test_tip_grid_usage():
        """Test tip grid usage state."""
        print("\n=== Tip grid usage state test ===")
        
        converter = ProtocolToCommandConverter()
        
        # Check tip grid usage state initialization
        print("Initial tip grid usage status:")
        for tip_name, usage_list in converter.tip_grid_usage.items():
            used_count = sum(usage_list)
            total_count = len(usage_list)
            print(f"  {tip_name}: {used_count}/{total_count} used")
        
        # Test multiple Equip actions
        test_protocol = {
            "description": "Tip grid usage test",
            "processes": [
                {
                    "name": "Process_001",
                    "description": "Tip attach test",
                    "orders": [
                        {
                            "action": "Equip",
                            "amount": 0,
                            "time": {"value": 0, "unit": "sec"},
                            "target": "none"
                        },
                        {
                            "action": "Eject",
                            "amount": 0,
                            "time": {"value": 0, "unit": "sec"},
                            "target": "none"
                        },
                        {
                            "action": "Equip",
                            "amount": 0,
                            "time": {"value": 0, "unit": "sec"},
                            "target": "none"
                        },
                        {
                            "action": "Eject",
                            "amount": 0,
                            "time": {"value": 0, "unit": "sec"},
                            "target": "none"
                        },
                        {
                            "action": "Equip",
                            "amount": 0,
                            "time": {"value": 0, "unit": "sec"},
                            "target": "none"
                        }
                    ]
                }
            ]
        }
        
        try:
            # protocol convert
            command_list = converter.convert_protocol_data(test_protocol)
            
            print(f"\nConversion complete: {len(command_list)} commands created")
            
            # Print tip grid usage state
            print("\nFinal tip grid usage state:")
            for tip_name, usage_list in converter.tip_grid_usage.items():
                used_count = sum(usage_list)
                total_count = len(usage_list)
                print(f"  {tip_name}: {used_count}/{total_count} used")
                if used_count > 0:
                    used_indices = [i for i, used in enumerate(usage_list) if used]
                    print(f"    used Grid Index: {used_indices[:10]}{'...' if len(used_indices) > 10 else ''}")
            
            # Check Equip command coordinates
            equip_commands = [cmd for cmd in command_list if cmd.get('type') == 'equip' and cmd.get('action') in ['move_xy_position', 'move_z_position']]
            print(f"\nEquip command coordinates:")
            for i, cmd in enumerate(equip_commands, 1):
                xyz = cmd['parameters']['xyz']
                action = cmd.get('action', 'unknown')
                print(f"  {i}. {action}: {xyz}")
            
        except Exception as e:
            print(f"Test in progress - Error occurred: {e}")
            import traceback
            traceback.print_exc()
    
    # Menu options
    import sys
    if len(sys.argv) > 1:
        mode = sys.argv[1]
    else:
        print("=== Protocol to Command Converter ===")
        print("Usage:")
        print("  python3 protocol_to_command_converter.py [input_file] [output_file]")
        print("  python3 protocol_to_command_converter.py [mode]")
        print("")
        print("Modes:")
        print("  1: Basic test (using test data)")
        print("  2: Grid coordinate test")
        print("  3: Protocol coordinate test")
        print("  4: Tip grid usage state test")
        print("  5: Full test")
        print("")
        print("example:")
        print("  python3 protocol_to_command_converter.py protocol/test.json output.json")
        print("  python3 protocol_to_command_converter.py 1")
        print("  python3 protocol_to_command_converter.py protocol/test.json")
        print("")
        mode = input("Test mode (1: basic, 2: grid coordinates, 3: protocol coordinates, 4: tip grid state, 5: all): ").strip()
    
    if mode in ["1", "basic"]:
        test_converter()
    elif mode in ["2", "grid"]:
        test_grid_coordinates()
    elif mode in ["3", "protocol"]:
        test_protocol_with_coordinates()
    elif mode in ["4", "tipgrid"]:
        test_tip_grid_usage()
    elif mode in ["5", "all"]:
        test_converter()
        test_grid_coordinates()
        test_protocol_with_coordinates()
        test_tip_grid_usage()
    else:
        # Case where filename is given (mode is not a number)
        input_file = sys.argv[1]
        output_file = sys.argv[2] if len(sys.argv) > 2 else "test_cmd_list.json"
        test_converter(input_file, output_file)
