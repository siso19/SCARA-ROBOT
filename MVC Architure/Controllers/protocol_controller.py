"""
프로토콜 컨트롤러
MVC 패턴의 Controller 계층 - UI와 Model 연결
"""

from typing import Optional, Dict, Any
from PySide6.QtCore import QObject, Signal
from models.protocol_model import ProtocolModel
from services.grid_selection_service import GridSelectionService


class ProtocolController(QObject):
    """프로토콜 컨트롤러"""
    
    # 시그널 정의
    ui_update_needed = Signal()  # UI 업데이트 필요 시
    error_occurred = Signal(str)  # 오류 발생 시
    success_message = Signal(str)  # 성공 메시지 시
    
    def __init__(self, protocol_model: ProtocolModel, grid_service: GridSelectionService):
        super().__init__()
        self._protocol_model = protocol_model
        self._grid_service = grid_service
        self._selected_process: Optional[Dict[str, Any]] = None
        self._selected_order_index: Optional[int] = None
        
        # 시그널 연결
        self._connect_signals()
    
    def _connect_signals(self):
        """시그널 연결"""
        # 모델 시그널 연결
        self._protocol_model.data_changed.connect(self._on_data_changed)
        self._protocol_model.process_added.connect(self._on_process_added)
        self._protocol_model.order_added.connect(self._on_order_added)
        
        # 그리드 서비스 시그널 연결 (grid_service가 존재할 때만)
        if self._grid_service:
            self._grid_service.target_updated.connect(self._on_target_updated)
    
    def load_protocol_from_file(self, file_path: str) -> tuple[bool, dict]:
        """파일에서 프로토콜 로드"""
        success, grid_name_mapping = self._protocol_model.load_from_file(file_path)
        if success:
            print(f"[DEBUG] Protocol loaded successfully: {file_path}")
            if grid_name_mapping:
                print(f"[DEBUG] Grid name mapping loaded: {grid_name_mapping}")
            #self.success_message.emit(f"프로토콜을 성공적으로 로드했습니다: {file_path}")
        else:
            self.error_occurred.emit("Failed to load protocol.")
        return success, grid_name_mapping
    
    def save_protocol_to_file(self, file_path: str) -> bool:
        """프로토콜을 파일로 저장"""
        success = self._protocol_model.save_to_file(file_path)
        if success:
            #self.success_message.emit(f"프로토콜을 성공적으로 저장했습니다: {file_path}")
            print(f"[DEBUG] Protocol saved successfully: {file_path}")
        else:
            self.error_occurred.emit("Failed to save protocol.")
        return success
    
    def add_process(self, description: str = "") -> bool:
        """새 프로세스 추가"""
        next_name = self._protocol_model.generate_next_process_name()
        success = self._protocol_model.add_process(next_name, description)
        if success:
            self.success_message.emit(f"Process '{next_name}' has been added.")
        else:
            self.error_occurred.emit("Failed to add process.")
        return success
    
    def add_process_at_position(self, description: str = "", insert_after_process: str = None) -> bool:
        """지정된 프로세스 뒤에 새 프로세스 추가"""
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
        """새 주문 추가"""
        print(f"[DEBUG] Controller: add_order called")
        print(f"[DEBUG] Controller: Action={action}, Amount={amount}, Time={time_value} {time_unit}")
        
        # 마지막 프로세스에 추가
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
        """지정된 위치에 새 주문 추가"""
        print(f"[DEBUG] Controller: add_order_at_position called")
        print(f"[DEBUG] Controller: Action={action}, Amount={amount}, Time={time_value} {time_unit}")
        print(f"[DEBUG] Controller: Process={process_name}, Order Index={order_index}")
        
        # 프로세스 결정
        if process_name:
            target_process = self._protocol_model.get_process_by_name(process_name)
            if not target_process:
                self.error_occurred.emit(f"Process '{process_name}' not found.")
                return False
        else:
            # 마지막 프로세스 사용
            target_process = self._protocol_model.get_last_process()
            if not target_process:
                self.error_occurred.emit("No processes found. Please add a process first.")
                return False
            process_name = target_process["name"]
        
        # 타겟 정보 결정 (UI에서 전달받은 정보 우선 사용)
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
        """선택된 주문 업데이트"""
        print(f"[DEBUG] Controller: update_selected_order called")
        print(f"[DEBUG] Controller: Selected process: {self._selected_process['name'] if self._selected_process else 'None'}")
        print(f"[DEBUG] Controller: Selected order index: {self._selected_order_index}")
        
        if not self._selected_process or self._selected_order_index is None:
            print("[DEBUG] Controller: No order selected for update")
            self.error_occurred.emit("No order selected for update.")
            return False
        
        # 타겟 정보 결정 (UI에서 전달받은 정보 우선 사용)
        if target_data is not None:
            target = target_data
            print(f"[DEBUG] Controller: Target info from UI: {target}")
        else:
            target = self.get_target_for_order()
            print(f"[DEBUG] Controller: Target info from Grid Service: {target}")
        
        # 주문 데이터 생성
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
            order_data  # OrderData를 dict로 변환
        )
        print(f"[DEBUG] Controller: Model update result: {success}")
        
        if success:
            print(f"[DEBUG] Controller: Order '{action}' updated successfully")
            #self.success_message.emit(f"주문 '{action}'이 업데이트되었습니다.")
        else:
            print("[DEBUG] Controller: Order update failed")
            self.error_occurred.emit("Failed to update order.")
        return success
    
    def select_order_by_index(self, process_name: str, order_index: int):
        """인덱스로 주문 선택 (정확한 선택)"""
        print(f"[DEBUG] Controller: select_order_by_index called - Process: {process_name}, Index: {order_index}")
        
        # 프로세스 찾기
        process = self._protocol_model.get_process_by_name(process_name)
        if not process:
            print(f"[DEBUG] Controller: Process '{process_name}' not found")
            return False
        
        # 인덱스 범위 확인 (dict 기반)
        if 0 <= order_index < len(process["orders"]):
            self._selected_process = process
            self._selected_order_index = order_index
            print(f"[DEBUG] Controller: Order selected - Process: {process_name}, Index: {order_index}")
            return True
        else:
            print(f"[DEBUG] Controller: Invalid order index - Index: {order_index}, Max: {len(process['orders'])-1}")
            return False

    def select_order_for_update(self, process_name: str, order_data: dict):
        """업데이트를 위해 주문 선택 (폴백 메소드)"""
        print(f"[DEBUG] Controller: select_order_for_update called (fallback)")
        
        # 프로세스 찾기
        process = self._protocol_model.get_process_by_name(process_name)
        if not process:
            return False
        
        # 주문 인덱스 찾기 (dict 기반)
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
        """프로세스 선택"""
        self._selected_process = self._protocol_model.get_process_by_name(process_name)
        self._selected_order_index = None
        self.ui_update_needed.emit()
    
    def select_order(self, process_name: str, order_index: int):
        """주문 선택"""
        process = self._protocol_model.get_process_by_name(process_name)
        if process and 0 <= order_index < len(process["orders"]):
            self._selected_process = process
            self._selected_order_index = order_index
            
            # 선택된 주문의 타겟 정보를 그리드 서비스에 설정 (dict 기반)
            order = process["orders"][order_index]
            if self._grid_service:
                self._grid_service.set_target_from_order(order["target"])
            
            self.ui_update_needed.emit()
    
    def clear_selection(self):
        """선택 해제"""
        self._selected_process = None
        self._selected_order_index = None
        self.ui_update_needed.emit()
    
    def get_selected_process(self) -> Optional[dict]:
        """선택된 프로세스 반환 (dict 기반)"""
        return self._selected_process
    
    def get_selected_order(self) -> Optional[dict]:
        """선택된 주문 반환 (dict 기반)"""
        if self._selected_process and self._selected_order_index is not None:
            if 0 <= self._selected_order_index < len(self._selected_process["orders"]):
                return self._selected_process["orders"][self._selected_order_index]
        return None
    
    def get_protocol_data(self):
        """프로토콜 데이터 반환 (dict 기반)"""
        return self._protocol_model.protocol_dict
    
    def get_target_summary(self) -> str:
        """타겟 요약 정보 반환"""
        return self._grid_service.get_target_summary()
    
    def get_target_details(self) -> str:
        """타겟 상세 정보 반환"""
        return self._grid_service.get_target_details()
    
    def clear_all_grid_selections(self):
        """모든 그리드 선택 해제"""
        self._grid_service.clear_all_selections()
    
    def update_grid_selection(self, group_name: str, item_name: str, positions):
        """그리드 선택 업데이트"""
        self._grid_service.update_selection(group_name, item_name, positions)
    
    def update_grid_selection_from_ui(self, target_data):
        """UI에서 그리드 선택 정보 업데이트 (더 이상 사용하지 않음)"""
        print(f"[DEBUG] Controller: update_grid_selection_from_ui called (deprecated): {target_data}")
        # 이 메서드는 더 이상 사용하지 않음
        pass
    
    def get_target_for_order(self) -> dict:
        """현재 선택된 Order의 target 정보만 가져오기"""
        # Grid Service에서 현재 선택 정보를 가져와서 target 형태로 변환
        selections = self._grid_service.get_selections()
        
        # 빈 그룹 제거
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
        """모든 그룹의 선택 정보를 가져오기"""
        # 각 그룹의 선택 정보를 수집하는 로직
        # 실제로는 그룹 위젯들에서 직접 가져와야 하지만,
        # 현재는 그리드 서비스에서 관리하는 정보를 반환
        return self._grid_service.get_selections()
    
    def _on_data_changed(self):
        """데이터 변경 시 호출"""
        self.ui_update_needed.emit()
    
    def _on_process_added(self, process_name: str):
        """프로세스 추가 시 호출"""
        print(f"Process added: {process_name}")
    
    def _on_order_added(self, process_name: str, action: str):
        """주문 추가 시 호출"""
        print(f"Order added: {process_name} - {action}")
    
    def _on_target_updated(self, target_info: Dict[str, Any]):
        """타겟 업데이트 시 호출"""
        print(f"Target updated: {target_info}")
        self.ui_update_needed.emit() 