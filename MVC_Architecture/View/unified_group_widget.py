import yaml
import os
import re
from typing import List, Tuple, Dict, Any, Optional
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QPushButton, QWidget, QGroupBox, QGridLayout,
    QLineEdit, QLabel
)
from PySide6.QtCore import Signal, Qt, QPoint
from PySide6.QtGui import QPainter, QPen, QColor, QPolygon
from views.base_group_widget import BaseGroupWidget
from tip_grid import TIPGrid
from models.mea_stack_manager import MEAStackManager
from utils.mea_height_calculator import MEAHeightCalculator
from PySide6.QtGui import QIntValidator


class ArrowWidget(QWidget):
    """Arrow widget - draws an arrow between grids."""
    
    def __init__(self, direction='right', size=2, parent=None):
        """
        Args:
            direction: arrow direction ('right', 'left', 'up', 'down')
            size: size proportional to grid count (default: 2)
            parent: parent widget
        """
        super().__init__(parent)
        self.direction = direction
        self.size = size
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)  # Pass through mouse events
        
    def paintEvent(self, event):
        """Draw arrow."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Set pen
        pen = QPen(QColor(100, 100, 100), 3, Qt.SolidLine)
        painter.setPen(pen)
        
        width = self.width()
        height = self.height()
        
        if self.direction == 'right':
            # Right arrow
            # Arrow body (horizontal line)
            start_x = 0
            end_x = width - height // 2
            mid_y = height // 2
            painter.drawLine(start_x, mid_y, end_x, mid_y)
            
            # Arrow head (triangle)
            arrow_size = height // 2
            arrow_points = QPolygon([
                QPoint(end_x, mid_y),
                QPoint(end_x - arrow_size, mid_y - arrow_size // 2),
                QPoint(end_x - arrow_size, mid_y + arrow_size // 2)
            ])
            painter.setBrush(QColor(100, 100, 100))
            painter.drawPolygon(arrow_points)
        elif self.direction == 'left':
            # Left arrow
            # Arrow body (horizontal line)
            start_x = height // 2
            end_x = width
            mid_y = height // 2
            painter.drawLine(start_x, mid_y, end_x, mid_y)
            
            # Arrow head (triangle)
            arrow_size = height // 2
            arrow_points = QPolygon([
                QPoint(start_x, mid_y),
                QPoint(start_x + arrow_size, mid_y - arrow_size // 2),
                QPoint(start_x + arrow_size, mid_y + arrow_size // 2)
            ])
            painter.setBrush(QColor(100, 100, 100))
            painter.drawPolygon(arrow_points)
        elif self.direction == 'down':
            # Down arrow
            # Arrow body (vertical line)
            start_y = 0
            end_y = height - width // 2
            mid_x = width // 2
            painter.drawLine(mid_x, start_y, mid_x, end_y)
            
            # Arrow head (triangle)
            arrow_size = width // 2
            arrow_points = QPolygon([
                QPoint(mid_x, end_y),
                QPoint(mid_x - arrow_size // 2, end_y - arrow_size),
                QPoint(mid_x + arrow_size // 2, end_y - arrow_size)
            ])
            painter.setBrush(QColor(100, 100, 100))
            painter.drawPolygon(arrow_points)
        elif self.direction == 'up':
            # Up arrow (bottom to top)
            # Arrow body (vertical line) - fixed at 100px length
            mid_x = width // 2
            arrow_length = 100  # stick length 100px
            arrow_size = width // 2  # arrow head size
            
            # Center arrow in widget, with extra space for arrow head
            center_y = height // 2
            start_y = center_y + arrow_length // 2  # start from bottom
            end_y = center_y - arrow_length // 2  # top end
            
            # Adjust so arrow head stays within widget bounds
            if end_y - arrow_size < 0:
                # Shift down if top boundary exceeded
                offset = arrow_size - end_y + 5
                start_y += offset
                end_y += offset
            
            painter.drawLine(mid_x, start_y, mid_x, end_y)
            
            # Arrow head (triangle) - at top end
            arrow_points = QPolygon([
                QPoint(mid_x, end_y),  # top end (arrow head)
                QPoint(mid_x - arrow_size // 2, end_y + arrow_size),
                QPoint(mid_x + arrow_size // 2, end_y + arrow_size)
            ])
            painter.setBrush(QColor(100, 100, 100))
            painter.drawPolygon(arrow_points)


class UnifiedGroupWidget(BaseGroupWidget):
    """Unified group widget - dynamically created via YAML config."""
    
    # Volume update signal
    volume_updated_signal = Signal()
    
    # Add grid name change signal
    grid_name_changed = Signal(str, str, str)  # group name, original name, new name
    
    def __init__(self, group_config: Dict[str, Any], parent=None):
        # For JIG group: initialize MEA stack management first (used in init_ui())
        self.group_config = group_config
        self.group_name = group_config.get("name", "Unknown")
        
        if self.group_name == "JIG":
            self.stack_manager = MEAStackManager()
            self.height_calculator = MEAHeightCalculator(self.stack_manager)
            self.stack_inputs: Dict[str, Any] = {}
            self.stack_labels: Dict[str, Any] = {}
        else:
            self.stack_manager = None
            self.height_calculator = None
            self.stack_inputs = {}
            self.stack_labels = {}
        
        # Initialize remaining settings
        self.display_name = group_config.get("display_name", self.group_name)
        self.description = group_config.get("description", "")
        self.layout_type = group_config.get("layout", "vertical")
        self.grids_config = group_config.get("grids", [])
        self.clear_button_config = group_config.get("clear_button", {})
        
        # Tube Interface reference (set later)
        self.tube_interface = None
        
        super().__init__(self.group_name, parent)
    
    def init_ui(self):
        """Initialize UI - dynamically created based on YAML config."""
        layout = QVBoxLayout(self)
        
        # Set common margins and spacing
        margins = self.group_config.get("margins", [10, 10, 10, 10])
        spacing = self.group_config.get("spacing", 15)
        layout.setContentsMargins(*margins)
        layout.setSpacing(spacing)
        
        # Create grids based on config
        self._create_grids()
        
        # Place grids according to layout type
        self._arrange_grids(layout)
        
        # Add top spacing
        layout.addStretch()
        
        # Create clear button
        if self.clear_button_config.get("enabled", True):
            self._create_clear_button(layout)
        
        # Draw arrow as overlay (after layout completion)
        if hasattr(self, '_arrow_info') and self._arrow_info:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, self._draw_arrow_overlay)  # draw arrow after layout completes
    
    def _create_grids(self):
        """Create grid widgets based on YAML config."""
        for grid_config in self.grids_config:
            name = grid_config["name"]
            # Use default if rows, cols not specified
            rows = grid_config.get("rows", 1)
            cols = grid_config.get("cols", 1)
            circle_scale = grid_config.get("circle_scale", 1.0)
            
            # Create TIPGrid instance (pass group name)
            grid_widget = TIPGrid(name, rows, cols, circle_scale=circle_scale, group_name=self.group_name)
            
            # Create container to display grid name
            grid_container = self._create_grid_with_label(grid_widget, name)
            self.grid_widgets[name] = grid_container
    
    def _create_grid_with_label(self, grid_widget, name):
        """Create container with grid and name display/edit fields."""
        from PySide6.QtCore import Qt
        
        container = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        
        # Add grid widget
        layout.addWidget(grid_widget)
        
        # Editable field for SOURCES/SOURCE group only; otherwise read-only label
        if self.group_name in ["SOURCES", "SOURCE"]:
            # Source ID: lowercase original grid name (unique identifier, immutable)
            source_id = name.lower()
            
            # Source Desc: user-editable name (initial value is grid name)
            source_desc = name
            
            # Add name edit field (below) - for Source Desc editing
            name_edit = QLineEdit(source_desc)
            name_edit.setAlignment(Qt.AlignCenter)
            name_edit.setStyleSheet("""
                QLineEdit {
                    font-size: 13px;
                    font-weight: bold;
                    color: #666666;
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
            
            # Connect name change signal (Source Desc - applied on Enter or focus loss)
            name_edit.returnPressed.connect(lambda: self._on_source_desc_entered(name))
            name_edit.editingFinished.connect(lambda: self._on_source_desc_editing_finished(name))
            
            layout.addWidget(name_edit)
            container.name_edit = name_edit
            
            # Add volume input field (below name field)
            volume_layout = QHBoxLayout()
            volume_layout.setContentsMargins(0, 0, 0, 0)
            volume_layout.setSpacing(2)
            
            volume_edit = QLineEdit()
            volume_edit.setPlaceholderText("0.0")
            volume_edit.setAlignment(Qt.AlignCenter)
            volume_edit.setStyleSheet("""
                QLineEdit {
                    font-size: 13px;
                    font-weight: bold;
                    color: #333333;
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
            
            # Connect volume change signal (applied on Enter or focus loss)
            volume_edit.returnPressed.connect(lambda: self._on_volume_entered(name))
            volume_edit.editingFinished.connect(lambda: self._on_volume_editing_finished(name))
            
            # Add mL label
            volume_label = QLabel("mL")
            volume_label.setAlignment(Qt.AlignCenter)
            volume_label.setStyleSheet("""
                QLabel {
                    font-size: 13px;
                    font-weight: bold;
                    color: #666666;
                    padding: 2px;
                    background-color: transparent;
                }
            """)
            
            volume_layout.addStretch()
            volume_layout.addWidget(volume_edit)
            volume_layout.addWidget(volume_label)
            volume_layout.addStretch()
            
            layout.addLayout(volume_layout)
            container.volume_edit = volume_edit
            container.source_id = source_id  # Source ID (unique identifier, immutable)
            container.source_desc = source_desc  # Source Desc (user-editable)
            container.table_item_name = source_id  # table_item_name equals source_id
        elif self.group_name == "JIG":
            # For JIG group: add MEA stack management (same as MEA1-3)
            # Layout containing name and stack input (center-aligned)
            name_stack_layout = QHBoxLayout()
            name_stack_layout.setContentsMargins(0, 0, 0, 0)
            name_stack_layout.setSpacing(5)
            
            # Add left margin (for center alignment)
            name_stack_layout.addStretch()
            
            # Name label
            name_label = QLabel(name)
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
            location_key = name.lower()
            if self.stack_manager:
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
                stack_input.textChanged.connect(
                    lambda text, loc=location_key: self._on_stack_count_changed(loc, text)
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
            
            container.name_edit = None
            container.volume_edit = None
            container.table_item_name = None
        else:
            # Read-only label
            name_label = QLabel(name)
            name_label.setAlignment(Qt.AlignCenter)
            name_label.setStyleSheet("""
                QLabel {
                    font-size: 18px;
                    font-weight: bold;
                    color: #666666;
                    padding: 2px;
                    background-color: transparent;
                }
            """)
            
            layout.addWidget(name_label)
            container.name_edit = None
            container.volume_edit = None
            container.table_item_name = None
        
        container.setLayout(layout)
        
        # Store reference to actual grid widget (for signal connection)
        container.grid_widget = grid_widget
        
        # Set center alignment for all group layouts
        layout.setAlignment(Qt.AlignCenter)
        
        return container
    
    def _arrange_grids(self, main_layout):
        """Arrange grids according to layout type."""
        if self.layout_type == "horizontal":
            # Horizontal placement
            grid_layout = QHBoxLayout()
            grid_layout.setSpacing(self.group_config.get("grid_spacing", 20))
            grid_layout.setAlignment(Qt.AlignCenter)
            
            # Apply center alignment to all grid containers
            for grid_container in self.grid_widgets.values():
                grid_layout.addWidget(grid_container, alignment=Qt.AlignCenter)
            
            main_layout.addLayout(grid_layout)
            main_layout.setAlignment(grid_layout, Qt.AlignHCenter | Qt.AlignVCenter)
            
        elif self.layout_type == "grid":
            # Grid placement (2D array)
            grid_layout = QGridLayout()
            grid_layout.setSpacing(self.group_config.get("grid_spacing", 20))
            
            # Calculate max grid size (for 180-degree rotation + vertical mirroring)
            max_col = max(grid_config.get("position", [0, 0])[0] for grid_config in self.grids_config)
            max_row = max(grid_config.get("position", [0, 0])[1] for grid_config in self.grids_config)
            
            if self.group_name == "SOURCE":
                print(f"[DEBUG] {self.group_name} group: direct placement without rotation:")
            else:
                print(f"[DEBUG] {self.group_name} group: 180-degree rotation + vertical mirroring applied:")
            print(f"  Max size: {max_col + 1} x {max_row + 1}")
            
            for grid_config in self.grids_config:
                name = grid_config["name"]
                position = grid_config.get("position", [0, 0])
                col, row = position  # [x, y] order correctly interpreted as [col, row]
                
                # SOURCE group: no 180-degree rotation
                if self.group_name == "SOURCE":
                    final_col = col
                    final_row = row
                    print(f"  {name}: ({col}, {row}) -> ({final_col}, {final_row}) [no rotation]")
                else:
                    # Step 1: 180-degree rotation: (col, row) -> (max_col - col, max_row - row)
                    rotated_col = max_col - col
                    rotated_row = max_row - row
                    
                    # Step 2: vertical mirroring: (rotated_col, rotated_row) -> (rotated_col, max_row - rotated_row)
                    final_col = rotated_col  # horizontal stays the same
                    final_row = max_row - rotated_row  # flip vertical only
                    
                    print(f"  {name}: ({col}, {row}) -> ({rotated_col}, {rotated_row}) -> ({final_col}, {final_row})")
                
                if name in self.grid_widgets:
                    # Apply center alignment to all grids
                    grid_layout.addWidget(self.grid_widgets[name], final_row, final_col, 
                                        alignment=Qt.AlignCenter)
            
            # For TIPS group: add arrow between TIP-TRASH and TIP1
            if self.group_name == "TIPS":
                print(f"[DEBUG] Adding arrow: TIPS group")
                # Find positions of TIP-TRASH and TIP1
                tip_trash_final_col = None
                tip_trash_final_row = None
                tip1_final_col = None
                tip1_final_row = None
                
                for grid_config in self.grids_config:
                    name = grid_config["name"]
                    position = grid_config.get("position", [0, 0])
                    col, row = position
                    
                    # Apply 180-degree rotation + vertical mirroring
                    rotated_col = max_col - col
                    rotated_row = max_row - row
                    final_col = rotated_col
                    final_row = max_row - rotated_row
                    
                    if name == "TIP-TRASH":
                        tip_trash_final_col = final_col
                        tip_trash_final_row = final_row
                        print(f"[DEBUG] TIP-TRASH position: ({col}, {row}) -> ({final_col}, {final_row})")
                    elif name == "TIP1":
                        tip1_final_col = final_col
                        tip1_final_row = final_row
                        print(f"[DEBUG] TIP1 position: ({col}, {row}) -> ({final_col}, {final_row})")
                
                print(f"[DEBUG] Position check:")
                print(f"  TIP-TRASH: col={tip_trash_final_col}, row={tip_trash_final_row}")
                print(f"  TIP1: col={tip1_final_col}, row={tip1_final_row}")
                print(f"  Same row? {tip_trash_final_row == tip1_final_row if tip_trash_final_row is not None and tip1_final_row is not None else False}")
                print(f"  Same col? {tip_trash_final_col == tip1_final_col if tip_trash_final_col is not None and tip1_final_col is not None else False}")
                print(f"  TIP1 to the right? {tip1_final_col > tip_trash_final_col if tip_trash_final_col is not None and tip1_final_col is not None else False}")
                print(f"  TIP1 below? {tip1_final_row > tip_trash_final_row if tip_trash_final_row is not None and tip1_final_row is not None else False}")
                
                # Add arrow if TIP-TRASH and TIP1 are in same row and TIP1 is to the right
                # Or if same column and TIP1 is below TIP-TRASH
                # Image shows vertical layout, so correct to: same column and TIP1 below
                # But debug shows same row, so need to verify actual layout
                # Handle both cases: same row+right or same column+below
                is_same_row = (tip_trash_final_row is not None and tip1_final_row is not None and
                              tip_trash_final_row == tip1_final_row)
                is_same_col = (tip_trash_final_col is not None and tip1_final_col is not None and
                              tip_trash_final_col == tip1_final_col)
                is_tip1_right = (tip_trash_final_col is not None and tip1_final_col is not None and
                                tip1_final_col > tip_trash_final_col)
                is_tip1_below = (tip_trash_final_row is not None and tip1_final_row is not None and
                                tip1_final_row > tip_trash_final_row)
                
                # Image shows TIP-TRASH above, TIP1 below: vertical layout
                # But debug shows same row -> should actually be same column
                # YAML position is [col, row] format, but may actually be [row, col]
                # For now: handle as same row with TIP1 to the right (horizontal layout)
                # Or if actual layout is vertical: same column with TIP1 below
                if (tip_trash_final_col is not None and tip1_final_col is not None and
                    tip_trash_final_row is not None and tip1_final_row is not None):
                    
                    # Same row and TIP1 to the right (horizontal layout)
                    # Counter-clockwise 90-degree rotation: 'right' -> 'up' (bottom to top)
                    if is_same_row and is_tip1_right:
                        arrow_direction = 'up'  # counter-clockwise 90-degree rotation
                        arrow_row = tip_trash_final_row
                        arrow_col = tip_trash_final_col + 1  # between TIP-TRASH and TIP1
                        print(f"[DEBUG] Horizontal layout: arrow direction={arrow_direction} (counter-clockwise 90-degree), row={arrow_row}, col={arrow_col}")
                    # Same column and TIP1 below (vertical layout)
                    elif is_same_col and is_tip1_below:
                        arrow_direction = 'up'
                        arrow_row = tip_trash_final_row + 1  # directly below TIP-TRASH
                        arrow_col = tip_trash_final_col
                        print(f"[DEBUG] Vertical layout: arrow direction={arrow_direction}, row={arrow_row}, col={arrow_col}")
                    else:
                        arrow_direction = None
                        arrow_row = None
                        arrow_col = None
                        print(f"[DEBUG] Condition not met: neither same row+right nor same column+below")
                
                if arrow_direction is not None:
                    
                    print(f"[DEBUG] Arrow addition condition met!")
                    
                    # Save arrow info (to draw as overlay after layout completes)
                    tip1_grid = None
                    if "TIP1" in self.grid_widgets:
                        tip1_grid = self.grid_widgets["TIP1"].grid_widget
                        print(f"[DEBUG] TIP1 grid found: {tip1_grid is not None}")
                    else:
                        print(f"[DEBUG] TIP1 grid not found! grid_widgets keys: {list(self.grid_widgets.keys())}")
                    
                    if tip1_grid:
                        # Save arrow info (used after layout completes)
                        if not hasattr(self, '_arrow_info'):
                            self._arrow_info = []
                        
                        grid_spacing = self.group_config.get("grid_spacing", 20)
                        self._arrow_info.append({
                            'direction': arrow_direction,
                            'tip_trash_widget': self.grid_widgets.get("TIP-TRASH"),
                            'tip1_widget': self.grid_widgets.get("TIP1"),
                            'tip1_grid': tip1_grid,
                            'grid_spacing': grid_spacing
                        })
                        print(f"[DEBUG] Arrow info saved (will draw as overlay after layout)")
                else:
                    print(f"[DEBUG] Arrow condition not met - skipping arrow")
            
            # Apply center alignment to all groups
            grid_layout.setAlignment(Qt.AlignCenter)
            
            # For SOURCES group: reduce vertical spacing to 30%
            if self.group_name == "SOURCES":
                grid_layout.setVerticalSpacing(int(grid_layout.spacing() * 0.3))
            
            main_layout.addLayout(grid_layout)
            main_layout.setAlignment(grid_layout, Qt.AlignHCenter | Qt.AlignVCenter)
            
        else:  # vertical (default)
            # Vertical layout - apply vertical mirroring for MEA group
            if self.group_name == "MEA":
                # For MEA group: reverse order for vertical mirroring
                grid_containers = list(self.grid_widgets.values())
                for grid_container in reversed(grid_containers):
                    main_layout.addWidget(grid_container, alignment=Qt.AlignCenter)
            else:
                # Other groups: place with center alignment
                for grid_container in self.grid_widgets.values():
                    main_layout.addWidget(grid_container, alignment=Qt.AlignCenter)
    
    def _draw_arrow_overlay(self):
        """Draw arrow as overlay after layout completes."""
        if not hasattr(self, '_arrow_info') or not self._arrow_info:
            return
        
        # Remove existing arrows
        if hasattr(self, '_arrow_widgets') and self._arrow_widgets:
            for arrow in self._arrow_widgets:
                if arrow:
                    arrow.deleteLater()
            self._arrow_widgets = []
        
        print(f"[DEBUG] Starting arrow overlay drawing")
        
        for arrow_data in self._arrow_info:
            tip_trash_widget = arrow_data.get('tip_trash_widget')
            tip1_widget = arrow_data.get('tip1_widget')
            tip1_grid = arrow_data.get('tip1_grid')
            arrow_direction = arrow_data.get('direction')
            grid_spacing = arrow_data.get('grid_spacing', 20)
            
            if not tip_trash_widget or not tip1_widget or not tip1_grid:
                print(f"[DEBUG] Widget not found: tip_trash={tip_trash_widget is not None}, tip1={tip1_widget is not None}, tip1_grid={tip1_grid is not None}")
                continue
            
            # Calculate widget actual position (relative to parent widget)
            tip_trash_geo = tip_trash_widget.geometry()
            tip1_geo = tip1_widget.geometry()
            
            # Widget geometry may be (0,0) if not yet laid out
            if tip_trash_geo.width() == 0 or tip_trash_geo.height() == 0:
                print(f"[DEBUG] Widget not yet laid out, will retry")
                from PySide6.QtCore import QTimer
                QTimer.singleShot(200, self._draw_arrow_overlay)  # retry after 200ms
                return
            
            print(f"[DEBUG] Widget positions:")
            print(f"  TIP-TRASH: geometry={tip_trash_geo}")
            print(f"  TIP1: geometry={tip1_geo}")
            
            # Calculate grid size
            grid_width = tip1_grid.grid_selector.BOX_WIDTH + 40
            grid_height = tip1_grid.grid_selector.BOX_HEIGHT + 40
            
            # Calculate arrow position (between TIP-TRASH and TIP1)
            if arrow_direction == 'right':
                # Horizontal arrow: between right end of TIP-TRASH and left end of TIP1
                # Right end position of TIP-TRASH
                tip_trash_right = tip_trash_geo.right()
                # Left end position of TIP1
                tip1_left = tip1_geo.left()
                # Arrow start position (right end of TIP-TRASH)
                arrow_x = tip_trash_right
                # Arrow width (up to left end of TIP1)
                arrow_width = tip1_left - tip_trash_right
                # Arrow height and Y position
                arrow_y = tip_trash_geo.center().y() - 25  # 25px above center
                arrow_height = 50
                
                # Adjust if arrow is too small
                if arrow_width < 50:
                    arrow_width = 50
                    arrow_x = (tip_trash_right + tip1_left) // 2 - 25  # center placement
            elif arrow_direction == 'up':
                # Vertical arrow: placed between TIP-TRASH and TIP1
                # Right end position of TIP-TRASH
                tip_trash_right = tip_trash_geo.right()
                # Left end position of TIP1
                tip1_left = tip1_geo.left()
                # Center height of both widgets
                tip_trash_center_y = tip_trash_geo.center().y()
                tip1_center_y = tip1_geo.center().y()
                center_y = (tip_trash_center_y + tip1_center_y) // 2
                
                # Center arrow between TIP-TRASH and TIP1
                # X position: center between TIP-TRASH and TIP1
                arrow_x = (tip_trash_right + tip1_left) // 2 - 25  # 25px left of center
                # Y position: start at center height of both widgets (bottom to top)
                # Arrow height: distance between widgets * 3 + extra space for arrow head
                space_between = tip1_left - tip_trash_right
                arrow_head_margin = 30  # extra space for arrow head
                arrow_height = space_between * 3 + arrow_head_margin  # 3x length + extra space
                arrow_y = center_y - arrow_height // 2 + 40  # start from center going up, shift 40px down
                arrow_width = 50
                
                print(f"[DEBUG] Arrow position: space_between={space_between}, arrow_height={arrow_height}, arrow_x={arrow_x}, arrow_y={arrow_y}")
            else:
                continue
            
            # Create arrow widget
            arrow_widget = ArrowWidget(direction=arrow_direction, size=2, parent=self)
            arrow_widget.setFixedSize(arrow_width, arrow_height)
            arrow_widget.move(arrow_x, arrow_y)
            arrow_widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            arrow_widget.raise_()
            arrow_widget.show()
            
            print(f"[DEBUG] Arrow overlay placement: x={arrow_x}, y={arrow_y}, width={arrow_width}, height={arrow_height}")
            
            # Save arrow
            if not hasattr(self, '_arrow_widgets'):
                self._arrow_widgets = []
            self._arrow_widgets.append(arrow_widget)
        
        print(f"[DEBUG] Arrow overlay drawing complete")
    
    def _create_clear_button(self, layout):
        """Create clear button."""
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 5, 0, 5)
        button_layout.setSpacing(0)
        button_layout.addStretch()  # left padding
        
        # Get button config
        button_text = self.clear_button_config.get("text", "✕")
        button_size = self.clear_button_config.get("size", [20, 20])
        button_style = self.clear_button_config.get("style", "red_circle")
        
        clear_btn = QPushButton(button_text)
        clear_btn.setFixedSize(*button_size)
        
        # Apply style
        if button_style == "red_circle":
            clear_btn.setStyleSheet(self._get_red_circle_style())
        else:
            # Default or custom style
            clear_btn.setStyleSheet(self.clear_button_config.get("custom_style", ""))
        
        clear_btn.clicked.connect(self.clear_selections)
        button_layout.addWidget(clear_btn)
        button_layout.addStretch()  # right padding
        layout.addLayout(button_layout)
    
    def _get_red_circle_style(self) -> str:
        """Return red circular button style."""
        return """
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
                border-color: #ff1744;
            }
            QPushButton:pressed {
                background-color: #d32f2f;
            }
        """
    
    def setup_connections(self):
        """Connect signals."""
        # Connect selection change signals for each grid
        for item_name, grid_container in self.grid_widgets.items():
            # Access actual grid widget from container
            actual_grid_widget = grid_container.grid_widget
            actual_grid_widget.selection_changed.connect(
                lambda positions, name=item_name: self._on_grid_selection_changed(name, positions)
            )
    
    def _on_grid_selection_changed(self, item_name: str, positions: List[Tuple[int, int]]):
        """Called when grid selection changes."""
        self.selection_changed.emit(self.group_name, item_name, positions)
    
    def _on_source_desc_entered(self, grid_name: str):
        """Called when Enter is pressed in Source Desc input field."""
        if self.group_name in ["SOURCES", "SOURCE"]:
            if grid_name not in self.grid_widgets:
                return
            
            grid_container = self.grid_widgets[grid_name]
            if not hasattr(grid_container, 'name_edit') or not grid_container.name_edit:
                return
            
            # Get input value
            new_desc = grid_container.name_edit.text()
            
            # Update Source Desc
            self._update_source_desc(grid_name, new_desc)
            
            # Release focus
            grid_container.name_edit.clearFocus()
    
    def _on_source_desc_editing_finished(self, grid_name: str):
        """Called when focus is lost from Source Desc input field."""
        if self.group_name in ["SOURCES", "SOURCE"]:
            if grid_name not in self.grid_widgets:
                return
            
            grid_container = self.grid_widgets[grid_name]
            if not hasattr(grid_container, 'name_edit') or not grid_container.name_edit:
                return
            
            # Get input value
            new_desc = grid_container.name_edit.text()
            
            # Update Source Desc
            self._update_source_desc(grid_name, new_desc)
    
    def _update_source_desc(self, grid_name: str, new_desc: str):
        """Update Source Desc."""
        if self.group_name not in ["SOURCES", "SOURCE"]:
            return
        
        print(f"[DEBUG] {self.group_name} Source Desc changed: {grid_name} -> {new_desc}")
        
        # Update source_desc (do not change Source ID)
        if grid_name in self.grid_widgets:
            grid_container = self.grid_widgets[grid_name]
            if hasattr(grid_container, 'source_desc'):
                grid_container.source_desc = new_desc
                print(f"Source Desc updated: {grid_name} -> {new_desc}")
        
        # Emit Source Desc change signal (Source ID stays the same)
        source_id = grid_name.lower()  # Source ID does not change
        self.grid_name_changed.emit(self.group_name, source_id, new_desc)
    
    def get_all_positions(self) -> Dict[str, List[Tuple[int, int]]]:
        """Return all grid selection info (access actual grid widget from container)."""
        positions = {}
        for item_name, grid_container in self.grid_widgets.items():
            actual_grid_widget = grid_container.grid_widget
            selected_positions = actual_grid_widget.get_selected_positions()
            
            # Use Source Desc as key for SOURCES/SOURCE group
            if self.group_name in ["SOURCES", "SOURCE"]:
                source_desc = item_name  # default
                if hasattr(grid_container, 'source_desc') and grid_container.source_desc:
                    source_desc = grid_container.source_desc
                positions[source_desc] = selected_positions
            else:
                positions[item_name] = selected_positions
        return positions
    
    def set_positions(self, positions_data: Dict[str, List[Tuple[int, int]]]):
        """Set group selection info (access actual grid widget from container)."""
        for item_name, positions in positions_data.items():
            # Convert Source Desc to Source ID for SOURCES/SOURCE group
            if self.group_name in ["SOURCES", "SOURCE"]:
                # Find Source ID from Source Desc (reverse mapping)
                grid_name = None
                for grid_key, grid_container in self.grid_widgets.items():
                    source_desc = grid_key  # default
                    if hasattr(grid_container, 'source_desc') and grid_container.source_desc:
                        source_desc = grid_container.source_desc
                    
                    # Use grid if Source Desc matches
                    if source_desc == item_name:
                        grid_name = grid_key
                        break
                
                # If not found, item_name may be the grid name
                if not grid_name and item_name in self.grid_widgets:
                    grid_name = item_name
                
                if grid_name and grid_name in self.grid_widgets:
                    actual_grid_widget = self.grid_widgets[grid_name].grid_widget
                    if positions:
                        actual_grid_widget.set_selection(positions)
                    else:
                        actual_grid_widget.clear_selection()
                else:
                    print(f"No grid found for {item_name} (Source Desc)")
            else:
                # Use as-is for other groups
                if item_name in self.grid_widgets:
                    actual_grid_widget = self.grid_widgets[item_name].grid_widget
                    if positions:
                        actual_grid_widget.set_selection(positions)
                    else:
                        actual_grid_widget.clear_selection()
    
    def clear_selections(self):
        """Clear all selections (access actual grid widget from container)."""
        for grid_container in self.grid_widgets.values():
            actual_grid_widget = grid_container.grid_widget
            actual_grid_widget.clear_selection()
        self.clear_requested.emit(self.group_name)
    
    # Compatibility methods (maintain compatibility with existing code)
    def get_all_tip_positions(self) -> Dict[str, List[Tuple[int, int]]]:
        """TIP group compatibility method."""
        return self.get_all_positions()
    
    def set_tip_positions(self, tip_data: Dict[str, List[Tuple[int, int]]]):
        """TIP group compatibility method."""
        self.set_positions(tip_data)
    
    def set_tip_used_positions(self, tip_used_data: Dict[str, List[Tuple[int, int]]]):
        """TIP group: mark 'used' positions in each grid (gray)."""
        for item_name, positions in tip_used_data.items():
            if item_name in self.grid_widgets:
                actual_grid_widget = self.grid_widgets[item_name].grid_widget
                if hasattr(actual_grid_widget, 'set_used_positions'):
                    actual_grid_widget.set_used_positions(positions)
    
    def clear_tip_used_positions(self):
        """TIP group: clear all 'used' marks from all grids."""
        for grid_container in self.grid_widgets.values():
            actual_grid_widget = grid_container.grid_widget
            if hasattr(actual_grid_widget, 'clear_used_positions'):
                actual_grid_widget.clear_used_positions()
    
    def clear_tip_selections(self):
        """TIP group compatibility method."""
        self.clear_selections()
    
    def get_all_mea_positions(self) -> Dict[str, List[Tuple[int, int]]]:
        """MEA group compatibility method."""
        return self.get_all_positions()
    
    def set_mea_positions(self, mea_data: Dict[str, List[Tuple[int, int]]]):
        """MEA group compatibility method."""
        self.set_positions(mea_data)
    
    def clear_mea_selections(self):
        """MEA group compatibility method."""
        self.clear_selections()
    
    def get_all_source_positions(self) -> Dict[str, List[Tuple[int, int]]]:
        """SOURCE group compatibility method."""
        return self.get_all_positions()
    
    def set_source_positions(self, source_data: Dict[str, List[Tuple[int, int]]]):
        """SOURCE group compatibility method."""
        self.set_positions(source_data)
    
    def clear_source_selections(self):
        """SOURCE group compatibility method."""
        self.clear_selections()
    
    def get_all_jig_positions(self) -> Dict[str, List[Tuple[int, int]]]:
        """JIG group compatibility method."""
        return self.get_all_positions()
    
    def set_jig_positions(self, jig_data: Dict[str, List[Tuple[int, int]]]):
        """JIG group compatibility method."""
        self.set_positions(jig_data)
    
    def clear_jig_selections(self):
        """JIG group compatibility method."""
        self.clear_selections()
    
    def apply_grid_name_mapping(self, name_mapping: dict):
        """Apply Source Desc mapping to UI (source_id -> source_desc)."""
        try:
            print(f"[DEBUG] {self.group_name} group: applying Source Desc mapping: {name_mapping}")
            
            for source_id, source_desc in name_mapping.items():
                print(f"{source_id} -> {source_desc}")
                
                # Find grid container (by source_id)
                grid_container = None
                for grid_name, container in self.grid_widgets.items():
                    if hasattr(container, 'source_id') and container.source_id == source_id:
                        grid_container = container
                        break
                    elif grid_name.lower() == source_id.lower():
                        grid_container = container
                        break
                
                if grid_container:
                    # Update source_desc
                    if hasattr(grid_container, 'source_desc'):
                        grid_container.source_desc = source_desc
                    
                    # Find name edit field from container layout
                    layout = grid_container.layout()
                    if layout:
                        for i in range(layout.count()):
                            item = layout.itemAt(i)
                            if item and item.widget():
                                widget = item.widget()
                                # Check if QLineEdit (name edit field)
                                if hasattr(widget, 'setText') and hasattr(widget, 'text'):
                                    print(f"Name edit field found: {source_id}")
                                    widget.setText(source_desc)
                                    print(f"Source Desc change complete: {source_id} -> {source_desc}")
                                    break
                        else:
                            print(f"Name edit field not found for {source_id}")
                    else:
                        print(f"Layout not found for {source_id}")
                else:
                    print(f"Grid not found for {source_id}")
            
            # Sources without mapping: set to default (grid name)
            if self.group_name in ["SOURCES", "SOURCE"]:
                # List of mapped Source IDs (case-insensitive)
                mapped_source_ids = {sid.lower() for sid in name_mapping.keys()}
                
                for grid_name, grid_container in self.grid_widgets.items():
                    # Get Source ID
                    source_id = grid_name.lower()
                    if hasattr(grid_container, 'source_id') and grid_container.source_id:
                        source_id = grid_container.source_id
                    elif hasattr(grid_container, 'table_item_name') and grid_container.table_item_name:
                        source_id = grid_container.table_item_name
                    
                    # Set default if no mapping
                    if source_id.lower() not in mapped_source_ids:
                        # Always set to default if no mapping
                        grid_container.source_desc = grid_name
                        if hasattr(grid_container, 'name_edit') and grid_container.name_edit:
                            grid_container.name_edit.blockSignals(True)
                            grid_container.name_edit.setText(grid_name)
                            grid_container.name_edit.blockSignals(False)
                            print(f"{grid_name} (ID: {source_id}) default Source Desc set: {grid_name}")
                        else:
                            print(f"{grid_name} (ID: {source_id}) name_edit not found")
            
            print(f"[DEBUG] {self.group_name} group name mapping applied")
            
        except Exception as e:
            print(f"[DEBUG] {self.group_name} group name mapping error: {e}")
            import traceback
            traceback.print_exc()
    
    def set_tube_interface(self, tube_interface):
        """Set Tube Interface and load initial volumes."""
        self.tube_interface = tube_interface
        if self.group_name in ["SOURCES", "SOURCE"]:
            # Load volume with slight delay (wait for tube_factory init)
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, self.load_all_volumes)
    
    def load_all_volumes(self):
        """Load volumes for all grids from Tube Interface."""
        # Prevent duplicate calls
        if hasattr(self, '_loading_volumes') and self._loading_volumes:
            return
        
        self._loading_volumes = True
        
        try:
            if not self.tube_interface:
                print(f"[DEBUG] {self.group_name} group: Tube Interface not configured.")
                return
            
            if self.group_name not in ["SOURCES", "SOURCE"]:
                return
            
            # Minimize log output (prevent excessive logs)
            loaded_count = 0
            for grid_name, grid_container in self.grid_widgets.items():
                if hasattr(grid_container, 'volume_edit') and grid_container.volume_edit:
                    try:
                        self._load_volume_from_tube_interface(grid_name)
                        loaded_count += 1
                    except (AttributeError, RuntimeError) as e:
                        print(f"[DEBUG] {grid_name} volume load error: {e}")
                        continue
            # Print summary only (remove individual messages)
            # print(f"[DEBUG] {self.group_name} group: all volumes loaded: {loaded_count}")
        finally:
            self._loading_volumes = False
    
    def _load_volume_from_tube_interface(self, grid_name: str):
        """Load volume for a specific grid from Tube Interface."""
        if not self.tube_interface:
            return
        
        if grid_name not in self.grid_widgets:
            return
        
        grid_container = self.grid_widgets[grid_name]
        if not hasattr(grid_container, 'volume_edit') or not grid_container.volume_edit:
            return
        
        # Get Source ID (unique identifier, immutable)
        source_id = grid_name.lower()  # default: lowercase grid name
        if hasattr(grid_container, 'source_id') and grid_container.source_id:
            source_id = grid_container.source_id
        elif hasattr(grid_container, 'table_item_name') and grid_container.table_item_name:
            source_id = grid_container.table_item_name
        
        try:
            # Get directly from tube manager (using Source ID)
            manager = self.tube_interface.factory.get_tube_manager_by_table_name(source_id)
            if manager:
                # Get current volume
                volume_ul = manager.current_volume_ul
                
                # Check if experiment is running (via parent)
                is_experiment_running = False
                if self.parent():
                    # Check experiment state if parent is main window
                    parent = self.parent()
                    while parent:
                        if hasattr(parent, 'experiment_state'):
                            from gui.constants import ExperimentConstants
                            is_experiment_running = (
                                parent.experiment_state == ExperimentConstants.EXPERIMENT_STATES.get('RUNNING', 'running')
                            )
                            break
                        parent = parent.parent()
                
                # Set default if value is 0 or very small
                # Only set default when experiment is not running (maintain actual consumed state during experiment)
                if volume_ul <= 0.01 and not is_experiment_running:  # Set default only if <= 0.01 ul and not running
                    # Set default liquid level (height = 90% of tube length)
                    if manager.set_default_liquid_level():
                        volume_ul = manager.current_volume_ul
                        print(f"[DEBUG] {grid_name} default volume set: {volume_ul:.2f} ul")
                    else:
                        # If set_default_liquid_level fails, calculate and set directly
                        default_height = manager.length_mm * 0.9
                        default_volume_ul = manager._calculate_volume_from_height(default_height)
                        if manager.set_liquid_volume(default_volume_ul):
                            volume_ul = default_volume_ul
                            print(f"[DEBUG] {grid_name} default volume set directly: {volume_ul:.2f} ul")
                elif volume_ul <= 0.01 and is_experiment_running:
                    # During experiment: maintain depleted state (do not reset to default)
                    print(f"[DEBUG] {grid_name} volume is 0 but experiment is running, skipping default reset.")
                
                volume_mL = volume_ul / 1000.0  # ul -> mL conversion
                
                # Update volume input field (block signals to prevent infinite loop)
                volume_edit = grid_container.volume_edit
                volume_edit.blockSignals(True)
                volume_edit.setText(f"{volume_mL:.2f}")
                volume_edit.setEnabled(True)  # ensure enabled
                volume_edit.blockSignals(False)
                
                # Get Source Desc (for display)
                source_desc = grid_name
                if hasattr(grid_container, 'source_desc') and grid_container.source_desc:
                    source_desc = grid_container.source_desc
                
                # Remove individual load messages (prevent excessive logs)
                # print(f"[DEBUG] {source_desc} (ID: {source_id}) volume loaded: {volume_mL:.2f} mL ({volume_ul:.2f} ul)")
            else:
                # If item not in Tube Interface
                volume_edit = grid_container.volume_edit
                volume_edit.blockSignals(True)
                volume_edit.setText("")
                volume_edit.setPlaceholderText("N/A")
                volume_edit.setEnabled(False)
                volume_edit.blockSignals(False)
                print(f"[DEBUG] {grid_name} (ID: {source_id}): Tube Manager not found.")
        except Exception as e:
            print(f"[DEBUG] {grid_name} volume load error: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_volume_entered(self, grid_name: str):
        """Called when Enter is pressed in volume input field."""
        if not self.tube_interface:
            return
        
        if grid_name not in self.grid_widgets:
            return
        
        grid_container = self.grid_widgets[grid_name]
        if not hasattr(grid_container, 'volume_edit') or not grid_container.volume_edit:
            return
        
        # Get input value
        volume_text = grid_container.volume_edit.text()
        
        # Update volume
        self._update_volume_from_text(grid_name, volume_text)
        
        # Release focus
        grid_container.volume_edit.clearFocus()
    
    def _on_volume_editing_finished(self, grid_name: str):
        """Called when focus is lost from volume input field."""
        if not self.tube_interface:
            return
        
        if grid_name not in self.grid_widgets:
            return
        
        grid_container = self.grid_widgets[grid_name]
        if not hasattr(grid_container, 'volume_edit') or not grid_container.volume_edit:
            return
        
        # Get input value
        volume_text = grid_container.volume_edit.text()
        
        # Update volume
        self._update_volume_from_text(grid_name, volume_text)
    
    def _update_volume_from_text(self, grid_name: str, volume_text: str):
        """Update volume from input text."""
        if not self.tube_interface:
            return
        
        if grid_name not in self.grid_widgets:
            return
        
        grid_container = self.grid_widgets[grid_name]
        if not hasattr(grid_container, 'volume_edit') or not grid_container.volume_edit:
            return
        
        # Get Source ID (unique identifier, immutable)
        source_id = grid_name.lower()  # default: lowercase grid name
        if hasattr(grid_container, 'source_id') and grid_container.source_id:
            source_id = grid_container.source_id
        elif hasattr(grid_container, 'table_item_name') and grid_container.table_item_name:
            source_id = grid_container.table_item_name
        
        # Get Source Desc (for display)
        source_desc = grid_name
        if hasattr(grid_container, 'source_desc') and grid_container.source_desc:
            source_desc = grid_container.source_desc
        
        # Parse input value (extract numbers only)
        try:
            # Ignore empty string but still emit signal (may have been changed elsewhere)
            if not volume_text.strip():
                # Emit signal even for empty string (reflect changes from other sources)
                self.volume_updated_signal.emit()
                return
            
            # Extract number (including decimal)
            number_match = re.search(r'[\d.]+', volume_text)
            if not number_match:
                # Emit signal even for non-numeric input
                self.volume_updated_signal.emit()
                return
            
            volume_mL = float(number_match.group())
            
            # Check for negative value
            if volume_mL < 0:
                print(f"[DEBUG] {source_desc}: negative volume not allowed.")
                # Emit signal even for negative value
                self.volume_updated_signal.emit()
                return
            
            # mL -> ul conversion
            volume_ul = volume_mL * 1000.0
            
            # Write to Tube Interface (using Source ID)
            success = self.tube_interface.set_liquid_volume(source_id, volume_ul)
            
            if success:
                print(f"[DEBUG] {source_desc} (ID: {source_id}) volume set: {volume_mL:.2f} mL ({volume_ul:.2f} ul)")
            else:
                print(f"[DEBUG] {source_desc} (ID: {source_id}) volume set failed")
            
            # Always emit tube status update signal regardless of success (always refresh table)
            self.volume_updated_signal.emit()
                
        except ValueError:
            # Emit signal even for non-numeric value
            self.volume_updated_signal.emit()
        except Exception as e:
            print(f"[DEBUG] {grid_name} volume change processing error: {e}")
            import traceback
            traceback.print_exc()
            # Emit signal even on error
            self.volume_updated_signal.emit()
    
    def _on_stack_count_changed(self, location: str, text: str):
        """Called when stack count changes (for JIG group)."""
        if not self.stack_manager:
            return
        
        try:
            count = int(text) if text else 0
            if self.stack_manager.set_stack_count(location, count):
                self._update_stack_display(location)
        except ValueError:
            pass
    
    def _update_stack_display(self, location: str):
        """Update stack display (for JIG group)."""
        if not self.stack_manager:
            return
        
        count = self.stack_manager.get_stack_count(location)
        max_count = self.stack_manager.MAX_COUNTS.get(location, 0)
        
        if location in self.stack_labels:
            self.stack_labels[location].setText(f"/ {max_count}")
    
    def get_stack_count(self, location: str) -> int:
        """Get stack count (for JIG group)."""
        if self.stack_manager:
            return self.stack_manager.get_stack_count(location)
        return 0
    
    def set_stack_count(self, location: str, count: int) -> bool:
        """Set stack count (for JIG group)."""
        if not self.stack_manager:
            return False
        
        if self.stack_manager.set_stack_count(location, count):
            if location in self.stack_inputs:
                self.stack_inputs[location].setText(str(count))
            self._update_stack_display(location)
            return True
        return False
    
    def showEvent(self, event):
        """Draw arrow overlay when widget is shown."""
        super().showEvent(event)
        if hasattr(self, '_arrow_info') and self._arrow_info:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, self._draw_arrow_overlay)
    
    def resizeEvent(self, event):
        """Redraw arrow overlay when widget is resized."""
        super().resizeEvent(event)
        if hasattr(self, '_arrow_info') and self._arrow_info:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, self._draw_arrow_overlay)


class GroupWidgetFactory:
    """Group widget factory class."""
    
    @staticmethod
    def load_config(config_path: str = "config/groups_config.yaml") -> Dict[str, Any]:
        """Load YAML config file."""
        try:
            with open(config_path, 'r', encoding='utf-8') as file:
                config = yaml.safe_load(file)
            return config
        except FileNotFoundError:
            print(f"Warning: config file not found: {config_path}")
            return GroupWidgetFactory._get_default_config()
        except yaml.YAMLError as e:
            print(f"Warning: YAML parse error: {e}")
            return GroupWidgetFactory._get_default_config()
    
    @staticmethod
    def create_group_widget(group_key: str, config: Dict[str, Any]):
        """Create widget for a specific group."""
        if group_key in config.get("groups", {}):
            group_config = config["groups"][group_key]
            group_name = group_config.get("name", "Unknown")
            
            # Use MEAGroupWidget for MEA group
            if group_name == "MEA":
                try:
                    from views.mea_group_widget import MEAGroupWidget
                    return MEAGroupWidget(group_config)
                except ImportError:
                    print("Cannot import MEAGroupWidget. Using UnifiedGroupWidget.")
                    return UnifiedGroupWidget(group_config)
            else:
                return UnifiedGroupWidget(group_config)
        else:
            raise ValueError(f"No config found for group '{group_key}'.")
    
    @staticmethod
    def create_all_group_widgets(config: Dict[str, Any]) -> Dict[str, UnifiedGroupWidget]:
        """Create all group widgets."""
        widgets = {}
        for group_key in config.get("groups", {}):
            widgets[group_key] = GroupWidgetFactory.create_group_widget(group_key, config)
        return widgets
    
    @staticmethod
    def _get_default_config() -> Dict[str, Any]:
        """Return default config (used when config file is missing)."""
        return {
            "groups": {
                "group1": {
                    "name": "Group1",
                    "display_name": "Group1",
                    "description": "Default Group 1",
                    "layout": "vertical",
                    "grids": [
                        {"name": "GRID1", "rows": 8, "cols": 12, "circle_scale": 1.0, "position": [0, 0]}
                    ],
                    "clear_button": {"enabled": True, "text": "✕", "size": [20, 20], "style": "red_circle"}
                }
            },
            "common": {
                "margins": [10, 10, 10, 10],
                "spacing": 15,
                "grid_spacing": 20
            }
        }
