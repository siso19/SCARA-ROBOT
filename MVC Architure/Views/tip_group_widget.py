from typing import List, Tuple, Dict
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QPushButton
from views.base_group_widget import BaseGroupWidget
from tip_grid import TIPGrid


class TIPGroupWidget(BaseGroupWidget):
    """TIP Group Widget"""
    
    def __init__(self, parent=None):
        super().__init__("TIP", parent)
    
    def init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(15)
        
        # Create TIP grids
        self.grid_widgets["TIP1"] = TIPGrid("TIP1", 8, 12, circle_scale=1.0)
        self.grid_widgets["TIP2"] = TIPGrid("TIP2", 8, 12, circle_scale=1.0)
        self.grid_widgets["TIP3"] = TIPGrid("TIP3", 8, 12, circle_scale=1.0)
        
        # Arrange TIP grids vertically
        layout.addWidget(self.grid_widgets["TIP1"])
        layout.addWidget(self.grid_widgets["TIP2"])
        layout.addWidget(self.grid_widgets["TIP3"])
        
        # Add top spacing
        layout.addStretch()
        
        # TIP group clear button (small circular button)
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 5, 0, 5)
        button_layout.setSpacing(0)
        button_layout.addStretch()  # Left padding
        
        clear_tip_btn = QPushButton("✕")
        clear_tip_btn.setFixedSize(20, 20)
        clear_tip_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff6b6b;
                border: 1px solid #ff5252;
                border-radius: 10px;
                color: white;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #ff5252;
                border-color: #ff1744;
            }
            QPushButton:pressed {
                background-color: #d32f2f;
            }
        """)
        clear_tip_btn.clicked.connect(self.clear_selections)
        button_layout.addWidget(clear_tip_btn)
        
        button_layout.addStretch()  # Right padding
        layout.addLayout(button_layout)
    
    def setup_connections(self):
        """Connect signals."""
        # Connect selection change signals for each grid
        for item_name, grid_widget in self.grid_widgets.items():
            grid_widget.selection_changed.connect(
                lambda positions, name=item_name: self._on_grid_selection_changed(name, positions)
            )
    
    def _on_grid_selection_changed(self, item_name: str, positions: List[Tuple[int, int]]):
        """Called when grid selection changes."""
        self.selection_changed.emit(self.group_name, item_name, positions)
    
    def get_all_tip_positions(self) -> Dict[str, List[Tuple[int, int]]]:
        """Return all TIP selection data."""
        return self.get_all_positions()
    
    def set_tip_positions(self, tip_data: Dict[str, List[Tuple[int, int]]]):
        """Set TIP group selection data."""
        self.set_positions(tip_data)
    
    def clear_tip_selections(self):
        """Clear TIP group selections."""
        self.clear_selections() 