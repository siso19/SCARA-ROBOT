from typing import List, Tuple, Dict
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QPushButton
from views.base_group_widget import BaseGroupWidget
from tip_grid import TIPGrid


class JIGGroupWidget(BaseGroupWidget):
    """JIG Group Widget"""
    
    def __init__(self, parent=None):
        super().__init__("JIG", parent)
    
    def init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(15)
        
        # Create JIG grid (8 rows x 2 cols for consistency with Group2)
        self.grid_widgets["JIG1"] = TIPGrid("JIG1", 8, 2, circle_scale=2.0, group_name="JIG")
        
        # Center JIG grid horizontally
        jig_layout = QHBoxLayout()
        jig_layout.setContentsMargins(0, 0, 0, 0)
        jig_layout.addStretch()  # Left padding
        jig_layout.addWidget(self.grid_widgets["JIG1"])  # Place JIG grid in center
        jig_layout.addStretch()  # Right padding
        
        layout.addLayout(jig_layout)
        
        # Add top spacing
        layout.addStretch()
        
        # JIG group clear button (small circular button)
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 5, 0, 5)
        button_layout.setSpacing(0)
        button_layout.addStretch()  # Left padding
        
        clear_jig_btn = QPushButton("✕")
        clear_jig_btn.setFixedSize(20, 20)
        clear_jig_btn.setStyleSheet("""
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
        clear_jig_btn.clicked.connect(self.clear_selections)
        button_layout.addWidget(clear_jig_btn)
        
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
    
    def get_all_jig_positions(self) -> Dict[str, List[Tuple[int, int]]]:
        """Return all JIG selection data."""
        return self.get_all_positions()
    
    def set_jig_positions(self, jig_data: Dict[str, List[Tuple[int, int]]]):
        """Set JIG group selection data."""
        self.set_positions(jig_data)
    
    def clear_jig_selections(self):
        """Clear JIG group selections."""
        self.clear_selections() 