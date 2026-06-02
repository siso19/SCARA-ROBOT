"""
MEA 그룹 위젯
MVC 패턴의 View 계층 - MEA 그룹 UI
"""

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
    """MEA 그룹 위젯 (Stack 기능 포함)"""
    
    stack_count_changed = Signal(str, int)  # location, count
    grid_name_changed = Signal(str, str, str)  # 그룹명, 원래이름, 새이름 (호환성을 위해 추가)
    
    def __init__(self, group_config: Dict[str, Any] = None, parent=None):
        # stack_manager를 먼저 초기화 (init_ui()에서 사용되므로)
        self.stack_manager = MEAStackManager()
        self.height_calculator = MEAHeightCalculator(self.stack_manager)
        self.stack_inputs: Dict[str, QLineEdit] = {}
        self.stack_labels: Dict[str, QLabel] = {}
        
        # YAML 설정 저장
        if group_config:
            self.group_config = group_config
            self.group_name = group_config.get("name", "MEA")
            self.grids_config = group_config.get("grids", [])
            self.clear_button_config = group_config.get("clear_button", {})
        else:
            # 기본 설정 (하위 호환성)
            self.group_config = {}
            self.group_name = "MEA"
            self.grids_config = [
                {"name": "MEA1", "rows": 8, "cols": 2, "circle_scale": 2.0, "position": [13, 18]},
                {"name": "MEA2", "rows": 8, "cols": 2, "circle_scale": 2.0, "position": [13, 20]},
                {"name": "MEA3", "rows": 8, "cols": 2, "circle_scale": 2.0, "position": [13, 23]}
            ]
            self.clear_button_config = {"enabled": True, "text": "✕", "size": [20, 20], "style": "red_circle"}
        
        # BaseGroupWidget 초기화 (이 시점에 init_ui()가 호출됨)
        super().__init__(self.group_name, parent)
    
    def init_ui(self):
        """UI 초기화 - YAML 설정에 따라 동적으로 생성"""
        layout = QVBoxLayout(self)
        
        # 공통 여백과 간격 설정
        margins = self.group_config.get("margins", [10, 10, 10, 10]) if self.group_config else [10, 10, 10, 10]
        spacing = self.group_config.get("spacing", 15) if self.group_config else 15
        layout.setContentsMargins(*margins)
        layout.setSpacing(spacing)
        
        # YAML 설정에 따라 MEA 그리드들 생성
        self._create_grids()
        
        # 레이아웃 타입에 따라 그리드 배치
        self._arrange_grids(layout)
        
        # 상단 여백 추가
        layout.addStretch()
        
        # 클리어 버튼 생성
        if self.clear_button_config.get("enabled", True):
            self._create_clear_button(layout)
    
    def _create_grids(self):
        """YAML 설정에 따라 그리드 위젯들 생성"""
        for grid_config in self.grids_config:
            name = grid_config["name"]
            container = self._create_mea_container(name, grid_config)
            self.grid_widgets[name] = container
    
    def _arrange_grids(self, main_layout):
        """레이아웃 타입에 따라 그리드들을 배치"""
        from PySide6.QtWidgets import QGridLayout
        
        layout_type = self.group_config.get("layout", "horizontal") if self.group_config else "horizontal"
        
        if layout_type == "grid":
            # Grid 레이아웃 사용 (position 기반 배치)
            grid_layout = QGridLayout()
            grid_layout.setSpacing(self.group_config.get("grid_spacing", 20) if self.group_config else 20)
            
            # 최대 position 찾기
            max_col = 0
            max_row = 0
            for grid_config in self.grids_config:
                position = grid_config.get("position", [0, 0])
                col, row = position
                max_col = max(max_col, col)
                max_row = max(max_row, row)
            
            # position에 따라 그리드 배치
            # MEA 그룹은 SOURCE 그룹과 마찬가지로 회전/미러링 없이 직접 배치
            for grid_config in self.grids_config:
                name = grid_config["name"]
                position = grid_config.get("position", [0, 0])
                col, row = position
                
                # 회전 없이 직접 배치 (SOURCE 그룹과 동일)
                final_col = col
                final_row = row
                
                if name in self.grid_widgets:
                    grid_layout.addWidget(self.grid_widgets[name], final_row, final_col, 
                                        alignment=Qt.AlignCenter)
            
            main_layout.addLayout(grid_layout)
        elif layout_type == "vertical":
            # Vertical 레이아웃 (세로 배치) - YAML 설정 순서대로 배치
            for grid_config in self.grids_config:
                name = grid_config["name"]
                if name in self.grid_widgets:
                    main_layout.addWidget(self.grid_widgets[name])
        else:
            # Horizontal 레이아웃 (기본값)
            mea_layout = QHBoxLayout()
            mea_layout.setContentsMargins(0, 0, 0, 0)
            mea_layout.setSpacing(20)
            
            for grid_config in self.grids_config:
                name = grid_config["name"]
                if name in self.grid_widgets:
                    mea_layout.addWidget(self.grid_widgets[name])
            
            main_layout.addLayout(mea_layout)
    
    def _create_clear_button(self, layout):
        """Clear 버튼 생성"""
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 5, 0, 5)
        button_layout.addStretch()
        
        clear_text = self.clear_button_config.get("text", "✕")
        clear_size = self.clear_button_config.get("size", [20, 20])
        
        clear_btn = QPushButton(clear_text)
        clear_btn.setFixedSize(clear_size[0], clear_size[1])
        
        # 스타일 설정
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
        """MEA 그리드와 스택 입력 필드를 포함하는 컨테이너 생성"""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        
        # YAML 설정에서 그리드 정보 가져오기
        if grid_config:
            rows = grid_config.get("rows", 8)
            cols = grid_config.get("cols", 2)
            circle_scale = grid_config.get("circle_scale", 2.0)
        else:
            # 기본값 (하위 호환성)
            rows = 8
            cols = 2
            circle_scale = 2.0
        
        # 그리드 위젯
        # 90도 회전: rows와 cols를 교환 (mea-measure와 동일)
        # TIPGrid(grid_width, grid_height)이므로 rows를 grid_width, cols를 grid_height로 전달
        grid_widget = TIPGrid(mea_name, rows, cols, circle_scale=circle_scale, group_name=self.group_name)
        layout.addWidget(grid_widget)
        
        # 컨테이너에 그리드 위젯 참조 저장 (setup_connections에서 사용)
        container.grid_widget = grid_widget
        
        # 이름과 스택 입력을 포함하는 레이아웃 (가운데 정렬)
        name_stack_layout = QHBoxLayout()
        name_stack_layout.setContentsMargins(0, 0, 0, 0)
        name_stack_layout.setSpacing(5)
        
        # 왼쪽 여백 추가 (가운데 정렬을 위해)
        name_stack_layout.addStretch()
        
        # 이름 라벨
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
        
        # 스택 개수 입력 필드
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
        # textChanged와 editingFinished 모두 연결 (엔터/포커스 변경 시에도 업데이트)
        stack_input.textChanged.connect(
            lambda text, loc=location_key: self._on_stack_count_changed(loc, text)
        )
        stack_input.editingFinished.connect(
            lambda loc=location_key: self._on_stack_count_finished(loc)
        )
        self.stack_inputs[location_key] = stack_input
        name_stack_layout.addWidget(stack_input)
        
        # 표시 라벨 (현재 개수 / 최대 개수)
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
        
        # 오른쪽 여백 추가 (가운데 정렬을 위해)
        name_stack_layout.addStretch()
        layout.addLayout(name_stack_layout)
        
        return container
    
    def _on_stack_count_changed(self, location: str, text: str):
        """스택 개수 변경 시 호출 (실시간 업데이트)"""
        try:
            count = int(text) if text else 0
            if self.stack_manager.set_stack_count(location, count):
                self._update_stack_display(location)
                self.stack_count_changed.emit(location, count)
        except ValueError:
            pass
    
    def _on_stack_count_finished(self, location: str):
        """스택 개수 입력 완료 시 호출 (엔터/포커스 변경)"""
        try:
            if location in self.stack_inputs:
                text = self.stack_inputs[location].text()
                count = int(text) if text else 0
                # 최대 개수 확인
                max_count = self.stack_manager.MAX_COUNTS.get(location, 0)
                if count < 0 or count > max_count:
                    # 잘못된 값이면 이전 값으로 복원
                    count = self.stack_manager.get_stack_count(location)
                    self.stack_inputs[location].setText(str(count))
                elif self.stack_manager.set_stack_count(location, count):
                    self._update_stack_display(location)
                    self.stack_count_changed.emit(location, count)
        except ValueError:
            pass
    
    def _update_stack_display(self, location: str):
        """스택 표시 업데이트"""
        count = self.stack_manager.get_stack_count(location)
        max_count = self.stack_manager.MAX_COUNTS.get(location, 0)
        
        if location in self.stack_labels:
            self.stack_labels[location].setText(f"/ {max_count}")
        
        # 높이 정보 계산 (선택적)
        pick_height = self.height_calculator.calculate_pick_height(location)
        if pick_height:
            # 높이 정보를 툴팁으로 표시할 수 있음
            pass
    
    def get_stack_count(self, location: str) -> int:
        """스택 개수 조회"""
        return self.stack_manager.get_stack_count(location)
    
    def set_stack_count(self, location: str, count: int) -> bool:
        """스택 개수 설정 (외부에서 호출)"""
        if self.stack_manager.set_stack_count(location, count):
            if location in self.stack_inputs:
                self.stack_inputs[location].setText(str(count))
            self._update_stack_display(location)
            return True
        return False
    
    def setup_connections(self):
        """시그널 연결"""
        # 각 그리드의 선택 변경 시그널 연결
        for item_name, container in self.grid_widgets.items():
            # container에서 실제 그리드 위젯 가져오기
            if hasattr(container, 'grid_widget'):
                grid_widget = container.grid_widget
                grid_widget.selection_changed.connect(
                    lambda positions, name=item_name: self._on_grid_selection_changed(name, positions)
                )
    
    def _on_grid_selection_changed(self, item_name: str, positions: List[Tuple[int, int]]):
        """그리드 선택 변경 시 호출"""
        self.selection_changed.emit(self.group_name, item_name, positions)
    
    def get_all_positions(self) -> Dict[str, List[Tuple[int, int]]]:
        """모든 그리드의 선택 정보 반환 (컨테이너 구조 고려)"""
        positions = {}
        for item_name, container in self.grid_widgets.items():
            if hasattr(container, 'grid_widget'):
                grid_widget = container.grid_widget
                positions[item_name] = grid_widget.get_selected_positions()
        return positions
    
    def set_positions(self, positions_data: Dict[str, List[Tuple[int, int]]]):
        """그룹의 선택 정보 설정 (컨테이너 구조 고려)"""
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
        """모든 선택 해제 (컨테이너 구조 고려)"""
        for container in self.grid_widgets.values():
            if hasattr(container, 'grid_widget'):
                grid_widget = container.grid_widget
                grid_widget.clear_selection()
        self.clear_requested.emit(self.group_name)
    
    def get_all_mea_positions(self) -> Dict[str, List[Tuple[int, int]]]:
        """모든 MEA의 선택 정보를 반환"""
        return self.get_all_positions()
    
    def set_mea_positions(self, mea_data: Dict[str, List[Tuple[int, int]]]):
        """MEA 그룹의 선택 정보를 설정"""
        self.set_positions(mea_data)
    
    def clear_mea_selections(self):
        """MEA 그룹의 선택을 해제"""
        self.clear_selections() 