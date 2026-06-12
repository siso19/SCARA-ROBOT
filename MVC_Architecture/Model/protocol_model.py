"""
Protocol Data Model
MVC Model Layer
"""

import json
import os
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from PySide6.QtCore import QObject, Signal

# Protocol action list
PROTOCOL_ACTIONS = [
    "Equip",            # Equip pipette
    "Eject",            # Eject pipette
    "Pick",             # Pick
    "Place",            # Place
    "Take",             # Take / aspirate
    "Apply",            # Apply
    "Dispose",          # Dispose
    "Measure",          # Measure
    "Wait",             # Wait
    "Open",             # Open
    "Close",            # Close
    "Mix"               # Mix
]

@dataclass
class GridPosition:
    """Grid position data."""
    x: int
    y: int
    
    def to_tuple(self) -> tuple:
        return (self.x, self.y)
    
    @classmethod
    def from_tuple(cls, pos_tuple: tuple) -> 'GridPosition':
        return cls(pos_tuple[0], pos_tuple[1])


@dataclass
class TargetInfo:
    """Target information."""
    group_name: str
    item_name: str
    positions: List[GridPosition]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_name": self.group_name,
            "item_name": self.item_name,
            "positions": [pos.to_tuple() for pos in self.positions]
        }


@dataclass
class OrderData:
    """Order data."""
    action: str
    amount: int
    time_value: int
    time_unit: str
    target: Dict[str, Any]  # Target info per group
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "amount": self.amount,
            "time": {
                "value": self.time_value,
                "unit": self.time_unit
            },
            "target": self.target
        }


@dataclass
class ProcessData:
    """Process data."""
    name: str
    description: str
    orders: List[OrderData]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "orders": [order.to_dict() for order in self.orders]
        }


@dataclass
class ProtocolData:
    """Protocol data."""
    description: str
    processes: List[ProcessData]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "description": self.description,
            "processes": [process.to_dict() for process in self.processes]
        }


class ProtocolModel(QObject):
    """Protocol Data Model - manages a single source dict (simplified)"""
    
    # Signal definitions
    data_changed = Signal()  # Emitted when data changes
    process_added = Signal(str)  # Emitted when process is added (process name)
    process_removed = Signal(str)  # Emitted when process is removed (process name)
    order_added = Signal(str, str)  # Emitted when order is added (process name, action)
    order_removed = Signal(str, str)  # Emitted when order is removed (process name, action)
    
    def __init__(self):
        super().__init__()
        # Manages only a single source dict
        self._protocol_dict = {
            "description": "Empty protocol data",
            "processes": []
        }
        self._current_file_path: Optional[str] = None
    
    @property
    def protocol_dict(self) -> Dict[str, Any]:
        """Return source dict (no copy). Auto-assign sort_order to unset processes."""
        self._ensure_sort_orders()
        return self._protocol_dict
    
    def get_process_by_name(self, process_name: str) -> Optional[Dict[str, Any]]:
        """Find process by name."""
        for process in self._protocol_dict["processes"]:
            if process.get("name") == process_name:
                return process
        return None
    
    def get_process_by_index(self, process_index: int) -> Optional[Dict[str, Any]]:
        """Find process by index."""
        if 0 <= process_index < len(self._protocol_dict["processes"]):
            return self._protocol_dict["processes"][process_index]
        return None
    
    def _get_next_sort_order(self) -> int:
        """Return the largest sort_order among current processes + 1."""
        processes = self._protocol_dict.get('processes', [])
        if not processes:
            return 0
        max_order = max(p.get('sort_order', 0) for p in processes)
        return max_order + 1

    def _ensure_sort_orders(self):
        """Auto-assign sort_order to processes that lack it (backward compatibility)."""
        for i, process in enumerate(self._protocol_dict.get('processes', [])):
            if 'sort_order' not in process:
                process['sort_order'] = i

    def _reassign_sort_orders(self):
        """Reassign sort_order based on current list order."""
        for i, process in enumerate(self._protocol_dict.get('processes', [])):
            process['sort_order'] = i

    def generate_next_process_name(self) -> str:
        """Generate the next process name (3-digit format: Process_000, Process_001, ...)."""
        import re
        processes = self._protocol_dict.get('processes', [])
        max_process_num = 0
        
        # Extract numbers from processes starting with 'Process_'
        for process in processes:
            process_name = process.get('name', '')
            # Extract number if starts with 'Process_' (supports 3-digit or general numbers)
            match = re.match(r'^Process_(\d+)$', process_name)
            if match:
                process_num = int(match.group(1))
                if process_num > max_process_num:
                    max_process_num = process_num
        
        # Generate new process name with next number (3-digit format)
        return f"Process_{max_process_num + 1:03d}"
    
    def add_process(self, name: str, description: str = "") -> bool:
        """Add a new process."""
        try:
            # Check for duplicate names
            if self.get_process_by_name(name):
                print(f" [DEBUG] Duplicate process name: {name}")
                return False
            
            new_process = {
                "name": name,
                "description": description,
                "sort_order": self._get_next_sort_order(),
                "orders": []
            }
            
            self._protocol_dict["processes"].append(new_process)
            print(f" [DEBUG] data_changed signal emit start (receivers: {self.receivers('data_changed')})")
            self.data_changed.emit()
            print(f" DEBUG] data_changed signal emit complete")
            print(f" [DEBUG] Process added successfully: {name}")
            return True
            
        except Exception as e:
            print(f" [DEBUG] Process add error: {e}")
            return False
    
    def remove_process(self, process_name: str) -> bool:
        """Remove a process."""
        try:
            original_length = len(self._protocol_dict["processes"])
            self._protocol_dict["processes"] = [
                p for p in self._protocol_dict["processes"] 
                if p.get("name") != process_name
            ]
            
            if len(self._protocol_dict["processes"]) < original_length:
                self.data_changed.emit()
                print(f" [DEBUG] Process removed successfully: {process_name}")
                return True
            else:
                print(f" [DEBUG] Process removal failed: {process_name} not found")
                return False
                
        except Exception as e:
            print(f" [DEBUG] Process removal error: {e}")
            return False
    
    def add_order(self, process_name: str, order_dict: Dict[str, Any]) -> bool:
        """Add an order."""
        try:
            print(f" [DEBUG] ProtocolModel.add_order started")
            print(f" process_name: '{process_name}'")
            print(f" order_dict: {order_dict}")
            
            process = self.get_process_by_name(process_name)
            print(f" Found process: {process}")
            
            if process:
                print(f" process['orders'] current state: {process.get('orders', [])}")
                process["orders"].append(order_dict)
                print(f" process['orders'] state after add: {process.get('orders', [])}")
                print(f" [DEBUG] data_changed signal emit start (receivers: {self.receivers('data_changed')})")
                self.data_changed.emit()
                print(f" [DEBUG] data_changed signal emit complete")
                print(f" [DEBUG] Order added successfully: {process_name} - {order_dict.get('action', 'Unknown')}")
                return True
            else:
                print(f" [DEBUG] Process not found: {process_name}")
                print(f" [DEBUG] Current process list:")
                for i, proc in enumerate(self._protocol_dict.get('processes', [])):
                    print(f"   - {i}: {proc.get('name', 'Unknown')}")
                return False
            
        except Exception as e:
            print(f" [DEBUG] Order add error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def remove_order(self, process_name: str, order_index: int) -> bool:
        """Remove an order."""
        try:
            process = self.get_process_by_name(process_name)
            if process and 0 <= order_index < len(process["orders"]):
                removed_order = process["orders"].pop(order_index)
                self.data_changed.emit()
                print(f" [DEBUG] Order removed successfully: {process_name} - {removed_order.get('action', 'Unknown')}")
                return True
            return False
            
        except Exception as e:
            print(f" [DEBUG] Order removal error: {e}")
            return False
    
    def update_description(self, new_description: str) -> bool:
        """Update protocol description."""
        try:
            self._protocol_dict["description"] = new_description
            self.data_changed.emit()
            print(f" [DEBUG] Description updated successfully: {new_description}")
            return True
            
        except Exception as e:
            print(f" [DEBUG] Description update error: {e}")
            return False
    
    def load_from_file(self, file_path: str) -> tuple[bool, dict]:
        """Load protocol data from file."""
        try:
            print(f" [DEBUG] ProtocolModel.load_from_file started: {file_path}")
            print(f" _protocol_dict state before load: {len(self._protocol_dict.get('processes', []))} processes")
            
            with open(file_path, 'r', encoding='utf-8') as f:
                loaded_data = json.load(f)
            
            print(f" Data loaded from file: {len(loaded_data.get('processes', []))} processes")
            
            # Extract grid name mapping (copy only, do not pop)
            grid_name_mapping = loaded_data.get('grid_name_mapping', {})
            if grid_name_mapping:
                print(f" Grid name mapping found: {grid_name_mapping}")
                # Convert Source ID inside target to Source Desc
                loaded_data = self._convert_target_source_ids_to_descs(loaded_data, grid_name_mapping)
                # Keep grid_name_mapping in protocol_dict (for later use)
                # Do not remove with pop
            
            # Assign directly to _protocol_dict
            self._protocol_dict = loaded_data
            
            # Auto-assign sort_order to existing data without it (backward compatibility)
            self._ensure_sort_orders()
            
            print(f" _protocol_dict state after assignment: {len(self._protocol_dict.get('processes', []))} processes")
            
            self._current_file_path = file_path
            self.data_changed.emit()
            print(f" [DEBUG] File loaded successfully: {file_path}")
            return True, grid_name_mapping
            
        except Exception as e:
            print(f" [DEBUG] File load error: {e}")
            import traceback
            traceback.print_exc()
            return False, {}
    
    def save_to_file(self, file_path: str, grid_name_mapping: dict = None) -> bool:
        """Save protocol data to file."""
        try:
            # Prepare data for saving
            save_data = self._protocol_dict.copy()
            
            # If grid name mapping exists, convert Source ID in target to Source Desc
            if grid_name_mapping:
                save_data = self._convert_target_source_ids_to_descs(save_data, grid_name_mapping)
                save_data = {
                    "grid_name_mapping": grid_name_mapping,
                    **save_data
                }
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, indent=2, ensure_ascii=False)
            
            self._current_file_path = file_path
            print(f" [DEBUG] File saved successfully: {file_path}")
            if grid_name_mapping:
                print(f" [DEBUG] Grid name mapping included: {grid_name_mapping}")
            return True
            
        except Exception as e:
            print(f" [DEBUG] File save error: {e}")
            return False
    
    def get_current_file_path(self) -> Optional[str]:
        """Return current file path."""
        return self._current_file_path 
    
    def _convert_target_source_ids_to_descs(self, protocol_dict: dict, grid_name_mapping: dict) -> dict:
        """Convert Source ID inside target to Source Desc."""
        try:
            # Extract SOURCE group mapping (source_id -> source_desc)
            source_mapping = {}
            for group_name in ['SOURCE', 'SOURCES']:
                if group_name in grid_name_mapping:
                    source_mapping.update(grid_name_mapping[group_name])
            
            if not source_mapping:
                return protocol_dict
            
            # Create reverse mapping (case-insensitive): SOURCE6 -> source6 -> DIW
            id_to_desc = {}
            for source_id, source_desc in source_mapping.items():
                # Also supports uppercase format like SOURCE6, SOURCE2
                id_to_desc[source_id.lower()] = source_desc
                id_to_desc[source_id.upper()] = source_desc
                # Also supports SOURCE6 -> SOURCE6 format
                if source_id.lower().startswith('source'):
                    upper_id = source_id.upper()
                    id_to_desc[upper_id] = source_desc
            
            # Iterate over processes
            processes = protocol_dict.get('processes', [])
            for process in processes:
                orders = process.get('orders', [])
                for order in orders:
                    target = order.get('target', {})
                    if not target or target == "none":
                        continue
                    
                    # Handle SOURCE/SOURCES group
                    for group_name in ['SOURCE', 'SOURCES']:
                        if group_name in target:
                            source_group = target[group_name]
                            converted_group = {}
                            
                            for source_name, positions in source_group.items():
                                # Convert Source ID to Source Desc
                                source_key = source_name.lower()
                                if source_key in id_to_desc:
                                    converted_name = id_to_desc[source_key]
                                    print(f" [DEBUG] Target conversion: {source_name} -> {converted_name}")
                                else:
                                    # Use as-is if no mapping exists
                                    converted_name = source_name
                                
                                converted_group[converted_name] = positions
                            
                            target[group_name] = converted_group
            
            print(f" [DEBUG] Target Source ID -> Source Desc conversion complete")
            return protocol_dict
            
        except Exception as e:
            print(f" [DEBUG] Target conversion error: {e}")
            import traceback
            traceback.print_exc()
            return protocol_dict
    
    # ===== Unified CRUD methods =====
    
    def delete_process_by_name(self, process_name: str) -> bool:
        """Delete process by name (for TreeView integration)."""
        try:
            print(f" [DEBUG] ProtocolModel.delete_process_by_name started: {process_name}")
            original_length = len(self._protocol_dict["processes"])
            self._protocol_dict["processes"] = [
                p for p in self._protocol_dict["processes"] 
                if p["name"] != process_name
            ]
            
            if len(self._protocol_dict["processes"]) < original_length:
                print(f" [DEBUG] Process deleted successfully: {process_name}")
                self.process_removed.emit(process_name)
                self.data_changed.emit()
                return True
            else:
                print(f" [DEBUG] Process deletion failed: {process_name} not found")
                return False
        except Exception as e:
            print(f" [DEBUG] Process removal error: {e}")
            return False
    
    def delete_order_by_process_and_index(self, process_name: str, order_index: int) -> bool:
        """Delete order by process name and index (for TreeView integration)."""
        try:
            print(f" [DEBUG] ProtocolModel.delete_order_by_process_and_index started: {process_name}, {order_index}")
            process = self.get_process_by_name(process_name)
            if process and 0 <= order_index < len(process["orders"]):
                removed_order = process["orders"].pop(order_index)
                print(f" [DEBUG] Order deleted successfully: {process_name}, {order_index}")
                self.order_removed.emit(process_name, removed_order.get("action", ""))
                self.data_changed.emit()
                return True
            else:
                print(f" [DEBUG] Order deletion failed: process or index not found")
                return False
        except Exception as e:
            print(f" [DEBUG] Order removal error: {e}")
            return False
    
    def add_process_at_position(self, process_name: str, description: str = "", position: int = -1) -> bool:
        """Add process at specified position (for TreeView integration)."""
        try:
            print(f" [DEBUG] ProtocolModel.add_process_at_position started: {process_name}, position: {position}")
            
            # Create new process
            new_process = {
                "name": process_name,
                "description": description,
                "sort_order": 0,
                "orders": []
            }
            
            if position == -1 or position >= len(self._protocol_dict["processes"]):
                # Append to the end
                new_process["sort_order"] = self._get_next_sort_order()
                self._protocol_dict["processes"].append(new_process)
                print(f" Appended at end")
            else:
                # Insert at specified position and reassign sort_order
                self._protocol_dict["processes"].insert(position, new_process)
                self._reassign_sort_orders()
                print(f" Inserted at position {position}")
            
            print(f" [DEBUG] Process added successfully: {process_name}")
            self.process_added.emit(process_name)
            print(f" [DEBUG] data_changed signal emit start (receivers: {self.receivers('data_changed')})")
            self.data_changed.emit()
            print(f" [DEBUG] data_changed signal emit complete")
            return True
            
        except Exception as e:
            print(f" [DEBUG] Process add error: {e}")
            return False
    
    def add_order_at_position(self, process_name: str, order_dict: Dict[str, Any], position: int = -1) -> bool:
        """Add order at specified position (for TreeView integration)."""
        try:
            print(f" [DEBUG] ProtocolModel.add_order_at_position started")
            print(f" process_name: '{process_name}'")
            print(f" order_dict: {order_dict}")
            print(f" position: {position}")
            
            process = self.get_process_by_name(process_name)
            print(f" Found process: {process}")
            
            if process:
                print(f" process['orders'] current state: {process.get('orders', [])}")
                print(f" process['orders'] length: {len(process.get('orders', []))}")
                
                if position == -1 or position >= len(process["orders"]):
                    # Append to the end
                    process["orders"].append(order_dict)
                    print(f" Appended at end")
                else:
                    # Insert at specified position
                    process["orders"].insert(position, order_dict)
                    print(f" Inserted at position {position}")
                
                print(f" process['orders'] state after add: {process.get('orders', [])}")
                print(f" [DEBUG] Order added successfully: {process_name}")
                self.order_added.emit(process_name, order_dict.get("action", ""))
                self.data_changed.emit()
                return True
            else:
                print(f" [DEBUG] Order add failed: process {process_name} not found")
                print(f" [DEBUG] Current process list:")
                for i, proc in enumerate(self._protocol_dict.get('processes', [])):
                    print(f"   - {i}: {proc.get('name', 'Unknown')}")
                return False
                
        except Exception as e:
            print(f" [DEBUG] Order add error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def update_process_name(self, old_name: str, new_name: str) -> bool:
        """Rename process (for TreeView integration)."""
        try:
            print(f" [DEBUG] ProtocolModel.update_process_name started: {old_name} → {new_name}")
            
            process = self.get_process_by_name(old_name)
            if process:
                process["name"] = new_name
                print(f" [DEBUG] Process name changed successfully: {old_name} → {new_name}")
                self.data_changed.emit()
                return True
            else:
                print(f" [DEBUG] Process name change failed: {old_name} not found")
                return False
                
        except Exception as e:
            print(f" [DEBUG] Process name change error: {e}")
            return False
    
    def copy_order_to_process(self, source_process_name: str, source_order_index: int, target_process_name: str, target_position: int = -1) -> bool:
        """Copy order to another process (for TreeView integration)."""
        try:
            print(f" [DEBUG] ProtocolModel.copy_order_to_process started: {source_process_name}[{source_order_index}] → {target_process_name}[{target_position}]")
            
            source_process = self.get_process_by_name(source_process_name)
            target_process = self.get_process_by_name(target_process_name)
            
            if source_process and target_process and 0 <= source_order_index < len(source_process["orders"]):
                # Copy order
                copied_order = source_process["orders"][source_order_index].copy()
                
                # Generate name field in 'Order_number' format
                import re
                target_orders = target_process.get("orders", [])
                max_order_num = 0
                
                # Extract numbers from orders whose name starts with 'Order_'
                for order in target_orders:
                    order_name = order.get('name', '')
                    if order_name:
                        match = re.match(r'^Order_(\d+)$', order_name)
                        if match:
                            order_num = int(match.group(1))
                            if order_num > max_order_num:
                                max_order_num = order_num
                
                # Generate new order name with next number (3-digit format)
                new_order_name = f"Order_{max_order_num + 1:03d}"
                copied_order["name"] = new_order_name
                
                # Add to target process
                if target_position == -1 or target_position >= len(target_process["orders"]):
                    target_process["orders"].append(copied_order)
                    print(f" Appended at end (name: {new_order_name})")
                else:
                    target_process["orders"].insert(target_position, copied_order)
                    print(f" Inserted at position {target_position} (name: {new_order_name})")
                
                print(f" [DEBUG] Order copied successfully: {source_process_name}[{source_order_index}] → {target_process_name} (name: {new_order_name})")
                self.order_added.emit(target_process_name, copied_order.get("action", ""))
                self.data_changed.emit()
                return True
            else:
                print(f" [DEBUG] Order copy failed: source or target process/index not found")
                return False
                
        except Exception as e:
            print(f" [DEBUG] Order copy error: {e}")
            return False
    
    def update_order(self, process_name: str, order_index: int, order_data: Dict[str, Any]) -> bool:
        """Update an order."""
        try:
            print(f" [DEBUG] ProtocolModel.update_order started: {process_name}, {order_index}")
            print(f" Received order_data: {order_data}")
            print(f" order_data['action']: {order_data.get('action')}")
            print(f" order_data['amount']: {order_data.get('amount')}")
            print(f" order_data['time']: {order_data.get('time')}")
            if 'time' in order_data and isinstance(order_data['time'], dict):
                print(f" order_data['time']['value']: {order_data['time'].get('value')}")
                print(f" order_data['time']['unit']: {order_data['time'].get('unit')}")
            
            process = self.get_process_by_name(process_name)
            if not process:
                print(f" [DEBUG] Process not found: {process_name}")
                return False
            
            if order_index < 0 or order_index >= len(process.get("orders", [])):
                print(f" [DEBUG] Order index out of range: {order_index}")
                return False
            
            old_order = process["orders"][order_index]
            print(f" Existing order: {old_order}")
            
            process["orders"][order_index] = order_data.copy()
            
            updated_order = process["orders"][order_index]
            print(f" Updated order: {updated_order}")
            print(f" Updated order['time']: {updated_order.get('time')}")
            
            print(f" [DEBUG] Order updated successfully: {process_name}, {order_index}")
            self.data_changed.emit()
            return True
            
        except Exception as e:
            print(f" [DEBUG] Error during order update: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def move_order_within_process(self, process_name: str, source_index: int, target_index: int) -> bool:
        """Move an order within the same process."""
        try:
            print(f" [DEBUG] ProtocolModel.move_order_within_process started: {process_name}, {source_index} → {target_index}")
            
            process = self.get_process_by_name(process_name)
            if not process:
                print(f" [DEBUG] Process not found: {process_name}")
                return False
            
            orders = process.get("orders", [])
            if not (0 <= source_index < len(orders) and 0 <= target_index < len(orders)):
                print(f" [DEBUG] Index out of range: source={source_index}, target={target_index}, length={len(orders)}")
                return False
            
            # Ignore if same position
            if source_index == target_index:
                return True
            
            # Move order
            order = orders.pop(source_index)
            
            # Adjust target index (if source is before target, index decreases by one)
            if source_index < target_index:
                target_index -= 1
            
            orders.insert(target_index, order)
            
            print(f" [DEBUG] Order moved successfully: {process_name}, {source_index} → {target_index}")
            self.data_changed.emit()
            return True
            
        except Exception as e:
            print(f" [DEBUG] Order move error: {e}")
            import traceback
            traceback.print_exc()
            return False 

    def move_process(self, process_name: str, direction: int) -> bool:
        """Move a process up (-1) or down (+1)."""
        try:
            processes = self._protocol_dict.get('processes', [])
            current_idx = None
            for i, p in enumerate(processes):
                if p.get('name') == process_name:
                    current_idx = i
                    break
            
            if current_idx is None:
                print(f" [DEBUG] Process not found: {process_name}")
                return False
            
            target_idx = current_idx + direction
            if target_idx < 0 or target_idx >= len(processes):
                return False
            
            processes[current_idx], processes[target_idx] = processes[target_idx], processes[current_idx]
            self._reassign_sort_orders()
            
            print(f" [DEBUG] Process moved successfully: {process_name}, {current_idx} → {target_idx}")
            self.data_changed.emit()
            return True
            
        except Exception as e:
            print(f" [DEBUG] Process move error: {e}")
            import traceback
            traceback.print_exc()
            return False

    def copy_process(self, original_process_name: str, new_process_name: str) -> bool:
        """Copy a process."""
        try:
            print(f" [DEBUG] ProtocolModel.copy_process started: {original_process_name} → {new_process_name}")
            
            # Find source process
            original_process = self.get_process_by_name(original_process_name)
            if not original_process:
                print(f" [DEBUG] Source process not found: {original_process_name}")
                return False
            
            # Create new process data (deep copy)
            import copy
            new_process = copy.deepcopy(original_process)
            new_process["name"] = new_process_name
            new_process["sort_order"] = self._get_next_sort_order()
            
            # Add to process list
            self._protocol_dict["processes"].append(new_process)
            
            print(f" [DEBUG] Process copied successfully: {original_process_name} → {new_process_name}")
            self.process_added.emit(new_process_name)
            self.data_changed.emit()
            return True
            
        except Exception as e:
            print(f" [DEBUG] Error during process copy: {e}")
            import traceback
            traceback.print_exc()
            return False 