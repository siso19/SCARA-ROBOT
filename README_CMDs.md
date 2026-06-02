# Listing Commands

## 목차
1. [Features](#features)
2. [좌표계](#좌표계)
3. [Command & Function Mapping](#command--function-mapping)
4. [Action List](#action-list)
5. [에러 처리](#에러-처리)
6. [상태 관리](#상태-관리)
7. [매개변수 상세](#매개변수-상세)
8. [용어 정의](#용어-정의)

## Features
- JSON File 로 만들어진 프로토콜(./protocol/)의 각각의 order 들을 command list 로 표현하여 cmd_list.json 생성
- cmd_list.json 에서의 커맨드 넘버들은 protocol 에서의 각 process, order number 들을 참고하여 부여한다. (통일성 & 가독성)
- protocol json file 이 적절히 작성되었는지 아래의 Rule 을 참고하여 유효성을 판단한다.
- **초기화 이동**: 프로토콜 시작 시 초기 위치 (0,0,0)로 이동
    - 모든 프로토콜의 첫 번째 명령으로 실행
    - 안전한 시작 위치 보장
- **안전한 이동**: x,y 이동과 z 이동을 분리하여 충돌 방지
    - 모든 x,y 이동은 최상위 위치 (z=0)에서만 수행
    - z 이동은 x,y 위치가 확정된 후에만 수행
    - 물체와의 충돌 위험 최소화
    - equip 명령: move_to_top → move_xy_position → move_z_position 순서
- **연속된 타겟 최적화**: 짧은 거리 이동에 move_offset 사용
    - 첫 번째 타겟: 절대 좌표로 이동 (move_xy_position + move_z_position)
    - 연속된 타겟: 상대 오프셋으로 이동 (move_offset + move_z_position)
    - 한 축으로만 이동하는 경우를 연속된 타겟으로 판단
- 이동 : tip box 의 수량, 액체의 용량, 복수 선택된 타겟을 계산하여 자동으로 위치 이동하도록 한다.
    - tip box: 내부 격자에서 tip 1개씩만 장착하여 사용 가능하여, Equip 후에는 다음 격자 위치로 이동하여야 함.
    - source (액체) - 주어진 용량(in table_coordinates.json)에서 Take 액션으로 모두 소모되면, 같은 액체의 다음번호로 이동하여야 함.
    - 복수 타겟 - 하나의 액션에 복수의 타겟(=복수 격자 위치)이면, 순서대로 같은 액션을 수행함.
- 정의 : TIP BOX, TIP Trash, Liquid Trash 등의 위치는 사전에 table_coordinates.json 에 정의되어야 함.
    - Tip box : 기본적으로 8x12 격자로 3통이 세로로 배치되며, 
                팁의 위치와 배열은 table_coordinates.json 에 미리 정의되며,
                한 격자에 1개의 팁이 배치되어 소모되며,
                어느위치까지 팁을 소모했는지 기억하고, 계산 가능
    - Tip Trash : 사용후 Tip Eject 액션에 따라 팁을 버리는 통이며,
                위치는 사전에 table_coordinates.json 에 미리 정의 됨.
    - Liquid Trash : Dispose 액션에 따라 용액을 피펫이 흡입하여 버릴때 사용되는 통으로,
                위치는 사전에 table_coordinates.json 에 미리 정의 됨. 

## 좌표계
- table_coordinates.json 의 center_coordinates 또는 xxx_center_coordinates 값을 참조해야 함.
- 이는 로봇의 기준 좌표( 0,0,0 )를 중심으로 계산 및 커맨드 구성을 해야 함.
- 각 커맨드별로 지정된 end-effector 의 x-y 의 center 값과 z 값의 min 값을 참조하여야 한다.

### 좌표 변환 공식
- **Grid 좌표 → Table 좌표**: `table_coord = grid_table_coordinates[grid_index]`
- **Table 좌표 → Center 좌표**: `center_coord = grid_center_coordinates[grid_index]`
- **Center 좌표 → 최종 좌표**: `final_coord = inverse_kinematics(center_coord, end_effector_offset)`

### Z 좌표 계산 규칙 (개선됨)
- **초기화 이동**: `z = 0` (초기 위치로 이동)
- **equip/eject 액션**: `tool_center_z + origin_0_z_offset` (팁 장착/제거)
- **take/apply/dispose 액션**: `tool_center_z + tool_size_z` (액체 작업)
- **pick/place 액션**: `tool_center_z` (그리퍼 작업)
- **move_to_top**: 항상 `z = 0` (최상위 위치로 고정)
- **move_xy_position**: 항상 `z = 0` (X,Y만 이동, 안전한 이동 패턴)

### 좌표 계산 예시
```python
# 1. 초기화 이동
initialization_z = 0  # 초기 위치로 이동

# 2. Equip 액션 (팁 장착)
tool_center_z = -308.48  # tip1의 center_coordinates.z
origin_0_z = 10          # tip1의 grid_pattern.origin_0.z
equip_z = tool_center_z + origin_0_z = -308.48 + 10 = -298.48

# 3. Take 액션 (액체 흡입)
tool_center_z = -400.5   # source1의 center_coordinates.z
tool_size_z = 58.52      # source1의 size.height
take_z = tool_center_z + tool_size_z = -400.5 + 58.52 = -341.98

# 4. 안전한 이동 패턴
move_xy_position_z = 0   # X,Y만 이동 (Z=0)
move_to_top_z = 0        # 최상위 위치로 이동 (Z=0)
```

### Grid 사용 도구들
- **Tip Box**: 8x12 격자로 팁들이 배치됨 (tip1, tip2, tip3)
- **MEA Tool**: 8x2 격자로 측정 포인트들이 배치됨 (mea1, mea2, mea3)
- **Source**: 격자 없이 단일 위치 (source1, source2, source3)

### 좌표 변환 규칙
- **Grid 좌표 [0,0]**: 각 도구의 첫 번째 격자 위치
- **Grid 좌표 [0,1]**: 각 도구의 두 번째 격자 위치 (같은 행)
- **Grid 좌표 [1,0]**: 각 도구의 다음 행 첫 번째 격자 위치
- **Source 좌표**: Grid 없이 center_coordinates 직접 사용

### 위치 기본 계산:
    - 최종 좌표 = inverse_kinematics(사용하고자 하는 툴의 좌표, end-effector의 좌표, link1, link2) 

----

## Command & Function Mapping

### 이동 명령어 (통일화됨)
* move_to : ScaraInterface.move_end_effector(end-effector, xyz, tip) - current x,y 에서 z = 0 으로 이동.
* move_xy_position : ScaraInterface.move_end_effector(end-effector, [x, y, 0], tip) - x,y 이동 (z=0에서)
* move_z_position : ScaraInterface.move_end_effector(end-effector, [x, y, z], tip) - z 이동
* move_to_top : ScaraInterface.move_to_top(end-effector, xyz, tip) - 최상위 위치로 이동 (z=0)
* move_offset : ScaraInterface.move_offset(axis, offset, speed) - 상대적 오프셋 이동

**개선사항**: 모든 액션에서 일관된 함수명 사용 (이전: `ScaraInterface.move_to_xyz` → 현재: `ScaraInterface.move_end_effector`)

* rotate_cw (lid-closing) : ScaraInterface.gripper.set_rotation_angle(-360*5)
* rotate_ccw (lid-opening) : ScaraInterface.gripper.set_rotation_angle(+360*5)
* pick : ScaraInterface.gripper.close()
* place : ScaraInterface.gripper.open()


* take : DakenInterface.aspirate_liquid(ammount)
* apply : DakenInterface.spit_liquid(amount)
* check_tip : DakenInterface.check_tip()
* eject : DakenInterface.eject_tip()

* end-effector ->
    - pipette : ServorInterface.move_to_angle(60)
    - gripper : ServorInterface.move_to_angle(240)


----


# Action 에 따른 커맨드 구성

## Action List

### Initialization: 초기화 이동
    - parameters
        - xyz: [0, 0, 0] (고정값)
    - 사전 조건
        - 없음 (프로토콜 시작 시 자동 실행)
    - 설명
        프로토콜 시작 시 초기 위치로 이동
        **모든 프로토콜의 첫 번째 명령으로 자동 실행**
        **안전한 시작 위치 보장**
        **로봇의 기준 좌표 (0,0,0)로 이동**
    - command list
        - move_xy_position (0, 0, 0) - 초기 위치로 이동

### Equip: 피펫 장착
    - parameters 
        - pos 
            : NONE -> 팁 위치 자동 계산 (tip1, tip2, tip3 순서로 사용하지 않은 그리드 위치 자동 선택)
            : 지정 좌표 -> 해당 위치의 팁 장착후, 다음 위치 자동 계산
    - 사전 조건
        - 팁이 장착되지 않은 상태여야 함
        - end-effector가 pipette로 설정 가능해야 함
    - 설명
        피펫 장착 명령
        **자동 팁 위치 계산 시스템**: target이 'none'인 경우 tip1, tip2, tip3 순서로 사용하지 않은 그리드 위치를 자동 선택
        **팁 그리드 사용 상태 추적**: 각 팁 박스의 그리드 사용 여부를 실시간으로 관리하여 중복 방지
        **안전한 이동 패턴**: move_to_top → move_xy_position → move_z_position 순서로 충돌 방지
        **Z 좌표 계산**: tool_center_z + origin_0_z_offset (팁의 정확한 장착 위치)
        **중복하여 Equip 명령이 수행되지 않도록 해야 함**
        **팁 장착 재시도 로직**: Z축 -7mm → +7mm → 팁 체크 → 실패 시 재시도 (최대 3회)
    - command list
        - set_end_effector (pipette)
        - move_to_top (현재 위치의 최상위)
        - move_xy_position (팁 위치로 X,Y 이동, Z=0)
        - move_z_position (팁 위치로 Z축 이동)
        - tip_equip_with_retry (팁 장착 - 재시도 로직 포함)
            - parameters: max_retries (기본 3), retry_delay (기본 1.0초), z_offset (기본 7mm)
            - 동작: Z축 -7mm → +7mm → 팁 체크 → 실패 시 재시도
        - move_to_top (최상위 위치로 이동)

### Eject: 피펫 제거
    - parameters
        - pos
            : NONE -> Tip Trash 에 버리기
            : 지정 좌표 -> 해당 위치에 팁 버리기
    - 사전 조건
        - Equip 액션이 먼저 수행되어야 함 (팁 장착 상태)
        - end-effector가 pipette로 설정되어 있어야 함
    - 설명
        피펫 명령
        위치 이동 -> 팁 Eject -> 최상위 위치로 이동
        ** Eject 는 Equip 이후에 유효한 기능임 **
        ** Tip Trash 의 위치는 사전에 정의 됨. in table_coordinates.json **
    - command list
        - end-effector = pipette
        - move_to (Tip Trash position)
        - eject
        - move_to_top (absolute z=0), 최고 높이로 이동

### Pick: 집기
    - parameters
        - pos 
            : 지정 좌표 -> 해당 위치의 툴의 중앙(center pos)위치를 잡아야 함
            ** center pos 는 크기 값(x,y) 와 위치값을 참조하여 계산해야 하며,  
            Pick 하기 위해서 세로축 z 크기 - 4mm 아래로 위치해야 한다. 
    - 사전 조건
        - end-effector가 gripper로 설정 가능해야 함
        - 그리퍼가 비어있는 상태여야 함
    - 설명
        그리퍼 명령
        위치 이동 -> 집기 동작 수행 -> 최상위 위치로 이동
        ** 중복하여 Pick 명령이 수행되지 않도록 해야 함 **
    - command list
        - end-effector = gripper
        - move_to (center-pos of the tool) 
           **center-pos 는 크기와 위치 x, y 값으로 계산 **
        - gripper_close, **force detection**
        - move_to_top (absolute z=0), 최고 높이로 이동

### Place: 놓기
    - parameters
        - pos 
            : 지정 좌표 -> 툴의 중앙(center pos)위치를 기준으로 정해진 위치에 놓아야 함
            ** center pos 는 크기 값(x,y) 와 위치값을 참조하여 계산해야 하며,  
            Place 하기 위해서는 세로축 z 크기 - 4mm 아래로 위치해야 한다. 
    - 사전 조건
        - Pick 액션이 먼저 수행되어야 함 (그리퍼에 툴이 잡혀있는 상태)
        - end-effector가 gripper로 설정되어 있어야 함
    - 설명
        그리퍼 명령
        위치 이동 -> 놓기 동작 수행 -> 최상위 위치로 이동
        ** Place 는 Pick 이후에 유효한 기능임 **
    - command list
        - end-effector = gripper
        - move_to (center-pos of the tool) 
          **center-pos 는 크기와 위치 x, y 값으로 계산 **
        - gripper_open
        - move_to_top (absolute z=0), 최고 높이로 이동

### Take: 가져오기, 흡입
    - parameters
        - pos 
            : 지정 좌표 (단수 또는 복수) -> 해당 위치 이동후 용량만큼 흡입, 
        - amount
            : 흡입할 양 (uL or mL)
    - 사전 조건
        - Equip 액션이 먼저 수행되어야 함 (팁 장착 상태)
        - end-effector가 pipette로 설정되어 있어야 함
    - 설명
        액체 흡입 명령
        ** 안전한 이동을 위해 x,y 이동과 z 이동을 분리하여 수행 **
        ** 첫 번째 위치: x,y 이동 → z 이동 → 흡입 → x,y 복귀 **
        ** 연속된 타겟: x,y 오프셋 이동 → z 이동 → 흡입 → x,y 복귀 **
        ** Z 좌표 계산**: tool_center_z + tool_size_z (액체 용기의 상단에서 흡입)
        ** 흡입할 위치의 용량을 모두 소모했을것으로 계산되면, 다음 좌표로 이동하여 계속진행 **
        ** 소스 용액의 용량이 사전에 정의되어야 한다. in table_coordinates.json **
        ** 흡입 동작에서는 액체의 수면을 감지하고, 흡입하면서 액체의 수면을 따라 내려가야함 **
    - command list
        - end-effector = pipette
        - **첫 번째 위치 또는 단일 타겟:**
            - move_xy_position (target-position, z=0) - x,y 이동
            - move_z_position (target-position, z) - z 이동
            - take (amount) - 흡입
            - move_xy_position (target-position, z=0) - x,y 복귀
        - **연속된 타겟 (두 번째 이후):**
            - move_offset (axis, offset) - x,y 오프셋 이동
            - move_z_position (target-position, z) - z 이동
            - take (amount) - 흡입
            - move_xy_position (target-position, z=0) - x,y 복귀

### Apply: 적용
    - parameters
        - pos 
            : 지정 좌표 (단수 또는 복수) 
               -> 단수일경우, 해당 위치에 이동하여 적용할 양을 적용(배출) / 복수일경우, 차례대로 이동하면서 적용
        - amount
            : 적용할 양 (uL or mL)
    - 사전 조건
        - Equip 액션이 먼저 수행되어야 함 (팁 장착 상태)
        - Take 액션이 먼저 수행되어야 함 (액체 흡입 상태)
        - end-effector가 pipette로 설정되어 있어야 함
    - 설명
        피펫 명령
        ** 안전한 이동을 위해 x,y 이동과 z 이동을 분리하여 수행 **
        ** 첫 번째 위치: x,y 이동 → z 이동 → 적용 → x,y 복귀 **
        ** 연속된 타겟: x,y 오프셋 이동 → z 이동 → 적용 → x,y 복귀 **
        ** Apply 는 Take 이후에 유효한 기능이며, Apply 할때는 Take 한 용량 내에서만 적용될수 있도록 계산 ** 
    - command list
        - end-effector = pipette
        - **첫 번째 위치 또는 단일 타겟:**
            - move_xy_position (target-position, z=0) - x,y 이동
            - move_z_position (target-position, z) - z 이동
            - apply (amount) - 적용
            - move_xy_position (target-position, z=0) - x,y 복귀
        - **연속된 타겟 (두 번째 이후):**
            - move_offset (axis, offset) - x,y 오프셋 이동
            - move_z_position (target-position, z) - z 이동
            - apply (amount) - 적용
            - move_xy_position (target-position, z=0) - x,y 복귀

### Dispose: 버리기
    - parameters
        - pos 
        : 지정 좌표 (단수 또는 복수) 에서 차례대로 하나씩 용량만큼 흡입해서 liq-trash 으로 이동하여 dispose all 
        - amount : all
    - 사전 조건
        - Equip 액션이 먼저 수행되어야 함 (팁 장착 상태)
        - end-effector가 pipette로 설정되어 있어야 함
    - 설명
        피펫 명령
        ** 안전한 이동을 위해 x,y 이동과 z 이동을 분리하여 수행 **
        ** 첫 번째 위치: x,y 이동 → z 이동 → 흡입 → x,y 복귀 **
        ** 연속된 타겟: x,y 오프셋 이동 → z 이동 → 흡입 → x,y 복귀 **
        ** 모든 타겟 처리 후: Liquid Trash로 x,y 이동 → z 이동 → 배출 → x,y 복귀 **
        ** liq-trash 의 위치가 사전에 정의되어야 한다. in table_coordinates.json**
    - command list
        - end-effector = pipette
        - **각 타겟 위치에서 흡입:**
            - **첫 번째 위치 또는 단일 타겟:**
                - move_xy_position (target-position, z=0) - x,y 이동
                - move_z_position (target-position, z) - z 이동
                - suction_for_disposal (amount) - 흡입
            - **연속된 타겟 (두 번째 이후):**
                - move_offset (axis, offset) - x,y 오프셋 이동
                - move_z_position (target-position, z) - z 이동
                - suction_for_disposal (amount) - 흡입
        - **Liquid Trash로 이동하여 배출:**
            - move_xy_position (Liquid-Trash, z=0) - x,y 이동
            - move_z_position (Liquid-Trash, z) - z 이동
            - dispose_waste - 오수처리
            - move_xy_position (Liquid-Trash, z=0) - x,y 복귀

### Measure: 측정
    - parameters
        NONE
    - 설명
        제어 명령
        측정 시작
    - command list
        - measure_start

### Wait: 대기
    - parameters
        - time : 시간 sec or min
    - 설명
        지정된 시간만큼 대기
    - command list
        - wait (time)

### Open: 열기
    - parameters
        - tool-name-number
            : 해당 위치의 해당 크기 뚜껑 열기 (table_coordinates.json 참조하여 위치와 크기 파악)
    - 사전 조건
        - end-effector가 gripper로 설정 가능해야 함
        - 그리퍼가 비어있는 상태여야 함
    - 설명
        그리퍼 명령
        위치 & 크기 체크 -> 위치 이동 -> 열기 동작 수행 -> 최상위 위치로 이동
    - command list
        - end-effector = gripper
        - move_to (target-position)
        - gripper_close
        - rotate_ccw() && move_to (dz = 12, speed = ?)
        - move_to_top (absolute z=0), 최고 높이로 이동

### Close: 닫기
    - parameters
        - pos 
            : 지정 좌표 -> 해당 위치의 뚜껑 닫기 (table_coordinates.json 참조하여 위치와 크기 파악)
            ** center pos 는 크기 값(x,y) 와 위치값을 참조하여 계산해야 하며,  
            닫기 위해서는 세로축 z 크기 - 4mm 아래로 위치해야 한다. 
    - 사전 조건
        - end-effector가 gripper로 설정 가능해야 함
        - 그리퍼가 비어있는 상태여야 함
    - 설명
        그리퍼 명령
        위치 이동후, 닫기 동작 수행후, 최상위 위치로 이동
    - command list
        - end-effector = gripper
        - move_to (target-position)
        - gripper_close
        - rotate_cw && move_to (dz = -12, speed = ?)
        - gripper_open
        - move_to_top (absolute z=0), 최고 높이로 이동

----

## 에러 처리

### 일반적인 에러 상황
- 팁이 장착되지 않은 상태에서 Take/Apply/Dispose 수행 시
- 그리퍼가 비어있는 상태에서 Place 수행 시
- 좌표 계산 실패 시
- 하드웨어 통신 오류 시

### 에러 처리 방법
- 각 액션 수행 전 상태 확인
- 실패 시 이전 상태로 복구
- 사용자에게 명확한 오류 메시지 제공

----

## 상태 관리

### 팁 관리
- 현재 사용 중인 팁 위치 추적
- 팁 소모량 계산
- 팁 교체 시점 결정

### 액체 관리  
- 각 소스의 남은 용량 추적
- 소스 교체 시점 결정
- 액체 수면 높이 계산

### 그리퍼 상태
- 현재 잡고 있는 툴 정보
- 그리퍼 개방/폐쇄 상태

----

## 매개변수 상세

### 액션별 매개변수 정의
- **pos**: [x, y] 좌표 배열 (단수 또는 복수)
- **amount**: 수치 (uL, mL 단위)
- **time**: 시간 객체 {value: 숫자, unit: "sec"|"min"}
- **target**: 타겟 그룹 객체 {GROUP: {ITEM: [[x,y], ...]}}
- **tool-name-number**: 도구 식별자 (table_coordinates.json 참조)

### 자동 팁 위치 계산 시스템
- **target이 'none'인 경우**: tip1, tip2, tip3 순서로 사용하지 않은 그리드 위치를 자동 선택
- **팁 그리드 사용 상태 추적**: 각 팁 박스의 그리드 사용 여부를 실시간으로 관리
- **중복 방지**: 이미 사용된 그리드 위치는 자동으로 제외

## 용어 정의

### 기본 용어
- **Protocol**: 실험 시나리오를 정의한 JSON 파일
- **Command List**: Protocol을 실행 가능한 명령어로 변환한 JSON 파일
- **End-effector**: 로봇의 끝단 도구 (pipette, gripper)
- **Grid**: 특정 도구(tip box, MEA tool 등) 내부의 격자 배치 좌표계
- **Grid Coordinates**: 도구 내부 격자 위치 (예: [0,0], [0,1])
- **Table Coordinates**: 테이블상의 절대 좌표
- **Center Coordinates**: 로봇 기준 좌표계

### 액션 용어
- **Equip**: 팁 장착
- **Eject**: 팁 제거
- **Pick**: 툴 집기
- **Place**: 툴 놓기
- **Take**: 액체 흡입
- **Apply**: 액체 적용
- **Dispose**: 오수처리
- **Measure**: 측정
- **Wait**: 대기
- **Open**: 뚜껑 열기
- **Close**: 뚜껑 닫기

### 이동 명령어 용어
- **move_xy_position**: x,y 좌표만으로 이동 (z=0에서)
- **move_z_position**: z 좌표만으로 이동
- **move_to_top**: 최상위 위치로 이동 (z=0, 안전한 복귀)
- **move_offset**: 상대적 오프셋 이동 (axis, offset, speed)
- **연속된 타겟**: 한 축으로만 이동하는 다수의 타겟 좌표
- **안전한 이동**: x,y 이동과 z 이동을 분리하여 충돌 방지
