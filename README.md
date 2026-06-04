# SCARA-ROBOT
Hitbot SCARA 로봇팔을 활용한 실험실 워크플로우 자동화 서버입니다.
MEA, TIP, SOURCE, JIG 타겟에 대한 프로토콜 설계, 명령 변환, 로봇 실행, 액체 자동 처리를 지원합니다.

# Overview
이 저장소는 MEA (Microelectrode Array) 바이오센서 실험 자동화를 위한 서버 아키텍처를 담고 있습니다.
사용자가 정의한 실험 프로토콜을 순차적인 로봇 동작 명령으로 변환하여,
표면 기능화, 세균 샘플 처리, PBS 세척, 전기화학 측정(CV/EIS)을 완전 자동으로 실행합니다.

# Architecture
서버는 MVC (Model-View-Controller) 패턴을 기반으로 구성되어 있습니다.

```
SCARA-Robot-Automated-MEA-Protocol-Server/
├── protocol_maker.py                        # 진입점
├── models/
│   └── protocol_model.py                    # 프로토콜 데이터 모델
├── controllers/
│   └── protocol_controller.py               # 프로토콜 실행 컨트롤러
├── services/
│   └── grid_selection_service.py            # 그리드 좌표 서비스
├── views/
│   ├── mea_group_widget.py                  # MEA 타겟 인터페이스
│   ├── source_group_widget.py               # 소스 튜브 인터페이스
│   ├── tip_group_widget.py                  # 팁 박스 인터페이스
│   └── jig_group_widget.py                  # JIG 타겟 인터페이스
├── handlers/
│   ├── experiment_execution_handler.py      # 실험 실행 로직
│   ├── robot_initialization_handler.py      # 로봇 초기화 로직
│   └── tube_handler.py                      # 액체 상태 관리
└── config/
    ├── robot_constants_config.json          # 로봇 모션 파라미터
    └── table.yaml                           # 공간 좌표 정의
```

**데이터 흐름:**

```
사용자가 GUI(views/)에서 프로토콜 설계
            ↓
protocol_model.py 가 프로토콜을 구조화된 데이터로 저장
            ↓
protocol_controller.py 가 실행 순서 결정
            ↓
experiment_execution_handler.py 가 별도 스레드에서 로봇 구동
            ↓
cmd_list.json (명령 목록) → Hitbot SCARA 로봇팔 실행
```

# Command
서버는 프로토콜을 구조화된 JSON 명령 목록(`cmd_list.json`)으로 변환합니다.
각 명령은 로봇 인터페이스 함수와 직접 매핑됩니다.

# Config
로봇 동작은 두 개의 설정 파일로 정의됩니다.

# Handlers
3개의 핵심 핸들러가 로봇 제어 로직을 담당합니다.

# Protocol_maker.py

`protocol_maker.py`는 애플리케이션 진입점입니다. 시작 시 세 가지 작업을 수행합니다:

1. **로깅 설정** : 로그 파일 출력 및 콘솔 스트림 초기화
2. **Qt 환경 설정** : X11 / Wayland / Docker 디스플레이 환경 감지 및 적응
3. **GUI 실행** : `ProtocolMakerWindow` 인스턴스 생성 및 Qt 애플리케이션 이벤트 루프 시작
