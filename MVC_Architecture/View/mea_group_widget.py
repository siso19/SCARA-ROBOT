from typing import List, Tuple, Dict, Any
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QLabel, QWidget
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIntValidator
from views.base_group_widget import BaseGroupWidget
from tip_grid import TIPGrid
from models.mea_stack_manager import MEAStackManager
from utils.mea_height_calculator import MEAHeightCalculator


class MEAGroupWidget(BaseGroupWidget):
    """MEA Group Widget (with Stack functionality)"""
    
    stack_count_changed = Signal(str, int)  # location, count
    grid_name_changed = Signal(str, str, str)  # group name, original name, new name (added for compatibility)
    
    def __init__(self, group_config: Dict[str, Any] = None, parent=None):
        # Initialize stack_manager first (used in init_ui())
        self.stack_manager = MEAStackManager()
        self.height_calculator = MEAHeightCalculator(self.stack_manager)
        self.stack_inputs: Dict[str, QLineEdit] = {}
        self.stack_labels: Dict[str, QLabel] = {}
        
        # Save YAML config
        if group_config:
            self.group_config = group_config
            self.group_name = group_config.get("name", "MEA")
            self.grids_config = group_config.get("grids", [])
            self.clear_button_config = group_config.get("clear_button", {})
        else:
            # Default config (backward compatibility)
            self.group_config = {}
            self.group_name = "MEA"
            self.grids_config = [
                {"name": "MEA1", "rows": 8, "cols": 2, "circle_scale": 2.0, "position": [13, 18]},
                {"name": "MEA2", "rows": 8, "cols": 2, "circle_scale": 2.0, "position": [13, 20]},
                {"name": "MEA3", "rows": 8, "cols": 2, "circle_scale": 2.0, "position": [13, 23]}
            ]
            self.clear_button_config = {"enabled": True, "text": "✕", "size": [20, 20], "style": "red_circle"}
        
        # Initialize BaseGroupWidget (init_ui() is called at this point)
        super().__init__(self.group_name, parent)
    
    def init_ui(self):
        """Initialize UI - dynamically created based on YAML config."""
        layout = QVBoxLayout(self)
        
        # Set common margins and spacing
        margins = self.group_config.get("margins", [10, 10, 10, 10]) if self.group_config else [10, 10, 10, 10]
        spacing = self.group_config.get("spacing", 15) if self.group_config else 15
        layout.setContentsMargins(*margins)
        layout.setSpacing(spacing)
        
        # Create MEA grids based on YAML config
        self._create_grids()
        
        # Place grids according to layout type
        self._arrange_grids(layout)
        
        # Add top spacing
        layout.addStretch()
        
        # Create clear button
        if self.clear_button_config.get("enabled", True):
            self._create_clear_button(layout)
    
    def _create_grids(self):
        """Create grid widgets based on YAML config."""
        for grid_config in self.grids_config:
            name = grid_config["name"]
            container = self._create_mea_container(name, grid_config)
            self.grid_widgets[name] = container
    
    def _arrange_grids(self, main_layout):
        """Arrange grids according to layout type."""
        from PySide6.QtWidgets import QGridLayout
        
        layout_type = self.group_config.get("layout", "horizontal") if self.group_config else "horizontal"
        
        if layout_type == "grid":
            # Use grid layout (position-based placement)
            grid_layout = QGridLayout()
            grid_layout.setSpacing(self.group_config.get("grid_spacing", 20) if self.group_config else 20)
            
            # Find max position
            max_col = 0
            max_row = 0
            for grid_config in self.grids_config:
                position = grid_config.get("position", [0, 0])
                col, row = position
                max_col = max(max_col, col)
                max_row = max(max_row, row)
            
            # Place grids according to position
            # MEA group is placed directly without rotation/mirroring, same as SOURCE group
            for grid_config in self.grids_config:
                name = grid_config["name"]
                position = grid_config.get("position", [0, 0])
                col, row = position
                
                # Direct placement without rotation (same as SOURCE group)
                final_col = col
                final_row = row
                
                if name in self.grid_widgets:
                    grid_layout.addWidget(self.grid_widgets[name], final_row, final_col, 
                                        alignment=Qt.AlignCenter)
            
            main_layout.addLayout(grid_layout)
        elif layout_type == "vertical":
            # Vertical layout - placed in YAML config order
            for grid_config in self.grids_config:
                name = grid_config["name"]
                if name in self.grid_widgets:
                    main_layout.addWidget(self.grid_widgets[name])
        else:
            # Horizontal layout (default)
            mea_layout = QHBoxLayout()
            mea_layout.setContentsMargins(0, 0, 0, 0)
            mea_layout.setSpacing(20)
            
            for grid_config in self.grids_config:
                name = grid_config["name"]
                if name in self.grid_widgets:
                    mea_layout.addWidget(self.grid_widgets[name])
            
            main_layout.addLayout(mea_layout)
    
    def _create_clear_button(self, layout):
        """Create Clear button."""
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 5, 0, 5)
        button_layout.addStretch()
        
        clear_text = self.clear_button_config.get("text", "✕")
        clear_size = self.clear_button_config.get("size", [20, 20])
        
        clear_btn = QPushButton(clear_text)
        clear_btn.setFixedSize(clear_size[0], clear_size[1])
        
        # Set style
        style_type = self.clear_button_config.get("style", "red_circle")
        if style_type == "red_circle":
            clear_btn.setStyleSheet("""
                QPushButton {
                    background-color: #ff6b6b;
                    border: 1px solid #ff5252;
                    border-radius: 10px;
                    color: white;
                    font-weight: bold;
                    font-size: 18px;
                }
                QPushButton:hover {
                    background-color: #ff5252;
                }
            """)
        
        clear_btn.clicked.connect(self.clear_selections)
        button_layout.addWidget(clear_btn)
        button_layout.addStretch()
        layout.addLayout(button_layout)
    
    def _create_mea_container(self, mea_name: str, grid_config: Dict[str, Any] = None) -> QWidget:
        """Create container with MEA grid and stack input fields."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        
        # Get grid info from YAML config
        if grid_config:
            rows = grid_config.get("rows", 8)
            cols = grid_config.get("cols", 2)
            circle_scale = grid_config.get("circle_scale", 2.0)
        else:
            # Default values (backward compatibility)
            rows = 8
            cols = 2
            circle_scale = 2.0
        
        # Grid widget
        # 90-degree rotation: swap rows and cols (same as mea-measure)
        # TIPGrid(grid_width, grid_height): pass rows as grid_width, cols as grid_height
        grid_widget = TIPGrid(mea_name, rows, cols, circle_scale=circle_scale, group_name=self.group_name)
        layout.addWidget(grid_widget)
        
        # Store grid widget reference in container (used in setup_connections)
        container.grid_widget = grid_widget
        
        # Layout containing name and stack input (center-aligned)
        name_stack_layout = QHBoxLayout()
        name_stack_layout.setContentsMargins(0, 0, 0, 0)
        name_stack_layout.setSpacing(5)
        
        # Add left margin (for center alignment)
        name_stack_layout.addStretch()
        
        # Name label
        name_label = QLabel(mea_name)
        name_label.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        name_label.setStyleSheet("""
            QLabel {
                font-size: 18px;
                font-weight: bold;
                color: #333333;
            }
        """)
        name_stack_layout.addWidget(name_label)
        
        # Stack count input field
        location_key = mea_name.lower()
        max_count = self.stack_manager.MAX_COUNTS.get(location_key, 0)
        
        stack_input = QLineEdit("0")
        stack_input.setPlaceholderText("0")
        stack_input.setFixedWidth(40)
        stack_input.setAlignment(Qt.AlignCenter)
        stack_input.setValidator(QIntValidator(0, max_count))
        stack_input.setStyleSheet("""
            QLineEdit {
                font-size: 18px;
                font-weight: bold;
                padding: 2px;
                background-color: #f8f8f8;
                border: 1px solid #cccccc;
                border-radius: 3px;
            }
            QLineEdit:focus {
                border: 1px solid #0078d4;
                background-color: white;
            }
        """)
        # Connect both textChanged and editingFinished (update on Enter/focus change too)
        stack_input.textChanged.connect(
            lambda text, loc=location_key: self._on_stack_count_changed(loc, text)
        )
        stack_input.editingFinished.connect(
            lambda loc=location_key: self._on_stack_count_finished(loc)
        )
        self.stack_inputs[location_key] = stack_input
        name_stack_layout.addWidget(stack_input)
        
        # Display label (current count / max count)
        stack_label = QLabel(f"/ {max_count}")
        stack_label.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        stack_label.setStyleSheet("""
            QLabel {
                font-size: 18px;
                font-weight: bold;
                color: #666666;
            }
        """)
        self.stack_labels[location_key] = stack_label
        name_stack_layout.addWidget(stack_label)
        
        # Add right margin (for center alignment)
        name_stack_layout.addStretch()
        layout.addLayout(name_stack_layout)
        
        return container
    
    def _on_stack_count_changed(self, location: str, text: str):
        """Called when stack count changes (real-time update)."""
        try:
            count = int(text) if text else 0
            if self.stack_manager.set_stack_count(location, count):
                self._update_stack_display(location)
                self.stack_count_changed.emit(location, count)
        except ValueError:
            pass
    
    def _on_stack_count_finished(self, location: str):
        """Called when stack count input is complete (Enter/focus change)."""
        try:
            if location in self.stack_inputs:
                text = self.stack_inputs[location].text()
                count = int(text) if text else 0
                # Check max count
                max_count = self.stack_manager.MAX_COUNTS.get(location, 0)
                if count < 0 or count > max_count:
                    # Restore previous value if invalid
                    count = self.stack_manager.get_stack_count(location)
                    self.stack_inputs[location].setText(str(count))
                elif self.stack_manager.set_stack_count(location, count):
                    self._update_stack_display(location)
                    self.stack_count_changed.emit(location, count)
        except ValueError:
            pass
    
    def _update_stack_display(self, location: str):
        """Update stack display."""
        count = self.stack_manager.get_stack_count(location)
        max_count = self.stack_manager.MAX_COUNTS.get(location, 0)
        
        if location in self.stack_labels:
            self.stack_labels[location].setText(f"/ {max_count}")
        
        # Calculate height info (optional)
        pick_height = self.height_calculator.calculate_pick_height(location)
        if pick_height:
            # Height info can be shown as tooltip
            pass
    
    def get_stack_count(self, location: str) -> int:
        """Get stack count."""
        return self.stack_manager.get_stack_count(location)
    
    def set_stack_count(self, location: str, count: int) -> bool:
        """Set stack count (called externally)."""
        if self.stack_manager.set_stack_count(location, count):
            if location in self.stack_inputs:
                self.stack_inputs[location].setText(str(count))
            self._update_stack_display(location)
            return True
        return False
    
    def setup_connections(self):
        """Connect signals."""
        # Connect selection change signals for each grid
        for item_name, container in self.grid_widgets.items():
            # Get actual grid widget from container
            if hasattr(container, 'grid_widget'):
                grid_widget = container.grid_widget
                grid_widget.selection_changed.connect(
                    lambda positions, name=item_name: self._on_grid_selection_changed(name, positions)
                )
    
    def _on_grid_selection_changed(self, item_name: str, positions: List[Tuple[int, int]]):
        """Called when grid selection changes."""
        self.selection_changed.emit(self.group_name, item_name, positions)
    
    def get_all_positions(self) -> Dict[str, List[Tuple[int, int]]]:
        """Return all grid selection info (considering container structure)."""
        positions = {}
        for item_name, container in self.grid_widgets.items():
            if hasattr(container, 'grid_widget'):
                grid_widget = container.grid_widget
                positions[item_name] = grid_widget.get_selected_positions()
        return positions
    
    def set_positions(self, positions_data: Dict[str, List[Tuple[int, int]]]):
        """Set group selection info (considering container structure)."""
        for item_name, positions in positions_data.items():
            if item_name in self.grid_widgets:
                container = self.grid_widgets[item_name]
                if hasattr(container, 'grid_widget'):
                    grid_widget = container.grid_widget
                    if positions:
                        grid_widget.set_selection(positions)
                    else:
                        grid_widget.clear_selection()
    
    def clear_selections(self):
        """Clear all selections (considering container structure)."""
        for container in self.grid_widgets.values():
            if hasattr(container, 'grid_widget'):
                grid_widget = container.grid_widget
                grid_widget.clear_selection()
        self.clear_requested.emit(self.group_name)
    
    def get_all_mea_positions(self) -> Dict[str, List[Tuple[int, int]]]:
        """Return all MEA selection info."""
        return self.get_all_positions()
    
    def set_mea_positions(self, mea_data: Dict[str, List[Tuple[int, int]]]):
        """Set MEA group selection info."""
        self.set_positions(mea_data)
    
    def clear_mea_selections(self):
        """Clear MEA group selections."""
        self.clear_selections() 