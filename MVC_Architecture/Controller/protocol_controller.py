"""
Protocol Controller
MVC Controller Layer - Connects UI and Model
"""

from typing import Optional, Dict, Any
from PySide6.QtCore import QObject, Signal
from models.protocol_model import ProtocolModel
from services.grid_selection_service import GridSelectionService


class ProtocolController(QObject):
    """Protocol Controller"""
    
    # Signal definitions
    ui_update_needed = Signal()  # Emitted when UI update is needed
    error_occurred = Signal(str)  # Emitted on error
    success_message = Signal(str)  # Emitted on success
    
    def __init__(self, protocol_model: ProtocolModel, grid_service: GridSelectionService):
        super().__init__()
        self._protocol_model = protocol_model
        self._grid_service = grid_service
        self._selected_process: Optional[Dict[str, Any]] = None
        self._selected_order_index: Optional[int] = None
        
        # Connect signals
        self._connect_signals()
    
    def _connect_signals(self):
        """Connect signals."""
        # Connect model signals
        self._protocol_model.data_changed.connect(self._on_data_changed)
        self._protocol_model.process_added.connect(self._on_process_added)
        self._protocol_model.order_added.connect(self._on_order_added)
        
        # Connect grid service signals (only if grid_service exists)
        if self._grid_service:
            self._grid_service.target_updated.connect(self._on_target_updated)
    
    def load_protocol_from_file(self, file_path: str) -> tuple[bool, dict]:
        """Load protocol from file."""
        success, grid_name_mapping = self._protocol_model.load_from_file(file_path)
        if success:
            print(f"[DEBUG] Protocol loaded successfully: {file_path}")
            if grid_name_mapping:
                print(f"[DEBUG] Grid name mapping loaded: {grid_name_mapping}")
            #self.success_message.emit(f"Protocol loaded successfully: {file_path}")
        else:
            self.error_occurred.emit("Failed to load protocol.")
        return success, grid_name_mapping
    
    def save_protocol_to_file(self, file_path: str) -> bool:
        """Save protocol to file."""
        success = self._protocol_model.save_to_file(file_path)
        if success:
            #self.success_message.emit(f"Protocol saved successfully: {file_path}")
            print(f"[DEBUG] Protocol saved successfully: {file_path}")
        else:
            self.error_occurred.emit("Failed to save protocol.")
        return success
    
    def add_process(self, description: str = "") -> bool:
        """Add a new process."""
        next_name = self._protocol_model.generate_next_process_name()
        success = self._protocol_model.add_process(next_name, description)
        if success:
            self.success_message.emit(f"Process '{next_name}' has been added.")
        else:
            self.error_occurred.emit("Failed to add process.")
        return success
    
    def add_process_at_position(self, description: str = "", insert_after_process: str = None) -> bool:
        """Add a new process after the specified process."""
        next_name = self._protocol_model.generate_next_process_name()
        
        if insert_after_process:
            success = self._protocol_model.insert_process_after(insert_after_process, next_name, description)
        else:
            success = self._protocol_model.add_process(next_name, description)
        
        if success:
            self.success_message.emit(f"Process '{next_name}' has been added.")
        else:
            self.error_occurred.emit("Failed to add process.")
        return success
    
    def add_order(self, action: str, amount: int, time_value: int, time_unit: str, target_data: dict = None) -> bool:
        """Add a new order."""
        print(f"[DEBUG] Controller: add_order called")
        print(f"[DEBUG] Controller: Action={action}, Amount={amount}, Time={time_value} {time_unit}")
        
        # Add to the last process
        last_process = self._protocol_model.get_last_process()
        if not last_process:
            self.error_occurred.emit("No processes found. Please add a process first.")
            return False
        
        if target_data is not None:
            target = target_data
            print(f"[DEBUG] Controller: Target info from UI: {target}")
        elif self._grid_service:
            target = self._grid_service.get_target_for_order()
            print(f"[DEBUG] Controller: Target info from Grid Service: {target}")
        else:
            target = {}
            print(f"[DEBUG] Controller: No Grid Service - using empty target")
        
        order_data = {
            "action": action,
            "amount": amount,
            "time": {"value": time_value, "unit": time_unit},
            "target": target
        }
        print(f"[DEBUG] Controller: Created order data: {order_data}")
        
        success = self._protocol_model.add_order(last_process["name"], order_data)
        if success:
            print(f"[DEBUG] Controller: Order '{action}' added successfully")
            self.success_message.emit(f"Order '{action}' has been added.")
        else:
            print("[DEBUG] Controller: Order add failed")
            self.error_occurred.emit("Failed to add order.")
        return success
    
    def add_order_at_position(self, action: str, amount: int, time_value: int, time_unit: str, 
                             target_data: dict = None, process_name: str = None, order_index: int = None) -> bool:
        """Add a new order at the specified position."""
        print(f"[DEBUG] Controller: add_order_at_position called")
        print(f"[DEBUG] Controller: Action={action}, Amount={amount}, Time={time_value} {time_unit}")
        print(f"[DEBUG] Controller: Process={process_name}, Order Index={order_index}")
        
        # Determine target process
        if process_name:
            target_process = self._protocol_model.get_process_by_name(process_name)
            if not target_process:
                self.error_occurred.emit(f"Process '{process_name}' not found.")
                return False
        else:
            # Use the last process
            target_process = self._protocol_model.get_last_process()
            if not target_process:
                self.error_occurred.emit("No processes found. Please add a process first.")
                return False
            process_name = target_process["name"]
        
        # Determine target info (UI-provided data takes priority)
        if target_data is not None:
            target = target_data
            print(f"[DEBUG] Controller: Target info from UI: {target}")
        elif self._grid_service:
            target = self._grid_service.get_target_for_order()
            print(f"[DEBUG] Controller: Target info from Grid Service: {target}")
        else:
            target = {}
            print(f"[DEBUG] Controller: No Grid Service - using empty target")
        
        order_data = {
            "action": action,
            "amount": amount,
            "time": {"value": time_value, "unit": time_unit},
            "target": target
        }
        print(f"[DEBUG] Controller: Created order data: {order_data}")
        
        if order_index is not None:
            success = self._protocol_model.insert_order(process_name, order_index, order_data)
        else:
            success = self._protocol_model.add_order(process_name, order_data)
        
        if success:
            print(f"[DEBUG] Controller: Order '{action}' added successfully")
            self.success_message.emit(f"Order '{action}' has been added.")
        else:
            print("[DEBUG] Controller: Order add failed")
            self.error_occurred.emit("Failed to add order.")
        return success
    
    def update_selected_order(self, action: str, amount: int, time_value: int, time_unit: str, target_data: dict = None) -> bool:
        """Update the selected order."""
        print(f"[DEBUG] Controller: update_selected_order called")
        print(f"[DEBUG] Controller: Selected process: {self._selected_process['name'] if self._selected_process else 'None'}")
        print(f"[DEBUG] Controller: Selected order index: {self._selected_order_index}")
        
        if not self._selected_process or self._selected_order_index is None:
            print("[DEBUG] Controller: No order selected for update")
            self.error_occurred.emit("No order selected for update.")
            return False
        
        # Determine target info (UI-provided data takes priority)
        if target_data is not None:
            target = target_data
            print(f"[DEBUG] Controller: Target info from UI: {target}")
        else:
            target = self.get_target_for_order()
            print(f"[DEBUG] Controller: Target info from Grid Service: {target}")
        
        # Build order data
        order_data = {
            "action": action,
            "amount": amount,
            "time": {"value": time_value, "unit": time_unit},
            "target": target
        }
        print(f"[DEBUG] Controller: Created order data: {order_data}")
        
        success = self._protocol_model.update_order(
            self._selected_process["name"], 
            self._selected_order_index, 
            order_data  # Convert OrderData to dict
        )
        print(f"[DEBUG] Controller: Model update result: {success}")
        
        if success:
            print(f"[DEBUG] Controller: Order '{action}' updated successfully")
            #self.success_message.emit(f"Order '{action}' has been updated.")
        else:
            print("[DEBUG] Controller: Order update failed")
            self.error_occurred.emit("Failed to update order.")
        return success
    
    def select_order_by_index(self, process_name: str, order_index: int):
        """Select order by index (exact selection)."""
        print(f"[DEBUG] Controller: select_order_by_index called - Process: {process_name}, Index: {order_index}")
        
        # Find process
        process = self._protocol_model.get_process_by_name(process_name)
        if not process:
            print(f"[DEBUG] Controller: Process '{process_name}' not found")
            return False
        
        # Validate index range (dict-based)
        if 0 <= order_index < len(process["orders"]):
            self._selected_process = process
            self._selected_order_index = order_index
            print(f"[DEBUG] Controller: Order selected - Process: {process_name}, Index: {order_index}")
            return True
        else:
            print(f"[DEBUG] Controller: Invalid order index - Index: {order_index}, Max: {len(process['orders'])-1}")
            return False

    def select_order_for_update(self, process_name: str, order_data: dict):
        """Select order for update (fallback method)."""
        print(f"[DEBUG] Controller: select_order_for_update called (fallback)")
        
        # Find process
        process = self._protocol_model.get_process_by_name(process_name)
        if not process:
            return False
        
        # Find order index (dict-based)
        order_index = None
        for i, order in enumerate(process["orders"]):
            if (order["action"] == order_data.get("action") and
                order["amount"] == order_data.get("amount") and
                order["time"]["value"] == order_data.get("time", {}).get("value")):
                order_index = i
                break
        
        if order_index is not None:
            self._selected_process = process
            self._selected_order_index = order_index
            print(f"[DEBUG] Controller: Fallback order selected - Index: {order_index}")
            return True
        
        return False
    
    def select_process(self, process_name: str):
        """Select a process."""
        self._selected_process = self._protocol_model.get_process_by_name(process_name)
        self._selected_order_index = None
        self.ui_update_needed.emit()
    
    def select_order(self, process_name: str, order_index: int):
        """Select an order."""
        process = self._protocol_model.get_process_by_name(process_name)
        if process and 0 <= order_index < len(process["orders"]):
            self._selected_process = process
            self._selected_order_index = order_index
            
            # Set selected order target info to grid service (dict-based)
            order = process["orders"][order_index]
            if self._grid_service:
                self._grid_service.set_target_from_order(order["target"])
            
            self.ui_update_needed.emit()
    
    def clear_selection(self):
        """Clear selection."""
        self._selected_process = None
        self._selected_order_index = None
        self.ui_update_needed.emit()
    
    def get_selected_process(self) -> Optional[dict]:
        """Return selected process (dict-based)."""
        return self._selected_process
    
    def get_selected_order(self) -> Optional[dict]:
        """Return selected order (dict-based)."""
        if self._selected_process and self._selected_order_index is not None:
            if 0 <= self._selected_order_index < len(self._selected_process["orders"]):
                return self._selected_process["orders"][self._selected_order_index]
        return None
    
    def get_protocol_data(self):
        """Return protocol data (dict-based)."""
        return self._protocol_model.protocol_dict
    
    def get_target_summary(self) -> str:
        """Return target summary."""
        return self._grid_service.get_target_summary()
    
    def get_target_details(self) -> str:
        """Return target details."""
        return self._grid_service.get_target_details()
    
    def clear_all_grid_selections(self):
        """Clear all grid selections."""
        self._grid_service.clear_all_selections()
    
    def update_grid_selection(self, group_name: str, item_name: str, positions):
        """Update grid selection."""
        self._grid_service.update_selection(group_name, item_name, positions)
    
    def update_grid_selection_from_ui(self, target_data):
        """Update grid selection from UI (deprecated)."""
        print(f"[DEBUG] Controller: update_grid_selection_from_ui called (deprecated): {target_data}")
        # This method is no longer used
        pass
    
    def get_target_for_order(self) -> dict:
        """Get target info of the currently selected order."""
        # Get current selections from Grid Service and convert to target format
        selections = self._grid_service.get_selections()
        
        # Remove empty groups
        target_data = {}
        for group_name, group_data in selections.items():
            if group_data:
                non_empty_items = {}
                for item_name, positions in group_data.items():
                    if positions:
                        non_empty_items[item_name] = positions
                if non_empty_items:
                    target_data[group_name] = non_empty_items
        
        return target_data if target_data else "none"
    
    def get_all_selections(self):
        """Get selection info for all groups."""
        # Logic to collect selection info from each group
        # In practice, should be retrieved directly from group widgets,
        # but currently returns data managed by the grid service
        return self._grid_service.get_selections()
    
    def _on_data_changed(self):
        """Called when data changes."""
        self.ui_update_needed.emit()
    
    def _on_process_added(self, process_name: str):
        """Called when a process is added."""
        print(f"Process added: {process_name}")
    
    def _on_order_added(self, process_name: str, action: str):
        """Called when an order is added."""
        print(f"Order added: {process_name} - {action}")
    
    def _on_target_updated(self, target_info: Dict[str, Any]):
        """Called when target is updated."""
        print(f"Target updated: {target_info}")
        self.ui_update_needed.emit() 